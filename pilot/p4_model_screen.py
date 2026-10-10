"""Screen OpenRouter replacements for Luna on the saved 10-task telecom sample.

Agent and partner use the same candidate, as in the Luna runs: temperature 1.0,
reasoning disabled, one pinned OpenRouter provider with fallbacks disabled.
Native runner and evaluator; no added retries.
"""

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot"
OUT = PILOT / "runs/p4/v7_c5_openrouter_us_20261009/agent_screen"

# Providers chosen by the interface screen (first-party where the account allows it).
PROVIDERS = {
    "deepseek/deepseek-v4.1-flash": "Fireworks",
    "qwen/qwen3.8-flash": "Alibaba",
    "qwen/qwen3.7-flash": "Alibaba",
    "xiaomi/mimo-v2.6-flash": "Xiaomi",
    "minimax/minimax-m3": "Minimax",
    "qwen/qwen3.7-plus": "Alibaba",
    "mistralai/mistral-large-4-0": "Mistral",
    "xiaomi/mimo-v2.6-pro": "Xiaomi",
    "qwen/qwen3.7-max": "Alibaba",
    "deepseek/deepseek-v4-pro": "Azure",
    "moonshotai/kimi-k3": "Fireworks",
    "anthropic/claude-sonnet-4.6": "Anthropic",
    "anthropic/claude-opus-4.6": "Anthropic",
}


def load_key(path):
    raw = Path(path).read_text(encoding="utf-8")
    match = re.search(r"sk-or-[A-Za-z0-9\-_]+", raw)
    return match.group(0) if match else raw.strip()


def llm_args(model):
    return {
        "temperature": 1.0,
        "api_key": "os.environ/OPENROUTER_API_KEY",
        "num_retries": 0,
        "timeout": 180.0,
        "extra_body": {
            "provider": {"order": [PROVIDERS[model]], "allow_fallbacks": False},
            "reasoning": {"enabled": False},
            "usage": {"include": True},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=PROVIDERS)
    parser.add_argument("--key-file", default=str(ROOT / "api/api.txt"))
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--tasks", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--tag", default="")
    parser.add_argument("--all-tasks", action="store_true", help="all 114 base tasks")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--task-prefix", default="", help="e.g. [mobile_data_issue]")
    args = parser.parse_args()
    os.environ["OPENROUTER_API_KEY"] = load_key(args.key_file)
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        os.environ.pop(name, None)

    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner import run_domain

    if args.all_tasks:
        from tau2.runner import load_tasks

        task_ids = [
            t.id
            for t in load_tasks("telecom", "base")
            if t.id.startswith(args.task_prefix)
        ]
    else:
        task_ids = json.loads((PILOT / "sample.json").read_text())["task_ids"]
        task_ids = task_ids[: args.tasks]
    name = args.model.replace("/", "__") + (f"_{args.tag}" if args.tag else "")
    directory = Path(args.out) / name
    if (directory / "results.json").exists():
        parser.error(f"Results exist: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    model = "openrouter/" + args.model
    config = TextRunConfig(
        domain="telecom",
        task_split_name="base",
        task_ids=task_ids,
        agent="llm_agent",
        user="user_simulator",
        llm_agent=model,
        llm_args_agent=llm_args(args.model),
        llm_user=model,
        llm_args_user=llm_args(args.model),
        num_trials=args.trials,
        seed=0,
        max_steps=200,
        max_errors=10,
        max_concurrency=args.concurrency,
        save_to=str(directory.resolve()),
        log_level="WARNING",
        auto_review=False,
        hallucination_retries=0,
    )
    config.validate()
    run_domain(config)


if __name__ == "__main__":
    main()
