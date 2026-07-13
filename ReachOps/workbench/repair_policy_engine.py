# -*- coding: utf-8 -*-
"""Deterministic repair policy decisions for autonomous ReachOps runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


REPAIR_POLICY_SCHEMA_VERSION = "reachops.repair_policy.v1"
PAGE_STATE_REPAIR_COVERAGE_SCHEMA_VERSION = "reachops.page_state_repair_coverage.v1"


@dataclass
class RepairDecision:
    error_code: str
    action: str
    reason: str
    switch_profile: bool = False
    cooldown_profile: bool = False
    retry_same_profile: bool = False
    fallback_allowed: bool = False
    degrade_to: str = ""
    block_execution: bool = False
    max_retries: int = 0
    retry_after_seconds: int = 0
    cooldown_seconds: int = 0
    requires_human_review: bool = False
    evidence_required: bool = True
    evidence_bundle_required: bool = True
    executable_steps: list[dict[str, Any]] = field(default_factory=list)
    no_ai_token_used: bool = True
    next_actions: list[str] = field(default_factory=list)
    schema_version: str = REPAIR_POLICY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["no_ai_token_used"] = True
        payload["schema_version"] = REPAIR_POLICY_SCHEMA_VERSION
        payload["terminal_outcome"] = repair_terminal_outcome(payload)
        payload["repair_decision_id"] = repair_decision_id(payload)
        return payload


class RepairPolicyEngine:
    """Maps known execution/page failures to deterministic local repair actions."""

    PROFILE_COOLDOWN_AND_SWITCH = {
        "LOGIN_REQUIRED",
        "CAPTCHA_DETECTED",
        "PROXY_FAILED",
        "PROFILE_START_FAILED",
        "IXBROWSER_KERNEL_MISMATCH",
        "ACCOUNT_RESTRICTED",
        "COMMENT_ACCESS_GATED",
    }
    SAME_PROFILE_RETRY = {
        "PAGE_TIMEOUT",
        "PLATFORM_TEMPORARY_ERROR",
        "DOM_STALLED",
        "MODAL_BLOCKED",
        "IXBROWSER_SERVER_BUSY",
        "IXBROWSER_NETWORK_ERROR",
        "BROWSER_CRASHED",
    }
    ACTION_DEGRADE = {
        "COMMENT_BOX_MISSING",
        "COMMENT_BOX_NOT_FOUND",
        "SUBMIT_BUTTON_MISSING",
        "COMMENT_SUBMIT_FAILED",
        "COMMENT_INPUT_NOT_FILLED",
        "COMMENT_SUBMIT_BUTTON_DISABLED",
        "COMMENT_SUBMIT_NOT_CONFIRMED",
    }
    RATE_LIMITS = {
        "RATE_LIMITED",
        "COMMENT_BLOCKED",
        "FOLLOW_RATE_LIMITED",
        "DM_RATE_LIMITED",
        "DAILY_QUOTA_EXCEEDED",
        "PROFILE_HOURLY_LIMIT_EXCEEDED",
        "VIDEO_HOURLY_LIMIT_EXCEEDED",
    }
    FALLBACK_ACTIONS = {
        "DM_NOT_AVAILABLE",
        "DM_ENTRY_NOT_FOUND",
        "DM_NOT_ALLOWED",
        "DM_RATE_LIMITED",
        "FOLLOW_NOT_AVAILABLE",
        "FOLLOW_BUTTON_MISSING",
        "FOLLOW_RATE_LIMITED",
        "FOLLOW_BLOCKED",
    }
    PRECHECK_CONFIGURATION_BLOCKS = {
        "profile_group_live_refresh_required",
        "profile_group_list_unavailable",
        "profile_group_not_found",
        "profile_group_counts_incomplete",
        "profile_group_count_unknown",
        "PROFILE_GROUP_PRECHECK_BLOCKED",
    }

    def decide(
        self,
        error_code: str,
        *,
        action_type: str = "",
        attempt: int = 1,
        page_state: dict[str, Any] | None = None,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        code = str(error_code or "UNKNOWN_PAGE_STATE")
        action_type = str(action_type or "")
        attempt = max(1, int(attempt or 1))
        max_retries = max(0, int(max_retries or 0))
        page_state_name = str((page_state or {}).get("state") or "")
        if page_state_name and code in {"ACTION_FAILED", "OUTREACH_EXECUTION_FAILED"}:
            code = page_state_name

        if code in self.PRECHECK_CONFIGURATION_BLOCKS:
            return RepairDecision(
                error_code=code,
                action="refresh_profile_groups_and_reselect",
                reason="local_precheck_configuration_not_executable",
                block_execution=True,
                requires_human_review=True,
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "refresh_profile_groups", "required": True, "source": "ixbrowser_local_api"},
                    {"step": "reselect_profile_group", "required": True},
                    {"step": "block_execution", "required": True},
                ],
                next_actions=[
                    "重新刷新 ixBrowser 配置分组。",
                    "选择存在且账号数量已确认的分组。",
                    "保持本轮阻断，不启动浏览器和真实提交。",
                ],
            ).to_dict()

        if code in self.PROFILE_COOLDOWN_AND_SWITCH:
            hard_block = code in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"}
            return RepairDecision(
                error_code=code,
                action="cooldown_profile_and_switch",
                reason="profile_or_session_not_safe_to_continue",
                switch_profile=True,
                cooldown_profile=True,
                block_execution=hard_block,
                cooldown_seconds=3600 if hard_block else 900,
                requires_human_review=hard_block,
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "cooldown_profile", "seconds": 3600 if hard_block else 900},
                    {"step": "switch_profile", "scope": "same_profile_group"},
                ],
                next_actions=[
                    "标记当前账号冷却或隔离。",
                    "切换同分组下一个健康账号。",
                    "保留截图和页面状态证据。",
                ],
            ).to_dict()

        if code in self.SAME_PROFILE_RETRY:
            can_retry = attempt <= max_retries
            retry_after_seconds = min(60, 5 * attempt)
            return RepairDecision(
                error_code=code,
                action="retry_same_profile_with_backoff" if can_retry else "switch_profile_after_retry_exhausted",
                reason="transient_page_or_browser_state",
                retry_same_profile=can_retry,
                switch_profile=not can_retry,
                max_retries=max_retries,
                retry_after_seconds=retry_after_seconds if can_retry else 0,
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "dismiss_modal", "max_attempts": 1, "when": code == "MODAL_BLOCKED"},
                    {"step": "refresh_page", "when": code in {"PAGE_TIMEOUT", "PLATFORM_TEMPORARY_ERROR", "DOM_STALLED", "MODAL_BLOCKED"}},
                    {"step": "backoff", "seconds": retry_after_seconds if can_retry else 0},
                    {"step": "retry_same_profile", "allowed": can_retry},
                    {"step": "switch_profile", "allowed": not can_retry, "scope": "same_profile_group"},
                ],
                next_actions=[
                    "刷新页面或重新定位目标元素。",
                    "退避后重试当前账号。",
                    "重试耗尽后切换账号或阻断当前目标。",
                ],
            ).to_dict()

        if code in self.ACTION_DEGRADE:
            if action_type == "comment_reply" and code in {"COMMENT_BOX_MISSING", "COMMENT_BOX_NOT_FOUND", "SUBMIT_BUTTON_MISSING", "COMMENT_SUBMIT_FAILED", "COMMENT_INPUT_NOT_FILLED", "COMMENT_SUBMIT_BUTTON_DISABLED", "COMMENT_SUBMIT_NOT_CONFIRMED"}:
                can_retry = attempt <= max_retries
                retry_after_seconds = min(60, 5 * attempt)
                return RepairDecision(
                    error_code=code,
                    action="retry_same_profile_with_backoff" if can_retry else "switch_profile_after_retry_exhausted",
                    reason="comment_composer_not_ready",
                    retry_same_profile=can_retry,
                    switch_profile=not can_retry,
                    max_retries=max_retries,
                    retry_after_seconds=retry_after_seconds if can_retry else 0,
                    executable_steps=[
                        {"step": "capture_page_state_bundle", "required": True},
                        {"step": "refresh_page", "when": True},
                        {"step": "backoff", "seconds": retry_after_seconds if can_retry else 0},
                        {"step": "retry_same_profile", "allowed": can_retry},
                        {"step": "switch_profile", "allowed": not can_retry, "scope": "same_profile_group"},
                    ],
                    next_actions=[
                        "重新打开或刷新评论区域。",
                        "退避后重试当前账号。",
                        "重试耗尽后切换同分组账号继续执行。",
                    ],
                ).to_dict()
            return RepairDecision(
                error_code=code,
                action="degrade_to_collect",
                reason="required_action_element_missing",
                degrade_to="collect",
                block_execution=action_type == "comment_reply",
                requires_human_review=action_type == "comment_reply",
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "stop_live_submit", "required": True},
                    {"step": "degrade_mode", "to": "collect"},
                ],
                next_actions=[
                    "停止当前真实提交动作。",
                    "保留页面状态和截图证据。",
                    "降级为只采集或等待人工复核。",
                ],
            ).to_dict()

        if code in self.RATE_LIMITS:
            return RepairDecision(
                error_code=code,
                action="cooldown_profile_or_scope",
                reason="rate_or_quota_limit",
                switch_profile=True,
                cooldown_profile=True,
                max_retries=0,
                cooldown_seconds=1800,
                requires_human_review=code in {"RATE_LIMITED", "COMMENT_BLOCKED"},
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "cooldown_profile_or_scope", "seconds": 1800},
                    {"step": "switch_profile", "scope": "same_profile_group"},
                ],
                next_actions=[
                    "冷却当前账号或限频 scope。",
                    "切换账号或等待下一个执行窗口。",
                ],
            ).to_dict()

        if code in self.FALLBACK_ACTIONS:
            return RepairDecision(
                error_code=code,
                action="fallback_action",
                reason="primary_action_not_available",
                fallback_allowed=True,
                executable_steps=[
                    {"step": "capture_page_state_bundle", "required": True},
                    {"step": "create_or_select_fallback_action", "chain": "configured_action_fallback"},
                ],
                next_actions=[
                    "使用动作降级链路。",
                    "优先选择风险更低的触达动作。",
                ],
            ).to_dict()

        if code == "UNKNOWN_PAGE_STATE":
            return RepairDecision(
                error_code=code,
                action="capture_unknown_state_bundle",
                reason="unclassified_page_state",
                block_execution=True,
                requires_human_review=True,
                executable_steps=[
                    {"step": "capture_unknown_state_bundle", "required": True},
                    {"step": "record_offline_learning_candidate", "auto_apply": False},
                    {"step": "block_execution", "required": True},
                ],
                next_actions=[
                    "保存截图、DOM 摘要、URL 和执行阶段。",
                    "本轮跳过或阻断，等待离线规则升级。",
                ],
            ).to_dict()

        return RepairDecision(
            error_code=code,
            action="record_failure",
            reason="no_specific_repair_policy",
            fallback_allowed=False,
            requires_human_review=True,
            executable_steps=[
                {"step": "record_failure", "required": True},
                {"step": "capture_page_state_bundle", "required": True},
            ],
            next_actions=["记录失败原因和证据，等待后续规则扩展。"],
        ).to_dict()


def repair_decision_summary(decision: dict[str, Any]) -> str:
    return (
        f"{decision.get('action') or 'record_failure'} "
        f"outcome={decision.get('terminal_outcome') or repair_terminal_outcome(decision)} "
        f"switch={str(bool(decision.get('switch_profile'))).lower()} "
        f"cooldown={str(bool(decision.get('cooldown_profile'))).lower()} "
        f"retry={str(bool(decision.get('retry_same_profile'))).lower()} "
        f"degrade={decision.get('degrade_to') or '-'}"
    )


def repair_terminal_outcome(decision: dict[str, Any]) -> str:
    if str(decision.get("degrade_to") or ""):
        return "degraded"
    if bool(decision.get("block_execution")):
        return "blocked"
    if bool(decision.get("retry_same_profile")):
        return "retry"
    if bool(decision.get("switch_profile")):
        return "switch_profile"
    if bool(decision.get("fallback_allowed")):
        return "fallback"
    return "recorded"


def repair_decision_id(decision: dict[str, Any]) -> str:
    fingerprint = {
        "schema_version": REPAIR_POLICY_SCHEMA_VERSION,
        "error_code": str(decision.get("error_code") or ""),
        "action": str(decision.get("action") or ""),
        "reason": str(decision.get("reason") or ""),
        "terminal_outcome": str(decision.get("terminal_outcome") or repair_terminal_outcome(decision)),
        "retry_same_profile": bool(decision.get("retry_same_profile")),
        "switch_profile": bool(decision.get("switch_profile")),
        "cooldown_profile": bool(decision.get("cooldown_profile")),
        "fallback_allowed": bool(decision.get("fallback_allowed")),
        "degrade_to": str(decision.get("degrade_to") or ""),
        "block_execution": bool(decision.get("block_execution")),
        "executable_steps": decision.get("executable_steps") or [],
    }
    raw = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "repair_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_page_state_repair_coverage(page_states: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """Summarize whether every sensed page state has a deterministic local handling route."""
    if page_states is None:
        from ReachOps.workbench.page_state_detector import PAGE_STATES

        states = sorted(PAGE_STATES)
    else:
        states = sorted(str(state or "") for state in page_states if str(state or ""))
    engine = RepairPolicyEngine()
    rows: list[dict[str, Any]] = []
    for state in states:
        if state == "READY":
            row = {
                "state": "READY",
                "covered": True,
                "action": "continue_execution",
                "terminal_outcome": "continue",
                "requires_human_review": False,
                "evidence_required": False,
                "runtime_auto_apply": True,
                "no_ai_token_used": True,
            }
        else:
            action_type = "comment_reply" if state in {"COMMENT_BOX_MISSING", "SUBMIT_BUTTON_MISSING"} else ""
            decision = engine.decide(state, action_type=action_type)
            steps = [str(row.get("step") or "") for row in decision.get("executable_steps") or [] if isinstance(row, dict)]
            row = {
                "state": state,
                "covered": bool(decision.get("schema_version") == REPAIR_POLICY_SCHEMA_VERSION and steps),
                "action": str(decision.get("action") or ""),
                "terminal_outcome": str(decision.get("terminal_outcome") or repair_terminal_outcome(decision)),
                "requires_human_review": bool(decision.get("requires_human_review")),
                "evidence_required": bool(decision.get("evidence_required", True)),
                "evidence_bundle_required": bool(decision.get("evidence_bundle_required", True)),
                "executable_steps": steps,
                "runtime_auto_apply": False,
                "no_ai_token_used": True,
            }
        rows.append(row)
    uncovered = [row["state"] for row in rows if not row.get("covered")]
    return {
        "schema_version": PAGE_STATE_REPAIR_COVERAGE_SCHEMA_VERSION,
        "state_count": len(rows),
        "covered_count": len(rows) - len(uncovered),
        "uncovered_count": len(uncovered),
        "uncovered_states": uncovered,
        "all_page_states_covered": not uncovered,
        "routes": rows,
        "no_ai_token_used": True,
    }
