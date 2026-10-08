"""Within-state reply-cluster uncertainty supplement; never alters selection."""

import json

import b2 as x
import numpy as np


def run():
    """Resample six branch draws, paired for single/persistent, 1,000 times."""
    data = [
        json.loads(line)
        for line in (x.D["b"] / "trajectories.jsonl").read_text().splitlines()
    ]
    later = [
        json.loads(line)
        for line in (x.D["b"] / "later_partner_turns.jsonl").read_text().splitlines()
    ]
    rng = np.random.default_rng(x.read(x.OUT / "plan.json")["seeds"]["bootstrap"])
    result = []
    for sid in sorted({r["state_id"] for r in data}):
        conditions = {}
        success_samples = {}
        shared_indices = rng.integers(0, 6, size=(1000, 6))
        for arm in ["native", "single", "persistent"]:
            rows = [r for r in data if r["state_id"] == sid and r["condition"] == arm]
            groups = [
                [r for r in rows if r["unit"].split(":")[-2] == f"d{j}"]
                for j in range(6)
            ]
            assert all(len(g) == 4 for g in groups)
            values = {
                "success": lambda r: r["reward"],
                "turns_mean": lambda r: r["turns"],
                "partner_turns_mean": lambda r: r["partner_turns"],
            }
            for cat in [
                "transfer",
                "max_steps",
                "user_stop_all_assertions",
                "user_stop_unmet_assertions",
            ]:
                values[f"termination_{cat}"] = (
                    lambda r, cat=cat: r["termination"] == cat
                )
            samples = {name: [] for name in values}
            for replicate in range(1000):
                indices = (
                    rng.integers(0, 6, 6)
                    if arm == "native"
                    else shared_indices[replicate]
                )
                chosen = [r for j in indices for r in groups[j]]
                for name, f in values.items():
                    samples[name].append(float(np.mean([f(r) for r in chosen])))
            conditions[arm] = {
                name: {
                    "estimate": float(np.mean([f(r) for r in rows])),
                    "reply_cluster_95_CI": np.quantile(
                        samples[name], [0.025, 0.975]
                    ).tolist(),
                    "numerator": sum(f(r) for r in rows),
                    "denominator": 24,
                }
                for name, f in values.items()
            }
            success_samples[arm] = np.array(samples["success"])
        turns = [r for r in later if r["state_id"] == sid]
        groups = [
            [r for r in turns if r["unit"].split(":")[-2] == f"d{j}"] for j in range(6)
        ]
        metrics = {
            "tool_rate": (lambda r: r["has_user_tool_call"], lambda r: 1),
            "unobserved_claim_rate": (
                lambda r: r["claim_check"]["unobserved_claim_n"] > 0,
                lambda r: 1,
            ),
            "incorrect_claim_rate": (
                lambda r: r["claim_check"]["incorrect_claim_n"] > 0,
                lambda r: 1,
            ),
            "transfer_compliance": (
                lambda r: r["mandated_transfer"] and r["transfer_compliant"],
                lambda r: r["mandated_transfer"],
            ),
        }
        later_rates = {}
        for name, (num, den) in metrics.items():
            n, d = sum(num(r) for r in turns), sum(den(r) for r in turns)
            samples = []
            for _ in range(1000):
                chosen = [r for j in rng.integers(0, 6, 6) for r in groups[j]]
                denominator = sum(den(r) for r in chosen)
                if denominator:
                    samples.append(sum(num(r) for r in chosen) / denominator)
            later_rates[name] = {
                "numerator": n,
                "denominator": d,
                "estimate": n / d if d else None,
                "reply_cluster_95_CI": np.quantile(samples, [0.025, 0.975]).tolist()
                if samples
                else None,
                "valid_replicates": len(samples),
            }
        result.append(
            {
                "state_id": sid,
                "conditions": conditions,
                "persistent_minus_single_reply_cluster_95_CI": np.quantile(
                    success_samples["persistent"] - success_samples["single"],
                    [0.025, 0.975],
                ).tolist(),
                "later_partner": later_rates,
            }
        )
    x.save(
        x.D["b"] / "state_intervals.json",
        {
            "method": "Within state, paired resampling of the six shared branch draws for single/persistent; independent native resampling; retaining four suffixes per draw; 1000 bootstrap replicates. Pooled report remains task-cluster bootstrap. Zero-event intervals can be degenerate; no population guarantee.",
            "states": result,
        },
    )


if __name__ == "__main__":
    run()
