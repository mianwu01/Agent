"""Plot paired sensitivity and mean outcome shifts from the v6.1 measurement."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    """Export two panels without clipping noisy variance estimates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", type=Path, default=Path(__file__).parent / "runs/p4/v6_paired_20261004"
    )
    args = parser.parse_args()
    data = json.loads((args.run / "summary.json").read_text())
    states = data["states"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3), layout="constrained")
    for openness, color, label in [
        (False, "#8b949e", "Observed closed"),
        (True, "#0077b6", "Open / Sol-recoverable"),
    ]:
        selected = [s for s in states if s["open_union"] == openness]
        for ax, keys in zip(
            axes, [("S_hat", "S_hat"), ("V_hat", "V_hat")], strict=True
        ):
            ax.scatter(
                [s["q"][keys[0]] for s in selected],
                [s["q_prime"][keys[1]] for s in selected],
                s=48,
                color=color,
                alpha=0.65,
                label=label,
                edgecolors="white",
                linewidths=0.5,
            )
    x = [s["q"]["S_hat"] for s in states]
    y = [s["q_prime"]["S_hat"] for s in states]
    lo = min([0, *x, *y]) - 0.015
    hi = max([0.05, *x, *y]) + 0.015
    axes[0].plot([lo, hi], [lo, hi], color="#aab0b6", ls="--", lw=1)
    axes[0].axhline(0, color="#d7dce0", lw=0.8)
    axes[0].axvline(0, color="#d7dce0", lw=0.8)
    axes[0].set(
        xlim=(lo, hi),
        ylim=(lo, hi),
        xlabel="Native sensitivity S_q",
        ylabel="Faithful proposal sensitivity S_q-prime",
        title="Partner-turn variance (noise corrected)",
    )
    for s in sorted(states, key=lambda s: s["sensitivity_contrast"], reverse=True)[:3]:
        axes[0].annotate(
            s["state_id"],
            (s["q"]["S_hat"], s["q_prime"]["S_hat"]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
        )
    axes[1].plot([0, 1], [0, 1], color="#aab0b6", ls="--", lw=1)
    axes[1].set(
        xlim=(-0.04, 1.04),
        ylim=(-0.04, 1.04),
        xlabel="Native success V_q",
        ylabel="Faithful proposal success V_q-prime",
        title="Mean outcome shift (separate from variance)",
    )
    axes[0].legend(loc="lower right", fontsize=8)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.15)
    fig.suptitle(
        f"Paired partner sampling: {len(states)} states, k=6, m=4 per family",
        fontsize=12,
    )
    fig.savefig(args.run / "paired_sensitivity.png", dpi=180)
    fig.savefig(args.run / "paired_sensitivity.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
