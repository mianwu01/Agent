"""Task-cluster uncertainty for paired sensitivity and cross-fitted concentration."""

import argparse
import collections
import json
import random
import statistics
from pathlib import Path

import p4_v6_paired as paired


def interval(values):
    """Summarize valid bootstrap ratios without clipping or imputing denominators."""
    if not values:
        return {"valid_replicates": 0, "interval_95": None}
    xs = sorted(values)
    return {
        "valid_replicates": len(xs),
        "interval_95": [xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]],
    }


def main():
    """Resample tasks, keeping their correlated prefix measurements together."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=paired.OUT)
    parser.add_argument("--replicates", type=int, default=1000)
    args = parser.parse_args()
    data = json.loads((args.run / "summary.json").read_text())
    groups = collections.defaultdict(list)
    for state in data["states"]:
        groups[state["task_id"]].append(state)
    keys = sorted(groups)
    rng = random.Random(2026100411)
    contrasts = []
    ratios = {label: [[], []] for label in ["all", "open_union"]}
    for _ in range(args.replicates):
        selected = [rng.choice(keys) for _ in keys]
        states = [s for k in selected for s in groups[k]]
        contrasts.append(
            statistics.mean(
                statistics.mean(s["sensitivity_contrast"] for s in groups[k])
                for k in selected
            )
        )
        for label, subset in [
            ("all", states),
            ("open_union", [s for s in states if s["open_union"]]),
        ]:
            for fold, result in enumerate(paired.concentration(subset)["folds"]):
                if result["C10"] is not None:
                    ratios[label][fold].append(result["C10"])
    result = {
        "task_clusters": len(keys),
        "replicates": args.replicates,
        "sensitivity_contrast": interval(contrasts),
        "concentration": {
            label: [interval(fold) for fold in folds] for label, folds in ratios.items()
        },
        "notes": [
            "Task-cluster bootstrap conditional on the observed state pool and empirical openness labels.",
            "Report valid ratio replicate counts: nonpositive denominators have no meaningful ratio.",
            "Raw ratios and intervals may extend outside [0,1] because sensitivities are noise-corrected.",
        ],
    }
    (args.run / "uncertainty.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
