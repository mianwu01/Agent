"""Verify immutable inputs, frozen prompts, and completed follow-up artifacts."""

import collections
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

out = Path(__file__).resolve().parent
source = out.parent / "v6_paired_20261004"
manifest = json.loads((out / "input_manifest.json").read_text())
errors = []
if (
    hashlib.sha256((out / "prereg.json").read_bytes()).hexdigest()
    != manifest["prereg_sha256"]
):
    errors.append("prereg changed")


def check(item):
    name, expected = item
    return (
        name
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected
        else None
    )


with ThreadPoolExecutor(max_workers=16) as pool:
    errors.extend(
        f"source changed: {name}"
        for name in pool.map(check, manifest["inputs"].items())
        if name
    )
p = json.loads((out / "prereg.json").read_text())
wire = p["check3"]["prompt"] + " Return valid json."
request_models = collections.Counter()
request_statuses = collections.Counter()
for path in (out / "requests").glob("*.json"):
    r = json.loads(path.read_text())
    req = r["request"]
    request_models[req["model"]] += 1
    request_statuses[r["status"]] += 1
    if req["model"] not in ["openai/gpt-5.6-sol", "openai/gpt-5.6-luna"]:
        errors.append("non-labeler model call")
    if req["temperature"] != 0 or req["messages"][0]["content"] != wire:
        errors.append("labeler prompt or temperature differs")
    if not r["unit"].startswith("label:"):
        errors.append("non-labeler unit in ledger")
    if r["status"] == "started":
        errors.append("unfinished request")
rows = [json.loads(s) for s in (out / "check3_labels.jsonl").read_text().splitlines()]
protocol = json.loads((source / "protocol.json").read_text())
expected = {
    (f"{s['state_id']}:{arm}:d{j}", model)
    for s in protocol["states"]
    for arm in ["q", "q_prime"]
    for j in range(6)
    for model in ["gpt-5.6-sol", "gpt-5.6-luna"]
}
actual = {(r["unit"], r["labeler"]) for r in rows}
if actual != expected or len(rows) != 960:
    errors.append("label matrix differs")
for r in rows:
    if (
        r["action"] not in p["check3"]["action"]
        or r["communication"] not in p["check3"]["communication"]
    ):
        errors.append("invalid taxonomy")
    if r["prompt_sha256"] != hashlib.sha256(p["check3"]["prompt"].encode()).hexdigest():
        errors.append("core prompt digest differs")
raw = np.load(out / "permutation_raw.npz")
for key in raw.files:
    if key.endswith("_orders") and not np.all(
        np.sort(raw[key], axis=1) == np.arange(24)
    ):
        errors.append("invalid permutation")
summary = json.loads((source / "summary.json").read_text())
for i, s in enumerate(summary["states"]):
    for a, family in enumerate(["q", "q_prime"]):
        if not np.isclose(raw["reward_observed"][i, a], s[family]["S_hat"], atol=1e-12):
            errors.append("observed sensitivity differs")
required = [
    "prereg.json",
    "prereg_amendment.json",
    "check1_permutation.json",
    "check2_level.json",
    "check3_labels.jsonl",
    "check3_diversity.json",
    "report.md",
    "S_hat_null_distribution.png",
    "behavior_distinct_counts.png",
    "labeler_usage.json",
]
errors.extend(
    "missing artifact: " + name for name in required if not (out / name).exists()
)
result = {
    "source_input_files_unchanged": len(manifest["inputs"]),
    "prereg_unchanged": True,
    "labels": len(rows),
    "only_new_model_calls": "fixed behavior labelers",
    "requests_by_model": dict(request_models),
    "request_statuses": dict(request_statuses),
    "permutations": 2000,
    "errors": errors,
}
(out / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if errors:
    raise RuntimeError("Audit failed")
