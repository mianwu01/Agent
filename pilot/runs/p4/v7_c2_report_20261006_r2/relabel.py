"""Instance-mapped frozen labels of cases and historical complete partner turns."""

import argparse
import collections

import c2 as c

read, save = c.read, c.save


def manifest():
    """Prepare all block inputs without passing rewards to the labeler."""
    path = c.D["step2"] / "manifest.json"
    if path.exists():
        return read(path)
    oldplan = read(c.BASE / "v7_b2_report_20261005/plan.json")
    tasks = read(c.D["step2"] / "tasks.json")
    units = {}
    trajectories = []
    cases = []

    def add(task_id, prefix, block, instance):
        digest = c.x.p4.digest(
            {
                "task": task_id,
                "prefix": [c.x.b.ta.semantic(m) for m in prefix],
                "block": [c.x.b.ta.semantic(m) for m in block],
            }
        )
        if digest not in units:
            units[digest] = {"digest": digest, "task_id": task_id, "instances": []}
            save(
                c.D["step2"] / "label_inputs" / f"{digest}.json",
                {"task_id": task_id, "prefix": prefix, "block": block},
            )
        units[digest]["instances"].append(instance)
        return digest

    for case in oldplan["cases"]:
        sid, cid = case["state_id"], case["candidate_id"]
        r = read(c.BASE / "v7_b1_step2_20261004/replies" / f"{sid}:fixed:{cid}.json")
        digest = add(
            case["task_id"],
            r["prefix"][: -len(r["partner_block"])],
            r["partner_block"],
            {"case": cid},
        )
        cases.append(
            {
                "candidate_id": cid,
                "state_id": sid,
                "task_id": case["task_id"],
                "direction": case["direction"],
                "label_digest": digest,
            }
        )

    def addtrajectory(directory, unit, replyunit, cohort, condition):
        row = read(directory / "continuations" / f"{unit}.json")
        sim = read(directory / "trajectories" / f"{unit}.json")
        reply = read(directory / "replies" / f"{replyunit}.json")
        start = len(reply["prefix"]) - len(reply["partner_block"])
        indices = c.mech.partner_blocks(sim["messages"], start)
        digests = []
        for ordinal, blockindices in enumerate(indices):
            prefix = sim["messages"][: blockindices[0]]
            block = [sim["messages"][i] for i in blockindices]
            digests.append(
                add(
                    row["task_id"],
                    prefix,
                    block,
                    {
                        "trajectory": unit,
                        "cohort": cohort,
                        "condition": condition,
                        "ordinal": ordinal,
                        "initial": ordinal == 0,
                    },
                )
            )
        trajectories.append(
            {
                "unit": unit,
                "state_id": row["state_id"],
                "task_id": row["task_id"],
                "cohort": cohort,
                "condition": condition,
                "reward": row["reward"],
                "termination_reason": row["termination_reason"],
                "label_digests": digests,
                "initial_label": digests[0] if digests else None,
                "later_turn_n": max(0, len(digests) - 1),
            }
        )

    for sid in oldplan["b1_states"]:
        for condition in ["native", "single", "persistent"]:
            d = c.BASE / (
                "v6_paired_20261004"
                if condition == "native"
                else "v7_b1_step3b_20261004"
            )
            arm = "q" if condition == "native" else condition
            for j in range(6):
                for rep in range(4):
                    addtrajectory(
                        d,
                        f"{sid}:{arm}:d{j}:r{rep}",
                        f"{sid}:{'tools' if condition == 'persistent' else arm}:d{j}",
                        "B1",
                        condition,
                    )
    d = c.BASE / "v7_b2_b2_20261005"
    for f in sorted((d / "continuations").glob("*.json")):
        row = read(f)
        unit = row["unit"]
        addtrajectory(
            d,
            unit,
            f"{row['state_id']}:tools_v2:d{row['j']}",
            "v2_Sol" if "persistent_sol" in unit else "v2_Luna",
            "persistent",
        )
    result = {
        "unique_label_inputs": list(units.values()),
        "cases": cases,
        "trajectories": trajectories,
        "tasks_n": len(tasks),
        "raw_partner_turn_instances": sum(
            len(r["label_digests"]) for r in trajectories
        ),
    }
    save(path, result)
    print(
        "MANIFEST",
        len(units),
        "unique label inputs",
        len(trajectories),
        "trajectories",
        flush=True,
    )
    return result


def run(workers):
    c.setup("step2", workers)
    m = manifest()
    tasks = read(c.D["step2"] / "tasks.json")
    jobs = []
    for inp in m["unique_label_inputs"]:

        def job(key, inp=inp):
            target = c.D["step2"] / "mapped_labels" / f"{inp['digest']}.json"
            if target.exists():
                return read(target)
            data = read(c.D["step2"] / "label_inputs" / f"{inp['digest']}.json")
            label = c.annotate(
                c.x.b.Task.model_validate(tasks[inp["task_id"]]),
                data["prefix"],
                data["block"],
                key,
                inp["digest"],
            )
            save(target, label)
            return label

        jobs.append(job)
    c.x.b.run_jobs("step2", jobs, workers)


def summarize():
    import numpy as np

    m = read(c.D["step2"] / "manifest.json")
    labels = {
        r["digest"]: read(c.D["step2"] / "mapped_labels" / f"{r['digest']}.json")
        for r in m["unique_label_inputs"]
    }
    classes = {
        r["candidate_id"]: r
        for r in read(c.BASE / "v7_c_step2_20261005/reclassification.json")["cases"]
    }
    cases = []
    for case in m["cases"]:
        label = labels[case["label_digest"]]
        cases.append(
            {
                **case,
                "case_class": classes[case["candidate_id"]]["new_class"],
                "valid": label["valid"],
                "style": label["style"],
                "mechanical_violations": label["mechanical_violations"],
                "scenario_db_violations": label["programmatic_scenario_violations"],
                "scenario_model_violations": label["model_scenario_violations"],
                "departed_style_rules": label["departed_style_rules"],
            }
        )
    save(
        c.D["step2"] / "case_labels.json",
        {
            "model_labels": True,
            "cases": cases,
            "class_counts_by_style": {
                s: dict(
                    collections.Counter(
                        r["case_class"] for r in cases if r["valid"] and r["style"] == s
                    )
                )
                for s in ["in_rule", "out_of_rule"]
            },
            "invalid_cases": [r["candidate_id"] for r in cases if not r["valid"]],
        },
    )
    rows = []
    for r in m["trajectories"]:
        ll = [labels[d] for d in r["label_digests"]]
        invalid = [
            {
                "ordinal": i,
                "mechanical": v["mechanical_violations"],
                "scenario_db": v["programmatic_scenario_violations"],
                "scenario_model": v["model_scenario_violations"],
            }
            for i, v in enumerate(ll)
            if not v["valid"]
        ]
        rows.append(
            {
                **r,
                "valid": not invalid,
                "style": "out_of_rule"
                if any(v["style"] == "out_of_rule" for v in ll)
                else "in_rule",
                "invalid_turns": invalid,
                "out_of_rule_turns": sum(v["style"] == "out_of_rule" for v in ll),
            }
        )
    save(c.D["step2"] / "trajectory_labels.json", rows)
    rng = np.random.default_rng(2026100602)

    def score(rr):
        n = len(rr)
        k = sum(r["reward"] == 1 for r in rr)
        return {
            "successes": k,
            "n": n,
            "rate": k / n if n else None,
            "Wilson95_CI": list(c.x.stats.wilson(k, n)) if n else None,
        }

    def comparison(a, b):
        # Both samples remain historical/post-hoc filtered; not a randomized mediation contrast.
        aa = score(a)
        bb = score(b)
        taskids = sorted({r["task_id"] for r in a + b})
        samples = []
        for _ in range(1000):
            ids = rng.choice(taskids, len(taskids), replace=True) if taskids else []
            ar = [r for tid in ids for r in a if r["task_id"] == tid]
            br = [r for tid in ids for r in b if r["task_id"] == tid]
            if ar and br:
                samples.append(score(ar)["rate"] - score(br)["rate"])
        return {
            "persistent": aa,
            "single": bb,
            "difference": aa["rate"] - bb["rate"] if aa["n"] and bb["n"] else None,
            "task_cluster_bootstrap95_CI": list(np.quantile(samples, [0.025, 0.975]))
            if samples
            else None,
            "bootstrap_valid_replicates": len(samples),
        }

    results = {}
    b1 = [r for r in rows if r["cohort"] == "B1"]
    v2 = [r for r in rows if r["cohort"] == "v2_Luna"]
    v2states = {r["state_id"] for r in v2}
    for name, persistent, single in [
        (
            "B1_20states",
            [r for r in b1 if r["condition"] == "persistent"],
            [r for r in b1 if r["condition"] == "single"],
        ),
        (
            "v2_Luna_10states",
            v2,
            [r for r in b1 if r["condition"] == "single" and r["state_id"] in v2states],
        ),
    ]:
        results[name] = {}
        for split in ["all_raw", "all_valid", "in_rule", "out_of_rule"]:

            def select(rr):
                return [
                    r
                    for r in rr
                    if split == "all_raw"
                    or r["valid"]
                    and (split == "all_valid" or r["style"] == split)
                ]

            results[name][split] = comparison(select(persistent), select(single))
        results[name]["invalid_counts"] = {
            "persistent": sum(not r["valid"] for r in persistent),
            "single": sum(not r["valid"] for r in single),
        }
    save(
        c.D["step2"] / "persistent_split.json",
        {
            "comparisons": results,
            "v2_Sol_descriptive": {
                s: score(
                    [
                        r
                        for r in rows
                        if r["cohort"] == "v2_Sol" and r["valid"] and r["style"] == s
                    ]
                )
                for s in ["in_rule", "out_of_rule"]
            },
            "selection_caveat": "Validity/style splits condition on generated post-branch behaviors and can alter task/state composition; not causal mediation estimates. Raw denominators and per-trajectory instance labels retained.",
            "unique_labels": len(labels),
            "turn_instances": m["raw_partner_turn_instances"],
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["manifest", "run", "summarize"])
    ap.add_argument("--workers", type=int, default=64)
    args = ap.parse_args()
    if args.phase == "run":
        run(args.workers)
    else:
        globals()[args.phase]()
