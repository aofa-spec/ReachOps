# -*- coding: utf-8 -*-
"""Evidence bundle builder for auditable ReachOps runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ReachOps.execution_plan import (
    adversarial_cli_args_for_contract_preview,
    build_autonomous_preflight_forecast,
    build_execution_plan_runtime_contract,
    plan_fingerprint_sha256,
    read_execution_plan,
)
from ReachOps.run_session import normalize_ai_usage_ledger, read_run_session
from ReachOps.run_session import RUN_SESSION_STATE_ORDER, TERMINAL_RUN_SESSION_STATES
from ReachOps.workbench.offline_learning_ledger import summarize_offline_learning
from ReachOps.workbench.repair_policy_engine import build_page_state_repair_coverage


EVIDENCE_BUNDLE_SCHEMA_VERSION = "reachops.evidence_bundle.v1"


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _extract_log_token(line: str, key: str) -> str:
    prefix = f"{key}="
    for part in str(line or "").replace(",", " ").split():
        if part.startswith(prefix):
            return part[len(prefix) :].strip().strip("'\"")
    return ""


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _read_lines(path: str | Path, limit: int = 240) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-max(1, int(limit or 1)) :]


def _sha256(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        with path.open("rb") as fh:
            return hashlib.sha256(fh.read(max_bytes)).hexdigest()
    except Exception:
        return ""


def file_artifact(path_value: Any, kind: str, label: str = "") -> dict[str, Any]:
    path_text = _safe_text(path_value)
    if not path_text:
        return {"kind": kind, "label": label or kind, "path": "", "exists": False}
    path = Path(path_text)
    exists = path.is_file()
    return {
        "kind": kind,
        "label": label or kind,
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "sha256": _sha256(path) if exists else "",
    }


def collect_evidence_artifacts(
    *,
    execution_plan_path: str = "",
    run_session_path: str = "",
    result_path: str = "",
    log_path: str = "",
    offline_learning_path: str = "",
    extra_artifacts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    artifacts = [
        file_artifact(execution_plan_path, "execution_plan", "ExecutionPlan"),
        file_artifact(run_session_path, "run_session", "RunSession"),
        file_artifact(result_path, "run_result", "Run result"),
        file_artifact(log_path, "runtime_log", "Runtime log"),
        file_artifact(offline_learning_path, "offline_learning", "Offline learning ledger"),
    ]
    for row in extra_artifacts or []:
        if isinstance(row, dict):
            artifacts.append(
                file_artifact(row.get("path") or row.get("href"), str(row.get("kind") or "report"), str(row.get("label") or "Report"))
            )
    seen: set[str] = set()
    deduped = []
    for row in artifacts:
        key = f"{row.get('kind')}|{row.get('path')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_timeline(log_lines: list[str], run_session: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    if run_session.get("created_at"):
        timeline.append({"stage": "CREATED", "at": run_session.get("created_at"), "message": "RunSession created", "source": "run_session", "no_ai_token_used": True})
    if run_session.get("started_at"):
        timeline.append({"stage": "STARTED", "at": run_session.get("started_at"), "message": "Execution started", "source": "run_session", "no_ai_token_used": True})
    checkpoint = run_session.get("checkpoint") if isinstance(run_session.get("checkpoint"), dict) else {}
    if checkpoint:
        checkpoint_stage = _safe_text(checkpoint.get("state") or run_session.get("state"), "CHECKPOINT")
        checkpoint_message = _safe_text(
            checkpoint.get("last_log_line")
            or checkpoint.get("last_stage")
            or f"checkpoint state={checkpoint_stage}"
        )
        timeline.append(
            {
                "stage": "CHECKPOINT",
                "at": run_session.get("updated_at", ""),
                "message": checkpoint_message[:500],
                "source": "run_session.checkpoint",
                "state": checkpoint_stage,
                "runtime_state_inferred": _safe_text(checkpoint.get("runtime_state_inferred")),
                "terminal_seen": bool(checkpoint.get("terminal_seen", False)),
                "no_ai_token_used": True,
            }
        )
    for event in run_session.get("control_history") or []:
        if not isinstance(event, dict):
            continue
        action = _safe_text(event.get("action"), "control")
        status = _safe_text(event.get("status"))
        reason = _safe_text(event.get("reason"))
        message = f"control action={action} status={status or '-'} paused={str(bool(event.get('paused'))).lower()}"
        if reason:
            message += f" reason={reason}"
        timeline.append({"stage": "CONTROL", "at": event.get("at", ""), "message": message[:500], "source": "run_session.control_history", "no_ai_token_used": True})
    for event in run_session.get("state_history") or []:
        if not isinstance(event, dict):
            continue
        state = _safe_text(event.get("state"), "CREATED")
        message = f"state={state} status={_safe_text(event.get('status')) or '-'}"
        last_stage = _safe_text(event.get("last_stage"))
        if last_stage:
            message += f" stage={last_stage}"
        timeline.append(
            {
                "stage": "RUN_STATE",
                "at": event.get("at", ""),
                "message": message[:500],
                "source": "run_session.state_history",
                "state": state,
                "runtime_state_inferred": _safe_text(event.get("runtime_state_inferred")),
                "log_line_count": int(event.get("log_line_count") or 0),
                "terminal_seen": bool(event.get("terminal_seen", False)),
                "no_ai_token_used": True,
            }
        )
    for row in _walk_dicts({"run_session": run_session, "result": result}):
        repair_audit = row.get("repair_audit")
        if isinstance(repair_audit, dict):
            timeline.append(
                {
                    "stage": "REPAIR",
                    "at": _safe_text(repair_audit.get("at") or repair_audit.get("created_at")),
                    "message": (
                        f"repair action={_safe_text(repair_audit.get('repair_action')) or '-'} "
                        f"error={_safe_text(repair_audit.get('error_code')) or '-'} "
                        f"profile={_safe_text(repair_audit.get('profile_id')) or '-'}"
                    )[:500],
                    "source": "repair_audit",
                    "action_id": _safe_text(repair_audit.get("action_id")),
                    "profile_id": _safe_text(repair_audit.get("profile_id")),
                    "error_code": _safe_text(repair_audit.get("error_code")),
                    "no_ai_token_used": True,
                }
            )
        risk_gate = row.get("risk_gate")
        if isinstance(risk_gate, dict):
            allowed = bool(risk_gate.get("allowed"))
            timeline.append(
                {
                    "stage": "RISK_GATE",
                    "at": _safe_text(risk_gate.get("at") or risk_gate.get("created_at")),
                    "message": (
                        f"risk_gate {'allowed' if allowed else 'blocked'} "
                        f"reason={_safe_text(risk_gate.get('reason_code')) or '-'} "
                        f"profile={_safe_text(risk_gate.get('profile_id')) or '-'}"
                    )[:500],
                    "source": "risk_gate",
                    "allowed": allowed,
                    "reason_code": _safe_text(risk_gate.get("reason_code")),
                    "profile_id": _safe_text(risk_gate.get("profile_id")),
                    "action_type": _safe_text(risk_gate.get("action_type")),
                    "no_ai_token_used": True,
                }
            )
        page_state = row.get("page_state")
        if isinstance(page_state, dict):
            timeline.append(
                {
                    "stage": "PAGE_STATE",
                    "at": _safe_text(page_state.get("observed_at")),
                    "message": (
                        f"page_state={_safe_text(page_state.get('state')) or 'UNKNOWN_PAGE_STATE'} "
                        f"title={_safe_text(page_state.get('title')) or '-'}"
                    )[:500],
                    "source": "page_state",
                    "state": _safe_text(page_state.get("state"), "UNKNOWN_PAGE_STATE"),
                    "current_url": _safe_text(page_state.get("current_url")),
                    "signals": list(page_state.get("signals") or [])[:12],
                    "no_ai_token_used": True,
                }
            )
        account_health = row.get("account_health")
        if isinstance(account_health, dict):
            status = _safe_text(account_health.get("status"))
            error_code = _safe_text(account_health.get("last_error_code"))
            profile_id = _safe_text(account_health.get("profile_id"))
            message = "account_health event=profile_health_updated"
            if profile_id:
                message += f" profile={profile_id}"
            if status:
                message += f" status={status}"
            if error_code:
                message += f" error={error_code}"
            timeline.append(
                {
                    "stage": "ACCOUNT_HEALTH",
                    "at": _safe_text(account_health.get("updated_at")),
                    "message": message[:500],
                    "source": "account_health",
                    "event": "profile_health_updated",
                    "profile_id": profile_id,
                    "status": status,
                    "error_code": error_code,
                    "reason": _safe_text(account_health.get("last_error_message")),
                    "cooldown": status == "cooldown",
                    "consecutive_failures": int(account_health.get("consecutive_failures") or 0),
                    "no_ai_token_used": True,
                }
            )
    for line in log_lines[-160:]:
        text = str(line)
        if not text.strip():
            continue
        if "profile_health_updated" in text or "profile_forced_cooldown" in text:
            event_name = "profile_forced_cooldown" if "profile_forced_cooldown" in text else "profile_health_updated"
            profile_id = _extract_log_token(text, "profile") or _extract_log_token(text, "profile_id") or _extract_log_token(text, "entity_id")
            status = _extract_log_token(text, "status")
            error_code = _extract_log_token(text, "error_code")
            reason = _extract_log_token(text, "reason") or _extract_log_token(text, "error")
            message = f"account_health event={event_name}"
            if profile_id:
                message += f" profile={profile_id}"
            if status:
                message += f" status={status}"
            if error_code:
                message += f" error={error_code}"
            if reason:
                message += f" reason={reason}"
            timeline.append(
                {
                    "stage": "ACCOUNT_HEALTH",
                    "at": "",
                    "message": message[:500],
                    "source": "runtime_log.account_health",
                    "event": event_name,
                    "profile_id": profile_id,
                    "status": status,
                    "error_code": error_code,
                    "reason": reason,
                    "cooldown": event_name == "profile_forced_cooldown" or status == "cooldown",
                    "no_ai_token_used": True,
                }
            )
            continue
        marker = ""
        for candidate in ("PLAN", "CHECK", "START", "REPAIR", "BLOCK", "DONE", "WARN", "ERROR", "RUN"):
            if f" {candidate} " in text or text.startswith(candidate):
                marker = candidate
                break
        if not marker and "action_router_repair" in text:
            marker = "REPAIR"
        if marker:
            timeline.append({"stage": marker, "at": "", "message": text[:500], "source": "runtime_log", "no_ai_token_used": True})
    status = _safe_text(result.get("status"))
    if status:
        timeline.append({"stage": status.upper(), "at": result.get("generated_at", ""), "message": "Run result finalized", "source": "run_result", "no_ai_token_used": True})
    if run_session.get("completed_at"):
        timeline.append({"stage": run_session.get("state", "COMPLETED"), "at": run_session.get("completed_at"), "message": "RunSession terminal state", "source": "run_session", "no_ai_token_used": True})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in timeline:
        key = "|".join(
            [
                _safe_text(event.get("stage")),
                _safe_text(event.get("source")),
                _safe_text(event.get("at")),
                _safe_text(event.get("message")),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped[-220:]


def build_account_health_summary(log_lines: list[str], run_session: dict[str, Any] | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for row in _walk_dicts({"run_session": run_session or {}, "result": result or {}}):
        account_health = row.get("account_health")
        if not isinstance(account_health, dict):
            continue
        status = _safe_text(account_health.get("status"))
        error_code = _safe_text(account_health.get("last_error_code"))
        failures = int(account_health.get("consecutive_failures") or 0)
        events.append(
            {
                "event": "profile_health_updated",
                "profile_id": _safe_text(account_health.get("profile_id")),
                "status": status,
                "error_code": error_code,
                "reason": _safe_text(account_health.get("last_error_message")),
                "cooldown": status == "cooldown",
                "consecutive_failures": failures,
                "consecutive_failure_cooldown": status == "cooldown" and failures >= 3 and error_code not in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"},
                "source": "account_health",
                "no_ai_token_used": True,
            }
        )
    for line in log_lines[-240:]:
        text = str(line or "")
        if "profile_health_updated" not in text and "profile_forced_cooldown" not in text:
            continue
        event_name = "profile_forced_cooldown" if "profile_forced_cooldown" in text else "profile_health_updated"
        status = _extract_log_token(text, "status")
        error_code = _extract_log_token(text, "error_code")
        reason = _extract_log_token(text, "reason") or _extract_log_token(text, "error")
        profile_id = _extract_log_token(text, "profile") or _extract_log_token(text, "profile_id") or _extract_log_token(text, "entity_id")
        events.append(
            {
                "event": event_name,
                "profile_id": profile_id,
                "status": status,
                "error_code": error_code,
                "reason": reason,
                "cooldown": event_name == "profile_forced_cooldown" or status == "cooldown",
                "consecutive_failure_cooldown": event_name == "profile_forced_cooldown" and error_code not in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"},
                "source": "runtime_log.account_health",
                "no_ai_token_used": True,
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        key = "|".join(
            [
                _safe_text(event.get("source")),
                _safe_text(event.get("event")),
                _safe_text(event.get("profile_id")),
                _safe_text(event.get("status")),
                _safe_text(event.get("error_code")),
                _safe_text(event.get("reason")),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    events = deduped
    return {
        "schema_version": "reachops.account_health_summary.v1",
        "event_count": len(events),
        "cooldown_event_count": len([row for row in events if row.get("cooldown")]),
        "forced_cooldown_count": len([row for row in events if row.get("event") == "profile_forced_cooldown"]),
        "consecutive_failure_cooldown_count": len([row for row in events if row.get("consecutive_failure_cooldown")]),
        "profile_ids": sorted({str(row.get("profile_id") or "") for row in events if row.get("profile_id")}),
        "error_codes": sorted({str(row.get("error_code") or "") for row in events if row.get("error_code")}),
        "events": events[:60],
        "no_ai_token_used": True,
    }


def outcome_summary(plan: dict[str, Any], run_session: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    session_state = _safe_text(run_session.get("state"))
    session_status = _safe_text(run_session.get("status"))
    result_status = _safe_text(result.get("status"))
    if session_state in {"BLOCKED", "DEGRADED"}:
        status = session_status or session_state
    else:
        status = result_status or session_status or session_state or "unknown"
    reason = ""
    if str(status).lower() != "completed":
        reason = _safe_text(result.get("error") or result.get("message") or (run_session.get("result") or {}).get("reason"))
    return {
        "status": status,
        "state": _safe_text(run_session.get("state"), "UNKNOWN"),
        "target": _safe_text(plan.get("target") or result.get("target")),
        "mode": _safe_text(plan.get("mode")),
        "profile_group": _safe_text(plan.get("profile_group") or result.get("profile_group")),
        "completed": status in {"completed", "COMPLETED"},
        "blocked_or_degraded": status not in {"completed", "COMPLETED", ""},
        "reason": reason,
        "recovery": result.get("recovery") if isinstance(result.get("recovery"), dict) else {},
        "no_ai_token_during_execution": bool(
            run_session.get("no_ai_token_during_execution", True)
            and ((plan.get("risk_policy") or {}).get("no_ai_token_during_execution", True))
        ),
    }


def build_plan_runtime_contract_summary(plan: dict[str, Any], run_session: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    evidence = run_session.get("evidence") if isinstance(run_session.get("evidence"), dict) else {}
    contract = evidence.get("execution_plan_contract") if isinstance(evidence.get("execution_plan_contract"), dict) else {}
    if not contract:
        contract = result.get("execution_plan_contract") if isinstance(result.get("execution_plan_contract"), dict) else {}
    if not contract and plan:
        contract = build_execution_plan_runtime_contract(
            plan,
            adversarial_cli_args_for_contract_preview(plan),
            source="execution_plan_audit_preview",
            audit_preview=True,
        )
    result_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
    plan_id = _safe_text(plan.get("plan_id") or run_session.get("plan_id") or result_plan.get("plan_id"))
    contract_plan_id = _safe_text(contract.get("plan_id"))
    plan_fingerprint = _safe_text(plan.get("plan_fingerprint_sha256") or (plan_fingerprint_sha256(plan) if plan else ""))
    contract_plan_fingerprint = _safe_text(contract.get("plan_fingerprint_sha256"))
    runtime_after_fingerprint = _safe_text(contract.get("runtime_after_fingerprint_sha256"))
    return {
        "schema_version": "reachops.plan_runtime_contract_summary.v1",
        "contract_schema_version": _safe_text(contract.get("schema_version")),
        "source": _safe_text(contract.get("source") or ("execution_plan" if contract else "")),
        "audit_preview": bool(contract.get("audit_preview", False)),
        "plan_id": plan_id,
        "contract_plan_id": contract_plan_id,
        "plan_id_matches": bool(plan_id and contract_plan_id and plan_id == contract_plan_id),
        "plan_fingerprint_sha256": plan_fingerprint,
        "contract_plan_fingerprint_sha256": contract_plan_fingerprint,
        "plan_fingerprint_matches": bool(plan_fingerprint and contract_plan_fingerprint and plan_fingerprint == contract_plan_fingerprint),
        "runtime_after_fingerprint_sha256": runtime_after_fingerprint,
        "runtime_after_fingerprint_present": bool(runtime_after_fingerprint),
        "cli_args_ignored_for_plan_fields": bool(contract.get("cli_args_ignored_for_plan_fields", False)),
        "has_before_after_diff": isinstance(contract.get("before"), dict) and isinstance(contract.get("after"), dict),
        "before": contract.get("before") if isinstance(contract.get("before"), dict) else {},
        "after": contract.get("after") if isinstance(contract.get("after"), dict) else {},
        "no_ai_token_used": bool(contract.get("no_ai_token_used", True)),
    }


def build_execution_runtime_contract_summary(plan: dict[str, Any], run_session: dict[str, Any]) -> dict[str, Any]:
    plan_contract = plan.get("runtime_contract") if isinstance(plan.get("runtime_contract"), dict) else {}
    session_contract = run_session.get("execution_runtime_contract") if isinstance(run_session.get("execution_runtime_contract"), dict) else {}
    evidence = run_session.get("evidence") if isinstance(run_session.get("evidence"), dict) else {}
    evidence_contract = evidence.get("execution_runtime_contract") if isinstance(evidence.get("execution_runtime_contract"), dict) else {}
    contract = plan_contract or session_contract or evidence_contract
    policy = ((run_session.get("ai_usage_ledger") or {}).get("policy") or {}) if isinstance(run_session.get("ai_usage_ledger"), dict) else {}
    schema = _safe_text(contract.get("schema_version"))
    executor = _safe_text(contract.get("executor"))
    control_surface = _safe_text(contract.get("control_surface"))
    plan_matches_session = bool(plan_contract and session_contract and plan_contract == session_contract)
    plan_matches_evidence = bool(plan_contract and evidence_contract and plan_contract == evidence_contract)
    return {
        "schema_version": "reachops.execution_runtime_contract_summary.v1",
        "contract_schema_version": schema,
        "present": bool(contract),
        "source": "execution_plan" if plan_contract else "run_session" if session_contract else "run_session.evidence" if evidence_contract else "",
        "executor": executor,
        "control_surface": control_surface,
        "local_program_executor": executor == "local_program",
        "local_client_console_control_surface": control_surface == "local_client_console",
        "ai_console_is_execution_dependency": bool(contract.get("ai_console_is_execution_dependency", True)),
        "ai_console_control_surface_only": contract.get("ai_console_is_execution_dependency") is False,
        "no_ai_token_during_execution": contract.get("no_ai_token_during_execution") is True,
        "execution_phase_ai_calls_allowed": bool(contract.get("execution_phase_ai_calls_allowed", True)),
        "execution_phase_ai_calls_disallowed": contract.get("execution_phase_ai_calls_allowed") is False,
        "no_submit_without_authorization": contract.get("no_submit_without_authorization") is True,
        "never_bypass_login_or_captcha": contract.get("never_bypass_login_or_captcha") is True,
        "run_session_required": contract.get("run_session_required") is True,
        "checkpoint_required": contract.get("checkpoint_required") is True,
        "page_state_evidence_required": contract.get("page_state_evidence_required") is True,
        "repair_policy_required": contract.get("repair_policy_required") is True,
        "risk_gate_required": contract.get("risk_gate_required") is True,
        "evidence_bundle_required": contract.get("evidence_bundle_required") is True,
        "plan_matches_session": plan_matches_session,
        "plan_matches_evidence": plan_matches_evidence,
        "ai_usage_policy_matches_contract": bool(
            policy.get("no_ai_token_during_execution") is contract.get("no_ai_token_during_execution")
            and policy.get("execution_phase_ai_calls_allowed") is contract.get("execution_phase_ai_calls_allowed")
            and _safe_text(policy.get("executor")) == executor
            and policy.get("ai_console_is_execution_dependency") is contract.get("ai_console_is_execution_dependency")
        ),
        "no_ai_token_used": True,
    }


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def collect_page_state_artifacts(run_session: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path_value: Any, kind: str, label: str) -> None:
        path_text = _safe_text(path_value)
        if not path_text:
            return
        key = f"{kind}|{path_text}"
        if key in seen:
            return
        seen.add(key)
        artifacts.append(file_artifact(path_text, kind, label))

    for row in _walk_dicts({"run_session": run_session, "result": result}):
        screenshot = row.get("screenshot") if isinstance(row.get("screenshot"), dict) else {}
        add(screenshot.get("path"), "page_state_screenshot", "Page state screenshot")
        add(row.get("sidecar_path"), "page_state_sidecar", "Page state sidecar")
        if "page_state" in row or "page_state_bundle" in row or "page_diagnostics" in row:
            add(row.get("evidence_path"), "page_state_evidence", "Page state evidence")
    return artifacts


def collect_offline_learning_artifacts(offline_learning: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path_value: Any) -> None:
        path_text = _safe_text(path_value)
        if not path_text or path_text in seen:
            return
        seen.add(path_text)
        artifacts.append(file_artifact(path_text, "offline_learning_evidence", "Offline learning evidence"))

    records = offline_learning.get("records") if isinstance(offline_learning.get("records"), list) else []
    for record in records:
        if isinstance(record, dict):
            for path in record.get("evidence_paths") or []:
                add(path)
    policy_candidates = offline_learning.get("policy_candidates") if isinstance(offline_learning.get("policy_candidates"), dict) else {}
    candidates = policy_candidates.get("candidates") if isinstance(policy_candidates.get("candidates"), list) else []
    for candidate in candidates:
        if isinstance(candidate, dict):
            for path in candidate.get("evidence_paths") or []:
                add(path)
    return artifacts


def account_repair_paths(base_dir: str | Path) -> dict[str, str]:
    root = Path(base_dir)
    report_dir = root / "reports" / "acceptance_remediation"
    return {
        "plan_json": str(report_dir / "latest_account_repair_plan.json"),
        "plan_markdown": str(report_dir / "latest_account_repair_plan.md"),
        "apply_result": str(report_dir / "latest_account_repair_apply.json"),
    }


def collect_account_repair_artifacts(base_dir: str | Path) -> list[dict[str, Any]]:
    paths = account_repair_paths(base_dir)
    artifacts = [
        file_artifact(paths["plan_json"], "account_repair_plan", "Account repair plan JSON"),
        file_artifact(paths["plan_markdown"], "account_repair_plan_markdown", "Account repair plan Markdown"),
        file_artifact(paths["apply_result"], "account_repair_apply", "Account repair apply result"),
    ]
    return [row for row in artifacts if row.get("exists")]


def build_account_repair_summary(base_dir: str | Path) -> dict[str, Any]:
    paths = account_repair_paths(base_dir)
    plan_path = Path(paths["plan_json"])
    apply_path = Path(paths["apply_result"])
    plan = _read_json(plan_path) if plan_path.is_file() else {}
    apply_result = _read_json(apply_path) if apply_path.is_file() else {}
    safety_contract = (
        apply_result.get("safety_contract") if isinstance(apply_result.get("safety_contract"), dict) else {}
    )
    groups = plan.get("groups") if isinstance(plan.get("groups"), list) else []
    hard_errors = {
        "IXBROWSER_KERNEL_MISMATCH",
        "LOGIN_REQUIRED",
        "CAPTCHA_DETECTED",
        "PROXY_FAILED",
        "COMMENT_ACCESS_GATED",
        "ACCOUNT_RESTRICTED",
    }
    repair_groups = [row for row in groups if isinstance(row, dict)]
    selected_hard_profiles = []
    for group in repair_groups:
        if _safe_text(group.get("error")) in hard_errors:
            selected_hard_profiles.extend(str(item) for item in (group.get("profile_ids") or []) if str(item))
    computed_error_events = sum(int(row.get("count") or 0) for row in repair_groups)
    computed_summary_only = sum(
        max(0, int(row.get("summary_only_count") or int(row.get("count") or 0) - len(row.get("profile_ids") or [])))
        for row in repair_groups
    )
    pending_recheck = bool(
        apply_result
        and _safe_text(apply_result.get("status")) == "applied"
        and int(apply_result.get("moved_count") or 0) > 0
        and int(apply_result.get("failed_count") or 0) == 0
    )
    return {
        "schema_version": "reachops.account_repair_summary.v1",
        "plan_path": str(plan_path),
        "plan_exists": plan_path.is_file(),
        "markdown_path": paths["plan_markdown"],
        "markdown_exists": Path(paths["plan_markdown"]).is_file(),
        "apply_path": str(apply_path),
        "apply_exists": apply_path.is_file(),
        "batch_id": _safe_text(plan.get("batch_id")),
        "profile_group": _safe_text(plan.get("profile_group")),
        "error_group_count": len(repair_groups),
        "total_profiles_by_error": int(plan.get("total_unique_profiles_by_error") or 0),
        "total_error_events_by_error": int(
            plan.get("total_error_events_by_error") or computed_error_events or plan.get("total_unique_profiles_by_error") or 0
        ),
        "summary_only_error_count": int(plan.get("summary_only_error_count") or computed_summary_only),
        "hard_blocker_profile_count": len(list(dict.fromkeys(selected_hard_profiles))),
        "operator_steps": list(plan.get("operator_steps") or [])[:8],
        "error_groups": [
            {
                "error": _safe_text(row.get("error")),
                "count": int(row.get("count") or 0),
                "profile_ids_sample": [str(item) for item in (row.get("profile_ids") or [])[:8]],
                "profile_ids_total": int(row.get("profile_ids_total") or len(row.get("profile_ids") or [])),
                "summary_only_count": int(row.get("summary_only_count") or 0),
                "recommended_action": _safe_text(row.get("recommended_action")),
            }
            for row in repair_groups[:12]
        ],
        "apply_status": _safe_text(apply_result.get("status")),
        "apply_selected_count": int(apply_result.get("selected_count") or 0),
        "apply_moved_count": int(apply_result.get("moved_count") or 0),
        "apply_failed_count": int(apply_result.get("failed_count") or 0),
        "safety_contract": safety_contract,
        "manual_apply_required": bool(safety_contract.get("manual_apply_required", True)),
        "operator_confirmed_apply": bool(safety_contract.get("operator_confirmed_apply")),
        "hard_blocker_only": bool(safety_contract.get("hard_blocker_only", True)),
        "moves_only_to_quarantine_group": bool(safety_contract.get("moves_only_to_quarantine_group", True)),
        "no_browser_started": bool(safety_contract.get("no_browser_started", True)),
        "no_submit": bool(safety_contract.get("no_submit", True)),
        "pending_recheck": pending_recheck,
        "next_actions": _account_repair_next_actions(plan, apply_result, pending_recheck),
        "no_ai_token_used": True,
    }


def _account_repair_next_actions(plan: dict[str, Any], apply_result: dict[str, Any], pending_recheck: bool) -> list[str]:
    if not plan:
        return ["没有账号修复计划；如出现账号阻断，先生成验收/修复报告。"]
    if pending_recheck:
        return ["账号修复已应用，重新刷新账号分组并复跑预检。"]
    if apply_result and int(apply_result.get("failed_count") or 0) > 0:
        return ["账号修复应用存在失败项，先处理失败结果再重新预检。"]
    return list(plan.get("operator_steps") or [])[:4] or ["按账号修复计划处理阻断账号后重新预检。"]


def build_repair_summary(run_session: dict[str, Any], result: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    audit_events: list[dict[str, Any]] = []
    for row in _walk_dicts({"run_session": run_session, "result": result}):
        decision = row.get("repair_decision")
        if isinstance(decision, dict):
            decisions.append(decision)
        audit = row.get("repair_audit")
        if isinstance(audit, dict):
            audit_events.append(audit)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in decisions:
        key = _safe_text(decision.get("repair_decision_id"))
        if not key:
            key = "|".join(
                [
                    _safe_text(decision.get("error_code")),
                    _safe_text(decision.get("action")),
                    _safe_text(decision.get("reason")),
                    _safe_text(decision.get("degrade_to")),
                ]
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(decision)
    retry_events = [line for line in log_lines if "action_router_repair_retry_same_profile" in line or "retry_same_profile" in line]
    decision_events = [line for line in log_lines if "action_router_repair_decision" in line or "repair_decision" in line]
    switch_count = max(
        len([row for row in deduped if row.get("switch_profile")]),
        len([row for row in audit_events if row.get("switch_profile")]),
    )
    cooldown_count = max(
        len([row for row in deduped if row.get("cooldown_profile")]),
        len([row for row in audit_events if row.get("cooldown_profile")]),
    )
    retry_decision_count = max(
        len([row for row in deduped if row.get("retry_same_profile")]),
        len([row for row in audit_events if row.get("retry_same_profile")]),
    )
    retry_count = max(retry_decision_count, len(retry_events))
    degrade_count = max(
        len([row for row in deduped if _safe_text(row.get("degrade_to"))]),
        len([row for row in audit_events if _safe_text(row.get("degrade_to"))]),
    )
    block_count = max(
        len([row for row in deduped if row.get("block_execution")]),
        len([row for row in audit_events if row.get("block_execution")]),
    )
    repair_step_results = [
        step
        for row in audit_events
        for step in (row.get("repair_step_results") or [])
        if isinstance(step, dict)
    ]
    terminal_outcome_counts: dict[str, int] = {}
    for row in deduped:
        outcome = _safe_text(row.get("terminal_outcome")) or (
            "degraded"
            if _safe_text(row.get("degrade_to"))
            else (
                "blocked"
                if row.get("block_execution")
                else (
                    "retry"
                    if row.get("retry_same_profile")
                    else ("switch_profile" if row.get("switch_profile") else ("fallback" if row.get("fallback_allowed") else "recorded"))
                )
            )
        )
        terminal_outcome_counts[outcome] = terminal_outcome_counts.get(outcome, 0) + 1
    return {
        "schema_version": "reachops.repair_summary.v1",
        "decision_count": len(deduped),
        "audit_event_count": len(audit_events),
        "log_event_count": len(decision_events) + len(retry_events),
        "retry_count": retry_count,
        "switch_profile_count": switch_count,
        "cooldown_profile_count": cooldown_count,
        "degrade_count": degrade_count,
        "block_count": block_count,
        "repair_step_result_count": len(repair_step_results),
        "repair_step_executed_count": len([row for row in repair_step_results if row.get("status") in {"executed", "planned_by_router", "already_captured_or_recorded", "handled_by_account_health"}]),
        "repair_step_browser_required_count": len([row for row in repair_step_results if row.get("status") == "requires_browser_executor"]),
        "terminal_outcome_counts": terminal_outcome_counts,
        "terminal_retry_count": int(terminal_outcome_counts.get("retry") or 0),
        "terminal_switch_profile_count": int(terminal_outcome_counts.get("switch_profile") or 0),
        "terminal_degrade_count": int(terminal_outcome_counts.get("degraded") or 0),
        "terminal_block_count": int(terminal_outcome_counts.get("blocked") or 0),
        "actions": sorted({str(row.get("action") or "") for row in deduped if row.get("action")}),
        "error_codes": sorted({str(row.get("error_code") or "") for row in deduped if row.get("error_code")}),
        "decisions": deduped[:20],
        "audit_events": audit_events[:40],
        "repair_step_results": repair_step_results[:80],
        "no_ai_token_used": True,
    }


def build_risk_summary(run_session: dict[str, Any], result: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    def inferred_category(row: dict[str, Any]) -> str:
        code = _safe_text(row.get("reason_code"))
        if row.get("allowed") is True or code == "OK":
            return "allowed"
        if row.get("requires_authorization") or "AUTH" in code or code.startswith("LIVE_SUBMIT"):
            return "authorization"
        if row.get("cooldown") or code in {"PROFILE_IN_COOLDOWN", "LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"}:
            return "account_health"
        if row.get("quota_ok") is False or code == "DAILY_QUOTA_EXCEEDED":
            return "quota"
        if row.get("rate_limit_ok") is False or "RATE" in code or "LIMIT" in code:
            return "rate_limit"
        if code == "DUPLICATE_ACTION_TEXT":
            return "duplicate_text"
        if row.get("high_risk") or code == "HIGH_RISK_REVIEW_NOTE_REQUIRED":
            return "high_risk"
        if code in {"PUBLISH_PROFILE_BLOCKED", "PROFILE_REQUIRED"}:
            return "profile_policy"
        return "policy"

    def inferred_outcome(row: dict[str, Any]) -> str:
        if row.get("allowed") is True:
            return "allowed"
        actions = row.get("risk_actions") if isinstance(row.get("risk_actions"), list) else []
        steps = {str(action.get("step") or "") for action in actions if isinstance(action, dict)}
        if row.get("requires_human_review"):
            return "blocked_human_review"
        if steps & {"wait_or_switch_profile", "cooldown_scope"}:
            return "blocked_wait_or_switch"
        if "rewrite_or_rotate_message" in steps:
            return "blocked_rewrite_required"
        return "blocked"

    decisions: list[dict[str, Any]] = []
    for row in _walk_dicts({"run_session": run_session, "result": result}):
        decision = row.get("risk_gate")
        if isinstance(decision, dict):
            decisions.append(decision)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in decisions:
        key = _safe_text(decision.get("risk_decision_id"))
        if not key:
            key = "|".join(
                [
                    _safe_text(decision.get("profile_id")),
                    _safe_text(decision.get("action_type")),
                    _safe_text(decision.get("reason_code")),
                    _safe_text(decision.get("allowed")),
                ]
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(decision)
    risk_log_events = [line for line in log_lines if "risk_gate" in line or "live_submit_authorization_blocked" in line]
    allowed_count = len([row for row in deduped if row.get("allowed") is True])
    blocked = [row for row in deduped if row.get("allowed") is False]
    risk_category_counts: dict[str, int] = {}
    terminal_outcome_counts: dict[str, int] = {}
    for row in deduped:
        category = _safe_text(row.get("risk_category"))
        if not category:
            category = inferred_category(row)
        outcome = _safe_text(row.get("terminal_outcome")) or inferred_outcome(row)
        risk_category_counts[category] = risk_category_counts.get(category, 0) + 1
        terminal_outcome_counts[outcome] = terminal_outcome_counts.get(outcome, 0) + 1
    return {
        "schema_version": "reachops.risk_summary.v1",
        "decision_count": len(deduped),
        "log_event_count": len(risk_log_events),
        "allowed_count": allowed_count,
        "blocked_count": len(blocked),
        "authorization_block_count": len([row for row in blocked if row.get("requires_authorization") or "AUTH" in _safe_text(row.get("reason_code"))]),
        "quota_block_count": len([row for row in blocked if row.get("quota_ok") is False or _safe_text(row.get("reason_code")) == "DAILY_QUOTA_EXCEEDED"]),
        "rate_limit_block_count": len([row for row in blocked if row.get("rate_limit_ok") is False or "RATE" in _safe_text(row.get("reason_code"))]),
        "cooldown_block_count": len([row for row in blocked if row.get("cooldown")]),
        "high_risk_count": len([row for row in deduped if row.get("high_risk")]),
        "human_review_required_count": len([row for row in blocked if row.get("requires_human_review")]),
        "block_execution_count": len([row for row in deduped if row.get("block_execution")]),
        "risk_action_count": sum(len(row.get("risk_actions") or []) for row in deduped),
        "risk_category_counts": risk_category_counts,
        "terminal_outcome_counts": terminal_outcome_counts,
        "reason_codes": sorted({str(row.get("reason_code") or "") for row in deduped if row.get("reason_code")}),
        "decisions": deduped[:20],
        "no_ai_token_used": True,
    }


def build_operator_risk_gate_summary(run_session: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _walk_dicts({"run_session": run_session, "result": result}):
        decision = row.get("risk_gate")
        if not isinstance(decision, dict):
            continue
        reason_code = _safe_text(decision.get("reason_code"))
        allowed = bool(decision.get("allowed"))
        action_type = _safe_text(row.get("action_type") or decision.get("action_type"))
        profile_id = _safe_text(row.get("profile_id") or decision.get("profile_id"))
        target_username = _safe_text(row.get("target_username") or row.get("username"))
        status = _safe_text(row.get("status"))
        actions = decision.get("risk_actions") if isinstance(decision.get("risk_actions"), list) else []
        action_steps = [
            _safe_text(action.get("step"))
            for action in actions
            if isinstance(action, dict) and _safe_text(action.get("step"))
        ]
        next_step = _safe_text(row.get("next_step"))
        if not next_step:
            if "rewrite_or_rotate_message" in action_steps:
                next_step = "改写或轮换话术后重试"
            elif "request_operator_authorization" in action_steps:
                next_step = "等待人工授权后再执行"
            elif "wait_or_switch_profile" in action_steps or "cooldown_scope" in action_steps:
                next_step = "等待冷却或切换账号"
            elif "block_execution" in action_steps:
                next_step = "保持阻断，等待处理"
        risk_gate_summary = _safe_text(row.get("risk_gate_summary"))
        if not risk_gate_summary:
            if allowed:
                risk_gate_summary = "风险门禁通过"
            else:
                parts = ["风险门禁阻断"]
                if reason_code:
                    parts.append(reason_code)
                category = _safe_text(decision.get("risk_category"))
                outcome = _safe_text(decision.get("terminal_outcome"))
                if category:
                    parts.append(f"类别：{category}")
                if outcome:
                    parts.append(f"结果：{outcome}")
                reason = _safe_text(decision.get("reason"))
                if reason and reason != reason_code:
                    parts.append(reason)
                risk_gate_summary = " / ".join(parts)
        key = _safe_text(decision.get("risk_decision_id")) or "|".join(
            [target_username, action_type, profile_id, reason_code, status]
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "target_username": target_username,
                "action_type": action_type,
                "profile_id": profile_id,
                "status": status,
                "risk_gate_summary": risk_gate_summary,
                "next_step": next_step,
                "reason_code": reason_code,
                "allowed": allowed,
                "risk_action_steps": action_steps,
                "no_ai_token_used": True,
            }
        )
    blocked_rows = [row for row in rows if not row.get("allowed")]
    return {
        "schema_version": "reachops.operator_risk_gate_summary.v1",
        "row_count": len(rows),
        "blocked_count": len(blocked_rows),
        "allowed_count": len([row for row in rows if row.get("allowed")]),
        "primary_reason": _safe_text((blocked_rows[0] if blocked_rows else (rows[0] if rows else {})).get("risk_gate_summary")),
        "primary_next_step": _safe_text((blocked_rows[0] if blocked_rows else (rows[0] if rows else {})).get("next_step")),
        "rows": rows[:20],
        "no_ai_token_used": True,
    }


def build_risk_policy_summary(risk_summary: dict[str, Any]) -> dict[str, Any]:
    decisions = risk_summary.get("decisions") if isinstance(risk_summary.get("decisions"), list) else []
    blocked = [row for row in decisions if isinstance(row, dict) and row.get("allowed") is False]
    reason_codes = [str(row.get("reason_code") or "") for row in blocked]
    duplicate_blocks = [
        row
        for row in blocked
        if "DUPLICATE" in str(row.get("reason_code") or "") or any(
            str(action.get("step") or "") == "rewrite_or_rotate_message"
            for action in (row.get("risk_actions") or [])
            if isinstance(action, dict)
        )
    ]
    publish_blocks = [row for row in blocked if str(row.get("reason_code") or "") == "PUBLISH_PROFILE_BLOCKED"]
    profile_group_blocks = [
        row
        for row in blocked
        if str(row.get("reason_code") or "").startswith("profile_group_")
        or any(
            str(action.get("step") or "") in {"refresh_profile_groups", "reselect_profile_group"}
            for action in (row.get("risk_actions") or [])
            if isinstance(action, dict)
        )
    ]
    high_risk_review_blocks = [
        row
        for row in blocked
        if row.get("high_risk") or str(row.get("reason_code") or "") == "HIGH_RISK_REVIEW_NOTE_REQUIRED"
    ]
    next_actions: list[str] = []
    if int(risk_summary.get("authorization_block_count") or 0) > 0:
        next_actions.append("补齐授权门禁；未授权前不执行真实评论、关注或私信。")
    if int(risk_summary.get("quota_block_count") or 0) > 0:
        next_actions.append("等待额度窗口恢复或切换同分组健康账号。")
    if int(risk_summary.get("rate_limit_block_count") or 0) > 0:
        next_actions.append("等待限频窗口恢复，必要时降低执行强度。")
    if duplicate_blocks:
        next_actions.append("更换触达话术或等待去重窗口结束。")
    if publish_blocks:
        next_actions.append("切换到获客执行账号分组，不使用发布主账号。")
    if profile_group_blocks:
        next_actions.append("刷新 ixBrowser 配置分组并重新选择已确认账号数量的执行分组。")
    if high_risk_review_blocks:
        next_actions.append("高风险动作补充人工复核说明后再执行。")
    return {
        "schema_version": "reachops.risk_policy_summary.v1",
        "policy_block_count": len(blocked),
        "authorization_block_count": int(risk_summary.get("authorization_block_count") or 0),
        "quota_block_count": int(risk_summary.get("quota_block_count") or 0),
        "rate_limit_block_count": int(risk_summary.get("rate_limit_block_count") or 0),
        "duplicate_text_block_count": len(duplicate_blocks),
        "publish_profile_block_count": len(publish_blocks),
        "profile_group_block_count": len(profile_group_blocks),
        "high_risk_review_block_count": len(high_risk_review_blocks),
        "cooldown_block_count": int(risk_summary.get("cooldown_block_count") or 0),
        "human_review_required_count": int(risk_summary.get("human_review_required_count") or 0),
        "reason_codes": sorted(set(reason_codes)),
        "evidence_samples": [
            {
                "reason_code": _safe_text(row.get("reason_code")),
                "profile_id": _safe_text(row.get("profile_id")),
                "action_type": _safe_text(row.get("action_type")),
                "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
                "risk_actions": row.get("risk_actions") if isinstance(row.get("risk_actions"), list) else [],
            }
            for row in blocked[:12]
        ],
        "next_actions": next_actions[:8],
        "no_ai_token_used": True,
    }


def build_page_state_summary(run_session: dict[str, Any], result: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    screenshot_unavailable_count = 0
    screenshot_unavailable_seen: set[str] = set()
    for row in _walk_dicts({"run_session": run_session, "result": result}):
        page_state = row.get("page_state")
        if isinstance(page_state, dict):
            snapshots.append(page_state)
        screenshot = row.get("screenshot") if isinstance(row.get("screenshot"), dict) else {}
        if screenshot and screenshot.get("captured") is False and _safe_text(screenshot.get("unavailable_reason")):
            unavailable_key = "|".join(
                [
                    _safe_text(row.get("sidecar_path")),
                    _safe_text(screenshot.get("unavailable_reason")),
                    _safe_text(row.get("captured_at")),
                ]
            )
            if unavailable_key not in screenshot_unavailable_seen:
                screenshot_unavailable_seen.add(unavailable_key)
                screenshot_unavailable_count += 1
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snapshot in snapshots:
        key = "|".join(
            [
                _safe_text(snapshot.get("state")),
                _safe_text(snapshot.get("current_url")),
                _safe_text(snapshot.get("title")),
                _safe_text(snapshot.get("body_text_sha256")),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(snapshot)
    state_counts: dict[str, int] = {}
    for snapshot in deduped:
        state = _safe_text(snapshot.get("state"), "UNKNOWN_PAGE_STATE") or "UNKNOWN_PAGE_STATE"
        state_counts[state] = state_counts.get(state, 0) + 1
    blocking_states = {
        "LOGIN_REQUIRED",
        "CAPTCHA_DETECTED",
        "RATE_LIMITED",
        "PAGE_TIMEOUT",
        "DOM_STALLED",
        "MODAL_BLOCKED",
        "COMMENT_BOX_MISSING",
        "SUBMIT_BUTTON_MISSING",
        "UNKNOWN_PAGE_STATE",
    }
    signals = sorted(
        {
            str(signal)
            for snapshot in deduped
            for signal in (snapshot.get("signals") or [])
            if str(signal)
        }
    )
    page_state_log_events = [line for line in log_lines if "page_state" in line or "UNKNOWN_PAGE_STATE" in line]
    return {
        "schema_version": "reachops.page_state_summary.v1",
        "snapshot_count": len(deduped),
        "log_event_count": len(page_state_log_events),
        "state_counts": state_counts,
        "blocking_count": sum(count for state, count in state_counts.items() if state in blocking_states and state != "READY"),
        "unknown_count": int(state_counts.get("UNKNOWN_PAGE_STATE") or 0),
        "login_required_count": int(state_counts.get("LOGIN_REQUIRED") or 0),
        "captcha_count": int(state_counts.get("CAPTCHA_DETECTED") or 0),
        "rate_limited_count": int(state_counts.get("RATE_LIMITED") or 0),
        "screenshot_unavailable_count": screenshot_unavailable_count,
        "signals": signals[:40],
        "snapshots": deduped[:20],
        "no_ai_token_used": True,
    }


def build_control_summary(run_session: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    events = [row for row in (run_session.get("control_history") or []) if isinstance(row, dict)]
    control = run_session.get("control") if isinstance(run_session.get("control"), dict) else {}
    action_counts: dict[str, int] = {}
    for event in events:
        action = _safe_text(event.get("action"), "unknown") or "unknown"
        action_counts[action] = action_counts.get(action, 0) + 1
    control_log_events = [
        line
        for line in log_lines
        if "web_ui_stop_requested" in line
        or "web_ui_stop_signal_failed" in line
        or "web_ui_stop_process_still_running" in line
        or "run_session_recovered_interrupted" in line
    ]
    return {
        "schema_version": "reachops.control_summary.v1",
        "event_count": len(events),
        "log_event_count": len(control_log_events),
        "pause_count": int(action_counts.get("pause") or 0),
        "resume_count": int(action_counts.get("resume") or 0),
        "stop_count": int(action_counts.get("stop") or 0),
        "recovery_count": int(action_counts.get("recover_interrupted_run") or 0),
        "failed_control_count": len([row for row in events if row.get("ok") is False]),
        "last_action": _safe_text(events[-1].get("action")) if events else "",
        "current_paused": bool(control.get("current_paused", control.get("paused", False))),
        "current_status": _safe_text(control.get("status")),
        "events": events[-20:],
        "no_ai_token_used": True,
    }


def build_run_recovery_summary(
    run_session: dict[str, Any],
    result: dict[str, Any],
    log_lines: list[str],
    control_summary: dict[str, Any],
) -> dict[str, Any]:
    control_events = [
        row
        for row in (run_session.get("control_history") or [])
        if isinstance(row, dict) and _safe_text(row.get("action")) == "recover_interrupted_run"
    ]
    session_result = run_session.get("result") if isinstance(run_session.get("result"), dict) else {}
    recovery_payloads = []
    for candidate in (session_result.get("recovery"), result.get("recovery")):
        if isinstance(candidate, dict):
            recovery_payloads.append(candidate)
    log_markers = [
        line
        for line in log_lines
        if "run_session_recovered_interrupted" in line
        or "PROCESS_INTERRUPTED" in line
        or "recover_interrupted_run" in line
    ]
    checkpoint = run_session.get("checkpoint") if isinstance(run_session.get("checkpoint"), dict) else {}
    recovered = bool(control_events or recovery_payloads or log_markers)
    reasons = sorted(
        {
            reason
            for reason in [
                *[_safe_text(row.get("reason")) for row in control_events],
                *[_safe_text(row.get("reason")) for row in recovery_payloads],
                _safe_text(session_result.get("reason")),
                _safe_text(result.get("reason")),
            ]
            if reason
        }
    )
    return {
        "schema_version": "reachops.run_recovery_summary.v1",
        "recovered": recovered,
        "recovery_count": int(control_summary.get("recovery_count") or len(control_events) or len(recovery_payloads) or 0),
        "control_event_count": len(control_events),
        "recovery_payload_count": len(recovery_payloads),
        "log_marker_count": len(log_markers),
        "reasons": reasons,
        "latest_reason": reasons[-1] if reasons else "",
        "last_stage": _safe_text(checkpoint.get("last_stage") or result.get("last_stage") or session_result.get("last_stage")),
        "runtime_state_inferred": _safe_text(checkpoint.get("runtime_state_inferred")),
        "checkpoint_state": _safe_text(checkpoint.get("state") or run_session.get("state")),
        "checkpoint_log_line_count": int(checkpoint.get("log_line_count") or 0),
        "result_error": _safe_text(session_result.get("error") or result.get("error")),
        "result_status": _safe_text(session_result.get("status") or result.get("status")),
        "terminal_state": _safe_text(run_session.get("state")),
        "events": control_events[-10:],
        "recovery_payloads": recovery_payloads[-5:],
        "no_ai_token_used": True,
    }


def build_run_session_health_summary(run_session: dict[str, Any]) -> dict[str, Any]:
    health = run_session.get("session_health") if isinstance(run_session.get("session_health"), dict) else {}
    if health:
        return dict(health)
    checkpoint = run_session.get("checkpoint") if isinstance(run_session.get("checkpoint"), dict) else {}
    control = run_session.get("control") if isinstance(run_session.get("control"), dict) else {}
    state = _safe_text(run_session.get("state")) or ""
    return {
        "schema_version": "reachops.run_session_health.v1",
        "status": "missing" if not run_session else ("terminal" if state in {"BLOCKED", "DEGRADED", "COMPLETED"} else "unknown"),
        "state": state,
        "stale": False,
        "terminal": state in {"BLOCKED", "DEGRADED", "COMPLETED"},
        "paused": bool(control.get("current_paused") or control.get("paused")),
        "running": False,
        "updated_at": _safe_text(run_session.get("updated_at")),
        "age_seconds": 0,
        "stale_after_seconds": 0,
        "last_stage": _safe_text(checkpoint.get("last_stage")),
        "runtime_state_inferred": _safe_text(checkpoint.get("runtime_state_inferred")),
        "log_line_count": int(checkpoint.get("log_line_count") or 0),
        "pid": int(run_session.get("pid") or 0),
        "no_ai_token_used": True,
    }


def build_autonomous_execution_summary(
    run_session: dict[str, Any],
    run_session_health: dict[str, Any],
    control_summary: dict[str, Any],
    ai_usage_summary: dict[str, Any],
    log_lines: list[str],
) -> dict[str, Any]:
    raw_history = [row for row in (run_session.get("state_history") or []) if isinstance(row, dict)]
    history: list[dict[str, Any]] = []
    last_key = None
    for row in raw_history:
        key = (
            _safe_text(row.get("state")),
            _safe_text(row.get("last_stage")),
            _safe_text(row.get("runtime_state_inferred")),
            int(row.get("log_line_count") or 0),
        )
        if key == last_key:
            continue
        history.append(row)
        last_key = key
    checkpoint = run_session.get("checkpoint") if isinstance(run_session.get("checkpoint"), dict) else {}
    observed_states: list[str] = []
    for row in history:
        state = _safe_text(row.get("state"))
        if state and state not in observed_states:
            observed_states.append(state)
    checkpoint_state = _safe_text(checkpoint.get("state") or run_session.get("state"))
    if checkpoint_state and checkpoint_state not in observed_states:
        observed_states.append(checkpoint_state)
    inferred_state = _safe_text(checkpoint.get("runtime_state_inferred"))
    if inferred_state and inferred_state not in observed_states:
        observed_states.append(inferred_state)

    implemented_states = [state for state in RUN_SESSION_STATE_ORDER if state]
    session_result = run_session.get("result") if isinstance(run_session.get("result"), dict) else {}
    precheck_block_errors = {
        "IXBROWSER_LOCAL_API_UNAVAILABLE",
        "profile_group_live_refresh_required",
        "profile_group_list_unavailable",
        "profile_group_not_found",
        "profile_group_counts_incomplete",
        "profile_group_count_unknown",
        "account_repair_required",
        "PROFILE_GROUP_PRECHECK_BLOCKED",
    }
    result_error = _safe_text(session_result.get("error") or session_result.get("reason"))
    precheck_blocked = bool(
        "BLOCKED" in observed_states
        and "PRECHECK" in observed_states
        and (
            result_error in precheck_block_errors
            or result_error.startswith("profile_group_")
            or "IXBROWSER_LOCAL_API_UNAVAILABLE" in json.dumps(session_result, ensure_ascii=False)
        )
    )
    core_states = ["CREATED", "PRECHECK", "BLOCKED"] if precheck_blocked else ["CREATED", "PRECHECK", "PROFILE_OPENING", "COLLECTING"]
    terminal_states = [state for state in observed_states if state in TERMINAL_RUN_SESSION_STATES]
    missing_core_states = [state for state in core_states if state not in observed_states]
    missing_implemented_states = [state for state in implemented_states if state not in observed_states]
    transition_count = max(0, len(history) - 1)
    transition_violations = [
        row for row in (run_session.get("state_transition_violations") or []) if isinstance(row, dict)
    ]
    invalid_history_transitions = [
        row for row in history if isinstance(row, dict) and row.get("valid_transition") is False
    ]
    state_machine_contract = (
        run_session.get("state_machine_contract") if isinstance(run_session.get("state_machine_contract"), dict) else {}
    )
    state_transition_violation_count = len(transition_violations) + len(invalid_history_transitions)
    recovery_events = [
        row
        for row in (run_session.get("control_history") or [])
        if isinstance(row, dict) and _safe_text(row.get("action")) == "recover_interrupted_run"
    ]
    explicit_recovery_markers = [
        line
        for line in log_lines
        if "PROCESS_INTERRUPTED" in line or "recover_interrupted_run" in line
    ]
    zero_token = bool(
        ai_usage_summary.get("audit_status") == "pass"
        and int(ai_usage_summary.get("execution_phase_ai_call_count") or 0) == 0
        and int(ai_usage_summary.get("execution_phase_token_estimate") or 0) == 0
    )
    health_ok = bool(
        run_session_health.get("schema_version") == "reachops.run_session_health.v1"
        and run_session_health.get("stale") is not True
        and _safe_text(run_session_health.get("status")) in {"healthy", "terminal", "paused", "idle"}
    )
    return {
        "schema_version": "reachops.autonomous_execution_summary.v1",
        "implemented_state_count": len(implemented_states),
        "implemented_states": implemented_states,
        "observed_state_count": len(observed_states),
        "observed_states": observed_states,
        "missing_core_states": missing_core_states,
        "missing_implemented_states": missing_implemented_states,
        "required_core_states": core_states,
        "precheck_blocked": precheck_blocked,
        "precheck_block_reason": result_error,
        "raw_state_history_count": len(raw_history),
        "state_history_count": len(history),
        "state_history_compacted": len(history) != len(raw_history),
        "transition_count": transition_count,
        "state_machine_contract_schema": _safe_text(
            state_machine_contract.get("schema_version"),
            "reachops.run_session_state_machine_contract.v1",
        ),
        "valid_state_transitions": bool(
            state_machine_contract.get("valid_transition", True)
            and int(state_machine_contract.get("violation_count") or 0) == 0
            and state_transition_violation_count == 0
        ),
        "state_transition_violation_count": state_transition_violation_count,
        "state_transition_violations": (transition_violations + invalid_history_transitions)[-20:],
        "terminal_state_observed": bool(terminal_states),
        "terminal_states": terminal_states,
        "checkpoint_present": bool(checkpoint),
        "checkpoint_state": checkpoint_state,
        "runtime_state_inferred": inferred_state,
        "health_current": health_ok,
        "control_event_count": int(control_summary.get("event_count") or 0),
        "recovery_event_count": len(recovery_events) + len(explicit_recovery_markers),
        "recovery_supported": "recover_interrupted_run" in json.dumps(run_session, ensure_ascii=False) or bool(recovery_events),
        "zero_token": zero_token,
        "autonomous_core_ready": bool(
            not missing_core_states
            and bool(terminal_states)
            and bool(checkpoint)
            and health_ok
            and zero_token
            and state_transition_violation_count == 0
        ),
        "next_actions": [
            f"补齐本地状态覆盖：{state}"
            for state in missing_core_states[:4]
        ]
        or (
            ["继续补齐修复、降级、阻断等分支状态覆盖。"]
            if missing_implemented_states
            else ["归档本地自治执行状态覆盖证据。"]
        ),
        "no_ai_token_used": True,
    }


def build_ai_usage_summary(run_session: dict[str, Any], plan: dict[str, Any], log_lines: list[str]) -> dict[str, Any]:
    ledger = normalize_ai_usage_ledger(run_session.get("ai_usage_ledger"), plan)
    execution_phase = ledger.get("execution_phase") if isinstance(ledger.get("execution_phase"), dict) else {}
    operator_console = ledger.get("operator_console") if isinstance(ledger.get("operator_console"), dict) else {}
    policy = ledger.get("policy") if isinstance(ledger.get("policy"), dict) else {}
    suspicious_log_events = []
    for line in log_lines:
        lowered = line.lower()
        normalized = lowered.replace(" ", "")
        if "no_ai_token_used=true" in normalized or "no_ai_token_used:true" in normalized:
            continue
        if (
            "openai" in lowered
            or "llm" in lowered
            or "external_ai" in lowered
            or "ai_token_used=true" in normalized
            or "ai_token_used:true" in normalized
        ):
            suspicious_log_events.append(line)
    violations = list(ledger.get("violations") or [])
    if suspicious_log_events:
        violations.append("execution_log_contains_ai_call_marker")
    violations = list(dict.fromkeys(str(item) for item in violations if str(item)))
    ai_call_count = int(execution_phase.get("ai_call_count") or 0)
    token_estimate = int(execution_phase.get("token_estimate") or 0)
    return {
        "schema_version": "reachops.ai_usage_summary.v1",
        "audit_status": "fail" if violations else "pass",
        "no_ai_token_during_execution": bool(policy.get("no_ai_token_during_execution", True)),
        "execution_phase_ai_call_count": ai_call_count,
        "execution_phase_token_estimate": token_estimate,
        "operator_console_local_rule_call_count": int(operator_console.get("local_rule_call_count") or 0),
        "operator_console_ai_call_count": int(operator_console.get("ai_call_count") or 0),
        "operator_console_token_estimate": int(operator_console.get("token_estimate") or 0),
        "suspicious_log_event_count": len(suspicious_log_events),
        "violations": violations,
        "ledger": ledger,
        "no_ai_token_used": ai_call_count == 0 and token_estimate == 0 and not violations,
    }


def build_autonomous_preflight_forecast_summary(plan: dict[str, Any]) -> dict[str, Any]:
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    forecast = runtime.get("autonomous_preflight_forecast") if isinstance(runtime.get("autonomous_preflight_forecast"), dict) else {}
    source = "persisted_in_execution_plan"
    persisted = bool(forecast)
    if not forecast and plan:
        forecast = build_autonomous_preflight_forecast(plan)
        source = "derived_from_execution_plan"
    if not forecast:
        return {
            "schema_version": "reachops.autonomous_preflight_forecast_summary.v1",
            "exists": False,
            "source": "missing",
            "persisted": False,
            "ready": False,
            "predicted_blocker_count": 0,
            "repair_route_count": 0,
            "evidence_requirement_count": 0,
            "runtime_invariants": {},
            "no_ai_token_used": True,
        }
    routes = forecast.get("repair_routes") if isinstance(forecast.get("repair_routes"), list) else []
    blockers = forecast.get("predicted_blockers") if isinstance(forecast.get("predicted_blockers"), list) else []
    evidence = forecast.get("evidence_requirements") if isinstance(forecast.get("evidence_requirements"), list) else []
    states = forecast.get("predicted_state_sequence") if isinstance(forecast.get("predicted_state_sequence"), list) else []
    return {
        "schema_version": "reachops.autonomous_preflight_forecast_summary.v1",
        "exists": True,
        "source": source,
        "persisted": persisted,
        "forecast_schema_version": _safe_text(forecast.get("schema_version")),
        "status": _safe_text(forecast.get("status")),
        "ready": forecast.get("status") == "ready" and bool(forecast.get("start_allowed")),
        "start_allowed": bool(forecast.get("start_allowed")),
        "predicted_state_sequence": [str(item) for item in states],
        "predicted_blockers": [str(item) for item in blockers],
        "predicted_blocker_count": len(blockers),
        "repair_routes": routes,
        "repair_route_count": len(routes),
        "evidence_requirements": [str(item) for item in evidence],
        "evidence_requirement_count": len(evidence),
        "runtime_invariants": forecast.get("runtime_invariants") if isinstance(forecast.get("runtime_invariants"), dict) else {},
        "no_ai_token_used": True,
    }


def build_autonomous_preflight_reconciliation(
    *,
    forecast: dict[str, Any],
    repair_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    page_state_summary: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    state_counts = page_state_summary.get("state_counts") if isinstance(page_state_summary.get("state_counts"), dict) else {}
    actual_page_states = sorted(str(state) for state in state_counts.keys() if str(state))
    actual_repair_actions: set[str] = set()
    for action in repair_summary.get("actions") or []:
        text = _safe_text(action)
        if text:
            actual_repair_actions.add(text)
    for row in (repair_summary.get("decisions") or []) + (repair_summary.get("audit_events") or []):
        if not isinstance(row, dict):
            continue
        for key in ("action", "repair_action", "error_code", "terminal_outcome", "degrade_to"):
            text = _safe_text(row.get(key))
            if text:
                actual_repair_actions.add(text)
        for step in row.get("executable_steps") or []:
            if isinstance(step, dict):
                text = _safe_text(step.get("step"))
            else:
                text = _safe_text(step)
            if text:
                actual_repair_actions.add(text)
        for step in row.get("repair_step_results") or []:
            if isinstance(step, dict):
                text = _safe_text(step.get("step") or step.get("name"))
                status = _safe_text(step.get("status"))
                if text:
                    actual_repair_actions.add(text)
                if status:
                    actual_repair_actions.add(status)
    for event in timeline:
        if not isinstance(event, dict):
            continue
        if _safe_text(event.get("stage")) == "REPAIR":
            for key in ("action", "repair_action", "error_code", "message"):
                text = _safe_text(event.get(key))
                if text:
                    actual_repair_actions.add(text)
    actual_risk_reasons = [str(item) for item in (risk_summary.get("reason_codes") or []) if str(item)]
    actual_risk_actions: set[str] = set()
    for row in risk_summary.get("decisions") or []:
        if not isinstance(row, dict):
            continue
        for action in row.get("risk_actions") or []:
            if isinstance(action, dict):
                text = _safe_text(action.get("step"))
            else:
                text = _safe_text(action)
            if text:
                actual_risk_actions.add(text)

    routes = forecast.get("repair_routes") if isinstance(forecast.get("repair_routes"), list) else []
    matched_routes: list[dict[str, Any]] = []
    unobserved_routes: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        state = _safe_text(route.get("state"))
        action = _safe_text(route.get("action"))
        terminal = _safe_text(route.get("terminal_outcome"))
        match_reasons: list[str] = []
        if state and state in state_counts:
            match_reasons.append("page_state_observed")
        if action and action in actual_repair_actions:
            match_reasons.append("repair_action_observed")
        if terminal and terminal in actual_repair_actions:
            match_reasons.append("terminal_outcome_observed")
        if action and action in actual_risk_actions:
            match_reasons.append("risk_action_observed")
        row = {
            "state": state,
            "action": action,
            "terminal_outcome": terminal,
            "match_reasons": match_reasons,
        }
        if match_reasons:
            matched_routes.append(row)
        else:
            unobserved_routes.append(row)

    forecast_exists = bool(forecast.get("exists", bool(forecast.get("forecast_schema_version") or forecast.get("schema_version"))))
    if not forecast_exists:
        status = "forecast_missing"
    elif matched_routes and unobserved_routes:
        status = "partially_matched"
    elif matched_routes:
        status = "matched"
    elif int(page_state_summary.get("snapshot_count") or 0) or int(repair_summary.get("decision_count") or 0) or int(risk_summary.get("decision_count") or 0):
        status = "not_observed"
    else:
        status = "not_observed"
    risk_gate_aligned = bool(
        int(risk_summary.get("decision_count") or 0) > 0
        and (
            int(risk_summary.get("blocked_count") or 0) == 0
            or actual_risk_reasons
            or actual_risk_actions
        )
    )
    return {
        "schema_version": "reachops.autonomous_preflight_reconciliation.v1",
        "forecast_exists": forecast_exists,
        "forecast_source": _safe_text(forecast.get("source")) or "missing",
        "forecast_persisted": bool(forecast.get("persisted")),
        "status": status,
        "actual_page_states": actual_page_states,
        "actual_page_state_counts": state_counts,
        "actual_repair_actions": sorted(actual_repair_actions)[:40],
        "actual_risk_reasons": actual_risk_reasons[:40],
        "actual_risk_actions": sorted(actual_risk_actions)[:40],
        "matched_route_count": len(matched_routes),
        "matched_routes": matched_routes[:20],
        "unobserved_route_count": len(unobserved_routes),
        "unobserved_routes": unobserved_routes[:20],
        "risk_gate_aligned": risk_gate_aligned,
        "actual_evidence_counts": {
            "page_state_snapshots": int(page_state_summary.get("snapshot_count") or 0),
            "repair_decisions": int(repair_summary.get("decision_count") or 0),
            "repair_audit_events": int(repair_summary.get("audit_event_count") or 0),
            "risk_decisions": int(risk_summary.get("decision_count") or 0),
            "risk_blocks": int(risk_summary.get("blocked_count") or 0),
            "timeline_events": len(timeline),
        },
        "no_ai_token_used": True,
    }


def build_autonomy_readiness_summary(
    *,
    plan_runtime_contract: dict[str, Any],
    ai_usage_summary: dict[str, Any],
    repair_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    page_state_summary: dict[str, Any],
    control_summary: dict[str, Any],
    autonomous_execution_summary: dict[str, Any],
    run_session_health: dict[str, Any] | None = None,
    account_health_summary: dict[str, Any],
    account_repair_summary: dict[str, Any],
    offline_learning: dict[str, Any],
    audit: dict[str, Any],
    page_state_repair_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    health = run_session_health if isinstance(run_session_health, dict) else {}
    page_state_repair_coverage = page_state_repair_coverage if isinstance(page_state_repair_coverage, dict) else {}
    health_status = _safe_text(health.get("status"))
    health_current = bool(
        health.get("schema_version") == "reachops.run_session_health.v1"
        and health_status in {"healthy", "terminal", "paused", "idle"}
        and health.get("stale") is not True
    )
    checks = [
        {
            "name": "execution_plan_replayable",
            "passed": bool(
                plan_runtime_contract.get("plan_id_matches")
                and plan_runtime_contract.get("plan_fingerprint_matches")
                and plan_runtime_contract.get("runtime_after_fingerprint_present")
            ),
            "evidence": "ExecutionPlan runtime contract",
        },
        {
            "name": "run_session_checkpointed",
            "passed": bool(
                autonomous_execution_summary.get("checkpoint_present")
                and int(autonomous_execution_summary.get("state_history_count") or 0) > 0
            ),
            "evidence": "RunSession checkpoint/state_history",
        },
        {
            "name": "run_session_transitions_valid",
            "passed": bool(
                autonomous_execution_summary.get("valid_state_transitions")
                and int(autonomous_execution_summary.get("state_transition_violation_count") or 0) == 0
            ),
            "evidence": {
                "contract_schema": autonomous_execution_summary.get("state_machine_contract_schema") or "",
                "violation_count": int(autonomous_execution_summary.get("state_transition_violation_count") or 0),
            },
        },
        {
            "name": "autonomous_state_machine_core_covered",
            "passed": bool(autonomous_execution_summary.get("autonomous_core_ready")),
            "evidence": {
                "observed_states": autonomous_execution_summary.get("observed_states") or [],
                "missing_core_states": autonomous_execution_summary.get("missing_core_states") or [],
                "terminal_state_observed": bool(autonomous_execution_summary.get("terminal_state_observed")),
            },
        },
        {
            "name": "run_session_health_current",
            "passed": health_current,
            "evidence": {
                "status": health_status or "missing",
                "stale": bool(health.get("stale")),
                "age_seconds": int(health.get("age_seconds") or 0),
                "last_stage": _safe_text(health.get("last_stage")),
            },
        },
        {
            "name": "page_state_sensed",
            "passed": int(page_state_summary.get("snapshot_count") or 0) > 0,
            "evidence": "PageState summary",
        },
        {
            "name": "page_state_evidence_audited",
            "passed": bool(
                int(page_state_summary.get("snapshot_count") or 0) > 0
                and int(audit.get("page_state_sidecar_artifact_count") or 0) > 0
                and (
                    int(audit.get("page_state_screenshot_artifact_count") or 0) > 0
                    or int(page_state_summary.get("screenshot_unavailable_count") or 0) > 0
                )
            ),
            "evidence": {
                "snapshot_count": int(page_state_summary.get("snapshot_count") or 0),
                "sidecar_artifacts": int(audit.get("page_state_sidecar_artifact_count") or 0),
                "screenshot_artifacts": int(audit.get("page_state_screenshot_artifact_count") or 0),
                "screenshot_unavailable_count": int(page_state_summary.get("screenshot_unavailable_count") or 0),
            },
        },
        {
            "name": "repair_policy_audited",
            "passed": int(repair_summary.get("decision_count") or 0) > 0 or int(repair_summary.get("audit_event_count") or 0) > 0,
            "evidence": "Repair summary",
        },
        {
            "name": "page_state_repair_policy_covered",
            "passed": bool(
                page_state_repair_coverage.get("schema_version") == "reachops.page_state_repair_coverage.v1"
                and page_state_repair_coverage.get("all_page_states_covered") is True
                and int(page_state_repair_coverage.get("uncovered_count") or 0) == 0
            ),
            "evidence": {
                "covered_count": int(page_state_repair_coverage.get("covered_count") or 0),
                "uncovered_states": page_state_repair_coverage.get("uncovered_states") or [],
            },
        },
        {
            "name": "risk_gate_audited",
            "passed": int(risk_summary.get("decision_count") or 0) > 0,
            "evidence": "Risk summary",
        },
        {
            "name": "account_health_visible",
            "passed": int(account_health_summary.get("event_count") or 0) > 0 or bool(account_repair_summary.get("plan_exists")),
            "evidence": "Account health/repair summary",
        },
        {
            "name": "offline_learning_available",
            "passed": int(offline_learning.get("record_count") or 0) >= 0 and isinstance(offline_learning.get("policy_candidates"), dict),
            "evidence": "Offline learning ledger",
        },
        {
            "name": "execution_zero_token",
            "passed": bool(
                ai_usage_summary.get("audit_status") == "pass"
                and int(ai_usage_summary.get("execution_phase_ai_call_count") or 0) == 0
                and int(ai_usage_summary.get("execution_phase_token_estimate") or 0) == 0
            ),
            "evidence": "AI usage ledger",
        },
        {
            "name": "evidence_bundle_complete_enough",
            "passed": int(audit.get("existing_artifact_count") or 0) > 0 and int(audit.get("timeline_count") or 0) > 0,
            "evidence": "Evidence artifacts/timeline",
        },
    ]
    passed = [row for row in checks if row.get("passed")]
    failed = [row for row in checks if not row.get("passed")]
    return {
        "schema_version": "reachops.autonomy_readiness_summary.v1",
        "ready": not failed,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "checks": checks,
        "failed_checks": [row.get("name") for row in failed],
        "next_actions": [
            f"补齐自治链路证据：{row.get('name')}"
            for row in failed[:5]
        ] or ["归档自治执行证据包。"],
        "no_ai_token_used": True,
    }


def build_product_capability_summary(
    *,
    plan_runtime_contract: dict[str, Any],
    run_session_health: dict[str, Any],
    ai_usage_summary: dict[str, Any],
    autonomy_readiness_summary: dict[str, Any],
    repair_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    page_state_summary: dict[str, Any],
    control_summary: dict[str, Any],
    autonomous_execution_summary: dict[str, Any],
    account_health_summary: dict[str, Any],
    account_repair_summary: dict[str, Any],
    offline_learning: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    autonomy_checks = {
        _safe_text(row.get("name")): bool(row.get("passed"))
        for row in autonomy_readiness_summary.get("checks", [])
        if isinstance(row, dict)
    }
    zero_token = bool(
        ai_usage_summary.get("audit_status") == "pass"
        and int(ai_usage_summary.get("execution_phase_ai_call_count") or 0) == 0
        and int(ai_usage_summary.get("execution_phase_token_estimate") or 0) == 0
    )
    session_current = bool(
        run_session_health.get("schema_version") == "reachops.run_session_health.v1"
        and run_session_health.get("stale") is not True
        and _safe_text(run_session_health.get("status")) in {"healthy", "terminal", "paused", "idle"}
    )
    phase_3_next_action = "补齐 checkpoint、恢复或 0 token 执行审计。"
    missing_core_states = [
        _safe_text(state)
        for state in (autonomous_execution_summary.get("missing_core_states") or [])
        if _safe_text(state)
    ]
    if missing_core_states:
        phase_3_next_action = "补齐本地自治状态覆盖：" + "、".join(missing_core_states[:4]) + "。"
    elif not bool(autonomous_execution_summary.get("valid_state_transitions", True)):
        phase_3_next_action = "修复 RunSession 状态跳转合同，避免异常状态序列被当成自治执行成功。"
    elif not bool(autonomous_execution_summary.get("terminal_state_observed")):
        phase_3_next_action = "补齐本地执行终态证据，确保 RunSession 明确 COMPLETED/BLOCKED/DEGRADED。"
    elif not zero_token:
        phase_3_next_action = "修复执行期 AI token 审计，确保自动执行阶段不调用外部 AI。"
    elif not session_current:
        phase_3_next_action = "修复 RunSession health，避免陈旧或未知会话被当成可用执行。"
    phases = [
        {
            "phase": 1,
            "key": "phase_1_unified_client_runtime",
            "title": "统一产品骨架",
            "passed": bool(int(audit.get("existing_artifact_count") or 0) > 0 and isinstance(control_summary, dict)),
            "evidence": ["evidence_bundle", "control_summary", "operator_summary"],
            "next_action": "保持 Web 控制台、API、证据包和启动入口统一。",
        },
        {
            "phase": 2,
            "key": "phase_2_execution_plan_standardized",
            "title": "执行计划标准化",
            "passed": bool(autonomy_checks.get("execution_plan_replayable")),
            "evidence": ["plan_runtime_contract", "execution_plan"],
            "next_action": "修复 ExecutionPlan 与运行时参数不一致的问题。",
        },
        {
            "phase": 3,
            "key": "phase_3_autonomous_execution",
            "title": "本地自治执行引擎",
            "passed": bool(
                autonomy_checks.get("run_session_checkpointed")
                and autonomy_checks.get("run_session_transitions_valid")
                and autonomy_checks.get("autonomous_state_machine_core_covered")
                and autonomy_checks.get("run_session_health_current")
                and zero_token
                and session_current
            ),
            "evidence": ["run_session", "autonomous_execution_summary", "run_session_health", "ai_usage_summary"],
            "next_action": phase_3_next_action,
        },
        {
            "phase": 4,
            "key": "phase_4_page_state_sensing",
            "title": "页面状态感知",
            "passed": bool(autonomy_checks.get("page_state_sensed") and autonomy_checks.get("page_state_evidence_audited")),
            "evidence": ["page_state_summary", "page_state_screenshot", "page_state_sidecar"],
            "next_action": "补齐页面快照、DOM 摘要、截图或未知状态包。",
        },
        {
            "phase": 5,
            "key": "phase_5_self_repair_policy",
            "title": "自修复策略中心",
            "passed": bool(
                autonomy_checks.get("repair_policy_audited")
                and autonomy_checks.get("page_state_repair_policy_covered")
            ),
            "evidence": ["repair_summary", "account_repair_summary", "page_state_repair_coverage"],
            "next_action": "补齐 RepairPolicyEngine 决策、执行步骤或账号修复清单。",
        },
        {
            "phase": 6,
            "key": "phase_6_account_risk_gate",
            "title": "账号池与风险门禁",
            "passed": bool(autonomy_checks.get("risk_gate_audited") and autonomy_checks.get("account_health_visible")),
            "evidence": ["risk_summary", "risk_policy_summary", "account_health_summary"],
            "next_action": "补齐账号健康、授权门、额度、限频或重复话术证据。",
        },
        {
            "phase": 7,
            "key": "phase_7_ai_social_console",
            "title": "AI 社交式控制台",
            "passed": bool(zero_token and int(ai_usage_summary.get("operator_console_ai_call_count") or 0) == 0),
            "evidence": ["ai_usage_summary", "operator_summary", "autonomy_readiness_summary"],
            "next_action": "确保 AI 控制台只解释和生成计划，不成为执行依赖。",
        },
        {
            "phase": 8,
            "key": "phase_8_evidence_delivery_loop",
            "title": "证据与交付闭环",
            "passed": bool(
                autonomy_checks.get("evidence_bundle_complete_enough")
                and isinstance(offline_learning.get("policy_candidates"), dict)
                and isinstance(account_repair_summary, dict)
            ),
            "evidence": ["artifacts", "timeline", "offline_learning", "operator_summary"],
            "next_action": "补齐证据产物、时间线、离线学习或报告首页。",
        },
    ]
    passed = [row for row in phases if row.get("passed")]
    failed = [row for row in phases if not row.get("passed")]
    return {
        "schema_version": "reachops.product_capability_summary.v1",
        "ready": not failed,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "phases": phases,
        "failed_phases": [row.get("key") for row in failed],
        "next_actions": [row.get("next_action") for row in failed[:5] if row.get("next_action")]
        or ["八阶段产品能力证据已闭环，归档本轮报告。"],
        "no_ai_token_used": True,
    }


def build_product_development_goals(product_capability_summary: dict[str, Any]) -> dict[str, Any]:
    """Translate the eight product phases into an operator-facing development target contract."""
    product = product_capability_summary if isinstance(product_capability_summary, dict) else {}
    phases = [row for row in (product.get("phases") or []) if isinstance(row, dict)]
    objective_by_key = {
        "phase_1_unified_client_runtime": "统一启动入口、Web 控制台、后端状态和执行脚本，只保留一个主客户端产品骨架。",
        "phase_2_execution_plan_standardized": "把人类和 AI 输入统一成可复现、可下载、可重放的 ExecutionPlan。",
        "phase_3_autonomous_execution": "执行开始后由本地状态机、checkpoint、恢复和控制动作独立推进，默认 0 token。",
        "phase_4_page_state_sensing": "持续采集 URL、标题、DOM 摘要、弹窗、按钮、截图和文本，并分类页面状态。",
        "phase_5_self_repair_policy": "用 RepairPolicyEngine 自动处理已知故障，失败时明确阻断并留下错误包。",
        "phase_6_account_risk_gate": "用账号健康、额度、授权门和风险门禁阻止失控执行。",
        "phase_7_ai_social_console": "AI 只作为沟通窗口生成计划、解释阻断和复盘，不成为执行依赖。",
        "phase_8_evidence_delivery_loop": "每次 run 产出计划、日志、截图、状态、结果、时间线和最终验收证据。",
    }
    acceptance_by_key = {
        "phase_1_unified_client_runtime": ["统一控制台可启动", "所有按钮绑定真实 API", "DOM/runtime smoke 和 delivery audit 无失败"],
        "phase_2_execution_plan_standardized": ["同一计划可重复执行", "控制台参数和后端实际参数一致", "计划可下载、可审计"],
        "phase_3_autonomous_execution": ["进程中断可恢复或明确失败", "控制台准确显示阶段", "执行期 AI token 为 0"],
        "phase_4_page_state_sensing": ["登录、验证码、卡住、按钮缺失和加载失败可分类", "异常有截图和 sidecar", "blocked 不被当成 success"],
        "phase_5_self_repair_policy": ["已知故障自动重试、刷新、关闭弹窗、换账号或降级", "修复失败后阻断", "未知状态生成错误包"],
        "phase_6_account_risk_gate": ["未授权不能真实动作", "验证码和风控提示不能绕过", "连续失败账号自动隔离"],
        "phase_7_ai_social_console": ["自然语言能改 ExecutionPlan", "AI 可解释为什么停了", "执行中不消耗 token"],
        "phase_8_evidence_delivery_loop": ["每次 run 有完整证据包", "最终报告说明做了什么和没做什么", "外部真实验证独立标记"],
    }
    stages: list[dict[str, Any]] = []
    for row in phases:
        key = _safe_text(row.get("key"))
        passed = bool(row.get("passed"))
        evidence = [str(item) for item in (row.get("evidence") or []) if str(item)]
        stages.append(
            {
                "stage": int(row.get("phase") or 0),
                "key": key,
                "title": _safe_text(row.get("title")),
                "status": "completed" if passed else "needs_work",
                "passed": passed,
                "objective": objective_by_key.get(key, _safe_text(row.get("title"))),
                "acceptance": acceptance_by_key.get(key, []),
                "evidence": evidence,
                "proof_sources": evidence,
                "gap": "" if passed else _safe_text(row.get("next_action")),
                "next_action": _safe_text(row.get("next_action")),
            }
        )
    completed = [row for row in stages if row.get("passed")]
    needs_work = [row for row in stages if not row.get("passed")]
    current_focus = needs_work[0] if needs_work else (stages[-1] if stages else {})
    return {
        "schema_version": "reachops.product_development_goals.v1",
        "goal_statement": "输入一个目标，生成一个计划，程序自动执行，遇到问题自动修复，无法修复就留下证据并清楚解释，全程默认不消耗 AI token。",
        "ready": not needs_work and bool(stages),
        "stage_count": len(stages),
        "completed_stage_count": len(completed),
        "needs_work_stage_count": len(needs_work),
        "current_focus": current_focus,
        "stages": stages,
        "next_actions": [
            f"{row.get('title')}：{row.get('next_action')}"
            for row in needs_work[:5]
            if row.get("next_action")
        ] or ["八阶段开发目标已具备证据闭环，进入真实授权和 Windows 最终交付验收。"],
        "no_ai_token_used": True,
    }


def build_operator_summary(
    *,
    summary: dict[str, Any],
    audit: dict[str, Any],
    repair_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    risk_policy_summary: dict[str, Any] | None = None,
    page_state_summary: dict[str, Any],
    control_summary: dict[str, Any],
    offline_learning: dict[str, Any],
    account_repair_summary: dict[str, Any] | None = None,
    ai_usage_summary: dict[str, Any] | None = None,
    autonomy_readiness_summary: dict[str, Any] | None = None,
    product_capability_summary: dict[str, Any] | None = None,
    page_state_repair_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_actions: list[str] = []
    primary_blocker = _safe_text(summary.get("reason"))
    title = "执行已完成" if summary.get("completed") else "执行需要处理"
    severity = "ok" if summary.get("completed") else "blocked"
    page_state_repair_coverage = page_state_repair_coverage if isinstance(page_state_repair_coverage, dict) else {}
    if int(risk_summary.get("authorization_block_count") or 0) > 0:
        primary_blocker = primary_blocker or "真实动作缺少授权。"
        next_actions.append("补齐真实评论、关注或私信授权后再启动。")
    risk_policy_summary = risk_policy_summary if isinstance(risk_policy_summary, dict) else {}
    for action in risk_policy_summary.get("next_actions") or []:
        if action:
            next_actions.append(str(action))
    if int(page_state_summary.get("unknown_count") or 0) > 0:
        primary_blocker = primary_blocker or "存在未知页面状态。"
        next_actions.append("查看未知页面状态证据包，评估是否升级 PageStateDetector。")
    elif int(page_state_summary.get("blocking_count") or 0) > 0:
        primary_blocker = primary_blocker or "页面状态阻断执行。"
        next_actions.append("处理登录、验证码、限频、弹窗或 DOM 阻断后重试。")
    if int(repair_summary.get("block_count") or 0) > 0:
        primary_blocker = primary_blocker or "自修复策略已阻断继续执行。"
        next_actions.append("复核 RepairPolicyEngine 决策，确认是否隔离账号或新增策略。")
    if int(control_summary.get("stop_count") or 0) > 0:
        primary_blocker = primary_blocker or "本次运行包含停止控制事件。"
        next_actions.append("确认停止是人工操作还是保护性停止，再决定是否恢复同一计划。")
    ai_usage_summary = ai_usage_summary if isinstance(ai_usage_summary, dict) else {}
    if ai_usage_summary.get("audit_status") == "fail":
        primary_blocker = primary_blocker or "执行期 AI token 审计失败。"
        next_actions.append("复核 ai_usage_ledger，确认执行阶段没有调用外部 AI。")
    policy_candidates = offline_learning.get("policy_candidates") if isinstance(offline_learning.get("policy_candidates"), dict) else {}
    policy_review_summary = (
        offline_learning.get("policy_review_summary") if isinstance(offline_learning.get("policy_review_summary"), dict) else {}
    )
    policy_release_proposal = (
        offline_learning.get("policy_release_proposal")
        if isinstance(offline_learning.get("policy_release_proposal"), dict)
        else {}
    )
    if int(policy_candidates.get("candidate_count") or 0) > 0:
        next_actions.append("复核离线学习候选规则；人工确认前不要自动应用。")
    if int(policy_review_summary.get("approved_count") or 0) > 0:
        next_actions.append("已批准的离线候选规则仍需进入显式策略发布，不自动绕过 RiskGate。")
    if int(policy_release_proposal.get("ready_for_release_count") or 0) > 0:
        next_actions.append("生成离线策略发布建议包；发布前 runtime_auto_apply 必须保持 0。")
    account_repair_summary = account_repair_summary if isinstance(account_repair_summary, dict) else {}
    if int(account_repair_summary.get("hard_blocker_profile_count") or 0) > 0:
        next_actions.append("按账号修复计划处理硬阻断账号，完成后重新预检。")
    if account_repair_summary.get("pending_recheck"):
        next_actions.append("账号修复已应用，刷新账号分组并重新预检。")
    autonomy_readiness_summary = autonomy_readiness_summary if isinstance(autonomy_readiness_summary, dict) else {}
    for action in autonomy_readiness_summary.get("next_actions") or []:
        if action:
            next_actions.append(str(action))
    product_capability_summary = product_capability_summary if isinstance(product_capability_summary, dict) else {}
    for action in product_capability_summary.get("next_actions") or []:
        if action:
            next_actions.append(str(action))
    missing_artifacts = audit.get("missing_artifacts") if isinstance(audit.get("missing_artifacts"), list) else []
    if missing_artifacts:
        severity = "warning" if severity == "ok" else severity
        next_actions.append("补齐缺失证据产物，避免复盘链路不完整。")
    if not primary_blocker:
        primary_blocker = "没有记录明确阻断。"
    if not next_actions:
        next_actions.append("归档证据包 Markdown 和 JSON 报告。")
    return {
        "schema_version": "reachops.operator_summary.v1",
        "title": title,
        "severity": severity,
        "status": summary.get("status", ""),
        "state": summary.get("state", ""),
        "primary_blocker": primary_blocker,
        "next_actions": list(dict.fromkeys(next_actions))[:8],
        "proof": {
            "existing_artifact_count": int(audit.get("existing_artifact_count") or 0),
            "missing_artifact_count": len(missing_artifacts),
            "timeline_count": int(audit.get("timeline_count") or 0),
            "repair_decision_count": int(repair_summary.get("decision_count") or 0),
            "risk_gate_decision_count": int(risk_summary.get("decision_count") or 0),
            "risk_policy_block_count": int(risk_policy_summary.get("policy_block_count") or 0),
            "risk_policy_duplicate_text_block_count": int(risk_policy_summary.get("duplicate_text_block_count") or 0),
            "page_state_snapshot_count": int(page_state_summary.get("snapshot_count") or 0),
            "page_state_repair_all_covered": bool(page_state_repair_coverage.get("all_page_states_covered")),
            "page_state_repair_uncovered_count": int(page_state_repair_coverage.get("uncovered_count") or 0),
            "control_event_count": int(control_summary.get("event_count") or 0),
            "offline_policy_candidate_count": int(policy_candidates.get("candidate_count") or 0),
            "offline_policy_review_count": int(policy_review_summary.get("review_count") or 0),
            "offline_policy_approved_count": int(policy_review_summary.get("approved_count") or 0),
            "offline_policy_runtime_auto_apply_count": int(policy_review_summary.get("runtime_auto_apply_count") or 0),
            "offline_policy_release_ready_count": int(policy_release_proposal.get("ready_for_release_count") or 0),
            "offline_policy_release_runtime_auto_apply_count": int(
                policy_release_proposal.get("runtime_auto_apply_count") or 0
            ),
            "account_repair_error_group_count": int(account_repair_summary.get("error_group_count") or 0),
            "account_repair_hard_blocker_profile_count": int(account_repair_summary.get("hard_blocker_profile_count") or 0),
            "account_repair_manual_apply_required": bool(account_repair_summary.get("manual_apply_required", True)),
            "account_repair_hard_blocker_only": bool(account_repair_summary.get("hard_blocker_only", True)),
            "account_repair_no_submit": bool(account_repair_summary.get("no_submit", True)),
            "autonomy_ready": bool(autonomy_readiness_summary.get("ready", False)),
            "autonomy_failed_count": int(autonomy_readiness_summary.get("failed_count") or 0),
            "product_capability_ready": bool(product_capability_summary.get("ready", False)),
            "product_capability_failed_count": int(product_capability_summary.get("failed_count") or 0),
            "ai_usage_audit_status": ai_usage_summary.get("audit_status", ""),
            "execution_phase_ai_call_count": int(ai_usage_summary.get("execution_phase_ai_call_count") or 0),
            "execution_phase_token_estimate": int(ai_usage_summary.get("execution_phase_token_estimate") or 0),
        },
        "no_ai_token_used": True,
    }


def build_evidence_bundle(
    *,
    base_dir: str | Path,
    execution_plan_path: str = "",
    run_session_path: str = "",
    result_path: str = "",
    log_path: str = "",
    offline_learning_path: str = "",
    extra_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan = read_execution_plan(execution_plan_path) if execution_plan_path and Path(execution_plan_path).is_file() else {}
    run_session = read_run_session(run_session_path) if run_session_path and Path(run_session_path).is_file() else {}
    result = _read_json(result_path) if result_path else {}
    effective_log_path = log_path or _safe_text(result.get("log_path") or (run_session.get("evidence") or {}).get("log_path"))
    log_lines = _read_lines(effective_log_path)
    learning_summary = summarize_offline_learning(offline_learning_path, limit=12) if offline_learning_path else {}
    page_state_artifacts = collect_page_state_artifacts(run_session, result)
    offline_learning_artifacts = collect_offline_learning_artifacts(learning_summary)
    account_repair_artifacts = collect_account_repair_artifacts(base_dir)
    artifacts = collect_evidence_artifacts(
        execution_plan_path=execution_plan_path or _safe_text(run_session.get("execution_plan_path")),
        run_session_path=run_session_path,
        result_path=result_path,
        log_path=effective_log_path,
        offline_learning_path=offline_learning_path,
        extra_artifacts=list(extra_artifacts or []) + page_state_artifacts + offline_learning_artifacts + account_repair_artifacts,
    )
    plan_id = _safe_text(plan.get("plan_id") or run_session.get("plan_id") or (result.get("execution_plan") or {}).get("plan_id"))
    session_id = _safe_text(run_session.get("session_id") or Path(run_session_path).stem if run_session_path else "")
    repair_summary = build_repair_summary(run_session, result, log_lines)
    risk_summary = build_risk_summary(run_session, result, log_lines)
    operator_risk_gate_summary = build_operator_risk_gate_summary(run_session, result)
    risk_policy_summary = build_risk_policy_summary(risk_summary)
    page_state_summary = build_page_state_summary(run_session, result, log_lines)
    control_summary = build_control_summary(run_session, log_lines)
    run_recovery_summary = build_run_recovery_summary(run_session, result, log_lines, control_summary)
    run_session_health = build_run_session_health_summary(run_session)
    ai_usage_summary = build_ai_usage_summary(run_session, plan, log_lines)
    autonomous_execution_summary = build_autonomous_execution_summary(
        run_session,
        run_session_health,
        control_summary,
        ai_usage_summary,
        log_lines,
    )
    account_health_summary = build_account_health_summary(log_lines, run_session, result)
    account_repair_summary = build_account_repair_summary(base_dir)
    plan_runtime_contract = build_plan_runtime_contract_summary(plan, run_session, result)
    execution_runtime_contract = build_execution_runtime_contract_summary(plan, run_session)
    autonomous_preflight_forecast = build_autonomous_preflight_forecast_summary(plan)
    page_state_repair_coverage = build_page_state_repair_coverage()
    audit = {
        "artifact_count": len(artifacts),
        "existing_artifact_count": len([row for row in artifacts if row.get("exists")]),
        "missing_artifacts": [row for row in artifacts if not row.get("exists")],
        "timeline_count": 0,
        "offline_learning_record_count": int(learning_summary.get("record_count") or 0),
        "offline_policy_candidate_count": int((learning_summary.get("policy_candidates") or {}).get("candidate_count") or 0),
        "offline_policy_review_count": int((learning_summary.get("policy_review_summary") or {}).get("review_count") or 0),
        "offline_policy_approved_count": int((learning_summary.get("policy_review_summary") or {}).get("approved_count") or 0),
        "offline_policy_runtime_auto_apply_count": int(
            (learning_summary.get("policy_review_summary") or {}).get("runtime_auto_apply_count") or 0
        ),
        "offline_policy_release_ready_count": int(
            (learning_summary.get("policy_release_proposal") or {}).get("ready_for_release_count") or 0
        ),
        "offline_policy_release_runtime_auto_apply_count": int(
            (learning_summary.get("policy_release_proposal") or {}).get("runtime_auto_apply_count") or 0
        ),
        "repair_decision_count": int(repair_summary.get("decision_count") or 0),
        "page_state_repair_coverage_state_count": int(page_state_repair_coverage.get("state_count") or 0),
        "page_state_repair_coverage_uncovered_count": int(page_state_repair_coverage.get("uncovered_count") or 0),
        "page_state_repair_all_covered": bool(page_state_repair_coverage.get("all_page_states_covered")),
        "risk_gate_decision_count": int(risk_summary.get("decision_count") or 0),
        "operator_risk_gate_row_count": int(operator_risk_gate_summary.get("row_count") or 0),
        "operator_risk_gate_blocked_count": int(operator_risk_gate_summary.get("blocked_count") or 0),
        "risk_policy_block_count": int(risk_policy_summary.get("policy_block_count") or 0),
        "risk_policy_duplicate_text_block_count": int(risk_policy_summary.get("duplicate_text_block_count") or 0),
        "page_state_snapshot_count": int(page_state_summary.get("snapshot_count") or 0),
        "control_event_count": int(control_summary.get("event_count") or 0),
        "run_recovery_count": int(run_recovery_summary.get("recovery_count") or 0),
        "run_recovery_recovered": bool(run_recovery_summary.get("recovered")),
        "run_recovery_reason": run_recovery_summary.get("latest_reason", ""),
        "account_health_event_count": int(account_health_summary.get("event_count") or 0),
        "account_health_cooldown_event_count": int(account_health_summary.get("cooldown_event_count") or 0),
        "page_state_artifact_count": len(page_state_artifacts),
        "page_state_screenshot_artifact_count": len([row for row in page_state_artifacts if row.get("kind") == "page_state_screenshot"]),
        "page_state_sidecar_artifact_count": len([row for row in page_state_artifacts if row.get("kind") == "page_state_sidecar"]),
        "offline_learning_artifact_count": len(offline_learning_artifacts),
        "account_repair_artifact_count": len(account_repair_artifacts),
        "account_repair_error_group_count": int(account_repair_summary.get("error_group_count") or 0),
        "account_repair_pending_recheck": bool(account_repair_summary.get("pending_recheck")),
        "account_repair_manual_apply_required": bool(account_repair_summary.get("manual_apply_required", True)),
        "account_repair_hard_blocker_only": bool(account_repair_summary.get("hard_blocker_only", True)),
        "account_repair_no_browser_started": bool(account_repair_summary.get("no_browser_started", True)),
        "account_repair_no_submit": bool(account_repair_summary.get("no_submit", True)),
        "execution_plan_contract_present": bool(plan_runtime_contract.get("contract_schema_version")),
        "execution_plan_contract_plan_id_matches": bool(plan_runtime_contract.get("plan_id_matches")),
        "execution_plan_contract_fingerprint_matches": bool(plan_runtime_contract.get("plan_fingerprint_matches")),
        "execution_plan_runtime_after_fingerprint_present": bool(plan_runtime_contract.get("runtime_after_fingerprint_present")),
        "execution_plan_contract_ignored_cli_args": bool(plan_runtime_contract.get("cli_args_ignored_for_plan_fields")),
        "execution_runtime_contract_present": bool(execution_runtime_contract.get("present")),
        "execution_runtime_contract_local_program": bool(execution_runtime_contract.get("local_program_executor")),
        "execution_runtime_contract_ai_control_surface_only": bool(
            execution_runtime_contract.get("ai_console_control_surface_only")
        ),
        "execution_runtime_contract_ai_calls_disallowed": bool(
            execution_runtime_contract.get("execution_phase_ai_calls_disallowed")
        ),
        "execution_runtime_contract_ai_usage_policy_matches": bool(
            execution_runtime_contract.get("ai_usage_policy_matches_contract")
        ),
        "execution_runtime_contract_evidence_required": bool(
            execution_runtime_contract.get("page_state_evidence_required")
            and execution_runtime_contract.get("evidence_bundle_required")
        ),
        "autonomous_preflight_forecast_exists": bool(autonomous_preflight_forecast.get("exists")),
        "autonomous_preflight_forecast_ready": bool(autonomous_preflight_forecast.get("ready")),
        "autonomous_preflight_repair_route_count": int(autonomous_preflight_forecast.get("repair_route_count") or 0),
        "autonomous_preflight_evidence_requirement_count": int(autonomous_preflight_forecast.get("evidence_requirement_count") or 0),
        "ai_usage_audit_status": ai_usage_summary.get("audit_status", ""),
        "execution_phase_ai_call_count": int(ai_usage_summary.get("execution_phase_ai_call_count") or 0),
        "execution_phase_token_estimate": int(ai_usage_summary.get("execution_phase_token_estimate") or 0),
        "no_ai_token_during_execution": bool(ai_usage_summary.get("no_ai_token_during_execution", True)),
        "autonomous_observed_state_count": int(autonomous_execution_summary.get("observed_state_count") or 0),
        "autonomous_state_history_count": int(autonomous_execution_summary.get("state_history_count") or 0),
        "autonomous_valid_state_transitions": bool(autonomous_execution_summary.get("valid_state_transitions")),
        "autonomous_state_transition_violation_count": int(
            autonomous_execution_summary.get("state_transition_violation_count") or 0
        ),
        "autonomous_core_ready": bool(autonomous_execution_summary.get("autonomous_core_ready")),
        "autonomous_missing_core_states": autonomous_execution_summary.get("missing_core_states") or [],
    }
    outcome = outcome_summary(plan, run_session, result)
    timeline = build_timeline(log_lines, run_session, result)
    audit["timeline_count"] = len(timeline)
    autonomous_preflight_reconciliation = build_autonomous_preflight_reconciliation(
        forecast=autonomous_preflight_forecast,
        repair_summary=repair_summary,
        risk_summary=risk_summary,
        page_state_summary=page_state_summary,
        timeline=timeline,
    )
    audit["autonomous_preflight_reconciliation_status"] = autonomous_preflight_reconciliation.get("status", "")
    audit["autonomous_preflight_matched_route_count"] = int(
        autonomous_preflight_reconciliation.get("matched_route_count") or 0
    )
    audit["autonomous_preflight_unobserved_route_count"] = int(
        autonomous_preflight_reconciliation.get("unobserved_route_count") or 0
    )
    audit["autonomous_preflight_risk_gate_aligned"] = bool(
        autonomous_preflight_reconciliation.get("risk_gate_aligned")
    )
    autonomy_readiness_summary = build_autonomy_readiness_summary(
        plan_runtime_contract=plan_runtime_contract,
        ai_usage_summary=ai_usage_summary,
        repair_summary=repair_summary,
        risk_summary=risk_summary,
        page_state_summary=page_state_summary,
        control_summary=control_summary,
        autonomous_execution_summary=autonomous_execution_summary,
        run_session_health=run_session_health,
        account_health_summary=account_health_summary,
        account_repair_summary=account_repair_summary,
        offline_learning=learning_summary,
        page_state_repair_coverage=page_state_repair_coverage,
        audit=audit,
    )
    product_capability_summary = build_product_capability_summary(
        plan_runtime_contract=plan_runtime_contract,
        run_session_health=run_session_health,
        ai_usage_summary=ai_usage_summary,
        autonomy_readiness_summary=autonomy_readiness_summary,
        repair_summary=repair_summary,
        risk_summary=risk_summary,
        page_state_summary=page_state_summary,
        control_summary=control_summary,
        autonomous_execution_summary=autonomous_execution_summary,
        account_health_summary=account_health_summary,
        account_repair_summary=account_repair_summary,
        offline_learning=learning_summary,
        audit=audit,
    )
    product_development_goals = build_product_development_goals(product_capability_summary)
    audit["autonomy_ready"] = bool(autonomy_readiness_summary.get("ready"))
    audit["autonomy_failed_count"] = int(autonomy_readiness_summary.get("failed_count") or 0)
    audit["product_capability_ready"] = bool(product_capability_summary.get("ready"))
    audit["product_capability_failed_count"] = int(product_capability_summary.get("failed_count") or 0)
    audit["product_development_goal_ready"] = bool(product_development_goals.get("ready"))
    audit["product_development_goal_stage_count"] = int(product_development_goals.get("stage_count") or 0)
    operator_summary = build_operator_summary(
        summary=outcome,
        audit=audit,
        repair_summary=repair_summary,
        risk_summary=risk_summary,
        risk_policy_summary=risk_policy_summary,
        page_state_summary=page_state_summary,
        control_summary=control_summary,
        offline_learning=learning_summary,
        account_repair_summary=account_repair_summary,
        ai_usage_summary=ai_usage_summary,
        autonomy_readiness_summary=autonomy_readiness_summary,
        product_capability_summary=product_capability_summary,
        page_state_repair_coverage=page_state_repair_coverage,
    )
    return {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "bundle_id": f"bundle_{session_id or plan_id or hashlib.sha256(utc_now_iso().encode('utf-8')).hexdigest()[:12]}",
        "generated_at": utc_now_iso(),
        "plan_id": plan_id,
        "session_id": session_id,
        "summary": outcome,
        "operator_summary": operator_summary,
        "execution_plan": {
            "path": execution_plan_path or _safe_text(run_session.get("execution_plan_path")),
            "schema_version": plan.get("schema_version", ""),
            "mode": plan.get("mode", ""),
            "target": plan.get("target", ""),
        },
        "run_session": {
            "path": run_session_path,
            "schema_version": run_session.get("schema_version", ""),
            "state": run_session.get("state", ""),
            "status": run_session.get("status", ""),
            "checkpoint": run_session.get("checkpoint") or {},
            "session_health": run_session_health,
            "control": run_session.get("control") or {},
            "control_history": run_session.get("control_history") or [],
            "state_history": run_session.get("state_history") or [],
        },
        "result": {
            "path": result_path,
            "status": result.get("status", ""),
            "generated_at": result.get("generated_at", ""),
        },
        "artifacts": artifacts,
        "timeline": timeline,
        "tail": log_lines[-80:],
        "repair_summary": repair_summary,
        "risk_summary": risk_summary,
        "operator_risk_gate_summary": operator_risk_gate_summary,
        "risk_policy_summary": risk_policy_summary,
        "page_state_summary": page_state_summary,
        "control_summary": control_summary,
        "run_recovery_summary": run_recovery_summary,
        "run_session_health": run_session_health,
        "autonomous_execution_summary": autonomous_execution_summary,
        "account_health_summary": account_health_summary,
        "account_repair_summary": account_repair_summary,
        "page_state_repair_coverage": page_state_repair_coverage,
        "plan_runtime_contract": plan_runtime_contract,
        "execution_runtime_contract": execution_runtime_contract,
        "autonomous_preflight_forecast": autonomous_preflight_forecast,
        "autonomous_preflight_reconciliation": autonomous_preflight_reconciliation,
        "autonomy_readiness_summary": autonomy_readiness_summary,
        "product_capability_summary": product_capability_summary,
        "product_development_goals": product_development_goals,
        "ai_usage_summary": ai_usage_summary,
        "offline_learning": learning_summary,
        "audit": audit,
    }


def write_evidence_bundle(bundle: dict[str, Any], path: str | Path, latest_path: str | Path | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if latest_path:
        latest = Path(latest_path)
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def render_evidence_markdown(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    operator_summary = bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {}
    artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), list) else []
    timeline = bundle.get("timeline") if isinstance(bundle.get("timeline"), list) else []
    lines = [
        "# ReachOps Evidence Bundle",
        "",
        f"- Bundle: {bundle.get('bundle_id', '-')}",
        f"- Plan: {bundle.get('plan_id', '-')}",
        f"- Session: {bundle.get('session_id', '-')}",
        f"- Status: {summary.get('status', '-')}",
        f"- State: {summary.get('state', '-')}",
        f"- Target: {summary.get('target', '-')}",
        f"- Mode: {summary.get('mode', '-')}",
        f"- Profile group: {summary.get('profile_group', '-')}",
        f"- No AI token during execution: {summary.get('no_ai_token_during_execution') is True}",
        "",
        "## Operator Summary",
        "",
        f"- Title: {operator_summary.get('title') or '-'}",
        f"- Severity: {operator_summary.get('severity') or '-'}",
        f"- Primary blocker: {operator_summary.get('primary_blocker') or '-'}",
        f"- No AI token used: {operator_summary.get('no_ai_token_used') is True}",
        "",
        "### Next Actions",
        "",
    ]
    for action in operator_summary.get("next_actions") or ["归档证据包。"]:
        lines.append(f"- {action}")
    autonomy_readiness = bundle.get("autonomy_readiness_summary") if isinstance(bundle.get("autonomy_readiness_summary"), dict) else {}
    if autonomy_readiness:
        lines.extend(
            [
                "",
                "## Autonomy Readiness Summary",
                "",
                f"- Ready: {str(bool(autonomy_readiness.get('ready'))).lower()}",
                f"- Passed checks: {autonomy_readiness.get('passed_count', 0)}",
                f"- Failed checks: {autonomy_readiness.get('failed_count', 0)}",
            ]
        )
        for row in autonomy_readiness.get("checks") or []:
            if isinstance(row, dict):
                status = "pass" if row.get("passed") else "fail"
                lines.append(f"- {row.get('name')}: {status} ({row.get('evidence') or '-'})")
    product_capability = bundle.get("product_capability_summary") if isinstance(bundle.get("product_capability_summary"), dict) else {}
    if product_capability:
        lines.extend(
            [
                "",
                "## Product Capability Summary",
                "",
                f"- Ready: {str(bool(product_capability.get('ready'))).lower()}",
                f"- Passed phases: {product_capability.get('passed_count', 0)}",
                f"- Failed phases: {product_capability.get('failed_count', 0)}",
            ]
        )
        for row in product_capability.get("phases") or []:
            if isinstance(row, dict):
                status = "pass" if row.get("passed") else "fail"
                evidence = ", ".join(str(item) for item in row.get("evidence", []) if item)
                lines.append(f"- {row.get('key')}: {status} ({evidence or '-'})")
    development_goals = bundle.get("product_development_goals") if isinstance(bundle.get("product_development_goals"), dict) else {}
    if development_goals:
        focus = development_goals.get("current_focus") if isinstance(development_goals.get("current_focus"), dict) else {}
        lines.extend(
            [
                "",
                "## Product Development Goals",
                "",
                f"- Ready: {str(bool(development_goals.get('ready'))).lower()}",
                f"- Stages: {development_goals.get('completed_stage_count', 0)}/{development_goals.get('stage_count', 0)} completed",
                f"- Current focus: {focus.get('title') or '-'}",
                f"- Goal: {development_goals.get('goal_statement') or '-'}",
            ]
        )
        for row in development_goals.get("stages") or []:
            if isinstance(row, dict):
                status = "done" if row.get("passed") else "next"
                lines.append(f"- {row.get('stage')}. {row.get('title')}: {status} / {row.get('next_action') or '-'}")
    lines.extend(
        [
            "",
        "## Why",
        "",
        summary.get("reason") or ("Execution completed." if summary.get("completed") else "No blocker reason recorded."),
        "",
        "## Artifacts",
        "",
        ]
    )
    for artifact in artifacts:
        state = "exists" if artifact.get("exists") else "missing"
        lines.append(f"- {artifact.get('label') or artifact.get('kind')}: {state} - {artifact.get('path') or '-'}")
    plan_runtime_contract = bundle.get("plan_runtime_contract") if isinstance(bundle.get("plan_runtime_contract"), dict) else {}
    if plan_runtime_contract:
        lines.extend(
            [
                "",
                "## ExecutionPlan Runtime Contract",
                "",
                f"- Contract schema: {plan_runtime_contract.get('contract_schema_version') or '-'}",
                f"- Source: {plan_runtime_contract.get('source') or '-'}",
                f"- Plan ID matches: {str(bool(plan_runtime_contract.get('plan_id_matches'))).lower()}",
                f"- Plan fingerprint matches: {str(bool(plan_runtime_contract.get('plan_fingerprint_matches'))).lower()}",
                f"- Runtime after fingerprint present: {str(bool(plan_runtime_contract.get('runtime_after_fingerprint_present'))).lower()}",
                f"- CLI args ignored for plan fields: {str(bool(plan_runtime_contract.get('cli_args_ignored_for_plan_fields'))).lower()}",
                f"- No AI token used: {str(bool(plan_runtime_contract.get('no_ai_token_used'))).lower()}",
            ]
        )
    execution_runtime_contract = (
        bundle.get("execution_runtime_contract") if isinstance(bundle.get("execution_runtime_contract"), dict) else {}
    )
    if execution_runtime_contract:
        lines.extend(
            [
                "",
                "## Execution Runtime Contract",
                "",
                f"- Contract schema: {execution_runtime_contract.get('contract_schema_version') or '-'}",
                f"- Executor: {execution_runtime_contract.get('executor') or '-'}",
                f"- Control surface: {execution_runtime_contract.get('control_surface') or '-'}",
                f"- AI control surface only: {str(bool(execution_runtime_contract.get('ai_console_control_surface_only'))).lower()}",
                f"- Execution AI calls disallowed: {str(bool(execution_runtime_contract.get('execution_phase_ai_calls_disallowed'))).lower()}",
                f"- AI usage policy matches contract: {str(bool(execution_runtime_contract.get('ai_usage_policy_matches_contract'))).lower()}",
                f"- Page state evidence required: {str(bool(execution_runtime_contract.get('page_state_evidence_required'))).lower()}",
                f"- Evidence bundle required: {str(bool(execution_runtime_contract.get('evidence_bundle_required'))).lower()}",
            ]
        )
    autonomous_preflight = bundle.get("autonomous_preflight_forecast") if isinstance(bundle.get("autonomous_preflight_forecast"), dict) else {}
    if autonomous_preflight:
        lines.extend(
            [
                "",
                "## Autonomous Preflight Forecast",
                "",
                f"- Exists: {str(bool(autonomous_preflight.get('exists'))).lower()}",
                f"- Source: {autonomous_preflight.get('source') or '-'}",
                f"- Persisted in plan: {str(bool(autonomous_preflight.get('persisted'))).lower()}",
                f"- Forecast schema: {autonomous_preflight.get('forecast_schema_version') or '-'}",
                f"- Status: {autonomous_preflight.get('status') or '-'}",
                f"- Start allowed: {str(bool(autonomous_preflight.get('start_allowed'))).lower()}",
                f"- Repair routes: {autonomous_preflight.get('repair_route_count', 0)}",
                f"- Evidence requirements: {autonomous_preflight.get('evidence_requirement_count', 0)}",
                f"- No AI token used: {str(bool(autonomous_preflight.get('no_ai_token_used'))).lower()}",
            ]
        )
        states = autonomous_preflight.get("predicted_state_sequence") if isinstance(autonomous_preflight.get("predicted_state_sequence"), list) else []
        if states:
            lines.append(f"- State chain: {' -> '.join(str(item) for item in states[:10])}")
        for row in (autonomous_preflight.get("repair_routes") or [])[:8]:
            if isinstance(row, dict):
                lines.append(f"- Repair route: {row.get('state') or '-'} -> {row.get('action') or '-'} / {row.get('terminal_outcome') or '-'}")
        for item in (autonomous_preflight.get("evidence_requirements") or [])[:8]:
            lines.append(f"- Evidence: {item}")
    autonomous_preflight_reconciliation = (
        bundle.get("autonomous_preflight_reconciliation")
        if isinstance(bundle.get("autonomous_preflight_reconciliation"), dict)
        else {}
    )
    if autonomous_preflight_reconciliation:
        lines.extend(
            [
                "",
                "## Autonomous Preflight Reconciliation",
                "",
                f"- Status: {autonomous_preflight_reconciliation.get('status') or '-'}",
                f"- Forecast source: {autonomous_preflight_reconciliation.get('forecast_source') or '-'}",
                f"- Forecast persisted: {str(bool(autonomous_preflight_reconciliation.get('forecast_persisted'))).lower()}",
                f"- Matched routes: {autonomous_preflight_reconciliation.get('matched_route_count', 0)}",
                f"- Unobserved routes: {autonomous_preflight_reconciliation.get('unobserved_route_count', 0)}",
                f"- Risk gate aligned: {str(bool(autonomous_preflight_reconciliation.get('risk_gate_aligned'))).lower()}",
                f"- No AI token used: {str(bool(autonomous_preflight_reconciliation.get('no_ai_token_used'))).lower()}",
            ]
        )
        actual_states = autonomous_preflight_reconciliation.get("actual_page_states")
        if isinstance(actual_states, list) and actual_states:
            lines.append("- Actual page states: " + ", ".join(str(item) for item in actual_states[:8]))
        risk_reasons = autonomous_preflight_reconciliation.get("actual_risk_reasons")
        if isinstance(risk_reasons, list) and risk_reasons:
            lines.append("- Actual risk reasons: " + ", ".join(str(item) for item in risk_reasons[:8]))
        for row in (autonomous_preflight_reconciliation.get("matched_routes") or [])[:8]:
            if isinstance(row, dict):
                reasons = ", ".join(str(item) for item in row.get("match_reasons", []) if item)
                lines.append(
                    f"- Matched route: {row.get('state') or '-'} -> {row.get('action') or '-'}"
                    f" ({reasons or '-'})"
                )
        for row in (autonomous_preflight_reconciliation.get("unobserved_routes") or [])[:5]:
            if isinstance(row, dict):
                lines.append(f"- Unobserved route: {row.get('state') or '-'} -> {row.get('action') or '-'}")
    lines.extend(["", "## Timeline", ""])
    for event in timeline[-80:]:
        lines.append(f"- {event.get('stage', '-')}: {event.get('message', '-')}")
    repair_summary = bundle.get("repair_summary") if isinstance(bundle.get("repair_summary"), dict) else {}
    if repair_summary:
        repair_machine_actions = _markdown_repair_machine_actions(repair_summary)
        lines.extend(
            [
                "",
                "## Repair Summary",
                "",
                f"- Decisions: {repair_summary.get('decision_count', 0)}",
                f"- Audit events: {repair_summary.get('audit_event_count', 0)}",
                f"- Retries: {repair_summary.get('retry_count', 0)}",
                f"- Switch profile: {repair_summary.get('switch_profile_count', 0)}",
                f"- Cooldown profile: {repair_summary.get('cooldown_profile_count', 0)}",
                f"- Degraded: {repair_summary.get('degrade_count', 0)}",
                f"- Blocked by repair: {repair_summary.get('block_count', 0)}",
                f"- Repair step results: {repair_summary.get('repair_step_result_count', 0)}",
                f"- Repair steps executed locally: {repair_summary.get('repair_step_executed_count', 0)}",
                f"- Repair steps needing browser executor: {repair_summary.get('repair_step_browser_required_count', 0)}",
            ]
        )
        if repair_machine_actions:
            lines.extend(["", "### Repair Machine Actions", ""])
            lines.extend(repair_machine_actions)
    risk_summary = bundle.get("risk_summary") if isinstance(bundle.get("risk_summary"), dict) else {}
    if risk_summary:
        risk_machine_actions = _markdown_risk_machine_actions(risk_summary)
        lines.extend(
            [
                "",
                "## Risk Summary",
                "",
                f"- Decisions: {risk_summary.get('decision_count', 0)}",
                f"- Allowed: {risk_summary.get('allowed_count', 0)}",
                f"- Blocked: {risk_summary.get('blocked_count', 0)}",
                f"- Authorization blocks: {risk_summary.get('authorization_block_count', 0)}",
                f"- Quota blocks: {risk_summary.get('quota_block_count', 0)}",
                f"- Rate limit blocks: {risk_summary.get('rate_limit_block_count', 0)}",
                f"- Human review required: {risk_summary.get('human_review_required_count', 0)}",
                f"- Risk actions: {risk_summary.get('risk_action_count', 0)}",
                f"- High risk decisions: {risk_summary.get('high_risk_count', 0)}",
            ]
        )
        if risk_machine_actions:
            lines.extend(["", "### Risk Gate Machine Actions", ""])
            lines.extend(risk_machine_actions)
    operator_risk_gate_summary = (
        bundle.get("operator_risk_gate_summary")
        if isinstance(bundle.get("operator_risk_gate_summary"), dict)
        else {}
    )
    if operator_risk_gate_summary:
        lines.extend(
            [
                "",
                "## Operator Risk Gate Summary",
                "",
                f"- Rows: {operator_risk_gate_summary.get('row_count', 0)}",
                f"- Blocked: {operator_risk_gate_summary.get('blocked_count', 0)}",
                f"- Allowed: {operator_risk_gate_summary.get('allowed_count', 0)}",
                f"- Primary reason: {operator_risk_gate_summary.get('primary_reason') or '-'}",
                f"- Primary next step: {operator_risk_gate_summary.get('primary_next_step') or '-'}",
            ]
        )
        for row in (operator_risk_gate_summary.get("rows") or [])[:8]:
            if isinstance(row, dict):
                lines.append(
                    "- "
                    f"{row.get('target_username') or '-'} / "
                    f"{row.get('action_type') or '-'} / "
                    f"{row.get('profile_id') or '-'} / "
                    f"{row.get('risk_gate_summary') or '-'} / "
                    f"{row.get('next_step') or '-'}"
                )
    risk_policy_summary = bundle.get("risk_policy_summary") if isinstance(bundle.get("risk_policy_summary"), dict) else {}
    if risk_policy_summary:
        lines.extend(
            [
                "",
                "## Risk Policy Summary",
                "",
                f"- Policy blocks: {risk_policy_summary.get('policy_block_count', 0)}",
                f"- Authorization blocks: {risk_policy_summary.get('authorization_block_count', 0)}",
                f"- Quota blocks: {risk_policy_summary.get('quota_block_count', 0)}",
                f"- Rate limit blocks: {risk_policy_summary.get('rate_limit_block_count', 0)}",
                f"- Duplicate text blocks: {risk_policy_summary.get('duplicate_text_block_count', 0)}",
                f"- Publish profile blocks: {risk_policy_summary.get('publish_profile_block_count', 0)}",
                f"- High risk review blocks: {risk_policy_summary.get('high_risk_review_block_count', 0)}",
            ]
        )
        for action in risk_policy_summary.get("next_actions") or []:
            lines.append(f"- {action}")
    account_health_summary = bundle.get("account_health_summary") if isinstance(bundle.get("account_health_summary"), dict) else {}
    if account_health_summary:
        lines.extend(
            [
                "",
                "## Account Health Summary",
                "",
                f"- Events: {account_health_summary.get('event_count', 0)}",
                f"- Cooldown events: {account_health_summary.get('cooldown_event_count', 0)}",
                f"- Forced cooldown: {account_health_summary.get('forced_cooldown_count', 0)}",
                f"- Consecutive failure cooldown: {account_health_summary.get('consecutive_failure_cooldown_count', 0)}",
            ]
        )
    account_repair_summary = bundle.get("account_repair_summary") if isinstance(bundle.get("account_repair_summary"), dict) else {}
    if account_repair_summary:
        lines.extend(
            [
                "",
                "## Account Repair Summary",
                "",
                f"- Plan exists: {str(bool(account_repair_summary.get('plan_exists'))).lower()}",
                f"- Error groups: {account_repair_summary.get('error_group_count', 0)}",
                f"- Hard blocker profiles: {account_repair_summary.get('hard_blocker_profile_count', 0)}",
                f"- Apply status: {account_repair_summary.get('apply_status') or '-'}",
                f"- Pending recheck: {str(bool(account_repair_summary.get('pending_recheck'))).lower()}",
                f"- Manual apply required: {str(bool(account_repair_summary.get('manual_apply_required', True))).lower()}",
                f"- Hard blocker only: {str(bool(account_repair_summary.get('hard_blocker_only', True))).lower()}",
                f"- No browser started: {str(bool(account_repair_summary.get('no_browser_started', True))).lower()}",
                f"- No submit: {str(bool(account_repair_summary.get('no_submit', True))).lower()}",
            ]
        )
        for row in (account_repair_summary.get("error_groups") or [])[:5]:
            if isinstance(row, dict):
                lines.append(
                    f"- {row.get('error', '-')} count={row.get('count', 0)} action={row.get('recommended_action') or '-'}"
                )
    page_state_summary = bundle.get("page_state_summary") if isinstance(bundle.get("page_state_summary"), dict) else {}
    if page_state_summary:
        lines.extend(
            [
                "",
                "## Page State Summary",
                "",
                f"- Snapshots: {page_state_summary.get('snapshot_count', 0)}",
                f"- Blocking states: {page_state_summary.get('blocking_count', 0)}",
                f"- Unknown states: {page_state_summary.get('unknown_count', 0)}",
                f"- Login required: {page_state_summary.get('login_required_count', 0)}",
                f"- Captcha: {page_state_summary.get('captcha_count', 0)}",
            ]
        )
        state_counts = page_state_summary.get("state_counts") if isinstance(page_state_summary.get("state_counts"), dict) else {}
        if state_counts:
            lines.extend(["", "### Page State Counts", ""])
            for state, count in sorted(state_counts.items()):
                lines.append(f"- {state}: {count}")
    control_summary = bundle.get("control_summary") if isinstance(bundle.get("control_summary"), dict) else {}
    if control_summary:
        lines.extend(
            [
                "",
                "## Control Summary",
                "",
                f"- Events: {control_summary.get('event_count', 0)}",
                f"- Pauses: {control_summary.get('pause_count', 0)}",
                f"- Resumes: {control_summary.get('resume_count', 0)}",
                f"- Stops: {control_summary.get('stop_count', 0)}",
                f"- Recoveries: {control_summary.get('recovery_count', 0)}",
                f"- Failed controls: {control_summary.get('failed_control_count', 0)}",
                f"- Last action: {control_summary.get('last_action') or '-'}",
                f"- Current paused: {str(bool(control_summary.get('current_paused'))).lower()}",
            ]
        )
    run_recovery_summary = bundle.get("run_recovery_summary") if isinstance(bundle.get("run_recovery_summary"), dict) else {}
    if run_recovery_summary:
        lines.extend(
            [
                "",
                "## Run Recovery Summary",
                "",
                f"- Recovered: {str(bool(run_recovery_summary.get('recovered'))).lower()}",
                f"- Recovery count: {run_recovery_summary.get('recovery_count', 0)}",
                f"- Latest reason: {run_recovery_summary.get('latest_reason') or '-'}",
                f"- Result error: {run_recovery_summary.get('result_error') or '-'}",
                f"- Terminal state: {run_recovery_summary.get('terminal_state') or '-'}",
                f"- Last stage: {run_recovery_summary.get('last_stage') or '-'}",
                f"- Runtime state inferred: {run_recovery_summary.get('runtime_state_inferred') or '-'}",
                f"- Checkpoint log lines: {run_recovery_summary.get('checkpoint_log_line_count', 0)}",
                f"- No AI token used: {str(bool(run_recovery_summary.get('no_ai_token_used'))).lower()}",
            ]
        )
    run_session_health = bundle.get("run_session_health") if isinstance(bundle.get("run_session_health"), dict) else {}
    if run_session_health:
        lines.extend(
            [
                "",
                "## Run Session Health",
                "",
                f"- Status: {run_session_health.get('status', '-')}",
                f"- State: {run_session_health.get('state', '-')}",
                f"- Stale: {str(bool(run_session_health.get('stale'))).lower()}",
                f"- Paused: {str(bool(run_session_health.get('paused'))).lower()}",
                f"- Terminal: {str(bool(run_session_health.get('terminal'))).lower()}",
                f"- Age seconds: {run_session_health.get('age_seconds', 0)}",
                f"- Last stage: {run_session_health.get('last_stage') or '-'}",
            ]
        )
    autonomous_execution_summary = bundle.get("autonomous_execution_summary") if isinstance(bundle.get("autonomous_execution_summary"), dict) else {}
    if autonomous_execution_summary:
        lines.extend(
            [
                "",
                "## Autonomous Execution Summary",
                "",
                f"- Core ready: {str(bool(autonomous_execution_summary.get('autonomous_core_ready'))).lower()}",
                f"- Observed states: {', '.join(autonomous_execution_summary.get('observed_states') or []) or '-'}",
                f"- Missing core states: {', '.join(autonomous_execution_summary.get('missing_core_states') or []) or '-'}",
                f"- Terminal observed: {str(bool(autonomous_execution_summary.get('terminal_state_observed'))).lower()}",
                f"- State history events: {autonomous_execution_summary.get('state_history_count', 0)}",
                f"- Valid state transitions: {str(bool(autonomous_execution_summary.get('valid_state_transitions', True))).lower()}",
                f"- State transition violations: {autonomous_execution_summary.get('state_transition_violation_count', 0)}",
                f"- Recovery events: {autonomous_execution_summary.get('recovery_event_count', 0)}",
                f"- Zero token: {str(bool(autonomous_execution_summary.get('zero_token'))).lower()}",
            ]
        )
    page_state_repair_coverage = (
        bundle.get("page_state_repair_coverage") if isinstance(bundle.get("page_state_repair_coverage"), dict) else {}
    )
    if page_state_repair_coverage:
        lines.extend(
            [
                "",
                "## Page State Repair Coverage",
                "",
                f"- All covered: {str(bool(page_state_repair_coverage.get('all_page_states_covered'))).lower()}",
                f"- Covered: {page_state_repair_coverage.get('covered_count', 0)}",
                f"- Uncovered: {page_state_repair_coverage.get('uncovered_count', 0)}",
            ]
        )
        for row in (page_state_repair_coverage.get("routes") or [])[:8]:
            if isinstance(row, dict):
                lines.append(
                    f"- {row.get('state', '-')} -> {row.get('action', '-')} "
                    f"outcome={row.get('terminal_outcome', '-')}"
                )
    ai_usage_summary = bundle.get("ai_usage_summary") if isinstance(bundle.get("ai_usage_summary"), dict) else {}
    if ai_usage_summary:
        lines.extend(
            [
                "",
                "## AI Usage Summary",
                "",
                f"- Audit status: {ai_usage_summary.get('audit_status', '-')}",
                f"- Execution AI calls: {ai_usage_summary.get('execution_phase_ai_call_count', 0)}",
                f"- Execution token estimate: {ai_usage_summary.get('execution_phase_token_estimate', 0)}",
                f"- Suspicious log events: {ai_usage_summary.get('suspicious_log_event_count', 0)}",
            ]
        )
    offline = bundle.get("offline_learning") if isinstance(bundle.get("offline_learning"), dict) else {}
    policy_candidates = offline.get("policy_candidates") if isinstance(offline.get("policy_candidates"), dict) else {}
    policy_review_summary = offline.get("policy_review_summary") if isinstance(offline.get("policy_review_summary"), dict) else {}
    policy_release_proposal = (
        offline.get("policy_release_proposal") if isinstance(offline.get("policy_release_proposal"), dict) else {}
    )
    if policy_candidates:
        lines.extend(
            [
                "",
                "## Offline Policy Candidates",
                "",
                f"- Candidates: {policy_candidates.get('candidate_count', 0)}",
                f"- Min occurrences: {policy_candidates.get('min_occurrences', 0)}",
                "- Auto apply: False",
                f"- Reviews: {policy_review_summary.get('review_count', 0)}",
                f"- Approved: {policy_review_summary.get('approved_count', 0)}",
                f"- Release ready: {policy_release_proposal.get('ready_for_release_count', 0)}",
                f"- Release gate: {policy_release_proposal.get('release_gate', 'code_or_policy_release_required')}",
                f"- Release runtime auto apply: {policy_release_proposal.get('runtime_auto_apply_count', 0)}",
            ]
        )
        for candidate in (policy_candidates.get("candidates") or [])[:5]:
            if isinstance(candidate, dict):
                lines.append(
                    f"- {candidate.get('candidate_state', '-')} -> {candidate.get('candidate_action', '-')} "
                    f"occurrences={candidate.get('occurrence_count', 0)} review=true"
                )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_repair_machine_actions(repair_summary: dict[str, Any]) -> list[str]:
    rows = repair_summary.get("audit_events") if isinstance(repair_summary.get("audit_events"), list) else []
    if not rows:
        rows = repair_summary.get("decisions") if isinstance(repair_summary.get("decisions"), list) else []
    output: list[str] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        steps = []
        for step in row.get("executable_steps") or []:
            if isinstance(step, dict):
                name = _safe_text(step.get("step"))
                if name:
                    details = []
                    if step.get("seconds"):
                        details.append(f"seconds={step.get('seconds')}")
                    if step.get("scope"):
                        details.append(f"scope={step.get('scope')}")
                    if step.get("to"):
                        details.append(f"to={step.get('to')}")
                    steps.append(f"{name}({', '.join(details)})" if details else name)
            elif step:
                steps.append(_safe_text(step))
        retry_after = int(row.get("retry_after_seconds") or 0)
        cooldown = int(row.get("cooldown_seconds") or 0)
        review = bool(row.get("requires_human_review"))
        action = _safe_text(row.get("repair_action") or row.get("action") or row.get("error_code") or "repair")
        suffix = []
        if retry_after:
            suffix.append(f"retry_after={retry_after}s")
        if cooldown:
            suffix.append(f"cooldown={cooldown}s")
        if review:
            suffix.append("human_review=true")
        body = ", ".join(steps) if steps else "no executable steps recorded"
        if suffix:
            body += f" | {'; '.join(suffix)}"
        output.append(f"- {action}: {body}")
    return output


def _markdown_risk_machine_actions(risk_summary: dict[str, Any]) -> list[str]:
    rows = risk_summary.get("decisions") if isinstance(risk_summary.get("decisions"), list) else []
    output: list[str] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        actions = []
        for action in row.get("risk_actions") or []:
            if isinstance(action, dict):
                name = _safe_text(action.get("step"))
                if name:
                    details = []
                    if action.get("target"):
                        details.append(f"target={action.get('target')}")
                    if action.get("scope"):
                        details.append(f"scope={action.get('scope')}")
                    if action.get("required") is not None:
                        details.append(f"required={str(bool(action.get('required'))).lower()}")
                    actions.append(f"{name}({', '.join(details)})" if details else name)
            elif action:
                actions.append(_safe_text(action))
        code = _safe_text(row.get("reason_code") or "risk_gate")
        allowed = str(bool(row.get("allowed"))).lower()
        review = str(bool(row.get("requires_human_review"))).lower()
        block = str(bool(row.get("block_execution"))).lower()
        body = ", ".join(actions) if actions else "no risk actions recorded"
        output.append(f"- {code}: allowed={allowed}; block_execution={block}; human_review={review}; actions={body}")
    return output


def write_evidence_markdown(bundle: dict[str, Any], path: str | Path, latest_path: str | Path | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render_evidence_markdown(bundle)
    target.write_text(text, encoding="utf-8")
    if latest_path:
        latest = Path(latest_path)
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(text, encoding="utf-8")
    return target
