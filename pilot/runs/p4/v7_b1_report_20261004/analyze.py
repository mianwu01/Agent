"""Offline mode attribution, retest intervals and round-1 reporting."""

import argparse
import collections
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import matplotlib

matplotlib.use("Agg")
import b1 as b
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import beta, norm

OUT = b.OUT
D = b.D
BASE = b.BASE
read = b.read
save = b.save


def features(step):
    """Reconstruct final user DB without sampling; freeze historical M2-M4 definitions."""
    paths = read(BASE / "v7_e2_20261004/task_device_fields.json")
    tasks = read(D[step] / "tasks.json")
    feature_dir = D[step] / "features"
    feature_dir.mkdir(exist_ok=True)
    rows = list((D[step] / "continuations").glob("*.json"))

    def extract(path):
        target = feature_dir / path.name
        if target.exists():
            return read(target)
        r = read(path)
        unit = r["unit"]
        prefixunit = unit.rsplit(":", 1)[0]
        if ":persistent:" in unit:
            prefixunit = f"{r['state_id']}:tools:d{r['j']}"
        reply = read(D[step] / "replies" / f"{prefixunit}.json")
        sim = read(D[step] / "trajectories" / path.name)
        orch = b.v6.build(b.Task.model_validate(tasks[r["task_id"]]), sim["messages"])
        orch.initialize()
        suffix = sim["messages"][len(reply["prefix"]) :]
        row = {
            **r,
            "reward": int(r["reward"] == 1),
            "family": unit.split(":")[1],
            "final_user_state": b.p4.state(orch.environment)["user"],
            "assertions": r["assertions_final"],
            "next_action_type": b.ta.action_type(suffix),
            "agent_tool_path": [
                c["name"]
                for m in suffix
                if m["role"] == "assistant"
                for c in m.get("tool_calls") or []
            ],
            "next_turn": b.ta.first_next_turn(sim["messages"], len(reply["prefix"])),
        }
        row["modes"] = {m: b.ta.mode_key(row, m, paths) for m in ["M2", "M3", "M4"]}
        save(target, row)
        return row

    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for i, f in enumerate(as_completed([pool.submit(extract, p) for p in rows]), 1):
            results.append(f.result())
            if i % 100 == 0:
                print("features", step, i, "/", len(rows), flush=True)
    results.sort(key=lambda r: r["unit"])
    (D[step] / "features.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
    )
    return results


def load_features(step):
    return [
        json.loads(s) for s in (D[step] / "features.jsonl").read_text().splitlines()
    ]


def cluster_mean(rows, field, seed=2026100804):
    tids = sorted({r["task_id"] for r in rows})
    rng = np.random.default_rng(seed)
    bytask = {t: [r[field] for r in rows if r["task_id"] == t] for t in tids}
    samples = [
        np.mean(
            [x for t in rng.choice(tids, len(tids), replace=True) for x in bytask[t]]
        )
        for _ in range(1000)
    ]
    return {
        "mean": float(np.mean([r[field] for r in rows])),
        "numerator": float(sum(r[field] for r in rows)),
        "denominator": len(rows),
        "task_clusters": len(tids),
        "bootstrap_95_CI": np.quantile(samples, [0.025, 0.975]).tolist(),
    }


def attribution():
    ao = load_features("step1")
    assert len(ao) == 960
    old = [
        json.loads(s)
        for s in (BASE / "v7_e2_20261004/mode_rows.jsonl").read_text().splitlines()
    ]
    cases = read(OUT / "plan.json")["states"]
    bystate = {
        c["state_id"]: sorted(
            [r for r in ao if r["state_id"] == c["state_id"]], key=lambda r: r["rep"]
        )
        for c in cases
    }
    rng = np.random.default_rng(2026100805)
    results = {}
    per_state = []
    curve_rows = []
    for m in ["M2", "M3", "M4"]:
        results[m] = {}
        for c in cases:
            sid = c["state_id"]
            controls = bystate[sid]
            full = {r["modes"][m] for r in controls}
            source_modes = {
                a: {
                    r["modes"][m]
                    for r in old
                    if r["state_id"] == sid and r["family"] == a
                }
                for a in ["q", "q_prime"]
            }
            row = {
                "mode": m,
                "state_id": sid,
                "task_id": c["task_id"],
                "agent_only_distinct": len(full),
                "families": {},
            }
            for arm, ms in source_modes.items():
                attr = ms - full
                row["families"][arm] = {
                    "attributable_numerator": len(attr),
                    "source_distinct_denominator": len(ms),
                    "share": len(attr) / len(ms),
                    "absent_modes": sorted(attr),
                    "covered_modes": sorted(ms & full),
                }
            curves = []
            for _ in range(50):
                seen = set()
                sat = []
                counts = {a: [] for a in source_modes}
                for i in rng.permutation(24):
                    seen.add(controls[i]["modes"][m])
                    sat.append(len(seen))
                    for arm, ms in source_modes.items():
                        counts[arm].append(len(ms - seen))
                curves.append({"saturation": sat, **counts})
            means = {}
            for kind in ["saturation", "q", "q_prime"]:
                arr = np.asarray([r[kind] for r in curves], float)
                means[kind] = {
                    "mean": arr.mean(axis=0).tolist(),
                    "order_band_low": np.quantile(arr, 0.025, axis=0).tolist(),
                    "order_band_high": np.quantile(arr, 0.975, axis=0).tolist(),
                }
            prefix_counts = {}
            for n in [6, 12, 18, 24]:
                control_set = {r["modes"][m] for r in controls[:n]}
                prefix_counts[str(n)] = {
                    a: len(ms - control_set) for a, ms in source_modes.items()
                }
            row["fixed_rep_prefix_attribution_counts"] = prefix_counts
            per_state.append(row)
            curve_rows.append(
                {
                    "mode": m,
                    "state_id": sid,
                    "task_id": c["task_id"],
                    "curves50": curves,
                    "summary": means,
                }
            )
        selected = [r for r in per_state if r["mode"] == m]
        for arm in ["q", "q_prime"]:
            num = sum(r["families"][arm]["attributable_numerator"] for r in selected)
            den = sum(
                r["families"][arm]["source_distinct_denominator"] for r in selected
            )
            cirows = [
                {
                    "task_id": r["task_id"],
                    "count": r["families"][arm]["attributable_numerator"],
                    "share": r["families"][arm]["share"],
                }
                for r in selected
            ]
            results[m][arm] = {
                "attributable_count": num,
                "source_distinct_count": den,
                "pooled_share": num / den,
                "per_state_count": cluster_mean(cirows, "count"),
                "per_state_share": cluster_mean(cirows, "share"),
                "prefix_counts": {
                    str(n): sum(
                        r["fixed_rep_prefix_attribution_counts"][str(n)][arm]
                        for r in selected
                    )
                    for n in [6, 12, 18, 24]
                },
            }
    save(
        D["step1"] / "attribution.json",
        {
            "per_state": per_state,
            "aggregate": results,
            "limitation": "Partner-attributable is finite-sample absence from original-block control at same state. Twenty-four draws cannot establish population support exclusion; continued later partner randomness is part of this agent-only control exactly as requested.",
        },
    )
    save(D["step1"] / "saturation_curves.json", curve_rows)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, m in zip(axes, ["M2", "M3", "M4"]):
        rs = [r for r in curve_rows if r["mode"] == m]
        for kind in ["saturation", "q", "q_prime"]:
            values = np.asarray(
                [[r["curves50"][j][kind] for r in rs] for j in range(50)], float
            ).sum(axis=1)
            ax.plot(np.arange(1, 25), values.mean(axis=0), label=kind)
            ax.fill_between(
                np.arange(1, 25),
                np.quantile(values, 0.025, axis=0),
                np.quantile(values, 0.975, axis=0),
                alpha=0.12,
            )
        ax.set(
            title=m,
            xlabel="Original-block control suffixes / state",
            ylabel="Sum of per-state mode counts",
        )
        ax.legend()
    fig.suptitle(
        "Control reachable modes (saturation) and remaining absent q / q_prime modes; order bands"
    )
    fig.tight_layout()
    for ext in ["png", "pdf"]:
        fig.savefig(D["step1"] / f"attribution_saturation.{ext}", dpi=160)
    plt.close(fig)
    state_figure_dir = D["step1"] / "state_curves"
    state_figure_dir.mkdir(exist_ok=True)
    for c in cases:
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))
        for ax, m in zip(axes, ["M2", "M3", "M4"]):
            row = next(
                r
                for r in curve_rows
                if r["state_id"] == c["state_id"] and r["mode"] == m
            )
            for kind, summary in row["summary"].items():
                ax.plot(np.arange(1, 25), summary["mean"], label=kind)
                ax.fill_between(
                    np.arange(1, 25),
                    summary["order_band_low"],
                    summary["order_band_high"],
                    alpha=0.12,
                )
            ax.set(
                title=m,
                xlabel="Original-block suffixes",
                ylabel="Distinct / remaining absent modes",
            )
        axes[-1].legend(fontsize=8)
        fig.suptitle(c["state_id"])
        fig.tight_layout()
        fig.savefig(state_figure_dir / f"{c['state_id']}.png", dpi=140)
        plt.close(fig)
    attributed_signals(ao, old)
    print("ATTRIBUTION COMPLETE", results, flush=True)


def attributed_signals(ao, old):
    directions = sorted({(r["state_id"], r["family"], r["task_id"]) for r in old})
    tids = sorted({d[2] for d in directions})
    rng = np.random.default_rng(2026100804)
    indexes = {t: [i for i, d in enumerate(directions) if d[2] == t] for t in tids}
    bootids = [
        [i for t in rng.choice(tids, len(tids), replace=True) for i in indexes[t]]
        for _ in range(1000)
    ]
    output = {}
    raw = []
    for mode in ["M2", "M3", "M4"]:
        ctrl = {
            sid: {r["modes"][mode] for r in ao if r["state_id"] == sid}
            for sid, _, _ in directions
        }
        folds = []
        for fold in [0, 1]:
            past = {
                d: [
                    r
                    for r in old
                    if (r["state_id"], r["family"], r["task_id"]) == d
                    and (r["j"] < 3) == (fold == 0)
                ]
                for d in directions
            }
            future = {
                d: [
                    r
                    for r in old
                    if (r["state_id"], r["family"], r["task_id"]) == d
                    and (r["j"] >= 3) == (fold == 0)
                ]
                for d in directions
            }
            globalpast = {r["modes"][mode] for rs in past.values() for r in rs}
            x = collections.defaultdict(list)
            y = collections.defaultdict(list)
            for d in directions:
                counter = collections.Counter(r["modes"][mode] for r in past[d])
                p = np.mean([r["reward"] for r in past[d]])
                sx = {
                    "GT": sum(n == 1 for n in counter.values()) / 12,
                    "REWARD_VARIANCE": float(p * (1 - p)),
                    "REWARD": float(p),
                    "COUNT": 1 / 14,
                }
                targets = {}
                for name, seen in [
                    ("own_past", set(counter)),
                    ("all_directions_past", globalpast),
                ]:
                    new = [
                        r["modes"][mode]
                        for r in future[d]
                        if r["modes"][mode] not in seen
                        and r["modes"][mode] not in ctrl[d[0]]
                    ]
                    targets[name] = len(new)
                    targets[name + "_distinct"] = len(set(new))
                for k, v in sx.items():
                    x[k].append(v)
                for k, v in targets.items():
                    y[k].append(v)
                raw.append(
                    {
                        "mode": mode,
                        "fold": fold,
                        "state_id": d[0],
                        "family": d[1],
                        "task_id": d[2],
                        "signals": sx,
                        "targets": targets,
                        "past_n": 12,
                        "future_n": 12,
                        "agent_only_n": 24,
                    }
                )
            folds.append(
                (
                    {k: np.array(v, float) for k, v in x.items()},
                    {k: np.array(v, float) for k, v in y.items()},
                )
            )
        output[mode] = {}
        for target in folds[0][1]:
            output[mode][target] = {}
            metrics = ["spearman", "precision", "capture", "lift"]
            # For distinct targets, precision is distinct modes / selected future suffixes,
            # while capture/lift retain the same total-distinct-mode target denominator.
            for signal in folds[0][0]:
                observed = [b.ta.top_metrics(x[signal], y[target]) for x, y in folds]
                samples = collections.defaultdict(list)
                for ids in bootids:
                    ms = [
                        b.ta.top_metrics(x[signal][ids], y[target][ids])
                        for x, y in folds
                    ]
                    for metric in metrics:
                        if all(m[metric] is not None for m in ms):
                            samples[metric].append(
                                float(np.mean([m[metric] for m in ms]))
                            )
                output[mode][target][signal] = {
                    "folds": observed,
                    "statistics": {
                        metric: {
                            "mean": float(np.mean([m[metric] for m in observed]))
                            if all(m[metric] is not None for m in observed)
                            else None,
                            "bootstrap_95_CI": np.quantile(
                                samples[metric], [0.025, 0.975]
                            ).tolist()
                            if samples[metric]
                            else None,
                            "valid_replicates": len(samples[metric]),
                        }
                        for metric in metrics
                    },
                }
            observed_a = [b.ta.top_metrics(x["GT"], y[target]) for x, y in folds]
            observed_b = [
                b.ta.top_metrics(x["REWARD_VARIANCE"], y[target]) for x, y in folds
            ]
            diff = collections.defaultdict(list)
            for ids in bootids:
                am = [b.ta.top_metrics(x["GT"][ids], y[target][ids]) for x, y in folds]
                bm = [
                    b.ta.top_metrics(x["REWARD_VARIANCE"][ids], y[target][ids])
                    for x, y in folds
                ]
                for metric in metrics:
                    if all(r[metric] is not None for r in am + bm):
                        diff[metric].append(
                            float(
                                np.mean([a[metric] - c[metric] for a, c in zip(am, bm)])
                            )
                        )
            output[mode][target]["GT_minus_REWARD_VARIANCE"] = {
                metric: {
                    "mean": float(
                        np.mean(
                            [
                                a[metric] - c[metric]
                                for a, c in zip(observed_a, observed_b)
                            ]
                        )
                    )
                    if all(r[metric] is not None for r in observed_a + observed_b)
                    else None,
                    "bootstrap_95_CI": np.quantile(
                        diff[metric], [0.025, 0.975]
                    ).tolist()
                    if diff[metric]
                    else None,
                    "valid_replicates": len(diff[metric]),
                }
                for metric in metrics
            }
    save(D["step1"] / "attributed_signal_comparison.json", output)
    save(D["step1"] / "bootstrap_task_indices.json", bootids)
    (D["step1"] / "direction_folds.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in raw)
    )


def wilson(c, n):
    z = norm.ppf(0.975)
    p = c / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def difference_interval(a, n, b, m):
    """Newcombe score interval avoids degeneracy at all-zero or all-one samples."""
    p = a / n
    q = b / m
    la, ua = wilson(a, n)
    lb, ub = wilson(b, m)
    return [
        float(p - q - np.sqrt((p - la) ** 2 + (ub - q) ** 2)),
        float(p - q + np.sqrt((ua - p) ** 2 + (q - lb) ** 2)),
    ]


def binomial_interval(c, n):
    return [
        float(beta.ppf(0.025, c, n - c + 1)) if c else 0.0,
        float(beta.ppf(0.975, c + 1, n - c)) if c < n else 1.0,
    ]


def retest():
    p = read(OUT / "plan.json")
    rows = load_features("step2")
    ao = load_features("step1")
    assert len(rows) == p["step2_suffixes"]
    results = []
    for c in p["candidates"]:
        sid = c["state_id"]
        cid = c["candidate_id"]
        fixed = [
            r
            for r in rows
            if r["state_id"] == sid
            and r["unit"].split(":")[2] == cid
            and r["family"] == "fixed"
        ]
        native = [
            r for r in rows if r["family"] == f"native_{cid}" and r["state_id"] == sid
        ]
        original = [r for r in ao if r["state_id"] == sid]
        assert len(fixed) == len(native) == 16 and len(original) == 24
        x = sum(r["reward"] for r in fixed)
        y = sum(r["reward"] for r in native)
        z = sum(r["reward"] for r in original)
        delta = x / 16 - y / 16
        interval = difference_interval(x, 16, y, 16)
        direction = (
            "harmful"
            if c["screening_shift"] < 0
            else "beneficial"
            if c["screening_shift"] > 0
            else "zero_screening_shift"
        )
        exclusive = set(c["exclusive_M2_modes"])
        reappeared = {r["modes"]["M2"] for r in fixed} & exclusive
        results.append(
            {
                **c,
                "fixed_successes": x,
                "fixed_n": 16,
                "native_reference_successes": y,
                "native_reference_n": 16,
                "original_control_successes": z,
                "original_control_n": 24,
                "retest_shift": delta,
                "retest_95_CI": interval,
                "vs_original_shift": x / 16 - z / 24,
                "vs_original_95_CI": difference_interval(x, 16, z, 24),
                "sign_holds": bool(np.sign(delta) == np.sign(c["screening_shift"]))
                if c["screening_shift"]
                else None,
                "direction": direction,
                "unadjusted_CI_excludes_zero_same_direction": bool(interval[1] < 0)
                if direction == "harmful"
                else bool(interval[0] > 0)
                if direction == "beneficial"
                else False,
                "absolute_attenuation": abs(c["screening_shift"]) - abs(delta),
                "signed_attenuation": float(c["screening_shift"] - delta),
                "reappeared_exclusive_M2_modes": sorted(reappeared),
                "exclusive_M2_fixed_occurrences": sum(
                    r["modes"]["M2"] in exclusive for r in fixed
                ),
                "exclusive_M2_native_occurrences": sum(
                    r["modes"]["M2"] in exclusive for r in native
                ),
                "exclusive_M2_original_occurrences": sum(
                    r["modes"]["M2"] in exclusive for r in original
                ),
                "new_M2_modes_fixed": sorted({r["modes"]["M2"] for r in fixed}),
            }
        )
    summary = {}
    for cohort in ["primary", "random_controls", "all"]:
        rs = [
            r
            for r in results
            if cohort == "all" or r["random_control"] == (cohort == "random_controls")
        ]
        summary[cohort] = {}
        for direction in ["harmful", "beneficial", "zero_screening_shift"]:
            subset = [r for r in rs if r["direction"] == direction]
            n = len(subset)
            if not n:
                continue
            sign = sum(r["sign_holds"] is True for r in subset)
            survive = sum(
                r["unadjusted_CI_excludes_zero_same_direction"] for r in subset
            )
            for r in subset:
                r["sign_survival_rate"] = float(r["sign_holds"] is True)
                r["CI_survival_rate"] = float(
                    r["unadjusted_CI_excludes_zero_same_direction"]
                )
            summary[cohort][direction] = {
                "n": n,
                "sign_holds": sign,
                "sign_holds_binomial_95_CI": binomial_interval(sign, n),
                "CI_excludes_zero_same_direction": survive,
                "survival_binomial_95_CI": binomial_interval(survive, n),
                "task_cluster_sign_survival": cluster_mean(
                    subset, "sign_survival_rate"
                ),
                "task_cluster_CI_survival": cluster_mean(subset, "CI_survival_rate"),
                "mean_absolute_attenuation": float(
                    np.mean([r["absolute_attenuation"] for r in subset])
                ),
            }
    save(
        D["step2"] / "retest.json",
        {
            "candidates": results,
            "summary": summary,
            "interval_method": "Unadjusted95% Newcombe independent-binomial risk-difference score intervals. Original-control draws are shared across candidates at the same state. Survival means CI excludes0 in screening direction, exploratory and not multiplicity-corrected.",
            "screening_bank_null_compatible": True,
            "exclusive_M2_candidates": sum(
                bool(r["exclusive_M2_modes"]) for r in results
            ),
            "exclusive_M2_candidates_reappeared": sum(
                bool(r["reappeared_exclusive_M2_modes"])
                for r in results
                if r["exclusive_M2_modes"]
            ),
        },
    )
    fig, ax = plt.subplots(figsize=(8, 6))
    for r in results:
        ax.plot(
            r["screening_shift"],
            r["retest_shift"],
            "x" if r["random_control"] else "o",
            color="C1" if r["random_control"] else "C0",
        )
        ax.vlines(
            r["screening_shift"],
            *r["retest_95_CI"],
            color="C1" if r["random_control"] else "C0",
            alpha=0.25,
        )
    ax.axhline(0, color="gray")
    ax.plot([-1, 1], [-1, 1], "--", color="gray")
    ax.set(
        xlabel="Screening shift",
        ylabel="Independent retest shift",
        title="Fixed block minus fresh native reference; circles primary / crosses random",
    )
    fig.tight_layout()
    for ext in ["png", "pdf"]:
        fig.savefig(D["step2"] / f"retest_regression.{ext}", dpi=160)
    plt.close(fig)
    print("RETEST COMPLETE", summary, flush=True)


def conditions():
    """Three-condition descriptive sensitivity and proper-control mode comparison."""
    p = read(OUT / "plan.json")
    rows = load_features("step3b")
    ao = load_features("step1")
    states = p["step3b_states"]
    assert len(rows) == 960
    old = [
        json.loads(s)
        for s in (BASE / "v7_e2_20261004/mode_rows.jsonl").read_text().splitlines()
    ]
    native = [r for r in old if r["state_id"] in states and r["family"] == "q"]
    data = rows + [{**r, "family": "native"} for r in native]
    expected_labels = {
        (r["unit"].rsplit(":", 1)[0], r["rep"])
        for r in rows
        if r["family"] == "single" and r["next_turn"]["next_partner_block"] is not None
    }
    observed_labels = [
        (read(f)["unit"], r["rep"])
        for f in (D["step3b"] / "undo_labels").glob("*.json")
        for r in read(f)["judgment"]["relations"]
    ]
    assert len(observed_labels) == len(set(observed_labels)), "Duplicate undo labels"
    assert set(observed_labels) == expected_labels, {
        "missing": sorted(expected_labels - set(observed_labels)),
        "extra": sorted(set(observed_labels) - expected_labels),
    }
    bystate = []
    undo = []
    for sid in states:
        control = {r["modes"]["M3"] for r in ao if r["state_id"] == sid}
        task_id = next(c["task_id"] for c in p["states"] if c["state_id"] == sid)
        state = {"state_id": sid, "task_id": task_id}
        for condition in ["native", "single", "persistent"]:
            rs = [r for r in data if r["state_id"] == sid and r["family"] == condition]
            assert len(rs) == 24
            groups = [[r["reward"] for r in rs if r["j"] == j] for j in range(6)]
            assert all(len(g) == 4 for g in groups)
            count = np.array([sum(g) for g in groups])
            total = int(count.sum())
            S = float(
                (23 * np.dot(count, count) - 3 * total * total - 20 * total) / 1440
            )
            modes = {r["modes"]["M3"] for r in rs}
            state[condition] = {
                "S_hat": S,
                "successes": total,
                "n": 24,
                "mean_success": total / 24,
                "reply_successes": count.tolist(),
                "attributable_M3_count": len(modes - control),
                "M3_distinct": len(modes),
                "attributable_M3_share": len(modes - control) / len(modes),
                "attributable_modes": sorted(modes - control),
            }
        bystate.append(state)
        rel = [
            r
            for f in (D["step3b"] / "undo_labels").glob(f"{sid}:*.json")
            for r in read(f)["judgment"]["relations"]
        ]
        counts = collections.Counter(r["relation"] for r in rel)
        undo.append(
            {
                "state_id": sid,
                "task_id": task_id,
                "available": len(rel),
                "censored_no_next_partner": 24 - len(rel),
                "relations": dict(counts),
                "undo_share": counts["contradicts_or_undoes"] / len(rel)
                if rel
                else None,
            }
        )
    aggregate = {}
    contrasts = {}
    for condition in ["native", "single", "persistent"]:
        aggregate[condition] = {}
        for field in [
            "S_hat",
            "mean_success",
            "attributable_M3_count",
            "attributable_M3_share",
            "M3_distinct",
        ]:
            aggregate[condition][field] = cluster_mean(
                [
                    {"task_id": r["task_id"], field: r[condition][field]}
                    for r in bystate
                ],
                field,
            )
        aggregate[condition]["successes"] = sum(
            r[condition]["successes"] for r in bystate
        )
        aggregate[condition]["suffix_n"] = 480
    for a, c in [
        ("single", "native"),
        ("persistent", "native"),
        ("persistent", "single"),
    ]:
        contrasts[f"{a}_minus_{c}"] = {}
        for field in ["S_hat", "mean_success", "attributable_M3_count"]:
            contrasts[f"{a}_minus_{c}"][field] = cluster_mean(
                [
                    {"task_id": r["task_id"], field: r[a][field] - r[c][field]}
                    for r in bystate
                ],
                field,
            )
    save(
        D["step3b"] / "conditions.json",
        {
            "per_state": bystate,
            "aggregate": aggregate,
            "paired_task_cluster_contrasts": contrasts,
            "native_suffixes_reused": 480,
            "new_single_suffixes": 480,
            "new_persistent_suffixes": 480,
            "native_setup_matches": "Same states, native partner/agent/prompt/temp1 and200newstep limit. Native is historical reuse, so session/timing is not contemporaneously randomized. Single and persistent share branch replies but have fresh independent seeds.",
            "S_interpretation": "Persistent S estimates variance over initial branch reply while integrating fresh later proposals into continuation noise. It is not the variance over full persistent partner trajectories.",
            "attribution_limitation": "Absence from finite24-original-block control; not population support exclusion. Historical M3 field abstraction is frozen for comparability.",
        },
    )
    n = sum(r["available"] for r in undo)
    num = sum(r["relations"].get("contradicts_or_undoes", 0) for r in undo)
    save(
        D["step3b"] / "undo.json",
        {
            "model_judgment": True,
            "per_state": undo,
            "aggregate": {
                "undo_numerator": num,
                "available_denominator": n,
                "total_suffixes": 480,
                "censored_no_next_partner": 480 - n,
                "share": num / n if n else None,
            },
            "cluster_mean_of_state_shares": cluster_mean(
                [r for r in undo if r["undo_share"] is not None], "undo_share"
            ),
            "limitation": "Frozen E0 labeler may confuse agent repair with partner reversal; no human labels or causal undo certification.",
        },
    )
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, field in zip(axes, ["S_hat", "mean_success", "attributable_M3_count"]):
        for i, c in enumerate(["native", "single", "persistent"]):
            r = aggregate[c][field]
            ax.plot(i, r["mean"], "o")
            ax.vlines(i, *r["bootstrap_95_CI"])
        ax.set(
            xticks=[0, 1, 2],
            xticklabels=["native", "single", "persistent"],
            title=field,
        )
    fig.tight_layout()
    for ext in ["png", "pdf"]:
        fig.savefig(D["step3b"] / f"condition_comparison.{ext}", dpi=160)
    plt.close(fig)
    print("CONDITIONS COMPLETE", contrasts, flush=True)


def multiplicity():
    """Supplementary exact directional inference; retains primary intervals unchanged."""
    from scipy.stats import fisher_exact

    data = read(D["step2"] / "retest.json")
    rows = []
    for r in data["candidates"]:
        x = r["fixed_successes"]
        z = r["native_reference_successes"]
        p = float(
            fisher_exact(
                [[x, 16 - x], [z, 16 - z]],
                alternative="less" if r["direction"] == "harmful" else "greater",
            ).pvalue
        )
        rows.append(
            {
                "candidate_id": r["candidate_id"],
                "reply_unit": r["reply_unit"],
                "direction": r["direction"],
                "random_control": r["random_control"],
                "one_sided_fisher_p": p,
            }
        )
    order = np.argsort([r["one_sided_fisher_p"] for r in rows])
    previous = 0
    for i, k in enumerate(order):
        previous = max(
            previous, min(1, (len(rows) - i) * rows[k]["one_sided_fisher_p"])
        )
        rows[k]["Holm_p"] = previous
    save(
        D["step2"] / "multiplicity_supplement.json",
        {
            "supplemental_not_prespecified": True,
            "method": "Directional Fisher exact p in independently retested screening direction; Holm across all32 preselected candidates, dependence-robust. Descriptive0.05 reading only; no sampling stopped or selected by these values. Original unadjusted score intervals and survival definitions unchanged.",
            "candidates": rows,
            "summary": {
                co: {
                    d: sum(
                        r["Holm_p"] < 0.05
                        for r in rows
                        if r["direction"] == d
                        and (co == "all" or r["random_control"] == (co == "controls"))
                    )
                    for d in ["harmful", "beneficial"]
                }
                for co in ["primary", "controls", "all"]
            },
        },
    )
    features = load_features("step2")
    cases = {c["state_id"]: c for c in read(OUT / "plan.json")["states"]}
    records = {r["candidate_id"]: r for r in data["candidates"]}
    for r in rows:
        if r["Holm_p"] >= 0.05:
            continue
        candidate = records[r["candidate_id"]]
        sid = candidate["state_id"]
        cid = candidate["candidate_id"]
        fixed = [x for x in features if x["unit"].startswith(f"{sid}:fixed:{cid}:")]
        native = [x for x in features if x["family"] == f"native_{cid}"]
        first = {
            "failure": min(
                [
                    x
                    for x in (fixed if r["direction"] == "harmful" else native)
                    if x["reward"] == 0
                ],
                key=lambda x: (x["j"], x["rep"]),
            ),
            "success": min(
                [
                    x
                    for x in (native if r["direction"] == "harmful" else fixed)
                    if x["reward"] == 1
                ],
                key=lambda x: (x["j"], x["rep"]),
            ),
        }
        branch_source = read(b.SRC / "sources" / f"{cases[sid]['source_id']}.json")
        output = {
            "candidate": candidate,
            "supplemental_directional_inference": r,
            "preceding_agent_request": b.ta.semantic(
                branch_source["messages"][cases[sid]["index"] - 1]
            ),
            "modes": {},
            "selection": "Earliest representative failure and success in the tested direction. Mechanical outcome/assertion/path records, not human failure labels or an additional annotation.",
        }
        for name, x in first.items():
            reply = read(D["step2"] / "replies" / f"{x['unit'].rsplit(':', 1)[0]}.json")
            output["modes"][name] = {
                "suffix_unit": x["unit"],
                "partner_block": [b.ta.semantic(m) for m in reply["partner_block"]],
                "reward": x["reward"],
                "final_assertions": x["assertions"],
                "unmet_assertions": [
                    a["assertion"] for a in x["assertions"] if not a["met"]
                ],
                "agent_tool_path": x["agent_tool_path"],
                "M2": x["modes"]["M2"],
                "M3": x["modes"]["M3"],
                "trajectory_path": str(
                    (D["step2"] / "trajectories" / f"{x['unit']}.json").relative_to(
                        b.ROOT
                    )
                ),
            }
        save(D["step2"] / "reconfirmed_cases" / f"{cid}.json", output)
    print("MULTIPLICITY SUPPLEMENT COMPLETE", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=["features", "attribution", "retest", "conditions", "multiplicity"],
    )
    parser.add_argument("--step", choices=list(D), default="step1")
    args = parser.parse_args()
    if args.phase == "features":
        features(args.step)
    else:
        globals()[args.phase]()


if __name__ == "__main__":
    main()
