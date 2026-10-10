# Native baseline: DeepSeek V4.1 Flash (agent + user), 2026-10-09

OpenRouter `deepseek/deepseek-v4.1-flash`, provider pinned to Fireworks, reasoning disabled,
temperature 1.0 for both roles, native tau2 runner/evaluator, all 114 telecom base tasks x 4 trials planned.
Stopped at 379/456 runs (Claude Code reaped the process under low system memory); all 114 tasks covered.
Cost ≈ $0.011 per conversation (92% cached input).

| Task type | Pass | Luna census (912 runs) |
|---|---|---|
| mms_issue | 86/147 (59%) | 8/392 (2%) |
| mobile_data_issue | 131/140 (94%) | 62/288 (22%) |
| service_issue | 89/92 (97%) | 164/232 (71%) |
| total | 306/379 (81%) | 234/912 (26%) |

Frozen delegation detector (`v7_c2_native912_20261007/analyze.py`, unchanged): 3 delegation user turns,
0 followed by an immediate executed transfer (Luna: 17/17). In the two genuine delegations (run speed test;
check network mode) the DeepSeek agent declined to act remotely and guided the user to the user tool.
The third hit is a status report, not a request.

Conclusion: the delegation→transfer mechanism found on Luna is absent in this agent's native behaviour.
The search comparison on DeepSeek therefore measures discovery of DeepSeek's own failure modes
(mostly mms_issue), not rediscovery of the Luna mechanism.
