# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .device_identity import DeviceIdentity


@dataclass
class AuthorizationDecision:
    allowed: bool
    error_code: str = ""
    error_message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


class LiveSubmitAuthorizationGate:
    """Local server-synced authorization status gate for live outreach actions.

    This class intentionally does not store activation codes, secrets, or signed
    payloads. It only reads the local status cache that an external activation
    service can refresh.
    """

    STATUS_FILENAME = "reachops_activation_status.json"

    def __init__(self, status_path: str, device_identity: type[DeviceIdentity] = DeviceIdentity):
        self.status_path = status_path
        self.device_identity = device_identity

    @classmethod
    def from_storage(cls, storage) -> "LiveSubmitAuthorizationGate":
        runtime_paths = getattr(storage, "runtime_paths", None)
        if runtime_paths and getattr(runtime_paths, "activation_status_path", ""):
            return cls(str(runtime_paths.activation_status_path))
        db_path = str(getattr(storage, "db_path", "") or "")
        status_dir = os.path.dirname(os.path.abspath(db_path)) if db_path else os.getcwd()
        return cls(os.path.join(status_dir, cls.STATUS_FILENAME))

    def authorize_live_submit(self, action: dict, profile: dict, feature: str = "live_submit") -> AuthorizationDecision:
        status = self._read_status()
        action_type = str(action.get("action_type") or "")
        profile_id = str(profile.get("profile_id") or profile.get("id") or "")
        evidence = {
            "status_path": self.status_path,
            "feature": feature,
            "action_type": action_type,
            "profile_id": profile_id,
            "license_tier": str(status.get("license_tier") or ""),
            "current_device_id": self.device_identity.current_device_id(),
        }
        if not status:
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", "activation status not found", evidence)
        if bool(status.get("template_only")):
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", "activation status is a template", evidence)
        if not bool(status.get("active")):
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", "activation is inactive", evidence)
        bound_device_id = str(status.get("device_id") or "").strip()
        if bound_device_id and bound_device_id != evidence["current_device_id"]:
            return AuthorizationDecision(
                False,
                "LIVE_SUBMIT_DEVICE_MISMATCH",
                "activation is bound to another device",
                {**evidence, "bound_device_id": bound_device_id},
            )
        expires_at = str(status.get("expires_at") or "").strip()
        if expires_at and self._is_expired(expires_at):
            return AuthorizationDecision(False, "LIVE_SUBMIT_LICENSE_EXPIRED", "activation has expired", {**evidence, "expires_at": expires_at})
        capabilities = status.get("capabilities") if isinstance(status.get("capabilities"), dict) else {}
        if not bool(capabilities.get(feature)):
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", f"feature not enabled: {feature}", evidence)
        if action_type and action_type in {"comment_reply", "follow_review", "dm_review"} and capabilities.get(action_type) is False:
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", f"action not enabled: {action_type}", evidence)
        return AuthorizationDecision(True, evidence={**evidence, "expires_at": expires_at})

    def _read_status(self) -> dict:
        try:
            with open(self.status_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _is_expired(self, expires_at: str) -> bool:
        value = expires_at.replace("Z", "+00:00")
        try:
            expires = datetime.fromisoformat(value)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires <= datetime.now(timezone.utc)
        except Exception:
            return True
