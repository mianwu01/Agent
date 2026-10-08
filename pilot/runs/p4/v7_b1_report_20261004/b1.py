"""P4 v7 Tier B round 1: native replay controls and independent retests."""

# ruff: noqa: E402
import argparse
import collections
import copy
import importlib.util
import itertools
import json
import random
import shutil
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import litellm
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "pilot/runs/p4"
OUT = Path(__file__).resolve().parent
SRC = BASE / "v6_paired_20261004"
A = BASE / "v7_tier_a_20261004"
D = {s: BASE / f"v7_b1_{s}_20261004" for s in ["step1", "step2", "step3a", "step3b"]}
sys.path.insert(0, str(ROOT / "pilot"))
import p4_v6 as v6
import p4_v6_paired as paired

from tau2.data_model.tasks import Task

spec = importlib.util.spec_from_file_location("tier_a", A / "tier_a.py")
ta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ta)
p4 = v6.p4
TRANSFER = ta.TRANSFER
SETUP_ACTIVE = False


def read(p):
    return json.loads(Path(p).read_text())


def save(p, o):
    p4.save(p, o)


def retry_transport_completion(completion, **kwargs):
    """Retry transient transport failures with identical arguments and per-call audit."""
    transient = (
        litellm.Timeout,
        litellm.BadGatewayError,
        litellm.InternalServerError,
        litellm.APIConnectionError,
        litellm.RateLimitError,
    )
    for attempt in range(3):
        try:
            return completion(**kwargs)
        except transient:
            if attempt == 2:
                raise


def setup(step, workers):
    global SETUP_ACTIVE
    v6.OUT = D[step]
    paired.OUT = D[step]
    p4.OUT = D[step]
    if SETUP_ACTIVE:
        return
    SETUP_ACTIVE = True
    p4.setup(ROOT / "api.txt", workers)
    p4.llm_utils.completion = lambda **kwargs: retry_transport_completion(
        p4.audited_completion, **kwargs
    )
    p4.KEY_LIMITS = [threading.BoundedSemaphore(max(1, workers // 4)) for _ in range(4)]


def source_block(case):
    source = read(SRC / "sources" / f"{case['source_id']}.json")
    end = case["index"] + 1
    while (
        end < len(source["messages"]) and source["messages"][end]["role"] != "assistant"
    ):
        end += 1
    return source["messages"][:end], source["messages"][case["index"] : end]


def plan():
    """Freeze all sampling units and selections before new outcome collection."""
    if (OUT / "plan.json").exists():
        return read(OUT / "plan.json")
    protocol = read(SRC / "protocol.json")
    cases = {c["state_id"]: c for c in protocol["states"]}
    levels = read(BASE / "v7_e1_20261004/check2_level.json")["states"]
    q_high = [r["state_id"] for r in levels if r["q"]["exceeds_own_null95"]]
    qp_high = [r["state_id"] for r in levels if r["q_prime"]["exceeds_own_null95"]]
    modes = [
        json.loads(s)
        for s in (BASE / "v7_e2_20261004/mode_rows.jsonl").read_text().splitlines()
    ]
    native_modes = {r["modes"]["M2"] for r in modes if r["family"] == "q"}
    unique = collections.defaultdict(set)
    for r in modes:
        if r["family"] == "q_prime" and r["modes"]["M2"] not in native_modes:
            unique[r["unit"].rsplit(":", 1)[0]].add(r["modes"]["M2"])
    replies = {p.stem: read(p) for p in (SRC / "replies").glob("*.json")}
    outcome = collections.defaultdict(list)
    for r in modes:
        outcome[
            (r["state_id"], replies[r["unit"].rsplit(":", 1)[0]]["partner_signature"])
        ].append(r["reward"])
    native_mean = {
        sid: np.mean(
            [r["reward"] for r in modes if r["state_id"] == sid and r["family"] == "q"]
        )
        for sid in cases
    }
    bank = read(SRC / "candidate_bank.json")
    bank_by_key = {(r["state_id"], r["partner_signature"]): r for r in bank}
    candidates = {}

    def add(unit, reason, control=False):
        r = replies[unit]
        k = (r["state_id"], r["partner_signature"])
        if k in candidates:
            candidates[k]["selection_reasons"].append(reason)
            candidates[k]["exclusive_M2_modes"] = sorted(
                set(candidates[k]["exclusive_M2_modes"]) | unique.get(unit, set())
            )
            return
        ys = outcome[k]
        screening = float(np.mean(ys) - native_mean[r["state_id"]])
        b = bank_by_key.get(k)
        candidates[k] = {
            "candidate_id": f"c{len(candidates):03d}",
            "state_id": r["state_id"],
            "task_id": cases[r["state_id"]]["task_id"],
            "reply_unit": unit,
            "partner_signature": r["partner_signature"],
            "screening_shift": b["delta_hat"] if b else screening,
            "screening_block_successes": int(sum(ys)),
            "screening_block_n": len(ys),
            "screening_native_mean": float(native_mean[r["state_id"]]),
            "selection_reasons": [reason],
            "random_control": control,
            "exclusive_M2_modes": sorted(unique.get(unit, set())),
        }

    for u in sorted(unique):
        add(u, "q_prime-exclusive M2 producer")
    for sid in q_high:
        bysignature = {}
        for unit, r in replies.items():
            if r["state_id"] == sid:
                k = (sid, r["partner_signature"])
                bysignature.setdefault(k, unit)
        ranked = sorted(
            bysignature.values(),
            key=lambda u: (
                -abs(
                    np.mean(outcome[(sid, replies[u]["partner_signature"])])
                    - native_mean[sid]
                ),
                u,
            ),
        )
        for u in ranked[:2]:
            add(u, "top-two absolute shift at native-q null-exceeding state")
    for b in sorted(bank, key=lambda r: (-abs(r["delta_hat"]), r["reply_unit"])):
        if len(candidates) >= 25:
            break
        if b["state_id"] not in TRANSFER:
            add(b["reply_unit"], "largest remaining bank absolute shift")
    primary_n = len(candidates)
    eligible = [
        b
        for b in bank
        if b["state_id"] not in TRANSFER
        and (b["state_id"], b["partner_signature"]) not in candidates
    ]
    for b in random.Random(2026100801).sample(eligible, 5):
        add(b["reply_unit"], "random bank control", True)
    summary = read(SRC / "summary.json")["states"]
    open_sids = sorted(
        r["state_id"]
        for r in summary
        if r["open_union"] and r["state_id"] not in TRANSFER
    )
    other = [s for s in open_sids if s not in q_high]
    step3b_states = q_high + random.Random(2026100802).sample(other, 15)
    step3a_states = q_high + random.Random(2026100803).sample(other, 5)
    obj = {
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_hash": __import__("subprocess")
        .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
        .strip(),
        "agent": "openai/gpt-5.6-luna",
        "partner": "openai/gpt-5.6-luna",
        "agent_temperature": 1.0,
        "partner_temperature": 1.0,
        "states": protocol["states"],
        "native_q_null_exceeding_states": q_high,
        "q_prime_null_exceeding_states": qp_high,
        "interpretation_of_five_states": "Use native q five null-exceeding states; q_prime has a different five, retained for transparency. Native q is the relevance evidence identified in Tier A.",
        "candidates": list(candidates.values()),
        "primary_candidate_count": primary_n,
        "retained_all_mandatory_candidates_even_if_over_25": True,
        "step1_suffixes": 960,
        "step2_suffixes": len(candidates) * 32,
        "step3a_states": step3a_states,
        "step3b_states": step3b_states,
        "seeds": {
            "controls": 2026100801,
            "step3b_states": 2026100802,
            "step3a_states": 2026100803,
            "bootstrap": 2026100804,
            "curves": 2026100805,
        },
        "optional_temperature_zero": "Not run in round 1: attribution control, retest and interface experiment take priority.",
        "attribution_definition": "Finite-sample absence from original-block control modes at SAME state; not population support exclusion or proved causal attribution. Prefix sample sizes6/12/18/24; random-order50 curves.",
        "M3_fields": "Freeze Tier A task_device_fields.json to make arms directly comparable; out-of-set device changes are recorded as a limitation, not silently extend historical mode keys.",
        "retest_survival": "Report retained sign and separately unadjusted percentile-bootstrap95CI excluding0; no gating or claim of multiplicity-corrected confirmation. Negative estimates retained.",
        "E3_target": "Count future suffixes new relative to own past / all directions past AND absent from state-specific24-suffix agent-only mode set; also count DISTINCT such modes as secondary. Same two half-reply folds; bootstrap task clusters; paired GT minus reward-variance differences for rho/precision/capture/lift.",
        "native_reference_reuse": "Step3 native q branch and later native partner setup matches original paired run; reuse original suffixes only and report historical-vs-fresh distinction.",
        "step3_interface": "Validate JSON calls against native tool JSON schemas, execute tools through native orchestrator; fidelity prompt unchanged. No researcher persona or persistent behavior rule.",
        "step3a_reading": "Compare action/report rates with old q and old q_prime on same10states; use mechanical execution plus frozen Sol private-context labeler. If action rate remains clearly lower than q, stop3b and report blocker, not force success via outcome-dependent prompt tuning.",
    }
    save(OUT / "plan.json", obj)
    for step in D:
        D[step].mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / "tasks.json", D[step] / "tasks.json")
        for sid, c in cases.items():
            target = D[step] / "sources" / f"{c['source_id']}.json"
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                shutil.copy2(SRC / "sources" / target.name, target)
    for c in protocol["states"]:
        prefix, block = source_block(c)
        save(
            D["step1"] / "replies" / f"{c['state_id']}:original:d0.json",
            {
                "unit": f"{c['state_id']}:original:d0",
                "state_id": c["state_id"],
                "j": 0,
                "prefix": prefix,
                "partner_block": block,
                "partner_signature": v6.partner_signature(block),
                "origin": "Exact original source trajectory partner turn, replay only",
            },
        )
    for c in obj["candidates"]:
        r = copy.deepcopy(replies[c["reply_unit"]])
        r["unit"] = f"{c['state_id']}:fixed:{c['candidate_id']}"
        save(D["step2"] / "replies" / f"{r['unit']}.json", r)
    print(
        "PLAN",
        primary_n,
        "primary + 5 controls;",
        obj["step2_suffixes"],
        "retest suffixes; 3a",
        step3a_states,
        flush=True,
    )
    return obj


def run_jobs(step, jobs, workers):
    """Resume durable units, retry promptly, and preserve every failed-attempt record."""
    setup(step, workers)
    failures = []
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(job, i % 4): (i, job, 0) for i, job in enumerate(jobs)}
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                i, job, attempt = futures.pop(future)
                try:
                    future.result()
                    completed += 1
                except Exception as exc:
                    save(
                        D[step]
                        / "errors"
                        / f"job{i}:attempt{attempt}:{time.time_ns()}.json",
                        {"type": type(exc).__name__, "error": str(exc)},
                    )
                    if attempt < 2:
                        futures[pool.submit(job, i % 4)] = (i, job, attempt + 1)
                    else:
                        failures.append(i)
                        completed += 1
                if completed and completed % 40 == 0:
                    print(
                        step,
                        "completed",
                        completed,
                        "/",
                        len(jobs),
                        "exhausted failures",
                        len(failures),
                        flush=True,
                    )
    if failures:
        raise RuntimeError(f"{len(failures)} jobs incomplete; durable outputs retained")
    print(step, "COMPLETE", flush=True)


def step1(workers):
    p = read(OUT / "plan.json")
    jobs = []
    for case in p["states"]:
        reply = read(D["step1"] / "replies" / f"{case['state_id']}:original:d0.json")
        for rep in range(24):
            jobs.append(
                lambda key, c=case, r=reply, n=rep: v6.continuation(c, r, n, key)
            )
    run_jobs("step1", jobs, workers)


def native_sample(case, arm, j, key):
    """Draw an unfiltered native partner turn for a fresh reference."""
    unit = f"{case['state_id']}:{arm}:d{j}"
    path = v6.OUT / "replies" / f"{unit}.json"
    if path.exists():
        return read(path)
    p4.UNIT.set(unit)
    p4.KEY.set(key)
    task = Task.model_validate(read(v6.OUT / "tasks.json")[case["task_id"]])
    source = read(v6.OUT / "sources" / f"{case['source_id']}.json")
    prefix = source["messages"][: case["index"]]
    orch = v6.build(task, prefix, p4.stable_seed(unit), key)
    orch.initialize()
    before = v6.assertions(orch.environment, task)
    paired.complete_partner(orch)
    messages = [m.model_dump(mode="json") for m in orch.get_messages()]
    r = {
        "unit": unit,
        "state_id": case["state_id"],
        "j": j,
        "prefix": messages,
        "partner_block": messages[len(prefix) :],
        "assertions_before": before,
        "assertions_after_partner": v6.assertions(orch.environment, task),
        "state_after_partner": p4.state(orch.environment),
        "partner_signature": v6.partner_signature(messages[len(prefix) :]),
        "native_unfiltered": True,
    }
    save(path, r)
    return r


def step2(workers):
    p = read(OUT / "plan.json")
    cases = {c["state_id"]: c for c in p["states"]}
    jobs = []
    for candidate in p["candidates"]:
        case = cases[candidate["state_id"]]
        reply = read(
            D["step2"]
            / "replies"
            / f"{case['state_id']}:fixed:{candidate['candidate_id']}.json"
        )
        for rep in range(16):
            jobs.append(
                lambda key, c=case, r=reply, n=rep: v6.continuation(c, r, n, key)
            )
        for j in range(16):

            def reference(key, c=case, cand=candidate, n=j):
                arm = f"native_{cand['candidate_id']}"
                r = native_sample(c, arm, n, key)
                return v6.continuation(c, r, 0, key)

            jobs.append(reference)
    run_jobs("step2", jobs, workers)


TOOLS_PROMPT = (
    paired.PROPOSAL_PROMPT
    + """
Interface requirement: return five complete first-message decisions using the native schemas supplied below. User tools are executable actions, not prose suggestions. For EVERY candidate independently, identify whether the current agent request requires a device action, diagnostic, or observation of a current field. When it does, include the corresponding permitted native tool calls, instead of replacing the action with a promise, a guessed report, or a wording variation that silently omits execution. Tool candidates have message=null; after tools execute the native user simulator will write the report from their real results. Text candidates have no tool calls, and are appropriate when the request can be answered from already observed facts, asks for non-device information, genuinely requires clarification, or requires a terminal protocol token. Preserve legitimate uncertainty; do not invent calls or arguments, and do not add unrequested device actions. Vary valid reports and decisions while preserving the required tool interface. Do not write personas or persistent behavior rules.
"""
)


def tool_candidate_errors(candidate, tools):
    """Validate native content-or-tools legality and actual native tool schemas."""
    from jsonschema import Draft202012Validator

    schemas = {t.name: t.openai_schema["function"]["parameters"] for t in tools}
    errors = []
    calls = candidate.get("tool_calls") or []
    text = candidate.get("message")
    if not calls and not (isinstance(text, str) and text.strip()):
        errors.append("native message must have content or tool calls")
    for call in calls:
        if call.get("name") not in schemas:
            errors.append("unknown tool " + str(call.get("name")))
            continue
        schema = copy.deepcopy(schemas[call["name"]])
        schema["additionalProperties"] = False
        errors.extend(
            e.message
            for e in Draft202012Validator(schema).iter_errors(call.get("arguments"))
        )
    return errors


def tools_reply(case, unit, key, j=0, prefix=None, remaining_steps=None):
    """Propose schema-valid tools, execute a complete native turn, fidelity unchanged."""
    from run_branch import proposal_messages

    from tau2.data_model.message import SystemMessage, UserMessage

    path = v6.OUT / "replies" / f"{unit}.json"
    if path.exists():
        return read(path)
    task = Task.model_validate(read(v6.OUT / "tasks.json")[case["task_id"]])
    if prefix is None:
        prefix = read(v6.OUT / "sources" / f"{case['source_id']}.json")["messages"][
            : case["index"]
        ]
    transferred = (
        "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
        in (prefix[-1].get("content") or "").upper()
    )
    proposal_prompt = TOOLS_PROMPT
    if transferred:
        proposal_prompt += (
            " The preceding agent explicitly announced a transfer. The native "
            "simulation guidelines require ###TRANSFER### in the user reply. "
            "Every candidate must include that terminal token, use no tools, "
            "and must not resume troubleshooting."
        )
    for attempt in itertools.count():
        attempt_unit = f"{unit}:attempt{attempt}"
        if (v6.OUT / "rejected_replies" / f"{attempt_unit}.json").exists():
            continue
        p4.UNIT.set(attempt_unit)
        p4.KEY.set(key)
        seed = p4.stable_seed(attempt_unit)
        orch = v6.build(task, prefix, seed, key)
        if remaining_steps is not None:
            orch.max_steps = remaining_steps
        orch.initialize()
        before = p4.state(orch.environment)
        before_assertions = v6.assertions(orch.environment, task)
        proposal_path = v6.OUT / "proposals" / f"{attempt_unit}.json"
        invalid_path = v6.OUT / "invalid_proposals" / f"{attempt_unit}.json"
        if not proposal_path.exists() and invalid_path.exists():
            previous = read(invalid_path)
            errors = {
                str(i): tool_candidate_errors(c, orch.user.tools)
                for i, c in enumerate(previous["batch"])
            }
            if len(previous["batch"]) != 5 or any(errors.values()):
                continue
            proposal = {
                **previous,
                "schema_errors": errors,
                "previous_invalid_schema_errors": previous["schema_errors"],
                "native_validation_version": "native_inclusive_or_v2",
                "recovered_from_invalid_proposal": str(
                    invalid_path.relative_to(v6.OUT)
                ),
            }
            index = random.Random(p4.stable_seed(attempt_unit + ":draw")).randrange(5)
            proposal.update(selected_index=index, selected=proposal["batch"][index])
            save(proposal_path, proposal)
            save(
                v6.OUT / "revalidated_proposals" / f"{attempt_unit}.json",
                {
                    "original_invalid_path": str(invalid_path.relative_to(v6.OUT)),
                    "old_errors": previous["schema_errors"],
                    "native_errors": errors,
                    "selected_index": index,
                    "native_validation_version": "native_inclusive_or_v2",
                },
            )
        if proposal_path.exists():
            proposal = read(proposal_path)
        else:
            history = proposal_messages(orch.user, prefix)[:-1]
            p4.ROLE.set("q_prime_tools_proposal")
            response = p4.llm_utils.generate(
                model=orch.user.llm,
                messages=[
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
                                "native_user_visible_history": p4.llm_utils.to_litellm_messages(
                                    history[1:]
                                ),
                                "available_user_tool_schemas": [
                                    t.openai_schema for t in orch.user.tools
                                ],
                                "generation_instruction": proposal_prompt
                                + " Return only valid json.",
                            }
                        ),
                    ),
                ],
                tools=None,
                response_format={"type": "json_object"},
                max_completion_tokens=4096,
                **{**p4.llm_args(key), "seed": seed},
            )
            batch = json.loads(response.content)["candidates"]
            errors = {
                str(i): tool_candidate_errors(c, orch.user.tools)
                for i, c in enumerate(batch)
            }
            proposal = {
                "response": response.model_dump(mode="json"),
                "batch": batch,
                "schema_errors": errors,
            }
            if len(batch) != 5 or any(errors.values()):
                save(v6.OUT / "invalid_proposals" / f"{attempt_unit}.json", proposal)
                continue
            index = random.Random(p4.stable_seed(attempt_unit + ":draw")).randrange(5)
            proposal.update(selected_index=index, selected=batch[index])
            save(proposal_path, proposal)
        paired.first_response(orch.user, proposal["selected"], attempt_unit)
        paired.complete_partner(orch)
        messages = [m.model_dump(mode="json") for m in orch.get_messages()]
        block = messages[len(prefix) :]
        fidelity_path = v6.OUT / "fidelity" / f"{attempt_unit}.json"
        if fidelity_path.exists():
            fidelity = read(fidelity_path)
        else:
            fidelity = p4.json_response(
                paired.FIDELITY_PROMPT,
                {
                    "scenario": orch.user.system_prompt,
                    "user_visible_history": [
                        m.model_dump(mode="json")
                        for m in proposal_messages(orch.user, prefix)[:-1]
                    ],
                    "private_state_before": before["user"],
                    "private_state_after": p4.state(orch.environment)["user"],
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
            save(fidelity_path, fidelity)
        if transferred and (
            not any(
                "###TRANSFER###" in (m.get("content") or "")
                for m in block
                if m["role"] == "user"
            )
            or any(m.get("tool_calls") for m in block)
        ):
            fidelity = {
                **fidelity,
                "faithful": False,
                "reason": "Explicit transfer requires the native terminal token without further tool actions",
            }
        reply = {
            "unit": unit,
            "state_id": case["state_id"],
            "j": j,
            "prefix": messages,
            "partner_block": block,
            "assertions_before": before_assertions,
            "assertions_after_partner": v6.assertions(orch.environment, task),
            "state_after_partner": p4.state(orch.environment),
            "candidate": proposal["selected"],
            "attempt": attempt,
            "fidelity": fidelity,
            "partner_signature": v6.partner_signature(block),
            "generation_usage": p4.token_totals(block),
            "native_step_count": orch.step_count,
            "native_num_errors": orch.num_errors,
            "proposal_version": "schema_validated_tools_v7_b1",
            "native_validation_version": "native_inclusive_or_v2",
            "transfer_terminal_required": transferred,
            "termination_reason": orch.termination_reason.value if orch.done else None,
        }
        if fidelity["faithful"]:
            save(path, reply)
            return reply
        save(v6.OUT / "rejected_replies" / f"{attempt_unit}.json", reply)


def step3a(workers):
    p = read(OUT / "plan.json")
    cases = {c["state_id"]: c for c in p["states"]}
    save(
        D["step3a"] / "prompts.json",
        {
            "created_at": time.time(),
            "proposal": TOOLS_PROMPT,
            "fidelity": paired.FIDELITY_PROMPT,
            "private_labeler": read(BASE / "v7_e0_20261004/annotator_prompts.json")[
                "prompts"
            ]["private"],
            "note": "Original v6 format already supported optional tools; intervention clarifies required tool use and validates schemas, rather than claiming a missing parser. No device snapshot added.",
        },
    )
    jobs = []
    for sid in p["step3a_states"]:
        for j in range(6):
            jobs.append(
                lambda key, c=cases[sid], n=j: tools_reply(
                    c, f"{c['state_id']}:tools:d{n}", key, n
                )
            )
    run_jobs("step3a", jobs, workers)
    interface_labels(workers)


def interface_labels(workers):
    """Use frozen Tier A private-context labels for the same six-block batches."""
    p = read(OUT / "plan.json")
    prompts = read(BASE / "v7_e0_20261004/annotator_prompts.json")["prompts"]
    context = read(A / "context.json")["before"]
    jobs = []
    for sid in p["step3a_states"]:

        def label(key, s=sid):
            path = D["step3a"] / "labels" / f"{s}.json"
            if path.exists():
                return read(path)
            rs = [
                read(D["step3a"] / "replies" / f"{s}:tools:d{j}.json") for j in range(6)
            ]
            b = context[s]
            payload = {
                "scenario": b["scenario"],
                "user_visible_history": b["user_visible_history"],
                "private_before": b["user"],
                "blocks": [
                    {
                        "j": r["j"],
                        "partner_block": [ta.semantic(m) for m in r["partner_block"]],
                    }
                    for r in rs
                ],
            }
            result = p4.json_response(
                prompts["private"],
                payload,
                "gpt-5.6-sol",
                f"{s}:interface_private_label",
                key,
            )
            assert sorted(r["j"] for r in result["blocks"]) == list(range(6))
            save(path, {"model": "gpt-5.6-sol", "temperature": 0, "judgment": result})
            return result

        jobs.append(label)
    run_jobs("step3a", jobs, workers)
    baseline = read(BASE / "v7_e0_20261004/private_context_frequencies.json")[
        "per_state"
    ]
    aggregate = {arm: {} for arm in ["q", "q_prime_old", "q_prime_tools"]}
    per_state = {}
    for sid in p["step3a_states"]:
        rows = read(D["step3a"] / "labels" / f"{sid}.json")["judgment"]["blocks"]
        per_state[sid] = {
            "q": baseline[sid]["q"],
            "q_prime_old": baseline[sid]["q_prime"],
            "q_prime_tools": {
                k: {
                    "numerator": sum(r[k] for r in rows),
                    "denominator": 6,
                    "share": sum(r[k] for r in rows) / 6,
                }
                for k in ["device_tool_action", "device_state_report"]
            },
        }
        actual = sum(
            any(
                m.get("tool_calls")
                for m in read(D["step3a"] / "replies" / f"{sid}:tools:d{j}.json")[
                    "partner_block"
                ]
            )
            for j in range(6)
        )
        per_state[sid]["mechanical_tool_execution_count"] = actual
    for arm in aggregate:
        for k in ["device_tool_action", "device_state_report"]:
            n = sum(per_state[sid][arm][k]["numerator"] for sid in per_state)
            aggregate[arm][k] = {"numerator": n, "denominator": 60, "share": n / 60}
    action_difference = (
        aggregate["q_prime_tools"]["device_tool_action"]["share"]
        - aggregate["q"]["device_tool_action"]["share"]
    )
    task_by_sid = {c["state_id"]: c["task_id"] for c in p["states"]}
    tids = sorted({task_by_sid[s] for s in per_state})
    rng = np.random.default_rng(2026100806)
    boot = []
    for _ in range(1000):
        selected = [
            s
            for t in rng.choice(tids, size=len(tids), replace=True)
            for s in per_state
            if task_by_sid[s] == t
        ]
        boot.append(
            np.mean(
                [
                    per_state[s]["q_prime_tools"]["device_tool_action"]["share"]
                    - per_state[s]["q"]["device_tool_action"]["share"]
                    for s in selected
                ]
            )
        )
    band = np.quantile(boot, [0.025, 0.975]).tolist()
    proceed = band[1] >= 0
    save(
        D["step3a"] / "interface_check.json",
        {
            "model_judgment": True,
            "per_state": per_state,
            "aggregate": aggregate,
            "tool_action_difference_vs_q": action_difference,
            "paired_task_cluster_95_CI": band,
            "reading_rule": "Clearly below native q means the paired task-cluster95CI is wholly negative. This is an exploratory reading of the requested interface condition, not equivalence certification or a stopping rule for the rest of round1. No prompt tuning on results.",
            "proceed_to_3b": proceed,
            "new_suffixes": 0,
            "mechanical_execution_total": sum(
                r["mechanical_tool_execution_count"] for r in per_state.values()
            ),
        },
    )
    print(
        "INTERFACE",
        aggregate,
        "paired action delta CI",
        band,
        "proceed",
        proceed,
        flush=True,
    )


def persistent_continuation(case, reply, rep, key):
    """Adopt faithfully executed proposal turns without resetting live agent history."""
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

    unit = f"{case['state_id']}:persistent:d{reply['j']}:r{rep}"
    path = v6.OUT / "continuations" / f"{unit}.json"
    if path.exists():
        return read(path)
    p4.UNIT.set(unit)
    p4.KEY.set(key)
    task = Task.model_validate(read(v6.OUT / "tasks.json")[case["task_id"]])
    orch = v6.build(task, reply["prefix"], p4.stable_seed(unit), key)
    original_step = orch.step
    turn = 0
    validation_versions = collections.Counter()

    def step():
        nonlocal turn
        if orch.from_role.value == "agent" and orch.to_role.value == "user":
            prefix = [m.model_dump(mode="json") for m in orch.get_messages()]
            context_hash = p4.digest([ta.semantic(m) for m in prefix])[:16]
            turn_unit = f"{unit}:turn{turn}:{context_hash}"
            r = tools_reply(
                case,
                turn_unit,
                key,
                prefix=prefix,
                remaining_steps=orch.max_steps - orch.step_count,
            )
            assert [ta.semantic(m) for m in r["prefix"][: len(prefix)]] == [
                ta.semantic(m) for m in prefix
            ]
            validation_versions[
                r.get("native_validation_version", "strict_xor_v1")
            ] += 1
            # Restore the accepted tool effects and native user history from exact messages.
            clone = v6.build(
                task, r["prefix"], p4.stable_seed(turn_unit + ":restore"), key
            )
            clone.initialize()
            assert p4.state(clone.environment) == r["state_after_partner"]
            orch.environment = clone.environment
            orch.user_state = clone.user_state
            orch.message = clone.message
            orch.from_role = clone.from_role
            orch.to_role = clone.to_role
            orch.trajectory.extend(p4.MESSAGE_LIST.validate_python(r["partner_block"]))
            orch.step_count += r["native_step_count"]
            orch.num_errors += r["native_num_errors"]
            if clone.done:
                orch.done = True
                orch.termination_reason = clone.termination_reason
            turn += 1
            p4.UNIT.set(unit)
            p4.KEY.set(key)
        else:
            original_step()

    orch.step = step
    started = time.monotonic()
    sim = orch.run()
    sim.reward_info = evaluate_simulation(
        sim, task, EvaluationType.ALL, False, "telecom"
    )
    data = sim.model_dump(mode="json")
    save(v6.OUT / "trajectories" / f"{unit}.json", data)
    row = {
        "unit": unit,
        "state_id": case["state_id"],
        "task_id": case["task_id"],
        "j": reply["j"],
        "rep": rep,
        "reward": sim.reward_info.reward,
        "termination_reason": data["termination_reason"],
        "assertions_final": v6.assertions(orch.environment, task),
        "agent_model": orch.agent.llm,
        "usage": p4.token_totals(data["messages"][len(reply["prefix"]) :]),
        "persistent_proposal_turns": turn,
        "future_proposal_validation_versions": dict(validation_versions),
        "seconds": time.monotonic() - started,
    }
    save(path, row)
    print(unit, "reward", row["reward"], "new proposal turns", turn, flush=True)
    return row


def step3b(workers):
    p = read(OUT / "plan.json")
    check = read(D["step3a"] / "interface_check.json")
    if not check["proceed_to_3b"]:
        print(
            "3b NOT RUN: interface action rate remains below native q; see interface_check.json",
            flush=True,
        )
        return
    save(D["step3b"] / "prompts.json", read(D["step3a"] / "prompts.json"))
    (D["step3b"] / "replies").mkdir(exist_ok=True)
    cases = {c["state_id"]: c for c in p["states"]}
    # Reuse interface draws at matching states; fresh draws elsewhere, shared across single/persistent.
    jobs = []
    for sid in p["step3b_states"]:
        for j in range(6):
            src = D["step3a"] / "replies" / f"{sid}:tools:d{j}.json"
            target = D["step3b"] / "replies" / f"{sid}:tools:d{j}.json"
            if src.exists():
                shutil.copy2(src, target)
            else:
                jobs.append(
                    lambda key, c=cases[sid], n=j: tools_reply(
                        c, f"{c['state_id']}:tools:d{n}", key, n
                    )
                )
    run_jobs("step3b", jobs, workers)
    jobs = []
    for sid in p["step3b_states"]:
        for j in range(6):
            r = read(D["step3b"] / "replies" / f"{sid}:tools:d{j}.json")
            single = {**r, "unit": f"{sid}:single:d{j}"}
            save(D["step3b"] / "replies" / f"{sid}:single:d{j}.json", single)
            for rep in range(4):
                jobs.append(
                    lambda key, c=cases[sid], r=single, n=rep: v6.continuation(
                        c, r, n, key
                    )
                )
                jobs.append(
                    lambda key, c=cases[sid], r=r, n=rep: persistent_continuation(
                        c, r, n, key
                    )
                )
    run_jobs("step3b", jobs, workers)


def undo_labels(workers):
    """Frozen E0-style judgments on the next native turn in the single condition."""
    feature_rows = [
        json.loads(s) for s in (D["step3b"] / "features.jsonl").read_text().splitlines()
    ]
    prompt = read(BASE / "v7_e0_20261004/annotator_prompts.json")["prompts"][
        "regression"
    ]
    save(
        D["step3b"] / "undo_prompt.json",
        {
            "core_prompt": prompt,
            "full_wire_prompt": prompt + " Return valid json.",
            "model": "gpt-5.6-sol",
            "temperature": 0,
            "limitation": "Retains Tier A judge limitations, including possible agent-side repair conflation; these are provisional model judgments.",
        },
    )
    grouped = collections.defaultdict(list)
    for r in feature_rows:
        if r["family"] == "single" and r["next_turn"]["next_partner_block"] is not None:
            grouped[r["unit"].rsplit(":", 1)[0]].append(r)
    jobs = []
    for unit, rs in grouped.items():
        complete = [r for r in feature_rows if r["unit"].rsplit(":", 1)[0] == unit]
        if len(complete) != 4:
            continue

        def label(key, u=unit, rows=rs):
            path = D["step3b"] / "undo_labels" / f"{u}.json"
            if path.exists():
                cached = read(path)
                relations = cached["judgment"]["relations"]
                if len(relations) == len(rows) and {r["rep"] for r in relations} == {
                    r["rep"] for r in rows
                }:
                    return cached
                archive = (
                    D["step3b"]
                    / "transport_history"
                    / "undo_partial_coverage"
                    / f"{u}:{time.time_ns()}.json"
                )
                save(
                    archive,
                    {
                        **cached,
                        "archive_reason": "Early cached label input omitted not-yet-completed suffixes; re-label complete reply group with unchanged frozen prompt/model",
                        "expected_reps": sorted(r["rep"] for r in rows),
                    },
                )
                path.unlink()
            reply = read(D["step3b"] / "replies" / f"{u}.json")
            case = next(
                c
                for c in read(OUT / "plan.json")["states"]
                if c["state_id"] == reply["state_id"]
            )
            source = read(SRC / "sources" / f"{case['source_id']}.json")
            payload = {
                "preceding_agent_request": ta.semantic(
                    source["messages"][case["index"] - 1]
                ),
                "replaced_block": [ta.semantic(m) for m in reply["partner_block"]],
                "suffixes": [{"rep": r["rep"], **r["next_turn"]} for r in rows],
            }
            result = p4.json_response(
                prompt, payload, "gpt-5.6-sol", u + ":undo_label", key
            )
            assert len(result["relations"]) == len(rows)
            assert {r["rep"] for r in result["relations"]} == {r["rep"] for r in rows}
            assert all(
                r["relation"] in ["continues", "neutral", "contradicts_or_undoes"]
                for r in result["relations"]
            )
            save(
                path,
                {
                    "unit": u,
                    "state_id": reply["state_id"],
                    "judgment": result,
                    "model": "gpt-5.6-sol",
                    "temperature": 0,
                },
            )
            return result

        jobs.append(label)
    run_jobs("step3b", jobs, workers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=["plan", "step1", "step2", "step3a", "step3b", "undo_labels"]
    )
    parser.add_argument("--workers", type=int, default=48)
    args = parser.parse_args()
    if args.phase == "plan":
        plan()
    else:
        globals()[args.phase](args.workers)


if __name__ == "__main__":
    main()
