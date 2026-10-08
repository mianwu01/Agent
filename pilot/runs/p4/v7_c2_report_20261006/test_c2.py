"""Offline invariants for frozen rule extraction, style retention and audit cost."""

import hashlib
import json
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
D1 = BASE / "v7_c2_step1_20261006"
D2 = BASE / "v7_c2_step2_20261006"


def read(p):
    return json.loads(p.read_text())


class C2Tests(unittest.TestCase):
    def test_every_verbatim_rule_span_matches_native_prompt(self):
        rules = read(D1 / "rules_v2.json")
        for rule in rules["rules"]:
            for occurrence in rule["instances"]:
                start, end = occurrence["span"]
                self.assertEqual(
                    rules["native_system_prompts"][occurrence["task_id"]][start:end],
                    rule["verbatim"],
                )

    def test_one_action_cooperation_and_persona_are_style(self):
        rules = read(D1 / "rules_v2.json")["rules"]
        item = next(
            r
            for r in rules
            if r.get("verbatim", "")
            and "If the agent asks multiple actions" in r["verbatim"]
        )
        self.assertEqual(item["category"], "style")
        item = next(
            r
            for r in rules
            if r.get("verbatim", "") and "Only call a tool if" in r["verbatim"]
        )
        self.assertEqual(item["category"], "style")

    def test_out_of_rule_turns_are_not_rejected_for_style(self):
        rows = [read(p) for p in (D1 / "replies").glob("*.json")]
        self.assertGreater(sum(r["label"]["style"] == "out_of_rule" for r in rows), 0)
        self.assertTrue(all(r["label"]["valid"] for r in rows))
        self.assertTrue(
            all(
                not r["label"]["mechanical_violations"]
                and not r["label"]["scenario_violations"]
                for r in rows
            )
        )

    def test_native_prompt_is_byte_identical_in_recorded_proposals(self):
        rules = read(D1 / "rules_v2.json")
        plan = read(D1 / "plan.json")
        tasks = {s["state_id"]: s["task_id"] for s in plan["sanity_states"]}
        for f in (D1 / "proposals").glob("*.json"):
            row = read(f)
            state = f.stem.split(":")[0]
            expected = hashlib.sha256(
                rules["native_system_prompts"][tasks[state]].encode()
            ).hexdigest()
            self.assertEqual(row["native_system_prompt_sha256"], expected)
            self.assertTrue(row["native_prompt_verbatim"])
            self.assertIn("candidate", row["only_added_instruction"])

    def test_case_style_labels_have_complete_frozen_rule_coverage(self):
        rules = read(D1 / "rules_v2.json")
        manifest = read(D2 / "manifest.json")
        categories = {r["rule_id"]: r["category"] for r in rules["rules"]}
        for case in manifest["cases"]:
            path = D2 / "mapped_labels" / f"{case['label_digest']}.json"
            if not path.exists():
                continue
            label = read(path)
            expected = {
                r
                for r in rules["per_task_rule_ids"][case["task_id"]]
                if categories[r] == "style"
            }
            self.assertEqual(
                {r["rule_id"] for r in label["all_style_rule_labels"]}, expected
            )
            self.assertTrue(label["model_judgment"])

    def test_token_projection_counts_aliases_once_and_all_arms(self):
        p = read(BASE / "v7_c2_step3_20261006/cost_projection.json")
        self.assertEqual(
            sum(p["projected_tokens_per_arm"].values()), p["projected_all_arms_tokens"]
        )
        self.assertFalse(p["exceeds_3x_B1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
