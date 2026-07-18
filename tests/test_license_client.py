import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ReachOps.license_client import ReachOpsLicenseClient
from ReachOps.runtime_paths import RuntimePaths


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LicenseClientTests(unittest.TestCase):
    def test_preview_payload_uses_allowlisted_license_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ReachOpsLicenseClient(
                endpoint="https://license.example.test/activate",
                license_key="secret-license",
                runtime_paths=RuntimePaths.build(base_dir=tmp),
                device_id="device-a",
                app_version="0.4.0",
            )

            payload = client.build_request_payload()

            self.assertEqual(
                set(payload),
                {"license_key", "device_id", "app_version", "platform", "runtime_mode", "requested_capabilities"},
            )
            forbidden_words = ["comment", "username", "screenshot", "cookie", "database", "tiktok_status"]
            encoded = json.dumps(payload, sort_keys=True)
            self.assertTrue("comment_reply" in payload["requested_capabilities"])
            for word in forbidden_words:
                if word == "comment":
                    self.assertNotIn('"comment":', encoded)
                else:
                    self.assertNotIn(word, encoded)

    def test_refresh_writes_activation_status_atomically(self):
        requests = []

        def opener(request, *, timeout):
            requests.append(
                {
                    "url": request.full_url,
                    "timeout": timeout,
                    "payload": json.loads(request.data.decode("utf-8")),
                }
            )
            return FakeResponse(
                {
                    "activation_status": {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    }
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.build(base_dir=tmp)
            client = ReachOpsLicenseClient(
                endpoint="https://license.example.test/activate",
                license_key="secret-license",
                runtime_paths=paths,
                device_id="device-a",
                app_version="0.4.0",
                opener=opener,
            )

            result = client.refresh(timeout_seconds=7)
            written = json.loads(Path(paths.activation_status_path).read_text(encoding="utf-8"))

            self.assertTrue(result.refreshed)
            self.assertEqual(result.status, "refreshed")
            self.assertEqual(result.as_dict()["request_payload"]["license_key"], "***redacted***")
            self.assertEqual(requests[0]["timeout"], 7)
            self.assertEqual(requests[0]["payload"]["device_id"], "device-a")
            self.assertEqual(written["active"], True)
            self.assertEqual(written["current_device_id"], "device-a")
            self.assertEqual(written["license_client"], "reachops_local_v1")
            self.assertFalse(written["customer_data_uploaded"])
            self.assertTrue(written["last_verified_at"])

    def test_missing_endpoint_does_not_write_activation_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.build(base_dir=tmp)
            client = ReachOpsLicenseClient(
                endpoint="",
                license_key="secret-license",
                runtime_paths=paths,
                device_id="device-a",
            )

            result = client.refresh()

            self.assertFalse(result.refreshed)
            self.assertEqual(result.status, "endpoint_missing")
            self.assertFalse(Path(paths.activation_status_path).exists())

    def test_cli_preview_redacts_license_key_and_avoids_file_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "tools/reachops_license_refresh.py",
                    "--endpoint",
                    "https://license.example.test/activate",
                    "--license-key",
                    "secret-license",
                    "--runtime-dir",
                    tmp,
                    "--device-id",
                    "device-a",
                    "--preview",
                    "--json",
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                text=True,
                capture_output=True,
                check=False,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(payload["status"], "preview")
            self.assertEqual(payload["request_payload"]["license_key"], "***redacted***")
            self.assertFalse(payload["customer_data_uploaded"])
            self.assertFalse(Path(RuntimePaths.build(base_dir=tmp).activation_status_path).exists())


if __name__ == "__main__":
    unittest.main()
