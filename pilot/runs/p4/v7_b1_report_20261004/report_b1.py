"""Write round-1 report with raw sizes, uncertainty and transport accounting."""

import collections
import hashlib
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor

import b1 as b

OUT = b.OUT
D = b.D
read = b.read
save = b.save


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        + ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
    )


def f(v):
    return "undefined" if v is None else f"{v:.4f}"


def ci(r):
    band = r.get("bootstrap_95_CI")
    return f(r["mean"]) + (f" [{f(band[0])}, {f(band[1])}]" if band else "")


def interval_reading(stat):
    """Describe exploratory direction without discarding the interval."""
    lo, hi = stat["bootstrap_95_CI"]
    if lo > 0:
        return "the exploratory interval lies above zero"
    if hi < 0:
        return "the exploratory interval lies below zero"
    return "the interval includes zero, so the direction remains uncertain"


def accounting():
    manifests = {}
    for p in b.A.glob("input_manifest*.json"):
        manifests.update(read(p))

    def verify(pair):
        path, digest = pair
        return (
            path
            if hashlib.sha256((b.ROOT / path).read_bytes()).hexdigest() != digest
            else None
        )

    with ThreadPoolExecutor(max_workers=24) as pool:
        changed = [x for x in pool.map(verify, manifests.items()) if x]
    assert not changed, changed
    totals = {}
    unreturned = []
    models = collections.Counter()
    for step, directory in D.items():
        usage = collections.Counter()
        roles = collections.Counter()
        temperatures = collections.Counter()
        failures = collections.Counter()
        credential_counts = collections.Counter()
        route_models = collections.defaultdict(collections.Counter)
        paths = list((directory / "requests").glob("*.json"))

        def ledger(path):
            row = read(path)
            assert row["request"]["api_key"].startswith("os.environ/P4_API_KEY_")
            assert row["request"].get("temperature") in [0, 1]
            return row

        with ThreadPoolExecutor(max_workers=24) as pool:
            for row in pool.map(ledger, paths):
                roles[row["role"]] += 1
                condition = next(
                    (
                        c
                        for c in ["single", "persistent", "original"]
                        if f":{c}:" in row["unit"]
                    ),
                    "other",
                )
                route = f"{condition}:credential{row['key_index']}:{row['role']}"
                credential_counts[route] += 1
                if row["status"] == "response":
                    route_models[route][str(row.get("returned_model"))] += 1
                usage["requests"] += 1
                usage[row["status"]] += 1
                temperatures[str(row["request"].get("temperature"))] += 1
                models[row.get("returned_model", "no_returned_model")] += 1
                for k in ["prompt_tokens", "completion_tokens"]:
                    usage[k] += (row.get("usage") or {}).get(k, 0) or 0
                if row["status"] != "response":
                    unreturned.append(
                        {
                            "step": step,
                            "request_id": row["id"],
                            "unit": row["unit"],
                            "status": row["status"],
                            "error_type": row.get("error_type"),
                        }
                    )
                    failures[row.get("error_type", "started_without_return")] += 1
        suffix_records = [read(f) for f in (directory / "continuations").glob("*.json")]
        turns = [
            r["persistent_proposal_turns"]
            for r in suffix_records
            if "persistent_proposal_turns" in r
        ]
        totals[step] = {
            "continuation_descriptives": {
                "termination_reasons": dict(
                    collections.Counter(r["termination_reason"] for r in suffix_records)
                ),
                "persistent_accepted_future_turns": {
                    "sum": sum(turns),
                    "denominator": len(turns),
                    "median": statistics.median(turns) if turns else None,
                    "maximum": max(turns) if turns else None,
                    "termination_reasons": dict(
                        collections.Counter(
                            r["termination_reason"]
                            for r in suffix_records
                            if "persistent_proposal_turns" in r
                        )
                    ),
                },
            },
            "usage": dict(usage),
            "roles": dict(roles),
            "credential_allocation_by_condition_role": dict(credential_counts),
            "returned_models_by_condition_credential_role": {
                k: dict(v) for k, v in route_models.items()
            },
            "temperatures": dict(temperatures),
            "failures": dict(failures),
            "suffixes_saved": len(list((directory / "continuations").glob("*.json"))),
        }
    save(
        OUT / "token_accounting.json",
        {
            "steps": totals,
            "total": dict(
                sum(
                    (collections.Counter(v["usage"]) for v in totals.values()),
                    collections.Counter(),
                )
            ),
            "returned_models": dict(models),
            "unreturned_requests": unreturned,
            "limitation": "Requests interrupted or failed before a response have unknown provider-side token usage; totals sum returned usage only. Failed suffix attempts can consume tokens before retry; all request records remain.",
        },
    )
    p = read(OUT / "plan.json")
    expected = {
        "step1": 960,
        "step2": p["step2_suffixes"],
        "step3a": 0,
        "step3b": 960
        if read(D["step3a"] / "interface_check.json")["proceed_to_3b"]
        else 0,
    }
    assert all(totals[k]["suffixes_saved"] == n for k, n in expected.items())
    planned_units = {
        "step1": {
            f"{c['state_id']}:original:d0:r{rep}"
            for c in p["states"]
            for rep in range(24)
        },
        "step2": {
            f"{c['state_id']}:fixed:{c['candidate_id']}:r{rep}"
            for c in p["candidates"]
            for rep in range(16)
        }
        | {
            f"{c['state_id']}:native_{c['candidate_id']}:d{j}:r0"
            for c in p["candidates"]
            for j in range(16)
        },
        "step3b": {
            f"{sid}:{family}:d{j}:r{rep}"
            for sid in p["step3b_states"]
            for family in ["single", "persistent"]
            for j in range(6)
            for rep in range(4)
        },
    }
    for step in ["step1", "step2", "step3b"]:
        actual_units = {f.stem for f in (D[step] / "continuations").glob("*.json")}
        assert actual_units == planned_units[step], {
            "step": step,
            "missing": sorted(planned_units[step] - actual_units),
            "extra": sorted(actual_units - planned_units[step]),
        }
    case_by_id = {c["state_id"]: c for c in p["states"]}
    replay_checks = []
    for sid, c in case_by_id.items():
        original = read(D["step1"] / "replies" / f"{sid}:original:d0.json")
        prefix, block = b.source_block(c)
        assert original["prefix"] == prefix and original["partner_block"] == block
        replay_checks.append({"state_id": sid, "original_block_exact": True})
    transfer_checks = []
    for path in (D["step3b"] / "replies").glob("*:turn*.json"):
        r = read(path)
        prefix = r["prefix"][: -len(r["partner_block"])]
        transferred = (
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
            in (prefix[-1].get("content") or "").upper()
        )
        if transferred:
            valid = any(
                "###TRANSFER###" in (m.get("content") or "")
                for m in r["partner_block"]
                if m["role"] == "user"
            ) and not any(m.get("tool_calls") for m in r["partner_block"])
            transfer_checks.append({"unit": r["unit"], "valid": valid})
    assert all(r["valid"] for r in transfer_checks)
    save(
        D["step3b"] / "transfer_protocol_audit.json",
        {
            "accepted_explicit_transfer_turns": len(transfer_checks),
            "violations": 0,
            "records": transfer_checks,
            "archived_correction": "transport_history/transfer_protocol/correction.json",
        },
    )
    save(
        OUT / "audit.json",
        {
            "historical_source_files_verified": len(manifests),
            "historical_changed_files": changed,
            "expected_new_suffixes": expected,
            "actual_saved_suffixes": {
                k: r["suffixes_saved"] for k, r in totals.items()
            },
            "original_source_block_replay": replay_checks,
            "git_hash": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=b.ROOT, text=True
            ).strip(),
            "new_raw_ledger_paths": {
                k: str(d.relative_to(b.ROOT) / "requests") for k, d in D.items()
            },
            "tests_log": "tests.log",
            "execution_code_sha256": {
                f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                for f in OUT.glob("*.py")
            },
            "frozen_plan_sha256": hashlib.sha256(
                (OUT / "plan.json").read_bytes()
            ).hexdigest(),
            "execution_amendments": [
                "execution_amendment_resume.json",
                "execution_amendment_transport.json",
                "execution_amendment_native_message.json",
            ],
            "model_labels_not_human": True,
            "persistent_context_cache": "Future proposal cache includes semantic preceding-history digest; agent state is kept live when accepted partner effects are adopted. Transport initialization runs once per process to avoid closing cached HTTP sessions.",
        },
    )
    version_rows = []
    for path in (D["step3b"] / "continuations").glob("*:persistent:*.json"):
        r = read(path)
        versions = r.get(
            "future_proposal_validation_versions",
            {"strict_xor_v1": r["persistent_proposal_turns"]},
        )
        version_rows.append(
            {
                "unit": r["unit"],
                "state_id": r["state_id"],
                "future_validation_versions": versions,
                "contains_corrected_validation_turn": versions.get(
                    "native_inclusive_or_v2", 0
                )
                > 0,
            }
        )
    save(
        D["step3b"] / "native_validation_audit.json",
        {
            "initial_branch_draws": "All 120 shared initial branch draws retained from strict_xor_v1",
            "v1_only_persistent_suffixes": sum(
                not r["contains_corrected_validation_turn"] for r in version_rows
            ),
            "corrected_validation_present_suffixes": sum(
                r["contains_corrected_validation_turn"] for r in version_rows
            ),
            "recovered_false_invalid_batches": len(
                list((D["step3b"] / "revalidated_proposals").glob("*.json"))
            ),
            "per_suffix": version_rows,
            "limitation": "Earlier samples were conditioned on the erroneous stricter XOR batch filter. Later native-valid OR samples alter that acceptance law. Pooled persistent results describe mixed-version execution, not an isolated uniformly corrected persistent generator. Frozen generation/fidelity prompts unchanged; false rejections retained.",
            "amendment": "../v7_b1_report_20261004/execution_amendment_native_message.json",
        },
    )
    save(OUT / "input_manifest.json", manifests)
    return totals


def report():
    p = read(OUT / "plan.json")
    attr = read(D["step1"] / "attribution.json")["aggregate"]
    signals = read(D["step1"] / "attributed_signal_comparison.json")
    retest = read(D["step2"] / "retest.json")
    multiple = read(D["step2"] / "multiplicity_supplement.json")
    interface = read(D["step3a"] / "interface_check.json")
    run3 = interface["proceed_to_3b"]
    condition = read(D["step3b"] / "conditions.json") if run3 else None
    totals = accounting()
    validation = read(D["step3b"] / "native_validation_audit.json") if run3 else None
    lines = [
        "# P4 v7 — Tier B round 1",
        "",
        "Exploratory attribution control, independent retest and tools-aware single/persistent partner. Same Luna agent and native/VS Luna partner, temperature 1.0, original 40 states and 200-new-step suffix limit. No researcher-written personas or persistent behavior rules. Sol temperature-0 judgments are model labels, not human ground truth. Historical v6/v6.1 and Tier A files were preserved.",
        "",
        "## Step 1 — exact original-block control",
        "",
        "Executed 40 × 24 = 960 fresh original-block suffixes. The entire original partner turn, including calls and results, is replayed; the agent and later native partner are resampled. Terminal source turns produce deterministic, already-ended episodes and are kept in the counts. No optional temperature-0 arm. M2–M4 definitions and task device fields are frozen from Tier A.",
        "",
        table(
            [
                "Mode",
                "Source",
                "Absent from 24-control mode set / source modes",
                "Pooled share",
                "Mean absent modes/state [task-cluster CI]",
                "Absent counts at 6 / 12 / 18 / 24",
            ],
            [
                [
                    m,
                    arm,
                    f"{r['attributable_count']}/{r['source_distinct_count']}",
                    f(r["pooled_share"]),
                    ci(r["per_state_count"]),
                    "/".join(str(r["prefix_counts"][str(n)]) for n in [6, 12, 18, 24]),
                ]
                for m, x in attr.items()
                for arm, r in x.items()
            ],
        ),
        "",
        "![Control saturation and remaining absent modes](../v7_b1_step1_20261004/attribution_saturation.png)",
        "",
        "Counts are sums of per-state distinct modes: the same semantic mode in different states is compared with each state’s own control. The primary prefix counts use rep 0…n−1; curves use 50 shuffled orders and retain every per-state curve. “Partner-attributable” means only absent from this finite control, not outside its population support. Later native partner randomness is deliberately included in agent-only, so this is an original-block baseline rather than isolated agent-temperature noise.",
        "",
        "E3 repeats reply-half holdout / swapped folds on the historical q/q′ data. Future novelty must also be absent from the same state’s 24 control suffixes. Both future-suffix counts and distinct future-mode counts are saved. Below is novelty against all directions’ past; own-past results and raw numerators are in attributed_signal_comparison.json / direction_folds.jsonl.",
        "",
        table(
            [
                "Mode",
                "Signal",
                "Spearman [task-cluster CI]",
                "Top-quarter precision [CI]",
                "Capture [CI]",
                "Lift [CI]",
            ],
            [
                [
                    m,
                    s,
                    ci(r["statistics"]["spearman"]),
                    ci(r["statistics"]["precision"]),
                    ci(r["statistics"]["capture"]),
                    ci(r["statistics"]["lift"]),
                ]
                for m, x in signals.items()
                for s, r in x["all_directions_past"].items()
                if s != "GT_minus_REWARD_VARIANCE"
            ],
        ),
        "",
        table(
            [
                "Mode",
                "Paired GT − reward variance: rho [CI]",
                "Precision difference [CI]",
                "Capture difference [CI]",
                "Lift difference [CI]",
            ],
            [
                [
                    m,
                    ci(
                        x["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["spearman"]
                    ),
                    ci(
                        x["all_directions_past"]["GT_minus_REWARD_VARIANCE"][
                            "precision"
                        ]
                    ),
                    ci(x["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["capture"]),
                    ci(x["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["lift"]),
                ]
                for m, x in signals.items()
            ],
        ),
        "",
    ]
    m3q = attr["M3"]["q"]
    m3p = attr["M3"]["q_prime"]
    lines += [
        f"Plain-language reading: the original-block control covers {m3q['source_distinct_count'] - m3q['attributable_count']}/{m3q['source_distinct_count']} native-q M3 modes and {m3p['source_distinct_count'] - m3p['attributable_count']}/{m3p['source_distinct_count']} q′ M3 modes at the same states. The remaining modes are candidates for partner attribution, with control sample-size dependence shown above. This removes a major source of apparent novelty without proving that all covered modes are agent randomness or that every uncovered mode is caused by partner variation. Read the paired signal differences to judge GT beyond reward variance; a positive GT correlation alone is insufficient.",
        "",
        "For the compact M3 definition after control filtering, GT versus reward variance has a paired correlation difference "
        + ci(
            signals["M3"]["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["spearman"]
        )
        + " and top-quarter lift difference "
        + ci(signals["M3"]["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["lift"])
        + ". Neither interval establishes a GT advantage. The M4 correlation difference is "
        + ci(
            signals["M4"]["all_directions_past"]["GT_minus_REWARD_VARIANCE"]["spearman"]
        )
        + ", while the corresponding allocation-lift difference still includes zero. GT remains useful predictive evidence, rather than a proven superior reuse rule.",
        "",
        "Distinct future-mode targets (secondary) are also reported below; suffix-count precision and distinct-mode precision use different numerators and must not be conflated.",
        "",
        table(
            [
                "Mode",
                "Signal",
                "Distinct-target Spearman [CI]",
                "Distinct-target capture [CI]",
                "Distinct-target lift [CI]",
            ],
            [
                [
                    m,
                    signal,
                    ci(r["statistics"]["spearman"]),
                    ci(r["statistics"]["capture"]),
                    ci(r["statistics"]["lift"]),
                ]
                for m, x in signals.items()
                for signal, r in x["all_directions_past_distinct"].items()
                if signal != "GT_minus_REWARD_VARIANCE"
            ],
        ),
        "",
        "## Step 2 — fresh retest",
        "",
        f"{p['primary_candidate_count']} deduplicated mandatory/strong primary candidates + 5 frozen random bank controls = {len(p['candidates'])} candidates; {p['step2_suffixes']} new suffixes, 16 fixed + 16 independently drawn native-reference blocks per candidate. All 18 q′-exclusive M2-producing blocks were represented after signature deduplication. The five high states are native-q null exceedances; the different q′ set is retained in plan.json. Mandatory coverage exceeded the approximate 25 slots, so no required block was dropped. Step-1 original-block suffixes are a shared third reference, not newly resampled again.",
        "",
        table(
            [
                "Candidate / source",
                "Selection / control",
                "Screen shift",
                "Fixed / native / original successes",
                "Retest shift [score 95% CI]",
                "Sign holds",
                "Same-direction CI excludes 0",
                "Absolute attenuation",
                "M2 reappears",
            ],
            [
                [
                    r["candidate_id"] + " " + r["reply_unit"],
                    "random" if r["random_control"] else "primary",
                    f(r["screening_shift"]),
                    f"{r['fixed_successes']}/16; {r['native_reference_successes']}/16; {r['original_control_successes']}/24",
                    f(r["retest_shift"])
                    + f" [{f(r['retest_95_CI'][0])}, {f(r['retest_95_CI'][1])}]",
                    r["sign_holds"],
                    r["unadjusted_CI_excludes_zero_same_direction"],
                    f(r["absolute_attenuation"]),
                    str(len(r["reappeared_exclusive_M2_modes"]))
                    + "/"
                    + str(len(r["exclusive_M2_modes"])),
                ]
                for r in retest["candidates"]
            ],
        ),
        "",
        table(
            [
                "Cohort",
                "Screening direction",
                "n",
                "Sign holds",
                "Same-direction CI excludes zero",
                "Mean absolute attenuation",
            ],
            [
                [
                    co,
                    d,
                    r["n"],
                    r["sign_holds"],
                    r["CI_excludes_zero_same_direction"],
                    f(r["mean_absolute_attenuation"]),
                ]
                for co, x in retest["summary"].items()
                for d, r in x.items()
            ],
        ),
        "",
        "![Screening versus fresh retest](../v7_b1_step2_20261004/retest_regression.png)",
        "",
        "Per-candidate intervals use independent-binomial Newcombe score risk differences, so all-zero/all-one samples do not create collapsed uncertainty. Survival is reported as retained sign and separately an unadjusted 95% interval excluding zero in the screening direction; it is exploratory, not multiplicity-corrected confirmation. Negative shifts, zero shifts and increases in effect magnitude are retained. The exclusive modes are the original global q′-only M2 keys, not a newly selected success definition. Full per-candidate recurrence in fixed/native/original arms and vs-original score intervals are saved.",
        "",
        f"Plain-language reading: {retest['exclusive_M2_candidates_reappeared']}/{retest['exclusive_M2_candidates']} exclusive-M2-producing candidates reproduce at least one of those modes with a fixed block. Reappearance alone is not a partner effect if fresh native or original-block suffixes also reach it. The directional retest table, rather than the screening cutoff, determines the strength and uncertainty of the outcome-effect evidence.",
        "",
        "Supplemental, not prespecified: directional Fisher exact tests in the preselected screening directions, Holm-adjusted across all 32 retested candidates. Primary candidates retaining a descriptive 0.05 adjusted reading: "
        + str(multiple["summary"]["primary"])
        + ". No sampling or main survival definition changed. Exact failure/success assertion vectors, tool paths and branch blocks for these cases are archived in step2/reconfirmed_cases/; they are mechanical execution records, not human failure-mode labels.",
        "",
        "The earlier within-state/family permutation preserves each family’s mean. Thus a q′ family mean shift relative to q can remain inside that candidate-count null. The null-compatible bank count and these fixed-block-versus-native retests test different questions; null-count ratios must not be read as an entry-specific FDR or proof that these independently retested effects cannot exist.",
        "",
        "## Step 3 — tools interface and persistence",
        "",
        "3a: 10 frozen states × 6 accepted draws, no suffixes. Original proposal JSON already admitted tools; this intervention clarifies preserving tools required by a request and validates each name/argument against native schemas before actual native execution. During 3a, the validator incorrectly restricted first messages to text XOR tools; native simulator completed reports from actual tool results. The later native-OR correction and its mixed-version limitation are documented below. Native scenario/history and the Sol fidelity prompt are unchanged. No private device DB snapshot was added to the proposal.",
        "",
        table(
            [
                "Source, same 10 states",
                "Model-labelled device tools",
                "Model-labelled device-state report",
            ],
            [
                [
                    arm,
                    str(v["device_tool_action"]["numerator"]) + "/60",
                    str(v["device_state_report"]["numerator"]) + "/60",
                ]
                for arm, v in interface["aggregate"].items()
            ],
        ),
        "",
        f"Paired device-action difference vs native q: {f(interface['tool_action_difference_vs_q'])} [{f(interface['paired_task_cluster_95_CI'][0])}, {f(interface['paired_task_cluster_95_CI'][1])}]. Mechanically observed blocks with user tool calls: {interface['mechanical_execution_total']}/60. Interface condition {'met: the rate is not clearly below q, so 3b ran' if run3 else 'not met: 3b was not run; lower action rate is the blocker'}. This is not certification of equivalence. No action-rate-driven prompt tuning was performed.",
        "",
    ]
    if run3:
        lines += [
            "3b: 20 frozen open states (five native-q high states + 15 preselected random others), 6 branch draws × 4 suffixes per condition. Single and persistent share the exact accepted branch draws; single then returns to native partner, persistent makes a fresh tools-aware VS proposal at every later partner turn. 480 fresh suffixes each; 480 native suffixes are reused from the paired run with identical setup. Interface draws at overlapping states are reused. Accepted future-turn effects are replay-validated; live agent state is preserved, and proposal caches are keyed by preceding-history hash.",
            "",
            table(
                [
                    "Condition",
                    "Successes / 480",
                    "Mean S_hat [task-cluster CI]",
                    "Mean attributable M3 modes/state [CI]",
                ],
                [
                    [
                        c,
                        str(r["successes"]) + "/480",
                        ci(r["S_hat"]),
                        ci(r["attributable_M3_count"]),
                    ]
                    for c, r in condition["aggregate"].items()
                ],
            ),
            "",
            table(
                [
                    "Paired condition contrast",
                    "Success difference [CI]",
                    "S_hat difference [CI]",
                    "Attributable M3 count difference [CI]",
                ],
                [
                    [
                        c,
                        ci(r["mean_success"]),
                        ci(r["S_hat"]),
                        ci(r["attributable_M3_count"]),
                    ]
                    for c, r in condition["paired_task_cluster_contrasts"].items()
                ],
            ),
            "",
            f"**Native-message validation amendment:** the initial implementation wrongly required text XOR tool calls, whereas native Message.validate permits both together. One compound-request turn accumulated 114 rejected batches under this false restriction; native-valid combined text/tool candidates were rejected before fidelity evaluation. The validator was corrected to native inclusive OR without editing model outputs or tuning generation/fidelity prompts. A separate offline native-schema audit found 114/114 saved false-invalid batches legal; the sampler enabled reuse at matching histories, but actual recovered false-invalid batches were {validation['recovered_false_invalid_batches']}. Offline schema legality therefore does not imply fidelity acceptance or execution. The original invalid records remain. Initial branch draws and single suffixes retain v1; {validation['v1_only_persistent_suffixes']}/480 persistent suffixes use only v1-accepted future turns, and {validation['corrected_validation_present_suffixes']}/480 include corrected-v2 turns, sometimes together with cached v1 turns. Thus the pooled persistent contrast is exploratory mixed-version execution and cannot isolate persistence under a uniformly corrected proposal sampler. See [version audit](../v7_b1_step3b_20261004/native_validation_audit.json) and [amendment](execution_amendment_native_message.json).",
            "",
            "![Three-condition comparison](../v7_b1_step3b_20261004/condition_comparison.png)",
            "",
        ]
        future_turns = totals["step3b"]["continuation_descriptives"][
            "persistent_accepted_future_turns"
        ]
        lines += [
            f"Operational size: the 480 finalized persistent suffixes contain {future_turns['sum']} accepted future VS turns; median {future_turns['median']}, maximum {future_turns['maximum']}. Persistent termination reasons (raw counts): {future_turns['termination_reasons']}. This is in addition to the 120 shared initial branch draws. The conditions have equal suffix counts, not equal generator-call or token cost. Accepted proposals used only by interrupted/retried paths and rejected proposals remain in the audit files and ledger, so actual model calls exceed these finalized-trajectory counts.",
            "",
        ]
        undo_stats = read(D["step3b"] / "undo.json")
        undo = undo_stats["aggregate"]
        lines += [
            f"Single next-turn undo: {undo['undo_numerator']}/{undo['available_denominator']} = {f(undo['share'])}; {undo['censored_no_next_partner']} suffixes have no later native partner turn and are censored. Mean of state-specific undo shares [task-cluster CI]: {ci(undo_stats['cluster_mean_of_state_shares'])}. Frozen Sol E0-style judgments retain possible conflation of agent repair with partner reversal; this is a provisional model-labelled rate, not a causal regression estimate.",
            "",
            "Persistent S_hat measures sensitivity to the initial branch draw while averaging over fresh later proposals. It is not total variance over whole partner trajectories. Native q is historical rather than contemporaneously randomized, and mode attribution remains limited by 24 original-block draws. Per-state results and all negative estimates are retained.",
            "",
            "Plain-language reading: single − native success is "
            + ci(
                condition["paired_task_cluster_contrasts"]["single_minus_native"][
                    "mean_success"
                ]
            )
            + "; "
            + interval_reading(
                condition["paired_task_cluster_contrasts"]["single_minus_native"][
                    "mean_success"
                ]
            )
            + ". Persistent − single success is "
            + ci(
                condition["paired_task_cluster_contrasts"]["persistent_minus_single"][
                    "mean_success"
                ]
            )
            + "; "
            + interval_reading(
                condition["paired_task_cluster_contrasts"]["persistent_minus_single"][
                    "mean_success"
                ]
            )
            + ". Its initial-draw sensitivity difference is "
            + ci(
                condition["paired_task_cluster_contrasts"]["persistent_minus_single"][
                    "S_hat"
                ]
            )
            + "; "
            + interval_reading(
                condition["paired_task_cluster_contrasts"]["persistent_minus_single"][
                    "S_hat"
                ]
            )
            + ". Persistence can shift the mean without increasing initial-draw sensitivity, because later partner choices are integrated into suffix noise. Tool-call rate alone does not establish stronger outcome effects; native comparisons also retain the historical-reuse limitation.",
            "",
        ]
    lines += [
        "## Three questions",
        "",
        f"1. **How much Tier A structural novelty is agent randomness?** Original-block resampling covers {m3q['source_distinct_count'] - m3q['attributable_count']}/{m3q['source_distinct_count']} native-q and {m3p['source_distinct_count'] - m3p['attributable_count']}/{m3p['source_distinct_count']} q′ per-state M3 modes. This includes randomness from later native partner turns; the remaining finite-sample absence is not proven partner causation.",
        "",
    ]
    primary = retest["summary"]["primary"]
    lines += [
        "2. **Do effects survive independent retest?** "
        + "; ".join(
            f"{d}: {r['sign_holds']}/{r['n']} retain sign, {r['CI_excludes_zero_same_direction']}/{r['n']} have an unadjusted same-direction interval excluding zero"
            for d, r in primary.items()
        )
        + ". These are exploratory evidence with screening selection and multiplicity limits.",
        "",
    ]
    if run3:
        x = condition["paired_task_cluster_contrasts"]
        lines += [
            f"3. **Does action or persistence change outcomes more?** Single − native success: {ci(x['single_minus_native']['mean_success'])}; persistent − single: {ci(x['persistent_minus_single']['mean_success'])}. Interpret signs and full intervals; neither mode novelty nor an increased tool rate substitutes for this execution evidence. The persistent arm mixes validator versions, so it does not isolate a uniform corrected generator.",
            "",
        ]
    else:
        lines += [
            "3. **Does action or persistence change outcomes more?** Not tested: the interface still produced clearly fewer actions, so the requested interface condition blocked 3b. No outcome conclusion is inferred.",
            "",
        ]
    lines += [
        "## Detailed evidence",
        "",
        "Per-state control attribution and sample-size curves: [attribution.json](../v7_b1_step1_20261004/attribution.json), [saturation_curves.json](../v7_b1_step1_20261004/saturation_curves.json), [signal comparisons](../v7_b1_step1_20261004/attributed_signal_comparison.json). Each of the 40 state curves is under step1/state_curves/.",
        "",
        "Every candidate’s screening/retest shifts, score intervals, mode recurrence and references: [retest.json](../v7_b1_step2_20261004/retest.json). The supplemental multiplicity analysis is [multiplicity_supplement.json](../v7_b1_step2_20261004/multiplicity_supplement.json); actual success/failure trajectories and mechanical unmet-assertion records are under step2/reconfirmed_cases/.",
        "",
        "Interface observations: [interface_check.json](../v7_b1_step3a_20261004/interface_check.json). All 20 states’ three-condition sensitivities, success numerators and M3 counts: [conditions.json](../v7_b1_step3b_20261004/conditions.json). Next-turn model judgments and denominators: [undo.json](../v7_b1_step3b_20261004/undo.json), with raw judgments under step3b/undo_labels/. Every negative estimate is retained.",
        "",
        "## Accounting and audit",
        "",
        table(
            [
                "Step",
                "Saved new suffixes",
                "Returned prompt tokens",
                "Returned completion tokens",
                "Request records",
                "Errors / unfinished",
            ],
            [
                [
                    s,
                    r["suffixes_saved"],
                    r["usage"].get("prompt_tokens", 0),
                    r["usage"].get("completion_tokens", 0),
                    r["usage"]["requests"],
                    str(r["usage"].get("error", 0))
                    + " / "
                    + str(r["usage"].get("started", 0)),
                ]
                for s, r in totals.items()
            ],
        ),
        "",
        "Every attempt is preserved in each new step’s redacted requests/ ledger. Unknown provider-side tokens for interrupted/failed calls are not imputed. A transport-resume correction avoided closing a cached HTTP client during successive phases; accepted draws were reused. Persistent future-turn cache identity was tightened before those suffixes began. A subsequent protocol audit found accepted future replies violating the existing mandated transfer token; affected suffixes and proposal evidence were archived under step3b/transport_history/transfer_protocol and rerun with the same native programmatic terminal requirement restored. The resumable proposal loop was also corrected to skip previously rejected cached draws and continue fresh rejection sampling as in the original paired sampler; the native explicit-transfer proposal reminder was restored. These execution amendments are recorded in execution_amendment_resume.json. Transient provider failures now retry the identical audited call up to three times and failed jobs requeue promptly, avoiding whole-episode restart for routine network errors and batch-wide retry barriers; see execution_amendment_transport.json. Six early partial annotation caches were archived and relabelled on complete reply groups using the unchanged frozen Sol prompt; coverage is validated by exact (reply, repetition) identity. The native-message legality correction and the mixed-version interpretation are separately recorded in execution_amendment_native_message.json. No fidelity model prompt was tuned. No optional temperature-zero control, no new personas, no researcher/human behavioral labels. Source hashes and exact original-block identity are verified in audit.json. Tests use explicitly synthetic fixtures and never enter run statistics.",
        "",
        "Temperatures match the requested batch at 1.0; the τ² paper’s standard user simulator temperature is 0. This round does not add a headline temperature-0 comparison. All effects, survival counts and search-signal comparisons remain exploratory.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("REPORT COMPLETE", flush=True)


if __name__ == "__main__":
    report()
