"""One self-contained C2 report with explicit completion and authentication status."""

import collections
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
D = {s: BASE / f"v7_c2_{s}_20261006" for s in ["step1", "step2", "step3"]}


def read(p):
    return json.loads(p.read_text())


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def tokens():
    result = {}
    for step, d in D.items():
        calls = [read(p) for p in (d / "requests").glob("*.json")]
        roles = {}
        for role in sorted({r["role"] for r in calls}):
            rr = [r for r in calls if r["role"] == role]
            roles[role] = {
                "request_records": len(rr),
                "returned_usage_records": sum(r.get("usage") is not None for r in rr),
                "unknown_usage_records": sum(r.get("usage") is None for r in rr),
                "prompt_tokens": sum(
                    (r.get("usage") or {}).get("prompt_tokens", 0) for r in rr
                ),
                "completion_tokens": sum(
                    (r.get("usage") or {}).get("completion_tokens", 0) for r in rr
                ),
                "total_tokens": sum(
                    (r.get("usage") or {}).get("total_tokens", 0) for r in rr
                ),
            }
        result[step] = {
            "roles": roles,
            "status_counts": dict(collections.Counter(r["status"] for r in calls)),
            "returned_model_ids": dict(
                collections.Counter(
                    r.get("returned_model") for r in calls if r.get("returned_model")
                )
            ),
            "temperature_counts": dict(
                collections.Counter(str(r["request"].get("temperature")) for r in calls)
            ),
        }
    save(OUT / "token_accounting.json", result)
    return result


def report():
    rules = read(D["step1"] / "rules_v2.json")
    manifest = read(D["step2"] / "manifest.json")
    originals = {
        r["candidate_id"]: r
        for r in read(BASE / "v7_c_step2_20261005/reclassification.json")["cases"]
    }
    cases = []
    for case in manifest["cases"]:
        path = D["step2"] / "mapped_labels" / f"{case['label_digest']}.json"
        if not path.exists():
            cases.append({**case, "label_status": "pending"})
            continue
        label = read(path)
        cases.append(
            {
                **case,
                "label_status": "complete",
                "case_class": originals[case["candidate_id"]]["new_class"],
                "valid": label["valid"],
                "style": label["style"],
                "mechanical_violations": label["mechanical_violations"],
                "programmatic_scenario_violations": label[
                    "programmatic_scenario_violations"
                ],
                "model_scenario_violations": label["model_scenario_violations"],
                "departed_style_rules": label["departed_style_rules"],
            }
        )
    save(
        D["step2"] / "case_labels.json",
        {
            "cases": cases,
            "model_labels_not_human_annotations": True,
            "rule_inventory": "rules_v2; added native-format style label is programmatic; all remaining Sol judgments unchanged",
        },
    )
    accepted = [read(f) for f in (D["step1"] / "replies").glob("*.json")]
    native = [read(f) for f in (D["step1"] / "native_labels").glob("*.json")]
    redo = (
        read(D["step1"] / "sanity_format_redo_units.json")["units"]
        if (D["step1"] / "sanity_format_redo_units.json").exists()
        else []
    )
    qualified = [r for r in accepted if r["unit"] not in redo]
    reason_counts = collections.Counter()
    for f in (D["step1"] / "rejected_proposals").glob("*.json"):
        for reason in read(f)["reasons"]:
            reason_counts["VS_JSON_schema:" + reason] += 1
    for f in (D["step1"] / "rejected_replies").glob("*.json"):
        label = read(f)["label"]
        for reason in label["mechanical_violations"]:
            reason_counts["mechanical:" + reason] += 1
        for reason in label["programmatic_scenario_violations"]:
            reason_counts["DB_scenario:" + reason["field"]] += 1
        for reason in label["model_scenario_violations"]:
            reason_counts["model_scenario:" + reason["rule_id"]] += 1
    counts = {
        s: dict(
            collections.Counter(
                r["case_class"] for r in cases if r.get("valid") and r.get("style") == s
            )
        )
        for s in ["in_rule", "out_of_rule"]
    }
    bad = [
        r["candidate_id"]
        for r in cases
        if r.get("label_status") == "complete" and not r["valid"]
    ]
    summary = {
        "sanity_valid_turns_saved": len(accepted),
        "final_generator_qualified_draws": len(qualified),
        "requested_sanity_draws": 60,
        "sanity_redo_units": redo,
        "accepted_style_counts": dict(
            collections.Counter(r["label"]["style"] for r in accepted)
        ),
        "qualified_draw_style_counts": dict(
            collections.Counter(r["label"]["style"] for r in qualified)
        ),
        "native_baseline_labels": len(native),
        "rejection_reason_counts": dict(reason_counts),
        "case_class_counts_by_style": counts,
        "invalid_cases": bad,
        "historical_unique_label_inputs": len(manifest["unique_label_inputs"]),
        "historical_unique_labels_complete": len(
            list((D["step2"] / "mapped_labels").glob("*.json"))
        ),
        "historical_partner_turn_instances": manifest["raw_partner_turn_instances"],
        "historical_trajectory_count": len(manifest["trajectories"]),
        "search_started": False,
    }
    save(OUT / "status.json", summary)
    accounting = tokens()
    projection = read(D["step3"] / "cost_projection.json")
    lines = [
        "# P4 v7 Tier C continued：规则、重标与搜索准备",
        "",
        "**当前状态：15个固定案例重标完成；sanity和历史逐回合重标尚未完成；Step3未启动。四条既有凭据均返回HTTP401，已保存认证诊断。** 本报告不把缺失标签视为有效、不制造后过滤的成功率，也不把未运行的搜索臂记成零发现。",
        "",
        "固定项目标准：mechanical与scenario违背使回合无效，style偏离保留并逐条标注。原C1把多动作澄清当作协议bug的解释，在本项目标准下撤回；历史报告保留。所有Sol标签都是模型判断，新增格式标签来自程序字段检查，没有人工标签。",
        "",
        "## Step1：逐字规则与生成器",
        "",
        "完整20个原生system prompts、逐字quote的位置及所属任务见 [rules_v2.json](../v7_c2_step1_20261006/rules_v2.json)。原抽取版本 [rules.json](../v7_c2_step1_20261006/rules.json) 保留，格式边界修订见 [amendment](../v7_c2_step1_20261006/plan_amendment_native_format.json)。表中正文上下文也保留用于覆盖，不适用的上下文不算风格违背；runtime-derived行明确区分于逐字原生规则。",
        "",
        "|Rule ID|分类|逐字原文或明确标识的runtime要求|",
        "|---|---|---|",
    ]
    for rule in rules["rules"]:
        quote = (
            rule.get("verbatim")
            or "【runtime-derived，非原prompt原文】" + rule["operational_definition"]
        )
        lines.append(
            f"|{rule['rule_id']}|{rule['category']}|{quote.replace('|', '&#124;').replace(chr(10), '<br>')}|"
        )
    lines += [
        "",
        "VS生成调用保留第一条native system prompt逐字不变，保留原生user-visible history，工具通过原生API schemas提供；唯一添加内容是k=5候选及概率的采样/JSON输出指令。按预先固定种子从5个候选均匀抽1个，概率记录但不作为权重；没有行为强化指令或研究者persona。原始请求账本可核对prompt。",
        "",
        "机械检查覆盖原生工具与参数、实际native工具结果来源和终止tokens；场景事实与真实DB比较，过去时及不确定表达不自动按当前DB定罪（[解析范围修订](../v7_c2_step2_20261006/plan_amendment_scenario_claim_scope.json)），未能解析的内容由冻结Sol t=0按逐字规则判定。每个适用style规则单列状态，style不会进入拒绝条件。原生runtime允许content+tools并隐藏行内文本，因此提示中的“不能同时做两者”是style，而不是机械XOR门。",
        "",
        "### Sanity：未完成，保留原始分母",
        "",
        "|项目|当前数量|计划数量|",
        "|---|---:|---:|",
        f"|已保存有效VS回合|{len(accepted)}|60|",
        f"|符合最终采样过滤版本的已完成draw|{len(qualified)}|60|",
        f"|native q逐规则标签|{len(native)}|60|",
    ]
    for style in ["in_rule", "out_of_rule"]:
        lines.append(
            f"|全部已保存VS回合的{style}|{sum(r['label']['style'] == style for r in accepted)}|分母{len(accepted)}|"
        )
    lines += [
        "",
        f"其中{len(redo)}个draw曾因现在归为style的content+tools而重采，其后接受回合仍有效，但不能算作最终生成器的sanity抽样；需要恢复该draw。原始记录保留，不抹掉这次错误过滤。style标签和规则分母见 [status.json](status.json)，native q比较与最终out_of_rule区间待完成60+60后报告。",
        "",
        "拒绝原因原始计数（含已纠正的旧格式拒绝，不将它重新解释为最终标准的违规）：`"
        + json.dumps(dict(reason_counts), ensure_ascii=False)
        + "`。认证/JSON路由错误是执行失败，单列于ledger，不当作伙伴违规。",
        "",
        "## Step2：15个固定案例",
        "",
        "|Case|State|方向|既有案例类|机械违规|场景违规|style|偏离style规则ID|",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        if case["label_status"] != "complete":
            lines.append(
                f"|{case['candidate_id']}|{case['state_id']}|{case['direction']}|待标签|未知|未知|未知|—|"
            )
            continue
        departures = (
            ", ".join(r["rule_id"] for r in case["departed_style_rules"]) or "—"
        )
        lines.append(
            f"|{case['candidate_id']}|{case['state_id']}|{case['direction']}|{case['case_class']}|{', '.join(case['mechanical_violations']) or '无'}|{'有' if case['programmatic_scenario_violations'] or case['model_scenario_violations'] else '无'}|{case['style']}|{departures}|"
        )
    lines += [
        "",
        "各rule的完整证据quote、programmatic DB检查及Sol场景判断保留在 [case_labels.json](../v7_c2_step2_20261006/case_labels.json) 和 mapped_labels/。原有类依据真实Luna/Sol retest、scope修正和原始区间沿用，没有新续写或新分类阈值。",
        "",
        "|类|in_rule有效案例|out_of_rule有效案例|",
        "|---|---:|---:|",
    ]
    for cls in [
        "reward_spec_mismatch",
        "hard_for_both",
        "capability_dependent",
        "infeasible_after_block",
        "beneficial_disclosure",
        "beneficial_other",
        "unclear",
    ]:
        lines.append(
            f"|{cls}|{counts['in_rule'].get(cls, 0)}|{counts['out_of_rule'].get(cls, 0)}|"
        )
    lines += [
        "",
        f"无效案例：{bad or '无（15个均有效）'}。c015的Sol失败中10/16仅未满足精确补流量断言，但合并Luna后11/32，冻结合并规则仍为unclear；style/validity标签没有掩盖这项奖励规格问题。",
        "",
        "### 持续伙伴的成功率分解：标签尚未齐全",
        "",
        f"已建立{len(manifest['trajectories'])}条历史轨迹、{manifest['raw_partner_turn_instances']}个伙伴回合实例的映射，共{len(manifest['unique_label_inputs'])}个唯一标签输入；其中{summary['historical_unique_labels_complete']}个已完成完整模型/程序标签。B1覆盖native/single/persistent及初始回合，v2覆盖全部240条Luna和72条Sol持续续写。机械与DB可独立继续离线检查，但缺失的场景判断与style标签保持未知。因此当前不能报告排除违规后的persistent−single差值或完整in_rule/out_of_rule分层区间。不是把未经检查的轨迹默认当作有效。",
    ]
    pcheck = D["step2"] / "programmatic_summary_v2.json"
    if pcheck.exists():
        lines += [
            "",
            "离线程序检查结果：`"
            + json.dumps(read(pcheck), ensure_ascii=False)
            + "`。这些不是完整场景有效性判定，未解析规则仍需Sol判断。",
        ]
    lines += [
        "",
        "## Step3：预计成本与执行状态",
        "",
        "|Arm|预计tokens|目标suffix-equivalents|当前执行|",
        "|---|---:|---:|---|",
    ]
    for arm, n in projection["projected_tokens_per_arm"].items():
        lines.append(f"|{arm}|{n:,.0f}|1000|未启动|")
    lines += [
        "",
        f"成本基准是B1 step2全部返回tokens/1024条saved suffix，得到每个suffix-equivalent {projection['tokens_per_suffix_equivalent']:.6f} tokens；不同模型的token统一计量，不声称同价。B1总返回tokens {projection['B1_total_returned_tokens']:,}，三倍上限{projection['three_times_B1_tokens']:,}，五臂预计合计{projection['projected_all_arms_tokens']:,.0f}，未超过上限。Step1/2和失败调用单独列账，不隐藏在搜索效率分母里。",
        "",
        "预算拆分、buffer来源、selection公式、GT只记录的约束、独立16vs16 retest、Sol检查、case去重以及未知usage处理见 [plan.json](../v7_c2_step3_20261006/plan.json)；最终规则关联修订在其amendment中。模型目录列出了DeepSeek/Claude/Qwen，但尚未做可调用性probe，不能把目录存在当作实际运行。",
        "",
        "因凭据失效，A0–A4没有fresh seed episode、screen、retest或Sol-check结果；目前不回答效率优劣，不生成虚假的曲线或三张案例卡。认证诊断见 [authentication_diagnostic.json](authentication_diagnostic.json)。",
        "",
        "## 两个问题的当前答案",
        "",
    ]
    harmful = [r for r in cases if r["direction"] == "harmful" and r.get("valid")]
    hcounts = collections.Counter(r["style"] for r in harmful)
    lines += [
        f"1. 10个已确认有害固定案例（含1个随机对照）中，当前逐条规则标签为 **in_rule {hcounts.get('in_rule', 0)}个，out_of_rule {hcounts.get('out_of_rule', 0)}个**。只看9个主要有害案例，in_rule5、out_of_rule4。这里in_rule是符合native风格规则的模型判定，不是实测该块在q下出现概率；out_of_rule也不意味着随机simulator绝对不可能生成。",
        "2. 搜索循环是否更省预算：**尚不能判断**。搜索尚未启动，不能以准备好的代码或成本预测代替实验。",
        "",
        "## 已发生的调用与恢复位置",
        "",
        "|步骤/角色|请求记录|返回usage|未知usage|返回tokens|",
        "|---|---:|---:|---:|---:|",
    ]
    for step, row in accounting.items():
        for role, v in row["roles"].items():
            lines.append(
                f"|{step}/{role}|{v['request_records']}|{v['returned_usage_records']}|{v['unknown_usage_records']}|{v['total_tokens']}|"
            )
    lines += [
        "",
        "失败/中断请求usage未知，不按零计，也不把input/output aliases重复相加。JSON模式的两项传输格式修订、原始失败尝试、库存修订、格式边界修订均保留；没有重新训练或按效果调标签器。",
        "",
        "恢复位置：先补齐最终生成器sanity draws及native基线标签；完成10,590个唯一历史标签；报告完整persistent split；再执行已冻结的搜索预算与family接口probe。此次暂停原因是四条凭据均HTTP401，不是预算阈值。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    save(
        OUT / "report_status.json",
        {
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "completion": "partial_authenticated_calls_blocked",
            "status": summary,
        },
    )
    print("REPORT cases", len(cases), "harmful style", dict(hcounts), flush=True)


if __name__ == "__main__":
    report()
