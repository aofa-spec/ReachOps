# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


LICENSE_GRACE_DAYS = 7
LIVE_SUBMIT_FEATURE = "live_submit"


@dataclass(frozen=True)
class LicenseState:
    status: str
    client_access_allowed: bool
    live_submit_allowed: bool
    reason_code: str
    reason: str
    grace_days: int = LICENSE_GRACE_DAYS
    grace_expires_at: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "client_access_allowed": self.client_access_allowed,
            "live_submit_allowed": self.live_submit_allowed,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "grace_days": self.grace_days,
            "grace_expires_at": self.grace_expires_at,
            "expires_at": self.expires_at,
        }


class LicenseStateEvaluator:
    """Local license status state machine.

    Grace keeps the local client usable for bounded offline recovery, but it is
    never sufficient for live platform actions.
    """

    def __init__(self, grace_days: int = LICENSE_GRACE_DAYS):
        self.grace_days = max(0, int(grace_days))

    def evaluate(self, payload: dict[str, Any], now: datetime | None = None) -> LicenseState:
        now = self._coerce_now(now)
        if not isinstance(payload, dict) or not payload:
            return self._state("missing", False, False, "LICENSE_STATUS_MISSING", "license status not found")
        expires_at = str(payload.get("expires_at") or "").strip()
        if bool(payload.get("template_only")):
            return self._state("template", False, False, "LICENSE_TEMPLATE_ONLY", "license status is a template", expires_at=expires_at)
        if not bool(payload.get("active")):
            return self._state("inactive", False, False, "LICENSE_INACTIVE", "license is inactive", expires_at=expires_at)
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
        if capabilities.get("client_access") is False:
            return self._state("client_disabled", False, False, "LICENSE_CLIENT_ACCESS_DISABLED", "client access capability is disabled", expires_at=expires_at)
        expires = self._parse_time(expires_at)
        if expires is None:
            return self._state("invalid_expiry", False, False, "LICENSE_EXPIRY_INVALID", "license expiry is missing or invalid", expires_at=expires_at)
        if expires > now:
            return self._state(
                "active",
                True,
                bool(capabilities.get(LIVE_SUBMIT_FEATURE)),
                "LICENSE_ACTIVE",
                "license is active",
                expires_at=expires_at,
            )
        grace_expires = expires + timedelta(days=self.grace_days)
        if now <= grace_expires and self.grace_days > 0:
            return self._state(
                "grace",
                True,
                False,
                "LICENSE_GRACE_PERIOD",
                "license is expired but within offline grace period; live submit remains blocked",
                expires_at=expires_at,
                grace_expires_at=self._format_time(grace_expires),
            )
        return self._state(
            "expired",
            False,
            False,
            "LICENSE_EXPIRED",
            "license is expired and outside grace period",
            expires_at=expires_at,
            grace_expires_at=self._format_time(grace_expires),
        )

    def _state(
        self,
        status: str,
        client_access_allowed: bool,
        live_submit_allowed: bool,
        reason_code: str,
        reason: str,
        expires_at: str = "",
        grace_expires_at: str = "",
    ) -> LicenseState:
        return LicenseState(
            status=status,
            client_access_allowed=client_access_allowed,
            live_submit_allowed=live_submit_allowed,
            reason_code=reason_code,
            reason=reason,
            grace_days=self.grace_days,
            grace_expires_at=grace_expires_at,
            expires_at=expires_at,
        )

    def _coerce_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _parse_time(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _format_time(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
