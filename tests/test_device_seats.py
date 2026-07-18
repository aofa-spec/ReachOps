import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ReachOps.device_seats import evaluate_device_seat_state
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_acceptance_status import activation_actions, activation_failed_checks


class DeviceA:
    @classmethod
    def current_device_id(cls) -> str:
        return "device-a"


class DeviceSeatTests(unittest.TestCase):
    def test_legacy_unbound_activation_remains_compatible(self):
        state = evaluate_device_seat_state({"active": True}, "device-a")

        self.assertEqual(state.status, "legacy_unbound")
        self.assertEqual(state.allowed_seats, 1)
        self.assertTrue(state.device_allowed)
        self.assertTrue(state.seat_available)

    def test_current_device_bound_with_extra_seats_is_allowed(self):
        state = evaluate_device_seat_state(
            {
                "device_seats": {
                    "allowed": 2,
                    "devices": [{"device_id": "device-a"}, {"device_id": "device-b"}],
                }
            },
            "device-a",
        )

        self.assertEqual(state.status, "bound_current_device")
        self.assertEqual(state.allowed_seats, 2)
        self.assertEqual(state.registered_device_ids, ["device-a", "device-b"])
        self.assertTrue(state.device_allowed)

    def test_unbound_device_is_rejected_when_seat_limit_is_full(self):
        state = evaluate_device_seat_state(
            {"device_seats": {"allowed": 1, "devices": [{"device_id": "device-b"}]}},
            "device-a",
        )

        self.assertEqual(state.status, "seat_limit_exceeded")
        self.assertFalse(state.device_allowed)
        self.assertFalse(state.seat_available)
        self.assertEqual(state.reason_code, "DEVICE_SEAT_LIMIT_EXCEEDED")

    def test_unbound_device_with_available_seat_still_requires_activation_refresh(self):
        state = evaluate_device_seat_state(
            {"device_seats": {"allowed": 2, "devices": [{"device_id": "device-b"}]}},
            "device-a",
        )

        self.assertEqual(state.status, "seat_available_unbound")
        self.assertFalse(state.device_allowed)
        self.assertTrue(state.seat_available)
        self.assertEqual(state.reason_code, "DEVICE_SEAT_REQUIRES_ACTIVATION")

    def test_authorization_gate_blocks_unbound_current_device_even_when_seat_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "device_seats": {"allowed": 2, "devices": [{"device_id": "device-b"}]},
                        "capabilities": {"live_submit": True, "comment_reply": True},
                    }
                ),
                encoding="utf-8",
            )

            decision = LiveSubmitAuthorizationGate(str(status_path), device_identity=DeviceA).authorize_live_submit(
                {"action_type": "comment_reply"},
                {"profile_id": "12345"},
            )

            self.assertFalse(decision.allowed)
            self.assertEqual(decision.error_code, "LIVE_SUBMIT_DEVICE_MISMATCH")
            self.assertEqual(decision.evidence["device_seat_state"]["status"], "seat_available_unbound")
            self.assertTrue(decision.evidence["device_seat_state"]["seat_available"])

    def test_activation_status_reports_device_seat_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_at": "2999-01-01T00:00:00Z",
                        "license_tier": "enterprise",
                        "device_seats": {"allowed": 1, "devices": [{"device_id": "device-b"}]},
                        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"REACHOPS_DEVICE_ID": "device-a"}):
                result = check_activation_status(status_path)

            self.assertFalse(result["ready"])
            self.assertEqual(result["device_seat_state"]["status"], "seat_limit_exceeded")
            self.assertIn("device_seat_allows_current_device", activation_failed_checks(result))
            self.assertTrue(any("device_id/device_seats" in action for action in activation_actions(result)))


if __name__ == "__main__":
    unittest.main()
