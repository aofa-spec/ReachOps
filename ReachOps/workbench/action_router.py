# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Protocol

from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import GrowthStorage, new_id

from .account_health_manager import AccountHealthManager
from .action_executors import ActionExecutorRegistry
from .authorization_gate import LiveSubmitAuthorizationGate
from .template_manager import TemplateManager


ACTION_PRIORITY = {
    "comment_reply": 0,
    "follow_review": 1,
    "dm_review": 2,
}

PUBLIC_ACTION_TYPE = {
    "comment_reply": "comment",
    "follow_review": "follow",
    "dm_review": "dm",
}

FALLBACK_CHAIN = {
    "dm_review": ["comment_reply", "follow_review"],
    "follow_review": ["comment_reply"],
    "comment_reply": [],
}

SWITCH_PROFILE_CODES = {
    "PROFILE_START_FAILED",
    "PAGE_OPEN_FAILED",
    "CREATOR_PAGE_OPEN_FAILED",
    "PROXY_FAILED",
    "BROWSER_CRASHED",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "COMMENT_BLOCKED",
    "COMMENT_BOX_NOT_FOUND",
    "COMMENT_SUBMIT_FAILED",
    "FOLLOW_RATE_LIMITED",
    "DM_RATE_LIMITED",
    "ACCOUNT_RESTRICTED",
}

FALLBACK_CODES = {
    "DM_NOT_AVAILABLE",
    "DM_ENTRY_NOT_FOUND",
    "DM_NOT_ALLOWED",
    "DM_RATE_LIMITED",
    "FOLLOW_NOT_AVAILABLE",
    "FOLLOW_BUTTON_MISSING",
    "FOLLOW_RATE_LIMITED",
    "FOLLOW_BLOCKED",
}


@dataclass
class ActionRouterConfig:
    max_workers: int = 2
    per_profile_action_limit: int = 10
    max_switch_attempts: int = 2
    action_types: list[str] = field(default_factory=lambda: ["comment_reply", "follow_review", "dm_review"])
    dry_run: bool = True
    auto_approve: bool = True
    auto_confirm: bool = True
    min_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    profile_group: str = ""
    per_profile_hour_limit: int = 20
    per_profile_video_hour_limit: int = 1
    allow_live_submit: bool = False
    live_preflight_only: bool = False
    block_publish_profiles: bool = True
    batch_id: str = ""
    require_authorization: bool = True
    authorization_feature: str = "live_submit"
    require_execution_evidence: bool = True


class PlatformActionExecutor(Protocol):
    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        ...


class FixtureActionExecutor:
    """Deterministic executor for smoke, pressure tests, and demo mode."""

    def __init__(self, outcomes: list[dict] | None = None):
        self.outcomes = list(outcomes or [])
        self._index = 0
        self._lock = threading.Lock()

    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        with self._lock:
            outcome = self._select_outcome(action, profile)
        if str(outcome.get("status") or "") == "success":
            return {
                "status": "success",
                "error_code": "",
                "error_message": "",
                "evidence_path": str(outcome.get("evidence_path") or ""),
            }
        return {
            "status": "failed",
            "error_code": str(outcome.get("error_code") or "ACTION_FAILED"),
            "error_message": str(outcome.get("error_message") or outcome.get("error_code") or "fixture failure"),
            "evidence_path": str(outcome.get("evidence_path") or ""),
        }

    def _select_outcome(self, action: dict, profile: dict | None = None) -> dict:
        if not self.outcomes:
            return {"status": "success"}
        action_type = str(action.get("action_type") or "")
        public_action_type = PUBLIC_ACTION_TYPE.get(action_type, action_type)
        profile_id = str((profile or {}).get("profile_id") or (profile or {}).get("id") or "")
        has_targeted = any(row.get("action_type") or row.get("public_action_type") or row.get("profile_id") for row in self.outcomes)
        if has_targeted:
            fallback = None
            for row in self.outcomes:
                expected_action = str(row.get("action_type") or "")
                expected_public = str(row.get("public_action_type") or "")
                expected_profile = str(row.get("profile_id") or "")
                action_matches = not expected_action and not expected_public
                if expected_action == action_type or expected_public == public_action_type:
                    action_matches = True
                profile_matches = not expected_profile or expected_profile == profile_id
                if action_matches and profile_matches:
                    return dict(row)
                if not expected_action and not expected_public and not expected_profile and fallback is None:
                    fallback = row
            if fallback is not None:
                return dict(fallback)
            return {"status": "success"}
        outcome = dict(self.outcomes[self._index % len(self.outcomes)])
        self._index += 1
        return outcome


class ActionRouter:
    """Routes lead actions across profiles with fallback and account switching."""

    def __init__(
        self,
        storage: GrowthStorage,
        executor: PlatformActionExecutor | None = None,
        template_manager: TemplateManager | None = None,
        health_manager: AccountHealthManager | None = None,
        authorization_gate: LiveSubmitAuthorizationGate | None = None,
    ):
        self.storage = storage
        self.executor = executor or FixtureActionExecutor()
        self.executor_registry = ActionExecutorRegistry(self.executor)
        self.template_manager = template_manager or TemplateManager(storage)
        self.health_manager = health_manager or AccountHealthManager(storage)
        self.authorization_gate = authorization_gate or LiveSubmitAuthorizationGate.from_storage(storage)
        self._lock = threading.Lock()
        self._profile_locks: dict[str, threading.Lock] = {}

    def run(self, profiles: list[dict], config: ActionRouterConfig | None = None, limit: int = 100) -> dict:
        config = config or ActionRouterConfig()
        previous_batch_id = self.storage._active_batch_id()
        if config.batch_id:
            self.storage.set_active_collection_batch(config.batch_id)
        try:
            max_workers = max(1, int(config.max_workers or 1))
            available_profiles = self.health_manager.rank_profiles(
                profiles,
                group_name=config.profile_group,
                max_count=max(len(profiles or []), max_workers),
            )
            worker_profiles = available_profiles[:max_workers]
            actions = self._select_actions(config, limit=limit)
            q: Queue[dict] = Queue()
            for action in actions:
                q.put(action)
            results: list[dict] = []

            def worker(profile: dict):
                handled = 0
                while handled < config.per_profile_action_limit:
                    profile_id = str(profile.get("profile_id") or profile.get("id") or "")
                    if self._profile_is_cooldown(profile_id):
                        self.storage.log_event("action_router_profile_stopped", profile_id, {"reason": "cooldown"})
                        return
                    try:
                        action = q.get_nowait()
                    except Exception:
                        return
                    try:
                        result_rows = self._execute_with_switch_and_fallback(action, available_profiles, profile, config)
                    except Exception as exc:
                        error_message = str(exc) or exc.__class__.__name__
                        self.health_manager.record_failure(profile, "ACTION_ROUTER_EXCEPTION", error_message)
                        self.storage.log_event(
                            "action_router_worker_exception",
                            str(action.get("id") or ""),
                            {
                                "profile_id": profile_id,
                                "action_type": str(action.get("action_type") or ""),
                                "error": error_message,
                            },
                        )
                        result_rows = [
                            self._record(
                                action,
                                profile,
                                "failed",
                                "ACTION_ROUTER_EXCEPTION",
                                error_message,
                                self._evidence_stub(action, profile, "ACTION_ROUTER_EXCEPTION"),
                                1,
                            )
                        ]
                    finally:
                        q.task_done()
                    with self._lock:
                        results.extend(result_rows)
                    handled += 1
                    self._sleep(config)

            threads = [
                threading.Thread(target=worker, args=(profile,), daemon=True)
                for profile in worker_profiles
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            summary = self._summary(actions, available_profiles, results)
            summary["worker_count"] = len(worker_profiles)
            summary["available_profile_count"] = len(available_profiles)
            self.storage.log_event("action_router_run_completed", "", summary)
            return summary
        finally:
            if config.batch_id:
                self.storage.set_active_collection_batch(previous_batch_id)

    def _select_actions(self, config: ActionRouterConfig, limit: int) -> list[dict]:
        allowed = {self.template_manager.normalize_action_type(item) for item in (config.action_types or [])}
        selectable = {"pending", "pending_review", "approved", "retryable", "account_switched"}
        rows = []
        for row in self.storage.list_action_queue(limit=limit, batch_id=str(config.batch_id or "")):
            action_type = str(row.get("action_type") or "")
            if allowed and action_type not in allowed:
                continue
            if str(row.get("status") or "") not in selectable:
                continue
            if config.auto_approve and row.get("status") == "pending_review":
                self.storage.update_action_status(row["id"], "approved", "action router auto approve")
                row["status"] = "approved"
            if config.auto_confirm and not int(row.get("execution_confirmed") or 0):
                self.storage.confirm_action_execution(row["id"], confirmed_by="action_router", note="action router auto confirm")
                row["execution_confirmed"] = 1
            rows.append(row)
        return sorted(rows, key=lambda row: (ACTION_PRIORITY.get(str(row.get("action_type") or ""), 99), -int(row.get("lead_score") or 0)))

    def _execute_with_switch_and_fallback(
        self,
        action: dict,
        profiles: list[dict],
        initial_profile: dict,
        config: ActionRouterConfig,
    ) -> list[dict]:
        results = []
        current_action = action
        current_profile = initial_profile
        attempt = 1
        while True:
            result = self._execute_once(current_action, current_profile, config, attempt)
            results.append(result)
            if result["status"] == "success":
                return results
            if result.get("switch_profile") and attempt < config.max_switch_attempts:
                next_profile = self._next_profile(profiles, current_profile)
                if next_profile:
                    results.append(self._record_account_switched(current_action, current_profile, next_profile, result, attempt))
                    current_profile = next_profile
                    attempt += 1
                    continue
            fallback = self._fallback_action(current_action, result.get("error_code", ""), batch_id=config.batch_id)
            if fallback:
                current_action = fallback
                attempt = 1
                continue
            return results

    def _execute_once(self, action: dict, profile: dict, config: ActionRouterConfig, attempt: int) -> dict:
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        profile_block = self._profile_block_reason(profile, config)
        if profile_block:
            return self._record(action, profile, "skipped", profile_block, profile_block, "", attempt)
        if self._profile_is_cooldown(profile_id):
            return self._record(action, profile, "skipped", "PROFILE_IN_COOLDOWN", "profile is in cooldown", "", attempt)
        if not config.dry_run and not config.allow_live_submit and not config.live_preflight_only:
            return self._record(action, profile, "skipped", "LIVE_EXECUTION_NOT_CONFIRMED", "live submit requires explicit confirmation", "", attempt)
        if not config.dry_run and not config.live_preflight_only and config.require_authorization:
            decision = self.authorization_gate.authorize_live_submit(action, profile, feature=config.authorization_feature)
            if not decision.allowed:
                self.storage.log_event(
                    "live_submit_authorization_blocked",
                    action_id,
                    {
                        "error_code": decision.error_code,
                        "error_message": decision.error_message,
                        **(decision.evidence or {}),
                    },
                )
                return self._record(action, profile, "skipped", decision.error_code, decision.error_message, "", attempt)
        if self.storage.is_target_excluded(str(action.get("target_username") or ""), str(action.get("target_url") or "")):
            return self._record(action, profile, "skipped", "TARGET_EXCLUDED", "target excluded", "", attempt)
        quota_ok, used, limit = self.storage.check_daily_quota(profile_id, action_type, 20)
        if not quota_ok:
            return self._record(action, profile, "skipped", "DAILY_QUOTA_EXCEEDED", f"{used}/{limit}", "", attempt)
        limited, rate_code = self._check_rate_limits(action, profile, config)
        if limited:
            return self._record(action, profile, "skipped", rate_code, rate_code, "", attempt)

        self.storage.update_action_status(action_id, "running", "action router started")
        rendered = self.template_manager.render(action, profile)
        profile_lock = self._profile_execution_lock(profile_id)
        with profile_lock:
            platform_result = self.executor_registry.execute(action, profile, rendered.rendered_text, dry_run=config.dry_run)
        if str(platform_result.get("status") or "") == "success":
            evidence_path = str(platform_result.get("evidence_path") or "")
            if not config.dry_run and not config.live_preflight_only and config.require_execution_evidence and not self._valid_execution_evidence(evidence_path, action):
                self.health_manager.record_failure(profile, "LIVE_SUBMIT_EVIDENCE_MISSING", "live submit succeeded without evidence")
                return self._record(
                    action,
                    profile,
                    "failed",
                    "LIVE_SUBMIT_EVIDENCE_MISSING",
                    "live submit succeeded without evidence",
                    "",
                    attempt,
                )
            result = self._record(
                action,
                profile,
                "success",
                "",
                rendered.rendered_text,
                evidence_path or self._evidence_stub(action, profile, "success"),
                attempt,
            )
            self.storage.increment_daily_quota(profile_id, action_type, 20)
            self._increment_rate_limits(action, profile, config)
            self.health_manager.record_success(profile)
            return result

        error_code = str(platform_result.get("error_code") or "ACTION_FAILED")
        error_message = str(platform_result.get("error_message") or error_code)
        self.health_manager.record_failure(profile, error_code, error_message)
        result = self._record(
            action,
            profile,
            "failed",
            error_code,
            error_message,
            str(platform_result.get("evidence_path") or self._evidence_stub(action, profile, error_code)),
            attempt,
        )
        result["switch_profile"] = error_code in SWITCH_PROFILE_CODES
        result["fallback_available"] = bool(self._fallback_action(action, error_code, create=False, batch_id=config.batch_id))
        return result

    def _valid_execution_evidence(self, evidence_path: str, action: dict) -> bool:
        value = str(evidence_path or "").strip()
        if not value:
            return False
        if "://" in value:
            return True
        if not os.path.isfile(value):
            return False
        try:
            with open(value, "rb") as fh:
                data = fh.read()
        except Exception:
            return False
        if not data:
            return False
        sidecar_path = f"{value}.json"
        if not os.path.isfile(sidecar_path):
            return False
        try:
            with open(sidecar_path, "r", encoding="utf-8") as fh:
                sidecar = json.load(fh)
        except Exception:
            return False
        if not isinstance(sidecar, dict):
            return False
        expected_hash = hashlib.sha256(data).hexdigest()
        if str(sidecar.get("screenshot_sha256") or "") != expected_hash:
            return False
        expected_action_type = str(action.get("action_type") or "")
        if expected_action_type and str(sidecar.get("action_type") or "") != expected_action_type:
            return False
        return True

    def _profile_block_reason(self, profile: dict, config: ActionRouterConfig) -> str:
        if not config.block_publish_profiles:
            return ""
        joined = " ".join(
            str(profile.get(key) or "")
            for key in ["profile_id", "id", "name", "group_name", "group_id", "tag", "usage"]
        ).lower()
        unsafe_tokens = [
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
        if any(token in joined for token in unsafe_tokens):
            return "PUBLISH_PROFILE_BLOCKED"
        return ""

    def _check_rate_limits(self, action: dict, profile: dict, config: ActionRouterConfig) -> tuple[bool, str]:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        action_type = str(action.get("action_type") or "")
        hour_key = self._hour_key()
        checks = [
            ("profile_hour", profile_id, int(config.per_profile_hour_limit or 0), "PROFILE_HOURLY_LIMIT_EXCEEDED"),
        ]
        video_scope = self._video_scope(action)
        if action_type == "comment_reply" and video_scope:
            checks.append(("profile_video_hour", video_scope, int(config.per_profile_video_hour_limit or 0), "VIDEO_HOURLY_LIMIT_EXCEEDED"))
        for scope_type, scope_value, limit, code in checks:
            ok, _used, _limit = self.storage.check_rate_limit(profile_id, action_type, scope_type, scope_value, hour_key, limit)
            if not ok:
                return True, code
        return False, ""

    def _increment_rate_limits(self, action: dict, profile: dict, config: ActionRouterConfig):
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        action_type = str(action.get("action_type") or "")
        hour_key = self._hour_key()
        self.storage.increment_rate_limit(profile_id, action_type, "profile_hour", profile_id, hour_key, int(config.per_profile_hour_limit or 0))
        video_scope = self._video_scope(action)
        if action_type == "comment_reply" and video_scope:
            self.storage.increment_rate_limit(
                profile_id,
                action_type,
                "profile_video_hour",
                video_scope,
                hour_key,
                int(config.per_profile_video_hour_limit or 0),
            )

    def _hour_key(self) -> str:
        from datetime import datetime

        return datetime.utcnow().strftime("%Y-%m-%dT%H")

    def _video_scope(self, action: dict) -> str:
        value = str(action.get("source_path") or action.get("target_url") or action.get("video_url") or "").strip()
        return value or str(action.get("lead_id") or "")

    def _evidence_stub(self, action: dict, profile: dict, status: str) -> str:
        action_id = str(action.get("id") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        return f"evidence://growth_ops/{profile_id}/{action_id}/{status}"

    def _record(
        self,
        action: dict,
        profile: dict,
        public_status: str,
        error_code: str,
        message: str,
        evidence_path: str,
        attempt: int,
    ) -> dict:
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        if not evidence_path:
            evidence_path = self._evidence_stub(action, profile, public_status or error_code or "recorded")
        execution_id = self.storage.create_outreach_execution(
            action_id,
            action_type,
            str(action.get("target_username") or ""),
            status=public_status,
            profile_id=profile_id,
            evidence_path=evidence_path,
            error_code=error_code,
            error_message=message,
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "completed" if public_status == "success" else public_status,
            error_code=error_code,
            error_message=message,
            retryable=public_status == "failed" and error_code in SWITCH_PROFILE_CODES,
        )
        if public_status in {"skipped", "failed"}:
            self.storage.update_action_status(action_id, public_status, message or error_code)
        if public_status == "success":
            self.storage.update_action_status(action_id, "success", "action router success")
        self.storage.log_event(
            f"action_router_{public_status}",
            action_id,
            {"profile_id": profile_id, "execution_id": execution_id, "error_code": error_code, "attempt": attempt},
        )
        return {
            "action_id": action_id,
            "execution_id": execution_id,
            "action_type": action_type,
            "public_action_type": PUBLIC_ACTION_TYPE.get(action_type, action_type),
            "status": public_status,
            "profile_id": profile_id,
            "attempt": attempt,
            "error_code": error_code,
            "error_message": message,
            "evidence_path": evidence_path,
        }

    def _record_account_switched(
        self,
        action: dict,
        current_profile: dict,
        next_profile: dict,
        failed_result: dict,
        attempt: int,
    ) -> dict:
        action_id = str(action.get("id") or "")
        action_type = str(action.get("action_type") or "")
        profile_id = str(current_profile.get("profile_id") or current_profile.get("id") or "")
        next_profile_id = str(next_profile.get("profile_id") or next_profile.get("id") or "")
        error_code = str(failed_result.get("error_code") or "ACTION_PROFILE_SWITCHED")
        message = f"switch profile to {next_profile_id} after {error_code}"
        evidence_path = f"{self._evidence_stub(action, current_profile, 'account_switched')}_to_{next_profile_id}"
        execution_id = self.storage.create_outreach_execution(
            action_id,
            action_type,
            str(action.get("target_username") or ""),
            status="account_switched",
            profile_id=profile_id,
            evidence_path=evidence_path,
            error_code=error_code,
            error_message=message,
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "account_switched",
            error_code=error_code,
            error_message=message,
            retryable=False,
        )
        self.storage.log_event(
            "action_router_account_switched",
            action_id,
            {"profile_id": profile_id, "next_profile_id": next_profile_id, "execution_id": execution_id, "error_code": error_code, "attempt": attempt},
        )
        return {
            "action_id": action_id,
            "execution_id": execution_id,
            "action_type": action_type,
            "public_action_type": PUBLIC_ACTION_TYPE.get(action_type, action_type),
            "status": "account_switched",
            "profile_id": profile_id,
            "next_profile_id": next_profile_id,
            "attempt": attempt,
            "error_code": error_code,
            "error_message": message,
            "evidence_path": evidence_path,
        }

    def _fallback_action(self, action: dict, error_code: str, create: bool = True, batch_id: str = "") -> dict:
        if error_code and error_code not in FALLBACK_CODES:
            return {}
        chain = FALLBACK_CHAIN.get(str(action.get("action_type") or ""), [])
        if not chain:
            return {}
        lead_id = str(action.get("lead_id") or "")
        target_batch_id = str(action.get("batch_id") or batch_id or "")
        existing = self.storage.list_action_queue(limit=1000, batch_id=target_batch_id) if target_batch_id else self.storage.list_action_queue(limit=1000)
        by_type = {str(row.get("action_type") or ""): row for row in existing if str(row.get("lead_id") or "") == lead_id}
        for fallback_type in chain:
            if fallback_type in by_type:
                return by_type[fallback_type]
            if create:
                item = ActionQueueItem(
                    id=new_id("aq"),
                    lead_id=lead_id,
                    action_type=fallback_type,
                    target_username=str(action.get("target_username") or ""),
                    target_url=str(action.get("source_path") or action.get("target_url") or ""),
                    suggested_text=str(action.get("suggested_text") or ""),
                    status="pending",
                    risk_level=str(action.get("risk_level") or "medium"),
                )
                action_id, _ = self.storage.upsert_action_queue_item(item)
                if target_batch_id:
                    with self.storage.connect() as conn:
                        conn.execute(
                            "UPDATE action_queue SET batch_id=COALESCE(NULLIF(batch_id, ''), ?) WHERE id=?",
                            (target_batch_id, action_id),
                        )
                rows = [row for row in self.storage.list_action_queue(limit=1000) if row.get("id") == action_id]
                return rows[0] if rows else item.__dict__
        return {}

    def _next_profile(self, profiles: list[dict], current_profile: dict) -> dict:
        current_id = str(current_profile.get("profile_id") or current_profile.get("id") or "")
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            if profile_id != current_id and not self._profile_is_cooldown(profile_id):
                return profile
        return {}

    def _profile_is_cooldown(self, profile_id: str) -> bool:
        if not profile_id:
            return False
        for row in self.storage.list_profile_health(limit=1000):
            if str(row.get("profile_id") or "") == str(profile_id):
                return str(row.get("status") or "").lower() == "cooldown"
        return False

    def _profile_execution_lock(self, profile_id: str) -> threading.Lock:
        key = str(profile_id or "unknown")
        with self._lock:
            lock = self._profile_locks.get(key)
            if not lock:
                lock = threading.Lock()
                self._profile_locks[key] = lock
            return lock

    def _sleep(self, config: ActionRouterConfig):
        low = max(0.0, float(config.min_delay_seconds or 0))
        high = max(low, float(config.max_delay_seconds or 0))
        if high:
            import random

            time.sleep(random.uniform(low, high))

    def _summary(self, actions: list[dict], profiles: list[dict], results: list[dict]) -> dict:
        counts: dict[str, int] = {}
        errors: dict[str, int] = {}
        for row in results:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            if row.get("error_code"):
                code = str(row.get("error_code"))
                errors[code] = errors.get(code, 0) + 1
        profile_ids = {
            str(profile.get("profile_id") or profile.get("id") or "")
            for profile in profiles or []
            if str(profile.get("profile_id") or profile.get("id") or "")
        }
        profile_health = []
        cooldown_profile_ids = []
        for row in self.storage.list_profile_health(limit=1000):
            profile_id = str(row.get("profile_id") or "")
            if profile_ids and profile_id not in profile_ids:
                continue
            item = {
                "profile_id": profile_id,
                "group_name": str(row.get("group_name") or ""),
                "status": str(row.get("status") or "healthy"),
                "health_score": int(row.get("health_score") or 0),
                "consecutive_failures": int(row.get("consecutive_failures") or 0),
                "last_error_code": str(row.get("last_error_code") or ""),
            }
            profile_health.append(item)
            if item["status"] == "cooldown":
                cooldown_profile_ids.append(profile_id)
        return {
            "selected_actions": len(actions),
            "worker_count": len(profiles),
            "attempt_count": len([row for row in results if row.get("status") != "account_switched"]),
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "account_switched": counts.get("account_switched", 0),
            "errors": errors,
            "cooldown_profiles": len(cooldown_profile_ids),
            "cooldown_profile_ids": cooldown_profile_ids,
            "profile_health": profile_health,
            "results": results,
        }
