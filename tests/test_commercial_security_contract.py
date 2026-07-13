import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ReachOps.updater import ReachOpsUpdateManager
from ReachOps.version import PRODUCT_ID
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate


class StubDeviceIdentity:
    @classmethod
    def current_device_id(cls) -> str:
        return "device-1"


class CommercialSecurityContractTest(unittest.TestCase):
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

    def test_remote_http_update_manifest_is_rejected_before_network_access(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0")

        with patch("urllib.request.urlopen") as urlopen, self.assertRaisesRegex(
            ValueError,
            "must use https",
        ):
            manager.load_manifest("http://updates.example.com/reachops-update-manifest.json")

        urlopen.assert_not_called()

    def test_local_update_manifest_remains_supported(self):
        manager = ReachOpsUpdateManager(current_version="0.4.0")
        manifest = {
            "product_id": PRODUCT_ID,
            "platform": "windows",
            "version": "0.4.1",
            "installer": {
                "file_name": "ReachOps-Setup-0.4.1.exe",
                "sha256": "0" * 64,
                "size_bytes": 1,
            },
        }

        with TemporaryDirectory() as td:
            path = Path(td) / "reachops-update-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = manager.load_manifest(path)

        self.assertEqual(loaded, manifest)
        self.assertTrue(manager.check_manifest(loaded).available)


if __name__ == "__main__":
    unittest.main()
