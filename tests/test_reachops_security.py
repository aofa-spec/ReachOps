# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ReachOps.intelligence.ai_strategy import build_default_acquisition_intelligence_provider
from ReachOps.runtime_paths import RuntimePaths
from ReachOps.security.credential_store import (
    BACKEND_NON_WINDOWS_UNAVAILABLE,
    BACKEND_WINDOWS_CREDENTIAL_MANAGER,
    CREDENTIAL_STORAGE_SCHEMA_VERSION,
    CredentialStoreUnavailable,
    ReachOpsCredentialStore,
    credential_storage_status,
    redact_secret,
)
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from ReachOps.workbench.license_refresh_client import (
    LICENSE_REFRESH_SCHEMA_VERSION,
    LicenseRefreshError,
    LicenseRefreshRejected,
    LicenseRefreshResponse,
    build_license_refresh_request,
    refresh_license_status,
    validate_license_refresh_request,
)


class ReachOpsSecurityTests(unittest.TestCase):
    def test_redact_secret_never_returns_full_secret(self) -> None:
        secret = "sk-test-secret-abcdef123456"
        redacted = redact_secret(secret)
        self.assertNotEqual(redacted, secret)
        self.assertNotIn("sk-test-secret-abcdef", redacted)
        self.assertTrue(redacted.endswith("3456"))
        self.assertGreaterEqual(redacted.count("*"), 8)

    def test_redact_secret_with_zero_visible_tail_hides_entire_secret(self) -> None:
        secret = "sk-test-secret-zero-tail"
        redacted = redact_secret(secret, visible_tail=0)

        self.assertNotEqual(redacted, secret)
        self.assertNotIn(secret, redacted)
        self.assertNotIn("zero-tail", redacted)
        self.assertEqual(set(redacted), {"*"})
        self.assertGreaterEqual(len(redacted), 8)

    def test_non_windows_refuses_secret_persistence(self) -> None:
        if sys.platform.startswith("win"):
            self.skipTest("non-Windows refusal is covered on macOS/Linux")
        status = credential_storage_status()
        self.assertEqual(status["schema_version"], CREDENTIAL_STORAGE_SCHEMA_VERSION)
        self.assertEqual(status["backend"], BACKEND_NON_WINDOWS_UNAVAILABLE)
        self.assertFalse(status["available"])
        self.assertFalse(status["secret_persistence_allowed"])
        self.assertTrue(status["windows_credential_manager_required"])
        self.assertFalse(status["status_includes_secret_values"])
        with self.assertRaises(CredentialStoreUnavailable):
            ReachOpsCredentialStore().set_secret("ai_api_key", "sk-should-not-persist")

    def test_status_never_contains_secret_value_fields(self) -> None:
        status_text = repr(credential_storage_status())
        self.assertNotIn("CredentialBlob", status_text)
        self.assertNotIn("sk-", status_text)
        self.assertNotIn("api_key", status_text)

    def test_default_ai_provider_uses_env_key_without_persistence(self) -> None:
        provider = build_default_acquisition_intelligence_provider(
            {
                "REACHOPS_AI_ENDPOINT": "https://ai.local/analyze",
                "REACHOPS_AI_API_KEY": "sk-env-only",
                "REACHOPS_AI_MODEL": "reachops-test",
            }
        )
        headers = provider._headers()  # type: ignore[attr-defined]
        self.assertEqual(headers["Authorization"], "Bearer sk-env-only")
        self.assertNotIn("sk-env-only", repr(credential_storage_status()))

    def test_default_ai_provider_has_no_auth_header_when_no_secret_available(self) -> None:
        previous = os.environ.pop("REACHOPS_AI_API_KEY", None)
        try:
            provider = build_default_acquisition_intelligence_provider(
                {
                    "REACHOPS_AI_ENDPOINT": "https://ai.local/analyze",
                    "REACHOPS_AI_MODEL": "reachops-test",
                }
            )
            self.assertNotIn("Authorization", provider._headers())  # type: ignore[attr-defined]
        finally:
            if previous is not None:
                os.environ["REACHOPS_AI_API_KEY"] = previous

    def test_source_contract_requires_windows_credential_manager_backend(self) -> None:
        import ReachOps.security.credential_store as credential_store

        source = Path(credential_store.__file__).read_text(encoding="utf-8")
        self.assertIn("win32cred", source)
        self.assertIn("CredWrite", source)
        self.assertIn("CredRead", source)
        self.assertIn("CRED_TYPE_GENERIC", source)
        self.assertIn(BACKEND_WINDOWS_CREDENTIAL_MANAGER, source)
        self.assertIn("must not be written to SQLite", source)

    def test_legacy_tk_ai_settings_do_not_persist_key_to_environment(self) -> None:
        source = Path("ReachOps/workbench/console.py").read_text(encoding="utf-8")
        self.assertIn("ReachOpsCredentialStore().set_secret(\"ai_api_key\", key)", source)
        self.assertIn("key_backend=windows_credential_manager", source)
        self.assertNotIn("os.environ[\"REACHOPS_AI_API_KEY\"] = key", source)

    def test_license_refresh_request_contains_only_minimal_license_metadata(self) -> None:
        payload = build_license_refresh_request(
            license_id="lic_test_123",
            device_id="device-test",
            app_version="0.4.0",
            requested_at="2026-07-19T00:00:00Z",
        )

        self.assertEqual(payload["schema_version"], LICENSE_REFRESH_SCHEMA_VERSION)
        self.assertEqual(set(payload), {"schema_version", "license_id", "device_id", "app_version", "platform", "requested_at"})
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in ["comment", "username", "screenshot", "cookie", "session", "sqlite", "db_path", "target_url"]:
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(payload.get("customer_data_uploaded", False))

    def test_license_refresh_rejects_customer_data_fields(self) -> None:
        payload = build_license_refresh_request(license_id="lic_test_123", device_id="device-test", app_version="0.4.0")
        payload["username"] = "real_user_should_not_upload"

        with self.assertRaises(LicenseRefreshRejected):
            validate_license_refresh_request(payload)

    def test_license_refresh_failure_does_not_write_activation_status(self) -> None:
        def failing_transport(endpoint: str, payload: dict, timeout_seconds: int) -> LicenseRefreshResponse:
            return LicenseRefreshResponse(status_code=503, payload={"error": "maintenance"})

        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.build(tmp).ensure_dirs()
            with self.assertRaises(LicenseRefreshError):
                refresh_license_status(
                    endpoint="https://license.example.test/refresh",
                    license_id="lic_test_123",
                    app_version="0.4.0",
                    base_dir=tmp,
                    device_id="device-test",
                    transport=failing_transport,
                )

            self.assertFalse(Path(paths.activation_status_path).exists())

    def test_license_refresh_writes_local_activation_status_without_customer_data(self) -> None:
        def ok_transport(endpoint: str, payload: dict, timeout_seconds: int) -> LicenseRefreshResponse:
            self.assertEqual(endpoint, "https://license.example.test/refresh")
            self.assertEqual(payload["license_id"], "lic_test_123")
            return LicenseRefreshResponse(
                status_code=200,
                payload={
                    "activation_status": {
                        "active": True,
                        "device_id": payload["device_id"],
                        "license_id": payload["license_id"],
                        "license_tier": "enterprise",
                        "subscription_status": "active",
                        "expires_at": "2999-01-01T00:00:00Z",
                        "capabilities": {
                            "live_submit": True,
                            "comment_reply": True,
                            "follow_review": True,
                            "dm_review": False,
                        },
                        "update_metadata": {"latest_version": "0.4.1"},
                    }
                },
            )

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"REACHOPS_DEVICE_ID": "device-test"}, clear=False):
            result = refresh_license_status(
                endpoint="https://license.example.test/refresh",
                license_id="lic_test_123",
                app_version="0.4.0",
                base_dir=tmp,
                device_id="device-test",
                transport=ok_transport,
            )
            status_path = Path(result["activation_status_path"])
            written = json.loads(status_path.read_text(encoding="utf-8"))
            serialized = json.dumps(written, ensure_ascii=False).lower()

            self.assertEqual(result["schema_version"], LICENSE_REFRESH_SCHEMA_VERSION)
            self.assertTrue(status_path.exists())
            self.assertFalse(written["template_only"])
            self.assertEqual(written["device_id"], "device-test")
            self.assertEqual(written["license_state"]["state"], "active_current")
            self.assertTrue(written["license_state"]["live_submit_ready"])
            self.assertFalse(written["customer_data_uploaded"])
            self.assertTrue(written["no_browser_started"])
            self.assertTrue(written["no_submit"])
            for forbidden in ["comment_text", "username", "cookie", "session", "sqlite", "screenshot"]:
                self.assertNotIn(forbidden, serialized)

            action = {"id": "action-1", "action_type": "comment_reply"}
            profile = {"profile_id": "profile-1"}
            decision = LiveSubmitAuthorizationGate(str(status_path)).authorize_live_submit(action, profile)
            self.assertTrue(decision.allowed)

    def test_license_refresh_source_contract_uses_https_and_atomic_local_status(self) -> None:
        source = Path("ReachOps/workbench/license_refresh_client.py").read_text(encoding="utf-8")
        self.assertIn("LICENSE_REFRESH_SCHEMA_VERSION", source)
        self.assertIn("endpoint must use https", source)
        self.assertIn("ALLOWED_REQUEST_KEYS", source)
        self.assertIn("FORBIDDEN_REFRESH_TOKENS", source)
        self.assertIn("os.replace", source)
        self.assertIn("customer_data_uploaded\": False", source)
        self.assertIn("no_browser_started\": True", source)
        self.assertIn("no_submit\": True", source)


if __name__ == "__main__":
    unittest.main()
