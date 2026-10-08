"""Mechanical case evidence and saved-trajectory decomposition; no sampling."""

import argparse
import collections
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import b2 as x
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

read, save = x.read, x.save

# Each pattern expresses a current state, not a request to change one.
BOOL_PATTERNS = {
    "airplane_mode": r"airplane(?: mode)?(?:\s+(?:is|was|remains|still|currently|now|turned)){0,3}\s*[:=]?\s*(on|off|enabled|disabled)",
    "data_enabled": r"(?:mobile|cellular) data(?:\s+(?:is|was|remains|still|enabled|currently|now|turned)){0,3}\s*[:=]?\s*(on|off|enabled|disabled|yes|no)",
    "roaming_enabled": r"(?:data )?roaming(?:\s+(?:is|was|remains|still|enabled|currently|now|turned)){0,3}\s*[:=]?\s*(on|off|enabled|disabled|yes|no)",
    "data_saver_mode": r"data saver(?: mode)?(?:\s+(?:is|was|remains|still|currently|now|turned)){0,3}\s*[:=]?\s*(on|off|enabled|disabled)",
    "wifi_enabled": r"wi[ -]?fi(?: radio)?(?:\s+(?:is|was|remains|still|currently|now|turned)){0,3}\s*[:=]?\s*(on|off|enabled|disabled)",
    "wifi_connected": r"wi[ -]?fi(?:\s+(?:is|was|remains|still|connected|currently|now|turned)){0,3}\s*[:=]?\s*(connected|disconnected|not connected|yes|no)",
    "vpn_connected": r"vpn(?:\s+(?:is|was|remains|still|currently|now|turned)){0,3}\s*[:=]?\s*(connected|disconnected|not connected)",
}
DEVICE_WORDS = re.compile(
    r"\b(?:data|wi[ -]?fi|vpn|apn|mms|mbps|permissions?|airplane|roaming|network|signal|sim|battery)\b",
    re.I,
)


def clean(m):
    return {
        k: m.get(k)
        for k in ["role", "content", "tool_calls", "requestor", "id", "error"]
        if m.get(k) is not None
    }


FIELD_TOOLS = {
    "device.airplane_mode": {
        "check_network_status",
        "check_status_bar",
        "toggle_airplane_mode",
    },
    "device.data_enabled": {"check_network_status", "toggle_data"},
    "device.roaming_enabled": {"check_network_status", "toggle_roaming"},
    "device.data_saver_mode": {
        "check_data_restriction_status",
        "toggle_data_saver_mode",
    },
    "device.wifi_enabled": {"check_wifi_status", "check_network_status", "toggle_wifi"},
    "device.wifi_connected": {
        "check_wifi_status",
        "check_network_status",
    },
    "device.vpn_connected": {"check_vpn_status", "connect_vpn", "disconnect_vpn"},
    "device.network_mode_preference": {
        "check_network_mode_preference",
        "set_network_mode_preference",
    },
    "derived.speed_mbps": {"run_speed_test"},
    "derived.can_send_mms": {"can_send_mms"},
}


def flat(obj, prefix=""):
    """Flatten JSON into stable leaf paths, including lists."""
    if isinstance(obj, dict):
        return {
            p: v
            for k, val in obj.items()
            for p, v in flat(val, f"{prefix}.{k}" if prefix else k).items()
        }
    if isinstance(obj, list):
        return {
            p: v
            for i, val in enumerate(obj)
            for p, v in flat(val, f"{prefix}[{i}]").items()
        }
    return {prefix: obj}


def delta(before, after):
    a, b = flat(before), flat(after)
    return [
        {"field": k, "before": a.get(k), "after": b.get(k)}
        for k in sorted(a.keys() | b.keys())
        if a.get(k) != b.get(k)
    ]


def claims(text, speech=True):
    """Conservative explicit device-fact parser; unsupported text stays unassessed."""
    detected, unknown = [], []
    for sentence in re.split(r"(?<=[.!?\n])\s+", text or ""):
        lower = sentence.lower().strip()
        if speech and (
            "?" in lower
            or re.search(
                r"\b(?:please|could you|can you|if|should|would|will|try to|need to)\b",
                lower,
            )
        ):
            continue
        found = []
        for field, pattern in BOOL_PATTERNS.items():
            for m in re.finditer(pattern + r"\b", lower):
                found.append(
                    {
                        "field": f"device.{field}",
                        "value": m.group(1) in {"on", "enabled", "yes", "connected"},
                        "quote": sentence,
                        "matched": m.group(0),
                    }
                )
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*mbps", lower):
            found.append(
                {
                    "field": "derived.speed_mbps",
                    "value": float(m.group(1)),
                    "quote": sentence,
                    "matched": m.group(0),
                }
            )
        for m in re.finditer(
            r"(?:messaging app|i|phone|device|it)\s+(?:still\s+)?(can|cannot|can't)\s+(?:send|sending)\s+(?:an?\s+)?mms",
            lower,
        ):
            found.append(
                {
                    "field": "derived.can_send_mms",
                    "value": m.group(1) == "can",
                    "quote": sentence,
                    "matched": m.group(0),
                }
            )
        for m in re.finditer(
            r"(?:network (?:mode )?preference\s*[:=]?\s*|set to\s*)(4g_5g_preferred|3g_only|2g_only)",
            lower,
        ):
            found.append(
                {
                    "field": "device.network_mode_preference",
                    "value": m.group(1),
                    "quote": sentence,
                    "matched": m.group(0),
                }
            )
        detected.extend(found)
        if speech and DEVICE_WORDS.search(sentence) and not found and sentence.strip():
            unknown.append(sentence)
    return detected, unknown


def equal(a, b):
    if (
        isinstance(a, (int, float))
        and not isinstance(a, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
    ):
        return abs(a - b) <= 0.011
    return a == b


def check_claims(history, block, env, before_env=None):
    """Compare statements with DB and successful observed tool-output values."""
    observations, field_reads = [], []
    lookup = {c["id"]: c for m in history + block for c in m.get("tool_calls") or []}
    for index, m in enumerate(history + block):
        if m["role"] != "tool" or m.get("requestor") != "user" or m.get("error"):
            continue
        tool = lookup.get(m.get("id"), {}).get("name")
        field_reads.extend(
            {"field": field, "message_index": index, "tool": tool}
            for field, tools in FIELD_TOOLS.items()
            if tool in tools
        )
        detected, _ = claims(m.get("content") or "", speech=False)
        observations.extend(
            {
                **c,
                "message_index": index,
                "tool": lookup.get(m.get("id"), {}).get("name"),
            }
            for c in detected
        )
    truth = flat(x.p4.state(env)["user"])
    speed, _ = env.user_tools._run_speed_test()
    truth.update(
        {
            "derived.speed_mbps": speed,
            "derived.can_send_mms": env.user_tools._can_send_mms(),
        }
    )
    before_truth = None
    if before_env is not None:
        before_truth = flat(x.p4.state(before_env)["user"])
        speed, _ = before_env.user_tools._run_speed_test()
        before_truth.update(
            {
                "derived.speed_mbps": speed,
                "derived.can_send_mms": before_env.user_tools._can_send_mms(),
            }
        )
    rows, unknown = [], []
    for m in block:
        if m["role"] != "user" or not m.get("content"):
            continue
        detected, unseen = claims(m["content"])
        unknown.extend(unseen)
        for c in detected:
            supports = [
                o
                for o in observations
                if o["field"] == c["field"] and equal(o["value"], c["value"])
            ]
            reads = [o for o in field_reads if o["field"] == c["field"]]
            # User text with tool calls is emitted before those calls execute.
            if m.get("tool_calls"):
                supports = [o for o in supports if o["message_index"] < len(history)]
                reads = [o for o in reads if o["message_index"] < len(history)]
            value = (
                before_truth
                if m.get("tool_calls") and before_truth is not None
                else truth
            ).get(c["field"])
            rows.append(
                {
                    **c,
                    "db_value": value,
                    "db_matches": equal(c["value"], value),
                    "matching_tool_observations": supports,
                    "field_read_observations": reads,
                    "unobserved": not (supports or reads),
                    "stale_observation": bool(supports)
                    and not equal(c["value"], value),
                }
            )
    return {
        "claims": rows,
        "recognized_claim_n": len(rows),
        "unobserved_claim_n": sum(c["unobserved"] for c in rows),
        "incorrect_claim_n": sum(not c["db_matches"] for c in rows),
        "unassessed_device_sentences": unknown,
        "scope": "Parser v3: field read/output evidence is separate from claimed value and current DB truth. Mapping is conservative; unparsed text unassessed. Inline text/tool claims precede their calls.",
    }


def replay(task, messages):
    orch = x.v6.build(x.b.Task.model_validate(task), messages)
    orch.initialize()
    return orch


def block_evidence(task, reply):
    prefix = reply["prefix"][: -len(reply["partner_block"])]
    before, after = replay(task, prefix), replay(task, reply["prefix"])
    assertions_before = x.v6.assertions(before.environment, before.task)
    assertions_after = x.v6.assertions(after.environment, after.task)
    if "state_after_partner" in reply:
        assert x.p4.state(after.environment) == reply["state_after_partner"]
    return {
        "request": next(
            (clean(m) for m in reversed(prefix) if m["role"] == "assistant"), None
        ),
        "block": [clean(m) for m in reply["partner_block"]],
        "prefix_before": [clean(m) for m in prefix],
        "db_before": x.p4.state(before.environment),
        "db_after": x.p4.state(after.environment),
        "db_changes": delta(
            x.p4.state(before.environment), x.p4.state(after.environment)
        ),
        "assertions_before": assertions_before,
        "assertions_after": assertions_after,
        "directly_satisfied_assertions": [
            a["assertion"]
            for a, b in zip(assertions_after, assertions_before)
            if a["met"] and not b["met"]
        ],
        "directly_broken_assertions": [
            a["assertion"]
            for a, b in zip(assertions_after, assertions_before)
            if not a["met"] and b["met"]
        ],
        "device_claim_check": check_claims(
            prefix, reply["partner_block"], after.environment, before.environment
        ),
    }


def normalized_agent_decision(message):
    """Compare actual decisions without generated call identifiers or metadata."""
    return {
        "role": message["role"],
        "content": message.get("content") or "",
        "tool_calls": [
            {"name": t["name"], "arguments": t.get("arguments", {})}
            for t in message.get("tool_calls") or []
        ],
    }


def agent_path(messages, start):
    out = []
    for i, m in enumerate(messages[start:], start):
        if m["role"] == "assistant":
            out.append(
                {
                    "index": i,
                    "message": clean(m),
                    "type": "tool_call" if m.get("tool_calls") else "communication",
                    "semantic": normalized_agent_decision(m),
                }
            )
    return out


def first_divergence(a, b):
    """Ordered executed agent-decision divergence; includes path censoring."""
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else None
        right = b[i] if i < len(b) else None
        if (
            left is None
            or right is None
            or normalized_agent_decision(left["message"])
            != normalized_agent_decision(right["message"])
        ):
            return {"agent_decision_ordinal": i, "candidate": left, "native": right}
    return None


def a_cards():
    p = read(x.OUT / "plan.json")
    tasks = read(x.D["a"] / "tasks.json")
    for c in p["cases"]:
        target = x.D["a"] / "mechanical_cards" / f"{c['candidate_id']}.json"
        if target.exists():
            continue
        sid, cid = c["state_id"], c["candidate_id"]
        fixed_reply = read(x.OLD["step2"] / "replies" / f"{sid}:fixed:{cid}.json")
        fixed = block_evidence(tasks[c["task_id"]], fixed_reply)
        native, suffixes, pairs = [], [], []
        for rep in range(16):
            nr = read(x.OLD["step2"] / "replies" / f"{sid}:native_{cid}:d{rep}.json")
            native.append({"j": rep, **block_evidence(tasks[c["task_id"]], nr)})
            paths = {}
            for arm, unit, reply in [
                ("candidate", f"{sid}:fixed:{cid}:r{rep}", fixed_reply),
                ("native", f"{sid}:native_{cid}:d{rep}:r0", nr),
            ]:
                row = read(x.OLD["step2"] / "continuations" / f"{unit}.json")
                sim = read(x.OLD["step2"] / "trajectories" / f"{unit}.json")
                paths[arm] = agent_path(sim["messages"], len(reply["prefix"]))
                suffixes.append(
                    {
                        "arm": arm,
                        "unit": unit,
                        "rep": rep,
                        "reward": row["reward"],
                        "assertions_final": row["assertions_final"],
                        "unmet": [
                            a["assertion"]
                            for a in row["assertions_final"]
                            if not a["met"]
                        ],
                        "agent_path": paths[arm],
                        "trajectory": str(
                            (
                                x.OLD["step2"] / "trajectories" / f"{unit}.json"
                            ).relative_to(x.ROOT)
                        ),
                    }
                )
            pairs.append(
                {
                    "rep": rep,
                    "pairing": "rep-index descriptive alignment of independently sampled suffixes, not matched random noise",
                    "first_divergence": first_divergence(
                        paths["candidate"], paths["native"]
                    ),
                }
            )
        save(
            target,
            {
                "candidate": c,
                "private_task_scenario": tasks[c["task_id"]].get("user_scenario"),
                "fixed": fixed,
                "native_blocks": native,
                "suffixes": suffixes,
                "paired_path_divergences": pairs,
            },
        )
        print("MECHANICAL CARD", cid, sid, flush=True)


def partner_blocks(messages, start):
    """A whole user/environment turn ends at the next assistant decision."""
    blocks, current = [], []
    for i in range(start, len(messages)):
        m = messages[i]
        if m["role"] == "assistant":
            if current:
                blocks.append(current)
                current = []
        elif m["role"] == "user" or (
            current and m["role"] == "tool" and m.get("requestor") == "user"
        ):
            current.append(i)
    if current:
        blocks.append(current)
    return blocks


def trajectory_decompose(row, sim, reply, task):
    start = len(reply["prefix"])
    suffix = sim["messages"][start:]
    blocks = partner_blocks(sim["messages"], start)
    agent_turns = sum(m["role"] == "assistant" for m in suffix)
    user_stop = row["termination_reason"] == "user_stop"
    all_met = all(a["met"] for a in row["assertions_final"])
    transfer = any(
        "###TRANSFER###" in (m.get("content") or "")
        for m in suffix
        if m["role"] == "user"
    )
    term = (
        "transfer"
        if transfer
        else "max_steps"
        if row["termination_reason"] == "max_steps"
        else "user_stop_all_assertions"
        if user_stop and all_met
        else "user_stop_unmet_assertions"
        if user_stop
        else row["termination_reason"]
    )
    last_index = next(
        (
            i
            for i in range(len(sim["messages"]) - 1, start - 1, -1)
            if sim["messages"][i]["role"] == "assistant"
        ),
        None,
    )
    last = clean(sim["messages"][last_index]) if last_index is not None else None
    result = {
        "unit": row["unit"],
        "state_id": row["state_id"],
        "task_id": row["task_id"],
        "condition": row["condition"],
        "reward": row["reward"],
        "assertions_final": row["assertions_final"],
        "all_assertions_met": all_met,
        "termination": term,
        "native_termination": row["termination_reason"],
        "agent_turns": agent_turns,
        "partner_turns": len(blocks),
        "turns": agent_turns + len(blocks),
        "partner_turns_with_initial": 1 + len(blocks),
        "turns_with_initial": 1 + agent_turns + len(blocks),
        "last_agent_index": last_index,
        "last_agent": last,
        "last_context": [
            clean(m) for m in sim["messages"][max(start, (last_index or start) - 4) :]
        ],
    }
    later = []
    if row["condition"] == "persistent":
        for ordinal, indices in enumerate(blocks):
            end = indices[-1] + 1
            block = [sim["messages"][i] for i in indices]
            prefix = sim["messages"][: indices[0]]
            orch = replay(task, sim["messages"][:end])
            before = (
                replay(task, prefix)
                if any(
                    m.get("content") and m.get("tool_calls")
                    for m in block
                    if m["role"] == "user"
                )
                else None
            )
            check = check_claims(
                prefix, block, orch.environment, before.environment if before else None
            )
            preceding = next(
                (m for m in reversed(prefix) if m["role"] == "assistant"), {}
            )
            mandated = (
                "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
                in (preceding.get("content") or "").upper()
            )
            compliant = any(
                "###TRANSFER###" in (m.get("content") or "")
                for m in block
                if m["role"] == "user"
            ) and not any(m.get("tool_calls") for m in block)
            later.append(
                {
                    "unit": row["unit"],
                    "state_id": row["state_id"],
                    "task_id": row["task_id"],
                    "ordinal": ordinal,
                    "message_indices": indices,
                    "user_tool_call_n": sum(
                        len(m.get("tool_calls") or [])
                        for m in block
                        if m["role"] == "user"
                    ),
                    "has_user_tool_call": any(
                        m.get("tool_calls") for m in block if m["role"] == "user"
                    ),
                    "claim_check": check,
                    "mandated_transfer": mandated,
                    "transfer_compliant": compliant if mandated else None,
                }
            )
    return result, later


def b_decompose():
    """Extract B1 before any B2 calls, then freeze the rerun states."""
    p = read(x.OUT / "plan.json")
    cs = {c["state_id"]: c for c in p["states"]}
    tasks = read(x.D["b"] / "tasks.json")
    jobs = []
    for sid in p["b1_states"]:
        for condition in ["native", "single", "persistent"]:
            for j in range(6):
                for rep in range(4):
                    family = "q" if condition == "native" else condition
                    directory = (
                        x.BASE / "v6_paired_20261004"
                        if condition == "native"
                        else x.OLD["step3b"]
                    )
                    unit = f"{sid}:{family}:d{j}:r{rep}"
                    replyunit = (
                        f"{sid}:tools:d{j}"
                        if condition == "persistent"
                        else f"{sid}:{family}:d{j}"
                    )
                    jobs.append((sid, condition, directory, unit, replyunit))

    def extract(job):
        sid, condition, directory, unit, ru = job
        target = x.D["b"] / "decomposition" / f"{unit}.json"
        if target.exists():
            return read(target)
        row = {
            **read(directory / "continuations" / f"{unit}.json"),
            "condition": condition,
        }
        sim = read(directory / "trajectories" / f"{unit}.json")
        reply = read(directory / "replies" / f"{ru}.json")
        result, later = trajectory_decompose(row, sim, reply, tasks[cs[sid]["task_id"]])
        save(target, {"trajectory": result, "later_partner_turns": later})
        return {"trajectory": result, "later_partner_turns": later}

    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for i, f in enumerate(as_completed([pool.submit(extract, j) for j in jobs]), 1):
            results.append(f.result())
            if i % 100 == 0:
                print("B1 DECOMPOSE", i, "/", len(jobs), flush=True)
    rows = sorted([r["trajectory"] for r in results], key=lambda r: r["unit"])
    assert len(rows) == 1440
    later = [t for r in results for t in r["later_partner_turns"]]
    (x.D["b"] / "trajectories.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    (x.D["b"] / "later_partner_turns.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in later)
    )
    states = []
    for sid in p["b1_states"]:
        groups = {
            c: [r for r in rows if r["state_id"] == sid and r["condition"] == c]
            for c in ["native", "single", "persistent"]
        }
        state = {
            "state_id": sid,
            "task_id": cs[sid]["task_id"],
            "conditions": {
                c: {
                    "successes": sum(r["reward"] for r in rs),
                    "n": len(rs),
                    "success": np.mean([r["reward"] for r in rs]),
                    "terminations": dict(
                        collections.Counter(r["termination"] for r in rs)
                    ),
                    "turns_mean": np.mean([r["turns"] for r in rs]),
                    "partner_turns_mean": np.mean([r["partner_turns"] for r in rs]),
                }
                for c, rs in groups.items()
            },
        }
        state["persistent_minus_single"] = (
            state["conditions"]["persistent"]["success"]
            - state["conditions"]["single"]["success"]
        )
        state["pooled_contribution"] = state["persistent_minus_single"] / 20
        states.append(state)
    save(x.D["b"] / "states.json", states)
    big = sorted(states, key=lambda r: (r["persistent_minus_single"], r["state_id"]))[
        :6
    ]
    bigids = [r["state_id"] for r in big]
    small = sorted(
        [r for r in states if r["state_id"] not in bigids],
        key=lambda r: (abs(r["persistent_minus_single"]), r["state_id"]),
    )[:4]
    selection = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "large_drop": bigids,
        "little_drop": [r["state_id"] for r in small],
        "selection_statistics": big + small,
        "B1_states_sha256": x.sha(x.D["b"] / "states.json"),
        "rule": p["B2"],
        "frozen_before_B2_calls": True,
    }
    target = x.D["b2"] / "b2_selection.json"
    if target.exists():
        previous = read(target)
        assert (
            previous["large_drop"] == selection["large_drop"]
            and previous["little_drop"] == selection["little_drop"]
        )
    else:
        save(target, selection)
    fig, ax = plt.subplots(figsize=(12, 5))
    ranked = sorted(states, key=lambda r: r["persistent_minus_single"])
    ax.bar(
        [r["state_id"] for r in ranked], [r["persistent_minus_single"] for r in ranked]
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Persistent − single success (24 suffixes per state/condition)")
    ax.tick_params(axis="x", rotation=60)
    fig.tight_layout()
    fig.savefig(x.D["b"] / "state_drop.png", dpi=160)
    plt.close(fig)
    print(
        "B1 DONE, B2 SELECTION",
        selection["large_drop"],
        selection["little_drop"],
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["a_cards", "b_decompose"])
    args = parser.parse_args()
    globals()[args.phase]()


if __name__ == "__main__":
    main()
