"""Measure AutoDL concurrency with bounded, zero-retry chat requests."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests


def main():
    """Save every attempt; stop increasing at an error or throughput regression."""
    key = Path("../Memory/key/key.txt").read_text().split()[0]
    report = {
        "levels": [],
        "selected": 3,
        "seed_support": "accepted, determinism unverified",
    }
    out = Path("pilot/concurrency.json")

    def call(i):
        start = time.monotonic()
        try:
            r = requests.post(
                "https://www.autodl.art/api/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={
                    "model": "gpt-5.6-luna",
                    "temperature": 1.0,
                    "reasoning_effort": "none",
                    "seed": i,
                    "max_completion_tokens": 64,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Read this customer context. "
                            + (
                                "The mobile customer needs help with service and billing. "
                                * 400
                            ),
                        },
                        {
                            "role": "user",
                            "content": "Reply with one short customer-support greeting.",
                        },
                    ],
                },
                timeout=90,
            )
            d = r.json()
            return {
                "status": r.status_code,
                "seconds": time.monotonic() - start,
                "usage": d.get("usage"),
                "ok": r.status_code == 200 and bool(d.get("choices")),
            }
        except Exception as e:
            return {
                "ok": False,
                "error_type": type(e).__name__,
                "seconds": time.monotonic() - start,
            }

    previous = 0
    for n in [6, 12, 24, 48, 64]:
        start = time.monotonic()
        with ThreadPoolExecutor(n) as pool:
            rows = list(pool.map(call, range(n * 2)))
        elapsed = time.monotonic() - start
        rate = len(rows) / elapsed
        good = all(r["ok"] for r in rows)
        report["levels"].append(
            {
                "concurrency": n,
                "seconds": elapsed,
                "requests_per_second": rate,
                "requests": rows,
            }
        )
        if good and rate >= previous * 0.9:
            report["selected"] = n
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(
            "concurrency",
            n,
            "ok",
            sum(r["ok"] for r in rows),
            "/",
            len(rows),
            "rps",
            round(rate, 2),
            "selected",
            report["selected"],
            flush=True,
        )
        if not good or rate < previous * 0.9:
            break
        previous = rate
    report["limit_note"] = (
        "Highest reliable level tested, bounded at 64; no claim of an absolute endpoint limit."
    )
    out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
