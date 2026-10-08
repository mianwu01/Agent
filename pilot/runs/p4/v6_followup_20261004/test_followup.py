"""Synthetic checks of pooling and variance identities, independent of pilot outcomes."""

import unittest

import followup as f
import numpy as np


class FollowupTests(unittest.TestCase):
    def test_permutation_p_reunites_exact_float_ties(self):
        result = f.null_stat(0.01, np.array([np.nextafter(0.01, -np.inf), 0.01, 0.02]))
        self.assertEqual(result["permutation_p_upper"], 1.0)
        self.assertEqual(result["permutation_numerator"], 4)

    def test_integer_estimator_matches_original_formula(self):
        x = np.random.default_rng(3).integers(2, size=(100, 6, 4, 5))
        p = x.mean(axis=-2)
        original = p.var(axis=-2, ddof=1) - (p * (1 - p) / 3).mean(axis=-2)
        np.testing.assert_allclose(f.sensitivity(x), original, atol=1e-15)

    def test_bootstrap_variance_ratio_keeps_zero_denominators(self):
        states = [{"task_id": "a"}, {"task_id": "b"}]
        result = f.ratio_bootstrap(
            states, np.array([1.0, 2.0]), np.array([4.0, 8.0]), 4
        )
        self.assertEqual(result["bootstrap_95_CI"], [0.25, 0.25])
        self.assertEqual(result["valid_replicates"], 1000)
        result = f.ratio_bootstrap(states, np.zeros(2), np.zeros(2), 4)
        self.assertIsNone(result["ratio"])
        self.assertIsNone(result["bootstrap_95_CI"])
        self.assertEqual(result["valid_replicates"], 0)

    def test_noise_correction_preserves_negative_estimates(self):
        x = np.array([[[1], [1], [0], [0]]] * 6, float)
        self.assertAlmostEqual(float(f.sensitivity(x)[0]), -1 / 12)
        x = np.array([[[j % 2]] * 4 for j in range(6)], float)
        self.assertAlmostEqual(float(f.sensitivity(x)[0]), 0.3)

    def test_signature_pooling_across_families_changes_selection(self):
        replies = [
            [
                {"partner_signature": f"{a}_{j}", "fidelity": {"faithful": True}}
                for j in range(6)
            ]
            for a in range(2)
        ]
        replies[0][0]["partner_signature"] = replies[1][0]["partner_signature"] = (
            "shared"
        )
        successes = np.array([[4, 2, 2, 2, 2, 2, 0, 2, 2, 2, 2, 2]])
        self.assertEqual(
            f.bank_counts(replies, successes, 0.5, [0])[0].tolist(), [0, 1, 0]
        )
        self.assertEqual(
            f.bank_counts(replies, successes, 0.5, [1])[0].tolist(), [1, 0, 0]
        )
        self.assertEqual(
            f.bank_counts(replies, successes, 0.5, [0, 1])[0].tolist(), [0, 0, 0]
        )

    def test_last_representative_fidelity_matches_original_bank(self):
        replies = [
            [
                {"partner_signature": "same", "fidelity": {"faithful": a == 0}}
                for j in range(6)
            ]
            for a in range(2)
        ]
        successes = np.full((1, 12), 4)
        self.assertEqual(
            f.bank_counts(replies, successes, 0, [0, 1])[0].tolist(), [0, 0, 1]
        )

    def test_anova_decomposition_matches_population_variance(self):
        groups = {("a", "x"): [1, 1, 1, 1], ("b", "y"): [0, 0, 0, 0, 1, 0, 1, 0]}
        result = f.label_variance(groups)
        population = np.array([y for ys in groups.values() for y in ys])
        self.assertAlmostEqual(
            result["between_variance"] + result["within_variance"],
            float(population.var()),
        )
        self.assertEqual(result["denominator"], 12)


if __name__ == "__main__":
    unittest.main()
