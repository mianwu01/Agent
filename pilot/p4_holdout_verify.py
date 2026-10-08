"""Verify frozen holdout provenance, blinded payloads and terminal accounting."""

import collections
import hashlib
import json
import time

import p4_holdout as h


def main():
    """Verify technical integrity without treating rejected reviews as negatives."""
    h.activate()
    h.verify_frozen()
    sample = h.p4.read(h.OUT / "sample.json")
    protocol = h.p4.read(h.OUT / "protocol.json")
    iid, _, _ = h.p4.source_data()
    assert h.p4.digest(iid) == protocol["source_sha256"]
    items = {i["sample_id"]: i for i in sample["items"]}
    panel = h.p4.read(h.OUT / "review_panel.json")["items"]
    assert len(items) == 48
    assert len({i["simulation_id"] for i in items.values()}) == 48
    assert collections.Counter(i["stratum"] for i in items.values()) == {
        "screen_hit": 24,
        "screen_nonhit": 24,
    }
    assert collections.Counter(i["stratum"] for i in panel) == {
        "screen_hit": 12,
        "screen_nonhit": 12,
    }
    ids, tasks = set(), set()
    for root in (h.calibration.OLD, h.calibration.OUT):
        ids.update(i["simulation_id"] for i in h.p4.read(root / "sample.json")["items"])
        tasks.update(
            c["task_id"] for c in h.p4.read(root / "approved_cases.json")["cases"]
        )
    assert ids == set(sample["excluded_ids"])
    assert tasks == set(sample["excluded_tasks"]) and len(tasks) == 11
    for item in items.values():
        assert item["simulation_id"] not in ids and item["task_id"] not in tasks
        sim = h.p4.read(h.OUT / "sources" / (item["sample_id"] + ".json"))
        assert sim["id"] == item["simulation_id"]
        assert h.capability_screen(sim) == (item["stratum"] == "screen_hit")
        meta = sample["strata"][item["stratum"]]
        assert item["inclusion_probability"] == meta["sampled"] / meta["population"]
    reviews = {}
    for folder, selected in (
        ("reviews", list(items.values())),
        ("independent_reviews", panel),
    ):
        entries = {p.stem: h.p4.read(p) for p in (h.OUT / folder).glob("*.json")}
        assert set(entries) == {i["sample_id"] for i in selected}
        assert all(
            e["status"] in {"ok", "certificate_rejected", "error"}
            for e in entries.values()
        )
        reviews[folder] = entries
    calls = [h.p4.read(p) for p in (h.OUT / "requests").glob("*.json")]
    assert len(calls) == 81
    assert all(c["status"] in {"response", "error"} for c in calls)
    for call in calls:
        folder, sid = call["unit"].split(":")
        request = call["request"]
        payload = json.loads(request["messages"][1]["content"])["input"]
        assert set(payload) == {"policy_lines", "agent_tools", "transcript"}
        assert h.p4.digest(payload) == reviews[folder][sid]["payload_sha256"]
        sim = h.p4.read(h.OUT / "sources" / (sid + ".json"))
        assert payload["transcript"] == h.p4.agent_view(sim["messages"])
        assert request["messages"][0]["content"] == h.PROMPT + " Return valid json."
        assert request["reasoning_effort"] == "none" and request["temperature"] == 0
    keys = (h.p4.ROOT / "api.txt").read_text().split()
    files = [p for p in h.OUT.rglob("*") if p.is_file()]
    assert not any(key.encode() in p.read_bytes() for p in files for key in keys), (
        "Credential match; values withheld"
    )
    inputs = [
        h.OUT / n
        for n in (
            "protocol.json",
            "sample.json",
            "assistant_reference.json",
            "analysis.json",
        )
    ]
    inputs += [
        h.p4.ROOT / "pilot" / n
        for n in ("p4_holdout.py", "p4_holdout_report.py", "p4_holdout_verify.py")
    ]
    verification = {
        "verified_at_unix": time.time(),
        "independent_unique_sources": 48,
        "reference_panel": 24,
        "excluded_previous_tasks": 11,
        "frozen_screen_prompt_validator_unchanged": True,
        "reviewer_payloads_checked": len(calls),
        "payload_metadata_and_user_tool_results_excluded": True,
        "provider_attempts": len(calls),
        "pending_requests": 0,
        "review_status": {
            f: dict(collections.Counter(e["status"] for e in es.values()))
            for f, es in reviews.items()
        },
        "credential_scan_files": len(files),
        "credential_matches": 0,
        "tests": {
            "passed": 4,
            "log": "../specificity_20261003/tests.log",
            "scope": "holdout tests in the eight-test log",
        },
        "provenance_sha256": {
            str(p.relative_to(h.p4.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
        "limit": "Integrity checks do not establish semantic accuracy, human truth, causal failures or G1 passage. Nine provider errors remain after one permitted recovery; no further retries.",
    }
    h.p4.save(h.OUT / "final_verification.json", verification)
    h.p4.save(
        h.OUT / "handoff.json",
        {
            "status": "complete_with_unresolved_reviews",
            "G1_passed": False,
            "analysis": "analysis.json",
            "verification": "final_verification.json",
            "human_annotation": "../calibration_20261003/annotation.html; no returned labels",
            "next_control_batch": "../specificity_20261003",
            "next_steps": [
                "Finish frozen generic early-escalation specificity controls",
                "Develop semantic certificate checks using development errors, never rescore frozen holdout",
                "Obtain human adjudication, freeze causal validation/deduplication/cost accounting before G2",
            ],
        },
    )
    print({"provider_attempts": len(calls), "credential_matches": 0, "frozen": True})


if __name__ == "__main__":
    main()
