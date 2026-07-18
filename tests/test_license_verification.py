import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ReachOps.license_verification import evaluate_license_verification_state
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_acceptance_status import activation_actions, activation_failed_checks


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LicenseVerificationTests(unittest.TestCase):
    def test_recent_verification_is_fresh_for_24_hour_interval(self):
        now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
        state = evaluate_license_verification_state({"last_verified_at": iso(now - timedelta(hours=2))}, now=now)

        self.assertEqual(state.status, "fresh")
        self.assertFalse(state.verification_required)
        self.assertEqual(state.interval_hours, 24)
        self.assertEqual(state.next_verify_at, "2026-07-20T10:00:00Z")

    def test_old_verification_is_due_after_24_hours(self):
        now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
        state = evaluate_license_verification_state({"last_verified_at": iso(now - timedelta(hours=25))}, now=now)

        self.assertEqual(state.status, "verification_due")
        self.assertTrue(state.verification_required)
        self.assertEqual(state.reason_code, "LICENSE_VERIFICATION_REQUIRED")

    def test_explicit_next_verify_at_controls_due_status(self):
        now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
        state = evaluate_license_verification_state(
            {"last_verified_at": iso(now - timedelta(hours=1)), "next_verify_at": iso(now - timedelta(minutes=1))},
            now=now,
        )

        self.assertEqual(state.status, "verification_due")
        self.assertTrue(state.verification_required)
        self.assertEqual(state.next_verify_at, "2026-07-19T11:59:00Z")

    def test_missing_verification_requires_first_activation_check(self):
        state = evaluate_license_verification_state({"active": True})

        self.assertEqual(state.status, "verification_due")
        self.assertTrue(state.verification_required)
        self.assertEqual(state.reason_code, "LICENSE_VERIFICATION_REQUIRED")

    def test_activation_status_reports_due_license_verification_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            status_path = Path(tmp) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "last_verified_at": iso(now - timedelta(hours=25)),
                        "license_tier": "enterprise",
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )

            result = check_activation_status(status_path)

            self.assertFalse(result["ready"])
            self.assertEqual(result["license_verification_state"]["status"], "verification_due")
            self.assertIn("license_verification_current", activation_failed_checks(result))
            self.assertTrue(any("24 小时" in action for action in activation_actions(result)))


if __name__ == "__main__":
    unittest.main()
