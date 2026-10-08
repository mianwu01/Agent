# Prompt B execution

All model calls use `openai/gpt-5.6-luna`, AutoDL, temperature 1.0,
reasoning none. Strong-agent execution is disabled until separately invoked.
No `src/tau2` changes. Reading outputs contain recorded outcomes, not failure labels.

## Pre-launch estimate and concurrency

`b1-estimate.md` / `.json`: 1,368 fresh runs, 129.75M tokens, 12.70 hours at
concurrency 3, extrapolated separately by mode from the 60-run pilot.
The throughput probe (`probe_concurrency.py`, `concurrency.json`) tested two
waves at 6, 12, 24, 48, and 64 requests, each with a roughly 4,000-token input.
48 completed 96/96; 64 completed 124/128 (four SSL errors). B1/B2 use 48,
the highest tested reliable level. Ideal runtime scaling from concurrency 3
is 0.79 hours; this is not a guarantee because response latency and workload
change with concurrency. Probes have no retries; native simulation retries
remain unchanged. Probe requests accepted `seed`, but deterministic sampling
is not established.

## Pipeline

Run from the repository root using `.venv/bin/python pilot/run_b.py`.
It runs B1 default (114×8), B1 solo (114×4), completeness/CSV generation,
B2, then B3. Stage status: `b-status.json`; stage logs: `b-*.log`.
It stops on an error. Do not rerun the whole pipeline over existing results;
use native `run_trial.py --iid --resume` only after inspecting the cause.

B1 files: `runs/iid/{default,no-user}/{results,config,batch_timing}.json`.
`summary.csv` has one row per task, rewards ordered by trial index, and
per-run total and per-role input/output tokens.

## Selection and proposal

Selection uses Python `random.Random(20260928)`, task ID order, and source
order `(trial, id)`. Up to two successful default sources are sampled uniformly,
then up to two eligible message-array indices per source. `selection.json`
saves the selections and eligible lists. No successful sources means no branches.

Eligible turns are nonempty user text without tool calls. The native
`UserSimulator.is_stop()` excludes `###STOP###`, `###TRANSFER###`, and
`###OUT-OF-SCOPE###`.

`proposal_messages()` uses native `UserSimulator.get_init_state()`,
`is_valid_user_history_message()`, and `UserState.flip_roles()`. It then appends
one system message containing the exact requested instruction. Native user tool
schemas remain available, but `tool_choice="none"` requests the JSON proposal.
No evaluation criteria, gold actions, agent policy, ticket, or source outcome
are added. `proposals/` preserves the complete user-visible request and response.
Five distinct candidates with finite probabilities in [0,1] are required;
probabilities are not renormalized. The first minimum wins ties. Invalid output
is retained and raises an error; there is no automatic proposal retry.

## Continuations and accounting

Each arm has two continuations. `branch_id` is `<source_sim_id>:<i>:<arm>:<rep>`.
A deterministic SHA-256-derived seed is sent for each branch. A copied native
Task retains its initialization data/actions and receives only a replacement
`initial_state.message_history`. Native Orchestrator replays with default
strict checking, and the evaluator evaluates the full trajectory against the
original task. The 200-step limit applies to newly executed continuation steps,
as in native prefix initialization. A replacement containing a native stop
signal may terminate immediately; it is retained and evaluated normally.

`prefixes/<branch_id>.json` is the full message list, including the replacement
for vs_tail. `trajectories/` contains full native SimulationRun JSON.
Per-continuation `rows/` are durable checkpoints; `branches.jsonl` is assembled
from them. Exceptions are retained in `errors.json` and fail the stage; no
position is silently discarded. Fix the cause before explicitly rerunning
`run_branch.py`; it reuses completed rows and valid proposal responses.

`cont_*_tokens` contain `{agent, user}` totals for messages after the prefix.
The selected synthetic replacement has no generation usage. Proposal usage is
reported on both vs_tail continuation rows for traceability, but per-arm totals
count raw response usage for each proposal attempt exactly once, including archived invalid calls. Failed provider attempts, if
retried inside tau2/LiteLLM, are not represented by successful-response usage.
For resample, `new_user_message` is the first newly generated user text without
tool calls; it is null if termination occurs without such text.

B3 writes one Markdown per flipped continuation under `reading/`, an index,
and `summary.csv`. `branches` counts unique source/position pairs per arm;
`continuations` counts rows. Flip means reward == 0, exactly as requested.

## Strong agent (not run automatically)

```bash
.venv/bin/python pilot/strong_agent.py pilot/runs/branch/branches.jsonl MODEL_NAME \
  --key-file ../Memory/key/key.txt --concurrency 3
```

Agent defaults to the same AutoDL endpoint and temperature/reasoning settings;
`--api-base` and `--key-env` allow an explicitly chosen other route. User stays
Luna through AutoDL. Only flipped vs_tail rows run; each loads its existing
prefix verbatim and the saved original B1 task. No proposals or selections are
repeated. Outputs: `strong_agent.jsonl`, with trajectories/config/checkpoints
under `strong/<model-hash>/`. Existing `(branch_id, model)` rows are reused.
Unsupported model settings fail visibly instead of silently changing them.

## Validation

`test_branch.py` checks strict replay on selected successful pilot prefixes,
exact equivalence to native user API-visible inputs, exclusion of agent-only
fields, replacement routing, evaluation against the original task, zero suffix
usage for terminal-prefix replay, and malformed candidate rejection. The first
comparison used Pydantic bookkeeping timestamps and was corrected to compare
actual API messages; no replay mismatch was observed.

## Transport recovery during B1

The first sustained batch stalled after 38 completed runs. A `py-spy` thread
snapshot (`iid-stall-stacks.txt`) showed workers queued on tau2's shared
10-connection HTTP pool and active requests waiting on SSL reads. A fresh
single AutoDL request succeeded in 8.18 seconds. The short concurrency probe
had used independent connections and therefore did not expose this bottleneck.
The batch was stopped with tau2's native SIGINT handling (exit 130), preserving
all 38 completed runs. Unfinished attempts may have consumed tokens not present
in completed-result usage; they were not counted as benchmark outcomes.

`transport.py` now sizes the shared HTTP pool to the worker count. B1/B2 and the
strong script use a 120-second per-request timeout; model, temperature, reasoning,
and native retry counts are unchanged. The previous results/config are archived
by `run_trial.py --resume`; transport-only timeout/concurrency changes are allowed
by its resume check. `run_b.py --resume-iid` uses native checkpoints and appends
stage logs. There is no retry loop around stages. B2/B3 still start automatically
after both B1 modes complete and validate. The recorded resumed batch wall time
excludes the interrupted first launch; stage logs preserve that overhead.

## Authorized B2 recovery

The first pass preserved four malformed proposals (three ordinary replies and
one four-candidate list), plus an empty user-response continuation error.
No replay error was observed. The user explicitly authorized one replacement
proposal per affected position, preserving and counting the original call.
`run_branch.py --replace-invalid-once` archives originals under
`proposals/original_invalid/`, uses the identical prompt/settings with a distinct
replacement seed, and durably refuses any third call. Both calls' usage is
reported in affected rows; summary totals sum each raw response once.
Completed rows and valid proposals are reused. Resample continuations run
independently before proposal generation.

Continuations use tau2's native `run_with_retry` with the configured native
retry count/delay. Strict initialization and evaluation are outside that
handler so replay/evaluation bugs surface. Usage from an interrupted or failed
continuation attempt is unavailable in its final trajectory and is excluded
from recorded totals. Error records from prior invocations remain in
`error_history/`.

## Completed outputs

B1: 912 default and 456 no-user runs, 121,509,070 recorded tokens.
B2: 97 sources, 189 selected positions, 756 continuations.
Resample: 378 continuations, 89 flipped (23.545%), 24,359,527 tokens.
vs_tail: 378 continuations, 90 flipped (23.810%), 25,034,110 tokens.
The latter includes 193 proposal calls: 189 initial and four authorized
replacements, including all four invalid responses. No proposal usage is missing.
B2 total: 49,393,637 recorded tokens. Failed/interrupted continuation-attempt
usage remains unavailable and is excluded from recorded totals.

B3: 179 reading files plus [index](runs/branch/reading/index.md);
[arm summary](runs/branch/summary.csv);
[IID summary](runs/iid/summary.csv).
Nine offline tests and Ruff checks pass. `audit_b.py` verifies all planned
continuations, source selection, unchanged prefixes, candidates/minimum choice,
suffix usage, and reading-file coverage; results are in `runs/branch/audit.json`.
Credential scan passed and no tracked repository files changed.
Strong-agent continuations have not been run.
