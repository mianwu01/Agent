"""Screen OpenRouter replacements for the Sol annotator on saved judge inputs.

Negatives: the 32 saved Sol full-input judgments (all historical accepts).
Synthetic positives: the same inputs with one goal-changing sentence appended to
the partner's final message (a scenario violation by the prompt's own definition).
Synthetic items are labeled as such and are not human gold.
Temperature 0, reasoning disabled, pinned provider, no retries.
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "pilot/runs/p4"
PAIRS = RUNS / "v7_c3_cost_control_20261008/validation_pairs.json"
OUT = RUNS / "v7_c5_openrouter_us_20261009/judge_screen"
INJECT = (
    " Actually, forget about fixing this. I've decided I just want to cancel my "
    "line and close my account today."
)
URL = "https://openrouter.ai/api/v1/chat/completions"
# (field, phrase when True, phrase when False); rotated across items.
FIELDS = [
    ("airplane_mode", "airplane mode is ON", "airplane mode is OFF"),
    ("data_enabled", "mobile data is turned ON", "mobile data is turned OFF"),
    ("roaming_enabled", "data roaming is ON", "data roaming is OFF"),
    ("wifi_enabled", "Wi-Fi is turned ON", "Wi-Fi is turned OFF"),
    ("data_saver_mode", "Data Saver is ON", "Data Saver is OFF"),
]


def device_fact(full, index):
    """Pick a boolean device field; return (field, true_phrase, false_phrase)."""
    device = (full.get("private_state_after") or {}).get("device") or {}
    for k in range(len(FIELDS)):
        field, on, off = FIELDS[(index + k) % len(FIELDS)]
        if isinstance(device.get(field), bool):
            return field, (on if device[field] else off), (off if device[field] else on)
    return None


def append(full, text):
    mutated = json.loads(json.dumps(full))
    last = [m for m in mutated["partner_block"] if m["role"] == "user" and m["content"]]
    last[-1]["content"] = last[-1]["content"].rstrip() + text
    return mutated


def items():
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))["pairs"]
    out = []
    for i, p in enumerate(pairs):
        full = p["full_input"]
        full = json.loads(full) if isinstance(full, str) else full
        rid, system = p["source_request_id"], p["system_prompt"]
        out.append(("hist", rid, system, full, False))
        out.append(("synth", rid, system, append(full, INJECT), True))
        fact = device_fact(full, i)
        if fact:
            _, true_phrase, false_phrase = fact
            # Confident, observed-sounding claim contradicting the DB.
            text = f" I just looked at my phone and {false_phrase}."
            out.append(("fact", rid, system, append(full, text), True))
            # Same contradicting content, explicitly uncertain and unobserved.
            text = f" I haven't checked, but I'm not sure whether {false_phrase}."
            out.append(("hedge", rid, system, append(full, text), False))
    return out


def parse(text):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def judge(key, model, provider, item):
    kind, rid, system, full, expect = item
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
        "provider": {"order": [provider], "allow_fallbacks": False},
        "reasoning": {"enabled": False},
        "usage": {"include": True},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(full, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    rec = {"kind": kind, "source_request_id": rid, "expect_violation": expect}
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {**rec, "error": f"{e.code} {e.read()[:200].decode(errors='replace')}"}
    except Exception as e:  # noqa: BLE001 - record transport failures, no retry
        return {**rec, "error": str(e)[:200]}
    if "choices" not in d:
        return {**rec, "error": json.dumps(d)[:200]}
    content = d["choices"][0]["message"].get("content")
    out = parse(content)
    scen_ids = {r["rule_id"] for r in full["rule_texts"]["scenario"]}
    style_ids = {r["rule_id"] for r in full["rule_texts"]["style_and_persona"]}
    rec.update(
        secs=round(time.time() - t, 1),
        provider=d.get("provider"),
        usage=d.get("usage"),
        raw=content,
        parsed=out is not None,
    )
    if out is not None:
        viol = out.get("scenario_violations") or []
        rec.update(
            violation=bool(viol),
            style_departures=len(out.get("style_departures") or []),
            complete_ids=set(out.get("assessed_scenario_rule_ids") or []) >= scen_ids
            and set(out.get("assessed_style_rule_ids") or []) >= style_ids,
        )
    return rec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--key-file", default=str(ROOT / "api/api.txt"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--kinds", default="hist,synth,fact,hedge")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    raw = Path(args.key_file).read_text(encoding="utf-8")
    key = re.search(r"sk-or-[A-Za-z0-9\-_]+", raw).group(0)
    kinds = set(args.kinds.split(","))
    tag = f"_{args.tag}" if args.tag else ""
    path = OUT / (args.model.replace("/", "__") + tag + ".json")
    if path.exists():
        parser.error(f"exists: {path}")
    with ThreadPoolExecutor(args.workers) as ex:
        recs = list(
            ex.map(
                lambda it: judge(key, args.model, args.provider, it),
                [it for it in items() if it[0] in kinds],
            )
        )
    ok = [r for r in recs if r.get("parsed")]
    hist = [r for r in ok if r["kind"] == "hist"]
    synth = [r for r in ok if r["kind"] == "synth"]
    summary = {
        "model": args.model,
        "provider": args.provider,
        "n": len(recs),
        "errors": sum("error" in r for r in recs),
        "unparsed": sum(r.get("parsed") is False for r in recs),
        "hist_agree_with_sol": sum(not r["violation"] for r in hist),
        "hist_n": len(hist),
        "synth_detected": sum(r["violation"] for r in synth),
        "synth_n": len(synth),
        "fact_detected": sum(r["violation"] for r in ok if r["kind"] == "fact"),
        "fact_n": sum(r["kind"] == "fact" for r in ok),
        "hedge_accepted": sum(not r["violation"] for r in ok if r["kind"] == "hedge"),
        "hedge_n": sum(r["kind"] == "hedge" for r in ok),
        "complete_ids": sum(r["complete_ids"] for r in ok),
        "cost_usd": round(
            sum((r.get("usage") or {}).get("cost") or 0 for r in recs), 4
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"summary": summary, "records": recs}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
