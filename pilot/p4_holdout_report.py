"""Report held-out screen calibration with explicit unresolved-reference bounds."""

import collections
import csv
import html
import random
import re

import p4_holdout as h


def write_csv(name, rows):
    """Write a deterministic inspectable table."""
    if rows:
        with (h.OUT / name).open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def metrics(rows, populations, unknown_value):
    """Compute stratum-weighted candidate estimates, never verified-failure counts."""
    rates = {}
    for group in populations:
        selected = [r for r in rows if r["stratum"] == group]
        values = [
            int(r["C_candidate"]) if r["C_candidate"] is not None else unknown_value
            for r in selected
        ]
        rates[group] = sum(values) / len(values)
    hit_C = populations["screen_hit"] * rates["screen_hit"]
    missed_C = populations["screen_nonhit"] * rates["screen_nonhit"]
    prevalence = (hit_C + missed_C) / sum(populations.values())
    return {
        "candidate_precision": rates["screen_hit"],
        "weighted_C_candidate_miss_fraction": missed_C / (hit_C + missed_C)
        if hit_C + missed_C
        else 0,
        "weighted_random_failure_C_yield": prevalence,
        "relative_review_count_reduction_proxy": 1 - prevalence / rates["screen_hit"]
        if rates["screen_hit"]
        else None,
    }


def clustered_bootstrap(rows, populations):
    """Explore task-cluster uncertainty within each sampled screen stratum."""
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        groups[row["stratum"]][row["task_id"]].append(row)
    rng = random.Random(2026100305)
    values = collections.defaultdict(list)
    for _ in range(5000):
        sampled = []
        for tasks in groups.values():
            clusters = list(tasks.values())
            sampled.extend(
                r for cluster in rng.choices(clusters, k=len(clusters)) for r in cluster
            )
        for unknown in [0, 1]:
            for key, value in metrics(sampled, populations, unknown).items():
                if value is not None:
                    values[(unknown, key)].append(value)
    intervals = {}
    for (unknown, key), draws in values.items():
        draws.sort()
        intervals.setdefault(key, {})[f"unknown_as_{unknown}"] = [
            draws[int(0.025 * (len(draws) - 1))],
            draws[int(0.975 * (len(draws) - 1))],
        ]
    return {
        "iterations": 5000,
        "seed": 2026100305,
        "intervals": intervals,
        "limit": "Exploratory conditional task-cluster bootstrap within strata; not a design-exact confidence interval or independent human validation. Null candidate labels get separate sensitivity scenarios, never silently negatives.",
    }


def termination_audit(items):
    """Separate transfer-marker-before-tool hits from their observable context."""
    result = []
    for item in items:
        sim = h.p4.read(h.OUT / "sources" / (item["sample_id"] + ".json"))
        transferred = False
        announcements = []
        for index, message in enumerate(sim["messages"]):
            if message["role"] == "assistant":
                transferred |= any(
                    t["name"] == "transfer_to_human_agents"
                    for t in message.get("tool_calls") or []
                )
                if re.search(
                    r"being transferred|you are.{0,40}transfer|transferring you",
                    message.get("content") or "",
                    re.I,
                ):
                    announcements.append(index)
            if (
                message["role"] == "user"
                and "###TRANSFER###" in (message.get("content") or "")
                and not transferred
            ):
                result.append(
                    {
                        "sample_id": item["sample_id"],
                        "marker_index": index,
                        "prior_agent_transfer_announcement": bool(announcements),
                        "announcement_indices": announcements,
                        "interpretation": "Marker precedes formal agent transfer tool. User guidelines permit marker after clear agent transfer announcement; this alone is not a simulator-error diagnosis.",
                    }
                )
    h.p4.save(
        h.OUT / "termination_audit.json",
        {
            "events": result,
            "guideline": "data/tau2/user_simulator/simulation_guidelines_tools.md:27",
        },
    )
    return result


def main():
    """Export counts, missingness, conditional yield, budgets and interpretation."""
    h.activate()
    h.verify_frozen()
    sample = h.p4.read(h.OUT / "sample.json")
    items = {i["sample_id"]: i for i in sample["items"]}
    references = h.p4.read(h.OUT / "assistant_reference.json")["entries"]
    review_groups = {}
    for folder in ["reviews", "independent_reviews"]:
        review_groups[folder] = {
            p.stem: h.p4.read(p) for p in (h.OUT / folder).glob("*.json")
        }
    rows = []
    for ref in references:
        item = items[ref["sample_id"]]
        row = {
            "sample_id": ref["sample_id"],
            "episode_id": ref["episode_id"],
            "task_id": item["task_id"],
            "stratum": item["stratum"],
            "C_candidate": ref["C_candidate"],
            "reference_reason": ref["reason"],
        }
        for folder in review_groups:
            review = review_groups[folder].get(ref["sample_id"], {})
            row[folder + "_status"] = review.get("status", "pending")
            row[folder + "_label"] = review.get("label", {}).get(
                "category", "unresolved"
            )
        rows.append(row)
    write_csv("panel_audit.csv", rows)
    populations = {
        group: meta["population"] for group, meta in sample["strata"].items()
    }
    by_stratum = []
    for group in populations:
        selected = [r for r in rows if r["stratum"] == group]
        by_stratum.append(
            {
                "stratum": group,
                "population": populations[group],
                "first_review_sample": 24,
                "reference_sample": len(selected),
                "C_candidates": sum(r["C_candidate"] is True for r in selected),
                "non_C": sum(r["C_candidate"] is False for r in selected),
                "unresolved": sum(r["C_candidate"] is None for r in selected),
            }
        )
    reviewer_diagnostics = {}
    for folder, reviews in review_groups.items():
        scored = [
            r
            for r in rows
            if r["C_candidate"] is not None and r[folder + "_status"] == "ok"
        ]
        predicted_C = [r for r in scored if r[folder + "_label"] == "C"]
        false_C = [r["sample_id"] for r in predicted_C if r["C_candidate"] is False]
        missed_C = [
            r["sample_id"]
            for r in scored
            if r["C_candidate"] is True and r[folder + "_label"] != "C"
        ]
        unresolved = [r["sample_id"] for r in rows if r[folder + "_status"] != "ok"]
        reviewer_diagnostics[folder] = {
            "observed": len(reviews),
            "status": dict(collections.Counter(r["status"] for r in reviews.values())),
            "grounded_review_coverage": sum(
                r["status"] == "ok" for r in reviews.values()
            )
            / len(reviews)
            if reviews
            else None,
            "scored_resolved_reference_reviews": len(scored),
            "predicted_C_in_scored_panel": len(predicted_C),
            "supported_C_in_scored_panel": len(predicted_C) - len(false_C),
            "candidate_precision_on_scored_panel": (len(predicted_C) - len(false_C))
            / len(predicted_C)
            if predicted_C
            else None,
            "false_C_ids": false_C,
            "missed_C_ids": missed_C,
            "unresolved_review_ids": unresolved,
            "limit": "Syntactically grounded output remains semantically fallible. Missing/error/rejected reviews not treated as negatives; scoring uses coding-assistant candidate reference, not human gold.",
        }
    calls = [h.p4.read(p) for p in (h.OUT / "requests").glob("*.json")]
    cost = collections.defaultdict(
        lambda: {"requests": 0, "known_tokens": 0, "unknown_usage_requests": 0}
    )
    cost_rows = []
    for call in calls:
        folder, sid = call["unit"].split(":", 1)
        group = cost[folder]
        group["requests"] += 1
        usage = call.get("usage")
        tokens = (
            usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            if usage is not None
            else None
        )
        if tokens is None:
            group["unknown_usage_requests"] += 1
        else:
            group["known_tokens"] += tokens
        cost_rows.append(
            {
                "request_id": call["id"],
                "phase": folder,
                "sample_id": sid,
                "stratum": items[sid]["stratum"],
                "key_index": call["key_index"],
                "status": call["status"],
                "known_tokens": tokens,
            }
        )
    write_csv("request_costs.csv", cost_rows)
    report = {
        "independent_failure_sources": 48,
        "excluded_continuation_tasks": 11,
        "residual_population": sum(populations.values()),
        "reference_panel": 24,
        "stratum_outcomes": by_stratum,
        "candidate_estimates": {
            "unknown_as_0": metrics(rows, populations, 0),
            "unknown_as_1": metrics(rows, populations, 1),
        },
        "uncertainty": clustered_bootstrap(rows, populations),
        "screen_kept_population_fraction": populations["screen_hit"]
        / sum(populations.values()),
        "reviewer_diagnostics": reviewer_diagnostics,
        "termination_events": termination_audit(list(items.values())),
        "request_accounting": dict(cost),
        "known_tokens": sum(v["known_tokens"] for v in cost.values()),
        "provider_metadata": {
            "returned_models": dict(
                collections.Counter(
                    call.get("returned_model", "unreported") for call in calls
                )
            ),
            "requests_reporting_positive_reasoning_tokens": sum(
                (
                    (
                        (call.get("usage") or {}).get("completion_tokens_details") or {}
                    ).get("reasoning_tokens")
                    or 0
                )
                > 0
                for call in calls
            ),
            "limit": "Configured reasoning_effort=none is not a guarantee of absent internal reasoning; preserve actual provider usage and returned model metadata.",
        },
        "unknown_usage_requests": sum(
            v["unknown_usage_requests"] for v in cost.values()
        ),
        "interpretation": "Screen candidate precision and miss fraction meet point-estimate development targets in this independent panel, but the automated reviewer grounding/consistency target fails. Only coding-assistant reference is available; G1 not passed. Screen hits cover most remaining failures, so simple review-count savings are modest. No discovery-efficiency claim.",
        "limits": "Reference panel is binary phone/diagnostic C classification, not exhaustive A/B/other diagnosis. Payment capability omission is an adjacent candidate kept outside frozen C. One ambiguous unavailable-device-action statement remains null. New API token costs exclude old source generation, coding-assistant compute, human review time and billing uncertainty. Prospective targets are developmental; no automatic confirmatory gate passage.",
    }
    h.p4.save(h.OUT / "analysis.json", report)
    table = "".join(
        f"<tr><td>{r['stratum']}</td><td>{r['population']}</td><td>{r['reference_sample']}</td><td>{r['C_candidates']}</td><td>{r['non_C']}</td><td>{r['unresolved']}</td></tr>"
        for r in by_stratum
    )
    reviewer_table = "".join(
        f"<tr><td>{name}</td><td>{r['observed']}</td><td>{html.escape(str(r['status']))}</td><td>{r['grounded_review_coverage']:.1%}</td><td>{r['supported_C_in_scored_panel']}/{r['predicted_C_in_scored_panel']}</td></tr>"
        for name, r in reviewer_diagnostics.items()
        if r["grounded_review_coverage"] is not None
    )
    low, high = (
        report["candidate_estimates"]["unknown_as_0"],
        report["candidate_estimates"]["unknown_as_1"],
    )
    document = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 新版筛子独立留出验证</title><style>body{{font:16px/1.7 system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#17223b}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d7deea;padding:10px;text-align:left}}th{{background:#edf2fa}}.note{{background:#fff3d7;padding:16px}}</style><h1>P4 新版筛子独立留出验证</h1>
<p>在 API 请求前冻结筛子、判据与抽样。排除前两批已审阅轨迹及 11 个对照任务后，残余 iid 失败池为 526 条：命中 433 条、未命中 93 条；各抽 24 条，共 48 条。预先从两组各选 12 条接受第二模型审阅和编码助手候选复核。所有模型输入隐藏 reward、分层、旧标签、任务答案与用户工具原始输出。</p>
<h2>独立候选参考</h2><table><tr><th>组</th><th>残余总体</th><th>参考样本</th><th>C 候选</th><th>非 C</th><th>未解决</th></tr>{table}</table>
<p>编码助手在查看本批 API 标签之前，使用打乱后的匿名可见对话完成二元 C 候选裁决；知道该批来自失败轨迹。不是独立人工真值。非 C 不代表不存在 A/B 或其他失败。严格手机/诊断 C 范围没有因支付委托候选而事后扩大。</p>
<p>候选精度点估计 {low["candidate_precision"]:.1%}；加权 C 候选漏检比例为 {low["weighted_C_candidate_miss_fraction"]:.1%}–{high["weighted_C_candidate_miss_fraction"]:.1%}，区间端点对应将唯一未解决项分别视为非 C/C，属于敏感性范围而非置信区间。analysis.json 另报任务聚类 bootstrap 的条件不确定性。不能直接外推全 benchmark 或称作经验证失败的召回率。</p>
<h2>自动审阅可靠性</h2><table><tr><th>审阅阶段</th><th>记录数</th><th>状态</th><th>结构有效率</th><th>参考面板内支持的 C / 输出 C</th></tr>{reviewer_table}</table>
<p>索引定位减少自由引用错误，但模型仍把一般提前转人工标成 C，有时解释中已经承认 C 缺少证据。冻结的结构检查也会把不相关的“cannot send MMS”与后文“diagnostics needed”误当同一个能力否定，或漏掉“do not provide device diagnostics”的真实表达。本批保留冻结版，不据此改规则重新评分；错误记录用于下一版开发。被拒证书、接口错误与缺失标注均保留为未解决。</p>
<h2>验证成本与其他候选</h2><p>筛子保留 {report["screen_kept_population_fraction"]:.1%} 的残余失败，最多仅直接排除其余部分。按等复核成本的候选产率估算，所需复核条数的下降代理值为 {low["relative_review_count_reduction_proxy"]:.1%}–{high["relative_review_count_reduction_proxy"]:.1%}；这不含轨迹生成、人工、反事实确认成本，不能作为每个经验证失败的成本。</p>
<p>h029：缺少支付工具而未指导用户付款，属于相邻伙伴能力候选，未并入手机 C。h025：agent 未调用转人工工具，却在回复里宣布转人工，随后 user 输出 TRANSFER；用户指南允许在明确被告知转人工后输出该标记，因此“早于工具调用”本身不足以判为 simulator 错误。h045：明确的 device diagnostics 缺失表述被词法筛子漏掉。</p>
<p>本批已记录新 API tokens {report["known_tokens"]:,}；{report["unknown_usage_requests"]} 个请求 usage 未知，保留一次显式接口恢复的全部尝试。旧源轨迹生成、编码助手计算和人工时间未计入此数。</p>
<p class="note">G1 尚未通过。候选筛选的独立点估计有价值，但自动审阅的结构有效率与语义一致性不足，人工裁决与竞争解释验证尚缺。下一步先改进判据一致性检查并补人工裁决，冻结失败确认与去重协议，再比较 iid / 随机分支 / 自适应分支的等预算发现曲线。</p>
<p><a href="analysis.json">完整分析</a> · <a href="panel_audit.csv">24 条参考与模型输出</a> · <a href="assistant_reference.json">候选裁决依据</a> · <a href="protocol.json">冻结协议与筛子代码</a> · <a href="request_costs.csv">请求成本</a> · <a href="termination_audit.json">终止过程检查</a></p></html>"""
    (h.OUT / "report.html").write_text(document)
    print(
        {
            "strata": by_stratum,
            "estimates": report["candidate_estimates"],
            "reviewers": {k: v["status"] for k, v in reviewer_diagnostics.items()},
            "known_tokens": report["known_tokens"],
            "unknown_usage": report["unknown_usage_requests"],
        }
    )


if __name__ == "__main__":
    main()
