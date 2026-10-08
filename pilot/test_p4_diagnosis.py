"""Meaningful checks for information isolation, fixed actions and cost auditing."""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import p4_diagnosis as p4

from tau2.data_model.message import AssistantMessage, UserMessage


class DiagnosisTests(unittest.TestCase):
    def test_agent_view_hides_user_tools_and_preserves_indices(self):
        messages = [
            {"role": "assistant", "content": "Please inspect your data setting."},
            {
                "role": "user",
                "tool_calls": [
                    {
                        "id": "u1",
                        "name": "check_network_status",
                        "arguments": {},
                        "requestor": "user",
                    }
                ],
            },
            {
                "role": "tool",
                "id": "u1",
                "content": "PRIVATE DEVICE STATE",
                "requestor": "user",
            },
            {"role": "user", "content": "Mobile data is ON."},
        ]
        visible = p4.agent_view(messages)
        self.assertEqual([m["index"] for m in visible], [0, 3])
        self.assertNotIn("PRIVATE DEVICE STATE", str(visible))

    def test_agent_view_keeps_agent_tool_results(self):
        messages = [
            {
                "role": "tool",
                "id": "a1",
                "content": "ACCOUNT STATE",
                "requestor": "assistant",
            }
        ]
        visible = p4.agent_view(messages)
        self.assertEqual(visible[0]["content"], "ACCOUNT STATE")
        self.assertEqual(visible[0]["tool_calls"], [])

    def test_fixed_action_is_once_and_does_not_reuse_generation_usage(self):
        agent = SimpleNamespace(
            _generate_next_message=lambda message, state: AssistantMessage(
                role="assistant", content="native suffix"
            )
        )
        original = AssistantMessage(
            role="assistant",
            content="fixed",
            usage={"prompt_tokens": 100, "completion_tokens": 5},
        )
        p4.force_response(agent, original.model_dump(mode="json"))
        state = SimpleNamespace(messages=[])
        incoming = UserMessage(role="user", content="observed report")
        first = agent._generate_next_message(incoming, state)
        self.assertEqual(first.content, "fixed")
        self.assertIsNone(first.usage)
        self.assertIsNotNone(first.timestamp)
        self.assertEqual(state.messages, [incoming])
        second = agent._generate_next_message(incoming, state)
        self.assertEqual(second.content, "native suffix")

    def test_horizon_counts_multicall_as_one_environment_step(self):
        prefix = [
            {"role": "assistant", "content": "greeting"},
            {"role": "user", "content": "request"},
            {"role": "assistant", "tool_calls": [{"name": "a"}, {"name": "b"}]},
            {"role": "tool", "content": "a result"},
            {"role": "tool", "content": "b result"},
        ]
        self.assertEqual(p4.prefix_steps(prefix), 3)

    def test_failed_provider_attempt_is_durable_with_unknown_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(p4, "OUT", Path(directory)),
                patch.object(p4, "ORIGINAL_COMPLETION", side_effect=TimeoutError),
            ):
                with self.assertRaises(TimeoutError):
                    p4.audited_completion(
                        model="openai/example", messages=[], num_retries=0
                    )
            rows = list((Path(directory) / "requests").glob("*.json"))
            self.assertEqual(len(rows), 1)
            record = p4.read(rows[0])
            self.assertEqual(record["status"], "error")
            self.assertIsNone(record["usage"])

    def test_mutating_prefix_initializes_once_and_fixed_tool_finalizes(self):
        original_out = p4.OUT
        case = next(
            c
            for c in p4.read(original_out / "approved_cases.json")["cases"]
            if c["sample_id"] == "s003"
        )
        real_builder = p4.build_text_orchestrator
        initializations = []

        def offline_builder(*args, **kwargs):
            orch = real_builder(*args, **kwargs)
            original_init = orch.initialize

            def initialize():
                initializations.append(True)
                return original_init()

            orch.initialize = initialize
            orch.agent._generate_next_message = lambda message, state: AssistantMessage(
                role="assistant",
                content="YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
            )
            orch.user.generate_next_message = lambda message, state: (
                UserMessage(role="user", content="###TRANSFER###"),
                state,
            )
            return orch

        with tempfile.TemporaryDirectory() as directory:
            temp_out = Path(directory)
            (temp_out / "sources").mkdir()
            shutil.copyfile(
                original_out / "sources/s003.json", temp_out / "sources/s003.json"
            )
            shutil.copyfile(original_out / "tasks.json", temp_out / "tasks.json")
            with (
                patch.object(p4, "OUT", temp_out),
                patch.object(
                    p4, "build_text_orchestrator", side_effect=offline_builder
                ),
            ):
                row = p4.run_one((case, "fixed_original", 999), 0)
            self.assertEqual(row["status"], "completed", row.get("error_message"))
            self.assertEqual(len(initializations), 1)
            self.assertTrue(row["state_trace"])


if __name__ == "__main__":
    unittest.main()
