# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ReachOps.runtime_paths import RuntimePaths

from .device_identity import DeviceIdentity
from .license_state import LICENSE_STATE_SCHEMA_VERSION, evaluate_license_state


LICENSE_REFRESH_SCHEMA_VERSION = "reachops.license_refresh.v1"
DEFAULT_TIMEOUT_SECONDS = 15
ALLOWED_REQUEST_KEYS = {
    "schema_version",
    "license_id",
    "device_id",
    "app_version",
    "platform",
    "requested_at",
}
FORBIDDEN_REFRESH_TOKENS = (
    "comment",
    "cookie",
    "database",
    "db_path",
    "dom",
    "evidence",
    "password",
    "profile_url",
    "screenshot",
    "secret",
    "session",
    "sqlite",
    "target_url",
    "tiktok",
    "token",
    "username",
)


class LicenseRefreshError(RuntimeError):
    pass


class LicenseRefreshRejected(LicenseRefreshError):
    pass


@dataclass(frozen=True)
class LicenseRefreshResponse:
    status_code: int
    payload: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def build_license_refresh_request(
    *,
    license_id: str,
    app_version: str,
    device_id: str | None = None,
    platform: str = "windows-local-client",
    requested_at: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": LICENSE_REFRESH_SCHEMA_VERSION,
        "license_id": str(license_id or "").strip(),
        "device_id": str(device_id or DeviceIdentity.current_device_id()).strip(),
        "app_version": str(app_version or "").strip(),
        "platform": str(platform or "windows-local-client").strip(),
        "requested_at": str(requested_at or _utc_now()),
    }
    validate_license_refresh_request(payload)
    return payload


def validate_license_refresh_request(payload: dict[str, Any]) -> None:
    keys = set(payload)
    extra = keys - ALLOWED_REQUEST_KEYS
    if extra:
        raise LicenseRefreshRejected(f"license refresh request contains forbidden fields: {sorted(extra)}")
    lowered = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    for token in FORBIDDEN_REFRESH_TOKENS:
        if f'"{token}"' in lowered or f"_{token}" in lowered or f"{token}_" in lowered:
            raise LicenseRefreshRejected(f"license refresh request contains forbidden customer-data token: {token}")
    if not str(payload.get("license_id") or "").strip():
        raise LicenseRefreshRejected("license_id is required")
    if not str(payload.get("device_id") or "").strip():
        raise LicenseRefreshRejected("device_id is required")
    if not str(payload.get("app_version") or "").strip():
        raise LicenseRefreshRejected("app_version is required")


def default_license_refresh_transport(endpoint: str, payload: dict[str, Any], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> LicenseRefreshResponse:
    url = str(endpoint or "").strip()
    if not url.startswith("https://"):
        raise LicenseRefreshRejected("license refresh endpoint must use https")
    validate_license_refresh_request(payload)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)) as response:
            body = response.read().decode("utf-8")
            status_code = int(getattr(response, "status", 0) or 0)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status_code = int(exc.code or 0)
    except Exception as exc:
        raise LicenseRefreshError(f"license refresh request failed: {exc}") from exc
    try:
        response_payload = json.loads(body or "{}")
    except Exception as exc:
        raise LicenseRefreshError("license refresh response is not valid JSON") from exc
    if not isinstance(response_payload, dict):
        raise LicenseRefreshError("license refresh response must be a JSON object")
    return LicenseRefreshResponse(status_code=status_code, payload=response_payload)


def normalize_license_refresh_response(response_payload: dict[str, Any], request_payload: dict[str, Any]) -> dict[str, Any]:
    status = response_payload if isinstance(response_payload, dict) else {}
    activation = status.get("activation_status") if isinstance(status.get("activation_status"), dict) else status
    capabilities = activation.get("capabilities") if isinstance(activation.get("capabilities"), dict) else {}
    normalized = {
        "schema_version": LICENSE_STATE_SCHEMA_VERSION,
        "refresh_schema_version": LICENSE_REFRESH_SCHEMA_VERSION,
        "template_only": False,
        "active": bool(activation.get("active")),
        "revoked": bool(activation.get("revoked")),
        "subscription_status": str(activation.get("subscription_status") or activation.get("subscription_state") or "").strip().lower(),
        "device_id": str(activation.get("device_id") or request_payload.get("device_id") or "").strip(),
        "license_id": str(activation.get("license_id") or request_payload.get("license_id") or "").strip(),
        "license_tier": str(activation.get("license_tier") or "").strip(),
        "expires_at": str(activation.get("expires_at") or "").strip(),
        "last_verified_at": str(activation.get("last_verified_at") or activation.get("license_verified_at") or _utc_now()).strip(),
        "capabilities": {
            "live_submit": bool(capabilities.get("live_submit")),
            "comment_reply": bool(capabilities.get("comment_reply")),
            "follow_review": bool(capabilities.get("follow_review")),
            "dm_review": bool(capabilities.get("dm_review")),
        },
        "update_metadata": activation.get("update_metadata") if isinstance(activation.get("update_metadata"), dict) else {},
        "customer_data_uploaded": False,
        "no_browser_started": True,
        "no_submit": True,
        "refreshed_by": "reachops_license_refresh_client",
    }
    normalized["license_state"] = evaluate_license_state(normalized)
    return normalized


def refresh_license_status(
    *,
    endpoint: str,
    license_id: str,
    app_version: str,
    base_dir: str | None = None,
    status_path: str | Path | None = None,
    device_id: str | None = None,
    transport: Callable[[str, dict[str, Any], int], LicenseRefreshResponse] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    write_status: bool = True,
) -> dict[str, Any]:
    paths = RuntimePaths.build(base_dir).ensure_dirs()
    target_path = Path(status_path).expanduser() if status_path else Path(paths.activation_status_path)
    request_payload = build_license_refresh_request(
        license_id=license_id,
        app_version=app_version,
        device_id=device_id,
    )
    send = transport or default_license_refresh_transport
    response = send(str(endpoint or "").strip(), request_payload, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))
    if int(response.status_code or 0) != 200:
        raise LicenseRefreshError(f"license refresh server returned HTTP {response.status_code}")
    activation_status = normalize_license_refresh_response(response.payload, request_payload)
    result = {
        "schema_version": LICENSE_REFRESH_SCHEMA_VERSION,
        "status": "refreshed",
        "activation_status_path": str(target_path),
        "request": request_payload,
        "activation_status": activation_status,
        "write_status": bool(write_status),
        "customer_data_uploaded": False,
        "no_browser_started": True,
        "no_submit": True,
    }
    if write_status:
        _atomic_write_json(target_path, activation_status)
    return result
