# -*- coding: utf-8 -*-
from __future__ import annotations

from ReachOps.intelligence.storage import GrowthStorage


COOLDOWN_ERROR_CODES = {
    "PROFILE_MISSING",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "PROFILE_START_FAILED",
    "IXBROWSER_KERNEL_MISMATCH",
    "PROFILE_PREFLIGHT_TIMEOUT",
    "ACCOUNT_RESTRICTED",
    "RATE_LIMITED",
    "COMMENT_BLOCKED",
    "COMMENT_ACCESS_GATED",
    "FOLLOW_RATE_LIMITED",
    "DM_RATE_LIMITED",
}

IMMEDIATE_COOLDOWN_ERROR_CODES = {
    "PROFILE_MISSING",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "PROFILE_START_FAILED",
    "PAGE_OPEN_FAILED",
    "BROWSER_CRASHED",
    "PROFILE_PREFLIGHT_TIMEOUT",
    "IXBROWSER_KERNEL_MISMATCH",
    "ACCOUNT_RESTRICTED",
    "COMMENT_ACCESS_GATED",
}

TRANSIENT_START_ERROR_CODES = {
    "IXBROWSER_SERVER_BUSY",
    "IXBROWSER_NETWORK_ERROR",
    "BROWSER_CRASHED",
    "PROFILE_PREFLIGHT_TIMEOUT",
}

EXECUTION_GROUP_HINTS = {
    "action",
    "actions",
    "comment",
    "comments",
    "discovery",
    "discover",
    "outreach",
    "growth",
    "lead",
    "leads",
}

PUBLISH_GROUP_HINTS = {
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
}


class AccountHealthManager:
    """Ranks execution profiles and updates health after action attempts."""

    def __init__(self, storage: GrowthStorage, cooldown_after_failures: int = 3):
        self.storage = storage
        self.cooldown_after_failures = max(1, int(cooldown_after_failures or 3))

    def rank_profiles(self, profiles: list[dict], group_name: str = "", max_count: int = 0) -> list[dict]:
        rows = list(profiles or [])
        if group_name:
            rows = [row for row in rows if self._matches_group(row, group_name)]
        health = {str(row.get("profile_id") or ""): row for row in self.storage.list_profile_health(limit=10000)}
        status_rank = {"healthy": 0, "degraded": 1, "cooldown": 9}

        usable_rows = []
        for row in rows:
            profile_id = str(row.get("profile_id") or row.get("id") or "")
            item = health.get(profile_id, {})
            status = str(item.get("status") or "").lower()
            error_code = str(item.get("last_error_code") or "")
            if error_code in IMMEDIATE_COOLDOWN_ERROR_CODES:
                continue
            if status == "cooldown" and not self._retryable_cooldown(item):
                continue
            usable_rows.append(row)
        rows = usable_rows

        def sort_key(profile: dict):
            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            item = health.get(profile_id, {})
            status = str(item.get("status") or "healthy")
            return (
                self._usage_rank(profile),
                status_rank.get(status, 2),
                self._transient_rank(item),
                int(item.get("consecutive_failures") or 0),
                -int(item.get("health_score") or 100),
                profile_id,
            )

        ranked = sorted(rows, key=sort_key)
        if max_count:
            ranked = ranked[: max(1, int(max_count))]
        return ranked

    def _retryable_cooldown(self, health_row: dict) -> bool:
        code = str(health_row.get("last_error_code") or "")
        message = str(health_row.get("last_error_message") or "")
        if code in TRANSIENT_START_ERROR_CODES:
            return True
        if code == "PROFILE_START_FAILED" and self._looks_transient_start_failure(message):
            return True
        return False

    def _transient_rank(self, health_row: dict) -> int:
        return 1 if self._retryable_cooldown(health_row) else 0

    def _looks_transient_start_failure(self, message: str) -> bool:
        text = str(message or "").lower()
        return any(
            token in text
            for token in [
                "server busy",
                "code=1008",
                "econnreset",
                "network socket",
                "chrome not reachable",
                "invalid session id",
                "no such window",
                "target window already closed",
            ]
        )

    def _usage_rank(self, profile: dict) -> int:
        joined = " ".join(
            str(profile.get(key) or "")
            for key in ["profile_id", "id", "name", "group_name", "group_id", "tag", "usage", "purpose"]
        ).lower()
        if any(token in joined for token in PUBLISH_GROUP_HINTS):
            return 9
        if any(token in joined for token in EXECUTION_GROUP_HINTS):
            return 0
        return 2

    def _matches_group(self, profile: dict, group_name: str) -> bool:
        requested = self._tokens(group_name)
        if not requested:
            return True
        target_text = " ".join(
            str(profile.get(key) or "")
            for key in ["profile_id", "id", "name", "group_name", "group_id", "tag", "usage", "purpose"]
        )
        target = self._tokens(target_text)
        if len(requested) == 1:
            return bool(requested & target)
        return requested.issubset(target)

    def _tokens(self, value: str) -> set[str]:
        tokens = set()
        for part in str(value or "").replace("_", " ").replace("-", " ").replace("/", " ").split():
            clean = "".join(ch for ch in part.lower() if ch.isalnum())
            if clean:
                tokens.add(clean)
        return tokens

    def should_cooldown(self, profile_id: str, error_code: str = "") -> bool:
        if str(error_code or "") in IMMEDIATE_COOLDOWN_ERROR_CODES:
            return True
        health = {str(row.get("profile_id") or ""): row for row in self.storage.list_profile_health(limit=10000)}
        row = health.get(str(profile_id or ""), {})
        return int(row.get("consecutive_failures") or 0) >= self.cooldown_after_failures

    def record_success(self, profile: dict) -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        row = self.storage.record_profile_health(
            profile_id,
            group_name=str(profile.get("group_name") or ""),
            ok=True,
        )
        return dict(row.__dict__)

    def record_failure(self, profile: dict, error_code: str, error_message: str = "") -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        row = self.storage.record_profile_health(
            profile_id,
            group_name=str(profile.get("group_name") or ""),
            ok=False,
            error_code=str(error_code or ""),
            error_message=str(error_message or ""),
        )
        should_force_cooldown = str(error_code or "") in IMMEDIATE_COOLDOWN_ERROR_CODES or int(
            getattr(row, "consecutive_failures", 0) or 0
        ) >= self.cooldown_after_failures
        if should_force_cooldown:
            row = self._force_cooldown(profile_id, str(error_code or ""), str(error_message or ""))
        return dict(row.__dict__)

    def _force_cooldown(self, profile_id: str, error_code: str, error_message: str):
        return self.storage.force_profile_cooldown(profile_id, error_code=error_code, error_message=error_message or error_code)
