"""Independent P4 criterion calibration and policy-matched delegation controls."""

import argparse
import collections
import contextvars
import json
import random
import re
import time

import p4_diagnosis as p4

from tau2.data_model.tasks import Task

OLD = p4.OUT
OUT = p4.ROOT / "pilot/runs/p4/calibration_20261003"
APPENDIX = contextvars.ContextVar("calibration_appendix", default="")
NATIVE_BUILDER = p4.build_text_orchestrator
REMINDERS = {
    "resample": "",
    "generic_policy": "Reminder: Follow the troubleshooting procedure in the existing policy. Before transferring to a human agent, try all applicable permitted ways to resolve the issue. Base each next step on the user's current report, check the result, and continue troubleshooting when the issue remains unresolved.",
    "capability_policy": "Reminder: Follow the troubleshooting procedure in the existing policy. Phone-side operations described there can be performed by the user following your guidance, even when absent from your own tool list. Ask the user to perform the applicable step, report the result, and continue troubleshooting when unresolved.",
}

STRICT_PROMPT = """Audit a candidate interaction error using ONLY the supplied policy, agent tools and agent-visible transcript. Reward, task answers, initialization, user tool results, old reviewer labels and sampling strata are withheld. A/B/C are candidates, NOT causal labels. Select the earliest decision satisfying a strict certificate; otherwise none/uncertain.
A: an instruction contradicts explicit still-valid earlier reported state. Cite that report, the contradictory instruction, and reason about ALL intervening actions. Procedural order alone is not A. A conditional 'ensure ON, leave it if ON' is not contradictory merely because it refers to a toggle.
B: an unconditional state-dependent write is issued without necessary state information. State TWO possibilities compatible with visible history and explain how executing the SAME instruction has different appropriateness/effect across them. Queries and conditional/target-setting instructions are not B. Multiple tools in one call are not B by themselves.
C: the assistant explicitly uses absence of ITS OWN phone/diagnostic tool as a reason to stop, refuse or transfer, although an applicable USER-performed procedure already exists in the policy. Cite the explicit unavailable-tool rationale and a literal applicable delegation/procedure passage. General early escalation WITHOUT that rationale is other, not C. Legitimate policy escalation (locked SIM etc.), nonapplicable procedures, user refusal, and fully exhausted troubleshooting do not qualify.
Other: supported different candidate, including general premature escalation; describe it without claiming C.
Return ONLY json: {category:'A'|'B'|'C'|'other'|'none'|'uncertain',decision_index:original assistant index or null,evidence:[{index,quote}],policy_quote:literal policy passage or '',explanation:string,competing_explanations:[strings],confidence:number,certificate:{state_evidence_index:integer or null,intervening_actions_checked:string,compatible_states:[strings],same_action_different_effect:string,unconditional:boolean,unavailable_tool_quote:string,delegable_procedure_quote:string,applicability:string,legitimate_escalation_excluded:string}}. Quotes must be literal substrings of input. Do not infer hidden state, presume truthful/exhaustive user reports, or use task names. When strict proof is missing choose none or uncertain instead of forcing a category."""


def activate():
    """Route all new artifacts and API accounting into this independent batch."""
    p4.OUT = OUT


def prepare():
    """Freeze an independent sample and controls before any new API response."""
    activate()
    if (OUT / "protocol.json").exists():
        return
    old_sample = p4.read(OLD / "sample.json")
    excluded_ids = {i["simulation_id"] for i in old_sample["items"]}
    excluded_tasks = {
        c["task_id"] for c in p4.read(OLD / "approved_cases.json")["cases"]
    }
    iid, tasks, _ = p4.source_data()
    groups = collections.defaultdict(list)
    for sim in iid["simulations"]:
        if sim["id"] in excluded_ids or sim["task_id"] in excluded_tasks:
            continue
        if sim["reward_info"]["reward"] == 1:
            group = "iid_success"
        else:
            group = (
                "iid_ability_signal" if p4.ability_signal(sim) else "iid_other_failure"
            )
        groups[group].append(sim)
    rng = random.Random(2026100302)
    items, strata = [], {}
    for group, candidates in sorted(groups.items()):
        candidates.sort(key=lambda s: s["id"])
        count = 12 if group == "iid_success" else 24
        strata[group] = {
            "population": len(candidates),
            "sampled": count,
            "inclusion_probability": count / len(candidates),
        }
        for sim in rng.sample(candidates, count):
            sid = f"v{len(items):03d}"
            p4.save(OUT / "sources" / (sid + ".json"), sim)
            items.append(
                {
                    "sample_id": sid,
                    "simulation_id": sim["id"],
                    "task_id": sim["task_id"],
                    "stratum": group,
                    "recorded_reward": sim["reward_info"]["reward"],
                    "inclusion_probability": count / len(candidates),
                }
            )
    panel = []
    for group in sorted(groups):
        selected = [i for i in items if i["stratum"] == group]
        panel.extend(rng.sample(selected, 4 if group == "iid_success" else 10))
    p4.save(OUT / "sample.json", {"items": items, "strata": strata})
    p4.save(OUT / "tasks.json", tasks)
    p4.save(OUT / "review_panel.json", {"items": panel})
    p4.save(
        OUT / "protocol.json",
        {
            "frozen_at_unix": time.time(),
            "scope": "Prospective calibration on independent saved trajectories; all 7 old case tasks and 120 old reviewed trajectory IDs excluded. Repeated tasks within this sample remain correlated.",
            "source_sha256": p4.digest(iid),
            "seed": 2026100302,
            "review_prompt": STRICT_PROMPT,
            "reviewers": {"first": "gpt-5.6-luna", "second": "gpt-5.6-sol"},
            "review_budget": {
                "first": 60,
                "second": 24,
                "recovery": "at most once per provider error",
            },
            "reference": "Model certificates plus explicitly recorded coding-assistant adjudication; no human gold labels, human time or confirmatory precision claim.",
            "continuation_budget": "At most four distinct C candidate tasks not in the old seven-case panel, three arms, eight replications per arm (96 maximum). Freeze cases before continuation outcomes.",
            "reminders": REMINDERS,
            "reminder_matching": "Both reminders reiterate existing policy, share troubleshooting and continuation instructions, and have similar word counts. Capability arm additionally identifies the user as executor. No new tools, hidden state, task answers, or persona changes. Append persistently to agent policy only; user policy unchanged.",
            "main_contrast": "capability_policy minus generic_policy, with resample baseline; selected-prefix exploratory effects, not discovery efficiency or clean isolation of all prompt effects",
            "counting": "Candidates never automatically count as validated failures. Calibrated screen diagnostics are conditional on assistant adjudication; weighted only to the residual iid population defined by exclusions.",
            "gates": "G1 remains unpassed without trustworthy precision, miss-rate, independent mechanism checks and validation cost. No automatic promotion of A/B/C into confirmed modes.",
            "excluded_tasks": sorted(excluded_tasks),
        },
    )
    print("prepared", len(items), "independent sources", flush=True)


def strict_certificate(label, view, policy):
    """Check observable grounding and reject structurally unsupported A/B/C."""
    p4.validate_label(label, view, policy)
    category = label["category"]
    cert = label.get("certificate", {})
    by_index = {m["index"]: m for m in view}
    if category == "A":
        idx = cert.get("state_evidence_index")
        if idx not in by_index or idx >= label["decision_index"]:
            raise ValueError("A missing earlier evidence")
        if not cert.get("intervening_actions_checked"):
            raise ValueError("A missing validity analysis")
    if category == "B":
        states = cert.get("compatible_states", [])
        if (
            len(states) < 2
            or len(set(states)) < 2
            or not cert.get("same_action_different_effect")
            or cert.get("unconditional") is not True
        ):
            raise ValueError("B missing information-value certificate")
    if category == "C":
        quote = cert.get("unavailable_tool_quote", "")
        decision = by_index[label["decision_index"]]
        visible = (decision.get("content") or "") + json.dumps(
            decision.get("tool_calls") or [], ensure_ascii=False
        )
        # Permit literal quotes inside tool-call arguments without JSON escaping.
        argument_text = " ".join(
            str(v)
            for t in decision.get("tool_calls") or []
            for v in (t.get("arguments") or {}).values()
        )
        if not quote or (quote not in visible and quote not in argument_text):
            raise ValueError("C lacks explicit rationale in the actual decision")
        if not re.search(
            r"tool|diagnostic|function|capabilit", quote, re.I
        ) or not re.search(
            r"unavailable|not available|cannot|can't|lack|not include|no .{0,80}(?:tool|function)",
            quote,
            re.I,
        ):
            raise ValueError("C quote lacks an explicit capability-denial cue")
        procedure = cert.get("delegable_procedure_quote", "")
        if not procedure or procedure not in policy:
            raise ValueError("C missing policy procedure")
        names = [t["tool"] for t in p4.read(OLD / "tool_semantics.json")["tools"]]
        if not any(name in procedure for name in names):
            raise ValueError(
                "C requires a concrete user procedure, not a section title"
            )
        if not cert.get("applicability") or not cert.get(
            "legitimate_escalation_excluded"
        ):
            raise ValueError("C missing applicability/exclusion analysis")
    return label


def audit_one(item, number, model="gpt-5.6-luna", folder="strict_reviews"):
    """Obtain one grounded review without labels, reward or stratum in the input."""
    sid = item["sample_id"]
    path = OUT / folder / (sid + ".json")
    if path.exists():
        return p4.read(path)
    sim = p4.read(OUT / "sources" / (sid + ".json"))
    task = Task.model_validate(p4.read(OUT / "tasks.json")[item["task_id"]])
    orch = NATIVE_BUILDER(p4.config(), task)
    view = p4.agent_view(sim["messages"])
    payload = {
        "policy": orch.agent.domain_policy,
        "agent_tools": [t.openai_schema for t in orch.agent.tools],
        "transcript": view,
    }
    entry = {"sample_id": sid, "model": model, "payload_sha256": p4.digest(payload)}
    try:
        label = p4.json_response(
            STRICT_PROMPT, payload, model, folder + ":" + sid, number % 4
        )
        entry["raw_label"] = label
        try:
            entry["label"] = strict_certificate(label, view, orch.agent.domain_policy)
            entry["status"] = "ok"
        except (KeyError, TypeError, ValueError) as exc:
            entry.update(status="certificate_rejected", reason=str(exc))
    except Exception as exc:
        entry.update(
            status="error", error_type=type(exc).__name__, reason=str(exc)[:1000]
        )
    p4.save(path, entry)
    return entry


def reminder_builder(*args, **kwargs):
    """Apply a context-local agent reminder before native initialization."""
    orch = NATIVE_BUILDER(*args, **kwargs)
    if APPENDIX.get():
        orch.agent.domain_policy += "\n\n" + APPENDIX.get()
    return orch


def run_one(job, number):
    """Run a native continuation under a persistent, policy-only reminder."""
    case, arm, rep = job
    token = APPENDIX.set(REMINDERS[arm])
    try:
        entry = p4.run_one((case, arm, rep), number)
        entry["policy_appendix"] = REMINDERS[arm]
        entry["calibration_protocol_sha256"] = p4.digest(p4.read(OUT / "protocol.json"))
        p4.save(OUT / "continuations" / (entry["unit"] + ".json"), entry)
        return entry
    finally:
        APPENDIX.reset(token)


def main():
    """Prepare, audit, independently review, or execute frozen continuation cases."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=["prepare", "audit", "review", "run", "summary"]
    )
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    prepare()
    if args.phase == "prepare":
        return
    if args.phase == "summary":
        p4.summarize()
        return
    p4.setup(p4.ROOT / "api.txt", args.workers)
    if args.phase == "audit":
        p4.pool_jobs(p4.read(OUT / "sample.json")["items"], audit_one, args.workers)
    elif args.phase == "review":
        p4.pool_jobs(
            p4.read(OUT / "review_panel.json")["items"],
            lambda item, n: audit_one(item, n, "gpt-5.6-sol", "independent_reviews"),
            args.workers,
        )
    else:
        cases = p4.read(OUT / "approved_cases.json")["cases"]
        assert len(cases) <= 4 and len({c["task_id"] for c in cases}) == len(cases)
        p4.build_text_orchestrator = reminder_builder
        jobs = [(c, arm, rep) for c in cases for arm in REMINDERS for rep in range(8)]
        p4.pool_jobs(jobs, run_one, args.workers)
    p4.summarize()


if __name__ == "__main__":
    main()
