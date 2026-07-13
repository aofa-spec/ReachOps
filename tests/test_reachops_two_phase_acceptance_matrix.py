import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.reachops_two_phase_acceptance_matrix import build_matrix, main


def local_ready_goal_payload():
    return {
        "final_delivery_ready": False,
        "delivery_boundary": {
            "local_mvp_scope_ready": True,
            "overall_final_delivery_scope_ready": False,
        },
        "deliverable_index": {
            "windows_final_package": {"ready": False},
            "authorized_live_submit": {"ready": False},
        },
        "goal_pending_external_validation": ["授权允许时能真实执行", "真实 TikTok 平台提交"],
        "final_delivery_blockers": [
            {
                "scope": "external_authorized_execution",
                "required_evidence": ["comment_visible_confirmed=true"],
            }
        ],
        "local_mvp_evidence": {
            "latest_batch": {"id": "gb_test", "profile_group": "United States"},
            "groups": {"group_count": 15, "known_group_count": 15, "all_group_counts_known": True, "profile_count": 2910},
            "start_contract_evidence_complete": True,
            "start_contract_evidence": {
                "target_planned": True,
                "campaign_started": True,
                "profile_preflight_checked": True,
                "collection_done": True,
                "action_terminal_or_no_submit_reason": True,
            },
            "operation_counts": {"candidates": 2, "actions": 0},
            "no_action_reason": {"code": "low_intent_candidates", "no_submit": True},
            "no_action_reason_present_when_no_actions": True,
        },
        "sections": {
            "mac_loop_acceptance": {
                "payload": {
                    "web_ui": {
                        "base_url": "http://127.0.0.1:8769",
                        "ixbrowser_ready": True,
                        "run_result_status": "completed",
                    },
                    "checks": {
                        "web_ui_reachable": True,
                        "ixbrowser_api_ready": True,
                        "groups_available": True,
                        "group_counts_known": True,
                        "all_group_counts_known": True,
                        "groups_fresh": True,
                        "acceptance_pass": True,
                        "no_headless_timeout_in_current_result": True,
                    },
                    "acceptance": {
                        "checks": {
                            "target_planned": True,
                            "product_auto_detected": True,
                            "profile_preflight_fresh": True,
                            "profile_available_count": 2,
                            "collection_done": True,
                        }
                    },
                }
            },
            "client_delivery": {"payload": {"status": "passed", "readiness": "pass", "failed_checks": []}},
            "repository_cleanliness": {"payload": {"status": "passed", "passed": True, "forbidden_count": 0}},
            "delivery_package": {
                "payload": {
                    "status": "failed",
                    "final_delivery_ready": False,
                    "missing_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                    "failures": ["exe_missing"],
                }
            },
            "final_gate": {
                "payload": {
                    "status": "not_ready",
                    "final_delivery_ready": False,
                    "failed_checks": ["goal_status:passed", "delivery_package:passed"],
                }
            },
        },
    }


class ReachOpsTwoPhaseAcceptanceMatrixTests(unittest.TestCase):
    def test_local_mvp_ready_does_not_equal_final_delivery_ready(self):
        matrix = build_matrix(local_ready_goal_payload())

        self.assertEqual(matrix["status"], "local_mvp_accepted_final_pending")
        self.assertTrue(matrix["local_mvp_ready"])
        self.assertFalse(matrix["final_delivery_ready"])
        self.assertIn("windows_final_artifacts", matrix["failed_items"])
        self.assertIn("authorized_live_submit", matrix["failed_items"])
        passed_ids = {row["id"] for row in matrix["rows"] if row["passed"]}
        self.assertIn("target_type_and_source_planning", passed_ids)
        self.assertIn("headless_runner_started", passed_ids)
        self.assertIn("profile_preflight_checked", passed_ids)
        self.assertIn("collection_completed", passed_ids)
        self.assertIn("candidate_scoring_completed", passed_ids)
        self.assertIn("outreach_terminal_or_skip_reason", passed_ids)

    def test_missing_no_action_reason_blocks_local_mvp(self):
        payload = local_ready_goal_payload()
        payload["local_mvp_evidence"]["no_action_reason"] = {}
        payload["local_mvp_evidence"]["no_action_reason_present_when_no_actions"] = False

        matrix = build_matrix(payload)

        self.assertEqual(matrix["status"], "not_ready")
        self.assertFalse(matrix["local_mvp_ready"])
        self.assertIn("outreach_terminal_or_skip_reason", matrix["failed_items"])

    def test_missing_profile_preflight_blocks_local_mvp(self):
        payload = local_ready_goal_payload()
        payload["local_mvp_evidence"]["start_contract_evidence"]["profile_preflight_checked"] = False
        payload["sections"]["mac_loop_acceptance"]["payload"]["acceptance"]["checks"]["profile_preflight_fresh"] = False

        matrix = build_matrix(payload)

        self.assertEqual(matrix["status"], "not_ready")
        self.assertFalse(matrix["local_mvp_ready"])
        self.assertIn("profile_preflight_checked", matrix["failed_items"])

    def test_incomplete_group_counts_blocks_local_mvp(self):
        payload = local_ready_goal_payload()
        payload["local_mvp_evidence"]["groups"]["known_group_count"] = 14
        payload["local_mvp_evidence"]["groups"]["all_group_counts_known"] = False
        payload["sections"]["mac_loop_acceptance"]["payload"]["checks"]["all_group_counts_known"] = False

        matrix = build_matrix(payload)

        self.assertEqual(matrix["status"], "not_ready")
        self.assertFalse(matrix["local_mvp_ready"])
        self.assertIn("fresh_group_counts", matrix["failed_items"])

    def test_cli_default_gates_local_mvp_but_require_final_gates_final_delivery(self):
        payload = local_ready_goal_payload()
        with patch("tools.reachops_two_phase_acceptance_matrix.latest_or_refresh", return_value=payload):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--json"]), 0)
                self.assertEqual(main(["--require-final", "--json"]), 1)


if __name__ == "__main__":
    unittest.main()
