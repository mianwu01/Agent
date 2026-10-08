"""Preserve original labels and apply source-derived format classification offline."""

import json
import shutil

import c2 as c


def revise(label, block):
    result = json.loads(json.dumps(label))
    result["mechanical_violations"] = [
        e
        for e in label["mechanical_violations"]
        if e != "message_has_both_text_and_tools"
    ]
    result["programmatic_scenario_violations"] = c.programmatic_scenario_violations(
        label["fact_check"]
    )
    fmt = c.program_format_style(block)
    result["all_style_rule_labels"] = [
        v for v in label["all_style_rule_labels"] if v["rule_id"] != fmt["rule_id"]
    ] + [fmt]
    result["departed_style_rules"] = [
        v for v in result["all_style_rule_labels"] if v["status"] == "out_of_rule"
    ]
    result["style"] = "out_of_rule" if result["departed_style_rules"] else "in_rule"
    result["scenario_violations"] = bool(
        result["programmatic_scenario_violations"]
        or result["model_scenario_violations"]
    )
    result["valid"] = not (
        result["mechanical_violations"] or result["scenario_violations"]
    )
    result["programmatic_revision"] = (
        "rules_v2: inline content+tools allowed by runtime, style label appended without a new judge; uncertain claims deferred to frozen judge"
    )
    return result


def run():
    for step in ["step1", "step2"]:
        directory = c.D[step]
        archive = directory / "pre_format_check_archive"
        archive.mkdir(exist_ok=True)
        if step == "step1":
            for f in (directory / "replies").glob("*.json"):
                r = c.read(f)
                dst = archive / "replies" / f.name
                dst.parent.mkdir(exist_ok=True)
                if not dst.exists():
                    shutil.copy2(f, dst)
                r["label"] = revise(r["label"], r["partner_block"])
                c.save(f, r)
        else:
            manifest = c.read(directory / "manifest.json")
            inputs = {v["digest"]: v for v in manifest["unique_label_inputs"]}
            for f in (directory / "mapped_labels").glob("*.json"):
                inp = c.read(directory / "label_inputs" / f.name)
                label = c.read(f)
                dst = archive / "mapped_labels" / f.name
                dst.parent.mkdir(exist_ok=True)
                if not dst.exists():
                    shutil.copy2(f, dst)
                revised = revise(label, inp["block"])
                c.save(f, revised)
                digest = c.x.p4.digest(
                    {
                        "task": inp["task_id"],
                        "prefix": [c.x.b.ta.semantic(m) for m in inp["prefix"]],
                        "block": [c.x.b.ta.semantic(m) for m in inp["block"]],
                        "rules_sha256": c.sha(c.rules_path()),
                    }
                )
                revised["label_input_digest"] = digest
                c.save(directory / "labels" / f"{digest}.json", revised)
            # Only after the offline controller has completed: normalize all saved program checks.
            checks = list((directory / "programmatic_checks").glob("*.json"))
            for f in checks:
                row = c.read(f)
                dst = archive / "programmatic_checks" / f.name
                dst.parent.mkdir(exist_ok=True)
                if not dst.exists():
                    shutil.copy2(f, dst)
                raw = row["mechanical_violations"]
                row["mechanical_violations"] = [
                    v for v in raw if v != "message_has_both_text_and_tools"
                ]
                row["format_style"] = {
                    "rule_id": "r_5112db5336c2d337",
                    "status": "out_of_rule"
                    if "message_has_both_text_and_tools" in raw
                    else "in_rule",
                    "origin": "programmatic saved native message fields",
                }
                row["programmatic_scenario_violations"] = (
                    c.programmatic_scenario_violations(row["fact_check"])
                )
                row["rule_inventory_version"] = "rules_v2"
                c.save(f, row)
            rows = [c.read(f) for f in checks]
            c.save(
                directory / "programmatic_summary_v2.json",
                {
                    "unique_inputs": len(inputs),
                    "completed_checks": len(rows),
                    "mechanical_invalid_inputs": sum(
                        bool(r["mechanical_violations"]) for r in rows
                    ),
                    "programmatic_DB_mismatch_inputs": sum(
                        bool(r["programmatic_scenario_violations"]) for r in rows
                    ),
                    "format_style_out_of_rule_inputs": sum(
                        r["format_style"]["status"] == "out_of_rule" for r in rows
                    ),
                    "original_programmatic_summary_retained": True,
                    "new_model_calls": 0,
                },
            )
    # One old candidate was incorrectly rejected only for inline format: isolate its accepted later draw.
    affected = []
    directory = c.D["step1"]
    for f in (directory / "rejected_proposals").glob("*.json"):
        r = c.read(f)
        if r["reasons"] == ["message_has_both_text_and_tools"]:
            unit = f.stem.rsplit(":attempt", 1)[0]
            affected.append(unit)
    c.save(
        directory / "sanity_format_redo_units.json",
        {
            "units": sorted(set(affected)),
            "reason": "These selected old proposals were filtered for what is now explicitly style. Their later accepted draws are valid turns but not a final-generator sampling sanity result; redo those units after credentials are restored.",
            "new_model_calls": 0,
        },
    )
    print("MIGRATED; redo units", affected, flush=True)


if __name__ == "__main__":
    run()
