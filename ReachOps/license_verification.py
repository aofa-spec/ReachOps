# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_VERIFICATION_INTERVAL_HOURS = 24


@dataclass(frozen=True)
class LicenseVerificationState:
    status: str
    verification_required: bool
    interval_hours: int
    last_verified_at: str
    next_verify_at: str
    reason_code: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "verification_required": self.verification_required,
            "interval_hours": self.interval_hours,
            "last_verified_at": self.last_verified_at,
            "next_verify_at": self.next_verify_at,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


def evaluate_license_verification_state(
    activation_status: dict[str, Any],
    *,
    now: datetime | None = None,
    default_interval_hours: int = DEFAULT_VERIFICATION_INTERVAL_HOURS,
) -> LicenseVerificationState:
    status = activation_status if isinstance(activation_status, dict) else {}
    now = _normalize_datetime(now or datetime.now(timezone.utc))
    interval_hours = _interval_hours(status, default_interval_hours)
    last_verified_at = str(
        status.get("last_verified_at")
        or status.get("verified_at")
        or status.get("last_license_check_at")
        or ""
    ).strip()
    explicit_next = str(status.get("next_verify_at") or status.get("next_license_check_at") or "").strip()
    last_verified = _parse_datetime(last_verified_at)
    next_verify = _parse_datetime(explicit_next) if explicit_next else None
    if next_verify is None and last_verified is not None:
        next_verify = last_verified + timedelta(hours=interval_hours)

    if not status:
        return _state("missing", True, interval_hours, last_verified_at, "", "LICENSE_STATUS_MISSING", "activation status not found")
    if last_verified is None and next_verify is None:
        return _state(
            "verification_due",
            True,
            interval_hours,
            last_verified_at,
            explicit_next,
            "LICENSE_VERIFICATION_REQUIRED",
            "license has not been verified on this device",
        )
    next_text = _format_utc(next_verify) if next_verify is not None else explicit_next
    if next_verify is not None and next_verify <= now:
        return _state(
            "verification_due",
            True,
            interval_hours,
            last_verified_at,
            next_text,
            "LICENSE_VERIFICATION_REQUIRED",
            "license verification is due",
        )
    return _state("fresh", False, interval_hours, last_verified_at, next_text, "", "")


def _interval_hours(status: dict[str, Any], default_interval_hours: int) -> int:
    for value in [
        status.get("verification_interval_hours"),
        status.get("license_verification_interval_hours"),
        status.get("check_interval_hours"),
        default_interval_hours,
    ]:
        try:
            parsed = int(value)
        except Exception:
            continue
        if parsed > 0:
            return parsed
    return DEFAULT_VERIFICATION_INTERVAL_HOURS


def _state(
    status: str,
    verification_required: bool,
    interval_hours: int,
    last_verified_at: str,
    next_verify_at: str,
    reason_code: str,
    reason: str,
) -> LicenseVerificationState:
    return LicenseVerificationState(
        status=status,
        verification_required=verification_required,
        interval_hours=interval_hours,
        last_verified_at=last_verified_at,
        next_verify_at=next_verify_at,
        reason_code=reason_code,
        reason=reason,
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
