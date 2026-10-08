"""Offline-compatible judgment caching, evidence projection and dollar reservations."""

import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

VERSION = "cost-control-v1"
PURE_REQUEST = re.compile(
    r"(?:could you|can you|please)\s+(?:please\s+)?"
    r"(?:run (?:a |the )?speed test(?: for me)?|"
    r"check (?:my |the )?(?:phone.s current )?network mode(?: for me)?|"
    r"(?:tell me how to|guide me to|have me) "
    r"(?:run (?:a |the )?speed test(?: myself)?|"
    r"check (?:my |the )?(?:phone.s current )?network mode(?: myself)?))"
    r"[.!?]*",
    re.I,
)


def canonical(value):
    """Serialize semantic evidence deterministically."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_only(block):
    """Recognize a small explicit set of fact-free, goal-preserving requests."""
    users = [m for m in block if m["role"] == "user"]
    return (
        len(users) == 1
        and len(block) == 1
        and not users[0].get("tool_calls")
        and bool(PURE_REQUEST.fullmatch((users[0].get("content") or "").strip()))
    )


DB_REPORT = re.compile(
    r"(?:my )?(?:mobile data|data saver|data roaming|airplane mode) is "
    r"(?:on|off|enabled|disabled)[.!]*|"
    r"(?:my )?vpn is (?:connected|disconnected)[.!]*|"
    r"(?:my )?(?:preferred )?network mode is (?:set to )?(?:2g|4g/5g preferred)[.!]*",
    re.I,
)


def db_report_only(block):
    """Recognize a single current-state report; values still require DB verification."""
    return (
        len(block) == 1
        and block[0]["role"] == "user"
        and not block[0].get("tool_calls")
        and bool(DB_REPORT.fullmatch((block[0].get("content") or "").strip()))
    )


def compact_payload(payload):
    """Build a shadow evidence view; it is not an approved replacement judge input."""
    facts = payload.get("programmatic_fact_check") or {}
    fields = {c["field"] for c in facts.get("claims", [])}

    def select(tree):
        result = {}

        def walk(value, prefix=""):
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, f"{prefix}.{key}" if prefix else key)
            elif prefix in fields:
                result[prefix] = value

        walk(tree)
        return result

    history = payload.get("visible_prior_history") or []
    relevant_tools = {
        o.get("tool")
        for claim in facts.get("claims", [])
        for field in ["field_read_observations", "matching_tool_observations"]
        for o in claim.get(field, [])
    }
    call_names = {
        call["id"]: call.get("name") or call.get("function", {}).get("name")
        for message in history
        for call in message.get("tool_calls") or []
    }
    related = [
        {"index": i, "message": message}
        for i, message in enumerate(history)
        if any(
            (call.get("name") or call.get("function", {}).get("name")) in relevant_tools
            for call in message.get("tool_calls") or []
        )
        or (
            message.get("role") == "tool"
            and call_names.get(message.get("tool_call_id")) in relevant_tools
        )
    ]
    return {
        "rule_texts": payload["rule_texts"],
        "private_scenario_verbatim": payload.get("private_scenario_verbatim"),
        "partner_block": payload["partner_block"],
        "last_agent_request": next(
            (
                m
                for m in reversed(history)
                if m.get("role") == "user" and m.get("content")
            ),
            None,
        ),
        "related_history": related,
        "private_state_before": select(payload.get("private_state_before") or {}),
        "private_state_after": select(payload.get("private_state_after") or {}),
        "programmatic_fact_check": facts,
        "programmatic_current_fact_mismatches": payload.get(
            "programmatic_current_fact_mismatches", []
        ),
        "validation_status": "shadow_only; historical/converted message indices may differ; full-history judge remains authoritative",
    }


class BudgetStop(BaseException):
    """Stop sending requests at a configured dollar allowance."""


class CostStore:
    """Share durable cost reservations and exact judgment cache across arm processes."""

    def __init__(self, path, config):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, arm TEXT, model TEXT, role TEXT, status TEXT, reserved REAL, charged REAL, input_tokens INTEGER, output_tokens INTEGER, task_id TEXT, phase TEXT, started REAL, finished REAL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (time REAL, kind TEXT, detail TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)"
            )
            frozen = canonical(config)
            old = db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            if old and old[0] != frozen:
                raise ValueError(
                    "Budget/pricing config differs from this ledger; use a new ledger"
                )
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('config',?)", (frozen,))

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def event(self, kind, detail):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events VALUES (?,?,?)",
                (time.time(), kind, canonical(detail)),
            )

    def price(self, model, input_tokens=0):
        rates = self.config["rates_per_million"].get(model.removeprefix("openrouter/"))
        if not rates or rates.get("input") is None or rates.get("output") is None:
            raise BudgetStop(
                f"No verified provider dollar rates configured for {model}"
            )
        rates = dict(rates)
        for tier in rates.get("overrides", []):
            if input_tokens >= tier["min_prompt_tokens"]:
                rates.update(
                    input=float(tier["prompt"]) * 1e6,
                    output=float(tier["completion"]) * 1e6,
                    cached_input=float(tier.get("input_cache_read", tier["prompt"]))
                    * 1e6,
                )
        if (
            min(
                rates["input"],
                rates["output"],
                (
                    rates.get("cached_input")
                    if rates.get("cached_input") is not None
                    else rates["input"]
                ),
            )
            < 0
        ):
            raise ValueError("Rates must be nonnegative")
        return rates

    def reserve(self, arm, model, role, inputs, outputs, task_id=None, phase=None):
        rates = self.price(model, inputs)
        amount = (inputs * rates["input"] + outputs * rates["output"]) / 1e6
        ident = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT arm,model,COALESCE(charged,reserved) FROM calls"
            ).fetchall()
            scopes = [
                ("total", sum(r[2] for r in rows), self.config["total_usd_cap"]),
                (
                    "arm",
                    sum(r[2] for r in rows if r[0] == arm),
                    self.config.get("arm_usd_caps", {}).get(
                        arm, self.config["arm_usd_cap"]
                    ),
                ),
                (
                    "sol",
                    sum(r[2] for r in rows if "sol" in r[1].lower()),
                    self.config["sol_usd_cap"],
                ),
            ]
            if "sol" in model.lower() and arm in self.config.get("sol_usd_caps", {}):
                scopes.append(
                    (
                        "arm_sol",
                        sum(
                            r[2] for r in rows if r[0] == arm and "sol" in r[1].lower()
                        ),
                        self.config["sol_usd_caps"][arm],
                    )
                )
            for scope, spent, cap in scopes:
                if scope == "sol" and "sol" not in model.lower():
                    continue
                if cap is None or spent + amount > cap:
                    raise BudgetStop(f"{scope} dollar reservation exceeds cap")
            db.execute(
                "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    arm,
                    model,
                    role,
                    "inflight",
                    amount,
                    None,
                    inputs,
                    outputs,
                    task_id,
                    phase,
                    time.time(),
                    None,
                ),
            )
        return ident

    def settle(self, ident, usage=None):
        with self.connect() as db:
            row = db.execute("SELECT model FROM calls WHERE id=?", (ident,)).fetchone()
            if (
                usage is None
                or not any(k in usage for k in ["prompt_tokens", "input_tokens"])
                or not any(k in usage for k in ["completion_tokens", "output_tokens"])
            ):
                db.execute(
                    "UPDATE calls SET status='unknown',finished=? WHERE id=?",
                    (time.time(), ident),
                )
                return
            inputs = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            outputs = usage.get("completion_tokens", usage.get("output_tokens", 0))
            rates = self.price(row[0], inputs)
            details = usage.get("prompt_tokens_details") or {}
            cached = min(inputs, details.get("cached_tokens") or 0)
            cost = (
                (inputs - cached) * rates["input"]
                + cached
                * (
                    rates.get("cached_input")
                    if rates.get("cached_input") is not None
                    else rates["input"]
                )
                + outputs * rates["output"]
            ) / 1e6
            if isinstance(usage.get("cost"), (int, float)):
                cost = usage["cost"]
            db.execute(
                "UPDATE calls SET status='response',charged=?,input_tokens=?,output_tokens=?,finished=? WHERE id=?",
                (cost, inputs, outputs, time.time(), ident),
            )

    def recover(self):
        """Keep interrupted reservations charged conservatively when no usage returned."""
        with self.connect() as db:
            db.execute("UPDATE calls SET status='unknown' WHERE status='inflight'")

    def cached(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO cache VALUES (?,?)", (key, canonical(value))
            )

    def totals(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT arm,model,role,status,COUNT(*),SUM(COALESCE(charged,reserved)) FROM calls GROUP BY arm,model,role,status"
            ).fetchall()
        return [
            dict(zip(["arm", "model", "role", "status", "calls", "usd"], r))
            for r in rows
        ]


def judge_key(model, messages, settings):
    """Cache the full exact decision input, rule prompt and model settings."""
    return hashlib.sha256(
        canonical(
            {
                "version": VERSION,
                "model": model,
                "messages": messages,
                "settings": settings,
            }
        ).encode()
    ).hexdigest()


def input_upper_bound(messages, tools=None):
    """Reserve full UTF-8 bytes plus message overhead, without assuming cache discount."""
    return (
        len(canonical({"messages": messages, "tools": tools}).encode())
        + 4096
        + 64 * len(messages)
    )


def valid_judgment(content, payload):
    """Cache only schema-complete joint decisions, including valid rejection decisions."""
    try:
        obj = json.loads(content)
        for axis, field in [
            ("style_and_persona", "assessed_style_rule_ids"),
            ("scenario", "assessed_scenario_rule_ids"),
        ]:
            expected = {r["rule_id"] for r in payload["rule_texts"][axis]}
            if set(obj[field]) != expected:
                return False
        for field, axis in [
            ("style_departures", "style_and_persona"),
            ("scenario_violations", "scenario"),
        ]:
            expected = {r["rule_id"] for r in payload["rule_texts"][axis]}
            if not isinstance(obj[field], list) or any(
                r["rule_id"] not in expected for r in obj[field]
            ):
                return False
        return True
    except (ValueError, KeyError, TypeError):
        return False
