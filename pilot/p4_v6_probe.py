"""Small VS-batch versus outcome-feedback probe at a measured v6 state."""

import argparse
import collections
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import p4_v6 as v6
from run_branch import proposal_messages

from tau2.data_model.message import SystemMessage, UserMessage
from tau2.data_model.tasks import Task


def main():
    """Generate text-only faithful alternatives and measure their suffix outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=v6.OUT)
    parser.add_argument("--out", type=Path, default=v6.OUT.parent / "v6_probe_20261004")
    parser.add_argument("--state", default="s003")
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--m", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--key-file", type=Path, default=v6.p4.ROOT / "api.txt")
    args = parser.parse_args()
    source = args.source.resolve()
    original_protocol = v6.p4.read(source / "protocol.json")
    case = next(c for c in original_protocol["states"] if c["state_id"] == args.state)
    original = v6.p4.read(source / "sources" / (case["source_id"] + ".json"))
    task_data = v6.p4.read(source / "tasks.json")[case["task_id"]]
    task = Task.model_validate(task_data)
    prefix = original["messages"][: case["index"]]
    measured = [
        v6.p4.read(p)
        for p in (source / "continuations").glob(case["state_id"] + "*.json")
    ]
    baseline = statistics.mean(r["reward"] == 1 for r in measured)
    feedback = []
    for j in range(original_protocol["k"]):
        reply = v6.p4.read(source / "replies" / f"{case['state_id']}:d{j}.json")
        feedback.append(
            {
                "partner_block": [
                    {key: msg.get(key) for key in ("role", "content", "tool_calls")}
                    for msg in reply["partner_block"]
                ],
                "delta_hat": statistics.mean(
                    r["reward"] == 1 for r in measured if r["j"] == j
                )
                - baseline,
            }
        )
    v6.OUT = args.out.resolve()
    v6.p4.OUT = v6.OUT
    v6.p4.setup(args.key_file, args.workers)
    v6.p4.save(v6.OUT / "tasks.json", {task.id: task_data})
    v6.p4.save(
        v6.OUT / "protocol.json",
        {
            "source": str(source),
            "case": case,
            "baseline_success": baseline,
            "arms": ["vs_multi", "outcome_feedback"],
            "arm_definitions": {
                "vs_multi": "Single-batch VS baseline; no iterative VS-Multi claim",
                "outcome_feedback": "Same batch generation plus measured outcome feedback",
            },
            "candidates_per_arm": args.candidates,
            "m": args.m,
            "scope": "Text-only probes. Native tools disabled during candidate generation; task/DB retained during continuation. Exploratory effects, no significance gate.",
        },
    )
    jobs = []
    for arm in ["vs_multi", "outcome_feedback"]:
        unit = case["state_id"] + ":" + arm
        v6.p4.UNIT.set(unit)
        v6.p4.KEY.set(0)
        v6.p4.ROLE.set("probe")
        path = v6.OUT / "proposals" / (arm + ".json")
        orch = v6.build(task, prefix)
        orch.initialize()
        if path.exists():
            saved = v6.p4.read(path)
        else:
            instruction = f'Generate {args.candidates} behaviorally different messages you could plausibly send next as this customer. Follow your scenario and the actual phone state. Do not claim to have performed a new action; you may ask for clarification, express uncertainty, or report facts you already know. Return only a JSON array of objects with "message" and "probability" (a number between 0 and 1). Probabilities are verbalized estimates, not model logprobs.'
            history = proposal_messages(orch.user, prefix)
            history[-1] = SystemMessage(role="system", content=instruction)
            if arm == "outcome_feedback":
                history.append(
                    SystemMessage(
                        role="system",
                        content="Measured replies and changes in agent success follow. Seek a different faithful behavior that could change success; do not repeat an existing reply.\n"
                        + json.dumps(feedback),
                    )
                )
            response = v6.p4.llm_utils.generate(
                model=orch.user.llm,
                messages=history,
                tools=orch.user.tools,
                tool_choice="none",
                **v6.p4.llm_args(0),
            )

            text = response.content
            candidates = json.loads(text[text.index("[") : text.rindex("]") + 1])
            saved = {
                "response": response.model_dump(mode="json"),
                "candidates": candidates,
            }
            v6.p4.save(path, saved)
        for j, candidate in enumerate(saved["candidates"]):
            identifier = unit + f":d{j}"
            fidelity_path = v6.OUT / "fidelity" / (identifier + ".json")
            if fidelity_path.exists():
                fidelity = v6.p4.read(fidelity_path)
            else:
                fidelity = v6.p4.json_response(
                    'Check whether this candidate is a plausible faithful customer reply at this prefix. The user system prompt, private phone state, and user-visible history are supplied. Reject invented device observations, invented actions, contradictions, or abandonment of the customer goal. Uncertainty and clarification are allowed. Return JSON {"faithful": true/false, "reason": "..."}.',
                    {
                        "user_system": orch.user.system_prompt,
                        "state": v6.p4.state(orch.environment)["user"],
                        "history": [
                            m.model_dump(mode="json")
                            for m in proposal_messages(orch.user, prefix)[:-1]
                        ],
                        "candidate": candidate["message"],
                    },
                    "gpt-5.6-sol",
                    identifier + ":fidelity",
                    0,
                )
                v6.p4.save(fidelity_path, fidelity)
            if not fidelity["faithful"]:
                continue
            msg = UserMessage(role="user", content=candidate["message"]).model_dump(
                mode="json"
            )
            reply = {"unit": identifier, "j": j, "prefix": prefix + [msg]}
            for rep in range(args.m):
                jobs.append((arm, candidate, case, reply, rep))
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(v6.continuation, c, d, r, n % 4): (arm, candidate)
            for n, (arm, candidate, c, d, r) in enumerate(jobs)
        }
        for future in as_completed(futures):
            arm, candidate = futures[future]
            results.append({**future.result(), "arm": arm, "candidate": candidate})
    v6.p4.save(v6.OUT / "results.json", results)
    summary = []
    for arm in ["vs_multi", "outcome_feedback"]:
        for j in sorted({r["j"] for r in results if r["arm"] == arm}):
            selected = [r for r in results if r["arm"] == arm and r["j"] == j]
            summary.append(
                {
                    "arm": arm,
                    "j": j,
                    "message": selected[0]["candidate"]["message"],
                    "success_rate": statistics.mean(r["reward"] == 1 for r in selected),
                    "delta_hat": statistics.mean(r["reward"] == 1 for r in selected)
                    - baseline,
                }
            )
    usage = collections.Counter()
    for path in (v6.OUT / "requests").glob("*.json"):
        request = v6.p4.read(path)
        for kind in ("prompt_tokens", "completion_tokens"):
            usage[kind] += (request.get("usage") or {}).get(kind, 0)
    v6.p4.save(
        v6.OUT / "summary.json",
        {
            "baseline": baseline,
            "candidates": summary,
            "provider_usage": dict(usage),
            "note": "Exploratory effects based on two suffixes per candidate; fidelity is a model assessment, not human gold.",
        },
    )
    lines = [
        "# Text-only partner probe",
        "",
        f"State: {case['state_id']}; native sampled-reply success rate: {baseline:.3f}.",
        "",
        "| Arm | Candidate | Success rate | Delta |",
        "|---|---|---:|---:|",
    ]
    for row in summary:
        arm = "VS batch" if row["arm"] == "vs_multi" else "Outcome feedback"
        message = row["message"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {arm} | {message} | {row['success_rate']:.3f} | {row['delta_hat']:+.3f} |"
        )
    lines.extend(
        [
            "",
            f"Provider usage: {dict(usage)}.",
            "",
            "Each candidate has two continuations and a model fidelity assessment. The VS arm uses one candidate batch, not iterative VS-Multi. These are exploratory effects; the native-reply baseline at this state consists of identical phone-number replies.",
        ]
    )
    (v6.OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(summary, flush=True)


if __name__ == "__main__":
    main()
