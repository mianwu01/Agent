"""Offline descriptive analysis of saved Prompt B artifacts; no model imports/calls."""

import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BRANCH = ROOT / "pilot/runs/branch"
SEED = 20260929
inputs = {}


def read(path):
    """Read and fingerprint an input artifact."""
    path = Path(path)
    data = path.read_bytes()
    inputs[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def csv_out(name, rows):
    """Write a rectangular table."""
    rows = list(rows)
    assert rows
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def table(rows):
    """Render a CSV-like table to Markdown."""
    keys = list(rows[0])

    def fmt(x):
        return (
            (f"{x:.6f}" if isinstance(x, float) else str(x))
            .replace("|", "\\|")
            .replace("\n", " ")
        )

    return "\n".join(
        ["| " + " | ".join(keys) + " |", "| " + " | ".join(["---"] * len(keys)) + " |"]
        + ["| " + " | ".join(fmt(r[k]) for k in keys) + " |" for r in rows]
    )


def tokens(sim):
    """Sum response usage, excluding tool messages."""
    total = 0
    for m in sim["messages"]:
        if m["role"] not in ("assistant", "user"):
            continue
        u = m.get("usage")
        assert not m.get("raw_data") or u is not None
        if u:
            total += u["prompt_tokens"] + u["completion_tokens"]
    return total


def quantile(values, q):
    """Linear interpolated sample quantile, index (n-1)*q."""
    x = sorted(values)
    i = (len(x) - 1) * q
    low = int(i)
    return x[low] + (x[min(low + 1, len(x) - 1)] - x[low]) * (i - low)


def main():
    """Produce A–G tables, examples, provenance, and one descriptive report."""
    batches = {
        m: read(ROOT / f"pilot/runs/iid/{m}/results.json")
        for m in ("default", "no-user")
    }
    rows = [read(p) for p in sorted((BRANCH / "rows").glob("*.json"))]
    manifest = read(BRANCH / "selection.json")
    assert len(rows) == 756 and len(manifest["positions"]) == 189
    report = [
        "# Prompt B descriptive results",
        "Analysis only; no new model runs. Success = reward == 1; failure/flip = reward == 0. No failure interpretation.",
    ]
    counts = {}
    overall = []
    for mode, batch in batches.items():
        assert len(batch["tasks"]) == 114
        groups = defaultdict(list)
        for s in batch["simulations"]:
            assert s["reward_info"]["reward"] in (0, 1)
            groups[s["task_id"]].append(s)
        n = 8 if mode == "default" else 4
        assert all(len(g) == n for g in groups.values())
        counts[mode] = {
            k: sum(s["reward_info"]["reward"] == 1 for s in g)
            for k, g in groups.items()
        }
        histogram = Counter(counts[mode].values())
        csv_out(
            f"a_{mode}_histogram.csv",
            [{"successes": i, "tasks": histogram[i]} for i in range(n + 1)],
        )
        overall.append(
            dict(
                mode=mode,
                runs=len(batch["simulations"]),
                successes=sum(counts[mode].values()),
                success_rate=sum(counts[mode].values()) / len(batch["simulations"]),
            )
        )
    per_task = []
    for task in sorted(counts["default"]):
        d, n = counts["default"][task] / 8, counts["no-user"][task] / 4
        cat = (
            "S"
            if n >= 0.75 and d <= 0.25
            else "R"
            if d >= 0.75 and n <= 0.25
            else "both ok"
            if d >= 0.75 and n >= 0.75
            else "both fail"
            if d <= 0.25 and n <= 0.25
            else "mixed"
        )
        per_task.append(
            dict(
                task_id=task,
                default_successes=counts["default"][task],
                no_user_successes=counts["no-user"][task],
                default_mean=d,
                no_user_mean=n,
                category=cat,
            )
        )
    csv_out("a_tasks.csv", per_task)
    cats = Counter(r["category"] for r in per_task)
    cat_rows = csv_out(
        "a_categories.csv",
        [
            dict(category=k, tasks=cats[k])
            for k in ("S", "R", "both ok", "both fail", "mixed")
        ],
    )
    csv_out("a_overall.csv", overall)
    report += [
        "## A. B1 outcome structure",
        table(overall),
        "S: no-user mean ≥0.75 and default mean ≤0.25. R: reverse. Both ok: both means ≥0.75. Both fail: both means ≤0.25. Mixed: all remaining tasks. A1 specifies S/R; the same high/low cutoffs are applied to the additional categories.",
        table(cat_rows),
    ]
    for mode in batches:
        report += [
            f"### {mode} success-count histogram",
            table(list(csv.DictReader((OUT / f"a_{mode}_histogram.csv").open()))),
        ]
    pairs = defaultdict(list)
    for r in rows:
        pairs[(r["source_sim_id"], r["i"])].append(r)
    assert len(pairs) == 189 and all(len(v) == 4 for v in pairs.values())
    positions = [v[0]["i"] / v[0]["n_messages_source"] for v in pairs.values()]
    q1, q2 = quantile(positions, 1 / 3), quantile(positions, 2 / 3)
    stratified = []
    for dimension in (
        "default_success_count",
        "relative_position_empirical_tercile",
        "relative_position_fixed_third",
    ):
        labels = (
            ["1-3", "4-6", "7-8"]
            if dimension == "default_success_count"
            else ["lower", "middle", "upper"]
        )
        for arm in ("resample", "vs_tail"):
            groups = defaultdict(list)
            for r in rows:
                if r["arm"] != arm:
                    continue
                if dimension == "default_success_count":
                    c = counts["default"][r["task_id"]]
                    idx = 0 if c <= 3 else 1 if c <= 6 else 2
                else:
                    a, b = (q1, q2) if "empirical" in dimension else (1 / 3, 2 / 3)
                    p = r["i"] / r["n_messages_source"]
                    idx = 0 if p <= a else 1 if p <= b else 2
                groups[labels[idx]].append(r)
            for label in labels:
                g = groups[label]
                stratified.append(
                    dict(
                        dimension=dimension,
                        arm=arm,
                        bin=label,
                        positions=len({(r["source_sim_id"], r["i"]) for r in g}),
                        continuations=len(g),
                        flipped=sum(r["flipped"] for r in g),
                        flip_rate=sum(r["flipped"] for r in g) / len(g) if g else "",
                    )
                )
    csv_out("b_stratified_flip_rates.csv", stratified)
    report += [
        "## B. Stratified flip rates",
        f"Empirical terciles are computed once across 189 unique positions using linear quantiles: q1={q1:.12g}, q2={q2:.12g}. Lower: x≤q1; middle: q1<x≤q2; upper: x>q2. Ties stay together. Fixed thirds additionally use cutoffs 1/3 and 2/3 with the same boundary convention. x=i/n_messages_source, using the recorded zero-based i. Rates are continuation-weighted.",
        table(stratified),
    ]
    pair_rows = []
    for (source, i), group in sorted(pairs.items()):
        assert {(r["arm"], r["rep"]) for r in group} == {
            (a, k) for a in ("resample", "vs_tail") for k in (0, 1)
        }
        pair_rows.append(
            dict(
                source_sim_id=source,
                i=i,
                resample_flips=sum(
                    r["flipped"] for r in group if r["arm"] == "resample"
                ),
                vs_tail_flips=sum(r["flipped"] for r in group if r["arm"] == "vs_tail"),
            )
        )
    csv_out("c_pairs.csv", pair_rows)
    joint = Counter((r["resample_flips"], r["vs_tail_flips"]) for r in pair_rows)
    matrix = csv_out(
        "c_pairing_3x3.csv",
        [
            dict(resample_flips=i, **{f"vs_tail_{j}": joint[i, j] for j in range(3)})
            for i in range(3)
        ],
    )
    report += [
        "## C. Paired flip counts",
        "Rows: resample flips out of 2; columns: vs_tail flips out of 2. Cell counts are source/position pairs.",
        table(matrix),
    ]
    proposals = []
    example_rows = {}
    for key, group in sorted(pairs.items()):
        r = next(r for r in group if r["arm"] == "vs_tail")
        p = read(ROOT / r["proposal_path"])
        chosen = min(p["candidates"], key=lambda c: c["probability"])
        assert len(p["candidates"]) == 5 and chosen == p["chosen"]
        proposals.append(
            dict(
                source_sim_id=key[0],
                i=key[1],
                chosen_probability=chosen["probability"],
                probability_sum=sum(c["probability"] for c in p["candidates"]),
                replacement_used="original_invalid_path" in p,
            )
        )
        example_rows[key] = (r, p)
    csv_out("d_proposal_probabilities.csv", proposals)
    dist_summary = []
    for field in ("chosen_probability", "probability_sum"):
        vals = [p[field] for p in proposals]
        freq = Counter(vals)
        csv_out(
            f"d_{field}_distribution.csv",
            [
                dict(value=v, positions=freq[v], fraction=freq[v] / len(vals))
                for v in sorted(freq)
            ],
        )
        dist_summary.append(
            dict(
                variable=field,
                n=len(vals),
                mean=sum(vals) / len(vals),
                min=min(vals),
                p10=quantile(vals, 0.1),
                p25=quantile(vals, 0.25),
                median=quantile(vals, 0.5),
                p75=quantile(vals, 0.75),
                p90=quantile(vals, 0.9),
                max=max(vals),
            )
        )
    csv_out("d_distribution_summary.csv", dist_summary)
    examples = random.Random(SEED).sample(sorted(example_rows), 25)
    lines = [
        "# VS proposal examples",
        f"Uniform sample without replacement of 25 of 189 source/position pairs. Python random.Random({SEED}); population sorted by (source_sim_id, i). Final valid proposals; no normalization.",
    ]
    for key in examples:
        r, p = example_rows[key]
        lines += [
            f"## {key[0]}:{key[1]}",
            "Original user message:",
            "~~~text",
            r["original_user_message"],
            "~~~",
            "Candidates:",
        ]
        for j, c in enumerate(p["candidates"], 1):
            lines += [
                f"### {j}. Probability {c['probability']}"
                + (" — chosen" if c == p["chosen"] else ""),
                "~~~text",
                c["message"],
                "~~~",
            ]
    (OUT / "vs_examples.md").write_text("\n\n".join(lines) + "\n")
    report += [
        "## D. VS proposal probabilities",
        "Each of the 189 final valid proposals is counted once, including the four replacements. Original invalid calls are excluded from candidate distributions but included in token accounting. Full exact-value frequency distributions are in d_*_distribution.csv.",
        table(dist_summary),
        "[25 sampled examples](vs_examples.md).",
    ]
    termination = Counter()
    failed = []
    check_summary = []
    for r in rows:
        if not r["flipped"]:
            continue
        sim = read(ROOT / r["trajectory_path"])
        termination[r["arm"], r["termination_reason"]] += 1
        info = sim["reward_info"]
        env = [c for c in info.get("env_assertions") or [] if c["met"] is False]
        actions = [
            c for c in info.get("action_checks") or [] if c["action_match"] is False
        ]
        check_summary.append(
            dict(
                branch_id=r["branch_id"],
                arm=r["arm"],
                env_failures=len(env),
                action_failures=len(actions),
                reward_basis=json.dumps(info["reward_basis"]),
            )
        )
        for kind, checks, key, name in (
            ("env_assertion", env, "env_assertion", "func_name"),
            ("action_check", actions, "action", "name"),
        ):
            for c in checks:
                failed.append(
                    dict(
                        branch_id=r["branch_id"],
                        arm=r["arm"],
                        check_type=kind,
                        function_name=c[key][name],
                        details=json.dumps(c, ensure_ascii=False),
                    )
                )
    csv_out("e_failed_checks_details.csv", failed)
    csv_out("e_flipped_continuations.csv", check_summary)
    term_rows = csv_out(
        "e_termination_reasons.csv",
        [
            dict(arm=a, termination_reason=t, continuations=n)
            for (a, t), n in sorted(termination.items())
        ],
    )
    grouped = defaultdict(list)
    for r in failed:
        grouped[r["arm"], r["check_type"], r["function_name"]].append(r)
    functions = csv_out(
        "e_failed_check_functions.csv",
        [
            dict(
                arm=a,
                check_type=k,
                function_name=f,
                failed_check_occurrences=len(g),
                continuations=len({r["branch_id"] for r in g}),
            )
            for (a, k, f), g in sorted(grouped.items())
        ],
    )
    check_counts = []
    for arm in ("resample", "vs_tail"):
        g = [r for r in check_summary if r["arm"] == arm]
        check_counts.append(
            dict(
                arm=arm,
                flipped=len(g),
                any_env_failure=sum(r["env_failures"] > 0 for r in g),
                any_action_failure=sum(r["action_failures"] > 0 for r in g),
                both=sum(r["env_failures"] > 0 and r["action_failures"] > 0 for r in g),
                neither=sum(
                    r["env_failures"] == 0 and r["action_failures"] == 0 for r in g
                ),
            )
        )
    csv_out("e_check_types.csv", check_counts)
    report += [
        "## E. Recorded checks in flipped continuations",
        table(term_rows),
        table(check_counts),
        "Counts below include every recorded false env assertion/action check, whether or not that check type belongs to the task's reward_basis. Occurrences count checks; continuations count distinct branch IDs. These are recorded checks, not inferred causes. Per-continuation reward_basis is in e_flipped_continuations.csv.",
        table(functions),
    ]
    accounting = []
    for mode, batch in batches.items():
        accounting.append(
            dict(
                stage="B1",
                arm=mode,
                outcomes=len(batch["simulations"]),
                failures=sum(
                    s["reward_info"]["reward"] == 0 for s in batch["simulations"]
                ),
                continuation_tokens=sum(tokens(s) for s in batch["simulations"]),
                proposal_tokens=0,
            )
        )
    raw_proposals = [read(p) for p in sorted((BRANCH / "proposals").rglob("*.json"))]
    assert len(raw_proposals) == 193 and all(
        p["response"]["usage"] is not None for p in raw_proposals
    )
    for arm in ("resample", "vs_tail"):
        g = [r for r in rows if r["arm"] == arm]
        proposal_tokens = (
            sum(
                p["response"]["usage"]["prompt_tokens"]
                + p["response"]["usage"]["completion_tokens"]
                for p in raw_proposals
            )
            if arm == "vs_tail"
            else 0
        )
        accounting.append(
            dict(
                stage="B2",
                arm=arm,
                outcomes=len(g),
                failures=sum(r["flipped"] for r in g),
                continuation_tokens=sum(
                    sum(r["cont_input_tokens"].values())
                    + sum(r["cont_output_tokens"].values())
                    for r in g
                ),
                proposal_tokens=proposal_tokens,
            )
        )
    for r in accounting:
        r["recorded_total_tokens"] = r["continuation_tokens"] + r["proposal_tokens"]
        r["failures_per_million_recorded_tokens"] = (
            r["failures"] * 1e6 / r["recorded_total_tokens"]
        )
    csv_out("f_yield_per_token.csv", accounting)
    report += [
        "## F. Yield per recorded token",
        table(accounting),
        "Both stages use all saved response usage, including saved invalid proposal responses. Neither stage imputes unavailable failed/interrupted-attempt usage. Therefore these denominators are recorded-token totals, not total billed usage; the rates are not adjusted for missing usage.",
    ]
    # Reconstruct interrupted B1 units from FIFO order and the final pre-stop monitor.
    history_path = (
        ROOT / "pilot/runs/iid/default/history/1790605503969516042/results.json"
    )
    history = read(history_path)
    log = (ROOT / "pilot/b-iid-default.log").read_text()
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log)
    before = clean.split("Ctrl+C received")[0]
    status = list(re.finditer(r"Status: (\d+)/912 complete.*?(\d+) running:", before))
    assert status
    completed, active = map(int, status[-1].groups())
    assert completed == len(history["simulations"]) == 38 and active == 48
    done = {(s["task_id"], s["trial"]) for s in history["simulations"]}
    first = [(t["id"], trial) for trial in range(8) for t in history["tasks"]][
        : completed + active
    ]
    assert done <= set(first)
    interrupted = [unit for unit in first if unit not in done]
    assert len(interrupted) == 48
    visible = re.findall(
        r"(\[(?:mobile_data_issue|service_issue)[^\n]*?\[PERSONA:[^]]+\])\.(\d+)\(\d+s\)",
        before[status[-1].end() :].replace("\n", ""),
    )
    assert len(visible) == 10 and set((t, int(n)) for t, n in visible) <= set(
        interrupted
    )
    final = {(s["task_id"], s["trial"]): s for s in batches["default"]["simulations"]}
    missing = []
    for task, trial in interrupted:
        s = final[task, trial]
        missing.append(
            dict(
                stage="B1",
                arm="default",
                task_id=task,
                trial=trial,
                branch_id="",
                completed_simulation_id=s["id"],
                seed=s["seed"],
                attempt="initial launch",
                event="interrupted by SIGINT",
                missing_input_tokens="unknown",
                missing_output_tokens="unknown",
                identification="FIFO reconstruction: first 86 leased units minus 38 checkpoints",
                evidence="pilot/b-iid-default.log:30198; pilot/runs/iid/default/history/1790605503969516042/results.json; src/tau2/runner/batch.py:816",
            )
        )
    errors = [
        e for p in sorted((BRANCH / "error_history").glob("*.json")) for e in read(p)
    ]
    for e in errors:
        if "UserMessage must have either content or tool_calls" not in e["error"]:
            continue
        s = e["selection"]
        bid = f"{s['source_sim_id']}:{s['i']}:vs_tail:0"
        r = next(r for r in rows if r["branch_id"] == bid)
        missing.append(
            dict(
                stage="B2",
                arm="vs_tail",
                task_id=s["task_id"],
                trial="",
                branch_id=bid,
                completed_simulation_id=bid,
                seed=r["seed_or_rep"],
                attempt="first pass",
                event=e["error"].replace("\n", " "),
                missing_input_tokens="unknown",
                missing_output_tokens="unknown",
                identification="saved position error; vs_tail rep0 failed, rep1 not launched (recorded recovery history)",
                evidence="pilot/runs/branch/error_history/1790609492911271184.json; pilot/PROMPT_B.md",
            )
        )
    assert len(missing) == 49
    csv_out("g_missing_attempt_usage.csv", missing)
    proposal_errors = []
    for p in sorted((BRANCH / "proposals/original_invalid").glob("*.json")):
        d = read(p)
        u = d["response"]["usage"]
        proposal_errors.append(
            dict(
                proposal_id=p.stem,
                event="invalid original proposal",
                usage_missing=False,
                input_tokens=u["prompt_tokens"],
                output_tokens=u["completion_tokens"],
                path=str(p.relative_to(ROOT)),
            )
        )
    csv_out("g_failed_proposals_with_known_usage.csv", proposal_errors)
    retry_pattern = (
        r"failed \(attempt \d|Retry \d/|succeeded on retry \d|failed after \d+ attempts"
    )
    scanned = []
    for name in (
        "b-iid-default.log",
        "b-iid-no-user.log",
        "b-branch.log",
        "b-branch-recovery.log",
        "branch-runtime.log",
    ):
        path = ROOT / "pilot" / name
        text = path.read_text()
        inputs[str(path.relative_to(ROOT))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        hits = [
            dict(line=i, text=line)
            for i, line in enumerate(text.splitlines(), 1)
            if re.search(retry_pattern, line)
        ]
        scanned.append(dict(path=str(path.relative_to(ROOT)), native_retry_events=hits))
    assert all(not x["native_retry_events"] for x in scanned)
    (OUT / "g_retry_log_scan.json").write_text(json.dumps(scanned, indent=2) + "\n")
    report += [
        "## G. Failed/interrupted-attempt usage ledger",
        "[g_missing_attempt_usage.csv](g_missing_attempt_usage.csv) lists 48 interrupted B1 default runs and one failed B2 vs_tail continuation. No such B1 no-user attempt is identified in retained logs. Each row links the eventual completed run/branch; the interrupted attempt's simulation UUID was not retained.",
        "B1 identities are reconstructed, not all individually printed: the final status reports 38 completed and 48 active; the native scheduler leases in trial-major FIFO order. The first 86 units minus the 38 archived checkpoints identify the 48 interrupted units. All 10 identities printed in the truncated final status match this set. Queued but unstarted units are excluded.",
        "B2's saved error identifies the source/position; the recorded recovery history identifies vs_tail replicate 0. Its failed partial trajectory/usage was not saved. Replicate 1 had not yet started and is not a missing-usage attempt.",
        "Four invalid proposal calls have saved usage and are already counted in F; see g_failed_proposals_with_known_usage.csv. Their replacement calls are also counted once.",
        "No native simulation retry events were found in the five retained run logs (g_retry_log_scan.json). Provider-internal retries/timeouts do not have a complete per-request ledger. Thus this is the complete identifiable run-level ledger from saved evidence, not proof that all provider attempts are observable. Unknown usage is left unknown, never treated as zero. Probes and the earlier trial are outside B1/B2 and excluded from both denominators.",
        "## Files and reproducibility",
        "Run offline with: `.venv/bin/python pilot/analysis/analyze.py`. All output tables and examples are in this directory. input_manifest.json records SHA-256 fingerprints of read inputs. No source run artifacts are modified.",
    ]
    (OUT / "results.md").write_text("\n\n".join(report) + "\n")
    (OUT / "input_manifest.json").write_text(
        json.dumps(dict(example_seed=SEED, inputs=inputs), indent=2) + "\n"
    )
    print(
        json.dumps(
            dict(
                overall=overall,
                categories=cat_rows,
                pairing=matrix,
                yield_per_token=accounting,
                missing_attempts=len(missing),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
