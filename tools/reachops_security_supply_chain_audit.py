# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.security_signing import sign_payload, verify_signed_payload
from ReachOps.updater import ReachOpsUpdateManager
from ReachOps.version import BUILD_CHANNEL, PRODUCT_ID
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from tools.write_reachops_update_manifest import build_manifest


SCHEMA_VERSION = "reachops.security_supply_chain_audit.v1"
REVOCATION_SLA_HOURS = 24


class AuditDeviceIdentity:
    @classmethod
    def current_device_id(cls) -> str:
        return "audit-device"


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def active_entitlement(**overrides) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entitlement_id": "ent-audit",
        "issued_at": "2026-07-14T00:00:00Z",
        "active": True,
        "device_id": "audit-device",
        "device_registration": {
            "device_id": "audit-device",
            "max_concurrent_devices": 2,
            "registered_device_count": 1,
        },
        "expires_at": "2999-01-01T00:00:00Z",
        "offline_grace_until": "2999-01-08T00:00:00Z",
        "license_tier": "enterprise",
        "audit": {
            "issued_by": "reachops-license-service",
            "event_id": "evt-audit-1",
            "revocation_sla_hours": REVOCATION_SLA_HOURS,
            "nonce_status": "fresh",
        },
        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
    }
    payload.update(overrides)
    return payload


def _decision_dict(payload: dict[str, Any], *, key_ring: dict[str, str], action_type: str = "comment_reply") -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp, patch.object(
        LiveSubmitAuthorizationGate,
        "is_packaged_runtime",
        return_value=True,
    ), patch.dict(os.environ, {"REACHOPS_REQUIRE_ACTIVATION": "0"}, clear=False):
        status_path = Path(tmp) / "reachops_activation_status.json"
        status_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        gate = LiveSubmitAuthorizationGate(
            str(status_path),
            device_identity=AuditDeviceIdentity,
            entitlement_key_ring=key_ring,
        )
        decision = gate.authorize_live_submit({"action_type": action_type}, {"profile_id": "profile-audit"})
    return {
        "allowed": decision.allowed,
        "error_code": decision.error_code,
        "error_message": decision.error_message,
        "signature_reason": (decision.evidence or {}).get("signature_reason", ""),
    }


def run_entitlement_matrix() -> dict[str, Any]:
    key_ring = {"ent-v1": "old-secret", "ent-v2": "new-secret"}
    active_signed = sign_payload(active_entitlement(), "ent-v2", "new-secret", signature_field="entitlement_signature")
    old_signed = sign_payload(active_entitlement(entitlement_id="ent-old"), "ent-v1", "old-secret", signature_field="entitlement_signature")
    replayed_signed = sign_payload(
        active_entitlement(audit={"issued_by": "reachops-license-service", "event_id": "evt-audit-1", "nonce_status": "replayed"}),
        "ent-v2",
        "new-secret",
        signature_field="entitlement_signature",
    )
    rows = {
        "valid_signed": _decision_dict(active_signed, key_ring=key_ring),
        "unsigned": _decision_dict(active_entitlement(), key_ring=key_ring),
        "rotated_new_key": _decision_dict(active_signed, key_ring={"ent-v2": "new-secret"}),
        "retired_old_key": _decision_dict(old_signed, key_ring={"ent-v2": "new-secret"}),
        "wrong_device": _decision_dict(
            sign_payload(active_entitlement(device_id="other-device", device_registration={"device_id": "other-device", "max_concurrent_devices": 2, "registered_device_count": 1}), "ent-v2", "new-secret", signature_field="entitlement_signature"),
            key_ring=key_ring,
        ),
        "revoked": _decision_dict(
            sign_payload(active_entitlement(revoked=True, revoked_at="2026-07-14T01:00:00Z"), "ent-v2", "new-secret", signature_field="entitlement_signature"),
            key_ring=key_ring,
        ),
        "expired_offline_grace": _decision_dict(
            sign_payload(active_entitlement(offline_grace_until="2000-01-01T00:00:00Z"), "ent-v2", "new-secret", signature_field="entitlement_signature"),
            key_ring=key_ring,
        ),
        "device_limit_exceeded": _decision_dict(
            sign_payload(active_entitlement(device_registration={"device_id": "audit-device", "max_concurrent_devices": 1, "registered_device_count": 2}), "ent-v2", "new-secret", signature_field="entitlement_signature"),
            key_ring=key_ring,
        ),
        "emergency_disabled_action": _decision_dict(
            sign_payload(active_entitlement(emergency_disabled_features=["comment_reply"]), "ent-v2", "new-secret", signature_field="entitlement_signature"),
            key_ring=key_ring,
        ),
        "replay_detected": _decision_dict(replayed_signed, key_ring=key_ring),
    }
    passed = bool(
        rows["valid_signed"]["allowed"]
        and rows["rotated_new_key"]["allowed"]
        and not rows["unsigned"]["allowed"]
        and rows["unsigned"]["error_code"] == "LIVE_SUBMIT_ENTITLEMENT_SIGNATURE_INVALID"
        and not rows["retired_old_key"]["allowed"]
        and rows["retired_old_key"]["signature_reason"] == "signature_key_unknown"
        and rows["wrong_device"]["error_code"] == "LIVE_SUBMIT_DEVICE_MISMATCH"
        and rows["revoked"]["error_code"] == "LIVE_SUBMIT_ENTITLEMENT_REVOKED"
        and rows["expired_offline_grace"]["error_code"] == "LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED"
        and rows["device_limit_exceeded"]["error_code"] == "LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED"
        and rows["emergency_disabled_action"]["error_code"] == "LIVE_SUBMIT_FEATURE_DISABLED"
        and rows["replay_detected"]["error_code"] == "LIVE_SUBMIT_ENTITLEMENT_REPLAYED"
    )
    return {
        "schema_version": "reachops.entitlement_security_matrix.v1",
        "passed": passed,
        "status": "passed" if passed else "failed",
        "revocation_sla_hours": REVOCATION_SLA_HOURS,
        "key_rotation": {"current_key": "ent-v2", "retired_key_rejected": not rows["retired_old_key"]["allowed"]},
        "cases": rows,
    }


def run_update_manifest_matrix() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        installer = base / "ReachOps-Setup-audit.exe"
        installer.write_bytes(b"reachops installer audit")
        manifest = build_manifest(
            installer,
            version="9.9.9",
            build="audit",
            channel=BUILD_CHANNEL,
            download_url="https://updates.example.com/ReachOps-Setup-audit.exe",
            signing_key_id="manifest-v2",
            signing_key="manifest-secret",
        )
        manager = ReachOpsUpdateManager(current_version="0.4.0", manifest_key_ring={"manifest-v2": "manifest-secret"})
        signature_ok, signature_reason = verify_signed_payload(manifest, {"manifest-v2": "manifest-secret"}, signature_field="manifest_signature")
        manager.validate_manifest(manifest, require_signature=True)
        installer_verified = manager.verify_installer(installer, manifest)
        tampered = {**manifest, "version": "9.9.10"}
        try:
            manager.validate_manifest(tampered, require_signature=True)
            tampered_rejected = False
            tampered_error = ""
        except Exception as exc:
            tampered_rejected = "signature invalid" in str(exc)
            tampered_error = str(exc)
        bad_installer = base / "ReachOps-Setup-audit-bad.exe"
        bad_installer.write_bytes(b"tampered")
        bad_installer_rejected = not manager.verify_installer(bad_installer, manifest)
        try:
            manager.load_manifest("http://updates.example.com/reachops-update-manifest.json")
            http_rejected = False
            http_error = ""
        except Exception as exc:
            http_rejected = "must use https" in str(exc)
            http_error = str(exc)
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(manifest)):
            https_loaded = manager.load_manifest("https://updates.example.com/reachops-update-manifest.json")
        downgrade_blocked = not ReachOpsUpdateManager(current_version="9.9.10").check_manifest(manifest).available
        rollback_manifest = {
            **manifest,
            "version": "9.9.8",
            "rollback_policy": {"allow_downgrade": True, "minimum_version": "0.4.0"},
        }
        rollback_manifest = sign_payload(rollback_manifest, "manifest-v2", "manifest-secret", signature_field="manifest_signature")
        rollback_available = ReachOpsUpdateManager(current_version="9.9.10", manifest_key_ring={"manifest-v2": "manifest-secret"}).check_manifest(rollback_manifest).reason == "rollback_available"
    passed = bool(
        signature_ok
        and signature_reason == "signature_valid"
        and installer_verified
        and tampered_rejected
        and bad_installer_rejected
        and http_rejected
        and https_loaded == manifest
        and downgrade_blocked
        and rollback_available
    )
    return {
        "schema_version": "reachops.update_supply_chain_matrix.v1",
        "passed": passed,
        "status": "passed" if passed else "failed",
        "signature_valid": signature_ok,
        "signature_reason": signature_reason,
        "installer_verified": installer_verified,
        "tampered_manifest_rejected": tampered_rejected,
        "tampered_manifest_error": tampered_error,
        "bad_installer_hash_or_size_rejected": bad_installer_rejected,
        "http_manifest_rejected": http_rejected,
        "http_manifest_error": http_error,
        "https_signed_manifest_loaded": https_loaded == manifest,
        "downgrade_without_rollback_blocked": downgrade_blocked,
        "explicit_rollback_available": rollback_available,
        "verified_fields": ["product_id", "platform", "channel", "version", "installer.sha256", "installer.size_bytes", "manifest_signature", "rollback_policy"],
    }


def build_report() -> dict[str, Any]:
    entitlement = run_entitlement_matrix()
    update = run_update_manifest_matrix()
    failures: list[str] = []
    if not entitlement.get("passed"):
        failures.append("entitlement_security_matrix_failed")
    if not update.get("passed"):
        failures.append("update_supply_chain_matrix_failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "product_id": PRODUCT_ID,
        "entitlement": entitlement,
        "update_supply_chain": update,
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ReachOps packaged entitlement and update supply-chain security.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps security supply-chain audit: {payload['status']}")
        if payload["failures"]:
            print("Failures: " + ", ".join(payload["failures"]))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
