"""
RunSession state machine for autonomous ReachOps executions.

This module manages the complete execution lifecycle with support for:
- Autonomous state transitions
- Page state detection integration  
- Self-repair mechanisms
- Checkpoint persistence
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Import our new modules
from .page_state_detector import PageStateDetector, PageStateInfo
from .repair_policy_engine import RepairPolicyEngine


RUN_SESSION_SCHEMA_VERSION = "reachops.run_session.v1"
AI_USAGE_LEDGER_SCHEMA_VERSION = "reachops.ai_usage_ledger.v1"
RUN_SESSION_STATES = {
    "CREATED",
    "PRECHECK",
    "PROFILE_OPENING",
    "PROFILE_PREFLIGHT",
    "COLLECTING",
    "SCORING",
    "ACTION_PLANNING",
    "EXECUTING",
    "REPAIRING",
    "DEGRADED",
    "BLOCKED",
    "COMPLETED",
}
RUN_SESSION_STATE_ORDER = [
    "CREATED",
    "PRECHECK",
    "PROFILE_OPENING",
    "PROFILE_PREFLIGHT",
    "COLLECTING",
    "SCORING",
    "ACTION_PLANNING",
    "EXECUTING",
    "REPAIRING",
    "DEGRADED",
    "BLOCKED",
    "COMPLETED",
]
RUN_SESSION_STATE_RANK = {state: index for index, state in enumerate(RUN_SESSION_STATE_ORDER)}
TERMINAL_RUN_SESSION_STATES = {"BLOCKED", "DEGRADED", "COMPLETED"}
RUN_SESSION_ALLOWED_TRANSITIONS = {
    "CREATED": {"CREATED", "PRECHECK", "PROFILE_OPENING", "PROFILE_PREFLIGHT", "BLOCKED"},
    "PRECHECK": {"PRECHECK", "PROFILE_OPENING", "PROFILE_PREFLIGHT", "COLLECTING", "BLOCKED", "COMPLETED"},
    "PROFILE_OPENING": {"PROFILE_OPENING", "PROFILE_PREFLIGHT", "COLLECTING", "REPAIRING", "BLOCKED"},
    "PROFILE_PREFLIGHT": {"PROFILE_PREFLIGHT", "COLLECTING", "ACTION_PLANNING", "EXECUTING", "REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"},
    "COLLECTING": {"COLLECTING", "SCORING", "REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"},
    "SCORING": {"SCORING", "ACTION_PLANNING", "REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"},
    "ACTION_PLANNING": {"ACTION_PLANNING", "EXECUTING", "REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"},
    "EXECUTING": {"EXECUTING", "REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"},
    "REPAIRING": {
        "REPAIRING",
        "PROFILE_OPENING",
        "COLLECTING",
        "ACTION_PLANNING",
        "EXECUTING",
        "DEGRADED",
        "BLOCKED",
        "COMPLETED",
    },
    "DEGRADED": {"DEGRADED", "COLLECTING", "BLOCKED", "COMPLETED"},
    "BLOCKED": {"BLOCKED"},
    # Historical terminal truth can be corrected when an older runner wrote
    # completed despite blocked campaign evidence.
    "COMPLETED": {"COMPLETED", "BLOCKED"},
}


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_utc_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _seconds_since(value: str, *, now: datetime | None = None) -> int:
    parsed = _parse_utc_iso(value)
    if parsed is None:
        return 0
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - parsed).total_seconds()))


def run_session_id(plan_id: str, created_at: str | None = None) -> str:
    raw = f"{plan_id or 'plan'}|{created_at or utc_now_iso()}"
    return "run_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def is_allowed_state_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is allowed."""
    return bool(to_state in RUN_SESSION_ALLOWED_TRANSITIONS.get(from_state, set()))
    return target in RUN_SESSION_ALLOWED_TRANSITIONS.get(source, {source, "BLOCKED"})


def normalize_state_machine_contract(payload: dict[str, Any]) -> dict[str, Any]:
    session = payload if isinstance(payload, dict) else {}
    state = str(session.get("state") or "CREATED")
    if state not in RUN_SESSION_STATES:
        state = "CREATED"
    violations = [row for row in list(session.get("state_transition_violations") or []) if isinstance(row, dict)]
    history = [row for row in list(session.get("state_history") or []) if isinstance(row, dict)]
    previous_state = state
    if len(history) >= 2:
        previous_state = str((history[-2] or {}).get("state") or state)
    contract = session.get("state_machine_contract") if isinstance(session.get("state_machine_contract"), dict) else {}
    return {
        "schema_version": "reachops.run_session_state_machine_contract.v1",
        "from_state": str(contract.get("from_state") or previous_state),
        "to_state": str(contract.get("to_state") or state),
        "valid_transition": bool(contract.get("valid_transition", True)) and not violations,
        "violation_count": len(violations),
        "terminal_states": sorted(TERMINAL_RUN_SESSION_STATES),
        "no_ai_token_used": True,
    }


def build_ai_usage_ledger(execution_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = execution_plan if isinstance(execution_plan, dict) else {}
    risk_policy = plan.get("risk_policy") if isinstance(plan.get("risk_policy"), dict) else {}
    runtime_contract = plan.get("runtime_contract") if isinstance(plan.get("runtime_contract"), dict) else {}
    no_ai_during_execution = bool(risk_policy.get("no_ai_token_during_execution", True))
    if runtime_contract:
        no_ai_during_execution = bool(no_ai_during_execution and runtime_contract.get("no_ai_token_during_execution") is True)
    execution_ai_allowed = bool(runtime_contract.get("execution_phase_ai_calls_allowed", False))
    return {
        "schema_version": AI_USAGE_LEDGER_SCHEMA_VERSION,
        "policy": {
            "no_ai_token_during_execution": no_ai_during_execution,
            "execution_phase_ai_calls_allowed": execution_ai_allowed,
            "execution_runtime_contract_schema": str(
                runtime_contract.get("schema_version") or "reachops.execution_runtime_contract.v1"
            ),
            "executor": str(runtime_contract.get("executor") or "local_program"),
            "ai_console_is_execution_dependency": bool(runtime_contract.get("ai_console_is_execution_dependency", False)),
            "allowed_ai_windows": [
                "plan_generation_before_start",
                "post_run_recap",
                "operator_requested_unknown_state_analysis",
            ],
        },
        "execution_phase": {
            "ai_call_count": 0,
            "token_estimate": 0,
            "last_call_at": "",
            "last_call_reason": "",
        },
        "operator_console": {
            "local_rule_call_count": 0,
            "ai_call_count": 0,
            "token_estimate": 0,
        },
        "violations": [],
        "audit_status": "pass" if no_ai_during_execution else "policy_not_required",
        "no_ai_token_during_execution": no_ai_during_execution,
        "no_ai_token_used": True,
    }


def normalize_ai_usage_ledger(value: Any, execution_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = build_ai_usage_ledger(execution_plan)
    if isinstance(value, dict):
        ledger.update(value)
        policy = dict(ledger.get("policy") or {})
        policy.setdefault("no_ai_token_during_execution", True)
        policy.setdefault("execution_phase_ai_calls_allowed", False)
        if not policy.get("execution_runtime_contract_schema"):
            policy["execution_runtime_contract_schema"] = "reachops.execution_runtime_contract.v1"
        if not policy.get("executor"):
            policy["executor"] = "local_program"
        policy.setdefault("ai_console_is_execution_dependency", False)
        policy.setdefault(
            "allowed_ai_windows",
            [
                "plan_generation_before_start",
                "post_run_recap",
                "operator_requested_unknown_state_analysis",
            ],
        )
        execution_phase = dict(ledger.get("execution_phase") or {})
        execution_phase.setdefault("ai_call_count", 0)
        execution_phase.setdefault("token_estimate", 0)
        execution_phase.setdefault("last_call_at", "")
        execution_phase.setdefault("last_call_reason", "")
        operator_console = dict(ledger.get("operator_console") or {})
        operator_console.setdefault("local_rule_call_count", 0)
        operator_console.setdefault("ai_call_count", 0)
        operator_console.setdefault("token_estimate", 0)
        ledger["policy"] = policy
        ledger["execution_phase"] = execution_phase
        ledger["operator_console"] = operator_console
    ai_call_count = int((ledger.get("execution_phase") or {}).get("ai_call_count") or 0)
    token_estimate = int((ledger.get("execution_phase") or {}).get("token_estimate") or 0)
    violations = list(ledger.get("violations") or [])
    if bool((ledger.get("policy") or {}).get("no_ai_token_during_execution", True)) and (ai_call_count > 0 or token_estimate > 0):
        violations.append("execution_phase_ai_token_used")
    ledger["violations"] = list(dict.fromkeys(str(item) for item in violations if str(item)))
    ledger["audit_status"] = "fail" if ledger["violations"] else "pass"
    ledger["no_ai_token_during_execution"] = bool((ledger.get("policy") or {}).get("no_ai_token_during_execution", True))
    ledger["no_ai_token_used"] = ai_call_count == 0 and token_estimate == 0 and not ledger["violations"]
    ledger["schema_version"] = AI_USAGE_LEDGER_SCHEMA_VERSION
    return ledger


def execution_runtime_contract_from_plan(execution_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = execution_plan if isinstance(execution_plan, dict) else {}
    contract = plan.get("runtime_contract") if isinstance(plan.get("runtime_contract"), dict) else {}
    if not contract:
        risk_policy = plan.get("risk_policy") if isinstance(plan.get("risk_policy"), dict) else {}
        contract = {
            "schema_version": "reachops.execution_runtime_contract.v1",
            "executor": "local_program",
            "control_surface": "local_client_console",
            "ai_console_is_execution_dependency": False,
            "no_ai_token_during_execution": bool(risk_policy.get("no_ai_token_during_execution", True)),
            "execution_phase_ai_calls_allowed": False,
            "no_submit_without_authorization": True,
            "requires_human_authorization_for_live_actions": bool(
                risk_policy.get("require_human_authorization_for_live_actions", plan.get("mode") == "live_comment")
            ),
            "never_bypass_login_or_captcha": bool(risk_policy.get("never_bypass_login_or_captcha", True)),
            "run_session_required": True,
            "checkpoint_required": True,
            "page_state_evidence_required": True,
            "repair_policy_required": True,
            "risk_gate_required": True,
            "evidence_bundle_required": True,
        }
    return dict(contract)


def build_session_health(
    session: dict[str, Any],
    *,
    running: bool | None = None,
    stale_after_seconds: int = 120,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(session, dict) or not session:
        return {
            "schema_version": "reachops.run_session_health.v1",
            "status": "missing",
            "stale": False,
            "terminal": False,
            "paused": False,
            "running": bool(running),
            "no_ai_token_used": True,
        }
    state = str(session.get("state") or "CREATED")
    checkpoint = session.get("checkpoint") if isinstance(session.get("checkpoint"), dict) else {}
    control = session.get("control") if isinstance(session.get("control"), dict) else {}
    updated_at = str(session.get("updated_at") or checkpoint.get("updated_at") or session.get("created_at") or "")
    age = _seconds_since(updated_at, now=now)
    terminal = state in TERMINAL_RUN_SESSION_STATES
    paused = bool(control.get("current_paused") or control.get("paused"))
    running_value = bool(running) if running is not None else (not terminal and not paused)
    stale = bool(not terminal and not paused and age > max(0, int(stale_after_seconds or 0)))
    if terminal:
        status = "terminal"
    elif paused:
        status = "paused"
    elif stale:
        status = "stale"
    elif running_value:
        status = "healthy"
    else:
        status = "idle"
    return {
        "schema_version": "reachops.run_session_health.v1",
        "status": status,
        "state": state,
        "stale": stale,
        "terminal": terminal,
        "paused": paused,
        "running": running_value,
        "updated_at": updated_at,
        "age_seconds": age,
        "stale_after_seconds": max(0, int(stale_after_seconds or 0)),
        "last_stage": str(checkpoint.get("last_stage") or ""),
        "runtime_state_inferred": str(checkpoint.get("runtime_state_inferred") or ""),
        "log_line_count": int(checkpoint.get("log_line_count") or 0),
        "pid": int(session.get("pid") or 0),
        "no_ai_token_used": True,
    }


@dataclass
class RunSession:
    plan_id: str
    execution_plan_path: str = ""
    state: str = "CREATED"
    status: str = "created"
    session_id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    completed_at: str = ""
    pid: int = 0
    checkpoint: dict[str, Any] = field(default_factory=dict)
    state_history: list[dict[str, Any]] = field(default_factory=list)
    control: dict[str, Any] = field(default_factory=dict)
    control_history: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    ai_usage_ledger: dict[str, Any] = field(default_factory=build_ai_usage_ledger)
    execution_runtime_contract: dict[str, Any] = field(default_factory=dict)
    state_machine_contract: dict[str, Any] = field(default_factory=dict)
    state_transition_violations: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = RUN_SESSION_SCHEMA_VERSION
    no_ai_token_during_execution: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        state = str(payload.get("state") or "CREATED")
        payload["state"] = state if state in RUN_SESSION_STATES else "CREATED"
        payload["session_id"] = payload.get("session_id") or run_session_id(
            str(payload.get("plan_id") or ""), str(payload.get("created_at") or "")
        )
        payload["status"] = state_to_status(payload["state"])
        payload["checkpoint"] = dict(payload.get("checkpoint") or {})
        payload["state_history"] = list(payload.get("state_history") or [])
        if not payload["state_history"]:
            payload["state_history"].append(
                {
                    "at": payload.get("created_at") or utc_now_iso(),
                    "state": payload["state"],
                    "status": payload["status"],
                    "last_stage": str(payload.get("checkpoint", {}).get("last_stage") or "RunSession created")[:500],
                    "source": "run_session",
                    "no_ai_token_used": True,
                }
            )
        payload["control"] = dict(payload.get("control") or {})
        payload["control_history"] = list(payload.get("control_history") or [])
        payload["result"] = dict(payload.get("result") or {})
        payload["evidence"] = dict(payload.get("evidence") or {})
        payload["execution_runtime_contract"] = dict(payload.get("execution_runtime_contract") or {})
        payload["state_transition_violations"] = [
            row for row in list(payload.get("state_transition_violations") or []) if isinstance(row, dict)
        ]
        payload["state_machine_contract"] = normalize_state_machine_contract(payload)
        payload["ai_usage_ledger"] = normalize_ai_usage_ledger(payload.get("ai_usage_ledger"))
        payload["no_ai_token_during_execution"] = bool(payload["ai_usage_ledger"].get("no_ai_token_during_execution", True))
        payload["session_health"] = build_session_health(payload)
        return payload


def state_to_status(state: str) -> str:
    if state == "COMPLETED":
        return "completed"
    if state == "BLOCKED":
        return "blocked"
    if state == "DEGRADED":
        return "degraded"
    if state == "CREATED":
        return "created"
    return "running"


def create_run_session(
    execution_plan: dict[str, Any],
    *,
    execution_plan_path: str = "",
    result_path: str = "",
    log_path: str = "",
    log_offset: int = 0,
) -> dict[str, Any]:
    plan_id = str((execution_plan or {}).get("plan_id") or "")
    created_at = utc_now_iso()
    session = RunSession(
        plan_id=plan_id,
        execution_plan_path=str(execution_plan_path or ""),
        created_at=created_at,
        session_id=run_session_id(plan_id, created_at),
        checkpoint={
            "state": "CREATED",
            "last_stage": "RunSession created",
            "log_offset": int(log_offset or 0),
            "log_path": str(log_path or ""),
            "result_path": str(result_path or ""),
        },
        evidence={
            "execution_plan_path": str(execution_plan_path or ""),
            "log_path": str(log_path or ""),
            "result_path": str(result_path or ""),
            "execution_runtime_contract": execution_runtime_contract_from_plan(execution_plan),
        },
        ai_usage_ledger=build_ai_usage_ledger(execution_plan),
        execution_runtime_contract=execution_runtime_contract_from_plan(execution_plan),
    )
    return session.to_dict()


def transition_run_session(
    session: dict[str, Any],
    state: str,
    *,
    pid: int | None = None,
    last_stage: str = "",
    checkpoint_update: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    control: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(session or {})
    next_state = state if state in RUN_SESSION_STATES else "BLOCKED"
    previous_state = str(payload.get("state") or "CREATED")
    if previous_state not in RUN_SESSION_STATES:
        previous_state = "CREATED"
    history = [row for row in list(payload.get("state_history") or []) if isinstance(row, dict)]
    history_state = str((history[-1] or {}).get("state") or "") if history else ""
    if history_state in RUN_SESSION_STATES and RUN_SESSION_STATE_RANK.get(history_state, 0) > RUN_SESSION_STATE_RANK.get(previous_state, 0):
        previous_state = history_state
    valid_transition = is_allowed_state_transition(previous_state, next_state)
    payload["state"] = next_state
    payload["status"] = state_to_status(next_state)
    payload["updated_at"] = utc_now_iso()
    if next_state != "CREATED" and not payload.get("started_at"):
        payload["started_at"] = payload["updated_at"]
    if next_state in TERMINAL_RUN_SESSION_STATES and not payload.get("completed_at"):
        payload["completed_at"] = payload["updated_at"]
    if pid is not None:
        payload["pid"] = int(pid or 0)
    checkpoint = dict(payload.get("checkpoint") or {})
    checkpoint["state"] = next_state
    if last_stage:
        checkpoint["last_stage"] = str(last_stage)[:500]
    if checkpoint_update is not None:
        checkpoint.update(dict(checkpoint_update or {}))
    payload["checkpoint"] = checkpoint
    last_event = history[-1] if history else {}
    last_recorded_state = str(last_event.get("state") or "") if last_event else ""
    next_last_stage = str(last_stage or checkpoint.get("last_stage") or "")[:500]
    next_runtime_state = str(checkpoint.get("runtime_state_inferred") or "")
    next_log_line_count = int(checkpoint.get("log_line_count") or 0)
    history_changed = bool(
        next_state != last_recorded_state
        or next_last_stage != str(last_event.get("last_stage") or "")
        or next_runtime_state != str(last_event.get("runtime_state_inferred") or "")
        or next_log_line_count != int(last_event.get("log_line_count") or 0)
    )
    if history_changed:
        transition_event = {
            "at": payload["updated_at"],
            "state": next_state,
            "from_state": previous_state,
            "to_state": next_state,
            "valid_transition": valid_transition,
            "status": payload["status"],
            "last_stage": next_last_stage,
            "runtime_state_inferred": next_runtime_state,
            "log_line_count": next_log_line_count,
            "terminal_seen": bool(checkpoint.get("terminal_seen", False)),
            "source": "run_session.transition",
            "no_ai_token_used": True,
        }
        if not valid_transition:
            transition_event["violation"] = "invalid_state_transition"
            transition_event["violation_detail"] = f"{previous_state}->{next_state}"
        history.append(transition_event)
    payload["state_history"] = history[-160:]
    violations = [row for row in list(payload.get("state_transition_violations") or []) if isinstance(row, dict)]
    if not valid_transition:
        violations.append(
            {
                "at": payload["updated_at"],
                "from_state": previous_state,
                "to_state": next_state,
                "reason": "invalid_state_transition",
                "last_stage": next_last_stage,
                "no_ai_token_used": True,
            }
        )
    payload["state_transition_violations"] = violations[-40:]
    payload["state_machine_contract"] = {
        "schema_version": "reachops.run_session_state_machine_contract.v1",
        "from_state": previous_state,
        "to_state": next_state,
        "valid_transition": valid_transition,
        "violation_count": len(payload["state_transition_violations"]),
        "terminal_states": sorted(TERMINAL_RUN_SESSION_STATES),
        "no_ai_token_used": True,
    }
    if result is not None:
        payload["result"] = dict(result or {})
        execution_plan_contract = payload["result"].get("execution_plan_contract")
        if isinstance(execution_plan_contract, dict):
            merged_evidence = dict(payload.get("evidence") or {})
            merged_evidence["execution_plan_contract"] = dict(execution_plan_contract)
            payload["evidence"] = merged_evidence
    if control is not None:
        merged = dict(payload.get("control") or {})
        control_update = dict(control or {})
        merged.update(control_update)
        if "paused" in control_update:
            merged["current_paused"] = bool(control_update.get("paused"))
        else:
            merged.setdefault("current_paused", bool(merged.get("paused", False)))
        payload["control"] = merged
        action = str(control_update.get("last_action") or "").strip()
        if action:
            event = {
                "at": payload["updated_at"],
                "action": action,
                "state": next_state,
                "status": str(control_update.get("status") or payload.get("status") or ""),
                "paused": bool(control_update.get("paused", merged.get("paused", False))),
                "pid": int(payload.get("pid") or 0),
                "reason": str(control_update.get("reason") or ""),
                "ok": bool(control_update.get("ok", True)),
                "no_ai_token_used": True,
            }
            history = list(payload.get("control_history") or [])
            history.append(event)
            payload["control_history"] = history[-80:]
    if evidence is not None:
        merged_evidence = dict(payload.get("evidence") or {})
        merged_evidence.update(dict(evidence or {}))
        payload["evidence"] = merged_evidence
    payload["ai_usage_ledger"] = normalize_ai_usage_ledger(payload.get("ai_usage_ledger"))
    if not isinstance(payload.get("execution_runtime_contract"), dict) or not payload.get("execution_runtime_contract"):
        evidence_payload = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        if isinstance(evidence_payload.get("execution_runtime_contract"), dict):
            payload["execution_runtime_contract"] = dict(evidence_payload.get("execution_runtime_contract") or {})
    if not isinstance(payload.get("execution_runtime_contract"), dict) or not payload.get("execution_runtime_contract"):
        payload["execution_runtime_contract"] = execution_runtime_contract_from_plan()
    payload["state_transition_violations"] = [
        row for row in list(payload.get("state_transition_violations") or []) if isinstance(row, dict)
    ]
    payload["state_machine_contract"] = normalize_state_machine_contract(payload)
    payload["schema_version"] = RUN_SESSION_SCHEMA_VERSION
    payload["no_ai_token_during_execution"] = bool(payload["ai_usage_ledger"].get("no_ai_token_during_execution", True))
    payload["session_health"] = build_session_health(payload)
    return payload


def infer_run_state(lines: list[str], running: bool, run_result: dict[str, Any] | None = None) -> str:
    result_status = str((run_result or {}).get("status") or "")
    if result_status == "completed":
        return "COMPLETED"
    if result_status in {"blocked", "launch_failed", "headless_exited_immediately", "timeout_finalized"}:
        return "BLOCKED"
    joined = "\n".join(lines[-80:])
    if "BLOCK  campaign failed" in joined or "BLOCK  campaign not_started" in joined:
        return "BLOCKED"
    if "action_submit" in joined or "action_preflight" in joined or "TOUCH  run_completed" in joined:
        return "EXECUTING"
    if "action_queue_created" in joined or "ACTION " in joined or "outreach_execution" in joined:
        return "ACTION_PLANNING"
    if "SCORE " in joined or "candidate_user_scored" in joined or "operation_lead_created" in joined:
        return "SCORING"
    if "comments_collected" in joined or "video_discovered" in joined or "COLLECT " in joined:
        return "COLLECTING"
    joined_lower = joined.lower()
    explicit_repair_seen = any(
        marker in joined_lower
        for marker in (
            " repair_decision",
            " repair_audit",
            " repair_step",
            " repair_policy",
            " profile_start_failed_retry",
            "web_ui_account_gate_blocked",
            "web_ui_account_repair",
            "账号修复",
        )
    )
    if explicit_repair_seen:
        return "REPAIRING"
    if "profile_preflight" in joined:
        return "PROFILE_PREFLIGHT"
    if "open_profile" in joined or "profile" in joined.lower():
        return "PROFILE_OPENING"
    if running:
        return "PRECHECK"
    return "CREATED"


def write_run_session(session: dict[str, Any], path: str | Path, latest_path: str | Path | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(session or {})
    payload["schema_version"] = RUN_SESSION_SCHEMA_VERSION
    payload["ai_usage_ledger"] = normalize_ai_usage_ledger(payload.get("ai_usage_ledger"))
    if not isinstance(payload.get("execution_runtime_contract"), dict) or not payload.get("execution_runtime_contract"):
        evidence_payload = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        payload["execution_runtime_contract"] = dict(
            evidence_payload.get("execution_runtime_contract") or execution_runtime_contract_from_plan()
        )
    payload["state_transition_violations"] = [
        row for row in list(payload.get("state_transition_violations") or []) if isinstance(row, dict)
    ]
    payload["state_machine_contract"] = normalize_state_machine_contract(payload)
    if isinstance(payload.get("execution_runtime_contract"), dict) and payload.get("execution_runtime_contract"):
        evidence = dict(payload.get("evidence") or {})
        evidence.setdefault("execution_runtime_contract", dict(payload["execution_runtime_contract"]))
        payload["evidence"] = evidence
    payload["no_ai_token_during_execution"] = bool(payload["ai_usage_ledger"].get("no_ai_token_during_execution", True))
    payload["session_health"] = build_session_health(payload)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if latest_path:
        latest = Path(latest_path)
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_run_session(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        payload["ai_usage_ledger"] = normalize_ai_usage_ledger(payload.get("ai_usage_ledger"))
        if not isinstance(payload.get("execution_runtime_contract"), dict) or not payload.get("execution_runtime_contract"):
            evidence_payload = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
            if isinstance(evidence_payload.get("execution_runtime_contract"), dict):
                payload["execution_runtime_contract"] = dict(evidence_payload.get("execution_runtime_contract") or {})
        if not isinstance(payload.get("execution_runtime_contract"), dict) or not payload.get("execution_runtime_contract"):
            payload["execution_runtime_contract"] = execution_runtime_contract_from_plan()
        payload["state_transition_violations"] = [
            row for row in list(payload.get("state_transition_violations") or []) if isinstance(row, dict)
        ]
        payload["state_machine_contract"] = normalize_state_machine_contract(payload)
        payload["no_ai_token_during_execution"] = bool(payload["ai_usage_ledger"].get("no_ai_token_during_execution", True))
        payload["state_history"] = [row for row in list(payload.get("state_history") or []) if isinstance(row, dict)]
        if not payload["state_history"]:
            payload["state_history"].append(
                {
                    "at": payload.get("created_at") or utc_now_iso(),
                    "state": str(payload.get("state") or "CREATED"),
                    "status": str(payload.get("status") or state_to_status(str(payload.get("state") or "CREATED"))),
                    "last_stage": str((payload.get("checkpoint") or {}).get("last_stage") or "RunSession loaded")[:500],
                    "source": "run_session.read",
                    "no_ai_token_used": True,
                }
            )
        payload["session_health"] = build_session_health(payload)
        return payload
    except Exception:
        return {}
