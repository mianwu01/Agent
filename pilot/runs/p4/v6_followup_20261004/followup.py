"""Frozen offline follow-up; model calls are restricted to behavior annotation."""
# ruff: noqa: E402

import argparse
import collections
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy.stats import beta, binom

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT / "pilot"))
import p4_v6 as v6

from tau2.data_model.tasks import Task

SOURCE = ROOT / "pilot/runs/p4/v6_paired_20261004"
PREREG = json.loads((OUT / "prereg.json").read_text())
PREREG_HASH = hashlib.sha256((OUT / "prereg.json").read_bytes()).hexdigest()
ARMS = ["q", "q_prime"]
TRANSFERS = {"s012", "s018", "s019", "s020", "s022"}


def save(name, data):
    """Write analysis artifacts only inside the follow-up directory."""
    (OUT / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def load_data():
    """Read fixed observed outcomes and full suffix assertion vectors."""
    protocol = json.loads((SOURCE / "protocol.json").read_text())
    summary = json.loads((SOURCE / "summary.json").read_text())
    states = summary["states"]
    replies, vectors = [], []
    for state in states:
        rr, xx = [], []
        for arm in ARMS:
            rs, xs = [], []
            for j in range(6):
                rs.append(
                    json.loads(
                        (
                            SOURCE / "replies" / f"{state['state_id']}:{arm}:d{j}.json"
                        ).read_text()
                    )
                )
                rows = [
                    json.loads(
                        (
                            SOURCE
                            / "continuations"
                            / f"{state['state_id']}:{arm}:d{j}:r{rep}.json"
                        ).read_text()
                    )
                    for rep in range(4)
                ]
                xs.append(
                    [
                        [
                            int(row["reward"] == 1),
                            *[int(a["met"]) for a in row["assertions_final"]],
                        ]
                        for row in rows
                    ]
                )
            rr.append(rs)
            xx.append(np.asarray(xs, dtype=float))
        replies.append(rr)
        vectors.append(xx)
    return protocol, states, replies, vectors


def sensitivity(x):
    """Noise-correct six replicated reply means; retain negatives."""
    counts = x.sum(axis=-2)
    total = counts.sum(axis=-2)
    return (23 * (counts**2).sum(axis=-2) - 3 * total**2 - 20 * total) / 1440


def quantiles(x):
    return {
        "null_mean": float(np.mean(x)),
        "null_95th_percentile": float(np.quantile(x, 0.95)),
        "null_central_95_interval": np.quantile(x, [0.025, 0.975]).tolist(),
    }


def null_stat(observed, null):
    # Binary k=6,m=4 S statistics have lattice spacing >= 1/(1440*40).
    # This tolerance only reunites exact ties split by floating summation.
    upper = int(np.count_nonzero(null >= observed - 1e-12))
    return {
        "observed": float(observed),
        **quantiles(null),
        "permutation_p_upper": float((1 + upper) / (len(null) + 1)),
        "permutation_numerator": 1 + upper,
        "permutation_denominator": len(null) + 1,
    }


def bootstrap(states, values, seed):
    """Resample whole task clusters with state-equal means within each replicate."""
    groups = collections.defaultdict(list)
    for i, state in enumerate(states):
        groups[state["task_id"]].append(i)
    groups = list(groups.values())
    rng = np.random.default_rng(seed)
    nums, dens = [], []
    for _ in range(1000):
        ids = [
            i for g in rng.integers(len(groups), size=len(groups)) for i in groups[g]
        ]
        nums.append(float(np.sum(values[ids])))
        dens.append(len(ids))
    distribution = np.asarray(nums) / np.asarray(dens)
    return {
        "mean": float(np.mean(values)),
        "numerator": float(np.sum(values)),
        "denominator": len(values),
        "task_clusters": len(groups),
        "bootstrap_95_CI": np.quantile(distribution, [0.025, 0.975]).tolist(),
        "bootstrap_numerators": nums,
        "bootstrap_denominators": dens,
    }


def binomial_summary(k, n):
    interval = [
        0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1)),
        1 if k == n else float(beta.ppf(0.975, k + 1, n - k)),
    ]
    return {
        "count": k,
        "denominator": n,
        "share": k / n,
        "Clopper_Pearson_95_CI": interval,
        "chance_expected_count": 0.05 * n,
        "Binomial_n_005_central95_count_interval": binom.ppf([0.025, 0.975], n, 0.05)
        .astype(int)
        .tolist(),
        "caveat": "Discrete thresholds and clustered states limit independent-binomial interpretation.",
    }


def ratio_bootstrap(states, numerator, denominator, seed):
    """Retain raw sums and undefined zero-variance bootstrap ratios."""
    groups = collections.defaultdict(list)
    for i, state in enumerate(states):
        groups[state["task_id"]].append(i)
    groups = list(groups.values())
    rng = np.random.default_rng(seed)
    nums, dens, ratios = [], [], []
    for _ in range(1000):
        ids = [
            i for g in rng.integers(len(groups), size=len(groups)) for i in groups[g]
        ]
        n, d = float(numerator[ids].sum()), float(denominator[ids].sum())
        nums.append(n)
        dens.append(d)
        if d > 0:
            ratios.append(n / d)
    n, d = float(numerator.sum()), float(denominator.sum())
    return {
        "numerator": n,
        "denominator": d,
        "ratio": n / d if d > 0 else None,
        "bootstrap_95_CI": np.quantile(ratios, [0.025, 0.975]).tolist()
        if ratios
        else None,
        "valid_replicates": len(ratios),
        "bootstrap_numerators": nums,
        "bootstrap_denominators": dens,
    }


def duplicate_label_diagnostic(rows):
    """Describe repeated-input instability without revising any frozen labels."""
    result = {}
    for model in [
        PREREG["check3"]["primary_model"],
        PREREG["check3"]["agreement_model"],
    ]:
        scopes = {}
        for scope in ["all480", "nontransfer420"]:
            groups = collections.defaultdict(list)
            for row in rows:
                if row["labeler"] == model and (
                    scope == "all480" or row["state_id"] not in TRANSFERS
                ):
                    groups[row["input_sha256"]].append(row)
            repeated = [group for group in groups.values() if len(group) > 1]
            inconsistent = [
                group
                for group in repeated
                if len({(r["action"], r["communication"]) for r in group}) > 1
            ]
            scopes[scope] = {
                "repeated_input_groups": len(repeated),
                "repeated_input_blocks": sum(len(g) for g in repeated),
                "inconsistent_groups": len(inconsistent),
                "details": [
                    {
                        "units": [r["unit"] for r in g],
                        "labels": [
                            list(pair)
                            for pair in sorted(
                                {(r["action"], r["communication"]) for r in g}
                            )
                        ],
                    }
                    for g in inconsistent
                ],
            }
        result[model] = scopes
    return {
        "supplemental_not_preregistered": True,
        "no_labels_changed": True,
        "by_labeler": result,
    }


def bank_counts(replies, success, baseline, arms):
    """Exactly reproduce signature pooling, last representative and cutoff."""
    groups = collections.defaultdict(list)
    faithful = {}
    for arm in arms:
        for j, reply in enumerate(replies[arm]):
            groups[reply["partner_signature"]].append(arm * 6 + j)
            faithful[reply["partner_signature"]] = reply["fidelity"]["faithful"]
    counts = np.zeros((success.shape[0], 3), dtype=int)
    for sig, indices in groups.items():
        delta = success[:, indices].sum(axis=1) / (4 * len(indices)) - baseline
        passes = np.abs(delta) >= 0.25
        if faithful[sig]:
            counts[:, 0] += passes & (delta < 0)
            counts[:, 1] += passes & (delta >= 0)
        else:
            counts[:, 2] += passes
    return counts


def checks12():
    """Compute the preregistered vector-synchronized permutation null."""
    protocol, states, replies, vectors = load_data()
    manifest_paths = [
        SOURCE / "protocol.json",
        SOURCE / "summary.json",
        SOURCE / "candidate_bank.json",
    ]
    manifest_paths += sorted((SOURCE / "replies").glob("*.json"))
    manifest_paths += sorted((SOURCE / "continuations").glob("*.json"))
    save(
        "input_manifest_recompute.json"
        if (OUT / "input_manifest.json").exists()
        else "input_manifest.json",
        {
            "step1_started_at": time.time(),
            "prereg_sha256": PREREG_HASH,
            "inputs": {
                str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in manifest_paths
            },
            "numpy_version": np.__version__,
        },
    )
    rng = np.random.default_rng(PREREG["seeds"]["permutation"])
    reward_observed = np.empty((40, 2))
    reward_null = np.empty((40, 2, 2000))
    banks_observed = np.zeros((3, 3), int)
    banks_null = np.zeros((3, 2000, 3), int)
    local = []
    raw = {}
    for i, state in enumerate(states):
        perm_success = []
        observed_success = []
        for arm, x in enumerate(vectors[i]):
            order = rng.random((2000, 24)).argsort(axis=1)
            permuted = x.reshape(24, -1)[order].reshape(2000, 6, 4, -1)
            sn = sensitivity(permuted)
            so = sensitivity(x)
            reward_observed[i, arm] = so[0]
            reward_null[i, arm] = sn[:, 0]
            raw[f"{state['state_id']}_{ARMS[arm]}_orders"] = order.astype(np.uint8)
            raw[f"{state['state_id']}_{ARMS[arm]}_assertion_S"] = sn[:, 1:]
            perm_success.append(permuted[..., 0].sum(axis=2))
            observed_success.append(x[..., 0].sum(axis=1))
            assertions = []
            for a in range(x.shape[-1] - 1):
                before = replies[i][arm][0]["assertions_before"][a]
                after = [
                    r["assertions_after_partner"][a]["met"] for r in replies[i][arm]
                ]
                assertions.append(
                    {
                        "assertion": before["assertion"],
                        "before_met": before["met"],
                        "after_partner_successes": sum(after),
                        "after_partner_denominator": 6,
                        "suffix_successes": int(x[..., a + 1].sum()),
                        "suffix_denominator": 24,
                        **null_stat(so[a + 1], sn[:, a + 1]),
                    }
                )
            max_obs = float(np.max(so[1:]))
            max_null = sn[:, 1:].max(axis=1)
            raw[f"{state['state_id']}_{ARMS[arm]}_max_assertion_S"] = max_null
            local.append(
                {
                    "state_id": state["state_id"],
                    "family": ARMS[arm],
                    "assertions": assertions,
                    "max_over_assertions": null_stat(max_obs, max_null),
                    "max_exceeds_own_null95": bool(
                        max_obs > np.quantile(max_null, 0.95) + 1e-12
                    ),
                }
            )
        perm_success = np.concatenate(perm_success, axis=1)
        observed_success = np.concatenate(observed_success)[None, :]
        baseline = float(vectors[i][0][..., 0].mean())
        for b, arms in enumerate([[0], [1], [0, 1]]):
            banks_observed[b] += bank_counts(
                replies[i], observed_success, baseline, arms
            )[0]
            banks_null[b] += bank_counts(replies[i], perm_success, baseline, arms)
    prior = json.loads((SOURCE / "candidate_bank.json").read_text())
    prior_counts = [
        sum(e["faithful"] and e["direction"] == direction for e in prior)
        for direction in ["harmful", "beneficial"]
    ]
    assert banks_observed[2, :2].tolist() == prior_counts, (
        banks_observed,
        prior_counts,
    )
    bank_output = {}
    for b, name in enumerate(["q_only", "q_prime_only", "pooled_exact_original"]):
        bank_output[name] = {}
        for d, direction in enumerate(["harmful", "beneficial", "unfaithful"]):
            observed = int(banks_observed[b, d])
            bank_output[name][direction] = {
                **null_stat(observed, banks_null[b, :, d]),
                "expected_null_count_over_observed": float(
                    banks_null[b, :, d].mean() / observed
                )
                if observed
                else None,
                "null_counts": banks_null[b, :, d].tolist(),
            }
    masks = {
        "all40": np.ones(40, bool),
        "open_union": np.array([s["open_union"] for s in states]),
    }
    levels = {}
    for name, mask in masks.items():
        subset = [s for s, m in zip(states, mask) if m]
        levels[name] = {}
        for arm, family in enumerate(ARMS):
            observed = reward_observed[mask, arm]
            null = reward_null[mask, arm, :].mean(axis=0)
            threshold = np.quantile(reward_null[mask, arm, :], 0.95, axis=1)
            exceed = int(np.count_nonzero(observed > threshold + 1e-12))
            levels[name][family] = {
                **bootstrap(subset, observed, PREREG["seeds"]["bootstrap"]),
                **null_stat(observed.mean(), null),
                "null_mean_S_draws": null.tolist(),
                "state_exceedance": binomial_summary(exceed, len(observed)),
                "secondary_assertion_max_exceedance": binomial_summary(
                    sum(
                        x["max_exceeds_own_null95"]
                        for x in local
                        if x["family"] == family
                        and x["state_id"] in {s["state_id"] for s in subset}
                    ),
                    len(subset),
                ),
            }
    per_state = []
    for i, state in enumerate(states):
        per_state.append(
            {
                "state_id": state["state_id"],
                "task_id": state["task_id"],
                "open_union": state["open_union"],
                **{
                    family: {
                        **null_stat(reward_observed[i, arm], reward_null[i, arm]),
                        "exceeds_own_null95": bool(
                            reward_observed[i, arm]
                            > np.quantile(reward_null[i, arm], 0.95) + 1e-12
                        ),
                    }
                    for arm, family in enumerate(ARMS)
                },
            }
        )
    raw.update(
        reward_observed=reward_observed, reward_null=reward_null, banks_null=banks_null
    )
    np.savez_compressed(OUT / "permutation_raw.npz", **raw)
    save(
        "check1_permutation.json",
        {
            "prereg_sha256": PREREG_HASH,
            "permutations": 2000,
            "bank": bank_output,
            "mean_S_null_and_observed": levels,
            "source_bank_verified_counts": prior_counts,
        },
    )
    save(
        "check2_level.json",
        {
            "prereg_sha256": PREREG_HASH,
            "levels": levels,
            "states": per_state,
            "assertion_outcomes": local,
            "notes": [
                "Final-reward and assertion permutations use the same suffix-vector reassignment.",
                "All negative estimates retained; assertion maxima recomputed inside each permutation.",
            ],
        },
    )
    print("CHECKS 1 AND 2 COMPLETE", flush=True)


def semantic_message(message):
    return {
        k: message[k]
        for k in ["role", "content", "tool_calls", "requestor", "name", "error"]
        if k in message
    }


def label_blocks(workers):
    """Call only the two frozen labelers; never generate partner/agent suffixes."""
    protocol, states, replies, vectors = load_data()
    p4 = v6.p4
    p4.OUT = OUT
    p4.setup(ROOT / "api.txt", workers)
    p4.KEY_LIMITS = [threading.BoundedSemaphore(workers // 4) for _ in range(4)]
    tasks = json.loads((SOURCE / "tasks.json").read_text())
    payloads = {}
    for i, state in enumerate(states):
        source = json.loads(
            (SOURCE / "sources" / f"{state['source_id']}.json").read_text()
        )
        prefix = source["messages"][: state["index"]]
        orch = v6.build(Task.model_validate(tasks[state["task_id"]]), prefix)
        orch.initialize()
        private_before = p4.state(orch.environment)["user"]
        for arm in range(2):
            for reply in replies[i][arm]:
                payloads[reply["unit"]] = {
                    "agent_last_message": semantic_message(prefix[-1]),
                    "partner_block": [
                        semantic_message(m) for m in reply["partner_block"]
                    ],
                    "private_state_before": private_before,
                    "private_state_after": reply["state_after_partner"]["user"],
                    "assertions_before": reply["assertions_before"],
                    "assertions_after_partner": reply["assertions_after_partner"],
                }

    def label(unit, model, key):
        filename = OUT / "labels" / f"{unit}:{model}.json"
        if filename.exists():
            return json.loads(filename.read_text())
        result = p4.json_response(
            PREREG["check3"]["prompt"],
            payloads[unit],
            model,
            f"label:{unit}:{model}",
            key,
        )
        for axis in ["action", "communication"]:
            if result[axis] not in PREREG["check3"][axis]:
                raise ValueError(f"Invalid {axis} label")
        row = {
            "unit": unit,
            "state_id": unit.split(":")[0],
            "family": unit.split(":")[1],
            "draw": int(unit.split(":")[2][1:]),
            "labeler": model,
            "action": result["action"],
            "communication": result["communication"],
            "input_sha256": p4.digest(payloads[unit]),
            "prompt_sha256": hashlib.sha256(
                PREREG["check3"]["prompt"].encode()
            ).hexdigest(),
            "temperature": 0,
        }
        p4.save(filename, row)
        return row

    jobs = [
        (unit, model, n % 4)
        for n, unit in enumerate(payloads)
        for model in [
            PREREG["check3"]["primary_model"],
            PREREG["check3"]["agreement_model"],
        ]
    ]
    for attempt in range(4):
        failed = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(label, *job): job for job in jobs}
            for n, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                except Exception as exc:
                    job = futures[future]
                    failed.append(job)
                    p4.save(
                        OUT / "label_errors" / f"{job[0]}:{job[1]}:{attempt}.json",
                        {
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                if n % 40 == 0:
                    print(
                        "label pass",
                        attempt,
                        "completed",
                        n,
                        "/",
                        len(jobs),
                        "failed",
                        len(failed),
                        flush=True,
                    )
        if not failed:
            break
        jobs = failed
    if failed:
        raise RuntimeError(f"{len(failed)} label jobs incomplete")
    rows = [json.loads(p.read_text()) for p in sorted((OUT / "labels").glob("*.json"))]
    assert len(rows) == 960
    (OUT / "check3_labels.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
    usage, statuses, models = (
        collections.Counter(),
        collections.Counter(),
        collections.defaultdict(collections.Counter),
    )
    for path in (OUT / "requests").glob("*.json"):
        request = json.loads(path.read_text())
        statuses[request["status"]] += 1
        for key in ["prompt_tokens", "completion_tokens"]:
            usage[key] += (request.get("usage") or {}).get(key, 0)
            models[request["request"]["model"]][key] += (
                request.get("usage") or {}
            ).get(key, 0)
    save(
        "labeler_usage.json",
        {
            "statuses": dict(statuses),
            "token_usage": dict(usage),
            "by_requested_model": {k: dict(v) for k, v in models.items()},
        },
    )
    print("LABELS COMPLETE", flush=True)


def kappa(rows, axis):
    pairs = collections.defaultdict(dict)
    for row in rows:
        pairs[row["unit"]][row["labeler"]] = row[axis]
    sol, luna = PREREG["check3"]["primary_model"], PREREG["check3"]["agreement_model"]
    left = [p[sol] for p in pairs.values()]
    right = [p[luna] for p in pairs.values()]
    a, b = collections.Counter(left), collections.Counter(right)
    n = len(left)
    agreement = sum(x == y for x, y in zip(left, right)) / n
    expected = sum(a[k] * b[k] for k in set(a) | set(b)) / n**2
    return {
        "n": n,
        "observed_agreement": agreement,
        "chance_agreement": expected,
        "kappa": (agreement - expected) / (1 - expected) if expected < 1 else None,
        "confusion": {
            x: dict(collections.Counter(y for xx, y in zip(left, right) if xx == x))
            for x in set(left)
        },
    }


def label_variance(groups):
    """Report weighted ANOVA and equal-observed-label noise correction distinctly."""
    sizes = np.array([len(v) for v in groups.values()], dtype=float)
    successes = np.array([sum(v) for v in groups.values()], dtype=float)
    means = successes / sizes
    n, total = sizes.sum(), successes.sum()
    grand = total / n
    between_ss = float(np.sum(sizes * (means - grand) ** 2))
    within_ss = float(np.sum(sizes * means * (1 - means)))
    var_means = float(means.var(ddof=1)) if len(means) > 1 else 0.0
    noise = float(np.mean(means * (1 - means) / (sizes - 1))) if len(means) > 1 else 0.0
    return {
        "labels": [
            {
                "label": list(label),
                "successes": int(sum(outcomes)),
                "denominator": len(outcomes),
                "mean": sum(outcomes) / len(outcomes),
            }
            for label, outcomes in groups.items()
        ],
        "between_sum_squares": between_ss,
        "within_sum_squares": within_ss,
        "total_sum_squares": between_ss + within_ss,
        "denominator": int(n),
        "between_variance": between_ss / n,
        "within_variance": within_ss / n,
        "total_variance": (between_ss + within_ss) / n,
        "between_share": between_ss / (between_ss + within_ss)
        if between_ss + within_ss > 0
        else None,
        "label_mean_sample_variance": var_means,
        "noise_correction": noise,
        "S_label_hat_equal_labels": var_means - noise,
        "successes": int(total),
    }


def check3():
    """Compare behavioral diversity and outcome decomposition with both labelers."""
    protocol, states, replies, vectors = load_data()
    labels = [
        json.loads(line)
        for line in (OUT / "check3_labels.jsonl").read_text().splitlines()
    ]
    lookup = {
        (r["unit"], r["labeler"]): (r["action"], r["communication"]) for r in labels
    }
    models = {}
    for model in [
        PREREG["check3"]["primary_model"],
        PREREG["check3"]["agreement_model"],
    ]:
        results = []
        for i, state in enumerate(states):
            pairs = [
                [lookup[(r["unit"], model)] for r in replies[i][a]] for a in range(2)
            ]
            sets = [set(p) for p in pairs]
            novel = sum(label not in sets[0] for label in pairs[1])
            pooled = collections.defaultdict(list)
            family_stats = {}
            for a, arm in enumerate(ARMS):
                grouped = collections.defaultdict(list)
                for j, label in enumerate(pairs[a]):
                    values = vectors[i][a][j, :, 0].tolist()
                    grouped[label].extend(values)
                    pooled[label].extend(values)
                family_stats[arm] = label_variance(grouped)
            results.append(
                {
                    "state_id": state["state_id"],
                    "task_id": state["task_id"],
                    "open_union": state["open_union"],
                    "mandated_transfer": state["state_id"] in TRANSFERS,
                    "q_distinct": len(sets[0]),
                    "q_prime_distinct": len(sets[1]),
                    "paired_distinct_difference": len(sets[1]) - len(sets[0]),
                    "novel_q_prime_numerator": novel,
                    "novel_q_prime_denominator": 6,
                    "novel_q_prime_share": novel / 6,
                    "behavior_variance": {
                        "pooled_across_families": label_variance(pooled),
                        **family_stats,
                        "S_label_contrast": family_stats["q_prime"][
                            "S_label_hat_equal_labels"
                        ]
                        - family_stats["q"]["S_label_hat_equal_labels"],
                    },
                }
            )
        aggregate = {}
        for name in ["nontransfer_all", "nontransfer_open_union", "mandated_transfer"]:
            subset = [
                r
                for r in results
                if (
                    r["mandated_transfer"]
                    if name == "mandated_transfer"
                    else not r["mandated_transfer"]
                    and (name != "nontransfer_open_union" or r["open_union"])
                )
            ]
            values = {}
            for measure in [
                "q_distinct",
                "q_prime_distinct",
                "paired_distinct_difference",
                "novel_q_prime_share",
            ]:
                values[measure] = bootstrap(
                    subset,
                    np.asarray([r[measure] for r in subset], float),
                    PREREG["seeds"]["bootstrap"],
                )
            values["S_label_contrast"] = bootstrap(
                subset,
                np.asarray(
                    [r["behavior_variance"]["S_label_contrast"] for r in subset]
                ),
                PREREG["seeds"]["bootstrap"],
            )
            values["pooled_variance_raw"] = {
                "between_sum_squares": sum(
                    r["behavior_variance"]["pooled_across_families"][
                        "between_sum_squares"
                    ]
                    for r in subset
                ),
                "within_sum_squares": sum(
                    r["behavior_variance"]["pooled_across_families"][
                        "within_sum_squares"
                    ]
                    for r in subset
                ),
                "denominator": 48 * len(subset),
            }
            for component in ["between_variance", "within_variance", "total_variance"]:
                values[component] = bootstrap(
                    subset,
                    np.asarray(
                        [
                            r["behavior_variance"]["pooled_across_families"][component]
                            for r in subset
                        ]
                    ),
                    PREREG["seeds"]["bootstrap"],
                )
            values["between_label_variance_share"] = ratio_bootstrap(
                subset,
                np.asarray(
                    [
                        r["behavior_variance"]["pooled_across_families"][
                            "between_sum_squares"
                        ]
                        for r in subset
                    ]
                ),
                np.asarray(
                    [
                        r["behavior_variance"]["pooled_across_families"][
                            "total_sum_squares"
                        ]
                        for r in subset
                    ]
                ),
                PREREG["seeds"]["bootstrap"],
            )
            for family in ARMS:
                values["S_label_" + family] = bootstrap(
                    subset,
                    np.asarray(
                        [
                            r["behavior_variance"][family]["S_label_hat_equal_labels"]
                            for r in subset
                        ]
                    ),
                    PREREG["seeds"]["bootstrap"],
                )
            aggregate[name] = values
        models[model] = {"aggregate": aggregate, "states": results}
    agreement = {
        scope: {
            axis: kappa(
                [
                    r
                    for r in labels
                    if scope == "all480" or r["state_id"] not in TRANSFERS
                ],
                axis,
            )
            for axis in ["action", "communication"]
        }
        for scope in ["all480", "nontransfer420"]
    }
    save(
        "check3_diversity.json",
        {
            "prereg_sha256": PREREG_HASH,
            "agreement": agreement,
            "duplicate_input_consistency": duplicate_label_diagnostic(labels),
            "labelers": models,
            "limitations": [
                "Label agreement is measured, not assumed.",
                "ANOVA is raw and descriptive; finite-sample between-label variance includes noise. Equal-label corrected S changes the weighting distribution and is not identical to text-draw S.",
                "Behavior-label grouping across families can reflect family mean shifts; do not interpret it as a new causal experiment.",
                "Equal-label S noise correction treats pooled suffixes as Bernoulli replicates; it does not model additional nested heterogeneity between text replies sharing a label. This statistic is descriptive and not used in the routing rule.",
            ],
        },
    )
    print("CHECK 3 COMPLETE", flush=True)


def figures_report():
    """Export local figures and apply the frozen decision rules without tuning."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c1 = json.loads((OUT / "check1_permutation.json").read_text())
    c2 = json.loads((OUT / "check2_level.json").read_text())
    c3 = json.loads((OUT / "check3_diversity.json").read_text())

    def ci_text(interval):
        return (
            "undefined"
            if interval is None
            else f"[{interval[0]:.4f}, {interval[1]:.4f}]"
        )

    raw = np.load(OUT / "permutation_raw.npz")
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout="constrained")
    for a, family in enumerate(ARMS):
        observed, null = raw["reward_observed"][:, a], raw["reward_null"][:, a, :]
        q = np.quantile(null, [0.025, 0.95, 0.975], axis=1)
        ax = axes[a, 0]
        ax.fill_between(
            np.arange(40),
            q[0],
            q[2],
            color="gray",
            alpha=0.25,
            label="Per-state central95% null band",
        )
        ax.plot(q[1], ":", color="gray", label="Null95th percentile")
        ax.scatter(np.arange(40), observed, s=20, label="Observed S_hat")
        ax.axhline(0, color="black", lw=0.6)
        ax.set(title=family, xlabel="Fixed state index", ylabel="S_hat")
        ax.legend(fontsize=8)
        ax = axes[a, 1]
        bins = np.linspace(
            min(observed.min(), null.min()) - 0.01,
            max(observed.max(), null.max()) + 0.01,
            25,
        )
        ax.hist(
            null.flatten(),
            bins=bins,
            density=True,
            color="gray",
            alpha=0.4,
            label="Null mixture across states",
        )
        ax.hist(
            observed,
            bins=bins,
            density=True,
            histtype="step",
            lw=2,
            label="Observed states",
        )
        ax.set(xlabel="S_hat", ylabel="Density")
        ax.legend(fontsize=8)
    fig.savefig(OUT / "S_hat_null_distribution.png", dpi=180)
    fig.savefig(OUT / "S_hat_null_distribution.pdf")
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), layout="constrained")
    for ax, (model, results) in zip(axes, c3["labelers"].items()):
        ss = results["states"]
        xx = np.arange(40)
        ax.plot(xx, [s["q_distinct"] for s in ss], "o-", label="q")
        ax.plot(xx, [s["q_prime_distinct"] for s in ss], "s-", label="q_prime")
        for i, s in enumerate(ss):
            if s["mandated_transfer"]:
                ax.axvspan(i - 0.4, i + 0.4, color="gray", alpha=0.2)
        ax.set(
            title=model,
            xlabel="Fixed state index; gray = mandated transfer",
            ylabel="Distinct behavior label pairs",
            ylim=(0.5, 6.5),
        )
        ax.legend()
    fig.savefig(OUT / "behavior_distinct_counts.png", dpi=180)
    fig.savefig(OUT / "behavior_distinct_counts.pdf")
    plt.close(fig)
    level = c2["levels"]["open_union"]["q"]
    ci = level["bootstrap_95_CI"]
    band = level["null_central_95_interval"]
    matters = (
        "Yes"
        if ci[0] > level["null_95th_percentile"]
        and level["permutation_p_upper"] <= 0.05
        else "No"
        if ci[0] >= band[0] and ci[1] <= band[1]
        else "Indeterminate"
    )
    behavioral = {}
    for model, results in c3["labelers"].items():
        aggregate = results["aggregate"]["nontransfer_open_union"]
        d = aggregate["paired_distinct_difference"]["bootstrap_95_CI"]
        novel = aggregate["novel_q_prime_share"]["mean"]
        behavioral[model] = (
            "Yes"
            if d[0] > 0 and novel >= 0.2
            else "No"
            if d[0] <= 0 <= d[1] and novel < 0.2
            else "Indeterminate"
        )
    bank_decisions = {}
    for direction in ["harmful", "beneficial"]:
        stat = c1["bank"]["pooled_exact_original"][direction]
        lo, hi = stat["null_central_95_interval"]
        bank_decisions[direction] = (
            "Yes"
            if stat["observed"] > stat["null_95th_percentile"]
            and stat["permutation_p_upper"] <= 0.05
            else "No (approximately null)"
            if lo <= stat["observed"] <= hi and stat["permutation_p_upper"] > 0.05
            else "Outside table / below null or mixed threshold"
        )
    broad = behavioral[PREREG["check3"]["primary_model"]]
    route = (
        "A"
        if matters == "No"
        else "B"
        if matters == "Yes" and broad == "No"
        else "C"
        if matters == "Yes" and broad == "Yes"
        else "No A/B/C row applies"
    )
    ds = [
        direction
        for direction, result in bank_decisions.items()
        if result == "No (approximately null)"
    ]
    decision = {
        "check2_q_open_union": matters,
        "check3_by_labeler": behavioral,
        "check1_by_direction": bank_decisions,
        "route": route,
        "route_D_directions": ds,
        "criteria": PREREG["decision_operationalization"],
    }
    save("decision.json", decision)
    lines = [
        "# P4 v6.1 frozen follow-up",
        "",
        f"Preregistered SHA256: `{PREREG_HASH}`. No new continuations; 960 frozen behavior labels (480 blocks × 2 models). Original run read-only.",
        "",
        "## Check 1: candidate bank permutation null",
        "",
        "| Bank | Direction | Observed | Null mean | Null95th | p upper | Null mean / observed |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, bank in c1["bank"].items():
        for direction in ["harmful", "beneficial"]:
            s = bank[direction]
            lines.append(
                f"| {name} | {direction} | {s['observed']:.0f} | {s['null_mean']:.2f} | {s['null_95th_percentile']:.2f} | {s['permutation_p_upper']:.4f} | {s['expected_null_count_over_observed']:.3f} |"
            )
    lines += [
        "",
        "The expected null-count ratio is not an entry-specific FDR; it is retained without clipping. Within-family permutation preserves family means, including q_prime − q mean shifts.",
        "",
        "## Check 2: sensitivity level",
        "",
        "| Stratum | Family | Mean S_hat [cluster95% CI] | Null mean /95th | p | States above own null95th [binomial95% CI] | Assertion max above null |",
        "|---|---|---|---|---:|---|---|",
    ]
    for name, families in c2["levels"].items():
        for family, s in families.items():
            e = s["state_exceedance"]
            a = s["secondary_assertion_max_exceedance"]
            lines.append(
                f"| {name} | {family} | {s['mean']:.5f} {ci_text(s['bootstrap_95_CI'])} | {s['null_mean']:.5f} / {s['null_95th_percentile']:.5f} | {s['permutation_p_upper']:.4f} | {e['count']}/{e['denominator']} {ci_text(e['Clopper_Pearson_95_CI'])} | {a['count']}/{a['denominator']} |"
            )
    lines += [
        "",
        "Binomial chance-count intervals and all assertion-specific estimates are in check2_level.json. Assertion maxima are recalculated inside each synchronized-vector permutation, accounting for the within-state assertion search. Task dependence and discrete null distributions limit a nominal 5% state exceedance reference.",
        "",
        "## Check 3: behavioral broadening",
        "",
        "| Labeler | Stratum | Distinct q | Distinct q_prime | Paired difference [95% CI] | New-label share [95% CI] | Behavior S contrast [95% CI] | Between-label share [95% CI] |",
        "|---|---|---:|---:|---|---|---|---|",
    ]
    for model, results in c3["labelers"].items():
        for name, a in results["aggregate"].items():
            d = a["paired_distinct_difference"]
            n = a["novel_q_prime_share"]
            v = a["S_label_contrast"]
            share = a["between_label_variance_share"]
            share_text = (
                "undefined (zero outcome variance)"
                if share["ratio"] is None
                else f"{share['ratio']:.3f} {ci_text(share['bootstrap_95_CI'])}"
            )
            lines.append(
                f"| {model} | {name} (n={d['denominator']}) | {a['q_distinct']['mean']:.3f} | {a['q_prime_distinct']['mean']:.3f} | {d['mean']:.3f} {ci_text(d['bootstrap_95_CI'])} | {n['mean']:.3f} {ci_text(n['bootstrap_95_CI'])} | {v['mean']:.5f} {ci_text(v['bootstrap_95_CI'])} | {share_text} |"
            )
    lines += [
        "",
        "Agreement kappa (all480 / nontransfer420): "
        + str(
            {
                axis: [
                    c3["agreement"][scope][axis]["kappa"]
                    for scope in ["all480", "nontransfer420"]
                ]
                for axis in ["action", "communication"]
            }
        ),
        "",
        "Supplemental, not preregistered: repeated-input consistency diagnostic (no relabeling): "
        + str(
            {
                model: {
                    scope: {
                        key: values[key]
                        for key in [
                            "repeated_input_groups",
                            "repeated_input_blocks",
                            "inconsistent_groups",
                        ]
                    }
                    for scope, values in scopes.items()
                }
                for model, scopes in c3["duplicate_input_consistency"][
                    "by_labeler"
                ].items()
            }
        ),
        "The primary Sol labeler assigns different communication labels to the exact same terminal-token input in three transfer states. Those states are excluded from primary aggregates, but this provides direct evidence of annotator instability even at temperature0. Neither labeler's outputs were corrected or tuned.",
        "",
        "Five mandated-transfer states are excluded from primary diversity aggregates and reported separately. All per-state label-group counts, raw between/within sums of squares, and denominators are in check3_diversity.json. Weighted raw ANOVA and equal-label noise-corrected S are different estimands; neither establishes a new causal intervention.",
        "Observed new-label share is finite-sample novelty relative to six q draws, not proof that the label is outside the population support of q.",
        "The equal-label S correction assumes Bernoulli replication within each pooled label and does not account for additional nested text-reply heterogeneity. It is descriptive and not the primary routing statistic.",
        "",
        "## Frozen decision table result",
        "",
        f"Check2 (q, open union): **{matters}**. Check3 by labeler: {behavioral}. Check1 by direction: {bank_decisions}.",
        "",
        f"Applicable A/B/C row: **{route}**. Route D applies to: {ds or 'none under frozen approximate-null criterion'}.",
        "",
        f"The q permutation test is significant (p={level['permutation_p_upper']:.4f}) and the mean bootstrap CI is {ci_text(ci)}, but the frozen conservative Yes criterion additionally requires its lower bound to exceed the null95th percentile {level['null_95th_percentile']:.5f}. This criterion is not met. The CI is not wholly inside the null band either. Thus Check2 is not classified as No / partner barely matters. Check3's paired difference CI crosses0 while novelty exceeds20%, so it satisfies neither the frozen Yes nor No criterion.",
        "",
        "Original decision table:",
        "",
        "| Check2 | Check3 | Check1 | Route |",
        "|---|---|---|---|",
    ]
    for row in PREREG["decision_table"]:
        lines.append(
            f"| {row['check2']} | {row['check3']} | {row['check1']} | {row['route']} |"
        )
    lines += [
        "",
        "Any indeterminate or labeler-discordant result remains unresolved rather than being forced into a route. Absence of significant contrast is not evidence of equivalence; route C is the requested planning rule, not a proof of a universal premise failure.",
        "",
        "## Temperature caveat",
        "",
        PREREG["caveat"],
        "",
        "Raw permutation arrays: permutation_raw.npz. Label requests and token usage: requests/ and labeler_usage.json.",
        "",
        "Preregistration versions: prereg.json is unchanged. prereg_amendment.json records a transport-provenance omission: the inherited p4.json_response helper appends the constant ` Return valid json.` to the registered core system prompt. The amendment preserves both the original core and full wire prompt. The same wrapper was used from the first call for both models; no definitions, thresholds, seeds or labels changed, and no extra labeling was performed.",
        "",
        "The amendment also records an arithmetic implementation correction. For binary k=6,m=4 outcomes, the identical registered estimator is evaluated as `(23*sum(c_j^2)-3*T^2-20*T)/1440`. Exact ties are reunited with a 1e-12 comparison tolerance, far below the statistic lattice. The initial q open-union p=0.003498 is corrected to0.004998; q_prime states exceeding their own95th percentile decrease from6 to5. The prior output version is preserved in arithmetic_before_correction/. Definitions, permutation draws, thresholds and labels are unchanged.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["offline", "labels", "diversity", "report"])
    parser.add_argument("--workers", type=int, default=96)
    args = parser.parse_args()
    {
        "offline": checks12,
        "labels": lambda: label_blocks(args.workers),
        "diversity": check3,
        "report": figures_report,
    }[args.phase]()
    assert hashlib.sha256((OUT / "prereg.json").read_bytes()).hexdigest() == PREREG_HASH


if __name__ == "__main__":
    main()
