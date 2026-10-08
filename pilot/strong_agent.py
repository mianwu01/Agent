"""Run one strong-agent continuation per flipped vs_tail row, reusing saved prefixes."""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from branch_common import (
    BRANCH,
    ROOT,
    config,
    continue_prefix,
    load_key,
    stable_seed,
    write_json,
)
from loguru import logger
from transport import configure_transport

from tau2.data_model.tasks import Task


def main():
    """Load existing branch artifacts; never repeat proposals or source selection."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("branches", type=Path)
    p.add_argument("model")
    p.add_argument("--key-file", type=Path, default=ROOT.parent / "Memory/key/key.txt")
    p.add_argument("--api-base", default="https://www.autodl.art/api/v1")
    p.add_argument("--key-env", default="PILOT_AUTODL_API_KEY")
    p.add_argument("--concurrency", type=int, default=3)
    a = p.parse_args()
    load_key(a.key_file)
    configure_transport(a.concurrency)
    logger.remove()
    logger.add("pilot/strong-runtime.log", level="WARNING")
    rows = [
        json.loads(line) for line in a.branches.read_text().splitlines() if line.strip()
    ]
    rows = [r for r in rows if r["arm"] == "vs_tail" and r["flipped"] is True]
    assert len({r["branch_id"] for r in rows}) == len(rows)
    data = json.loads((ROOT / "pilot/runs/iid/default/results.json").read_text())
    tasks = {t["id"]: Task.model_validate(t) for t in data["tasks"]}
    cfg = config(a.model, a.api_base, a.key_env)
    output = BRANCH / "strong_agent.jsonl"
    existing = (
        [json.loads(s) for s in output.read_text().splitlines()]
        if output.exists()
        else []
    )
    completed = {(r["branch_id"], r["model"]): r for r in existing}
    directory = BRANCH / "strong" / hashlib.sha256(a.model.encode()).hexdigest()[:12]
    settings = directory / "config.json"
    if settings.exists():
        assert json.loads(settings.read_text()) == cfg.model_dump(mode="json"), (
            "Changed strong run settings"
        )
    write_json(settings, cfg.model_dump(mode="json"))

    def run(row):
        key = (row["branch_id"], a.model)
        if key in completed:
            return completed[key]
        rp = directory / "rows" / f"{row['branch_id']}.json"
        if rp.exists():
            return json.loads(rp.read_text())
        prefix = json.loads((ROOT / row["prefix_path"]).read_text())
        seed = stable_seed(row["branch_id"] + ":strong:" + a.model)
        sim, tok = continue_prefix(
            tasks[row["task_id"]], prefix, seed, row["branch_id"] + ":strong", cfg
        )
        tp = directory / "trajectories" / f"{row['branch_id']}.json"
        write_json(tp, sim)
        result = {
            "branch_id": row["branch_id"],
            "model": a.model,
            "reward": sim["reward_info"]["reward"],
            "termination_reason": sim["termination_reason"],
            "tokens": tok,
            "trajectory_path": str(tp.relative_to(ROOT)),
            "seed": seed,
            "prefix_path": row["prefix_path"],
        }
        write_json(rp, result)
        return result

    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        output.write_text("")
    errors = []
    with ThreadPoolExecutor(a.concurrency) as pool:
        fs = {pool.submit(run, r): r for r in rows}
        for f in as_completed(fs):
            try:
                result = f.result()
                completed[(result["branch_id"], result["model"])] = result
            except Exception as e:
                errors.append(
                    {
                        "branch_id": fs[f]["branch_id"],
                        "error_type": type(e).__name__,
                        "error": str(e),
                    }
                )
                write_json(directory / "errors.json", errors)
            output.parent.mkdir(parents=True, exist_ok=True)
            tmp = output.with_suffix(".tmp")
            tmp.write_text(
                "".join(json.dumps(v) + "\n" for _, v in sorted(completed.items()))
            )
            tmp.replace(output)
    if errors:
        raise RuntimeError(
            "Strong continuations failed; see saved errors; no rows dropped"
        )


if __name__ == "__main__":
    main()
