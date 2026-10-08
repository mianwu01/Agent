"""Verify budget isolation, resume accounting, exact cache and bypass boundaries."""

import contextvars
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from p4_cost_control import (
    BudgetStop,
    CostStore,
    compact_payload,
    judge_key,
    request_only,
    valid_judgment,
)


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "costs.sqlite"
        self.config = {
            "total_usd_cap": 1,
            "arm_usd_cap": 1,
            "sol_usd_cap": 0.3,
            "rates_per_million": {
                "sol": {"input": 1, "output": 1},
                "luna": {"input": 1, "output": 1},
            },
        }
        self.store = CostStore(self.path, self.config)

    def test_parallel_reservations_cannot_exceed_global_cap(self):
        def reserve(i):
            try:
                return CostStore(self.path, self.config).reserve(
                    str(i), "luna", "agent", 200000, 0
                )
            except BudgetStop:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(reserve, range(12)))
        self.assertEqual(sum(r is not None for r in accepted), 5)
        self.assertAlmostEqual(sum(r["usd"] for r in self.store.totals()), 1)

    def test_sol_cap_separate_from_luna(self):
        self.store.reserve("A0", "sol", "judge", 200000, 0)
        with self.assertRaises(BudgetStop):
            self.store.reserve("A1", "sol", "judge", 200000, 0)
        self.store.reserve("A1", "luna", "agent", 200000, 0)

    def test_unknown_reserve_retained_after_reopen(self):
        ident = self.store.reserve("A0", "sol", "judge", 200000, 0)
        self.store.settle(ident)
        reopened = CostStore(self.path, self.config)
        self.assertAlmostEqual(reopened.totals()[0]["usd"], 0.2)
        with self.assertRaises(BudgetStop):
            reopened.reserve("A1", "sol", "judge", 200000, 0)

    def test_actual_usage_releases_reserve(self):
        ident = self.store.reserve("A0", "sol", "judge", 200000, 0)
        self.store.settle(ident, {"prompt_tokens": 10000, "completion_tokens": 5000})
        self.assertAlmostEqual(self.store.totals()[0]["usd"], 0.015)
        self.store.reserve("A0", "sol", "judge", 200000, 0)

    def test_missing_price_never_sends(self):
        with self.assertRaises(BudgetStop):
            self.store.reserve("A0", "unknown", "agent", 1, 1)
        self.assertEqual(self.store.totals(), [])

    def test_pricing_cannot_change_existing_ledger(self):
        with self.assertRaises(ValueError):
            CostStore(self.path, {**self.config, "sol_usd_cap": 2})

    def test_cache_separates_model_rules_and_state(self):
        messages = [
            {"role": "system", "content": "rule1"},
            {"role": "user", "content": "state1"},
        ]
        key = judge_key("sol", messages, {"temperature": 0})
        self.store.cache(key, {"content": "original"})
        self.assertEqual(self.store.cached(key)["content"], "original")
        for model, ms, settings in [
            ("luna", messages, {"temperature": 0}),
            ("sol", messages, {"temperature": 1}),
            ("sol", [{"content": "rule2"}], {"temperature": 0}),
        ]:
            self.assertIsNone(self.store.cached(judge_key(model, ms, settings)))

    def test_fact_or_goal_change_never_bypasses(self):
        for text in [
            "Could you run a speed test for me? My data is enabled.",
            "Please run a speed test instead of fixing my internet.",
            "I bought 1GB.",
            "Please transfer me.",
        ]:
            self.assertFalse(request_only([{"role": "user", "content": text}]))
        self.assertTrue(
            request_only(
                [{"role": "user", "content": "Could you run a speed test for me?"}]
            )
        )
        self.assertFalse(
            request_only(
                [
                    {
                        "role": "user",
                        "content": "Please run a speed test.",
                        "tool_calls": [{"name": "run_speed_test"}],
                    }
                ]
            )
        )

    def test_incomplete_decision_is_not_cached(self):
        payload = {
            "rule_texts": {"style_and_persona": [], "scenario": [{"rule_id": "r1"}]}
        }
        self.assertFalse(valid_judgment('{"assessed_scenario_rule_ids":[]}', payload))
        self.assertTrue(
            valid_judgment(
                '{"assessed_style_rule_ids":[],"assessed_scenario_rule_ids":["r1"],"style_departures":[],"scenario_violations":[]}',
                payload,
            )
        )

    def test_compact_keeps_private_goal_and_marks_pending(self):
        payload = {
            "rule_texts": {},
            "private_scenario_verbatim": "goal",
            "partner_block": [],
            "programmatic_fact_check": {"claims": []},
            "visible_prior_history": [{"role": "user", "content": "request"}],
        }
        result = compact_payload(payload)
        self.assertEqual(result["private_scenario_verbatim"], "goal")
        self.assertEqual(result["last_agent_request"]["content"], "request")
        self.assertIn("shadow_only", result["validation_status"])

    def test_total_only_usage_stays_reserved(self):
        ident = self.store.reserve("A0", "sol", "judge", 200000, 0)
        self.store.settle(ident, {"total_tokens": 1000})
        self.assertEqual(self.store.totals()[0]["status"], "unknown")
        self.assertAlmostEqual(self.store.totals()[0]["usd"], 0.2)

    def test_null_cached_price_falls_back_to_normal_input(self):
        cfg = {
            **self.config,
            "rates_per_million": {
                "sol": {"input": 1, "output": 1, "cached_input": None}
            },
        }
        store = CostStore(Path(self.tmp.name) / "null.sqlite", cfg)
        ident = store.reserve("A0", "sol", "judge", 200000, 0)
        store.settle(
            ident,
            {
                "prompt_tokens": 10000,
                "completion_tokens": 0,
                "prompt_tokens_details": {"cached_tokens": 10000},
            },
        )
        self.assertAlmostEqual(store.totals()[0]["usd"], 0.01)

    def test_installed_cache_reuses_exact_decision_without_generation(self):
        import p4_cost_control_run as run

        payload = {
            "rule_texts": {"style_and_persona": [], "scenario": []},
            "partner_block": [],
        }
        answer = json.dumps(
            {
                "assessed_style_rule_ids": [],
                "assessed_scenario_rule_ids": [],
                "style_departures": [],
                "scenario_violations": [],
            }
        )
        generator = Mock(return_value=SimpleNamespace(content=answer))
        c = SimpleNamespace(
            x=SimpleNamespace(
                p4=SimpleNamespace(
                    ROLE=contextvars.ContextVar("role", default="rule_labeler"),
                    audited_completion=Mock(),
                    llm_utils=SimpleNamespace(generate=generator),
                )
            ),
            annotate=Mock(),
            FULL_STYLE=False,
        )
        with patch.object(run, "NEW", Path(self.tmp.name)):
            run.install(c, self.store, "A0")
            kwargs = {
                "model": "sol",
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "rules"},
                    {"role": "user", "content": json.dumps({"input": payload})},
                ],
            }
            c.x.p4.llm_utils.generate(**kwargs)
            c.x.p4.llm_utils.generate(**kwargs)
            self.assertEqual(generator.call_count, 1)
            self.assertEqual(self.store.totals(), [])

    def test_program_request_still_checks_native_transfer_protocol(self):
        import p4_cost_control_run as run

        mechanical = Mock(return_value=["required_transfer_token_missing"])
        c = SimpleNamespace(
            x=SimpleNamespace(
                p4=SimpleNamespace(
                    ROLE=contextvars.ContextVar("role2", default="judge"),
                    audited_completion=Mock(),
                    llm_utils=SimpleNamespace(generate=Mock()),
                )
            ),
            annotate=Mock(),
            FULL_STYLE=False,
            mech=SimpleNamespace(replay=Mock()),
            mechanical_check=mechanical,
        )
        original_generate = c.x.p4.llm_utils.generate
        with patch.object(run, "NEW", Path(self.tmp.name)):
            run.install(c, self.store, "A0")
            result = c.annotate(
                SimpleNamespace(model_dump=lambda **kw: {}),
                [],
                [{"role": "user", "content": "Please run a speed test."}],
                0,
                "case",
            )
            self.assertFalse(result["valid"])
            mechanical.assert_called_once()
            original_generate.assert_not_called()

    def test_db_report_correct_and_contradictory_values(self):
        import p4_cost_control_run as run

        for truth in [True, False]:
            facts = {
                "claims": [{"db_matches": truth}],
                "unassessed_device_sentences": [],
            }
            generator = Mock()
            env = SimpleNamespace(environment=object())
            c = SimpleNamespace(
                x=SimpleNamespace(
                    p4=SimpleNamespace(
                        ROLE=contextvars.ContextVar("report_role", default="judge"),
                        audited_completion=Mock(),
                        llm_utils=SimpleNamespace(generate=generator),
                    )
                ),
                annotate=Mock(),
                FULL_STYLE=False,
                mech=SimpleNamespace(
                    replay=Mock(return_value=env), check_claims=Mock(return_value=facts)
                ),
                mechanical_check=Mock(return_value=[]),
                programmatic_scenario_violations=lambda f: [
                    v for v in f["claims"] if not v["db_matches"]
                ],
            )
            with patch.object(run, "NEW", Path(self.tmp.name)):
                run.install(c, self.store, "A0")
                result = c.annotate(
                    SimpleNamespace(model_dump=lambda **kw: {}),
                    [],
                    [{"role": "user", "content": "Mobile data is on."}],
                    0,
                    "report_case",
                )
                self.assertEqual(result["valid"], truth)
                self.assertFalse(result["model_judgment"])
                generator.assert_not_called()

    def test_partial_parser_does_not_bypass_judge(self):
        import p4_cost_control_run as run

        env = SimpleNamespace(environment=object())
        original = Mock(return_value="full_judge_required")
        c = SimpleNamespace(
            x=SimpleNamespace(
                p4=SimpleNamespace(
                    ROLE=contextvars.ContextVar("partial_role", default="judge"),
                    audited_completion=Mock(),
                    llm_utils=SimpleNamespace(generate=Mock()),
                )
            ),
            annotate=original,
            FULL_STYLE=False,
            mech=SimpleNamespace(
                replay=Mock(return_value=env),
                check_claims=Mock(
                    return_value={
                        "claims": [],
                        "unassessed_device_sentences": ["Mobile data is on."],
                    }
                ),
            ),
            mechanical_check=Mock(return_value=[]),
        )
        with patch.object(run, "NEW", Path(self.tmp.name)):
            run.install(c, self.store, "A0")
            result = c.annotate(
                SimpleNamespace(model_dump=lambda **kw: {}),
                [],
                [{"role": "user", "content": "Mobile data is on."}],
                0,
                "report_case",
            )
            self.assertEqual(result, "full_judge_required")
            original.assert_called_once()

    def test_openrouter_prefix_and_long_context_prices(self):
        cfg = {
            **self.config,
            "total_usd_cap": 10,
            "arm_usd_cap": 10,
            "sol_usd_cap": 10,
            "rates_per_million": {
                "openai/sol": {
                    "input": 2,
                    "output": 10,
                    "overrides": [
                        {
                            "min_prompt_tokens": 272000,
                            "prompt": 0.000004,
                            "completion": 0.000015,
                        }
                    ],
                }
            },
        }
        store = CostStore(Path(self.tmp.name) / "tiers.sqlite", cfg)
        ident = store.reserve("A0", "openrouter/openai/sol", "judge", 300000, 1000)
        self.assertAlmostEqual(store.totals()[0]["usd"], 1.215)
        store.settle(
            ident, {"prompt_tokens": 300000, "completion_tokens": 1000, "cost": 1.1}
        )
        self.assertAlmostEqual(store.totals()[0]["usd"], 1.1)


if __name__ == "__main__":
    unittest.main()
