# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_DEVICE_SEATS = 1


@dataclass(frozen=True)
class DeviceSeatState:
    status: str
    current_device_id: str
    allowed_seats: int
    registered_device_ids: list[str]
    device_allowed: bool
    seat_available: bool
    reason_code: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "current_device_id": self.current_device_id,
            "allowed_seats": self.allowed_seats,
            "registered_device_ids": list(self.registered_device_ids),
            "registered_device_count": len(self.registered_device_ids),
            "device_allowed": self.device_allowed,
            "seat_available": self.seat_available,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


def evaluate_device_seat_state(activation_status: dict[str, Any], current_device_id: str) -> DeviceSeatState:
    status = activation_status if isinstance(activation_status, dict) else {}
    current = _normalize_device_id(current_device_id)
    allowed = _allowed_seats(status)
    registered = _registered_device_ids(status)

    if not current:
        return _state("current_device_missing", current, allowed, registered, False, False, "DEVICE_ID_MISSING", "current device id is unavailable")
    if not registered:
        return _state("legacy_unbound", current, allowed, registered, True, True, "", "activation does not declare device seats")
    if current in registered:
        return _state("bound_current_device", current, allowed, registered, True, len(registered) <= allowed, "", "")
    if len(registered) >= allowed:
        return _state(
            "seat_limit_exceeded",
            current,
            allowed,
            registered,
            False,
            False,
            "DEVICE_SEAT_LIMIT_EXCEEDED",
            "activation has no available device seat for this device",
        )
    return _state(
        "seat_available_unbound",
        current,
        allowed,
        registered,
        False,
        True,
        "DEVICE_SEAT_REQUIRES_ACTIVATION",
        "a seat is available but this device is not activated yet",
    )


def _allowed_seats(status: dict[str, Any]) -> int:
    seats = status.get("device_seats") if isinstance(status.get("device_seats"), dict) else {}
    for value in [
        seats.get("allowed"),
        seats.get("limit"),
        seats.get("max_devices"),
        status.get("seat_limit"),
        status.get("device_seat_limit"),
        status.get("max_devices"),
    ]:
        try:
            parsed = int(value)
        except Exception:
            continue
        if parsed > 0:
            return parsed
    return DEFAULT_DEVICE_SEATS


def _registered_device_ids(status: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    if status.get("device_id"):
        values.append(status.get("device_id"))
    for key in ["device_ids", "registered_device_ids", "activated_device_ids"]:
        if isinstance(status.get(key), list):
            values.extend(status.get(key) or [])
    seats = status.get("device_seats") if isinstance(status.get("device_seats"), dict) else {}
    if isinstance(seats.get("devices"), list):
        for row in seats.get("devices") or []:
            if isinstance(row, dict):
                values.append(row.get("device_id") or row.get("id"))
            else:
                values.append(row)
    result = []
    seen = set()
    for value in values:
        clean = _normalize_device_id(value)
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
    return result


def _normalize_device_id(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum() or ch in {"_", "-"})[:96]


def _state(
    status: str,
    current_device_id: str,
    allowed_seats: int,
    registered_device_ids: list[str],
    device_allowed: bool,
    seat_available: bool,
    reason_code: str,
    reason: str,
) -> DeviceSeatState:
    return DeviceSeatState(
        status=status,
        current_device_id=current_device_id,
        allowed_seats=allowed_seats,
        registered_device_ids=registered_device_ids,
        device_allowed=device_allowed,
        seat_available=seat_available,
        reason_code=reason_code,
        reason=reason,
    )
