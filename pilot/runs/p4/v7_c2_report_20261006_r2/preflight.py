"""No-suffix other-family interface probe and pre-run amendments."""

import json
from datetime import datetime, timezone

import c2 as c
import search as s


def main():
    c.FULL_STYLE = False
    c.setup("step3", 2)
    plan = c.read(c.ACTIVE / "plan.json")
    old = c.read(c.BASE / "v7_c2_step1_20261006/plan.json")
    case = old["sanity_states"][0]
    source = c.read(
        c.BASE / "v7_c2_step1_20261006/sources" / f"{case['source_id']}.json"
    )
    prefix = source["messages"][: case["index"]]
    other = [f for f in plan["families"] if f.startswith("other:")]
    results = []
    available = []
    for family in other:
        try:
            reply = c.sample_reply(
                case, 0, 0, family=family, prefix=prefix, unit="other_family_interface"
            )
            calls = [c.read(p) for p in (c.ACTIVE / "requests").glob("*.json")]
            returned = sorted(
                {
                    r.get("returned_model")
                    for r in calls
                    if r.get("role") == "user" and r.get("returned_model")
                }
            )
            different_family = any(
                "deepseek" in r.lower() or "qwen" in r.lower() or "claude" in r.lower()
                for r in returned
            )
            results.append(
                {
                    "family": family,
                    "valid": reply["label"]["valid"],
                    "returned_models": returned,
                    "different_model_family": different_family,
                }
            )
            if different_family:
                available.append(family)
        except Exception as exc:
            results.append(
                {
                    "family": family,
                    "available": False,
                    "type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
            )
    c.save(c.ACTIVE / "interface_probe.json", {"results": results, "suffixes": 0})
    # Future execution uses the effective pre-run amendment; original plan remains frozen.
    amendment = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "User-requested r2 persona inventory and reduced full-label scope; pre-screen tested model availability; parallel independent suffixes do not change node-level reuse rule.",
        "effective_families": ["native", "vs"] + available,
        "style_label_scope": "Only independently verified cases get full rule/persona labels. Screening/generated turns receive mechanical and scenario checks; unknown style is not in_rule. Fixed single case labels branch block; persistent intervention labels all candidate turns across its16 retest suffixes.",
        "search_workers_per_arm": 8,
        "rule_inventory_sha256": c.sha(c.rules_path()),
        "label_prompt": c.LABEL_PROMPT,
        "context_cleanup": "Full native generator system prompt unchanged. Model judge receives compact applicable rule text, private scenario, history, DB; no rule-location audit metadata.",
        "shared_probe_cost": "All preflight returned tokens split equally across five arms, charged to each arm token cap and efficiency denominator. Unknown probe usage kept unknown separately.",
        "persona_and_sanity_scope": "No additional full-style sanity re-labelling after user restricted full labels to confirmed cases. Historical55 accepted draws retained as historical incomplete sanity, not presented as r2 full sanity.",
        "sensitivity": "Variance(reply means,ddof1)-mean(p_i*(1-p_i))/(m-1); k6,m2; retain negative estimates.",
        "native_node_revisits": "All generators, including native, draw fresh6replies per expansion. Cached reference6x2 is only a reference, never reused as the native generator expansion. All generator suffix units are expansion-specific. Additional native reference costs included.",
        "case_classes": "Frozen C1 scope-corrected definitions. Fixed-block DB-change classes are not automatically assigned to a persistent generator without a fixed-block analogue.",
    }
    c.save(c.ACTIVE / "plan_amendment_r2.json", amendment)
    s.mode_paths(c.read(c.ACTIVE / "tasks.json"))
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
