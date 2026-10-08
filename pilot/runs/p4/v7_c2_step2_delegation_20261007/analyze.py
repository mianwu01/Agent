"""Offline lexical detection of user delegation of user-exclusive device operations."""

import ast
import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = ROOT / "pilot/runs/p4"
SOURCE = BASE / "v7_c2_step2_action_20261007"
ADDRESS = r"(?:\b(?:could|can|would|will|should) you\s+(?:please\s+)?(?:first\s+)?|\bplease\s+(?:first\s+)?|(?:^|[.!?]\s+))"
OPERATIONS = [
    (
        "network_mode_read",
        "check_network_mode_preference",
        r"(?:check|read|look at|tell me)\b[^.!?]{0,65}\b(?:network mode|preferred network type)",
    ),
    ("speed_test", "run_speed_test", r"(?:run|do|perform)\s+(?:a |the )?speed test\b"),
    (
        "vpn_disconnect",
        "disconnect_vpn",
        r"(?:disconnect|turn off|disable)\s+(?:the |my )?vpn\b",
    ),
    (
        "network_mode_change",
        "set_network_mode_preference",
        r"(?:change|set|switch)\b[^.!?]{0,45}\b(?:network mode|preferred network type)",
    ),
    (
        "device_restart",
        "reboot_device",
        r"(?:restart|reboot)\s+(?:my |the )?(?:phone|device)\b",
    ),
]
AMBIGUOUS = (
    ADDRESS
    + r"(?:check|investigate|look into)\b[^.!?]{0,90}(?:connection status|what else|causing the problem)"
)


def detect(text):
    text = text.replace("’", "'")
    hits = []
    for name, tool, pattern in OPERATIONS:
        for match in re.finditer(ADDRESS + pattern, text, re.I):
            hits.append(
                {
                    "operation": name,
                    "user_tool": tool,
                    "span": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    return {
        "strict_delegation": bool(hits),
        "matches": hits,
        "ambiguous_diagnostic_request": bool(re.search(AMBIGUOUS, text, re.I)),
    }


def public_methods(path):
    tree = ast.parse(path.read_text())
    return sorted(
        {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        }
    )


def summary(rows):
    n = len(rows)
    return {
        "n": n,
        "successes": sum(r["reward"] == 1 for r in rows),
        "transfer_count": sum(r["agent_transferred"] for r in rows),
        "first_action_transfer_count": sum(
            "transfer_to_human_agents" in r["first_agent_action"] for r in rows
        ),
        "success_rate": sum(r["reward"] == 1 for r in rows) / n if n else None,
        "transfer_rate": sum(r["agent_transferred"] for r in rows) / n if n else None,
    }


def main():
    tool_path = ROOT / "src/tau2/domains/telecom/tools.py"
    user_path = ROOT / "src/tau2/domains/telecom/user_tools.py"
    sources = [
        SOURCE / "per_case.json",
        SOURCE / "suffix_associations.json",
        tool_path,
        user_path,
    ]
    plan = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "new_model_calls": 0,
        "address_pattern": ADDRESS,
        "operations": OPERATIONS,
        "ambiguous_pattern": AMBIGUOUS,
        "definitions": {
            "strict": "Explicit agent-addressed request for a concrete operation implemented only by the native user tools. Requests to guide/explain/tell what to press are not delegation. Connection-status/other-causes requests are separately ambiguous because agent can inspect carrier records.",
            "outcomes": "Saved Luna candidate/native suffixes, stratified by strict lexical feature; transfer means executed transfer tool anywhere after branch, including after success. Also report immediate transfer.",
            "frequency": "Original q reply draws and independent native reference draws separately; source-native candidate excluded from original q. Shared q at repeated state deduplicated for aggregate prevalence. No independent per-feature intervention.",
        },
        "tool_inventory": {
            "agent": public_methods(tool_path),
            "user": public_methods(user_path),
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
    }
    for _, tool, _ in OPERATIONS:
        assert (
            tool in plan["tool_inventory"]["user"]
            and tool not in plan["tool_inventory"]["agent"]
        ), tool
    if not (OUT / "plan.json").exists():
        (OUT / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        )
    cases = json.loads(sources[0].read_text())["cases"]
    suffixes = json.loads(sources[1].read_text())["rows"]
    results = []
    native_unique = {}
    for case in cases:
        cid = case["candidate_id"]
        batches = {}
        for label, key in [
            ("original_q", "paired_raw"),
            ("independent_native", "independent_raw"),
        ]:
            raw = [
                {
                    "unit": r["unit"],
                    "text": r["features"]["text"],
                    **detect(r["features"]["text"]),
                }
                for r in case[key]
            ]
            batches[label] = {
                "matches": sum(r["strict_delegation"] for r in raw),
                "n": len(raw),
                "ambiguous_count": sum(r["ambiguous_diagnostic_request"] for r in raw),
                "raw": raw,
            }
            if label == "original_q":
                for r in raw:
                    native_unique[r["unit"]] = r
        cohorts = {}
        for arm in ["candidate", "native"]:
            raw = [
                {**r, "delegation": detect(r["branch_features"]["text"])}
                for r in suffixes
                if r["candidate_id"] == cid and r["arm"] == arm
            ]
            cohorts[arm] = {
                str(flag): summary(
                    [r for r in raw if r["delegation"]["strict_delegation"] == flag]
                )
                for flag in [True, False]
            }
        results.append(
            {
                "candidate_id": cid,
                "state_id": case["state_id"],
                "direction": case["direction"],
                "fixed_text": case["fixed_features"]["text"],
                "fixed": detect(case["fixed_features"]["text"]),
                "native_frequency": batches,
                "outcomes": cohorts,
            }
        )
    tests = {
        "explicit_mode_check": detect(
            "Could you check what network mode it's currently on first?"
        )["strict_delegation"],
        "speed_test_by_you": detect("Should you run a speed test for me?")[
            "strict_delegation"
        ],
        "imperative_vpn": detect("Disconnect the VPN now")["strict_delegation"],
        "guidance_is_not_delegation": not detect(
            "Could you please tell me exactly what to press, one step at a time?"
        )["strict_delegation"],
        "have_me_act_not_delegation": not detect(
            "Please have me disconnect the VPN next."
        )["strict_delegation"],
        "guide_me_not_delegation": not detect(
            "Please guide me through checking the network mode."
        )["strict_delegation"],
        "carrier_diagnostic_ambiguous": not detect(
            "Please check what else could be causing the problem"
        )["strict_delegation"],
    }
    assert all(tests.values()), tests
    pooled = {}
    for arm in ["candidate", "native"]:
        rs = [r for r in suffixes if r["arm"] == arm]
        pooled[arm] = {
            str(flag): summary(
                [
                    r
                    for r in rs
                    if detect(r["branch_features"]["text"])["strict_delegation"] == flag
                ]
            )
            for flag in [True, False]
        }
    data = {
        "cases": results,
        "pooled_descriptive_outcomes": pooled,
        "original_q_deduplicated": {
            "n": len(native_unique),
            "matches": sum(r["strict_delegation"] for r in native_unique.values()),
            "raw": list(native_unique.values()),
        },
        "verification": tests,
        "new_model_calls": 0,
    }
    (OUT / "results.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# 用户委托 agent 执行手机操作：离线检验",
        "",
        "检测器在计算前冻结。严格特征要求：用户明确要求 agent 执行一个只有用户工具支持的具体手机操作。查连接状态/查原因另列为歧义请求；agent 可以检查线路和套餐信息，因此不能一概算作越过工具边界。",
        "",
        "|案例|状态|候选严格委托|候选歧义诊断请求|原始 q 严格委托|独立原生严格委托|",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        q = r["native_frequency"]["original_q"]
        n = r["native_frequency"]["independent_native"]
        lines.append(
            f"|{r['candidate_id']}|{r['state_id']}|{r['fixed']['strict_delegation']}|{r['fixed']['ambiguous_diagnostic_request']}|{q['matches']}/{q['n']}|{n['matches']}/{n['n']}|"
        )
    lines += [
        "",
        "|案例/来源|严格委托|成功|后续任意转人工|下一 agent 动作转人工|",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if r["direction"] != "harmful":
            continue
        for arm in ["candidate", "native"]:
            for flag, s in r["outcomes"][arm].items():
                if not s["n"]:
                    continue
                lines.append(
                    f"|{r['candidate_id']}/{arm}|{flag}|{s['successes']}/{s['n']}|{s['transfer_count']}/{s['n']}|{s['first_action_transfer_count']}/{s['n']}|"
                )
    lines += [
        "",
        "跨案例原生/候选汇总仅作描述；各状态难度和候选选择不同。按案例的原始分子、分母、逐条命中文本及所有15例结果在 results.json。原始 q 去重后严格委托 "
        + str(data["original_q_deduplicated"]["matches"])
        + "/"
        + str(len(native_unique))
        + "。",
        "",
        "本轮无模型调用。只有完整固定块经过历史独立重测，尚未单独干预委托措辞；这影响下一步：将明确委托与指导请求做配对重测。转人工可能发生在成功后，成功率和立即转人工率分别报告。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "native_unique": {
                    k: v
                    for k, v in data["original_q_deduplicated"].items()
                    if k != "raw"
                },
                "pooled": pooled,
                "checks": tests,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
