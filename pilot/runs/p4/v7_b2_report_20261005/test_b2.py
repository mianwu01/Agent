"""Synthetic parser tests and read-only native replay/model preflight."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import b2 as x
import mechanical as m


class DB:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode):
        return self.value


def env(data=True):
    return SimpleNamespace(
        tools=SimpleNamespace(db=DB({})),
        user_tools=SimpleNamespace(
            db=DB({"device": {"data_enabled": data}}),
            _run_speed_test=lambda: (20, "Good"),
            _can_send_mms=lambda: False,
        ),
    )


class Checks(unittest.TestCase):
    def test_authentication_failover_is_audited_and_context_reset(self):
        attempts = []
        token = x.p4.KEY.set(1)

        def fake(completion, **kwargs):
            attempts.append((x.p4.KEY.get(), kwargs["api_key"], kwargs["temperature"]))
            if len(attempts) == 1:
                raise ValueError("Invalid authentication credentials")
            return "response"

        try:
            with patch.object(x.b, "retry_transport_completion", fake):
                self.assertEqual(x.routed_completion(temperature=1.0), "response")
            self.assertEqual(
                attempts,
                [
                    (0, "os.environ/P4_API_KEY_1", 1.0),
                    (2, "os.environ/P4_API_KEY_3", 1.0),
                ],
            )
            self.assertEqual(x.p4.KEY.get(), 1)
        finally:
            x.p4.KEY.reset(token)

    def test_non_authentication_error_does_not_failover(self):
        with patch.object(
            x.b, "retry_transport_completion", side_effect=ValueError("schema invalid")
        ) as call:
            with self.assertRaisesRegex(ValueError, "schema invalid"):
                x.routed_completion(temperature=1.0)
            self.assertEqual(call.call_count, 1)

    def test_call_ids_do_not_create_action_divergences(self):
        a = {
            "role": "assistant",
            "tool_calls": [
                {"id": "a", "name": "refuel_data", "arguments": {"gb_amount": 2}}
            ],
        }
        b = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "b", "name": "refuel_data", "arguments": {"gb_amount": 2}}
            ],
        }
        self.assertIsNone(
            m.first_divergence(m.agent_path([a], 0), m.agent_path([b], 0))
        )
        b["tool_calls"][0]["arguments"]["gb_amount"] = 1
        self.assertEqual(
            m.first_divergence(m.agent_path([a], 0), m.agent_path([b], 0))[
                "agent_decision_ordinal"
            ],
            0,
        )

    def test_wrong_value_after_read_is_observed(self):
        history = [
            {
                "role": "user",
                "tool_calls": [{"id": "t", "name": "check_network_status"}],
            },
            {
                "role": "tool",
                "requestor": "user",
                "id": "t",
                "content": "Mobile Data Enabled: Yes",
            },
        ]
        report = [{"role": "user", "content": "Mobile data is OFF."}]
        result = m.check_claims(history, report, env(True))
        self.assertEqual(result["unobserved_claim_n"], 0)
        self.assertEqual(result["incorrect_claim_n"], 1)

    def test_true_without_read_still_unobserved(self):
        result = m.check_claims(
            [], [{"role": "user", "content": "Mobile data is ON."}], env(True)
        )
        self.assertEqual(result["unobserved_claim_n"], 1)
        self.assertEqual(result["incorrect_claim_n"], 0)

    def test_inline_before_effect_and_no_self_support(self):
        block = [
            {
                "role": "user",
                "content": "Mobile data is OFF.",
                "tool_calls": [{"id": "t", "name": "toggle_data"}],
            },
            {
                "role": "tool",
                "requestor": "user",
                "id": "t",
                "content": "Mobile data is ON.",
            },
        ]
        result = m.check_claims([], block, env(True), env(False))
        self.assertEqual(result["incorrect_claim_n"], 0)
        self.assertEqual(result["unobserved_claim_n"], 1)

    def test_questions_conditionals_settings_ambiguity(self):
        self.assertEqual(
            m.claims(
                "Is mobile data OFF? Please turn airplane mode ON. If Wi-Fi is OFF, turn it ON."
            )[0],
            [],
        )
        self.assertTrue(m.claims("Mobile data is currently disabled.")[0])
        self.assertEqual(m.claims("VPN is ON in settings.")[0], [])
        self.assertEqual(m.claims("Mobile data only works abroad.")[0], [])

    def test_native_field_tools_exist(self):
        from tau2.domains.telecom.user_tools import TelecomUserTools

        self.assertTrue(
            all(
                hasattr(TelecomUserTools, tool)
                for tools in m.FIELD_TOOLS.values()
                for tool in tools
            )
        )

    def test_sol_changes_agent_only_and_branch_state(self):
        p = x.read(x.OUT / "plan.json")
        c = p["cases"][0]
        task = x.b.Task.model_validate(x.read(x.D["a"] / "tasks.json")[c["task_id"]])
        reply = x.read(
            x.D["a"] / "replies" / f"{c['state_id']}:sol_fixed:{c['candidate_id']}.json"
        )
        luna = x.v6.build(task, reply["prefix"])
        sol = x.v6.build(task, reply["prefix"], agent_model=x.SOL)
        luna.initialize()
        sol.initialize()
        self.assertEqual(sol.agent.llm, x.SOL)
        self.assertEqual(sol.user.llm, luna.user.llm)
        self.assertEqual(sol.agent.llm_args["temperature"], 1.0)
        self.assertEqual(x.p4.state(sol.environment), reply["state_after_partner"])
        self.assertEqual(x.p4.state(sol.environment), x.p4.state(luna.environment))


if __name__ == "__main__":
    unittest.main()
