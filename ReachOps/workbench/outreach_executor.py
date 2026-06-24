# -*- coding: utf-8 -*-
from __future__ import annotations

from ReachOps.intelligence.storage import GrowthStorage

from .execution_guard import ExecutionGuard


class OutreachExecutor:
    """Controlled outreach executor.

    First-stage execution is audit-first: it creates execution records and only
    marks approved actions as completed when the policy explicitly allows that
    action type. Platform automation can be added behind this interface later.
    """

    def __init__(self, storage: GrowthStorage, guard: ExecutionGuard | None = None):
        self.storage = storage
        self.guard = guard or ExecutionGuard()

    def execute_action(self, action: dict, profile_id: str, dry_run: bool = True, profile_state: dict | None = None) -> dict:
        allowed, code = self.guard.check(action, profile_id, profile_state=profile_state)
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        target_username = str(action.get("target_username") or "")
        target_url = str(action.get("target_url") or "")
        if not allowed:
            execution_id = self.storage.create_outreach_execution(
                action_id,
                action_type,
                target_username,
                status="skipped",
                profile_id=profile_id,
                error_code=code,
                error_message="blocked by outreach policy",
            )
            self.storage.log_error("OUTREACH_POLICY_BLOCKED", code, profile_id=profile_id)
            self.storage.log_event("outreach_execution_skipped", execution_id, {"action_id": action_id, "code": code})
            return {"execution_id": execution_id, "status": "skipped", "error_code": code}
        if self.storage.is_target_excluded(target_username, target_url):
            execution_id = self.storage.create_outreach_execution(
                action_id,
                action_type,
                target_username,
                status="skipped",
                profile_id=profile_id,
                error_code="TARGET_EXCLUDED",
                error_message="target is in exclusion list",
            )
            self.storage.log_error("OUTREACH_POLICY_BLOCKED", "TARGET_EXCLUDED", profile_id=profile_id)
            self.storage.log_event("outreach_execution_skipped", execution_id, {"action_id": action_id, "code": "TARGET_EXCLUDED"})
            return {"execution_id": execution_id, "status": "skipped", "error_code": "TARGET_EXCLUDED"}
        quota_ok, used, limit = self.storage.check_daily_quota(profile_id, action_type, self.guard.policy.max_actions_per_profile_day)
        if not quota_ok:
            execution_id = self.storage.create_outreach_execution(
                action_id,
                action_type,
                target_username,
                status="skipped",
                profile_id=profile_id,
                error_code="DAILY_QUOTA_EXCEEDED",
                error_message=f"daily quota exceeded: {used}/{limit}",
            )
            self.storage.log_error("OUTREACH_POLICY_BLOCKED", "DAILY_QUOTA_EXCEEDED", profile_id=profile_id)
            self.storage.log_event("outreach_execution_skipped", execution_id, {"action_id": action_id, "code": "DAILY_QUOTA_EXCEEDED"})
            return {"execution_id": execution_id, "status": "skipped", "error_code": "DAILY_QUOTA_EXCEEDED"}
        if dry_run:
            execution_id = self.storage.create_outreach_execution(
                action_id,
                action_type,
                target_username,
                status="completed",
                profile_id=profile_id,
            )
            self.storage.record_action_execution_result(
                action_id,
                execution_id,
                "completed",
                error_message="dry-run controlled execution",
            )
            self.storage.increment_daily_quota(profile_id, action_type, self.guard.policy.max_actions_per_profile_day)
            self.guard.record_success(profile_id)
            self.storage.log_event("outreach_execution_completed", execution_id, {"action_id": action_id, "dry_run": True})
            return {"execution_id": execution_id, "status": "completed", "dry_run": True}
        execution_id = self.storage.create_outreach_execution(
            action_id,
            action_type,
            target_username,
            status="failed",
            profile_id=profile_id,
            error_code="OUTREACH_EXECUTION_FAILED",
            error_message="live platform executor is not enabled",
        )
        self.guard.record_failure(profile_id)
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "failed",
            error_code="OUTREACH_EXECUTION_FAILED",
            error_message="live platform executor is not enabled",
            retryable=True,
        )
        self.storage.log_error("OUTREACH_EXECUTION_FAILED", "live platform executor is not enabled", profile_id=profile_id)
        return {"execution_id": execution_id, "status": "failed", "error_code": "OUTREACH_EXECUTION_FAILED"}
