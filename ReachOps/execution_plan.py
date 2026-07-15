# -*- coding: utf-8 -*-
"""Run-level ExecutionPlan model for ReachOps autonomous client runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PLAN_SCHEMA_VERSION = "reachops.execution_plan.v1"
AUTONOMOUS_PREFLIGHT_FORECAST_SCHEMA_VERSION = "reachops.autonomous_preflight_forecast.v1"
ALLOWED_PLAN_MODES = {"preflight", "collect", "live_comment"}
ALLOWED_PLAN_VOLUMES = {"quick", "standard", "stress"}

EXECUTION_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "reachops.execution_plan.v1",
    "title": "ReachOps ExecutionPlan",
    "type": "object",
    "required": [
        "schema_version",
        "target",
        "source_type",
        "mode",
        "profile_group",
        "limits",
        "authorization",
        "repair_policy",
        "risk_policy",
        "runtime_contract",
    ],
    "properties": {
        "schema_version": {"const": PLAN_SCHEMA_VERSION},
        "plan_id": {"type": "string"},
        "plan_fingerprint_sha256": {"type": "string"},
        "created_at": {"type": "string"},
        "target": {"type": "string", "minLength": 1},
        "source_type": {"type": "string"},
        "mode": {"enum": sorted(ALLOWED_PLAN_MODES)},
        "volume": {"enum": sorted(ALLOWED_PLAN_VOLUMES)},
        "profile_group": {"type": "string"},
        "limits": {"type": "object"},
        "authorization": {"type": "object"},
        "repair_policy": {"type": "object"},
        "risk_policy": {"type": "object"},
        "runtime_contract": {"type": "object"},
        "ui": {"type": "object"},
        "runtime": {"type": "object"},
    },
}


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text


def _safe_int(value: Any, default: int = 0, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    parsed = max(int(minimum), parsed)
    if maximum is not None:
        parsed = min(int(maximum), parsed)
    return parsed


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "确认", "已确认"}


def normalize_plan_mode(value: Any) -> str:
    mode = _clean_text(value, "preflight")
    return mode if mode in ALLOWED_PLAN_MODES else "preflight"


def normalize_plan_volume(value: Any) -> str:
    volume = _clean_text(value, "quick")
    return volume if volume in ALLOWED_PLAN_VOLUMES else "quick"


@dataclass
class ExecutionPlan:
    target: str
    source_type: str = "auto"
    mode: str = "preflight"
    profile_group: str = "United States"
    volume: str = "quick"
    limits: dict[str, Any] = field(default_factory=dict)
    authorization: dict[str, Any] = field(default_factory=dict)
    repair_policy: dict[str, Any] = field(default_factory=dict)
    risk_policy: dict[str, Any] = field(default_factory=dict)
    runtime_contract: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    schema_version: str = PLAN_SCHEMA_VERSION
    plan_id: str = ""
    plan_fingerprint_sha256: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = normalize_plan_mode(payload.get("mode"))
        payload["volume"] = normalize_plan_volume(payload.get("volume"))
        payload["target"] = _clean_text(payload.get("target"))
        payload["source_type"] = _clean_text(payload.get("source_type"), "auto") or "auto"
        payload["profile_group"] = _clean_text(payload.get("profile_group"), "United States") or "United States"
        payload["limits"] = dict(payload.get("limits") or {})
        payload["authorization"] = dict(payload.get("authorization") or {})
        payload["repair_policy"] = dict(payload.get("repair_policy") or {})
        payload["risk_policy"] = dict(payload.get("risk_policy") or {})
        payload["runtime_contract"] = dict(payload.get("runtime_contract") or default_execution_runtime_contract(payload.get("mode")))
        payload["ui"] = dict(payload.get("ui") or {})
        payload["runtime"] = dict(payload.get("runtime") or {})
        payload["plan_id"] = payload.get("plan_id") or plan_id_for_payload(payload)
        payload["plan_fingerprint_sha256"] = payload.get("plan_fingerprint_sha256") or plan_fingerprint_sha256(payload)
        return payload


def canonical_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stable = dict(payload or {})
    stable.pop("plan_id", None)
    stable.pop("plan_fingerprint_sha256", None)
    stable.pop("created_at", None)
    runtime = stable.get("runtime") if isinstance(stable.get("runtime"), dict) else None
    if runtime is not None:
        runtime = dict(runtime)
        runtime.pop("autonomous_preflight_forecast", None)
        runtime.pop("start_preflight_decision", None)
        stable["runtime"] = runtime
    return stable


def plan_fingerprint_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(canonical_plan_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_id_for_payload(payload: dict[str, Any]) -> str:
    stable = canonical_plan_payload(payload)
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "plan_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def execution_plan_runtime_args(payload: dict[str, Any], before: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    before = before if isinstance(before, dict) else {}
    return {
        "target": _clean_text(payload.get("target")),
        "source_type": _clean_text(payload.get("source_type"), "auto") or "auto",
        "profile_group": _clean_text(payload.get("profile_group"), "United States") or "United States",
        "mode": normalize_plan_mode(payload.get("mode")),
        "volume": normalize_plan_volume(payload.get("volume")),
        "profile_limit": _safe_int(limits.get("profile_limit"), 3, minimum=1, maximum=1000000),
        "max_videos": _safe_int(limits.get("max_videos"), 3, minimum=1, maximum=1000000),
        "max_comments": _safe_int(limits.get("max_comments"), 20, minimum=1, maximum=1000000),
        "timeout": _safe_int(limits.get("timeout_seconds"), 300, minimum=30, maximum=86400),
        "comment_text": _clean_text(runtime.get("comment_text")),
        "base_dir": _clean_text(runtime.get("base_dir") or before.get("base_dir")),
    }


def build_execution_plan_runtime_contract(
    payload: dict[str, Any],
    before: dict[str, Any] | None = None,
    *,
    source: str = "execution_plan",
    audit_preview: bool = False,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized["plan_id"] = normalized.get("plan_id") or plan_id_for_payload(normalized)
    normalized["plan_fingerprint_sha256"] = normalized.get("plan_fingerprint_sha256") or plan_fingerprint_sha256(normalized)
    before = dict(before or {})
    after = execution_plan_runtime_args(normalized, before)
    runtime_after_fingerprint = json.dumps(after, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "reachops.execution_plan_runtime_contract.v1",
        "source": _clean_text(source, "execution_plan") or "execution_plan",
        "plan_id": str(normalized.get("plan_id") or ""),
        "plan_fingerprint_sha256": str(normalized.get("plan_fingerprint_sha256") or ""),
        "runtime_after_fingerprint_sha256": hashlib.sha256(runtime_after_fingerprint.encode("utf-8")).hexdigest(),
        "cli_args_ignored_for_plan_fields": True,
        "audit_preview": bool(audit_preview),
        "before": before,
        "after": after,
        "no_ai_token_used": True,
    }


def adversarial_cli_args_for_contract_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": "__cli_target_must_be_ignored__",
        "source_type": "__cli_source_type_must_be_ignored__",
        "profile_group": "__cli_profile_group_must_be_ignored__",
        "mode": "collect" if payload.get("mode") != "collect" else "preflight",
        "volume": "stress" if payload.get("volume") != "stress" else "quick",
        "profile_limit": 999999,
        "max_videos": 999999,
        "max_comments": 999999,
        "timeout": 999999,
        "comment_text": "__cli_comment_text_must_be_ignored__",
        "base_dir": "__cli_base_dir_must_be_ignored__",
    }


def default_repair_policy() -> dict[str, Any]:
    return {
        "PROFILE_MISSING": {"action": "remove_or_repair_profile_reference", "continue": "next_profile"},
        "LOGIN_REQUIRED": {"action": "quarantine_profile", "continue": "next_profile"},
        "PROFILE_START_FAILED": {"action": "retry_then_cooldown", "max_retries": 2},
        "PAGE_TIMEOUT": {"action": "refresh_then_retry", "max_retries": 1},
        "DOM_STALLED": {"action": "refresh_then_degrade", "degrade_to": "collect"},
        "MODAL_BLOCKED": {"action": "dismiss_known_modal_then_retry", "max_retries": 1},
        "UNKNOWN_PAGE_STATE": {"action": "capture_error_bundle_then_block"},
    }


def default_risk_policy(mode: str) -> dict[str, Any]:
    return {
        "no_ai_token_during_execution": True,
        "stop_on_captcha": True,
        "stop_on_rate_limit": True,
        "block_unlicensed_live_submit": True,
        "require_human_authorization_for_live_actions": mode == "live_comment",
        "never_bypass_login_or_captcha": True,
    }


def default_execution_runtime_contract(mode: Any = "preflight") -> dict[str, Any]:
    normalized_mode = normalize_plan_mode(mode)
    return {
        "schema_version": "reachops.execution_runtime_contract.v1",
        "executor": "local_program",
        "control_surface": "local_client_console",
        "loopback_host": "127.0.0.1",
        "ai_console_role": "communication_and_control_surface",
        "ai_console_is_execution_dependency": False,
        "no_ai_token_during_execution": True,
        "execution_phase_ai_calls_allowed": False,
        "no_submit_without_authorization": True,
        "requires_human_authorization_for_live_actions": normalized_mode == "live_comment",
        "never_bypass_login_or_captcha": True,
        "run_session_required": True,
        "checkpoint_required": True,
        "page_state_evidence_required": True,
        "repair_policy_required": True,
        "risk_gate_required": True,
        "evidence_bundle_required": True,
    }


def build_autonomous_preflight_forecast(
    plan: dict[str, Any],
    *,
    preflight_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Predict how the local autonomous runtime will handle this plan before launch."""
    plan = plan if isinstance(plan, dict) else {}
    preflight_decision = preflight_decision if isinstance(preflight_decision, dict) else {}
    validation_errors = validate_execution_plan(plan)
    blockers = [str(item) for item in (preflight_decision.get("blockers") or []) if str(item)]
    blockers.extend(error for error in validation_errors if error not in blockers)
    blockers = list(dict.fromkeys(blockers))

    mode = normalize_plan_mode(plan.get("mode"))
    authorization = plan.get("authorization") if isinstance(plan.get("authorization"), dict) else {}
    repair_policy = plan.get("repair_policy") if isinstance(plan.get("repair_policy"), dict) else {}
    risk_policy = plan.get("risk_policy") if isinstance(plan.get("risk_policy"), dict) else {}
    runtime_contract = plan.get("runtime_contract") if isinstance(plan.get("runtime_contract"), dict) else {}
    live_allowed = bool(authorization.get("live_submit_allowed"))
    start_allowed = bool(preflight_decision.get("start_allowed")) and not validation_errors

    risk_gates = [
        {
            "gate": "execution_plan_schema",
            "status": "passed" if not validation_errors else "blocked",
            "blockers": validation_errors,
            "terminal_outcome": "BLOCKED" if validation_errors else "",
        },
        {
            "gate": "profile_group_list",
            "status": "blocked" if "profile_group_list_not_ready" in blockers else "passed",
            "terminal_outcome": "BLOCKED" if "profile_group_list_not_ready" in blockers else "",
        },
        {
            "gate": "live_action_authorization",
            "status": "passed" if mode != "live_comment" or live_allowed else "blocked",
            "blockers": ["live_comment_confirmation_required"] if mode == "live_comment" and not live_allowed else [],
            "terminal_outcome": "BLOCKED" if mode == "live_comment" and not live_allowed else "",
        },
        {
            "gate": "no_ai_token_execution",
            "status": "passed" if risk_policy.get("no_ai_token_during_execution") is True else "blocked",
            "blockers": [] if risk_policy.get("no_ai_token_during_execution") is True else ["risk_policy_no_ai_token_required"],
            "terminal_outcome": "BLOCKED" if risk_policy.get("no_ai_token_during_execution") is not True else "",
        },
        {
            "gate": "login_captcha_never_bypass",
            "status": "passed" if risk_policy.get("never_bypass_login_or_captcha") is True else "blocked",
            "blockers": [] if risk_policy.get("never_bypass_login_or_captcha") is True else ["risk_policy_never_bypass_login_or_captcha_required"],
            "terminal_outcome": "BLOCKED" if risk_policy.get("never_bypass_login_or_captcha") is not True else "",
        },
    ]

    repair_routes = []
    repair_specs = [
        ("LOGIN_REQUIRED", "quarantine_profile", "BLOCKED_OR_NEXT_PROFILE"),
        ("PROFILE_START_FAILED", "retry_then_cooldown", "REPAIRING"),
        ("DOM_STALLED", "refresh_then_degrade", "DEGRADED"),
        ("MODAL_BLOCKED", "dismiss_known_modal_then_retry", "REPAIRING"),
        ("UNKNOWN_PAGE_STATE", "capture_error_bundle_then_block", "BLOCKED"),
    ]
    for state, fallback_action, terminal_outcome in repair_specs:
        policy = repair_policy.get(state) if isinstance(repair_policy.get(state), dict) else {}
        action = str(policy.get("action") or fallback_action)
        repair_routes.append(
            {
                "state": state,
                "action": action,
                "terminal_outcome": terminal_outcome,
                "evidence": ["page_state_sidecar", "screenshot", "run_session_checkpoint"],
                "no_ai_token_used": True,
            }
        )

    degradation_routes = []
    if mode == "live_comment":
        degradation_routes.append(
            {
                "from": "live_comment",
                "to": "collect",
                "trigger": "risk_signal_or_authorization_missing",
                "reason": "真实动作出现风控、登录、验证码、限频或授权缺口时降级或阻断。",
            }
        )
    if repair_policy.get("DOM_STALLED"):
        degradation_routes.append(
            {
                "from": mode,
                "to": "collect",
                "trigger": "DOM_STALLED",
                "reason": "页面卡住后先刷新，仍失败则降级采集或阻断。",
            }
        )

    human_required_actions = []
    if "target_required" in blockers:
        human_required_actions.append("输入目标后再启动。")
    if "profile_group_list_not_ready" in blockers:
        human_required_actions.append("刷新 ixBrowser 配置分组并确认账号数量。")
    if "live_comment_confirmation_required" in blockers or (mode == "live_comment" and not live_allowed):
        human_required_actions.append("真实评论前确认授权目标和提交权限。")
    if "account_repair_required" in blockers:
        human_required_actions.append("执行账号修复计划或确认账号已修复后重新预检。")

    predicted_state_sequence = ["CREATED", "PRECHECK"]
    if start_allowed:
        predicted_state_sequence.extend(["PROFILE_OPENING", "COLLECTING", "SCORING", "ACTION_PLANNING"])
        if mode == "live_comment":
            predicted_state_sequence.append("EXECUTING")
        predicted_state_sequence.extend(["REPAIRING", "DEGRADED", "BLOCKED", "COMPLETED"])
    else:
        predicted_state_sequence.append("BLOCKED")

    return {
        "schema_version": AUTONOMOUS_PREFLIGHT_FORECAST_SCHEMA_VERSION,
        "status": "ready" if start_allowed else "blocked",
        "start_allowed": start_allowed,
        "plan_id": str(plan.get("plan_id") or ""),
        "mode": mode,
        "profile_group": str(plan.get("profile_group") or ""),
        "predicted_state_sequence": list(dict.fromkeys(predicted_state_sequence)),
        "predicted_blockers": blockers,
        "risk_gates": risk_gates,
        "repair_routes": repair_routes,
        "degradation_routes": degradation_routes,
        "human_required_actions": human_required_actions,
        "evidence_requirements": [
            "execution_plan_snapshot",
            "run_session_state_history",
            "page_state_sidecar",
            "repair_decision",
            "risk_decision",
            "evidence_bundle",
        ],
        "runtime_invariants": {
            "no_ai_token_during_execution": risk_policy.get("no_ai_token_during_execution") is True
            and runtime_contract.get("no_ai_token_during_execution") is True,
            "no_browser_started": True,
            "no_submit": True,
            "never_bypass_login_or_captcha": risk_policy.get("never_bypass_login_or_captcha") is True
            and runtime_contract.get("never_bypass_login_or_captcha") is True,
            "live_submit_allowed": live_allowed,
            "executor": str(runtime_contract.get("executor") or ""),
            "ai_console_is_execution_dependency": runtime_contract.get("ai_console_is_execution_dependency") is True,
        },
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }


def attach_autonomous_preflight_forecast(
    plan: dict[str, Any],
    *,
    preflight_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(plan or {})
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    runtime = dict(runtime)
    decision = preflight_decision if isinstance(preflight_decision, dict) else {}
    if decision:
        runtime["start_preflight_decision"] = decision
    payload["runtime"] = runtime
    forecast = build_autonomous_preflight_forecast(payload, preflight_decision=decision)
    runtime["autonomous_preflight_forecast"] = forecast
    payload["runtime"] = runtime
    payload["plan_id"] = payload.get("plan_id") or plan_id_for_payload(payload)
    payload["plan_fingerprint_sha256"] = payload.get("plan_fingerprint_sha256") or plan_fingerprint_sha256(payload)
    return payload


def build_execution_plan(
    *,
    target: Any,
    source_type: Any = "auto",
    mode: Any = "preflight",
    profile_group: Any = "United States",
    volume: Any = "quick",
    profile_limit: Any = 3,
    max_videos: Any = 3,
    max_comments: Any = 20,
    timeout_seconds: Any = 300,
    comment_text: Any = "",
    live_confirmed: Any = False,
    account_repair_confirmed: Any = False,
    force_account_recheck: Any = False,
    base_dir: Any = "",
    origin: str = "web_ui",
) -> dict[str, Any]:
    normalized_mode = normalize_plan_mode(mode)
    normalized_volume = normalize_plan_volume(volume)
    normalized_target = _clean_text(target)
    normalized_source_type = _clean_text(source_type, "auto") or "auto"
    normalized_profile_group = _clean_text(profile_group, "United States") or "United States"
    normalized_profile_limit = _safe_int(profile_limit, 3, minimum=1, maximum=1000000)
    normalized_max_videos = _safe_int(max_videos, 3, minimum=1, maximum=1000000)
    normalized_max_comments = _safe_int(max_comments, 20, minimum=1, maximum=1000000)
    normalized_timeout_seconds = _safe_int(timeout_seconds, 300, minimum=30, maximum=86400)
    normalized_live_confirmed = _truthy(live_confirmed)
    normalized_account_repair_confirmed = _truthy(account_repair_confirmed)
    normalized_force_account_recheck = _truthy(force_account_recheck)
    normalized_comment_text = _clean_text(comment_text)
    plan = ExecutionPlan(
        target=normalized_target,
        source_type=normalized_source_type,
        mode=normalized_mode,
        profile_group=normalized_profile_group,
        volume=normalized_volume,
        limits={
            "profile_limit": normalized_profile_limit,
            "max_videos": normalized_max_videos,
            "max_comments": normalized_max_comments,
            "timeout_seconds": normalized_timeout_seconds,
        },
        authorization={
            "live_confirmed": normalized_live_confirmed,
            "account_repair_confirmed": normalized_account_repair_confirmed,
            "live_submit_allowed": normalized_mode == "live_comment" and normalized_live_confirmed,
        },
        repair_policy=default_repair_policy(),
        risk_policy=default_risk_policy(normalized_mode),
        runtime_contract=default_execution_runtime_contract(normalized_mode),
        ui={
            "origin": origin,
            "comment_text_present": bool(normalized_comment_text),
            "parameter_mapping": {
                "schema_version": "reachops.execution_plan_parameter_mapping.v1",
                "origin": origin,
                "fields": {
                    "target": {"input": _clean_text(target), "normalized": normalized_target},
                    "source_type": {"input": _clean_text(source_type, "auto"), "normalized": normalized_source_type},
                    "mode": {"input": _clean_text(mode, "preflight"), "normalized": normalized_mode},
                    "volume": {"input": _clean_text(volume, "quick"), "normalized": normalized_volume},
                    "profile_group": {"input": _clean_text(profile_group, "United States"), "normalized": normalized_profile_group},
                    "profile_limit": {"input": str(profile_limit), "normalized": normalized_profile_limit},
                    "max_videos": {"input": str(max_videos), "normalized": normalized_max_videos},
                    "max_comments": {"input": str(max_comments), "normalized": normalized_max_comments},
                    "timeout_seconds": {"input": str(timeout_seconds), "normalized": normalized_timeout_seconds},
                    "live_confirmed": {"input": str(live_confirmed), "normalized": normalized_live_confirmed},
                    "account_repair_confirmed": {"input": str(account_repair_confirmed), "normalized": normalized_account_repair_confirmed},
                    "force_account_recheck": {"input": str(force_account_recheck), "normalized": normalized_force_account_recheck},
                    "comment_text_present": {"input": bool(_clean_text(comment_text)), "normalized": bool(normalized_comment_text)},
                },
                "no_ai_token_used": True,
            },
        },
        runtime={
            "base_dir": _clean_text(base_dir),
            "force_account_recheck": normalized_force_account_recheck,
        },
    )
    payload = plan.to_dict()
    if normalized_comment_text:
        payload["runtime"]["comment_text"] = normalized_comment_text
        payload["plan_id"] = plan_id_for_payload(payload)
        payload["plan_fingerprint_sha256"] = plan_fingerprint_sha256(payload)
    return payload


def validate_execution_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan_object_required"]
    if str(plan.get("schema_version") or "") != PLAN_SCHEMA_VERSION:
        errors.append("schema_version_invalid")
    if not _clean_text(plan.get("target")):
        errors.append("target_required")
    if not _clean_text(plan.get("source_type")):
        errors.append("source_type_required")
    if not _clean_text(plan.get("profile_group")):
        errors.append("profile_group_required")
    if normalize_plan_mode(plan.get("mode")) != plan.get("mode"):
        errors.append("mode_invalid")
    if normalize_plan_volume(plan.get("volume")) != plan.get("volume"):
        errors.append("volume_invalid")
    for section in ["limits", "authorization", "repair_policy", "risk_policy"]:
        if not isinstance(plan.get(section), dict):
            errors.append(f"{section}_required")
    limits = plan.get("limits") if isinstance(plan.get("limits"), dict) else {}
    for key in ["profile_limit", "max_videos", "max_comments", "timeout_seconds"]:
        if key not in limits:
            errors.append(f"limits_{key}_required")
        elif _safe_int(limits.get(key), 0, minimum=0) <= 0:
            errors.append(f"limits_{key}_invalid")
    authorization = plan.get("authorization") if isinstance(plan.get("authorization"), dict) else {}
    if plan.get("mode") == "live_comment":
        if authorization.get("live_confirmed") is not True:
            errors.append("authorization_live_confirmed_required")
        if authorization.get("live_submit_allowed") is not True:
            errors.append("authorization_live_submit_allowed_required")
    if plan.get("mode") in {"preflight", "collect"} and authorization.get("live_submit_allowed") is True:
        errors.append("authorization_live_submit_not_allowed_for_mode")
    risk_policy = plan.get("risk_policy") if isinstance(plan.get("risk_policy"), dict) else {}
    if risk_policy.get("no_ai_token_during_execution") is not True:
        errors.append("risk_policy_no_ai_token_required")
    if risk_policy.get("never_bypass_login_or_captcha") is not True:
        errors.append("risk_policy_never_bypass_login_or_captcha_required")
    runtime_contract = plan.get("runtime_contract") if isinstance(plan.get("runtime_contract"), dict) else {}
    if runtime_contract.get("schema_version") != "reachops.execution_runtime_contract.v1":
        errors.append("runtime_contract_required")
    else:
        if runtime_contract.get("executor") != "local_program":
            errors.append("runtime_contract_local_program_required")
        if runtime_contract.get("control_surface") != "local_client_console":
            errors.append("runtime_contract_local_client_console_required")
        if runtime_contract.get("ai_console_is_execution_dependency") is not False:
            errors.append("runtime_contract_ai_console_control_surface_only_required")
        if runtime_contract.get("no_ai_token_during_execution") is not True:
            errors.append("runtime_contract_no_ai_token_required")
        if runtime_contract.get("execution_phase_ai_calls_allowed") is not False:
            errors.append("runtime_contract_execution_ai_calls_disallowed_required")
        if runtime_contract.get("no_submit_without_authorization") is not True:
            errors.append("runtime_contract_no_submit_without_authorization_required")
        if runtime_contract.get("never_bypass_login_or_captcha") is not True:
            errors.append("runtime_contract_never_bypass_login_or_captcha_required")
        for key in ["run_session_required", "checkpoint_required", "page_state_evidence_required", "repair_policy_required", "risk_gate_required", "evidence_bundle_required"]:
            if runtime_contract.get(key) is not True:
                errors.append(f"runtime_contract_{key}_required")
        if plan.get("mode") == "live_comment" and runtime_contract.get("requires_human_authorization_for_live_actions") is not True:
            errors.append("runtime_contract_live_authorization_required")
    fingerprint = _clean_text(plan.get("plan_fingerprint_sha256"))
    if fingerprint and fingerprint != plan_fingerprint_sha256(plan):
        errors.append("plan_fingerprint_sha256_mismatch")
    plan_id = _clean_text(plan.get("plan_id"))
    if plan_id and plan_id != plan_id_for_payload(plan):
        errors.append("plan_id_mismatch")
    repair_policy = plan.get("repair_policy") if isinstance(plan.get("repair_policy"), dict) else {}
    for key in ["LOGIN_REQUIRED", "PROFILE_START_FAILED", "DOM_STALLED", "UNKNOWN_PAGE_STATE"]:
        if key not in repair_policy:
            errors.append(f"repair_policy_{key}_required")
    mapping = ((plan.get("ui") if isinstance(plan.get("ui"), dict) else {}).get("parameter_mapping") or {})
    if not isinstance(mapping, dict) or mapping.get("schema_version") != "reachops.execution_plan_parameter_mapping.v1":
        errors.append("ui_parameter_mapping_required")
    elif mapping.get("no_ai_token_used") is not True:
        errors.append("ui_parameter_mapping_no_ai_token_required")
    return errors


def write_execution_plan(plan: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(plan or {})
    payload["plan_id"] = payload.get("plan_id") or plan_id_for_payload(payload)
    payload["plan_fingerprint_sha256"] = payload.get("plan_fingerprint_sha256") or plan_fingerprint_sha256(payload)
    errors = validate_execution_plan(payload)
    if errors:
        raise ValueError("Invalid ExecutionPlan: " + ",".join(errors))
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_execution_plan(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("runtime_contract"), dict):
        payload.pop("plan_id", None)
        payload.pop("plan_fingerprint_sha256", None)
        payload["runtime_contract"] = default_execution_runtime_contract(payload.get("mode"))
    payload["plan_id"] = payload.get("plan_id") or plan_id_for_payload(payload)
    payload["plan_fingerprint_sha256"] = payload.get("plan_fingerprint_sha256") or plan_fingerprint_sha256(payload)
    errors = validate_execution_plan(payload)
    if errors:
        raise ValueError("Invalid ExecutionPlan: " + ",".join(errors))
    return payload
