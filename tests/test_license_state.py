# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ReachOps.workbench.license_state import LicenseStateEvaluator


class LicenseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
        self.evaluator = LicenseStateEvaluator(grace_days=7)

    def test_active_license_allows_client_and_live_submit_when_capability_enabled(self):
        state = self.evaluator.evaluate(
            {
                "active": True,
                "expires_at": "2026-07-19T12:00:00Z",
                "capabilities": {"client_access": True, "live_submit": True},
            },
            now=self.now,
        )

        self.assertEqual(state.status, "active")
        self.assertTrue(state.client_access_allowed)
        self.assertTrue(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "LICENSE_ACTIVE")

    def test_grace_period_allows_client_access_but_blocks_live_submit(self):
        state = self.evaluator.evaluate(
            {
                "active": True,
                "expires_at": "2026-07-15T12:00:00Z",
                "capabilities": {"client_access": True, "live_submit": True},
            },
            now=self.now,
        )

        self.assertEqual(state.status, "grace")
        self.assertTrue(state.client_access_allowed)
        self.assertFalse(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "LICENSE_GRACE_PERIOD")
        self.assertEqual(state.grace_expires_at, "2026-07-22T12:00:00Z")

    def test_expired_license_outside_grace_blocks_client_and_live_submit(self):
        state = self.evaluator.evaluate(
            {
                "active": True,
                "expires_at": "2026-07-01T12:00:00Z",
                "capabilities": {"client_access": True, "live_submit": True},
            },
            now=self.now,
        )

        self.assertEqual(state.status, "expired")
        self.assertFalse(state.client_access_allowed)
        self.assertFalse(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "LICENSE_EXPIRED")

    def test_template_and_inactive_statuses_block_all_access(self):
        template = self.evaluator.evaluate({"template_only": True, "active": True, "expires_at": "2026-07-19T12:00:00Z"}, now=self.now)
        inactive = self.evaluator.evaluate({"active": False, "expires_at": "2026-07-19T12:00:00Z"}, now=self.now)

        self.assertEqual(template.reason_code, "LICENSE_TEMPLATE_ONLY")
        self.assertFalse(template.client_access_allowed)
        self.assertFalse(template.live_submit_allowed)
        self.assertEqual(inactive.reason_code, "LICENSE_INACTIVE")
        self.assertFalse(inactive.client_access_allowed)
        self.assertFalse(inactive.live_submit_allowed)


if __name__ == "__main__":
    unittest.main()
