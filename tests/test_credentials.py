import unittest
from unittest.mock import patch

from ReachOps.credentials import (
    AI_API_KEY_SECRET,
    ReachOpsCredentialStore,
    SecretLookup,
    ai_api_key_status,
    resolve_ai_api_key,
)
from ReachOps.intelligence.ai_strategy import HTTPAcquisitionIntelligenceProvider, build_default_acquisition_intelligence_provider


class FakeWindowsCredentialStore(ReachOpsCredentialStore):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.deleted = []

    def supported(self) -> bool:
        return True

    def _read_windows_secret(self, target_name: str) -> str:
        return self.values.get(target_name, "")

    def _write_windows_secret(self, target_name: str, secret_value: str) -> None:
        self.values[target_name] = secret_value

    def _delete_windows_secret(self, target_name: str) -> bool:
        self.deleted.append(target_name)
        return self.values.pop(target_name, None) is not None


class ReachOpsCredentialTests(unittest.TestCase):
    def test_non_windows_store_does_not_persist_secret(self):
        store = ReachOpsCredentialStore()
        with patch("platform.system", return_value="Darwin"):
            result = store.write_secret(AI_API_KEY_SECRET, "secret-value")
            lookup = store.read_secret(AI_API_KEY_SECRET)

        self.assertFalse(result.stored)
        self.assertFalse(result.persistent)
        self.assertEqual(result.status, "unsupported_platform")
        self.assertFalse(lookup.configured)
        self.assertEqual(lookup.source, "unsupported_platform")

    def test_environment_key_is_session_fallback_only(self):
        env = {"REACHOPS_AI_API_KEY": "session-secret"}
        with patch("platform.system", return_value="Darwin"):
            lookup = resolve_ai_api_key(env=env)
            status = ai_api_key_status(env=env)

        self.assertEqual(lookup.value, "session-secret")
        self.assertEqual(lookup.source, "environment_session")
        self.assertFalse(lookup.persistent)
        self.assertTrue(status["configured"])
        self.assertFalse(status["persistent"])
        self.assertTrue(status["secret_value_redacted"])

    def test_windows_credential_manager_round_trip_uses_reachops_target(self):
        store = FakeWindowsCredentialStore()

        stored = store.write_secret(AI_API_KEY_SECRET, "win-secret")
        lookup = store.read_secret(AI_API_KEY_SECRET)
        deleted = store.write_secret(AI_API_KEY_SECRET, "")

        self.assertTrue(stored.stored)
        self.assertTrue(stored.persistent)
        self.assertEqual(stored.source, "windows_credential_manager")
        self.assertEqual(lookup.value, "win-secret")
        self.assertEqual(lookup.source, "windows_credential_manager")
        self.assertEqual(store.deleted, ["ReachOps:ai_api_key"])
        self.assertTrue(deleted.deleted)

    def test_windows_credential_manager_precedes_environment_key(self):
        store = FakeWindowsCredentialStore()
        store.write_secret(AI_API_KEY_SECRET, "stored-secret")

        lookup = resolve_ai_api_key(env={"REACHOPS_AI_API_KEY": "env-secret"}, credential_store=store)

        self.assertEqual(lookup.value, "stored-secret")
        self.assertEqual(lookup.source, "windows_credential_manager")
        self.assertTrue(lookup.persistent)

    def test_default_http_ai_provider_uses_secret_resolver(self):
        env = {"REACHOPS_AI_ENDPOINT": "https://ai.local/analyze", "REACHOPS_AI_MODEL": "test-model"}
        with patch(
            "ReachOps.intelligence.ai_strategy.resolve_ai_api_key",
            return_value=SecretLookup("resolved-secret", "windows_credential_manager", True, True),
        ):
            provider = build_default_acquisition_intelligence_provider(env=env)

        self.assertIsInstance(provider, HTTPAcquisitionIntelligenceProvider)
        self.assertEqual(provider.api_key, "resolved-secret")
        self.assertEqual(provider._headers()["Authorization"], "Bearer resolved-secret")


if __name__ == "__main__":
    unittest.main()
