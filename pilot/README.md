# Telecom pilot

Pinned repository: `sierra-research/tau2-bench`, commit
`b7ea9074c1cba482b30687fecdb5c8425fd6f619` (detached HEAD).
All added code and outputs are under `pilot/`. No `src/tau2` edits.

See [solo-comparison.md](solo-comparison.md) for the exact constructor mismatch,
the [pilot-only diff](solo-compat.patch), and the evidence/limits of comparison
with the shipped no-user runs. In particular, their top-level policy metadata
contains default-mode policy and does not establish the actual solo policy used.

## Current status

- Prompt B is complete: 1,368 IID runs, 756 continuations, and 179 reading files. See [PROMPT_B.md](PROMPT_B.md) for B1/B2/B3 commands,
  selection/replay details, token accounting, the transport recovery, and the
  separate strong-agent script. Live stage status is in `b-status.json`.

- Luna pilot authorized on 2026-09-28: `openai/gpt-5.6-luna` through AutoDL
  for both agent and user simulator, temperature 1.0 and explicit
  `reasoning_effort="none"` for both roles. This replaces the unavailable GPT-4.1
  user for this candidate only, so it is a separate comparison condition.
  The live structured-tool-call and tool-result round-trip probe passed with
  provider token usage on both responses. A separate default-mode smoke run completed
  in 35.64 seconds with 16 messages, reward 0, and no missing generated-message usage.
  The 60-run Luna trial is complete: default 14/40 (35%), solo 12/20 (60%),
  with zero infrastructure failures and complete provider usage. Two tasks have
  mixed outcomes across default trials; none do across solo trials. Full metrics:
  [summary.md](runs/trial/summary.md), with CSV and JSON alongside it.
  [audit.json](runs/trial/luna/audit.json) records token totals and returned model IDs. One probe response identified its model
  as `gpt-5.6-luna-2026-07-09`, the other as `gpt-5.6-luna`; raw responses are saved.
  LiteLLM's bundled price map does not recognize the snapshot and can record zero
  estimated cost. That field is not a verified AutoDL charge; use token usage.
- A1 complete: [reading index](reading/index.md), 30 S tasks and 15 R tasks;
  [notes.csv](reading/notes.csv) contains only task/simulation IDs, with annotation
  fields blank. No failure classification or interpretation has been performed.
- Installed with `uv sync --python 3.12`; `tau2 check-data` passes after the
  dependency fix below.
- [sample.json](sample.json) fixes the seed-0 sample of 10 base tasks. Native-runner
  tooling and [comparison table](runs/trial/summary.md) are prepared.
- Original-model smoke and 180 candidate runs are pending actual local vLLM connection
  details and OpenAI/OpenRouter credentials. The provided local host, port, and
  served name were placeholders. No model measurements have been fabricated.
- The available `Memory/.tmp/aiaaa.env` endpoint returned HTTP 403 for `/models`;
  `Memory/.tmp/tokenrhythm_20260915.env` returned HTTP 200 but listed neither
  GPT-4.1 nor gpt-oss. Those routes have not been substituted for the requested
  OpenAI/OpenRouter references.
- Resumed on 2026-09-28 with working shell, writes, and network access. AutoDL
  `https://www.autodl.art/api/v1/models` returned HTTP 200 for all four tokens in
  the supplied external key file. All four model lists omit the planned models.
  Direct chat requests using the first token returned HTTP 503, “模型不存在或已被删除”
  (model does not exist or has been deleted), for `gpt-4.1-mini`,
  `gpt-4.1-mini-2025-04-14`, `gpt-4.1-2025-04-14`, and `gpt-oss-20b`.
  This is now a model-availability blocker, not a sandbox or credential-loading
  blocker. No smoke simulation or trial could be launched with those original models.
  No alternate model has been substituted; agent and user replacements require
  an explicit model choice to preserve the intended comparison.
  The sanitized responses are in
  [autodl-availability.json](runs/trial/probes/autodl-availability.json).
  Reproduce the check (no retries, no credentials written to outputs) with:

  ```bash
  .venv/bin/python pilot/probe_autodl.py --key-file ../Memory/key/key.txt
  ```

## Setup and encountered issues

Run from the repository root:

```bash
uv python install 3.12
uv sync --python 3.12
uv pip install --python .venv/bin/python -r pilot/requirements-setup.txt
.venv/bin/tau2 check-data
```

`uv` was initially absent, and the available Python 3 was 3.10.16; this checkout
requires Python >=3.12,<3.14. Installed uv 0.12.19 and Python 3.12.14. The pinned
lock resolves LiteLLM 1.81.11. Core `uv sync` succeeds, but the CLI initially
failed with `ModuleNotFoundError: websockets`: `data_model/simulation.py` imports
the OpenAI voice package, whose `__init__.py` imports its WebSocket provider.
Installing `websockets==17.1` fixes the text CLI without source changes. A plain
subsequent `uv sync` removes this extra package: reinstall the setup requirements,
or use `uv run --no-sync` / `.venv/bin/python` for pilot commands.

The initial Git checkout/status crashed with SIGBUS. `strace` located an unreadable
region of `web/leaderboard/public/blog/audio/clean/task_59.wav` on the workspace
filesystem. Restoring that file byte-for-byte from `git show HEAD:<path>` fixed
Git status and checkout. It is not a repository modification. HEAD already matched
the requested commit at clone time and is now explicitly detached there.

LiteLLM's optional remote price-map fetch hit an SSL EOF and used its bundled
map. Token reporting uses provider usage fields, not inferred token costs.

An offline builder check also found a pinned solo-mode bug: `build_user()` passes
`tools`, `instructions`, `llm`, `llm_args`, and `persona_config` to `DummyUser`,
but its constructor accepts no arguments. [solo_compat.py](solo_compat.py) registers
`pilot_dummy_user`, a subclass that accepts those unused kwargs and calls the
unchanged `DummyUser.__init__()`. No behavior, runner, orchestrator, evaluator,
or source files are replaced. Both the trial driver and [tau2_cli.py](tau2_cli.py)
register this adapter. Results transparently name it in user implementation metadata.

## Reading packs

```bash
.venv/bin/python pilot/render_reading.py
```

Inputs are the two exact `data/tau2/results/final/gpt-4.1-2025-04-14_telecom_...`
files requested. Each has 114 tasks and 456 simulations; the renderer validates
four distinct trial numbers per task and identical task definitions across modes.
[reading/manifest.json](reading/manifest.json) records source SHA-256 hashes,
selection IDs, reference IDs, filenames, and counts.

Means use `reward_info.reward` across all four trials. S selects no-user mean
>=0.75 and default mean <=0.25; R reverses these inequalities. Counts exactly match
30 and 15. “First” is ascending saved `trial`, not completion/file order. Failure
means reward <1; success means reward =1. All reward arrays use that trial order.

Category, persona label, and `|`-separated subtasks are parsed from task IDs. Full
scenario data (including persona instructions) and ticket are preserved. Every
saved message is numbered by zero-based array position and shows its original
`turn_idx`; agent (`assistant`) and user calls include complete names and arguments.
Only tool-result content is cut to 300 source characters, with a separate truncation
notice. Failed env assertions use `met == false`; failed action checks use
`action_match == false`. Reward basis/breakdown are shown since a recorded check
need not contribute to the reward. Reference sequences preserve all tool calls
in conversation order, with names/arguments only.

Re-rendering preserves existing human notes for matching task/simulation pairs.
The filenames use a short task-ID SHA-256 to keep links manageable.

## Exact solo/no-user settings

At this pin, “no-user” is a combination of implementations, not a `--no-user`
CLI flag. The upstream intended pair is `llm_agent_solo` / `dummy_user`, but the
constructor bug above prevents that pair from running unmodified. The working
pilot CLI is the native CLI with the adapter registered:

```bash
.venv/bin/python pilot/tau2_cli.py run --domain telecom --task-split-name base \
  --agent llm_agent_solo --user pilot_dummy_user \
  --agent-llm gpt-4.1-mini-2025-04-14 \
  --agent-llm-args '{"temperature":1.0}' \
  --user-llm gpt-4.1-2025-04-14 --user-llm-args '{"temperature":1.0}' \
  --num-tasks 1 --num-trials 1 --seed 0
```

API (with `pilot/` on the Python import path): call
`solo_compat.register_pilot_dummy_user()`, create
`TextRunConfig(domain="telecom", agent="llm_agent_solo",
user="pilot_dummy_user", llm_agent=..., llm_args_agent={...})`, then
`tau2.runner.run_domain(config)`. Default mode uses `agent="llm_agent"` and
`user="user_simulator"`.

The registry marks `llm_agent_solo` with `solo_mode=True`; the native builder
selects the solo environment/policy, gives the agent both agent and user tools,
and supplies the task ticket. The dummy user makes no LLM calls. The evaluator
receives the same `solo_mode` flag. See `src/tau2/registry.py`,
`src/tau2/runner/build.py`, `src/tau2/agent/llm_agent.py`, and
`src/tau2/runner/simulation.py`.

## Local vLLM through LiteLLM

Use LiteLLM's OpenAI-compatible provider prefix and put `api_base` in the
**agent** LLM args. The `/v1` suffix is required for the usual vLLM server:

```bash
.venv/bin/tau2 run --domain telecom --agent llm_agent --user user_simulator \
  --agent-llm openai/gpt-oss-20b \
  --agent-llm-args '{"api_base":"http://HOST:PORT/v1","api_key":"EMPTY","temperature":1.0,"reasoning_effort":"medium","allowed_openai_params":["reasoning_effort"]}' \
  --user-llm gpt-4.1-2025-04-14 \
  --user-llm-args '{"temperature":1.0,"api_base":"https://api.openai.com/v1"}' \
  --num-tasks 1 --num-trials 1
```

Replace `gpt-oss-20b` with the actual served model ID (as returned by `/v1/models`).
`allowed_openai_params` prevents an unfamiliar served alias from causing LiteLLM
to drop `reasoning_effort`. A standard gpt-oss vLLM launch uses its OpenAI/Harmony
tool parser and reasoning parser, e.g. for versions supporting these flags:

```bash
vllm serve openai/gpt-oss-20b --served-model-name gpt-oss-20b \
  --enable-auto-tool-choice --tool-call-parser openai --reasoning-parser openai
```

The server/version and actual parser configuration are not yet available to
verify. Do not assume textual tool markup is sufficient: tau2 consumes structured
`choices[0].message.tool_calls`, then JSON-decodes the function arguments.
The driver provides a two-request `--probe-only` check through tau2's own
`generate()` and LiteLLM: automatic tool choice must yield the correct structured
name/arguments and the following request must accept the tool result. Run this
on local and OpenRouter before comparing them. Probe responses are saved under
`pilot/runs/trial/probes/`; they are not simulation runs or included in the table.

## Pilot protocol and commands

### Luna via AutoDL

The Luna candidate uses the same saved 10 tasks, 4 default trials and 2 solo
trials per task (60 total), seed 0, native runner/evaluator, and limits below.
Solo mode makes no user LLM calls. Credentials are loaded from the first token
in the external file into `PILOT_AUTODL_API_KEY`; configs contain only the
`os.environ/PILOT_AUTODL_API_KEY` reference. No key rotation or extra retries.

```bash
.venv/bin/python pilot/run_trial.py --candidate luna --autodl-key-file ../Memory/key/key.txt --probe-only
.venv/bin/python pilot/run_trial.py --candidate luna --autodl-key-file ../Memory/key/key.txt --smoke
.venv/bin/python pilot/run_trial.py --candidate luna --autodl-key-file ../Memory/key/key.txt --mode default
.venv/bin/python pilot/run_trial.py --candidate luna --autodl-key-file ../Memory/key/key.txt --mode no-user
.venv/bin/python pilot/summarize_trial.py
```

The smoke output is under `runs/smoke/luna/default/`; trial outputs are under
`runs/trial/luna/{default,no-user}/`. Reading-pack annotations remain untouched.

### Original candidates (pending availability)

Candidates:

1. Local gpt-oss-20b: `openai/<served_name>`, medium reasoning.
2. OpenRouter: `openrouter/openai/gpt-oss-20b`, medium reasoning.
3. OpenAI: `gpt-4.1-mini-2025-04-14`.

User: `gpt-4.1-2025-04-14`. Temperature: **1.0 for both roles**, all modes.
The shipped trajectories used temperature **0.0** and record an older generating
commit (`f125e68a2cdc6161f11a4c611413ea4a0918edac`); these new runs are at the
requested pin and temperature and are not exact reproductions of those runs.

The sample is `random.Random(0).sample(load_tasks("telecom", "base"), 10)` in
the native loader's file order, saved in `sample.json`. Every candidate uses these
same tasks. Native run seed is 0; tau2 derives per-trial seeds itself. Default mode
has four trials/task, solo has two: 60 runs/candidate, 180 total. Max steps 200,
max consecutive tool errors 10, concurrency 3. Native retries are retained;
there is no added retry loop. Automatic conversation review is off and
hallucination-based reruns are disabled; this tooling does not interpret failures.

Use a private external env file with variables shown in [env.example](env.example).
No credentials belong in model configs. The direct OpenAI endpoint is explicit
for the reference agent and user; proxy base-URL environment variables are cleared
by this driver to avoid silently rerouting them.

```bash
.venv/bin/python pilot/run_trial.py --prepare
.venv/bin/python pilot/run_trial.py --env-file /path/to/private.env --candidate local --probe-only
.venv/bin/python pilot/run_trial.py --env-file /path/to/private.env --candidate openrouter --probe-only
.venv/bin/python pilot/run_trial.py --env-file /path/to/private.env --candidate mini --smoke

for candidate in local openrouter mini; do
  for mode in default no-user; do
    .venv/bin/python pilot/run_trial.py --env-file /path/to/private.env \
      --candidate "$candidate" --mode "$mode" || exit
  done
done
.venv/bin/python pilot/summarize_trial.py
```

`--smoke` uses the first sampled task, one default-mode trial, and saves separately
under `pilot/runs/smoke/`. Regular results are native tau2 `Results` JSON at
`pilot/runs/trial/<candidate>/<mode>/results.json`, with full configs and batch
timing alongside them. An absolute `save_to` directs the native runner into these
directories (this pin appends `results.json` to the save directory).

The native runner checkpoints completed simulations and retains exhausted
infrastructure failures as records. The driver validates the expected run count
and rejects any such failures instead of reporting a success aggregate. Exceptions
propagate. Explicit `--resume` invokes tau2's resume; inspect and fix the cause
first. The driver archives previous result/config/timing files under `history/`
before resuming, since tau2 replaces infrastructure-error records. It refuses
changed run settings (apart from the resume flag).

## Token usage and table definitions

Per-message usage is indeed `simulations[].messages[].usage`, with
`prompt_tokens` and `completion_tokens`; `src/tau2/utils/llm_utils.py` copies
these from LiteLLM's response. Separate totals by stored message role:
`assistant` = agent, `user` = simulator. Include each role's messages that request
tools; tool **result** messages do not make additional LLM calls. Static opening
messages may have null usage. `raw_data` also preserves the provider response
in newly generated results. Completion tokens use the provider's aggregate,
without adding reasoning tokens a second time.

The table uses reward =1 as success. “Mixed tasks” counts the union of tasks
with success and failure **within** either mode, not disagreement only across
modes. Per-mode mixed counts are also written to `summary.json`.

Means pool all 60 runs in each complete candidate row (40 default +20 solo).
Message counts include every saved message, including tool results and scripted
greetings. Tokens are summed per run and role, then averaged; solo user totals
are zero. Missing usage on identifiable generated messages is an error, not a
silent zero. Wall time is `SimulationRun.duration` (orchestrator elapsed time),
excluding evaluation, queue time, and failed attempts before a successful retry.
`batch_timing.json` gives total runner time as an additional measurement.

Incomplete, absent, or infrastructure-error batches have explicit status and no
aggregate row metrics. The table is saved as Markdown, CSV, and JSON.

## Offline validation

```bash
.venv/bin/python -m unittest discover -s pilot -p 'test_*.py'
```

These checks cover native default/solo orchestrator construction, sample eligibility,
LiteLLM structured tool-call and result transport against a local HTTP stub,
medium reasoning forwarding for an unfamiliar served alias, token attribution,
mixed-outcome counting, and rejecting infrastructure-error summaries. They are
not live model trials and do not validate the unavailable vLLM parser itself.
The initial probe test found missing explicit `role` fields required by tau2's
message models; those were added before any live probe. Stub model cost warnings
reflect its intentionally unregistered name; provider token usage is still checked.

Validation completed: all three unittest checks pass (`validation.log`), Ruff
lint/format pass, all 45 reading links/message counts and initially blank notes
were audited, and Git reports no tracked-file changes. A scan of pilot artifacts
found none of the credentials inspected during connection discovery. Original-model live smoke, local-server parser verification, and original-model
trial measurements remain pending. Luna smoke and all 60 Luna trials are now
complete; the three offline checks also passed after adding Luna (`validation-luna.log`).
