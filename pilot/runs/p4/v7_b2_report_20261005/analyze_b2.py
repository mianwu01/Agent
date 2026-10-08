"""Frozen labels, score intervals and clustered descriptive round-2 statistics."""

import argparse
import collections
import json
from pathlib import Path

import b2 as x
import numpy as np

read, save = x.read, x.save


def rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines()]


def score(successes, n):
    return {
        "successes": successes,
        "n": n,
        "rate": successes / n,
        "score_95_CI": list(x.stats.wilson(successes, n)),
    }


def difference(a, b):
    return {
        "difference": a["rate"] - b["rate"],
        "score_95_CI": x.stats.difference_interval(
            a["successes"], a["n"], b["successes"], b["n"]
        ),
        "numerators": [a["successes"], b["successes"]],
        "denominators": [a["n"], b["n"]],
    }


def a_summary():
    p = read(x.OUT / "plan.json")
    results = []
    for c in p["cases"]:
        sid, cid = c["state_id"], c["candidate_id"]
        new = {
            arm: [
                read(f)
                for f in sorted(
                    (x.D["a"] / "continuations").glob(f"{sid}:{arm}*{cid}*.json")
                )
            ]
            for arm in ["sol_fixed", "sol_native"]
        }
        assert len(new["sol_fixed"]) == 16 and len(new["sol_native"]) == 16
        rates = {
            "Luna_fixed": score(c["fixed_successes"], 16),
            "Luna_native": score(c["native_reference_successes"], 16),
            "Sol_fixed": score(
                sum(int(r["reward"] == 1) for r in new["sol_fixed"]), 16
            ),
            "Sol_native": score(
                sum(int(r["reward"] == 1) for r in new["sol_native"]), 16
            ),
        }
        change = difference(rates["Sol_fixed"], rates["Luna_fixed"])
        fixed_gain = difference(rates["Sol_fixed"], rates["Sol_native"])
        if c["direction"] == "beneficial":
            cls = "beneficial_directness_check"
        elif change["score_95_CI"][0] > 0:
            cls = "interaction_failure"
        elif (
            rates["Sol_fixed"]["score_95_CI"][1] < 0.5
            and fixed_gain["score_95_CI"][1] < 0
        ):
            cls = "partner_sabotage_or_task_infeasible_probe"
        else:
            cls = "unclear"
        mechanical = read(x.D["a"] / "mechanical_cards" / f"{cid}.json")
        assertion_diagnostic = {}
        for label, records in {
            "Luna_fixed": [
                r for r in mechanical["suffixes"] if r["arm"] == "candidate"
            ],
            "Luna_native": [r for r in mechanical["suffixes"] if r["arm"] == "native"],
            "Sol_fixed": new["sol_fixed"],
            "Sol_native": new["sol_native"],
        }.items():
            sole_refuel = []
            for row in records:
                unmet = [
                    a["assertion"] for a in row["assertions_final"] if not a["met"]
                ]
                if (
                    len(unmet) == 1
                    and unmet[0]["func_name"] == "assert_data_refueling_amount"
                ):
                    sole_refuel.append(row["unit"])
            assertion_diagnostic[label] = {
                "n": len(records),
                "failures": sum(r["reward"] != 1 for r in records),
                "sole_unmet_exact_refueling_n": len(sole_refuel),
                "units": sole_refuel,
                "interpretation": "Other saved task assertions met; failure of exact refueling amount alone is not evidence of unsuccessful connectivity troubleshooting.",
            }
        result = {
            "candidate_id": cid,
            "state_id": sid,
            "task_id": c["task_id"],
            "direction": c["direction"],
            "random_control": c["random_control"],
            "rates": rates,
            "Sol_minus_Luna_fixed": change,
            "Sol_fixed_minus_native": fixed_gain,
            "operational_class": cls,
            "directly_satisfied_assertions": mechanical["fixed"][
                "directly_satisfied_assertions"
            ],
            "directly_broken_assertions": mechanical["fixed"][
                "directly_broken_assertions"
            ],
            "device_claim_check": mechanical["fixed"]["device_claim_check"],
            "assertion_diagnostic": assertion_diagnostic,
            "class_caveat": "Operational score-CI reading; Sol failure is not a proof of sabotage or infeasibility. Model summaries separately marked.",
        }
        save(x.D["a"] / "a2_cases" / f"{cid}.json", result)
        results.append(result)
    save(
        x.D["a"] / "a2_summary.json",
        {
            "cases": results,
            "class_counts": dict(
                collections.Counter(
                    r["operational_class"]
                    for r in results
                    if r["direction"] == "harmful"
                )
            ),
            "fixed_plan": p["A2"],
            "new_suffixes": 480,
        },
    )
    print(
        "A2 SUMMARY",
        [
            (
                r["candidate_id"],
                r["operational_class"],
                r["rates"]["Sol_fixed"]["successes"],
            )
            for r in results
        ],
        flush=True,
    )
    return results


def labels(workers):
    p = read(x.OUT / "plan.json")
    data = rows(x.D["b"] / "trajectories.jsonl")
    x.setup("b", workers)
    jobs = []
    for r in data:
        if r["termination"] != "user_stop_unmet_assertions":
            continue
        target = x.D["b"] / "stop_labels" / f"{r['unit']}.json"
        if target.exists():
            continue
        m = r["last_agent"]
        if (
            m is None
            or m.get("tool_calls")
            or (m.get("content") or "").strip() in {"###STOP###", "###TRANSFER###", ""}
        ):
            save(
                target,
                {
                    "unit": r["unit"],
                    "category": "other_or_unclear",
                    "source": "mechanical_tool_or_terminal_or_absent",
                    "reason": "No natural-language last-agent claim/request",
                },
            )
            continue

        def label(key, r=r, target=target):
            answer = x.p4.json_response(
                p["labelers"]["stop_prompt"],
                {
                    "last_agent": r["last_agent"],
                    "context": r["last_context"],
                    "assertions_final": r["assertions_final"],
                },
                "gpt-5.6-sol",
                r["unit"] + ":stop_label",
                key,
            )
            assert answer["category"] in {
                "claims_resolution",
                "still_troubleshooting",
                "asks_user_action",
                "other_or_unclear",
            }
            save(
                target,
                {
                    "unit": r["unit"],
                    **answer,
                    "source": "Sol_t0_model_judgment",
                    "frozen_prompt": "../v7_b2_report_20261005/plan.json",
                },
            )

        jobs.append(label)
    x.b.run_jobs("b", jobs, workers)


def ratio(data, numerator, denominator):
    """Pooled estimate with task-cluster ratio bootstrap, retaining zero denominators."""
    tids = sorted({r["task_id"] for r in data})
    groups = {t: [r for r in data if r["task_id"] == t] for t in tids}
    rng = np.random.default_rng(read(x.OUT / "plan.json")["seeds"]["bootstrap"])
    num, den = sum(numerator(r) for r in data), sum(denominator(r) for r in data)
    samples = []
    for _ in range(1000):
        selected = [
            r for t in rng.choice(tids, len(tids), replace=True) for r in groups[t]
        ]
        d = sum(denominator(r) for r in selected)
        if d:
            samples.append(sum(numerator(r) for r in selected) / d)
    return {
        "numerator": num,
        "denominator": den,
        "estimate": num / den if den else None,
        "task_cluster_95_CI": np.quantile(samples, [0.025, 0.975]).tolist()
        if samples
        else None,
        "valid_bootstrap_replicates": len(samples),
    }


def b_summary():
    data = rows(x.D["b"] / "trajectories.jsonl")
    later = rows(x.D["b"] / "later_partner_turns.jsonl")
    for r in data:
        if r["termination"] == "user_stop_unmet_assertions":
            label = read(x.D["b"] / "stop_labels" / f"{r['unit']}.json")
            assert label["unit"] == r["unit"]
            r["last_agent_category"] = label["category"]
            r["label_source"] = label["source"]
    results = {}
    for condition in ["native", "single", "persistent"]:
        selected = [r for r in data if r["condition"] == condition]
        results[condition] = {
            "n": len(selected),
            "successes": sum(r["reward"] for r in selected),
            "turns": ratio(selected, lambda r: r["turns"], lambda r: 1),
            "partner_turns": ratio(selected, lambda r: r["partner_turns"], lambda r: 1),
            "terminations": {
                cat: ratio(selected, lambda r: r["termination"] == cat, lambda r: 1)
                for cat in sorted({r["termination"] for r in data})
            },
            "unmet_stop_last_agent": {
                cat: ratio(
                    selected,
                    lambda r: r.get("last_agent_category") == cat,
                    lambda r: r["termination"] == "user_stop_unmet_assertions",
                )
                for cat in [
                    "claims_resolution",
                    "still_troubleshooting",
                    "asks_user_action",
                    "other_or_unclear",
                ]
            },
        }
        results[condition]["failure_by_termination"] = {
            cat: ratio(
                selected,
                lambda r: r["termination"] == cat and r["reward"] != 1,
                lambda r: 1,
            )
            for cat in results[condition]["terminations"]
        }
        results[condition]["transfer_assertions_unmet"] = ratio(
            selected,
            lambda r: r["termination"] == "transfer" and not r["all_assertions_met"],
            lambda r: 1,
        )
        results[condition]["transfer_assertions_all_met"] = ratio(
            selected,
            lambda r: r["termination"] == "transfer" and r["all_assertions_met"],
            lambda r: 1,
        )
    later_stats = {
        "tool_turn_rate": ratio(later, lambda r: r["has_user_tool_call"], lambda r: 1),
        "unobserved_claim_turn_rate": ratio(
            later, lambda r: r["claim_check"]["unobserved_claim_n"] > 0, lambda r: 1
        ),
        "incorrect_claim_turn_rate": ratio(
            later, lambda r: r["claim_check"]["incorrect_claim_n"] > 0, lambda r: 1
        ),
        "recognized_claim_rate": ratio(
            later, lambda r: r["claim_check"]["recognized_claim_n"] > 0, lambda r: 1
        ),
        "unassessed_sentence_turn_rate": ratio(
            later,
            lambda r: bool(r["claim_check"]["unassessed_device_sentences"]),
            lambda r: 1,
        ),
        "unobserved_per_claim": ratio(
            later,
            lambda r: r["claim_check"]["unobserved_claim_n"],
            lambda r: r["claim_check"]["recognized_claim_n"],
        ),
        "transfer_compliance": ratio(
            later,
            lambda r: r["mandated_transfer"] and r["transfer_compliant"],
            lambda r: r["mandated_transfer"],
        ),
    }
    states = read(x.D["b"] / "states.json")
    for state in states:
        rs = [r for r in data if r["state_id"] == state["state_id"]]
        ls = [r for r in later if r["state_id"] == state["state_id"]]
        state["later_turns"] = {
            "n": len(ls),
            "tool_n": sum(r["has_user_tool_call"] for r in ls),
            "unobserved_claim_turn_n": sum(
                r["claim_check"]["unobserved_claim_n"] > 0 for r in ls
            ),
            "incorrect_claim_turn_n": sum(
                r["claim_check"]["incorrect_claim_n"] > 0 for r in ls
            ),
            "mandated_transfer_n": sum(r["mandated_transfer"] for r in ls),
            "compliant_transfer_n": sum(
                r["mandated_transfer"] and r["transfer_compliant"] for r in ls
            ),
        }
        state["last_agent_categories"] = {
            c: dict(
                collections.Counter(
                    r.get("last_agent_category")
                    for r in rs
                    if r["condition"] == c
                    and r["termination"] == "user_stop_unmet_assertions"
                )
            )
            for c in results
        }
        state["failure_by_termination"] = {
            c: dict(
                collections.Counter(
                    r["termination"]
                    for r in rs
                    if r["condition"] == c and r["reward"] != 1
                )
            )
            for c in results
        }
        state["failure_type_difference_persistent_minus_single"] = {
            cat: (
                state["failure_by_termination"]["persistent"].get(cat, 0)
                - state["failure_by_termination"]["single"].get(cat, 0)
            )
            / 24
            for cat in results["persistent"]["terminations"]
        }
        assert (
            abs(
                sum(state["failure_type_difference_persistent_minus_single"].values())
                + state["persistent_minus_single"]
            )
            < 1e-10
        )
    accounting = {
        cat: x.stats.cluster_mean(
            [
                {
                    **s,
                    "value": s["failure_type_difference_persistent_minus_single"][cat],
                }
                for s in states
            ],
            "value",
            read(x.OUT / "plan.json")["seeds"]["bootstrap"],
        )
        for cat in results["persistent"]["terminations"]
    }
    save(
        x.D["b"] / "b1_summary.json",
        {
            "conditions": results,
            "states": states,
            "later_partner": later_stats,
            "model_label_count": sum(
                r.get("label_source") == "Sol_t0_model_judgment" for r in data
            ),
            "mechanical_label_count": sum(
                r.get("label_source", "").startswith("mechanical") for r in data
            ),
            "failure_difference_accounting": accounting,
            "accounting_caveat": "Exact signed decomposition of observed failure-rate difference, not causal mediation. Transfer category separates mandated user tokens following agent handoff requests from ordinary user stops.",
            "claim_parser_amendment": "../v7_b2_report_20261005/plan_amendment_claim_observation.json",
        },
    )
    print("B1 SUMMARY COMPLETE", flush=True)


def cards(workers):
    import mechanical

    summaries = read(x.D["a"] / "a2_summary.json")["cases"]
    x.setup("a", workers)
    jobs = []
    for summary in summaries:
        target = x.D["a"] / "case_cards" / f"{summary['candidate_id']}.json"
        if target.exists():
            continue
        c = read(x.D["a"] / "mechanical_cards" / f"{summary['candidate_id']}.json")
        fixed = {
            k: v for k, v in c["fixed"].items() if k not in {"db_before", "db_after"}
        }
        native = [
            {
                k: v
                for k, v in r.items()
                if k not in {"db_before", "db_after", "prefix_before"}
            }
            for r in c["native_blocks"]
        ]
        examples = []
        for arm in ["candidate", "native"]:
            for reward in [0, 1]:
                candidates = [
                    r
                    for r in c["suffixes"]
                    if r["arm"] == arm and r["reward"] == reward
                ]
                if candidates:
                    examples.append(sorted(candidates, key=lambda r: r["unit"])[0])
        payload = {
            "rates_and_class": summary,
            "source_private_task_scenario": c.get("private_task_scenario"),
            "fixed_branch": fixed,
            "all_native_blocks": native,
            "Luna_representative_paths": examples,
            "paired_first_divergences": c["paired_path_divergences"],
            "selection": "Representative paths are lowest unit id at each observed outcome, not researcher chosen. All suffixes saved in mechanical card. No path proves causality.",
        }
        sol_examples = []
        sid, cid = summary["state_id"], summary["candidate_id"]
        for arm in ["sol_fixed", "sol_native"]:
            raw = [
                read(f)
                for f in sorted(
                    (x.D["a"] / "continuations").glob(f"{sid}:{arm}*{cid}*.json")
                )
            ]
            for reward in [0, 1]:
                candidates = [r for r in raw if r["reward"] == reward]
                if not candidates:
                    continue
                row = candidates[0]
                sim = read(x.D["a"] / "trajectories" / f"{row['unit']}.json")
                reply = read(
                    x.D["a"] / "replies" / f"{row['unit'].rsplit(':r', 1)[0]}.json"
                )
                sol_examples.append(
                    {
                        "unit": row["unit"],
                        "reward": row["reward"],
                        "assertions_final": row["assertions_final"],
                        "agent_path": mechanical.agent_path(
                            sim["messages"], len(reply["prefix"])
                        ),
                    }
                )
        payload["Sol_representative_paths"] = sol_examples
        payload["first_tool_divergences"] = [
            {
                "rep": pair["rep"],
                "first_tool_divergence": mechanical.first_divergence(
                    [
                        r
                        for r in next(
                            s
                            for s in c["suffixes"]
                            if s["arm"] == "candidate" and s["rep"] == pair["rep"]
                        )["agent_path"]
                        if r["type"] == "tool_call"
                    ],
                    [
                        r
                        for r in next(
                            s
                            for s in c["suffixes"]
                            if s["arm"] == "native" and s["rep"] == pair["rep"]
                        )["agent_path"]
                        if r["type"] == "tool_call"
                    ],
                ),
            }
            for pair in c["paired_path_divergences"]
        ]
        save(
            x.D["a"] / "tool_divergences" / f"{cid}.json",
            payload["first_tool_divergences"],
        )

        def label(key, payload=payload, target=target, summary=summary):
            answer = x.p4.json_response(
                read(x.OUT / "plan.json")["labelers"]["card_prompt"],
                payload,
                "gpt-5.6-sol",
                summary["candidate_id"] + ":case_card",
                key,
            )
            assert 5 <= len(answer["lines"]) <= 8
            save(
                target,
                {
                    "candidate_id": summary["candidate_id"],
                    "state_id": summary["state_id"],
                    "source": "Sol_t0_model_summary_not_human_label",
                    **answer,
                },
            )

        jobs.append(label)
    x.b.run_jobs("a", jobs, workers)


def b2_summary():
    p = read(x.OUT / "plan.json")
    selection = read(x.D["b2"] / "b2_selection.json")
    data = [read(f) for f in (x.D["b2"] / "continuations").glob("*.json")]
    assert len(data) == 312
    assert all(
        r["initial_validation_version"] == "native_inclusive_or_v2"
        and set(r["future_proposal_validation_versions"]) <= {"native_inclusive_or_v2"}
        for r in data
    )
    termination_decomposition = {}
    for cohort in ["all", "large_drop", "little_drop"]:
        cohort_states = (
            selection["large_drop"] + selection["little_drop"]
            if cohort == "all"
            else selection[cohort]
        )
        termination_decomposition[cohort] = {}
        for arm in ["persistent_luna", "persistent_sol"]:
            selected = [
                r for r in data if r["state_id"] in cohort_states and arm in r["unit"]
            ]
            counts = collections.Counter()
            failures = collections.Counter()
            for row in selected:
                sim = read(x.D["b2"] / "trajectories" / f"{row['unit']}.json")
                transfer = any(
                    m["role"] == "user" and "###TRANSFER###" in (m.get("content") or "")
                    for m in sim["messages"]
                )
                category = (
                    "transfer"
                    if transfer
                    else "max_steps"
                    if row["termination_reason"] == "max_steps"
                    else "user_stop_all_assertions"
                    if row["termination_reason"] == "user_stop"
                    and all(a["met"] for a in row["assertions_final"])
                    else "user_stop_unmet_assertions"
                    if row["termination_reason"] == "user_stop"
                    else row["termination_reason"]
                )
                counts[category] += 1
                if row["reward"] != 1:
                    failures[category] += 1
            termination_decomposition[cohort][arm] = {
                "n": len(selected),
                "counts": dict(counts),
                "failure_counts": dict(failures),
            }
    old = read(x.D["b"] / "states.json")
    states = []
    for sid in selection["large_drop"] + selection["little_drop"]:
        raw = {
            arm: [r for r in data if r["state_id"] == sid and arm in r["unit"]]
            for arm in ["persistent_luna", "persistent_sol"]
        }
        assert len(raw["persistent_luna"]) == 24
        if sid in selection["large_drop"]:
            assert len(raw["persistent_sol"]) == 12
        o = next(r for r in old if r["state_id"] == sid)
        rates = {
            "Luna_v2": score(sum(r["reward"] == 1 for r in raw["persistent_luna"]), 24),
            "Luna_B1_persistent": score(o["conditions"]["persistent"]["successes"], 24),
            "Luna_B1_single": score(o["conditions"]["single"]["successes"], 24),
        }
        if raw["persistent_sol"]:
            rates["Sol_v2"] = score(
                sum(r["reward"] == 1 for r in raw["persistent_sol"]), 12
            )
        comparisons = {
            "v2_minus_B1_persistent": difference(
                rates["Luna_v2"], rates["Luna_B1_persistent"]
            ),
            "v2_minus_B1_single": difference(rates["Luna_v2"], rates["Luna_B1_single"]),
        }
        if "Sol_v2" in rates:
            comparisons["Sol_minus_Luna_v2"] = difference(
                rates["Sol_v2"], rates["Luna_v2"]
            )
        states.append(
            {
                "state_id": sid,
                "task_id": o["task_id"],
                "cohort": "large_drop"
                if sid in selection["large_drop"]
                else "little_drop",
                "rates": rates,
                "comparisons": comparisons,
                "terminations": {
                    a: dict(collections.Counter(r["termination_reason"] for r in rs))
                    for a, rs in raw.items()
                },
            }
        )
    aggregate = {}
    for cohort in ["all", "large_drop", "little_drop"]:
        selected = [r for r in states if cohort == "all" or r["cohort"] == cohort]
        aggregate[cohort] = {
            key: x.stats.cluster_mean(
                [{**r, "value": r["comparisons"][key]["difference"]} for r in selected],
                "value",
                p["seeds"]["bootstrap"],
            )
            for key in selected[0]["comparisons"]
            if all(key in r["comparisons"] for r in selected)
        }
        aggregate[cohort]["raw_rates"] = {
            key: score(
                sum(r["rates"][key]["successes"] for r in selected),
                sum(r["rates"][key]["n"] for r in selected),
            )
            for key in selected[0]["rates"]
            if all(key in r["rates"] for r in selected)
        }
    save(
        x.D["b2"] / "comparison.json",
        {
            "states": states,
            "aggregate": aggregate,
            "new_suffixes": 312,
            "uniform_v2_verified": True,
            "termination_decomposition": termination_decomposition,
            "caveats": "Historical B1 contrasts are selection-dependent descriptive remeasurements. Sol and Luna share 6 branch blocks but differ in suffix count and later stochastic proposals; score CIs are per-state independent-binomial approximations, aggregate CIs task-clustered.",
        },
    )
    print("B2 COMPARISON COMPLETE", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=["a_summary", "labels", "b_summary", "cards", "b2_summary"]
    )
    parser.add_argument("--workers", type=int, default=48)
    a = parser.parse_args()
    globals()[a.phase](a.workers) if a.phase in {"labels", "cards"} else globals()[
        a.phase
    ]()


if __name__ == "__main__":
    main()
