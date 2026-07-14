import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ReachOps.security_signing import sign_payload, verify_signed_payload
from ReachOps.updater import ReachOpsUpdateManager
from ReachOps.version import PRODUCT_ID
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate


class StubDeviceIdentity:
    @classmethod
    def current_device_id(cls) -> str:
        return "device-1"


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def active_entitlement(**overrides) -> dict:
    payload = {
        "entitlement_id": "ent-1",
        "issued_at": "2026-01-01T00:00:00Z",
        "active": True,
        "device_id": "device-1",
        "device_registration": {
            "device_id": "device-1",
            "max_concurrent_devices": 2,
            "registered_device_count": 1,
        },
        "expires_at": "2999-01-01T00:00:00Z",
        "offline_grace_until": "2999-01-08T00:00:00Z",
        "license_tier": "enterprise",
        "audit": {"issued_by": "reachops-license-service", "event_id": "evt-1"},
        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
    }
    payload.update(overrides)
    return payload


def update_manifest(**overrides) -> dict:
    manifest = {
        "product_id": PRODUCT_ID,
        "channel": "mvp",
        "platform": "windows",
        "version": "0.4.1",
        "installer": {
            "file_name": "ReachOps-Setup-0.4.1.exe",
            "sha256": "0" * 64,
            "size_bytes": 1,
        },
        "rollback_policy": {
            "allow_downgrade": False,
            "minimum_version": "0.0.0",
        },
    }
    manifest.update(overrides)
    return manifest


class CommercialSecurityContractTest(unittest.TestCase):
    def test_security_signature_detects_tampering(self):
        payload = {"product_id": PRODUCT_ID, "version": "0.4.1", "installer": {"sha256": "0" * 64}}
        signed = sign_payload(payload, "k1", "secret", signature_field="manifest_signature")

        self.assertTrue(verify_signed_payload(signed, {"k1": "secret"}, signature_field="manifest_signature")[0])

        tampered = {**signed, "version": "0.4.2"}
        ok, reason = verify_signed_payload(tampered, {"k1": "secret"}, signature_field="manifest_signature")
        self.assertFalse(ok)
        self.assertEqual(reason, "signature_mismatch")

    def test_packaged_activation_cannot_be_disabled_by_environment(self):
        with patch.object(LiveSubmitAuthorizationGate, "is_packaged_runtime", return_value=True), patch.dict(
            os.environ,
            {"REACHOPS_REQUIRE_ACTIVATION": "0"},
            clear=False,
        ):
            self.assertTrue(LiveSubmitAuthorizationGate.activation_required())

    def test_source_runtime_can_explicitly_disable_activation_for_development(self):
        with patch.object(LiveSubmitAuthorizationGate, "is_packaged_runtime", return_value=False), patch.dict(
            os.environ,
            {"REACHOPS_REQUIRE_ACTIVATION": "0"},
            clear=False,
        ):
            self.assertFalse(LiveSubmitAuthorizationGate.activation_required())

    def test_packaged_runtime_without_status_blocks_live_submit(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ), patch.dict(os.environ, {"REACHOPS_REQUIRE_ACTIVATION": "0"}, clear=False):
            gate = LiveSubmitAuthorizationGate(
                str(Path(td) / "missing_activation_status.json"),
                device_identity=StubDeviceIdentity,
            )
            decision = gate.authorize_live_submit(
                {"action_type": "comment_reply"},
                {"profile_id": "profile-1"},
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_NOT_AUTHORIZED")
        self.assertTrue(decision.evidence["activation_required"])
        self.assertEqual(decision.evidence["runtime_mode"], "packaged")
        self.assertNotIn("development_bypass", decision.evidence)

    def test_packaged_runtime_rejects_unsigned_entitlement_payload(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            status_path.write_text(json.dumps(active_entitlement()), encoding="utf-8")
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_ENTITLEMENT_SIGNATURE_INVALID")
        self.assertEqual(decision.evidence["signature_reason"], "signature_missing")

    def test_packaged_runtime_accepts_signed_entitlement_payload(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            payload = active_entitlement()
            status_path.write_text(
                json.dumps(sign_payload(payload, "k1", "secret", signature_field="entitlement_signature")),
                encoding="utf-8",
            )
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertTrue(decision.allowed)

    def test_packaged_runtime_rejects_revoked_entitlement_payload(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            signed = sign_payload(active_entitlement(revoked=True, revoked_at="2026-01-02T00:00:00Z"), "k1", "secret", signature_field="entitlement_signature")
            status_path.write_text(json.dumps(signed), encoding="utf-8")
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_ENTITLEMENT_REVOKED")

    def test_packaged_runtime_rejects_expired_offline_grace(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            signed = sign_payload(active_entitlement(offline_grace_until="2000-01-01T00:00:00Z"), "k1", "secret", signature_field="entitlement_signature")
            status_path.write_text(json.dumps(signed), encoding="utf-8")
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED")

    def test_packaged_runtime_rejects_concurrent_device_limit_exceeded(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            signed = sign_payload(
                active_entitlement(
                    device_registration={
                        "device_id": "device-1",
                        "max_concurrent_devices": 1,
                        "registered_device_count": 2,
                    }
                ),
                "k1",
                "secret",
                signature_field="entitlement_signature",
            )
            status_path.write_text(json.dumps(signed), encoding="utf-8")
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED")

    def test_packaged_runtime_rejects_emergency_disabled_action(self):
        with TemporaryDirectory() as td, patch.object(
            LiveSubmitAuthorizationGate,
            "is_packaged_runtime",
            return_value=True,
        ):
            status_path = Path(td) / "reachops_activation_status.json"
            signed = sign_payload(
                active_entitlement(emergency_disabled_features=["comment_reply"]),
                "k1",
                "secret",
                signature_field="entitlement_signature",
            )
            status_path.write_text(json.dumps(signed), encoding="utf-8")
            gate = LiveSubmitAuthorizationGate(
                str(status_path),
                device_identity=StubDeviceIdentity,
                entitlement_key_ring={"k1": "secret"},
            )
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "profile-1"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_FEATURE_DISABLED")

    def test_remote_http_update_manifest_is_rejected_before_network_access(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0")

        with patch("urllib.request.urlopen") as urlopen, self.assertRaisesRegex(
            ValueError,
            "must use https",
        ):
            manager.load_manifest("http://updates.example.com/reachops-update-manifest.json")

        urlopen.assert_not_called()

    def test_remote_https_update_manifest_requires_signature(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0", manifest_key_ring={"k1": "secret"})
        manifest = update_manifest()

        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(manifest)), self.assertRaisesRegex(
            ValueError,
            "manifest signature invalid: signature_missing",
        ):
            manager.load_manifest("https://updates.example.com/reachops-update-manifest.json")

    def test_remote_https_update_manifest_accepts_valid_signature(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0", manifest_key_ring={"k1": "secret"})
        manifest = update_manifest()
        signed = sign_payload(manifest, "k1", "secret", signature_field="manifest_signature")

        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(signed)):
            loaded = manager.load_manifest("https://updates.example.com/reachops-update-manifest.json")

        self.assertEqual(loaded, signed)
        self.assertTrue(manager.check_manifest(loaded).available)

    def test_remote_https_update_manifest_rejects_tampered_signature(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0", manifest_key_ring={"k1": "secret"})
        signed = sign_payload(update_manifest(), "k1", "secret", signature_field="manifest_signature")
        tampered = {**signed, "version": "0.4.2"}

        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(tampered)), self.assertRaisesRegex(
            ValueError,
            "manifest signature invalid: signature_mismatch",
        ):
            manager.load_manifest("https://updates.example.com/reachops-update-manifest.json")

    def test_update_manifest_rejects_downgrade_without_rollback_policy(self):
        manager = ReachOpsUpdateManager(current_version="0.4.2")
        manifest = update_manifest(version="0.4.1")

        update = manager.check_manifest(manifest)

        self.assertFalse(update.available)
        self.assertEqual(update.reason, "current_version_is_newer")

    def test_update_manifest_accepts_explicit_rollback_policy(self):
        manager = ReachOpsUpdateManager(current_version="0.4.2")
        manifest = update_manifest(
            version="0.4.1",
            rollback_policy={"allow_downgrade": True, "minimum_version": "0.4.0"},
        )

        update = manager.check_manifest(manifest)

        self.assertTrue(update.available)
        self.assertEqual(update.reason, "rollback_available")

    def test_local_update_manifest_remains_supported(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0")
        manifest = update_manifest()

        with TemporaryDirectory() as td:
            path = Path(td) / "reachops-update-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = manager.load_manifest(path)

        self.assertEqual(loaded, manifest)
        self.assertTrue(manager.check_manifest(loaded).available)


if __name__ == "__main__":
    unittest.main()
