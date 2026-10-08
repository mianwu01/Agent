"""Tier A v7: existing-run analyses and frozen model annotations only."""

# ruff: noqa: E402
import argparse
import collections
import copy
import hashlib
import json
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = OUT.parent
SRC = BASE / "v6_paired_20261004"
FOLLOW = BASE / "v6_followup_20261004"
DIRS = {i: BASE / f"v7_e{i}_20261004" for i in range(4)}
sys.path.insert(0, str(ROOT / "pilot"))
import p4_v6 as v6
from run_branch import proposal_messages

from tau2.agent.base_agent import is_valid_agent_history_message
from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT
from tau2.data_model.tasks import Task

MANIFEST = {}
ARM = ["q", "q_prime"]
REPORT_MAP = {
    "accurate_complete_report": "accurate_complete",
    "partial_or_ambiguous_report": "partial_or_vague",
    "inaccurate_report": "inaccurate",
    "no_report": "none",
    "clarification_question": "clarification_question",
    "affect_or_offtask": "affect_or_offtask",
    "terminal_token_only": "terminal_token_only",
}
TRANSFER = {"s012", "s018", "s019", "s020", "s022"}


def read(path):
    path = Path(path)
    blob = path.read_bytes()
    if "v7_" not in str(path):
        MANIFEST[str(path.relative_to(ROOT))] = hashlib.sha256(blob).hexdigest()
    return json.loads(blob)


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    tmp.replace(path)


def semantic(m):
    return {
        k: m[k]
        for k in ["role", "content", "tool_calls", "requestor", "name", "error"]
        if k in m
    }


def key(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def norm_messages(messages):
    aliases = {}
    result = copy.deepcopy(messages)

    def alias(x):
        if x not in aliases:
            aliases[x] = f"tool_{len(aliases)}"
        return aliases[x]

    for m in result:
        for c in m.get("tool_calls") or []:
            if c.get("id"):
                c["id"] = alias(c["id"])
        if m.get("tool_call_id"):
            m["tool_call_id"] = alias(m["tool_call_id"])
    return result


def init_data():
    protocol = read(SRC / "protocol.json")
    summary = read(SRC / "summary.json")
    tasks = read(SRC / "tasks.json")
    labels = [
        json.loads(line)
        for line in (FOLLOW / "check3_labels.jsonl").read_text().splitlines()
    ]
    MANIFEST[str((FOLLOW / "check3_labels.jsonl").relative_to(ROOT))] = hashlib.sha256(
        (FOLLOW / "check3_labels.jsonl").read_bytes()
    ).hexdigest()
    lookup = {
        (r["unit"], r["labeler"]): (r["action"], REPORT_MAP[r["communication"]])
        for r in labels
    }
    sources = {
        c["source_id"]: read(SRC / "sources" / f"{c['source_id']}.json")
        for c in protocol["states"]
    }
    replies = {
        f"{c['state_id']}:{arm}:d{j}": read(
            SRC / "replies" / f"{c['state_id']}:{arm}:d{j}.json"
        )
        for c in protocol["states"]
        for arm in ARM
        for j in range(6)
    }
    before = {}
    for c in protocol["states"]:
        o = v6.build(
            Task.model_validate(tasks[c["task_id"]]),
            sources[c["source_id"]]["messages"][: c["index"]],
        )
        o.initialize()
        before[c["state_id"]] = {
            "user": v6.p4.state(o.environment)["user"],
            "scenario": o.user.system_prompt,
            "user_visible_history": [
                semantic(m.model_dump(mode="json"))
                for m in proposal_messages(
                    o.user, sources[c["source_id"]]["messages"][: c["index"]]
                )[:-1]
                if m.role != "system"
            ],
            "agent_system": o.agent.system_prompt,
        }
    return protocol, summary, tasks, lookup, sources, replies, before


def first_next_turn(messages, start):
    end = start
    while end < len(messages) and messages[end]["role"] != "user":
        end += 1
    if end == len(messages):
        return {
            "next_partner_block": None,
            "intervening_agent": [semantic(m) for m in messages[start:]],
            "end_reason": "no_later_partner_turn",
        }
    stop = end + 1
    while stop < len(messages) and messages[stop]["role"] != "assistant":
        stop += 1
    return {
        "next_partner_block": [semantic(m) for m in messages[end:stop]],
        "intervening_agent": [semantic(m) for m in messages[start:end]],
        "end_reason": None,
    }


def action_type(messages):
    first = next((m for m in messages if m["role"] == "assistant"), None)
    if first is None:
        return ("no_next_agent_action",)
    if first.get("tool_calls"):
        return ("tools", tuple(c["name"] for c in first["tool_calls"]))
    text = (first.get("content") or "").lower()
    if any(
        x in text
        for x in [
            "###stop###",
            "###transfer###",
            "###out_of_scope###",
            "you are being transferred",
        ]
    ):
        return ("terminal",)
    if re.search(
        r"\b(turn|toggle|enable|disable|restart|reboot|reset|set|switch|open|check|run|test|refuel)\b",
        text,
    ):
        return ("device_action_request",)
    return (
        ("information_request",) if "?" in text else ("information_or_acknowledgment",)
    )


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        return {
            p: v
            for k, x in obj.items()
            for p, v in flatten(x, prefix + "." + k if prefix else k).items()
        }
    if isinstance(obj, list):
        return {
            p: v
            for i, x in enumerate(obj)
            for p, v in flatten(x, prefix + "." + str(i)).items()
        }
    return {prefix: obj}


def categorical(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return "negative" if v < 0 else "zero" if v == 0 else "positive"
    return v


def prepare():
    protocol, summary, tasks, lookup, sources, replies, before = init_data()
    save(
        OUT / "context.json",
        {"protocol": protocol, "summary": summary, "before": before},
    )
    for name in [
        "check1_permutation.json",
        "check2_level.json",
        "check3_diversity.json",
        "prereg.json",
        "prereg_amendment.json",
        "labeler_usage.json",
    ]:
        original = FOLLOW / name
        read(original)
        shutil.copy2(original, DIRS[1] / name)
    converted = []
    for line in (FOLLOW / "check3_labels.jsonl").read_text().splitlines():
        row = json.loads(line)
        row["report"] = REPORT_MAP[row["communication"]]
        row["reused_from"] = "v6_followup_20261004"
        converted.append(row)
    (DIRS[1] / "behavior_labels.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in converted)
    )
    save(
        DIRS[1] / "reuse.json",
        {
            "new_calls": 0,
            "mapping": REPORT_MAP,
            "models": ["gpt-5.6-sol", "gpt-5.6-luna"],
            "warning": "Frozen communication labels are renamed bijectively, not relabeled or human-adjudicated. Numerical corrections and prompt wrapper from prior amendment retained.",
        },
    )
    case_by_id = {c["state_id"]: c for c in protocol["states"]}
    units = [f"{r['unit']}:r{rep}" for r in replies.values() for rep in range(4)]

    def extract(unit):
        row = read(SRC / "continuations" / f"{unit}.json")
        sim = read(SRC / "trajectories" / f"{unit}.json")
        r = replies[unit.rsplit(":", 1)[0]]
        c = case_by_id[row["state_id"]]
        messages = sim["messages"]
        start = len(r["prefix"])
        suffix = messages[start:]
        o = v6.build(
            Task.model_validate(tasks[c["task_id"]]),
            messages,
            seed=v6.p4.stable_seed(unit),
        )
        touched_fields = set()
        original_response = o.environment.get_response

        def traced_response(call):
            previous = flatten(v6.p4.state(o.environment)["user"])
            result = original_response(call)
            current = flatten(v6.p4.state(o.environment)["user"])
            touched_fields.update(
                p
                for p in previous.keys() | current.keys()
                if p.startswith("device.") and previous.get(p) != current.get(p)
            )
            return result

        o.environment.get_response = traced_response
        o.initialize()
        final = v6.p4.state(o.environment)["user"]
        next_turn = first_next_turn(messages, start)
        first = next((m for m in suffix if m["role"] == "assistant"), None)
        return {
            "unit": unit,
            "state_id": c["state_id"],
            "task_id": c["task_id"],
            "family": unit.split(":")[1],
            "j": r["j"],
            "rep": row["rep"],
            "reward": int(row["reward"] == 1),
            "assertions": row["assertions_final"],
            "final_user_state": final,
            "execution_touched_fields": sorted(touched_fields),
            "next_action_type": action_type(suffix),
            "agent_tool_path": [
                call["name"]
                for m in suffix
                if m["role"] == "assistant"
                for call in m.get("tool_calls") or []
            ],
            "next_turn": next_turn,
            "first_agent_response_id": (first.get("raw_data") or {}).get("id")
            if first
            else None,
            "termination_reason": row["termination_reason"],
            "behavior_label": lookup[(r["unit"], "gpt-5.6-sol")],
        }

    records = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(extract, u) for u in units]
        for i, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if i % 160 == 0:
                print("restored final state", i, "/", len(units), flush=True)
    records.sort(key=lambda r: r["unit"])
    (OUT / "suffix_features.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    save(OUT / "input_manifest.json", MANIFEST)
    print("PREPARE COMPLETE", flush=True)


def load_features():
    return [
        json.loads(line)
        for line in (OUT / "suffix_features.jsonl").read_text().splitlines()
    ]


def bank_case_files():
    context = read(OUT / "context.json")
    states = context["summary"]["states"]
    features = load_features()
    byunit = {r["unit"]: r for r in features}
    ranked = sorted(states, key=lambda s: s["sensitivity_contrast"], reverse=True)
    chosen = ranked[:8] + ranked[-4:]
    labels = {
        (r["unit"], r["labeler"]): r
        for r in [
            json.loads(s)
            for s in (DIRS[1] / "behavior_labels.jsonl").read_text().splitlines()
        ]
    }
    sources = {}
    for state in chosen:
        source = sources.setdefault(
            state["source_id"], read(SRC / "sources" / f"{state['source_id']}.json")
        )
        lines = [
            f"# {state['state_id']}",
            "",
            "Selected by rank of S_hat(q_prime)-S_hat(q): "
            + ("top8" if state in ranked[:8] else "bottom4"),
            "",
            "## Preceding agent request",
            "",
            "```json",
            json.dumps(
                semantic(source["messages"][state["index"] - 1]),
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
        for arm in ARM:
            for j in range(6):
                unit = f"{state['state_id']}:{arm}:d{j}"
                reply = read(SRC / "replies" / f"{unit}.json")
                lines += [
                    "",
                    f"## {unit}",
                    "",
                    "Model labels: "
                    + str(
                        {
                            model: (
                                labels[(unit, model)]["action"],
                                labels[(unit, model)]["report"],
                            )
                            for model in ["gpt-5.6-sol", "gpt-5.6-luna"]
                        }
                    ),
                    "",
                    "```json",
                    json.dumps(
                        [semantic(m) for m in reply["partner_block"]],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "```",
                ]
                for rep in range(4):
                    row = byunit[f"{unit}:r{rep}"]
                    lines += [
                        "",
                        f"Suffix r{rep}: reward={row['reward']}; termination={row['termination_reason']}",
                        "",
                        "```json",
                        json.dumps(row["next_turn"], ensure_ascii=False, indent=2),
                        "```",
                    ]
        path = DIRS[1] / "cases" / f"{state['state_id']}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
    save(
        DIRS[1] / "tail_selection.json",
        {
            "top8": [s["state_id"] for s in ranked[:8]],
            "bottom4": [s["state_id"] for s in ranked[-4:]],
            "selection": "Screening ranks only, no independent retest and no candidate-bank effect claims; case files contain raw blocks/outcomes/next turns, not aggregated case statistics.",
        },
    )


def e0_mechanical():
    context = read(OUT / "context.json")
    protocol = context["protocol"]
    tasks = read(SRC / "tasks.json")
    cases = {c["state_id"]: c for c in protocol["states"]}
    features = load_features()
    feature_byunit = {r["unit"]: r for r in features}
    examples = ["s000", "s003", "s010", "s018", "s034"]
    targets = {}
    response_ids = {}
    for sid in examples:
        reply = read(SRC / "replies" / f"{sid}:q_prime:d0.json")
        unit = f"{sid}:q_prime:d0:attempt{reply['attempt']}"
        proposal = read(SRC / "proposals" / f"{unit}.json")
        targets[unit] = ("proposal", sid)
        response_ids[unit] = (proposal["response"].get("raw_data") or {}).get("id")
    selected = []
    original_blocks = {}
    for case in protocol["states"]:
        source = read(SRC / "sources" / f"{case['source_id']}.json")
        end = case["index"] + 1
        while (
            end < len(source["messages"])
            and source["messages"][end]["role"] != "assistant"
        ):
            end += 1
        block = source["messages"][case["index"] : end]
        original_blocks[case["state_id"]] = (source, end, block)
        if (
            not any(
                any(
                    t in (m.get("content") or "")
                    for t in ["###STOP###", "###TRANSFER###", "###OUT_OF_SCOPE###"]
                )
                for m in block
            )
            and len(selected) < 10
        ):
            selected.append(case)
            for arm in ARM:
                unit = f"{case['state_id']}:{arm}:d0:r0"
                targets[unit] = ("agent", case["state_id"])
                response_ids[unit] = feature_byunit[unit]["first_agent_response_id"]
    found = {}

    def scan(path):
        with path.open() as handle:
            head = handle.read(650)
        match = re.search(r'"unit":\s*"([^"]+)"', head)
        role = re.search(r'"role":\s*"([^"]+)"', head)
        if not match or match.group(1) not in targets or not role:
            return None
        unit = match.group(1)
        kind = targets[unit][0]
        if role.group(1) != ("q_prime_proposal" if kind == "proposal" else "agent"):
            return None
        entry = read(path)
        if (
            entry.get("status") != "response"
            or (entry.get("response") or {}).get("id") != response_ids[unit]
        ):
            return None
        return unit, entry

    with ThreadPoolExecutor(max_workers=32) as pool:
        for n, result in enumerate(
            pool.map(scan, list((SRC / "requests").glob("*.json"))), 1
        ):
            if result:
                found[result[0]] = result[1]
            if n % 6000 == 0:
                print("ledger headers scanned", n, flush=True)
    payload_report = []
    for sid in examples:
        reply = read(SRC / "replies" / f"{sid}:q_prime:d0.json")
        unit = f"{sid}:q_prime:d0:attempt{reply['attempt']}"
        entry = found[unit]
        body = entry["request"]
        save(DIRS[0] / "proposal_payloads" / f"{sid}.json", body)
        system = body["messages"][0]["content"]
        payload = json.loads(body["messages"][1]["content"])
        case = cases[sid]
        task = tasks[case["task_id"]]
        instructions = task["user_scenario"]["instructions"]
        instruction_matches = {
            k: (v in system)
            for k, v in instructions.items()
            if isinstance(v, str) and v
        }
        payload_report.append(
            {
                "state_id": sid,
                "request_id": entry["id"],
                "private_task_instructions_in_system": instruction_matches,
                "device_snapshot_field_present": any(
                    k in payload
                    for k in [
                        "private_state",
                        "private_state_before",
                        "device",
                        "private_user_state",
                    ]
                ),
                "payload_keys": list(payload),
                "scenario_delimited_in_system": "<scenario>" in system,
                "available_user_tools": len(payload["available_user_tool_schemas"]),
            }
        )
    save(
        DIRS[0] / "private_scenario_check.json",
        {
            "examples": payload_report,
            "reading": "Full native private task scenario is in the system message; explicit runtime device snapshot is not in VS JSON payload. Native q also accesses device facts through user tools rather than an extra DB snapshot. Device observations already present in visible tool history can be present.",
        },
    )
    diffs = []
    for case in selected:
        source, end, block = original_blocks[case["state_id"]]
        original_prefix = source["messages"][:end]
        original_agent_messages = [
            m
            for m in v6.p4.MESSAGE_LIST.validate_python(original_prefix)
            if is_valid_agent_history_message(m)
        ]
        source_system = SYSTEM_PROMPT.format(
            domain_policy=source["policy"], agent_instruction=AGENT_INSTRUCTION
        )
        expected = v6.p4.llm_utils.to_litellm_messages(
            [
                v6.p4.SystemMessage(role="system", content=source_system),
                *original_agent_messages,
            ]
        )
        o = v6.build(Task.model_validate(tasks[case["task_id"]]), original_prefix)
        o.initialize()
        restored = v6.p4.llm_utils.to_litellm_messages(
            o.agent_state.system_messages + o.agent_state.messages + [o.message]
        )
        item = {
            "state_id": case["state_id"],
            "original_input_reconstructed_not_raw_baseline_request": True,
            "original_vs_restored_equal": norm_messages(expected)
            == norm_messages(restored),
            "original_messages": len(expected),
            "restored_messages": len(restored),
            "source_policy_equals_current": source_system == o.agent.system_prompt,
            "sampled_branch_captured_requests": {},
        }
        save(
            DIRS[0] / "branch_contexts" / f"{case['state_id']}:original.json",
            {
                "original_reconstructed": norm_messages(expected),
                "native_restored": norm_messages(restored),
            },
        )
        for arm in ARM:
            unit = f"{case['state_id']}:{arm}:d0:r0"
            r = read(SRC / "replies" / f"{case['state_id']}:{arm}:d0.json")
            o = v6.build(Task.model_validate(tasks[case["task_id"]]), r["prefix"])
            o.initialize()
            branch = (
                v6.p4.llm_utils.to_litellm_messages(
                    o.agent_state.system_messages + o.agent_state.messages + [o.message]
                )
                if not o.done
                else None
            )
            captured = found.get(unit)
            observed = captured["request"]["messages"] if captured else None
            item["sampled_branch_captured_requests"][arm] = {
                "restored_done": o.done,
                "captured_request_available": captured is not None,
                "expected_vs_captured_equal": norm_messages(branch)
                == norm_messages(observed)
                if branch is not None and observed is not None
                else None,
            }
            save(
                DIRS[0] / "branch_contexts" / f"{case['state_id']}:{arm}.json",
                {
                    "expected_branch": norm_messages(branch) if branch else None,
                    "captured_branch": norm_messages(observed) if observed else None,
                },
            )
        diffs.append(item)
    save(
        DIRS[0] / "branch_context_identity.json",
        {
            "states": diffs,
            "limitation": "Original IID request bodies were not logged in available IID directory. Original source policy and exact source agent-visible message projection are reconstructed, not falsely described as raw archived baseline requests; sampled suffix input is validated against captured request linked by actual response ID.",
        },
    )
    print("E0 MECHANICAL COMPLETE", flush=True)


def jobs_payloads():
    """Freeze annotation prompts and materialize blind payloads before API calls."""
    context = read(OUT / "context.json")
    cases = {c["state_id"]: c for c in context["protocol"]["states"]}
    before = context["before"]
    features = load_features()
    byreply = collections.defaultdict(list)
    for row in features:
        byreply[row["unit"].rsplit(":", 1)[0]].append(row)
    prereg = read(FOLLOW / "prereg.json")
    baseprompt = prereg["check3"]["prompt"]
    prompts = {
        "regression": """Annotate the next native partner turn after a fixed replacement. This is a MODEL JUDGMENT, not human truth. Input includes the preceding agent request, replaced executed partner block, and up to four independent suffixes with intervening agent messages/tool results and the next executed partner block. For each suffix return JSON {"relations":[{"rep":0,"relation":"continues"|"neutral"|"contradicts_or_undoes","reason":"brief"},...]}. Judge the salient action/reporting behavior rather than surface words. Continues: sustains the same distinctive compliance/partialness/withholding/uncertainty or cooperation style when comparable. Contradicts_or_undoes: materially reverses a report/action or repairs the same branch behavior (e.g. executes an action previously skipped, clarifies an initially vague report), even if an intervening request elicits the repair. Neutral: new topic, terminal token, no comparable behavior, or ordinary progress without reversal. Do not call ordinary changed device state caused by explicit new instructions a contradiction. Do not infer causality, success, or intention beyond evidence. Output exactly one row per supplied suffix; no rows for absent next turns.""",
        "private": """Annotate references to private context in each supplied executed block. Return JSON {"blocks":[{"j":0,"mentions_private_scenario":true/false,"device_state_report":true/false,"device_tool_action":true/false,"unobserved_device_claim":true/false},...]}. A private-scenario reference explicitly mentions supplied identity, location, goal/constraint or task instruction. A device-state report states a concrete current device condition. Device-tool action means actual executed user tools read or change device state. Unobserved-device claim means device factual text without support in preceding visible history or actual tool results inside this block; do not count a report after a newly executed diagnostic as unobserved. This is model judgment; whether an action was motivated by unseen private state cannot be inferred. Never infer that the generator saw the supplied private DB. Use the scenario/history/private before and executed block only; no suffix outcomes. Return one row for each j.""",
        "rejected": baseprompt,
        "batch": baseprompt.replace(
            "executed customer partner turns", "proposed customer partner turns"
        )
        + ' These five possibilities were proposed, not executed. For action labels interpret listed tool calls as intended actions relative to the request; do not claim execution or invent tool effects. A text-only claim does not imply performing a tool action. Device truth is assessed only against visible history and private before state. Return JSON {"labels":[{"candidate_index":0,"action":"...","communication":"..."},...]}, one row for every candidate, using exactly the same enumerations above.',
    }
    save(
        DIRS[0] / "annotator_prompts.json",
        {
            "created_at": time.time(),
            "model": "gpt-5.6-sol",
            "temperature": 0,
            "prompts": prompts,
            "note": "Executed accepted labels are reused frozen E1 Sol labels. Rejected executed blocks use the identical frozen E1 core prompt. Batch labels refer to intended, unexecuted candidates only.",
        },
    )
    jobs = []
    for c in context["protocol"]["states"]:
        source = read(SRC / "sources" / f"{c['source_id']}.json")
        last = semantic(source["messages"][c["index"] - 1])
        b = before[c["state_id"]]
        for arm in ARM:
            rs = [
                read(SRC / "replies" / f"{c['state_id']}:{arm}:d{j}.json")
                for j in range(6)
            ]
            private = {
                "scenario": b["scenario"],
                "user_visible_history": b["user_visible_history"],
                "private_before": b["user"],
                "blocks": [
                    {
                        "j": r["j"],
                        "partner_block": [semantic(m) for m in r["partner_block"]],
                    }
                    for r in rs
                ],
            }
            jobs.append(
                {
                    "kind": "private",
                    "id": f"{c['state_id']}:{arm}",
                    "payload": private,
                    "state_id": c["state_id"],
                    "family": arm,
                }
            )
            for r in rs:
                available = [
                    row
                    for row in byreply[r["unit"]]
                    if row["next_turn"]["next_partner_block"] is not None
                ]
                if available:
                    payload = {
                        "preceding_agent_request": last,
                        "replaced_block": [semantic(m) for m in r["partner_block"]],
                        "suffixes": [
                            {"rep": row["rep"], **row["next_turn"]} for row in available
                        ],
                    }
                    jobs.append(
                        {
                            "kind": "regression",
                            "id": r["unit"],
                            "payload": payload,
                            "state_id": c["state_id"],
                            "family": arm,
                        }
                    )
    rejected = []
    for path in sorted((SRC / "rejected_replies").glob("*.json")):
        r = read(path)
        c = cases[r["state_id"]]
        source = read(SRC / "sources" / f"{c['source_id']}.json")
        payload = {
            "agent_last_message": semantic(source["messages"][c["index"] - 1]),
            "partner_block": [semantic(m) for m in r["partner_block"]],
            "private_state_before": before[r["state_id"]]["user"],
            "private_state_after": r["state_after_partner"]["user"],
            "assertions_before": r["assertions_before"],
            "assertions_after_partner": r["assertions_after_partner"],
        }
        jobs.append(
            {
                "kind": "rejected",
                "id": path.stem,
                "payload": payload,
                "state_id": r["state_id"],
            }
        )
        rejected.append(
            {
                "id": path.stem,
                "state_id": r["state_id"],
                "reason": r["fidelity"]["reason"],
                "proposal_version": r.get("proposal_version"),
                "block": [semantic(m) for m in r["partner_block"]],
            }
        )
    save(DIRS[0] / "rejected_records.json", rejected)
    for path in sorted((SRC / "proposals").glob("*.json")):
        prop = read(path)
        sid = path.stem.split(":")[0]
        c = cases[sid]
        source = read(SRC / "sources" / f"{c['source_id']}.json")
        payload = {
            "agent_last_message": semantic(source["messages"][c["index"] - 1]),
            "private_state_before": before[sid]["user"],
            "user_visible_history": before[sid]["user_visible_history"],
            "candidates": [
                {"candidate_index": j, **candidate}
                for j, candidate in enumerate(prop["batch"])
            ],
        }
        jobs.append(
            {"kind": "batch", "id": path.stem, "payload": payload, "state_id": sid}
        )
    save(DIRS[0] / "annotation_jobs.json", jobs)
    save(OUT / "input_manifest_e0.json", MANIFEST)
    print(
        "ANNOTATION JOBS",
        dict(collections.Counter(j["kind"] for j in jobs)),
        flush=True,
    )


def annotate(workers=96):
    """Only bounded annotation calls, with durable retries and redacted ledger."""
    jobs = read(DIRS[0] / "annotation_jobs.json")
    prompts = read(DIRS[0] / "annotator_prompts.json")["prompts"]
    p4 = v6.p4
    p4.OUT = OUT
    p4.setup(ROOT / "api.txt", workers)
    p4.KEY_LIMITS = [threading.BoundedSemaphore(workers // 4) for _ in range(4)]
    allowed = read(FOLLOW / "prereg.json")["check3"]

    def call(job, n):
        path = DIRS[0] / "annotations" / f"{job['kind']}:{job['id']}.json"
        if path.exists():
            return read(path)
        result = p4.json_response(
            prompts[job["kind"]],
            job["payload"],
            "gpt-5.6-sol",
            f"v7_label:{job['kind']}:{job['id']}",
            n % 4,
        )
        if job["kind"] == "regression":
            assert {r["rep"] for r in result["relations"]} == {
                r["rep"] for r in job["payload"]["suffixes"]
            }
            assert all(
                r["relation"] in ["continues", "neutral", "contradicts_or_undoes"]
                for r in result["relations"]
            )
        elif job["kind"] == "private":
            assert {r["j"] for r in result["blocks"]} == set(range(6))
            assert all(
                isinstance(r[k], bool)
                for r in result["blocks"]
                for k in [
                    "mentions_private_scenario",
                    "device_state_report",
                    "device_tool_action",
                    "unobserved_device_claim",
                ]
            )
        elif job["kind"] == "batch":
            assert {r["candidate_index"] for r in result["labels"]} == set(
                range(len(job["payload"]["candidates"]))
            )
            assert all(
                r[a] in allowed[a]
                for r in result["labels"]
                for a in ["action", "communication"]
            )
        else:
            assert all(result[a] in allowed[a] for a in ["action", "communication"])
        row = {
            "kind": job["kind"],
            "id": job["id"],
            "state_id": job["state_id"],
            "family": job.get("family"),
            "judgment": result,
            "model": "gpt-5.6-sol",
            "temperature": 0,
            "prompt_sha256": hashlib.sha256(
                (prompts[job["kind"]] + " Return valid json.").encode()
            ).hexdigest(),
            "input_sha256": p4.digest(job["payload"]),
        }
        p4.save(path, row)
        return row

    pending = list(enumerate(jobs))
    for attempt in range(4):
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(call, j, n): (n, j) for n, j in pending}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                except Exception as exc:
                    n, j = futures[future]
                    failures.append((n, j))
                    p4.save(
                        OUT / "errors" / f"{j['kind']}:{j['id']}:{attempt}.json",
                        {"type": type(exc).__name__, "error": str(exc)},
                    )
                if i % 80 == 0:
                    print(
                        "annotation",
                        attempt,
                        i,
                        "/",
                        len(pending),
                        "failures",
                        len(failures),
                        flush=True,
                    )
        if not failures:
            break
        pending = failures
    if failures:
        raise RuntimeError("annotation jobs incomplete")
    print("ANNOTATIONS COMPLETE", flush=True)


def mode_key(row, definition, paths):
    m = [row["reward"]]
    if definition == "M1":
        return key(m)
    assertion = sorted(
        [
            (
                a["assertion"]["env_type"],
                a["assertion"]["func_name"],
                key(a["assertion"]["arguments"]),
                key(a["assertion"].get("assert_value")),
                int(a["met"]),
            )
            for a in row["assertions"]
        ]
    )
    m.append(assertion)
    if definition == "M5":
        return key([row["behavior_label"], m])
    if definition == "M2":
        return key(m)
    flat = flatten(row["final_user_state"])
    m.extend(
        [
            [(p, categorical(flat.get(p))) for p in paths[row["task_id"]]],
            row["next_action_type"],
        ]
    )
    if definition == "M4":
        m.append(row["agent_tool_path"])
    return key(m)


def e2():
    """Mechanically build modes and shuffled-order discovery curves."""
    features = load_features()
    context = read(OUT / "context.json")
    tasks = read(SRC / "tasks.json")
    bytask = collections.defaultdict(list)
    for r in features:
        bytask[r["task_id"]].append(r)
    paths = {}
    for tid, rs in bytask.items():
        o = v6.build(Task.model_validate(tasks[tid]), [])
        initialization_fields = set()
        original_init_action = o.environment.run_env_function_call

        def traced_init_action(action):
            previous = flatten(v6.p4.state(o.environment)["user"])
            result = original_init_action(action)
            current = flatten(v6.p4.state(o.environment)["user"])
            initialization_fields.update(
                p
                for p in previous.keys() | current.keys()
                if p.startswith("device.") and previous.get(p) != current.get(p)
            )
            return result

        o.environment.run_env_function_call = traced_init_action
        o.initialize()
        initial = flatten(v6.p4.state(o.environment)["user"])
        # Field changes across actual task execution; no text embedding or model.
        touched = {
            p
            for r in rs
            for p, v in flatten(r["final_user_state"]).items()
            if p.startswith("device.") and initial.get(p) != v
        }
        touched.update(initialization_fields)
        touched.update(p for r in rs for p in r["execution_touched_fields"])
        for sid, b in context["before"].items():
            case = next(
                c for c in context["protocol"]["states"] if c["state_id"] == sid
            )
            if case["task_id"] == tid:
                touched.update(
                    p
                    for p, v in flatten(b["user"]).items()
                    if p.startswith("device.") and initial.get(p) != v
                )
        # Include explicit user-device initialization leaves, even if restored by end.
        init = (tasks[tid].get("initial_state") or {}).get("initialization_data") or {}
        for p in flatten(init):
            if "device." in p:
                touched.add(p[p.index("device.") :])
        paths[tid] = sorted(touched)
    save(DIRS[2] / "task_device_fields.json", paths)
    bystate = collections.defaultdict(list)
    for r in features:
        if r["family"] == "q":
            bystate[r["state_id"]].append(r)
    fixed = []
    approx = []
    for sid, rows in bystate.items():
        groups = collections.defaultdict(list)
        for r in rows:
            reply = read(SRC / "replies" / f"{sid}:q:d{r['j']}.json")
            groups[reply["partner_signature"]].append(r)
        eligible = [g for g in groups.values() if len({r["j"] for r in g}) >= 2]
        if eligible:
            selected = sorted(
                eligible, key=lambda g: (-len(g), min(r["j"] for r in g))
            )[0]
            fixed.extend(selected)
            approx.append(
                {
                    "state_id": sid,
                    "draws": sorted({r["j"] for r in selected}),
                    "suffixes": len(selected),
                }
            )
    matched = {r["state_id"] for r in fixed}
    for r in features:
        r["modes"] = {
            mode: mode_key(r, mode, paths) for mode in ["M1", "M2", "M3", "M4", "M5"]
        }
    (DIRS[2] / "mode_rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in features)
    )
    save(
        DIRS[2] / "agent_only_approximation.json",
        {
            "matched_states": sorted(matched),
            "groups": approx,
            "suffix_count": len(fixed),
            "limitation": "Largest repeated native block within q; not a proper fresh resampling of original partner. Unequal observation budgets and subset overlap constrain causal interpretation.",
        },
    )
    rng = np.random.default_rng(2026100701)
    results = {}
    curves = {}
    for cohort in ["all", "matched_states"]:
        subset = (
            features
            if cohort == "all"
            else [r for r in features if r["state_id"] in matched]
        )
        sources = {a: [r for r in subset if r["family"] == a] for a in ARM}
        sources["agent_only_approx"] = fixed
        results[cohort] = {}
        curves[cohort] = {}
        for mode in ["M1", "M2", "M3", "M4", "M5"]:
            source_sets = {
                name: {mode_key(r, mode, paths) for r in rows}
                for name, rows in sources.items()
            }
            results[cohort][mode] = {}
            curves[cohort][mode] = {}
            for name, rows in sources.items():
                values = [mode_key(r, mode, paths) for r in rows]
                count = collections.Counter(values)
                f1 = sum(c == 1 for c in count.values())
                f2 = sum(c == 2 for c in count.values())
                n = len(values)
                observed = len(count)
                curves50 = []
                for _ in range(50):
                    seen = set()
                    curve = []
                    for i in rng.permutation(n):
                        seen.add(values[i])
                        curve.append(len(seen))
                    curves50.append(curve)
                ca = np.asarray(curves50)
                curves[cohort][mode][name] = {
                    "n": n,
                    "mean": ca.mean(axis=0).tolist(),
                    "band_low": np.quantile(ca, 0.025, axis=0).tolist(),
                    "band_high": np.quantile(ca, 0.975, axis=0).tolist(),
                }
                exclusive = source_sets[name] - set.union(
                    *(s for other, s in source_sets.items() if other != name)
                )
                results[cohort][mode][name] = {
                    "n": n,
                    "observed_modes": observed,
                    "f1": f1,
                    "f2": f2,
                    "Chao1": observed + f1 * f1 / (2 * f2)
                    if f2
                    else observed + f1 * (f1 - 1) / 2,
                    "GT_numerator": f1,
                    "GT_denominator": n,
                    "GT_rate": f1 / n,
                    "source_exclusive_modes": len(exclusive),
                    "exclusive_share_of_source_modes": len(exclusive) / observed,
                    "modes_per_suffix": observed / n,
                }
    save(DIRS[2] / "discovery_statistics.json", results)
    save(DIRS[2] / "discovery_curves.json", curves)
    print(
        "E2 COMPLETE matched states",
        len(matched),
        "agent approximation suffixes",
        len(fixed),
        flush=True,
    )


def top_metrics(signal, target):
    n = len(signal)
    k = max(1, int(np.ceil(0.25 * n)))
    cut = np.sort(signal)[-k]
    above = signal > cut
    ties = signal == cut
    weights = above.astype(float)
    weights[ties] = (k - int(above.sum())) / int(ties.sum())
    num = float(np.dot(weights, target))
    total = float(target.sum())
    rho = (
        float(spearmanr(signal, target).statistic)
        if np.ptp(signal) > 0 and np.ptp(target) > 0
        else None
    )
    return {
        "spearman": rho,
        "selected_new_suffixes": num,
        "selected_directions": k,
        "all_new_suffixes": total,
        "future_suffixes_per_direction": 12,
        "precision": num / (12 * k),
        "random_precision": total / (12 * n),
        "capture": num / total if total > 0 else None,
        "random_capture": k / n,
        "lift": (num / total) / (k / n) if total > 0 else None,
        "boundary_tie_directions": int(ties.sum()),
    }


def e3():
    """Evaluate past discovery signals against genuinely held-out reply draws."""
    rows = [
        json.loads(line)
        for line in (DIRS[2] / "mode_rows.jsonl").read_text().splitlines()
    ]
    directions = sorted({(r["state_id"], r["family"], r["task_id"]) for r in rows})
    bydir = collections.defaultdict(list)
    for r in rows:
        bydir[(r["state_id"], r["family"], r["task_id"])].append(r)
    output = {}
    raw = []
    rng = np.random.default_rng(2026100702)
    tasks = sorted({d[2] for d in directions})
    taskids = {
        task: [i for i, d in enumerate(directions) if d[2] == task] for task in tasks
    }
    bootstrap_ids = [
        [
            i
            for task in rng.choice(tasks, size=len(tasks), replace=True)
            for i in taskids[task]
        ]
        for _ in range(1000)
    ]
    for mode in ["M2", "M3", "M4"]:
        folds = []
        for fold in range(2):
            past = {
                d: [r for r in bydir[d] if (r["j"] < 3) == (fold == 0)]
                for d in directions
            }
            future = {
                d: [r for r in bydir[d] if (r["j"] >= 3) == (fold == 0)]
                for d in directions
            }
            globalpast = {r["modes"][mode] for rs in past.values() for r in rs}
            signals = collections.defaultdict(list)
            targets = collections.defaultdict(list)
            for d in directions:
                counter = collections.Counter(r["modes"][mode] for r in past[d])
                p = sum(r["reward"] for r in past[d]) / 12
                gt = sum(n == 1 for n in counter.values()) / 12
                x = {
                    "GT": gt,
                    "COUNT": 1 / 14,
                    "REWARD": p,
                    "REWARD_VARIANCE": p * (1 - p),
                }
                local = sum(r["modes"][mode] not in counter for r in future[d])
                globalnew = sum(r["modes"][mode] not in globalpast for r in future[d])
                y = {"own_past": local, "all_directions_past": globalnew}
                for s, v in x.items():
                    signals[s].append(v)
                for t, v in y.items():
                    targets[t].append(v)
                raw.append(
                    {
                        "mode": mode,
                        "fold": fold,
                        "state_id": d[0],
                        "family": d[1],
                        "task_id": d[2],
                        "past_n": 12,
                        "future_n": 12,
                        "source_prefix_visits": 1,
                        "signals": x,
                        "targets": y,
                    }
                )
            folds.append(
                (
                    {k: np.asarray(v, float) for k, v in signals.items()},
                    {k: np.asarray(v, float) for k, v in targets.items()},
                )
            )
        output[mode] = {}
        for target in ["own_past", "all_directions_past"]:
            output[mode][target] = {}
            for signal in ["GT", "COUNT", "REWARD", "REWARD_VARIANCE"]:
                observed = [top_metrics(x[signal], y[target]) for x, y in folds]
                replicates = collections.defaultdict(list)
                for ids in bootstrap_ids:
                    metrics = [
                        top_metrics(x[signal][ids], y[target][ids]) for x, y in folds
                    ]
                    for metric in ["spearman", "precision", "capture", "lift"]:
                        if all(m[metric] is not None for m in metrics):
                            replicates[metric].append(
                                np.mean([m[metric] for m in metrics])
                            )
                summary = {
                    metric: {
                        "average_folds": float(np.mean([m[metric] for m in observed]))
                        if all(m[metric] is not None for m in observed)
                        else None,
                        "bootstrap_95_CI": np.quantile(
                            replicates[metric], [0.025, 0.975]
                        ).tolist()
                        if replicates[metric]
                        else None,
                        "valid_replicates": len(replicates[metric]),
                    }
                    for metric in ["spearman", "precision", "capture", "lift"]
                }
                output[mode][target][signal] = {
                    "folds": observed,
                    "average_and_cluster_CI": summary,
                    "constant_signal": all(np.ptp(x[signal]) == 0 for x, y in folds),
                }
    save(DIRS[3] / "signal_comparison.json", output)
    (DIRS[3] / "direction_folds.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw)
    )
    save(DIRS[3] / "bootstrap_task_indices.json", bootstrap_ids)
    print("E3 COMPLETE", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=["prepare", "mechanical", "jobs", "annotate", "cases", "e2", "e3"],
    )
    parser.add_argument("--workers", type=int, default=96)
    args = parser.parse_args()
    funcs = {
        "prepare": prepare,
        "mechanical": e0_mechanical,
        "jobs": jobs_payloads,
        "annotate": lambda: annotate(args.workers),
        "cases": bank_case_files,
        "e2": e2,
        "e3": e3,
    }
    funcs[args.phase]()
    if MANIFEST:
        save(OUT / f"input_manifest_{args.phase}.json", MANIFEST)


if __name__ == "__main__":
    main()
