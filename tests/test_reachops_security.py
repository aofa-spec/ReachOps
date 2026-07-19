# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from ReachOps.intelligence.ai_strategy import build_default_acquisition_intelligence_provider
from ReachOps.security.credential_store import (
    BACKEND_NON_WINDOWS_UNAVAILABLE,
    BACKEND_WINDOWS_CREDENTIAL_MANAGER,
    CREDENTIAL_STORAGE_SCHEMA_VERSION,
    CredentialStoreUnavailable,
    ReachOpsCredentialStore,
    credential_storage_status,
    redact_secret,
)


class ReachOpsSecurityTests(unittest.TestCase):
    def test_redact_secret_never_returns_full_secret(self) -> None:
        secret = "sk-test-secret-abcdef123456"
        redacted = redact_secret(secret)
        self.assertNotEqual(redacted, secret)
        self.assertNotIn("sk-test-secret-abcdef", redacted)
        self.assertTrue(redacted.endswith("3456"))
        self.assertGreaterEqual(redacted.count("*"), 8)

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


if __name__ == "__main__":
    unittest.main()
