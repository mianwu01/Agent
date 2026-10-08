"""Render flipped continuations and accounting summaries without failure labels."""

import csv
import html
import json
import re

from branch_common import BRANCH, ROOT
from render_reading import block


def render_messages(messages, start):
    """Render text and complete tool calls/results with original array indices."""
    parts = []
    for i, m in enumerate(messages, start):
        parts.append(f"### Message {i} — {m['role']}\n")
        if m.get("content") is not None:
            parts.append(block(m["content"]))
        if m.get("tool_calls"):
            parts.append(block(m["tool_calls"]))
        if m["role"] == "tool":
            parts.append(
                f"Requestor: {m.get('requestor')}; call ID: {m.get('id')}; error: {m.get('error')}\n"
            )
    return parts


def main():
    """Write per-flip reading packs and one summary row per arm."""
    rows = [json.loads(s) for s in (BRANCH / "branches.jsonl").read_text().splitlines()]
    data = json.loads((ROOT / "pilot/runs/iid/default/results.json").read_text())
    tasks = {t["id"]: t for t in data["tasks"]}
    out = BRANCH / "reading"
    out.mkdir(parents=True, exist_ok=True)
    links = []
    for row in rows:
        if not row["flipped"]:
            continue
        task = tasks[row["task_id"]]
        prefix = json.loads((ROOT / row["prefix_path"]).read_text())
        sim = json.loads((ROOT / row["trajectory_path"]).read_text())
        match = re.fullmatch(r"\[([^]]+)\](.*?)\[PERSONA:([^]]+)\]", task["id"])
        category, subtasks, persona = match.groups()
        lines = [
            f"# {task['id']}\n",
            f"Branch: `{row['branch_id']}`; arm: {row['arm']}; rep: {row['rep']}\n",
            f"Category: {category}; persona: {persona}; subtasks: {', '.join(subtasks.split('|'))}\n",
            "## Scenario\n",
            block(task["user_scenario"]),
            "## Ticket\n",
            block(task.get("ticket")),
            "## Last six prefix messages\n",
            *render_messages(prefix[-6:], max(0, len(prefix) - 6)),
            "## User message comparison\n",
            "<table><tr><th>Original</th><th>New</th></tr><tr><td><pre>"
            + html.escape(row["original_user_message"] or "")
            + "</pre></td><td><pre>"
            + html.escape(row["new_user_message"] or "[No user text generated]")
            + "</pre></td></tr></table>\n",
        ]
        if row["arm"] == "vs_tail":
            lines += ["## All five proposed candidates\n", block(row["vs_candidates"])]
        lines += [
            "## Continuation (new messages only)\n",
            *render_messages(sim["messages"][len(prefix) :], len(prefix)),
            "## Recorded outcome\n",
            f"Reward: {row['reward']}; termination: {row['termination_reason']}\n",
        ]
        info = sim["reward_info"]
        for title, key, flag in [
            ("Failed assertions", "env_assertions", "met"),
            ("Failed action checks", "action_checks", "action_match"),
        ]:
            lines += [
                f"### {title}\n",
                block([c for c in info.get(key) or [] if c[flag] is False]),
            ]
        name = row["branch_id"] + ".md"
        (out / name).write_text("\n".join(lines) + "\n")
        links.append(f"- [{row['branch_id']}](./{name})")
    (out / "index.md").write_text(
        "# Flipped continuations\n\n" + "\n".join(links) + "\n"
    )
    planned = len(json.loads((BRANCH / "selection.json").read_text())["positions"])
    all_proposals = [
        json.loads(p.read_text()) for p in (BRANCH / "proposals").rglob("*.json")
    ]
    summaries = []
    for arm in ["resample", "vs_tail"]:
        group = [r for r in rows if r["arm"] == arm]
        proposals = all_proposals if arm == "vs_tail" else []
        usages = [
            p["response"]["usage"]
            for p in proposals
            if p.get("response", {}).get("usage") is not None
        ]
        proposal_input = sum(u["prompt_tokens"] for u in usages)
        proposal_output = sum(u["completion_tokens"] for u in usages)
        input_tokens = (
            sum(sum(r["cont_input_tokens"].values()) for r in group) + proposal_input
        )
        output_tokens = (
            sum(sum(r["cont_output_tokens"].values()) for r in group) + proposal_output
        )
        flips = sum(r["flipped"] for r in group)
        summaries.append(
            {
                "arm": arm,
                "branches": len({(r["source_sim_id"], r["i"]) for r in group}),
                "continuations": len(group),
                "flipped": flips,
                "flip_rate": flips / len(group) if group else "",
                "total_tokens": input_tokens + output_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "planned_branches": planned,
                "planned_continuations": planned * 2,
                "status": "complete" if len(group) == planned * 2 else "incomplete",
                "proposal_calls": len(proposals),
                "proposal_failures": sum("candidates" not in p for p in proposals),
                "proposals_missing_usage": len(proposals) - len(usages),
                "proposal_input_tokens": proposal_input,
                "proposal_output_tokens": proposal_output,
            }
        )
    with (BRANCH / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0]))
        w.writeheader()
        w.writerows(summaries)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
