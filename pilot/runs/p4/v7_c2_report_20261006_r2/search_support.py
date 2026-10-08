"""Parallel independent suffix units and full labels only for verified cases."""

from concurrent.futures import ThreadPoolExecutor

import c2 as c


def parallel(s, fn, items):
    phase, arm, task = s.PHASE.get(), s.ARM.get(), s.TASK.get()

    def wrapped(item):
        s.PHASE.set(phase)
        s.ARM.set(arm)
        s.TASK.set(task)
        return fn(item)

    with ThreadPoolExecutor(max_workers=s.WORKERS) as pool:
        return list(pool.map(wrapped, items))


def expand(s, case, family, index, arm, key, paths):
    s.TASK.set(case["task_id"])
    target = c.ACTIVE
    unit = f"exp{index:04d}:{case['state_id']}:{family}"
    file = target / "expansions" / f"{unit}.json"
    if file.exists():
        return c.read(file)

    def ref(j):
        r = c.sample_reply(
            case, j, key, "native", unit=f"{case['state_id']}:screen_reference:d{j}"
        )
        return r

    references = parallel(s, ref, range(6))
    reference = parallel(
        s,
        lambda pair: s.run_suffix(case, references[pair[0]], pair[1], key, "native"),
        [(j, r) for j in range(6) for r in range(2)],
    )
    mean = sum(r["reward"] == 1 for r in reference) / len(reference)
    families = (
        c.read(target / "effective_plan.json")["families"]
        if arm in ["A0", "A1", "A4"]
        else [family]
    )
    candidates, draws, statistics = [], [], {}
    for gen in families:
        replies = parallel(
            s,
            lambda j: c.sample_reply(case, j, key, gen, unit=f"{unit}:{gen}:d{j}"),
            range(6),
        )
        future = "vs" if arm == "A1" else "native"
        singles = parallel(
            s,
            lambda pair: s.run_suffix(case, replies[pair[0]], pair[1], key, future),
            [(j, r) for j in range(6) for r in range(2)],
        )
        draws.extend(singles)
        means = []
        for j, reply in enumerate(replies):
            rr = singles[j * 2 : j * 2 + 2]
            k = sum(r["reward"] == 1 for r in rr)
            means.append(k / 2)
            candidates.append(
                {
                    "candidate_id": f"{unit}:{gen}:d{j}",
                    "state": case,
                    "reply_unit": reply["unit"],
                    "family": gen,
                    "future": future,
                    "persistent_direction": False,
                    "screening_shift": k / 2 - mean,
                    "screening_successes": k,
                    "screening_n": 2,
                    "screening_reference_successes": sum(
                        r["reward"] == 1 for r in reference
                    ),
                    "screening_reference_n": len(reference),
                    "screening_style": "unassessed",
                }
            )
        avg = sum(means) / 6
        statistics[gen + ":single"] = {
            "reply_success_rates": means,
            "S_hat": sum((p - avg) ** 2 for p in means) / 5
            - sum(p * (1 - p) for p in means) / 6,
            "k": 6,
            "m": 2,
        }
        if arm in ["A1", "A2", "A3"]:
            pfuture = "vs" if arm == "A1" else gen
            persisted = (
                singles
                if arm == "A1"
                else parallel(
                    s,
                    lambda pair: s.run_suffix(
                        case,
                        replies[pair[0]],
                        pair[1],
                        key,
                        pfuture,
                        unit=f"{unit}:{gen}:persistent:d{pair[0]}:r{pair[1]}",
                    ),
                    [(j, r) for j in range(6) for r in range(2)],
                )
            )
            if arm != "A1":
                draws.extend(persisted)
            candidates.append(
                {
                    "candidate_id": f"{unit}:{gen}:persistent",
                    "state": case,
                    "family": gen,
                    "future": pfuture,
                    "persistent_direction": True,
                    "screening_shift": sum(v["reward"] == 1 for v in persisted) / 12
                    - mean,
                    "screening_successes": sum(v["reward"] == 1 for v in persisted),
                    "screening_n": 12,
                    "screening_reference_successes": sum(
                        v["reward"] == 1 for v in reference
                    ),
                    "screening_reference_n": len(reference),
                }
            )
    import collections

    outcomes = [int(r["reward"] == 1) for r in draws]
    p = sum(outcomes) / len(outcomes)
    frequency = collections.Counter(s.mode(r, paths) for r in draws)
    result = {
        "unit": unit,
        "state_id": case["state_id"],
        "task_id": case["task_id"],
        "family": family,
        "candidates": candidates,
        "screen_rewards": outcomes,
        "variance": p * (1 - p),
        "GT": sum(v == 1 for v in frequency.values()) / len(draws),
        "mode_counts": dict(frequency),
        "sensitivity": statistics,
        "completed": True,
    }
    c.save(file, result)
    return result


def check(s, candidate, key, sol=False):
    target = c.ACTIVE
    cid = candidate["candidate_id"]
    phase = "sol" if sol else "retest"
    file = target / "checks" / f"{cid}:{phase}.json"
    if file.exists():
        return c.read(file)
    case = candidate["state"]
    s.TASK.set(case["task_id"])
    agent = c.SOL if sol else None

    def fixed(rep):
        r = (
            c.sample_reply(
                case,
                rep,
                key,
                candidate["family"],
                unit=f"{cid}:{phase}:candidate_draw{rep}",
            )
            if candidate["persistent_direction"]
            else c.read(target / "replies" / f"{candidate['reply_unit']}.json")
        )
        return s.run_suffix(
            case,
            r,
            rep,
            key,
            candidate["future"],
            agent,
            unit=f"{cid}:{phase}:fixed:r{rep}",
        )

    def native(rep):
        r = c.sample_reply(
            case, rep, key, "native", unit=f"{cid}:{phase}:reference:d{rep}"
        )
        return s.run_suffix(
            case, r, 0, key, "native", agent, unit=f"{cid}:{phase}:native:r{rep}"
        )

    rows = parallel(
        s,
        lambda item: (fixed if item[0] == "fixed" else native)(item[1]),
        [(tag, i) for tag in ["fixed", "native"] for i in range(16)],
    )
    ff, nn = rows[:16], rows[16:]
    ks, kn = sum(r["reward"] == 1 for r in ff), sum(r["reward"] == 1 for r in nn)
    ci = c.x.stats.difference_interval(ks, 16, kn, 16)
    result = {
        "candidate": candidate,
        "agent": "Sol" if sol else "Luna",
        "fixed_successes": ks,
        "native_successes": kn,
        "n_each": 16,
        "shift": ks / 16 - kn / 16,
        "95_CI": ci,
        "same_direction_CI_excludes_zero": (
            candidate["screening_shift"] < 0 and ci[1] < 0
        )
        or (candidate["screening_shift"] > 0 and ci[0] > 0),
        "style": "unassessed",
        "valid": all(r["valid"] for r in rows),
        "fixed_units": [r["unit"] for r in ff],
        "native_units": [r["unit"] for r in nn],
        "completed_at_returned_tokens": sum(s.SPENT.values()),
        "completed_at_charged_tokens": sum(s.SPENT.values()) + sum(s.UNKNOWN.values()),
    }
    c.save(file, result)
    return result


def verified_labels(s, result):
    """Judge full style/persona only after a case survives independent retesting."""
    c.FULL_STYLE = True
    try:
        cand = result["candidate"]
        task = c.x.b.Task.model_validate(
            c.read(c.ACTIVE / "tasks.json")[cand["state"]["task_id"]]
        )
        if not cand["persistent_direction"] and cand["future"] == "native":
            r = c.read(c.ACTIVE / "replies" / f"{cand['reply_unit']}.json")
            label = c.annotate(
                task,
                r["prefix"][: -len(r["partner_block"])],
                r["partner_block"],
                0,
                cand["candidate_id"] + ":verified_labels",
            )
            labels = [label]
        else:
            labels = []
            for unit in result["fixed_units"]:
                sim = c.read(c.ACTIVE / "trajectories" / f"{unit}.json")
                if cand["persistent_direction"]:
                    start = cand["state"]["index"]
                else:
                    r = c.read(c.ACTIVE / "replies" / f"{cand['reply_unit']}.json")
                    start = len(r["prefix"]) - len(r["partner_block"])
                import labels_run

                digests = []
                for indices in c.mech.partner_blocks(sim["messages"], start):
                    prefix = sim["messages"][: indices[0]]
                    block = [sim["messages"][i] for i in indices]
                    digest = c.x.p4.digest(
                        {"task": task.id, "prefix": prefix, "block": block}
                    )
                    c.save(
                        c.ACTIVE / "label_inputs" / f"{digest}.json",
                        {"prefix": prefix, "block": block},
                    )
                    digests.append(digest)
                if digests:
                    batch = labels_run.trajectory(
                        {
                            "unit": unit + ":verified",
                            "task_id": task.id,
                            "label_digests": digests,
                        }
                    )
                    labels.extend(row["label"] for row in batch["labels"])
        result["verified_rule_labels"] = labels
        result["valid"] = result["valid"] and all(r["valid"] for r in labels)
        result["style"] = (
            "out_of_rule"
            if any(r["style"] == "out_of_rule" for r in labels)
            else "in_rule"
        )
        result["verified_labels_completed_at_tokens"] = sum(s.SPENT.values()) + sum(
            s.UNKNOWN.values()
        )
        result["verified_label_cost_metric"] = "returned + unknown reserved tokens"
        c.save(c.ACTIVE / "verified" / f"{cand['candidate_id']}.json", result)
        return result
    finally:
        c.FULL_STYLE = False
