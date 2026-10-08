"""Offline prevalence using frozen behavior labels and mechanical executed-call patterns."""

import collections
import datetime
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "pilot/runs/p4"
OUT = BASE / "v7_c2_step2_20261006_r2/native_behavior_prevalence_20261006"


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def rate(k, n):
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


def calls(block):
    return [
        (t["name"], json.dumps(t.get("arguments", {}), sort_keys=True))
        for m in block
        if m["role"] == "user"
        for t in m.get("tool_calls") or []
    ]


def text(block):
    return "\n".join(m.get("content") or "" for m in block if m["role"] == "user")


def features(block):
    value = text(block).lower()
    return {
        "photo_mention_and_question_mark": ("photo" in value and "?" in value),
        "explicit_one_step_phrase": bool(
            re.search(
                r"one (?:action|step)|first (?:action|step)|step[- ]by[- ]step|one at a time",
                value,
            )
        ),
    }


def main():
    labelpath = BASE / "v6_followup_20261004/check3_labels.jsonl"
    plan = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "new_model_calls": 0,
        "primary_same_behavior": "Exact equality of frozen E1 action AND communication labels; Sol primary, frozen Luna separately. Same state only. Six q draws, not 24 suffixes. No new labels or tuning.",
        "secondary": "Same action axis, same communication axis, and identical ordered executed user-tool call name+arguments pattern. Empty pattern explicitly retained. Mechanical patterns compared separately on six paired native draws and sixteen independent B1 native-reference draws; never pooled across batches.",
        "s030_lexical_descriptive_features": {
            "photo_mention_and_question_mark": "user text contains photo and ?",
            "explicit_one_step_phrase": "one action/step, first action/step, step-by-step, or one at a time; regex saved in script. Text feature only; not a behavior or human label.",
        },
        "denominator": "Every saved native draw at the same branch; no outcome conditioning or filtering. Candidate from q contributes to the six-draw primary estimate; report leave-one-out too. Case count is 15, repeated states/candidates are not independent.",
        "CI": "Wilson95% for draw proportions; describes observed generator draw frequency, not harmful-effect prevalence.",
        "label_source_sha256": hashlib.sha256(labelpath.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not (OUT / "plan.json").exists():
        save(OUT / "plan.json", plan)
    labels = [json.loads(s) for s in labelpath.read_text().splitlines()]
    index = {(r["unit"], r["labeler"]): r for r in labels}
    manifest = read(BASE / "v7_c2_step2_20261006_r2/manifest.json")
    results = []
    for case in manifest["cases"]:
        card = read(
            BASE / "v7_b2_a_20261005/mechanical_cards" / f"{case['candidate_id']}.json"
        )
        candidate = card["candidate"]
        rule = read(
            BASE
            / "v7_c2_step2_20261006_r2/mapped_labels"
            / f"{case['label_digest']}.json"
        )
        units = [f"{case['state_id']}:q:d{j}" for j in range(6)]
        row = {
            **case,
            "reply_unit": candidate["reply_unit"],
            "style": rule["style"],
            "valid": rule["valid"],
            "model_labels": {},
        }
        paired_blocks = [
            read(BASE / "v6_paired_20261004/replies" / f"{u}.json")["partner_block"]
            for u in units
        ]
        fixed = card["fixed"]["block"]
        refs = [r["block"] for r in card["native_blocks"]]
        for labeler in ["gpt-5.6-sol", "gpt-5.6-luna"]:
            target = index[(candidate["reply_unit"], labeler)]
            native = [index[(u, labeler)] for u in units]

            def same(r):
                return (r["action"], r["communication"]) == (
                    target["action"],
                    target["communication"],
                )

            leave = [r for r in native if r["unit"] != candidate["reply_unit"]]
            row["model_labels"][labeler] = {
                "candidate_label": [target["action"], target["communication"]],
                "same_behavior": rate(sum(map(same, native)), len(native)),
                "matching_native_units": [r["unit"] for r in native if same(r)],
                "same_action": rate(
                    sum(r["action"] == target["action"] for r in native), len(native)
                ),
                "same_communication": rate(
                    sum(r["communication"] == target["communication"] for r in native),
                    len(native),
                ),
                "candidate_is_native_q": candidate["reply_unit"] in units,
                "leave_candidate_out": rate(sum(map(same, leave)), len(leave)),
                "native_label_counts": dict(
                    collections.Counter(
                        r["action"] + " / " + r["communication"] for r in native
                    )
                ),
            }
        row["mechanical_same_ordered_tool_pattern"] = {
            "candidate_pattern": calls(fixed),
            "paired_native": rate(
                sum(calls(b) == calls(fixed) for b in paired_blocks), len(paired_blocks)
            ),
            "independent_B1_native": rate(
                sum(calls(b) == calls(fixed) for b in refs), len(refs)
            ),
        }
        row["s030_lexical_features"] = None
        if case["state_id"] == "s030":
            row["s030_lexical_features"] = {
                name: {
                    "candidate": present,
                    "paired_native": rate(
                        sum(features(b)[name] for b in paired_blocks),
                        len(paired_blocks),
                    ),
                    "independent_B1_native": rate(
                        sum(features(b)[name] for b in refs), len(refs)
                    ),
                }
                for name, present in features(fixed).items()
            }
        results.append(row)
    save(
        OUT / "per_case.json",
        {
            "cases": results,
            "interpretation": "Model labels are coarse, frozen judgments, not human labels. Native frequency of a behavior does not imply identical effect for every reply in that label. Six draws are small; zero is not evidence of impossibility. B1 reference blocks have no frozen E1 model labels, so only mechanical/lexical secondary rates reported there.",
        },
    )
    lines = [
        "# 确认案例：原生伙伴同类行为的离线比例",
        "",
        "同类行为主定义：复用冻结的 E1 action×communication 标签，Sol 主表，Luna 一致性对照；零新增模型调用。只比较同一分叉状态。每状态原生有6个独立回复，不把24次续写当作24个回复。",
        "",
        "|案例|状态|规则|Sol 候选行为|独立原生同类/n|Wilson95%CI|Luna 同类/n|独立原生同工具序列/16|",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        sol = r["model_labels"]["gpt-5.6-sol"]
        luna = r["model_labels"]["gpt-5.6-luna"]
        a = sol["leave_candidate_out"]
        b = luna["leave_candidate_out"]
        t = r["mechanical_same_ordered_tool_pattern"]["independent_B1_native"]
        lines.append(
            f"|{r['candidate_id']}|{r['state_id']}|{r['style']}|{' / '.join(sol['candidate_label'])}|{a['matches']}/{a['draws']} ({a['rate']:.1%})|[{a['Wilson95_CI'][0]:.3f}, {a['Wilson95_CI'][1]:.3f}]|{b['matches']}/{b['draws']}|{t['matches']}/{t['draws']}|"
        )
    lines += [
        "",
        "原生q来源候选的主表去掉自身，分母为5；其余分母为6。per_case.json同时保留包含自身的原始比例。跨案例共享状态，不能把15行看作独立样本。工具序列是机械辅助特征，空序列表示无用户工具动作，不等于完整行为标签；它来自另一次批次，不能与6次主表比例混为同一估计。",
        "",
        "## s030",
        "",
    ]
    for r in results:
        if r["state_id"] == "s030":
            lines.append(
                f"{r['candidate_id']}：{json.dumps(r['s030_lexical_features'], ensure_ascii=False)}"
            )
    lines += [
        "",
        "这些比例回答“原生曾出现多少同类行为”，不回答该类的每一种说法有多少会导致失败。规则内也不等于行为常见。0/6的95%上界约0.39，不能解释为原生绝不产生。既有标签的两轴分歧保留，尤其不把宽泛的澄清/报告类别当作精确机制。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("OFFLINE PREVALENCE", len(results), "cases", OUT)


if __name__ == "__main__":
    main()
