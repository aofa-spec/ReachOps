import tempfile
import unittest
from pathlib import Path

from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import GrowthStorage


class PublicReplyLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.storage = GrowthStorage(str(Path(self.tmp.name) / "runtime" / "growth.sqlite3"))

    def _lead_action(self):
        lead_id, created = self.storage.upsert_operation_lead(
            "candidate-reply-1",
            "comment_intent",
            "high",
            95,
            "keyword match is only a candidate signal",
            "https://www.tiktok.com/@creator/video/123",
        )
        self.assertTrue(created)
        action = ActionQueueItem(
            id="action-reply-1",
            lead_id=lead_id,
            action_type="comment_reply",
            target_username="buyer_reply",
            target_url="https://www.tiktok.com/@creator/video/123",
            suggested_text="Reply only after approval.",
            status="approved",
        )
        action_id, action_created = self.storage.upsert_action_queue_item(action)
        self.assertTrue(action_created)
        return lead_id, action_id

    def _lead(self, lead_id: str) -> dict:
        return next(row for row in self.storage.list_operation_leads(limit=50) if row["id"] == lead_id)

    def test_keyword_candidate_does_not_create_qualified_lead_without_reply(self):
        lead_id, _action_id = self._lead_action()

        lead = self._lead(lead_id)

        self.assertNotEqual(lead["lifecycle_stage"], "qualified")
        self.assertEqual(self.storage.count_table("reply_observations"), 0)
        self.assertEqual(self.storage.count_table("lead_qualification_decisions"), 0)

    def test_public_reply_observation_links_action_and_lead_idempotently(self):
        lead_id, action_id = self._lead_action()

        first_id, first_created = self.storage.record_reply_observation(
            action_id,
            reply_author="buyer_reply",
            reply_text="I still need the product link.",
            reply_url="https://www.tiktok.com/@creator/video/123?reply=1",
            evidence_path="/tmp/reachops/redacted/reply-observed.json",
            raw_payload={"fixture": "redacted"},
        )
        duplicate_id, duplicate_created = self.storage.record_reply_observation(
            action_id,
            reply_author="@buyer_reply",
            reply_text="I still need the product link.",
            reply_url="https://www.tiktok.com/@creator/video/123?reply=1",
        )

        self.assertTrue(first_created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first_id, duplicate_id)
        replies = self.storage.list_reply_observations(lead_id=lead_id)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["action_id"], action_id)
        self.assertEqual(replies[0]["lead_id"], lead_id)
        self.assertEqual(replies[0]["reply_author"], "buyer_reply")
        self.assertEqual(self._lead(lead_id)["lifecycle_stage"], "reply_received")

    def test_contacted_requires_verified_live_execution_before_public_reply(self):
        lead_id, action_id = self._lead_action()

        self.storage.update_action_status(action_id, "completed", note="preflight completed")
        self.assertNotEqual(self._lead(lead_id)["lifecycle_stage"], "contacted")

        self.storage.create_outreach_execution(
            action_id,
            "comment_reply",
            "buyer_reply",
            status="submitted_unverified",
            execution_mode="live",
            submission_state="submitted_unverified",
            verification_state="pending",
            evidence_verified=False,
        )
        self.storage.update_action_status(action_id, "success", note="unverified live submission")
        self.assertNotEqual(self._lead(lead_id)["lifecycle_stage"], "contacted")

        self.storage.create_outreach_execution(
            action_id,
            "comment_reply",
            "buyer_reply",
            status="success",
            execution_mode="live",
            submission_state="verified_success",
            verification_state="verified",
            evidence_verified=True,
        )
        self.storage.update_action_status(action_id, "success", note="verified live success")
        self.assertEqual(self._lead(lead_id)["lifecycle_stage"], "contacted")

    def test_qualified_lead_requires_linked_reply_confirming_need(self):
        lead_id, action_id = self._lead_action()
        reply_id, _created = self.storage.record_reply_observation(
            action_id,
            "buyer_reply",
            "Can you send the exact link? I want to buy it.",
            reply_url="https://www.tiktok.com/@creator/video/123?reply=2",
        )

        not_qualified_id, not_qualified_created = self.storage.record_lead_qualification_decision(
            reply_id,
            qualified=False,
            reason="reply is not yet a confirmed offer need",
            decided_by="operator",
        )
        self.assertTrue(not_qualified_created)
        self.assertTrue(not_qualified_id.startswith("lqd_"))
        self.assertEqual(self._lead(lead_id)["lifecycle_stage"], "reply_received")

        with self.assertRaisesRegex(ValueError, "reply-confirmed need"):
            self.storage.record_lead_qualification_decision(reply_id, qualified=True, reason="")

        qualified_id, qualified_created = self.storage.record_lead_qualification_decision(
            reply_id,
            qualified=True,
            reason="reply asks for exact product link and states purchase intent",
            decided_by="operator",
        )
        duplicate_id, duplicate_created = self.storage.record_lead_qualification_decision(
            reply_id,
            qualified=True,
            reason="reply asks for exact product link and states purchase intent",
            decided_by="operator",
        )

        self.assertTrue(qualified_created)
        self.assertFalse(duplicate_created)
        self.assertEqual(qualified_id, duplicate_id)
        self.assertEqual(self._lead(lead_id)["lifecycle_stage"], "qualified")
        decisions = self.storage.list_lead_qualification_decisions(lead_id=lead_id)
        self.assertEqual([int(row["qualified"]) for row in decisions], [0, 1])

    def test_qualification_decision_rejects_missing_reply_observation(self):
        self._lead_action()

        with self.assertRaisesRegex(ValueError, "reply_observation_id does not exist"):
            self.storage.record_lead_qualification_decision(
                "ro_missing",
                qualified=True,
                reason="should not qualify without linked public reply",
            )


if __name__ == "__main__":
    unittest.main()
