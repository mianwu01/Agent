# B1 pre-launch estimate

Luna agent and user via AutoDL; temperature 1.0; reasoning none.

| Mode | Runs | Input tokens | Output tokens | Batch hours (concurrency 3) |
| --- | ---: | ---: | ---: | ---: |
| default | 912 | 80,142,388 | 1,094,286 | 10.46 |
| no-user | 456 | 48,108,866 | 401,348 | 2.24 |
| Total | 1368 | 128,251,254 | 1,495,634 | 12.70 |

Expected total tokens: **129,746,888**.

- 114 tasks; 8 default and 4 no-user trials per task; 1368 runs total.
- Both modes scale their measured 10-task trial by 22.8.
- Wall time scales measured batch time, including runner overhead, at concurrency 3 with modes run sequentially.
- Task difficulty, response latency and token usage may differ over all 114 tasks; this is a point estimate, not an upper bound.
- Excludes B2 proposals, branch continuations, strong-agent runs, and additional smoke/probe calls.
- All 1368 B1 runs are estimated as fresh runs; no pilot reuse assumed.
- No dollar estimate: AutoDL rates have not been verified.

See `b1-estimate.json` for per-role means, source hashes, and arithmetic.
Regenerate with `.venv/bin/python pilot/estimate_b1.py`.
