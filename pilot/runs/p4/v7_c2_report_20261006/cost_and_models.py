"""Audited model-catalog discovery and pre-search cost projection."""

import os
import time

import c2 as c
import requests


def main():
    c.setup("step3", 8)
    begin = time.time()
    catalog = []
    error = None
    try:
        response = requests.get(
            c.x.p4.BASE + "/models",
            headers={"Authorization": "Bearer " + os.environ["P4_API_KEY_1"]},
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()
        catalog = [
            r["id"] for r in raw.get("data", []) if isinstance(r, dict) and "id" in r
        ]
    except requests.RequestException as exc:
        error = type(exc).__name__
    c.save(
        c.D["step3"] / "model_catalog.json",
        {
            "started_at": begin,
            "seconds": time.time() - begin,
            "catalog_endpoint": c.x.p4.BASE + "/models",
            "model_ids": catalog,
            "error_type": error,
            "tokens": 0,
            "authorization": "existing approved route1; credential never recorded",
        },
    )
    other = [
        m
        for m in catalog
        if any(k in m.lower() for k in ["claude", "gemini", "qwen", "deepseek"])
    ]
    b1 = c.read(c.BASE / "v7_b1_report_20261004/token_accounting.json")
    total = sum(
        s["usage"]["prompt_tokens"] + s["usage"]["completion_tokens"]
        for s in b1["steps"].values()
    )
    ref = b1["steps"]["step2"]
    suffixeq = (
        ref["usage"]["prompt_tokens"] + ref["usage"]["completion_tokens"]
    ) / ref["suffixes_saved"]
    obj = {
        "created_before_search_calls": True,
        "B1_total_returned_tokens": total,
        "three_times_B1_tokens": 3 * total,
        "suffix_equivalent_definition": "All returned agent/partner/proposal/judge tokens charged to the arm, divided by B1 step2 total returned tokens per saved suffix. Failed/interrupted unknown usage separately recorded, not imputed into returned totals. Same token unit across models; dollars unavailable, not assumed equal.",
        "tokens_per_suffix_equivalent": suffixeq,
        "target_suffix_equivalents_per_arm": 1000,
        "projected_tokens_per_arm": {
            arm: 1000 * suffixeq for arm in ["A0", "A1", "A2", "A3", "A4"]
        },
        "projected_all_arms_tokens": 5000 * suffixeq,
        "exceeds_3x_B1": 5000 * suffixeq > 3 * total,
        "other_family_catalog_candidates": other,
        "budget_splits": {
            "fresh_seed_episodes": 0.10,
            "screening_expansions": 0.40,
            "independent_retest": 0.30,
            "Sol_check": 0.20,
        },
        "notes": "Step1 sanity and Step2 historical labels separately accounted, not hidden inside arm budgets. Input/output aliases not added twice. Catalog availability alone does not prove callable tool-capable model; run a recorded interface probe only after freezing selection. Target arm budgets are token caps with exact completed costs and unused remainder reported.",
    }
    c.save(c.D["step3"] / "cost_projection.json", obj)
    print(
        "PROJECTED PER ARM",
        round(suffixeq * 1000),
        "TOTAL",
        round(suffixeq * 5000),
        "LIMIT",
        3 * total,
        "other-family catalog candidates",
        other[:20],
        flush=True,
    )


if __name__ == "__main__":
    main()
