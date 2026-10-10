# A0 vs A3 on OpenRouter models — first run (shakedown), 2026-10-09

Agent/partner `deepseek/deepseek-v4.1-flash` (Fireworks), judge and strong agent `moonshotai/kimi-k3`
(InferenceNet), other family `qwen/qwen3.8-flash` (Alibaba); reasoning off; frozen C2 plan otherwise.
Caps: $20/arm, Kimi $17/arm, frozen per-arm token cap. Amendments: `plan_amendment_stop_relax_20261009.json`.

| Arm | Status | Spent | Seeds | Screen expansions | Retests | Verified |
|---|---|---|---|---|---|---|
| A0 uniform | stopped at Kimi $ cap | $18.93 | 20 | 3 (all mobile_data), 1 skipped | 21, all 16/16 vs 16/16 | 0 |
| A3 adaptive | complete (token cap) | $17.06 | 20 | 3 (2 mobile_data, 1 mms), 1 skipped | 4 | 0 |

A3 retests (other-family persistent): screening shifts −0.42, −0.42, +0.17, +0.17; retest 11 vs 12, 13 vs 11,
16 vs 15, 15 vs 15 of 16 — none significant. A0 screened only saturated states (reference 12/12, every
candidate 2/2) and spent its whole retest budget on 21 zero-shift candidates.

## Why this run cannot rank the methods

1. Frozen seed set is Luna-specific: 18/20 tasks are mobile_data_issue (206/226 states), where DeepSeek
   passes 94% natively. Search mostly happened where the agent does not fail.
2. Frozen token cap assumed ~100k-token suffixes; DeepSeek suffixes are ~2.5x longer, so each arm screened
   only 3 states.
3. Retest has no minimum-shift gate: zero-shift candidates consumed A0's retest budget.
4. Judge (Kimi rule-labeler) is ~85% of spend: every later partner turn of every suffix and every seed turn
   is judged.

Observed behaviour consistent with design: A3's variance rule moved to non-saturated nodes (incl. an mms
state) and retested only nonzero-shift candidates; A0 did not.

## Fixes for method v2 (not yet implemented)

- Dollar budget per arm instead of token budget.
- Seed task pool re-drawn for the tested model (all 114 tasks, or stratified), identical across arms.
- Retest only candidates with nonzero screening shift.
- Judge only the branched reply at screening; judge later partner turns only for retest candidates;
  no judge on native seed turns.
- Sequential (early-stopping) retests instead of fixed 16 vs 16.
