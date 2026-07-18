# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from ReachOps.credential_secrets import AI_API_KEY_CREDENTIAL, WindowsCredentialSecretStore
from ReachOps.intelligence.ai_strategy import (
    HTTPAcquisitionIntelligenceProvider,
    RuleBasedAcquisitionIntelligenceProvider,
    build_default_acquisition_intelligence_provider,
)


class FakeSecretStore:
    def __init__(self, value: str = "", available: bool = True):
        self.value = value
        self.available = available
        self.read_names: list[str] = []

    def is_available(self) -> bool:
        return self.available

    def get_secret(self, name: str) -> str:
        self.read_names.append(name)
        return self.value


class CredentialSecretsTests(unittest.TestCase):
    def test_non_windows_store_is_unavailable_and_does_not_write_fallback_file(self):
        store = WindowsCredentialSecretStore(platform="darwin")

        self.assertFalse(store.is_available())
        result = store.set_secret("AI/APIKey", "secret")

        self.assertFalse(result.ok)
        self.assertFalse(result.available)
        self.assertEqual(result.backend, "windows_credential_manager")
        self.assertEqual(result.error_code, "SECRET_STORE_UNAVAILABLE")

    def test_secret_target_names_are_scoped_to_reachops(self):
        store = WindowsCredentialSecretStore(platform="win32")

        self.assertEqual(store.target_name("AI/APIKey"), AI_API_KEY_CREDENTIAL)
        self.assertEqual(store.target_name(AI_API_KEY_CREDENTIAL), AI_API_KEY_CREDENTIAL)

    def test_default_ai_provider_reads_api_key_from_secret_store(self):
        store = FakeSecretStore(value="credential-key")

        provider = build_default_acquisition_intelligence_provider(
            env={"REACHOPS_AI_ENDPOINT": "https://ai.local/analyze"},
            secret_store=store,
        )

        self.assertIsInstance(provider, HTTPAcquisitionIntelligenceProvider)
        self.assertEqual(store.read_names, [AI_API_KEY_CREDENTIAL])
        self.assertEqual(provider._headers()["Authorization"], "Bearer credential-key")

    def test_environment_api_key_takes_precedence_over_secret_store(self):
        store = FakeSecretStore(value="credential-key")

        provider = build_default_acquisition_intelligence_provider(
            env={"REACHOPS_AI_ENDPOINT": "https://ai.local/analyze", "REACHOPS_AI_API_KEY": "env-key"},
            secret_store=store,
        )

        self.assertIsInstance(provider, HTTPAcquisitionIntelligenceProvider)
        self.assertEqual(store.read_names, [])
        self.assertEqual(provider._headers()["Authorization"], "Bearer env-key")

    def test_missing_endpoint_uses_offline_rules_without_secret_lookup(self):
        store = FakeSecretStore(value="credential-key")

        provider = build_default_acquisition_intelligence_provider(env={}, secret_store=store)

        self.assertIsInstance(provider, RuleBasedAcquisitionIntelligenceProvider)
        self.assertEqual(store.read_names, [])


if __name__ == "__main__":
    unittest.main()
