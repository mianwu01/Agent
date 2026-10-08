"""Offline checks for replay units, schema validation and persistent-state adoption."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze
import b1 as b
import numpy as np

from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage
from tau2.data_model.simulation import RewardInfo


class B1Tests(unittest.TestCase):
    def test_transport_retry_preserves_arguments(self):
        calls = []
        sentinel = object()

        def completion(**kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                raise b.litellm.Timeout(
                    message="synthetic timeout", model="test", llm_provider="openai"
                )
            return sentinel

        args = {
            "model": "test",
            "messages": [{"role": "user", "content": "fixed input"}],
            "temperature": 1,
        }
        self.assertIs(b.retry_transport_completion(completion, **args), sentinel)
        self.assertEqual(calls, [args] * 3)
        calls.clear()

        def invalid(**kwargs):
            calls.append(kwargs)
            raise ValueError("synthetic non-transport failure")

        with self.assertRaises(ValueError):
            b.retry_transport_completion(invalid, **args)
        self.assertEqual(len(calls), 1)

    def test_original_block_exact(self):
        p = b.read(b.OUT / "plan.json")
        for c in p["states"]:
            prefix, block = b.source_block(c)
            r = b.read(b.D["step1"] / "replies" / f"{c['state_id']}:original:d0.json")
            self.assertEqual(prefix, r["prefix"])
            self.assertEqual(block, r["partner_block"])

    def test_all_exclusive_producers_retained_and_deduplicated(self):
        p = b.read(b.OUT / "plan.json")
        rows = [
            json.loads(s)
            for s in (b.BASE / "v7_e2_20261004/mode_rows.jsonl")
            .read_text()
            .splitlines()
        ]
        q = {r["modes"]["M2"] for r in rows if r["family"] == "q"}
        replies = {f.stem: b.read(f) for f in (b.SRC / "replies").glob("*.json")}
        needed = {
            (r["state_id"], replies[r["unit"].rsplit(":", 1)[0]]["partner_signature"])
            for r in rows
            if r["family"] == "q_prime" and r["modes"]["M2"] not in q
        }
        actual = {(r["state_id"], r["partner_signature"]) for r in p["candidates"]}
        self.assertTrue(needed <= actual)
        self.assertEqual(len(actual), len(p["candidates"]))
        self.assertEqual(sum(r["random_control"] for r in p["candidates"]), 5)
        self.assertFalse(
            actual
            & {
                (r["state_id"], r["partner_signature"])
                for r in p["candidates"]
                if r["state_id"] in b.TRANSFER
            }
        )

    def test_schema_validation(self):
        p = b.read(b.OUT / "plan.json")
        c = p["states"][0]
        task = b.Task.model_validate(b.read(b.SRC / "tasks.json")[c["task_id"]])
        orch = b.v6.build(task, [])
        tools = orch.user.tools
        self.assertEqual(
            b.tool_candidate_errors({"message": "Question?", "tool_calls": []}, tools),
            [],
        )
        self.assertTrue(
            b.tool_candidate_errors(
                {
                    "message": None,
                    "tool_calls": [{"name": "invented", "arguments": {}}],
                },
                tools,
            )
        )
        native = UserMessage(
            role="user",
            content="I will toggle data now.",
            tool_calls=[
                ToolCall(
                    id="native_validation_test",
                    name="toggle_data",
                    arguments={},
                    requestor="user",
                )
            ],
        )
        native.validate()
        self.assertEqual(
            b.tool_candidate_errors(
                {
                    "message": native.content,
                    "tool_calls": [{"name": "toggle_data", "arguments": {}}],
                },
                tools,
            ),
            [],
        )
        self.assertTrue(
            b.tool_candidate_errors(
                {
                    "message": None,
                    "tool_calls": [
                        {"name": "toggle_data", "arguments": {"invented": 1}}
                    ],
                },
                tools,
            )
        )
        self.assertEqual(
            b.tool_candidate_errors(
                {
                    "message": None,
                    "tool_calls": [{"name": "toggle_data", "arguments": {}}],
                },
                tools,
            ),
            [],
        )

    def test_interval_extremes_do_not_collapse(self):
        lo, hi = analyze.difference_interval(0, 16, 0, 16)
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)
        lo, hi = analyze.difference_interval(16, 16, 0, 16)
        self.assertLess(lo, 1)
        self.assertAlmostEqual(hi, 1)
        a = analyze.difference_interval(3, 16, 11, 16)
        z = analyze.difference_interval(11, 16, 3, 16)
        self.assertTrue(np.allclose(a, [-z[1], -z[0]]))

    def test_persistent_adoption_executes_tools_and_preserves_agent_history(self):
        """Artificial deterministic fixture; never counted as experiment evidence."""
        p = b.read(b.OUT / "plan.json")
        case = next(c for c in p["states"] if c["state_id"] == "s016")
        initial = b.read(b.D["step3a"] / "replies" / "s016:tools:d0.json")
        task = b.Task.model_validate(b.read(b.SRC / "tasks.json")[case["task_id"]])
        real_build = b.v6.build
        seen = []
        turns = []
        adopted = []

        def fake_build(*args, **kwargs):
            orch = real_build(*args, **kwargs)

            def agent_generate(message, state):
                seen.append([m.content for m in state.messages] + [message.content])
                n = len(seen)
                text = (
                    "Please toggle mobile data."
                    if n == 1
                    else "Please toggle mobile data."
                    if n == 2
                    else "###STOP###"
                )
                output = AssistantMessage(role="assistant", content=text)
                state.messages.extend([message, output])
                return output, state

            orch.agent.generate_next_message = agent_generate
            orch.agent.is_stop = lambda message: message.content == "###STOP###"
            return orch

        def fake_reply(case, unit, key, j=0, prefix=None, remaining_steps=None):
            self.assertIn(b.p4.digest([b.ta.semantic(m) for m in prefix])[:16], unit)
            turns.append(prefix[-1]["content"])
            orch = real_build(task, prefix, seed=0, key=key)
            orch.initialize()

            def native_report(message, state):
                state.messages.append(message)
                return UserMessage(
                    role="user", content="Action completed from real tool output."
                )

            orch.user._generate_next_message = native_report
            name = "toggle_data" if "off" in prefix[-1]["content"] else "toggle_data"
            b.paired.first_response(
                orch.user,
                {"message": None, "tool_calls": [{"name": name, "arguments": {}}]},
                unit,
            )
            b.paired.complete_partner(orch)
            messages = [m.model_dump(mode="json") for m in orch.get_messages()]
            after = b.p4.state(orch.environment)
            adopted.append(after["user"]["device"]["data_enabled"])
            return {
                "prefix": messages,
                "partner_block": messages[len(prefix) :],
                "state_after_partner": after,
                "native_step_count": orch.step_count,
                "native_num_errors": orch.num_errors,
            }

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            b.save(target / "tasks.json", b.read(b.SRC / "tasks.json"))
            with (
                patch.object(b.v6, "OUT", target),
                patch.object(b.v6, "build", fake_build),
                patch.object(b, "tools_reply", fake_reply),
                patch(
                    "tau2.evaluator.evaluator.evaluate_simulation",
                    return_value=RewardInfo(reward=0.0),
                ),
            ):
                row = b.persistent_continuation(case, initial, 999, 0)
                self.assertEqual(row["persistent_proposal_turns"], 2)
                self.assertEqual(
                    adopted,
                    [
                        not initial["state_after_partner"]["user"]["device"][
                            "data_enabled"
                        ],
                        initial["state_after_partner"]["user"]["device"][
                            "data_enabled"
                        ],
                    ],
                )
                self.assertIn("Please toggle mobile data.", seen[-1])
                self.assertIn("Please toggle mobile data.", seen[-1])
                trajectory = b.read(target / "trajectories" / f"{row['unit']}.json")
                calls = [
                    c["name"]
                    for m in trajectory["messages"][len(initial["prefix"]) :]
                    if m["role"] == "user"
                    for c in m.get("tool_calls") or []
                ]
                self.assertEqual(calls, ["toggle_data", "toggle_data"])


if __name__ == "__main__":
    unittest.main()
