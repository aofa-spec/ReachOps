import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ReachOps.license_state import evaluate_license_state
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_acceptance_status import activation_actions, activation_failed_checks


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LicenseStateTests(unittest.TestCase):
    def test_future_activation_allows_app_and_live_submit(self):
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        state = evaluate_license_state({"active": True, "expires_at": iso(now + timedelta(days=30))}, now=now)

        self.assertEqual(state.status, "active")
        self.assertTrue(state.app_access_allowed)
        self.assertTrue(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "")

    def test_recently_expired_activation_enters_app_grace_but_blocks_live_submit(self):
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        state = evaluate_license_state({"active": True, "expires_at": iso(now - timedelta(days=1))}, now=now)

        self.assertEqual(state.status, "grace_period")
        self.assertTrue(state.app_access_allowed)
        self.assertFalse(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "LIVE_SUBMIT_LICENSE_GRACE_PERIOD")
        self.assertEqual(state.grace_until, "2026-07-25T00:00:00Z")

    def test_old_expired_activation_blocks_app_and_live_submit(self):
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        state = evaluate_license_state({"active": True, "expires_at": iso(now - timedelta(days=8))}, now=now)

        self.assertEqual(state.status, "expired")
        self.assertFalse(state.app_access_allowed)
        self.assertFalse(state.live_submit_allowed)
        self.assertEqual(state.reason_code, "LIVE_SUBMIT_LICENSE_EXPIRED")

    def test_live_submit_gate_blocks_grace_period_with_distinct_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": iso(datetime.now(timezone.utc) - timedelta(days=1)),
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    }
                ),
                encoding="utf-8",
            )

            decision = LiveSubmitAuthorizationGate(str(status_path)).authorize_live_submit(
                {"action_type": "comment_reply"},
                {"profile_id": "12345"},
            )

            self.assertFalse(decision.allowed)
            self.assertEqual(decision.error_code, "LIVE_SUBMIT_LICENSE_GRACE_PERIOD")
            self.assertEqual(decision.evidence["license_state"]["status"], "grace_period")
            self.assertTrue(decision.evidence["license_state"]["app_access_allowed"])
            self.assertFalse(decision.evidence["license_state"]["live_submit_allowed"])

    def test_activation_status_check_reports_license_grace_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": iso(datetime.now(timezone.utc) - timedelta(days=1)),
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            result = check_activation_status(status_path)

            self.assertFalse(result["ready"])
            self.assertEqual(result["license_state"]["status"], "grace_period")
            checks = {item["name"]: item for item in result["checks"]}
            self.assertTrue(checks["license_app_access_allowed"]["passed"])
            self.assertFalse(checks["license_live_submit_allowed"]["passed"])
            self.assertIn("license_live_submit_allowed", activation_failed_checks(result))
            self.assertTrue(any("7 天宽限期" in action for action in activation_actions(result)))


if __name__ == "__main__":
    unittest.main()
