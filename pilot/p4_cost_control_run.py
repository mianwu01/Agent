"""Prepare or run isolated C2 search with exact caching and dollar gates."""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from p4_cost_control import (
    BudgetStop,
    CostStore,
    canonical,
    compact_payload,
    db_report_only,
    input_upper_bound,
    judge_key,
    request_only,
    valid_judgment,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "pilot/runs/p4"
HISTORICAL = BASE / "v7_c2_report_20261006_r2"
NEW = Path(os.environ.get("P4_RUN_ROOT", str(BASE / "v7_c3_cost_control_20261008")))


def prepare():
    """Write a new experiment plan, retaining historical outputs unchanged."""
    NEW.mkdir(exist_ok=True)
    config = {
        "total_usd_cap": None,
        "arm_usd_cap": None,
        "sol_usd_cap": None,
        "rates_per_million": {
            m: {"input": None, "output": None, "cached_input": None}
            for m in [
                "openai/gpt-5.6-luna",
                "openai/gpt-5.6-sol",
                "openai/gpt-6-luna",
                "openai/DeepSeek-V4.1-Flash",
            ]
        },
        "pricing_source": "fill verified provider billing rates; no guessed OpenAI pricing",
    }
    if not (NEW / "billing_config.json").exists():
        (NEW / "billing_config.json").write_text(json.dumps(config, indent=2) + "\n")
    for name in [
        "plan.json",
        "tasks.json",
        "cost_projection.json",
        "model_catalog.json",
        "plan_amendment_r2.json",
    ]:
        source = BASE / "v7_c2_step3_20261006_r2" / name
        target = NEW / "step3" / name
        target.parent.mkdir(exist_ok=True)
        if source.exists() and not target.exists():
            target.write_bytes(source.read_bytes())
    amendment = {
        "new_model_calls": 0,
        "enabled": [
            "native mechanical checks",
            "exact full-input Sol judgment cache shared across arms",
            "fact-free request whitelist with native mechanical checks",
            "per-arm/global/Sol dollar reservation gates",
            "unknown request reserves retained",
            "native temperature1.0 and screening/retest sizes unchanged",
        ],
        "validation_pending": [
            "compact evidence Sol vs full input Sol",
            "Luna full-input vs Sol full-input",
        ],
        "compact_or_luna_authoritative": False,
        "full_style_only_after_confirmation": True,
        "currency": "USD at configured provider rates; exact requested model priced, cached-input discount applied only if configured and usage confirms it",
        "budget": "Identical per-arm USD cap replaces token budget as primary comparison; original token cap is a secondary ceiling. Total/Sol caps may stop arms early; incomplete arms reported, never compared as completed.",
        "historical": "Historical runs remain evidence, not combined with fresh optimized arms. Existing balance stop remains effective.",
        "metrics": [
            "distinct verified cases per dollar by class",
            "in_rule and all-valid separately",
            "cumulative cases vs dollars",
            "token/suffix auxiliary counts",
            "screen-to-retest survival",
        ],
    }
    (NEW / "cost_control_amendment.json").write_text(
        json.dumps(amendment, ensure_ascii=False, indent=2) + "\n"
    )
    return NEW


def stop_paths():
    """Do not carry a different provider's balance/auth stop into OpenRouter."""
    current = [
        NEW / "balance_stop.json",
        NEW / "authentication_stop.json",
        NEW / "regional_stop.json",
        NEW / "protocol_stop.json",
    ]
    if not any(
        p.exists()
        for p in [NEW / "provider_config.json", NEW / "openrouter/provider_config.json"]
    ):
        current += [
            HISTORICAL / "balance_stop.json",
            HISTORICAL / "authentication_stop.json",
        ]
    return current


def install(c, store, arm):
    """Install cost and judgment controls after native transport setup."""
    original_call = c.x.p4.audited_completion

    def paid(**kwargs):
        for stop in stop_paths():
            if stop.exists():
                raise RuntimeError(f"No requests while stop marker exists: {stop.name}")
        reserve = store.reserve(
            arm,
            kwargs["model"],
            c.x.p4.ROLE.get(),
            input_upper_bound(kwargs["messages"], kwargs.get("tools")),
            kwargs.get("max_completion_tokens") or 8192,
            task_id=sys.modules["search"].TASK.get()
            if "search" in sys.modules
            else None,
            phase=sys.modules["search"].PHASE.get()
            if "search" in sys.modules
            else "validation",
        )
        try:
            result = original_call(**kwargs)
        except BaseException:
            store.settle(reserve)
            raise
        usage = result.usage
        store.settle(
            reserve, usage.model_dump() if hasattr(usage, "model_dump") else usage
        )
        return result

    c.x.p4.audited_completion = paid
    original_generate = c.x.p4.llm_utils.generate

    def generate(**kwargs):
        if c.x.p4.ROLE.get() != "rule_labeler":
            return original_generate(**kwargs)
        messages = [
            m.model_dump(mode="json") if hasattr(m, "model_dump") else m
            for m in kwargs["messages"]
        ]
        try:
            payload = json.loads(messages[-1]["content"])["input"]
        except (ValueError, KeyError, TypeError):
            return original_generate(**kwargs)
        settings = {
            k: kwargs.get(k)
            for k in [
                "temperature",
                "reasoning_effort",
                "max_completion_tokens",
                "response_format",
                "api_base",
            ]
        }
        key = judge_key(kwargs["model"], messages, settings)
        cached = store.cached(key)
        if cached:
            store.event(
                "exact_judge_cache_hit",
                {"key": key, "arm": arm, "model": kwargs["model"]},
            )
            return SimpleNamespace(content=cached["content"])
        # Evidence projection is saved for validation, never sent as the live input.
        shadow = NEW / "shadow_inputs" / f"{key}.json"
        shadow.parent.mkdir(exist_ok=True)
        if not shadow.exists():
            shadow.write_text(
                canonical({"full": payload, "compact": compact_payload(payload)}) + "\n"
            )
        response = original_generate(**kwargs)
        if valid_judgment(response.content, payload):
            store.cache(
                key, {"content": response.content, "requested_model": kwargs["model"]}
            )
        return response

    c.x.p4.llm_utils.generate = generate
    old_annotate = c.annotate

    def annotate(task, prefix, block, key, unit):
        pure_request = request_only(block)
        pure_report = db_report_only(block)
        if c.FULL_STYLE or not (pure_request or pure_report):
            return old_annotate(task, prefix, block, key, unit)
        before = c.mech.replay(task.model_dump(mode="json"), prefix)
        after = c.mech.replay(task.model_dump(mode="json"), prefix + block)
        mechanical = c.mechanical_check(task, prefix, block, before, after)
        facts = (
            c.mech.check_claims(prefix, block, after.environment, before.environment)
            if pure_report
            else None
        )
        if pure_report and (
            not facts.get("claims") or facts.get("unassessed_device_sentences")
        ):
            return old_annotate(task, prefix, block, key, unit)
        mismatches = c.programmatic_scenario_violations(facts) if pure_report else []
        store.event(
            "programmatic_request_or_db_report",
            {
                "arm": arm,
                "unit": unit,
                "mechanical_rejection": bool(mechanical),
                "scenario_rejection": bool(mismatches),
                "pure_report": pure_report,
            },
        )
        return {
            "model_judgment": False,
            "model_requested": None,
            "temperature": None,
            "mechanical_violations": mechanical,
            "programmatic_scenario_violations": mismatches,
            "model_scenario_violations": [],
            "scenario_violations": bool(mismatches),
            "valid": not (mechanical or mismatches),
            "style": "unassessed",
            "departed_style_rules": [],
            "all_style_rule_labels": [],
            "all_scenario_rule_labels": [],
            "scenario_judgment_status": "programmatic exact device request / DB-verified current report",
            "fact_check": facts,
            "classification_standard": "style/persona still assessed after confirmation; no narrative/fact/goal-change text permitted by whitelist",
        }

    c.annotate = annotate


def provider_setup(c):
    """Select a process-local provider, preserving historical transport and evidence."""
    path = NEW / "provider_config.json"
    if not path.exists():
        path = NEW / "openrouter/provider_config.json"
    if not path.exists():
        return
    import c2_auth_transport

    provider = json.loads(path.read_text())
    if provider.get("wire_api") == "responses":
        import p4_responses_transport as provider_transport
    else:
        import p4_openrouter_transport as provider_transport
    c2_auth_transport.install = lambda runtime, workers: provider_transport.install(
        runtime, workers, provider
    )

    original_config = c.x.p4.config

    def same_historical_agent(*args, **kwargs):
        cfg = original_config(*args, **kwargs)
        cfg.llm_agent = cfg.llm_user = "openai/gpt-5.6-luna"
        return cfg

    c.x.p4.config = same_historical_agent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--arm", choices=["A0", "A1", "A2", "A3", "A4"])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    prepare()
    if not args.run:
        print(f"Prepared {NEW}; no API calls")
        return
    if not args.arm:
        parser.error("--run requires --arm")
    # Check before importing provider/framework modules or reading credentials.
    for stop in stop_paths():
        if stop.exists():
            raise RuntimeError(f"Existing {stop.name}: no API calls")
    config = json.loads((NEW / "billing_config.json").read_text())
    if any(config[k] is None for k in ["total_usd_cap", "arm_usd_cap", "sol_usd_cap"]):
        raise RuntimeError(
            "Dollar caps and verified prices must be supplied before running"
        )
    store = CostStore(NEW / "costs.sqlite", config)
    sys.path.insert(0, str(HISTORICAL))
    c = importlib.import_module("c2")
    s = importlib.import_module("search")
    c.OUT = NEW
    c.D["step3"] = NEW / "step3"
    provider_setup(c)
    original_setup = c.setup
    c.rules_path = lambda: BASE / "v7_c2_step1_20261006_r2/rules_v2.json"

    def setup(step, workers=4):
        original_setup(step, workers)
        install(c, store, args.arm)

    c.setup = setup
    try:
        s.run_arm(args.arm, args.workers)
    except BudgetStop as exc:
        (NEW / f"{args.arm}_run_status.json").write_text(
            json.dumps(
                {
                    "complete": False,
                    "reason": str(exc),
                    "status": "stopped_dollar_cap_or_missing_price",
                }
            )
            + "\n"
        )
    else:
        (NEW / f"{args.arm}_run_status.json").write_text(
            json.dumps({"complete": True}) + "\n"
        )
    finally:
        (NEW / f"{args.arm}_dollar_accounting.json").write_text(
            json.dumps(store.totals(), indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
