"""P4 C2 frozen native rule inventory, proposal/check separation and audits."""

# ruff: noqa: E402
import argparse
import hashlib
import json
import math
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = OUT.parent
sys.path.insert(0, str(BASE / "v7_b2_report_20261005"))
import b2 as x
import mechanical as mech
from run_branch import proposal_messages

from tau2.data_model.message import SystemMessage, UserMessage

D = {s: BASE / f"v7_c2_{s}_20261006_r2" for s in ["step1", "step2", "step3"]}
read, save = x.read, x.save
SOL = x.SOL
VS_INSTRUCTION = """Sample k=5 candidate next user decisions with verbalized probabilities. Return json {"candidates":[{"message":"text or null","tool_calls":[{"name":"tool name","arguments":{}}],"probability":0.2}, ...]}. Each candidate represents a native user message. Return exactly five candidates. One will be sampled uniformly from the five; probabilities are recorded, not used as weights."""
LABEL_PROMPT = """You are Sol t=0, a model annotator, not a human. Jointly assess EVERY supplied style/persona and scenario rule against the executed partner block, private state and history. Applicability: grounding/read-result rules concern assertions or reports of device facts, not a clarification question that asserts no device fact. Asking for clarification or reassurance continues the conversation and does not by itself violate continuing until task completion. Tool-menu options are descriptive alternatives, not an obligation to execute a tool immediately. Before flagging a departure, identify the rule trigger and a concrete contradictory act; quote evidence, not merely a question. Specific native persona requirements guide generic cooperation rules: confusion, anxiety, reassurance or inability to follow steps are in_rule where the persona requires them. Other independent departures still count. Persona never overrides mechanical/scenario rules. Do not force any case to be in_rule. Style departures are kept, never invalidated. Scenario violations mean changing the task goal or confidently asserting a device fact contrary to DB as if observed; vague, uncertain, partial or unobserved true facts are not violations by themselves. Historical statements use historical observations. Programs judge mechanics. Do not infer intent, sabotage, capability or reward. Return json {"assessed_style_rule_ids":[all style AND persona IDs],"assessed_scenario_rule_ids":[all scenario IDs],"style_departures":[{"rule_id":"...","evidence":"short verbatim evidence"}],"scenario_violations":[{"rule_id":"...","evidence":"inconsistent asserted fact and DB"}]}. Assess all listed rules, list EVERY applicable assessed ID even when there is no departure; empty exception lists explicitly mean all assessed rules in_rule/no violations. Do not repeat compliant rules with evidence."""

ACTIVE = None
RULES = None
LOCAL = threading.local()
FULL_STYLE = True


def rules_path():
    newer = D["step1"] / "rules_v2.json"
    return newer if newer.exists() else D["step1"] / "rules.json"


def program_format_style(block):
    departed = any(
        m.get("tool_calls") and (m.get("content") or "").strip()
        for m in block
        if m["role"] == "user"
    )
    return {
        "rule_id": "r_5112db5336c2d337",
        "status": "out_of_rule" if departed else "in_rule",
        "evidence": "native content+tools occur in the same user decision"
        if departed
        else "no same-decision nonempty text with tool calls",
        "origin": "programmatic native message fields",
    }


def programmatic_scenario_violations(facts):
    confident = []
    for fact in facts["claims"]:
        historical = re.search(
            r"\b(?:was|were|previously|before|used to)\b", fact["matched"], re.I
        )
        uncertain = re.search(
            r"\b(?:I think|maybe|not sure|might|possibly|I guess|not certain)\b",
            fact["quote"],
            re.I,
        )
        if not historical and not uncertain and not fact["db_matches"]:
            confident.append(fact)
    return confident


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def setup(step, workers=8):
    """Configure the current audited transport without historical credential routing."""
    global ACTIVE, RULES
    import c2_auth_transport as transport

    ACTIVE = D[step]
    ACTIVE.mkdir(parents=True, exist_ok=True)
    x.D = {step: ACTIVE}
    x.b.D = {step: ACTIVE}
    x.b.OUT = OUT
    x.v6.OUT = ACTIVE
    x.b.paired.OUT = ACTIVE
    x.p4.OUT = ACTIVE
    if not x.b.SETUP_ACTIVE:
        x.b.SETUP_ACTIVE = True
        transport.install(sys.modules[__name__], workers)
    RULES = read(rules_path())


def rule_category(quote, source):
    """Freeze a project-level interpretation without examining any outcomes."""
    text = quote.lower().lstrip("- ")
    if any(
        k in text
        for k in [
            "avoid repeating",
            "wait for the agent to ask",
            "only share information",
            "tool call does not return updated",
            "technical skills",
            "technical knowledge",
            "tech enthusiast",
            "precious photos",
        ]
    ):
        return "style"
    if "only do this after the agent" in text:
        return "mechanical"
    if source == "scenario" and any(
        k in text
        for k in [
            "at home",
            "united states",
            "mobile data is not",
            "either stops",
            "unable to send",
            "years old",
            "41-year-old",
        ]
    ):
        return "scenario"
    if any(
        k in text
        for k in [
            "###stop###",
            "###transfer###",
            "###out-of-scope###",
            "results of tool calls, always",
            "never make up the results",
            "never make up the results of tool calls",
            "messages when performing tool calls",
            "cannot do both at the same time",
            "generate one message at a time",
        ]
    ):
        return "mechanical"
    if any(
        k in text
        for k in [
            "follow their guidance",
            "frustration",
            "whenever the agent asks",
            "for example:",
            "always ground your response",
            "unsure about whether",
            "one action at",
            "multiple actions",
            "ask clarifying",
            "clarification",
            "only call a tool if",
            "disclose information",
            "paraphrasing",
            "natural conversation",
            "tone",
            "persona",
            "personality",
            "you are playing the role",
            "goal is to simulate realistic",
            "you have some tools",
            "continue the conversation",
            "remember:",
        ]
    ):
        return "style"
    if source == "guidelines" and text.startswith(
        ("at each turn", "send a message", "make a tool call")
    ):
        return "mechanical"
    if source == "guidelines" and "grounded in" in text:
        return "scenario"
    if source == "guidelines" and "error in a tool call" in text:
        return "style"
    if source == "guidelines" and (
        "strictly follow" in text or "never make up or hallucinate" in text
    ):
        return "scenario"
    if source == "scenario" and not any(
        k in text
        for k in [
            "willing",
            "resolved",
            "want",
            "access",
            "you are john",
            "france",
            "information",
            "name",
            "phone",
            "known",
            "unknown",
            "domain",
            "telecom",
        ]
    ):
        return "style"
    return "scenario"


def extract_rules(prompt, task_id):
    """Keep each nonempty native prompt line verbatim, splitting sentence spans."""
    result = []
    start = 0
    for line in prompt.splitlines(keepends=True):
        trimmed = line.strip()
        if (
            not trimmed
            or trimmed.startswith("#")
            or trimmed in ["<scenario>", "</scenario>"]
        ):
            start += len(line)
            continue
        source = "scenario" if start > prompt.find("<scenario>") else "guidelines"
        # Every native non-heading line is retained, including contextual sentences.
        spans = list(
            re.finditer(r".+?(?:[.!?](?=\s+[A-Z]|\s*$)|$)", line.strip(), re.S)
        )
        if not spans:
            spans = [re.match(r".+", trimmed)]
        for match in spans:
            quote = match.group(0).strip()
            if not quote:
                continue
            offset = prompt.find(quote, start)
            assert offset >= 0
            category = rule_category(quote, source)
            rid = (
                "r_" + hashlib.sha256((source + "\n" + quote).encode()).hexdigest()[:16]
            )
            result.append(
                {
                    "rule_id": rid,
                    "verbatim": quote,
                    "category": category,
                    "source": source,
                    "span": [offset, offset + len(quote)],
                    "task_id": task_id,
                    "classification_origin": "assistant classification frozen before any C2 outcome inspection",
                }
            )
        start += len(line)
    return result


def inventory():
    """Freeze native text, per-rule categories and sanity selection before calls."""
    if (D["step1"] / "rules.json").exists():
        return
    tasks = read(BASE / "v7_b1_step2_20261004/tasks.json")
    states = read(BASE / "v7_b1_report_20261004/plan.json")["states"]
    prompts = {}
    all_rules = {}
    per_task = {}
    for tid, obj in tasks.items():
        orch = x.v6.build(x.b.Task.model_validate(obj), [])
        orch.initialize()
        prompt = orch.user.system_prompt
        prompts[tid] = prompt
        rr = extract_rules(prompt, tid)
        per_task[tid] = []
        for r in rr:
            per_task[tid].append(r["rule_id"])
            if r["rule_id"] not in all_rules:
                all_rules[r["rule_id"]] = {
                    k: v for k, v in r.items() if k not in ["task_id", "span"]
                }
                all_rules[r["rule_id"]]["instances"] = []
            all_rules[r["rule_id"]]["instances"].append(
                {"task_id": tid, "span": r["span"]}
            )
    # Runtime schema/provenance requirements have exact source-code references.
    runtime = [
        (
            "native_user_schema",
            "Only native user tools; arguments validate against native JSON schemas.",
            "mechanical",
            "src/tau2/environment/tool.py + native user tool schemas",
        ),
        (
            "native_tool_provenance",
            "Tool-result messages must be the actual native environment outputs with matching call ids.",
            "mechanical",
            "src/tau2/environment/environment.py:set_state",
        ),
        (
            "native_format",
            "Native role/content/tool-message format; one decision has text or tools, with inline tool text hidden from the agent.",
            "mechanical",
            "src/tau2/data_model/message.py + simulation_guidelines_tools.md",
        ),
    ]
    for rid, quote, category, source in runtime:
        all_rules[rid] = {
            "rule_id": rid,
            "verbatim": None,
            "operational_definition": quote,
            "category": category,
            "source": source,
            "instances": [],
            "classification_origin": "runtime-derived requirement; not claimed as a verbatim prompt quote",
        }
    selection = random.Random(2026100601).sample(states, 10)
    rules = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "rules": list(all_rules.values()),
        "per_task_rule_ids": per_task,
        "native_system_prompts": prompts,
        "native_source_sha256": sha(
            ROOT / "data/tau2/user_simulator/simulation_guidelines_tools.md"
        ),
        "format_interpretation": "Native Pydantic and orchestrator allow content with tools, but such inline text is invisible to agent. Prompt both-at-once guidance is inventoried as mechanical message-format rule, applied at each decision; invalid inline combinations are recorded, never silently converted. One-action/multiple-request/cooperation/ground-before-report requirements are style. Actual fabricated environment results are mechanical; asserted false observed facts are scenario.",
        "scenario_boundary": "True but not read facts are style departures, not automatically invalid. Private goal/identity facts retained; no evaluator hidden target is used for style/scenario labels.",
        "mechanical_terminal": "TRANSFER only after explicit agent transfer announcement, required after that announcement. STOP requires observed native speed-test Excellent (mobile) or observed successful can_send_mms (MMS) consistent with current DB. Exact refueling amount is not substituted for private task goal. OUT-OF-SCOPE not authorized in these fully specified20 tasks without a programmatically identified missing required private field; report unsupported uses as mechanical violations.",
    }
    save(D["step1"] / "rules.json", rules)
    plan = {
        "created_at_utc": rules["created_at_utc"],
        "git_hash": rules["git_hash"],
        "rules_sha256": sha(rules_path()),
        "sanity_states": selection,
        "sanity": "10states x6 accepted new VS draws; compare with existing6 native q blocks at identical states; no suffixes",
        "VS_instruction": VS_INSTRUCTION,
        "label_prompt": LABEL_PROMPT,
        "labeler": "openai/gpt-5.6-sol",
        "labeler_temperature": 0,
        "generator_temperature": 1.0,
        "seeds": {"selection": 2026100601, "bootstrap": 2026100602},
        "bootstrap_replicates": 1000,
        "classifications": "Reuse corrected C1 mechanical case classes; invalid if any mechanical/scenario violation. Style verdicts never reject. All model labels marked; unknown labels cannot be silently considered valid.",
        "style_priority": "in_rule iff every applicable style rule in_rule; otherwise out_of_rule with rule ids. Unlabelled/malformed judgment retained as unknown and repeated same frozen prompt.",
        "history_policy": "Full native system prompt byte-for-byte as first message, same native user-visible history, only the VS sampling instruction appended as one system message. Native tools passed through API tool schemas, never explanatory steering prompt. Selected draw is uniform, probabilities logged only.",
        "native_baseline": "Raw native q saved blocks; apply identical checks and labels, do not selectively resample historical baseline",
        "source_tasks_sha256": sha(BASE / "v7_b1_step2_20261004/tasks.json"),
    }
    save(D["step1"] / "plan.json", plan)
    save(
        D["step2"] / "plan.json",
        {
            "created_at_utc": rules["created_at_utc"],
            "rules_sha256": sha(rules_path()),
            "label_prompt": LABEL_PROMPT,
            "scope": "15fixed B2 case blocks plus every later partner turn in all480 B1 persistent Luna suffixes and all240 B2 v2 persistent Luna +72 Sol suffixes. For persistent-drop analysis relabel initial turns and all native/single comparator partner turns as well; report Luna20states B1 and matched10states v2 separately; Sol72 descriptive separately.",
            "validity": "any mechanical/scenario violation invalid; any out_of_rule turn means trajectory out_of_rule; unknown labels separate",
            "bootstrap_replicates": 1000,
            "seed": 2026100602,
            "class_source": "v7_c_step2_20261005/reclassification.json + scope amendment; no new suffixes",
            "unit_dedup": "Hash task, full prefix and block; identical label inputs reuse one frozen model judgment, retain instance maps.",
        },
    )
    for s in D:
        shutil.copy2(BASE / "v7_b1_step2_20261004/tasks.json", D[s] / "tasks.json")
        for case in states:
            dst = D[s] / "sources" / f"{case['source_id']}.json"
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists():
                shutil.copy2(BASE / "v7_b1_step2_20261004/sources" / dst.name, dst)
    print("FROZEN RULES", len(all_rules), "tasks", len(tasks), flush=True)


def task_rules(task, actual_prompt=None):
    ids = (
        set(RULES["per_task_rule_ids"][task.id])
        if actual_prompt is None
        else {r["rule_id"] for r in extract_rules(actual_prompt, task.id)}
    )
    known = {r["rule_id"] for r in RULES["rules"]}
    ids &= known  # Context rows were explicitly removed by the r2 inventory.
    return [r for r in RULES["rules"] if r["rule_id"] in ids]


def transfer_announced(text):
    """Recognize a transfer announcement, excluding offers, questions and conditions."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = parsed.get("message", text)
    except (ValueError, TypeError):
        pass
    text = text.upper().replace("’", "'")
    if "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON." in text:
        return True
    for sentence in re.split(r"[.!?;]", text):
        if re.search(
            r"\b(?:IF|CAN|COULD|WOULD|MAY|MIGHT)\b|\b(?:NOT|CANNOT|CAN'T|WON'T)\b",
            sentence,
        ):
            continue
        if re.search(
            r"\b(?:I AM|I'M|WE ARE|WE'RE) (?:NOW )?(?:TRANSFERRING|CONNECTING)\b|\b(?:I WILL|I'LL|LET ME|I AM GOING TO|I'M GOING TO) (?:NOW )?(?:TRANSFER|CONNECT)\b|\bYOU (?:ARE|WILL BE) (?:BEING )?TRANSFERRED\b",
            sentence,
        ) and re.search(r"\b(?:HUMAN|SPECIALIST|ANOTHER AGENT)\b", sentence):
            return True
    return False


def terminal_check(task, prefix, block, env):
    """Check native terminal protocol from explicit events and observed diagnostics."""
    messages = prefix + block
    last = next((m for m in reversed(prefix) if m["role"] == "assistant"), {})
    text = last.get("content") or ""
    transfer = transfer_announced(text)
    emitted = "\n".join(
        m.get("content") or ""
        for m in block
        if m["role"] == "user" and not m.get("tool_calls")
    )
    errors = []
    if transfer and (
        "###TRANSFER###" not in emitted or any(m.get("tool_calls") for m in block)
    ):
        errors.append("required_transfer_token_missing_or_tools")
    if "###TRANSFER###" in emitted and not transfer:
        errors.append("transfer_without_announcement")
    if "###OUT-OF-SCOPE###" in emitted:
        errors.append("out_of_scope_without_identified_missing_private_field")
    calls = {t["id"]: t for m in messages for t in m.get("tool_calls") or []}
    user_outputs = [
        m
        for m in messages
        if m["role"] == "tool" and m.get("requestor") == "user" and not m.get("error")
    ]
    if task.id.startswith("[mobile_data_issue]"):
        speed, description = env.user_tools._run_speed_test()
        observed = any(
            calls.get(m.get("id"), {}).get("name") == "run_speed_test"
            and "excellent" in (m.get("content") or "").lower()
            for m in user_outputs
        )
        complete = (
            observed
            and speed is not None
            and (description or "").lower() == "excellent"
            and env.user_tools.db.device.data_enabled
        )
    else:
        observed = any(
            calls.get(m.get("id"), {}).get("name") == "can_send_mms"
            and "can send" in (m.get("content") or "").lower()
            and "cannot" not in (m.get("content") or "").lower()
            for m in user_outputs
        )
        complete = observed and env.user_tools._can_send_mms()
    if "###STOP###" in emitted and not complete:
        errors.append("stop_before_observed_private_goal")
    if complete and not transfer and "###STOP###" not in emitted:
        errors.append("required_stop_missing_after_observed_private_goal")
    return errors


def mechanical_check(task, prefix, block, before, after):
    """Enforce actual schemas/provenance/tokens without a model judge."""
    errors = []
    for m in block:
        if m["role"] == "user":
            errors.extend(
                x.b.tool_candidate_errors(
                    {"message": m.get("content"), "tool_calls": m.get("tool_calls")},
                    after.user.tools,
                )
            )
            for t in m.get("tool_calls") or []:
                if t.get("requestor") != "user":
                    errors.append("tool_requestor_not_user")
        elif m["role"] != "tool" or m.get("requestor") != "user":
            errors.append("partner_block_contains_nonuser_message")
    # Mutating tool outputs are checked by strict native replay; reads also verified.
    clone = mech.replay(task.model_dump(mode="json"), prefix)
    outputs = {m.get("id"): m for m in block if m["role"] == "tool"}
    for m in block:
        for tc in m.get("tool_calls") or []:
            if tc["name"] not in {t.name for t in clone.user.tools}:
                continue
            expected = outputs.get(tc["id"])
            if expected is None:
                errors.append("missing_native_tool_result")
                continue
            response = clone.environment.get_response(
                x.p4.MESSAGE_LIST.validate_python([m])[0].tool_calls[
                    (m.get("tool_calls") or []).index(tc)
                ]
            )

            # JSON-string or cosmetic enums normalize identically to native replay.
            def normalize(t):
                try:
                    return json.loads(t)
                except (json.JSONDecodeError, TypeError):
                    return t

            if normalize(response.content) != normalize(expected.get("content")):
                errors.append("fabricated_or_inconsistent_native_tool_result")
    errors.extend(terminal_check(task, prefix, block, after.environment))
    return sorted(set(errors))


def expand_judgment(judge, style, scenario):
    assert set(judge["assessed_style_rule_ids"]) == {r["rule_id"] for r in style}, (
        "Unassessed style/persona rules"
    )
    assert set(judge["assessed_scenario_rule_ids"]) == {
        r["rule_id"] for r in scenario
    }, "Unassessed scenario rules"
    departed = {r["rule_id"]: r for r in judge["style_departures"]}
    violated = {r["rule_id"]: r for r in judge["scenario_violations"]}
    assert set(departed) <= set(judge["assessed_style_rule_ids"])
    assert set(violated) <= set(judge["assessed_scenario_rule_ids"])
    return {
        "style_labels": [
            {
                "rule_id": r["rule_id"],
                "status": "out_of_rule" if r["rule_id"] in departed else "in_rule",
                "evidence": departed.get(r["rule_id"], {}).get(
                    "evidence", "explicitly assessed, no departure"
                ),
            }
            for r in style
        ],
        "scenario_labels": [
            {
                "rule_id": r["rule_id"],
                "violation": r["rule_id"] in violated,
                "evidence": violated.get(r["rule_id"], {}).get(
                    "evidence", "explicitly assessed, no violation"
                ),
            }
            for r in scenario
        ],
        "compact_model_judgment": judge,
    }


def compact_rule(r):
    return {
        "rule_id": r["rule_id"],
        "category": r["category"],
        "verbatim": r.get("verbatim", r.get("operational_definition")),
    }


def annotate(task, prefix, block, key, unit):
    """Programmatic mechanical/DB checks and one joint multi-rule Sol judgment."""
    digest = x.p4.digest(
        {
            "task": task.id,
            "prefix": [x.b.ta.semantic(m) for m in prefix],
            "block": [x.b.ta.semantic(m) for m in block],
            "rules_sha256": sha(rules_path()),
            "full_style": FULL_STYLE,
            "mechanical_version": "r2_native_private_goal_description",
        }
    )
    path = ACTIVE / "labels" / f"{digest}.json"
    if path.exists():
        return read(path)
    before = mech.replay(task.model_dump(mode="json"), prefix)
    after = mech.replay(task.model_dump(mode="json"), prefix + block)
    mechanical = mechanical_check(task, prefix, block, before, after)
    facts = mech.check_claims(prefix, block, after.environment, before.environment)
    # Freeze a temporal distinction omitted by the old parser, retain raw matches.
    scenario_db = programmatic_scenario_violations(facts)
    # Unexecuted rejected draws need no semantic judge. Pure native terminal
    # tokens without any tools contain neither device assertions nor a new goal.
    texts = [(m.get("content") or "").strip() for m in block if m["role"] == "user"]
    pure_terminal = (
        bool(texts)
        and all(t in {"###STOP###", "###TRANSFER###"} for t in texts)
        and not any(m.get("tool_calls") for m in block)
    )
    if not FULL_STYLE and (mechanical or scenario_db or pure_terminal):
        result = {
            "label_input_digest": digest,
            "model_judgment": False,
            "model_requested": None,
            "temperature": None,
            "mechanical_violations": mechanical,
            "programmatic_scenario_violations": scenario_db,
            "model_scenario_violations": [],
            "scenario_violations": bool(scenario_db),
            "valid": not (mechanical or scenario_db),
            "style": "unassessed",
            "departed_style_rules": [],
            "all_style_rule_labels": [],
            "all_scenario_rule_labels": [],
            "fact_check": facts,
            "scenario_judgment_status": "programmatic rejection"
            if mechanical or scenario_db
            else "parsed pure native terminal; no assertions, tool calls or goal-change narrative",
        }
        save(path, result)
        return result
    relevant = task_rules(task, after.user.system_prompt)
    style = [
        r
        for r in relevant
        if r["category"] in ("style", "persona")
        and r["rule_id"] != "r_5112db5336c2d337"
    ]
    if not FULL_STYLE:
        style = []
    scenario = [r for r in relevant if r["category"] == "scenario"]
    payload = {
        "rule_texts": {
            "style_and_persona": [compact_rule(r) for r in style],
            "scenario": [compact_rule(r) for r in scenario],
        },
        "private_scenario_verbatim": after.user.system_prompt.split("<scenario>", 1)[
            -1
        ].split("</scenario>", 1)[0],
        "visible_prior_history": x.p4.llm_utils.to_litellm_messages(
            proposal_messages(before.user, prefix)[1:-1]
        ),
        "partner_block": [
            {
                k: m.get(k)
                for k in ["role", "content", "tool_calls", "id", "requestor", "error"]
            }
            for m in block
        ],
        "private_state_before": x.p4.state(before.environment)["user"],
        "private_state_after": x.p4.state(after.environment)["user"],
        "programmatic_fact_check": facts,
        "programmatic_current_fact_mismatches": scenario_db,
    }
    labelpath = ACTIVE / "judgments" / f"{digest}.json"
    if labelpath.exists():
        judge = read(labelpath)
    else:
        for label_attempt in range(3):
            x.p4.UNIT.set(unit + f":labels:attempt{label_attempt}")
            x.p4.KEY.set(key)
            x.p4.ROLE.set("rule_labeler")
            response = x.p4.llm_utils.generate(
                model=SOL,
                messages=[
                    SystemMessage(role="system", content=LABEL_PROMPT),
                    UserMessage(
                        role="user",
                        content=json.dumps(
                            {"output_format": "json", "input": payload},
                            ensure_ascii=False,
                        ),
                    ),
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=2000,
                **x.p4.llm_args(key, judge=True),
            )
            try:
                judge = expand_judgment(json.loads(response.content), style, scenario)
            except (AssertionError, KeyError, TypeError, ValueError) as exc:
                save(
                    ACTIVE / "malformed_labels" / f"{digest}_{time.time_ns()}.json",
                    {
                        "content": response.content,
                        "error": str(exc),
                        "attempt": label_attempt,
                    },
                )
                if label_attempt == 2:
                    raise
                continue
            save(labelpath, judge)
            break
    # Malformed or incomplete label coverage is repeated, never converted to valid.
    if {item.get("rule_id") for item in judge.get("style_labels", [])} != {
        r["rule_id"] for r in style
    } or {item.get("rule_id") for item in judge.get("scenario_labels", [])} != {
        r["rule_id"] for r in scenario
    }:
        save(ACTIVE / "malformed_labels" / f"{digest}_{time.time_ns()}.json", judge)
        labelpath.unlink(missing_ok=True)
        raise ValueError(
            "Incomplete joint rule labels; retain malformed judgment for audit"
        )
    judge["style_labels"].append(program_format_style(block))
    departed = [
        item for item in judge["style_labels"] if item["status"] == "out_of_rule"
    ]
    violations = [item for item in judge["scenario_labels"] if item["violation"]]
    result = {
        "label_input_digest": digest,
        "model_judgment": True,
        "model_requested": SOL,
        "temperature": 0,
        "mechanical_violations": mechanical,
        "programmatic_scenario_violations": scenario_db,
        "model_scenario_violations": violations,
        "scenario_violations": bool(scenario_db or violations),
        "valid": not (mechanical or scenario_db or violations),
        "style": ("out_of_rule" if departed else "in_rule")
        if FULL_STYLE
        else "unassessed",
        "departed_style_rules": departed,
        "all_style_rule_labels": judge["style_labels"],
        "all_scenario_rule_labels": judge["scenario_labels"],
        "fact_check": facts,
        "classification_standard": "C2 style departures retained; no outcome data supplied to judge",
    }
    save(path, result)
    return result


def sample_reply(
    case, j, key, family="vs", prefix=None, unit=None, remaining_steps=None
):
    """Sample accepted native or VS turn; reject only mechanical/scenario violations."""
    unit = unit or f"{case['state_id']}:{family}:d{j}"
    path = ACTIVE / "replies" / f"{unit}.json"
    if path.exists():
        return read(path)
    task = x.b.Task.model_validate(read(ACTIVE / "tasks.json")[case["task_id"]])
    if prefix is None:
        prefix = read(ACTIVE / "sources" / f"{case['source_id']}.json")["messages"][
            : case["index"]
        ]
    attempt = 0
    while True:
        attempt_unit = f"{unit}:attempt{attempt}"
        x.p4.UNIT.set(attempt_unit)
        x.p4.KEY.set(key)
        orch = x.v6.build(task, prefix, x.p4.stable_seed(attempt_unit), key)
        if remaining_steps is not None:
            orch.max_steps = remaining_steps
        if family.startswith("other:"):
            orch.user.llm = "openai/" + family.split(":", 1)[1]
        orch.initialize()
        if family == "vs":
            messages = proposal_messages(orch.user, prefix)[:-1]
            assert messages[0].content == orch.user.system_prompt
            x.p4.ROLE.set("vs_proposal")
            response = x.p4.llm_utils.generate(
                model=orch.user.llm,
                messages=messages + [UserMessage(role="user", content=VS_INSTRUCTION)],
                tools=orch.user.tools,
                tool_choice="none",
                response_format={"type": "json_object"},
                max_completion_tokens=4096,
                **x.p4.llm_args(key),
            )
            try:
                batch = json.loads(response.content)["candidates"]
                if len(batch) != 5:
                    raise ValueError("candidate_count_not_five")
                for cand in batch:
                    if (
                        not isinstance(cand.get("probability"), (int, float))
                        or not math.isfinite(cand["probability"])
                        or not 0 <= cand["probability"] <= 1
                    ):
                        raise ValueError("invalid_probability")
                selected = random.Random(
                    x.p4.stable_seed(attempt_unit + ":draw")
                ).randrange(5)
                candidate = batch[selected]
                errors = x.b.tool_candidate_errors(candidate, orch.user.tools)
                if errors:
                    raise ValueError(";".join(errors))
            except (ValueError, KeyError, TypeError) as exc:
                save(
                    ACTIVE / "rejected_proposals" / f"{attempt_unit}.json",
                    {
                        "reasons": [str(exc)],
                        "response": response.model_dump(mode="json"),
                    },
                )
                attempt += 1
                continue
            save(
                ACTIVE / "proposals" / f"{attempt_unit}.json",
                {
                    "native_system_prompt_sha256": hashlib.sha256(
                        orch.user.system_prompt.encode()
                    ).hexdigest(),
                    "native_prompt_verbatim": True,
                    "only_added_instruction": VS_INSTRUCTION,
                    "batch": batch,
                    "selected_index": selected,
                },
            )
            x.b.paired.first_response(orch.user, candidate, attempt_unit)
        try:
            x.b.paired.complete_partner(orch)
        except ValueError as exc:
            if "UserMessage must have either content or tool_calls" not in str(exc):
                raise
            save(
                ACTIVE / "rejected_proposals" / f"{attempt_unit}.json",
                {
                    "reasons": ["empty_native_user_message"],
                    "error": str(exc),
                    "family": family,
                },
            )
            attempt += 1
            continue
        messages = [m.model_dump(mode="json") for m in orch.get_messages()]
        block = messages[len(prefix) :]
        label = annotate(task, prefix, block, key, attempt_unit)
        r = {
            "unit": unit,
            "state_id": case["state_id"],
            "j": j,
            "family": family,
            "prefix": messages,
            "partner_block": block,
            "state_after_partner": x.p4.state(orch.environment),
            "assertions_after_partner": x.v6.assertions(orch.environment, task),
            "native_step_count": orch.step_count,
            "native_num_errors": orch.num_errors,
            "attempt": attempt,
            "label": label,
            "partner_signature": x.v6.partner_signature(block),
            "generator_version": "C2_native_prompt_only_VS",
            "termination_reason": orch.termination_reason.value if orch.done else None,
        }
        if label["valid"]:
            save(path, r)
            return r
        save(ACTIVE / "rejected_replies" / f"{attempt_unit}.json", r)
        attempt += 1


def sanity(workers=48):
    p = read(D["step1"] / "plan.json")
    setup("step1", workers)
    redo_path = D["step1"] / "sanity_format_redo_units.json"
    if redo_path.exists():
        for unit in read(redo_path)["units"]:
            reply_path = ACTIVE / "replies" / f"{unit}.json"
            archive = (
                ACTIVE / "pre_format_check_archive" / "sampling_redo" / reply_path.name
            )
            archive.parent.mkdir(parents=True, exist_ok=True)
            if reply_path.exists() and not archive.exists():
                shutil.move(reply_path, archive)
    jobs = []
    for case in p["sanity_states"]:
        for j in range(6):
            jobs.append(lambda key, c=case, j=j: sample_reply(c, j, key))
    x.b.run_jobs("step1", jobs, workers)
    jobs = []
    for case in p["sanity_states"]:
        task = x.b.Task.model_validate(read(ACTIVE / "tasks.json")[case["task_id"]])
        for j in range(6):
            r = read(
                BASE / "v6_paired_20261004/replies" / f"{case['state_id']}:q:d{j}.json"
            )

            def labelnative(key, r=r, task=task):
                label = annotate(
                    task,
                    r["prefix"][: -len(r["partner_block"])],
                    r["partner_block"],
                    key,
                    r["unit"] + ":native_relabel",
                )
                save(ACTIVE / "native_labels" / f"{r['unit']}.json", label)
                return label

            jobs.append(labelnative)
    x.b.run_jobs("step1", jobs, workers)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["inventory", "sanity"])
    ap.add_argument("--workers", type=int, default=48)
    args = ap.parse_args()
    if args.phase == "inventory":
        inventory()
    else:
        sanity(args.workers)
