"""Summarize complete trial batches, retaining explicit pending/error status."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs/trial"
NAMES = {
    "local": "gpt-oss-20b / local vLLM",
    "openrouter": "gpt-oss-20b / OpenRouter",
    "mini": "gpt-4.1-mini-2025-04-14 / OpenAI",
    "luna": "gpt-5.6-luna / AutoDL (Luna user; reasoning none)",
}


def summarize(candidate, expected_ids):
    """Reject partial batches and infra failures rather than count them as failures."""
    groups = {}
    issues = []
    for mode, trials in [("default", 4), ("no-user", 2)]:
        path = RUNS / candidate / mode / "results.json"
        if not path.exists():
            issues.append(f"{mode}: pending")
            continue
        data = json.loads(path.read_text())
        sims = data["simulations"]
        if Counter(s["task_id"] for s in sims) != Counter(
            {t: trials for t in expected_ids}
        ):
            issues.append(f"{mode}: incomplete ({len(sims)}/{10 * trials})")
        elif {(s["task_id"], s["trial"]) for s in sims} != {
            (t, r) for t in expected_ids for r in range(trials)
        }:
            issues.append(f"{mode}: duplicate/missing trial numbers")
        elif any(
            s["termination_reason"] == "infrastructure_error"
            or s.get("reward_info") is None
            for s in sims
        ):
            issues.append(f"{mode}: infrastructure error (see results.json)")
        else:
            groups[mode] = sims
    row = {
        "model": NAMES[candidate],
        "status": "; ".join(issues) if issues else "complete",
    }
    if issues:
        return row
    mixed = set()
    for mode, sims in groups.items():
        row[mode + "_success_rate"] = mean(
            s["reward_info"]["reward"] == 1 for s in sims
        )
        by_task = defaultdict(set)
        for s in sims:
            by_task[s["task_id"]].add(s["reward_info"]["reward"] == 1)
        mode_mixed = {t for t, outcomes in by_task.items() if len(outcomes) > 1}
        row[mode + "_mixed_tasks"] = len(mode_mixed)
        mixed |= mode_mixed
    row["mixed_tasks"] = len(mixed)
    sims = groups["default"] + groups["no-user"]
    row["mean_messages"] = mean(len(s["messages"]) for s in sims)
    row["mean_wall_seconds"] = mean(s["duration"] for s in sims)
    for role, label in [("assistant", "agent"), ("user", "user")]:
        for token in ["prompt_tokens", "completion_tokens"]:
            totals = []
            for s in sims:
                total = 0
                for m in s["messages"]:
                    if m["role"] != role:
                        continue
                    usage = m.get("usage")
                    if usage is None:
                        if m.get("raw_data") or m.get("cost"):
                            raise ValueError(
                                f"Missing usage for generated message: {s['id']}"
                            )
                        continue  # Scripted greeting / initialization message.
                    if usage.get(token) is None:
                        raise ValueError(f"Missing {token}: {s['id']}")
                    total += usage[token]
                totals.append(total)
            row[f"mean_{label}_{token}"] = mean(totals)
    return row


def main():
    """Write one comparison table plus machine-readable statistics."""
    expected = json.loads((ROOT / "sample.json").read_text())["task_ids"]
    rows = [summarize(candidate, expected) for candidate in NAMES]
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    columns = [
        "model",
        "default_success_rate",
        "no-user_success_rate",
        "mixed_tasks",
        "mean_messages",
        "mean_agent_prompt_tokens",
        "mean_agent_completion_tokens",
        "mean_user_prompt_tokens",
        "mean_user_completion_tokens",
        "mean_wall_seconds",
        "status",
    ]
    with (RUNS / "summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    labels = [
        "Model",
        "Default success",
        "No-user success",
        "Mixed tasks",
        "Messages/run",
        "Agent prompt/run",
        "Agent completion/run",
        "User prompt/run",
        "User completion/run",
        "Wall seconds/run",
        "Status",
    ]
    lines = [
        "# Pilot model trial",
        "",
        "| " + " | ".join(labels) + " |",
        "| " + " | ".join(["---"] * len(labels)) + " |",
    ]
    for row in rows:
        values = []
        for key in columns:
            value = row.get(key, "—")
            if isinstance(value, float):
                value = (
                    f"{value:.1%}" if key.endswith("success_rate") else f"{value:.2f}"
                )
            values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "Success is reward = 1. Each complete row contains 40 default and 20 no-user runs. Mixed tasks counts the union of tasks with both success and failure within either mode; differences only between modes do not count. Per-mode counts are in summary.json.",
        "",
        "Means pool all 60 runs. Messages include tool messages and scripted greetings. Token counts sum messages[].usage by assistant/user role (including each role's tool-call messages); no-user user totals are zero. Wall time is SimulationRun.duration (orchestrator time), excluding evaluation, queue time, and failed retry attempts; batch_timing.json also records elapsed runner time. Pending/incomplete/infrastructure-error rows are not given aggregate scores.",
        "",
    ]
    (RUNS / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
