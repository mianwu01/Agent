"""Aggregate frozen Tier A outputs, create figures and write the report."""

import collections
import hashlib
import json
import re
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
BASE = OUT.parent
ROOT = OUT.parents[3]
D = {i: BASE / f"v7_e{i}_20261004" for i in range(4)}
SRC = BASE / "v6_paired_20261004"
FOLLOW = BASE / "v6_followup_20261004"


def read(p):
    return json.loads(Path(p).read_text())


def save(p, o):
    Path(p).write_text(
        json.dumps(o, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def ratio(n, d):
    return {"numerator": int(n), "denominator": int(d), "share": n / d if d else None}


def table(head, rows):
    return "\n".join(
        ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * len(head)) + " |"]
        + ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    )


def fmt(v):
    if v is None:
        return "undefined"
    return f"{v:.4f}"


def ci(o):
    v = o.get("average_folds", o.get("mean"))
    band = o.get("bootstrap_95_CI")
    return fmt(v) + (f" [{fmt(band[0])}, {fmt(band[1])}]" if band else "")


def aggregate_e0():
    jobs = read(D[0] / "annotation_jobs.json")
    annotations = [
        read(D[0] / "annotations" / f"{j['kind']}:{j['id']}.json") for j in jobs
    ]
    context = read(OUT / "context.json")
    sids = [c["state_id"] for c in context["protocol"]["states"]]
    private = {}
    regression = {}
    for sid in sids:
        private[sid] = {}
        regression[sid] = {}
        for arm in ["q", "q_prime"]:
            a = next(
                a
                for a in annotations
                if a["kind"] == "private" and a["id"] == f"{sid}:{arm}"
            )
            private[sid][arm] = {
                k: ratio(sum(r[k] for r in a["judgment"]["blocks"]), 6)
                for k in [
                    "mentions_private_scenario",
                    "device_state_report",
                    "device_tool_action",
                    "unobserved_device_claim",
                ]
            }
            rel = [
                r
                for a in annotations
                if a["kind"] == "regression"
                and a["state_id"] == sid
                and a["family"] == arm
                for r in a["judgment"]["relations"]
            ]
            count = collections.Counter(r["relation"] for r in rel)
            regression[sid][arm] = {
                k: ratio(count[k], len(rel))
                for k in ["continues", "neutral", "contradicts_or_undoes"]
            }
            regression[sid][arm]["available"] = len(rel)
            regression[sid][arm]["no_next_partner_turn"] = 24 - len(rel)
    private_total = {}
    regression_total = {}
    for arm in ["q", "q_prime"]:
        private_total[arm] = {
            k: ratio(sum(private[sid][arm][k]["numerator"] for sid in sids), 240)
            for k in private[sids[0]][arm]
        }
        n = sum(regression[sid][arm]["available"] for sid in sids)
        regression_total[arm] = {
            k: ratio(sum(regression[sid][arm][k]["numerator"] for sid in sids), n)
            for k in ["continues", "neutral", "contradicts_or_undoes"]
        }
        regression_total[arm].update(
            available=n, no_next_partner_turn=960 - n, total_suffixes=960
        )
    save(
        D[0] / "private_context_frequencies.json",
        {"model_judgment": True, "per_state": private, "aggregate": private_total},
    )
    save(
        D[0] / "next_turn_regression.json",
        {
            "model_judgment": True,
            "per_state": regression,
            "aggregate": regression_total,
            "missing_are_censored_not_neutral": True,
            "limitation": "Single frozen judge, no agreement test. Some reasons attribute agent-side repairs to partner undoing; rates are provisional judgments rather than validated causal regression measurements.",
        },
    )
    accepted = [
        json.loads(s) for s in (D[1] / "behavior_labels.jsonl").read_text().splitlines()
    ]
    accepted = [
        r
        for r in accepted
        if r["labeler"] == "gpt-5.6-sol" and ":q_prime:" in r["unit"]
    ]
    rejected = [a for a in annotations if a["kind"] == "rejected"]
    reasons = read(D[0] / "rejected_records.json")
    categories = collections.Counter()
    rules = [
        ("protocol_transfer", r"transfer|terminal|###"),
        (
            "unrequested_tool",
            r"without.*request|not requested|unrequested|unsolicited|unnecessary|not necessary",
        ),
        (
            "unsupported_device_report",
            r"ground|invent|fabricat|tool result|unsupported|unverified",
        ),
        ("scenario_inconsistency", r"scenario|contradict|identity|location"),
        ("other", r".*"),
    ]
    reason_records = []
    for r in reasons:
        category = next(
            name for name, pattern in rules if re.search(pattern, r["reason"], re.I)
        )
        categories[category] += 1
        reason_records.append({**r, "mechanical_reason_category": category})

    def dist(rows):
        return {
            axis: {
                k: ratio(v, len(rows))
                for k, v in collections.Counter(r[axis] for r in rows).items()
            }
            for axis in ["action", "communication"]
        }

    def dev(rows):
        return ratio(
            sum(
                r["action"]
                in [
                    "partial",
                    "none_when_requested",
                    "different_action",
                    "extra_action",
                ]
                or r["communication"]
                in ["partial_or_ambiguous_report", "inaccurate_report"]
                for r in rows
            ),
            len(rows),
        )

    reject_rows = [a["judgment"] for a in rejected]
    save(
        D[0] / "rejection_analysis.json",
        {
            "accepted_q_prime": dist(accepted),
            "rejected": dist(reject_rows),
            "descriptive_behavior_deviation_union": {
                "accepted": dev(accepted),
                "rejected": dev(reject_rows),
            },
            "reason_categories": dict(categories),
            "reason_rules_ordered": rules,
            "records": reason_records,
            "limitation": "Selected executed rejects only, unequal state/retry composition; descriptive enrichment is not a causal effect of filtering. The deviation union is a disclosed reading aid, not a validated noncompliance detector.",
        },
    )
    batches = []
    for a in annotations:
        if a["kind"] != "batch":
            continue
        prop = read(SRC / "proposals" / f"{a['id']}.json")
        labels = a["judgment"]["labels"]
        pattern = [
            json.dumps(c.get("tool_calls") or [], sort_keys=True) for c in prop["batch"]
        ]
        names = [
            json.dumps([t.get("name") for t in c.get("tool_calls") or []])
            for c in prop["batch"]
        ]
        batches.append(
            {
                "id": a["id"],
                "state_id": a["state_id"],
                "candidate_count": len(labels),
                "distinct_intended_labels": len(
                    {(r["action"], r["communication"]) for r in labels}
                ),
                "distinct_proposed_tool_patterns_with_arguments": len(set(pattern)),
                "distinct_proposed_tool_name_patterns": len(set(names)),
                "selected_index": prop["selected_index"],
            }
        )
    executed = []
    for p in sorted((SRC / "replies").glob("*:q_prime:*.json")):
        r = read(p)
        executed.append(
            {
                "unit": r["unit"],
                "state_id": r["state_id"],
                "status": "accepted",
                "pattern": [
                    [c["name"], c["arguments"]]
                    for m in r["partner_block"]
                    for c in m.get("tool_calls") or []
                ],
            }
        )
    for r in reasons:
        executed.append(
            {
                "unit": r["id"],
                "state_id": r["state_id"],
                "status": "rejected",
                "pattern": [
                    [c["name"], c["arguments"]]
                    for m in r["block"]
                    for c in m.get("tool_calls") or []
                ],
            }
        )
    proposal_checks = []
    for p in sorted((SRC / "replies").glob("*:q_prime:*.json")):
        r = read(p)
        batch_id = f"{r['unit']}:attempt{r['attempt']}"
        proposal = read(SRC / "proposals" / f"{batch_id}.json")
        proposal_checks.append(
            {
                "unit": r["unit"],
                "batch_id": batch_id,
                "saved_selected_matches_executed_candidate": proposal["selected"]
                == r.get("candidate"),
                "actual_executed_pattern": [
                    [c["name"], c["arguments"]]
                    for m in r["partner_block"]
                    for c in m.get("tool_calls") or []
                ],
            }
        )
    save(
        D[0] / "proposal_execution_identity.json",
        {
            "accepted_blocks_checked": len(proposal_checks),
            "mismatches": sum(
                not r["saved_selected_matches_executed_candidate"]
                for r in proposal_checks
            ),
            "records": proposal_checks,
            "limitation": "Saved root batch can differ from historical selected execution; no unselected candidate is treated as executed.",
        },
    )
    save(
        D[0] / "batch_similarity.json",
        {
            "batches": batches,
            "mean_distinct_intended_labels": float(
                np.mean([r["distinct_intended_labels"] for r in batches])
            ),
            "mean_distinct_proposed_tool_patterns": float(
                np.mean(
                    [
                        r["distinct_proposed_tool_patterns_with_arguments"]
                        for r in batches
                    ]
                )
            ),
            "actually_executed_selected_blocks": executed,
            "limitation": "Only selected candidates were executed; five-way executed tool-pattern diversity is unavailable. Root proposal files represent the saved final proposal per attempt; historical transport variants can differ from execution records. Actual executed blocks are the authority.",
        },
    )
    save(
        D[0] / "annotation_summary.json",
        {
            "jobs": dict(collections.Counter(j["kind"] for j in jobs)),
            "completed": len(annotations),
            "model": "gpt-5.6-sol",
            "temperature": 0,
            "new_continuations": 0,
        },
    )
    return private_total, regression_total, batches


def figures():
    for name in ["S_hat_null_distribution", "behavior_distinct_counts"]:
        for ext in ["png", "pdf"]:
            shutil.copy2(FOLLOW / f"{name}.{ext}", D[1] / f"{name}.{ext}")
    curves = read(D[2] / "discovery_curves.json")
    for cohort, data in curves.items():
        fig, axes = plt.subplots(1, 5, figsize=(20, 4))
        for ax, (mode, sources) in zip(axes, data.items()):
            for source, r in sources.items():
                x = np.arange(1, r["n"] + 1)
                ax.plot(x, r["mean"], label=source)
                ax.fill_between(x, r["band_low"], r["band_high"], alpha=0.12)
            ax.set(title=mode, xlabel="Saved suffixes", ylabel="Distinct modes")
        axes[-1].legend(fontsize=8)
        fig.suptitle(f"{cohort}: 50 orders; bands are order variability")
        fig.tight_layout()
        for ext in ["png", "pdf"]:
            fig.savefig(D[2] / f"discovery_{cohort}.{ext}", dpi=160)
        plt.close(fig)
    signal = read(D[3] / "signal_comparison.json")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, target in zip(axes, ["own_past", "all_directions_past"]):
        for j, s in enumerate(["GT", "COUNT", "REWARD", "REWARD_VARIANCE"]):
            for i, mode in enumerate(["M2", "M3", "M4"]):
                r = signal[mode][target][s]["average_and_cluster_CI"]["lift"]
                if r["average_folds"] is not None:
                    x = i + (j - 1.5) * 0.15
                    ax.plot(x, r["average_folds"], "o", label=s if i == 1 else None)
                    if r["bootstrap_95_CI"]:
                        ax.vlines(x, *r["bootstrap_95_CI"], alpha=0.6, color=f"C{j}")
        ax.axhline(1, color="gray", linestyle="--")
        ax.set(
            xticks=[0, 1, 2],
            xticklabels=["M2", "M3", "M4"],
            ylabel="Top-quarter lift over random",
            title=target,
        )
        ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ["png", "pdf"]:
        fig.savefig(D[3] / f"top_quarter_lift.{ext}", dpi=160)
    plt.close(fig)


def audit():
    changed = []
    checked = {}
    for p in OUT.glob("input_manifest*.json"):
        for name, h in read(p).items():
            if name in checked:
                assert checked[name] == h
            checked[name] = h
    for name, h in checked.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != h:
            changed.append(name)
    assert not changed, changed
    usage = collections.defaultdict(lambda: collections.Counter())
    temperature = []
    roles = collections.Counter()
    for p in (OUT / "requests").glob("*.json"):
        r = read(p)
        roles[r["role"]] += 1
        assert r["unit"].startswith("v7_label:")
        assert r["request"].get("api_key", "").startswith("os.environ/P4_API_KEY_")
        temperature.append(r["request"].get("temperature"))
        u = r.get("usage") or {}
        kind = r["unit"].split(":")[1]
        usage[kind]["requests"] += 1
        usage[kind][r["status"]] += 1
        for k in ["prompt_tokens", "completion_tokens"]:
            usage[kind][k] += u.get(k, 0) or 0
    assert set(temperature) == {0}
    save(
        OUT / "labeler_usage.json",
        {
            "by_annotation_kind": {k: dict(v) for k, v in usage.items()},
            "total": dict(sum(usage.values(), collections.Counter())),
            "reused_E1_separate": read(D[1] / "labeler_usage.json"),
            "warning": "Failed/interrupted requests without returned usage may have unknown provider-side usage.",
        },
    )
    save(
        OUT / "audit.json",
        {
            "source_files_verified": len(checked),
            "changed_source_files": changed,
            "new_continuations": 0,
            "request_roles": dict(roles),
            "all_new_request_temperature_zero": True,
            "annotation_prompts_frozen": True,
            "case_files": len(list((D[1] / "cases").glob("*.md"))),
            "historical_request_ledgers_unchanged": True,
        },
    )


def report():
    private, regression, batches = aggregate_e0()
    figures()
    audit()
    bank = read(D[1] / "check1_permutation.json")["bank"]
    level = read(D[1] / "check2_level.json")["levels"]
    diversity = read(D[1] / "check3_diversity.json")
    stats = read(D[2] / "discovery_statistics.json")
    signals = read(D[3] / "signal_comparison.json")
    branch = read(D[0] / "branch_context_identity.json")["states"]
    reject = read(D[0] / "rejection_analysis.json")
    approx = read(D[2] / "agent_only_approximation.json")
    usage = read(OUT / "labeler_usage.json")["total"]
    proposal_identity = read(D[0] / "proposal_execution_identity.json")
    curves = read(D[2] / "discovery_curves.json")["matched_states"]
    common_n = min(r["n"] for r in curves["M3"].values())
    save(
        D[2] / "common_budget_comparison.json",
        {
            "cohort": "matched_states",
            "suffixes_per_source": common_n,
            "modes": {
                m: {
                    source: {
                        "mean": r["mean"][common_n - 1],
                        "order_band": [
                            r["band_low"][common_n - 1],
                            r["band_high"][common_n - 1],
                        ],
                    }
                    for source, r in sources.items()
                }
                for m, sources in curves.items()
            },
        },
    )
    lines = [
        "# P4 v7 — Tier A report",
        "",
        "Tier A completed on the existing 40 states / 20 tasks, 480 executed partner blocks and 1,920 paired suffixes. No new agent or partner continuations. E1 reuses the corrected frozen v6.1 follow-up (2,000 permutations, 1,000 task-cluster bootstraps, 480 blocks × Sol/Luna labels); E0 adds 855 frozen Sol temperature-0 annotation jobs. All judgments remain model labels, with no human ground truth or relabeling.",
        "",
        "Main reading: partner replies matter at some telecom states, but the candidate bank remains null-compatible. M3/M4 retain structural diversity, and GT predicts held-out new-mode counts better than random allocation in these saved data. Neither a confirmed harmful case nor a persistent-behavior effect has yet been demonstrated.",
        "",
        "Models in the source batch: Luna agent, Luna native/VS partner (temperature 1); each arm has 6 blocks × 4 suffixes per state. Frozen executed-block labelers are Sol and Luna temperature 0; all new E0 calls are Sol temperature 0.",
        "",
        "## E0 — implementation and mechanism checks",
        "",
        table(
            ["Check", "Run / result", "Reading"],
            [
                [
                    "a: private scenario",
                    "5 exact proposal request payloads archived; private task scenario in system; explicit runtime device snapshot absent",
                    "The strong omission hypothesis is unsupported. VS and native q can read device facts through tools.",
                ],
                [
                    "b: next turn",
                    f"q undo {regression['q']['contradicts_or_undoes']['numerator']}/{regression['q']['available']}; q′ undo {regression['q_prime']['contradicts_or_undoes']['numerator']}/{regression['q_prime']['available']}",
                    "Single-labeler provisional judgment; see censoring and judge limitation below.",
                ],
                [
                    "c: branch context",
                    f"{sum(r['original_vs_restored_equal'] for r in branch)}/10 reconstructed original inputs identical; {sum(x['expected_vs_captured_equal'] is True for r in branch for x in r['sampled_branch_captured_requests'].values())}/20 sampled inputs match captured requests",
                    "Original IID raw requests unavailable; reconstructed source-policy/message input is explicitly distinguished.",
                ],
                [
                    "d: rejected proposals",
                    f"61 rejects vs 240 accepted; descriptive deviation union {reject['descriptive_behavior_deviation_union']['rejected']['numerator']}/61 vs {reject['descriptive_behavior_deviation_union']['accepted']['numerator']}/240",
                    "Reject reasons are dominated by transfer protocol; overall deviation coding is not enriched among rejects. State/retry composition differs.",
                ],
                [
                    "e: five-way VS batches",
                    f"301 batches / 1,505 intended candidates; mean distinct intended labels {np.mean([r['distinct_intended_labels'] for r in batches]):.3f}; proposed tool patterns {np.mean([r['distinct_proposed_tool_patterns_with_arguments'] for r in batches]):.3f}",
                    "Unselected candidates were never executed; intended patterns cannot stand in for five-way execution.",
                ],
            ],
        ),
        "",
        table(
            ["Private-context judgment", "q (out of 240)", "q′ (out of 240)"],
            [
                [k, private["q"][k]["numerator"], private["q_prime"][k]["numerator"]]
                for k in private["q"]
            ],
        ),
        "",
        table(
            ["Next native partner relation", "q", "q′"],
            [
                [
                    k,
                    f"{regression['q'][k]['numerator']}/{regression['q'][k]['denominator']}",
                    f"{regression['q_prime'][k]['numerator']}/{regression['q_prime'][k]['denominator']}",
                ]
                for k in ["continues", "neutral", "contradicts_or_undoes"]
            ]
            + [
                [
                    "No next partner turn (censored)",
                    regression["q"]["no_next_partner_turn"],
                    regression["q_prime"]["no_next_partner_turn"],
                ]
            ],
        ),
        "",
        "The next-turn labeler sometimes explains an “undo” by the agent’s repair rather than the partner’s behavior. We preserve these frozen labels and do not turn the reported rate into a validated regression effect. Missing next turns are censored, not neutral. Private-state mention/action coding is also model judgment, not proof of what motivated the generator. Per-state numerators and denominators are saved in E0 JSON files.",
        "",
        "Rejection reasons are mechanically grouped by disclosed ordered regex rules: "
        + str(reject["reason_categories"])
        + ". The accepted/rejected distributions use the identical frozen E1 Sol core prompt. Selection and task composition prevent a causal conclusion that fidelity filtering caused the absent sensitivity contrast.",
        "",
        "Plain-language reading: neither missing private instructions nor a changed reconstructed branch prompt explains the batch by itself. The proposal/filter interface is narrower than unrestricted partner behavior, and downstream turns may repair branch behavior. The current annotation establishes where to inspect; E6/E7 are needed to test those mechanisms by execution.",
        "",
        f"Saved root proposal selections differ from accepted execution candidates in {proposal_identity['mismatches']}/{proposal_identity['accepted_blocks_checked']} checks. Exact root payloads and actual executed blocks are retained separately; root intended-batch statistics cannot be substituted for executed-batch diversity.",
        "",
        "## E1 — null, sensitivity level, behavior and tail",
        "",
        table(
            [
                "Bank",
                "Direction",
                "Observed",
                "Null mean",
                "Null 95th",
                "p",
                "Null / observed",
            ],
            [
                [
                    b,
                    a,
                    int(v["observed"]),
                    fmt(v["null_mean"]),
                    fmt(v["null_95th_percentile"]),
                    fmt(v["permutation_p_upper"]),
                    fmt(v["expected_null_count_over_observed"]),
                ]
                for b, x in bank.items()
                for a, v in x.items()
            ],
        ),
        "",
        table(
            [
                "Cohort",
                "Family",
                "Mean S_hat [task-cluster 95% CI]",
                "Null mean / 95th",
                "p",
                "Own-null exceedances",
            ],
            [
                [
                    co,
                    arm,
                    ci(v),
                    fmt(v["null_mean"]) + " / " + fmt(v["null_95th_percentile"]),
                    fmt(v["permutation_p_upper"]),
                    str(v["state_exceedance"]["count"]) + "/" + str(v["denominator"]),
                ]
                for co, x in level.items()
                for arm, v in x.items()
            ],
        ),
        "",
    ]
    for model, r in diversity["labelers"].items():
        a = r["aggregate"]["nontransfer_open_union"]
        lines += [
            model + "; open nontransfer states:",
            "",
            table(
                [
                    "q distinct",
                    "q′ distinct",
                    "Paired delta [CI]",
                    "New-label share [CI]",
                    "Label S contrast [CI]",
                    "Raw between-label share [CI]",
                ],
                [
                    [
                        ci(a["q_distinct"]),
                        ci(a["q_prime_distinct"]),
                        ci(a["paired_distinct_difference"]),
                        ci(a["novel_q_prime_share"]),
                        ci(a["S_label_contrast"]),
                        ci(a["between_label_variance_share"]),
                    ]
                ],
            ),
            "",
        ]
    lines += [
        "Kappa on all 480 blocks: action "
        + fmt(diversity["agreement"]["all480"]["action"]["kappa"])
        + "; report "
        + fmt(diversity["agreement"]["all480"]["communication"]["kappa"])
        + ". Five mandated-transfer states are excluded from primary diversity and retained separately in the full JSON. Individual assertion maxima are compared against maxima within synchronized-vector permutations: q 5/40, q′ 7/40 (open: 5/33 and 6/33). All negative estimates and binomial intervals remain in check2_level.json.",
        "",
        "![Per-state S_hat and null bands](../v7_e1_20261004/S_hat_null_distribution.png)",
        "",
        "![Distinct model labels](../v7_e1_20261004/behavior_distinct_counts.png)",
        "",
        "E1-d: 12 raw case files (top 8 / bottom 4 screening contrasts) are in ../v7_e1_20261004/cases/. They contain the request, all 12 blocks, both frozen labels, all four suffix outcomes and next turns. These are inspection material, not independently confirmed harmful or beneficial case studies.",
        "",
        "Plain-language reading: the native sensitivity level exceeds its permutation null, so “the partner does not matter” is unsupported. The mean broadening contrast remains +0.0115 [-0.0031, 0.0271]. The candidate bank is consistent with no-effect noise; null-count ratios 0.949/0.968 are aggregate noise diagnostics, not entry-specific FDR. Novel labels occur, but the distinct-label difference is uncertain and report-axis agreement modest. Do not force A/B/C; D still applies.",
        "",
        "## E2 — mode definitions and discovery curves",
        "",
        "Modes are mechanical: M1 reward; M2 reward + semantic assertion pattern; M3 M2 + task-touched device leaves + next agent action type; M4 M3 + ordered tool names (repetitions retained); M5 frozen Sol behavior × M2. Numeric device values are abstracted to negative/zero/positive, categorical values retained. Task-touched fields include deterministic replay changes at every executed mutating tool, including fields later reverted, and explicit initialization leaves. Instruction types use a fixed disclosed rule in tier_a.py. Modes are global semantic keys rather than unique state IDs.",
        "",
        table(
            [
                "Mode",
                "Source",
                "n",
                "Distinct",
                "f1 / n (GT)",
                "Chao1",
                "Source-exclusive / distinct",
            ],
            [
                [
                    m,
                    source,
                    r["n"],
                    r["observed_modes"],
                    f"{r['f1']}/{r['n']} = {r['GT_rate']:.4f}",
                    f"{r['Chao1']:.2f}",
                    f"{r['source_exclusive_modes']}/{r['observed_modes']}",
                ]
                for m, x in stats["all"].items()
                for source, r in x.items()
            ],
        ),
        "",
        "![All saved suffix discovery curves](../v7_e2_20261004/discovery_all.png)",
        "",
        "![Matched state discovery curves](../v7_e2_20261004/discovery_matched_states.png)",
        "",
        f"Agent-only approximation: {len(approx['matched_states'])} states / {approx['suffix_count']} suffixes, the largest repeated q block per state. It is a subset of q and was not the original reply held fixed in fresh continuations; zero exclusive modes is guaranteed by inclusion. Matched-state statistics accompany all-state statistics, with 50 random orders and order-variability bands. An equal-budget endpoint comparison at 200 suffixes per source is saved in common_budget_comparison.json. The approximation includes 120/200 suffixes from five mandated-transfer states, versus 120/312 in the matched q arm. Therefore an equal total budget still differs in state weights and cannot isolate partner variation. Unequal observation budgets and the narrow matched cohort prevent a causal diversity comparison.",
        "",
        "Plain-language reading: M1 saturates immediately; M2 is coarse. M3/M4 retain more structure without nearly one new mode per suffix. q′ reaches additional saved structural modes, but mode novelty alone is not a verified change in final success. M4 can split repetitions and recovery paths that are incidental; M3 is a plausible compact choice, subject to E3 and fresh validation. M5 depends on unstable model labels and is supplementary.",
        "",
        "## E3 — held-out discovery signal",
        "",
        "80 (state, family) directions. Replies 1–3 / 4–6 provide 12 past / 12 future suffixes, then swap and average. Signals: GT=f1/12, COUNT=1/14 (one known prefix visit, degenerate), reward mean, reward variance. Cluster bootstrap: 1,000 task resamples, keeping states/families/folds together. Target suffixes are novel against own past or all directions’ past. Global novelty is frozen against the original past, not recomputed inside cluster resampling. Boundary ties get fractional uniform selection; undefined correlation stays undefined.",
        "",
        table(
            [
                "Mode",
                "Target",
                "Signal",
                "Spearman [CI]",
                "Top-quarter precision [CI]",
                "Capture [CI]",
                "Lift [CI]",
            ],
            [
                [
                    m,
                    target,
                    s,
                    ci(r["average_and_cluster_CI"]["spearman"]),
                    ci(r["average_and_cluster_CI"]["precision"]),
                    ci(r["average_and_cluster_CI"]["capture"]),
                    ci(r["average_and_cluster_CI"]["lift"]),
                ]
                for m, x in signals.items()
                for target, y in x.items()
                for s, r in y.items()
            ],
        ),
        "",
        "![Signal lift and task-cluster intervals](../v7_e3_20261004/top_quarter_lift.png)",
        "",
        "Plain-language reading: GT has positive held-out predictive value for M3/M4. Against the global past, M3 Spearman is 0.432 [0.203, 0.609] and top-quarter lift 1.703 [1.139, 2.296]; M4 is 0.728 [0.554, 0.821] and lift 2.231 [1.638, 2.815]. Reward variance also predicts novelty; these results do not establish a significant GT advantage over reward variance, because no paired difference test was specified. COUNT has no ranking information here and yields random allocation exactly. This supports testing GT as an internal allocation signal, while distinguishing structural path discovery from independently verified outcome changes. The split is held-out reply draws, not an adaptive search trial. Full fold metrics, valid bootstrap counts and raw targets are retained.",
        "",
        "## Cross-experiment reading",
        "",
        table(
            ["Hypothesis", "Evidence / remaining uncertainty"],
            [
                [
                    "1. Wrong statistic / few pivots",
                    "E1 has state-tail raw files and nonzero native sensitivity, while bank screening is largely null-compatible. Independent E4 retests are still required; mean contrast cannot settle a tail hypothesis.",
                ],
                [
                    "2. Wrong unit / persistent behavior",
                    "E0-b identifies provisional next-turn reversals with a censored baseline; no persistent intervention was run. E7 remains the test.",
                ],
                [
                    "3. Wording vs behavior",
                    "E1-c new-label shares are substantial, distinct-count CIs cross zero, and Sol/Luna disagree especially on reports. E0-e exposes limited within-batch intended behavioral variety. Not established as wording-only.",
                ],
                [
                    "4. Implementation",
                    "Private task instructions present; explicit DB snapshot absent; 10 reconstructed branch inputs and sampled request checks audited. Filtering rejects some behavior deviations. E0 does not prove a context bug or quantify its causal effect.",
                ],
                [
                    "5. Unsuitable environment",
                    "Native S exceeds permutation null; telecom is not partner-irrelevant. A cross-model/environment comparison E5 has not been run.",
                ],
                [
                    "6. Premise wrong",
                    "Not established: insignificant mean broadening is not equivalence, bank is unverified, and tail/persistence remain untested.",
                ],
            ],
        ),
        "",
        "Q1: M3/M4 are usable candidates, with exact definitions and discovery curves archived. Q2: persistent behavior remains unresolved. Q3: GT predicts held-out structural novelty and merits a controlled loop comparison; no adaptive benefit is yet demonstrated. Q4: no environment-switch conclusion without E5. Tier B has not started; this report is the requested Tier A reading milestone.",
        "",
        "## Provenance, accounting and caveats",
        "",
        f"New annotation requests: {usage.get('requests', 0)} ledger records; returned prompt tokens {usage.get('prompt_tokens', 0):,}, completion tokens {usage.get('completion_tokens', 0):,}. Reused E1 calls/tokens are accounted separately in labeler_usage.json. Interrupted/failed requests without returned usage have unknown provider-side usage. New requests are redacted in v7_tier_a_20261004/requests/. Prompts were frozen before annotation; no tuning on the data. Source hashes verified in audit.json; no historical run changed.",
        "",
        "Validation: seven targeted tests pass (mode boundaries, replay-state agreement, curve endpoints, held-out split/global novelty, fractional ties and degenerate signals); Ruff check and format pass for the three new analysis files.",
        "",
        "q used temperature 1.0, whereas the τ² paper evaluates the user simulator at temperature 0. This comparison uses an already-diverse native partner, not standard benchmark practice. No new temperature-0 arm was added. Reused preregistration and arithmetic amendment are preserved; the binary estimator retains the integer-equivalent calculation and exact-tie tolerance. Exploratory E0/E2/E3 rules/seeds are in plan.json and tier_a.py; these are exploration results, not new preregistered confirmatory tests.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("REPORT COMPLETE", flush=True)


if __name__ == "__main__":
    report()
