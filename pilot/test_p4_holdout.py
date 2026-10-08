"""Meaningful grounding and independent-holdout checks."""

import unittest

import p4_holdout as holdout


class HoldoutTests(unittest.TestCase):
    def test_locators_reconstruct_escaped_tool_argument_without_invented_quotes(self):
        text = 'Device tools are unavailable; the phone reports "ON".'
        view = [
            {
                "index": 4,
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"name": "transfer_to_human_agents", "arguments": {"summary": text}}
                ],
            }
        ]
        raw = {
            "category": "C",
            "decision_index": 4,
            "evidence_indices": [4],
            "policy_line_ids": [0],
            "certificate": {
                "applicability": "device data off",
                "legitimate_escalation_excluded": "not exhausted",
            },
        }
        label = holdout.validate_locators(
            raw, view, ["Guide the user to use toggle_data() when data is off."]
        )
        self.assertEqual(
            label["grounded_evidence"][0]["tool_calls"][0]["arguments"]["summary"], text
        )

    def test_generic_diagnostics_needed_is_not_C(self):
        view = [
            {
                "index": 2,
                "role": "assistant",
                "content": "Further device diagnostics are needed.",
                "tool_calls": [],
            }
        ]
        raw = {"category": "C", "decision_index": 2, "policy_line_ids": [0]}
        with self.assertRaisesRegex(AssertionError, "tool-denial"):
            holdout.validate_locators(
                raw, view, ["Guide the user with check_network_status()."]
            )

    def test_inaccessible_evidence_locator_is_rejected(self):
        raw = {"category": "none", "decision_index": None, "evidence_indices": [99]}
        with self.assertRaisesRegex(AssertionError, "Inaccessible"):
            holdout.validate_locators(raw, [], [])

    def test_holdout_is_disjoint_and_stratified_by_frozen_screen(self):
        sample = holdout.p4.read(holdout.OUT / "sample.json")
        self.assertEqual(len(sample["items"]), 48)
        excluded_ids = set(sample["excluded_ids"])
        excluded_tasks = set(sample["excluded_tasks"])
        self.assertEqual(len(excluded_tasks), 11)
        for item in sample["items"]:
            self.assertNotIn(item["simulation_id"], excluded_ids)
            self.assertNotIn(item["task_id"], excluded_tasks)
            sim = holdout.p4.read(
                holdout.OUT / "sources" / (item["sample_id"] + ".json")
            )
            self.assertEqual(
                holdout.capability_screen(sim), item["stratum"] == "screen_hit"
            )


if __name__ == "__main__":
    unittest.main()
