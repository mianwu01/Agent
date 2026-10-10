# Native check: MiniMax-M3 (agent + user), mobile_data_issue tasks, 2026-10-09

OpenRouter `minimax/minimax-m3`, first-party provider "Minimax" pinned, reasoning disabled, temperature 1.0,
native runner/evaluator, all 36 `[mobile_data_issue]` base tasks x 4 trials (143 completed). Cost $2.79 ($0.020/conv).

Pass 132/143 (92%). Frozen delegation detector: 1 delegation user turn, 0 followed by immediate transfer.
Luna on the same task family: 62/288 pass; 17 delegation turns, 17/17 immediate transfer.

Conclusion: like DeepSeek V4.1 Flash, MiniMax-M3 does not show the Luna delegation→transfer weakness natively.
