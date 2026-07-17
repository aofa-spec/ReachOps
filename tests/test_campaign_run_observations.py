import tempfile
import unittest
from pathlib import Path

from ReachOps.intelligence.schemas import ActionQueueItem, CandidateUser
from ReachOps.intelligence.storage import GrowthStorage


class CampaignRunObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "growth.sqlite3"
        self.storage = GrowthStorage(str(self.db_path))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_collection_batches_create_unique_campaign_runs_idempotently(self):
        campaign = self.storage.create_campaign("keyword", "anti aging serum")

        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)

        self.assertTrue(first.run_id.startswith("run_"))
        self.assertTrue(second.run_id.startswith("run_"))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(self.storage.run_id_for_batch(first.id), first.run_id)
        self.assertEqual(self.storage.run_id_for_batch(second.id), second.run_id)
        self.assertEqual(self.storage.count_table("campaign_runs"), 2)

        reopened = GrowthStorage(str(self.db_path))
        self.assertEqual(reopened.count_table("campaign_runs"), 2)
        self.assertEqual(reopened.run_id_for_batch(first.id), first.run_id)

    def test_observations_decisions_actions_and_evidence_are_run_scoped(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="CA", campaign_id=campaign.id)

        source_first = self.storage.record_source_observation(
            first.run_id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            observation_key="planned",
            payload={"priority": 1},
        )
        duplicate_first = self.storage.record_source_observation(
            first.run_id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            observation_key="planned",
            payload={"priority": 99},
        )
        source_second = self.storage.record_source_observation(
            second.run_id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            observation_key="planned",
            payload={"priority": 2},
        )

        self.assertEqual(source_first, duplicate_first)
        self.assertNotEqual(source_first, source_second)

        self.storage.set_active_collection_batch(first.id)
        candidate, created = self.storage.upsert_candidate(
            CandidateUser(
                id="candidate-1",
                content_id="content-1",
                username="same_user",
                profile_url="https://example.test/@same_user",
                comment_text="where can I buy this",
                qualify_score=80,
                intent_tags=["buy"],
            )
        )
        self.assertTrue(created)

        self.storage.set_active_collection_batch(second.id)
        same_candidate, created_again = self.storage.upsert_candidate(
            CandidateUser(
                id="candidate-2",
                content_id="content-1",
                username="same_user",
                profile_url="https://example.test/@same_user",
                comment_text="where can I buy this",
                qualify_score=90,
                intent_tags=["buy"],
            )
        )
        self.assertFalse(created_again)
        self.assertEqual(candidate.id, same_candidate.id)

        comment_first = self.storage.record_comment_observation(
            first.run_id,
            content_id="content-1",
            candidate_user_id=candidate.id,
            username="same_user",
            comment_text="where can I buy this",
            observation_key="comment_seen",
        )
        comment_second = self.storage.record_comment_observation(
            second.run_id,
            content_id="content-1",
            candidate_user_id=candidate.id,
            username="same_user",
            comment_text="where can I buy this",
            observation_key="comment_seen",
        )
        self.assertNotEqual(comment_first, comment_second)

        candidate_first = self.storage.record_candidate_observation(
            first.run_id,
            candidate_user_id=candidate.id,
            username="same_user",
            score=80,
            intent_tags=["buy"],
            observation_key="scored",
            comment_observation_id=comment_first,
        )
        candidate_second = self.storage.record_candidate_observation(
            second.run_id,
            candidate_user_id=candidate.id,
            username="same_user",
            score=90,
            intent_tags=["buy"],
            observation_key="scored",
            comment_observation_id=comment_second,
        )
        self.assertNotEqual(candidate_first, candidate_second)

        first_decision = self.storage.record_lead_decision(
            first.run_id,
            candidate_user_id=candidate.id,
            decision_type="high_intent",
            score=80,
            reason="first run score",
        )
        second_decision = self.storage.record_lead_decision(
            second.run_id,
            candidate_user_id=candidate.id,
            decision_type="high_intent",
            score=90,
            reason="second run score",
        )
        self.assertNotEqual(first_decision, second_decision)

        self.storage.set_active_collection_batch(first.id)
        lead_id, _ = self.storage.upsert_operation_lead(candidate.id, "high_intent", "high", 80, "first run")
        action_id, _ = self.storage.upsert_action_queue_item(
            ActionQueueItem(
                id="action-1",
                lead_id=lead_id,
                action_type="comment_reply",
                target_username="same_user",
                target_url="https://example.test/video/1",
            )
        )
        execution_id = self.storage.create_outreach_execution(
            action_id,
            "comment_reply",
            "same_user",
            status="success",
            execution_mode="preflight",
            submission_state="not_attempted",
        )

        action = next(row for row in self.storage.list_action_queue(limit=10) if row["id"] == action_id)
        execution = next(row for row in self.storage.list_outreach_executions(limit=10) if row["id"] == execution_id)
        self.assertEqual(action["run_id"], first.run_id)
        self.assertEqual(execution["run_id"], first.run_id)
        self.assertEqual(len(self.storage.list_action_queue(limit=10, run_id=first.run_id)), 1)
        self.assertEqual(len(self.storage.list_action_queue(limit=10, run_id=second.run_id)), 0)
        self.assertEqual(len(self.storage.list_outreach_executions(limit=10, run_id=first.run_id)), 1)
        self.assertEqual(len(self.storage.list_outreach_executions(limit=10, run_id=second.run_id)), 0)
        self.assertEqual(self.storage.outreach_execution_status_counts(run_id=first.run_id), {"success": 1})
        self.assertEqual(self.storage.outreach_execution_status_counts(run_id=second.run_id), {})

        first_trace = self.storage.list_observations_for_run(first.run_id)
        second_trace = self.storage.list_observations_for_run(second.run_id)
        self.assertEqual(len(first_trace["source_observations"]), 1)
        self.assertEqual(len(second_trace["source_observations"]), 1)
        self.assertEqual(len(first_trace["lead_decisions"]), 1)
        self.assertEqual(len(second_trace["lead_decisions"]), 1)
        self.assertEqual(first_trace["lead_decisions"][0]["batch_id"], first.id)
        self.assertEqual(second_trace["lead_decisions"][0]["batch_id"], second.id)


if __name__ == "__main__":
    unittest.main()
