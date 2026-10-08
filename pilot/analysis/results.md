# Prompt B descriptive results

Analysis only; no new model runs. Success = reward == 1; failure/flip = reward == 0. No failure interpretation.

## A. B1 outcome structure

| mode | runs | successes | success_rate |
| --- | --- | --- | --- |
| default | 912 | 234 | 0.256579 |
| no-user | 456 | 318 | 0.697368 |

S: no-user mean ≥0.75 and default mean ≤0.25. R: reverse. Both ok: both means ≥0.75. Both fail: both means ≤0.25. Mixed: all remaining tasks. A1 specifies S/R; the same high/low cutoffs are applied to the additional categories.

| category | tasks |
| --- | --- |
| S | 51 |
| R | 0 |
| both ok | 20 |
| both fail | 34 |
| mixed | 9 |

### default success-count histogram

| successes | tasks |
| --- | --- |
| 0 | 59 |
| 1 | 13 |
| 2 | 13 |
| 3 | 2 |
| 4 | 5 |
| 5 | 2 |
| 6 | 0 |
| 7 | 1 |
| 8 | 19 |

### no-user success-count histogram

| successes | tasks |
| --- | --- |
| 0 | 34 |
| 1 | 0 |
| 2 | 0 |
| 3 | 2 |
| 4 | 78 |

## B. Stratified flip rates

Empirical terciles are computed once across 189 unique positions using linear quantiles: q1=0.103713768116, q2=0.607744107744. Lower: x≤q1; middle: q1<x≤q2; upper: x>q2. Ties stay together. Fixed thirds additionally use cutoffs 1/3 and 2/3 with the same boundary convention. x=i/n_messages_source, using the recorded zero-based i. Rates are continuation-weighted.

| dimension | arm | bin | positions | continuations | flipped | flip_rate |
| --- | --- | --- | --- | --- | --- | --- |
| default_success_count | resample | 1-3 | 86 | 172 | 73 | 0.424419 |
| default_success_count | resample | 4-6 | 28 | 56 | 15 | 0.267857 |
| default_success_count | resample | 7-8 | 75 | 150 | 1 | 0.006667 |
| default_success_count | vs_tail | 1-3 | 86 | 172 | 75 | 0.436047 |
| default_success_count | vs_tail | 4-6 | 28 | 56 | 14 | 0.250000 |
| default_success_count | vs_tail | 7-8 | 75 | 150 | 1 | 0.006667 |
| relative_position_empirical_tercile | resample | lower | 63 | 126 | 38 | 0.301587 |
| relative_position_empirical_tercile | resample | middle | 63 | 126 | 31 | 0.246032 |
| relative_position_empirical_tercile | resample | upper | 63 | 126 | 20 | 0.158730 |
| relative_position_empirical_tercile | vs_tail | lower | 63 | 126 | 36 | 0.285714 |
| relative_position_empirical_tercile | vs_tail | middle | 63 | 126 | 23 | 0.182540 |
| relative_position_empirical_tercile | vs_tail | upper | 63 | 126 | 31 | 0.246032 |
| relative_position_fixed_third | resample | lower | 92 | 184 | 48 | 0.260870 |
| relative_position_fixed_third | resample | middle | 49 | 98 | 30 | 0.306122 |
| relative_position_fixed_third | resample | upper | 48 | 96 | 11 | 0.114583 |
| relative_position_fixed_third | vs_tail | lower | 92 | 184 | 42 | 0.228261 |
| relative_position_fixed_third | vs_tail | middle | 49 | 98 | 31 | 0.316327 |
| relative_position_fixed_third | vs_tail | upper | 48 | 96 | 17 | 0.177083 |

## C. Paired flip counts

Rows: resample flips out of 2; columns: vs_tail flips out of 2. Cell counts are source/position pairs.

| resample_flips | vs_tail_0 | vs_tail_1 | vs_tail_2 |
| --- | --- | --- | --- |
| 0 | 108 | 13 | 5 |
| 1 | 14 | 12 | 11 |
| 2 | 5 | 9 | 12 |

## D. VS proposal probabilities

Each of the 189 final valid proposals is counted once, including the four replacements. Original invalid calls are excluded from candidate distributions but included in token accounting. Full exact-value frequency distributions are in d_*_distribution.csv.

| variable | n | mean | min | p10 | p25 | median | p75 | p90 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chosen_probability | 189 | 0.063810 | 0.000000 | 0.030000 | 0.050000 | 0.060000 | 0.080000 | 0.100000 | 0.120000 |
| probability_sum | 189 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

[25 sampled examples](vs_examples.md).

## E. Recorded checks in flipped continuations

| arm | termination_reason | continuations |
| --- | --- | --- |
| resample | user_stop | 89 |
| vs_tail | user_stop | 90 |

| arm | flipped | any_env_failure | any_action_failure | both | neither |
| --- | --- | --- | --- | --- | --- |
| resample | 89 | 88 | 89 | 88 | 0 |
| vs_tail | 90 | 89 | 90 | 89 | 0 |

Counts below include every recorded false env assertion/action check, whether or not that check type belongs to the task's reward_basis. Occurrences count checks; continuations count distinct branch IDs. These are recorded checks, not inferred causes. Per-continuation reward_basis is in e_flipped_continuations.csv.

| arm | check_type | function_name | failed_check_occurrences | continuations |
| --- | --- | --- | --- | --- |
| resample | action_check | disconnect_vpn | 28 | 28 |
| resample | action_check | grant_app_permission | 6 | 3 |
| resample | action_check | reboot_device | 4 | 4 |
| resample | action_check | reseat_sim_card | 4 | 4 |
| resample | action_check | reset_apn_settings | 4 | 4 |
| resample | action_check | set_network_mode_preference | 48 | 48 |
| resample | action_check | toggle_airplane_mode | 18 | 18 |
| resample | action_check | toggle_data | 18 | 18 |
| resample | action_check | toggle_data_saver_mode | 20 | 20 |
| resample | action_check | toggle_roaming | 28 | 28 |
| resample | action_check | toggle_wifi_calling | 1 | 1 |
| resample | action_check | transfer_to_human_agents | 1 | 1 |
| resample | env_assertion | assert_can_send_mms | 18 | 18 |
| resample | env_assertion | assert_internet_speed | 65 | 65 |
| resample | env_assertion | assert_mobile_data_status | 37 | 37 |
| resample | env_assertion | assert_service_status | 5 | 5 |
| vs_tail | action_check | disconnect_vpn | 25 | 25 |
| vs_tail | action_check | grant_app_permission | 4 | 2 |
| vs_tail | action_check | reboot_device | 2 | 2 |
| vs_tail | action_check | refuel_data | 3 | 3 |
| vs_tail | action_check | reseat_sim_card | 7 | 7 |
| vs_tail | action_check | reset_apn_settings | 2 | 2 |
| vs_tail | action_check | set_network_mode_preference | 46 | 46 |
| vs_tail | action_check | toggle_airplane_mode | 19 | 19 |
| vs_tail | action_check | toggle_data | 18 | 18 |
| vs_tail | action_check | toggle_data_saver_mode | 21 | 21 |
| vs_tail | action_check | toggle_roaming | 34 | 34 |
| vs_tail | action_check | toggle_wifi_calling | 3 | 3 |
| vs_tail | action_check | transfer_to_human_agents | 1 | 1 |
| vs_tail | env_assertion | assert_can_send_mms | 18 | 18 |
| vs_tail | env_assertion | assert_data_refueling_amount | 3 | 3 |
| vs_tail | env_assertion | assert_internet_speed | 63 | 63 |
| vs_tail | env_assertion | assert_mobile_data_status | 44 | 44 |
| vs_tail | env_assertion | assert_service_status | 8 | 8 |

## F. Yield per recorded token

| stage | arm | outcomes | failures | continuation_tokens | proposal_tokens | recorded_total_tokens | failures_per_million_recorded_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | default | 912 | 678 | 79161969 | 0 | 79161969 | 8.564719 |
| B1 | no-user | 456 | 138 | 42347101 | 0 | 42347101 | 3.258783 |
| B2 | resample | 378 | 89 | 24359527 | 0 | 24359527 | 3.653601 |
| B2 | vs_tail | 378 | 90 | 24433663 | 600447 | 25034110 | 3.595095 |

Both stages use all saved response usage, including saved invalid proposal responses. Neither stage imputes unavailable failed/interrupted-attempt usage. Therefore these denominators are recorded-token totals, not total billed usage; the rates are not adjusted for missing usage.

## G. Failed/interrupted-attempt usage ledger

[g_missing_attempt_usage.csv](g_missing_attempt_usage.csv) lists 48 interrupted B1 default runs and one failed B2 vs_tail continuation. No such B1 no-user attempt is identified in retained logs. Each row links the eventual completed run/branch; the interrupted attempt's simulation UUID was not retained.

B1 identities are reconstructed, not all individually printed: the final status reports 38 completed and 48 active; the native scheduler leases in trial-major FIFO order. The first 86 units minus the 38 archived checkpoints identify the 48 interrupted units. All 10 identities printed in the truncated final status match this set. Queued but unstarted units are excluded.

B2's saved error identifies the source/position; the recorded recovery history identifies vs_tail replicate 0. Its failed partial trajectory/usage was not saved. Replicate 1 had not yet started and is not a missing-usage attempt.

Four invalid proposal calls have saved usage and are already counted in F; see g_failed_proposals_with_known_usage.csv. Their replacement calls are also counted once.

No native simulation retry events were found in the five retained run logs (g_retry_log_scan.json). Provider-internal retries/timeouts do not have a complete per-request ledger. Thus this is the complete identifiable run-level ledger from saved evidence, not proof that all provider attempts are observable. Unknown usage is left unknown, never treated as zero. Probes and the earlier trial are outside B1/B2 and excluded from both denominators.

## Files and reproducibility

Run offline with: `.venv/bin/python pilot/analysis/analyze.py`. All output tables and examples are in this directory. input_manifest.json records SHA-256 fingerprints of read inputs. No source run artifacts are modified.
