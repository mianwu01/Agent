"""Cards-first final report, model usage and exact-unit/source audit."""

import collections
import json
from concurrent.futures import ThreadPoolExecutor

import b2 as x

read, save = x.read, x.save


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        + [
            "| " + " | ".join(str(v).replace("|", "/") for v in row) + " |"
            for row in rows
        ]
    )


def band(mean, ci):
    if mean is None:
        return "undefined"
    return f"{mean:.3f}" + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")


def rate(r):
    return f"{r['successes']}/{r['n']} " + band(r["rate"], r["score_95_CI"])


def estimate(r):
    return f"{r['numerator']}/{r['denominator']} " + band(
        r["estimate"], r["task_cluster_95_CI"]
    )


def diff(r):
    return band(r["difference"], r["score_95_CI"])


def action_description(entry):
    """Literal executed agent decision, omitting generated identifiers."""
    if entry is None:
        return "路径已结束"
    message = entry["message"]
    calls = message.get("tool_calls") or []
    if calls:
        return "; ".join(
            t["name"]
            + " "
            + json.dumps(t.get("arguments", {}), ensure_ascii=False, sort_keys=True)
            for t in calls
        )
    return "说：" + (message.get("content") or "空消息")


def audit():
    p = read(x.OUT / "plan.json")
    manifest = read(x.OUT / "input_manifest.json")

    def verify(item):
        f, h = item
        return f if x.sha(x.ROOT / f) != h else None

    with ThreadPoolExecutor(max_workers=16) as pool:
        changed = [f for f in pool.map(verify, manifest.items()) if f]
    assert not changed, changed
    assert all(x.sha(x.ROOT / f) == h for f, h in p["historical_input_sha256"].items())
    selection = read(x.D["b2"] / "b2_selection.json")
    assert selection["B1_states_sha256"] == x.sha(x.D["b"] / "states.json")
    expected_a = {
        f"{c['state_id']}:sol_fixed:{c['candidate_id']}:r{rep}"
        for c in p["cases"]
        for rep in range(16)
    } | {
        f"{c['state_id']}:sol_native_{c['candidate_id']}:d{j}:r0"
        for c in p["cases"]
        for j in range(16)
    }
    expected_b2 = {
        f"{sid}:persistent_luna:d{j}:r{rep}"
        for sid in selection["large_drop"] + selection["little_drop"]
        for j in range(6)
        for rep in range(4)
    } | {
        f"{sid}:persistent_sol:d{j}:r{rep}"
        for sid in selection["large_drop"]
        for j in range(6)
        for rep in range(2)
    }
    expected = {"a": expected_a, "b2": expected_b2}
    for step, units in expected.items():
        assert {f.stem for f in (x.D[step] / "continuations").glob("*.json")} == units
    b2rows = [read(f) for f in (x.D["b2"] / "continuations").glob("*.json")]
    assert all(
        r["initial_validation_version"] == "native_inclusive_or_v2"
        and set(r["future_proposal_validation_versions"]) <= {"native_inclusive_or_v2"}
        for r in b2rows
    )
    assert all(
        r["agent_model"] == x.SOL
        for r in [read(f) for f in (x.D["a"] / "continuations").glob("*.json")]
    )
    transfer = []
    for f in (x.D["b2"] / "replies").glob("*.json"):
        r = read(f)
        assert r["native_validation_version"] == "native_inclusive_or_v2"
        if r["transfer_terminal_required"]:
            valid = any(
                "###TRANSFER###" in (m.get("content") or "")
                for m in r["partner_block"]
                if m["role"] == "user"
            ) and not any(m.get("tool_calls") for m in r["partner_block"])
            assert valid, f
            transfer.append(r["unit"])
    usage = {}
    models = collections.Counter()
    for step, d in x.D.items():
        counter = collections.Counter()
        rolemodels = collections.Counter()
        temperatures = collections.Counter()
        files = list((d / "requests").glob("*.json"))
        with ThreadPoolExecutor(max_workers=16) as pool:
            for r in pool.map(read, files):
                assert r["request"]["api_key"].startswith("os.environ/P4_API_KEY_")
                counter["records"] += 1
                counter[r["status"]] += 1
                rolemodels[str((r["role"], r["request"]["model"]))] += 1
                temperatures[str((r["role"], r["request"].get("temperature")))] += 1
                if r["status"] == "response":
                    for k, v in (r.get("usage") or {}).items():
                        if isinstance(v, (int, float)):
                            counter[k] += v
                    models[r.get("returned_model", r["request"]["model"])] += 1
        usage[step] = {
            "counts": dict(counter),
            "models_by_role": dict(rolemodels),
            "temperatures_by_role": dict(temperatures),
        }
    save(
        x.OUT / "token_accounting.json",
        {
            "steps": usage,
            "returned_models": dict(models),
            "limitation": "Returned usage only; interrupted/failed calls may consume provider tokens that are unknown, never imputed. All retries preserved.",
        },
    )
    record = {
        "historical_inputs_verified": len(manifest),
        "changed_historical_inputs": changed,
        "exact_suffix_counts": {k: len(v) for k, v in expected.items()},
        "uniform_v2_verified": True,
        "transfer_protocol_accepted_n": len(transfer),
        "transfer_protocol_violations": 0,
        "plan_sha256": x.sha(x.OUT / "plan.json"),
        "selection_sha256": x.sha(x.D["b2"] / "b2_selection.json"),
        "code_sha256": {f.name: x.sha(f) for f in x.OUT.glob("*.py")},
        "model_judgments_not_human_labels": True,
        "claim_definition_amendment": "plan_amendment_claim_observation.json",
        "tests_log": "tests.log",
        "credential_routing_amendment": "plan_amendment_credential_routing.json",
        "action_identity_amendment": "plan_amendment_action_identity.json",
        "case_card_display_audit": "case_card_display_audit.json",
    }
    save(x.OUT / "audit.json", record)
    return usage


def report():
    a = read(x.D["a"] / "a2_summary.json")
    b = read(x.D["b"] / "b1_summary.json")
    new = read(x.D["b2"] / "comparison.json")
    source_units = {
        c["candidate_id"]: c["reply_unit"] for c in read(x.OUT / "plan.json")["cases"]
    }
    state_ci = {
        s["state_id"]: s for s in read(x.D["b"] / "state_intervals.json")["states"]
    }
    usage = audit()
    lines = [
        "# P4 v7 — Tier B round 2",
        "",
        "请求模型为 openai/gpt-6-luna（Luna）与 openai/gpt-5.6-sol（Sol）；返回模型标识单列于 token_accounting.json。15 个固定回复案例（10 个状态）的机械检查、480 条 Sol 续写；B1 的 20 个状态 ×3 条件 ×6 分叉 draw ×4 续写，共 1,440 条历史续写分解；统一 v2 的 240 条 Luna +72 条 Sol 持久续写。保持探索性解释；卡片的模型摘要由冻结 Sol t=0 提示生成，机械事实由程序直接呈现，均不作为人工标签。",
        "",
        "## 案例卡片（A3）",
        "",
        "每张6–7行卡片的第1–4行及可选第7行按原始分叉块、归一化路径及末态断言机械生成，保证前序请求、分叉操作与后续操作分开；第5–6行是冻结 Sol 模型摘要，路径叙述来自代表续写而非所有续写一致。原始模型六行输出完整保留在 case_cards/。检查发现 c010/c012 的原始第2行把后续动作写成分叉动作，c023 的模型前序请求摘要额外写入了开启移动数据要求，部分描述混淆分叉末态与续写末态；原始动作比较也含随机 tool-call ID。因此展示层对所有案例统一引用真实固定块、原生 j=0 块、归一化首处分歧和全体末态断言计数，不改模型提示、不重生成标签；修正见 plan_amendment_action_identity.json。",
        "",
    ]
    for c in a["cases"]:
        card = read(x.D["a"] / "case_cards" / f"{c['candidate_id']}.json")
        lines += [
            f"### {c['candidate_id']} · {c['state_id']} · {c['direction']} · {source_units[c['candidate_id']]}"
            + (" · 随机对照" if c["random_control"] else ""),
            "",
        ]
        mechanical = read(x.D["a"] / "mechanical_cards" / f"{c['candidate_id']}.json")
        fixed_text = " ".join(
            m.get("content") or ""
            for m in mechanical["fixed"]["block"]
            if m["role"] == "user"
        )
        fixed_tools = [
            t["name"]
            for m in mechanical["fixed"]["block"]
            for t in (m.get("tool_calls") or [])
        ]
        native_text = " ".join(
            m.get("content") or ""
            for m in mechanical["native_blocks"][0]["block"]
            if m["role"] == "user"
        )
        native_tools = [
            t["name"]
            for m in mechanical["native_blocks"][0]["block"]
            for t in (m.get("tool_calls") or [])
        ]
        displayed = list(card["lines"])
        request_text = mechanical["fixed"]["request"].get("content") or ""
        try:
            request_json = json.loads(request_text)
            if isinstance(request_json, dict) and isinstance(
                request_json.get("message"), str
            ):
                request_text = request_json["message"]
        except json.JSONDecodeError:
            pass
        displayed[0] = "【机械原文】前序 agent 请求：" + request_text
        displayed[1] = (
            f"【机械原文】固定块：{fixed_text}；执行工具 {fixed_tools}，DB 改变字段数 {len(mechanical['fixed']['db_changes'])}；原生参考 j=0：{native_text}；执行工具 {native_tools}（全部 16 个参考块见原证据）。"
        )
        divergence = mechanical["paired_path_divergences"][0]["first_divergence"]
        displayed[2] = (
            f"【机械路径】独立 Luna rep=0 的首次决策差异在第 {divergence['agent_decision_ordinal']} 次：候选 {action_description(divergence['candidate'])}；原生 {action_description(divergence['native'])}；这不是匹配随机性或因果证明。"
            if divergence
            else "【机械路径】Luna rep=0 两条执行路径未发现决策差异（工具 ID 已归一化）。"
        )
        unmet = {
            arm: dict(
                collections.Counter(
                    {
                        "assert_mobile_data_status": "移动数据可用",
                        "assert_internet_speed": "excellent网速",
                        "assert_data_refueling_amount": "恰好加购2GB",
                        "assert_can_send_mms": "可发送MMS",
                    }.get(a["assertion"]["func_name"], a["assertion"]["func_name"])
                    for row in mechanical["suffixes"]
                    if row["arm"] == arm
                    for a in row["assertions_final"]
                    if not a["met"]
                )
            )
            for arm in ["candidate", "native"]
        }
        displayed[3] = (
            f"【机械断言】分叉前后满足向量 {[a['met'] for a in mechanical['fixed']['assertions_before']]} → {[a['met'] for a in mechanical['fixed']['assertions_after']]}；直接满足/破坏 {len(mechanical['fixed']['directly_satisfied_assertions'])}/{len(mechanical['fixed']['directly_broken_assertions'])} 项；Luna 末态每项未满足次数（各16条）：固定 {unmet['candidate']}，原生 {unmet['native']}。"
        )
        diagnostic = c["assertion_diagnostic"]
        if (
            diagnostic["Luna_fixed"]["sole_unmet_exact_refueling_n"]
            or diagnostic["Sol_fixed"]["sole_unmet_exact_refueling_n"]
        ):
            displayed.append(
                f"【机械评分核对】Luna 固定 {diagnostic['Luna_fixed']['sole_unmet_exact_refueling_n']}/16、Sol 固定 {diagnostic['Sol_fixed']['sole_unmet_exact_refueling_n']}/16 仅未满足精确充值量断言，其余任务断言已满足；低奖励不能直接解释为连接未恢复或任务不可行。"
            )
        lines += [f"{i + 1}. {text}" for i, text in enumerate(displayed)]
        lines += [
            "",
            f"机械原始证据：[DB、全部伙伴块、断言和 Luna 路径](../v7_b2_a_20261005/mechanical_cards/{c['candidate_id']}.json)；[Sol/Luna 成功率与分类](../v7_b2_a_20261005/a2_cases/{c['candidate_id']}.json)；[首次工具调用分歧](../v7_b2_a_20261005/tool_divergences/{c['candidate_id']}.json)。",
            "",
        ]
    lines += [
        "## A2：更强 agent 的执行检查",
        "",
        table(
            [
                "案例",
                "方向 / 对照",
                "Luna 固定",
                "Luna 原生参考",
                "Sol 固定",
                "Sol 新原生参考",
                "Sol−Luna 固定 [CI]",
                "操作性类别",
            ],
            [
                [
                    f"{c['candidate_id']} {c['state_id']}",
                    c["direction"] + (" / control" if c["random_control"] else ""),
                    rate(c["rates"]["Luna_fixed"]),
                    rate(c["rates"]["Luna_native"]),
                    rate(c["rates"]["Sol_fixed"]),
                    rate(c["rates"]["Sol_native"]),
                    diff(c["Sol_minus_Luna_fixed"]),
                    c["operational_class"],
                ]
                for c in a["cases"]
            ],
        ),
        "",
        "每个案例 16 条固定块 +16 条新原生块续写；所有 agent 温度均为 1.0，后续原生伙伴仍为 Luna。单个率使用 Wilson score95% CI，差值使用 Newcombe score95% CI，保留负值与端点不确定性。Luna 率来自 B1，Sol 率来自本轮；时间与新原生块差异不能完全排除。",
        "",
        "类别规则在 plan.json 中先冻结：固定块 Sol−Luna 差区间下界>0 为 interaction_failure；否则，Sol 固定率区间上界<0.5 且 Sol 原生−固定差区间下界>0，为 partner_sabotage_or_task_infeasible_probe；其余 unclear。这是操作性阅读规则，Sol 失败不能证明不可行或蓄意破坏，类别不控制采样。",
        "",
    ]
    lines += [
        "### 奖励与用户目标的差别",
        "",
        "原生用户场景允许必要时充值 2GB，解决标准是 speed test 达到 excellent；环境 assert_data_refueling_amount 则要求累计量恰好等于 2GB。先加 1GB 的回复可能恢复连接但不满足该断言。下表机械统计唯一未满足断言是充值量的失败，不能据此认定用户目标失败或任务不可行。",
        "",
        table(
            ["案例", "Luna 固定", "Luna 原生", "Sol 固定", "Sol 原生"],
            [
                [c["candidate_id"]]
                + [
                    f"{c['assertion_diagnostic'][key]['sole_unmet_exact_refueling_n']}/{c['assertion_diagnostic'][key]['n']}"
                    for key in ["Luna_fixed", "Luna_native", "Sol_fixed", "Sol_native"]
                ]
                for c in a["cases"]
                if any(
                    r["sole_unmet_exact_refueling_n"]
                    for r in c["assertion_diagnostic"].values()
                )
            ],
        ),
        "",
    ]
    beneficial = [c for c in a["cases"] if c["direction"] == "beneficial"]
    lines += [
        table(
            ["有益案例", "分叉本身直接满足的断言", "DB 事实检查"],
            [
                [
                    f"{c['candidate_id']} {c['state_id']}",
                    json.dumps(c["directly_satisfied_assertions"], ensure_ascii=False),
                    f"识别 {c['device_claim_check']['recognized_claim_n']}；未读工具 {c['device_claim_check']['unobserved_claim_n']}；DB 不符 {c['device_claim_check']['incorrect_claim_n']}",
                ]
                for c in beneficial
            ],
        ),
        "",
        "直接满足按分叉前 false → 分叉后 true 判定；文字披露本身不改变环境断言。未直接满足不能单独证明是更好的 agent 决策，须结合后续执行路径。首次分歧按精确 agent 消息/工具名与参数比较；文字变化可先于行为变化，不作为因果证明。按 rep 序号排列的 Luna 对照是独立样本的描述性配对。",
        "",
        "## B1：持久伙伴的结果分解",
        "",
        table(
            [
                "条件",
                "成功 /480",
                "后续总回合均值 [任务 CI]",
                "后续伙伴回合均值 [CI]",
                "普通 stop 全断言满足",
                "普通 stop 断言未满足",
                "转人工 / 其中断言未满足",
                "上限结束",
            ],
            [
                [
                    k,
                    f"{v['successes']}/480",
                    band(v["turns"]["estimate"], v["turns"]["task_cluster_95_CI"]),
                    band(
                        v["partner_turns"]["estimate"],
                        v["partner_turns"]["task_cluster_95_CI"],
                    ),
                    estimate(v["terminations"]["user_stop_all_assertions"]),
                    estimate(v["terminations"]["user_stop_unmet_assertions"]),
                    estimate(v["terminations"]["transfer"])
                    + " / "
                    + estimate(v["transfer_assertions_unmet"]),
                    estimate(v["terminations"]["max_steps"]),
                ]
                for k, v in b["conditions"].items()
            ],
        ),
        "",
        "回合定义：agent 的一次消息/工具调用决策或一个完整伙伴块；工具结果不是独立回合。上表从初始替换块之后计数，含初始块的数值在原始文件单列。转人工 token 优先归到 transfer，避免混入普通用户停止；奖励与断言是否全部满足分别保留。任务聚类 bootstrap1,000 次，任务内所有状态/续写一起重采。",
        "",
        "![每状态成功率差](../v7_b2_b_20261005/state_drop.png)",
        "",
        table(
            [
                "状态",
                "single 成功 /24",
                "persistent 成功 /24",
                "persistent−single",
                "对整体差值的贡献",
            ],
            [
                [
                    s["state_id"],
                    s["conditions"]["single"]["successes"],
                    s["conditions"]["persistent"]["successes"],
                    band(
                        s["persistent_minus_single"],
                        state_ci[s["state_id"]][
                            "persistent_minus_single_reply_cluster_95_CI"
                        ],
                    ),
                    f"{s['pooled_contribution']:.4f}",
                ]
                for s in sorted(b["states"], key=lambda r: r["persistent_minus_single"])
            ],
        ),
        "",
        table(
            ["失败终止类别", "persistent−single 失败率差 [任务 CI]"],
            [
                [cat, band(r["mean"], r["bootstrap_95_CI"])]
                for cat, r in b["failure_difference_accounting"].items()
            ],
        ),
        "",
        b["accounting_caveat"],
        "s002:persistent:d5:r3 是唯一上限结束案例：最终 DB 断言已全部满足，但原生 evaluator 对 max_steps 提前终止返回奖励0。因此终止奖励与最终断言分别报告。",
        "",
        table(
            [
                "条件：断言未满足的普通用户 stop",
                "声称解决",
                "继续排查",
                "请求用户操作",
                "其他 / 不明确",
            ],
            [
                [k]
                + [
                    estimate(v["unmet_stop_last_agent"][cat])
                    for cat in [
                        "claims_resolution",
                        "still_troubleshooting",
                        "asks_user_action",
                        "other_or_unclear",
                    ]
                ]
                for k, v in b["conditions"].items()
            ],
        ),
        "",
        f"分类来源：{b['model_label_count']} 个冻结 Sol t=0 模型判断，{b['mechanical_label_count']} 个工具/终止/缺失消息的机械判断。条件中无此类停止时比例 undefined，不当作零。",
        "",
        table(
            ["persistent 后续伙伴统计", "原始分子 / 分母及任务 CI"],
            [[k, estimate(v)] for k, v in b["later_partner"].items()],
        ),
        "",
        "工具率包括读取与修改工具。未观测/不准确事实来自冻结显式句式解析与真实 DB/原生诊断，不由模型评判。读过字段但报错值属于已观测的不准确声明；与工具一起输出的文字在执行前检查。任意工具历史不是当前值仍然正确的保证，过期观察另存。解析器未覆盖的设备句子为 unassessed，不能拿低检出率证明没有忠实性漂移。规则纠正在 [amendment](plan_amendment_claim_observation.json) 中，早期机械输出保留在 parser archives；原 plan 未改。",
        "",
        "每状态的回合数、终止比例、后续工具/声明率及区间另见 [state_intervals.json](../v7_b2_b_20261005/state_intervals.json)。状态内只有一个任务，因此状态内区间按六个分叉 draw 聚类重采 1,000 次，single/persistent 共享 draw 配对重采，native 独立重采，保留每 draw 的四条续写；总体区间仍按任务聚类。零事件的 bootstrap 区间可退化，不表示总体概率已知为零。",
        "",
        "## B2：统一 v2 的复测",
        "",
        "在 B1 分解后、B2 调用前冻结六个最大下降状态和四个接近零下降状态。所有 60 个分叉块、所有后续提议均使用 native inclusive-OR v2；不复用 B1 接受块。六个最大下降状态的 Sol 与 Luna 共享初始分叉块，但后续提议依各自历史重新生成。",
        "",
        table(
            [
                "状态 / 组",
                "新 Luna v2",
                "B1 persistent",
                "B1 single",
                "新 Sol v2",
                "v2−B1 persistent [score CI]",
                "v2−B1 single [CI]",
                "Sol−Luna v2 [CI]",
            ],
            [
                [
                    s["state_id"] + " / " + s["cohort"],
                    rate(s["rates"]["Luna_v2"]),
                    rate(s["rates"]["Luna_B1_persistent"]),
                    rate(s["rates"]["Luna_B1_single"]),
                    rate(s["rates"]["Sol_v2"]) if "Sol_v2" in s["rates"] else "未运行",
                    diff(s["comparisons"]["v2_minus_B1_persistent"]),
                    diff(s["comparisons"]["v2_minus_B1_single"]),
                    diff(s["comparisons"]["Sol_minus_Luna_v2"])
                    if "Sol_minus_Luna_v2" in s["comparisons"]
                    else "未运行",
                ]
                for s in new["states"]
            ],
        ),
        "",
        table(
            ["组", "差值", "均值 [任务聚类 CI]"],
            [
                [cohort, key, band(r["mean"], r["bootstrap_95_CI"])]
                for cohort, v in new["aggregate"].items()
                for key, r in v.items()
                if key != "raw_rates"
            ],
        ),
        "",
        table(
            [
                "B2 最大下降六状态",
                "n",
                "转人工 / 失败",
                "普通 stop 全满足",
                "普通 stop 未满足",
                "max_steps",
            ],
            [
                [
                    arm,
                    r["n"],
                    f"{r['counts'].get('transfer', 0)} / {r['failure_counts'].get('transfer', 0)}",
                    r["counts"].get("user_stop_all_assertions", 0),
                    r["counts"].get("user_stop_unmet_assertions", 0),
                    r["counts"].get("max_steps", 0),
                ]
                for arm, r in new["termination_decomposition"]["large_drop"].items()
            ],
        ),
        "",
        "此表只机械读取统一 v2 的新轨迹，与 B1 使用相同终止类别；六状态 Luna 各24条、Sol 各12条，分母分别144与72，不把原始次数直接当作概率差。全体与对照组的原始次数也保存在 comparison.json。",
        "",
        "统一 v2 在六个预选高下降状态中仍比 B1 single 低 0.236（任务聚类95% CI [-0.333, -0.167]），因此下降没有被 validator 修正消除；相对旧 persistent 的恢复为 +0.111 [-0.014, 0.201]，不宜把全部恢复归因于版本。Sol 相对 Luna 为 +0.035 [-0.083, 0.153]，没有明确的总体改善。",
        "",
        "四个原先接近零下降的对照状态也发生新下降：尤其 s010 从旧 single/persistent 的24/24变为新 v2的6/24，不能只强调高下降组的部分恢复。这个结果不符合‘只有原来最差状态受影响’的简单解释；新提议抽样、版本差异和路径变异尚未拆开，且 s010 没有 Sol rerun。little_drop 的 v2−旧 persistent CI 上界为 -2.8e-17，数值上等于0，不能当作严格排除0的证据；原始浮点值完整保留。",
        "",
        new["caveats"],
        "",
        "## 两个问题的回答",
        "",
    ]
    lines += [
        "c009（s028）在固定块上 Luna 为 1/16、Sol 为 9/16，Sol 原生参考也为 9/16，是主要案例中最清楚的应对改善；有害随机对照 c030 从 Luna 2/16 到 Sol 16/16。s030 的三个澄清/担忧回复在 Sol 上仍只有 2/16、4/16、3/16，而 Sol 原生参考均为 16/16，说明更强模型没有自动消除这种交互困难；这些回复没有不可逆地修改 DB，不能仅凭失败断言任务不可行。尤其低 Sol 成功探针 c007/c010/c011/c012 仍有 1/2/4/3 条固定块真实成功，直接显示至少存在成功执行路径；探针标签不能读成任务绝对不可行。",
        "",
        "c007 与 c015 的充值量评分需特别谨慎：Sol 固定块分别有 4/16 与 10/16 仅未满足精确充值断言，全部其他任务断言已满足。尤其 c015 的 Sol 奖励为 0/16，仍不能概括成 16 次用户问题都未解决。两项 beneficial s034 回复都读取并披露移动数据关闭，没有在分叉直接改变断言；其中 c024 在 Sol 上 16/16，c023 只有 3/16，披露同一类事实不保证同等后续效果。",
        "",
    ]
    counts = collections.Counter(
        c["operational_class"]
        for c in a["cases"]
        if c["direction"] == "harmful" and not c["random_control"]
    )
    controls = collections.Counter(
        c["operational_class"]
        for c in a["cases"]
        if c["direction"] == "harmful" and c["random_control"]
    )
    lines += [
        f"1. 在筛选出的九个有害主要案例中，操作性分类为 {dict(counts)}；有害随机对照为 {dict(controls)}。分类只描述这些已筛选的固定块，多个块来自同一状态，不能外推为总体比例。五个低 Sol 成功探针中，三个来自同一 s030，固定块只是澄清/担忧且没有 DB 修改；另两个充值案例存在上述精确量评分问题，因此不能把这五项当成已证明的任务不可行，更不能据此断言多数是蓄意破坏。交互失败类直接说明更强 agent 在同一固定块上有更高成功率；低 Sol 成功且原生参考更好只是破坏/不可行探针，仍需机械证据才能证明不可行；unclear 保留不确定性。",
        "",
    ]
    single = b["conditions"]["single"]
    persist = b["conditions"]["persistent"]
    extra_failure = single["successes"] - persist["successes"]
    extra_transfer = (
        persist["failure_by_termination"]["transfer"]["numerator"]
        - single["failure_by_termination"]["transfer"]["numerator"]
    )
    solcomp = new["aggregate"]["large_drop"]["Sol_minus_Luna_v2"]
    v2comp = new["aggregate"]["large_drop"]["v2_minus_B1_single"]
    lines += [
        f"2. B1 单轮→持久额外 {extra_failure} 次失败，其中转人工失败净增加 {extra_transfer} 次。强制转人工遵守率见上表；普通用户自行 stop 的未满足断言案例很少，因此不能把下降主要描述成伙伴直接提前结束。统一 v2 在最大下降组相对 B1 single 的差为 {band(v2comp['mean'], v2comp['bootstrap_95_CI'])}；同组 Sol−Luna 为 {band(solcomp['mean'], solcomp['bootstrap_95_CI'])}。这些值与执行路径一起用于判断更强 agent 能否应对。agent 发起转人工可能受到伙伴行为影响，但账面分解不能证明中介因果；有限 DB 解析覆盖也不能排除忠实性漂移。",
        "",
        "## 证据、调用与审计",
        "",
        "[冻结 plan](plan.json)；[B2 预选状态](../v7_b2_b2_20261005/b2_selection.json)；[B1 全轨迹统计](../v7_b2_b_20261005/b1_summary.json)；[每个持久后续回合检查](../v7_b2_b_20261005/later_partner_turns.jsonl)；[B2 比较](../v7_b2_b2_20261005/comparison.json)；[审计](audit.json)；[脱敏调用量](token_accounting.json)。",
        "",
        table(
            [
                "步骤",
                "请求记录",
                "返回 prompt tokens",
                "返回 completion tokens",
                "错误 / 未返回",
            ],
            [
                [
                    s,
                    v["counts"].get("records", 0),
                    v["counts"].get("prompt_tokens", 0),
                    v["counts"].get("completion_tokens", 0),
                    f"{v['counts'].get('error', 0)} / {v['counts'].get('started', 0)}",
                ]
                for s, v in usage.items()
            ],
        ),
        "",
        "凭据 2/4 在运行中返回认证错误，按 [路由 amendment](plan_amendment_credential_routing.json) 改用既有授权凭据 1/3，只补齐未完成单元；模型、提示、温度及种子不改。一次空 UserMessage 的解析异常按既有任务重试处理，未记为任务失败。每次调用与重试分别写入步骤目录下 requests/；中断/失败而未返回的 provider token 用量未知，不推算。新输出只在 v7_b2_* 目录，历史证据哈希验证；九项测试使用合成输入、认证路由 mock 与无调用原生 replay，不进入实验。API 凭据不写入数据或报告。agent 与伙伴温度均为1，Sol 判断温度0；τ² 论文标准 user 温度为0；本轮原生参考温度1已具有多样性，结果不能直接外推为标准 benchmark practice 下的效应。所有置信区间均属探索性，未作本轮多重比较确认。",
    ]
    (x.OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("B2 REPORT COMPLETE", flush=True)


if __name__ == "__main__":
    report()
