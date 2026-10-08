"""Exploratory v6: native partner-turn sampling and replicated continuations."""

import argparse
import ast
import collections
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import p4_diagnosis as p4

from tau2.data_model.tasks import Task
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.runner import build_text_orchestrator

OUT = p4.ROOT / "pilot/runs/p4/v6_20261004"


def run_config(key=0, seed=0):
    """Reuse the measured Luna condition and recorded API routing."""
    cfg = p4.config()
    cfg.llm_args_agent = p4.llm_args(key)
    cfg.llm_args_user = p4.llm_args(key)
    cfg.llm_args_agent["seed"] = seed
    cfg.llm_args_user["seed"] = seed
    cfg.max_retries = 0
    return cfg


def build(task, prefix, seed=0, key=0, agent_model=None):
    """Restore a native task and prefix, including both databases."""
    cfg = run_config(key, seed)
    if agent_model:
        cfg.llm_agent = agent_model
    return build_text_orchestrator(cfg, p4.with_prefix(task, prefix), seed=seed)


def assertions(env, task):
    """Read each task assertion directly at the current runtime state."""
    return [
        {
            "assertion": a.model_dump(mode="json"),
            "met": env.run_env_assertion(a, raise_assertion_error=False),
        }
        for a in task.evaluation_criteria.env_assertions or []
    ]


def prepare(n_states, k, m):
    """Sample across saved mobile-data/MMS partner turns without a judge."""
    path = OUT / "protocol.json"
    if path.exists():
        return p4.read(path)
    iid, tasks, sources = p4.source_data()
    pool = []
    for sim in iid["simulations"]:
        if not sim["task_id"].startswith(("[mobile_data_issue]", "[mms_issue]")):
            continue
        for i, msg in enumerate(sim["messages"]):
            # Start at the beginning of a partner turn; retain all its tool calls.
            if (
                i > 0
                and msg["role"] == "user"
                and sim["messages"][i - 1]["role"] == "assistant"
                and not sim["messages"][i - 1].get("tool_calls")
            ):
                pool.append(
                    {"source_id": sim["id"], "task_id": sim["task_id"], "index": i}
                )
    selected = random.Random(2026100406).sample(pool, n_states)
    for number, case in enumerate(selected):
        case["state_id"] = f"s{number:03d}"
        p4.save(
            OUT / "sources" / (case["source_id"] + ".json"), sources[case["source_id"]]
        )
    p4.save(OUT / "tasks.json", {c["task_id"]: tasks[c["task_id"]] for c in selected})
    protocol = {
        "version": "v6 exploratory pilot",
        "created_at": time.time(),
        "source": "pilot/runs/iid/default/results.json",
        "source_sha256": p4.digest(iid),
        "sampling": "Uniform eligible partner-turn starts across saved mobile_data/MMS trajectories; no judge or outcome selection",
        "eligible_states": len(pool),
        "states": selected,
        "k": k,
        "m": m,
        "agent": "openai/gpt-5.6-luna",
        "partner": "openai/gpt-5.6-luna",
        "temperature": 1.0,
        "reasoning_effort": "none",
        "purpose": "Exploration; no significance/early-stop gate and no human adjudication prerequisite",
        "typicality": "Only actual provider logprobs count; verbalized probabilities are not q logprob",
        "local_outcome": "Every task assertion recorded at prefix, partner-turn end and continuation end; no inferred subtask relevance",
        "continuation_limit": "Native 200 new steps, consistent with existing branch tooling",
    }
    p4.save(path, protocol)
    return protocol


def preflight(protocol):
    """Measure replay equivalence, local assertions, and user-tool semantics."""
    tasks = p4.read(OUT / "tasks.json")
    cases = protocol["states"]
    checks = []
    for case in cases[:5]:
        source = p4.read(OUT / "sources" / (case["source_id"] + ".json"))
        task = Task.model_validate(tasks[case["task_id"]])
        prefix = source["messages"][: case["index"]]
        started = time.monotonic()
        orch = build(task, prefix)
        orch.initialize()
        state_before = p4.state(orch.environment)
        # Replay independently, then execute the original partner tool calls live.
        end = case["index"]
        while (
            end < len(source["messages"])
            and source["messages"][end]["role"] != "assistant"
        ):
            end += 1
        for msg in source["messages"][case["index"] : end]:
            for call in msg.get("tool_calls") or []:
                orch.environment.get_response(
                    p4.MESSAGE_LIST.validate_python([msg])[0].tool_calls[
                        (msg["tool_calls"]).index(call)
                    ]
                )
                orch.environment.sync_tools()
        restored = build(task, source["messages"][:end])
        restored.initialize()
        checks.append(
            {
                **case,
                "prefix_hash": p4.digest(state_before),
                "partner_block_replay_matches_live_tools": p4.state(orch.environment)
                == p4.state(restored.environment),
                "next_role": str(restored.to_role),
                "local_assertions": assertions(restored.environment, task),
                "restore_and_check_seconds": time.monotonic() - started,
            }
        )
    task = Task.model_validate(tasks[cases[0]["task_id"]])
    orch = build(task, [])
    tree = ast.parse((p4.ROOT / "src/tau2/domains/telecom/user_tools.py").read_text())
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    inventory = []
    for tool in orch.user.tools:
        node = functions[tool.name]
        helpers = {tool.name}
        pending = [tool.name]
        while pending:
            name = pending.pop()
            for call in ast.walk(functions[name]):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "self"
                    and call.func.attr in functions
                    and call.func.attr not in helpers
                ):
                    helpers.add(call.func.attr)
                    pending.append(call.func.attr)
        writes = [
            ast.unparse(n)
            for name in sorted(helpers)
            for n in ast.walk(functions[name])
            if isinstance(n, (ast.Assign, ast.AugAssign))
            and any(
                isinstance(t, ast.Attribute)
                for t in ([n.target] if isinstance(n, ast.AugAssign) else n.targets)
            )
        ]
        inventory.append(
            {
                "name": tool.name,
                "description": tool.openai_schema["function"]["description"],
                "type": ast.unparse(node.decorator_list[0]).split(".")[-1].rstrip(")"),
                "operation": "toggle"
                if tool.name.startswith("toggle_")
                else "set"
                if tool.name.startswith("set_")
                else "other",
                "state_assignments_including_helpers": writes,
                "helper_functions": sorted(helpers - {tool.name}),
            }
        )
    result = {
        "replay_checks": checks,
        "user_tools": inventory,
        "tool_count": len(inventory),
    }
    p4.save(OUT / "preflight.json", result)
    print("preflight", len(checks), "replay checks; tools", len(inventory), flush=True)
    return result


def sample_reply(case, j, key):
    """Sample one complete native partner turn, with its tool results."""
    unit = f"{case['state_id']}:d{j}"
    path = OUT / "replies" / (unit + ".json")
    if path.exists():
        return p4.read(path)
    p4.UNIT.set(unit)
    p4.KEY.set(key)
    task = Task.model_validate(p4.read(OUT / "tasks.json")[case["task_id"]])
    source = p4.read(OUT / "sources" / (case["source_id"] + ".json"))
    prefix = source["messages"][: case["index"]]
    orch = build(task, prefix, p4.stable_seed(unit), key)
    orch.initialize()
    before = assertions(orch.environment, task)
    orch.step()
    while not orch.done and orch.to_role.value != "agent":
        orch.step()
        orch._check_termination()
    messages = [m.model_dump(mode="json") for m in orch.get_messages()]
    block = messages[len(prefix) :]
    reply = {
        "unit": unit,
        "state_id": case["state_id"],
        "j": j,
        "prefix": messages,
        "partner_block": block,
        "assertions_before": before,
        "assertions_after_partner": assertions(orch.environment, task),
        "state_after_partner": p4.state(orch.environment),
        "generation_usage": p4.token_totals(block),
        "logprobs": [
            m.get("raw_data", {}).get("choices", [{}])[0].get("logprobs")
            for m in block
            if m["role"] == "user"
        ],
    }
    p4.save(path, reply)
    return reply


def continuation(case, reply, rep, key, agent_model=None):
    """Hold a sampled partner turn fixed and independently rerun its suffix."""
    unit = f"{reply['unit']}:r{rep}"
    path = OUT / "continuations" / (unit + ".json")
    if path.exists():
        return p4.read(path)
    p4.UNIT.set(unit)
    p4.KEY.set(key)
    task = Task.model_validate(p4.read(OUT / "tasks.json")[case["task_id"]])
    orch = build(task, reply["prefix"], p4.stable_seed(unit), key, agent_model)
    started = time.monotonic()
    sim = orch.run()
    sim.reward_info = evaluate_simulation(
        sim, task, EvaluationType.ALL, False, "telecom"
    )
    data = sim.model_dump(mode="json")
    p4.save(OUT / "trajectories" / (unit + ".json"), data)
    row = {
        "unit": unit,
        "state_id": case["state_id"],
        "task_id": task.id,
        "j": reply["j"],
        "rep": rep,
        "reward": sim.reward_info.reward,
        "agent_model": orch.agent.llm,
        "termination_reason": data["termination_reason"],
        "assertions_final": assertions(orch.environment, task),
        "usage": p4.token_totals(data["messages"][len(reply["prefix"]) :]),
        "seconds": time.monotonic() - started,
    }
    p4.save(path, row)
    print(unit, "reward", row["reward"], flush=True)
    return row


def state_job(case, protocol, number):
    """Run each state's reply groups with durable per-reply/per-suffix outputs."""
    key = number % 4
    for j in range(protocol["k"]):
        reply = sample_reply(case, j, key)
        for rep in range(protocol["m"]):
            continuation(case, reply, rep, key)


def sensitivity(groups):
    """Separate between-reply variance from stochastic continuation variance."""
    means = [statistics.mean(g) for g in groups]
    m = len(groups[0])
    return statistics.variance(means) - statistics.mean(
        x * (1 - x) / (m - 1) for x in means
    )


def partner_signature(block):
    """Identify identical partner behavior independently of call IDs and usage."""
    return p4.digest(
        [
            {
                "role": msg["role"],
                "content": msg.get("content"),
                "requestor": msg.get("requestor"),
                "tool_calls": [
                    {"name": t["name"], "arguments": t["arguments"]}
                    for t in msg.get("tool_calls") or []
                ],
            }
            for msg in block
        ]
    )


def report(protocol):
    """Summarize exploratory sensitivity and actual provider token usage."""
    rows = [p4.read(p) for p in (OUT / "continuations").glob("*.json")]
    estimates = []
    bank = []
    for case in protocol["states"]:
        selected = [r for r in rows if r["state_id"] == case["state_id"]]
        if len(selected) != protocol["k"] * protocol["m"]:
            continue
        groups = [
            [r["reward"] == 1 for r in selected if r["j"] == j]
            for j in range(protocol["k"])
        ]
        replies = [
            p4.read(OUT / "replies" / f"{case['state_id']}:d{j}.json")
            for j in range(protocol["k"])
        ]
        signatures = [partner_signature(reply["partner_block"]) for reply in replies]
        local = []
        for a in range(len(selected[0]["assertions_final"])):
            gs = [
                [r["assertions_final"][a]["met"] for r in selected if r["j"] == j]
                for j in range(protocol["k"])
            ]
            local.append(
                {
                    "assertion": selected[0]["assertions_final"][a]["assertion"],
                    "S_hat": sensitivity(gs),
                }
            )
        estimates.append(
            {
                **case,
                "V_hat": statistics.mean([r["reward"] == 1 for r in selected]),
                "S_hat": sensitivity(groups),
                "reply_success_rates": [statistics.mean(g) for g in groups],
                "unique_partner_blocks": len(set(signatures)),
                "local_sensitivity": local,
            }
        )
        baseline = statistics.mean([r["reward"] == 1 for r in selected])
        for signature in set(signatures):
            indices = [j for j, s in enumerate(signatures) if s == signature]
            j = indices[0]
            pooled = [value for idx in indices for value in groups[idx]]
            delta = statistics.mean(pooled) - baseline
            if abs(delta) < 0.2:
                continue
            reply = replies[j]
            bank.append(
                {
                    **case,
                    "j": j,
                    "partner_block": reply["partner_block"],
                    "prefix_path": str(
                        OUT / "replies" / f"{case['state_id']}:d{j}.json"
                    ),
                    "V_hat": baseline,
                    "V_d_hat": statistics.mean(pooled),
                    "replications_for_identical_behavior": len(pooled),
                    "delta_hat": delta,
                    "status": "exploratory_candidate",
                    "validation": "Requires independent repeats; selection uses the same noisy pilot data",
                }
            )
    usage = collections.Counter()
    errors = 0
    for path in (OUT / "requests").glob("*.json"):
        request = p4.read(path)
        errors += request["status"] == "error"
        for kind in ("prompt_tokens", "completion_tokens"):
            usage[kind] += (request.get("usage") or {}).get(kind, 0)
    summary = {
        "states_completed": len(estimates),
        "continuations_completed": len(rows),
        "provider_usage": dict(usage),
        "request_errors": errors,
        "estimates": estimates,
        "interpretation": "Small exploratory batch; raw S estimates retained including negatives. No concentration or typicality claim from this batch.",
    }
    p4.save(OUT / "summary.json", summary)
    p4.save(OUT / "candidate_bank.json", bank)
    text = [
        "# Pivot-and-Probe v6 exploratory pilot",
        "",
        f"Completed {len(estimates)} states, {len(rows)} continuations.",
        "",
        "| State | V | S (final) | Distinct partner blocks | Reply success rates |",
        "|---|---:|---:|---:|---|",
    ]
    for e in estimates:
        text.append(
            f"| {e['state_id']} | {e['V_hat']:.3f} | {e['S_hat']:.4f} | {e['unique_partner_blocks']} | {e['reply_success_rates']} |"
        )
    text.extend(
        [
            "",
            f"Provider usage: {dict(usage)}; request errors: {errors}.",
            "",
            summary["interpretation"],
        ]
    )
    (OUT / "report.md").write_text("\n".join(text) + "\n")
    print({k: v for k, v in summary.items() if k != "estimates"}, flush=True)


def main():
    """Prepare, check replay and execute a small v6 pilot on existing data."""
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--key-file", type=Path, default=p4.ROOT / "api.txt")
    parser.add_argument("--states", type=int, default=12)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--m", type=int, default=2)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    OUT = args.out.resolve()
    p4.OUT = OUT
    protocol = prepare(args.states, args.k, args.m)
    if args.report_only:
        report(protocol)
        return
    preflight(protocol)
    if args.prepare_only:
        return
    p4.setup(args.key_file, args.workers)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [
            pool.submit(state_job, case, protocol, n)
            for n, case in enumerate(protocol["states"])
        ]
        for job in as_completed(jobs):
            job.result()
    report(protocol)


if __name__ == "__main__":
    main()
