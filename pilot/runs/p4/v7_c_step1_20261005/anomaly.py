"""Offline aligned trajectory evidence, schema/claim audits, and anomaly report."""

import collections
import json
import re

import c

read, save = c.read, c.save


def semantic(m):
    """Normalize random message metadata and tool ids, retaining executed content."""
    return {
        "role": m["role"],
        "content": m.get("content") or "",
        "requestor": m.get("requestor"),
        "tool_calls": [
            {
                "name": t["name"],
                "arguments": t["arguments"],
                "requestor": t.get("requestor"),
            }
            for t in m.get("tool_calls") or []
        ],
    }


def signature(messages):
    return c.x.p4.digest([semantic(m) for m in messages])


def next_agent(sim, end):
    return next(
        (c.mech.clean(m) for m in sim["messages"][end:] if m["role"] == "assistant"),
        None,
    )


def collect():
    """Audit all48 s010 persistent trajectories and every saved executed user turn."""
    p = read(c.OUT / "plan.json")
    task = read(c.OUT / "tasks.json")[p["state"]["task_id"]]
    data = {}
    totals = {}
    for name, d, branch, arm in [
        ("B1", c.B1, "tools", "persistent"),
        ("v2", c.B2, "tools_v2", "persistent_luna"),
    ]:
        replies = [read(f) for f in sorted((d / "replies").glob("s010*.json"))]
        lookup = {signature(r["prefix"]): r for r in replies}
        state_cache = {}

        def replay(messages):
            key = signature(messages)
            if key not in state_cache:
                state_cache[key] = c.mech.replay(task, messages)
            return state_cache[key]

        rows = []
        for j in range(6):
            initial = read(d / "replies" / f"s010:{branch}:d{j}.json")
            for rep in range(4):
                unit = f"s010:{arm}:d{j}:r{rep}"
                row = read(d / "continuations" / f"{unit}.json")
                sim = read(d / "trajectories" / f"{unit}.json")
                start = len(initial["prefix"]) - len(initial["partner_block"])
                blocks = c.mech.partner_blocks(sim["messages"], start)
                detailed = []
                for ordinal, indices in enumerate(blocks):
                    end = indices[-1] + 1
                    prefix = sim["messages"][: indices[0]]
                    block = [sim["messages"][i] for i in indices]
                    stored = lookup.get(signature(sim["messages"][:end]))
                    orch = replay(sim["messages"][:end])
                    before = replay(prefix)
                    errors = []
                    for m in block:
                        if m["role"] == "user":
                            errors.extend(
                                c.x.b.tool_candidate_errors(
                                    {
                                        "message": m.get("content"),
                                        "tool_calls": m.get("tool_calls"),
                                    },
                                    orch.user.tools,
                                )
                            )
                    request = next(
                        (m for m in reversed(prefix) if m["role"] == "assistant"), {}
                    )
                    mandated = (
                        "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
                        in (request.get("content") or "").upper()
                    )
                    transfer = any(
                        "###TRANSFER###" in (m.get("content") or "")
                        for m in block
                        if m["role"] == "user"
                    )
                    check = c.mech.check_claims(
                        prefix, block, orch.environment, before.environment
                    )
                    state_match = (
                        c.x.p4.state(orch.environment) == stored["state_after_partner"]
                        if stored
                        else None
                    )
                    if state_match is False:
                        raise AssertionError(
                            "Saved proposal DB does not replay: " + unit
                        )
                    detailed.append(
                        {
                            "ordinal": ordinal,
                            "message_indices": indices,
                            "preceding_request": c.mech.clean(request),
                            "block": [c.mech.clean(m) for m in block],
                            "next_agent": next_agent(sim, end),
                            "stored_reply_unit": stored["unit"] if stored else None,
                            "validator_version": stored.get(
                                "native_validation_version", "strict_xor_v1"
                            )
                            if stored
                            else "unmapped",
                            "fidelity_verdict": stored.get("fidelity")
                            if stored
                            else None,
                            "schema_errors": errors,
                            "mandated_transfer": mandated,
                            "transfer_compliant": transfer
                            and not any(m.get("tool_calls") for m in block)
                            if mandated
                            else None,
                            "unexpected_transfer": transfer and not mandated,
                            "state_after_matches_saved": state_match,
                            "claim_check": check,
                        }
                    )
                term = (
                    "transfer"
                    if any(
                        "###TRANSFER###" in (m.get("content") or "")
                        for m in sim["messages"][start:]
                        if m["role"] == "user"
                    )
                    else row["termination_reason"]
                )
                item = {
                    "unit": unit,
                    "j": j,
                    "rep": rep,
                    "reward": row["reward"],
                    "termination": term,
                    "assertions_final": row["assertions_final"],
                    "partner_turns": detailed,
                }
                rows.append(item)
                print("AUDIT", unit, "blocks", len(detailed), flush=True)
        data[name] = rows
        allblocks = [b for r in rows for b in r["partner_turns"]]
        totals[name] = {
            "successes": sum(r["reward"] == 1 for r in rows),
            "n": len(rows),
            "termination": dict(collections.Counter(r["termination"] for r in rows)),
            "partner_turns": len(allblocks),
            "schema_error_turns": sum(bool(b["schema_errors"]) for b in allblocks),
            "unmapped_turns": sum(b["stored_reply_unit"] is None for b in allblocks),
            "saved_db_mismatches": sum(
                b["state_after_matches_saved"] is False for b in allblocks
            ),
            "mandated_transfer_turns": sum(b["mandated_transfer"] for b in allblocks),
            "noncompliant_transfer_turns": sum(
                b["transfer_compliant"] is False or b["unexpected_transfer"]
                for b in allblocks
            ),
            "DB_incorrect_claims": sum(
                b["claim_check"]["incorrect_claim_n"] for b in allblocks
            ),
            "unobserved_claims": sum(
                b["claim_check"]["unobserved_claim_n"] for b in allblocks
            ),
            "unassessed_sentences": sum(
                len(b["claim_check"]["unassessed_device_sentences"]) for b in allblocks
            ),
        }
    differences = []
    for a, b in zip(data["B1"], data["v2"]):
        ab, bb = a["partner_turns"], b["partner_turns"]
        i = next(
            (
                i
                for i in range(min(len(ab), len(bb)))
                if signature(ab[i]["block"]) != signature(bb[i]["block"])
            ),
            None,
        )
        differences.append(
            {
                "B1_unit": a["unit"],
                "v2_unit": b["unit"],
                "alignment": "same draw/rep index, independent random suffixes; descriptive",
                "first_divergent_partner_ordinal": i,
                "B1_turn": ab[i] if i is not None else None,
                "v2_turn": bb[i] if i is not None else None,
                "B1_termination": a["termination"],
                "v2_termination": b["termination"],
            }
        )
    save(c.OUT / "trajectory_audit.json", {"totals": totals, "trajectories": data})
    save(c.OUT / "trajectory_diffs.json", differences)
    # Exact textual evidence: fixed branch request explicitly asks two separate actions.
    # No LLM labels or broad semantic classifier is introduced here.
    branch_evidence = []
    for j in range(6):
        r = read(c.B2 / "replies" / f"s010:tools_v2:d{j}.json")
        t = r["candidate"]["message"] or ""
        reversal = bool(
            re.search(r"^(?:please |go ahead and )?disconnect the vpn now\.", t, re.I)
        )
        branch_evidence.append(
            {
                "j": j,
                "preceding_agent_request": r["prefix"][-len(r["partner_block"]) - 1][
                    "content"
                ],
                "selected": r["candidate"],
                "fidelity": r["fidelity"],
                "explicit_action_role_reversal": reversal,
                "required_one_action_clarification_absent": not bool(
                    re.search(
                        r"one (?:action|step)|single (?:action|step)|multiple actions|at a time",
                        t,
                        re.I,
                    )
                ),
                "scope": "Exact saved branch wording only. Role-reversal matcher recognizes direct imperatives, not inferred intent.",
            }
        )
    save(
        c.OUT / "protocol_defect.json",
        {
            "bug": True,
            "component": "VS proposal/fidelity enforcement of native multi-action guideline",
            "guideline_path": "data/tau2/user_simulator/simulation_guidelines_tools.md",
            "guideline_quote": "If the agent asks multiple actions to perform, state that you cannot perform multiple actions at once, and ask the agent to instruct you one action at a time.",
            "preceding_request": "Please disconnect the VPN next, then run a speed test to check your mobile data performance.",
            "evidence": branch_evidence,
            "root_scope": "Schema-valid text proposals do not enforce this semantic protocol rule; all six accepted branch replies omit mandated one-action clarification. Four issue an explicit reverse request to the agent. Fidelity judgments accepted all six. This is a filtering/proposal protocol defect, not a DB replay or reward bug. It does not prove all of the success drop is caused by this defect.",
            "Step3": "not launched, per user bug-stop instruction",
        },
    )
    return totals


def report():
    """Write the completed first-two-step report with raw costs and score CIs."""
    audit = read(c.OUT / "trajectory_audit.json")
    rows = [read(f) for f in sorted((c.OUT / "continuations").glob("*.json"))]
    assert len(rows) == 12
    successes = sum(r["reward"] == 1 for r in rows)
    ci = list(c.x.stats.wilson(successes, 12))
    bydraw = [
        {
            "j": j,
            "successes": sum(r["reward"] == 1 for r in rows if r["j"] == j),
            "n": 2,
        }
        for j in range(6)
    ]
    counts = collections.Counter(
        "transfer"
        if any(
            "###TRANSFER###" in (m.get("content") or "")
            for m in read(c.OUT / "trajectories" / f"{r['unit']}.json")["messages"]
            if m["role"] == "user"
        )
        else r["termination_reason"]
        for r in rows
    )
    save(
        c.OUT / "single_control.json",
        {
            "successes": successes,
            "n": 12,
            "Wilson95_CI": ci,
            "by_draw": bydraw,
            "termination": dict(counts),
            "difference_vs_v2_persistent": {
                "difference": successes / 12 - 6 / 24,
                "Newcombe95_CI": c.x.stats.difference_interval(successes, 12, 6, 24),
            },
            "sampling_unit_caveat": "6 reused branch draws x2 fresh suffixes. Score intervals treat suffixes as independent conditional draws; shared branch and historical contrasts not a randomized version test.",
        },
    )
    calls = [read(f) for f in (c.OUT / "requests").glob("*.json")]
    tokens = {
        "request_records": len(calls),
        "returned_usage_requests": sum(q.get("usage") is not None for q in calls),
        "unknown_usage_requests": sum(q.get("usage") is None for q in calls),
        "by_role": {},
    }
    for role in sorted({q["role"] for q in calls}):
        qs = [q for q in calls if q["role"] == role]
        tokens["by_role"][role] = {
            "requests": len(qs),
            "prompt_tokens": sum(
                (q.get("usage") or {}).get("prompt_tokens", 0) for q in qs
            ),
            "completion_tokens": sum(
                (q.get("usage") or {}).get("completion_tokens", 0) for q in qs
            ),
            "total_tokens": sum(
                (q.get("usage") or {}).get("total_tokens", 0) for q in qs
            ),
            "unknown_usage_requests": sum(q.get("usage") is None for q in qs),
        }
    save(c.OUT / "token_accounting.json", tokens)
    p = read(c.OUT / "plan.json")
    changed = [
        name
        for name, digest in p["historical_sha256"].items()
        if c.sha(c.ROOT / name) != digest
    ]
    assert not changed
    save(
        c.OUT / "audit.json",
        {
            "historical_inputs_checked": len(p["historical_sha256"]),
            "historical_inputs_changed": changed,
            "new_suffixes": len(rows),
            "mechanical_replays": len(read(c.OUT / "mechanical_replay.json")),
            "Step3_started": False,
            "reason": "Native multi-action guideline missing from accepted branch behavior despite faithful=True",
            "code_sha256": {f.name: c.sha(f) for f in c.OUT.glob("*.py")},
            "frozen_plan_sha256": c.sha(c.OUT / "plan.json"),
        },
    )
    lines = [
        "# Tier C Step1：s010 异常核查",
        "",
        "发现的是 VS 候选/忠实性过滤的原生协议漏检；严格重放没有发现 DB 或奖励记录错误。按用户要求，Step3 未启动。",
        "",
        "|设置|成功/续写|终止类型|",
        "|---|---|---|",
    ]
    for name, v in audit["totals"].items():
        lines.append(
            f"|{name} persistent|{v['successes']}/{v['n']}|{v['termination']}|"
        )
    lines.append(
        f"|新 single-turn v2|{successes}/12，Wilson95% CI {ci}|{dict(counts)}|"
    )
    lines += [
        "",
        "新 single-turn 对照复用六个 v2 分支块，每块两次新续写，后续伙伴恢复 native；agent/partner temperature 保持1.0。按 draw 的原始结果见 [single_control.json](single_control.json)。该比较能检查分支块本身是否仍有影响，但历史批次并非配对随机版本实验，不能把差异全归因于 validator。",
        "",
        "## 具体改变和 bug 证据",
        "",
        "分支前客服的请求是：`Please disconnect the VPN next, then run a speed test to check your mobile data performance.` 原生规则明确规定，多动作请求必须要求客服一次指示一个动作。B1 的多个回复请求确认或一次一个动作，另一些执行了 VPN 工具；v2 的六个固定块都未执行工具，也都没有要求一次一个动作，四个直接要求客服断开 VPN。例：`Disconnect the VPN now. After that, I want a speed test...`。随后客服可能认为设备操作不在自己的工具集中并转人工。",
        "",
        "全部六块均得到 Sol 忠实性模型的 `faithful=true`。这是保存下来的模型判断，不是合规真值。schema validator 检查 JSON 和工具参数，未覆盖多动作语义规则；过滤器因此接受了违反原生协议的分支回复。此证据支持协议过滤缺陷，不能证明18个失败全部由此导致。",
        "",
        "[protocol_defect.json](protocol_defect.json) 保存原规则逐字引用及六个候选；[trajectory_diffs.json](trajectory_diffs.json) 保存24组首个伙伴差异、文本、工具、版本、忠实性 verdict、客服下一动作和终止类型。draw/rep 对齐只用于阅读，续写噪声并不配对。",
        "",
        "## 重放和后续回合核查",
        "",
        "6 个 v2 失败和6 个 B1 成功均严格机械重放，变更工具的返回值重放校验通过，最终断言向量与保存值相同，原生 evaluator 重算 reward 也相同。12 个重放未调用模型。B1/B2 未独立保存每条 suffix 的完整最终 DB，所以报告提供重新重放所得 DB 和断言对照，不声称对比不存在的 DB 快照。",
        "",
        "|历史条件|伙伴回合|schema 错误回合|未映射保存 proposal|保存 DB 不一致|transfer 违规回合|解析到的错误事实/未观察事实|未解析设备句|",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, v in audit["totals"].items():
        lines.append(
            f"|{name}|{v['partner_turns']}|{v['schema_error_turns']}|{v['unmapped_turns']}|{v['saved_db_mismatches']}|{v['noncompliant_transfer_turns']}|{v['DB_incorrect_claims']}/{v['unobserved_claims']}|{v['unassessed_sentences']}|"
        )
    lines += [
        "",
        "事实核查沿用冻结的 B2 机械解析器；未解析句子是未知，不能据此宣称不存在私有状态违背。后续每个映射回合的 verdict、执行字段及事实核查在 [trajectory_audit.json](trajectory_audit.json)。transfer 计数不等同于伙伴自行结束；保存的客服下一动作可检查实际来源。",
        "",
        "冻结解析器把 B1 的一句过去时 `The VPN was connected ... but I’ve disconnected it` 标成当前 DB 不匹配：这是可由原文本和先前工具执行辨识的时态假阳性，不能当作实际错误报告。原始解析数保留，未重写解析器。协议漏检也不代表 v2 validator 代码新引入了问题；B1 与 v2 都沿用相同的语义过滤，旧批次亦有多动作工具执行。版本差异、候选抽样和独立续写均混杂。\n\nStep2 的全部15个案例已按新规则重分类，见 [分类报告](../v7_c_step2_20261005/report.md)。规则在任何新续写前冻结；多类命中与聚合约定均公开。",
        "",
        "## 成本和下一步",
        "",
        "本轮仅新增12次 suffix，零新 proposal/judge，agent/partner 调用均保存在独立 redacted request ledger。"
        + json.dumps(tokens, ensure_ascii=False)
        + "。历史输入 hash 检查通过。",
        "",
        "Step3 尚未运行。应先明确修复上述原生协议漏检，再冻结搜索比较的定义和全部预算拆分。当前不能把 v2 persistent 当作已确认原生忠实的搜索生成器。",
    ]
    (c.OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    import sys

    if sys.argv[1] == "collect":
        collect()
    else:
        report()
