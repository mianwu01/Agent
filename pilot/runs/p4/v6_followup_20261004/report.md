# P4 v6.1 frozen follow-up

Preregistered SHA256: `914d618dea813348e134a332ad698da88270234d28c443a2998e1ae85024163b`. No new continuations; 960 frozen behavior labels (480 blocks × 2 models). Original run read-only.

## Check 1: candidate bank permutation null

| Bank | Direction | Observed | Null mean | Null95th | p upper | Null mean / observed |
|---|---|---:|---:|---:|---:|---:|
| q_only | harmful | 22 | 19.28 | 24.00 | 0.2214 | 0.877 |
| q_only | beneficial | 17 | 17.31 | 22.00 | 0.6072 | 1.018 |
| q_prime_only | harmful | 44 | 43.78 | 48.00 | 0.5372 | 0.995 |
| q_prime_only | beneficial | 45 | 42.72 | 47.00 | 0.2489 | 0.949 |
| pooled_exact_original | harmful | 66 | 62.61 | 69.00 | 0.2324 | 0.949 |
| pooled_exact_original | beneficial | 62 | 60.03 | 67.00 | 0.3498 | 0.968 |

The expected null-count ratio is not an entry-specific FDR; it is retained without clipping. Within-family permutation preserves family means, including q_prime − q mean shifts.

## Check 2: sensitivity level

| Stratum | Family | Mean S_hat [cluster95% CI] | Null mean /95th | p | States above own null95th [binomial95% CI] | Assertion max above null |
|---|---|---|---|---:|---|---|
| all40 | q | 0.01434 [0.0004, 0.0315] | -0.00006 / 0.00795 | 0.0050 | 5/40 [0.0419, 0.2680] | 5/40 |
| all40 | q_prime | 0.02583 [0.0092, 0.0446] | -0.00007 / 0.00826 | 0.0005 | 5/40 [0.0419, 0.2680] | 7/40 |
| open_union | q | 0.01751 [0.0006, 0.0377] | -0.00008 / 0.00976 | 0.0050 | 5/33 [0.0511, 0.3190] | 5/33 |
| open_union | q_prime | 0.03047 [0.0120, 0.0546] | -0.00009 / 0.01014 | 0.0005 | 5/33 [0.0511, 0.3190] | 6/33 |

Binomial chance-count intervals and all assertion-specific estimates are in check2_level.json. Assertion maxima are recalculated inside each synchronized-vector permutation, accounting for the within-state assertion search. Task dependence and discrete null distributions limit a nominal 5% state exceedance reference.

## Check 3: behavioral broadening

| Labeler | Stratum | Distinct q | Distinct q_prime | Paired difference [95% CI] | New-label share [95% CI] | Behavior S contrast [95% CI] | Between-label share [95% CI] |
|---|---|---:|---:|---|---|---|---|
| gpt-5.6-sol | nontransfer_all (n=35) | 2.686 | 3.143 | 0.457 [-0.0589, 1.0000] | 0.452 [0.3137, 0.5886] | 0.01549 [0.0009, 0.0298] | 0.133 [0.0802, 0.1994] |
| gpt-5.6-sol | nontransfer_open_union (n=33) | 2.758 | 3.152 | 0.394 [-0.1516, 0.9688] | 0.429 [0.2904, 0.5678] | 0.01628 [0.0010, 0.0309] | 0.134 [0.0800, 0.2034] |
| gpt-5.6-sol | mandated_transfer (n=5) | 1.600 | 3.400 | 1.800 [0.7500, 2.6000] | 0.367 [0.1333, 0.6333] | 0.00000 [0.0000, 0.0000] | undefined (zero outcome variance) |
| gpt-5.6-luna | nontransfer_all (n=35) | 2.371 | 2.486 | 0.114 [-0.3333, 0.5429] | 0.343 [0.2176, 0.4762] | 0.00229 [-0.0154, 0.0197] | 0.090 [0.0572, 0.1374] |
| gpt-5.6-luna | nontransfer_open_union (n=33) | 2.394 | 2.515 | 0.121 [-0.3637, 0.5759] | 0.343 [0.2121, 0.4844] | 0.00220 [-0.0170, 0.0200] | 0.090 [0.0571, 0.1395] |
| gpt-5.6-luna | mandated_transfer (n=5) | 1.000 | 1.400 | 0.400 [0.0000, 0.8000] | 0.067 [0.0000, 0.1333] | 0.00000 [0.0000, 0.0000] | undefined (zero outcome variance) |

Agreement kappa (all480 / nontransfer420): {'action': [0.7570175868319209, 0.6414112203585887], 'communication': [0.4742484917677467, 0.44810356575062466]}

Supplemental, not preregistered: repeated-input consistency diagnostic (no relabeling): {'gpt-5.6-sol': {'all480': {'repeated_input_groups': 11, 'repeated_input_blocks': 48, 'inconsistent_groups': 3}, 'nontransfer420': {'repeated_input_groups': 7, 'repeated_input_blocks': 17, 'inconsistent_groups': 1}}, 'gpt-5.6-luna': {'all480': {'repeated_input_groups': 11, 'repeated_input_blocks': 48, 'inconsistent_groups': 3}, 'nontransfer420': {'repeated_input_groups': 7, 'repeated_input_blocks': 17, 'inconsistent_groups': 3}}}
The primary Sol labeler assigns different communication labels to the exact same terminal-token input in three transfer states. Those states are excluded from primary aggregates, but this provides direct evidence of annotator instability even at temperature0. Neither labeler's outputs were corrected or tuned.

Five mandated-transfer states are excluded from primary diversity aggregates and reported separately. All per-state label-group counts, raw between/within sums of squares, and denominators are in check3_diversity.json. Weighted raw ANOVA and equal-label noise-corrected S are different estimands; neither establishes a new causal intervention.
Observed new-label share is finite-sample novelty relative to six q draws, not proof that the label is outside the population support of q.
The equal-label S correction assumes Bernoulli replication within each pooled label and does not account for additional nested text-reply heterogeneity. It is descriptive and not the primary routing statistic.

## Frozen decision table result

Check2 (q, open union): **Indeterminate**. Check3 by labeler: {'gpt-5.6-sol': 'Indeterminate', 'gpt-5.6-luna': 'Indeterminate'}. Check1 by direction: {'harmful': 'No (approximately null)', 'beneficial': 'No (approximately null)'}.

Applicable A/B/C row: **No A/B/C row applies**. Route D applies to: ['harmful', 'beneficial'].

The q permutation test is significant (p=0.0050) and the mean bootstrap CI is [0.0006, 0.0377], but the frozen conservative Yes criterion additionally requires its lower bound to exceed the null95th percentile 0.00976. This criterion is not met. The CI is not wholly inside the null band either. Thus Check2 is not classified as No / partner barely matters. Check3's paired difference CI crosses0 while novelty exceeds20%, so it satisfies neither the frozen Yes nor No criterion.

Original decision table:

| Check2 | Check3 | Check1 | Route |
|---|---|---|---|
| No (CI of mean within null band) | any | any | A: partner barely matters in telecom → switch to an environment with a freer partner (relaxed τ² user constraints or CooperBench); stop telecom locator work |
| Yes | No (paired distinct-label difference CI includes 0 and new-label share < 20%) | any | B: VS broadened wording, not behavior → test a behavior-level broadening method (open-model anti-sharpening or behavior-targeted proposals) on the top-S_q states only |
| Yes | Yes | any | C: broader behavior did not add sensitivity → the typicality half of the insight fails in this setting; report locality-only and re-plan |
| any | any | No (observed ≈ null) | D: candidate bank cannot be used for case studies; do not present individual "harmful behaviors" from it |

Any indeterminate or labeler-discordant result remains unresolved rather than being forced into a route. Absence of significant contrast is not evidence of equivalence; route C is the requested planning rule, not a proof of a universal premise failure.

## Temperature caveat

q used temperature1.0, whereas the τ²-bench paper evaluates user simulator at temperature0. Contrast is against an already-diverse native partner, not standard benchmark practice. No new temperature0 arm.

Raw permutation arrays: permutation_raw.npz. Label requests and token usage: requests/ and labeler_usage.json.

Preregistration versions: prereg.json is unchanged. prereg_amendment.json records a transport-provenance omission: the inherited p4.json_response helper appends the constant ` Return valid json.` to the registered core system prompt. The amendment preserves both the original core and full wire prompt. The same wrapper was used from the first call for both models; no definitions, thresholds, seeds or labels changed, and no extra labeling was performed.

The amendment also records an arithmetic implementation correction. For binary k=6,m=4 outcomes, the identical registered estimator is evaluated as `(23*sum(c_j^2)-3*T^2-20*T)/1440`. Exact ties are reunited with a 1e-12 comparison tolerance, far below the statistic lattice. The initial q open-union p=0.003498 is corrected to0.004998; q_prime states exceeding their own95th percentile decrease from6 to5. The prior output version is preserved in arithmetic_before_correction/. Definitions, permutation draws, thresholds and labels are unchanged.
