"""Measure native and broadened faithful partner sensitivity at mixed-task states."""

import argparse
import collections
import json
import math
import random
import statistics
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import p4_v6 as v6
from run_branch import proposal_messages

from tau2.data_model.message import SystemMessage, ToolCall, UserMessage
from tau2.data_model.tasks import Task

OUT = v6.OUT.parent / "v6_paired_20261004"
FIDELITY_PROMPT = """Check whether this complete partner turn is plausible and faithful to the supplied customer scenario, simulator guidelines, visible history and private state. The block includes native tool results where applicable. Allow incomplete reports, reasonable uncertainty, requests for clarification and different cooperation styles. Reject invented facts/actions, explicit false device reports, unauthorized tools, or contradictions of the customer's goal. Distinguish observations known to the user from facts never checked. Return JSON {"faithful": true/false, "reason": "..."}."""
PROPOSAL_PROMPT = """Generate a batch of five behaviorally varied possibilities for this customer's next decision. Follow the customer scenario and simulator guidelines. Preserve the goal and all known facts. Explore plausible variations in specificity, uncertainty, requests for clarification, and willingness to follow an instruction. You may select available user tools when the preceding agent instruction permits them. Each candidate is the first user message of the turn: either a text message or tool calls; actual tool outputs will be obtained by the environment. Do not claim to have performed a new action in a text-only candidate. Return JSON {"candidates": [{"message": "text or null", "tool_calls": [{"name": "available tool name", "arguments": {}}], "probability": 0.2}, ...]}. Use an empty tool_calls list for text-only candidates and null message for tool candidates. Probabilities are verbalized estimates only."""


def activate():
    """Reuse the existing native execution and redacted request ledger."""
    v6.OUT = OUT
    v6.p4.OUT = OUT


def prepare(n_states=40):
    """Balance mixed-outcome mobile-data/MMS tasks, then sample within each task."""
    path = OUT / "protocol.json"
    if path.exists():
        return v6.p4.read(path)
    iid, tasks, sources = v6.p4.source_data()
    by_task = collections.defaultdict(list)
    for sim in iid["simulations"]:
        by_task[sim["task_id"]].append(sim)
    rates = {
        tid: statistics.mean(s["reward_info"]["reward"] == 1 for s in sims)
        for tid, sims in by_task.items()
    }
    mixed = {tid: rate for tid, rate in rates.items() if 0.2 <= rate <= 0.8}
    focus = sorted(
        tid for tid in mixed if tid.startswith(("[mobile_data_issue]", "[mms_issue]"))
    )
    rng = random.Random(2026100410)
    pools = {}
    for tid in focus:
        pool = []
        for sim in sorted(by_task[tid], key=lambda s: s["id"]):
            for i, msg in enumerate(sim["messages"]):
                if (
                    i > 0
                    and msg["role"] == "user"
                    and sim["messages"][i - 1]["role"] == "assistant"
                    and not sim["messages"][i - 1].get("tool_calls")
                ):
                    pool.append({"source_id": sim["id"], "task_id": tid, "index": i})
        pools[tid] = pool
    per_task = collections.Counter(focus[i % len(focus)] for i in range(n_states))
    cases = []
    for tid, count in per_task.items():
        for case in rng.sample(pools[tid], count):
            case.update(
                state_id=f"s{len(cases):03d}",
                task_iid_success_rate=rates[tid],
                eligible_states_in_task=len(pools[tid]),
            )
            cases.append(case)
            v6.p4.save(
                OUT / "sources" / (case["source_id"] + ".json"),
                sources[case["source_id"]],
            )
    v6.p4.save(OUT / "tasks.json", {tid: tasks[tid] for tid in per_task})
    selection = {
        "source_simulations": len(iid["simulations"]),
        "total_tasks": len(tasks),
        "mixed_tasks_all_domains_of_telecom": mixed,
        "mixed_focus_tasks": {tid: rates[tid] for tid in focus},
        "task_counts": dict(per_task),
        "eligible_states_per_task": {tid: len(pools[tid]) for tid in focus},
    }
    v6.p4.save(OUT / "state_pool.json", selection)
    protocol = {
        "version": "v6.1 paired sensitivity",
        "created_at": time.time(),
        "source": "pilot/runs/iid/default/results.json",
        "source_sha256": v6.p4.digest(iid),
        "states": cases,
        "k": 6,
        "m": 4,
        "sol_m": 4,
        "agent": "openai/gpt-5.6-luna",
        "partner": "openai/gpt-5.6-luna",
        "reference_agent": "openai/gpt-5.6-sol",
        "temperature": 1.0,
        "reasoning_effort": "none",
        "sampling": "Task-balanced uniform prefix sample, conditional on pre-existing task success rate in [0.2,0.8]; no state-level filtering or judge",
        "q_prime": "Six independent VS batches of five; uniformly draw one candidate from each, execute its complete native partner turn, accept only after Sol fidelity check. Regenerate independent batch on rejection. No outcome feedback or probability weighting.",
        "proposal_prompt": PROPOSAL_PROMPT,
        "fidelity_prompt": FIDELITY_PROMPT,
        "crossfit": "Reply draws 0,1,2 vs 3,4,5; all four suffixes retained within each draw; independent sampling seeds for both groups",
        "open_strata": "Report q-unresolved, q-prime-unresolved, and union with Sol-recoverable separately; unresolved uses estimated V in [0.1,0.9]. Estimated floor/ceiling is descriptive, not proof of impossibility.",
        "sol_check": "Four suffixes on one block with the lowest measured Luna success across q and q_prime (ties in q then q_prime draw order). Diagnostic selection, not independent certification.",
        "primary_concentration": "Cross-fitted S_q_prime, all sampled states and open union separately; report raw noisy ratios/denominator and rank/evaluation groups",
        "typicality": "S_q_prime minus S_q is proposal-family sensitivity contrast, not a logprob correlation. Also report mean success shift, which can reveal distribution effects even if both variances are zero.",
        "planned_paired_continuations": len(cases) * 48,
        "planned_sol_continuations": len(cases) * 4,
        "continuation_limit": "Native 200 new steps, as in the first v6 batch",
    }
    v6.p4.save(path, protocol)
    print("prepared", len(cases), "states from", len(per_task), "tasks", flush=True)
    return protocol


def complete_partner(orch):
    """Execute one native user turn, including its tools, until user text/stop."""
    orch.step()
    while not orch.done and orch.to_role.value != "agent":
        orch.step()
        orch._check_termination()


def first_response(user, candidate, unit):
    """Force one proposed decision while preserving the native user history update."""
    original = user._generate_next_message
    used = False

    def generate(self, message, state):
        nonlocal used
        if used:
            return original(message, state)
        used = True
        state.messages.append(message)
        calls = [
            ToolCall(
                id=f"{v6.p4.stable_seed(unit)}_{i}",
                name=c["name"],
                arguments=c["arguments"],
                requestor="user",
            )
            # null tool_calls == none, matching b1.tool_candidate_errors validation.
            for i, c in enumerate(candidate.get("tool_calls") or [])
        ]
        return UserMessage(
            role="user", content=candidate["message"], tool_calls=calls or None
        )

    user._generate_next_message = types.MethodType(generate, user)


def sample(case, arm, j, key):
    """Sample a native or broadened faithful full partner turn independently."""
    unit = f"{case['state_id']}:{arm}:d{j}"
    path = OUT / "replies" / (unit + ".json")
    if path.exists():
        return v6.p4.read(path)
    task = Task.model_validate(v6.p4.read(OUT / "tasks.json")[case["task_id"]])
    source = v6.p4.read(OUT / "sources" / (case["source_id"] + ".json"))
    prefix = source["messages"][: case["index"]]
    transferred = (
        "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
        in (prefix[-1].get("content") or "").upper()
    )
    proposal_prompt = PROPOSAL_PROMPT
    if transferred:
        proposal_prompt += (
            " The preceding agent explicitly announced a transfer. The native "
            "simulation guidelines require ###TRANSFER### in the user reply. "
            "Every candidate must include that terminal token, use no tools, "
            "and must not resume troubleshooting."
        )
    attempt = 0
    while True:
        attempt_unit = unit + f":attempt{attempt}"
        v6.p4.UNIT.set(attempt_unit)
        v6.p4.KEY.set(key)
        seed = v6.p4.stable_seed(attempt_unit)
        orch = v6.build(task, prefix, seed, key)
        orch.initialize()
        before_state = v6.p4.state(orch.environment)
        before_assertions = v6.assertions(orch.environment, task)
        candidate = None
        if arm == "q_prime":
            proposal_path = OUT / "proposals" / (attempt_unit + ".json")
            if proposal_path.exists():
                proposal = v6.p4.read(proposal_path)
            else:
                v6.p4.ROLE.set("q_prime_proposal")
                history = proposal_messages(orch.user, prefix)
                history.pop()  # Replace the old VS instruction, preserving native history.
                visible_history = v6.p4.llm_utils.to_litellm_messages(history[1:])
                history = [
                    SystemMessage(
                        role="system",
                        content=history[0].content
                        + "\n\n"
                        + proposal_prompt
                        + " Return valid json.",
                    ),
                    UserMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "output_format": "json",
                                "native_user_visible_history": visible_history,
                                "available_user_tool_schemas": [
                                    tool.openai_schema for tool in orch.user.tools
                                ],
                                "generation_instruction": proposal_prompt
                                + " Return only valid json.",
                            }
                        ),
                    ),
                ]
                args = v6.p4.llm_args(key)
                args["seed"] = seed
                response = v6.p4.llm_utils.generate(
                    model=orch.user.llm,
                    messages=history,
                    tools=None,
                    response_format={"type": "json_object"},
                    max_completion_tokens=3072,
                    **args,
                )
                proposal = {
                    "response": response.model_dump(mode="json"),
                    "batch": json.loads(response.content)["candidates"],
                }
                index = random.Random(
                    v6.p4.stable_seed(attempt_unit + ":draw")
                ).randrange(len(proposal["batch"]))
                proposal.update(selected_index=index, selected=proposal["batch"][index])
                v6.p4.save(proposal_path, proposal)
            candidate = proposal["selected"]
            first_response(orch.user, candidate, attempt_unit)
        complete_partner(orch)
        messages = [m.model_dump(mode="json") for m in orch.get_messages()]
        block = messages[len(prefix) :]
        fidelity = None
        if arm in ["q", "q_prime"]:
            fidelity_path = OUT / "fidelity" / (attempt_unit + ".json")
            if fidelity_path.exists():
                fidelity = v6.p4.read(fidelity_path)
            else:
                fidelity = v6.p4.json_response(
                    FIDELITY_PROMPT,
                    {
                        "scenario": orch.user.system_prompt,
                        "user_visible_history": [
                            m.model_dump(mode="json")
                            for m in proposal_messages(orch.user, prefix)[:-1]
                        ],
                        "private_state_before": before_state["user"],
                        "private_state_after": v6.p4.state(orch.environment)["user"],
                        "partner_block": [
                            {
                                k: m.get(k)
                                for k in ["role", "content", "tool_calls", "requestor"]
                            }
                            for m in block
                        ],
                    },
                    "gpt-5.6-sol",
                    attempt_unit + ":fidelity",
                    key,
                )
                v6.p4.save(fidelity_path, fidelity)
        if transferred and (
            not any(
                "###TRANSFER###" in (message.get("content") or "")
                for message in block
                if message["role"] == "user"
            )
            or any(message.get("tool_calls") for message in block)
        ):
            fidelity = {
                **fidelity,
                "faithful": False,
                "reason": "Explicit transfer requires the native terminal token without further tool actions",
            }
        reply = {
            "unit": unit,
            "state_id": case["state_id"],
            "arm": arm,
            "j": j,
            "prefix": messages,
            "partner_block": block,
            "assertions_before": before_assertions,
            "assertions_after_partner": v6.assertions(orch.environment, task),
            "state_after_partner": v6.p4.state(orch.environment),
            "attempt": attempt,
            "candidate": candidate,
            "fidelity": fidelity,
            "partner_signature": v6.partner_signature(block),
            "generation_usage": v6.p4.token_totals(block),
            "proposal_version": "json_history_payload" if arm == "q_prime" else None,
            "transfer_terminal_required": transferred,
        }
        if arm == "q" or fidelity["faithful"]:
            v6.p4.save(path, reply)
            return reply
        v6.p4.save(OUT / "rejected_replies" / (attempt_unit + ".json"), reply)
        attempt += 1


def state_job(case, protocol, number):
    """Measure both independent reply groups and a same-state Sol diagnostic."""
    key = number % 4
    choices = []
    for arm in ["q", "q_prime"]:
        for j in range(protocol["k"]):
            reply = sample(case, arm, j, key)
            rows = [
                v6.continuation(case, reply, rep, key) for rep in range(protocol["m"])
            ]
            choices.append((statistics.mean(r["reward"] == 1 for r in rows), reply))
    chosen = min(choices, key=lambda p: p[0])[1]
    diagnostic = {**chosen, "unit": f"{case['state_id']}:sol:d{chosen['j']}"}
    v6.p4.save(
        OUT / "sol_selection" / (case["state_id"] + ".json"),
        {
            "source_unit": chosen["unit"],
            "luna_success_rate": min(c[0] for c in choices),
            "reply": diagnostic,
        },
    )
    for rep in range(protocol["sol_m"]):
        v6.continuation(case, diagnostic, rep, key, protocol["reference_agent"])
    return case["state_id"]


def arm_statistics(case, rows, arm, protocol):
    """Compute replicated variance and independent reply-half estimates."""
    selected = [r for r in rows if r["unit"].split(":")[1] == arm]
    groups = [
        [r["reward"] == 1 for r in selected if r["j"] == j]
        for j in range(protocol["k"])
    ]
    replies = [
        v6.p4.read(OUT / "replies" / f"{case['state_id']}:{arm}:d{j}.json")
        for j in range(protocol["k"])
    ]
    local = []
    for a in range(len(selected[0]["assertions_final"])):
        gs = [
            [r["assertions_final"][a]["met"] for r in selected if r["j"] == j]
            for j in range(protocol["k"])
        ]
        local.append(
            {
                "assertion": selected[0]["assertions_final"][a]["assertion"],
                "S_hat": v6.sensitivity(gs),
                "V_hat": statistics.mean(y for g in gs for y in g),
            }
        )
    return {
        "V_hat": statistics.mean(y for g in groups for y in g),
        "S_hat": v6.sensitivity(groups),
        "S_group_A": v6.sensitivity(groups[:3]),
        "S_group_B": v6.sensitivity(groups[3:]),
        "reply_success_rates": [statistics.mean(g) for g in groups],
        "unique_partner_blocks": len({r["partner_signature"] for r in replies}),
        "fidelity_rate": statistics.mean(r["fidelity"]["faithful"] for r in replies),
        "local_assertions": local,
    }


def concentration(states):
    """Rank with one independent reply half and sum with the other, then swap."""
    if not states:
        return {"states": 0, "folds": []}
    count = max(1, math.ceil(len(states) * 0.1))
    folds = []
    for rank, evaluate in [("S_group_A", "S_group_B"), ("S_group_B", "S_group_A")]:
        ordered = sorted(states, key=lambda s: s["q_prime"][rank], reverse=True)
        denominator = sum(s["q_prime"][evaluate] for s in states)
        numerator = sum(s["q_prime"][evaluate] for s in ordered[:count])
        folds.append(
            {
                "rank_half": rank,
                "evaluate_half": evaluate,
                "top_states": [s["state_id"] for s in ordered[:count]],
                "numerator": numerator,
                "denominator": denominator,
                "C10": numerator / denominator if denominator > 0 else None,
            }
        )
    return {
        "states": len(states),
        "top_count": count,
        "folds": folds,
        "note": "Raw noise-corrected estimates, including negatives. A ratio may fall outside [0,1]; nonpositive denominators have no meaningful concentration estimate.",
    }


def report(protocol, final=False):
    """Report paired sensitivities, sampled collapse, openness and directional candidates."""
    all_rows = [v6.p4.read(p) for p in (OUT / "continuations").glob("*.json")]
    states = []
    bank = []
    for case in protocol["states"]:
        rows = [r for r in all_rows if r["state_id"] == case["state_id"]]
        paired = [r for r in rows if r["unit"].split(":")[1] in ["q", "q_prime"]]
        if len(paired) != 2 * protocol["k"] * protocol["m"]:
            continue
        native = arm_statistics(case, rows, "q", protocol)
        broad = arm_statistics(case, rows, "q_prime", protocol)
        sol = [r for r in rows if r["unit"].split(":")[1] == "sol"]
        sol_rate = statistics.mean(r["reward"] == 1 for r in sol) if sol else None
        open_q = 0.1 <= native["V_hat"] <= 0.9
        open_prime = 0.1 <= broad["V_hat"] <= 0.9
        state = {
            **case,
            "q": native,
            "q_prime": broad,
            "sensitivity_contrast": broad["S_hat"] - native["S_hat"],
            "mean_success_shift": broad["V_hat"] - native["V_hat"],
            "open_q": open_q,
            "open_q_prime": open_prime,
            "sol_success_rate": sol_rate,
            "sol_repetitions": len(sol),
            "open_union": open_q
            or open_prime
            or (sol_rate is not None and sol_rate > 0),
        }
        states.append(state)
        pooled = collections.defaultdict(list)
        representatives = {}
        for arm in ["q", "q_prime"]:
            for j in range(protocol["k"]):
                reply = v6.p4.read(
                    OUT / "replies" / f"{case['state_id']}:{arm}:d{j}.json"
                )
                sig = reply["partner_signature"]
                representatives[sig] = reply
                pooled[sig].extend(
                    r for r in paired if r["unit"].split(":")[1] == arm and r["j"] == j
                )
        for sig, observations in pooled.items():
            success = statistics.mean(r["reward"] == 1 for r in observations)
            delta = success - native["V_hat"]
            if abs(delta) < 0.25:
                continue
            reply = representatives[sig]
            bank.append(
                {
                    "state_id": case["state_id"],
                    "task_id": case["task_id"],
                    "reply_unit": reply["unit"],
                    "partner_signature": sig,
                    "partner_block": reply["partner_block"],
                    "V_q_hat": native["V_hat"],
                    "V_d_hat": success,
                    "delta_hat": delta,
                    "observations": len(observations),
                    "direction": "harmful" if delta < 0 else "beneficial",
                    "faithful": reply["fidelity"]["faithful"],
                    "arm": reply["arm"],
                    "status": "exploratory_candidate",
                    "note": "Pooled identical blocks across both arms; observed effect is not an independently verified causal failure.",
                }
            )
    open_states = [s for s in states if s["open_union"]]
    strata = {
        "paired_complete": len(states),
        "q_unresolved": sum(s["open_q"] for s in states),
        "q_prime_unresolved": sum(s["open_q_prime"] for s in states),
        "open_union": len(open_states),
        "observed_floor_or_ceiling_without_recovery": len(states) - len(open_states),
        "both_families_observed_floor": sum(
            s["q"]["V_hat"] == 0 and s["q_prime"]["V_hat"] == 0 for s in states
        ),
        "both_families_observed_ceiling": sum(
            s["q"]["V_hat"] == 1 and s["q_prime"]["V_hat"] == 1 for s in states
        ),
        "opposite_family_floor_and_ceiling": sum(
            {s["q"]["V_hat"], s["q_prime"]["V_hat"]} == {0, 1} for s in states
        ),
        "sol_recoverable": sum(
            s["sol_success_rate"] is not None and s["sol_success_rate"] > 0
            for s in states
        ),
        "q_one_distinct_reply": sum(
            s["q"]["unique_partner_blocks"] == 1 for s in states
        ),
        "q_prime_one_distinct_reply": sum(
            s["q_prime"]["unique_partner_blocks"] == 1 for s in states
        ),
    }
    for arm in ["q", "q_prime"]:
        strata[arm + "_sample_collapse_rate"] = (
            statistics.mean(s[arm]["unique_partner_blocks"] == 1 for s in states)
            if states
            else None
        )
    task_means = collections.defaultdict(list)
    for s in states:
        task_means[s["task_id"]].append(s["sensitivity_contrast"])
    differences = [statistics.mean(xs) for xs in task_means.values()]
    contrast = {
        "task_clusters": len(differences),
        "mean_task_contrast": statistics.mean(differences) if differences else None,
        "paired_task_standard_error": statistics.stdev(differences)
        / math.sqrt(len(differences))
        if len(differences) > 1
        else None,
    }
    result = {
        "planned_states": len(protocol["states"]),
        "completed_continuations": len(all_rows),
        "completed_sol_continuations": sum(
            r["unit"].split(":")[1] == "sol" for r in all_rows
        ),
        "strata": strata,
        "sensitivity_contrast": contrast,
        "concentration_all": concentration(states),
        "concentration_open_union": concentration(open_states),
        "states": states,
        "candidate_directions": dict(
            collections.Counter(b["direction"] for b in bank if b["faithful"])
        ),
        "unfaithful_candidates": sum(not b["faithful"] for b in bank),
        "notes": [
            "Sample collapse is finite-sample duplicate evidence, not proof of zero population sensitivity.",
            "Proposal sensitivity contrast is not logprob typicality; its sign may be negative.",
            "Openness/floor/ceiling are empirical strata. Four Sol failures do not establish impossibility.",
        ],
    }
    if final:
        usage = collections.Counter()
        statuses = collections.Counter()
        for path in (OUT / "requests").glob("*.json"):
            request = v6.p4.read(path)
            statuses[request["status"]] += 1
            for kind in ["prompt_tokens", "completion_tokens"]:
                usage[kind] += (request.get("usage") or {}).get(kind, 0)
        result.update(provider_usage=dict(usage), request_statuses=dict(statuses))
    v6.p4.save(OUT / "summary.json", result)
    v6.p4.save(OUT / "candidate_bank.json", bank)
    lines = [
        "# Paired q / faithful q-prime pilot",
        "",
        f"Task-selected state pool; paired states complete {len(states)}/{len(protocol['states'])}. Continuations {len(all_rows)}.",
        "",
        "| State | V q | V q-prime | S q | S q-prime | Contrast | Distinct q/q-prime | Sol | Open |",
        "|---|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for s in states:
        sol_display = (
            f"{s['sol_success_rate']:.3f}"
            if s["sol_success_rate"] is not None
            else "pending"
        )
        lines.append(
            f"| {s['state_id']} | {s['q']['V_hat']:.3f} | {s['q_prime']['V_hat']:.3f} | {s['q']['S_hat']:.4f} | {s['q_prime']['S_hat']:.4f} | {s['sensitivity_contrast']:+.4f} | {s['q']['unique_partner_blocks']}/{s['q_prime']['unique_partner_blocks']} | {sol_display} | {s['open_union']} |"
        )
    lines.extend(
        [
            "",
            f"Strata: {strata}",
            "",
            f"Candidates: {result['candidate_directions']}",
            "",
            f"q-prime concentration in open union: {result['concentration_open_union']}",
            "",
            *result["notes"],
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    v6.p4.save(
        OUT / "progress.json",
        {
            "updated_at": time.time(),
            "paired_states_complete": len(states),
            "planned_states": len(protocol["states"]),
            "continuations_complete": len(all_rows),
            "sol_complete": result["completed_sol_continuations"],
        },
    )
    print("progress", len(states), "states", len(all_rows), "continuations", flush=True)
    return result


def main():
    """Prepare the selected state pool and run or resume the paired measurement."""
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--key-file", type=Path, default=v6.p4.ROOT / "api.txt")
    parser.add_argument("--states", type=int, default=40)
    parser.add_argument("--workers", type=int, default=40)
    parser.add_argument("--limit-states", type=int)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    OUT = args.out.resolve()
    activate()
    protocol = prepare(args.states)
    if args.report_only:
        report(protocol, final=True)
        return
    if args.prepare_only:
        v6.preflight(protocol)
        report(protocol)
        return
    v6.p4.setup(args.key_file, args.workers)
    v6.p4.KEY_LIMITS = [threading.BoundedSemaphore(12) for _ in range(4)]
    cases = (
        protocol["states"][: args.limit_states]
        if args.limit_states
        else protocol["states"]
    )
    failures = []
    for attempt in range(2):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = {
                pool.submit(state_job, case, protocol, n): (case, n)
                for n, case in enumerate(cases)
            }
            for future in as_completed(jobs):
                case, n = jobs[future]
                try:
                    future.result()
                except Exception as exc:
                    error = {
                        "state_id": case["state_id"],
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                    v6.p4.save(
                        OUT
                        / "errors"
                        / f"{case['state_id']}:attempt{attempt}:{time.time_ns()}.json",
                        error,
                    )
                    failures.append(case)
                    print(
                        "state error", case["state_id"], type(exc).__name__, flush=True
                    )
                report(protocol)
        if not failures:
            break
        if attempt == 0:
            cases, failures = failures, []
    summary = report(protocol, final=True)
    v6.p4.save(
        OUT / "execution.json",
        {
            "finished_at": time.time(),
            "requested_states_this_invocation": args.limit_states
            or len(protocol["states"]),
            "failed_states": [c["state_id"] for c in failures],
            "paired_states_complete": summary["strata"]["paired_complete"],
        },
    )
    if failures:
        raise RuntimeError(
            "State jobs remain incomplete; saved errors identify the affected units"
        )


if __name__ == "__main__":
    main()
