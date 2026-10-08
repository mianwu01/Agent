"""Record AutoDL model availability without saving credentials or retrying requests."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://www.autodl.art/api/v1"
MODELS = [
    "gpt-4.1-mini",
    "gpt-4.1-mini-2025-04-14",
    "gpt-4.1-2025-04-14",
    "gpt-oss-20b",
]


def main():
    """List models for each supplied token and probe planned IDs with token one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    keys = args.key_file.read_text().split()
    if not keys:
        parser.error("Key file is empty")
    output = Path(__file__).parent / "runs/trial/probes/autodl-availability.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "api_base": BASE,
        "note": "Availability requests only; not simulation results. No retries.",
        "requests": [],
    }

    def request(method, path, index, body=None):
        entry = {"method": method, "path": path, "key_index": index + 1}
        if body:
            entry["requested_model"] = body["model"]
        try:
            response = requests.request(
                method,
                BASE + path,
                headers={"Authorization": "Bearer " + keys[index]},
                json=body,
                timeout=45,
            )
            entry["http_status"] = response.status_code
            try:
                data = response.json()
            except ValueError:
                data = {"body": response.text[:2000]}
            if path == "/models" and isinstance(data.get("data"), list):
                data = {"model_ids": [model.get("id") for model in data["data"]]}
            entry["response"] = data
        except requests.RequestException as exc:
            entry["transport_error"] = type(exc).__name__
        report["requests"].append(entry)
        serialized = json.dumps(report, indent=2, ensure_ascii=False)
        for key in keys:
            serialized = serialized.replace(key, "[REDACTED]")
        output.write_text(serialized + "\n")
        print(
            method,
            path,
            entry.get("requested_model", f"key {index + 1}"),
            entry.get("http_status", entry.get("transport_error")),
            flush=True,
        )

    for index in range(len(keys)):
        request("GET", "/models", index)
    for model in MODELS:
        request(
            "POST",
            "/chat/completions",
            0,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply OK."}],
                "max_tokens": 8,
                "temperature": 1.0,
            },
        )
    print(output)


if __name__ == "__main__":
    main()
