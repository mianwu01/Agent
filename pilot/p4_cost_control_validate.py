"""Run the frozen compact/Luna judge comparison only after billing gates are ready."""

import argparse
import importlib
import json
import sys

from p4_cost_control import CostStore, valid_judgment
from p4_cost_control_run import (
    BASE,
    HISTORICAL,
    NEW,
    install,
    provider_setup,
    stop_paths,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        print(
            "Validation prepared; no model calls. Use --run after balance restoration and pricing configuration."
        )
        return
    for stop in stop_paths():
        if stop.exists():
            raise RuntimeError(f"{stop.name} still active; no API calls")
    config = json.loads((NEW / "billing_config.json").read_text())
    if any(config[k] is None for k in ["total_usd_cap", "arm_usd_cap", "sol_usd_cap"]):
        raise RuntimeError("Configure dollar caps and verified provider rates first")
    store = CostStore(NEW / "costs.sqlite", config)
    for model in ["openai/gpt-5.6-sol", "openai/gpt-5.6-luna"]:
        store.price(model)
    sys.path.insert(0, str(HISTORICAL))
    c = importlib.import_module("c2")
    c.OUT = NEW
    c.D["step2"] = NEW / "validation_requests"
    c.rules_path = lambda: BASE / "v7_c2_step1_20261006_r2/rules_v2.json"
    provider_setup(c)
    c.setup("step2", 2)
    install(c, store, "validation")
    folder = NEW / "validation_results"
    folder.mkdir(exist_ok=True)
    pairs = json.loads((NEW / "validation_pairs.json").read_text())["pairs"]
    for pair in pairs:
        for condition, model, key in [
            ("compact_sol", "openai/gpt-5.6-sol", "compact_input"),
            ("full_luna", "openai/gpt-5.6-luna", "full_input"),
        ]:
            path = folder / f"{pair['source_request_id']}_{condition}.json"
            if path.exists():
                continue
            c.x.p4.ROLE.set("comparison_labeler")
            c.x.p4.UNIT.set(f"judge_validation:{pair['source_request_id']}:{condition}")
            payload = pair[key]
            response = c.x.p4.llm_utils.generate(
                model=model,
                messages=[
                    c.SystemMessage(role="system", content=pair["system_prompt"]),
                    c.UserMessage(
                        role="user",
                        content=json.dumps(
                            {"output_format": "json", "input": payload},
                            ensure_ascii=False,
                        ),
                    ),
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=2000,
                **c.x.p4.llm_args(0, judge=True),
            )
            valid = valid_judgment(response.content, payload)
            judgment = json.loads(response.content) if valid else None
            reference = pair["historical_sol_decision"]

            def violation_ids(obj):
                return {r["rule_id"] for r in obj["scenario_violations"]}

            result = {
                "condition": condition,
                "model": model,
                "source_request_id": pair["source_request_id"],
                "schema_complete": valid,
                "response_content": response.content,
                "reference_sol_full_decision": reference,
                "new_decision": judgment,
                "same_rejection_decision": bool(violation_ids(judgment))
                == bool(violation_ids(reference))
                if valid
                else None,
                "same_violated_rules": violation_ids(judgment)
                == violation_ids(reference)
                if valid
                else None,
                "false_accept_vs_reference": valid
                and not violation_ids(judgment)
                and bool(violation_ids(reference)),
                "false_reject_vs_reference": valid
                and bool(violation_ids(judgment))
                and not violation_ids(reference),
            }
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    rows = [json.loads(p.read_text()) for p in folder.glob("*.json")]
    summary = {
        condition: {
            "n": len(rs),
            "schema_complete": sum(r["schema_complete"] for r in rs),
            "same_rejection_decision": sum(
                r["same_rejection_decision"] is True for r in rs
            ),
            "false_accept_vs_reference": sum(
                r["false_accept_vs_reference"] for r in rs
            ),
            "false_reject_vs_reference": sum(
                r["false_reject_vs_reference"] for r in rs
            ),
        }
        for condition in ["compact_sol", "full_luna"]
        for rs in [[r for r in rows if r["condition"] == condition]]
    }
    for condition, stats in summary.items():
        group = [r for r in rows if r["condition"] == condition]
        negative = sum(
            bool(r["reference_sol_full_decision"]["scenario_violations"]) for r in group
        )
        stats["reference_rejections"] = negative
        stats["reference_acceptances"] = len(group) - negative
        stats["false_accept_rate_vs_reference"] = (
            stats["false_accept_vs_reference"] / negative if negative else None
        )
    summary["authoritative_switch"] = False
    summary["reference"] = (
        "Saved Sol judgment, not human ground truth; no automatic promotion"
    )
    (NEW / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (NEW / "validation_dollar_accounting.json").write_text(
        json.dumps(store.totals(), indent=2) + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
