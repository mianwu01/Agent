"""Run B1 then B2/B3; stop visibly on any failed stage, without retry layers."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    """Launch sequential stages with the measured reliable concurrency."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-iid", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    n = json.loads((root / "pilot/concurrency.json").read_text())["selected"]
    commands = [
        (
            "iid-default",
            ["pilot/run_trial.py", "--candidate", "luna", "--iid", "--mode", "default"],
        ),
        (
            "iid-no-user",
            ["pilot/run_trial.py", "--candidate", "luna", "--iid", "--mode", "no-user"],
        ),
        ("iid-summary", ["pilot/summarize_iid.py"]),
        ("branch", ["pilot/run_branch.py"]),
        ("branch-reading", ["pilot/render_branch.py"]),
    ]
    for stage, cmd in commands:
        if stage.startswith("iid-") and stage != "iid-summary":
            cmd += [
                "--autodl-key-file",
                "../Memory/key/key.txt",
                "--max-concurrency",
                str(n),
            ]
        if args.resume_iid and stage in ("iid-default", "iid-no-user"):
            mode = "default" if stage == "iid-default" else "no-user"
            if (root / "pilot/runs/iid" / mode / "results.json").exists():
                cmd.append("--resume")
        if stage == "branch":
            cmd += ["--key-file", "../Memory/key/key.txt", "--concurrency", str(n)]
        status = {
            "stage": stage,
            "status": "running",
            "concurrency": n,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = root / "pilot/b-status.json"
        path.write_text(json.dumps(status, indent=2) + "\n")
        with (root / f"pilot/b-{stage}.log").open("a") as log:
            result = subprocess.run(
                [sys.executable, *cmd], cwd=root, stdout=log, stderr=subprocess.STDOUT
            )
        status.update(
            status="complete" if result.returncode == 0 else "failed",
            returncode=result.returncode,
        )
        path.write_text(json.dumps(status, indent=2) + "\n")
        if result.returncode:
            raise SystemExit(result.returncode)
    status.update(stage="B1-B3", status="complete")
    path.write_text(json.dumps(status, indent=2) + "\n")


if __name__ == "__main__":
    main()
