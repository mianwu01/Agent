"""Verify frozen-order, native replay, audit integrity and fresh control isolation."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]


def read(p):
    return json.loads(p.read_text())


def test_frozen_plans_predate_all_new_model_calls():
    first = min(read(f)["started_at"] for f in (OUT / "requests").glob("*.json"))
    for p in [OUT / "plan.json", OUT.parent / "v7_c_step2_20261005/plan.json"]:
        assert datetime.fromisoformat(read(p)["timestamp_utc"]).timestamp() < first


def test_strict_replay_has_correct_assertions_and_reward():
    rows = read(OUT / "mechanical_replay.json")
    assert len(rows) == 12
    assert all(
        r["strict_mutating_tool_output_replay"]
        and r["assertions_match"]
        and r["reward_match"]
        for r in rows
    )
    assert sum(r["reward"] == 1 for r in rows) == 6


def test_new_control_changes_suffix_only_and_retains_temperature():
    p = read(OUT / "plan.json")
    old = OUT.parent / "v7_b2_b2_20261005"
    rows = [read(f) for f in (OUT / "continuations").glob("*.json")]
    assert sorted((r["j"], r["rep"]) for r in rows) == [
        (j, r) for j in range(6) for r in range(2)
    ]
    for j in range(6):
        new = read(OUT / "replies" / f"s010:c_single_v2:d{j}.json")
        original = read(old / "replies" / f"s010:tools_v2:d{j}.json")
        assert new["prefix"] == original["prefix"]
        assert new["unit"] != original["unit"]
    for f in (OUT / "requests").glob("*.json"):
        request = read(f)
        assert request["role"] in ["agent", "user"]
        assert request["request"]["temperature"] == 1.0
    assert p["state"]["state_id"] == "s010"


def test_historical_inputs_are_unchanged():
    for name, digest in read(OUT / "plan.json")["historical_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_every_executed_persistent_block_maps_to_saved_database():
    a = read(OUT / "trajectory_audit.json")
    for source in a["trajectories"].values():
        for row in source:
            for turn in row["partner_turns"]:
                assert turn["state_after_matches_saved"] is True
                assert not turn["schema_errors"]
                assert turn["fidelity_verdict"]["faithful"] is True


def test_zero_success_is_not_infeasibility_proof():
    a = read(OUT.parent / "v7_c_step2_20261005/reclassification.json")
    for r in a["cases"]:
        if r["new_class"] == "hard_for_both":
            assert (
                r["rates"]["Sol_fixed"]["successes"]
                + r["rates"]["Luna_fixed"]["successes"]
                > 0
            )
        if r["new_class"] == "infeasible_after_block":
            assert r["db_changes"]


if __name__ == "__main__":
    import unittest

    suite = unittest.TestSuite(
        unittest.FunctionTestCase(fn)
        for name, fn in sorted(globals().copy().items())
        if name.startswith("test_")
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
