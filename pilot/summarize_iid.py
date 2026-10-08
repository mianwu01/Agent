"""Validate B1 completeness and write one row per task with ordered run metrics."""

import csv
import json
from collections import Counter
from pathlib import Path

from branch_common import token_totals


def main():
    """Refuse missing, duplicate, or infrastructure-error runs."""
    root = Path(__file__).parent / "runs/iid"
    groups = {}
    tasks = None
    for mode, n in [("default", 8), ("no-user", 4)]:
        d = json.loads((root / mode / "results.json").read_text())
        current = {t["id"] for t in d["tasks"]}
        assert len(current) == 114
        if tasks is None:
            tasks = current
        assert tasks == current
        sims = d["simulations"]
        assert Counter(s["task_id"] for s in sims) == Counter({t: n for t in tasks})
        assert {(s["task_id"], s["trial"]) for s in sims} == {
            (t, r) for t in tasks for r in range(n)
        }
        assert all(
            s["reward_info"] is not None
            and s["termination_reason"] != "infrastructure_error"
            for s in sims
        )
        groups[mode] = {
            t: sorted([s for s in sims if s["task_id"] == t], key=lambda s: s["trial"])
            for t in tasks
        }
    rows = []
    for t in sorted(tasks):
        row = {"task_id": t}
        for mode in groups:
            for s in groups[mode][t]:
                stem = f"{mode}_{s['trial']}"
                row[stem + "_reward"] = s["reward_info"]["reward"]
                tok = token_totals(s["messages"])
                for name in ["input", "output"]:
                    row[stem + "_" + name + "_tokens"] = sum(tok[name].values())
                    for role in ["agent", "user"]:
                        row[stem + "_" + role + "_" + name + "_tokens"] = tok[name][
                            role
                        ]
        rows.append(row)
    with (root / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("Validated 1368 runs; wrote", root / "summary.csv")


if __name__ == "__main__":
    main()
