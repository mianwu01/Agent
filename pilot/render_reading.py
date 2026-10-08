"""Render shipped telecom trajectories, without interpreting their failures."""

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pilot/reading"


def block(value):
    """Preserve text and JSON inside a safe Markdown fence."""
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, indent=2, ensure_ascii=False)
    )
    fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", text)), default=3))
    return f"{fence}\n{text}\n{fence}\n"


def reward(sim):
    return sim["reward_info"]["reward"]


def main():
    """Validate the input coverage and generate both reading sets."""
    OUT.mkdir(parents=True, exist_ok=True)
    groups, tasks, sources = {}, {}, {}
    for mode in ("default", "no-user"):
        path = (
            ROOT
            / f"data/tau2/results/final/gpt-4.1-2025-04-14_telecom_{mode}_gpt-4.1-2025-04-14_4trials.json"
        )
        data = json.loads(path.read_text())
        sources[mode] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        tasks[mode] = {t["id"]: t for t in data["tasks"]}
        groups[mode] = defaultdict(list)
        for sim in data["simulations"]:
            groups[mode][sim["task_id"]].append(sim)
        assert len(tasks[mode]) == len(groups[mode]) == 114
        assert len(data["simulations"]) == 456
        for sims in groups[mode].values():
            sims.sort(key=lambda s: s["trial"])
            assert len(sims) == 4 and len({s["trial"] for s in sims}) == 4
    assert tasks["default"] == tasks["no-user"]
    rows, selected = [], []
    counts = {"S": 0, "R": 0}
    for task_id, task in tasks["default"].items():
        rewards = {m: [reward(s) for s in groups[m][task_id]] for m in groups}
        d, n = mean(rewards["default"]), mean(rewards["no-user"])
        if n >= 0.75 and d <= 0.25:
            set_name, failed_mode, other_mode = "S", "default", "no-user"
        elif d >= 0.75 and n <= 0.25:
            set_name, failed_mode, other_mode = "R", "no-user", "default"
        else:
            continue
        counts[set_name] += 1
        sim = next(s for s in groups[failed_mode][task_id] if reward(s) < 1)
        reference = next(s for s in groups[other_mode][task_id] if reward(s) == 1)
        match = re.fullmatch(r"\[([^]]+)\](.*?)\[PERSONA:([^]]+)\]", task_id)
        assert match, task_id
        category, subtasks, persona = match.groups()
        subtasks = subtasks.split("|")
        filename = f"{set_name}-{category}-{hashlib.sha256(task_id.encode()).hexdigest()[:12]}.md"
        lines = [
            f"# {task_id}\n",
            f"Set: **{set_name}**; category: `{category}`; persona: `{persona}`.\n",
            "Subtasks (parsed from ID): "
            + ", ".join(f"`{s}`" for s in subtasks)
            + ".\n",
            f"Selected {failed_mode} trial: `{sim['trial']}`; sim_id: `{sim['id']}`; seed: `{sim['seed']}`.\n",
            "Rewards in ascending trial-number order:\n",
        ]
        for mode in groups:
            lines.append(
                f"- {mode}: `{rewards[mode]}` (mean {mean(rewards[mode]):.2f})"
            )
        lines += [
            "\n## User scenario\n",
            block(task["user_scenario"]),
            "## Ticket\n",
            block(task["ticket"]),
            "## Conversation\n",
            "Message indices are zero-based positions in the saved messages array. Tool results show at most 300 source characters.\n",
        ]
        for i, msg in enumerate(sim["messages"]):
            label = msg["role"]
            if label == "tool":
                label += f" (requestor: {msg.get('requestor')}, call ID: {msg.get('id')}, error: {msg.get('error')})"
            lines.append(
                f"### Message {i} — {label} — turn_idx {msg.get('turn_idx')}\n"
            )
            content = msg.get("content")
            if content is not None:
                if msg["role"] == "tool":
                    content = (
                        content
                        if isinstance(content, str)
                        else json.dumps(content, ensure_ascii=False)
                    )
                    lines.append(block(content[:300]))
                    if len(content) > 300:
                        lines.append(
                            f"*Truncated: {len(content)} source characters.*\n"
                        )
                else:
                    lines.append(block(content))
            for call in msg.get("tool_calls") or []:
                lines.append(
                    block(
                        {
                            "requestor": call.get("requestor", msg["role"]),
                            "id": call["id"],
                            "name": call["name"],
                            "arguments": call["arguments"],
                        }
                    )
                )
        info = sim["reward_info"]
        lines += [
            "## Recorded outcome\n",
            f"Reward: {reward(sim)}; termination: `{sim['termination_reason']}`.\n",
            "Reward basis: " + block(info.get("reward_basis")),
            "Reward breakdown: " + block(info.get("reward_breakdown")),
        ]
        for title, key, flag in (
            ("Failed environment assertions", "env_assertions", "met"),
            ("Failed action checks", "action_checks", "action_match"),
        ):
            checks = info.get(key)
            failed = [c for c in checks or [] if c[flag] is False]
            lines += [
                f"### {title}\n",
                block(failed)
                if failed
                else (
                    "Not recorded.\n"
                    if checks is None
                    else "None recorded as failed.\n"
                ),
            ]
        lines += [
            "## Successful trial in the other mode: tool-call sequence\n",
            f"Mode: {other_mode}; trial: `{reference['trial']}`; sim_id: `{reference['id']}`; reward: {reward(reference)}.\n",
        ]
        calls = [
            {"name": c["name"], "arguments": c["arguments"]}
            for m in reference["messages"]
            for c in m.get("tool_calls") or []
        ]
        lines.append(block(calls))
        (OUT / filename).write_text("\n".join(lines))
        rows.append(
            [
                task_id.replace("|", "\\|"),
                set_name,
                category,
                persona,
                str(len(subtasks)),
                str(rewards["default"]),
                str(rewards["no-user"]),
                f"[read]({filename})",
            ]
        )
        selected.append(
            {
                "task_id": task_id,
                "sim_id": sim["id"],
                "set": set_name,
                "file": filename,
                "trial": sim["trial"],
                "reference_sim_id": reference["id"],
            }
        )
    header = "# Telecom reading packs\n\nS: no-user mean ≥ 0.75, default mean ≤ 0.25. R: default mean ≥ 0.75, no-user mean ≤ 0.25.\n\n"
    header += f"Counts: S = {counts['S']}, R = {counts['R']}. First means lowest saved trial number; success means reward = 1.\n\n"
    header += "| Task ID | Set | Category | Persona | Subtasks | Default rewards | No-user rewards | File |\n| --- | --- | --- | --- | ---: | --- | --- | --- |\n"
    (OUT / "index.md").write_text(
        header + "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
    )
    # Preserve human annotations when re-rendering.
    notes = OUT / "notes.csv"
    existing = {}
    if notes.exists():
        with notes.open(newline="") as f:
            existing = {(r["task_id"], r["sim_id"]): r for r in csv.DictReader(f)}
    with notes.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["task_id", "sim_id", "one_line", "who_caused", "notes"]
        )
        writer.writeheader()
        for row in selected:
            writer.writerow(
                existing.get(
                    (row["task_id"], row["sim_id"]),
                    {k: row[k] for k in ("task_id", "sim_id")},
                )
            )
    (OUT / "manifest.json").write_text(
        json.dumps(
            {"sources": sources, "counts": counts, "selected": selected}, indent=2
        )
        + "\n"
    )
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
