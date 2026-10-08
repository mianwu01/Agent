"""Check native control-prefix replay and treatment isolation before API use."""

import unittest

import p4_specificity as s
import p4_specificity_report as report


class SpecificityTests(unittest.TestCase):
    def test_provider_errors_remain_unresolved_in_full_budget_bounds(self):
        rows = [
            {"arm": "capability_policy", "status": "completed", "reward": 1},
            {"arm": "capability_policy", "status": "error"},
        ]
        result = report.arm_summary(rows, 2)["capability_policy"]
        self.assertEqual(result["success_rate_completed_only"], 1)
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(result["unresolved_outcome_sensitivity"], [0.5, 1])

    def test_missing_controls_can_reverse_the_planned_contrast(self):
        rows = [{"arm": "capability_policy", "status": "completed", "reward": 1}]
        arms = report.arm_summary(rows, 2)
        self.assertEqual(report.difference_bounds(arms), [-0.5, 1])

    def test_controls_exclude_previous_tasks_and_have_non_C_reference(self):
        cases = s.c.p4.read(s.OUT / "approved_cases.json")["cases"]
        sample = s.c.p4.read(s.h.OUT / "sample.json")
        refs = {
            r["sample_id"]: r
            for r in s.c.p4.read(s.h.OUT / "assistant_reference.json")["entries"]
        }
        self.assertEqual(len({case["task_id"] for case in cases}), 4)
        for case in cases:
            self.assertNotIn(case["task_id"], sample["excluded_tasks"])
            self.assertIs(refs[case["sample_id"]]["C_candidate"], False)

    def test_all_control_states_and_system_prompts_match_across_arms(self):
        s.verify_frozen()
        tasks = s.c.p4.read(s.OUT / "tasks.json")
        for case in s.c.p4.read(s.OUT / "approved_cases.json")["cases"]:
            sim = s.c.p4.read(s.OUT / "sources" / (case["sample_id"] + ".json"))
            prefix = sim["messages"][: case["decision_index"]]
            task = s.Task.model_validate(tasks[case["task_id"]])
            for arm, reminder in s.c.REMINDERS.items():
                with self.subTest(sample=case["sample_id"], arm=arm):
                    token = s.c.APPENDIX.set(reminder)
                    try:
                        orch = s.c.reminder_builder(
                            s.c.p4.config(), s.c.p4.with_prefix(task, prefix)
                        )
                        orch.initialize()
                    finally:
                        s.c.APPENDIX.reset(token)
                    self.assertEqual(
                        s.c.p4.digest(s.c.p4.state(orch.environment)),
                        case["prefix_state_sha256"],
                    )
                    if reminder:
                        self.assertIn(
                            reminder,
                            "\n".join(
                                m.content for m in orch.agent_state.system_messages
                            ),
                        )
                        self.assertNotIn(
                            reminder,
                            "\n".join(
                                m.content for m in orch.user_state.system_messages
                            ),
                        )


if __name__ == "__main__":
    unittest.main()
