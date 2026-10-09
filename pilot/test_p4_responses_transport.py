"""Verify native prompt, tool-history and cost settings survive Responses routing."""

import unittest

from p4_responses_transport import (
    RelayProtocolError,
    completion_response,
    responses_payload,
    validate_response,
)


class ResponsesTests(unittest.TestCase):
    def kwargs(self):
        return {
            "model": "openai/gpt-5.6-luna",
            "messages": [
                {"role": "system", "content": "Exact native private scenario."},
                {"role": "user", "content": "Please help."},
            ],
            "temperature": 1.0,
            "reasoning_effort": "none",
            "max_completion_tokens": 128,
        }

    def test_native_system_verbatim_no_added_codex_instructions(self):
        payload = responses_payload(self.kwargs())
        self.assertEqual(payload["instructions"], "Exact native private scenario.")
        self.assertEqual(payload["model"], "gpt-5.6-luna")
        self.assertEqual(payload["temperature"], 1.0)
        self.assertEqual(payload["max_output_tokens"], 128)
        self.assertFalse(payload["store"])

    def test_missing_system_rejected_before_request(self):
        kwargs = self.kwargs()
        kwargs["messages"] = kwargs["messages"][1:]
        with self.assertRaises(RelayProtocolError):
            responses_payload(kwargs)

    def test_interleaved_system_rejected_before_request(self):
        kwargs = self.kwargs()
        kwargs["messages"].append({"role": "system", "content": "later"})
        with self.assertRaises(RelayProtocolError):
            responses_payload(kwargs)

    def test_tool_call_and_result_keep_ids_and_json(self):
        kwargs = self.kwargs()
        kwargs["messages"] += [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "check_mode",
                            "arguments": '{"field":"network_mode"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"mode":"2G"}'},
        ]
        payload = responses_payload(kwargs)
        self.assertEqual(payload["input"][1]["call_id"], "call_1")
        self.assertEqual(
            payload["input"][2],
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": '{"mode":"2G"}',
            },
        )

    def test_schemas_forced_tool_and_json_format_preserved(self):
        kwargs = self.kwargs()
        function = {
            "name": "check_mode",
            "parameters": {"type": "object", "properties": {}},
        }
        kwargs.update(
            tools=[{"type": "function", "function": function}],
            tool_choice={"type": "function", "function": {"name": "check_mode"}},
            response_format={"type": "json_object"},
        )
        payload = responses_payload(kwargs)
        self.assertEqual(payload["tools"], [{"type": "function", **function}])
        self.assertEqual(
            payload["tool_choice"], {"type": "function", "name": "check_mode"}
        )
        self.assertEqual(payload["text"]["format"], {"type": "json_object"})

    def test_tool_response_and_cached_usage_converted(self):
        response = completion_response(
            {
                "id": "resp_test",
                "model": "gpt-5.6-luna",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "check_mode",
                        "arguments": "{}",
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_tokens_details": {"cached_tokens": 50},
                },
            }
        )
        self.assertEqual(response.choices[0].message.tool_calls[0].id, "call_1")
        self.assertEqual(response.choices[0].finish_reason, "tool_calls")
        self.assertEqual(response.usage.prompt_tokens_details.cached_tokens, 50)

    def test_changed_prompt_temperature_model_or_limit_rejected(self):
        payload = responses_payload(self.kwargs())
        raw = {**payload, "usage": {"output_tokens": 5}}
        validate_response(payload, raw)
        for field, value in [
            ("instructions", "Codex injected"),
            ("temperature", 0.0),
            ("model", "gpt-6-luna"),
            ("max_output_tokens", None),
        ]:
            with self.subTest(field=field), self.assertRaises(RelayProtocolError):
                validate_response(payload, {**raw, field: value})

    def test_output_limit_overrun_rejected(self):
        payload = responses_payload(self.kwargs())
        with self.assertRaises(RelayProtocolError):
            validate_response(payload, {**payload, "usage": {"output_tokens": 129}})


if __name__ == "__main__":
    unittest.main()
