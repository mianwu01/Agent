"""Exploratory labels, case efficiency and task-cluster intervals from real artifacts."""

import collections
import json

import c2 as c
import numpy as np


def score(rows):
    k, n = sum(r["reward"] == 1 for r in rows), len(rows)
    return {
        "successes": k,
        "n": n,
        "rate": k / n if n else None,
        "Wilson95_CI": list(c.x.stats.wilson(k, n)) if n else None,
    }


def difference(a, b):
    aa, bb = score(a), score(b)
    rng = np.random.default_rng(2026100608)
    tasks = sorted({r["task_id"] for r in a + b})
    values = []
    ac = {
        t: (
            sum(r["reward"] == 1 for r in a if r["task_id"] == t),
            sum(r["task_id"] == t for r in a),
        )
        for t in tasks
    }
    bc = {
        t: (
            sum(r["reward"] == 1 for r in b if r["task_id"] == t),
            sum(r["task_id"] == t for r in b),
        )
        for t in tasks
    }
    for _ in range(1000):
        ids = rng.choice(tasks, len(tasks), replace=True) if tasks else []
        ak = sum(ac[t][0] for t in ids)
        an = sum(ac[t][1] for t in ids)
        bk = sum(bc[t][0] for t in ids)
        bn = sum(bc[t][1] for t in ids)
        if an and bn:
            values.append(ak / an - bk / bn)
    return {
        "persistent": aa,
        "single": bb,
        "difference": aa["rate"] - bb["rate"] if aa["n"] and bb["n"] else None,
        "task_cluster_bootstrap95_CI": list(np.quantile(values, [0.025, 0.975]))
        if values
        else None,
        "bootstrap_replicates": len(values),
    }


def label_summary():
    root = c.D["step2"]
    m = c.read(root / "manifest.json")
    classes = {
        r["candidate_id"]: r
        for r in c.read(c.BASE / "v7_c_step2_20261005/reclassification.json")["cases"]
    }
    cases = []
    for case in m["cases"]:
        path = root / "mapped_labels" / f"{case['label_digest']}.json"
        if path.exists():
            cases.append(
                {
                    **case,
                    "class": classes[case["candidate_id"]]["new_class"],
                    **c.read(path),
                }
            )
    trajectories = []
    for row in m["trajectories"]:
        path = root / "trajectory_batch_labels" / f"{row['unit']}.json"
        if not path.exists():
            continue
        labels = [r["label"] for r in c.read(path)["labels"]]
        trajectories.append(
            {
                **row,
                "valid": all(r["valid"] for r in labels),
                "style": "out_of_rule"
                if any(r["style"] == "out_of_rule" for r in labels)
                else "in_rule",
                "out_of_rule_turns": sum(r["style"] == "out_of_rule" for r in labels),
            }
        )
    comparisons = {}
    for cohort in ["B1", "v2_Luna"]:
        pp = [
            r
            for r in trajectories
            if r["cohort"] == cohort and r["condition"] == "persistent"
        ]
        states = {r["state_id"] for r in pp}
        ss = [
            r
            for r in trajectories
            if r["cohort"] == "B1"
            and r["condition"] == "single"
            and (cohort == "B1" or r["state_id"] in states)
        ]
        comparisons[cohort] = {}
        for split in ["all_raw", "all_valid", "in_rule", "out_of_rule"]:

            def select(rr):
                return [
                    r
                    for r in rr
                    if split == "all_raw"
                    or (r["valid"] and (split == "all_valid" or r["style"] == split))
                ]

            comparisons[cohort][split] = difference(select(pp), select(ss))
    strata = {}
    for row in trajectories:
        key = (
            row["cohort"],
            row["condition"],
            row["state_id"],
            row["style"],
            row["valid"],
        )
        strata.setdefault(key, []).append(row)
    per_state = [
        {
            "cohort": k[0],
            "condition": k[1],
            "state": k[2],
            "style": k[3],
            "valid": k[4],
            **score(v),
        }
        for k, v in strata.items()
    ]
    result = {
        "per_state_raw_counts": per_state,
        "sampling_quotas": {
            "B1_native": 40,
            "B1_single": 80,
            "B1_persistent": 80,
            "v2_Luna_persistent": 80,
            "v2_Sol_persistent": 20,
        },
        "cases": cases,
        "case_classes_by_style": {
            style: dict(
                collections.Counter(
                    r["class"] for r in cases if r["valid"] and r["style"] == style
                )
            )
            for style in ["in_rule", "out_of_rule"]
        },
        "sampled_trajectories_requested": 300,
        "sampled_trajectories_complete": len(trajectories),
        "sampled_trajectory_rows": trajectories,
        "persistent_comparisons": comparisons,
        "partial": len(cases) < 15 or len(trajectories) < 300,
        "caveat": "Sampled retrospective validity/style filtering; not causal mediation. Per-state quotas frozen without reward inspection. Incomplete trajectories are unknown, not valid.",
    }
    c.save(root / "relabel_summary.json", result)
    return result


def classify(root, check, sol):
    cand = check["candidate"]
    fixed = [c.read(root / "continuations" / f"{u}.json") for u in check["fixed_units"]]
    native = [
        c.read(root / "continuations" / f"{u}.json") for u in check["native_units"]
    ]
    sf = (
        [c.read(root / "continuations" / f"{u}.json") for u in sol["fixed_units"]]
        if sol
        else []
    )
    harmful = check["shift"] < 0
    failures = [r for r in fixed + sf if r["reward"] != 1]
    exact = []
    for r in failures:
        unmet = [
            a["assertion"]["func_name"] for a in r["assertions_final"] if not a["met"]
        ]
        exact.append(bool(unmet) and set(unmet) <= {"assert_data_refueling_amount"})
    changed = None
    facts = []
    native_facts = []
    if not cand["persistent_direction"]:
        reply = c.read(root / "replies" / f"{cand['reply_unit']}.json")
        task = c.x.b.Task.model_validate(
            c.read(root / "tasks.json")[cand["state"]["task_id"]]
        )
        prefix = reply["prefix"][: -len(reply["partner_block"])]
        before = c.mech.replay(task.model_dump(mode="json"), prefix)
        after = c.mech.replay(task.model_dump(mode="json"), reply["prefix"])
        changed = c.x.p4.state(before.environment) != c.x.p4.state(after.environment)
        facts = c.mech.check_claims(
            prefix, reply["partner_block"], after.environment, before.environment
        )["claims"]
        for row in native:
            ref = c.read(
                root
                / "replies"
                / f"{cand['candidate_id']}:retest:reference:d{row['j']}.json"
            )
            native_facts.extend(ref["label"].get("fact_check", {}).get("claims", []))
    native_claims = {
        (f["field"], json.dumps(f.get("value"), sort_keys=True))
        for f in native_facts
        if f.get("db_matches")
    }
    disclosures = [
        f
        for f in facts
        if f.get("db_matches")
        and (f["field"], json.dumps(f.get("value"), sort_keys=True))
        not in native_claims
    ]
    matches = []
    if harmful:
        if failures and sum(exact) / len(failures) >= 0.5:
            matches.append("reward_spec_mismatch")
        if sol:
            if (
                check["95_CI"][1] < 0
                and sol["95_CI"][1] < 0
                and changed is False
                and check["fixed_successes"] + sol["fixed_successes"] > 0
            ):
                matches.append("hard_for_both")
            ci = c.x.stats.difference_interval(
                sol["fixed_successes"], 16, check["fixed_successes"], 16
            )
            if ci[0] > 0:
                matches.append("capability_dependent")
            if (
                changed is True
                and check["fixed_successes"] + sol["fixed_successes"] == 0
            ):
                matches.append("infeasible_after_block")
    else:
        matches.append("beneficial_disclosure" if disclosures else "beneficial_other")
    return {
        "class": matches[0] if matches else "unclear",
        "matching_classes": matches,
        "Sol_check_complete": bool(sol),
        "block_DB_changed": changed,
        "exact_only_failures": sum(exact),
        "pooled_fixed_failures": len(failures),
        "disclosures": disclosures,
        "persistent_DB_scope": "Fixed-block DB-change classes unassessed for persistent generator directions; do not infer no change from absent fixed block."
        if cand["persistent_direction"]
        else None,
    }


def request_accounting(root):
    """Summarize redacted records without emitting credential or request content."""
    groups = {}
    for path in (root / "requests").glob("*.json"):
        row = c.read(path)
        key = (
            row.get("role"),
            row.get("request", {}).get("model"),
            row.get("returned_model"),
        )
        record = groups.setdefault(
            key,
            {
                "role": key[0],
                "requested_model": key[1],
                "returned_model": key[2],
                "responses": 0,
                "unknown_or_inflight": 0,
                "errors": 0,
                "returned_tokens": 0,
            },
        )
        if row["status"] == "response":
            record["responses"] += 1
            record["returned_tokens"] += (row.get("usage") or {}).get("total_tokens", 0)
            if row.get("usage") is None:
                record["unknown_or_inflight"] += 1
        else:
            record["unknown_or_inflight"] += 1
            record["errors"] += row["status"] == "error"
    return list(groups.values())


def search_summary():
    arms = {}
    for arm in ["A0", "A1", "A2", "A3", "A4"]:
        root = c.D["step3"] / "arms" / arm
        if not root.exists():
            continue
        costs = [c.read(p) for p in (root / "cost_calls").glob("*.json")]
        shared = (
            c.read(root / "effective_plan.json").get("shared_probe_returned_tokens", 0)
            if (root / "effective_plan.json").exists()
            else 0
        )
        tokens = sum(r.get("returned_tokens", 0) for r in costs) + shared
        projection = c.read(c.D["step3"] / "cost_projection.json")
        unknown = sum(
            r.get("reserved_estimate", 0)
            for r in costs
            if r["status"] in ["started", "unknown_usage"]
        )
        equivalents = (tokens + unknown) / projection["tokens_per_suffix_equivalent"]
        returned_equivalents = tokens / projection["tokens_per_suffix_equivalent"]
        paths = (
            c.read(root / "mode_paths.json")
            if (root / "mode_paths.json").exists()
            else {}
        )
        cases, cells = [], {}
        for p in (root / "verified").glob("*.json"):
            check = c.read(p)
            if not check["valid"]:
                continue
            solpath = root / "checks" / f"{check['candidate']['candidate_id']}:sol.json"
            sol = c.read(solpath) if solpath.exists() else None
            cls = classify(root, check, sol)
            failing = (
                check["fixed_units"] if check["shift"] < 0 else check["native_units"]
            )
            modes = []
            for unit in failing:
                row = c.read(root / "continuations" / f"{unit}.json")
                if row["reward"] != 1:
                    modes.append(
                        c.x.b.ta.mode_key(
                            {
                                "reward": int(row["reward"] == 1),
                                "assertions": row["assertions_final"],
                                "final_user_state": row["final_user_state"],
                                "next_action_type": row["next_action_type"],
                                "task_id": row["task_id"],
                            },
                            "M3",
                            paths,
                        )
                    )
            cid = check["candidate"]["candidate_id"]
            tid = check["candidate"]["state"]["task_id"]
            for mode in set(modes):
                key = (tid, cls["class"], mode)
                cells.setdefault(key, []).append(
                    {
                        "case": cid,
                        "style": check["style"],
                        "confirmed_at_tokens": max(
                            check.get(
                                "verified_labels_completed_at_tokens",
                                check.get("completed_at_charged_tokens", tokens),
                            ),
                            sol.get("completed_at_charged_tokens", 0) if sol else 0,
                        )
                        + shared,
                    }
                )
            cases.append(
                {
                    "candidate_id": cid,
                    "known_null_native_persistent": check["candidate"].get(
                        "persistent_direction", False
                    )
                    and check["candidate"].get("family") == "native"
                    and check["candidate"].get("future") == "native",
                    "task_id": tid,
                    "state": check["candidate"]["state"],
                    "style": check["style"],
                    "shift": check["shift"],
                    "CI": check["95_CI"],
                    "screening_shift": check["candidate"]["screening_shift"],
                    "fixed_successes": check["fixed_successes"],
                    "native_successes": check["native_successes"],
                    "n_each": 16,
                    "failing_M3_modes": sorted(set(modes)),
                    **cls,
                }
            )
        efficiency = {}
        bootstrap_inputs = {}
        tasks = (
            sorted(c.read(root / "tasks.json"))
            if (root / "tasks.json").exists()
            else []
        )
        rng = np.random.default_rng(2026100609)
        # Same task-cluster denominator weights for cases and task-assigned call costs.
        known_cost = collections.Counter()
        for r in costs:
            if r.get("task_id"):
                known_cost[r["task_id"]] += r.get("returned_tokens", 0) + (
                    r.get("reserved_estimate", 0)
                    if r["status"] in ["started", "unknown_usage"]
                    else 0
                )
        unassigned = tokens + unknown - sum(known_cost.values())
        for scope in ["all_valid", "in_rule"]:
            selected = {
                k: v
                for k, v in cells.items()
                if scope == "all_valid" or any(r["style"] == "in_rule" for r in v)
            }
            counts = collections.Counter(k[1] for k in selected)
            count_by_task = collections.Counter(k[0] for k in selected)
            boot = []
            class_boot = collections.defaultdict(list)
            class_tasks = {
                cls: collections.Counter(k[0] for k in selected if k[1] == cls)
                for cls in counts
            }
            rng = np.random.default_rng(2026100609)
            bootstrap_inputs[scope] = {
                "counts_by_task": dict(count_by_task),
                "cost_by_task": dict(known_cost),
                "unassigned_cost": unassigned,
            }
            for _ in range(1000):
                ids = rng.choice(tasks, len(tasks), replace=True) if tasks else []
                denominator = sum(known_cost[t] for t in ids) + unassigned
                if denominator:
                    for cls, by_task in class_tasks.items():
                        class_boot[cls].append(
                            sum(by_task[t] for t in ids)
                            * 1000
                            * projection["tokens_per_suffix_equivalent"]
                            / denominator
                        )
                    boot.append(
                        sum(count_by_task[t] for t in ids)
                        * 1000
                        * projection["tokens_per_suffix_equivalent"]
                        / denominator
                    )
            efficiency[scope] = {
                "distinct_cases": len(selected),
                "by_class": dict(counts),
                "per1000_suffix_equivalents": len(selected) * 1000 / equivalents
                if equivalents
                else None,
                "task_cluster_bootstrap95_CI": list(np.quantile(boot, [0.025, 0.975]))
                if boot
                else None,
                "by_class_task_cluster_bootstrap95_CI": {
                    cls: list(np.quantile(vals, [0.025, 0.975]))
                    for cls, vals in class_boot.items()
                },
                "by_class_per1000": {
                    k: v * 1000 / equivalents for k, v in counts.items()
                }
                if equivalents
                else {},
            }
        retests = list((root / "checks").glob("*:retest.json"))
        arms[arm] = {
            "complete": (root / "search_result.json").exists(),
            "shared_probe_tokens": shared,
            "model_role_accounting": request_accounting(root),
            "returned_tokens": tokens,
            "suffix_equivalents": equivalents,
            "returned_only_suffix_equivalents": returned_equivalents,
            "budget_denominator": "returned tokens + conservative reserved estimates for unknown-usage requests; not claimed exact billed tokens",
            "unknown_usage_reserved_estimate": sum(
                r.get("reserved_estimate", 0)
                for r in costs
                if r["status"] in ["started", "unknown_usage"]
            ),
            "cost_by_phase": dict(
                collections.Counter(
                    {
                        phase: sum(
                            r.get("returned_tokens", 0)
                            for r in costs
                            if r["phase"] == phase
                        )
                        for phase in {r["phase"] for r in costs}
                    }
                )
            ),
            "completed_retests": len(retests),
            "statistical_survivors": sum(
                c.read(p)["same_direction_CI_excludes_zero"] for p in retests
            ),
            "full_rule_valid_survivors": len(cases),
            "Sol_complete_survivors": sum(r["Sol_check_complete"] for r in cases),
            "verified_cases": len(cases),
            "retest_survival_rate": len(cases) / len(retests) if retests else None,
            "efficiency": efficiency,
            "bootstrap_inputs": bootstrap_inputs,
            "known_null_native_persistent_cases": [
                r["candidate_id"]
                for r in cases
                if r.get("known_null_native_persistent")
            ],
            "cases": cases,
            "distinct_cells": [
                {"task_id": k[0], "class": k[1], "M3": k[2], "evidence": v}
                for k, v in cells.items()
            ],
            "bootstrap_cost_caveat": "Unassigned shared call costs held fixed in cluster bootstrap; task-mapped screening/retest costs resampled with task clusters.",
        }
    paired = paired_efficiency(arms)
    c.save(c.D["step3"] / "paired_efficiency.json", paired)
    c.save(
        c.D["step3"] / "comparison.json",
        {
            "arms": arms,
            "partial": len(arms) < 5 or any(not r["complete"] for r in arms.values()),
        },
    )
    return arms


def paired_efficiency(arms):
    """Paired task-cluster differences with identical resampling weights across arms."""
    tasks = sorted(
        set(
            t
            for arm in arms.values()
            for scope in arm["bootstrap_inputs"].values()
            for t in scope["cost_by_task"]
        )
    )
    pairs = [
        ("A3", "A2"),
        ("A2", "A0"),
        ("A3", "A0"),
        ("A2", "A1"),
        ("A3", "A1"),
        ("A2", "A4"),
        ("A3", "A4"),
    ]
    unit = c.read(c.D["step3"] / "cost_projection.json")["tokens_per_suffix_equivalent"]
    results = []
    for a, b in pairs:
        if a not in arms or b not in arms:
            continue
        for scope in ["all_valid", "in_rule"]:
            rng = np.random.default_rng(2026100611)
            values = []

            def rate(arm, ids):
                data = arms[arm]["bootstrap_inputs"][scope]
                denominator = (
                    sum(data["cost_by_task"].get(t, 0) for t in ids)
                    + data["unassigned_cost"]
                )
                return (
                    sum(data["counts_by_task"].get(t, 0) for t in ids)
                    * 1000
                    * unit
                    / denominator
                    if denominator
                    else None
                )

            for _ in range(1000):
                ids = rng.choice(tasks, len(tasks), replace=True) if tasks else []
                aa, bb = rate(a, ids), rate(b, ids)
                if aa is not None and bb is not None:
                    values.append(aa - bb)
            aa = arms[a]["efficiency"][scope]["per1000_suffix_equivalents"]
            bb = arms[b]["efficiency"][scope]["per1000_suffix_equivalents"]
            results.append(
                {
                    "contrast": a + " - " + b,
                    "scope": scope,
                    "difference_per1000": aa - bb
                    if aa is not None and bb is not None
                    else None,
                    "task_cluster_bootstrap95_CI": list(
                        np.quantile(values, [0.025, 0.975])
                    )
                    if values
                    else None,
                    "both_complete": arms[a]["complete"] and arms[b]["complete"],
                    "replicates": len(values),
                }
            )
    return {
        "comparisons": results,
        "seed": 2026100611,
        "interpretation": "Exploratory paired task bootstrap; incomplete arms do not support efficiency rankings.",
    }


def figures(arms):
    """Export verified-case discovery curves, never fill missing arms with zeros."""
    if not any(r["verified_cases"] for r in arms.values()):
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    factor = c.read(c.D["step3"] / "cost_projection.json")[
        "tokens_per_suffix_equivalent"
    ]
    for scope in ["all_valid", "in_rule"]:
        fig, ax = plt.subplots(figsize=(8, 5))
        for arm, data in arms.items():
            events = []
            for cell in data["distinct_cells"]:
                eligible = [
                    r
                    for r in cell["evidence"]
                    if scope == "all_valid" or r["style"] == "in_rule"
                ]
                if eligible:
                    events.append(
                        min(r["confirmed_at_tokens"] for r in eligible) / factor
                    )
            if not events:
                continue
            events.sort()
            ax.step(
                [0] + events + [data["suffix_equivalents"]],
                [0] + list(range(1, len(events) + 1)) + [len(events)],
                where="post",
                label=arm + (" (partial)" if not data["complete"] else ""),
            )
        ax.set(
            xlabel="Charged token-equivalents (unknown usage conservatively reserved)",
            ylabel="Distinct verified (task, class, M3) cells",
            title=scope,
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(c.D["step3"] / f"verified_curve_{scope}.png", dpi=180)
        plt.close(fig)


def cards(arms):
    """Create evidence-only short case cards from saved execution, without extra model calls."""
    result = {}
    for arm, data in arms.items():
        root = c.D["step3"] / "arms" / arm
        selected = sorted(data["cases"], key=lambda r: -abs(r["shift"]))[:3]
        result[arm] = []
        for case in selected:
            check = c.read(root / "verified" / f"{case['candidate_id']}.json")
            candidate = check["candidate"]
            if candidate["persistent_direction"]:
                reply = c.read(
                    root
                    / "replies"
                    / f"{case['candidate_id']}:retest:candidate_draw0.json"
                )
            else:
                reply = c.read(root / "replies" / f"{candidate['reply_unit']}.json")
            prefix = reply["prefix"][: -len(reply["partner_block"])]
            request = next(
                (
                    r.get("content")
                    for r in reversed(prefix)
                    if r["role"] == "assistant"
                ),
                None,
            )
            partner = [
                r.get("content")
                for r in reply["partner_block"]
                if r["role"] == "user" and r.get("content")
            ]
            tools = [
                t["name"]
                for r in reply["partner_block"]
                for t in r.get("tool_calls") or []
            ]
            direction = (
                check["fixed_units"] if check["shift"] < 0 else check["native_units"]
            )
            failures = [c.read(root / "continuations" / f"{u}.json") for u in direction]
            failures = [r for r in failures if r["reward"] != 1]
            unmet = collections.Counter(
                a["assertion"]["func_name"]
                for r in failures
                for a in r["assertions_final"]
                if not a["met"]
            )
            next_actions = collections.Counter(r["next_action_type"] for r in failures)
            result[arm].append(
                {
                    "candidate_id": case["candidate_id"],
                    "class": case["class"],
                    "style": case["style"],
                    "agent_request": request,
                    "example_branch_text": partner,
                    "executed_branch_user_tools": tools,
                    "intervention": "persistent generator, branch example is draw0; additional turns saved in trajectories"
                    if candidate["persistent_direction"]
                    else "fixed single block",
                    "fixed_successes": check["fixed_successes"],
                    "native_successes": check["native_successes"],
                    "n_each": 16,
                    "shift": check["shift"],
                    "CI": check["95_CI"],
                    "first_agent_action_types_in_failing_direction": dict(next_actions),
                    "unmet_assertion_counts": dict(unmet),
                    "Sol_check_complete": case["Sol_check_complete"],
                    "DB_changed": case["block_DB_changed"],
                    "interpretation": "Recorded action and assertion patterns describe observed paths; they do not identify intent or prove a unique causal failure mechanism.",
                }
            )
    c.save(c.D["step3"] / "case_cards.json", result)
    return result


def report():
    labels = label_summary()
    arms = search_summary()
    figures(arms)
    case_cards = cards(arms)
    rules = c.read(c.rules_path())
    lines = [
        "# P4 v7 C2 修订：persona、抽样重标与搜索比较",
        "",
        "所有标签均为程序检查或模型判断；原生生成prompt、agent/partner温度1.0保持原设定。历史报告和数据保留。",
        "",
        "## 规则清理",
        "",
        "删除13条标题/角色/上下文行，15条角色特征单列persona；specific persona指导通用合作风格的解释，不覆盖机械与场景限制。只向标签器传ID、分类和逐字正文，审计位置保留在规则文件。",
        "",
        "|ID|类别|原文|",
        "|---|---|---|",
    ]
    for r in rules["rules"]:
        lines.append(
            f"|{r['rule_id']}|{r['category']}|{(r.get('verbatim') or r.get('operational_definition', '')).replace('|', '&#124;').replace(chr(10), '<br>')}|"
        )
    lines += [
        "",
        "## 15个确认案例",
        "",
        "|案例|状态|类|有效|规则标签|偏离规则|",
        "|---|---|---|---|---|---|",
    ]
    for r in labels["cases"]:
        lines.append(
            f"|{r['candidate_id']}|{r['state_id']}|{r['class']}|{r['valid']}|{r['style']}|{', '.join(x['rule_id'] for x in r['departed_style_rules']) or '无'}|"
        )
    lines += [
        "",
        f"完整case标签已完成{len(labels['cases'])}/15，轨迹联合标签完成{labels['sampled_trajectories_complete']}/300。未完成输入保留未知，不能作有效/无越界结论。",
        "",
        "## 持续轨迹抽样",
        "",
        "|cohort|分层|persistent成功/n|single成功/n|差|task-cluster95%CI|",
        "|---|---|---|---|---|---|",
    ]
    for cohort, splits in labels["persistent_comparisons"].items():
        for split, r in splits.items():
            a, b = r["persistent"], r["single"]
            lines.append(
                f"|{cohort}|{split}|{a['successes']}/{a['n']}|{b['successes']}/{b['n']}|{r['difference']}|{r['task_cluster_bootstrap95_CI']}|"
            )
    lines += [
        "",
        "抽样预定配额：B1 native40、single80、persistent80；v2 Luna persistent80、Sol persistent20，共300条，未按结果筛选。每状态/条件/规则标签的原始成功数、分母和score区间在relabel_summary.json。",
        "",
        "这是预先分层抽样后的历史描述，过滤有效性与style会改变样本组成，不作因果中介解释。每条轨迹的一次Sol调用联合判定所有适用规则和伙伴回合。",
        "",
        "## 搜索比较",
        "",
        "每臂预计102,752,639tokens（1000历史token suffix-equivalents），五臂预计513,763,193tokens，低于B1总用量三倍上限1,179,377,832。包含筛选、复测、Sol检查及场景judge成本。仅确认案例进行全style/persona标注；筛选回合只作必要有效性检查。",
        "",
        "|Arm|完成|retest|verified|all valid distinct/1000|in_rule distinct/1000|returned tokens|",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ["A0", "A1", "A2", "A3", "A4"]:
        r = arms.get(arm)
        if r:
            lines.append(
                f"|{arm}|{r['complete']}|{r['completed_retests']}|{r['verified_cases']}|{r['efficiency']['all_valid']['per1000_suffix_equivalents']}|{r['efficiency']['in_rule']['per1000_suffix_equivalents']}|{r['returned_tokens']}|"
            )
        else:
            lines.append(f"|{arm}|未启动|—|—|—|—|—|")
    lines += [
        "",
        "各类别效率及95%任务簇区间（每1000 suffix-equivalents）：",
        "",
        "|Arm|范围|类别|distinct|效率|95%CI|",
        "|---|---|---|---|---|---|",
    ]
    for arm, result in arms.items():
        for scope, row in result["efficiency"].items():
            for cls, count in row["by_class"].items():
                lines.append(
                    f"|{arm}|{scope}|{cls}|{count}|{row['by_class_per1000'].get(cls)}|{row['by_class_task_cluster_bootstrap95_CI'].get(cls)}|"
                )
    lines += [
        "",
        "配对任务簇效率差（探索性，未完成臂不支持排名）：",
        "",
        "|比较|范围|差/1000|95%CI|双方完成|",
        "|---|---|---|---|---|",
    ]
    for row in paired_efficiency(arms)["comparisons"]:
        lines.append(
            f"|{row['contrast']}|{row['scope']}|{row['difference_per1000']}|{row['task_cluster_bootstrap95_CI']}|{row['both_complete']}|"
        )
    for arm, row in arms.items():
        lines += [
            "",
            f"{arm}：统计同方向存活{row['statistical_survivors']}；完整规则有效{row['full_rule_valid_survivors']}；Sol检查完成{row['Sol_complete_survivors']}。已知原生持续/原生参考同分布的阳性：{row['known_null_native_persistent_cases']}，保留原始计数但不当作真实效应证据。",
        ]
    lines += [
        "",
        "搜索全部完成前，不从不同完成进度推断效率优劣。两次连续401触发跨控制器停止文件；停止后不再发新请求，已在途请求保留账本。",
        "",
        "## 当前两项回答",
        "",
    ]
    harmful = [r for r in labels["cases"] if r["direction"] == "harmful" and r["valid"]]
    count = collections.Counter(r["style"] for r in harmful)
    lines += [
        f"确认有害案例的规则内/规则外数量：{dict(count)}（完整度{len(labels['cases'])}/15）。这表示规则兼容性，不代表实测原生q概率。",
        "",
        "循环是否更高效：以完成的独立复测和相同完整预算为依据；未齐全时暂不下结论。",
    ]
    if len(arms) == 5 and all(r["complete"] for r in arms.values()):
        lines += ["", "完整比较的回答（以单元去重、实际计入预算的成本为分母）："]
        for row in paired_efficiency(arms)["comparisons"]:
            ci = row["task_cluster_bootstrap95_CI"]
            reading = (
                "区间跨0，尚不能判定效率改善"
                if not ci or ci[0] <= 0 <= ci[1]
                else (
                    "区间全为正，当前样本支持前臂效率更高"
                    if ci[0] > 0
                    else "区间全为负，当前样本支持前臂效率更低"
                )
            )
            lines.append(
                f"{row['scope']}，{row['contrast']}：效率差{row['difference_per1000']}，95%CI {ci}；{reading}。"
            )
        lines += [
            "",
            "这些均是探索性未校正比较；规则内表示原生规则兼容，不表示已测得原生生成概率。已知同分布比较的阳性单列，其个例不能作为伙伴效应证据。",
        ]
    if any(case_cards.values()):
        lines += ["", "## 搜索案例卡（程序提取，无新增模型总结）", ""]
        for arm, rows in case_cards.items():
            lines.append(
                f"### {arm}：{len(rows)}个案例卡"
                + ("（少于3个已验证案例）" if len(rows) < 3 else "")
            )
            lines.append("")
            for row in rows:
                lines += [
                    f"**{row['candidate_id']} — {row['class']} / {row['style']}**",
                    "",
                    f"Agent前一请求：{row['agent_request']}",
                    f"伙伴分支回复：{row['example_branch_text']}；已执行用户工具：{row['executed_branch_user_tools']}。",
                    f"干预单位：{row['intervention']}。",
                    f"复测固定/候选成功{row['fixed_successes']}/16，原生参考{row['native_successes']}/16；差{row['shift']}，95%CI {row['CI']}。",
                    f"失败方向的下一Agent动作类型：{row['first_agent_action_types_in_failing_direction']}；未满足断言计数：{row['unmet_assertion_counts']}。",
                    f"Sol检查完成：{row['Sol_check_complete']}；分支DB改变：{row['DB_changed']}。这些是执行路径描述，不作意图或唯一因果机制断言。",
                    "",
                ]
    for scope in ["all_valid", "in_rule"]:
        figure = c.D["step3"] / f"verified_curve_{scope}.png"
        if figure.exists():
            lines += [
                "",
                f"![{scope}累计验证模式](../{figure.parent.name}/{figure.name})",
                "",
            ]
    if (c.OUT / "balance_stop.json").exists():
        lines += [
            "",
            "## 当前停止原因",
            "",
            "五臂均未完成，没有已完成独立复测或verified案例，不能用0值比较算法效率。A0/A2曾收到空用户回复，A1/A4曾收到规则覆盖不完整的模型标签；已离线修补其拒绝/重试处理。A3账本确认Luna与Sol均返回Insufficient account balance，已停止所有新模型请求；余额恢复前不会自动重启。所有已完成轨迹、原始失败账本与调用成本保留，300条轨迹标签和15例离线比例表已完成。",
        ]
    incident = c.D["step3"] / "transfer_bug_costs.json"
    if incident.exists():
        bug = c.read(incident)
        lines += [
            "",
            "## 实现问题与恢复",
            "",
            f"条件性‘我可以转人工’曾被宽泛regex误判成强制转接；审计392次A1错误拒绝，未发现受影响的已接受回复，A0审计无同类影响。修正为明确肯定的转接公告，排除条件、提议、否定；6项回归测试通过。窄口径错误循环成本：{bug['identified_bug_call_count']}次调用、返回{bug['returned_tokens']}tokens、未知预留{bug['unknown_reserved_tokens']}tokens。全部保留并计入同一臂预算；已完成结果复用，未完成续写的伙伴缓存归档后重跑。比较涉及实现修复开销，需结合该项成本解读，不把浪费隐藏为零。",
        ]
    prevalence = c.D["step2"] / "native_behavior_prevalence_20261006" / "per_case.json"
    if prevalence.exists():
        lines += [
            "",
            "## 确认案例的原生同类行为比例（离线）",
            "",
            "复用冻结E1行为两轴标签，Sol主表、Luna对照；同状态6次原生回复，零新增模型调用。不是24次续写；独立16次原生参考另给机械工具序列比例，不冒充模型行为标签。",
            "",
            "|案例|状态|Sol独立同类/n|95%CI|Luna独立同类/n|",
            "|---|---|---|---|---|",
        ]
        for row in c.read(prevalence)["cases"]:
            sol = row["model_labels"]["gpt-5.6-sol"]["leave_candidate_out"]
            luna = row["model_labels"]["gpt-5.6-luna"]["leave_candidate_out"]
            lines.append(
                f"|{row['candidate_id']}|{row['state_id']}|{sol['matches']}/{sol['draws']}|{sol['Wilson95_CI']}|{luna['matches']}/{luna['draws']}|"
            )
        lines += [
            "",
            "[完整离线表、工具序列和s030文本特征](../v7_c2_step2_20261006_r2/native_behavior_prevalence_20261006/report.md)。0/6并不等于不可能；标签是粗粒度模型判断，共享标签不证明共享因果机制。候选来自原生q时，完整JSON另报去掉自身的比例。",
        ]
    usage = {step: request_accounting(c.D[step]) for step in ["step1", "step2"]}
    c.save(
        c.OUT / "model_role_accounting.json",
        {
            "steps": usage,
            "arms": {a: r["model_role_accounting"] for a, r in arms.items()},
        },
    )
    lines += [
        "",
        "## 模型调用与用量",
        "",
        "|范围|角色|请求模型|返回模型|响应数|返回tokens|未知/在途|",
        "|---|---|---|---|---|---|---|",
    ]
    for step, rows in list(usage.items()) + [
        (a, r["model_role_accounting"]) for a, r in arms.items()
    ]:
        for row in rows:
            lines.append(
                f"|{step}|{row['role']}|{row['requested_model']}|{row['returned_model']}|{row['responses']}|{row['returned_tokens']}|{row['unknown_or_inflight']}|"
            )
    lines += [
        "",
        "未知或已中断请求不按零成本处理；搜索预算另以输入加最大输出预留量计入，历史标注的未知量保留原始账本。",
    ]
    (c.OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(
        "REPORT",
        len(labels["cases"]),
        labels["sampled_trajectories_complete"],
        list(arms),
        flush=True,
    )


if __name__ == "__main__":
    report()
