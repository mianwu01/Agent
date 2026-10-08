"""Tests of mode boundaries, held-out folds and data/accounting consistency."""

import collections
import copy
import json
import unittest
from pathlib import Path

import numpy as np
import tier_a as ta

OUT = Path(__file__).resolve().parent


class TierATests(unittest.TestCase):
    def test_count_ties_are_random(self):
        result = ta.top_metrics(np.ones(80), np.arange(80, dtype=float))
        self.assertIsNone(result["spearman"])
        self.assertAlmostEqual(result["lift"], 1)
        self.assertAlmostEqual(result["capture"], 0.25)

    def test_zero_target_not_false_zero_correlation(self):
        result = ta.top_metrics(np.arange(80), np.zeros(80))
        self.assertIsNone(result["spearman"])
        self.assertIsNone(result["lift"])
        self.assertEqual(result["precision"], 0)

    def test_boundary_tie_fractional(self):
        result = ta.top_metrics(
            np.array([0.0, 1.0, 1.0, 0.0]), np.array([0.0, 4.0, 8.0, 0.0])
        )
        self.assertEqual(result["selected_new_suffixes"], 6)
        self.assertEqual(result["lift"], 2)

    def test_mode_identity_and_abstraction(self):
        row = ta.load_features()[0]
        paths = {row["task_id"]: ["device.mobile_data_enabled"]}
        other = copy.deepcopy(row)
        other["unit"] = "another"
        other["state_id"] = "other"
        self.assertEqual(ta.mode_key(row, "M4", paths), ta.mode_key(other, "M4", paths))
        other["agent_tool_path"] = row["agent_tool_path"] + ["repeat"]
        self.assertEqual(ta.mode_key(row, "M3", paths), ta.mode_key(other, "M3", paths))
        self.assertNotEqual(
            ta.mode_key(row, "M4", paths), ta.mode_key(other, "M4", paths)
        )
        self.assertEqual(ta.categorical(1), ta.categorical(100))
        self.assertNotEqual(ta.categorical(True), ta.categorical(1))

    def test_suffix_features_replay_outcomes(self):
        rows = ta.load_features()
        self.assertEqual(len(rows), 1920)
        self.assertEqual(len({r["unit"] for r in rows}), 1920)
        for arm, expected in [("q", 560), ("q_prime", 571)]:
            selected = [r for r in rows if r["family"] == arm]
            self.assertEqual(len(selected), 960)
            self.assertEqual(sum(r["reward"] for r in selected), expected)
        for unit in ["s003:q:d0:r0", "s034:q_prime:d5:r3"]:
            saved = next(r for r in rows if r["unit"] == unit)
            task = ta.read(ta.SRC / "tasks.json")[saved["task_id"]]
            sim = ta.read(ta.SRC / "trajectories" / f"{unit}.json")
            orch = ta.v6.build(ta.Task.model_validate(task), sim["messages"])
            orch.initialize()
            self.assertEqual(
                saved["final_user_state"], ta.v6.p4.state(orch.environment)["user"]
            )

    def test_curves_end_at_observed_mode_count(self):
        curves = ta.read(ta.DIRS[2] / "discovery_curves.json")
        stats = ta.read(ta.DIRS[2] / "discovery_statistics.json")
        for cohort, modes in curves.items():
            for mode, sources in modes.items():
                for source, row in sources.items():
                    self.assertEqual(len(row["mean"]), row["n"])
                    self.assertEqual(
                        row["mean"][-1], stats[cohort][mode][source]["observed_modes"]
                    )
                    self.assertTrue(
                        all(a <= b for a, b in zip(row["mean"], row["mean"][1:]))
                    )

    def test_heldout_split_novelty(self):
        rows = [
            json.loads(s)
            for s in (ta.DIRS[2] / "mode_rows.jsonl").read_text().splitlines()
        ]
        directions = collections.defaultdict(list)
        for r in rows:
            directions[(r["state_id"], r["family"])].append(r)
        folds = [
            json.loads(s)
            for s in (ta.DIRS[3] / "direction_folds.jsonl").read_text().splitlines()
        ]
        for mode in ["M2", "M3", "M4"]:
            for fold in [0, 1]:
                past = {
                    d: [r for r in rs if (r["j"] < 3) == (fold == 0)]
                    for d, rs in directions.items()
                }
                globalpast = {r["modes"][mode] for rs in past.values() for r in rs}
                for saved in [
                    r for r in folds if r["mode"] == mode and r["fold"] == fold
                ]:
                    d = (saved["state_id"], saved["family"])
                    future = [r for r in directions[d] if (r["j"] >= 3) == (fold == 0)]
                    self.assertEqual(len(past[d]), 12)
                    self.assertEqual(len(future), 12)
                    self.assertFalse(
                        {r["unit"] for r in past[d]} & {r["unit"] for r in future}
                    )
                    local = {r["modes"][mode] for r in past[d]}
                    self.assertEqual(
                        saved["targets"]["own_past"],
                        sum(r["modes"][mode] not in local for r in future),
                    )
                    self.assertEqual(
                        saved["targets"]["all_directions_past"],
                        sum(r["modes"][mode] not in globalpast for r in future),
                    )


if __name__ == "__main__":
    unittest.main()
