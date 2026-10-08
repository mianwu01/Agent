"""Frozen round-2 plans and audited native replay/continuation jobs."""

# ruff: noqa: E402
import argparse
import collections
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = ROOT / "pilot/runs/p4"
OLD = {s: BASE / f"v7_b1_{s}_20261004" for s in ["report", "step1", "step2", "step3b"]}
D = {s: BASE / f"v7_b2_{s}_20261005" for s in ["a", "b", "b2"]}
spec = importlib.util.spec_from_file_location("b1", OLD["report"] / "b1.py")
b = importlib.util.module_from_spec(spec)
sys.modules["b1"] = b
spec.loader.exec_module(b)
spec = importlib.util.spec_from_file_location(
    "b1_analysis", OLD["report"] / "analyze.py"
)
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)
read, save = b.read, b.save
v6, p4 = b.v6, b.p4
SOL = "openai/gpt-5.6-sol"

STOP_PROMPT = """This is a frozen MODEL JUDGMENT, not human ground truth. Classify the last agent message immediately before a user stop with unmet assertions. Input includes the last executed agent message, preceding context and final assertions. Return JSON {"category":"claims_resolution"|"still_troubleshooting"|"asks_user_action"|"other_or_unclear","reason":"brief evidence with quotation"}. Claims_resolution: asserts the customer's issue is resolved or service restored. Asks_user_action: requests a diagnostic, setting change, test, report or information from the user, even if a resolution claim also appears. Still_troubleshooting: discusses an unresolved issue, a next troubleshooting step or waiting without a specific request. Otherwise other_or_unclear. Use priority asks_user_action > claims_resolution > still_troubleshooting. A terminal token or a tool call alone is other_or_unclear. Do not infer deception, sabotage, task infeasibility or causality from the final failure. Return only the JSON."""
CARD_PROMPT = """Write one evidence-grounded case card in plain Chinese. This is a MODEL SUMMARY, not human annotation. Use only the supplied mechanical case card, real trajectories and rate/interval table. Return JSON {"lines":[six short lines]}. Lines: 1 the preceding agent request; 2 the candidate user's executed actions/report versus native; 3 the first recorded differing agent action (or no mechanical divergence found); 4 final unmet/satisfied assertions and any direct branch assertion changes; 5 Luna/Sol fixed/native successes and the supplied operational A2 class; 6 what the evidence supports and what remains unclear, including unobserved claims if detected. Never manufacture an intent/persona, human label, irreversible sabotage or causal explanation from a single stochastic suffix. A first divergence is an observed path difference, not proof the branch caused it. Device claims without a parser match are unassessed. A Sol failure does not prove task infeasibility. Keep six lines, each one sentence; no more than eight lines."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan():
    """Freeze case inclusion, prompts, operational classes and B2 selection rules."""
    target = OUT / "plan.json"
    if target.exists():
        return read(target)
    old = read(OLD["report"] / "plan.json")
    retest = read(OLD["step2"] / "retest.json")
    cases = [
        c
        for c in retest["candidates"]
        if c["unadjusted_CI_excludes_zero_same_direction"]
    ]
    assert len(cases) == 15
    obj = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "cases": cases,
        "states": old["states"],
        "b1_states": old["step3b_states"],
        "seeds": {"bootstrap": 2026100501, "selection": 2026100502},
        "bootstrap_replicates": 1000,
        "agent": {
            "A2": SOL,
            "B2_luna": "openai/gpt-6-luna",
            "B2_sol": SOL,
            "temperature": 1.0,
        },
        "partner": "native Luna at temperature1 in A2; corrected-v2 tools-aware VS Luna at temperature1 at every B2 turn; fidelity unchanged Sol t0",
        "A2": {
            "per_case": "16 fixed candidate suffixes +16 fresh native-block suffixes with Sol",
            "total": 480,
            "classification": "Harmful: interaction_failure if Newcombe95CI(Sol fixed - historical Luna fixed) lower>0. Otherwise partner_sabotage_or_task_infeasible_probe if Sol fixed Wilson95CI upper<0.5 AND Newcombe95CI(Sol native - Sol fixed) lower>0. Otherwise unclear. This is an exploratory reading rule, not proof of infeasibility or a sampling gate. Report Sol low success without native separation as unclear. Beneficial: mechanically report each false-to-true branch assertion and device facts disclosed; do not infer decision-help causality.",
        },
        "B1": {
            "turns": "agent conversational messages or tool-call decisions + complete partner blocks; tool results do not count as separate turns; count suffix from after initial block, include initial block as a separate inclusive statistic",
            "termination_priority": "transfer token > max_steps > user_stop_all_assertions > user_stop_unmet_assertions > other native reason; keep reward success separately from assertions",
            "later_partner": "all partner blocks after initial branch block, including native/terminal protocol; denominator complete executed blocks; per-state rates pooled numerator/denominator and task-cluster bootstrap",
            "last_agent_prompt": STOP_PROMPT,
        },
        "B2": {
            "large_drop": "6 states with most negative round1 persistent-minus-single success; ties by state_id",
            "little_drop": "4 remaining states with smallest absolute persistent-minus-single difference; ties by state_id; freeze b2_selection.json before rerun",
            "luna": "10 states x6 new v2-only branch draws x4 suffixes=240",
            "sol": "same6 v2 branch draws at6 large-drop states x2 suffixes=72; branch draws shared with Luna",
            "native_vs_historical": "comparisons to B1 are historical; A2 uses fresh native-reference blocks; Sol/Luna future randomness differs",
            "no_old_reply_cache": True,
        },
        "labelers": {
            "model": "gpt-5.6-sol",
            "temperature": 0,
            "stop_prompt": STOP_PROMPT,
            "card_prompt": CARD_PROMPT,
        },
        "mechanical_claims": "Frozen regex parser of affirmative current device assertions, exact bool/enum/numeric values and diagnostic predicates checked against actual DB/native read helpers. Matching earlier successful user-tool output supports observation; also record stale supports whose value changed. Recognized claim with no matching prior tool output is unobserved. Ignore instructions/questions/conditional clauses. Unparsed device-fact sentences remain unassessed, never presumed true or observed. Includes tool results inside the current block. Explicit quoted scenario constraints are not device facts. Save parser source hash with plan before any calls.",
        "score_intervals": "Wilson95% individual proportions; Newcombe95% independent-binomial differences, no endpoint degeneracy; exploratory unadjusted intervals retained",
        "historical_input_sha256": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                OLD["report"] / "plan.json",
                OLD["step2"] / "retest.json",
                OLD["step3b"] / "conditions.json",
            ]
        },
        "code_sha256_before_calls": {p.name: sha(p) for p in OUT.glob("*.py")},
    }
    save(target, obj)
    for directory in D.values():
        directory.mkdir(exist_ok=True)
        shutil.copy2(OLD["step2"] / "tasks.json", directory / "tasks.json")
        for c in old["states"]:
            dst = directory / "sources" / f"{c['source_id']}.json"
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists():
                shutil.copy2(OLD["step2"] / "sources" / dst.name, dst)
    for c in cases:
        src = (
            OLD["step2"] / "replies" / f"{c['state_id']}:fixed:{c['candidate_id']}.json"
        )
        r = read(src)
        r["unit"] = f"{c['state_id']}:sol_fixed:{c['candidate_id']}"
        save(D["a"] / "replies" / f"{r['unit']}.json", r)
    print("FROZEN", len(cases), "cases", flush=True)
    return obj


def routed_completion(**kwargs):
    requested = p4.KEY.get()
    route = requested if requested in (0, 2) else (0 if requested == 1 else 2)
    for alternative in (route, 2 if route == 0 else 0):
        token = p4.KEY.set(alternative)
        arguments = dict(kwargs, api_key=f"os.environ/P4_API_KEY_{alternative + 1}")
        try:
            return b.retry_transport_completion(p4.audited_completion, **arguments)
        except Exception as exc:
            if "Invalid authentication credentials" not in str(exc):
                raise
        finally:
            p4.KEY.reset(token)
    raise RuntimeError(
        "Both authorized active credential routes rejected authentication"
    )


def setup(step, workers):
    b.D = D
    b.OUT = OUT
    b.setup(step, workers)
    # Authentication-only rerouting; preserve every provider attempt in the ledger.
    p4.KEY_LIMITS = [threading.BoundedSemaphore(max(1, workers // 2)) for _ in range(4)]

    p4.llm_utils.completion = routed_completion


def a_run(workers):
    p = read(OUT / "plan.json")
    setup("a", workers)
    cs = {c["state_id"]: c for c in p["states"]}
    jobs = []
    for c in p["cases"]:
        case = cs[c["state_id"]]
        r = read(
            D["a"]
            / "replies"
            / f"{case['state_id']}:sol_fixed:{c['candidate_id']}.json"
        )
        for rep in range(16):
            jobs.append(
                lambda key, c=case, r=r, rep=rep: v6.continuation(c, r, rep, key, SOL)
            )
        for j in range(16):

            def reference(key, case=case, cand=c, j=j):
                r = b.native_sample(case, f"sol_native_{cand['candidate_id']}", j, key)
                return v6.continuation(case, r, 0, key, SOL)

            jobs.append(reference)
    b.run_jobs("a", jobs, workers)


def persistent(case, reply, rep, key, model):
    """Uniform v2 proposals at all user turns, retaining live selected-agent state."""
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

    arm = "persistent_sol" if model == SOL else "persistent_luna"
    unit = f"{case['state_id']}:{arm}:d{reply['j']}:r{rep}"
    path = D["b2"] / "continuations" / f"{unit}.json"
    if path.exists():
        return read(path)
    p4.UNIT.set(unit)
    p4.KEY.set(key)
    task = b.Task.model_validate(read(D["b2"] / "tasks.json")[case["task_id"]])
    orch = v6.build(task, reply["prefix"], p4.stable_seed(unit), key, model)
    original_step = orch.step
    versions = collections.Counter()
    turn = 0

    def step():
        nonlocal turn
        if orch.from_role.value != "agent" or orch.to_role.value != "user":
            original_step()
            return
        prefix = [m.model_dump(mode="json") for m in orch.get_messages()]
        digest = p4.digest([b.ta.semantic(m) for m in prefix])[:16]
        turn_unit = f"{unit}:turn{turn}:{digest}"
        r = b.tools_reply(
            case,
            turn_unit,
            key,
            prefix=prefix,
            remaining_steps=orch.max_steps - orch.step_count,
        )
        assert r["native_validation_version"] == "native_inclusive_or_v2"
        assert [b.ta.semantic(m) for m in r["prefix"][: len(prefix)]] == [
            b.ta.semantic(m) for m in prefix
        ]
        clone = v6.build(
            task, r["prefix"], p4.stable_seed(turn_unit + ":restore"), key, model
        )
        clone.initialize()
        assert p4.state(clone.environment) == r["state_after_partner"]
        orch.environment, orch.user_state = clone.environment, clone.user_state
        orch.message, orch.from_role, orch.to_role = (
            clone.message,
            clone.from_role,
            clone.to_role,
        )
        orch.trajectory.extend(p4.MESSAGE_LIST.validate_python(r["partner_block"]))
        orch.step_count += r["native_step_count"]
        orch.num_errors += r["native_num_errors"]
        if clone.done:
            orch.done, orch.termination_reason = True, clone.termination_reason
        versions[r["native_validation_version"]] += 1
        turn += 1
        p4.UNIT.set(unit)
        p4.KEY.set(key)

    orch.step = step
    start = time.monotonic()
    sim = orch.run()
    sim.reward_info = evaluate_simulation(
        sim, task, EvaluationType.ALL, False, "telecom"
    )
    data = sim.model_dump(mode="json")
    save(D["b2"] / "trajectories" / f"{unit}.json", data)
    row = {
        "unit": unit,
        "state_id": case["state_id"],
        "task_id": case["task_id"],
        "j": reply["j"],
        "rep": rep,
        "reward": sim.reward_info.reward,
        "agent_model": orch.agent.llm,
        "termination_reason": data["termination_reason"],
        "assertions_final": v6.assertions(orch.environment, task),
        "persistent_proposal_turns": turn,
        "future_proposal_validation_versions": dict(versions),
        "initial_validation_version": reply["native_validation_version"],
        "seconds": time.monotonic() - start,
    }
    save(path, row)
    print(unit, "reward", row["reward"], "future turns", turn, flush=True)
    return row


def b2_run(workers):
    p = read(OUT / "plan.json")
    selection = read(D["b2"] / "b2_selection.json")
    setup("b2", workers)
    save(D["b2"] / "prompts.json", read(BASE / "v7_b1_step3a_20261004/prompts.json"))
    cs = {c["state_id"]: c for c in p["states"]}
    jobs = []
    for sid in selection["large_drop"] + selection["little_drop"]:
        for j in range(6):
            jobs.append(
                lambda key, c=cs[sid], j=j: b.tools_reply(
                    c, f"{c['state_id']}:tools_v2:d{j}", key, j
                )
            )
    b.run_jobs("b2", jobs, workers)
    jobs = []
    for sid in selection["large_drop"] + selection["little_drop"]:
        for j in range(6):
            r = read(D["b2"] / "replies" / f"{sid}:tools_v2:d{j}.json")
            assert r["native_validation_version"] == "native_inclusive_or_v2"
            for rep in range(4):
                jobs.append(
                    lambda key, c=cs[sid], r=r, rep=rep: persistent(
                        c, r, rep, key, None
                    )
                )
            if sid in selection["large_drop"]:
                for rep in range(2):
                    jobs.append(
                        lambda key, c=cs[sid], r=r, rep=rep: persistent(
                            c, r, rep, key, SOL
                        )
                    )
    b.run_jobs("b2", jobs, workers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["plan", "a_run", "b2_run"])
    parser.add_argument("--workers", type=int, default=64)
    args = parser.parse_args()
    if args.phase == "plan":
        plan()
    else:
        globals()[args.phase](args.workers)


if __name__ == "__main__":
    main()
