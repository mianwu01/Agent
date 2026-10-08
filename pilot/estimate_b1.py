"""Estimate B1 usage from measured Luna trial tokens and batch elapsed times."""

import hashlib
import json
from pathlib import Path

PILOT = Path(__file__).resolve().parent


def main():
    """Save an auditable estimate; make no model calls."""
    modes = {}
    for mode, trials in [("default", 8), ("no-user", 4)]:
        directory = PILOT / "runs/trial/luna" / mode
        result_path = directory / "results.json"
        raw = result_path.read_bytes()
        simulations = json.loads(raw)["simulations"]
        assert all(
            s["reward_info"] is not None
            and s["termination_reason"] != "infrastructure_error"
            for s in simulations
        )
        config = json.loads((directory / "config.json").read_text())
        assert config["max_concurrency"] == 3
        count = 114 * trials
        multiplier = count / len(simulations)
        tokens = {}
        for role in ("assistant", "user"):
            tokens[role] = {}
            for field in ("prompt_tokens", "completion_tokens"):
                total = 0
                for simulation in simulations:
                    for message in simulation["messages"]:
                        if message["role"] != role:
                            continue
                        usage = message.get("usage")
                        if message.get("raw_data") and usage is None:
                            raise ValueError("Generated message lacks usage")
                        if usage is not None:
                            total += usage[field]
                tokens[role][field] = {
                    "trial_total": total,
                    "trial_mean_per_run": total / len(simulations),
                    "b1_expected_total": total * multiplier,
                }
        batch_seconds = json.loads((directory / "batch_timing.json").read_text())[
            "wall_seconds"
        ]
        modes[mode] = {
            "source": str(result_path.relative_to(PILOT)),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "trial_runs": len(simulations),
            "b1_runs": count,
            "scale_factor": multiplier,
            "tokens": tokens,
            "trial_mean_simulation_seconds": sum(s["duration"] for s in simulations)
            / len(simulations),
            "trial_batch_seconds": batch_seconds,
            "b1_expected_batch_seconds": batch_seconds * multiplier,
        }
    totals = {
        field: sum(
            mode["tokens"][role][field]["b1_expected_total"]
            for mode in modes.values()
            for role in ("assistant", "user")
        )
        for field in ("prompt_tokens", "completion_tokens")
    }
    totals["all_tokens"] = sum(totals.values())
    totals["wall_seconds"] = sum(
        mode["b1_expected_batch_seconds"] for mode in modes.values()
    )
    report = {
        "model": "openai/gpt-5.6-luna",
        "api_base": "https://www.autodl.art/api/v1",
        "temperature": 1.0,
        "reasoning_effort": "none",
        "max_concurrency": 3,
        "modes": modes,
        "totals": totals,
        "assumptions": [
            "114 tasks; 8 default and 4 no-user trials per task; 1368 runs total.",
            "Both modes scale their measured 10-task trial by 22.8.",
            "Wall time scales measured batch time, including runner overhead, "
            "at concurrency 3 with modes run sequentially.",
            "Task difficulty, response latency and token usage may differ over "
            "all 114 tasks; this is a point estimate, not an upper bound.",
            "Excludes B2 proposals, branch continuations, strong-agent runs, "
            "and additional smoke/probe calls.",
            "All 1368 B1 runs are estimated as fresh runs; no pilot reuse assumed.",
            "No dollar estimate: AutoDL rates have not been verified.",
        ],
    }
    destination = PILOT / "b1-estimate.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# B1 pre-launch estimate",
        "",
        "Luna agent and user via AutoDL; temperature 1.0; reasoning none.",
        "",
        "| Mode | Runs | Input tokens | Output tokens | Batch hours (concurrency 3) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, mode in modes.items():
        counts = {
            field: sum(
                role[field]["b1_expected_total"] for role in mode["tokens"].values()
            )
            for field in ("prompt_tokens", "completion_tokens")
        }
        lines.append(
            f"| {name} | {mode['b1_runs']} | {counts['prompt_tokens']:,.0f} | "
            f"{counts['completion_tokens']:,.0f} | "
            f"{mode['b1_expected_batch_seconds'] / 3600:.2f} |"
        )
    lines += [
        f"| Total | 1368 | {totals['prompt_tokens']:,.0f} | "
        f"{totals['completion_tokens']:,.0f} | {totals['wall_seconds'] / 3600:.2f} |",
        "",
        f"Expected total tokens: **{totals['all_tokens']:,.0f}**.",
        "",
        *[f"- {assumption}" for assumption in report["assumptions"]],
        "",
        "See `b1-estimate.json` for per-role means, source hashes, and arithmetic.",
        "Regenerate with `.venv/bin/python pilot/estimate_b1.py`.",
    ]
    (PILOT / "b1-estimate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
