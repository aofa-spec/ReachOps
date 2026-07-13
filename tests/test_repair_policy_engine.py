import unittest

from ReachOps.workbench.page_state_detector import PAGE_STATES
from ReachOps.workbench.repair_policy_engine import (
    RepairPolicyEngine,
    build_page_state_repair_coverage,
    repair_decision_summary,
)


class RepairPolicyEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = RepairPolicyEngine()

    def test_login_required_cooldowns_and_switches_profile(self):
        decision = self.engine.decide("LOGIN_REQUIRED", action_type="comment_reply")
        self.assertEqual(decision["action"], "cooldown_profile_and_switch")
        self.assertTrue(decision["repair_decision_id"].startswith("repair_"))
        self.assertEqual(decision["terminal_outcome"], "blocked")
        self.assertTrue(decision["cooldown_profile"])
        self.assertTrue(decision["switch_profile"])
        self.assertTrue(decision["block_execution"])
        self.assertTrue(decision["requires_human_review"])
        self.assertEqual(decision["cooldown_seconds"], 3600)
        self.assertIn("cooldown_profile", [row["step"] for row in decision["executable_steps"]])
        self.assertTrue(decision["no_ai_token_used"])

    def test_profile_start_failed_switches_profile(self):
        decision = self.engine.decide("PROFILE_START_FAILED")
        self.assertTrue(decision["switch_profile"])
        self.assertTrue(decision["cooldown_profile"])

    def test_dom_stalled_retries_same_profile_then_switches(self):
        first = self.engine.decide("DOM_STALLED", attempt=1, max_retries=1)
        second = self.engine.decide("DOM_STALLED", attempt=2, max_retries=1)
        self.assertEqual(first["action"], "retry_same_profile_with_backoff")
        self.assertEqual(first["terminal_outcome"], "retry")
        self.assertTrue(first["retry_same_profile"])
        self.assertEqual(first["retry_after_seconds"], 5)
        self.assertIn("backoff", [row["step"] for row in first["executable_steps"]])
        self.assertEqual(second["action"], "switch_profile_after_retry_exhausted")
        self.assertEqual(second["terminal_outcome"], "switch_profile")
        self.assertTrue(second["switch_profile"])

    def test_repair_decision_id_is_stable_for_same_policy(self):
        first = self.engine.decide("DOM_STALLED", attempt=1, max_retries=1)
        second = self.engine.decide("DOM_STALLED", attempt=1, max_retries=1)
        self.assertEqual(first["repair_decision_id"], second["repair_decision_id"])

    def test_modal_blocked_retries_locally(self):
        decision = self.engine.decide("MODAL_BLOCKED", attempt=1, max_retries=2)
        self.assertTrue(decision["retry_same_profile"])
        steps = {row["step"]: row for row in decision["executable_steps"]}
        self.assertEqual(steps["dismiss_modal"]["max_attempts"], 1)
        self.assertTrue(steps["dismiss_modal"]["when"])
        self.assertTrue(steps["refresh_page"]["when"])
        self.assertIn("刷新页面", " ".join(decision["next_actions"]))

    def test_comment_box_missing_degrades_to_collect(self):
        decision = self.engine.decide("COMMENT_BOX_MISSING", action_type="comment_reply")
        self.assertEqual(decision["action"], "degrade_to_collect")
        self.assertEqual(decision["degrade_to"], "collect")
        self.assertEqual(decision["terminal_outcome"], "degraded")
        self.assertTrue(decision["block_execution"])
        self.assertTrue(decision["requires_human_review"])
        self.assertIn("degrade_mode", [row["step"] for row in decision["executable_steps"]])

    def test_unknown_page_state_blocks_with_error_bundle(self):
        decision = self.engine.decide("UNKNOWN_PAGE_STATE")
        self.assertEqual(decision["action"], "capture_unknown_state_bundle")
        self.assertEqual(decision["terminal_outcome"], "blocked")
        self.assertTrue(decision["block_execution"])
        self.assertTrue(decision["requires_human_review"])
        self.assertIn("record_offline_learning_candidate", [row["step"] for row in decision["executable_steps"]])
        self.assertIn("截图", " ".join(decision["next_actions"]))

    def test_profile_group_not_found_blocks_with_refresh_reselect_steps(self):
        decision = self.engine.decide("profile_group_not_found", action_type="start_precheck")
        self.assertEqual(decision["action"], "refresh_profile_groups_and_reselect")
        self.assertEqual(decision["terminal_outcome"], "blocked")
        self.assertTrue(decision["block_execution"])
        self.assertTrue(decision["requires_human_review"])
        steps = [row["step"] for row in decision["executable_steps"]]
        self.assertIn("refresh_profile_groups", steps)
        self.assertIn("reselect_profile_group", steps)
        self.assertIn("block_execution", steps)
        self.assertIn("刷新 ixBrowser", " ".join(decision["next_actions"]))

    def test_page_state_can_override_generic_failure(self):
        decision = self.engine.decide(
            "OUTREACH_EXECUTION_FAILED",
            page_state={"state": "SUBMIT_BUTTON_MISSING"},
            action_type="comment_reply",
        )
        self.assertEqual(decision["error_code"], "SUBMIT_BUTTON_MISSING")
        self.assertEqual(decision["degrade_to"], "collect")

    def test_all_page_states_have_repair_or_continue_route(self):
        coverage = build_page_state_repair_coverage()
        self.assertEqual(coverage["schema_version"], "reachops.page_state_repair_coverage.v1")
        self.assertEqual(coverage["state_count"], len(PAGE_STATES))
        self.assertTrue(coverage["all_page_states_covered"])
        self.assertEqual(coverage["uncovered_states"], [])
        routes = {row["state"]: row for row in coverage["routes"]}
        self.assertEqual(routes["READY"]["action"], "continue_execution")
        self.assertEqual(routes["LOGIN_REQUIRED"]["action"], "cooldown_profile_and_switch")
        self.assertEqual(routes["DOM_STALLED"]["action"], "retry_same_profile_with_backoff")
        self.assertEqual(routes["COMMENT_BOX_MISSING"]["action"], "degrade_to_collect")
        self.assertEqual(routes["UNKNOWN_PAGE_STATE"]["action"], "capture_unknown_state_bundle")
        self.assertTrue(all(row["no_ai_token_used"] for row in coverage["routes"]))

    def test_summary_is_operator_readable(self):
        decision = self.engine.decide("PAGE_TIMEOUT")
        self.assertIn("outcome=retry", repair_decision_summary(decision))
        self.assertIn("retry=true", repair_decision_summary(decision))


if __name__ == "__main__":
    unittest.main()
