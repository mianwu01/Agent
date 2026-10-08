"""Checks for strict certificate rejection and reminder information isolation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import p4_calibration as calibration

from tau2.data_model.tasks import Task


class CalibrationTests(unittest.TestCase):
    def test_c_rejects_needed_diagnostics_without_capability_denial(self):
        text = "Further device diagnostics are needed."
        view = [{"index": 0, "role": "assistant", "content": text}]
        label = {
            "category": "C",
            "decision_index": 0,
            "evidence": [],
            "certificate": {"unavailable_tool_quote": text},
        }
        with self.assertRaisesRegex(ValueError, "capability-denial"):
            calibration.strict_certificate(label, view, "")

    def test_c_requires_explicit_rationale_at_decision(self):
        view = [
            {"index": 0, "role": "assistant", "content": "Further diagnostics needed."}
        ]
        label = {
            "category": "C",
            "decision_index": 0,
            "evidence": [],
            "policy_quote": "Guide the user.",
            "certificate": {
                "unavailable_tool_quote": "No diagnostic tools available.",
                "delegable_procedure_quote": "Guide the user.",
                "applicability": "device diagnosis",
                "legitimate_escalation_excluded": "not exhausted",
            },
        }
        with self.assertRaisesRegex(ValueError, "explicit rationale"):
            calibration.strict_certificate(label, view, "Guide the user.")

    def test_b_rejects_conditional_action_even_with_two_states(self):
        view = [{"index": 1, "role": "assistant", "content": "Turn data on if off."}]
        label = {
            "category": "B",
            "decision_index": 1,
            "evidence": [],
            "certificate": {
                "compatible_states": ["ON", "OFF"],
                "same_action_different_effect": "Toggle changes state.",
                "unconditional": False,
            },
        }
        with self.assertRaisesRegex(ValueError, "information-value"):
            calibration.strict_certificate(label, view, "")

    def test_reminder_is_agent_only_and_context_local(self):
        agent = SimpleNamespace(domain_policy="native policy")
        user = SimpleNamespace(domain_policy="native user policy")
        orch = SimpleNamespace(agent=agent, user=user)
        with patch.object(calibration, "NATIVE_BUILDER", return_value=orch):
            token = calibration.APPENDIX.set("capability reminder")
            try:
                changed = calibration.reminder_builder()
            finally:
                calibration.APPENDIX.reset(token)
        self.assertEqual(
            changed.agent.domain_policy, "native policy\n\ncapability reminder"
        )
        self.assertEqual(changed.user.domain_policy, "native user policy")
        self.assertEqual(calibration.APPENDIX.get(), "")

    def test_sample_excludes_previous_tasks_and_trajectories(self):
        old = calibration.p4.read(calibration.OLD / "sample.json")
        old_ids = {r["simulation_id"] for r in old["items"]}
        old_tasks = {
            r["task_id"]
            for r in calibration.p4.read(calibration.OLD / "approved_cases.json")[
                "cases"
            ]
        }
        sample = calibration.p4.read(calibration.OUT / "sample.json")["items"]
        self.assertEqual(len(sample), 60)
        self.assertFalse(old_ids & {r["simulation_id"] for r in sample})
        self.assertFalse(old_tasks & {r["task_id"] for r in sample})

    def test_native_replayed_prefix_keeps_reminder_in_agent_system_only(self):
        case = calibration.p4.read(calibration.OUT / "approved_cases.json")["cases"][0]
        sim = calibration.p4.read(
            calibration.OUT / "sources" / (case["sample_id"] + ".json")
        )
        task = Task.model_validate(
            calibration.p4.read(calibration.OUT / "tasks.json")[case["task_id"]]
        )
        prefix = sim["messages"][: case["decision_index"]]
        reminder = calibration.REMINDERS["capability_policy"]
        token = calibration.APPENDIX.set(reminder)
        try:
            orch = calibration.reminder_builder(
                calibration.p4.config(), calibration.p4.with_prefix(task, prefix)
            )
            orch.initialize()
        finally:
            calibration.APPENDIX.reset(token)
        self.assertEqual(
            calibration.p4.digest(calibration.p4.state(orch.environment)),
            case["prefix_state_sha256"],
        )
        self.assertIn(reminder, str(orch.agent_state.system_messages))
        self.assertNotIn(reminder, str(orch.user_state.system_messages))


if __name__ == "__main__":
    unittest.main()
