import importlib.util
import json
from pathlib import Path

out = Path("pilot/runs/p4/v7_c2_step2_action_20261007")
spec = importlib.util.spec_from_file_location("audit", out / "analyze_actions.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def block(
    tool="set_network_mode_preference",
    args=None,
    error=False,
    text="Where should I press?",
    output="ok",
):
    return [
        {
            "role": "user",
            "content": text,
            "tool_calls": [
                {
                    "id": "t",
                    "name": tool,
                    "arguments": args or {"mode": "4g_5g_preferred"},
                }
            ],
        },
        {
            "role": "tool",
            "requestor": "user",
            "id": "t",
            "content": output,
            "error": error,
        },
    ]


req = {"device_operations": [a.REQUEST_PATTERNS[0]], "purchase_amount_requested": False}
db = {"user": {"device": {"network_mode_preference": "4g_5g_preferred"}}}
check(
    "asked_after_successful_requested_action_is_not_omission",
    not a.features(block(), req, {}, db)["no_requested_operation_then_question"],
)
check(
    "wrong_mode_is_not_requested_action",
    a.features(block(args={"mode": "2g_only"}), req, {}, db)[
        "no_requested_operation_then_question"
    ],
)
check(
    "tool_error_is_not_executed",
    a.features(block(error=True), req, {}, db)["no_requested_operation_then_question"],
)
check(
    "read_only_tool_is_not_requested_mutation",
    a.features(block(tool="get_network_mode_preference"), req, {}, db)[
        "no_requested_operation_then_question"
    ],
)
check(
    "no_request_is_not_noncompliance",
    not a.features(
        [{"role": "user", "content": "Could you help?"}],
        {"device_operations": [], "purchase_amount_requested": False},
    )["no_requested_operation_then_question"],
)
r = {"device_operations": [a.REQUEST_PATTERNS[2]], "purchase_amount_requested": False}
f = a.features(block(tool="run_speed_test", args={}, output="No Connection"), r)
check(
    "no_connection_is_executed_diagnostic",
    f["any_requested_operation_executed"] and f["negative_speed_test_observed"],
)
f = a.features(
    [
        {
            "role": "user",
            "content": "Please add 1GB now, then add remaining 1GB if necessary.",
        }
    ],
    {"device_operations": [], "purchase_amount_requested": True},
)
check("conditional_remaining_amount_not_current_consent", f["consent_gb_now"] == 1)
rows = json.loads((out / "per_case.json").read_text())["cases"]
check("all_confirmed_cases_included", len(rows) == 15)
check(
    "all_harmful_cases_included", sum(r["direction"] == "harmful" for r in rows) == 10
)
for cid in ["c010", "c011", "c012"]:
    row = next(r for r in rows if r["candidate_id"] == cid)
    s = row["suffix_outcomes"]["native"]["omission_and_question"]
    check(
        cid + "_native_omission_recovers",
        s["success"]["matches"]
        == s["success"]["draws"]
        == s["next_partner_first_requested_tool_count"],
    )
extra = []
for row in rows:
    entry = {
        "candidate_id": row["candidate_id"],
        "state_id": row["state_id"],
        "features": {},
    }
    for feature in [
        "any_requested_operation_executed",
        "none_requested_without_question",
        "amount_requested_but_no_numeric_consent",
        "negative_speed_test_observed",
    ]:
        if not row["fixed_features"][feature]:
            continue
        entry["features"][feature] = {
            batch: a.rate(sum(r["features"][feature] for r in row[raw]), len(row[raw]))
            for batch, raw in [
                ("original_q", "paired_raw"),
                ("independent_native", "independent_raw"),
            ]
        }
    extra.append(entry)
(out / "verification.json").write_text(
    json.dumps(
        {
            "new_model_calls": 0,
            "checks_passed": checks,
            "additional_existing_feature_frequencies": extra,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
lines = [
    "",
    "## 结论与补充核对",
    "",
    "s030 的“原生几乎从不当轮不执行、先提问”解释不成立。原始 q 是 4/6；独立参考是 5/16、5/16、8/16。这些参考续写全部成功，而且全部在下一伙伴回合执行了要求的网络模式切换。候选固定块依然降低成功率，但这个动作特征不足以单独解释效果。c010 的下一 agent 动作有 9/16 直接转人工，而原生上述提问子集全部继续自然语言沟通。转人工也可能发生在任务已成功之后，不能直接当作失败。",
    "",
    "s008 的对应原生频率是 0/6、0/16；这支持该特征在这批样本中少见，但 0/16 的 Wilson 95% 上限是 19.4%，并不证明原生不会产生。",
    "",
    "10 个有害例子的特征构成：4 个未执行且提问（c003、c010–c012）；2 个授权 1GB（c007、c015，其中 c007 也未执行漫游但没提问）；1 个暂不给购买量授权（c009）；1 个开场信息差异（c000）；2 个已经执行请求却仍有害（c020、c030）。这是程序化描述，不是新的人工作因果分类。c000 的具体致因尚未确定。",
    "",
    "|案例|候选已经出现的程序特征|原始 q 同特征|独立原生同特征|",
    "|---|---|---|---|",
]
for entry in extra:
    if not entry["features"]:
        continue
    for key, rates in entry["features"].items():
        lines.append(
            f"|{entry['candidate_id']}|{key}|{a.count_string(rates['original_q'])}|{a.count_string(rates['independent_native'])}|"
        )
lines += [
    "",
    "这里只比较各个已定义特征，不把特征边际频率当成整段回复的等价频率。c020 的候选执行漫游并授权 2GB；c030 的候选执行测速并报告 No Connection，因此都不是“当轮没有执行”例子。",
    "",
    "### 1GB 与精确评分断言",
    "",
    "c007/s023 与 c015/s035 的原生授权 1GB 均为 0/6、0/16。候选后续 agent 实际购买量主要/全部为 1GB，而原生均为 2GB。区别首先是购买授权量，不是单纯有无执行。",
    "",
    "|案例|Luna 候选失败数|其中仅精确容量断言失败|Sol 候选失败数|其中仅精确容量断言失败|",
    "|---|---|---|---|---|",
]
for cid in ["c007", "c015"]:
    d = json.loads(
        (Path("pilot/runs/p4/v7_b2_a_20261005/a2_cases") / (cid + ".json")).read_text()
    )["assertion_diagnostic"]
    luna_result, s = d["Luna_fixed"], d["Sol_fixed"]
    lines.append(
        f"|{cid}|{luna_result['failures']}/16|{luna_result['sole_unmet_exact_refueling_n']}/{luna_result['failures']}|{s['failures']}/16|{s['sole_unmet_exact_refueling_n']}/{s['failures']}|"
    )
lines += [
    "",
    "仅精确容量失败表示其他保存的任务断言都满足；不将其当作排障失败。其余失败还存在其他未满足断言。选择 1GB 符合该回合 up-to-2GB 的授权选项，不能据此断言用户破坏任务。保持原有类别定义，不因这份补充审计修改历史类别。",
    "",
    "本轮使用 15 份个案卡、每案 16 条独立原生参考和 16 条候选续写（共 480 条 Luna 续写）及原始 q 回复；共享状态的原始 q 不作为多组独立观测合并。所有频率、Wilson 区间和逐条路径已保存。程序边界核对及数量/后续路径核对共 "
    + str(len(checks))
    + " 项通过，见 verification.json。没有任何新模型调用。搜索比较仍待余额恢复，已有未完成筛选不能支持效率结论。",
]
with (out / "report.md").open("a") as f:
    f.write("\n".join(lines) + "\n")
print("Verified", len(checks), "checks; finalized report")
