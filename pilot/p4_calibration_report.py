"""Revalidate P4 certificates and export explicitly provisional calibration results."""

import collections
import csv
import html
import json
import re

import p4_calibration as c
from p4_analyze import paired_bootstrap

from tau2.data_model.tasks import Task


def capability_screen(sim):
    """Screen explicit device capability denials; never assign a causal label."""
    for message in sim["messages"]:
        if message["role"] != "assistant":
            continue
        text = (
            (message.get("content") or "")
            + " "
            + json.dumps(message.get("tool_calls") or [], ensure_ascii=False)
        )
        device = re.search(
            r"device|diagnostic|phone|MMS|speed.?test|network.mode|airplane|VPN|APN|data.saver|permission",
            text,
            re.I,
        )
        tool_denial = re.search(
            r"(?:tool|function|diagnostic).{0,120}(?:unavailable|not available|cannot|not include)|"
            r"(?:unavailable|not available|lack|not include|no ).{0,120}(?:tool|function|diagnostic)",
            text,
            re.I,
        )
        if device and tool_denial:
            return True
    return False


def early_user_transfer(sim):
    """Detect the known simulator transfer marker before agent transfer action."""
    transferred = False
    for message in sim["messages"]:
        if message["role"] == "assistant":
            transferred |= any(
                t["name"] == "transfer_to_human_agents"
                for t in message.get("tool_calls") or []
            )
        if (
            message["role"] == "user"
            and "###TRANSFER###" in (message.get("content") or "")
            and not transferred
        ):
            return True
    return False


def write_csv(name, rows):
    """Write a stable, inspectable CSV artifact."""
    if rows:
        with (c.OUT / name).open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def revalidate(items, folder):
    """Apply the same version-two structural criteria to both raw reviewers."""
    tasks = c.p4.read(c.OUT / "tasks.json")
    results = []
    for item in items:
        path = c.OUT / folder / (item["sample_id"] + ".json")
        if not path.exists():
            continue
        original = c.p4.read(path)
        row = {"sample_id": item["sample_id"], "raw_status": original["status"]}
        raw = original.get("raw_label")
        if raw is None:
            row.update(status="provider_error", reason=original.get("reason"))
        else:
            sim = c.p4.read(c.OUT / "sources" / (item["sample_id"] + ".json"))
            task = Task.model_validate(tasks[item["task_id"]])
            orch = c.NATIVE_BUILDER(c.p4.config(), task)
            try:
                label = c.strict_certificate(
                    raw, c.p4.agent_view(sim["messages"]), orch.agent.domain_policy
                )
                row.update(status="grounded_candidate_review", label=label)
            except (KeyError, TypeError, ValueError) as exc:
                row.update(status="certificate_rejected", reason=str(exc))
        results.append(row)
    c.p4.save(c.OUT / (folder + "_validated.json"), results)
    return results


def main():
    """Produce calibration diagnostics and a conditional continuation comparison."""
    c.activate()
    sample = c.p4.read(c.OUT / "sample.json")
    items = sample["items"]
    first = revalidate(items, "strict_reviews")
    panel = c.p4.read(c.OUT / "review_panel.json")["items"]
    second = revalidate(panel, "independent_reviews")
    references = c.p4.read(c.OUT / "assistant_reference.json")["entries"]
    by_id = {i["sample_id"]: i for i in items}
    first_by_id = {r["sample_id"]: r for r in first}
    second_by_id = {r["sample_id"]: r for r in second}
    audit_rows = []
    for ref in references:
        sid = ref["sample_id"]
        item = by_id[sid]
        sim = c.p4.read(c.OUT / "sources" / (sid + ".json"))
        primary = first_by_id.get(sid, {})
        independent = second_by_id.get(sid, {})
        audit_rows.append(
            {
                "sample_id": sid,
                "task_id": item["task_id"],
                "stratum": item["stratum"],
                "native_success": int(item["recorded_reward"] == 1),
                "assistant_reference": ref["category"],
                "reference_C_candidate": int(ref["category"] == "C"),
                "old_ability_screen": int(c.p4.ability_signal(sim)),
                "revised_capability_screen": int(capability_screen(sim)),
                "known_early_user_transfer": int(early_user_transfer(sim)),
                "first_status": primary.get("status", "pending"),
                "first_label": primary.get("label", {}).get("category", "unresolved"),
                "second_status": independent.get("status", "pending"),
                "second_label": independent.get("label", {}).get(
                    "category", "unresolved"
                ),
                "panel_weight": sample["strata"][item["stratum"]]["population"]
                / sum(i["stratum"] == item["stratum"] for i in panel),
            }
        )
    write_csv("calibration_audit.csv", audit_rows)
    failure_panel = [r for r in audit_rows if not r["native_success"]]
    screening = []
    for screen in ["old_ability_screen", "revised_capability_screen"]:
        hits = [r for r in failure_panel if r[screen]]
        missed = [r for r in failure_panel if not r[screen]]
        weighted_C = sum(
            r["panel_weight"] * r["reference_C_candidate"] for r in failure_panel
        )
        weighted_missed = sum(
            r["panel_weight"] * r["reference_C_candidate"] for r in missed
        )
        screening.append(
            {
                "screen": screen,
                "reviewed_hits": len(hits),
                "C_candidates_in_hits": sum(r["reference_C_candidate"] for r in hits),
                "reviewed_nonhits": len(missed),
                "C_candidates_in_nonhits": sum(
                    r["reference_C_candidate"] for r in missed
                ),
                "weighted_C_candidate_precision": sum(
                    r["panel_weight"] * r["reference_C_candidate"] for r in hits
                )
                / sum(r["panel_weight"] for r in hits)
                if hits
                else None,
                "weighted_fraction_C_candidates_missed": weighted_missed / weighted_C
                if weighted_C
                else None,
                "limit": "Assistant-reference process candidates on 20 reviewed iid failures; small correlated development sample. Revised screen developed after seeing errors, requiring further holdout validation. Not validated-failure precision/recall.",
            }
        )
    calls = [c.p4.read(p) for p in (c.OUT / "requests").glob("*.json")]
    cost_groups = collections.defaultdict(
        lambda: {"requests": 0, "known_tokens": 0, "unknown_usage_requests": 0}
    )
    for call in calls:
        group = cost_groups[call["role"]]
        group["requests"] += 1
        usage = call.get("usage")
        if usage is None:
            group["unknown_usage_requests"] += 1
        else:
            group["known_tokens"] += usage.get("prompt_tokens", 0) + usage.get(
                "completion_tokens", 0
            )
    rows = [c.p4.read(p) for p in (c.OUT / "continuations").glob("*.json")]
    case_path = c.OUT / "approved_cases.json"
    cases = c.p4.read(case_path)["cases"] if case_path.exists() else []
    case_by_id = {case["sample_id"]: case for case in cases}
    mechanism_rows = []
    for row in rows:
        if row["status"] != "completed":
            continue
        suffix = row["simulation"]["messages"][
            case_by_id[row["sample_id"]]["decision_index"] :
        ]
        first_decision = next(m for m in suffix if m["role"] == "assistant")
        transfers = sum(
            t["name"] == "transfer_to_human_agents"
            for m in suffix
            if m["role"] == "assistant"
            for t in m.get("tool_calls") or []
        )
        device_calls = sum(
            t["name"] not in {"make_payment", "check_payment_request"}
            for m in suffix
            if m["role"] == "user"
            for t in m.get("tool_calls") or []
        )
        unmet = [
            check["env_assertion"]["func_name"]
            for check in row["simulation"]["reward_info"].get("env_assertions") or []
            if not check["met"]
        ]
        mechanism_rows.append(
            {
                "unit": row["unit"],
                "sample_id": row["sample_id"],
                "arm": row["arm"],
                "success": int(row["reward"] == 1),
                "first_decision_transfer": int(
                    any(
                        t["name"] == "transfer_to_human_agents"
                        for t in first_decision.get("tool_calls") or []
                    )
                ),
                "transfer_calls": transfers,
                "device_tool_calls": device_calls,
                "suffix_capability_denial_screen": int(
                    capability_screen({"messages": suffix})
                ),
                "unmet_assertions": "|".join(unmet),
            }
        )
    write_csv("continuation_mechanisms.csv", mechanism_rows)
    arm_rows = []
    for arm in c.REMINDERS:
        selected = [r for r in rows if r["arm"] == arm]
        done = [r for r in selected if r["status"] == "completed"]
        arm_rows.append(
            {
                "arm": arm,
                "planned": 8 * len(cases),
                "completed": len(done),
                "errors": sum(r["status"] == "error" for r in selected),
                "pending": sum(r["status"] == "started" for r in selected),
                "successes": sum(r["reward"] == 1 for r in done),
                "success_rate": sum(r["reward"] == 1 for r in done) / len(done)
                if done
                else None,
            }
        )
    write_csv("arm_outcomes.csv", arm_rows)
    case_rows = []
    for case in cases:
        for arm in c.REMINDERS:
            done = [
                r
                for r in rows
                if r["sample_id"] == case["sample_id"]
                and r["arm"] == arm
                and r["status"] == "completed"
            ]
            case_rows.append(
                {
                    "sample_id": case["sample_id"],
                    "arm": arm,
                    "completed": len(done),
                    "successes": sum(r["reward"] == 1 for r in done),
                }
            )
    write_csv("case_outcomes.csv", case_rows)
    report = {
        "reviewed_sources": len(first),
        "review_panel": len(panel),
        "reviewer_status": {
            "first": dict(collections.Counter(r["status"] for r in first)),
            "second": dict(collections.Counter(r["status"] for r in second)),
        },
        "assistant_reference_labels": dict(
            collections.Counter(r["category"] for r in references)
        ),
        "screening": screening,
        "known_early_user_transfer_sources": sum(
            early_user_transfer(
                c.p4.read(c.OUT / "sources" / (i["sample_id"] + ".json"))
            )
            for i in items
        ),
        "native_successes_with_C_process_candidate_in_panel": sum(
            r["native_success"] and r["reference_C_candidate"] for r in audit_rows
        ),
        "arm_outcomes": arm_rows,
        "continuation_process_by_arm": {
            arm: {
                "first_decision_transfers": sum(
                    r["first_decision_transfer"]
                    for r in mechanism_rows
                    if r["arm"] == arm
                ),
                "any_device_action": sum(
                    r["device_tool_calls"] > 0
                    for r in mechanism_rows
                    if r["arm"] == arm
                ),
                "suffix_denial_screen_hits": sum(
                    r["suffix_capability_denial_screen"]
                    for r in mechanism_rows
                    if r["arm"] == arm
                ),
            }
            for arm in c.REMINDERS
        },
        "v006_competing_explanation": {
            "completed": sum(r["sample_id"] == "v006" for r in mechanism_rows),
            "failed_data_refueling_assertion": sum(
                r["sample_id"] == "v006"
                and "assert_data_refueling_amount" in r["unmet_assertions"]
                for r in mechanism_rows
            ),
            "description": "Post-outcome evaluator audit: v006 has an unresolved carrier-side data-refueling requirement, in addition to its explicit unavailable-permissions-tool candidate. The experimenter uses evaluator assertions for diagnosis; no requirement or hidden state was supplied to the generating agent. Delegation reminder alone need not resolve all mixed failures.",
        },
        "contrasts": [
            paired_bootstrap(rows, "generic_policy", "capability_policy"),
            paired_bootstrap(rows, "resample", "capability_policy"),
        ],
        "request_accounting": dict(cost_groups),
        "known_tokens": sum(r["known_tokens"] for r in cost_groups.values()),
        "unknown_usage_requests": sum(
            r["unknown_usage_requests"] for r in cost_groups.values()
        ),
        "gate": "G1 remains unpassed: no human reference, validated-failure cost, full competing-explanation exclusion or independently validated revised-screen recall. G2 not tested.",
        "limits": "Reviews are outcome-blinded; coding-assistant reference is not blinded human truth. Certificates are grounding checks, not semantic/causal proof. Sources and tasks exclude the previous panel; four new cases remain selected, not representative. Persistent reminders also change prompt salience, so a positive contrast is supportive, not definitive partner-modeling isolation. Native reward can mark success despite unresolved visible device complaints. Sunk old rollout cost excluded from new API cost.",
    }
    c.p4.save(c.OUT / "analysis.json", report)
    table = "".join(
        f"<tr><td>{html.escape(r['arm'])}</td><td>{r['completed']}/{r['planned']}</td><td>{r['successes']}</td><td>{r['success_rate']:.1%}</td></tr>"
        for r in arm_rows
        if r["success_rate"] is not None
    )
    screens = "".join(
        f"<tr><td>{r['screen']}</td><td>{r['C_candidates_in_hits']}/{r['reviewed_hits']}</td><td>{r['C_candidates_in_nonhits']}/{r['reviewed_nonhits']}</td><td>{r['weighted_fraction_C_candidates_missed']:.1%}</td></tr>"
        for r in screening
    )
    document = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 阶段1独立校准</title><style>body{{font:16px/1.7 system-ui;max-width:1080px;margin:40px auto;padding:0 24px;color:#17223b}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d7deea;padding:10px;text-align:left}}th{{background:#edf2fa}}.note{{background:#fff3d7;padding:16px}}</style>
<h1>P4 阶段1独立校准与持续委托对照</h1>
<p>冻结 60 条新审阅轨迹：24 条旧关键词命中失败、24 条未命中失败、12 条成功对照。排除上批的 120 条轨迹和 7 个入选任务。随机预选 24 条接受第二模型审阅及编码助手候选裁决，其中 20 条原生失败、4 条原生成功。模型审阅隐藏 reward、分层信息、任务答案与用户工具结果。编码助手裁决已接触结果和模型意见，不能当人工盲审。</p>
<h2>筛子校准：只计候选过程</h2><table><tr><th>筛子</th><th>命中中 C 候选</th><th>未命中中 C 候选</th><th>加权 C 候选漏检比例</th></tr>{screens}</table>
<p>加权仅对应排除旧数据后的残余 iid 失败池。新能力关键词筛子由本批错误启发，属于开发集拟合，不能把本批读数当独立验证；重复任务和小样本也限制推断。A/B 未因结构检查或模型意见直接升级为已验证模式。拒绝证书表示未解决，不表示无机制。</p>
<p>24 条编码助手参考里出现 {report["native_successes_with_C_process_candidate_in_panel"]} 条原生成功但存在 C 候选过程的轨迹。说明过程候选与 benchmark 最终 reward 必须分别记录，不能将它自动计入经验证的失败。</p>
<h2>持续提醒对照</h2><table><tr><th>条件</th><th>完成/计划</th><th>成功数</th><th>成功率</th></tr>{table}</table>
<p><img src="reminder_comparison.png" alt="四个选定案例三种持续提醒的成功率" style="width:100%;height:auto"><a href="reminder_comparison.pdf">下载 PDF 图</a></p>
<p>resample 使用原 policy；generic_policy 持续强调按 policy 排查；capability_policy 持续强调可指导用户执行已有设备操作。两种提醒相近长度、同样强调排查与检查结果，只改变 agent policy，用户 policy 不变；不提供隐藏状态、工具或任务答案。四个任务与上批任务不重叠，前缀状态一致。此比较检验持续委托提示的相对价值，尚不能排除所有提示显著性与 policy 理解解释。</p>
<p>v006 的失败是混合过程：最终 evaluator 显示仍未满足数据加购条件，不能把这一项单方排查缺失直接归给设备操作委托。已有权限修复并不保证全部任务条件成立。该任务保留在统计里，不因结果为零而事后删除；详见逐续写机制表。</p>
<p>旧 No-User 数据提供补充背景：v001、v013、v036 各成功 4/4，v006 为 0/4。这与 v006 存在其他困难的观察一致，但 No-User 同时改变信息、工具与 policy，不能作为因果隔离证据。详见 ability_context.json。</p>
<h2>成本与闸门</h2><p>本批 API 已记录 {report["known_tokens"]:,} tokens；{report["unknown_usage_requests"]} 个请求 usage 未知。保留接口恢复的全部尝试，旧源轨迹的生成成本不计入新 API 数字；不是完整账单，也不是发现效率比较。</p>
<p class="note">G1 尚未通过：当前没有人工参考、经验证失败的完整确认成本，也未完成全部竞争解释对照。G2 未测试。后续应冻结新版筛子，在独立样本验证，并针对实际委托错误审查 simulator 执行与 policy 理解；再冻结发现单位与预算曲线。</p>
<p><a href="analysis.json">分析 JSON</a> · <a href="calibration_audit.csv">24 条裁决与筛子</a> · <a href="assistant_reference.json">裁决依据</a> · <a href="case_outcomes.csv">逐案例续跑</a> · <a href="continuation_mechanisms.csv">续写过程及未满足条件</a> · <a href="protocol.json">冻结协议</a> · <a href="certificate_revision.json">证书规则修订</a> · <a href="annotation.html">独立人工标注页</a></p></html>"""
    (c.OUT / "report.html").write_text(document)
    print(
        json.dumps(
            {
                "reviewer_status": report["reviewer_status"],
                "screening": screening,
                "arms": arm_rows,
                "known_tokens": report["known_tokens"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
