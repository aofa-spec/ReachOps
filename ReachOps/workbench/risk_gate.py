# -*- coding: utf-8 -*-
"""Unified risk gate for ReachOps live execution safety."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


RISK_GATE_SCHEMA_VERSION = "reachops.risk_gate.v1"
HIGH_RISK_LEVELS = {"high", "critical"}


@dataclass
class RiskGateDecision:
    allowed: bool
    reason_code: str = ""
    reason: str = ""
    severity: str = "info"
    profile_id: str = ""
    action_type: str = ""
    requires_authorization: bool = False
    authorization_ok: bool = False
    quota_ok: bool = True
    rate_limit_ok: bool = True
    high_risk: bool = False
    cooldown: bool = False
    block_execution: bool = False
    requires_human_review: bool = False
    risk_actions: list[dict[str, Any]] = field(default_factory=list)
    no_ai_token_used: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    schema_version: str = RISK_GATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["no_ai_token_used"] = True
        payload["schema_version"] = RISK_GATE_SCHEMA_VERSION
        payload["risk_category"] = risk_category(payload)
        payload["terminal_outcome"] = risk_terminal_outcome(payload)
        payload["risk_decision_id"] = risk_decision_id(payload)
        return payload


class RiskGate:
    """Deterministic safety gate before any platform action is executed."""

    def block_precheck(
        self,
        reason_code: str,
        reason: str,
        *,
        action_type: str = "start_precheck",
        evidence: dict[str, Any] | None = None,
        next_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Block before browser/profile execution when local configuration is unsafe."""
        code = str(reason_code or "LOCAL_PRECHECK_BLOCKED")
        return self._blocked(
            code,
            str(reason or "local precheck blocked"),
            "medium",
            {
                "profile_id": "",
                "action_type": action_type,
                "quota_ok": True,
                "rate_limit_ok": True,
                "evidence": dict(evidence or {}),
            },
            list(next_actions or ["修复本地配置后重新预检。"]),
        )

    def evaluate(
        self,
        action: dict[str, Any],
        profile: dict[str, Any],
        *,
        live_submit: bool = False,
        require_action_review: bool = False,
        require_authorization: bool = False,
        authorization_decision: Any = None,
        quota_status: dict[str, Any] | None = None,
        rate_status: dict[str, Any] | None = None,
        duplicate_text_status: dict[str, Any] | None = None,
        profile_state: dict[str, Any] | None = None,
        block_publish_profiles: bool = True,
    ) -> dict[str, Any]:
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        risk_level = str(action.get("risk_level") or "medium").lower()
        profile_state = profile_state or {}

        base = {
            "profile_id": profile_id,
            "action_type": action_type,
            "requires_authorization": bool(require_authorization and live_submit),
            "high_risk": risk_level in HIGH_RISK_LEVELS,
        }

        if not profile_id:
            return self._blocked("PROFILE_REQUIRED", "profile is required", "high", base, ["选择可执行账号后再启动。"])

        if block_publish_profiles and self._looks_like_publish_profile(profile):
            return self._blocked(
                "PUBLISH_PROFILE_BLOCKED",
                "publish/main account profile cannot execute outreach",
                "high",
                base,
                ["切换到获客执行账号分组，不使用发布主账号执行触达。"],
            )

        health_status = str(profile_state.get("status") or "").lower()
        if health_status == "cooldown" or bool(profile_state.get("cooldown")):
            return self._blocked(
                "PROFILE_IN_COOLDOWN",
                "profile is in cooldown",
                "medium",
                {**base, "cooldown": True, "evidence": profile_state},
                ["等待冷却结束或切换同分组健康账号。"],
            )

        last_error = str(profile_state.get("last_error_code") or "")
        if last_error in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"}:
            return self._blocked(
                last_error,
                "profile has high-risk last error",
                "high",
                {**base, "cooldown": True, "evidence": profile_state},
                ["人工修复账号登录/验证状态后再解除冷却。"],
            )

        if live_submit and require_action_review:
            if str(action.get("status") or "") != "approved":
                return self._blocked(
                    "ACTION_REQUIRES_REVIEW",
                    "action must be approved before live submit",
                    "medium",
                    base,
                    ["先在动作队列审核并批准该动作。"],
                )
            if not int(action.get("execution_confirmed") or 0):
                return self._blocked(
                    "ACTION_REQUIRES_EXECUTION_CONFIRMATION",
                    "action execution must be explicitly confirmed",
                    "medium",
                    base,
                    ["为真实动作补充执行确认。"],
                )

        if live_submit and risk_level in HIGH_RISK_LEVELS and not str(action.get("review_note") or "").strip():
            return self._blocked(
                "HIGH_RISK_REVIEW_NOTE_REQUIRED",
                "high risk action requires review note",
                "high",
                base,
                ["高风险动作必须填写复核说明后才能真实执行。"],
            )

        duplicate_text_status = duplicate_text_status or {}
        if live_submit and duplicate_text_status and not bool(duplicate_text_status.get("ok", True)):
            return self._blocked(
                str(duplicate_text_status.get("code") or "DUPLICATE_ACTION_TEXT"),
                str(duplicate_text_status.get("message") or "duplicate action text"),
                "medium",
                {**base, "evidence": duplicate_text_status},
                ["更换触达话术或等待去重窗口结束后再执行。"],
            )

        if live_submit and require_authorization:
            allowed = bool(getattr(authorization_decision, "allowed", False))
            if not allowed:
                code = str(getattr(authorization_decision, "error_code", "") or "LIVE_SUBMIT_NOT_AUTHORIZED")
                message = str(getattr(authorization_decision, "error_message", "") or "live submit not authorized")
                evidence = getattr(authorization_decision, "evidence", {}) or {}
                return self._blocked(
                    code,
                    message,
                    "high",
                    {**base, "authorization_ok": False, "evidence": evidence},
                    ["生成或刷新本机授权状态；未授权时不能执行真实评论、关注或私信。"],
                )

        quota_status = quota_status or {}
        if quota_status and not bool(quota_status.get("ok", True)):
            return self._blocked(
                "DAILY_QUOTA_EXCEEDED",
                f"{quota_status.get('used', 0)}/{quota_status.get('limit', 0)}",
                "medium",
                {**base, "quota_ok": False, "evidence": quota_status},
                ["等待下一个额度窗口或切换账号。"],
            )

        rate_status = rate_status or {}
        if rate_status and not bool(rate_status.get("ok", True)):
            return self._blocked(
                str(rate_status.get("code") or "RATE_LIMITED"),
                str(rate_status.get("message") or "rate limit reached"),
                "medium",
                {**base, "rate_limit_ok": False, "evidence": rate_status},
                ["等待限频窗口恢复或切换账号。"],
            )

        return RiskGateDecision(
            allowed=True,
            reason_code="OK",
            reason="risk gate passed",
            severity="info",
            profile_id=profile_id,
            action_type=action_type,
            requires_authorization=bool(require_authorization and live_submit),
            authorization_ok=not bool(require_authorization and live_submit) or bool(getattr(authorization_decision, "allowed", True)),
            quota_ok=True,
            rate_limit_ok=True,
            high_risk=risk_level in HIGH_RISK_LEVELS,
            block_execution=False,
            requires_human_review=False,
            evidence={"risk_level": risk_level},
            risk_actions=[],
            next_actions=[],
        ).to_dict()

    def _blocked(self, code: str, reason: str, severity: str, base: dict[str, Any], next_actions: list[str]) -> dict[str, Any]:
        evidence = dict(base.get("evidence") or {})
        return RiskGateDecision(
            allowed=False,
            reason_code=code,
            reason=reason,
            severity=severity,
            profile_id=str(base.get("profile_id") or ""),
            action_type=str(base.get("action_type") or ""),
            requires_authorization=bool(base.get("requires_authorization")),
            authorization_ok=bool(base.get("authorization_ok")),
            quota_ok=bool(base.get("quota_ok", True)),
            rate_limit_ok=bool(base.get("rate_limit_ok", True)),
            high_risk=bool(base.get("high_risk")),
            cooldown=bool(base.get("cooldown")),
            block_execution=True,
            requires_human_review=severity == "high" or bool(base.get("requires_authorization")),
            evidence=evidence,
            risk_actions=self._risk_actions_for_block(code, base),
            next_actions=next_actions,
        ).to_dict()

    def _risk_actions_for_block(self, code: str, base: dict[str, Any]) -> list[dict[str, Any]]:
        if code == "PROFILE_REQUIRED":
            return [{"step": "select_profile", "required": True}]
        if code == "PUBLISH_PROFILE_BLOCKED":
            return [
                {"step": "block_execution", "required": True},
                {"step": "switch_profile_group", "target": "non_publish_outreach_group"},
            ]
        if code in {"PROFILE_IN_COOLDOWN", "DAILY_QUOTA_EXCEEDED"}:
            return [
                {"step": "block_execution", "required": True},
                {"step": "wait_or_switch_profile", "scope": "same_profile_group"},
            ]
        if code in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"}:
            return [
                {"step": "block_execution", "required": True},
                {"step": "quarantine_profile", "required": True},
                {"step": "manual_account_repair", "required": True},
            ]
        if code in {"LIVE_SUBMIT_NOT_AUTHORIZED", "ACTION_REQUIRES_REVIEW", "ACTION_REQUIRES_EXECUTION_CONFIRMATION"} or "AUTH" in code:
            return [
                {"step": "block_live_submit", "required": True},
                {"step": "request_operator_authorization", "required": True},
            ]
        if code == "HIGH_RISK_REVIEW_NOTE_REQUIRED":
            return [
                {"step": "block_execution", "required": True},
                {"step": "request_review_note", "required": True},
            ]
        if code == "DUPLICATE_ACTION_TEXT":
            return [
                {"step": "block_execution", "required": True},
                {"step": "rewrite_or_rotate_message", "required": True},
                {"step": "keep_duplicate_text_evidence", "required": True},
            ]
        if "RATE" in code or "LIMIT" in code:
            return [
                {"step": "block_execution", "required": True},
                {"step": "cooldown_scope", "scope": "rate_limit_window"},
            ]
        if code.startswith("profile_group_") or code in {"LOCAL_PRECHECK_BLOCKED", "PROFILE_GROUP_PRECHECK_BLOCKED"}:
            return [
                {"step": "block_execution", "required": True},
                {"step": "refresh_profile_groups", "required": True},
                {"step": "reselect_profile_group", "required": True},
            ]
        return [{"step": "block_execution", "required": True}]

    def _looks_like_publish_profile(self, profile: dict[str, Any]) -> bool:
        joined = " ".join(
            str(profile.get(key) or "")
            for key in ["profile_id", "id", "name", "group_name", "group_id", "tag", "usage"]
        ).lower()
        return any(
            token in joined
            for token in [
                "publish",
                "publisher",
                "uploader",
                "upload",
                "posting",
                "main-account",
                "main_account",
                "主账号",
                "发布",
                "上传",
            ]
        )


def risk_gate_summary(decision: dict[str, Any]) -> str:
    status = "allowed" if decision.get("allowed") else "blocked"
    return (
        f"{status} reason={decision.get('reason_code') or '-'} "
        f"category={decision.get('risk_category') or risk_category(decision)} "
        f"outcome={decision.get('terminal_outcome') or risk_terminal_outcome(decision)} "
        f"auth={str(bool(decision.get('authorization_ok'))).lower()} "
        f"quota={str(bool(decision.get('quota_ok'))).lower()} "
        f"rate={str(bool(decision.get('rate_limit_ok'))).lower()} "
        f"risk={'high' if decision.get('high_risk') else 'normal'}"
    )


def risk_category(decision: dict[str, Any]) -> str:
    code = str(decision.get("reason_code") or "")
    if code == "OK":
        return "allowed"
    if bool(decision.get("requires_authorization")) or "AUTH" in code or code.startswith("LIVE_SUBMIT"):
        return "authorization"
    if bool(decision.get("cooldown")) or code in {"PROFILE_IN_COOLDOWN", "LOGIN_REQUIRED", "CAPTCHA_DETECTED", "ACCOUNT_RESTRICTED"}:
        return "account_health"
    if bool(decision.get("quota_ok")) is False or code == "DAILY_QUOTA_EXCEEDED":
        return "quota"
    if bool(decision.get("rate_limit_ok")) is False or "RATE" in code or "LIMIT" in code:
        return "rate_limit"
    if code == "DUPLICATE_ACTION_TEXT":
        return "duplicate_text"
    if bool(decision.get("high_risk")) or code == "HIGH_RISK_REVIEW_NOTE_REQUIRED":
        return "high_risk"
    if code in {"PUBLISH_PROFILE_BLOCKED", "PROFILE_REQUIRED"} or code.startswith("profile_group_") or code in {"LOCAL_PRECHECK_BLOCKED", "PROFILE_GROUP_PRECHECK_BLOCKED"}:
        return "profile_policy"
    return "policy"


def risk_terminal_outcome(decision: dict[str, Any]) -> str:
    if bool(decision.get("allowed")):
        return "allowed"
    if bool(decision.get("requires_human_review")):
        return "blocked_human_review"
    if any(str(action.get("step") or "") in {"wait_or_switch_profile", "cooldown_scope"} for action in (decision.get("risk_actions") or []) if isinstance(action, dict)):
        return "blocked_wait_or_switch"
    if any(str(action.get("step") or "") == "rewrite_or_rotate_message" for action in (decision.get("risk_actions") or []) if isinstance(action, dict)):
        return "blocked_rewrite_required"
    return "blocked"


def risk_decision_id(decision: dict[str, Any]) -> str:
    fingerprint = {
        "schema_version": RISK_GATE_SCHEMA_VERSION,
        "allowed": bool(decision.get("allowed")),
        "reason_code": str(decision.get("reason_code") or ""),
        "severity": str(decision.get("severity") or ""),
        "profile_id": str(decision.get("profile_id") or ""),
        "action_type": str(decision.get("action_type") or ""),
        "risk_category": str(decision.get("risk_category") or risk_category(decision)),
        "terminal_outcome": str(decision.get("terminal_outcome") or risk_terminal_outcome(decision)),
        "requires_authorization": bool(decision.get("requires_authorization")),
        "quota_ok": bool(decision.get("quota_ok", True)),
        "rate_limit_ok": bool(decision.get("rate_limit_ok", True)),
        "high_risk": bool(decision.get("high_risk")),
        "cooldown": bool(decision.get("cooldown")),
        "risk_actions": decision.get("risk_actions") or [],
    }
    raw = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "risk_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
