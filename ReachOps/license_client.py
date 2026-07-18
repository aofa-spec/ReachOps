# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.device_identity import DeviceIdentity


LICENSE_KEY_ENV = "REACHOPS_LICENSE_KEY"
LICENSE_ENDPOINT_ENV = "REACHOPS_LICENSE_ENDPOINT"
DEFAULT_TIMEOUT_SECONDS = 15

ALLOWED_REQUEST_FIELDS = {
    "license_key",
    "device_id",
    "app_version",
    "platform",
    "runtime_mode",
    "requested_capabilities",
}


@dataclass(frozen=True)
class LicenseRefreshResult:
    status: str
    refreshed: bool
    activation_status_path: str
    endpoint_configured: bool
    request_payload: dict[str, Any] = field(default_factory=dict)
    activation_status: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "refreshed": self.refreshed,
            "activation_status_path": self.activation_status_path,
            "endpoint_configured": self.endpoint_configured,
            "request_payload": _redact_request_payload(self.request_payload),
            "activation_status": dict(self.activation_status),
            "error": self.error,
            "no_browser_started": True,
            "no_submit": True,
            "customer_data_uploaded": False,
        }


class ReachOpsLicenseClient:
    """Minimal license refresh client.

    The client only sends license/device/version metadata to the configured
    license endpoint. Customer runtime data, TikTok state, usernames, comments,
    screenshots, cookies, SQLite files, and evidence paths are never part of
    the request contract.
    """

    def __init__(
        self,
        *,
        endpoint: str = "",
        license_key: str = "",
        runtime_paths: RuntimePaths | None = None,
        device_id: str = "",
        app_version: str = "",
        opener: Callable[..., Any] | None = None,
    ):
        self.endpoint = str(endpoint or os.environ.get(LICENSE_ENDPOINT_ENV) or "").strip()
        self.license_key = str(license_key or os.environ.get(LICENSE_KEY_ENV) or "").strip()
        self.runtime_paths = runtime_paths or RuntimePaths.build()
        self.device_id = str(device_id or DeviceIdentity.current_device_id()).strip()
        self.app_version = str(app_version or os.environ.get("REACHOPS_APP_VERSION") or "").strip()
        self.opener = opener or urllib.request.urlopen

    def build_request_payload(self, requested_capabilities: list[str] | None = None) -> dict[str, Any]:
        capabilities = []
        for value in requested_capabilities or ["live_submit", "comment_reply", "follow_review", "dm_review"]:
            clean = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in {"_", "-"})
            if clean and clean not in capabilities:
                capabilities.append(clean)
        payload = {
            "license_key": self.license_key,
            "device_id": self.device_id,
            "app_version": self.app_version,
            "platform": "windows_local_client",
            "runtime_mode": "packaged" if getattr(sys, "frozen", False) else "development",
            "requested_capabilities": capabilities,
        }
        return {key: payload[key] for key in ALLOWED_REQUEST_FIELDS}

    def refresh(self, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> LicenseRefreshResult:
        status_path = str(self.runtime_paths.activation_status_path)
        if not self.endpoint:
            return LicenseRefreshResult("endpoint_missing", False, status_path, False, error="license endpoint is not configured")
        if not self.license_key:
            return LicenseRefreshResult("license_key_missing", False, status_path, True, error="license key is not configured")
        payload = self.build_request_payload()
        response = self._post_json(payload, timeout_seconds=max(1, int(timeout_seconds)))
        activation_status = self._extract_activation_status(response)
        if not activation_status:
            return LicenseRefreshResult("invalid_response", False, status_path, True, request_payload=payload, error="license response missing activation_status")
        activation_status = self._normalize_activation_status(activation_status)
        self._write_activation_status(activation_status)
        return LicenseRefreshResult("refreshed", True, status_path, True, request_payload=payload, activation_status=activation_status)

    def _post_json(self, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"license refresh failed: {exc}") from exc
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("license refresh response must be a JSON object")
        return parsed

    @staticmethod
    def _extract_activation_status(response: dict[str, Any]) -> dict[str, Any]:
        value = response.get("activation_status", response)
        return value if isinstance(value, dict) else {}

    def _normalize_activation_status(self, activation_status: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now_iso()
        result = dict(activation_status)
        result["last_verified_at"] = str(result.get("last_verified_at") or result.get("verified_at") or now)
        result["current_device_id"] = self.device_id
        result["license_client"] = "reachops_local_v1"
        result["customer_data_uploaded"] = False
        return result

    def _write_activation_status(self, activation_status: dict[str, Any]) -> None:
        path = Path(self.runtime_paths.activation_status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(activation_status, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _redact_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload or {})
    if result.get("license_key"):
        result["license_key"] = "***redacted***"
    return result
