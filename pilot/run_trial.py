"""Small driver around tau2's native text runner; no additional retries."""

import argparse
import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot"
MODELS = {
    "local": "openai/gpt-oss-20b",
    "openrouter": "openrouter/openai/gpt-oss-20b",
    "mini": "gpt-4.1-mini-2025-04-14",
    "luna": "openai/gpt-5.6-luna",
}
USER = "gpt-4.1-2025-04-14"


def sample_tasks():
    """Sample in tau2's base-task file order, independently of run RNG."""
    from tau2.runner import load_tasks

    tasks = load_tasks("telecom", "base")
    assert len(tasks) == 114
    selected = random.Random(0).sample(tasks, 10)
    manifest = {
        "commit": "b7ea9074c1cba482b30687fecdb5c8425fd6f619",
        "sampling": "random.Random(0).sample(tau2.runner.load_tasks('telecom', 'base'), 10)",
        "task_ids": [t.id for t in selected],
    }
    path = PILOT / "sample.json"
    if path.exists():
        assert json.loads(path.read_text()) == manifest, "Saved sample changed"
    else:
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    return selected


def model_settings(candidate):
    """Read endpoint settings from the environment, never serialize keys."""
    model = MODELS[candidate]
    kwargs = {"temperature": 1.0}
    if candidate in ("local", "openrouter"):
        kwargs["reasoning_effort"] = "medium"
    if candidate == "local":
        base = os.environ.get("PILOT_VLLM_API_BASE")
        served = os.environ.get("PILOT_VLLM_MODEL")
        if not base or not served or "<" in base + served:
            raise ValueError("Set actual PILOT_VLLM_API_BASE and PILOT_VLLM_MODEL")
        model = "openai/" + served
        kwargs.update(api_base=base, allowed_openai_params=["reasoning_effort"])
    elif candidate == "mini":
        kwargs["api_base"] = "https://api.openai.com/v1"
    elif candidate == "luna":
        kwargs.update(
            api_base="https://www.autodl.art/api/v1",
            api_key="os.environ/PILOT_AUTODL_API_KEY",
            reasoning_effort="none",
            allowed_openai_params=["reasoning_effort"],
        )
    return model, kwargs


def probe(candidate, model, kwargs, directory):
    """Check automatic tool-call parsing and a tool-result round trip."""
    from tau2.data_model.message import SystemMessage, ToolMessage, UserMessage
    from tau2.environment.tool import Tool
    from tau2.utils.llm_utils import generate

    def pilot_echo(value: str) -> str:
        """Echo a value to verify tool calling.

        Args:
            value: Value to echo.
        """
        return value

    history = [
        SystemMessage(
            role="system",
            content="Call pilot_echo with value tau2-pilot. After the tool result, say done. Use the actual tool, not text describing a call.",
        ),
        UserMessage(role="user", content="Please run the check."),
    ]
    first = generate(
        model=model,
        messages=history,
        tools=[Tool(pilot_echo)],
        tool_choice="auto",
        **kwargs,
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{candidate}-tool-probe.json"
    path.write_text(
        json.dumps({"model": model, "first": first.model_dump(mode="json")}, indent=2)
        + "\n"
    )
    assert first.tool_calls and len(first.tool_calls) == 1, (
        f"No single structured tool call; see {path}"
    )
    call = first.tool_calls[0]
    assert call.name == "pilot_echo" and call.arguments == {"value": "tau2-pilot"}, (
        f"Unexpected tool call; see {path}"
    )
    history += [
        first,
        ToolMessage(
            role="tool",
            id=call.id,
            content=pilot_echo(**call.arguments),
            requestor="assistant",
        ),
    ]
    second = generate(model=model, messages=history, tools=[Tool(pilot_echo)], **kwargs)
    path.write_text(
        json.dumps(
            {
                "model": model,
                "first": first.model_dump(mode="json"),
                "second": second.model_dump(mode="json"),
            },
            indent=2,
        )
        + "\n"
    )
    assert second.content and not second.tool_calls, (
        f"Tool-result round trip failed; see {path}"
    )
    assert first.usage is not None and second.usage is not None, (
        f"Missing provider token usage; see {path}"
    )


def main():
    """Run one candidate/mode, or prepare the reproducible task sample."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=MODELS)
    parser.add_argument("--mode", choices=["default", "no-user"], default="default")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--autodl-key-file", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--iid", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=3)
    args = parser.parse_args()
    if args.autodl_key_file:
        keys = args.autodl_key_file.read_text().split()
        if not keys:
            parser.error("AutoDL key file is empty")
        os.environ["PILOT_AUTODL_API_KEY"] = keys[0]
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("env file does not exist")
        load_dotenv(args.env_file, override=True)
    # Do not let a proxy's global endpoint redirect the direct OpenAI reference.
    os.environ.pop("OPENAI_BASE_URL", None)
    os.environ.pop("OPENAI_API_BASE", None)
    tasks = sample_tasks()
    if args.iid:
        from tau2.runner import load_tasks

        if args.smoke or args.prepare or args.probe_only:
            parser.error("--iid cannot be combined with smoke, prepare, or probe")
        tasks = load_tasks("telecom", "base")
    if args.prepare:
        print((PILOT / "sample.json").read_text())
        return
    if not args.candidate:
        parser.error("--candidate is required except with --prepare")
    model, agent_args = model_settings(args.candidate)
    if args.iid:
        agent_args["timeout"] = 120.0
    required = []
    if args.candidate == "luna":
        required.append("PILOT_AUTODL_API_KEY")
    elif args.candidate == "mini" or (not args.probe_only and args.mode == "default"):
        required.append("OPENAI_API_KEY")
    if args.candidate == "openrouter":
        required.append("OPENROUTER_API_KEY")
    for name in required:
        if not os.environ.get(name):
            parser.error(f"Missing {name}; supply an env file or export it")
    if args.candidate == "local" and os.environ.get("PILOT_VLLM_API_KEY"):
        # LiteLLM resolves this reference internally; only the reference is saved.
        agent_args["api_key"] = "os.environ/PILOT_VLLM_API_KEY"
    elif args.candidate == "local":
        agent_args["api_key"] = "EMPTY"
    base = PILOT / "runs" / ("smoke" if args.smoke else "trial")
    if args.iid:
        base = PILOT / "runs/iid"
    if args.probe_only:
        probe(args.candidate, model, agent_args, base / "probes")
        return
    from solo_compat import register_pilot_dummy_user

    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner import run_domain

    solo_user = register_pilot_dummy_user()

    if args.smoke:
        tasks = tasks[:1]
    count = 1 if args.smoke else (4 if args.mode == "default" else 2)
    if args.iid:
        count = 8 if args.mode == "default" else 4
    directory = base / args.mode if args.iid else base / args.candidate / args.mode
    if (directory / "results.json").exists() and not args.resume:
        parser.error("Results exist; use --resume explicitly to use tau2's resume")
    config = TextRunConfig(
        domain="telecom",
        task_split_name="base",
        task_ids=[t.id for t in tasks],
        agent="llm_agent_solo" if args.mode == "no-user" else "llm_agent",
        user=solo_user if args.mode == "no-user" else "user_simulator",
        llm_agent=model,
        llm_args_agent=agent_args,
        llm_user=model if args.candidate == "luna" else USER,
        llm_args_user=(
            dict(agent_args)
            if args.candidate == "luna"
            else {"temperature": 1.0, "api_base": "https://api.openai.com/v1"}
        ),
        num_trials=count,
        seed=0,
        max_steps=200,
        max_errors=10,
        max_concurrency=args.max_concurrency,
        auto_resume=args.resume,
        save_to=str(directory.resolve()),
        log_level="WARNING",
        auto_review=False,
        hallucination_retries=0,
    )
    config.validate()
    directory.mkdir(parents=True, exist_ok=True)
    if args.resume and (directory / "results.json").exists():
        previous = json.loads((directory / "config.json").read_text())
        current = config.model_dump(mode="json")
        previous.pop("auto_resume", None)
        current.pop("auto_resume", None)
        # Transport-only changes are allowed; sampling settings must match.
        if args.iid:
            for saved in (previous, current):
                saved.pop("max_concurrency", None)
                for role in ("llm_args_agent", "llm_args_user"):
                    saved[role].pop("timeout", None)
        if previous != current:
            raise ValueError("Refusing to resume with changed run settings")
        archive = directory / "history" / str(time.time_ns())
        archive.mkdir(parents=True)
        for name in ("results.json", "config.json", "batch_timing.json"):
            path = directory / name
            if path.exists():
                (archive / name).write_bytes(path.read_bytes())
    (directory / "config.json").write_text(config.model_dump_json(indent=2) + "\n")
    if args.iid:
        from transport import configure_transport

        configure_transport(args.max_concurrency)
    started = time.perf_counter()
    results = run_domain(config)
    elapsed = time.perf_counter() - started
    (directory / "batch_timing.json").write_text(
        json.dumps({"wall_seconds": elapsed, "resume": args.resume}, indent=2) + "\n"
    )
    sims = results.simulations
    assert len(sims) == len(tasks) * count, "Native runner returned an incomplete batch"
    assert len({(s.task_id, s.trial) for s in sims}) == len(sims), "Duplicate runs"
    errors = [
        s.id
        for s in sims
        if s.termination_reason == "infrastructure_error" or s.reward_info is None
    ]
    if errors:
        raise RuntimeError(
            f"Infrastructure failures retained in {directory / 'results.json'}: {errors}"
        )
    print(f"Completed {len(sims)} runs: {directory / 'results.json'}")


if __name__ == "__main__":
    main()
