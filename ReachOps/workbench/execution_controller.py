# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Protocol

from ReachOps.intelligence.storage import GrowthStorage

from .execution_guard import ExecutionGuard


TECHNICAL_RETRYABLE_CODES = {
    "PROFILE_START_FAILED",
    "PAGE_OPEN_FAILED",
    "PROXY_FAILED",
    "BROWSER_CRASHED",
    "LOGIN_REQUIRED",
}

COOLDOWN_CODES = {
    "CAPTCHA_DETECTED",
    "RATE_LIMITED",
    "COMMENT_BLOCKED",
    "FOLLOW_RATE_LIMITED",
    "DM_RATE_LIMITED",
    "ACCOUNT_RESTRICTED",
}


@dataclass
class ExecutionMVPConfig:
    max_workers: int = 2
    per_profile_action_limit: int = 5
    max_switch_attempts: int = 2
    min_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    action_types: list[str] = field(default_factory=lambda: ["comment_reply"])
    auto_approve: bool = False
    auto_confirm: bool = False
    dry_run: bool = True


class PlatformActionExecutor(Protocol):
    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        ...


class FixturePlatformActionExecutor:
    """Deterministic executor used by pressure tests and tonight's MVP smoke."""

    def __init__(self, outcomes: list[dict] | None = None):
        self.outcomes = list(outcomes or [])
        self._lock = threading.Lock()
        self._index = 0

    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        with self._lock:
            if self.outcomes:
                outcome = dict(self.outcomes[self._index % len(self.outcomes)])
                self._index += 1
            else:
                outcome = {"status": "success", "error_code": ""}
        if outcome.get("status") == "success":
            return {
                "status": "success",
                "error_code": "",
                "error_message": "",
                "evidence_path": "",
                "rendered_text": rendered_text,
            }
        return {
            "status": "failed",
            "error_code": str(outcome.get("error_code") or "OUTREACH_EXECUTION_FAILED"),
            "error_message": str(outcome.get("error_message") or outcome.get("error_code") or "fixture failure"),
            "evidence_path": str(outcome.get("evidence_path") or ""),
            "rendered_text": rendered_text,
        }


class ActionTemplateRenderer:
    def __init__(self, storage: GrowthStorage, seed: int | None = None):
        self.storage = storage
        self.random = random.Random(seed)

    def render(self, action: dict) -> dict:
        action_type = str(action.get("action_type") or "")
        fallback = str(action.get("suggested_text") or "")
        body = self.storage.get_action_template_body(action_type, fallback=fallback)
        variants = [item.strip() for item in str(body or fallback or "").split("||") if item.strip()]
        selected = self.random.choice(variants) if variants else fallback
        values = {
            "username": str(action.get("target_username") or ""),
            "lead_type": str(action.get("lead_type") or ""),
            "score": str(action.get("lead_score") or action.get("score") or ""),
            "reason": str(action.get("reason") or ""),
        }
        try:
            rendered = selected.format(**values)
        except Exception:
            rendered = selected
        return {"template_body": body, "rendered_text": rendered, "variant_count": len(variants)}


class ExecutionMVPController:
    """Small multi-profile execution controller for the GrowthOps Execution MVP."""

    def __init__(
        self,
        storage: GrowthStorage,
        guard: ExecutionGuard,
        platform_executor: PlatformActionExecutor | None = None,
        template_renderer: ActionTemplateRenderer | None = None,
    ):
        self.storage = storage
        self.guard = guard
        self.platform_executor = platform_executor or FixturePlatformActionExecutor()
        self.template_renderer = template_renderer or ActionTemplateRenderer(storage)
        self._health_lock = threading.Lock()

    def run(self, profiles: list[dict], config: ExecutionMVPConfig | None = None, limit: int = 100) -> dict:
        config = config or ExecutionMVPConfig()
        profiles = self._select_profiles(profiles, config.max_workers)
        actions = self._select_actions(config, limit)
        queue: Queue[dict] = Queue()
        attempt_counts: dict[str, int] = {}
        lock = threading.Lock()
        results: list[dict] = []
        for action in actions:
            queue.put(action)

        def worker(profile: dict):
            handled = 0
            while handled < config.per_profile_action_limit:
                try:
                    action = queue.get_nowait()
                except Exception:
                    return
                action_id = str(action.get("id") or "")
                with lock:
                    attempt_counts[action_id] = attempt_counts.get(action_id, 0) + 1
                    attempt_no = attempt_counts[action_id]
                result = self._execute_once(action, profile, config, attempt_no)
                with lock:
                    results.append(result)
                current_profile = profile
                while result.get("retry_with_next_profile") and attempt_no < config.max_switch_attempts:
                    next_profile = self._next_profile(profiles, str(current_profile.get("profile_id") or current_profile.get("id") or ""))
                    if not next_profile:
                        break
                    current_profile = next_profile
                    with lock:
                        attempt_counts[action_id] = attempt_counts.get(action_id, 0) + 1
                        attempt_no = attempt_counts[action_id]
                    result = self._execute_once(action, current_profile, config, attempt_no)
                    with lock:
                        results.append(result)
                handled += 1
                self._sleep(config)
                queue.task_done()

        threads = []
        for profile in profiles:
            thread = threading.Thread(target=worker, args=(profile,), daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()

        summary = self._summary(results, profiles, actions)
        self.storage.log_event("execution_mvp_pressure_completed", "", summary)
        return summary

    def _select_profiles(self, profiles: list[dict], max_workers: int) -> list[dict]:
        rows = list(profiles or [])
        health = {str(row.get("profile_id") or ""): row for row in self.storage.list_profile_health(limit=1000)}

        def key(profile: dict):
            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            item = health.get(profile_id, {})
            status = str(item.get("status") or "healthy")
            status_rank = {"healthy": 0, "degraded": 1, "cooldown": 2}
            return (status_rank.get(status, 1), -int(item.get("health_score") or 100), profile_id)

        selected = sorted(rows, key=key)[: max(1, int(max_workers or 1))]
        return selected

    def _next_profile(self, profiles: list[dict], failed_profile_id: str) -> dict:
        candidates = [
            profile
            for profile in profiles
            if str(profile.get("profile_id") or profile.get("id") or "") != str(failed_profile_id or "")
        ]
        return candidates[0] if candidates else {}

    def _select_actions(self, config: ExecutionMVPConfig, limit: int) -> list[dict]:
        allowed_types = set(config.action_types or [])
        rows = []
        for action in self.storage.list_action_queue(limit=limit):
            if allowed_types and action.get("action_type") not in allowed_types:
                continue
            if action.get("status") in {"pending_review"} and config.auto_approve:
                self.storage.update_action_status(action["id"], "approved", "execution mvp auto approve")
                action["status"] = "approved"
            if action.get("status") in {"approved", "retryable"} and config.auto_confirm and not int(action.get("execution_confirmed") or 0):
                self.storage.confirm_action_execution(action["id"], confirmed_by="execution_mvp", note="execution mvp auto confirm")
                action["execution_confirmed"] = 1
            if action.get("status") in {"approved", "retryable"}:
                rows.append(action)
        return rows

    def _execute_once(self, action: dict, profile: dict, config: ExecutionMVPConfig, attempt_no: int) -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        action_id = str(action.get("id") or "")
        allowed, block_code = self.guard.check(action, profile_id)
        if not allowed:
            return self._record_blocked(action, profile, block_code, attempt_no)
        quota_ok, used, limit = self.storage.check_daily_quota(
            profile_id,
            str(action.get("action_type") or ""),
            self.guard.policy.max_actions_per_profile_day,
        )
        if not quota_ok:
            return self._record_blocked(action, profile, "DAILY_QUOTA_EXCEEDED", attempt_no, f"{used}/{limit}")
        rendered = self.template_renderer.render(action)
        platform_result = self.platform_executor.execute(action, profile, rendered["rendered_text"], dry_run=config.dry_run)
        status = str(platform_result.get("status") or "")
        if status == "success":
            execution_id = self.storage.create_outreach_execution(
                action_id,
                str(action.get("action_type") or ""),
                str(action.get("target_username") or ""),
                status="completed",
                profile_id=profile_id,
                evidence_path=str(platform_result.get("evidence_path") or ""),
            )
            self.storage.record_action_execution_result(action_id, execution_id, "completed", error_message=rendered["rendered_text"])
            self.storage.increment_daily_quota(profile_id, str(action.get("action_type") or ""), self.guard.policy.max_actions_per_profile_day)
            self.guard.record_success(profile_id)
            self._record_profile_health(profile_id, str(profile.get("group_name") or ""), True)
            self.storage.log_event(
                "execution_mvp_action_completed",
                action_id,
                {"profile_id": profile_id, "execution_id": execution_id, "attempt": attempt_no, "template": rendered},
            )
            return {
                "action_id": action_id,
                "execution_id": execution_id,
                "status": "completed",
                "profile_id": profile_id,
                "attempt": attempt_no,
                "template_text": rendered["rendered_text"],
            }
        error_code = str(platform_result.get("error_code") or "OUTREACH_EXECUTION_FAILED")
        retryable = error_code in TECHNICAL_RETRYABLE_CODES
        cooldown = error_code in COOLDOWN_CODES
        execution_id = self.storage.create_outreach_execution(
            action_id,
            str(action.get("action_type") or ""),
            str(action.get("target_username") or ""),
            status="failed",
            profile_id=profile_id,
            evidence_path=str(platform_result.get("evidence_path") or ""),
            error_code=error_code,
            error_message=str(platform_result.get("error_message") or error_code),
        )
        self.storage.record_action_execution_result(
            action_id,
            execution_id,
            "failed",
            error_code=error_code,
            error_message=str(platform_result.get("error_message") or error_code),
            retryable=retryable,
        )
        self.guard.record_failure(profile_id)
        self._record_profile_health(profile_id, str(profile.get("group_name") or ""), False, error_code, str(platform_result.get("error_message") or ""))
        self.storage.log_event(
            "execution_mvp_action_failed",
            action_id,
            {"profile_id": profile_id, "execution_id": execution_id, "attempt": attempt_no, "error_code": error_code, "retryable": retryable, "cooldown": cooldown},
        )
        return {
            "action_id": action_id,
            "execution_id": execution_id,
            "status": "failed",
            "profile_id": profile_id,
            "attempt": attempt_no,
            "error_code": error_code,
            "retryable": retryable,
            "cooldown": cooldown,
            "retry_with_next_profile": retryable,
        }

    def _record_blocked(self, action: dict, profile: dict, code: str, attempt_no: int, message: str = "") -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        action_id = str(action.get("id") or "")
        execution_id = self.storage.create_outreach_execution(
            action_id,
            str(action.get("action_type") or ""),
            str(action.get("target_username") or ""),
            status="skipped",
            profile_id=profile_id,
            error_code=code,
            error_message=message or "blocked by execution mvp guard",
        )
        self.storage.record_action_execution_result(action_id, execution_id, "failed", error_code=code, error_message=message or code, retryable=False)
        self.storage.log_event("execution_mvp_action_blocked", action_id, {"profile_id": profile_id, "execution_id": execution_id, "error_code": code})
        return {"action_id": action_id, "execution_id": execution_id, "status": "blocked", "profile_id": profile_id, "attempt": attempt_no, "error_code": code}

    def _record_profile_health(self, profile_id: str, group_name: str, ok: bool, error_code: str = "", error_message: str = ""):
        with self._health_lock:
            return self.storage.record_profile_health(profile_id, group_name=group_name, ok=ok, error_code=error_code, error_message=error_message)

    def _sleep(self, config: ExecutionMVPConfig):
        low = max(0.0, float(config.min_delay_seconds or 0))
        high = max(low, float(config.max_delay_seconds or 0))
        if high:
            time.sleep(random.uniform(low, high))

    def _summary(self, results: list[dict], profiles: list[dict], actions: list[dict]) -> dict:
        counts: dict[str, int] = {}
        errors: dict[str, int] = {}
        switched = 0
        attempts_by_action: dict[str, int] = {}
        for result in results:
            status = str(result.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            action_id = str(result.get("action_id") or "")
            attempts_by_action[action_id] = max(attempts_by_action.get(action_id, 0), int(result.get("attempt") or 0))
            if result.get("error_code"):
                code = str(result.get("error_code"))
                errors[code] = errors.get(code, 0) + 1
        switched = len([value for value in attempts_by_action.values() if value > 1])
        return {
            "selected_actions": len(actions),
            "worker_count": len(profiles),
            "attempt_count": len(results),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
            "profile_switch_count": switched,
            "errors": errors,
            "results": results,
        }
