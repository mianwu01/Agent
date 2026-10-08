"""Audit completed paired units against their saved native trajectories."""

import collections
from concurrent.futures import ThreadPoolExecutor

import p4_v6_paired as paired


def main():
    """Check the fixed matrix, replayed behavior, model, and native rewards."""
    paired.activate()
    p4 = paired.v6.p4
    protocol = paired.prepare()
    replies = {
        path.stem: p4.read(path) for path in (paired.OUT / "replies").glob("*.json")
    }
    selections = {
        path.stem: p4.read(path)["reply"]
        for path in (paired.OUT / "sol_selection").glob("*.json")
    }
    expected = set()
    for case in protocol["states"]:
        for arm in ["q", "q_prime"]:
            for j in range(protocol["k"]):
                for rep in range(protocol["m"]):
                    expected.add(f"{case['state_id']}:{arm}:d{j}:r{rep}")
        diagnostic = selections[case["state_id"]]
        for rep in range(protocol["sol_m"]):
            expected.add(f"{diagnostic['unit']}:r{rep}")
    paths = list((paired.OUT / "continuations").glob("*.json"))
    errors = []
    actual = {path.stem for path in paths}
    if actual != expected:
        errors.append(
            {
                "missing": sorted(expected - actual),
                "unexpected": sorted(actual - expected),
            }
        )

    def check(path):
        row = p4.read(path)
        sim = p4.read(paired.OUT / "trajectories" / path.name)
        arm = row["unit"].split(":")[1]
        reply = (
            selections[row["state_id"]]
            if arm == "sol"
            else replies[row["unit"].rsplit(":", 1)[0]]
        )
        prefix = sim["messages"][: len(reply["prefix"])]
        problems = []
        if paired.v6.partner_signature(prefix) != paired.v6.partner_signature(
            reply["prefix"]
        ):
            problems.append("replayed prefix behavior differs")
        if row["reward"] != sim["reward_info"]["reward"]:
            problems.append("native reward differs")
        expected_model = (
            protocol["reference_agent"] if arm == "sol" else protocol["agent"]
        )
        if row["agent_model"] != expected_model:
            problems.append("agent model differs")
        return {"unit": row["unit"], "problems": problems} if problems else None

    with ThreadPoolExecutor(max_workers=16) as pool:
        errors.extend(result for result in pool.map(check, paths) if result)
    broad = [r for r in replies.values() if r["arm"] == "q_prime"]
    if any(
        r["proposal_version"] != "json_history_payload" or not r["fidelity"]["faithful"]
        for r in broad
    ):
        errors.append({"problem": "q_prime version/fidelity mismatch"})
    for case in protocol["states"]:
        source = p4.read(paired.OUT / "sources" / f"{case['source_id']}.json")
        last_agent = source["messages"][case["index"] - 1].get("content") or ""
        if (
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
            not in last_agent.upper()
        ):
            continue
        for j in range(protocol["k"]):
            reply = replies[f"{case['state_id']}:q_prime:d{j}"]
            block = reply["partner_block"]
            if not any(
                "###TRANSFER###" in (m.get("content") or "") for m in block
            ) or any(m.get("tool_calls") for m in block):
                errors.append(
                    {"unit": reply["unit"], "problem": "transfer protocol violation"}
                )
    result = {
        "continuations": len(paths),
        "by_arm": dict(collections.Counter(p.stem.split(":")[1] for p in paths)),
        "replies": len(replies),
        "q_prime_reply_count": len(broad),
        "expected_continuations": len(expected),
        "errors": errors,
        "prefix_comparison": "Complete role/content/tool behavior, excluding regenerated timestamps and accounting metadata",
    }
    p4.save(paired.OUT / "audit.json", result)
    print(result)
    if errors:
        raise RuntimeError("Audit discrepancies saved in audit.json")


if __name__ == "__main__":
    main()
