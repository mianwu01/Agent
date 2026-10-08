"""Frozen equal-token-budget screen/retest/Sol and discovery-loop arms."""

import argparse
import collections
import contextvars
import math
import random
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import c2 as c
import litellm
import search_support as support

from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

read, save = c.read, c.save
ARM = contextvars.ContextVar("c2_arm", default=None)
PHASE = contextvars.ContextVar("c2_phase", default="interface")
TASK = contextvars.ContextVar("c2_task", default=None)
LOCK = threading.RLock()
SPENT = collections.Counter()
RESERVED = collections.Counter()
UNKNOWN = collections.Counter()
CAPS = {}
NODE_HISTORY = []
WORKERS = 8


class BudgetEnd(Exception):
    """An arm phase has spent its frozen token allowance."""


def frozen_plan():
    """Freeze budgets, selection, verification and mode deduplication before runs."""
    path = c.D["step3"] / "plan.json"
    if path.exists():
        return read(path)
    projection = read(c.D["step3"] / "cost_projection.json")
    models = read(c.D["step3"] / "model_catalog.json")["model_ids"]
    other = next(
        (
            m
            for m in ["DeepSeek-V4.1-Flash", "qwen3.7-max", "claude-sonnet-5"]
            if m in models
        ),
        None,
    )
    families = ["native", "vs"] + (["other:" + other] if other else [])
    obj = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "rules_sha256": c.sha(c.rules_path()),
        "agent": "openai/gpt-6-luna",
        "agent_temperature": 1.0,
        "partner_temperature": 1.0,
        "families": families,
        "other_family_interface_probe": "one native decision at frozen first sanity state; no suffix; availability failure recorded, remove only unavailable family with pre-screen amendment",
        "arms": ["A0", "A1", "A2", "A3", "A4"],
        "token_cap_per_arm": projection["projected_tokens_per_arm"]["A0"],
        "tokens_per_suffix_equivalent": projection["tokens_per_suffix_equivalent"],
        "budget_splits": projection["budget_splits"],
        "carryforward": "Unused seed allowance to screening; unused screening to retest; unused retest to Sol. All phases charged for every request, including labelers, rejected draws, partial trajectories, failed attempts and returned token usage. Unknown-usage attempts reserve their input estimate plus requested output maximum; those estimates reported separately from returned usage. Calls denied by cap are not sent. Final unused remainder and any accounting discrepancy reported.",
        "calls": "Offline litellm token_counter(gpt-4o) estimates message/schema input; reserve max_completion_tokens(default8192) before each call, release against provider total_tokens. Exact returned cost recorded. Token budget rather than dollars; no billing-equivalence claim across models.",
        "seed_episodes": "20 mixed tasks, one fresh episode each per arm in task-id order; A0/A2/A3 native, A1 VS persistent, A4 alternating native built-in Easy/Hard private persona texts. No v6 branch states used. Save all seed outcomes; tasks with incomplete seeds remain represented as incomplete, never silently treated as successes.",
        "state_pool": "All nonterminal complete user-turn branch starts in fresh seed trajectories, excluding explicit mandated transfer turns; no reward/state-openness filter. Source trajectory prefix includes native task init. Draw task uniformly, then state within task uniformly for A0/A1/A4. Loop arms use all such states as buffer.",
        "A0": "Uniform state selection; each family6draws x2single suffixes. Reference native6draws x2 reused only within same fresh state. Rank fixed blocks by absolute screening shift; no adaptivity.",
        "A1": "VS from start in fresh seeds; screen families at uniform states, subsequent partners VS for candidate suffixes. Reference native single suffixes independently. Persistent generator directions aggregate six draws; retest fresh draws rather than retaining a lucky screening branch block.",
        "A2": "Choose(state,generator)uniformly with replacement; same6draws shared between single and persistent x2suffixes each. Retest fixed single blocks and persistent generator directions.",
        "A3": "AsA2; select reward_variance +0.25*sqrt(log(2+completed_expansions)/(1+node_expansions)); unsampled variance0. Ties uniform seeded. Past expansions include both single/persistent completed suffix outcomes. GT=f1/n over M3 outcomes logged only, never selected.",
        "A4": "Built-in Easy/Hard persona baseline from start, same nonadaptive screening/retest/Sol asA0; task goal and initialization unchanged. Existing native persona paragraphs mechanically copied, no researcher persona authored. Persona condition carried into fresh native reference, Sol check and per-rule labels.",
        "screening": "6independent accepted reply draws x2suffixes; noise-corrected S and raw reply rates retained. Screening candidates sorted by |shift|, stable ties by id. No significance/null gate on screening.",
        "retest": "Top fixed-block candidates16fresh Luna suffixes vs16new native-reference reply draws/suffixes; persistent direction16fresh accepted branch draws with persistent generator vs16native-reference single suffixes. Include all exact outcomes. No optional stopping within completed candidate.",
        "verification": "Same-direction Newcombe95% retest CI excludes zero; exploratory, unadjusted; raw negative effects retained. Invalid mechanical/scenario blocks excluded before sampling, any post-branch validity issue recorded. Sol16candidate vs16native checks on every survivor until frozen Sol budget; incomplete Sol checks explicitly unassessed, no invented class evidence.",
        "classes": "Scope-corrected C1 definitions: reward_spec_mismatch first with failing-direction pooled Luna/Sol failures>=half exact-only (assert_data_refueling_amount); hard_for_both, capability_dependent, infeasible_after_block, beneficial_disclosure, beneficial_other, unclear. Primary classes with missing Sol evidence may only be unclear (reason incomplete check), and are shown separately. Persistent generator is labelled trajectory-by-trajectory; generator case in_rule only if all16verified candidate suffixes contain no style departure; rule diversity rates shown alongside.",
        "distinct_case": "(task_id, primary_class, failing-direction M3 mode). Failing direction=candidate failures for harmful, native-reference failures for beneficial. A case may support multiple failing M3 cells; count each cell, dedupe within arm. Count no failing mode for an empty failing-direction sample; preserve such case separately.",
        "M3": "Original TierA M3: reward + sorted final task-assertion vector + categorical final task-touched device fields + first post-branch agent action type. Touched fields determined by mechanical replay of initialization and reference goal task actions, not by newly found outcomes.",
        "report": "all valid and in_rule-only efficiency per1000token suffix-equivalents; task-cluster bootstrap1000 and cumulative verified cells vs actual spend. Three most informative cards/arm if at least3verified cases, otherwise every available and explicit shortfall.",
        "seeds": {"seed": 2026100603, "screen": 2026100604, "bootstrap": 2026100605},
        "budget_gate": projection,
    }
    save(path, obj)
    return obj


def configure(arm, workers):
    """Set arm-specific ledgers and a programmatic call budget."""
    original_dir = c.D["step3"]
    plan = read(original_dir / "plan.json")
    amendment_path = original_dir / "plan_amendment_r2.json"
    if amendment_path.exists():
        plan["families"] = read(amendment_path)["effective_families"]
    probe_rows = [read(p) for p in (original_dir / "requests").glob("*.json")]
    shared_tokens = (
        sum((r.get("usage") or {}).get("total_tokens", 0) for r in probe_rows) / 5
    )
    plan["shared_probe_returned_tokens"] = shared_tokens
    plan["token_cap_per_arm"] -= shared_tokens
    target = original_dir / "arms" / arm
    target.mkdir(parents=True, exist_ok=True)
    (target / "sources").mkdir(exist_ok=True)
    save(target / "tasks.json", read(original_dir / "tasks.json"))
    c.D["step3"] = target
    c.setup("step3", workers)
    save(target / "effective_plan.json", plan)
    cap = plan["token_cap_per_arm"]
    CAPS.update({p: cap * f for p, f in plan["budget_splits"].items()})
    # Each transport attempt is charged once, including retries and auth failover.
    for f in (target / "cost_calls").glob("*.json"):
        record = read(f)
        if record.get("status") == "response":
            SPENT[record["phase"]] += record["returned_tokens"]
        elif record.get("status") in ["started", "unknown_usage"]:
            UNKNOWN[record["phase"]] += record["reserved_estimate"]
    original_audited = c.x.p4.audited_completion

    def single_completion(**kwargs):
        phase = PHASE.get()
        max_output = kwargs.get("max_completion_tokens") or 8192
        kwargs["max_completion_tokens"] = max_output
        reserve = (
            litellm.token_counter(
                model="gpt-4o", messages=kwargs["messages"], tools=kwargs.get("tools")
            )
            + max_output
        )
        original_unit = c.x.p4.UNIT.get()
        task_index = re.search(r"seed_(\d+)", original_unit)
        task_ids = sorted(read(target / "tasks.json"))
        task_id = (
            task_ids[int(task_index.group(1))]
            if task_index and int(task_index.group(1)) < len(task_ids)
            else None
        )
        cost_record = {
            "unit": original_unit,
            "requested_model": kwargs.get("model"),
            "role": c.x.p4.ROLE.get(),
            "phase": phase,
            "task_id": TASK.get() or task_id,
            "reserved_estimate": reserve,
            "started_at": time.time(),
            "status": "not_sent",
        }
        cost_path = target / "cost_calls" / f"{uuid.uuid4().hex}.json"
        with LOCK:
            if SPENT[phase] + RESERVED[phase] + UNKNOWN[phase] + reserve > CAPS[phase]:
                raise BudgetEnd(phase)
            RESERVED[phase] += reserve
        cost_record["status"] = "started"
        save(cost_path, cost_record)
        token = c.x.p4.UNIT.set(f"{arm}:{phase}:" + original_unit)
        try:
            response = original_audited(**kwargs)
            if response.usage is None:
                with LOCK:
                    UNKNOWN[phase] += reserve
                cost_record.update(
                    status="unknown_usage",
                    model_responded=True,
                    unknown_reserved_estimate=reserve,
                )
                save(cost_path, cost_record)
                return response
            usage = (
                response.usage.model_dump()
                if hasattr(response.usage, "model_dump")
                else dict(response.usage)
            )
            actual = usage.get(
                "total_tokens",
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            )
            with LOCK:
                SPENT[phase] += actual
            cost_record.update(
                status="response",
                returned_tokens=actual,
                returned_model=getattr(response, "model", None),
            )
            save(cost_path, cost_record)
            return response
        except Exception:
            with LOCK:
                UNKNOWN[phase] += reserve
            cost_record.update(
                status="unknown_usage", unknown_reserved_estimate=reserve
            )
            save(cost_path, cost_record)
            raise
        finally:
            c.x.p4.UNIT.reset(token)
            with LOCK:
                RESERVED[phase] -= reserve
                save(
                    target / "budget_progress.json",
                    {
                        "returned_tokens": dict(SPENT),
                        "unknown_usage_reserved_estimates": dict(UNKNOWN),
                        "caps": CAPS,
                        "reserved_inflight": dict(RESERVED),
                    },
                )

    def completion(**kwargs):
        from c2_auth_transport import retry_timeout_once

        return retry_timeout_once(single_completion, kwargs)

    c.x.p4.audited_completion = completion
    c.x.p4.llm_utils.completion = c.x.routed_completion
    return plan, target


def run_suffix(case, reply, rep, key, future="native", agent=None, unit=None):
    """Checked native/VS/other partner at all subsequent turns, preserving agent state."""
    target = c.ACTIVE
    unit = unit or f"{reply['unit']}:future_{future}:r{rep}"
    path = target / "continuations" / f"{unit}.json"
    if path.exists():
        return read(path)
    task = c.x.b.Task.model_validate(read(target / "tasks.json")[case["task_id"]])
    orch = c.x.v6.build(task, reply["prefix"], c.x.p4.stable_seed(unit), key, agent)
    original_step = orch.step
    turn = 0
    labels = [reply.get("label")]

    def step():
        nonlocal turn
        if orch.from_role.value != "agent" or orch.to_role.value != "user":
            c.x.p4.UNIT.set(unit)
            c.x.p4.KEY.set(key)
            original_step()
            return
        prefix = [m.model_dump(mode="json") for m in orch.get_messages()]
        r = c.sample_reply(
            case,
            turn,
            key,
            family=future,
            prefix=prefix,
            unit=f"{unit}:turn{turn}",
            remaining_steps=orch.max_steps - orch.step_count,
        )
        clone = c.x.v6.build(
            task, r["prefix"], c.x.p4.stable_seed(unit + ":restore"), key, agent
        )
        clone.initialize()
        assert c.x.p4.state(clone.environment) == r["state_after_partner"]
        orch.environment, orch.user_state = clone.environment, clone.user_state
        orch.message, orch.from_role, orch.to_role = (
            clone.message,
            clone.from_role,
            clone.to_role,
        )
        orch.trajectory.extend(c.x.p4.MESSAGE_LIST.validate_python(r["partner_block"]))
        orch.step_count += r["native_step_count"]
        orch.num_errors += r["native_num_errors"]
        if clone.done:
            orch.done, orch.termination_reason = True, clone.termination_reason
        labels.append(r["label"])
        turn += 1
        c.x.p4.UNIT.set(unit)
        c.x.p4.KEY.set(key)

    orch.step = step
    c.x.p4.UNIT.set(unit)
    c.x.p4.KEY.set(key)
    start = time.monotonic()
    sim = orch.run()
    sim.reward_info = evaluate_simulation(
        sim, task, EvaluationType.ALL, False, "telecom"
    )
    data = sim.model_dump(mode="json")
    save(target / "trajectories" / f"{unit}.json", data)
    state = c.x.p4.state(orch.environment)
    assertions = c.x.v6.assertions(orch.environment, task)
    valid = all(label["valid"] for label in labels if label)
    row = {
        "unit": unit,
        "state_id": case["state_id"],
        "task_id": case["task_id"],
        "j": reply["j"],
        "rep": rep,
        "reward": sim.reward_info.reward,
        "termination_reason": data["termination_reason"],
        "assertions_final": assertions,
        "final_user_state": state["user"],
        "future_family": future,
        "agent_model": orch.agent.llm,
        "valid": valid,
        "style": "out_of_rule"
        if any(label["style"] == "out_of_rule" for label in labels if label)
        else "in_rule",
        "partner_labels": labels,
        "next_action_type": c.x.b.ta.action_type(
            data["messages"][len(reply["prefix"]) :]
        ),
        "seconds": time.monotonic() - start,
    }
    save(path, row)
    return row


def seed_episode(task_id, index, arm, key):
    """Fresh native/VS episode from the actual task initialization, not saved v6 states."""
    TASK.set(task_id)
    target = c.ACTIVE
    unit = f"seed_{index:02d}"
    f = target / "seed_records" / f"{unit}.json"
    if f.exists():
        return read(f)
    task = c.x.b.Task.model_validate(read(target / "tasks.json")[task_id])
    orch = c.x.v6.build(task, [], c.x.p4.stable_seed(arm + unit), key)
    orch.initialize()
    prefix = [m.model_dump(mode="json") for m in orch.get_messages()]
    case = {
        "state_id": unit,
        "task_id": task_id,
        "index": len(prefix),
        "source_id": unit,
    }
    future = "vs" if arm == "A1" else "native"
    r = c.sample_reply(
        case, 0, key, family=future, prefix=prefix, unit=unit + ":initial"
    )
    row = run_suffix(case, r, 0, key, future=future, unit=unit + ":episode")
    sim = read(target / "trajectories" / f"{row['unit']}.json")
    save(target / "sources" / f"{unit}.json", sim)
    states = []
    for i, m in enumerate(sim["messages"]):
        if (
            i > 0
            and m["role"] == "user"
            and sim["messages"][i - 1]["role"] == "assistant"
            and not sim["messages"][i - 1].get("tool_calls")
        ):
            if "TRANSFER" in (sim["messages"][i - 1].get("content") or ""):
                continue
            states.append(
                {
                    "state_id": f"{unit}_b{i:03d}",
                    "task_id": task_id,
                    "source_id": unit,
                    "index": i,
                }
            )
    result = {
        "seed_unit": unit,
        "task_id": task_id,
        "reward": row["reward"],
        "states": states,
    }
    save(f, result)
    return result


def mode_paths(tasks):
    """Task-defined touched device fields via initialization/reference actions only."""
    paths = {}
    for tid, obj in tasks.items():
        task = c.x.b.Task.model_validate(obj)
        orch = c.x.v6.build(task, [])
        fields = set()
        initialization = (obj.get("initial_state") or {}).get(
            "initialization_data"
        ) or {}
        for path in c.mech.flat(initialization):
            if "device." in path:
                fields.add(path[path.index("device.") :])
        original = orch.environment.get_response

        def trace(call):
            before = c.mech.flat(c.x.p4.state(orch.environment)["user"])
            response = original(call)
            after = c.mech.flat(c.x.p4.state(orch.environment)["user"])
            fields.update(
                k
                for k in before.keys() | after.keys()
                if k.startswith("device.") and before.get(k) != after.get(k)
            )
            return response

        orch.environment.get_response = trace
        original_init = orch.environment.run_env_function_call

        def trace_init(action):
            before = c.mech.flat(c.x.p4.state(orch.environment)["user"])
            response = original_init(action)
            after = c.mech.flat(c.x.p4.state(orch.environment)["user"])
            fields.update(
                k
                for k in before.keys() | after.keys()
                if k.startswith("device.") and before.get(k) != after.get(k)
            )
            return response

        orch.environment.run_env_function_call = trace_init
        orch.initialize()
        for action in task.evaluation_criteria.actions or []:
            if action.name in {t.name for t in orch.user.tools}:
                from tau2.data_model.message import ToolCall

                trace(
                    ToolCall(
                        id="reference",
                        name=action.name,
                        arguments=action.arguments,
                        requestor="user",
                    )
                )
        paths[tid] = sorted(fields)
    return paths


def mode(row, paths):
    return c.x.b.ta.mode_key(
        {
            "reward": int(row["reward"] == 1),
            "assertions": row["assertions_final"],
            "final_user_state": row["final_user_state"],
            "next_action_type": row["next_action_type"],
            "task_id": row["task_id"],
        },
        "M3",
        paths,
    )


def run_arm(arm, workers=8):
    global WORKERS
    WORKERS = workers
    c.FULL_STYLE = False
    plan, target = configure(arm, workers)
    ARM.set(arm)
    tasks = read(target / "tasks.json")
    if arm == "A4":
        prototypes = {}
        for task in tasks.values():
            persona = task["user_scenario"].get("persona")
            if persona:
                key = "Hard" if "64 years" in persona else "Easy"
                prototypes[key] = persona
        for index, tid in enumerate(sorted(tasks)):
            tasks[tid]["user_scenario"]["persona"] = prototypes[
                "Easy" if index % 2 == 0 else "Hard"
            ]
        save(target / "tasks.json", tasks)
    paths = mode_paths(tasks)
    save(target / "mode_paths.json", paths)

    def runjobs(jobs, phase):
        errors = []

        def wrap(job, index):
            PHASE.set(phase)
            ARM.set(arm)
            try:
                return job(index % 4)
            except BudgetEnd as exc:
                save(
                    target / "budget_incomplete" / f"{phase}:{index}.json",
                    {"phase": phase, "job": index, "reason": str(exc)},
                )
                return None
            except Exception as exc:
                save(
                    target
                    / "execution_errors"
                    / f"{phase}:{index}:{time.time_ns()}.json",
                    {"type": type(exc).__name__, "error": str(exc)[:2000]},
                )
                errors.append(index)
                return None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [
                f.result()
                for f in as_completed(
                    [pool.submit(wrap, j, i) for i, j in enumerate(jobs)]
                )
            ]
        if errors:
            raise RuntimeError(
                f"Incomplete {phase} jobs: {errors}; saved results retained"
            )
        return results

    runjobs(
        [
            lambda key, tid=tid, i=i: seed_episode(tid, i, arm, key)
            for i, tid in enumerate(sorted(tasks))
        ],
        "fresh_seed_episodes",
    )
    unused = max(
        0,
        CAPS["fresh_seed_episodes"]
        - SPENT["fresh_seed_episodes"]
        - UNKNOWN["fresh_seed_episodes"],
    )
    CAPS["screening_expansions"] += unused
    CAPS["fresh_seed_episodes"] -= unused
    seeds = [read(f) for f in sorted((target / "seed_records").glob("*.json"))]
    states = [s for seed in seeds for s in seed["states"]]
    save(
        target / "fresh_state_pool.json",
        {
            "states": states,
            "seed_episodes_completed": len(seeds),
            "task_count": len(tasks),
            "no_v6_states": True,
        },
    )
    if not states:
        raise RuntimeError("No completed fresh state pool; cannot run search")
    rng = random.Random(2026100604 + int(arm[-1]))
    bytask = collections.defaultdict(list)
    for state in states:
        bytask[state["task_id"]].append(state)
    families = plan["families"]
    nodes = [(s, f) for s in states for f in families]
    history = {}
    log = []
    index = 0
    PHASE.set("screening_expansions")
    # Screens are sequential at node granularity, model transport still audited.
    while (
        SPENT["screening_expansions"] + UNKNOWN["screening_expansions"] + 30000
        < CAPS["screening_expansions"]
    ):
        if arm in ["A0", "A1", "A4"]:
            state = rng.choice(states)
            family = "all"
        elif arm == "A2":
            state, family = rng.choice(nodes)
        else:
            scores = []
            for state, family in nodes:
                h = history.get((state["state_id"], family), [])
                out = [v for item in h for v in item["screen_rewards"]]
                p = sum(out) / len(out) if out else 0
                score = p * (1 - p) + 0.25 * math.sqrt(
                    math.log(2 + index) / (1 + len(h))
                )
                scores.append(score)
            chosen = rng.choice([i for i, s in enumerate(scores) if s == max(scores)])
            state, family = nodes[chosen]
        try:
            result = expand(state, family, index, arm, index % 4, paths)
        except BudgetEnd:
            break
        except Exception as exc:
            save(
                target / "execution_errors" / f"screen:{index}.json",
                {"type": type(exc).__name__, "error": str(exc)[:2000]},
            )
            raise
        history.setdefault((state["state_id"], family), []).append(result)
        node_modes = collections.Counter()
        for item in history[(state["state_id"], family)]:
            node_modes.update(item["mode_counts"])
        node_n = sum(node_modes.values())
        node_GT = sum(v == 1 for v in node_modes.values()) / node_n
        log.append(
            {
                "index": index,
                "state_id": state["state_id"],
                "family": family,
                "variance": result["variance"],
                "GT_secondary": node_GT,
                "GT_current_expansion": result["GT"],
                "node_past_suffix_count": node_n,
                "cumulative_tokens": sum(SPENT.values()),
                "selection": "reward_variance_plus_count" if arm == "A3" else "uniform",
            }
        )
        save(target / "selection_log.json", log)
        index += 1
        print(arm, "SCREEN", index, "tokens", int(sum(SPENT.values())), flush=True)
    # Deduplicate actual fixed blocks/directions before selecting expensive checks.
    candidates = [
        r for f in (target / "expansions").glob("*.json") for r in read(f)["candidates"]
    ]
    unique = {}
    for cand in sorted(
        candidates, key=lambda r: (-abs(r["screening_shift"]), r["candidate_id"])
    ):
        signature = (
            (cand["state"]["state_id"], cand["family"], cand["future"])
            if cand["persistent_direction"]
            else (
                cand["state"]["state_id"],
                read(target / "replies" / f"{cand['reply_unit']}.json")[
                    "partner_signature"
                ],
                cand["future"],
            )
        )
        unique.setdefault(signature, cand)
    ordered = list(unique.values())
    save(target / "candidate_screen_bank.json", ordered)
    unused = max(
        0,
        CAPS["screening_expansions"]
        - SPENT["screening_expansions"]
        - UNKNOWN["screening_expansions"],
    )
    CAPS["independent_retest"] += unused
    CAPS["screening_expansions"] -= unused
    PHASE.set("independent_retest")
    verified = []
    tested = []
    for i, cand in enumerate(ordered):
        try:
            result = independent_check(cand, i % 4)
        except BudgetEnd:
            break
        except Exception as exc:
            save(
                target / "execution_errors" / f"retest:{i}.json",
                {"type": type(exc).__name__, "error": str(exc)[:2000]},
            )
            continue
        tested.append(result)
        if result["same_direction_CI_excludes_zero"] and result["valid"]:
            import search_support

            try:
                result = search_support.verified_labels(sys.modules[__name__], result)
            except BudgetEnd:
                break
            if result["valid"]:
                verified.append(result)
        print(arm, "RETEST", i, result["shift"], result["95_CI"], flush=True)
    unused = max(
        0,
        CAPS["independent_retest"]
        - SPENT["independent_retest"]
        - UNKNOWN["independent_retest"],
    )
    CAPS["Sol_check"] += unused
    CAPS["independent_retest"] -= unused
    PHASE.set("Sol_check")
    sols = []
    for i, result in enumerate(verified):
        try:
            sols.append(independent_check(result["candidate"], i % 4, sol=True))
        except BudgetEnd:
            break
        except Exception as exc:
            save(
                target / "execution_errors" / f"sol:{i}.json",
                {"type": type(exc).__name__, "error": str(exc)[:2000]},
            )
    save(
        target / "search_result.json",
        {
            "arm": arm,
            "completed_expansions": index,
            "screened_candidates": len(ordered),
            "completed_retests": len(tested),
            "verified_cases": verified,
            "Sol_checks": sols,
            "returned_token_cost": dict(SPENT),
            "unknown_usage_reserved_estimates": dict(UNKNOWN),
            "frozen_token_cap": plan["token_cap_per_arm"],
            "actual_suffix_equivalents": sum(SPENT.values())
            / plan["tokens_per_suffix_equivalent"],
            "budget_unspent_returned_tokens": plan["token_cap_per_arm"]
            - sum(SPENT.values()),
            "seed_episodes": len(seeds),
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(
        arm, "DONE verified", len(verified), "tokens", sum(SPENT.values()), flush=True
    )


# Parallel independent execution preserves adaptive node-level selection.


def expand(case, family, index, arm, key, paths):
    return support.expand(sys.modules[__name__], case, family, index, arm, key, paths)


def independent_check(candidate, key, sol=False):
    return support.check(sys.modules[__name__], candidate, key, sol)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["plan", "run"])
    ap.add_argument("--arm", choices=["A0", "A1", "A2", "A3", "A4"])
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.phase == "plan":
        frozen_plan()
    else:
        run_arm(args.arm, args.workers)
