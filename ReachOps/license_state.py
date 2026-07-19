# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_LICENSE_GRACE_DAYS = 7


@dataclass(frozen=True)
class LicenseState:
    status: str
    active: bool
    app_access_allowed: bool
    live_submit_allowed: bool
    reason_code: str
    reason: str
    expires_at: str
    grace_until: str
    grace_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "active": self.active,
            "app_access_allowed": self.app_access_allowed,
            "live_submit_allowed": self.live_submit_allowed,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "expires_at": self.expires_at,
            "grace_until": self.grace_until,
            "grace_days": self.grace_days,
        }


def evaluate_license_state(
    activation_status: dict[str, Any],
    *,
    now: datetime | None = None,
    grace_days: int = DEFAULT_LICENSE_GRACE_DAYS,
) -> LicenseState:
    status = activation_status if isinstance(activation_status, dict) else {}
    now = _normalize_datetime(now or datetime.now(timezone.utc))
    grace_days = max(0, int(grace_days))
    expires_at = str(status.get("expires_at") or "").strip()

    if not status:
        return _state("missing", False, False, False, "LICENSE_STATUS_MISSING", "activation status not found", expires_at, "", grace_days)
    if bool(status.get("template_only")):
        return _state("template", False, False, False, "LICENSE_TEMPLATE_ONLY", "activation status is a template", expires_at, "", grace_days)
    if not bool(status.get("active")):
        return _state("inactive", False, False, False, "LICENSE_INACTIVE", "activation is inactive", expires_at, "", grace_days)
    if not expires_at:
        return _state("active", True, True, True, "", "", expires_at, "", grace_days)

    expires = _parse_datetime(expires_at)
    if expires is None:
        return _state("expired", False, False, False, "LIVE_SUBMIT_LICENSE_EXPIRED", "activation expiry is invalid", expires_at, "", grace_days)
    if expires > now:
        return _state("active", True, True, True, "", "", expires_at, _format_utc(expires + timedelta(days=grace_days)), grace_days)

    grace_until = expires + timedelta(days=grace_days)
    if now <= grace_until:
        return _state(
            "grace_period",
            True,
            True,
            False,
            "LIVE_SUBMIT_LICENSE_GRACE_PERIOD",
            "activation is expired but still inside the local app-access grace period",
            expires_at,
            _format_utc(grace_until),
            grace_days,
        )
    return _state(
        "expired",
        False,
        False,
        False,
        "LIVE_SUBMIT_LICENSE_EXPIRED",
        "activation has expired",
        expires_at,
        _format_utc(grace_until),
        grace_days,
    )


def _state(
    status: str,
    active: bool,
    app_access_allowed: bool,
    live_submit_allowed: bool,
    reason_code: str,
    reason: str,
    expires_at: str,
    grace_until: str,
    grace_days: int,
) -> LicenseState:
    return LicenseState(
        status=status,
        active=active,
        app_access_allowed=app_access_allowed,
        live_submit_allowed=live_submit_allowed,
        reason_code=reason_code,
        reason=reason,
        expires_at=expires_at,
        grace_until=grace_until,
        grace_days=grace_days,
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        return _normalize_datetime(parsed)
    except Exception:
        return None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return _normalize_datetime(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")
