"""Check full partner action replay and reply-half concentration isolation."""

import json
import types
import unittest
from pathlib import Path

import p4_v6_paired as paired

from tau2.data_model.message import MultiToolMessage, UserMessage
from tau2.data_model.tasks import Task


class PairedReplayTest(unittest.TestCase):
    """Exercise the native forced-user history update and independent estimation."""

    def test_tool_partner_preserves_history_and_replays_state(self):
        root = Path(__file__).parent / "runs/p4/v6_paired_20261004"
        case = json.loads((root / "protocol.json").read_text())["states"][0]
        source = json.loads(
            (root / "sources" / (case["source_id"] + ".json")).read_text()
        )
        task = Task.model_validate(
            json.loads((root / "tasks.json").read_text())[case["task_id"]]
        )
        prefix = source["messages"][: case["index"]]
        orch = paired.v6.build(task, prefix)
        orch.initialize()

        def finish(self, message, state):
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
            return UserMessage(role="user", content="Status checked.")

        orch.user._generate_next_message = types.MethodType(finish, orch.user)
        paired.first_response(
            orch.user,
            {
                "message": None,
                "tool_calls": [{"name": "check_status_bar", "arguments": {}}],
            },
            "offline-tool-check",
        )
        orch.step()
        self.assertEqual(orch.user_state.messages[-2].content, prefix[-1]["content"])
        self.assertEqual(orch.user_state.messages[-1].tool_calls[0].requestor, "user")
        orch.step()
        orch.step()
        messages = [m.model_dump(mode="json") for m in orch.get_messages()]
        restored = paired.v6.build(task, messages)
        restored.initialize()
        self.assertEqual(
            paired.v6.p4.state(orch.environment),
            paired.v6.p4.state(restored.environment),
        )
        self.assertEqual(restored.to_role.value, "agent")

    def test_crossfit_ranks_one_reply_half_and_evaluates_other(self):
        states = [
            {"state_id": "a", "q_prime": {"S_group_A": 0.2, "S_group_B": 0.01}},
            {"state_id": "b", "q_prime": {"S_group_A": 0.01, "S_group_B": 0.2}},
        ]
        result = paired.concentration(states)
        self.assertEqual(result["folds"][0]["top_states"], ["a"])
        self.assertEqual(result["folds"][1]["top_states"], ["b"])
        self.assertAlmostEqual(result["folds"][0]["C10"], 0.01 / 0.21)
        self.assertAlmostEqual(result["folds"][1]["C10"], 0.01 / 0.21)


if __name__ == "__main__":
    unittest.main()
