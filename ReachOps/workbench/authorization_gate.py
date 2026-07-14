# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ReachOps.security_signing import load_key_ring, verify_signed_payload

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

    def __init__(
        self,
        status_path: str,
        device_identity: type[DeviceIdentity] = DeviceIdentity,
        entitlement_key_ring: dict[str, str] | None = None,
    ):
        self.status_path = status_path
        self.device_identity = device_identity
        self.entitlement_key_ring = entitlement_key_ring

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
            "runtime_mode": self.runtime_mode(),
            "activation_required": self.activation_required(),
        }
        if not self.activation_required() and not status:
            return AuthorizationDecision(True, evidence={**evidence, "development_bypass": True})
        if not status:
            return AuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", "activation status not found", evidence)
        if self.is_packaged_runtime():
            signature_ok, signature_reason = verify_signed_payload(
                status,
                key_ring=self.entitlement_key_ring if self.entitlement_key_ring is not None else load_key_ring(),
                signature_field="entitlement_signature",
            )
            if not signature_ok:
                return AuthorizationDecision(
                    False,
                    "LIVE_SUBMIT_ENTITLEMENT_SIGNATURE_INVALID",
                    "packaged runtime requires a valid signed entitlement",
                    {**evidence, "signature_reason": signature_reason},
                )
            commercial_check = self._validate_packaged_entitlement(status, evidence["current_device_id"], feature, action_type)
            if commercial_check:
                return commercial_check
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

    def _validate_packaged_entitlement(
        self,
        status: dict[str, Any],
        current_device_id: str,
        feature: str,
        action_type: str,
    ) -> AuthorizationDecision | None:
        def blocked(code: str, message: str, **extra_evidence) -> AuthorizationDecision:
            return AuthorizationDecision(
                False,
                code,
                message,
                {
                    "status_path": self.status_path,
                    "runtime_mode": self.runtime_mode(),
                    "current_device_id": current_device_id,
                    **extra_evidence,
                },
            )

        if not str(status.get("entitlement_id") or "").strip():
            return blocked("LIVE_SUBMIT_ENTITLEMENT_INCOMPLETE", "signed entitlement is missing entitlement_id")
        if not str(status.get("issued_at") or "").strip():
            return blocked("LIVE_SUBMIT_ENTITLEMENT_INCOMPLETE", "signed entitlement is missing issued_at")
        if not str(status.get("expires_at") or "").strip():
            return blocked("LIVE_SUBMIT_LICENSE_EXPIRED", "signed entitlement is missing expires_at")
        if not str(status.get("device_id") or "").strip():
            return blocked("LIVE_SUBMIT_DEVICE_MISMATCH", "signed entitlement must be bound to this device")
        if bool(status.get("revoked")) or str(status.get("revoked_at") or "").strip():
            return blocked("LIVE_SUBMIT_ENTITLEMENT_REVOKED", "signed entitlement has been revoked")

        audit = status.get("audit") if isinstance(status.get("audit"), dict) else {}
        if not str(audit.get("issued_by") or "").strip() or not str(audit.get("event_id") or "").strip():
            return blocked("LIVE_SUBMIT_ENTITLEMENT_INCOMPLETE", "signed entitlement is missing audit history")
        if bool(audit.get("replay_detected")) or str(audit.get("nonce_status") or "").strip().lower() == "replayed":
            return blocked(
                "LIVE_SUBMIT_ENTITLEMENT_REPLAYED",
                "signed entitlement audit history marks this payload as replayed",
                audit_event_id=str(audit.get("event_id") or ""),
                nonce_status=str(audit.get("nonce_status") or ""),
            )

        registration = status.get("device_registration") if isinstance(status.get("device_registration"), dict) else {}
        registered_device_id = str(registration.get("device_id") or status.get("device_id") or "").strip()
        if registered_device_id != current_device_id:
            return blocked(
                "LIVE_SUBMIT_DEVICE_MISMATCH",
                "signed entitlement device registration does not match this device",
                bound_device_id=registered_device_id,
            )
        try:
            max_devices = int(registration.get("max_concurrent_devices") or 1)
            registered_count = int(registration.get("registered_device_count") or 1)
        except Exception:
            return blocked(
                "LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED",
                "signed entitlement has invalid concurrent device limits",
                max_concurrent_devices=registration.get("max_concurrent_devices"),
                registered_device_count=registration.get("registered_device_count"),
            )
        if max_devices < 1 or registered_count > max_devices:
            return blocked(
                "LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED",
                "signed entitlement exceeds the concurrent device limit",
                max_concurrent_devices=max_devices,
                registered_device_count=registered_count,
            )

        grace_until = str(status.get("offline_grace_until") or "").strip()
        if not grace_until:
            return blocked("LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED", "signed entitlement is missing offline grace deadline")
        if self._is_expired(grace_until):
            return blocked("LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED", "signed entitlement offline grace has expired", offline_grace_until=grace_until)

        disabled = {str(item) for item in status.get("emergency_disabled_features", []) if str(item).strip()}
        if feature in disabled or action_type in disabled:
            return blocked(
                "LIVE_SUBMIT_FEATURE_DISABLED",
                "signed entitlement disables this feature remotely",
                feature=feature,
                action_type=action_type,
                emergency_disabled_features=sorted(disabled),
            )
        return None

    def _read_status(self) -> dict:
        try:
            with open(self.status_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @classmethod
    def is_packaged_runtime(cls) -> bool:
        return bool(getattr(sys, "frozen", False))

    @classmethod
    def activation_required(cls) -> bool:
        """Return whether activation must be enforced for this runtime.

        Packaged builds are always commercial runtimes and must never allow an
        environment variable to disable activation. Environment overrides remain
        available only for source-based development and test runs.
        """

        if cls.is_packaged_runtime():
            return True
        explicit = str(os.environ.get("REACHOPS_REQUIRE_ACTIVATION") or "").strip().lower()
        if explicit in {"1", "true", "yes", "on"}:
            return True
        if explicit in {"0", "false", "no", "off"}:
            return False
        return True

    @classmethod
    def runtime_mode(cls) -> str:
        return "packaged" if cls.is_packaged_runtime() else "development"

    def _is_expired(self, expires_at: str) -> bool:
        value = expires_at.replace("Z", "+00:00")
        try:
            expires = datetime.fromisoformat(value)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires <= datetime.now(timezone.utc)
        except Exception:
            return True
