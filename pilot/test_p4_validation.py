"""Guard scientific counting against missing controls and duplicate runs."""

import unittest

import p4_validation as v


def supported():
    """Synthetic complete evidence fixture, never a research result."""
    result = {
        n: {
            "status": "supported" if n in v.OBLIGATIONS[:6] else "excluded",
            "artifact": "fixture",
            "rationale": "test",
        }
        for n in v.OBLIGATIONS
    }
    result["independent_human_adjudication"].update(
        reviewer_type="human", reviewer_id="fixture"
    )
    return result


class ValidationTests(unittest.TestCase):
    def test_global_reminder_success_does_not_satisfy_local_control(self):
        evidence = supported()
        evidence["information_matched_local_control"]["status"] = "diagnostic_only"
        self.assertFalse(v.eligibility(evidence)["countable_validated_instance"])

    def test_model_review_cannot_impersonate_human_adjudication(self):
        evidence = supported()
        evidence["independent_human_adjudication"]["reviewer_type"] = "model"
        self.assertIn(
            "independent_human_adjudication",
            v.eligibility(evidence)["unmet_obligations"],
        )

    def test_excluded_candidate_is_not_a_supported_failure(self):
        evidence = supported()
        evidence["candidate_semantics"]["status"] = "excluded"
        self.assertFalse(v.eligibility(evidence)["countable_validated_instance"])

    def test_absent_evidence_and_unsupported_not_applicable_fail_closed(self):
        self.assertEqual(
            len(v.eligibility({})["unmet_obligations"]), len(v.OBLIGATIONS)
        )
        evidence = supported()
        evidence["native_failed_outcome"]["status"] = "not_applicable"
        self.assertFalse(v.eligibility(evidence)["countable_validated_instance"])

    def test_cloned_messages_collapse_across_uuid_seed_and_timestamp(self):
        a = [
            {
                "role": "assistant",
                "content": "Please check.",
                "id": "a",
                "timestamp": "old",
            }
        ]
        b = [
            {
                "role": "assistant",
                "content": "Please check.",
                "id": "b",
                "timestamp": "new",
                "usage": {"seed": 99},
            }
        ]
        self.assertEqual(v.instance_key(a, 0, "C"), v.instance_key(b, 0, "C"))

    def test_only_verified_instances_and_known_triggers_are_counted(self):
        evidence = supported()
        result = v.count_verified(
            [
                {"evidence": evidence, "instance_key": "same", "trigger_key": "t"},
                {"evidence": evidence, "instance_key": "same", "trigger_key": "t"},
                {
                    "evidence": evidence,
                    "instance_key": "different",
                    "trigger_key": None,
                },
                {"evidence": {}, "instance_key": "unverified", "trigger_key": "new"},
            ]
        )
        self.assertEqual(result["validated_instances"], 2)
        self.assertEqual(result["distinct_triggers"], 1)

    def test_missing_state_does_not_become_a_new_trigger(self):
        with self.assertRaises(KeyError):
            v.trigger_key(
                "C", "mms_issue", ["assert_can_send_mms"], {}, "reported_unresolved"
            )
        with self.assertRaises(ValueError):
            v.trigger_key("C", "mms_issue", ["assert_can_send_mms"], {}, "unknown")


if __name__ == "__main__":
    unittest.main()
