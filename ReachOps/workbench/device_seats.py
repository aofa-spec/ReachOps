# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeviceSeatDecision:
    allowed: bool
    state: str
    error_code: str = ""
    error_message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _clean_device_id(value: Any) -> str:
    return str(value or "").strip()


def _append_unique(values: list[str], value: Any) -> None:
    item = _clean_device_id(value)
    if item and item not in values:
        values.append(item)


def _read_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _collect_assigned_devices(status: dict[str, Any]) -> list[str]:
    assigned: list[str] = []
    _append_unique(assigned, status.get("device_id"))
    for key in ("device_ids", "allowed_device_ids", "assigned_device_ids"):
        values = status.get(key)
        if isinstance(values, list):
            for value in values:
                _append_unique(assigned, value)
    for container_key in ("device_seats", "seats", "seat_entitlements"):
        container = status.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("device_id", "device_ids", "allowed_device_ids", "assigned_device_ids"):
            values = container.get(key)
            if isinstance(values, list):
                for value in values:
                    _append_unique(assigned, value)
            else:
                _append_unique(assigned, values)
    return assigned


def _seat_limit(status: dict[str, Any], assigned_count: int) -> int:
    default = max(1, assigned_count or 1)
    for container_key in ("device_seats", "seats", "seat_entitlements"):
        container = status.get(container_key)
        if isinstance(container, dict):
            for key in ("max_devices", "seat_count", "seats", "allowed_devices"):
                if key in container:
                    return _read_positive_int(container.get(key), default)
    for key in ("max_devices", "seat_count", "seats", "allowed_devices"):
        if key in status:
            return _read_positive_int(status.get(key), default)
    return default


def evaluate_device_seat(status: dict[str, Any], current_device_id: str) -> DeviceSeatDecision:
    """Evaluate local device entitlement without contacting a server.

    Compatibility rules:
    - Legacy activation files with a single ``device_id`` remain one-device licenses.
    - Blank device assignment remains allowed so existing activation bootstrap flows
      can bind a device before live acceptance.
    - Explicit seat lists support additional purchased devices and are enforced
      before live outreach is allowed.
    """

    payload = status if isinstance(status, dict) else {}
    current = _clean_device_id(current_device_id)
    assigned = _collect_assigned_devices(payload)
    seat_limit = _seat_limit(payload, len(assigned))
    evidence = {
        "current_device_id": current,
        "assigned_device_ids": assigned,
        "assigned_device_count": len(assigned),
        "seat_limit": seat_limit,
        "default_one_device": "device_seats" not in payload and "seats" not in payload and "seat_entitlements" not in payload,
        "local_data_access_allowed": True,
        "live_submit_scope": True,
    }
    if not current:
        return DeviceSeatDecision(False, "current_device_unknown", "LIVE_SUBMIT_DEVICE_UNKNOWN", "current device id is unavailable", evidence)
    if not assigned:
        return DeviceSeatDecision(True, "unbound_single_device_pending_binding", evidence={**evidence, "binding_required": True})
    if len(assigned) > seat_limit:
        return DeviceSeatDecision(
            False,
            "seat_limit_exceeded",
            "LIVE_SUBMIT_SEAT_LIMIT_EXCEEDED",
            "activation assigns more devices than the purchased seat limit",
            evidence,
        )
    if current not in assigned:
        return DeviceSeatDecision(
            False,
            "device_not_assigned_to_seat",
            "LIVE_SUBMIT_DEVICE_MISMATCH",
            "activation is not assigned to this device seat",
            evidence,
        )
    extra_seats = max(0, seat_limit - 1)
    return DeviceSeatDecision(
        True,
        "assigned",
        evidence={
            **evidence,
            "extra_seats": extra_seats,
            "seat_index": assigned.index(current) + 1,
        },
    )
