# Solo constructor fix and comparison with shipped no-user runs

No live model runs have completed. This describes the configuration that will be
used once credentials are available. No `src/tau2` file has been modified.

## Exact mismatch

At the pinned commit, `src/tau2/runner/build.py:build_user()` constructs every text
user with `tools`, `instructions`, `llm`, and `llm_args`. It also adds
`persona_config` for subclasses of `UserSimulator`. `DummyUser` is such a subclass,
so it receives all five keywords. But `DummyUser.__init__(self)` accepts none and
only calls `super().__init__(llm="dummy")`. Consequently native solo construction
raises `TypeError: DummyUser.__init__() got an unexpected keyword argument 'tools'`
before the first model request.

Git history shows the zero-argument constructor was added in `73dc244`
(`fix: allow DummyUser to be instantiated without arguments (#202)`). In the first
public release, DummyUser inherited its parent's argument-accepting constructor.
The current runner's keyword-based construction and the new constructor disagree.

## Fix under pilot only

`solo_compat.py` registers a new name, `pilot_dummy_user`, for `PilotDummyUser`,
a subclass of the native `DummyUser`. It accepts the five builder arguments and
then calls `super().__init__()` without forwarding them. They are unused by a
solo dummy; it neither receives user tools nor makes simulator calls.

The trial driver selects this name only in no-user mode. `tau2_cli.py` registers
the same adapter before invoking the otherwise unchanged native CLI. No built-in
registry entry is overwritten, no exception is caught, and no retry is added.

Core added constructor:

```diff
+class PilotDummyUser(DummyUser):
+    def __init__(
+        self, tools=None, instructions=None, llm=None,
+        llm_args=None, persona_config=None,
+    ):
+        super().__init__()
```

The full added adapter, CLI entry point, and driver are in
[solo-compat.patch](solo-compat.patch). Since all pilot files are new relative to
the pinned repository, that patch shows complete file additions, including the
driver's configuration rather than a hypothetical edit to tau2 source.

`audit_solo.py` verifies that an adapter constructed with nonempty unused kwargs
has exactly the same instance state and initial user state as a direct native
`DummyUser()`. `get_init_state`, `is_stop`, `set_seed`, `generate_next_message`,
and `stop` are the exact same inherited method objects. Actual construction gives
`LLMSoloAgent`, `PilotDummyUser`, and a `TelecomEnvironment` with both environment
and orchestrator solo flags true. See [solo-audit.json](solo-audit.json).

## Are the settings identical to the published no-user run?

**They use the native solo setup at the requested pin, but exact equivalence to
the published generating commit cannot be certified.** Known differences and
verification limits are below.

| Component | Published evidence | Configured pilot |
| --- | --- | --- |
| Agent | Saved implementation `llm_agent_solo` | Same registered implementation; actual class `tau2.agent.llm_agent.LLMSoloAgent` at the newer requested pin |
| User | Saved implementation `dummy_user` | `PilotDummyUser`, registered as `pilot_dummy_user`; only constructor compatibility differs from the pinned native dummy; no user inference |
| Policy selection | Actual per-run policy is absent from shipped simulations | `main_policy_solo.md` + `tech_support_manual.md`, combined by the native environment builder, `policy_type="manual"` |
| Environment | Domain `telecom`; public release's solo builder enabled solo mode and combined agent/user tools | Native `TelecomEnvironment`, default `db.toml` and `user_db.toml`, `solo_mode=True`, both toolkits available to the agent, task-specific initialization, no environment overrides |
| Evaluation / limits | 200 max steps, 10 max consecutive tool errors | Same limits; native runner passes `solo_mode=True` to native evaluator |

Both policy files and both database files are byte-identical between the first
public release `37199f3` and the requested pin; SHA-256 values are in the audit.
The release's telecom environment construction and tool implementations are
unchanged at the pin (task split loading was refactored). All 114 shipped task IDs
match the current base split, and every recorded task field in the shipped
snapshots matches the current task data, including instructions, tickets,
initialization, and evaluation criteria. New optional schema fields are not
claimed to exist in the old serialization.

The shipped results record generating commit
`f125e68a2cdc6161f11a4c611413ea4a0918edac`. This commit is absent from the clone,
and `git fetch origin <commit>` failed with `not our ref`. Public release evidence
therefore corroborates intended configuration but cannot prove that unavailable
commit's exact class source, tool code, database contents, or policy selection.
The current `LLMSoloAgent` also has refactored base classes compared with the first
public release; matching its name does not establish byte-identical code.

### Policy metadata trap

The published no-user `info.environment_info.policy` is **exactly equal to the
current default-mode policy**, not the solo policy. None of its 456 simulations
has a separate `policy` field. Therefore the saved top-level text alone cannot
prove what the published solo agent actually saw.

This is consistent with both the first public release and current native metadata
builder: `get_info()` constructs environment info without forwarding solo mode,
whereas the actual solo orchestrator builder does enable solo mode. The current
runner additionally saves actual runtime policy as `simulations[].policy`.
For our future solo runs, inspect that per-simulation field, not the top-level
environment policy. We have not changed native metadata or policy selection.

[published-policy-vs-current-solo.diff](published-policy-vs-current-solo.diff)
shows the recorded metadata versus actual current solo policy. It is **not proof
of a policy change between the actual published and pilot agents**.

### Other deliberate or unavoidable differences

- Code version: requested `b7ea9074...` versus recorded `f125e68...`.
- Agent model: gpt-oss-20b/OpenRouter or GPT-4.1-mini for the next runs, versus
  published GPT-4.1. Local gpt-oss remains unconfigured.
- Agent temperature: 1.0 versus published 0.0; gpt-oss reasoning effort medium.
- User LLM metadata: GPT-4.1 at 1.0 is configured for consistency with the default
  run, but the solo dummy ignores it and makes **zero user LLM calls**. Its native
  internal `llm` label is `dummy`, not the configured GPT-4.1 label.
- Seed: 0 versus published 300. Native runner derives per-trial seeds.
- Tasks/trials: 10 sampled tasks and 2 solo trials/task, versus all 114 tasks and
  4 trials/task. The default-mode pilot uses 4 trials/task.
- Native runner/orchestrator/evaluator and LiteLLM versions are those at the
  requested pin. No claim of reproducing the historical software environment.
- Pilot automatic review and hallucination-based reruns are disabled. Native
  transport/infrastructure retries remain; the adapter adds none.

## Remaining live execution

The next batch comprises OpenRouter and OpenAI: 120 runs total (60/candidate),
plus the separate smoke/probe checks. As of this audit, neither
`OPENAI_API_KEY` nor `OPENROUTER_API_KEY` is available in the process environment
or the inspected env files. The smoke launch stops at the explicit missing-key
check before any request; it has not produced a simulation. The user needs to
provide the existing env-file path, not paste its credentials. The local vLLM
line remains a template, so no local endpoint has been assumed.
