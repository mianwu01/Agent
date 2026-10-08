"""Audit historical fixed/sample labels for the corrected transfer predicate, no model calls."""

import re
import shutil

import c2 as c


def old_predicate(text):
    text = text.upper()
    return (
        "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON." in text
        or bool(
            re.search(
                r"\b(?:TRANSFERRING|TRANSFER|CONNECTING)\b.{0,70}\b(?:HUMAN|SPECIALIST|ANOTHER AGENT)\b",
                text,
            )
        )
    )


def main():
    root = c.D["step2"]
    tasks = c.read(root / "tasks.json")
    results = []
    for path in (root / "trajectory_batch_labels").glob("*.json"):
        row = c.read(path)
        changed = []
        for item in row["labels"]:
            inp = c.read(root / "label_inputs" / f"{item['digest']}.json")
            prefix = inp["prefix"]
            last = next((m for m in reversed(prefix) if m["role"] == "assistant"), {})
            text = last.get("content") or ""
            if old_predicate(text) == c.transfer_announced(text):
                continue
            task = c.x.b.Task.model_validate(tasks[row["trajectory"]["task_id"]])
            before = c.mech.replay(task.model_dump(mode="json"), prefix)
            after = c.mech.replay(task.model_dump(mode="json"), prefix + inp["block"])
            label = item["label"]
            prior = label["mechanical_violations"]
            new = c.mechanical_check(task, prefix, inp["block"], before, after)
            changed.append(
                {
                    "digest": item["digest"],
                    "old_mechanical": prior,
                    "new_mechanical": new,
                    "agent_message": text,
                }
            )
            label["mechanical_violations"] = new
            label["valid"] = not (
                new
                or label["programmatic_scenario_violations"]
                or label["model_scenario_violations"]
            )
        if changed:
            archive = root / "pre_transfer_fix_batch_labels" / path.name
            archive.parent.mkdir(exist_ok=True)
            if not archive.exists():
                shutil.copy2(path, archive)
            row["mechanical_version"] = "r3_explicit_transfer_announcement"
            c.save(path, row)
            results.append(
                {"trajectory": row["trajectory"]["unit"], "changes": changed}
            )
    c.save(
        root / "historical_transfer_mechanical_audit.json",
        {
            "new_model_calls": 0,
            "changed_trajectories": results,
            "model_labels_unchanged": True,
        },
    )
    print("HISTORICAL TRANSFER AUDIT changed trajectories", len(results))


if __name__ == "__main__":
    main()
