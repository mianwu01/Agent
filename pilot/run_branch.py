"""Select successful B1 sources, propose user alternatives, and run paired arms."""

import argparse
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from branch_common import (
    BRANCH,
    MESSAGE_LIST,
    ROOT,
    config,
    continue_prefix,
    file_id,
    load_key,
    stable_seed,
    write_json,
)
from loguru import logger
from transport import configure_transport

from tau2.data_model.message import SystemMessage, UserMessage
from tau2.data_model.tasks import Task
from tau2.runner import build_text_orchestrator
from tau2.user.user_simulator import UserSimulator
from tau2.user.user_simulator_base import is_valid_user_history_message
from tau2.utils.llm_utils import generate

INSTRUCTION = 'Instead of writing one reply, list 5 different messages you might plausibly send next as this customer, each with the probability that you would send it. Every candidate must follow your scenario instructions. Output only JSON: [{"message": "...", "probability": 0.xx}, ...]'
SELECTION_SEED = 20260928


def select(data):
    """Uniformly sample sources then eligible positions in deterministic order."""
    rng = random.Random(SELECTION_SEED)
    selected = []
    selected_sources = []
    without_success = []
    for task in sorted(data["tasks"], key=lambda t: t["id"]):
        sources = sorted(
            [
                s
                for s in data["simulations"]
                if s["task_id"] == task["id"] and s["reward_info"]["reward"] == 1
            ],
            key=lambda s: (s["trial"], s["id"]),
        )
        if not sources:
            without_success.append(task["id"])
        for source in rng.sample(sources, min(2, len(sources))):
            eligible = [
                i
                for i, m in enumerate(MESSAGE_LIST.validate_python(source["messages"]))
                if isinstance(m, UserMessage)
                and bool(m.content)
                and not m.tool_calls
                and not UserSimulator.is_stop(m)
            ]
            positions = rng.sample(eligible, min(2, len(eligible)))
            selected_sources.append(
                {
                    "task_id": task["id"],
                    "source_sim_id": source["id"],
                    "eligible_positions": eligible,
                    "selected_positions": positions,
                }
            )
            for i in positions:
                selected.append(
                    {
                        "task_id": task["id"],
                        "source_sim_id": source["id"],
                        "i": i,
                        "eligible_positions": eligible,
                    }
                )
    return {
        "seed": SELECTION_SEED,
        "source_order": "tasks sorted by id; successful sources sorted by (trial,id)",
        "positions": selected,
        "selected_sources": selected_sources,
        "tasks_without_success": without_success,
    }


def proposal_messages(user, prefix):
    """Use precisely the native user-visible history, then append the instruction."""
    messages = MESSAGE_LIST.validate_python(prefix)
    state = user.get_init_state(
        [m for m in messages if is_valid_user_history_message(m)]
    )
    history = state.system_messages + state.flip_roles()
    return history + [SystemMessage(role="system", content=INSTRUCTION)]


def parse_candidates(text):
    """Require five distinct nonempty messages and finite probabilities in [0,1]."""
    candidates = json.loads(text)
    if not isinstance(candidates, list) or len(candidates) != 5:
        raise ValueError("Expected exactly 5 candidates")
    for c in candidates:
        if (
            set(c) != {"message", "probability"}
            or not isinstance(c["message"], str)
            or not c["message"].strip()
        ):
            raise ValueError("Invalid candidate")
        p = c["probability"]
        if (
            isinstance(p, bool)
            or not isinstance(p, (int, float))
            or not math.isfinite(p)
            or not 0 <= p <= 1
        ):
            raise ValueError("Invalid probability")
    if len({c["message"] for c in candidates}) != 5:
        raise ValueError("Candidates are not distinct")
    return candidates


def propose(task, source, i, replace_invalid_once=False):
    """Make one user-only proposal call per selected source position, cached durably."""
    name = f"{source['id']}:{i}"
    path = BRANCH / "proposals" / f"{name}.json"
    original_path = path.parent / "original_invalid" / path.name
    if path.exists():
        saved = json.loads(path.read_text())
        if "candidates" in saved:
            return saved
        if not replace_invalid_once or original_path.exists():
            raise ValueError(f"Prior invalid proposal must be inspected: {path}")
        if "response" not in saved:
            raise ValueError(f"Proposal request has no saved response: {path}")
        original_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(original_path, saved)
    elif original_path.exists():
        raise ValueError(f"Replacement state missing; inspect {original_path}")
    attempt = ":replacement" if original_path.exists() else ""
    orch = build_text_orchestrator(
        config(), task, seed=stable_seed(name + ":proposal" + attempt)
    )
    # The builder creates the user from scenario+persona, never evaluation criteria.
    user = orch.user
    history = proposal_messages(user, source["messages"][:i])
    args = dict(user.llm_args)
    args["seed"] = stable_seed(name + ":proposal" + attempt)
    request = {
        "model": user.llm,
        "args": args,
        "messages": [m.model_dump(mode="json") for m in history],
        "tools": [t.openai_schema for t in user.tools or []],
        "tool_choice": "none",
    }
    write_json(path, {"request": request, "status": "request_started"})
    response = generate(
        model=user.llm, messages=history, tools=user.tools, tool_choice="none", **args
    )
    saved = {"request": request, "response": response.model_dump(mode="json")}
    write_json(path, saved)  # Preserve malformed output; never silently call again.
    candidates = parse_candidates(response.content)
    if response.usage is None:
        raise ValueError("Missing proposal usage")
    usage = dict(response.usage)
    if original_path.exists():
        original = json.loads(original_path.read_text())
        prior_usage = original["response"].get("usage")
        if prior_usage is None:
            raise ValueError("Missing original proposal usage")
        for key in ("prompt_tokens", "completion_tokens"):
            usage[key] += prior_usage[key]
        saved["original_invalid_path"] = str(original_path.relative_to(ROOT))
        saved["proposal_calls"] = 2
    saved.update(
        candidates=candidates,
        chosen=min(candidates, key=lambda c: c["probability"]),
        usage=usage,
    )
    write_json(path, saved)
    return saved


def run_position(selection, task, source, replace_invalid_once=False):
    """Run both arms and two independent seeded continuations per arm."""
    i = selection["i"]
    for arm in ["resample", "vs_tail"]:
        proposal = (
            propose(task, source, i, replace_invalid_once) if arm == "vs_tail" else None
        )
        for rep in range(2):
            bid = f"{source['id']}:{i}:{arm}:{rep}"
            row_path = BRANCH / "rows" / f"{file_id(bid)}.json"
            if row_path.exists():
                continue
            prefix = source["messages"][:i]
            if arm == "vs_tail":
                prefix = prefix + [
                    UserMessage(
                        role="user", content=proposal["chosen"]["message"]
                    ).model_dump(mode="json")
                ]
            pp = BRANCH / "prefixes" / f"{file_id(bid)}.json"
            write_json(pp, prefix)
            seed = stable_seed(bid)
            sim, tok = continue_prefix(task, prefix, seed, bid)
            tp = BRANCH / "trajectories" / f"{file_id(bid)}.json"
            write_json(tp, sim)
            suffix = sim["messages"][len(prefix) :]
            new = (
                proposal["chosen"]["message"]
                if arm == "vs_tail"
                else next(
                    (
                        m["content"]
                        for m in suffix
                        if m["role"] == "user"
                        and m.get("content")
                        and not m.get("tool_calls")
                    ),
                    None,
                )
            )
            row = {
                "branch_id": bid,
                "task_id": task.id,
                "source_sim_id": source["id"],
                "i": i,
                "n_messages_source": len(source["messages"]),
                "arm": arm,
                "rep": rep,
                "seed_or_rep": seed,
                "seed_status": "sent; accepted by endpoint, determinism unverified",
                "prefix_path": str(pp.relative_to(ROOT)),
                "original_user_message": source["messages"][i]["content"],
                "new_user_message": new,
                "reward": sim["reward_info"]["reward"],
                "flipped": sim["reward_info"]["reward"] == 0,
                "termination_reason": sim["termination_reason"],
                "cont_input_tokens": tok["input"],
                "cont_output_tokens": tok["output"],
                "trajectory_path": str(tp.relative_to(ROOT)),
            }
            if arm == "vs_tail":
                row.update(
                    vs_candidates=proposal["candidates"],
                    proposal_path=str(
                        (BRANCH / "proposals" / f"{source['id']}:{i}.json").relative_to(
                            ROOT
                        )
                    ),
                    proposal_input_tokens=proposal["usage"]["prompt_tokens"],
                    proposal_output_tokens=proposal["usage"]["completion_tokens"],
                )
            write_json(row_path, row)
    return selection


def collect_rows():
    """Regenerate JSONL from durable per-continuation rows, including partial progress."""
    rows = [json.loads(p.read_text()) for p in sorted((BRANCH / "rows").glob("*.json"))]
    path = BRANCH / "branches.jsonl"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(path)
    return rows


def main():
    """Run all selected positions and retain successes if another position errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--replace-invalid-once", action="store_true")
    args = parser.parse_args()
    load_key(args.key_file)
    configure_transport(args.concurrency)
    logger.remove()
    logger.add("pilot/branch-runtime.log", level="WARNING")
    data = json.loads((ROOT / "pilot/runs/iid/default/results.json").read_text())
    tasks = {t["id"]: Task.model_validate(t) for t in data["tasks"]}
    sources = {s["id"]: s for s in data["simulations"]}
    manifest = select(data)
    planned_ids = [
        f"{position['source_sim_id']}:{position['i']}:{arm}:{rep}"
        for position in manifest["positions"]
        for arm in ("resample", "vs_tail")
        for rep in range(2)
    ]
    assert len({stable_seed(bid) for bid in planned_ids}) == len(planned_ids), (
        "Continuation seed collision; do not launch with duplicate seeds"
    )
    path = BRANCH / "selection.json"
    if path.exists():
        assert json.loads(path.read_text()) == manifest, "Source selection changed"
    write_json(path, manifest)
    write_json(BRANCH / "config.json", config().model_dump(mode="json"))
    old_errors = BRANCH / "errors.json"
    if old_errors.exists():
        history = BRANCH / "error_history" / f"{time.time_ns()}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        old_errors.rename(history)
    errors = []
    with ThreadPoolExecutor(args.concurrency) as pool:
        pending = {
            pool.submit(
                run_position,
                s,
                tasks[s["task_id"]],
                sources[s["source_sim_id"]],
                args.replace_invalid_once,
            ): s
            for s in manifest["positions"]
        }
        for future in as_completed(pending):
            try:
                future.result()
            except Exception as e:
                errors.append(
                    {
                        "selection": pending[future],
                        "error_type": type(e).__name__,
                        "error": str(e),
                    }
                )
                write_json(BRANCH / "errors.json", errors)
            rows = collect_rows()
            print(
                "saved",
                len(rows),
                "/",
                len(manifest["positions"]) * 4,
                "errors",
                len(errors),
                flush=True,
            )
    if errors:
        raise RuntimeError(
            f"{len(errors)} failed positions; see errors.json; no runs discarded"
        )
    assert len(collect_rows()) == len(manifest["positions"]) * 4


if __name__ == "__main__":
    main()
