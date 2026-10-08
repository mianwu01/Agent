"""Render the four-case exploratory reminder comparison with matplotlib."""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    """Save an exportable descriptive figure; selected cases are not population data."""
    out = Path(__file__).resolve().parents[1] / "pilot/runs/p4/calibration_20261003"
    with (out / "case_outcomes.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    cases = ["v001", "v006", "v013", "v036"]
    labels = [
        "v001\nMMS / SIM + permissions",
        "v006\nMMS / mixed failure",
        "v013\nData / 2G",
        "v036\nData / speed test",
    ]
    arms = ["resample", "generic_policy", "capability_policy"]
    names = ["Original policy", "Generic policy reminder", "User capability reminder"]
    colors = ["#5470c6", "#8a919c", "#de8e36"]
    fig, ax = plt.subplots(figsize=(10.2, 4.9), layout="constrained")
    for number, (arm, name, color) in enumerate(zip(arms, names, colors, strict=True)):
        selected = [
            next(r for r in rows if r["sample_id"] == sid and r["arm"] == arm)
            for sid in cases
        ]
        assert all(int(r["completed"]) == 8 for r in selected)
        x = [i + (number - 1) * 0.24 for i in range(len(cases))]
        values = [int(r["successes"]) / 8 * 100 for r in selected]
        bars = ax.bar(x, values, width=0.22, label=name, color=color)
        ax.bar_label(
            bars,
            labels=[r["successes"] + "/8" for r in selected],
            padding=3,
            fontsize=10,
        )
    ax.set_xticks(range(len(cases)), labels, fontsize=10)
    ax.set_ylim(0, 114)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("Native task success (%)")
    ax.set_title(
        "Persistent user-capability guidance on four independent selected cases",
        fontsize=13,
        pad=16,
    )
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=False)
    fig.savefig(out / "reminder_comparison.png", dpi=180, bbox_inches="tight")
    fig.savefig(out / "reminder_comparison.pdf", bbox_inches="tight")
    plt.close(fig)
    print("Saved exploratory comparison PNG and PDF")


if __name__ == "__main__":
    main()
