"""Prepare or run isolated C2 search with exact caching and dollar gates."""

import argparse
import importlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

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
MAX_REPLY_ATTEMPTS = int(os.environ.get("P4_MAX_REPLY_ATTEMPTS", "30"))
# Method v2: skip the model judge on native seed/screening partner turns.
JUDGE_BRANCH_ONLY = os.environ.get("P4_JUDGE_BRANCH_ONLY") == "1"


STOP_RULE = "required_stop_missing_after_observed_private_goal"
RELAX = threading.local()


class ReplyAttemptCap(RuntimeError):
    """A state kept producing rejected partner replies."""


class ReplayMismatch(ReplyAttemptCap):
    """tau2 strict replay rejected a saved prefix at this state."""


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


def windows_safe_paths():
    """Map ':' in non-drive path parts to %3A so Windows never writes NTFS streams.

    Process-local; every Path construction (write, read, exists, glob) sees the same
    mapping, so historical colon-named unit files stay consistent within a run root.
    """
    if os.name != "nt":
        return
    import pathlib

    original = pathlib.PurePath.__init__
    if getattr(original, "_p4_colon_safe", False):
        return

    def init(self, *args):
        original(self, *args)
        safe = []
        for raw in self._raw_paths:
            drive, rest = os.path.splitdrive(raw)
            safe.append(drive + rest.replace(":", "%3A"))
        self._raw_paths = safe

    init._p4_colon_safe = True
    pathlib.PurePath.__init__ = init


def smoke_limits(s):
    """Opt-in tiny live run for a run root named *smoke*; frozen plan untouched."""
    limits = {
        name: os.environ.get(f"P4_SMOKE_{name.upper()}")
        for name in ["task", "expansions", "retests", "sol_checks"]
    }
    if not any(limits.values()):
        return None
    if "smoke" not in NEW.name:
        raise RuntimeError("P4_SMOKE_* limits are allowed only in a *smoke* run root")
    if limits["task"]:
        path = NEW / "step3" / "tasks.json"
        tasks = json.loads(path.read_text(encoding="utf-8"))
        if limits["task"] not in tasks:
            raise ValueError("P4_SMOKE_TASK is not a frozen step3 task id")
        path.write_text(
            json.dumps({limits["task"]: tasks[limits["task"]]}, indent=2) + "\n",
            encoding="utf-8",
        )
    counts = {"expand": 0, "retest": 0, "sol": 0}
    expand, check = s.expand, s.independent_check

    def limited_expand(*args, **kwargs):
        if counts["expand"] >= int(limits["expansions"] or 1):
            raise s.BudgetEnd("smoke expansion limit")
        counts["expand"] += 1
        return expand(*args, **kwargs)

    def limited_check(candidate, key, sol=False):
        name = "sol" if sol else "retest"
        limit = limits["sol_checks"] if sol else limits["retests"]
        if counts[name] >= int(limit or 0):
            raise s.BudgetEnd(f"smoke {name} limit")
        counts[name] += 1
        return check(candidate, key, sol)

    s.expand, s.independent_check = limited_expand, limited_check
    (NEW / "smoke_limits.json").write_text(json.dumps(limits, indent=2) + "\n")
    return limits


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
    original_build = getattr(getattr(c.x, "v6", None), "build", None)

    def build(task, prefix, *args, **kwargs):
        # tau2 strict replay can reject a prefix whose live tool outputs depended
        # on per-step environment syncs; keep the prefix for diagnosis and let
        # the screening loop skip the state instead of aborting the arm.
        orch = original_build(task, prefix, *args, **kwargs)
        initialize = orch.initialize

        def checked_initialize(*a, **k):
            try:
                return initialize(*a, **k)
            except ValueError as exc:
                if not str(exc).startswith("Tool call:"):
                    raise
                path = NEW / "replay_mismatches" / f"{time.time_ns()}.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "arm": arm,
                            "task_id": task.id,
                            "error": str(exc),
                            "prefix": prefix,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                store.event("replay_mismatch", {"arm": arm, "file": path.name})
                raise ReplayMismatch(str(exc)[:300]) from None

        orch.initialize = checked_initialize
        return orch

    if original_build:
        c.x.v6.build = build

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

    original_mechanical = getattr(c, "mechanical_check", None)

    def mechanical_check(*args, **kwargs):
        errors = original_mechanical(*args, **kwargs)
        if getattr(RELAX, "active", False) and STOP_RULE in errors:
            RELAX.used = True
            errors = [e for e in errors if e != STOP_RULE]
        return errors

    if original_mechanical:
        c.mechanical_check = mechanical_check
    original_digest = getattr(c.x.p4, "digest", None)

    def digest(obj):
        # Relaxed labels get their own cache key in both directions.
        if getattr(RELAX, "active", False) and isinstance(obj, dict):
            if "mechanical_version" in obj:
                obj = dict(obj, mechanical_version=obj["mechanical_version"] + "+stop")
        return original_digest(obj)

    if original_digest:
        c.x.p4.digest = digest

    def annotate(task, prefix, block, key, unit):
        # c2.sample_reply retries rejected replies without a bound. A partner model
        # that reports the observed private goal but never emits ###STOP### would
        # loop forever, so after MAX_REPLY_ATTEMPTS only that rule is relaxed
        # (recorded on the label); a hard cap stops any other runaway state.
        attempt = re.search(r":attempt(\d+)$", unit or "")
        n = int(attempt.group(1)) if attempt else 0
        if n >= MAX_REPLY_ATTEMPTS + 10:
            store.event("reply_attempt_cap", {"arm": arm, "unit": unit})
            raise ReplyAttemptCap(f"{unit}: {n} rejected attempts")
        if n < MAX_REPLY_ATTEMPTS:
            return checked(task, prefix, block, key, unit)
        RELAX.active, RELAX.used = True, False
        try:
            label = checked(task, prefix, block, key, unit)
        finally:
            RELAX.active = False
        if RELAX.used:
            label = dict(label, stop_rule_relaxed_after_attempts=n)
            store.event(
                "stop_rule_relaxed",
                {"arm": arm, "unit": unit, "valid": label.get("valid")},
            )
        return label

    def checked(task, prefix, block, key, unit):
        if not c.FULL_STYLE and native_turn_without_judge(unit):
            return program_only(task, prefix, block, unit)
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

    def program_only(task, prefix, block, unit):
        """Mechanical + DB checks only; no model judge (method v2 native turns)."""
        before = c.mech.replay(task.model_dump(mode="json"), prefix)
        after = c.mech.replay(task.model_dump(mode="json"), prefix + block)
        mechanical = c.mechanical_check(task, prefix, block, before, after)
        facts = c.mech.check_claims(
            prefix, block, after.environment, before.environment
        )
        mismatches = c.programmatic_scenario_violations(facts)
        store.event(
            "native_turn_program_only",
            {"arm": arm, "unit": unit, "valid": not (mechanical or mismatches)},
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
            "scenario_judgment_status": "method_v2 native seed/screening turn: programmatic checks only",
            "fact_check": facts,
        }

    c.annotate = annotate


def native_turn_without_judge(unit):
    """Method v2: native partner turns in seed/screening skip the model judge.

    Branched replies, persistent-generator turns and all retest/Sol turns are
    still judged.
    """
    if not JUDGE_BRANCH_ONLY or not unit:
        return False
    return bool(
        re.match(r"^seed_\d+:episode:turn\d+:attempt\d+$", unit)
        or (
            re.search(r":future_native:r\d+:turn\d+:attempt\d+$", unit)
            and ":retest:" not in unit
        )
    )


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


TURN_REPLY = re.compile(r"^(?P<base>.+):turn\d+$")


def archive_orphan_turns(arm_dir):
    """Move partner-turn replies of unfinished suffixes aside before resuming.

    run_suffix restarts an unfinished suffix from its branch reply and the agent
    regenerates its turns; reusing a cached later partner turn from the crashed
    run would splice it onto a different agent turn. Completed suffixes keep all
    their cached turns.
    """
    replies, done = arm_dir / "replies", arm_dir / "continuations"
    if not replies.exists():
        return 0
    finished = (
        {unquote(f.stem) for f in done.glob("*.json")} if done.exists() else set()
    )
    moved = 0
    for f in replies.glob("*.json"):
        match = TURN_REPLY.match(unquote(f.stem))
        if not match or match.group("base") in finished:
            continue
        if match.group("base").startswith("seed_"):
            continue
        target = arm_dir / "replies_orphaned" / f.name
        target.parent.mkdir(exist_ok=True)
        f.replace(target)
        moved += 1
    if moved:
        print(f"Archived {moved} orphaned partner-turn replies", flush=True)
    return moved


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
    windows_safe_paths()
    store = CostStore(NEW / "costs.sqlite", config)
    sys.path.insert(0, str(HISTORICAL))
    c = importlib.import_module("c2")
    s = importlib.import_module("search")
    smoke_limits(s)
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
        archive_orphan_turns(NEW / "step3" / "arms" / args.arm)
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
