"""Close diagnostic pilots into an honest evidence registry and human review packet."""

import collections
import hashlib
import html
import json
import random
import time

import p4_calibration as c
import p4_holdout as h
import p4_validation as v

from tau2.data_model.tasks import Task

OUT = c.p4.ROOT / "pilot/runs/p4/gate_closeout_20261003"
BATCHES = ("diagnosis_20261003", "calibration_20261003", "specificity_20261003")


def build_registry():
    """Map existing evidence to obligations, without manufacturing confirmations."""
    records = []
    for batch in BATCHES:
        root = OUT.parent / batch
        tasks = c.p4.read(root / "tasks.json")
        outcomes = [c.p4.read(p) for p in (root / "continuations").glob("*.json")]
        for case in c.p4.read(root / "approved_cases.json")["cases"]:
            sid = case["sample_id"]
            sim = c.p4.read(root / "sources" / (sid + ".json"))
            task = Task.model_validate(tasks[case["task_id"]])
            orch = c.NATIVE_BUILDER(
                c.p4.config(),
                c.p4.with_prefix(task, sim["messages"][: case["decision_index"]]),
            )
            orch.initialize()
            replay_ok = (
                c.p4.digest(c.p4.state(orch.environment)) == case["prefix_state_sha256"]
            )
            assert replay_ok
            evidence = {
                name: {
                    "status": "unresolved",
                    "artifact": None,
                    "rationale": "Not established by existing diagnostic artifacts",
                }
                for name in v.OBLIGATIONS
            }
            source_path = str(
                (root / "sources" / (sid + ".json")).relative_to(c.p4.ROOT)
            )
            evidence["native_failed_outcome"] = {
                "status": "supported"
                if sim["reward_info"]["reward"] == 0
                else "unresolved",
                "artifact": source_path,
                "rationale": "Recorded native benchmark reward; does not establish mechanism",
            }
            evidence["native_prefix_integrity"] = {
                "status": "supported",
                "artifact": str((root / "approved_cases.json").relative_to(c.p4.ROOT)),
                "rationale": "Recomputed native initial dual-state hash matches frozen prefix state",
            }
            evidence["candidate_semantics"].update(
                artifact=source_path,
                rationale="Original C/other label remains provisional until semantic and human adjudication; generic non-C controls cannot become C merely because reminders work",
            )
            evidence["information_matched_local_control"].update(
                status="diagnostic_only",
                artifact=str((root / "protocol.json").relative_to(c.p4.ROOT)),
                rationale="Existing replacement/reminder diagnostics do not jointly establish a registered local mechanism-specific contrast and competitor exclusions",
            )
            by_arm = {}
            for arm in sorted({r["arm"] for r in outcomes}):
                selected = [
                    r for r in outcomes if r["sample_id"] == sid and r["arm"] == arm
                ]
                complete = [r for r in selected if r["status"] == "completed"]
                by_arm[arm] = {
                    "completed": len(complete),
                    "successes": sum(r["reward"] == 1 for r in complete),
                    "errors": len(selected) - len(complete),
                }
            records.append(
                {
                    "record_id": batch + ":" + sid,
                    "batch": batch,
                    "sample_id": sid,
                    "task_id": case["task_id"],
                    "original_candidate": case["category"],
                    "decision_index": case["decision_index"],
                    "diagnostic_outcomes": by_arm,
                    "evidence": evidence,
                    "eligibility": v.eligibility(evidence),
                    "instance_key": v.instance_key(
                        sim["messages"], case["decision_index"], case["category"]
                    ),
                    "trigger_key": None,
                    "trigger_status": "Await adjudicated mode, unmet assertions at prefix and partner-event evidence; hidden state alone must not establish them",
                }
            )
    return records


def build_packet():
    """Create 48 anonymous candidate reviews from the two preselected panels."""
    inputs = []
    for root in (c.OUT, h.OUT):
        for item in c.p4.read(root / "review_panel.json")["items"]:
            inputs.append((root, item))
    random.Random(2026100307).shuffle(inputs)
    entries, mapping = [], []
    for number, (root, item) in enumerate(inputs):
        sim = c.p4.read(root / "sources" / (item["sample_id"] + ".json"))
        task = Task.model_validate(c.p4.read(root / "tasks.json")[item["task_id"]])
        orch = c.NATIVE_BUILDER(c.p4.config(), task)
        entry = {
            "episode_id": f"g1_{number + 1:03d}",
            "policy": orch.agent.domain_policy,
            "agent_tools": [t.openai_schema for t in orch.agent.tools],
            "transcript": c.p4.agent_view(sim["messages"]),
        }
        entries.append(entry)
        mapping.append(
            {
                "episode_id": entry["episode_id"],
                "batch": root.name,
                "sample_id": item["sample_id"],
                "input_sha256": c.p4.digest(entry),
            }
        )
    packet_hash = c.p4.digest(entries)
    c.p4.save(OUT / "annotation_packet.json", entries)
    c.p4.save(
        OUT / "annotation_manifest.json",
        {
            "packet_sha256": packet_hash,
            "mapping": mapping,
            "limit": "Panels were selected prospectively in earlier batches; this human packet is constructed after model/continuation results. Reviewer prior exposure must be reported. Human annotations are candidate evidence, not causal confirmation. Preserve cohort sampling weights; do not pool strata unweighted.",
        },
    )
    template = (c.OUT / "annotation.html").read_text()
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    start = template.index("const entries=")
    end = template.index("\nconst packetKey", start)
    page = template[:start] + "const entries=" + data + ";" + template[end:]
    page = page.replace("P4 独立候选", "P4 G1 候选").replace(
        "p4_human_annotations.json", "p4_g1_human_annotations.json"
    )
    page = page.replace(
        "annotation_type:'independent_human_candidate_review',",
        "annotation_type:'human_candidate_review',reviewer_id:reviewerId,packet_sha256:'"
        + packet_hash
        + "',",
    )
    page = page.replace(
        '<div class="controls">',
        '<label>标注者代号（无需实名）<input id="reviewer_id"></label><div class="controls">',
    )
    page = page.replace(
        "get('export').onclick=()=>{persist();",
        "get('export').onclick=()=>{persist();const reviewerId=get('reviewer_id').value.trim();if(!reviewerId){get('validation').textContent='请填写标注者代号';return;}",
    )
    (OUT / "annotation.html").write_text(page)
    assert len(entries) == 48 and len({e["episode_id"] for e in entries}) == 48
    assert all(
        set(e) == {"episode_id", "policy", "agent_tools", "transcript"} for e in entries
    )
    return packet_hash


def import_annotations(path):
    """Validate and preserve real, partial human input without promoting failures."""
    exported = c.p4.read(path)
    if (
        exported.get("annotation_type") != "human_candidate_review"
        or not isinstance(exported.get("reviewer_id"), str)
        or not exported["reviewer_id"].strip()
    ):
        raise ValueError("Missing human annotation type/reviewer identity")
    manifest = c.p4.read(OUT / "annotation_manifest.json")
    if exported.get("packet_sha256") != manifest["packet_sha256"]:
        raise ValueError("Wrong or missing packet hash")
    packet = {e["episode_id"]: e for e in c.p4.read(OUT / "annotation_packet.json")}
    seen = set()
    populated = []
    for row in exported["entries"]:
        identifier = row["episode_id"]
        if identifier not in packet or identifier in seen:
            raise ValueError("Unknown or duplicate human episode")
        seen.add(identifier)
        if row.get("category") is None:
            continue
        if row["category"] not in {"A", "B", "C", "other", "none", "uncertain"}:
            raise ValueError("Unknown human category")
        if row["category"] in {"A", "B", "C", "other"}:
            if not any(
                m["role"] == "assistant" and m["index"] == row.get("decision_index")
                for m in packet[identifier]["transcript"]
            ):
                raise ValueError("Human decision not in visible assistant history")
            if not row.get("evidence") or not row.get("rationale"):
                raise ValueError("Human candidate lacks evidence/rationale")
        if row.get("prior_exposure") not in {"yes", "no", "unsure"}:
            raise ValueError("Missing human prior-exposure disclosure")
        populated.append(row)
    c.p4.save(OUT / "human_annotations" / (c.p4.digest(exported) + ".json"), exported)
    print(
        {
            "received_candidate_annotations": len(populated),
            "causal_failures_auto_promoted": 0,
        }
    )


def main():
    """Freeze a development contract and report the remaining G1 requirements."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-annotations")
    args = parser.parse_args()
    if args.import_annotations:
        import_annotations(args.import_annotations)
        return
    if (OUT / "protocol.json").exists():
        raise ValueError(
            "Closeout already exists; do not overwrite frozen contract/packet"
        )
    contract = v.protocol()
    contract.update(
        frozen_at_unix=time.time(),
        retrospective_registry=True,
        validator_source_sha256=hashlib.sha256(
            (c.p4.ROOT / "pilot/p4_validation.py").read_bytes()
        ).hexdigest(),
    )
    c.p4.save(OUT / "protocol.json", contract)
    registry = build_registry()
    c.p4.save(OUT / "evidence_registry.json", registry)
    packet_hash = build_packet()
    counts = v.count_verified(registry)
    missing = collections.Counter(
        name for r in registry for name in r["eligibility"]["unmet_obligations"]
    )
    summary = {
        "diagnostic_cases": len(registry),
        "distinct_tasks": len({r["task_id"] for r in registry}),
        "original_categories": dict(
            collections.Counter(r["original_candidate"] for r in registry)
        ),
        "counts_under_development_contract": counts,
        "missing_obligations": dict(missing),
        "human_packet_episodes": 48,
        "packet_sha256": packet_hash,
        "new_API_requests": 0,
        "G1_passed": False,
        "limit": "Zero countable failures under this incomplete-evidence registry does not imply there are no real interaction failures. This is a retrospective readiness audit, not confirmatory scoring.",
    }
    c.p4.save(OUT / "analysis.json", summary)
    table = "".join(
        f"<tr><td>{html.escape(r['record_id'])}</td><td>{r['original_candidate']}</td><td>{html.escape(str(r['diagnostic_outcomes']))}</td><td>{len(r['eligibility']['unmet_obligations'])}</td></tr>"
        for r in registry
    )
    document = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 G1 收束</title><style>body{{font:16px/1.7 system-ui;max-width:1100px;margin:40px auto;padding:0 24px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:10px}}.note{{background:#fff3d7;padding:16px}}</style>
<h1>G1：从提醒诊断回到失败确认与发现计量</h1><p>已收束三批共 15 个不同任务、360 条诊断续跑，重新核验了 15 个共享前缀的双环境状态。本轮未调用 API，也未继续扩大提醒实验。</p>
<p class="note">已有结果支持候选过程和提示效果，但在当前证据合同下，可计数的经验证失败为 0：主要缺少独立人工裁决、局部机制对照、预先注册的对照读出和竞争解释审计。这不表示真实失败不存在；当前合同是在结果之后整理的开发版本，不能倒推成已预注册的确认实验。</p>
<h2>确认与计数规则</h2><p>候选标签、reward=0、提醒后成功和 No-User 成功分别记录。明确自身工具缺失只是 C 的可观察签名；一般委托遗漏需单独注册，不能因提醒有效而重标旧 C。计数必须有语义证据、人工裁决、原生失败与前缀完整性、信息匹配的局部对照，以及策略理解、用户执行、终止、环境与 evaluator 的排除证据。</p>
<p>触发条件按“模式卡 × intent × 未满足 assertion 函数 × 固定相关状态投影 × 有证据的伙伴行为”去重，排除 UUID、seed、persona 单独变化与搜索 embedding。缺失状态或行为证据不增加触发数；隐状态仅供离线审计，不能输入修正生成。协议包含 API 失败、丢弃提案、judge、重放计算和人工时间的成本要求。</p>
<h2>已有证据账本</h2><table><tr><th>案例</th><th>原始候选</th><th>诊断成功/完成</th><th>缺失义务</th></tr>{table}</table>
<h2>下一步</h2><ol><li>用 <a href="annotation.html">48 条候选标注页面</a>进行人工候选裁决，导出 JSON；保持旧两批的抽样权重，记录提前接触分析的情况。页面隐藏结果、任务 ID、分层和用户工具原始输出。</li><li>依据人工分歧收束语义证书，再冻结新病例上的局部控制与读出；全局提醒结果不能替代这些对照。</li><li>具备可用确认规则后，冻结 iid / 随机分支 / 自适应分支的共用算子、根轨迹收费、生成加 judge 预算、3 个种子和随机执行区组。提醒不会只提供给某一个发现臂。</li></ol>
<p><a href="protocol.json">开发证据与去重协议</a> · <a href="analysis.json">G1 缺口</a> · <a href="evidence_registry.json">完整证据账本</a></p></html>"""
    (OUT / "report.html").write_text(document)
    keys = (c.p4.ROOT / "api.txt").read_text().split()
    files = [p for p in OUT.rglob("*") if p.is_file()]
    assert not any(key.encode() in p.read_bytes() for p in files for key in keys), (
        "Credential match; values withheld"
    )
    c.p4.save(
        OUT / "final_verification.json",
        {
            "native_prefix_states_checked": len(registry),
            "packet_input_fields_checked": 48,
            "new_API_requests": 0,
            "credential_matches": 0,
            "provenance_sha256": {
                str(p.relative_to(c.p4.ROOT)): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in files
            },
        },
    )
    c.p4.save(
        OUT / "handoff.json",
        {
            "stage": "G1 diagnostic closeout",
            "G1_passed": False,
            "diagnostic_expansion_stopped": True,
            "report": "report.html",
            "next": "Human candidate adjudication plus narrowly registered local controls, then G2 shared-operator budget pilot",
            "counts": counts,
        },
    )
    print(summary)


if __name__ == "__main__":
    main()
