import json
import unittest

from ReachOps.telemetry import build_telemetry_payload, build_telemetry_policy_status


class ReachOpsTelemetryPolicyTests(unittest.TestCase):
    def test_telemetry_is_off_by_default_and_uploads_no_payload(self):
        event = {
            "error_code": "CAPTCHA_DETECTED",
            "username": "@realbuyer",
            "comment_text": "Need this serum today",
            "target_url": "https://www.tiktok.com/@creator/video/123",
            "cookie": "tt_chain_token",
        }

        result = build_telemetry_payload(event)
        serialized = json.dumps(result)

        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["telemetry_enabled"])
        self.assertTrue(result["default_off"])
        self.assertTrue(result["requires_explicit_opt_in"])
        self.assertFalse(result["customer_data_uploaded"])
        self.assertEqual(result["payload"], {})
        self.assertNotIn("@realbuyer", serialized)
        self.assertNotIn("Need this serum today", serialized)
        self.assertNotIn("https://www.tiktok.com/@creator/video/123", serialized)
        self.assertNotIn("tt_chain_token", serialized)

    def test_opt_in_telemetry_keeps_only_anonymous_allowlisted_fields(self):
        event = {
            "reachops_version": "0.4.0",
            "windows_version": "Windows 11 23H2",
            "error_code": "LOGIN_REQUIRED",
            "failing_module": "collector",
            "duration_ms": "42.8",
            "ixbrowser_active": 1,
            "installation_id": "customer-device-real-id",
            "crash_stack": (
                "RuntimeError password=secret token=abc for @realbuyer "
                "at https://www.tiktok.com/@creator/video/123"
            ),
            "username": "@realbuyer",
            "comment_text": "Need this serum today",
            "screenshot_path": "C:/Users/customer/evidence.png",
            "sqlite_path": "C:/Users/customer/growth_intelligence.db",
            "proxy_password": "proxy-secret",
            "cookies": "tt_chain_token",
        }

        result = build_telemetry_payload(event, opt_in=True)
        payload = result["payload"]
        serialized = json.dumps(result)

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["telemetry_enabled"])
        self.assertEqual(payload["reachops_version"], "0.4.0")
        self.assertEqual(payload["windows_version"], "Windows 11 23H2")
        self.assertEqual(payload["error_code"], "LOGIN_REQUIRED")
        self.assertEqual(payload["failing_module"], "collector")
        self.assertEqual(payload["duration_ms"], 42)
        self.assertTrue(payload["ixbrowser_active"])
        self.assertTrue(payload["installation_id"].startswith("anon_"))
        self.assertNotIn("customer-device-real-id", serialized)
        self.assertNotIn("@realbuyer", serialized)
        self.assertNotIn("Need this serum today", serialized)
        self.assertNotIn("https://www.tiktok.com/@creator/video/123", serialized)
        self.assertNotIn("password=secret", serialized)
        self.assertNotIn("proxy-secret", serialized)
        self.assertNotIn("tt_chain_token", serialized)
        self.assertNotIn("growth_intelligence.db", serialized)
        self.assertIn("***redacted***", payload["crash_stack"])
        self.assertIn("username", result["dropped_fields"])
        self.assertIn("comment_text", result["dropped_fields"])
        self.assertIn("screenshot_path", result["dropped_fields"])
        self.assertIn("sqlite_path", result["dropped_fields"])
        self.assertIn("proxy_password", result["dropped_fields"])
        self.assertIn("cookies", result["dropped_fields"])

    def test_policy_status_documents_allowed_and_forbidden_boundaries(self):
        status = build_telemetry_policy_status()

        self.assertFalse(status["telemetry_enabled"])
        self.assertTrue(status["default_off"])
        self.assertTrue(status["requires_explicit_opt_in"])
        self.assertIn("reachops_version", status["allowed_fields"])
        self.assertIn("windows_version", status["allowed_fields"])
        self.assertIn("installation_id", status["allowed_fields"])
        self.assertIn("username", status["forbidden_field_tokens"])
        self.assertIn("cookie", status["forbidden_field_tokens"])
        self.assertIn("sqlite", status["forbidden_field_tokens"])


if __name__ == "__main__":
    unittest.main()
