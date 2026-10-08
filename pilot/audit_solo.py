"""Audit solo construction and evidence available from the shipped results."""

import hashlib
import json
import subprocess
from pathlib import Path

from solo_compat import PilotDummyUser, register_pilot_dummy_user

from tau2.agent.llm_agent import LLMSoloAgent
from tau2.data_model.simulation import TextRunConfig
from tau2.domains.telecom.environment import get_environment
from tau2.runner import build_text_orchestrator, load_tasks
from tau2.user.user_simulator import DummyUser

ROOT = Path(__file__).resolve().parents[1]


def sha(value):
    """Hash bytes or UTF-8 text."""
    return hashlib.sha256(
        value.encode() if isinstance(value, str) else value
    ).hexdigest()


def main():
    """Record runtime settings and comparisons without making LLM calls."""
    source = (
        ROOT
        / "data/tau2/results/final/gpt-4.1-2025-04-14_telecom_no-user_gpt-4.1-2025-04-14_4trials.json"
    )
    published = json.loads(source.read_text())
    name = register_pilot_dummy_user()
    config = TextRunConfig(
        domain="telecom",
        agent="llm_agent_solo",
        user=name,
        llm_agent="gpt-4.1-mini-2025-04-14",
        llm_user="gpt-4.1-2025-04-14",
        llm_args_agent={"temperature": 1.0},
        llm_args_user={"temperature": 1.0},
        seed=0,
        num_trials=2,
        max_steps=200,
        max_errors=10,
        auto_review=False,
        hallucination_retries=0,
    )
    tasks = load_tasks("telecom", "base")
    orchestrator = build_text_orchestrator(config, tasks[0], seed=0)
    assert type(orchestrator.agent) is LLMSoloAgent
    assert orchestrator.solo_mode and orchestrator.environment.solo_mode
    inherited = [
        "get_init_state",
        "is_stop",
        "set_seed",
        "generate_next_message",
        "stop",
    ]
    assert all(getattr(PilotDummyUser, m) is getattr(DummyUser, m) for m in inherited)
    baseline = DummyUser()
    adapter = PilotDummyUser(
        tools=[object()],
        instructions="ignored",
        llm="ignored",
        llm_args={"temperature": 1.0},
        persona_config=None,
    )
    assert vars(adapter) == vars(baseline)
    assert adapter.get_init_state() == baseline.get_init_state()
    files = ["main_policy_solo.md", "tech_support_manual.md", "db.toml", "user_db.toml"]
    file_checks = {}
    for filename in files:
        path = "data/tau2/domains/telecom/" + filename
        historical = subprocess.check_output(
            ["git", "show", "37199f3:" + path], cwd=ROOT
        )
        current = (ROOT / path).read_bytes()
        file_checks[path] = {
            "sha256": sha(current),
            "same_as_first_public_release_37199f3": historical == current,
        }

    # Compare every field actually present in the shipped task snapshot, allowing
    # newer optional schema fields that were absent in the old serialization.
    def same_recorded_fields(old, new):
        if isinstance(old, dict):
            return isinstance(new, dict) and all(
                same_recorded_fields(v, new.get(k)) for k, v in old.items()
            )
        return old == new

    raw = json.loads((ROOT / "data/tau2/domains/telecom/tasks.json").read_text())
    raw = raw["tasks"] if isinstance(raw, dict) else raw
    by_id = {t["id"]: t for t in raw}
    changed = [
        t["id"]
        for t in published["tasks"]
        if not same_recorded_fields(t, by_id[t["id"]])
    ]
    saved_policy = published["info"]["environment_info"]["policy"]
    report = {
        "published_commit": published["info"]["git_commit"],
        "historical_commit_limitation": "Not in clone; git fetch origin <published commit> returned not our ref. First public release comparisons are corroboration, not proof about the unavailable commit.",
        "runtime": {
            "agent_class": type(orchestrator.agent).__name__,
            "user_class": type(orchestrator.user).__name__,
            "registered_agent": config.agent,
            "registered_user": config.user,
            "environment_class": type(orchestrator.environment).__name__,
            "domain": config.domain,
            "policy_type": "manual",
            "environment_solo_mode": orchestrator.environment.solo_mode,
            "orchestrator_solo_mode": orchestrator.solo_mode,
            "agent_tool_names": [t.name for t in orchestrator.agent.tools],
            "policy_sha256": sha(orchestrator.environment.get_policy()),
            "max_steps": config.max_steps,
            "max_errors": config.max_errors,
        },
        "adapter": {
            "same_instance_state_as_native_dummy": True,
            "unchanged_inherited_methods": inherited,
            "dummy_llm": adapter.llm,
        },
        "published_metadata": {
            "agent": published["info"]["agent_info"],
            "user_implementation": published["info"]["user_info"]["implementation"],
            "policy_sha256": sha(saved_policy),
        },
        "published_policy_metadata_matches_current_default": saved_policy
        == get_environment().get_policy(),
        "published_policy_metadata_matches_current_solo": saved_policy
        == orchestrator.environment.get_policy(),
        "published_simulations_with_policy_field": sum(
            "policy" in s for s in published["simulations"]
        ),
        "files": file_checks,
        "base_task_ids_match": {t.id for t in tasks}
        == {t["id"] for t in published["tasks"]},
        "tasks_with_changed_recorded_fields": changed,
        "live_requests_made": 0,
    }
    out = ROOT / "pilot/solo-audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Saved {out}; adapter state/method checks passed; {len(changed)} changed task snapshots"
    )


if __name__ == "__main__":
    main()
