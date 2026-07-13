# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from ReachOps.execution_plan import (
    build_autonomous_preflight_forecast,
    attach_autonomous_preflight_forecast,
    build_execution_plan,
    plan_fingerprint_sha256,
    validate_execution_plan,
    write_execution_plan,
)


class ExecutionPlanTests(unittest.TestCase):
    def test_parameter_mapping_matches_backend_normalized_contract(self) -> None:
        plan = build_execution_plan(
            target="  anti aging serum  ",
            source_type="keyword",
            mode="invalid-mode",
            profile_group="Canada",
            volume="stress",
            profile_limit="9999999",
            max_videos="20",
            max_comments="100",
            timeout_seconds="1800",
            live_confirmed="yes",
            account_repair_confirmed="no",
            force_account_recheck="true",
            comment_text="Hi",
            origin="unit_test",
        )
        mapping = ((plan.get("ui") or {}).get("parameter_mapping") or {})
        fields = mapping.get("fields") or {}

        self.assertEqual(validate_execution_plan(plan), [])
        self.assertEqual(mapping["schema_version"], "reachops.execution_plan_parameter_mapping.v1")
        self.assertTrue(mapping["no_ai_token_used"])
        self.assertEqual(plan["target"], "anti aging serum")
        self.assertEqual(fields["target"]["normalized"], plan["target"])
        self.assertEqual(fields["mode"]["input"], "invalid-mode")
        self.assertEqual(fields["mode"]["normalized"], plan["mode"])
        self.assertEqual(plan["mode"], "preflight")
        self.assertEqual(fields["profile_group"]["normalized"], plan["profile_group"])
        self.assertEqual(fields["profile_limit"]["normalized"], plan["limits"]["profile_limit"])
        self.assertEqual(fields["live_confirmed"]["normalized"], plan["authorization"]["live_confirmed"])
        self.assertEqual(fields["force_account_recheck"]["normalized"], plan["runtime"]["force_account_recheck"])
        self.assertTrue(fields["comment_text_present"]["normalized"])
        self.assertEqual(plan["runtime_contract"]["schema_version"], "reachops.execution_runtime_contract.v1")
        self.assertEqual(plan["runtime_contract"]["executor"], "local_program")
        self.assertEqual(plan["runtime_contract"]["control_surface"], "local_client_console")
        self.assertFalse(plan["runtime_contract"]["ai_console_is_execution_dependency"])
        self.assertTrue(plan["runtime_contract"]["no_ai_token_during_execution"])
        self.assertFalse(plan["runtime_contract"]["execution_phase_ai_calls_allowed"])
        self.assertTrue(plan["runtime_contract"]["no_submit_without_authorization"])
        self.assertTrue(plan["runtime_contract"]["run_session_required"])
        self.assertTrue(plan["runtime_contract"]["page_state_evidence_required"])
        self.assertTrue(plan["runtime_contract"]["evidence_bundle_required"])

    def test_same_normalized_plan_is_reproducible(self) -> None:
        first = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        second = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(first["plan_fingerprint_sha256"], second["plan_fingerprint_sha256"])
        self.assertEqual(first["plan_fingerprint_sha256"], plan_fingerprint_sha256(first))

    def test_plan_fingerprint_mismatch_is_rejected(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        plan["plan_fingerprint_sha256"] = "bad"
        self.assertIn("plan_fingerprint_sha256_mismatch", validate_execution_plan(plan))

    def test_plan_id_mismatch_is_rejected(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        plan["plan_id"] = "plan_wrong"
        self.assertIn("plan_id_mismatch", validate_execution_plan(plan))

    def test_live_comment_plan_requires_authorized_submit_gate(self) -> None:
        plan = build_execution_plan(
            target="anti aging serum",
            source_type="keyword",
            mode="live_comment",
            profile_group="Canada",
            live_confirmed=False,
        )
        errors = validate_execution_plan(plan)
        self.assertIn("authorization_live_confirmed_required", errors)
        self.assertIn("authorization_live_submit_allowed_required", errors)
        self.assertTrue(plan["runtime_contract"]["requires_human_authorization_for_live_actions"])

    def test_collect_plan_cannot_enable_live_submit(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        plan["authorization"]["live_submit_allowed"] = True
        self.assertIn("authorization_live_submit_not_allowed_for_mode", validate_execution_plan(plan))

    def test_missing_nested_contract_is_rejected_before_write(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        del plan["limits"]["max_comments"]
        del plan["repair_policy"]["DOM_STALLED"]
        plan["risk_policy"]["no_ai_token_during_execution"] = False
        plan["runtime_contract"]["no_ai_token_during_execution"] = False
        errors = validate_execution_plan(plan)
        self.assertIn("limits_max_comments_required", errors)
        self.assertIn("repair_policy_DOM_STALLED_required", errors)
        self.assertIn("risk_policy_no_ai_token_required", errors)
        self.assertIn("runtime_contract_no_ai_token_required", errors)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "Invalid ExecutionPlan"):
                write_execution_plan(plan, Path(td) / "bad_plan.json")

    def test_autonomous_preflight_forecast_blocks_unready_live_action_without_tokens(self) -> None:
        plan = build_execution_plan(
            target="anti aging serum",
            source_type="keyword",
            mode="live_comment",
            profile_group="Canada",
            live_confirmed=False,
        )
        forecast = build_autonomous_preflight_forecast(
            plan,
            preflight_decision={
                "schema_version": "reachops.start_preflight_decision.v1",
                "start_allowed": False,
                "blockers": ["live_comment_confirmation_required"],
            },
        )
        self.assertEqual(forecast["schema_version"], "reachops.autonomous_preflight_forecast.v1")
        self.assertEqual(forecast["status"], "blocked")
        self.assertFalse(forecast["start_allowed"])
        self.assertIn("live_comment_confirmation_required", forecast["predicted_blockers"])
        self.assertIn("authorization_live_confirmed_required", forecast["predicted_blockers"])
        self.assertIn("BLOCKED", forecast["predicted_state_sequence"])
        self.assertTrue(any(row["gate"] == "live_action_authorization" and row["status"] == "blocked" for row in forecast["risk_gates"]))
        self.assertTrue(any(row["state"] == "UNKNOWN_PAGE_STATE" and row["terminal_outcome"] == "BLOCKED" for row in forecast["repair_routes"]))
        self.assertTrue(any(row["to"] == "collect" for row in forecast["degradation_routes"]))
        self.assertTrue(any("真实评论前确认授权" in row for row in forecast["human_required_actions"]))
        self.assertTrue(forecast["runtime_invariants"]["no_ai_token_during_execution"])
        self.assertEqual(forecast["runtime_invariants"]["executor"], "local_program")
        self.assertFalse(forecast["runtime_invariants"]["ai_console_is_execution_dependency"])
        self.assertTrue(forecast["no_ai_token_used"])
        self.assertTrue(forecast["no_browser_started"])
        self.assertTrue(forecast["no_submit"])

    def test_autonomous_preflight_forecast_predicts_local_repair_and_evidence_contract(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        forecast = build_autonomous_preflight_forecast(
            plan,
            preflight_decision={
                "schema_version": "reachops.start_preflight_decision.v1",
                "start_allowed": True,
                "blockers": [],
            },
        )
        self.assertEqual(forecast["status"], "ready")
        self.assertTrue(forecast["start_allowed"])
        self.assertIn("PROFILE_OPENING", forecast["predicted_state_sequence"])
        self.assertIn("REPAIRING", forecast["predicted_state_sequence"])
        self.assertIn("COMPLETED", forecast["predicted_state_sequence"])
        self.assertTrue(any(row["state"] == "LOGIN_REQUIRED" and row["action"] == "quarantine_profile" for row in forecast["repair_routes"]))
        self.assertIn("execution_plan_snapshot", forecast["evidence_requirements"])
        self.assertIn("run_session_state_history", forecast["evidence_requirements"])
        self.assertTrue(forecast["runtime_invariants"]["never_bypass_login_or_captcha"])
        self.assertFalse(forecast["runtime_invariants"]["live_submit_allowed"])

    def test_attached_autonomous_preflight_forecast_is_derivative_and_replayable(self) -> None:
        plan = build_execution_plan(target="anti aging serum", source_type="keyword", mode="collect", profile_group="Canada")
        attached = attach_autonomous_preflight_forecast(
            plan,
            preflight_decision={
                "schema_version": "reachops.start_preflight_decision.v1",
                "start_allowed": True,
                "blockers": [],
            },
        )
        self.assertEqual(attached["plan_id"], plan["plan_id"])
        self.assertEqual(attached["plan_fingerprint_sha256"], plan["plan_fingerprint_sha256"])
        self.assertEqual(validate_execution_plan(attached), [])
        self.assertEqual(
            attached["runtime"]["autonomous_preflight_forecast"]["schema_version"],
            "reachops.autonomous_preflight_forecast.v1",
        )
        self.assertTrue(attached["runtime"]["autonomous_preflight_forecast"]["no_ai_token_used"])


if __name__ == "__main__":
    unittest.main()
