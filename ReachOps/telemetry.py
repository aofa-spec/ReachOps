# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from typing import Any


TELEMETRY_SCHEMA_VERSION = "reachops.telemetry_policy.v1"
REDACTION_TEXT = "***redacted***"

ALLOWED_FIELDS = {
    "reachops_version",
    "windows_version",
    "error_code",
    "failing_module",
    "crash_stack",
    "duration_ms",
    "ixbrowser_active",
    "installation_id",
}

FORBIDDEN_FIELD_TOKENS = (
    "comment",
    "cookie",
    "credential",
    "database",
    "dom",
    "password",
    "product",
    "proxy",
    "screenshot",
    "secret",
    "session",
    "sqlite",
    "target",
    "text",
    "token",
    "url",
    "username",
)

REDACTION_PATTERNS = (
    re.compile(r"https?://(?:www\.)?tiktok\.com/\S+", re.IGNORECASE),
    re.compile(r"(?<![\w.-])@[\w.-]{2,}", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)(api[_-]?key|license[_-]?key|password|proxy[_-]?password|token|secret)=\S+"),
    re.compile(r"(?i)(cookies?=)\S+"),
)


def build_telemetry_policy_status(*, opt_in: bool = False) -> dict[str, Any]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "telemetry_enabled": bool(opt_in),
        "default_off": True,
        "requires_explicit_opt_in": True,
        "customer_data_uploaded": False,
        "allowed_fields": sorted(ALLOWED_FIELDS),
        "forbidden_field_tokens": list(FORBIDDEN_FIELD_TOKENS),
    }


def build_telemetry_payload(event: dict[str, Any] | None, *, opt_in: bool = False) -> dict[str, Any]:
    policy = build_telemetry_policy_status(opt_in=opt_in)
    if not opt_in:
        return {
            **policy,
            "status": "disabled",
            "payload": {},
            "dropped_fields": sorted(str(key) for key in (event or {}).keys()),
        }
    payload: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in (event or {}).items():
        normalized = str(key or "").strip()
        if normalized not in ALLOWED_FIELDS or _forbidden_key(normalized):
            dropped.append(normalized)
            continue
        payload[normalized] = _sanitize_allowed_value(normalized, value)
    return {
        **policy,
        "status": "ready",
        "payload": payload,
        "dropped_fields": sorted(dropped),
        "redaction_applied": True,
        "no_screenshots_or_dom": True,
        "no_cookies_or_credentials": True,
        "no_sqlite_files": True,
        "no_customer_targets_or_usernames": True,
    }


def _sanitize_allowed_value(key: str, value: Any) -> Any:
    if key == "installation_id":
        return _anonymous_installation_id(value)
    if key == "duration_ms":
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0
    if key == "ixbrowser_active":
        return bool(value)
    text = str(value if value is not None else "")
    if key == "crash_stack":
        return _redact_text(text)[:8000]
    return _redact_text(text)[:500]


def _anonymous_installation_id(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"anon_{digest[:24]}"


def _redact_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(REDACTION_TEXT, redacted)
    return redacted


def _forbidden_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return any(token in normalized for token in FORBIDDEN_FIELD_TOKENS)
