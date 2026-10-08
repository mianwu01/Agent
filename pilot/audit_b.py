"""Audit completed Prompt B coverage, saved prefixes, usage, and reading outputs."""

import csv
import json

from branch_common import BRANCH, ROOT, token_totals, write_json
from run_branch import parse_candidates, select


def main():
    """Fail visibly on any missing or inconsistent output."""
    data = json.loads((ROOT / "pilot/runs/iid/default/results.json").read_text())
    solo = json.loads((ROOT / "pilot/runs/iid/no-user/results.json").read_text())
    assert len(data["tasks"]) == 114
    for batch, trials in ((data, 8), (solo, 4)):
        for task in batch["tasks"]:
            runs = [s for s in batch["simulations"] if s["task_id"] == task["id"]]
            assert len(runs) == trials
            assert len({s["trial"] for s in runs}) == trials
    manifest = json.loads((BRANCH / "selection.json").read_text())
    assert select(data) == manifest
    sources = {s["id"]: s for s in data["simulations"]}
    expected = {
        f"{s['source_sim_id']}:{s['i']}:{arm}:{rep}"
        for s in manifest["positions"]
        for arm in ("resample", "vs_tail")
        for rep in range(2)
    }
    rows = [json.loads(s) for s in (BRANCH / "branches.jsonl").read_text().splitlines()]
    assert len(rows) == len(expected)
    assert {r["branch_id"] for r in rows} == expected
    assert len({r["seed_or_rep"] for r in rows}) == len(rows)
    fields = ("role", "content", "tool_calls", "id", "requestor")
    for row in rows:
        source = sources[row["source_sim_id"]]
        assert source["reward_info"]["reward"] == 1
        prefix = json.loads((ROOT / row["prefix_path"]).read_text())
        trajectory = json.loads((ROOT / row["trajectory_path"]).read_text())
        assert row["original_user_message"] == source["messages"][row["i"]]["content"]
        assert prefix[: row["i"]] == source["messages"][: row["i"]]
        assert len(prefix) == row["i"] + (row["arm"] == "vs_tail")
        for old, new in zip(prefix, trajectory["messages"][: len(prefix)], strict=True):
            assert all(old.get(k) == new.get(k) for k in fields)
        tokens = token_totals(trajectory["messages"][len(prefix) :])
        assert tokens["input"] == row["cont_input_tokens"]
        assert tokens["output"] == row["cont_output_tokens"]
        assert row["reward"] == trajectory["reward_info"]["reward"]
        assert row["flipped"] == (row["reward"] == 0)
        if row["arm"] == "vs_tail":
            candidates = parse_candidates(json.dumps(row["vs_candidates"]))
            assert (
                min(candidates, key=lambda c: c["probability"])["message"]
                == row["new_user_message"]
            )
            assert prefix[-1]["content"] == row["new_user_message"]
            proposal = json.loads((ROOT / row["proposal_path"]).read_text())
            assert row["proposal_input_tokens"] == proposal["usage"]["prompt_tokens"]
            assert (
                row["proposal_output_tokens"] == proposal["usage"]["completion_tokens"]
            )
        if row["flipped"]:
            assert (BRANCH / "reading" / (row["branch_id"] + ".md")).exists()
    flips = sum(r["flipped"] for r in rows)
    assert len(list((BRANCH / "reading").glob("*.md"))) == flips + 1
    summaries = list(csv.DictReader((BRANCH / "summary.csv").open()))
    assert all(s["status"] == "complete" for s in summaries)
    assert not (BRANCH / "errors.json").exists()
    write_json(
        BRANCH / "audit.json",
        {
            "status": "passed",
            "iid_runs": len(data["simulations"]) + len(solo["simulations"]),
            "positions": len(manifest["positions"]),
            "continuations": len(rows),
            "reading_files": flips,
            "summaries": summaries,
        },
    )
    print(
        json.dumps(
            {"audit": "passed", "continuations": len(rows), "reading_files": flips}
        )
    )


if __name__ == "__main__":
    main()
