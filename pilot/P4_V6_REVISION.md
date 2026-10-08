# v6.1: paired native and broadened faithful sensitivity

This revision implements the 2026-10-04 discussion and supersedes the locator
and concentration-estimation instructions in handoff sections 03 and 05.
The original ZIP and first pilot are retained as historical evidence.

## Corrected measurement and locator

Define S_q(s) = Var under the normal partner q of V(s,d), and S_q_prime(s) under
a broadened faithful proposal family. The locator and main concentration result
use S_q_prime; S_q is a paired reference. Report both, their signed difference,
and V_q_prime minus V_q. A variance contrast need not be positive and is distinct
from a logprob/typicality correlation. A family change can shift average success
even when both within-family variances are zero.

Here q_prime has an explicit reproducible sampling rule: generate an independent
VS batch of five possibilities, draw one uniformly, execute the complete native
partner turn, and accept it after a Sol fidelity check. On rejection repeat with
an independent batch/draw. All six accepted reply draws use independent batches.
The proposal family permits the same native user tool schemas; tool outputs and
subsequent user messages are produced by the native environment/user simulator.
There is no outcome-conditioned proposal selection in this measurement batch.

Normal q replies receive the same fidelity check for measurement, without
filtering them or changing q. The proposal, actual executed block, fidelity
judgment, private-state snapshots and rejected proposals remain available.
Probability fields from VS are not used as logprob or sampling weights.

## State pool and strata

The 912 saved Luna trajectories cover 114 telecom tasks. Twenty-two tasks have
empirical success rates in [0.2,0.8]; twenty are mobile-data/MMS tasks. Select two
prefixes uniformly from each of those twenty tasks, yielding forty states.
There are 1,112 eligible prefix instances in that selected task pool. This is a
task-selected, task-balanced estimand, not the full telecom state distribution.
Source episode success is not a prefix-selection criterion. The protocol and
state pool were saved before the new continuation outcomes.

At each state: q and q_prime each have k=6 replies, m=4 suffixes per reply.
Record S, V, distinct reply blocks, fidelity and the vector of individual task
assertions for both arms. In addition run four Sol suffixes on the sampled block
with lowest Luna success, as a recovery diagnostic. Total: 1,920 paired suffixes
plus 160 Sol suffixes. Both continuation agents keep temperature 1.0 and reasoning
none; fidelity judgments use Sol at temperature 0.

Report q-unresolved, q_prime-unresolved, Sol-recoverable and their union
separately. Unresolved means estimated V in [0.1,0.9]. The main concentration
stratum is the open union, with all-state concentration shown alongside it.
Observed floor/ceiling and failed Sol recovery are descriptive labels rather
than proof that an individual task is impossible. A mixed task does not guarantee
that every sampled prefix is unresolved.

Sample collapse = k accepted/native draws yielding one distinct executed reply
block. Report its rate for q and q_prime. This is sample duplicate evidence,
not a proof that the underlying partner distribution is a point mass.

## Corrected cross-fitting

Split the six reply draws into two independent groups of three: draws 0,1,2 and
3,4,5. Keep all four suffixes attached to every reply in each group. Compute the
noise-corrected sensitivity within each group. Rank states using group A and
sum sensitivities using group B; swap roles for the second fold. Never split
m=2 into two m=1 estimates. Retain negative estimates and raw concentration
numerators/denominators; noisy ratios need not be within [0,1].

The underlying estimator for reply means p_j and m suffixes is:

S_hat = sample_variance(p_j) - mean[p_j(1-p_j)/(m-1)].

Independent batches are important: taking six candidates from one shared VS
batch would not provide independent groups for this measurement.

## Execution

```bash
.venv/bin/python pilot/p4_v6_paired.py --prepare-only
.venv/bin/python pilot/p4_v6_paired_fast.py --workers 96
.venv/bin/python pilot/p4_v6_paired.py --report-only
```

Default output: `pilot/runs/p4/v6_paired_20261004/`. Completed reply and suffix
files are reused on resume. The fast scheduler samples missing replies in parallel,
then schedules each missing suffix independently, with 96 workers and 24 concurrent
requests per key. Paired results are reported before Sol diagnostics. Failed units
receive up to four explicit attempts; completed units are retained. All attempts
remain in the existing redacted request ledger. This changes execution scheduling,
not the fixed sampling protocol, models, temperature or sample sizes.
`summary.json` and `report.md` contain the paired measurement, strata and
concentration; `candidate_bank.json` reports harmful and beneficial exploratory
candidates separately. Effects pool identical blocks across both families.

No human annotation or significance threshold gates this exploratory batch.
The next comparison is driven by measured sensitivity and directional effects,
with genuine logprob analysis reserved for a working open-model route.

## API framing correction during launch

The proxy rejected JSON-mode proposals when the JSON instruction was in an
additional trailing system message. A lowercase marker in that message did not
resolve it. It also returned an actual tool call despite `tool_choice="none"`.
Putting the marker only in the first system message still failed for some
histories. The working proposal call follows the existing two-message JSON
request pattern: system instructions plus a JSON user payload containing the
native user-visible history, tool schemas and an explicit json output request.
API function tools are omitted during candidate generation.
The selected candidate's action still executes through the native environment;
subsequent native user calls keep the original tool schemas.

Old q_prime proposals and suffixes are under `transport_history/trailing_system/`
and are excluded from the paired measurement. Native q suffixes are retained.
The current proposal version is `json_history_payload`; the intermediate
`first_system_text_schemas` attempts are archived separately as well. Successful old
attempts remain in token accounting; interrupted attempts have explicit unknown
usage. States, k/m, source sampling, models and analysis splits did not change.

## Native transfer protocol correction

Inspection found five sampled prefixes whose preceding agent explicitly announced
a transfer. Native simulator guidelines require `###TRANSFER###` there. The Sol
fidelity checker accepted some proposals that continued troubleshooting without
this token; these are protocol violations, not evidence of hidden faithful
sensitivity. All q_prime draws and suffixes at those five states are retained in
`transport_history/transfer_protocol/` and regenerated with an explicit terminal
constraint plus enforcement of the native transfer token in fidelity acceptance.
Other states and all native q observations are retained. These five states remain
in the sampled pool, including their terminal outcome, rather than being silently
excluded from the state distribution.

## Completed corrected batch

All forty states are complete: 960 q suffixes, 960 q_prime suffixes, and 160 Sol
diagnostic suffixes. The audit checks all 2,080 native trajectories, their reward
records, replayed prefix behavior and agent models, and all thirty corrected
transfer replies; it reports no discrepancies. The native tool-replay and
reply-half cross-fitting tests pass, as do Ruff checks for the changed scripts.

| Measurement | q | q_prime |
|---|---:|---:|
| Strict successes / 960 | 560 | 571 |
| Mean success | 0.5833 | 0.5948 |
| Empirically unresolved states | 23 / 40 | 24 / 40 |
| One distinct sampled reply block | 5 / 40 | 0 / 40 |

All five q sample-collapse cases follow an explicit transfer announcement. With
the native terminal protocol enforced, both families have zero success and zero
sensitivity there. q_prime uses varied wording around the same terminal token;
distinct text blocks do not imply distinct effective actions. Thus these cases
do not demonstrate hidden recoverable sensitivity under faithful broadening.

The mean task-cluster sensitivity contrast is +0.01149, with a 1,000-replicate
task-cluster bootstrap 95% interval [-0.00309, 0.02705]. This batch does not
establish that broadened sensitivity is larger on average. The open union has
33 states, and Sol succeeds at least once in 29 states. Five states have an
observed floor in both families; six have an observed ceiling in both.

Open-union cross-fit concentration estimates are 0.7321 and 0.3926. Bootstrap
intervals are [-0.4375, 4.75] and [0.05948, 0.79518]; the first fold has only
815/1,000 valid positive-denominator replicates. Concentration is unstable at
this replication level. Preserve the raw estimates rather than claiming that
most sensitivity is confined to the top ten percent of states.

The faithful exploratory bank has 66 harmful and 62 beneficial reply blocks with
observed absolute shifts of at least 0.25 relative to the sampled native mean.
These are selected candidates, not independently confirmed causal effects.
The next locator comparison should distinguish mandated protocol termination
from collapse over genuinely available partner choices, while retaining the
terminal-state counts in the descriptive report.

Artifacts: `summary.json`, `report.md`, `uncertainty.json`, `audit.json`,
`candidate_bank.json`, and `paired_sensitivity.png` / `.pdf` in the default run.
