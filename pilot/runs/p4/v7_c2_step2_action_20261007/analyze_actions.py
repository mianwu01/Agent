"""Offline requested-action, consent-quantity and saved-suffix audit; no LLM calls."""

import collections
import datetime
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = ROOT / "pilot/runs/p4"


def read(path):
    return json.loads(path.read_text())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def speech(message):
    value = message.get("content") or ""
    try:
        obj = json.loads(value)
        if isinstance(obj, dict):
            return obj.get("message", value)
    except (ValueError, TypeError):
        pass
    return value


def rate(k, n):
    if not n:
        return {"matches": k, "draws": n, "rate": None, "Wilson95_CI": None}
    z = 1.959963984540054
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {
        "matches": k,
        "draws": n,
        "rate": p,
        "Wilson95_CI": [center - half, center + half],
    }


REQUEST_PATTERNS = [
    {
        "id": "set_network_4g5g",
        "pattern": r"\bchange\b[^.!?]{0,160}\bnetwork\b[^.!?]{0,100}4g\s*/\s*5g",
        "tool": "set_network_mode_preference",
        "arguments": {"mode": "4g_5g_preferred"},
        "target_field": "network_mode_preference",
        "target_value": "4g_5g_preferred",
    },
    {
        "id": "reboot",
        "pattern": r"\b(?:restart|reboot)(?: the phone| your phone| it)?\b",
        "tool": "reboot_device",
        "arguments": {},
    },
    {
        "id": "test_connection",
        "pattern": r"\b(?:try (?:the internet|mobile data)|test the connection|run (?:a |the )?speed test)\b",
        "tool": "run_speed_test",
        "arguments": {},
    },
    {
        "id": "enable_roaming",
        "pattern": r"\b(?:make sure|turn on|enable)\b[^.!?]{0,80}\bdata roaming\b[^.!?]{0,50}\b(?:enabled|on)\b",
        "tool": "toggle_roaming",
        "alternative_tools": ["turn_roaming_on"],
        "arguments": {},
        "target_field": "roaming_enabled",
        "target_value": True,
    },
]
CONSENT_REQUEST = r"\bhow (?:much|many)\b[^.!?]{0,70}\blike to add\b"
CONSENT_AMOUNT = r"(?:please\s+)?(?:add|adding|full|another|remaining)\s+(?:the\s+)?(?:full\s+)?(\d+(?:\.\d+)?|one|two)\s*(?:gb|gigabytes?)\b"
QUESTION_PATTERN = r"\?|\b(?:could you|can you|should i|will it|what should|where should|please (?:tell|explain|clarify))\b"


def requests(message):
    value = speech(message).lower().replace("**", "")
    found = []
    for spec in REQUEST_PATTERNS:
        match = re.search(spec["pattern"], value)
        if match:
            found.append(
                {**spec, "request_span": match.group(0), "start": match.start()}
            )
    found.sort(key=lambda x: x["start"])
    return {
        "text": speech(message),
        "device_operations": found,
        "purchase_amount_requested": bool(re.search(CONSENT_REQUEST, value)),
    }


def executed(block):
    outputs = {
        m.get("id"): m
        for m in block
        if m["role"] == "tool" and m.get("requestor") == "user"
    }
    calls = []
    for i, m in enumerate(block):
        if m["role"] != "user":
            continue
        for t in m.get("tool_calls") or []:
            result = outputs.get(t["id"])
            calls.append(
                {
                    "name": t["name"],
                    "arguments": t.get("arguments") or {},
                    "index": i,
                    "result_present": result is not None,
                    "executed_successfully": result is not None
                    and not result.get("error", False),
                    "output": (result or {}).get("content"),
                }
            )
    return calls


def operation_done(spec, calls, after, before):
    for call in calls:
        if not call["executed_successfully"] or call["name"] not in [
            spec["tool"],
            *spec.get("alternative_tools", []),
        ]:
            continue
        if any(call["arguments"].get(k) != v for k, v in spec["arguments"].items()):
            continue
        field = spec.get("target_field")
        if (
            field
            and after.get("user", {}).get("device", {}).get(field)
            != spec["target_value"]
        ):
            continue
        return True
    return False


def features(block, req, before=None, after=None):
    before = before or {}
    after = after or {}
    calls = executed(block)
    value = "\n".join(speech(m) for m in block if m["role"] == "user")
    asked = bool(re.search(QUESTION_PATTERN, value, re.I))
    operations = [
        {
            "id": s["id"],
            "executed": operation_done(s, calls, after, before),
            "already_satisfied_before": s.get("target_field") is not None
            and before.get("user", {}).get("device", {}).get(s["target_field"])
            == s["target_value"],
        }
        for s in req["device_operations"]
    ]
    applicable = bool(operations)
    none_requested = applicable and not any(s["executed"] for s in operations)
    amounts = [
        float({"one": "1", "two": "2"}.get(m.group(1).lower(), m.group(1)))
        for m in re.finditer(CONSENT_AMOUNT, value, re.I)
    ]
    # First amount selects the current purchase; later conditional remaining1GB is separate.
    consent = amounts[0] if req["purchase_amount_requested"] and amounts else None
    successful = [c for c in calls if c["executed_successfully"]]
    return {
        "text": value,
        "requested_operations": operations,
        "device_action_applicable": applicable,
        "any_user_tool_executed": bool(successful),
        "any_requested_operation_executed": applicable and not none_requested,
        "all_requested_operations_executed": applicable
        and all(s["executed"] for s in operations),
        "question_marker": asked,
        "no_requested_operation_then_question": none_requested and asked,
        "no_user_tool_then_question": applicable and not successful and asked,
        "first_requested_operation_missing_then_question": applicable
        and not operations[0]["executed"]
        and asked,
        "none_requested_without_question": none_requested and not asked,
        "consent_gb_now": consent,
        "all_mentioned_consent_gb": amounts,
        "amount_requested_but_no_numeric_consent": req["purchase_amount_requested"]
        and consent is None,
        "negative_speed_test_observed": any(
            c["name"] == "run_speed_test"
            and c["executed_successfully"]
            and "no connection" in (c["output"] or "").lower()
            for c in calls
        ),
        "calls": calls,
    }


def summarize(rows, req):
    n = len(rows)
    app = bool(req["device_operations"])
    metrics = {
        name: rate(sum(bool(r["features"][name]) for r in rows), n)
        if app
        else {
            "matches": None,
            "draws": n,
            "rate": None,
            "reason": "No device operation requested; no-action is not noncompliance",
        }
        for name in [
            "no_requested_operation_then_question",
            "no_user_tool_then_question",
            "first_requested_operation_missing_then_question",
            "any_requested_operation_executed",
            "all_requested_operations_executed",
        ]
    }
    metrics["consent_amount_counts"] = (
        dict(collections.Counter(str(r["features"]["consent_gb_now"]) for r in rows))
        if req["purchase_amount_requested"]
        else None
    )
    metrics["consent1GB"] = (
        rate(sum(r["features"]["consent_gb_now"] == 1 for r in rows), n)
        if req["purchase_amount_requested"]
        else None
    )
    metrics["no_numeric_consent"] = (
        rate(
            sum(r["features"]["amount_requested_but_no_numeric_consent"] for r in rows),
            n,
        )
        if req["purchase_amount_requested"]
        else None
    )
    metrics["negative_speed_test_observed"] = rate(
        sum(r["features"]["negative_speed_test_observed"] for r in rows), n
    )
    return metrics


def trajectory_features(row, branch, req):
    trajectory = read(ROOT / row["trajectory"])
    messages = trajectory["messages"]
    start = len(branch["prefix_before"]) + len(branch["block"])
    future = messages[start:]
    # Native read/write tool errors are evaluated by returned tool messages, not prose.
    tool_outputs = {m.get("id"): m for m in future if m["role"] == "tool"}
    executed_agent = [
        t
        for m in future
        if m["role"] == "assistant"
        for t in m.get("tool_calls") or []
        if tool_outputs.get(t["id"]) is not None
        and not tool_outputs[t["id"]].get("error", False)
    ]
    refuels = [
        float(t["arguments"]["gb_amount"])
        for t in executed_agent
        if t["name"] == "refuel_data"
    ]
    assertions = row["assertions_final"]
    unmet = [a["assertion"]["func_name"] for a in assertions if not a["met"]]
    first = next((m for m in future if m["role"] == "assistant"), {})
    first_action = [t["name"] for t in first.get("tool_calls") or []] or [
        "communication"
    ]
    # First later partner block: include all user-tool continuations until agent speaks again.
    later = []
    begun = False
    for m in future:
        if m["role"] == "user":
            begun = True
        if begun and m["role"] == "assistant":
            break
        if begun:
            later.append(m)
    later_calls = executed(later)
    later_first = (
        any(
            c["executed_successfully"]
            and c["name"] == req["device_operations"][0]["tool"]
            and all(
                c["arguments"].get(k) == v
                for k, v in req["device_operations"][0]["arguments"].items()
            )
            for c in later_calls
        )
        if req["device_operations"]
        else None
    )
    return {
        "unit": row["unit"],
        "arm": row["arm"],
        "rep": row["rep"],
        "reward": row["reward"],
        "branch_features": features(
            branch["block"], req, branch["db_before"], branch["db_after"]
        ),
        "first_agent_action": first_action,
        "first_agent_text": speech(first),
        "agent_transferred": any(
            t["name"] == "transfer_to_human_agents" for t in executed_agent
        ),
        "next_partner_first_requested_tool_executed": later_first,
        "refuel_gb_calls": refuels,
        "refuel_gb_total_after_branch": sum(refuels),
        "unmet_assertions": unmet,
        "exact_amount_only_failure": bool(unmet)
        and set(unmet) == {"assert_data_refueling_amount"},
        "termination_reason": trajectory["termination_reason"],
        "trajectory_path": row["trajectory"],
    }


def outcome_summary(rows):
    return {
        "success": rate(sum(r["reward"] == 1 for r in rows), len(rows)),
        "first_agent_action_counts": dict(
            collections.Counter("+".join(r["first_agent_action"]) for r in rows)
        ),
        "agent_transfer_count": sum(r["agent_transferred"] for r in rows),
        "next_partner_first_requested_tool_count": sum(
            r["next_partner_first_requested_tool_executed"] is True for r in rows
        ),
        "refuel_gb_total_counts": dict(
            collections.Counter(str(r["refuel_gb_total_after_branch"]) for r in rows)
        ),
        "unmet_assertion_counts": dict(
            collections.Counter(a for r in rows for a in r["unmet_assertions"])
        ),
        "exact_amount_only_failures": sum(r["exact_amount_only_failure"] for r in rows),
    }


def mechanism_features(f, req):
    found = []
    if f["no_requested_operation_then_question"]:
        found.append("requested_device_action_omitted_with_question")
    if req["purchase_amount_requested"] and f["consent_gb_now"] == 1:
        found.append("1GB_consent_choice")
    if f["amount_requested_but_no_numeric_consent"]:
        found.append("purchase_amount_not_given")
    if f["any_requested_operation_executed"]:
        found.append("requested_device_action_executed")
    if f["negative_speed_test_observed"]:
        found.append("executed_test_reports_no_connection")
    if not req["device_operations"] and not req["purchase_amount_requested"]:
        found.append("no_action_or_purchase_request_at_branch")
    if f["none_requested_without_question"]:
        found.append("requested_device_action_omitted_without_question")
    return found


def main():
    manifest = read(BASE / "v7_c2_step2_20261006_r2/manifest.json")
    paths = [
        BASE / "v7_b2_a_20261005/mechanical_cards" / f"{a['candidate_id']}.json"
        for a in manifest["cases"]
    ]
    plan = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "new_model_calls": 0,
        "definitions": {
            "primary": "Last agent message parsed using saved regex -> requested native user operation(s). Executed iff matching tool call and arguments has native non-error tool result and requested mutation target holds after block. Primary deviation = none of these requested operations executed AND question/clarification marker in user speech. Also report zero-any-tool and missing-first-operation variants. This is a mechanical feature, not an intention label.",
            "multi_step": "Any requested operation, first requested operation, and all requested operations reported separately. First instruction is primary next step; later reboot/test are separate substeps. Conditional VPN/DataSaver contingencies at s008 are not required unconditionally; generic try-internet/mobile-data mapped to native run_speed_test, explicitly documented.",
            "no_action_request": "N/A, never label ordinary non-action as noncompliance. Purchases use user numeric consent rather than user tool calls: refuel_data is an agent tool.",
            "quantity": "First add/full1GB or2GB amount is current consent; later conditional remainingGB separate. Offered up-to2GB is not a mandate to buy2GB; evaluator exact2GB assertion is reported separately from real connectivity.",
            "comparison": "Six original paired native q draws (exclude own candidate when candidate originates from q) and16independent B1 native-reference branch blocks separately. Do not pool batches or count suffix repeats as reply draws. Mechanical outcome association within16native suffixes; candidate treatment shift verified by previous retest does not isolate a single feature.",
            "claims": "No new causal effect estimate for a feature; observational suffix associations describe paths. DB/card/tool records, no human labels and no LLM judgments used for new features.",
        },
        "request_patterns": REQUEST_PATTERNS,
        "consent_request_regex": CONSENT_REQUEST,
        "consent_amount_regex": CONSENT_AMOUNT,
        "question_marker_regex": QUESTION_PATTERN,
        "source_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not (OUT / "plan.json").exists():
        save("plan.json", plan)
    results = []
    all_suffixes = []
    for case, path in zip(manifest["cases"], paths):
        card = read(path)
        req = requests(card["fixed"]["request"])
        fixed = features(
            card["fixed"]["block"],
            req,
            card["fixed"]["db_before"],
            card["fixed"]["db_after"],
        )
        paired = []
        for j in range(6):
            unit = f"{case['state_id']}:q:d{j}"
            if unit == card["candidate"]["reply_unit"]:
                continue
            reply = read(BASE / "v6_paired_20261004/replies" / f"{unit}.json")
            paired.append(
                {
                    "unit": unit,
                    "features": features(
                        reply["partner_block"],
                        req,
                        card["fixed"]["db_before"],
                        reply["state_after_partner"],
                    ),
                }
            )
        independent = [
            {
                "unit": f"{case['candidate_id']}:native:d{r['j']}",
                "features": features(r["block"], req, r["db_before"], r["db_after"]),
            }
            for r in card["native_blocks"]
        ]
        suffixes = []
        for row in card["suffixes"]:
            branch = (
                card["fixed"]
                if row["arm"] == "candidate"
                else next(r for r in card["native_blocks"] if r["j"] == row["rep"])
            )
            suffixes.append(trajectory_features(row, branch, req))
        outcomes = {}
        for arm in ["candidate", "native"]:
            cohort = [r for r in suffixes if r["arm"] == arm]
            outcomes[arm] = {"all": outcome_summary(cohort)}
            if req["device_operations"]:
                for group, flag in [("omission_and_question", True), ("other", False)]:
                    selected = [
                        r
                        for r in cohort
                        if r["branch_features"]["no_requested_operation_then_question"]
                        == flag
                    ]
                    outcomes[arm][group] = outcome_summary(selected)
        results.append(
            {
                **case,
                "reply_unit": card["candidate"]["reply_unit"],
                "request": req,
                "fixed_features": fixed,
                "mechanical_candidate_features": mechanism_features(fixed, req),
                "paired_native": summarize(paired, req),
                "independent_native": summarize(independent, req),
                "paired_raw": paired,
                "independent_raw": independent,
                "suffix_outcomes": outcomes,
            }
        )
        all_suffixes.extend(
            {"candidate_id": case["candidate_id"], **r} for r in suffixes
        )
    save("per_case.json", {"cases": results, "new_model_calls": 0})
    save(
        "suffix_associations.json",
        {
            "rows": all_suffixes,
            "interpretation": "Per-suffix saved execution paths; feature associations are not randomized feature interventions.",
        },
    )
    report(results)
    print("ACTION AUDIT", len(results), "cases", len(all_suffixes), "suffixes", OUT)


def count_string(value):
    return (
        "N/A"
        if value["rate"] is None
        else f"{value['matches']}/{value['draws']} ({value['rate']:.1%})"
    )


def report(results):
    lines = [
        "# 确认案例：程序化动作与购买量审计",
        "",
        "零模型调用。原生同类行为主定义为：agent明确请求了用户工具操作，用户当轮没有执行任何被请求操作，而回复含问题或澄清标记。另报第一步未执行、完全无用户工具、完整执行所有步骤。缺乏用户操作请求的回合记N/A。购买量是用户授权给agent的数量，不等于用户执行设备操作。",
        "",
        "|案例|状态|方向|候选程序特征|原始q未执行且提问|独立原生未执行且提问|独立原生仅第一步缺失且提问|",
        "|---|---|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(
            f"|{row['candidate_id']}|{row['state_id']}|{row['direction']}|{', '.join(row['mechanical_candidate_features'])}|{count_string(row['paired_native']['no_requested_operation_then_question'])}|{count_string(row['independent_native']['no_requested_operation_then_question'])}|{count_string(row['independent_native']['first_requested_operation_missing_then_question'])}|"
        )
    lines += [
        "",
        "上述频率的原始分子/分母、Wilson95%区间、匹配的请求原文、实际工具及参数均在per_case.json。原始q与独立参考分开；原生来源候选去掉自己。没有采用Sol/Luna行为类别。",
        "",
        "## s030：同类动作特征是否也在原生成功中出现",
        "",
        "|案例|原生未执行且提问的成功数|其余原生成功数|候选成功数|候选第一agent动作|",
        "|---|---|---|---|---|",
    ]
    for row in results:
        if row["state_id"] != "s030":
            continue
        out = row["suffix_outcomes"]
        a = out["native"]["omission_and_question"]["success"]
        b = out["native"]["other"]["success"]
        c = out["candidate"]["all"]["success"]
        lines.append(
            f"|{row['candidate_id']}|{a['matches']}/{a['draws']}|{b['matches']}/{b['draws']}|{c['matches']}/{c['draws']}|{out['candidate']['all']['first_agent_action_counts']}|"
        )
    lines += [
        "",
        "## 购买量",
        "",
        "|案例|候选当前授权GB|原始q授权1GB|独立原生授权1GB|候选成功|原生成功|候选仅精确容量断言未满足|",
        "|---|---|---|---|---|---|---|",
    ]
    for row in results:
        if not row["request"]["purchase_amount_requested"]:
            continue
        o = row["suffix_outcomes"]
        a = o["candidate"]["all"]["success"]
        b = o["native"]["all"]["success"]
        lines.append(
            f"|{row['candidate_id']}|{row['fixed_features']['consent_gb_now']}|{count_string(row['paired_native']['consent1GB'])}|{count_string(row['independent_native']['consent1GB'])}|{a['matches']}/{a['draws']}|{b['matches']}/{b['draws']}|{o['candidate']['all']['exact_amount_only_failures']}|"
        )
    lines += [
        "",
        "## 10个有害例子的执行路径",
        "",
        "|案例|候选机械特征|候选/原生成功|候选/原生转人工数|候选/原生agent后续加购总量分布|",
        "|---|---|---|---|---|",
    ]
    for row in results:
        if row["direction"] != "harmful":
            continue
        a = row["suffix_outcomes"]["candidate"]["all"]
        b = row["suffix_outcomes"]["native"]["all"]
        lines.append(
            f"|{row['candidate_id']}|{', '.join(row['mechanical_candidate_features'])}|{a['success']['matches']}/{a['success']['draws']} vs {b['success']['matches']}/{b['success']['draws']}|{a['agent_transfer_count']} vs {b['agent_transfer_count']}|{a['refuel_gb_total_counts']} vs {b['refuel_gb_total_counts']}|"
        )
    lines += [
        "",
        "## 限制",
        "",
        "这些是机械特征和保存路径的关联，不能证明某一个特征单独决定了结果。程序定义的动作类别仍可能把不同具体提问归为同类。一般“试试网络”映射为native run_speed_test，不把纯自然语言“试过了”当作已执行；测速返回No Connection仍算执行了测速。完成网络模式切换但没重启/测速与完全未执行分开。1GB用户授权未违反agent给出的up-to2GB选项；是否仅因reward精确容量要求失败单独计数。字段未读、因果意图、自然语言未被模式解析部分均不补造。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
