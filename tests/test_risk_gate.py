import os
import json
import tempfile
import unittest
from dataclasses import dataclass, field

from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.workbench.action_router import ActionRouter
from ReachOps.workbench.account_health_manager import AccountHealthManager
from ReachOps.workbench.risk_gate import RiskGate, risk_gate_summary
from tools.reachops_web_ui import build_operator_outreach_rows


@dataclass
class FakeAuthorizationDecision:
    allowed: bool
    error_code: str = ""
    error_message: str = ""
    evidence: dict = field(default_factory=dict)


class RiskGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = RiskGate()
        self.action = {"id": "a1", "action_type": "comment_reply", "status": "approved", "execution_confirmed": 1}
        self.profile = {"profile_id": "p1", "group_name": "United States"}

    def test_allows_safe_dry_run_without_ai_token(self):
        decision = self.gate.evaluate(self.action, self.profile)
        self.assertTrue(decision["allowed"])
        self.assertTrue(decision["risk_decision_id"].startswith("risk_"))
        self.assertEqual(decision["risk_category"], "allowed")
        self.assertEqual(decision["terminal_outcome"], "allowed")
        self.assertTrue(decision["no_ai_token_used"])
        self.assertEqual(decision["schema_version"], "reachops.risk_gate.v1")

    def test_blocks_publish_profile(self):
        decision = self.gate.evaluate(self.action, {"profile_id": "main-account-1", "group_name": "publish"})
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "PUBLISH_PROFILE_BLOCKED")
        self.assertTrue(decision["block_execution"])
        self.assertIn("switch_profile_group", [row["step"] for row in decision["risk_actions"]])

    def test_blocks_cooldown_profile(self):
        decision = self.gate.evaluate(self.action, self.profile, profile_state={"status": "cooldown"})
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "PROFILE_IN_COOLDOWN")
        self.assertTrue(decision["cooldown"])
        self.assertTrue(decision["block_execution"])
        self.assertFalse(decision["requires_human_review"])
        self.assertIn("wait_or_switch_profile", [row["step"] for row in decision["risk_actions"]])

    def test_blocks_live_submit_without_authorization(self):
        decision = self.gate.evaluate(
            self.action,
            self.profile,
            live_submit=True,
            require_authorization=True,
            authorization_decision=FakeAuthorizationDecision(False, "LIVE_SUBMIT_NOT_AUTHORIZED", "missing"),
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "LIVE_SUBMIT_NOT_AUTHORIZED")
        self.assertEqual(decision["risk_category"], "authorization")
        self.assertEqual(decision["terminal_outcome"], "blocked_human_review")
        self.assertTrue(decision["requires_authorization"])
        self.assertTrue(decision["requires_human_review"])
        self.assertIn("request_operator_authorization", [row["step"] for row in decision["risk_actions"]])

    def test_blocks_high_risk_live_action_without_review_note(self):
        action = dict(self.action, risk_level="high", review_note="")
        decision = self.gate.evaluate(action, self.profile, live_submit=True)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "HIGH_RISK_REVIEW_NOTE_REQUIRED")
        self.assertTrue(decision["high_risk"])
        self.assertTrue(decision["requires_human_review"])
        self.assertIn("request_review_note", [row["step"] for row in decision["risk_actions"]])

    def test_blocks_quota_exhausted(self):
        decision = self.gate.evaluate(self.action, self.profile, quota_status={"ok": False, "used": 20, "limit": 20})
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "DAILY_QUOTA_EXCEEDED")
        self.assertEqual(decision["risk_category"], "quota")
        self.assertEqual(decision["terminal_outcome"], "blocked_wait_or_switch")
        self.assertFalse(decision["quota_ok"])
        self.assertTrue(decision["block_execution"])

    def test_blocks_rate_limited(self):
        decision = self.gate.evaluate(self.action, self.profile, rate_status={"ok": False, "code": "RATE_LIMITED"})
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "RATE_LIMITED")
        self.assertFalse(decision["rate_limit_ok"])
        self.assertTrue(decision["block_execution"])

    def test_blocks_duplicate_action_text_for_live_submit(self):
        decision = self.gate.evaluate(
            self.action,
            self.profile,
            live_submit=True,
            duplicate_text_status={
                "ok": False,
                "code": "DUPLICATE_ACTION_TEXT",
                "message": "same rendered text already used",
                "matched_execution_id": "oe_1",
            },
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "DUPLICATE_ACTION_TEXT")
        self.assertEqual(decision["risk_category"], "duplicate_text")
        self.assertEqual(decision["terminal_outcome"], "blocked_rewrite_required")
        self.assertTrue(decision["block_execution"])
        steps = [row["step"] for row in decision["risk_actions"]]
        self.assertIn("rewrite_or_rotate_message", steps)
        self.assertEqual(decision["evidence"]["matched_execution_id"], "oe_1")

    def test_blocks_precheck_profile_group_not_found(self):
        decision = self.gate.block_precheck(
            "profile_group_not_found",
            "group missing",
            evidence={"profile_group": "Ghost Group"},
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason_code"], "profile_group_not_found")
        self.assertTrue(decision["block_execution"])
        self.assertEqual(decision["risk_category"], "profile_policy")
        steps = [row["step"] for row in decision["risk_actions"]]
        self.assertIn("refresh_profile_groups", steps)
        self.assertIn("reselect_profile_group", steps)

    def test_summary_is_operator_readable(self):
        decision = self.gate.evaluate(self.action, self.profile, rate_status={"ok": False, "code": "RATE_LIMITED"})
        self.assertIn("reason=RATE_LIMITED", risk_gate_summary(decision))
        self.assertIn("category=rate_limit", risk_gate_summary(decision))
        self.assertIn("outcome=blocked_wait_or_switch", risk_gate_summary(decision))

    def test_risk_decision_id_is_stable_for_same_gate(self):
        first = self.gate.evaluate(self.action, self.profile, rate_status={"ok": False, "code": "RATE_LIMITED"})
        second = self.gate.evaluate(self.action, self.profile, rate_status={"ok": False, "code": "RATE_LIMITED"})
        self.assertEqual(first["risk_decision_id"], second["risk_decision_id"])

    def test_action_router_duplicate_text_status_matches_recent_success(self):
        class FakeStorage:
            def list_outreach_executions(self, limit=100, batch_id=""):
                return [
                    {
                        "id": "oe_recent",
                        "action_id": "a-old",
                        "status": "success",
                        "profile_id": "p1",
                        "action_type": "comment_reply",
                        "error_message": "Hello there",
                    }
                ]

        router = object.__new__(ActionRouter)
        router.storage = FakeStorage()
        status = router._duplicate_text_status(
            profile_id="p1",
            action_type="comment_reply",
            rendered_text=" hello   there ",
        )
        self.assertFalse(status["ok"])
        self.assertEqual(status["code"], "DUPLICATE_ACTION_TEXT")
        self.assertEqual(status["matched_execution_id"], "oe_recent")
        self.assertTrue(status["no_ai_token_used"])

    def test_storage_round_trips_risk_gate_on_outreach_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = GrowthStorage(os.path.join(tmp, "reachops.db"))
            gate = self.gate.evaluate(
                self.action,
                self.profile,
                live_submit=True,
                duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT"},
            )
            execution_id = storage.create_outreach_execution(
                "a1",
                "comment_reply",
                "target_user",
                status="skipped",
                profile_id="p1",
                error_code="DUPLICATE_ACTION_TEXT",
                error_message="duplicate text",
                risk_gate=gate,
            )

            rows = storage.list_outreach_executions(limit=10)

        row = next(item for item in rows if item["id"] == execution_id)
        self.assertEqual(row["risk_gate"]["schema_version"], "reachops.risk_gate.v1")
        self.assertEqual(row["risk_gate"]["reason_code"], "DUPLICATE_ACTION_TEXT")
        self.assertEqual(row["risk_gate"]["terminal_outcome"], "blocked_rewrite_required")

    def test_action_router_record_persists_risk_gate_before_returning(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = object.__new__(ActionRouter)
            router.storage = GrowthStorage(os.path.join(tmp, "reachops.db"))
            gate = self.gate.evaluate(
                self.action,
                self.profile,
                live_submit=True,
                duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT"},
            )

            result = router._record(
                self.action,
                self.profile,
                "skipped",
                "DUPLICATE_ACTION_TEXT",
                "duplicate text",
                "",
                1,
                risk_gate=gate,
            )
            rows = router.storage.list_outreach_executions(limit=10)

        persisted = next(item for item in rows if item["id"] == result["execution_id"])
        self.assertEqual(result["risk_gate"]["reason_code"], "DUPLICATE_ACTION_TEXT")
        self.assertEqual(persisted["risk_gate"]["reason_code"], "DUPLICATE_ACTION_TEXT")
        self.assertTrue(persisted["risk_gate"]["block_execution"])

    def test_operator_outreach_rows_expose_risk_gate_summary_and_next_step(self):
        gate = self.gate.evaluate(
            self.action,
            self.profile,
            live_submit=True,
            duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT"},
        )

        rows = build_operator_outreach_rows(
            [{"id": "a1", "action_type": "comment_reply", "target_username": "target", "status": "approved"}],
            [
                {
                    "id": "oe_1",
                    "action_id": "a1",
                    "action_type": "comment_reply",
                    "target_username": "target",
                    "profile_id": "p1",
                    "status": "skipped",
                    "error_code": "DUPLICATE_ACTION_TEXT",
                    "risk_gate_json": json.dumps(gate, ensure_ascii=False),
                    "created_at": "2026-07-05T00:00:00Z",
                }
            ],
            {"mode": "live_comment"},
        )

        self.assertIn("风险门禁阻断", rows[0]["risk_gate_summary"])
        self.assertIn("DUPLICATE_ACTION_TEXT", rows[0]["risk_gate_summary"])
        self.assertIn("改写或轮换话术", rows[0]["next_step"])

    def test_account_health_manager_forces_cooldown_after_configured_consecutive_failures(self):
        @dataclass
        class HealthRow:
            profile_id: str
            group_name: str = "US"
            status: str = "degraded"
            consecutive_failures: int = 0
            last_error_code: str = ""
            last_error_message: str = ""

        class FakeHealthStorage:
            def __init__(self):
                self.row = HealthRow("p1")
                self.forced = []

            def record_profile_health(self, profile_id, group_name="", ok=True, error_code="", error_message=""):
                self.row.profile_id = profile_id
                self.row.group_name = group_name
                self.row.consecutive_failures = 0 if ok else self.row.consecutive_failures + 1
                self.row.last_error_code = "" if ok else error_code
                self.row.last_error_message = "" if ok else error_message
                self.row.status = "healthy" if ok else "degraded"
                return self.row

            def force_profile_cooldown(self, profile_id, group_name="", error_code="", error_message=""):
                self.forced.append((profile_id, error_code))
                self.row.status = "cooldown"
                self.row.consecutive_failures = max(self.row.consecutive_failures, 3)
                self.row.last_error_code = error_code
                self.row.last_error_message = error_message
                return self.row

            def list_profile_health(self, limit=10000):
                return [dict(self.row.__dict__)]

        storage = FakeHealthStorage()
        manager = AccountHealthManager(storage, cooldown_after_failures=2)
        first = manager.record_failure({"profile_id": "p1", "group_name": "US"}, "COMMENT_SUBMIT_NOT_CONFIRMED", "not visible")
        second = manager.record_failure({"profile_id": "p1", "group_name": "US"}, "COMMENT_SUBMIT_NOT_CONFIRMED", "not visible")

        self.assertEqual(first["status"], "degraded")
        self.assertEqual(second["status"], "cooldown")
        self.assertEqual(storage.forced, [("p1", "COMMENT_SUBMIT_NOT_CONFIRMED")])

    def test_action_router_executes_safe_repair_steps_without_browser_claims(self):
        router = object.__new__(ActionRouter)
        previous = os.environ.get("REACHOPS_REPAIR_BACKOFF_MAX_SECONDS")
        os.environ["REACHOPS_REPAIR_BACKOFF_MAX_SECONDS"] = "0"
        try:
            results = router._execute_repair_steps(
                {
                    "retry_after_seconds": 5,
                    "executable_steps": [
                        {"step": "capture_page_state_bundle", "required": True},
                        {"step": "dismiss_modal", "max_attempts": 1, "when": True},
                        {"step": "refresh_page", "when": True},
                        {"step": "backoff", "seconds": 5},
                        {"step": "stop_live_submit", "required": True},
                        {"step": "degrade_mode", "to": "collect"},
                    ],
                }
            )
        finally:
            if previous is None:
                os.environ.pop("REACHOPS_REPAIR_BACKOFF_MAX_SECONDS", None)
            else:
                os.environ["REACHOPS_REPAIR_BACKOFF_MAX_SECONDS"] = previous
        by_step = {row["step"]: row for row in results}
        self.assertEqual(by_step["capture_page_state_bundle"]["status"], "already_captured_or_recorded")
        self.assertEqual(by_step["dismiss_modal"]["status"], "requires_browser_executor")
        self.assertEqual(by_step["refresh_page"]["status"], "requires_browser_executor")
        self.assertEqual(by_step["backoff"]["status"], "executed")
        self.assertEqual(by_step["backoff"]["seconds"], 5)
        self.assertEqual(by_step["stop_live_submit"]["status"], "planned_by_router")
        self.assertEqual(by_step["degrade_mode"]["status"], "planned_by_router")
        self.assertTrue(all(row["no_ai_token_used"] for row in results))

    def test_action_router_marks_completed_browser_repair_steps(self):
        router = object.__new__(ActionRouter)
        results = router._execute_repair_steps(
            {
                "executable_steps": [
                    {"step": "dismiss_modal", "max_attempts": 1, "when": True},
                    {"step": "refresh_page", "when": True},
                ],
            },
            completed_browser_steps={"dismiss_modal"},
        )
        by_step = {row["step"]: row for row in results}
        self.assertEqual(by_step["dismiss_modal"]["status"], "already_handled_by_browser_executor")
        self.assertEqual(by_step["refresh_page"]["status"], "requires_browser_executor")
        self.assertTrue(all(row["no_ai_token_used"] for row in results))


if __name__ == "__main__":
    unittest.main()
