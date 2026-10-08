"""Full confirmed-case labels; joint multi-turn labels on a frozen trajectory sample."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import c2 as c


def inputs(digest):
    return c.read(c.ACTIVE / "label_inputs" / f"{digest}.json")


def cases(workers):
    c.setup("step2", workers)
    m = c.read(c.ACTIVE / "manifest.json")
    tasks = c.read(c.ACTIVE / "tasks.json")

    def job(case):
        path = c.ACTIVE / "mapped_labels" / f"{case['label_digest']}.json"
        if path.exists():
            return c.read(path)
        inp = inputs(case["label_digest"])
        label = c.annotate(
            c.x.b.Task.model_validate(tasks[case["task_id"]]),
            inp["prefix"],
            inp["block"],
            0,
            "confirmed:" + case["candidate_id"],
        )
        c.save(path, label)
        print(
            case["candidate_id"],
            case["state_id"],
            label["style"],
            "valid",
            label["valid"],
            flush=True,
        )
        return label

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job, case) for case in m["cases"]]
        try:
            for f in as_completed(futures):
                f.result()
        except BaseException:
            for f in futures:
                f.cancel()
            raise


def trajectory(row):
    path = c.ACTIVE / "trajectory_batch_labels" / f"{row['unit']}.json"
    if path.exists():
        return c.read(path)
    tasks = c.read(c.ACTIVE / "tasks.json")
    task = c.x.b.Task.model_validate(tasks[row["task_id"]])
    prepared = []
    full = []
    for ordinal, digest in enumerate(row["label_digests"]):
        inp = inputs(digest)
        prefix, block = inp["prefix"], inp["block"]
        before = c.mech.replay(task.model_dump(mode="json"), prefix)
        after = c.mech.replay(task.model_dump(mode="json"), prefix + block)
        facts = c.mech.check_claims(
            prefix, block, after.environment, before.environment
        )
        relevant = c.task_rules(task, after.user.system_prompt)
        prepared.append(
            {
                "ordinal": ordinal,
                "digest": digest,
                "start": len(prefix),
                "stop": len(prefix) + len(block),
                "mechanical": c.mechanical_check(task, prefix, block, before, after),
                "fact_check": facts,
                "scenario_db": c.programmatic_scenario_violations(facts),
                "private_before": c.x.p4.state(before.environment)["user"],
                "private_after": c.x.p4.state(after.environment)["user"],
                "format_label": c.program_format_style(block),
            }
        )
        full = prefix + block
    style = [
        r
        for r in relevant
        if r["category"] in ("style", "persona")
        and r["rule_id"] != "r_5112db5336c2d337"
    ]
    scenario = [r for r in relevant if r["category"] == "scenario"]
    payload = {
        "output_format": "json",
        "rules": [c.compact_rule(r) for r in style + scenario],
        "private_scenario_verbatim": after.user.system_prompt.split("<scenario>", 1)[
            -1
        ].split("</scenario>", 1)[0],
        "history": [
            {
                k: m[k]
                for k in ("role", "content", "tool_calls", "id", "requestor", "error")
                if k in m
            }
            for m in full
        ],
        "turns": [
            {
                k: v
                for k, v in r.items()
                if k not in ("digest", "mechanical", "format_label")
            }
            for r in prepared
        ],
    }
    prompt = (
        c.LABEL_PROMPT
        + '\nMulti-turn batch: assessed_style_rule_ids and assessed_scenario_rule_ids are shared ONCE at top level. Return json {"assessed_style_rule_ids":[...],"assessed_scenario_rule_ids":[...],"turns":[{"ordinal":0,"style_departures":[],"scenario_violations":[]}, ...]}. Judge EVERY listed partner turn under its state and preceding history. Never use later facts to judge earlier turns. History shared once; start/stop indices identify blocks. Emit ONLY departures/violations per turn, no repeated compliant rules. Empty exceptions are explicit full-rule compliance verdicts, not missing labels.'
    )

    c.x.p4.UNIT.set("sampled_trajectory:" + row["unit"])
    c.x.p4.KEY.set(0)
    c.x.p4.ROLE.set("rule_labeler_batch")
    response = c.x.p4.llm_utils.generate(
        model=c.SOL,
        messages=[
            c.SystemMessage(role="system", content=prompt),
            c.UserMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=6000,
        **c.x.p4.llm_args(0, judge=True),
    )
    judge = json.loads(response.content)
    c.save(c.ACTIVE / "trajectory_batch_judgments" / f"{row['unit']}.json", judge)
    turns = {r["ordinal"]: r for r in judge["turns"]}
    assert set(turns) == set(range(len(prepared))), "Missing batch turn"
    labels = []
    for r in prepared:
        j = c.expand_judgment(
            {
                **turns[r["ordinal"]],
                "assessed_style_rule_ids": judge["assessed_style_rule_ids"],
                "assessed_scenario_rule_ids": judge["assessed_scenario_rule_ids"],
            },
            style,
            scenario,
        )
        assert {v["rule_id"] for v in j["style_labels"]} == {
            v["rule_id"] for v in style
        }, "Missing batch style rule"
        assert {v["rule_id"] for v in j["scenario_labels"]} == {
            v["rule_id"] for v in scenario
        }, "Missing batch scenario rule"
        sl = j["style_labels"] + [r["format_label"]]
        departed = [v for v in sl if v["status"] == "out_of_rule"]
        violated = [v for v in j["scenario_labels"] if v["violation"]]
        label = {
            "valid": not (r["mechanical"] or r["scenario_db"] or violated),
            "style": "out_of_rule" if departed else "in_rule",
            "mechanical_violations": r["mechanical"],
            "programmatic_scenario_violations": r["scenario_db"],
            "model_scenario_violations": violated,
            "departed_style_rules": departed,
            "all_style_rule_labels": sl,
            "all_scenario_rule_labels": j["scenario_labels"],
            "model_judgment": True,
            "model_requested": c.SOL,
            "temperature": 0,
            "batch_unit": row["unit"],
            "ordinal": r["ordinal"],
        }
        # Keep per-instance batch judgments; sharing of digest never overwrites full-case labels.
        labels.append({"digest": r["digest"], "label": label})
    result = {
        "trajectory": row,
        "labels": labels,
        "mechanical_version": "r2_native_private_goal_description",
    }
    c.save(path, result)
    print("TRAJECTORY", row["unit"], "turns", len(labels), flush=True)
    return result


def sampled(workers):
    c.setup("step2", workers)
    m = c.read(c.ACTIVE / "manifest.json")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(trajectory, r): r for r in m["trajectories"]}
        for f in as_completed(futures):
            row = futures[f]
            try:
                f.result()
            except Exception as exc:
                c.save(
                    c.ACTIVE / "batch_errors" / f"{row['unit']}.json",
                    {"type": type(exc).__name__, "message": str(exc)[:2000]},
                )
                print("FAILED", row["unit"], type(exc).__name__, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["cases", "sampled"])
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    globals()[a.phase](a.workers)
