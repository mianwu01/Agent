"""Prospectively frozen holdout validation of the revised P4 capability screen."""

import argparse
import inspect
import random
import re
import time

import p4_calibration as calibration
import p4_diagnosis as p4
from p4_calibration_report import capability_screen

from tau2.data_model.tasks import Task

OUT = p4.ROOT / "pilot/runs/p4/screen_holdout_20261003"
PROMPT = """Independently audit the supplied agent-visible conversation and policy for a candidate interaction process. No outcome, task answers, private user-tool results, prior labels or screen outputs are supplied. This is candidate classification, NOT causal verification.
For screen calibration select the earliest strictly supported C if one exists anywhere; otherwise select A/B/other/none/uncertain. C requires an explicit absence of the assistant's OWN phone/diagnostic tools as justification for refusal, stopping or escalation, while a concrete applicable USER-performed procedure exists in the provided policy. Generic 'further diagnostics needed' WITHOUT a tool-unavailability rationale is other, not C. Exclude mandatory escalation, exhausted applicable troubleshooting and user refusal. A requires contradiction of still-valid accessible state evidence, checking intervening actions. B requires an unconditional state-dependent write with at least two compatible states producing different effects; conditional ensure-ON instructions and multi-step requests alone are not B.
Use INDEX LOCATORS rather than inventing quotations. policy_line_ids must select exact supplied lines containing concrete applicable USER tool names, not headings or generic instructions. evidence_indices must select actual supplied transcript indices. decision_index must select an assistant decision. If a required certificate is absent, choose uncertain/other/none instead of forcing C.
Return ONLY json: {category:'A'|'B'|'C'|'other'|'none'|'uncertain',decision_index:integer or null,evidence_indices:[integers],policy_line_ids:[integers],explanation:string,competing_explanations:[strings],confidence:number,certificate:{state_evidence_index:integer or null,intervening_actions_checked:string,compatible_states:[strings],same_action_different_effect:string,unconditional:boolean,applicability:string,legitimate_escalation_excluded:string}}. Do not infer hidden initialization or assume user reports are exhaustive. A C certificate must explain applicability and why escalation was not yet legitimate."""


def activate():
    """Isolate new artifact paths while retaining the shared audited API transport."""
    p4.OUT = OUT


def prepare():
    """Freeze screen, sampling probabilities, review panel and criteria before API use."""
    activate()
    if (OUT / "protocol.json").exists():
        verify_frozen()
        return
    excluded_ids, excluded_tasks = set(), set()
    for root in (calibration.OLD, calibration.OUT):
        excluded_ids.update(
            i["simulation_id"] for i in p4.read(root / "sample.json")["items"]
        )
        excluded_tasks.update(
            c["task_id"] for c in p4.read(root / "approved_cases.json")["cases"]
        )
    iid, tasks, _ = p4.source_data()
    groups = {"screen_hit": [], "screen_nonhit": []}
    for sim in iid["simulations"]:
        if (
            sim["id"] in excluded_ids
            or sim["task_id"] in excluded_tasks
            or sim["reward_info"]["reward"] == 1
        ):
            continue
        groups["screen_hit" if capability_screen(sim) else "screen_nonhit"].append(sim)
    rng = random.Random(2026100304)
    items, panel, strata = [], [], {}
    for group, candidates in groups.items():
        candidates.sort(key=lambda s: s["id"])
        strata[group] = {
            "population": len(candidates),
            "sampled": 24,
            "inclusion_probability": 24 / len(candidates),
        }
        selected = []
        for sim in rng.sample(candidates, 24):
            sid = f"h{len(items):03d}"
            p4.save(OUT / "sources" / (sid + ".json"), sim)
            item = {
                "sample_id": sid,
                "simulation_id": sim["id"],
                "task_id": sim["task_id"],
                "stratum": group,
                "inclusion_probability": 24 / len(candidates),
                "recorded_reward": sim["reward_info"]["reward"],
            }
            items.append(item)
            selected.append(item)
        panel.extend(rng.sample(selected, 12))
    rng.shuffle(panel)
    p4.save(
        OUT / "sample.json",
        {
            "items": items,
            "strata": strata,
            "excluded_tasks": sorted(excluded_tasks),
            "excluded_ids": sorted(excluded_ids),
        },
    )
    p4.save(OUT / "tasks.json", tasks)
    p4.save(OUT / "review_panel.json", {"items": panel})
    screen_source = inspect.getsource(capability_screen)
    p4.save(
        OUT / "protocol.json",
        {
            "frozen_at_unix": time.time(),
            "seed": 2026100304,
            "scope": "Independent held-out previously generated iid failures; excludes both earlier reviewed cohorts and all eleven earlier continuation tasks. Not fresh rollout generation or a discovery-efficiency experiment.",
            "screen_source": screen_source,
            "screen_sha256": p4.digest(screen_source),
            "validator_source": inspect.getsource(validate_locators),
            "validator_sha256": p4.digest(inspect.getsource(validate_locators)),
            "review_prompt": PROMPT,
            "review_prompt_sha256": p4.digest(PROMPT),
            "source_sha256": p4.digest(iid),
            "sampling": "24 screen hits + 24 nonhits, uniformly without replacement within stratum; 12 from each prospectively selected for independent reviewer and coding-assistant reference. Repeated tasks retained and correlated.",
            "budget": {
                "first_reviews": 48,
                "second_reviews": 24,
                "recovery": "at most once per provider error; do not retry rejected semantic certificates",
            },
            "reviewers": {
                "first": "gpt-5.6-luna",
                "second": "gpt-5.6-sol",
                "temperature": 0,
                "reasoning_effort": "none",
            },
            "certificate": "Same development-v2 A/B/C requirements. Index locators replace free-form quotations; exact evidence and policy passages reconstructed from input. Syntactic grounding is not semantic or causal proof.",
            "prospective_targets": {
                "candidate_precision": 0.8,
                "weighted_C_candidate_miss_fraction_max": 0.2,
                "grounded_review_coverage": 0.9,
                "limit": "Development targets only; no automatic G1 passage, especially without human reference, uncertainty, competing explanations and verified failure cost.",
            },
            "reference": "Coding-assistant candidate review is not independent human truth. Missing/rejected/error labels remain unresolved, never negatives. Human annotation not returned at freeze.",
            "claims": "Evaluate held-out screen candidate precision/miss rate and provisional review yield, not confirmed-mode count or causal discovery efficiency.",
        },
    )
    print("prepared", strata, "panel", len(panel), flush=True)


def verify_frozen():
    """Prevent inadvertent post-freeze changes to the screen or prompt."""
    protocol = p4.read(OUT / "protocol.json")
    assert p4.digest(inspect.getsource(capability_screen)) == protocol["screen_sha256"]
    assert p4.digest(PROMPT) == protocol["review_prompt_sha256"]
    assert (
        p4.digest(inspect.getsource(validate_locators)) == protocol["validator_sha256"]
    )


def decision_text(message):
    """Extract literal visible assistant prose and tool arguments without escaping."""
    return (
        (message.get("content") or "")
        + " "
        + " ".join(
            str(v)
            for t in message.get("tool_calls") or []
            for v in (t.get("arguments") or {}).values()
        )
    )


def validate_locators(raw, view, lines):
    """Validate exact index grounding and the frozen version-two certificates."""
    category = raw["category"]
    assert category in {"A", "B", "C", "other", "none", "uncertain"}, "Unknown category"
    by_index = {m["index"]: m for m in view}
    idx = raw.get("decision_index")
    if category in {"A", "B", "C", "other"}:
        assert (
            type(idx) is int
            and idx in by_index
            and by_index[idx]["role"] == "assistant"
        ), "Not an assistant decision"
    evidence = raw.get("evidence_indices", [])
    line_ids = raw.get("policy_line_ids", [])
    assert all(type(i) is int and i in by_index for i in evidence), (
        "Inaccessible evidence index"
    )
    assert all(type(i) is int and 0 <= i < len(lines) for i in line_ids), (
        "Invalid policy line"
    )
    cert = raw.get("certificate", {})
    procedure = "\n".join(lines[i] for i in line_ids)
    if category == "A":
        earlier = cert.get("state_evidence_index")
        assert (
            earlier in by_index
            and earlier < idx
            and cert.get("intervening_actions_checked")
        ), "A lacks valid earlier state certificate"
    if category == "B":
        states = cert.get("compatible_states", [])
        assert (
            len(set(states)) >= 2
            and cert.get("same_action_different_effect")
            and cert.get("unconditional") is True
        ), "B lacks state-dependence certificate"
    if category == "C":
        text = decision_text(by_index[idx])
        assert re.search(
            r"tool|diagnostic|function|capabilit", text, re.I
        ) and re.search(
            r"unavailable|not available|cannot|can't|lack|not include|no .{0,80}(?:tool|function)",
            text,
            re.I,
        ), "C lacks explicit tool-denial cue"
        names = [
            t["tool"] for t in p4.read(calibration.OLD / "tool_semantics.json")["tools"]
        ]
        assert any(name in procedure for name in names), (
            "C lacks concrete user procedure"
        )
        assert cert.get("applicability") and cert.get(
            "legitimate_escalation_excluded"
        ), "C lacks applicability or exclusion analysis"
    label = dict(raw)
    label["grounded_evidence"] = [by_index[i] for i in evidence]
    label["grounded_policy_quote"] = procedure
    return label


def review_one(item, number, model="gpt-5.6-luna", folder="reviews"):
    """Review one source, hiding sample/stratum/outcome and reconstructing quotes."""
    path = OUT / folder / (item["sample_id"] + ".json")
    if path.exists():
        return p4.read(path)
    sim = p4.read(OUT / "sources" / (item["sample_id"] + ".json"))
    task = Task.model_validate(p4.read(OUT / "tasks.json")[item["task_id"]])
    orch = calibration.NATIVE_BUILDER(p4.config(), task)
    lines = orch.agent.domain_policy.splitlines()
    view = p4.agent_view(sim["messages"])
    payload = {
        "policy_lines": [{"line": i, "text": line} for i, line in enumerate(lines)],
        "agent_tools": [t.openai_schema for t in orch.agent.tools],
        "transcript": view,
    }
    row = {
        "sample_id": item["sample_id"],
        "model": model,
        "payload_sha256": p4.digest(payload),
        "key_index": number % 4 + 1,
    }
    try:
        raw = p4.json_response(
            PROMPT, payload, model, folder + ":" + item["sample_id"], number % 4
        )
        row["raw_label"] = raw
        try:
            row["label"] = validate_locators(raw, view, lines)
            row["status"] = "ok"
        except (AssertionError, KeyError, TypeError, ValueError) as exc:
            row.update(status="certificate_rejected", reason=str(exc))
    except Exception as exc:
        row.update(
            status="error", error_type=type(exc).__name__, reason=str(exc)[:1000]
        )
    p4.save(path, row)
    return row


def main():
    """Run one resumable phase with no hidden retries or completed-unit overwrite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "review", "independent"])
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    prepare()
    if args.phase == "prepare":
        return
    p4.setup(p4.ROOT / "api.txt", args.workers)
    if args.phase == "review":
        p4.pool_jobs(p4.read(OUT / "sample.json")["items"], review_one, args.workers)
    else:
        p4.pool_jobs(
            p4.read(OUT / "review_panel.json")["items"],
            lambda item, n: review_one(item, n, "gpt-5.6-sol", "independent_reviews"),
            args.workers,
        )
    p4.summarize()


if __name__ == "__main__":
    main()
