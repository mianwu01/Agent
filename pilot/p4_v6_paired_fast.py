"""Resume the fixed paired protocol with independent concurrent work units."""

import argparse
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import p4_v6_paired as paired


def run_jobs(jobs, workers, protocol, phase):
    """Retry individual failed units while retaining completed native outputs."""
    p4 = paired.v6.p4
    for attempt in range(4):
        failed = []
        last_report = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fn, *args): (unit, fn, args) for unit, fn, args in jobs
            }
            for future in as_completed(futures):
                unit, fn, args = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    p4.save(
                        paired.OUT / "errors" / f"fast:{unit}:{time.time_ns()}.json",
                        {
                            "unit": unit,
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    failed.append((unit, fn, args))
                    print("retry", unit, type(exc).__name__, flush=True)
                if time.monotonic() - last_report >= 30:
                    paired.report(protocol)
                    print(
                        phase, "pending", sum(not f.done() for f in futures), flush=True
                    )
                    last_report = time.monotonic()
        if not failed:
            return
        jobs = failed
    raise RuntimeError(
        f"{phase}: {len(jobs)} units remain incomplete; see saved errors"
    )


def main():
    """Complete paired measurements first, followed by concurrent Sol diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=96)
    parser.add_argument("--out", type=Path, default=paired.OUT)
    args = parser.parse_args()
    paired.OUT = args.out.resolve()
    paired.activate()
    protocol = paired.prepare()
    v6 = paired.v6
    p4 = v6.p4
    p4.setup(p4.ROOT / "api.txt", args.workers)
    p4.KEY_LIMITS = [threading.BoundedSemaphore(args.workers // 4) for _ in range(4)]
    jobs = []
    for n, case in enumerate(protocol["states"]):
        for arm in ["q", "q_prime"]:
            for j in range(protocol["k"]):
                unit = f"{case['state_id']}:{arm}:d{j}"
                if not (paired.OUT / "replies" / f"{unit}.json").exists():
                    jobs.append((unit, paired.sample, (case, arm, j, (n * 12 + j) % 4)))
    print("missing replies", len(jobs), "workers", args.workers, flush=True)
    run_jobs(jobs, args.workers, protocol, "replies")
    jobs = []
    for n, case in enumerate(protocol["states"]):
        for arm in ["q", "q_prime"]:
            for j in range(protocol["k"]):
                reply = p4.read(
                    paired.OUT / "replies" / f"{case['state_id']}:{arm}:d{j}.json"
                )
                for rep in range(protocol["m"]):
                    unit = f"{reply['unit']}:r{rep}"
                    if not (paired.OUT / "continuations" / f"{unit}.json").exists():
                        jobs.append(
                            (
                                unit,
                                v6.continuation,
                                (case, reply, rep, (n + j + rep) % 4),
                            )
                        )
    print("missing paired continuations", len(jobs), flush=True)
    run_jobs(jobs, args.workers, protocol, "paired")
    paired.report(protocol)
    print("PAIRED COMPLETE", flush=True)
    jobs = []
    for n, case in enumerate(protocol["states"]):
        choices = []
        for arm in ["q", "q_prime"]:
            for j in range(protocol["k"]):
                unit = f"{case['state_id']}:{arm}:d{j}"
                rows = [
                    p4.read(paired.OUT / "continuations" / f"{unit}:r{rep}.json")
                    for rep in range(protocol["m"])
                ]
                choices.append(
                    (
                        statistics.mean(r["reward"] == 1 for r in rows),
                        p4.read(paired.OUT / "replies" / f"{unit}.json"),
                    )
                )
        rate, chosen = min(choices, key=lambda item: item[0])
        diagnostic = {**chosen, "unit": f"{case['state_id']}:sol:d{chosen['j']}"}
        p4.save(
            paired.OUT / "sol_selection" / f"{case['state_id']}.json",
            {
                "source_unit": chosen["unit"],
                "luna_success_rate": rate,
                "reply": diagnostic,
            },
        )
        for rep in range(protocol["sol_m"]):
            unit = f"{diagnostic['unit']}:r{rep}"
            if not (paired.OUT / "continuations" / f"{unit}.json").exists():
                jobs.append(
                    (
                        unit,
                        v6.continuation,
                        (
                            case,
                            diagnostic,
                            rep,
                            (n + rep) % 4,
                            protocol["reference_agent"],
                        ),
                    )
                )
    print("missing Sol continuations", len(jobs), flush=True)
    run_jobs(jobs, args.workers, protocol, "sol")
    summary = paired.report(protocol, final=True)
    p4.save(
        paired.OUT / "execution.json",
        {
            "finished_at": time.time(),
            "workers": args.workers,
            "scheduler": "independent units",
            "failed_states": [],
            "paired_states_complete": summary["strata"]["paired_complete"],
        },
    )


if __name__ == "__main__":
    main()
