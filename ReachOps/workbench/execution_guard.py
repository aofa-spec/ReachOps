# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict

from .outreach_policy import OutreachPolicy


class ExecutionGuard:
    def __init__(self, policy: OutreachPolicy | None = None):
        self.policy = policy or OutreachPolicy()
        self.profile_action_counts = defaultdict(int)
        self.profile_failure_counts = defaultdict(int)

    def check(self, action: dict, profile_id: str, profile_state: dict | None = None) -> tuple[bool, str]:
        profile_id = str(profile_id or "")
        profile_state = profile_state or {}
        if not profile_id:
            return False, "PROFILE_REQUIRED"
        if profile_state.get("login_required"):
            return False, "LOGIN_REQUIRED"
        if profile_state.get("captcha_detected"):
            return False, "CAPTCHA_DETECTED"
        if profile_state.get("proxy_failed"):
            return False, "PROXY_FAILED"
        if profile_state.get("cooldown"):
            return False, "PROFILE_IN_COOLDOWN"
        if self.profile_failure_counts[profile_id] >= self.policy.cooldown_after_failures:
            return False, "PROFILE_IN_COOLDOWN"
        allowed, code = self.policy.is_execution_allowed(str(action.get("action_type") or ""), str(action.get("status") or ""))
        if not allowed:
            return allowed, code
        if self.profile_action_counts[profile_id] >= self.policy.max_actions_per_profile_round:
            return False, "PROFILE_ROUND_LIMIT_REACHED"
        if str(action.get("language_gate_status") or "ready") != "ready":
            return False, "LANGUAGE_CONFIRMATION_REQUIRED"
        if self.policy.require_execution_confirmation and not int(action.get("execution_confirmed") or 0):
            return False, "ACTION_REQUIRES_EXECUTION_CONFIRMATION"
        return True, ""

    def record_success(self, profile_id: str):
        self.profile_action_counts[str(profile_id or "")] += 1

    def record_failure(self, profile_id: str):
        self.profile_failure_counts[str(profile_id or "")] += 1
