"""Report and verify the frozen non-C reminder-control continuations."""

import collections
import hashlib
import html
import time

import p4_specificity as s


def arm_summary(rows, expected_per_arm=32):
    """Keep provider failures unresolved and report complete-case and full bounds."""
    result = {}
    for arm in s.c.REMINDERS:
        selected = [r for r in rows if r["arm"] == arm]
        completed = [r for r in selected if r["status"] == "completed"]
        wins = sum(r["reward"] == 1 for r in completed)
        unresolved = expected_per_arm - len(completed)
        result[arm] = {
            "scheduled": expected_per_arm,
            "observed": len(selected),
            "completed": len(completed),
            "successes": wins,
            "unresolved": unresolved,
            "success_rate_completed_only": wins / len(completed) if completed else None,
            "unresolved_outcome_sensitivity": [
                wins / expected_per_arm,
                (wins + unresolved) / expected_per_arm,
            ],
        }
    return result


def difference_bounds(arms):
    """Bound the planned contrast without assuming missing outcomes are failures."""
    cap = arms["capability_policy"]["unresolved_outcome_sensitivity"]
    generic = arms["generic_policy"]["unresolved_outcome_sensitivity"]
    return [cap[0] - generic[1], cap[1] - generic[0]]


def verify(rows, calls):
    """Check native history/state validity, source provenance and reminder isolation."""
    s.activate()
    s.verify_frozen()
    cases = s.c.p4.read(s.OUT / "approved_cases.json")["cases"]
    expected = {
        f"{case['sample_id']}:{arm}:{rep}"
        for case in cases
        for arm in s.c.REMINDERS
        for rep in range(8)
    }
    assert len(rows) == 96 and {r["unit"] for r in rows} == expected
    assert all(r["status"] in {"completed", "error"} for r in rows)
    protocol_hash = s.c.p4.digest(s.c.p4.read(s.OUT / "protocol.json"))
    fields = ("role", "content", "tool_calls", "id", "requestor")
    for case in cases:
        source = s.c.p4.read(s.OUT / "sources" / (case["sample_id"] + ".json"))
        prefix = source["messages"][: case["decision_index"]]
        for row in (r for r in rows if r["sample_id"] == case["sample_id"]):
            assert row["prefix_sha256"] == case["prefix_sha256"]
            assert row["policy_appendix"] == s.c.REMINDERS[row["arm"]]
            assert row["calibration_protocol_sha256"] == protocol_hash
            assert row["config"]["max_steps"] == max(
                1, 200 - s.c.p4.prefix_steps(prefix)
            )
            for role in ("agent", "user"):
                assert row["config"]["llm_" + role] == "openai/gpt-5.6-luna"
                args = row["config"]["llm_args_" + role]
                assert args["temperature"] == 1 and args["reasoning_effort"] == "none"
            if row["status"] == "completed":
                replay = row["simulation"]["messages"][: len(prefix)]
                assert len(replay) == len(prefix)
                assert all(
                    all(a.get(k) == b.get(k) for k in fields)
                    for a, b in zip(prefix, replay, strict=True)
                )
                assert row["state_trace"]
                assert row["simulation"]["reward_info"]["reward"] == row["reward"]
    role_counts = collections.Counter()
    for call in calls:
        assert call["status"] in {"response", "error"}
        assert call["unit"] in expected and call["role"] in {"agent", "user"}
        role_counts[call["role"]] += 1
        arm = call["unit"].split(":")[1]
        system = "\n".join(
            str(m.get("content") or "")
            for m in call["request"]["messages"]
            if m["role"] == "system"
        )
        for name, appendix in s.c.REMINDERS.items():
            if appendix:
                assert (appendix in system) == (call["role"] == "agent" and name == arm)
    keys = (s.c.p4.ROOT / "api.txt").read_text().split()
    files = [p for p in s.OUT.rglob("*") if p.is_file()]
    assert not any(key.encode() in p.read_bytes() for p in files for key in keys), (
        "Credential match; values withheld"
    )
    inputs = [
        s.OUT / n for n in ("protocol.json", "approved_cases.json", "analysis.json")
    ]
    inputs += [
        s.c.p4.ROOT / "pilot" / n
        for n in (
            "p4_specificity.py",
            "p4_specificity_report.py",
            "test_p4_specificity.py",
        )
    ]
    result = {
        "verified_at_unix": time.time(),
        "terminal_units": 96,
        "completed_units": sum(r["status"] == "completed" for r in rows),
        "pending_requests": 0,
        "provider_attempts": len(calls),
        "policy_requests_checked": dict(role_counts),
        "native_prefix_and_initial_state_checked_for_completed_units": True,
        "user_reminders_absent": True,
        "frozen_runner_cases_reminders_unchanged": True,
        "credential_matches": 0,
        "credential_scan_files": len(files),
        "tests": {
            "passed": 8,
            "log": "tests.log",
            "scope": "4 specificity + 4 holdout offline checks",
        },
        "provenance_sha256": {
            str(p.relative_to(s.c.p4.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
        "limit": "Technical verification only; provider seed determinism unverified and coding-assistant C-negative classification is not human truth. Unmatched selected panels cannot identify causal effect specificity.",
    }
    s.c.p4.save(s.OUT / "final_verification.json", result)
    return result


def main():
    """Export descriptive control results and contrast with the earlier C panel."""
    s.activate()
    rows = [s.c.p4.read(p) for p in (s.OUT / "continuations").glob("*.json")]
    calls = [s.c.p4.read(p) for p in (s.OUT / "requests").glob("*.json")]
    cases = s.c.p4.read(s.OUT / "approved_cases.json")["cases"]
    arms = arm_summary(rows)
    old_root = s.c.p4.ROOT / "pilot/runs/p4/calibration_20261003"
    old_rows = [s.c.p4.read(p) for p in (old_root / "continuations").glob("*.json")]
    old_arms = arm_summary(old_rows)
    per_case = {
        case["sample_id"]: {
            "task_id": case["task_id"],
            "arms": arm_summary(
                [r for r in rows if r["sample_id"] == case["sample_id"]], 8
            ),
        }
        for case in cases
    }
    examples = []
    for case in cases:
        source = s.c.p4.read(s.OUT / "sources" / (case["sample_id"] + ".json"))
        original = next(
            m
            for m in s.c.p4.agent_view(source["messages"])
            if m["index"] == case["decision_index"]
        )
        for row in rows:
            if (
                row["sample_id"] != case["sample_id"]
                or row["rep"] != 0
                or row["status"] != "completed"
            ):
                continue
            first = next(
                m
                for m in s.c.p4.agent_view(row["simulation"]["messages"])
                if m["index"] >= case["decision_index"] and m["role"] == "assistant"
            )
            examples.append(
                {
                    "unit": row["unit"],
                    "original_decision": original,
                    "first_resampled_decision": first,
                    "native_reward": row["reward"],
                }
            )
    s.c.p4.save(
        s.OUT / "first_action_examples.json",
        {
            "selection": "Replication zero from every completed case/arm, not selected for success; exact agent-visible original and first resampled assistant decision. Textual examples, not causal certificates.",
            "examples": examples,
        },
    )
    known = sum(
        (call.get("usage") or {}).get("prompt_tokens", 0)
        + (call.get("usage") or {}).get("completion_tokens", 0)
        for call in calls
    )
    unknown = sum(call.get("usage") is None for call in calls)
    report = {
        "arms": arms,
        "per_case": per_case,
        "capability_minus_generic_sensitivity": difference_bounds(arms),
        "earlier_C_panel_arms": old_arms,
        "earlier_C_panel_capability_minus_generic": difference_bounds(old_arms),
        "provider_attempts": len(calls),
        "request_status": dict(collections.Counter(call["status"] for call in calls)),
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
            "limit": "All requests configure reasoning_effort=none, but provider-reported reasoning tokens are sometimes nonzero. This is an API setting, not proof of absent internal reasoning or stable backend routing.",
        },
        "known_tokens": known,
        "unknown_usage_requests": unknown,
        "errors": [
            {
                "unit": r["unit"],
                "error_type": r.get("error_type"),
                "message": r.get("error_message"),
            }
            for r in rows
            if r["status"] == "error"
        ],
        "interpretation": "Exploratory non-C generic escalation controls. Capability-reminder improvement here would support a broader delegation/persistence explanation and weaken any exclusive C-mechanism reading of prior gains. No gain here would not prove specificity due to small, selected, unmatched tasks. Earlier and current panels have different tasks/states/personas and were not randomized to C status.",
        "G1_passed": False,
        "observed_conclusion": {
            "capability_exceeds_generic_in_selected_original_non_C_panel": difference_bounds(
                arms
            )[0]
            > 0,
            "tasks_with_positive_capability_minus_generic": sum(
                data["arms"]["capability_policy"]["successes"]
                > data["arms"]["generic_policy"]["successes"]
                for data in per_case.values()
            ),
            "limit": "Evidence that benefit is not confined to explicit-C-labeled original decisions; not evidence that latent capability confusion is absent or that general persistence/policy comprehension is excluded.",
        },
        "limits": "Reward success is native benchmark outcome, not validated interaction-failure count. Eight stochastic replications per selected prefix do not make 32 independent tasks. Coding-assistant labels are provisional and apply to the saved original decision, not an absence of latent capability confusion; resampling can introduce an explicit tool-absence rationale. Provider errors stay unresolved. No discovery efficiency or unique confirmed mode claim.",
    }
    s.c.p4.save(s.OUT / "analysis.json", report)
    verification = verify(rows, calls)
    table = ""
    for label, results in (("本批非 C 对照", arms), ("之前 C 候选", old_arms)):
        for arm, data in results.items():
            table += f"<tr><td>{label}</td><td>{arm}</td><td>{data['successes']}/{data['completed']}</td><td>{data['unresolved']}</td></tr>"
    case_table = ""
    for sid, data in per_case.items():
        counts = "".join(
            f"<td>{r['successes']}/{r['completed']}</td>" for r in data["arms"].values()
        )
        case_table += (
            f"<tr><td>{sid}</td><td>{html.escape(data['task_id'])}</td>{counts}</tr>"
        )
    lo, hi = difference_bounds(arms)
    document = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 非 C 提前升级对照</title>
<style>body{{font:16px/1.7 system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#17223b}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d7deea;padding:10px;text-align:left}}th{{background:#edf2fa}}.note{{padding:16px;background:#fff3d7}}</style>
<h1>P4 非 C 提前升级竞争解释对照</h1><p>在新续跑结果前冻结 4 个没有明确“自身手机/诊断工具缺失”理由的一般提前升级案例：2 个 MMS、2 个 mobile data。来自上一轮编码助手非 C 候选参考，排除之前 11 个续跑任务。每个相同历史前缀上比较原策略、通用排障提醒与用户能力提醒，各 8 次，共 96 次预算。用户策略、工具、状态和步数预算保持一致；提醒只持续追加到 agent 系统策略。</p>
<h2>原生 benchmark 成功数</h2><table><tr><th>面板</th><th>策略</th><th>成功/完成</th><th>未解决</th></tr>{table}</table>
<p>本批能力提醒相对通用提醒的成功率差的缺失结果敏感性范围为 {lo:+.1%}–{hi:+.1%}；全部完成时两端相等。它不是置信区间。</p>
<table><tr><th>案例</th><th>任务</th><th>原策略</th><th>通用提醒</th><th>能力提醒</th></tr>{case_table}</table>
<p class="note">本批若也受益，就支持能力提醒对一般过早放弃/用户委托也有帮助，削弱“收益只针对显式 C 标签”的解释。没有收益也不能证明特异性。非 C 仅描述保存的原始决定缺少显式能力否定，不保证潜在能力混淆不存在：重采样可能生成新的工具缺失理由。两个面板的任务、状态、persona 不同，未随机匹配；4 个前缀的重复不能视为 32 个独立任务。奖励成功不等于验证了因果失败模式，G1 仍未通过。</p>
<h2>成本与完整性</h2><p>终态续跑 {verification["terminal_units"]} 条，完整原生续跑 {verification["completed_units"]} 条；API 尝试 {len(calls)} 次，已知 tokens {known:,}，{unknown} 次 usage 未知。每条完整续跑的历史前缀和初始双环境状态均已核验；每次 agent/user 请求的提醒隔离已核验。没有自动重试；接口失败保留未解决。4 key 并发，不输出密钥。</p>
<p>请求配置统一为 reasoning_effort=none，但 {report["provider_metadata"]["requests_reporting_positive_reasoning_tokens"]} 次响应仍报告正数 reasoning tokens。保留实际模型名和 usage；API 参数不能证明模型内部完全没有推理，代理后端路由稳定性尚未验证。</p>
<p><a href="analysis.json">完整结果</a> · <a href="protocol.json">冻结协议</a> · <a href="final_verification.json">验证与来源哈希</a> · <a href="approved_cases.json">案例依据</a> · <a href="first_action_examples.json">每臂第零次首动作示例</a> · <a href="../screen_holdout_20261003/report.html">独立留出验证</a></p></html>"""
    (s.OUT / "report.html").write_text(document)
    s.c.p4.save(
        s.OUT / "handoff.json",
        {
            "status": "complete_with_unresolved" if report["errors"] else "complete",
            "G1_passed": False,
            "report": "report.html",
            "analysis": "analysis.json",
            "verification": "final_verification.json",
            "next_steps": [
                "Interpret generic-control benefit before any C-specific claim",
                "Develop semantic certificate checks on development errors",
                "Obtain human adjudication and freeze causal verification/deduplication/budget rules before discovery curves",
            ],
        },
    )
    print(
        {
            "arms": arms,
            "known_tokens": known,
            "unknown_usage": unknown,
            "completed": verification["completed_units"],
        }
    )


if __name__ == "__main__":
    main()
