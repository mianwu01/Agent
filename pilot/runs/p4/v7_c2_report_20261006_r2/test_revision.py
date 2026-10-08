"""Tests of authentication termination and complete compact label coverage."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import c2 as c
import c2_auth_transport as transport


class RevisionTests(unittest.TestCase):
    def test_stop_uses_native_goal_not_hidden_200mbps_assertion(self):
        task = SimpleNamespace(id="[mobile_data_issue]test")
        env = SimpleNamespace(
            user_tools=SimpleNamespace(
                _run_speed_test=lambda: (137.5, "Excellent"),
                db=SimpleNamespace(device=SimpleNamespace(data_enabled=True)),
            )
        )
        prefix = [
            {"role": "user", "tool_calls": [{"id": "speed", "name": "run_speed_test"}]},
            {
                "role": "tool",
                "requestor": "user",
                "id": "speed",
                "content": "137.5 Mbps, Excellent",
            },
            {"role": "assistant", "content": "What did the test show?"},
        ]
        self.assertEqual(
            c.terminal_check(
                task, prefix, [{"role": "user", "content": "###STOP###"}], env
            ),
            [],
        )

    def test_transfer_offers_are_not_announcements(self):
        for text in [
            "If this feels too stressful, leave it unchanged and I can transfer you to a human technical-support agent.",
            "Would you like me to transfer you to a human agent?",
            "I cannot transfer you to a specialist.",
            "If you'd like, I'll transfer you to a human agent.",
        ]:
            self.assertFalse(c.transfer_announced(text), text)
        for text in [
            "You are being transferred to a human agent. Please hold on.",
            "I'm transferring you to a human specialist now.",
            '{"message":"I will transfer you to another agent now."}',
        ]:
            self.assertTrue(c.transfer_announced(text), text)

    def test_timeout_retry_is_once_and_does_not_retry_auth(self):
        call = Mock(side_effect=[TimeoutError("timeout"), "response"])
        self.assertEqual(transport.retry_timeout_once(call, {}), "response")
        self.assertEqual(call.call_count, 2)
        call = Mock(side_effect=TimeoutError("timeout"))
        with self.assertRaises(TimeoutError):
            transport.retry_timeout_once(call, {})
        self.assertEqual(call.call_count, 2)
        call = Mock(side_effect=transport.AuthenticationStop("401"))
        with self.assertRaises(transport.AuthenticationStop):
            transport.retry_timeout_once(call, {})
        self.assertEqual(call.call_count, 1)

    def test_insufficient_balance_stops_followup_calls(self):
        transport.AUTH_STOP.clear()
        transport.AUTH_FAILURES = 0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.txt").write_text("unit-test-placeholder")
            original = Mock(side_effect=Exception("Insufficient account balance"))
            with (
                patch.object(c, "ROOT", root),
                patch.object(c, "OUT", root),
                patch.object(c, "ACTIVE", root),
                patch.object(c.x.p4, "audited_completion", original),
                patch.object(c.x.p4, "configure_transport"),
            ):
                transport.install(c, 1)
                for _ in range(2):
                    with self.assertRaises(transport.ServiceBalanceStop):
                        c.x.p4.audited_completion(messages=[])
                self.assertEqual(original.call_count, 1)
                self.assertTrue((root / "balance_stop.json").exists())

    def test_context_removed_persona_separated(self):
        rules = c.read(c.rules_path())
        self.assertEqual(len(rules["removed_context_rows"]), 13)
        self.assertEqual(sum(r["category"] == "persona" for r in rules["rules"]), 15)
        self.assertFalse(any(r.get("verbatim") == "Persona:" for r in rules["rules"]))

    def test_compact_all_rules_and_negative_labels(self):
        style = [{"rule_id": "style"}, {"rule_id": "persona"}]
        scenario = [{"rule_id": "scenario"}]
        judgment = {
            "assessed_style_rule_ids": ["style", "persona"],
            "assessed_scenario_rule_ids": ["scenario"],
            "style_departures": [{"rule_id": "style", "evidence": "quote"}],
            "scenario_violations": [],
        }
        result = c.expand_judgment(judgment, style, scenario)
        self.assertEqual(
            [r["status"] for r in result["style_labels"]], ["out_of_rule", "in_rule"]
        )
        self.assertFalse(result["scenario_labels"][0]["violation"])

    def test_missing_assessed_rule_rejected(self):
        with self.assertRaises(AssertionError):
            c.expand_judgment(
                {
                    "assessed_style_rule_ids": [],
                    "assessed_scenario_rule_ids": [],
                    "style_departures": [],
                    "scenario_violations": [],
                },
                [{"rule_id": "missing"}],
                [],
            )

    def test_401_stops_future_calls_and_controllers(self):
        class Unauthorized(Exception):
            status_code = 401

        transport.AUTH_STOP.clear()
        transport.AUTH_FAILURES = 0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.txt").write_text("unit-test-placeholder")
            original = Mock(side_effect=Unauthorized("invalid"))
            with (
                patch.object(c, "ROOT", root),
                patch.object(c, "OUT", root),
                patch.object(c, "ACTIVE", root),
                patch.object(c.x.p4, "audited_completion", original),
                patch.object(c.x.p4, "configure_transport"),
            ):
                transport.install(c, 1)
                with self.assertRaises(Unauthorized):
                    c.x.p4.audited_completion(messages=[])
                with self.assertRaises(transport.AuthenticationStop):
                    c.x.p4.audited_completion(messages=[])
                self.assertTrue((root / "authentication_stop.json").exists())
                with self.assertRaises(transport.AuthenticationStop):
                    c.x.p4.audited_completion(messages=[])
                self.assertEqual(original.call_count, 2)


if __name__ == "__main__":
    unittest.main()
