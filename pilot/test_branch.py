"""Replay, proposal isolation, and suffix-accounting checks against real pilot data."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_branch
import strong_agent
from branch_common import (
    MESSAGE_LIST,
    config,
    continue_prefix,
    token_totals,
    with_prefix,
)
from run_branch import parse_candidates, proposal_messages, select

from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.data_model.tasks import Task
from tau2.runner import build_text_orchestrator
from tau2.user.user_simulator import UserSimulator
from tau2.utils.llm_utils import to_litellm_messages


class BranchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(
            (Path(__file__).parent / "runs/trial/luna/default/results.json").read_text()
        )
        cls.tasks = {t["id"]: Task.model_validate(t) for t in cls.data["tasks"]}

    def test_replay_and_exact_native_user_view(self):
        """Every selected position replays and matches the native generation input."""
        sources = {s["id"]: s for s in self.data["simulations"]}
        manifest = select(self.data)
        self.assertEqual(manifest, select(self.data))
        for row in manifest["positions"]:
            source = sources[row["source_sim_id"]]
            prefix = source["messages"][: row["i"]]
            task = self.tasks[source["task_id"]]
            orch = build_text_orchestrator(
                config(), with_prefix(task, prefix), seed=123
            )
            orch.initialize()
            expected = proposal_messages(orch.user, prefix)[:-1]
            with patch(
                "tau2.user.user_simulator.generate",
                return_value=AssistantMessage(role="assistant", content="test"),
            ) as generate:
                orch.user.generate_next_message(orch.message, orch.user_state)
                actual = generate.call_args.kwargs["messages"]
            self.assertEqual(to_litellm_messages(actual), to_litellm_messages(expected))
            # Poison agent-only fields and verify user prompt/history is unaffected.
            poisoned = task.model_copy(deep=True)
            poisoned.ticket = "FORBIDDEN_AGENT_TICKET_MARKER"
            if poisoned.evaluation_criteria:
                poisoned.evaluation_criteria = None
            other = build_text_orchestrator(config(), poisoned, seed=123)
            self.assertEqual(
                to_litellm_messages(proposal_messages(other.user, prefix)),
                to_litellm_messages(proposal_messages(orch.user, prefix)),
            )
            replacement = UserMessage(
                role="user", content="Please explain that."
            ).model_dump(mode="json")
            other = build_text_orchestrator(
                config(), with_prefix(task, prefix + [replacement]), seed=123
            )
            other.initialize()
            self.assertEqual(other.to_role.value, "agent")

    def test_terminal_replay_evaluates_original_and_zero_suffix_usage(self):
        """Replay a completed success without model calls; compare original reward."""
        source = next(
            s
            for s in self.data["simulations"]
            if s["reward_info"]["reward"] == 1
            and isinstance(MESSAGE_LIST.validate_python(s["messages"])[-1], UserMessage)
            and UserSimulator.is_stop(MESSAGE_LIST.validate_python(s["messages"])[-1])
        )
        sim, tokens = continue_prefix(
            self.tasks[source["task_id"]], source["messages"], 0, "offline-replay"
        )
        self.assertEqual(sim["reward_info"]["reward"], source["reward_info"]["reward"])
        self.assertEqual(
            tokens,
            {"input": {"agent": 0, "user": 0}, "output": {"agent": 0, "user": 0}},
        )

    def test_strong_reuses_prefix_and_completed_rows(self):
        """Only flipped vs_tail rows run, and a second invocation makes no calls."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            branch = root / "pilot/runs/branch"
            branch.mkdir(parents=True)
            iid = root / "pilot/runs/iid/default"
            iid.mkdir(parents=True)
            task = self.data["tasks"][0]
            (iid / "results.json").write_text(json.dumps({"tasks": [task]}))
            prefix = [{"role": "user", "content": "Replacement text"}]
            (root / "prefix.json").write_text(json.dumps(prefix))
            rows = [
                dict(
                    branch_id=str(i),
                    task_id=task["id"],
                    arm=arm,
                    flipped=flipped,
                    prefix_path="prefix.json",
                )
                for i, (arm, flipped) in enumerate(
                    [("vs_tail", True), ("vs_tail", False), ("resample", True)]
                )
            ]
            source = branch / "branches.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in rows))
            simulation = {
                "reward_info": {"reward": 1},
                "termination_reason": "user_stop",
            }
            tokens = {
                "input": {"agent": 2, "user": 3},
                "output": {"agent": 1, "user": 1},
            }
            with (
                patch.object(strong_agent, "ROOT", root),
                patch.object(strong_agent, "BRANCH", branch),
                patch.object(strong_agent, "load_key"),
                patch.object(
                    strong_agent, "continue_prefix", return_value=(simulation, tokens)
                ) as run,
                patch.object(
                    sys, "argv", ["strong_agent.py", str(source), "test-model"]
                ),
            ):
                strong_agent.main()
                run.assert_called_once()
                self.assertEqual(run.call_args.args[1], prefix)
                self.assertEqual(run.call_args.args[4].llm_user, "openai/gpt-5.6-luna")
                strong_agent.main()
                run.assert_called_once()
            saved = [
                json.loads(line)
                for line in (branch / "strong_agent.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["branch_id"], "0")

    def test_invalid_proposal_preserves_resample_without_extra_call(self):
        """An invalid cached proposal cannot erase or rerun independent resamples."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            branch = root / "branch"
            (branch / "proposals").mkdir(parents=True)
            source = {
                "id": "source",
                "messages": [
                    {"role": "assistant", "content": "Hello"},
                    {"role": "user", "content": "Original"},
                ],
            }
            (branch / "proposals/source:1.json").write_text(
                json.dumps({"response": {"content": "invalid"}})
            )
            task = next(iter(self.tasks.values()))
            sim = {
                "messages": [
                    source["messages"][0],
                    {"role": "user", "content": "Regenerated"},
                ],
                "reward_info": {"reward": 1},
                "termination_reason": "user_stop",
            }
            tok = {"input": {"agent": 0, "user": 1}, "output": {"agent": 0, "user": 1}}
            with (
                patch.object(run_branch, "ROOT", root),
                patch.object(run_branch, "BRANCH", branch),
                patch.object(
                    run_branch, "continue_prefix", return_value=(sim, tok)
                ) as continuation,
                patch.object(run_branch, "generate") as generation,
            ):
                for _ in range(2):
                    with self.assertRaises(ValueError):
                        run_branch.run_position({"i": 1}, task, source)
                self.assertEqual(continuation.call_count, 2)
                generation.assert_not_called()
            self.assertEqual(len(list((branch / "rows").glob("*.json"))), 2)

    def test_replacement_once_and_combined_usage(self):
        """One authorized replacement preserves and counts the malformed call."""
        source = self.data["simulations"][0]
        task = self.tasks[source["task_id"]]
        candidates = [{"message": str(i), "probability": i / 10} for i in range(5)]
        for content in (json.dumps(candidates), "invalid again"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                branch = root / "branch"
                path = branch / "proposals" / f"{source['id']}:1.json"
                path.parent.mkdir(parents=True)
                original = {
                    "response": {
                        "content": "invalid",
                        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                    }
                }
                path.write_text(json.dumps(original))
                response = AssistantMessage(
                    role="assistant",
                    content=content,
                    usage={"prompt_tokens": 11, "completion_tokens": 5},
                )
                with (
                    patch.object(run_branch, "ROOT", root),
                    patch.object(run_branch, "BRANCH", branch),
                    patch.object(run_branch, "generate", return_value=response) as gen,
                ):
                    if content.startswith("["):
                        result = run_branch.propose(task, source, 1, True)
                        self.assertEqual(result["usage"]["prompt_tokens"], 18)
                        self.assertEqual(result["usage"]["completion_tokens"], 8)
                        run_branch.propose(task, source, 1, True)
                    else:
                        for _ in range(2):
                            with self.assertRaises(ValueError):
                                run_branch.propose(task, source, 1, True)
                    self.assertEqual(gen.call_count, 1)
                archived = path.parent / "original_invalid" / path.name
                self.assertEqual(json.loads(archived.read_text()), original)

    def test_candidate_validation_and_usage(self):
        good = [{"message": str(i), "probability": i / 10} for i in range(5)]
        self.assertEqual(parse_candidates(json.dumps(good)), good)
        for bad in [
            good[:4],
            [good[0]] * 5,
            [dict(c, probability=float("nan")) for c in good],
        ]:
            with self.assertRaises(ValueError):
                parse_candidates(json.dumps(bad))
        with self.assertRaises(ValueError):
            token_totals([{"role": "user", "raw_data": {"id": "x"}, "usage": None}])


if __name__ == "__main__":
    unittest.main()
