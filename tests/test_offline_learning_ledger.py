# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ReachOps.workbench.offline_learning_ledger import (
    OfflineLearningLedger,
    build_policy_candidates_from_records,
    review_policy_candidate,
    summarize_offline_learning,
)


class OfflineLearningLedgerTests(unittest.TestCase):
    def test_unknown_state_records_signature_and_occurrence_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unknown_states.json"
            ledger = OfflineLearningLedger(path)
            page_state = {
                "schema_version": "reachops.page_state.v1",
                "state": "UNKNOWN_PAGE_STATE",
                "current_url": "https://www.tiktok.com/@creator/video/123?x=1",
                "title": "Verify your account",
                "body_text_sample": "Please verify to continue",
                "body_text_sha256": "abc",
                "signals": ["page_or_network_load_failure"],
                "selector_counts": {"comment_box_count": 0},
            }
            first = ledger.record_unknown_state(
                page_state=page_state,
                error_code="UNKNOWN_PAGE_STATE",
                action_type="comment_reply",
                evidence_path="/tmp/evidence.png",
            )
            second = ledger.record_unknown_state(
                page_state=page_state,
                error_code="UNKNOWN_PAGE_STATE",
                action_type="comment_reply",
                evidence_path="/tmp/evidence-2.png",
            )
            self.assertEqual(first["signature"], second["signature"])
            self.assertEqual(second["occurrence_count"], 2)
            self.assertEqual(second["suggested_policy"]["candidate_state"], "CAPTCHA_DETECTED")
            summary = summarize_offline_learning(path)
            self.assertEqual(summary["schema_version"], "reachops.offline_learning.v1")
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["policy_candidates"]["schema_version"], "reachops.offline_policy_candidates.v1")
            self.assertEqual(summary["policy_candidates"]["candidate_count"], 1)
            self.assertFalse(summary["policy_candidates"]["candidates"][0]["auto_apply"])
            self.assertTrue(summary["policy_candidates"]["candidates"][0]["requires_human_review"])
            self.assertTrue(summary["no_ai_token_used"])

    def test_known_non_unknown_state_is_not_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unknown_states.json"
            ledger = OfflineLearningLedger(path)
            result = ledger.record_unknown_state(
                page_state={"state": "READY"},
                error_code="",
                action_type="comment_reply",
                evidence_path="/tmp/evidence.png",
            )
            self.assertEqual(result, {})

    def test_policy_candidates_require_repeated_unknowns(self) -> None:
        candidates = build_policy_candidates_from_records(
            [
                {
                    "signature": "uls_one",
                    "state": "UNKNOWN_PAGE_STATE",
                    "occurrence_count": 1,
                    "suggested_policy": {
                        "candidate_state": "LOGIN_REQUIRED",
                        "candidate_action": "cooldown_profile_and_switch",
                        "confidence": "medium",
                    },
                    "evidence_paths": ["/tmp/one.png"],
                },
                {
                    "signature": "uls_two",
                    "state": "UNKNOWN_PAGE_STATE",
                    "occurrence_count": 3,
                    "suggested_policy": {
                        "candidate_state": "LOGIN_REQUIRED",
                        "candidate_action": "cooldown_profile_and_switch",
                        "confidence": "medium",
                    },
                    "evidence_paths": ["/tmp/two.png"],
                },
            ]
        )
        self.assertEqual(candidates["candidate_count"], 1)
        self.assertEqual(candidates["candidates"][0]["occurrence_count"], 3)
        self.assertEqual(candidates["candidates"][0]["candidate_state"], "LOGIN_REQUIRED")
        self.assertFalse(candidates["candidates"][0]["auto_apply"])

    def test_operator_review_records_candidate_without_auto_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unknown_states.json"
            ledger = OfflineLearningLedger(path)
            page_state = {
                "state": "UNKNOWN_PAGE_STATE",
                "title": "Please log in",
                "body_text_sample": "Log in to continue",
                "body_text_sha256": "login-hash",
                "selector_counts": {"comment_box_count": 0},
            }
            ledger.record_unknown_state(page_state=page_state, error_code="UNKNOWN_PAGE_STATE", action_type="comment_reply")
            ledger.record_unknown_state(page_state=page_state, error_code="UNKNOWN_PAGE_STATE", action_type="comment_reply")

            result = review_policy_candidate(
                path,
                candidate_state="LOGIN_REQUIRED",
                candidate_action="cooldown_profile_and_switch",
                decision="approved",
                reviewer="ops",
                note="两次证据均为登录拦截。",
            )
            self.assertEqual(result["status"], "review_recorded")
            self.assertEqual(result["review"]["decision"], "approved")
            self.assertFalse(result["review"]["auto_apply"])
            self.assertEqual(result["review"]["runtime_effect"], "review_recorded_only")

            summary = summarize_offline_learning(path)
            self.assertEqual(summary["policy_review_summary"]["approved_count"], 1)
            self.assertEqual(
                summary["policy_release_proposal"]["schema_version"],
                "reachops.offline_policy_release_proposal.v1",
            )
            self.assertEqual(summary["policy_release_proposal"]["approved_count"], 1)
            self.assertEqual(summary["policy_release_proposal"]["ready_for_release_count"], 1)
            self.assertEqual(summary["policy_release_proposal"]["runtime_auto_apply_count"], 0)
            self.assertFalse(summary["policy_release_proposal"]["runtime_auto_apply"])
            self.assertEqual(summary["policy_release_proposal"]["release_gate"], "code_or_policy_release_required")
            proposal = summary["policy_release_proposal"]["proposals"][0]
            self.assertEqual(proposal["candidate_state"], "LOGIN_REQUIRED")
            self.assertEqual(proposal["candidate_action"], "cooldown_profile_and_switch")
            self.assertIn("PageStateDetector", proposal["target_components"])
            self.assertIn("RepairPolicyEngine", proposal["target_components"])
            self.assertIn("RiskGate", proposal["target_components"])
            self.assertFalse(proposal["runtime_auto_apply"])
            self.assertEqual(result["policy_release_proposal"]["ready_for_release_count"], 1)
            candidate = summary["policy_candidates"]["candidates"][0]
            self.assertEqual(candidate["review_status"], "approved")
            self.assertTrue(candidate["approved_for_rule_upgrade"])
            self.assertFalse(candidate["auto_apply"])


if __name__ == "__main__":
    unittest.main()
