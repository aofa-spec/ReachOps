# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ProfileGroupMoveResult:
    ok: bool
    profile_id: str
    group_id: str = ""
    group_name: str = ""
    error_code: str = ""
    error_message: str = ""


class IxProfileGroupManager:
    """Small standalone ixBrowser group manager for quarantining bad Profiles."""

    def __init__(
        self,
        group_name: str = "封禁账号",
        client_factory: Callable[[], Any] | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.group_name = str(group_name or "封禁账号").strip() or "封禁账号"
        self.client_factory = client_factory or self._default_client_factory
        self.logger = logger or (lambda _message: None)
        self._lock = threading.Lock()
        self._group_id = ""
        self._last_error_code = ""
        self._last_error_message = ""

    def move_profile_to_quarantine(self, profile_id: str, reason: str = "") -> ProfileGroupMoveResult:
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return ProfileGroupMoveResult(False, profile_id, error_code="PROFILE_ID_EMPTY", error_message="profile id is empty")
        if not profile_id.isdigit():
            return ProfileGroupMoveResult(False, profile_id, error_code="PROFILE_ID_INVALID", error_message="profile id must be numeric")
        try:
            client = self.client_factory()
        except Exception as exc:
            return ProfileGroupMoveResult(False, profile_id, error_code="IX_CLIENT_UNAVAILABLE", error_message=str(exc))
        self._last_error_code = ""
        self._last_error_message = ""
        group_id = self.ensure_group(client)
        if not group_id:
            return ProfileGroupMoveResult(
                False,
                profile_id,
                error_code=self._last_error_code or "IX_GROUP_UNAVAILABLE",
                error_message=self._last_error_message or f"group not found: {self.group_name}",
            )
        try:
            result = client.update_profile_groups_in_batches(int(profile_id), int(group_id))
        except Exception as exc:
            return ProfileGroupMoveResult(False, profile_id, str(group_id), self.group_name, "IX_PROFILE_GROUP_MOVE_FAILED", str(exc))
        if result is False or (isinstance(result, dict) and int((result.get("error") or {}).get("code") or 0) != 0):
            message = "API returned false"
            if isinstance(result, dict):
                message = str((result.get("error") or {}).get("message") or message)
            return ProfileGroupMoveResult(False, profile_id, str(group_id), self.group_name, "IX_PROFILE_GROUP_MOVE_FAILED", message)
        self.logger(f"profile {profile_id} moved to {self.group_name}: {reason}")
        return ProfileGroupMoveResult(True, profile_id, str(group_id), self.group_name)

    def ensure_group(self, client: Any | None = None) -> str:
        with self._lock:
            if self._group_id:
                return self._group_id
        client = client or self.client_factory()
        group_id, group_name = self._find_group(client)
        if not group_id:
            group_id = self._create_group(client)
            group_name = self.group_name if group_id else ""
        if group_id:
            with self._lock:
                self._group_id = str(group_id)
            return str(group_id)
        return ""

    def _find_group(self, client: Any) -> tuple[str, str]:
        prefix_match: tuple[str, str] = ("", "")
        for page in range(1, 101):
            response = client.get_group_list(page=page, limit=100) or []
            if response == [] and getattr(client, "code", None) is not None:
                self._record_client_error(client, "IX_GROUP_LIST_UNAVAILABLE")
                break
            rows = self._extract_group_rows(response)
            for row in rows:
                title = str(row.get("title") or row.get("group_name") or row.get("groupName") or row.get("name") or "").strip()
                group_id = str(row.get("id") or row.get("group_id") or row.get("groupId") or "").strip()
                if not group_id:
                    continue
                if title == self.group_name:
                    return group_id, title
                if title.startswith(f"{self.group_name}-") and not prefix_match[0]:
                    prefix_match = (group_id, title)
            total = getattr(client, "total", None)
            if total and page * 100 >= int(total):
                break
            if not total and len(rows) < 100:
                break
        return prefix_match

    @staticmethod
    def _extract_group_rows(response: Any) -> list[dict]:
        rows = response
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = []
                for key in ("records", "list", "rows", "items", "data"):
                    value = data.get(key)
                    if isinstance(value, list):
                        rows = value
                        break
            else:
                rows = []
                for key in ("records", "list", "rows", "items"):
                    value = response.get(key)
                    if isinstance(value, list):
                        rows = value
                        break
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _create_group(self, client: Any) -> str:
        response = client.create_group(self.group_name, sort=0)
        if response is None and getattr(client, "code", None) is not None:
            self._record_client_error(client, "IX_GROUP_CREATE_FAILED")
            return ""
        if isinstance(response, dict):
            for key in ("id", "group_id", "groupId", "data"):
                value = response.get(key)
                if isinstance(value, dict):
                    value = value.get("id") or value.get("group_id") or value.get("groupId")
                if value:
                    return str(value)
            error_code = int((response.get("error") or {}).get("code") or 0)
            if error_code == 105003:
                group_id, _name = self._find_group(client)
                return group_id
        elif response:
            return str(response)
        group_id, _name = self._find_group(client)
        return group_id

    def _record_client_error(self, client: Any, fallback_code: str) -> None:
        code = getattr(client, "code", None)
        message = str(getattr(client, "message", "") or "")
        self._last_error_code = fallback_code
        self._last_error_message = f"ixBrowser local API error code={code} message={message}".strip()

    @staticmethod
    def _default_client_factory():
        from ixbrowser_local_api import IXBrowserClient

        return IXBrowserClient()
