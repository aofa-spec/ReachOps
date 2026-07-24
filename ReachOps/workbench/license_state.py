# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


LICENSE_STATE_SCHEMA_VERSION = "reachops.license_state.v1"
GRACE_PERIOD_DAYS = 7
TERMINAL_SUBSCRIPTION_STATES = {"revoked", "chargeback", "fraud", "disabled"}
NONCURRENT_SUBSCRIPTION_STATES = {"canceled", "cancelled", "expired", "past_due", "payment_failed", "unpaid"}


def parse_utc_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def evaluate_license_state(payload: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    status = payload if isinstance(payload, dict) else {}
    if isinstance(now, datetime):
        current_time = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    else:
        current_time = datetime.now(timezone.utc)
    subscription_status = str(status.get("subscription_status") or status.get("subscription_state") or "").strip().lower()
    expires_at = parse_utc_timestamp(status.get("expires_at"))
    last_verified_at = parse_utc_timestamp(status.get("last_verified_at") or status.get("license_verified_at"))
    grace_until = last_verified_at + timedelta(days=GRACE_PERIOD_DAYS) if last_verified_at else None
    revoked = bool(status.get("revoked")) or subscription_status in TERMINAL_SUBSCRIPTION_STATES
    active = bool(status.get("active"))

    state = "active_current"
    reason = ""
    license_ready = False
    live_submit_ready = False
    grace_active = False

    if not status:
        state = "missing"
        reason = "activation status not found"
    elif bool(status.get("template_only")):
        state = "template"
        reason = "activation status is a template"
    elif revoked:
        state = "revoked"
        reason = "license is revoked"
    elif not active:
        state = "inactive"
        reason = "activation is inactive"
    elif expires_at is None:
        state = "invalid_expiry"
        reason = "expires_at is missing or invalid"
    elif expires_at <= current_time:
        state = "expired"
        reason = "license has expired"
    elif subscription_status in NONCURRENT_SUBSCRIPTION_STATES:
        if grace_until and current_time <= grace_until:
            state = "grace"
            reason = "subscription is non-current but within local grace period"
            license_ready = True
            grace_active = True
        else:
            state = "grace_expired"
            reason = "subscription is non-current and grace period has expired"
    else:
        state = "active_current"
        reason = "license is active and current"
        license_ready = True
        live_submit_ready = True

    return {
        "schema_version": LICENSE_STATE_SCHEMA_VERSION,
        "state": state,
        "reason": reason,
        "license_ready": bool(license_ready),
        "live_submit_ready": bool(live_submit_ready),
        "grace_active": bool(grace_active),
        "grace_period_days": GRACE_PERIOD_DAYS,
        "subscription_status": subscription_status,
        "revoked": bool(revoked),
        "active": bool(active),
        "expires_at": _iso(expires_at),
        "last_verified_at": _iso(last_verified_at),
        "grace_until": _iso(grace_until),
        "evaluated_at": _iso(current_time),
        "customer_data_uploaded": False,
        "no_browser_started": True,
        "no_submit": True,
    }
