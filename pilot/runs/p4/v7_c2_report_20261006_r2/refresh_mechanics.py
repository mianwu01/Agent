"""Recompute only programmatic labels after the native STOP-description correction."""

import shutil

import c2 as c


def main():
    root = c.D["step2"]
    tasks = c.read(root / "tasks.json")
    for path in (root / "trajectory_batch_labels").glob("*.json"):
        data = c.read(path)
        if data.get("mechanical_version") in {
            "r2_native_private_goal_description",
            "r3_explicit_transfer_announcement",
        }:
            continue
        archive = root / "pre_stop_fix_batch_labels" / path.name
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            shutil.copy2(path, archive)
        task = c.x.b.Task.model_validate(tasks[data["trajectory"]["task_id"]])
        for item in data["labels"]:
            inp = c.read(root / "label_inputs" / f"{item['digest']}.json")
            before = c.mech.replay(task.model_dump(mode="json"), inp["prefix"])
            after = c.mech.replay(
                task.model_dump(mode="json"), inp["prefix"] + inp["block"]
            )
            label = item["label"]
            label["mechanical_violations"] = c.mechanical_check(
                task, inp["prefix"], inp["block"], before, after
            )
            label["valid"] = not (
                label["mechanical_violations"]
                or label["programmatic_scenario_violations"]
                or label["model_scenario_violations"]
            )
        data["mechanical_version"] = "r2_native_private_goal_description"
        c.save(path, data)


if __name__ == "__main__":
    main()
