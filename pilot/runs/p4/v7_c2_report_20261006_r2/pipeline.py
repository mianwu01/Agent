"""Durable ordered C2 revision controller; never start search on incomplete relabeling."""

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = OUT.parent
STEP2 = BASE / "v7_c2_step2_20261006_r2"
STEP3 = BASE / "v7_c2_step3_20261006_r2"


def state(stage, **details):
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        **details,
    }
    (OUT / "pipeline_state.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload), flush=True)


def running_labels(phase):
    output = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
    return [
        line
        for line in output.splitlines()
        if "labels_run.py " + phase in line
        and line.split(None, 1)[1].startswith(
            (".venv/bin/python ", str(ROOT / ".venv/bin/python") + " ")
        )
    ]


def run(script, args=(), log=None):
    if (OUT / "balance_stop.json").exists() and script not in {
        "analyze.py",
        "refresh_mechanics.py",
    }:
        raise RuntimeError("Provider balance insufficient; no new model calls")
    if (OUT / "authentication_stop.json").exists():
        raise RuntimeError("Persistent401 stop file; no new controller/model calls")
    with (OUT / (log or script.replace(".py", ".log"))).open("a") as f:
        result = subprocess.run(
            [sys.executable, str(OUT / script), *args],
            cwd=ROOT,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    return result.returncode


def relabel_phase(phase, desired, directory, workers):
    state(
        "relabel_" + phase,
        complete=len(list(directory.glob("*.json"))),
        desired=desired,
    )
    while running_labels(phase):
        state(
            "relabel_" + phase,
            complete=len(list(directory.glob("*.json"))),
            desired=desired,
        )
        if (OUT / "authentication_stop.json").exists():
            raise RuntimeError("Persistent401; stopped")
        time.sleep(15)
    # Repair only absent outputs, retaining failed judgments and unknown usage.
    for sweep in range(3):
        if len(list(directory.glob("*.json"))) >= desired:
            break
        state(
            "repair_relabel_" + phase,
            sweep=sweep,
            complete=len(list(directory.glob("*.json"))),
            desired=desired,
        )
        run("labels_run.py", [phase, "--workers", str(workers)], phase + "_resume.log")
    complete = len(list(directory.glob("*.json")))
    if complete != desired:
        state(
            "blocked_incomplete_relabel",
            phase=phase,
            complete=complete,
            desired=desired,
        )
        run("analyze.py")
        raise RuntimeError("Relabel incomplete; do not start dependent search")


def prepare_resume(arm):
    """Keep completed results; quarantine partner caches for unfinished suffixes."""
    root = STEP3 / "arms" / arm
    if not root.exists():
        return
    complete = {p.stem for p in (root / "continuations").glob("*.json")}
    archive = root / "resume_audit" / str(time.time_ns())
    moved = []
    for path in (root / "replies").glob("*.json"):
        if ":turn" in path.stem and path.stem.rsplit(":turn", 1)[0] not in complete:
            target = archive / "unfinished_partner_cache" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            moved.append(path.name)
    interrupted = 0
    for directory in ["cost_calls", "requests"]:
        for path in (root / directory).glob("*.json"):
            row = json.loads(path.read_text())
            if row["status"] == "started":
                row["status"] = (
                    "unknown_usage"
                    if directory == "cost_calls"
                    else "interrupted_unknown_usage"
                )
                row["interruption_reason"] = (
                    "Resume after process exit; usage unknown, cost reservation retained"
                )
                path.write_text(json.dumps(row, indent=2) + "\n")
                interrupted += 1
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "manifest.json").write_text(
        json.dumps(
            {
                "completed_suffixes_reused": len(complete),
                "archived_partner_caches": moved,
                "interrupted_records": interrupted,
            },
            indent=2,
        )
        + "\n"
    )


def main():
    relabel_phase("cases", 15, STEP2 / "mapped_labels", 2)
    relabel_phase("sampled", 300, STEP2 / "trajectory_batch_labels", 16)
    run("refresh_mechanics.py")
    if run("analyze.py"):
        raise RuntimeError("Pre-search report failed")
    state(
        "steps1_2_read_before_search",
        report=str(OUT / "report.md"),
        cases=15,
        sampled_trajectories=300,
    )
    if not (STEP3 / "plan_amendment_r2.json").exists() and run("preflight.py"):
        raise RuntimeError("Other-family interface check failed")
    projection = json.loads((STEP3 / "cost_projection.json").read_text())
    if projection["exceeds_3x_B1"]:
        raise RuntimeError("Projected cost exceeds user three-times-B1 cap")
    state(
        "search_started",
        projected_tokens_per_arm=projection["projected_tokens_per_arm"],
        projected_all_tokens=projection["projected_all_arms_tokens"],
    )
    pending = ["A0", "A1", "A2", "A3", "A4"]
    active = {}
    retries = {}
    launch_times = {}
    failed = []
    while pending or active:
        if (OUT / "balance_stop.json").exists():
            state("stopped_insufficient_balance")
            for process, stream in active.values():
                process.terminate()
                stream.close()
            raise RuntimeError(
                "Insufficient provider balance; all new model calls stopped"
            )
        if (OUT / "authentication_stop.json").exists():
            state("stopped_persistent401")
            for process, stream in active.values():
                process.terminate()
                stream.close()
            raise RuntimeError("Persistent401; all search controllers stopped")
        while pending and len(active) < 2:
            arm = pending.pop(0)
            if (STEP3 / "arms" / arm / "search_result.json").exists():
                continue
            prepare_resume(arm)
            launch_times[arm] = time.time()
            stream = (OUT / f"search_{arm}.log").open("a")
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(OUT / "search.py"),
                    "run",
                    "--arm",
                    arm,
                    "--workers",
                    "8",
                ],
                cwd=ROOT,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            active[arm] = (process, stream)
        for arm in list(active):
            process, stream = active[arm]
            if process.poll() is None:
                continue
            stream.close()
            del active[arm]
            if process.returncode != 0:
                state("search_arm_failed", arm=arm, returncode=process.returncode)
                errors = []
                for path in (STEP3 / "arms" / arm / "execution_errors").glob("*.json"):
                    if path.stat().st_mtime >= launch_times[arm]:
                        errors.append(json.loads(path.read_text()).get("type"))
                transient = bool(errors) and all(
                    e in {"Timeout", "TimeoutError", "APITimeoutError"} for e in errors
                )
                if (
                    transient
                    and retries.get(arm, 0) < 2
                    and not (OUT / "authentication_stop.json").exists()
                ):
                    retries[arm] = retries.get(arm, 0) + 1
                    pending.append(arm)
                    state(
                        "search_arm_queued_resume", arm=arm, timeout_resume=retries[arm]
                    )
                else:
                    failed.append(arm)
                    state("search_arm_incomplete", arm=arm, error_types=errors)
                run("analyze.py")
                continue
            state("search_arm_complete", arm=arm)
            run("analyze.py")
        time.sleep(15)
    if run("analyze.py"):
        raise RuntimeError("Final report failed")
    state(
        "partial_arm_failures" if failed else "complete",
        incomplete_arms=failed,
        report=str(OUT / "report.md"),
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        if not isinstance(exc, KeyboardInterrupt):
            state("stopped", error_type=type(exc).__name__, reason=str(exc))
        raise
