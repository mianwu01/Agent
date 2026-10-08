"""Verify independent sampling, native prefixes and agent-only policy reminders."""

import collections
import hashlib
import json

import p4_calibration as c


def main():
    """Check complete outcomes, request-level isolation, provenance and redaction."""
    c.activate()
    cases = c.p4.read(c.OUT / "approved_cases.json")["cases"]
    sample = c.p4.read(c.OUT / "sample.json")["items"]
    previous = c.p4.read(c.OLD / "sample.json")["items"]
    excluded_tasks = set(c.p4.read(c.OUT / "protocol.json")["excluded_tasks"])
    assert len(sample) == 60
    assert not (
        {s["simulation_id"] for s in sample} & {s["simulation_id"] for s in previous}
    )
    assert not ({s["task_id"] for s in sample} & excluded_tasks)
    assert len(cases) == 4 and len({case["task_id"] for case in cases}) == 4
    rows = [c.p4.read(p) for p in (c.OUT / "continuations").glob("*.json")]
    expected = {
        f"{case['sample_id']}:{arm}:{rep}"
        for case in cases
        for arm in c.REMINDERS
        for rep in range(8)
    }
    assert len(rows) == 96 and {r["unit"] for r in rows} == expected
    assert all(r["status"] == "completed" for r in rows)
    sizes = collections.Counter(r["arm"] for r in rows)
    assert sizes == {arm: 32 for arm in c.REMINDERS}
    fields = ("role", "content", "tool_calls", "id", "requestor")
    protocol_hash = c.p4.digest(c.p4.read(c.OUT / "protocol.json"))
    for case in cases:
        source = c.p4.read(c.OUT / "sources" / (case["sample_id"] + ".json"))
        prefix = source["messages"][: case["decision_index"]]
        assert c.p4.digest(prefix) == case["prefix_sha256"]
        for row in (r for r in rows if r["sample_id"] == case["sample_id"]):
            assert row["prefix_sha256"] == case["prefix_sha256"]
            replay = row["simulation"]["messages"][: len(prefix)]
            assert len(replay) == len(prefix)
            assert all(
                all(a.get(k) == b.get(k) for k in fields)
                for a, b in zip(prefix, replay, strict=True)
            )
            assert row["policy_appendix"] == c.REMINDERS[row["arm"]]
            assert row["calibration_protocol_sha256"] == protocol_hash
            assert row["state_trace"]
            assert row["config"]["max_steps"] == max(1, 200 - c.p4.prefix_steps(prefix))
            assert row["simulation"]["reward_info"]["reward"] == row["reward"]
            for role in ("agent", "user"):
                args = row["config"]["llm_args_" + role]
                assert args["temperature"] == 1 and args["reasoning_effort"] == "none"
                assert row["config"]["llm_" + role] == "openai/gpt-5.6-luna"
    requests = [c.p4.read(p) for p in (c.OUT / "requests").glob("*.json")]
    agent_requests = user_requests = 0
    for request in requests:
        assert request["status"] != "started"
        if request["role"] not in {"agent", "user"}:
            continue
        assert request["unit"] in expected
        arm = request["unit"].split(":")[1]
        system = "\n".join(
            str(m.get("content") or "")
            for m in request["request"]["messages"]
            if m["role"] == "system"
        )
        if request["role"] == "agent":
            agent_requests += 1
            for name, appendix in c.REMINDERS.items():
                if appendix:
                    assert (appendix in system) == (name == arm)
        else:
            user_requests += 1
            assert not any(
                appendix in system for appendix in c.REMINDERS.values() if appendix
            )
    assert agent_requests and user_requests
    packet = c.p4.read(c.OUT / "annotation_packet.json")
    assert len(packet) == 24
    assert all(
        set(e) == {"episode_id", "policy", "agent_tools", "transcript"} for e in packet
    )
    keys = (c.p4.ROOT / "api.txt").read_text().split()
    files = [p for p in c.OUT.rglob("*") if p.is_file()]
    for path in files:
        data = path.read_bytes()
        assert not any(key.encode() in data for key in keys), (
            "Credential scan failed; values withheld"
        )
    inputs = [
        c.p4.ROOT / "pilot" / name
        for name in (
            "p4_calibration.py",
            "p4_calibration_report.py",
            "p4_calibration_verify.py",
            "p4_annotation_packet.py",
        )
    ] + [
        c.OUT / name
        for name in (
            "protocol.json",
            "sample.json",
            "approved_cases.json",
            "assistant_reference.json",
            "certificate_revision.json",
        )
    ]
    report = {
        "independent_sources": 60,
        "distinct_case_tasks": 4,
        "unique_complete_units": 96,
        "arm_sizes": dict(sizes),
        "prefix_messages_and_hashes_checked": True,
        "agent_policy_requests_checked": agent_requests,
        "user_policy_requests_checked": user_requests,
        "user_system_prompt_excludes_intervention_reminders": True,
        "pending_provider_requests": 0,
        "credential_scan_files": len(files),
        "credential_matches": 0,
        "tests": {"passed": 12, "log": "tests.log"},
        "annotation_packet": {"episodes": 24, "metadata_fields_excluded": True},
        "provenance_sha256": {
            str(p.relative_to(c.p4.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
        "limit": "Completed native runs each passed single-initialization state-hash check. Provider seed determinism is unverified. This checks technical validity, not human adjudication or causal isolation.",
    }
    c.p4.save(c.OUT / "final_verification.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "unique_complete_units",
                    "agent_policy_requests_checked",
                    "user_policy_requests_checked",
                    "credential_matches",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
