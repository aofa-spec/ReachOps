# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from ReachOps.workbench.device_seats import evaluate_device_seat
from tools.reachops_activation_status_check import check_activation_status


class StaticDevice:
    @classmethod
    def current_device_id(cls) -> str:
        return "device-b"


def activation_payload(**overrides):
    payload = {
        "active": True,
        "license_tier": "enterprise",
        "expires_at": "2099-01-01T00:00:00Z",
        "capabilities": {
            "live_submit": True,
            "comment_reply": True,
            "follow_review": True,
            "dm_review": True,
        },
    }
    payload.update(overrides)
    return payload


class DeviceSeatTests(unittest.TestCase):
    def test_default_single_device_license_allows_bound_device(self) -> None:
        decision = evaluate_device_seat(activation_payload(device_id="device-a"), "device-a")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "assigned")
        self.assertEqual(decision.evidence["seat_limit"], 1)
        self.assertTrue(decision.evidence["default_one_device"])

    def test_default_single_device_license_blocks_other_device_for_live_submit(self) -> None:
        decision = evaluate_device_seat(activation_payload(device_id="device-a"), "device-b")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_DEVICE_MISMATCH")

    def test_extra_seat_allows_secondary_device(self) -> None:
        payload = activation_payload(
            device_id="device-a",
            device_seats={"max_devices": 2, "device_ids": ["device-a", "device-b"]},
        )
        decision = evaluate_device_seat(payload, "device-b")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.evidence["seat_limit"], 2)
        self.assertEqual(decision.evidence["extra_seats"], 1)
        self.assertEqual(decision.evidence["seat_index"], 2)

    def test_overassigned_seat_manifest_blocks_live_submit(self) -> None:
        payload = activation_payload(device_seats={"max_devices": 1, "device_ids": ["device-a", "device-b"]})
        decision = evaluate_device_seat(payload, "device-a")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "LIVE_SUBMIT_SEAT_LIMIT_EXCEEDED")
        self.assertTrue(decision.evidence["local_data_access_allowed"])

    def test_unbound_legacy_activation_remains_bootstrap_compatible(self) -> None:
        decision = evaluate_device_seat(activation_payload(), "device-a")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "unbound_single_device_pending_binding")
        self.assertTrue(decision.evidence["binding_required"])

    def test_authorization_gate_allows_extra_seat_and_reports_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    activation_payload(
                        device_id="device-a",
                        device_seats={"max_devices": 2, "device_ids": ["device-a", "device-b"]},
                    )
                ),
                encoding="utf-8",
            )
            gate = LiveSubmitAuthorizationGate(str(status_path), device_identity=StaticDevice)
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "p1"})
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.evidence["device_seat_state"], "assigned")
            self.assertEqual(decision.evidence["device_seat"]["seat_limit"], 2)

    def test_authorization_gate_blocks_device_outside_seats(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(activation_payload(device_seats={"max_devices": 1, "device_ids": ["device-a"]})),
                encoding="utf-8",
            )
            gate = LiveSubmitAuthorizationGate(str(status_path), device_identity=StaticDevice)
            decision = gate.authorize_live_submit({"action_type": "comment_reply"}, {"profile_id": "p1"})
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.error_code, "LIVE_SUBMIT_DEVICE_MISMATCH")
            self.assertTrue(decision.evidence["device_seat"]["local_data_access_allowed"])

    def test_activation_status_check_reports_device_seat_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "reachops_activation_status.json"
            status_path.write_text(
                json.dumps(
                    activation_payload(
                        device_id="device-a",
                        device_seats={"max_devices": 2, "device_ids": ["device-a", "device-b"]},
                    )
                ),
                encoding="utf-8",
            )
            import os
            old_value = os.environ.get("REACHOPS_DEVICE_ID")
            os.environ["REACHOPS_DEVICE_ID"] = "device-b"
            try:
                status = check_activation_status(status_path)
            finally:
                if old_value is None:
                    os.environ.pop("REACHOPS_DEVICE_ID", None)
                else:
                    os.environ["REACHOPS_DEVICE_ID"] = old_value
            checks = {item["name"]: item for item in status["checks"]}
            self.assertTrue(checks["device_seat_entitled"]["passed"])
            self.assertTrue(status["device_seat"]["allowed"])
            self.assertEqual(status["device_seat"]["evidence"]["seat_limit"], 2)


if __name__ == "__main__":
    unittest.main()
