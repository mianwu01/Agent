"""Export P4 exploratory diagnosis outcomes, task-cluster uncertainty and HTML."""

import collections
import csv
import html
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pilot/runs/p4/diagnosis_20261003"
ARMS = ["resample", "fixed_original", "fixed_corrected"]
ARM_NAMES = {
    "resample": "自然重采样",
    "fixed_original": "固定原决策",
    "fixed_corrected": "固定修正决策",
}


def read(path):
    """Read a JSON artifact."""
    return json.loads(Path(path).read_text())


def write_csv(path, rows):
    """Write a compact table with deterministic column order."""
    if rows:
        with Path(path).open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def quantile(values, p):
    """Use the conservative empirical order statistic for bootstrap bounds."""
    return sorted(values)[int(p * (len(values) - 1))]


def paired_bootstrap(rows, left, right):
    """Resample tasks and independent suffixes; label small-panel limits explicitly."""
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        if row["status"] == "completed":
            groups[row["sample_id"]][row["arm"]].append(int(row["reward"] == 1))
    pairs = [g for g in groups.values() if g[left] and g[right]]
    if not pairs:
        return None
    point = sum(
        sum(g[right]) / len(g[right]) - sum(g[left]) / len(g[left]) for g in pairs
    ) / len(pairs)
    rng = random.Random(20261003)
    estimates = []
    for _ in range(10000):
        selected = rng.choices(pairs, k=len(pairs))
        value = 0.0
        for g in selected:
            a = rng.choices(g[left], k=len(g[left]))
            b = rng.choices(g[right], k=len(g[right]))
            value += sum(b) / len(b) - sum(a) / len(a)
        estimates.append(value / len(selected))
    return {
        "contrast": right + " minus " + left,
        "task_equal_weighted_difference": point,
        "bootstrap_95_interval": [
            quantile(estimates, 0.025),
            quantile(estimates, 0.975),
        ],
        "tasks": len(pairs),
        "iterations": 10000,
        "limit": "Selected tiny exploratory panel; conditional uncertainty, not population inference or confirmatory significance",
    }


def main():
    """Generate reproducible tables and a self-contained report without model calls."""
    cases = read(OUT / "approved_cases.json")["cases"]
    rows = [read(p) for p in sorted((OUT / "continuations").glob("*.json"))]
    detailed = []
    for row in rows:
        if row["status"] != "completed":
            continue
        decision = next(
            c["decision_index"] for c in cases if c["sample_id"] == row["sample_id"]
        )
        suffix = row["simulation"]["messages"][decision:]
        user_actions = [
            t["name"]
            for m in suffix
            if m["role"] == "user"
            for t in m.get("tool_calls") or []
        ]
        device_actions = [
            t
            for t in user_actions
            if t not in {"make_payment", "check_payment_request"}
        ]
        transfers = sum(
            t["name"] == "transfer_to_human_agents"
            for m in suffix
            if m["role"] == "assistant"
            for t in m.get("tool_calls") or []
        )
        detailed.append(
            {
                "unit": row["unit"],
                "sample_id": row["sample_id"],
                "category": row["category"],
                "arm": row["arm"],
                "success": int(row["reward"] == 1),
                "device_tool_calls": len(device_actions),
                "any_device_action": int(bool(device_actions)),
                "transfer_calls": transfers,
                "termination": row["simulation"]["termination_reason"],
                "live_state_checks": len(row["state_trace"]),
            }
        )
    write_csv(OUT / "mechanism_outcomes.csv", detailed)
    arm_rows = []
    for arm in ARMS:
        planned = [r for r in rows if r["arm"] == arm]
        done = [r for r in detailed if r["arm"] == arm]
        arm_rows.append(
            {
                "arm": arm,
                "planned": 8 * len(cases),
                "observed_units": len(planned),
                "completed": len(done),
                "errors": sum(r["status"] == "error" for r in planned),
                "pending": sum(r["status"] == "started" for r in planned),
                "successes": sum(r["success"] for r in done),
                "success_rate": sum(r["success"] for r in done) / len(done)
                if done
                else None,
                "with_device_action": sum(r["any_device_action"] for r in done),
            }
        )
    write_csv(OUT / "arm_outcomes.csv", arm_rows)
    category_rows = []
    for category in sorted({c["category"] for c in cases}):
        for arm in ARMS:
            done = [
                r for r in detailed if r["category"] == category and r["arm"] == arm
            ]
            category_rows.append(
                {
                    "category": category,
                    "arm": arm,
                    "completed": len(done),
                    "successes": sum(r["success"] for r in done),
                    "success_rate": sum(r["success"] for r in done) / len(done)
                    if done
                    else None,
                    "failed_with_transfer": sum(
                        not r["success"] and r["transfer_calls"] > 0 for r in done
                    ),
                }
            )
    write_csv(OUT / "category_outcomes.csv", category_rows)
    first = [read(p) for p in (OUT / "reviews").glob("*.json")]
    second = [read(p) for p in (OUT / "independent_reviews").glob("*.json")]
    sample = read(OUT / "sample.json")
    strata = []
    first_by_id = {r["sample_id"]: r for r in first}
    for group, counts in sample["strata"].items():
        selected = [i for i in sample["items"] if i["stratum"] == group]
        labels = collections.Counter(
            first_by_id[i["sample_id"]]
            .get("label", {})
            .get("category", "annotation_error")
            for i in selected
        )
        strata.append(
            {
                "stratum": group,
                **counts,
                **{
                    k: labels[k]
                    for k in [
                        "A",
                        "B",
                        "C",
                        "other",
                        "none",
                        "uncertain",
                        "annotation_error",
                    ]
                },
            }
        )
    write_csv(OUT / "screening_strata.csv", strata)
    calls = [read(p) for p in (OUT / "requests").glob("*.json")]
    accounting = collections.defaultdict(
        lambda: {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "unknown_usage_requests": 0,
            "elapsed_seconds": 0.0,
        }
    )
    for call in calls:
        phase = (
            call["unit"].split(":")[0]
            if call["role"] in {"judge", "diagnostic"}
            else "continuations"
        )
        group = (phase, call["role"], call["key_index"])
        tally = accounting[group]
        tally["requests"] += 1
        tally["elapsed_seconds"] += call.get("seconds", 0)
        usage = call.get("usage")
        if usage is None:
            tally["unknown_usage_requests"] += 1
        else:
            tally["prompt_tokens"] += usage.get("prompt_tokens", 0)
            tally["completion_tokens"] += usage.get("completion_tokens", 0)
    cost_rows = [
        {"phase": p, "role": r, "key_index": k, **v}
        for (p, r, k), v in sorted(accounting.items())
    ]
    write_csv(OUT / "request_costs.csv", cost_rows)
    total_tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in cost_rows)
    unknown = sum(r["unknown_usage_requests"] for r in cost_rows)
    report = {
        "case_count": len(cases),
        "completed": len(detailed),
        "expected": 24 * len(cases),
        "arm_outcomes": arm_rows,
        "category_outcomes": category_rows,
        "first_review": {
            "total": len(first),
            "status": dict(collections.Counter(r["status"] for r in first)),
            "provisional_labels": dict(
                collections.Counter(
                    r["label"]["category"] for r in first if r["status"] == "ok"
                )
            ),
        },
        "independent_review": {
            "total": len(second),
            "status": dict(collections.Counter(r["status"] for r in second)),
        },
        "contrasts": [
            paired_bootstrap(rows, "fixed_original", "fixed_corrected"),
            paired_bootstrap(rows, "resample", "fixed_corrected"),
        ],
        "known_response_tokens": total_tokens,
        "requests_with_unknown_usage": unknown,
        "cost_note": "Includes probes, format-rejected requests, diagnostic replay, explicit recoveries and abandoned proposals; billed usage and dollar cost are not verified.",
        "claims_limit": "Seven selected prefixes and one API agent/simulator configuration. Model-review agreement is not human annotation. Positive interventions do not by themselves isolate partner modeling from policy comprehension. Discovery efficiency has not been tested.",
    }
    (OUT / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    table = "".join(
        f"<tr><td>{ARM_NAMES[r['arm']]}</td><td>{r['completed']}/{r['planned']}</td><td>{r['successes']}</td><td>{r['success_rate']:.1%}</td><td>{r['with_device_action']}</td><td>{r['errors']}</td></tr>"
        for r in arm_rows
        if r["success_rate"] is not None
    )
    descriptions = "".join(
        f"<tr><td>{c['sample_id']}</td><td>{html.escape(c['category'])}</td><td>{html.escape(c['task_id'])}</td><td>{html.escape(c['proposal']['response_text'])}</td></tr>"
        for c in cases
    )
    category_table = "".join(
        f"<tr><td>{html.escape(r['category'])}</td><td>{ARM_NAMES[r['arm']]}</td><td>{r['successes']}/{r['completed']}</td><td>{r['failed_with_transfer']}</td></tr>"
        for r in category_rows
    )
    document = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 首轮交互失败诊断结果</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#17223b}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #d7deea;padding:10px;text-align:left;vertical-align:top}}th{{background:#edf2fa}}.note{{background:#fff3d7;padding:16px}}code{{background:#eef2f7}}a{{color:#275ac7}}</style>
<h1>P4 首轮交互失败诊断结果</h1><p>本批实验检查旧轨迹中提前转人工的候选机制。{len(cases)} 个不同任务的前缀，每个条件计划 8 次续写，共 {24 * len(cases)} 次；当前完成 {len(detailed)} 次。agent 和 user 均为 Luna，temperature=1.0，reasoning_effort=none。</p>
<h2>对照结果</h2><table><tr><th>条件</th><th>完成/计划</th><th>成功数</th><th>成功率</th><th>执行设备动作的续写数</th><th>接口或执行错误</th></tr>{table}</table>
<p>自然重采样重新生成下一轮 agent 决策；固定原决策执行原轨迹中的下一轮回复；固定修正决策仅替换这一轮，后续恢复原 agent。修正使用已有 policy 和当时可见信息，不注入隐藏状态或正确答案。两侧数据库初始哈希一致，并记录每步运行时哈希。完整任务按原始 evaluator 和 reward_basis 评估。</p>
<h2>分类结果与复发线索</h2><table><tr><th>候选类别</th><th>条件</th><th>成功/完成</th><th>失败且转人工</th></tr>{category_table}</table>
<p>必须将六个明确以工具不可用为理由的 C 候选与 s013 的一般提前转人工分开解读。整体差异不能替代 C 类别的差异。转人工计数只是可观察动作，不自动等于该机制复发，也不构成独立验证。</p>
<p>逐轨迹检查发现：s005:fixed_corrected:0 在改好网络模式后再次转人工，仍未检查 VPN 与 Data Saver；s015:fixed_corrected:0 已指导开启数据、切换网络及断开 VPN，却声称自己没有测速工具，随后转人工；s017:fixed_corrected:0 查询到 VPN 性能差后，以自己没有 disconnect_vpn 工具为由转人工。这些实例支持下一步检验持续的用户侧操作委托，而不是仅修正一个决策。三例是事后描述性观察，尚未完成完整竞争解释排除。</p>
<h2>候选与修正</h2><table><tr><th>实例</th><th>候选类别</th><th>任务</th><th>固定修正回复</th></tr>{descriptions}</table>
<h2>审阅与成本</h2><p>按五个层各抽 24 条，共 120 条旧轨迹，记录抽样概率。第一审阅者为 Luna，第二审阅者为 Sol，均隐藏 reward、抽样层、用户工具原始输出和任务答案。编码助手进一步检查入选实例；没有声称人工双人标注已完成。六个实例包含明确的设备工具不可用理由，s013 缺少该明确理由，单列为一般提前转人工。</p>
<p>已记录响应 token 共 {total_tokens:,}；{unknown} 个请求没有可核实 usage，不能按零计费。计入探测、被拒请求、恢复请求及未采用的修正提议。此数字不是完整账单。</p>
<h2>结论边界与下一步</h2><p class="note">本批是探索性选定前缀实验。正向对照差异可支持继续诊断该交互过程，尚不能单独证明伙伴建模机制，也不能证明自适应搜索优于随机分支。A/B 标签存在过宽情况，未据此宣布发现新的模式。正式搜索需要独立实例确认、校准判据、冻结去重与预算规则；修复泛化和其他 reasoning 设置尚未验证。</p>
<p>数据：<a href="analysis.json">分析 JSON</a> · <a href="case_outcomes.csv">逐实例对照</a> · <a href="category_outcomes.csv">分类对照</a> · <a href="mechanism_outcomes.csv">逐续写机制指标</a> · <a href="request_costs.csv">请求成本</a> · <a href="protocol.json">协议</a> · <a href="approved_cases.json">实例与信息匹配修正</a> · <a href="screening_strata.csv">抽样层及候选标签</a></p></html>"""
    (OUT / "report.html").write_text(document)
    print(
        json.dumps(
            {
                "completed": len(detailed),
                "expected": 24 * len(cases),
                "arms": arm_rows,
                "known_tokens": total_tokens,
                "unknown_usage": unknown,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
