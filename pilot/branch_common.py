"""Native prefix replay and continuation shared by B2 and the strong-agent script."""

import hashlib
import json
import os
from pathlib import Path

from pydantic import TypeAdapter
from run_trial import model_settings

from tau2.data_model.message import Message
from tau2.data_model.simulation import TextRunConfig
from tau2.data_model.tasks import InitialState, Task
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.runner import build_text_orchestrator
from tau2.runner.progress import run_with_retry

ROOT = Path(__file__).resolve().parents[1]
BRANCH = ROOT / "pilot/runs/branch"
MESSAGE_LIST = TypeAdapter(list[Message])


def write_json(path, data):
    """Atomically replace one JSON artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_key(path):
    """Load the first external token without storing it in configuration."""
    os.environ["PILOT_AUTODL_API_KEY"] = Path(path).read_text().split()[0]


def config(model=None, api_base=None, key_env=None):
    """Build the common default-mode settings, optionally replacing the agent."""
    luna, args = model_settings("luna")
    args["timeout"] = 120.0
    agent_args = dict(args)
    if api_base:
        agent_args["api_base"] = api_base
    if key_env:
        agent_args["api_key"] = "os.environ/" + key_env
    if model and "/" not in model:
        model = "openai/" + model
    return TextRunConfig(
        domain="telecom",
        task_split_name="base",
        agent="llm_agent",
        user="user_simulator",
        llm_agent=model or luna,
        llm_user=luna,
        llm_args_agent=agent_args,
        llm_args_user=dict(args),
        seed=0,
        max_steps=200,
        max_errors=10,
        auto_review=False,
        hallucination_retries=0,
        log_level="WARNING",
    )


def with_prefix(task, prefix):
    """Retain task initialization and replace only its message history."""
    copy = task.model_copy(deep=True)
    if copy.initial_state is None:
        copy.initial_state = InitialState()
    copy.initial_state.message_history = MESSAGE_LIST.validate_python(prefix)
    return copy


def token_totals(messages):
    """Count actual provider usage, separately for both generating roles."""
    totals = {k: {"agent": 0, "user": 0} for k in ["input", "output"]}
    for m in messages:
        if m["role"] not in ("assistant", "user"):
            continue
        usage = m.get("usage")
        if m.get("raw_data") and usage is None:
            raise ValueError("Missing generated-message usage")
        if usage is None:
            continue
        role = "agent" if m["role"] == "assistant" else "user"
        totals["input"][role] += usage["prompt_tokens"]
        totals["output"][role] += usage["completion_tokens"]
    return totals


def file_id(branch_id):
    """Use an explicit branch ID as its file name (Linux permits colons)."""
    if "/" in branch_id or ".." in branch_id:
        raise ValueError("Unsafe branch ID")
    return branch_id


def stable_seed(identifier):
    """Derive a distinct deterministic seed without Python's process-random hash."""
    return int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:4], "big") % (
        2**31 - 1
    )


def continue_prefix(task, prefix, seed, simulation_id, run_config=None):
    """Strictly replay, generate a suffix, then evaluate against the original task."""
    original = Task.model_validate(task) if isinstance(task, dict) else task
    cfg = run_config or config()

    def build():
        return build_text_orchestrator(
            cfg, with_prefix(original, prefix), seed=seed, simulation_id=simulation_id
        )

    # Replay errors must surface before the native transient-error retry handler.
    build().initialize()

    def execute():
        orch = build()
        sim = orch.run()
        sim.policy = orch.environment.get_policy()
        return sim

    sim = run_with_retry(
        execute,
        task=original,
        trial=0,
        seed=seed,
        max_retries=cfg.max_retries,
        retry_delay=cfg.retry_delay,
        console_display=False,
    )
    if sim.termination_reason == "infrastructure_error":
        write_json(
            BRANCH / "infrastructure_errors" / f"{file_id(simulation_id)}.json",
            sim.model_dump(mode="json"),
        )
        raise RuntimeError("Native continuation retries exhausted; failure saved")
    # Evaluation remains outside retries so strict full-trajectory replay bugs surface.
    sim.reward_info = evaluate_simulation(
        simulation=sim,
        task=original,
        domain="telecom",
        solo_mode=False,
        evaluation_type=EvaluationType.ALL,
    )
    data = sim.model_dump(mode="json")
    if data["termination_reason"] == "infrastructure_error":
        raise RuntimeError("Infrastructure failure")
    # Native replay only changes bookkeeping (timestamps/turn indices).
    fields = ("role", "content", "tool_calls", "id", "requestor")
    for old, new in zip(prefix, data["messages"][: len(prefix)], strict=True):
        if any(old.get(k) != new.get(k) for k in fields):
            raise ValueError("Replay changed prefix content")
    return data, token_totals(data["messages"][len(prefix) :])
