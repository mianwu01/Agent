"""Compare a stronger agent on exactly the v6 pilot's sampled partner turns."""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import p4_v6 as v6


def main():
    """Reuse partner samples and change only the continuation agent model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=v6.OUT)
    parser.add_argument(
        "--out", type=Path, default=v6.OUT.parent / "v6_reference_20261004"
    )
    parser.add_argument("--agent", default="openai/gpt-5.6-sol")
    parser.add_argument("--states", nargs="+", default=["s000", "s003", "s006", "s009"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--key-file", type=Path, default=v6.p4.ROOT / "api.txt")
    args = parser.parse_args()
    source = args.source.resolve()
    v6.OUT = args.out.resolve()
    v6.p4.OUT = v6.OUT
    protocol = v6.p4.read(source / "protocol.json")
    protocol = {
        **protocol,
        "created_at": time.time(),
        "agent": args.agent,
        "purpose": "Stronger-agent diagnostic on identical saved prefixes and partner blocks",
        "source_pilot": str(source),
        "states": [c for c in protocol["states"] if c["state_id"] in args.states],
    }
    if (v6.OUT / "protocol.json").exists():
        protocol = v6.p4.read(v6.OUT / "protocol.json")
    else:
        v6.p4.save(v6.OUT / "protocol.json", protocol)
        v6.p4.save(v6.OUT / "tasks.json", v6.p4.read(source / "tasks.json"))
    original_config = v6.run_config

    def reference_config(key=0, seed=0):
        cfg = original_config(key, seed)
        cfg.llm_agent = protocol["agent"]
        return cfg

    v6.run_config = reference_config
    v6.p4.setup(args.key_file, args.workers)
    jobs = []
    for case in protocol["states"]:
        for j in range(protocol["k"]):
            reply_path = source / "replies" / f"{case['state_id']}:d{j}.json"
            reply = v6.p4.read(reply_path)
            v6.p4.save(v6.OUT / "replies" / reply_path.name, reply)
            for rep in range(protocol["m"]):
                jobs.append((case, reply, rep))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(v6.continuation, c, d, r, n % 4)
            for n, (c, d, r) in enumerate(jobs)
        ]
        for future in as_completed(futures):
            future.result()
    v6.report(protocol)
    baseline = v6.p4.read(source / "summary.json")
    reference = v6.p4.read(v6.OUT / "summary.json")
    baseline_by_id = {e["state_id"]: e for e in baseline["estimates"]}
    comparison = [
        {
            "state_id": e["state_id"],
            "task_id": e["task_id"],
            "luna_success_rate": baseline_by_id[e["state_id"]]["V_hat"],
            "reference_success_rate": e["V_hat"],
            "luna_sensitivity": baseline_by_id[e["state_id"]]["S_hat"],
            "reference_sensitivity": e["S_hat"],
            "reference_reply_success_rates": e["reply_success_rates"],
        }
        for e in reference["estimates"]
    ]
    v6.p4.save(v6.OUT / "comparison.json", comparison)
    lines = [
        "# Same-prefix stronger-agent comparison",
        "",
        "| State | Luna success | Sol success | Sol sensitivity |",
        "|---|---:|---:|---:|",
    ]
    for row in comparison:
        lines.append(
            f"| {row['state_id']} | {row['luna_success_rate']:.3f} | "
            f"{row['reference_success_rate']:.3f} | {row['reference_sensitivity']:.4f} |"
        )
    lines.extend(
        [
            "",
            "Same sampled partner blocks, same suffix seeds, same tasks; only the agent model changes. Four states chosen for diagnostics after observing the pilot, including an all-success control. This is not an independent validation set or a causal failure certificate.",
        ]
    )
    (v6.OUT / "comparison.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
