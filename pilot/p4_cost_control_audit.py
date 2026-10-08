"""Export bounded historical judgment pairs and report offline input reduction."""

import hashlib
import json

from p4_cost_control import compact_payload, request_only, valid_judgment
from p4_cost_control_run import BASE, NEW, prepare


def main():
    prepare()
    folder = BASE / "v7_c2_step3_20261006_r2/arms/A0/requests"
    pairs = []
    scanned = 0
    # Sample by stable filename order, independent of rewards or judge verdicts.
    for path in sorted(folder.glob("*.json")):
        if len(pairs) == 32 or scanned == 400:
            break
        scanned += 1
        record = json.loads(path.read_text())
        if record.get("role") != "rule_labeler" or record.get("status") != "response":
            continue
        messages = record["request"]["messages"]
        try:
            payload = json.loads(messages[-1]["content"])["input"]
            answer = record["response"]["choices"][0]["message"]["content"]
        except (KeyError, ValueError, TypeError):
            continue
        if not valid_judgment(answer, payload):
            continue
        compact = compact_payload(payload)
        full_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
        short_bytes = len(json.dumps(compact, ensure_ascii=False).encode())
        pairs.append(
            {
                "source_request_id": record["id"],
                "source_relative_path": str(path.relative_to(BASE)),
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "system_prompt": messages[0]["content"],
                "full_input": payload,
                "compact_input": compact,
                "historical_sol_decision": json.loads(answer),
                "full_input_bytes": full_bytes,
                "compact_input_bytes": short_bytes,
                "request_only": request_only(payload["partner_block"]),
            }
        )
    result = {
        "new_api_calls": 0,
        "sample_size": len(pairs),
        "scanned_records": scanned,
        "sum_full_input_bytes": sum(p["full_input_bytes"] for p in pairs),
        "sum_compact_input_bytes": sum(p["compact_input_bytes"] for p in pairs),
        "whitelist_bypass_count": sum(p["request_only"] for p in pairs),
        "interpretation": "UTF-8 input bytes, not billed tokens or validated equivalent decisions. Rules/private goal retained. Shadow only until paired validation.",
    }
    if pairs:
        result["input_byte_reduction_fraction"] = (
            1 - result["sum_compact_input_bytes"] / result["sum_full_input_bytes"]
        )
    (NEW / "validation_pairs.json").write_text(
        json.dumps(
            {
                "sampling": "Stable filename order, first32 schema-complete Sol responses within first400 A0 request records; not reward-selected",
                "pairs": pairs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    (NEW / "offline_savings.json").write_text(json.dumps(result, indent=2) + "\n")
    validation = {
        "new_calls_now": 0,
        "future_max_calls": 2 * len(pairs),
        "models": ["openai/gpt-5.6-sol", "openai/gpt-5.6-luna"],
        "conditions": [
            "Sol compact input vs saved Sol full-input decision",
            "Luna full input vs saved Sol full-input decision",
        ],
        "temperature": 0,
        "prompt": "same saved system prompt for both models",
        "comparison": "mechanical parse scenario violations and rejection decision; report all disagreements, false accepts/rejects vs saved Sol and unmatched rule coverage",
        "automatic_authoritative_switch": False,
        "status": "blocked_by_balance_and_missing_provider_rates",
    }
    (NEW / "validation_plan.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
