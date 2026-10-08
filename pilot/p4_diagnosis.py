"""Exploratory P4 diagnosis with blinded review and audited four-key requests."""

# Bootstrap logging and offline price-map configuration before importing tau2.
# ruff: noqa: E402

import argparse
import collections
import contextvars
import csv
import hashlib
import json
import os
import random
import re
import threading
import time
import types
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from loguru import logger

logger.remove()

from branch_common import (
    MESSAGE_LIST,
    ROOT,
    config,
    stable_seed,
    token_totals,
    with_prefix,
)
from transport import configure_transport

from tau2.agent.base_agent import is_valid_agent_history_message
from tau2.data_model.message import (
    AssistantMessage,
    MultiToolMessage,
    SystemMessage,
    UserMessage,
)
from tau2.data_model.tasks import Task
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.runner import build_text_orchestrator
from tau2.utils import llm_utils

logger.remove()
OUT = ROOT / "pilot/runs/p4/diagnosis_20261003"
UNIT = contextvars.ContextVar("p4_unit", default="probe")
ROLE = contextvars.ContextVar("p4_role", default="judge")
KEY = contextvars.ContextVar("p4_key", default=0)
BASE = "https://www.autodl.art/api/v1"
ORIGINAL_COMPLETION = llm_utils.completion
SECRETS = []
KEY_LIMITS = [threading.BoundedSemaphore(4) for _ in range(4)]


def save(path, obj):
    """Save a redacted durable JSON artifact without exposing credentials."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    for secret in SECRETS:
        text = text.replace(secret, "[REDACTED]")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text + "\n")
    tmp.replace(path)


def read(path):
    """Read a JSON artifact."""
    return json.loads(Path(path).read_text())


def digest(obj):
    """Hash canonical serialized data for provenance and state checks."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()


def state(env):
    """Record both independent databases, including cross-tool synchronization."""
    return {
        "agent": env.tools.db.model_dump(mode="json"),
        "user": env.user_tools.db.model_dump(mode="json"),
    }


def audited_completion(**kwargs):
    """Record every provider attempt before execution; never retry invisibly."""
    name = uuid.uuid4().hex
    path = OUT / "requests" / (name + ".json")
    entry = {
        "id": name,
        "unit": UNIT.get(),
        "role": ROLE.get(),
        "key_index": KEY.get() + 1,
        "started_at": time.time(),
        "status": "started",
        "request": kwargs,
    }
    save(path, entry)
    start = time.monotonic()
    try:
        with KEY_LIMITS[KEY.get()]:
            response = ORIGINAL_COMPLETION(**kwargs)
        raw = (
            response.model_dump()
            if hasattr(response, "model_dump")
            else response.to_dict()
        )
        entry.update(
            status="response",
            response=raw,
            usage=raw.get("usage"),
            returned_model=raw.get("model"),
        )
        return response
    except Exception as exc:
        entry.update(
            status="error",
            error_type=type(exc).__name__,
            error_message=str(exc)[:2000],
            usage=None,
        )
        raise
    finally:
        entry["seconds"] = time.monotonic() - start
        save(path, entry)


def setup(key_file, workers):
    """Load four keys into separate environment variables and configure transport."""
    global SECRETS
    SECRETS = Path(key_file).read_text().split()
    if len(SECRETS) != 4 or len(set(SECRETS)) != 4:
        raise ValueError("Expected four distinct credentials")
    for i, key in enumerate(SECRETS):
        os.environ[f"P4_API_KEY_{i + 1}"] = key
    configure_transport(workers)
    llm_utils.completion = audited_completion
    import tau2.agent.llm_agent as agent_module
    import tau2.user.user_simulator as user_module

    original_generate = llm_utils.generate

    def role_generate(role):
        def generate(**kwargs):
            tok = ROLE.set(role)
            try:
                return original_generate(**kwargs)
            finally:
                ROLE.reset(tok)

        return generate

    agent_module.generate = role_generate("agent")
    user_module.generate = role_generate("user")


def llm_args(key_index, judge=False):
    """Use an environment reference, never a literal credential, in configs."""
    return {
        "api_base": BASE,
        "api_key": f"os.environ/P4_API_KEY_{key_index + 1}",
        "temperature": 0.0 if judge else 1.0,
        "reasoning_effort": "none",
        "allowed_openai_params": ["reasoning_effort"],
        "num_retries": 0,
        "timeout": 180.0 if judge else 120.0,
    }


def source_data():
    """Load frozen original tasks and simulations without modifying them."""
    iid = read(ROOT / "pilot/runs/iid/default/results.json")
    tasks = {t["id"]: t for t in iid["tasks"]}
    sources = {s["id"]: s for s in iid["simulations"]}
    return iid, tasks, sources


def agent_view(messages):
    """Expose only the exact agent-visible message projection with source indices."""
    result = []
    for i, msg in enumerate(MESSAGE_LIST.validate_python(messages)):
        if is_valid_agent_history_message(msg):
            result.append(
                {
                    "index": i,
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": [
                        t.model_dump(mode="json")
                        for t in getattr(msg, "tool_calls", None) or []
                    ],
                }
            )
    return result


def ability_signal(sim):
    """A broad lexical screen, explicitly not a failure-mechanism label."""
    return any(
        re.search(
            r"(device|diagnostic|phone).{0,100}(unavailable|not available|cannot|lack)|"
            r"(unavailable|cannot|lack).{0,100}(device|diagnostic|phone)",
            json.dumps(m.get("tool_calls") or []) + (m.get("content") or ""),
            re.I,
        )
        for m in sim["messages"]
        if m["role"] == "assistant"
    )


def prepare():
    """Freeze a stratified exploratory sample and its inclusion probabilities."""
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "sample.json").exists():
        return
    iid, tasks, _ = source_data()
    strata = collections.defaultdict(list)
    for sim in iid["simulations"]:
        if sim["reward_info"]["reward"] == 1:
            group = "iid_success"
        else:
            group = "iid_ability_signal" if ability_signal(sim) else "iid_other_failure"
        strata[group].append({"simulation": sim, "origin": "iid", "stratum": group})
    for row in [
        json.loads(line)
        for line in (ROOT / "pilot/runs/branch/branches.jsonl").read_text().splitlines()
    ]:
        if row["flipped"]:
            group = "branch_" + row["arm"]
            strata[group].append(
                {
                    "simulation": read(ROOT / row["trajectory_path"]),
                    "origin": row["arm"],
                    "stratum": group,
                }
            )
    rng = random.Random(20261003)
    selected = []
    populations = {}
    for group, candidates in sorted(strata.items()):
        candidates.sort(key=lambda c: c["simulation"]["id"])
        n = min(24, len(candidates))
        populations[group] = {
            "population": len(candidates),
            "sampled": n,
            "inclusion_probability": n / len(candidates),
        }
        for item in rng.sample(candidates, n):
            sim = item.pop("simulation")
            sid = "s" + str(len(selected)).zfill(3)
            item.update(
                sample_id=sid,
                simulation_id=sim["id"],
                task_id=sim["task_id"],
                inclusion_probability=n / len(candidates),
                recorded_reward=sim["reward_info"]["reward"],
            )
            save(OUT / "sources" / (sid + ".json"), sim)
            selected.append(item)
    save(
        OUT / "sample.json",
        {
            "seed": 20261003,
            "strata": populations,
            "items": selected,
            "iid_sha256": digest(iid),
            "sampling_unit": "trajectory, with correlated tasks retained",
        },
    )
    save(OUT / "tasks.json", tasks)
    save(
        OUT / "protocol.json",
        {
            "scope": "Exploratory criterion development on previously generated data; not retrospective preregistration",
            "agent_and_user": {
                "model": "openai/gpt-5.6-luna",
                "temperature": 1.0,
                "reasoning_effort": "none",
            },
            "review": "Outcome/stratum/tool-output-blinded agent-view reviewer; labels remain provisional",
            "categories": {
                "A": "Contradicts still-valid accessible state evidence",
                "B": "Unconditional state-dependent action without necessary information",
                "C": "Fails to use policy-described partner capabilities",
                "other": "Other candidate interaction mechanism",
                "none": "No supported candidate",
                "uncertain": "Insufficient evidence",
            },
            "case_budget": "At most 12 distinct-task candidates, 8 continuations in each of resample/fixed_original/fixed_corrected",
            "information_matching": "Correction proposer sees only original policy, agent tools and agent-visible history strictly before decision; no task ID, gold actions, user scenario, hidden DB or future messages",
            "horizon": "200 total native steps; prefix generation and environment-step groups count toward limit",
            "cost": "Every provider request logged, including errors/pending; no automatic provider or simulation retries; unknown error usage stays unknown",
            "claims": "Exploratory mechanism evidence; no validated-category or discovery-efficiency claims without adjudication and independent confirmation",
        },
    )
    print("prepared", len(selected), "trajectories", flush=True)


LABEL_PROMPT = """Review an interaction for a candidate failure mechanism. You receive only the agent's policy, tools and visible transcript. You do NOT know the reward, task initialization, user tool outputs or sample stratum. Do not infer hidden state. A: an agent decision contradicts still-valid visible evidence. B: an unconditional state-dependent instruction lacks necessary information. An instruction such as 'ensure ON; if already ON leave it' is conditional and NOT B merely because the user may use toggle. C: agent explicitly treats absence of its own device tools as inability to guide the user, despite an applicable procedure already in policy. Legitimate escalation (locked SIM, expired contract etc.) is NOT C. Other: a supported different interaction mechanism. None: no supported candidate. Uncertain: insufficient evidence. No-user outcomes cannot classify a cause. Output ONLY JSON with category (A/B/C/other/none/uncertain), decision_index (original assistant index or null), evidence (list of {index,quote}), policy_quote (literal quote or empty), explanation, competing_explanations (list), confidence (0..1). Select one earliest actionable candidate, not a catalog. Literal quotes must exist in supplied messages/policy. A report's validity must be assessed through intervening visible actions; never assume truthful/exhaustive reports. A candidate is not a causally confirmed failure."""


def json_response(prompt, payload, model, unit, key_index):
    """Make one bounded structured request and preserve malformed responses."""
    UNIT.set(unit)
    KEY.set(key_index)
    ROLE.set("judge")
    response = llm_utils.generate(
        model="openai/" + model,
        messages=[
            SystemMessage(role="system", content=prompt + " Return valid json."),
            UserMessage(
                role="user",
                content=json.dumps(
                    {"output_format": "json", "input": payload}, ensure_ascii=False
                ),
            ),
        ],
        **llm_args(key_index, judge=True),
        max_completion_tokens=1800,
        response_format={"type": "json_object"},
    )
    return json.loads(response.content)


def validate_label(label, view, policy):
    """Require exact evidence grounding and an assistant decision index."""
    if label["category"] not in {"A", "B", "C", "other", "none", "uncertain"}:
        raise ValueError("Invalid category")
    by_index = {m["index"]: m for m in view}
    idx = label.get("decision_index")
    if label["category"] in {"A", "B", "C", "other"}:
        if idx not in by_index or by_index[idx]["role"] != "assistant":
            raise ValueError("Decision is not agent-visible assistant message")
    for evidence in label.get("evidence", []):
        msg = by_index.get(evidence["index"])
        if (
            msg is None
            or not evidence["quote"]
            or evidence["quote"] not in json.dumps(msg, ensure_ascii=False)
        ):
            # Content quotes need not contain JSON serialization escapes.
            if msg is None or evidence["quote"] not in (msg.get("content") or ""):
                raise ValueError("Ungrounded transcript quote")
    quote = label.get("policy_quote", "")
    if quote and quote not in policy:
        raise ValueError("Ungrounded policy quote")
    return label


def screen_one(item, number, model="gpt-5.6-luna", folder="reviews"):
    """Review one saved source while hiding sampling and outcome metadata."""
    sid = item["sample_id"]
    path = OUT / folder / (sid + ".json")
    if path.exists():
        return read(path)
    sim = read(OUT / "sources" / (sid + ".json"))
    task = Task.model_validate(read(OUT / "tasks.json")[item["task_id"]])
    orch = build_text_orchestrator(config(), task)
    view = agent_view(sim["messages"])
    payload = {
        "policy": orch.agent.domain_policy,
        "agent_tools": [t.openai_schema for t in orch.agent.tools],
        "transcript": view,
    }
    entry = {
        "sample_id": sid,
        "model": model,
        "request_payload_sha256": digest(payload),
    }
    try:
        label = json_response(
            LABEL_PROMPT, payload, model, folder + ":" + sid, number % 4
        )
        entry["raw_label"] = label
        entry["label"] = validate_label(label, view, orch.agent.domain_policy)
        entry["status"] = "ok"
    except Exception as exc:
        entry.update(status="error", error_type=type(exc).__name__)
    save(path, entry)
    return entry


def pool_jobs(items, function, workers):
    """Run bounded parallel jobs and emit sparse durable progress."""
    result = []
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(function, item, i) for i, item in enumerate(items)]
        for future in as_completed(futures):
            result.append(future.result())
            if len(result) % 8 == 0 or len(result) == len(items):
                print("completed", len(result), "/", len(items), flush=True)
    return result


def review_panel():
    """Choose distinct-task candidates and independent negative reviews deterministically."""
    if (OUT / "panel.json").exists():
        return read(OUT / "panel.json")
    items = read(OUT / "sample.json")["items"]
    scored = []
    for item in items:
        entry = read(OUT / "reviews" / (item["sample_id"] + ".json"))
        if entry["status"] == "ok":
            scored.append((item, entry["label"]))
    candidates = sorted(
        [
            x
            for x in scored
            if x[1]["category"] in {"A", "B", "C", "other"}
            and x[0]["recorded_reward"] == 0
        ],
        key=lambda x: (x[1]["category"], -x[1].get("confidence", 0), x[0]["sample_id"]),
    )
    selected, seen = [], set()
    for category in ["A", "B", "C", "other"] * 12:
        if len(selected) >= 12:
            break
        eligible = [
            x
            for x in candidates
            if x[1]["category"] == category and x[0]["task_id"] not in seen
        ]
        if eligible:
            item, label = eligible[0]
            selected.append(item)
            seen.add(item["task_id"])
    negatives = [
        item for item, label in scored if label["category"] in {"none", "uncertain"}
    ]
    random.Random(20261004).shuffle(negatives)
    panel = {
        "candidates": selected,
        "negative_checks": negatives[:12],
        "note": "Second reviewer sees no first-review labels or outcomes",
    }
    save(OUT / "panel.json", panel)
    return panel


REPAIR_PROMPT = """Propose ONE next customer-service response using only the supplied policy, agent tools and visible prefix. The previous response has not happened. Do not infer initialization or hidden device state. The indicated candidate mechanism is a hypothesis. Replace it with a minimal policy-consistent response: A use valid existing evidence; B query relevant state or give a safe conditional instruction; C ask the user to execute an applicable diagnostic procedure already in policy. Do not supply a complete solution, change the user's persona, inject knowledge, or claim the issue is fixed. Return ONLY JSON: {response_text: nonempty plain user-facing English text, evidence_indices: list of original prefix indices, policy_quote: literal applicable policy text, explanation: string}. Avoid tool syntax pretending to execute user tools. You can ask the user to inspect a setting and report its result. No future transcript is available."""


def repair_one(item, number):
    """Construct and strictly initialize a proposed correction at a shared prefix."""
    sid = item["sample_id"]
    path = OUT / "proposals" / (sid + ".json")
    if path.exists():
        return read(path)
    first = read(OUT / "reviews" / (sid + ".json"))
    second = read(OUT / "independent_reviews" / (sid + ".json"))
    if first["status"] != "ok" or second["status"] != "ok":
        return {"sample_id": sid, "status": "review_error"}
    label = first["label"]
    if (
        label["category"] != second["label"]["category"]
        or label["decision_index"] != second["label"]["decision_index"]
    ):
        save(
            path,
            {
                "sample_id": sid,
                "status": "review_disagreement",
                "first": label,
                "second": second["label"],
            },
        )
        return read(path)
    sim = read(OUT / "sources" / (sid + ".json"))
    idx = label["decision_index"]
    task = Task.model_validate(read(OUT / "tasks.json")[item["task_id"]])
    prefix = sim["messages"][:idx]
    orch = build_text_orchestrator(config(), with_prefix(task, prefix))
    orch.initialize()
    payload = {
        "candidate_mechanism": label["category"],
        "policy": orch.agent.domain_policy,
        "agent_tools": [t.openai_schema for t in orch.agent.tools],
        "prefix": agent_view(prefix),
    }
    entry = {
        "sample_id": sid,
        "task_id": task.id,
        "category": label["category"],
        "decision_index": idx,
        "prefix_state_sha256": digest(state(orch.environment)),
        "prefix_sha256": digest(prefix),
        "original_response": sim["messages"][idx],
        "information_payload_sha256": digest(payload),
    }
    try:
        proposal = json_response(
            REPAIR_PROMPT, payload, "gpt-5.6-sol", "repair:" + sid, number % 4
        )
        if (
            not proposal.get("response_text")
            or not proposal.get("policy_quote")
            or proposal["policy_quote"] not in orch.agent.domain_policy
        ):
            raise ValueError("Correction missing grounded policy")
        valid_indices = {m["index"] for m in payload["prefix"]}
        if any(i not in valid_indices for i in proposal["evidence_indices"]):
            raise ValueError("Correction cites inaccessible evidence")
        entry.update(status="proposed", proposal=proposal)
    except Exception as exc:
        entry.update(status="error", error_type=type(exc).__name__)
    save(path, entry)
    return entry


def prefix_steps(prefix):
    """Count native generation and tool-batch steps, excluding initial greeting."""
    return sum(m["role"] in {"assistant", "user"} for m in prefix[1:]) + sum(
        bool(m.get("tool_calls")) for m in prefix
    )


def force_response(agent, fixed):
    """Replace exactly the first response while preserving native state updates."""
    original = agent._generate_next_message
    used = False

    def generate(self, message, current_state):
        nonlocal used
        if used:
            return original(message, current_state)
        used = True
        if isinstance(message, MultiToolMessage):
            current_state.messages.extend(message.tool_messages)
        elif message is not None:
            current_state.messages.append(message)
        response = AssistantMessage.model_validate(fixed).model_copy(deep=True)
        response.usage = None
        response.raw_data = None
        response.cost = None
        response.timestamp = AssistantMessage(role="assistant", content="").timestamp
        response.turn_idx = None
        return response

    agent._generate_next_message = types.MethodType(generate, agent)


def run_one(job, number):
    """Run a single frozen case/arm/rep with live state trace and request ledger."""
    case, arm, rep = job
    unit = f"{case['sample_id']}:{arm}:{rep}"
    path = OUT / "continuations" / (unit + ".json")
    if path.exists():
        return read(path)
    UNIT.set(unit)
    KEY.set(number % 4)
    sim = read(OUT / "sources" / (case["sample_id"] + ".json"))
    task = Task.model_validate(read(OUT / "tasks.json")[case["task_id"]])
    prefix = sim["messages"][: case["decision_index"]]
    cfg = config()
    cfg.llm_args_agent = llm_args(number % 4)
    cfg.llm_args_user = llm_args(number % 4)
    cfg.max_retries = 0
    cfg.max_steps = max(1, 200 - prefix_steps(prefix))
    seed = stable_seed(unit)
    cfg.llm_args_agent["seed"] = seed
    cfg.llm_args_user["seed"] = seed
    orch = build_text_orchestrator(
        cfg, with_prefix(task, prefix), seed=seed, simulation_id=unit
    )
    entry = {
        "unit": unit,
        "sample_id": case["sample_id"],
        "task_id": task.id,
        "category": case["category"],
        "arm": arm,
        "rep": rep,
        "seed": seed,
        "seed_determinism": "unverified",
        "key_index": number % 4 + 1,
        "config": cfg.model_dump(mode="json"),
        "prefix_sha256": digest(prefix),
        "status": "started",
    }
    save(path, entry)
    traces = []
    try:
        original_initialize = orch.initialize

        def checked_initialize(self):
            original_initialize()
            if digest(state(self.environment)) != case["prefix_state_sha256"]:
                raise ValueError("Initial state hash mismatch")

        orch.initialize = types.MethodType(checked_initialize, orch)
        original_step = orch.step

        def traced_step(self):
            original_step()
            traces.append(
                {
                    "step": self.step_count,
                    "state_sha256": digest(state(self.environment)),
                    "n_messages": len(self.trajectory),
                }
            )

        orch.step = types.MethodType(traced_step, orch)
        if arm == "fixed_original":
            force_response(orch.agent, case["original_response"])
        elif arm == "fixed_corrected":
            force_response(
                orch.agent,
                AssistantMessage(
                    role="assistant",
                    content=json.dumps({"message": case["proposal"]["response_text"]}),
                ).model_dump(mode="json"),
            )
        result = orch.run()
        result.policy = orch.environment.get_policy()
        result.reward_info = evaluate_simulation(
            result, task, EvaluationType.ALL, False, "telecom"
        )
        fields = ("role", "content", "tool_calls", "id", "requestor")
        raw = result.model_dump(mode="json")
        if len(raw["messages"]) < len(prefix) or any(
            any(a.get(k) != b.get(k) for k in fields)
            for a, b in zip(prefix, raw["messages"][: len(prefix)], strict=True)
        ):
            raise ValueError("Prefix drift")
        entry.update(
            status="completed",
            simulation=raw,
            reward=raw["reward_info"]["reward"],
            suffix_usage=token_totals(raw["messages"][len(prefix) :]),
            final_state=state(orch.environment),
            state_trace=traces,
        )
    except Exception as exc:
        entry.update(
            status="error",
            error_type=type(exc).__name__,
            error_message=str(exc)[:2000],
            state_trace=traces,
            partial_trajectory=[
                m.model_dump(mode="json") for m in getattr(orch, "trajectory", [])
            ],
        )
    save(path, entry)
    return entry


def summarize():
    """Summarize outcomes and costs while keeping unknown attempt usage unknown."""
    calls = [read(p) for p in (OUT / "requests").glob("*.json")]
    totals = collections.defaultdict(
        lambda: {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "unknown_usage_requests": 0,
        }
    )
    for call in calls:
        group = call["role"]
        t = totals[group]
        t["requests"] += 1
        usage = call.get("usage")
        if usage is None:
            t["unknown_usage_requests"] += 1
        else:
            t["prompt_tokens"] += usage.get("prompt_tokens", 0)
            t["completion_tokens"] += usage.get("completion_tokens", 0)
    outcomes = [read(p) for p in (OUT / "continuations").glob("*.json")]
    groups = collections.defaultdict(list)
    for row in outcomes:
        groups[(row["sample_id"], row["category"], row["arm"])].append(row)
    table = []
    for (sid, category, arm), values in sorted(groups.items()):
        completed = [v for v in values if v["status"] == "completed"]
        table.append(
            {
                "sample_id": sid,
                "category": category,
                "arm": arm,
                "planned_observed": len(values),
                "completed": len(completed),
                "errors": sum(v["status"] == "error" for v in values),
                "successes": sum(v["reward"] == 1 for v in completed),
                "success_rate": sum(v["reward"] == 1 for v in completed)
                / len(completed)
                if completed
                else None,
            }
        )
    save(
        OUT / "summary.json",
        {
            "request_accounting": dict(totals),
            "key_requests": dict(collections.Counter(c["key_index"] for c in calls)),
            "continuation_status": dict(
                collections.Counter(v["status"] for v in outcomes)
            ),
            "case_arms": table,
            "limit": "Exploratory selected candidates, provisional model reviews; no independent population causal or discovery-efficiency conclusion",
        },
    )
    if table:
        with (OUT / "case_outcomes.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    print(
        json.dumps(
            {
                "request_accounting": dict(totals),
                "outcomes": dict(collections.Counter(v["status"] for v in outcomes)),
            }
        ),
        flush=True,
    )


def main():
    """Execute one resumable phase; never overwrite completed original artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=["prepare", "probe", "screen", "review", "repair", "run", "summary"],
    )
    parser.add_argument("--key-file", default=str(ROOT / "api.txt"))
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    prepare()
    if args.phase in {"prepare", "summary"}:
        summarize()
        return
    setup(args.key_file, args.workers)
    if args.phase == "probe":
        from run_trial import probe

        def check(index, number):
            UNIT.set("probe:" + str(index + 1))
            KEY.set(index)
            probe(
                "luna",
                "openai/gpt-5.6-luna",
                {**llm_args(index), "max_completion_tokens": 128},
                OUT / "probes" / str(index + 1),
            )
            return index

        pool_jobs(list(range(4)), check, 4)
    elif args.phase == "screen":
        pool_jobs(read(OUT / "sample.json")["items"], screen_one, args.workers)
    elif args.phase == "review":
        panel = review_panel()
        pool_jobs(
            panel["candidates"] + panel["negative_checks"],
            lambda item, number: screen_one(
                item, number, "gpt-5.6-sol", "independent_reviews"
            ),
            args.workers,
        )
    elif args.phase == "repair":
        pool_jobs(read(OUT / "panel.json")["candidates"], repair_one, args.workers)
    elif args.phase == "run":
        cases = read(OUT / "approved_cases.json")["cases"]
        jobs = [
            (case, arm, rep)
            for rep in range(8)
            for case in cases
            for arm in ["resample", "fixed_original", "fixed_corrected"]
        ]
        pool_jobs(jobs, run_one, args.workers)
    summarize()


if __name__ == "__main__":
    main()
