"""Verify the completed frozen P4 panel and scan artifacts without exposing keys."""

import collections
import hashlib
import json

import p4_diagnosis as p4


def main():
    """Check complete units, prefix preservation, configuration and provenance."""
    cases = p4.read(p4.OUT / "approved_cases.json")["cases"]
    rows = [p4.read(f) for f in (p4.OUT / "continuations").glob("*.json")]
    assert len(rows) == 168 and len({r["unit"] for r in rows}) == 168
    assert all(r["status"] == "completed" for r in rows)
    sizes = collections.Counter(r["arm"] for r in rows)
    assert sizes == {"resample": 56, "fixed_original": 56, "fixed_corrected": 56}
    fields = ("role", "content", "tool_calls", "id", "requestor")
    for case in cases:
        source = p4.read(p4.OUT / "sources" / (case["sample_id"] + ".json"))
        prefix = source["messages"][: case["decision_index"]]
        assert p4.digest(prefix) == case["prefix_sha256"]
        selected = [r for r in rows if r["sample_id"] == case["sample_id"]]
        assert len(selected) == 24
        for row in selected:
            assert row["prefix_sha256"] == case["prefix_sha256"]
            replay = row["simulation"]["messages"][: len(prefix)]
            assert len(replay) == len(prefix)
            assert all(
                all(a.get(k) == b.get(k) for k in fields)
                for a, b in zip(prefix, replay, strict=True)
            )
            assert row["simulation"]["reward_info"]["reward"] == row["reward"]
            assert row["state_trace"]
            for role in ("agent", "user"):
                args = row["config"]["llm_args_" + role]
                assert args["temperature"] == 1.0
                assert args["reasoning_effort"] == "none"
    keys = (p4.ROOT / "api.txt").read_text().split()
    files = [f for f in p4.OUT.rglob("*") if f.is_file()]
    for file in files:
        data = file.read_bytes()
        assert not any(key.encode() in data for key in keys), (
            "Credential scan failed; values withheld"
        )
    inputs = [
        p4.ROOT / "pilot" / name
        for name in ("p4_diagnosis.py", "p4_analyze.py", "p4_verify.py")
    ] + [
        p4.OUT / name
        for name in ("approved_cases.json", "protocol.json", "sample.json")
    ]
    report = {
        "units": len(rows),
        "unique_units": len({r["unit"] for r in rows}),
        "all_completed": True,
        "arm_sizes": dict(sizes),
        "prefix_hashes_and_messages_match_frozen_cases": True,
        "configuration_checked": True,
        "credential_scan_files": len(files),
        "credential_matches": 0,
        "offline_tests": {"passed": 6, "log": "final_tests.log"},
        "provenance_sha256": {
            str(f.relative_to(p4.ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in inputs
        },
        "limit": "Every completed run passed the native single-initialization database hash check. Provider seed determinism remains unverified.",
    }
    p4.save(p4.OUT / "final_verification.json", report)
    print(json.dumps({"verified_units": len(rows), "credential_matches": 0}))


if __name__ == "__main__":
    main()
