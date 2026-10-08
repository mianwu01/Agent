"""Development contract for validated failures and non-embedding trigger counting."""

import hashlib
import json

VERSION = "g1_validation_development_v1"
OBLIGATIONS = (
    "candidate_semantics",
    "independent_human_adjudication",
    "native_failed_outcome",
    "native_prefix_integrity",
    "information_matched_local_control",
    "prespecified_control_readout",
    "policy_comprehension_alternative",
    "user_execution_audit",
    "simulator_termination_audit",
    "environment_evaluator_audit",
)
PARTNER_EVENTS = {
    "reported_unresolved",
    "ambiguous_report",
    "refused_action",
    "execution_mismatch",
}
STATE_FIELDS = (
    "device.sim_card_status",
    "device.sim_card_missing",
    "device.airplane_mode",
    "device.network_technology_connected",
    "device.network_connection_status",
    "device.network_mode_preference",
    "device.data_enabled",
    "device.roaming_enabled",
    "device.wifi_enabled",
    "device.wifi_calling_enabled",
    "device.data_saver_mode",
    "device.vpn_enabled_setting",
    "device.active_apn_settings.reset_at_reboot",
    "device.app_statuses.messaging.permissions.sms",
    "device.app_statuses.messaging.permissions.storage",
    "surroundings.is_abroad",
    "surroundings.mobile_data_usage_exceeded",
    "surroundings.line_active",
)


def digest(value):
    """Hash canonical scientific identities rather than run UUIDs or embeddings."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def nested(value, path):
    """Require an observed field; absent state is not equivalent to false."""
    for name in path.split("."):
        value = value[name]
    return value


def trigger_key(mechanism, intent, unmet_assertions, user_state, partner_event):
    """Freeze a coarse offline state/intent/partner key, excluding persona and IDs."""
    if not mechanism or intent not in {"mms_issue", "mobile_data_issue"}:
        raise ValueError("Unknown mechanism or intent")
    if partner_event not in PARTNER_EVENTS or not unmet_assertions:
        raise ValueError("Unestablished partner event or unresolved requirements")
    state = {path: nested(user_state, path) for path in STATE_FIELDS}
    state["device.active_apn_settings.mmsc_present"] = bool(
        nested(user_state, "device.active_apn_settings.mmsc_url")
    )
    key = {
        "version": VERSION,
        "mechanism": mechanism,
        "intent": intent,
        "unmet_assertions": sorted(set(unmet_assertions)),
        "user_state_projection": state,
        "partner_event": partner_event,
    }
    return {"fields": key, "sha256": digest(key)}


def instance_key(messages, decision_index, mechanism):
    """Collapse cloned trajectories despite different timestamps, UUIDs and seeds."""
    canonical = [
        {
            "role": m["role"],
            "content": m.get("content"),
            "tool_calls": [
                {"name": t["name"], "arguments": t.get("arguments")}
                for t in m.get("tool_calls") or []
            ],
        }
        for m in messages
    ]
    return digest(
        {
            "version": VERSION,
            "trajectory": canonical,
            "decision_index": decision_index,
            "mechanism": mechanism,
        }
    )


def eligibility(evidence):
    """Fail closed on absent, unresolved or unsupported certificates.

    This enforces required records, not their semantic truth. Evidence is accepted
    only after adjudication and the registered control readout; generating this
    dictionary cannot itself establish a causal failure.
    """
    missing = []
    for name in OBLIGATIONS:
        item = evidence.get(name, {})
        allowed = (
            {"supported"} if name in OBLIGATIONS[:6] else {"excluded", "not_applicable"}
        )
        if name == "environment_evaluator_audit":
            allowed = {"excluded"}
        if item.get("status") not in allowed:
            missing.append(name)
        elif not item.get("artifact") or not item.get("rationale"):
            missing.append(name)
        elif item.get("status") == "not_applicable" and name not in {
            "policy_comprehension_alternative",
            "user_execution_audit",
            "simulator_termination_audit",
        }:
            missing.append(name)
        elif name == "independent_human_adjudication" and (
            item.get("reviewer_type") != "human" or not item.get("reviewer_id")
        ):
            missing.append(name)
    return {
        "countable_validated_instance": not missing,
        "unmet_obligations": missing,
        "limit": "Structural evidence contract; artifact authenticity and semantic/control validity require audit. No automatic mechanism claim.",
    }


def count_verified(records):
    """Count only eligible instances; unknown trigger keys cannot inflate coverage."""
    instances, triggers = set(), set()
    eligible_without_trigger = 0
    for record in records:
        if not eligibility(record["evidence"])["countable_validated_instance"]:
            continue
        if not record.get("instance_key"):
            raise ValueError("Verified record lacks instance identity")
        instances.add(record["instance_key"])
        if record.get("trigger_key"):
            triggers.add(record["trigger_key"])
        else:
            eligible_without_trigger += 1
    return {
        "validated_instances": len(instances),
        "distinct_triggers": len(triggers),
        "eligible_records_without_trigger": eligible_without_trigger,
    }


def protocol():
    """Return explicit claim limits and requirements for subsequent registration."""
    return {
        "version": VERSION,
        "status": "Development evidence/counting contract, not empirically validated G1 passage",
        "obligations": list(OBLIGATIONS),
        "candidate_vs_failure": "Candidate label, reward failure, reminder rescue and No-User success are individually insufficient. Unresolved obligations stay unresolved, never negative labels.",
        "control": "Register local information-matched intervention, active comparator, allocation, repetitions and uncertainty/readout threshold BEFORE new outcomes. Generic/capability global reminders do not exclude policy comprehension. No-User changes information/tools/policy and is contextual only. No private state, task answers or future outcomes in correction generation.",
        "mechanism": "Explicit own-tool denial is an observable C signature, not proof of internal partner belief. Broader delegation omission must have a separately registered card, not retrospective relabeling of frozen C.",
        "dedup": {
            "unit": "mode card x intent x unmet native assertion functions x fixed offline user-state projection x adjudicated visible partner event",
            "state_fields": list(STATE_FIELDS)
            + ["device.active_apn_settings.mmsc_present"],
            "partner_events": sorted(PARTNER_EVENTS),
            "excluded": [
                "UUID",
                "seed",
                "persona alone",
                "account IDs",
                "search novelty embedding",
            ],
            "scope": "Initial trigger schema supports phone C only. A/B/new cards require their own frozen relevant fields. Keys coarsen trigger differences; not an exhaustive mode count.",
        },
        "hidden_state": "Offline replay/audit/grouping only; never supplied to generation or mistaken for agent-visible evidence. Missing fields/events mean no trigger count.",
        "cost": "Log root generation, suffix generation, discarded proposals, failures, judge attempts, replay compute and human time. Preserve unknown usage; no end-to-end cost per failure when costs or verified denominator are missing.",
        "G1": "Independent human/reference reliability, held-out candidate precision/miss uncertainty, competitor checks, and measured validation cost vs random review required. Existing .8/.2/.9 targets are developmental, not automatic gate passage.",
        "G2": "After usable validation, freeze iid/random/adaptive common tasks/model/operator pool/root charging and total generation+judge token budgets, three seeds; randomized execution blocks. No diagnostic capability reminder granted only to a discovery arm.",
    }
