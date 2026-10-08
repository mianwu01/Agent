"""Tier C anomaly replay and frozen single-turn control, with native audit routing."""

# ruff: noqa: E402
import argparse
import collections
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = OUT.parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(BASE / "v7_b2_report_20261005"))
import b2 as x
import mechanical as mech

from tau2.data_model.simulation import SimulationRun
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

read, save = x.read, x.save
B1 = BASE / "v7_b1_step3b_20261004"
B2 = BASE / "v7_b2_b2_20261005"
CLASSOUT = BASE / "v7_c_step2_20261005"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def plan():
    """Freeze all Step 1/2 rules before replay or new outcomes."""
    if (OUT / "plan.json").exists():
        return read(OUT / "plan.json")
    old = read(x.OUT / "plan.json")
    case = next(c for c in old["states"] if c["state_id"] == "s010")
    selected = {}
    for name, directory, target in [("B1", B1, 1), ("v2", B2, 0)]:
        records = [
            read(f)
            for f in sorted((directory / "continuations").glob("s010*persistent*.json"))
        ]
        selected[name] = [r["unit"] for r in records if r["reward"] == target][:6]
        assert len(selected[name]) == 6
    obj = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_hash": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "state": case,
        "mechanical_replay_units": selected,
        "single_turn": "Reuse each of the six B2 v2 branch blocks, 2 fresh suffixes each, native partner afterwards; temperatures 1.0; fresh unit ids/seeds, audited existing authentication-only routing",
        "seed": 2026100503,
        "score_CI": "Wilson95% rates, Newcombe95% independent-binomial differences; shared branch draws acknowledged; historical comparisons not matched causal estimates",
        "protocol_audit": "Native schema validation; transfer after explicit announcement; mandatory one-action clarification when the preceding agent explicitly requests multiple actions; DB claims checked with frozen B2 mechanical parser, unmatched text unassessed. Separately distinguish hard guideline violations from clarification/cooperation differences and proposal-prompt failures.",
        "diff": "Align B1 and v2 by draw/rep index descriptively, normalize random ids/metadata; show first divergent partner block and immediately following agent decision. Suffix randomness is independent.",
        "bug_gate": "If a reproducible replay/schema/protocol/fidelity-filter implementation defect is found, report before Step3 and do not launch Step3.",
        "historical_sha256": {
            str(p.relative_to(ROOT)): sha(p)
            for d in [B1, B2]
            for sub in ["continuations", "trajectories", "replies"]
            for p in sorted((d / sub).glob("s010*.json"))
        },
    }
    save(OUT / "plan.json", obj)
    rules = {
        "timestamp_utc": obj["timestamp_utc"],
        "git_hash": obj["git_hash"],
        "cases": [c["candidate_id"] for c in old["cases"]],
        "class_priority": [
            "reward_spec_mismatch",
            "hard_for_both",
            "capability_dependent",
            "infeasible_after_block",
            "beneficial_disclosure",
            "beneficial_other",
            "unclear",
        ],
        "definitions": {
            "reward_spec_mismatch": "Harmful failing direction = fixed-block suffixes. Pool Luna and Sol fixed-block failures; >= half have nonempty unmet assertions consisting solely of amount/format-exact assertions. Also report per-agent numerators/denominators. Mechanically exact assertion allowlist below.",
            "hard_for_both": "Harmful; both Luna fixed-native and Sol fixed-native Newcombe95% CIs have upper<0; block changes no DB field; >=1 fixed-block suffix succeeds under either agent.",
            "capability_dependent": "Harmful; Newcombe95% CI lower(Sol fixed - Luna fixed)>0.",
            "infeasible_after_block": "Harmful; block changes DB fields and zero fixed-block successes under both agents. Operational name, not proof of impossibility.",
            "beneficial_disclosure": "Beneficial; fixed block reports >=1 recognized device claim matching actual DB, whose (field,value) is absent from all16 native-reference blocks. Frozen mechanical parser; list observation coverage and missed sentences.",
            "beneficial_other": "Other beneficial cases.",
            "unclear": "No preceding rule matches.",
        },
        "exact_assertion_functions": ["assert_data_refueling_amount"],
        "allowlist_scope": "All saved B2 task assertions audited; this is the only amount/format-exact function in these cases. For future verified cases add a frozen amendment before classifying any new exact functions. Never infer exactness by task outcome.",
        "ambiguity_resolution": "Apply above priority, report all matching labels as well as the primary label. Pooled failure rule explicitly resolves unspecified multi-agent aggregation; per-agent diagnostics retained.",
        "intervals": "Newcombe independent-binomial score95%, as B2; exploratory unadjusted.",
        "no_model_calls": True,
        "code_sha256": sha(Path(__file__)),
    }
    save(CLASSOUT / "plan.json", rules)
    shutil.copy2(B2 / "tasks.json", OUT / "tasks.json")
    (OUT / "sources").mkdir(exist_ok=True)
    shutil.copy2(
        B2 / "sources" / f"{case['source_id']}.json",
        OUT / "sources" / f"{case['source_id']}.json",
    )
    for j in range(6):
        r = read(B2 / "replies" / f"s010:tools_v2:d{j}.json")
        r["source_unit"] = r["unit"]
        r["unit"] = f"s010:c_single_v2:d{j}"
        save(OUT / "replies" / f"{r['unit']}.json", r)
    return obj


def sample(workers):
    """Run exactly12 fresh native-after-branch suffixes."""
    p = read(OUT / "plan.json")
    x.D = {"c1": OUT}
    x.setup("c1", workers)
    jobs = []
    for j in range(6):
        r = read(OUT / "replies" / f"s010:c_single_v2:d{j}.json")
        for rep in range(2):
            jobs.append(
                lambda key, r=r, rep=rep: x.v6.continuation(p["state"], r, rep, key)
            )
    x.b.run_jobs("c1", jobs, workers)


def replay_selected():
    """Strictly replay twelve recorded trajectories and recompute reward offline."""
    p = read(OUT / "plan.json")
    task = read(OUT / "tasks.json")[p["state"]["task_id"]]
    task_model = x.b.Task.model_validate(task)
    assert not task["evaluation_criteria"].get("nl_assertions")
    result = []
    for name, d in [("B1", B1), ("v2", B2)]:
        for unit in p["mechanical_replay_units"][name]:
            row = read(d / "continuations" / f"{unit}.json")
            sim = read(d / "trajectories" / f"{unit}.json")
            orch = mech.replay(task, sim["messages"])
            assertions = x.v6.assertions(orch.environment, task_model)
            reward = evaluate_simulation(
                SimulationRun.model_validate(sim),
                task_model,
                EvaluationType.ALL,
                False,
                "telecom",
            ).reward
            matches = assertions == row["assertions_final"] and reward == row["reward"]
            assert matches
            entry = {
                "unit": unit,
                "source": name,
                "strict_mutating_tool_output_replay": True,
                "assertions_match": assertions == row["assertions_final"],
                "reward_match": reward == row["reward"],
                "reward": reward,
                "assertions_final": assertions,
                "replayed_final_db": x.p4.state(orch.environment),
                "note": "Final DB was not independently saved in B1/B2 suffix rows; deterministic strict replay and final assertion match verify the recorded actions/state implications.",
            }
            result.append(entry)
            print("REPLAY", unit, reward, flush=True)
    save(OUT / "mechanical_replay.json", result)


def classify():
    """Reclassify every B2 verified case using frozen mechanical rules."""
    rules = read(CLASSOUT / "plan.json")
    results = []
    spec = importlib.util.spec_from_file_location("b2_stats", x.OUT / "analyze_b2.py")
    stats = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stats)
    for cid in rules["cases"]:
        old = read(x.D["a"] / "a2_cases" / f"{cid}.json")
        card = read(x.D["a"] / "mechanical_cards" / f"{cid}.json")
        rates = old["rates"]
        harmful = old["direction"] == "harmful"
        matches = []
        diag = {}
        for agent in ["Luna", "Sol"]:
            records = (
                [r for r in card["suffixes"] if r["arm"] == "candidate"]
                if agent == "Luna"
                else [
                    read(f)
                    for f in sorted(
                        (x.D["a"] / "continuations").glob(
                            f"{old['state_id']}:sol_fixed:{cid}:r*.json"
                        )
                    )
                ]
            )
            failed = [r for r in records if r["reward"] != 1]
            exact = [
                r
                for r in failed
                if (
                    unmet := [
                        a["assertion"]["func_name"]
                        for a in r["assertions_final"]
                        if not a["met"]
                    ]
                )
                and all(n in rules["exact_assertion_functions"] for n in unmet)
            ]
            diag[agent] = {
                "exact_only_failures": len(exact),
                "failures": len(failed),
                "units": [r["unit"] for r in exact],
            }
        numerator = sum(v["exact_only_failures"] for v in diag.values())
        denominator = sum(v["failures"] for v in diag.values())
        changes = card["fixed"]["db_changes"]
        successes = rates["Luna_fixed"]["successes"] + rates["Sol_fixed"]["successes"]
        luna_shift = stats.difference(rates["Luna_fixed"], rates["Luna_native"])
        sol_shift = old["Sol_fixed_minus_native"]
        gain = old["Sol_minus_Luna_fixed"]
        if harmful and denominator and numerator / denominator >= 0.5:
            matches.append("reward_spec_mismatch")
        if (
            harmful
            and luna_shift["score_95_CI"][1] < 0
            and sol_shift["score_95_CI"][1] < 0
            and not changes
            and successes > 0
        ):
            matches.append("hard_for_both")
        if harmful and gain["score_95_CI"][0] > 0:
            matches.append("capability_dependent")
        if harmful and changes and successes == 0:
            matches.append("infeasible_after_block")
        native_claims = {
            (c["field"], json.dumps(c["value"], sort_keys=True))
            for n in card["native_blocks"]
            for c in n["device_claim_check"]["claims"]
            if c["db_matches"]
        }
        disclosures = [
            c
            for c in card["fixed"]["device_claim_check"]["claims"]
            if c["db_matches"]
            and (c["field"], json.dumps(c["value"], sort_keys=True))
            not in native_claims
        ]
        if not harmful:
            matches.append(
                "beneficial_disclosure" if disclosures else "beneficial_other"
            )
        results.append(
            {
                "candidate_id": cid,
                "state_id": old["state_id"],
                "direction": old["direction"],
                "old_class": old["operational_class"],
                "new_class": matches[0] if matches else "unclear",
                "all_matching_classes": matches,
                "rates": rates,
                "Luna_fixed_minus_native": luna_shift,
                "Sol_fixed_minus_native": sol_shift,
                "Sol_minus_Luna_fixed": gain,
                "exact_failure_diagnostic": diag,
                "pooled_exact_only_failures": numerator,
                "pooled_fixed_failures": denominator,
                "db_changes": changes,
                "verified_new_disclosures": disclosures,
                "parser_scope": card["fixed"]["device_claim_check"]["scope"],
            }
        )
    save(
        CLASSOUT / "reclassification.json",
        {
            "cases": results,
            "counts": dict(collections.Counter(r["new_class"] for r in results)),
        },
    )
    lines = [
        "# Tier C Step2：机械重分类",
        "",
        "按冻结优先级给出主类，同时保留所有命中规则。金额精确断言仅包含本批的 assert_data_refueling_amount；奖励规格判断以两种 agent 的固定块失败合并计数，逐 agent 原始数也保留。区间未校正多重比较。这些是操作性类别，不是人类标注或不可行性证明。",
        "",
        "|Case|State|旧类|新类|仅金额失败/固定块失败（Luna；Sol）|",
        "|---|---|---|---|---|",
    ]
    for r in results:
        a, b = r["exact_failure_diagnostic"].values()
        lines.append(
            f"|{r['candidate_id']}|{r['state_id']}|{r['old_class']}|{r['new_class']}|{a['exact_only_failures']}/{a['failures']}；{b['exact_only_failures']}/{b['failures']}|"
        )
    lines += [
        "",
        str(dict(collections.Counter(r["new_class"] for r in results))),
        "",
        "所有原始成功数、分母、区间、并列命中规则及披露证据见 [reclassification.json](reclassification.json)。披露类别依赖冻结的机械事实解析器；未匹配的句子不算已验证事实。",
    ]
    (CLASSOUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["plan", "sample", "replay", "classify"])
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    if args.phase == "sample":
        sample(args.workers)
    elif args.phase == "replay":
        replay_selected()
    else:
        globals()[args.phase]()
