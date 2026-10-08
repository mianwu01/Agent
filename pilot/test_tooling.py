"""Offline protocol/accounting checks; these are not live model runs."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import run_trial
import summarize_trial


class PilotTests(unittest.TestCase):
    def test_native_mode_builders(self):
        """Check all sampled tasks are supported and both native modes build."""
        from solo_compat import register_pilot_dummy_user

        from tau2.data_model.simulation import TextRunConfig
        from tau2.registry import registry
        from tau2.runner import build_text_orchestrator

        tasks = run_trial.sample_tasks()
        solo_user = register_pilot_dummy_user()
        solo_filter = registry.get_agent_task_filter("llm_agent_solo")
        self.assertTrue(all(solo_filter(task) for task in tasks))
        for solo in (False, True):
            config = TextRunConfig(
                domain="telecom",
                agent="llm_agent_solo" if solo else "llm_agent",
                user=solo_user if solo else "user_simulator",
                llm_agent="gpt-4.1-mini-2025-04-14",
                llm_user=run_trial.USER,
                llm_args_agent={"temperature": 1.0},
                llm_args_user={"temperature": 1.0},
            )
            orchestrator = build_text_orchestrator(config, tasks[0], seed=0)
            self.assertEqual(orchestrator.solo_mode, solo)

    def test_litellm_roundtrip_and_reasoning_forwarding(self):
        """An HTTP stub verifies the actual LiteLLM request/response path."""
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                message = {"role": "assistant", "content": "done"}
                if len(requests) == 1:
                    message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_test",
                                "type": "function",
                                "function": {
                                    "name": "pilot_echo",
                                    "arguments": '{"value":"tau2-pilot"}',
                                },
                            }
                        ],
                    }
                response = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "pilot-served-alias",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls"
                            if len(requests) == 1
                            else "stop",
                            "message": message,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 4,
                        "total_tokens": 16,
                    },
                }
                data = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                run_trial.probe(
                    "stub",
                    "openai/pilot-served-alias",
                    {
                        "api_base": f"http://127.0.0.1:{server.server_port}/v1",
                        "api_key": "EMPTY",
                        "temperature": 1.0,
                        "reasoning_effort": "medium",
                        "allowed_openai_params": ["reasoning_effort"],
                    },
                    Path(directory),
                )
                result = json.loads(
                    (Path(directory) / "stub-tool-probe.json").read_text()
                )
                self.assertEqual(
                    result["first"]["usage"],
                    {"prompt_tokens": 12, "completion_tokens": 4},
                )
            self.assertEqual(len(requests), 2)
            for request in requests:
                self.assertEqual(request["reasoning_effort"], "medium")
                self.assertEqual(request["temperature"], 1.0)
                self.assertEqual(request["model"], "pilot-served-alias")
            self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
            self.assertEqual(requests[1]["messages"][-1]["tool_call_id"], "call_test")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_accounting_and_infrastructure_errors(self):
        """Verify weighting, mixed outcomes, role attribution and error handling."""
        ids = [str(i) for i in range(10)]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(summarize_trial, "RUNS", Path(directory)),
        ):
            for mode, trials in [("default", 4), ("no-user", 2)]:
                sims = []
                for task in ids:
                    for trial in range(trials):
                        messages = [
                            {
                                "role": "assistant",
                                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                            },
                            {"role": "tool", "content": "result"},
                        ]
                        if mode == "default":
                            messages.append(
                                {
                                    "role": "user",
                                    "usage": {
                                        "prompt_tokens": 6,
                                        "completion_tokens": 3,
                                    },
                                }
                            )
                        sims.append(
                            {
                                "id": f"{mode}-{task}-{trial}",
                                "task_id": task,
                                "trial": trial,
                                "termination_reason": "agent_stop",
                                "reward_info": {"reward": int(trial > 0)},
                                "duration": 9,
                                "messages": messages,
                            }
                        )
                path = Path(directory) / "mini" / mode / "results.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"simulations": sims}))
            row = summarize_trial.summarize("mini", ids)
            self.assertEqual(row["default_success_rate"], 0.75)
            self.assertEqual(row["no-user_success_rate"], 0.5)
            self.assertEqual(row["mixed_tasks"], 10)
            self.assertEqual(row["mean_agent_prompt_tokens"], 10)
            self.assertEqual(row["mean_user_prompt_tokens"], 4)
            self.assertEqual(row["mean_user_completion_tokens"], 2)
            self.assertEqual(row["mean_messages"], 8 / 3)
            data = json.loads(path.read_text())
            data["simulations"][0]["termination_reason"] = "infrastructure_error"
            path.write_text(json.dumps(data))
            row = summarize_trial.summarize("mini", ids)
            self.assertIn("infrastructure error", row["status"])
            self.assertNotIn("default_success_rate", row)


if __name__ == "__main__":
    unittest.main()
