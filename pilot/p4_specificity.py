"""Frozen exploratory non-C early-escalation controls for persistent reminders."""

import argparse
import inspect
import time

import p4_calibration as c
import p4_holdout as h

from tau2.data_model.tasks import Task

OUT = c.p4.ROOT / "pilot/runs/p4/specificity_20261003"
SELECTION = {"h030": 43, "h035": 10, "h000": 24, "h037": 34}


def activate():
    """Reuse audited native runners in a separate artifact directory."""
    c.OUT = OUT
    c.activate()


def prepare():
    """Freeze four reference-negative tasks and native prefix states before API use."""
    activate()
    if (OUT / "protocol.json").exists():
        verify_frozen()
        return
    references = {
        r["sample_id"]: r
        for r in c.p4.read(h.OUT / "assistant_reference.json")["entries"]
    }
    items = {i["sample_id"]: i for i in c.p4.read(h.OUT / "sample.json")["items"]}
    tasks = c.p4.read(h.OUT / "tasks.json")
    cases = []
    for sid, idx in SELECTION.items():
        assert references[sid]["C_candidate"] is False
        item = items[sid]
        sim = c.p4.read(h.OUT / "sources" / (sid + ".json"))
        assert sim["messages"][idx]["role"] == "assistant"
        prefix = sim["messages"][:idx]
        task = Task.model_validate(tasks[item["task_id"]])
        orch = c.NATIVE_BUILDER(c.p4.config(), c.p4.with_prefix(task, prefix))
        orch.initialize()
        cases.append(
            {
                "sample_id": sid,
                "task_id": task.id,
                "category": "other",
                "decision_index": idx,
                "prefix_sha256": c.p4.digest(prefix),
                "prefix_state_sha256": c.p4.digest(c.p4.state(orch.environment)),
                "source_sha256": c.p4.digest(sim),
                "reference_reason": references[sid]["reason"],
                "original_response": sim["messages"][idx],
            }
        )
        c.p4.save(OUT / "sources" / (sid + ".json"), sim)
    assert len({case["task_id"] for case in cases}) == 4
    c.p4.save(OUT / "tasks.json", tasks)
    c.p4.save(OUT / "approved_cases.json", {"cases": cases})
    c.p4.save(
        OUT / "protocol.json",
        {
            "frozen_at_unix": time.time(),
            "purpose": "Competing-explanation check: does the capability reminder also help generic early escalation without an explicit own-tool absence rationale?",
            "selection": "Four assistant-reference non-C generic escalation cases, two MMS/two mobile-data, selected before new continuation outcomes; all eleven previous continuation tasks excluded. Observationally selected controls, not a randomized matched C/non-C population.",
            "source_panel": str(h.OUT.relative_to(c.p4.ROOT)),
            "reference_sha256": c.p4.digest(
                c.p4.read(h.OUT / "assistant_reference.json")
            ),
            "cases_sha256": c.p4.digest(cases),
            "reminders": c.REMINDERS,
            "builder_sha256": c.p4.digest(inspect.getsource(c.reminder_builder)),
            "runner_sha256": c.p4.digest(inspect.getsource(c.p4.run_one)),
            "replications_per_arm": 8,
            "continuation_budget": 96,
            "retry": "No automatic simulation/provider recovery. Existing units skipped on resumption. Provider errors remain unresolved.",
            "model": "openai/gpt-5.6-luna",
            "temperature": 1,
            "reasoning_effort": "none",
            "main_contrast": "capability_policy minus generic_policy; resample baseline. Compare descriptively with earlier four-C-case panel. Do not infer a causal C-by-treatment interaction across unmatched selected panels.",
            "isolation": "Agent-only persistent appendix before native initialization; unchanged user policy, tools, prefix, state and step budget. Seeds unit-specific, provider determinism unverified.",
            "gates": "Exploratory mechanism competitor check, not G1 passage or discovery curves. No human reference available.",
        },
    )
    verify_frozen()
    print("frozen four non-C cases; 96 continuations maximum", flush=True)


def verify_frozen():
    """Detect changes to reminders, selected cases and runner after freeze."""
    protocol = c.p4.read(OUT / "protocol.json")
    cases = c.p4.read(OUT / "approved_cases.json")["cases"]
    assert c.REMINDERS == protocol["reminders"]
    assert c.p4.digest(cases) == protocol["cases_sha256"]
    assert (
        c.p4.digest(inspect.getsource(c.reminder_builder)) == protocol["builder_sha256"]
    )
    assert c.p4.digest(inspect.getsource(c.p4.run_one)) == protocol["runner_sha256"]
    for case in cases:
        sim = c.p4.read(OUT / "sources" / (case["sample_id"] + ".json"))
        assert c.p4.digest(sim) == case["source_sha256"]
        assert (
            c.p4.digest(sim["messages"][: case["decision_index"]])
            == case["prefix_sha256"]
        )


def main():
    """Prepare or run the bounded frozen control batch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "run"])
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    prepare()
    if args.phase == "prepare":
        return
    c.p4.setup(c.p4.ROOT / "api.txt", args.workers)
    c.p4.build_text_orchestrator = c.reminder_builder
    cases = c.p4.read(OUT / "approved_cases.json")["cases"]
    jobs = [
        (case, arm, rep) for case in cases for arm in c.REMINDERS for rep in range(8)
    ]
    c.p4.pool_jobs(jobs, c.run_one, args.workers)
    c.p4.summarize()


if __name__ == "__main__":
    main()
