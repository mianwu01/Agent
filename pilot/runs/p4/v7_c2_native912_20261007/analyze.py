"""Audit saved native episodes for delegated user operations and immediate transfer."""

import collections
import datetime
import hashlib
import importlib.util
import json
import math
import random
import re
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
SOURCE = ROOT / "pilot/runs/iid/default/results.json"
DETECTOR = ROOT / "pilot/runs/p4/v7_c2_step2_delegation_20261007/analyze.py"
spec = importlib.util.spec_from_file_location("delegation", DETECTOR)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
EXTRA = [
    (
        "mobile_data_enable",
        "toggle_data",
        r"(?:enable|turn on)\s+(?:the |my )?mobile data\b",
    ),
    (
        "mobile_data_disable",
        "toggle_data",
        r"(?:disable|turn off)\s+(?:the |my )?mobile data\b",
    ),
    (
        "data_saver_disable",
        "toggle_data_saver",
        r"(?:disable|turn off)\s+(?:the |my )?data saver\b",
    ),
    (
        "airplane_mode",
        "toggle_airplane_mode",
        r"(?:disable|enable|turn off|turn on)\s+(?:the |my )?airplane mode\b",
    ),
]
COORDINATED = (
    d.ADDRESS
    + r"(?:check|read|look at)\b(?:(?![.!?]|\b(?:guide|instruct|have me|help me|tell me how)\b).){0,120}\band\s+(?:then\s+)?run\s+(?:a |the )?speed test\b"
)
REPLICATES = 2000
SEED = 2026100712


def detect(text):
    base = d.detect(text)
    hits = [
        h
        for h in base["matches"]
        if not re.search(r"\btell me (?:how|when|what|where)\b", h["span"], re.I)
    ]
    for name, tool, pattern in EXTRA:
        for m in re.finditer(d.ADDRESS + pattern, text, re.I):
            hits.append(
                {
                    "operation": name,
                    "user_tool": tool,
                    "span": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                    "extension": True,
                }
            )
    for m in re.finditer(COORDINATED, text, re.I):
        hits.append(
            {
                "operation": "speed_test",
                "user_tool": "run_speed_test",
                "span": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "extension": True,
            }
        )
    return {
        "primary_delegation": bool(hits),
        "previous_detector_delegation": base["strict_delegation"],
        "matches": hits,
        "ambiguous_diagnostic_request": base["ambiguous_diagnostic_request"],
    }


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [c - h, c + h]


def fraction(k, n):
    return {
        "numerator": k,
        "denominator": n,
        "rate": k / n if n else None,
        "Wilson95_CI": wilson(k, n),
    }


def blocks(messages):
    i = 0
    while i < len(messages):
        if messages[i]["role"] != "user":
            i += 1
            continue
        start = i
        while i < len(messages) and messages[i]["role"] != "assistant":
            i += 1
        yield start, i, messages[start:i], messages[i] if i < len(messages) else None


def summarize_events(events, field):
    result = {}
    for flag in [True, False]:
        rs = [r for r in events if r[field] == flag]
        result[str(flag)] = {
            "partner_blocks": len(rs),
            "immediate_transfer": fraction(
                sum(r["immediate_transfer"] for r in rs), len(rs)
            ),
            "episode_success": fraction(sum(r["reward"] == 1 for r in rs), len(rs)),
            "episode_failure": fraction(sum(r["reward"] < 1 for r in rs), len(rs)),
        }
    return result


def summarize_episodes(rows):
    failures = [r for r in rows if r["failure"]]
    hit = [r for r in rows if r["delegation_immediate_transfer"]]
    return {
        "episodes": len(rows),
        "tasks": len({r["task_id"] for r in rows}),
        "successes": sum(not r["failure"] for r in rows),
        "failures": len(failures),
        "episodes_with_delegation": sum(r["delegation"] for r in rows),
        "episodes_with_delegation_immediate_transfer": len(hit),
        "failed_episodes_with_delegation_immediate_transfer": sum(
            r["failure"] for r in hit
        ),
        "failure_path_share": fraction(
            sum(r["delegation_immediate_transfer"] for r in failures), len(failures)
        ),
        "hit_episode_success": fraction(sum(not r["failure"] for r in hit), len(hit)),
    }


def bootstrap(rows):
    clusters = collections.defaultdict(list)
    for r in rows:
        clusters[r["task_id"]].append(r)
    tasks = sorted(clusters)
    rng = random.Random(SEED)
    samples = []
    for _ in range(REPLICATES):
        rs = [r for t in rng.choices(tasks, k=len(tasks)) for r in clusters[t]]
        fs = [r for r in rs if r["failure"]]
        if fs:
            samples.append(
                sum(r["delegation_immediate_transfer"] for r in fs) / len(fs)
            )
    samples.sort()
    return {
        "replicates": REPLICATES,
        "seed": SEED,
        "task_clusters": len(tasks),
        "95_CI": [
            samples[int(0.025 * (len(samples) - 1))],
            samples[int(0.975 * (len(samples) - 1))],
        ],
        "statistic": "Failure episodes containing delegated user operation followed by immediate executed agent transfer / all failure episodes",
    }


def main():
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    plan = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "new_model_calls": 0,
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": source_hash,
        "previous_detector_sha256": hashlib.sha256(DETECTOR.read_bytes()).hexdigest(),
        "address_regex": d.ADDRESS,
        "operations": d.OPERATIONS,
        "extra_operations": EXTRA,
        "coordinated_regex": COORDINATED,
        "definitions": {
            "delegation": "Explicit agent-addressed concrete user-only tool operation. Guidance/have-me requests excluded; generic carrier/connection diagnostics separately ambiguous. Previous five-operation detector retained as a comparison. Extension adds named device actions and same-subject coordinated speed-test requests, from lexical scan without per-turn outcome inspection.",
            "block": "Every complete user turn through its user tools and results until next assistant message; concatenate user text. Next assistant message defines immediate action, regardless of later turns.",
            "transfer": "First assistant message contains transfer_to_human_agents call whose corresponding subsequent native tool result has error=False. Attempted and executed tracked separately. Transfer after a prior assistant response is not immediate.",
            "failure": "Saved reward <1; missing rewards excluded and counted. Episode share counts each episode once even if multiple events. Event success links final episode reward, not a new turn-level reward.",
            "interpretation": "Fraction of failures containing this observed path, not counterfactual fraction caused by this path. Report all912 episodes and task-family breakdown; no new model calls.",
        },
        "bootstrap": {"unit": "task cluster", "replicates": REPLICATES, "seed": SEED},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not (OUT / "plan.json").exists():
        (OUT / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        )
    tests = {
        "guidance_network_mode_excluded": not detect(
            "Please tell me how to change the network mode next."
        )["primary_delegation"],
        "user_next_step_excluded": not detect(
            "Please tell me when you are ready for me to change the preferred network mode."
        )["primary_delegation"],
        "direct_speed": detect("Could you run a speed test now?")["primary_delegation"],
        "guidance_excluded": not detect("Please have me run a speed test")[
            "primary_delegation"
        ],
        "instruction_excluded": not detect("Please instruct me to disconnect the VPN")[
            "primary_delegation"
        ],
        "guide_excluded": not detect(
            "Could you guide me through enabling Mobile Data?"
        )["primary_delegation"],
        "coordinate_same_subject": detect(
            "Could you please check my mobile data connection and run a speed test?"
        )["primary_delegation"],
        "coordinate_user_subject_excluded": not detect(
            "Could you have me refresh the connection and then run a speed test?"
        )["primary_delegation"],
    }
    assert all(tests.values()), tests
    data = json.loads(SOURCE.read_text())
    events = []
    episodes = []
    missing = []
    assert len({s["id"] for s in data["simulations"]}) == len(data["simulations"])
    for sim in data["simulations"]:
        reward = (sim.get("reward_info") or {}).get("reward")
        if reward is None:
            missing.append(sim["id"])
            continue
        messages = sim["messages"]
        output = {m.get("id"): m for m in messages if m["role"] == "tool"}
        local = []
        for start, end, block, next_agent in blocks(messages):
            text = "\n".join(
                m.get("content") or "" for m in block if m["role"] == "user"
            )
            found = detect(text)
            transfers = [
                c
                for c in (next_agent or {}).get("tool_calls") or []
                if c["name"] == "transfer_to_human_agents"
            ]
            successful = any(
                c["id"] in output and not output[c["id"]].get("error", False)
                for c in transfers
            )
            tools = [
                c["name"]
                for m in block
                if m["role"] == "user"
                for c in m.get("tool_calls") or []
            ]
            row = {
                "episode_id": sim["id"],
                "task_id": sim["task_id"],
                "trial": sim.get("trial"),
                "reward": reward,
                "block_start": start,
                "next_agent_index": end if next_agent else None,
                "user_text": text,
                **found,
                "user_tool_calls": tools,
                "immediate_transfer_attempted": bool(transfers),
                "immediate_transfer": successful,
                "next_agent_tool_calls": (next_agent or {}).get("tool_calls") or [],
                "next_agent_text": (next_agent or {}).get("content"),
                "transfer_result": [output.get(c["id"]) for c in transfers],
            }
            # Keep only relevant native tool results, without provider raw request data.
            row["transfer_result"] = [
                {k: r.get(k) for k in ["role", "id", "content", "error"]}
                for r in row["transfer_result"]
                if r is not None
            ]
            events.append(row)
            local.append(row)
        episodes.append(
            {
                "episode_id": sim["id"],
                "task_id": sim["task_id"],
                "trial": sim.get("trial"),
                "reward": reward,
                "failure": reward < 1,
                "delegation": any(r["primary_delegation"] for r in local),
                "delegation_immediate_transfer": any(
                    r["primary_delegation"] and r["immediate_transfer"] for r in local
                ),
                "previous_detector_path": any(
                    r["previous_detector_delegation"] and r["immediate_transfer"]
                    for r in local
                ),
                "matched_event_starts": [
                    r["block_start"]
                    for r in local
                    if r["primary_delegation"] and r["immediate_transfer"]
                ],
            }
        )
    summary = {
        "new_model_calls": 0,
        "source_sha256": source_hash,
        "missing_reward_episode_ids": missing,
        "overall": summarize_episodes(episodes),
        "failure_path_task_cluster_bootstrap": bootstrap(episodes),
        "previous_detector_failure_path_share": fraction(
            sum(r["failure"] and r["previous_detector_path"] for r in episodes),
            sum(r["failure"] for r in episodes),
        ),
        "events": {
            "partner_blocks": len(events),
            "delegation": sum(r["primary_delegation"] for r in events),
            "delegation_immediate_transfer": sum(
                r["primary_delegation"] and r["immediate_transfer"] for r in events
            ),
            "delegation_tool_also_called": sum(
                r["primary_delegation"] and bool(r["user_tool_calls"]) for r in events
            ),
            "by_delegation": summarize_events(events, "primary_delegation"),
        },
        "families": {},
        "verification": tests,
    }
    for family in sorted({r["task_id"].split("]")[0] + "]" for r in episodes}):
        rs = [r for r in episodes if r["task_id"].startswith(family)]
        summary["families"][family] = summarize_episodes(rs)
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    for name, rows in [("events.jsonl", events), ("episodes.jsonl", episodes)]:
        (OUT / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )
    hits = [r for r in events if r["primary_delegation"]]
    (OUT / "matched_turns.md").write_text(
        "\n\n".join(
            f"## {r['episode_id']} / turn {r['block_start']}\n\nTask: {r['task_id']}\n\nUser: {r['user_text']}\n\nNext agent: {r['next_agent_text']}\n\nTools: {json.dumps(r['next_agent_tool_calls'], ensure_ascii=False)}\n\nImmediate transfer: {r['immediate_transfer']}; final reward: {r['reward']}"
            for r in hits
        )
        + "\n"
    )
    overall = summary["overall"]
    ci = summary["failure_path_task_cluster_bootstrap"]["95_CI"]
    lines = [
        "# 912 条原生 telecom 轨迹：设备操作委托与立即转人工",
        "",
        "零新模型调用。源文件含912条轨迹、114个任务、每任务8次运行。原生奖励为0/1。",
        "",
        f"**{overall['failures']} 条失败中，{overall['failed_episodes_with_delegation_immediate_transfer']} 条包含‘明确委托用户设备操作 → 下一 agent 动作执行转人工’，占 {overall['failure_path_share']['rate']:.1%}；任务聚类 bootstrap 95% CI [{ci[0]:.1%}, {ci[1]:.1%}]。**",
        "",
        "|任务类型|轨迹|失败|含该路径的失败|占该类型失败|",
        "|---|---|---|---|---|",
    ]
    for family, s in summary["families"].items():
        lines.append(
            f"|{family}|{s['episodes']}|{s['failures']}|{s['failed_episodes_with_delegation_immediate_transfer']}|{s['failure_path_share']['rate']:.1%}|"
        )
    lines += [
        "",
        "|用户回合|回合数|下一步转人工|最终 episode 成功|",
        "|---|---|---|---|",
    ]
    for flag, s in summary["events"]["by_delegation"].items():
        t = s["immediate_transfer"]
        a = s["episode_success"]
        lines.append(
            f"|{'明确委托' if flag == 'True' else '未检出明确委托'}|{s['partner_blocks']}|{t['numerator']}/{t['denominator']}|{a['numerator']}/{a['denominator']}|"
        )
    lines += [
        "",
        f"检出 {summary['events']['delegation']} 个明确委托回合，其中 {summary['events']['delegation_immediate_transfer']} 个紧接着转人工；涉及 {overall['episodes_with_delegation_immediate_transfer']} 条不同轨迹。这些轨迹成功 {overall['hit_episode_success']['numerator']}/{overall['hit_episode_success']['denominator']}。",
        "",
        "“失败中有多少包含这条路径”是已有记录能支持的数字。要把它写成“多少失败由该机制造成”，还需要原地改写和prompt修复验证。",
        "",
        "## 审计与规则",
        "",
        "检测规则先冻结，复用前轮五类设备操作检测器，加入明确手机开关操作和同主语并列测速句。一般查线路/查原因不算明确用户设备委托；guide me / have me / instruct me不算委托。逐条命中见 matched_turns.md，完整回合与episode标记见 events.jsonl / episodes.jsonl。",
        "",
        f"原五类检测器对应失败路径占比：{summary['previous_detector_failure_path_share']['numerator']}/{summary['previous_detector_failure_path_share']['denominator']}。扩大规则前后的数字均保留。",
        "",
        "检测器边界核对8项通过。区间按任务聚类重采样2000次，随机种子2026100712；原始分子分母和Wilson区间均在summary.json。回合级成功列是对应episode的最终成功，可能重复计入同一episode，不作为独立成功样本估计。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
