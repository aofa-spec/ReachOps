import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ReachOps.intelligence.candidate_user_scorer import CandidateUserScorer
from ReachOps.intelligence.schemas import ActionQueueItem, CandidateUser, DiscoveredContent
from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.workbench.workflow_service import GrowthWorkflowService


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

    def test_campaign_isolation_for_runs_and_observations(self):
        first_campaign = self.storage.create_campaign("keyword", "serum")
        second_campaign = self.storage.create_campaign("keyword", "supplement")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=first_campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="US", campaign_id=second_campaign.id)

        first_source = self.storage.record_source_observation(
            first.run_id,
            source_id="shared-source",
            source_type="keyword",
            source_value="shared",
            observation_key="planned",
            payload={"campaign": "first"},
        )
        second_source = self.storage.record_source_observation(
            second.run_id,
            source_id="shared-source",
            source_type="keyword",
            source_value="shared",
            observation_key="planned",
            payload={"campaign": "second"},
        )

        self.assertNotEqual(first_source, second_source)
        self.assertEqual(len(self.storage.list_campaign_runs(campaign_id=first_campaign.id)), 1)
        self.assertEqual(len(self.storage.list_campaign_runs(campaign_id=second_campaign.id)), 1)
        self.assertEqual(self.storage.list_observations_for_run(first.run_id)["source_observations"][0]["campaign_id"], first_campaign.id)
        self.assertEqual(self.storage.list_observations_for_run(second.run_id)["source_observations"][0]["campaign_id"], second_campaign.id)

    def test_run_isolation_for_observations_decisions_actions_and_evidence(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="CA", campaign_id=campaign.id)

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

        content_first = self.storage.record_content_observation(
            first.run_id,
            content_id="content-1",
            observation_key="content_seen",
            payload={"video_url": "https://example.test/video/1"},
        )
        content_second = self.storage.record_content_observation(
            second.run_id,
            content_id="content-1",
            observation_key="content_seen",
            payload={"video_url": "https://example.test/video/1"},
        )
        self.assertNotEqual(content_first, content_second)

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
        self.storage.log_error("PRECHECK_NOTE", "redacted fixture error", source_id="source-1")
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
            evidence_path="/tmp/reachops/redacted/evidence.png",
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
        self.assertEqual(self.storage.outreach_execution_truth_counts(run_id=first.run_id)["preflight_passed"], 1)
        self.assertEqual(self.storage.outreach_execution_truth_counts(run_id=second.run_id)["preflight_passed"], 0)

        first_trace = self.storage.list_observations_for_run(first.run_id)
        second_trace = self.storage.list_observations_for_run(second.run_id)
        self.assertEqual(len(first_trace["content_observations"]), 1)
        self.assertEqual(len(second_trace["content_observations"]), 1)
        self.assertEqual(len(first_trace["comment_observations"]), 1)
        self.assertEqual(len(second_trace["comment_observations"]), 1)
        self.assertEqual(len(first_trace["candidate_observations"]), 1)
        self.assertEqual(len(second_trace["candidate_observations"]), 1)
        self.assertEqual(len(first_trace["lead_decisions"]), 2)
        self.assertEqual(len(second_trace["lead_decisions"]), 1)
        self.assertEqual(len(first_trace["outreach_executions"]), 1)
        self.assertEqual(len(second_trace["outreach_executions"]), 0)
        self.assertEqual(len(first_trace["growth_errors"]), 1)
        self.assertEqual(len(second_trace["growth_errors"]), 0)
        self.assertEqual(first_trace["lead_decisions"][0]["batch_id"], first.id)
        self.assertEqual(second_trace["lead_decisions"][0]["batch_id"], second.id)
        self.assertEqual(first_trace["outreach_executions"][0]["evidence_path"], "/tmp/reachops/redacted/evidence.png")

    def test_workflow_storage_writes_run_observation_ledger_automatically(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        run = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        self.storage.set_active_collection_batch(run.id)

        task = self.storage.create_collection_task(
            run.id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            profile_id="profile-1",
        )
        content, content_created = self.storage.upsert_content(
            DiscoveredContent(
                id="content-1",
                creator_id="creator-1",
                video_id="video-1",
                video_url="https://example.test/video/1",
                caption="demo",
                collector_level="fixture",
            )
        )
        candidate, candidate_created = self.storage.upsert_candidate(
            CandidateUser(
                id="candidate-1",
                content_id=content.id,
                username="buyer",
                profile_url="https://example.test/@buyer",
                comment_text="where can I buy this",
                qualify_score=81,
                intent_tags=["buy"],
                collector_level="fixture",
            )
        )
        lead_id, lead_created = self.storage.upsert_operation_lead(
            candidate.id,
            "high_intent",
            "high",
            81,
            "buying question",
            source_path=content.video_url,
        )
        same_lead_id, same_lead_created = self.storage.upsert_operation_lead(
            candidate.id,
            "high_intent",
            "high",
            81,
            "buying question",
            source_path=content.video_url,
        )
        updated_lead_id, updated_lead_created = self.storage.upsert_operation_lead(
            candidate.id,
            "high_intent",
            "high",
            92,
            "strong buying question",
            source_path=content.video_url,
        )

        self.assertEqual(task.run_id, run.run_id)
        self.assertTrue(content_created)
        self.assertTrue(candidate_created)
        self.assertTrue(lead_created)
        self.assertEqual(lead_id, same_lead_id)
        self.assertEqual(lead_id, updated_lead_id)
        self.assertFalse(same_lead_created)
        self.assertFalse(updated_lead_created)

        trace = self.storage.list_observations_for_run(run.run_id)
        self.assertEqual(len(trace["source_observations"]), 1)
        self.assertEqual(trace["source_observations"][0]["source_id"], "source-1")
        self.assertEqual(trace["source_observations"][0]["observation_key"], "collection_task_planned")
        source_payload = json.loads(trace["source_observations"][0]["payload_json"])
        self.assertEqual(source_payload["task_id"], task.id)
        self.assertEqual(source_payload["profile_id"], "profile-1")
        self.assertEqual(len(trace["content_observations"]), 1)
        self.assertEqual(trace["content_observations"][0]["content_id"], "content-1")
        self.assertEqual(len(trace["comment_observations"]), 1)
        self.assertEqual(trace["comment_observations"][0]["comment_text"], "where can I buy this")
        self.assertEqual(len(trace["candidate_observations"]), 1)
        self.assertEqual(trace["candidate_observations"][0]["score"], 81)
        self.assertEqual([row["decision_version"] for row in trace["lead_decisions"]], [1, 2])
        self.assertEqual([row["score"] for row in trace["lead_decisions"]], [81, 92])

        self.storage.create_collection_task(
            run.id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            profile_id="profile-1",
        )
        self.storage.upsert_content(
            DiscoveredContent(
                id="content-2",
                creator_id="creator-1",
                video_id="video-1",
                video_url="https://example.test/video/1",
                caption="demo",
            )
        )
        self.storage.upsert_candidate(
            CandidateUser(
                id="candidate-2",
                content_id=content.id,
                username="buyer",
                profile_url="https://example.test/@buyer",
                comment_text="where can I buy this",
                qualify_score=81,
                intent_tags=["buy"],
            )
        )
        repeated_trace = self.storage.list_observations_for_run(run.run_id)
        self.assertEqual(len(repeated_trace["source_observations"]), 1)
        self.assertEqual(len(repeated_trace["content_observations"]), 1)
        self.assertEqual(len(repeated_trace["comment_observations"]), 1)
        self.assertEqual(len(repeated_trace["candidate_observations"]), 1)
        self.assertEqual(len(repeated_trace["lead_decisions"]), 2)

    def test_scoring_workflow_records_run_scoped_candidate_observations(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="CA", campaign_id=campaign.id)

        def add_candidate(batch, suffix):
            self.storage.set_active_collection_batch(batch.id)
            content, _created = self.storage.upsert_content(
                DiscoveredContent(
                    id=f"content-{suffix}",
                    creator_id=f"creator-{suffix}",
                    video_id=f"video-{suffix}",
                    video_url=f"https://example.test/video/{suffix}",
                    caption="where to buy demo",
                    views=20000,
                    comments=200,
                )
            )
            candidate, _created = self.storage.upsert_candidate(
                CandidateUser(
                    id=f"candidate-{suffix}",
                    content_id=content.id,
                    username=f"buyer_{suffix}",
                    profile_url=f"https://example.test/@buyer_{suffix}",
                    comment_text=f"where can I buy {suffix}",
                    qualify_score=0,
                    intent_tags=[],
                )
            )
            return candidate

        first_candidate = add_candidate(first, "first")
        second_candidate = add_candidate(second, "second")
        scorer = CandidateUserScorer(self.storage)

        self.storage.set_active_collection_batch(first.id)
        first_updated = scorer.score_all(SimpleNamespace(active_batch_id=first.id))
        scorer.score_all(SimpleNamespace(active_batch_id=first.id))

        first_trace = self.storage.list_observations_for_run(first.run_id)
        second_trace_before = self.storage.list_observations_for_run(second.run_id)
        first_score_updates = [
            row for row in first_trace["candidate_observations"] if row["observation_key"].startswith("score_updated:")
        ]
        second_score_updates_before = [
            row for row in second_trace_before["candidate_observations"] if row["observation_key"].startswith("score_updated:")
        ]

        self.assertEqual(first_updated, 1)
        self.assertEqual([row["candidate_user_id"] for row in first_score_updates], [first_candidate.id])
        self.assertEqual(second_score_updates_before, [])

        self.storage.set_active_collection_batch(second.id)
        second_updated = scorer.score_all(SimpleNamespace(active_batch_id=second.id))

        second_trace = self.storage.list_observations_for_run(second.run_id)
        second_score_updates = [
            row for row in second_trace["candidate_observations"] if row["observation_key"].startswith("score_updated:")
        ]

        self.assertEqual(second_updated, 1)
        self.assertEqual([row["candidate_user_id"] for row in second_score_updates], [second_candidate.id])
        self.assertEqual(len(first_score_updates), 1)
        self.assertEqual(len(second_score_updates), 1)

    def test_campaign_export_prefers_run_scoped_reads(self):
        class ExportService:
            def __init__(self, storage, report_dir):
                self.storage = storage
                self.report_dir = str(report_dir)

            def build_campaign_strategy(self, campaign_id):
                return {"campaign_id": campaign_id, "generator": "test"}

        campaign = self.storage.create_campaign("keyword", "serum")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="CA", campaign_id=campaign.id)

        def populate_run(batch, suffix, score):
            self.storage.set_active_collection_batch(batch.id)
            content, _created = self.storage.upsert_content(
                DiscoveredContent(
                    id=f"content-{suffix}",
                    creator_id=f"creator-{suffix}",
                    video_id=f"video-{suffix}",
                    video_url=f"https://example.test/video/{suffix}",
                )
            )
            candidate, _created = self.storage.upsert_candidate(
                CandidateUser(
                    id=f"candidate-{suffix}",
                    content_id=content.id,
                    username=f"buyer_{suffix}",
                    profile_url=f"https://example.test/@buyer_{suffix}",
                    comment_text=f"where can I buy {suffix}",
                    qualify_score=score,
                    intent_tags=["buy"],
                )
            )
            lead_id, _created = self.storage.upsert_operation_lead(
                candidate.id,
                "high_intent",
                "high",
                score,
                f"{suffix} buying signal",
                source_path=content.video_url,
            )
            action_id, _created = self.storage.upsert_action_queue_item(
                ActionQueueItem(
                    id=f"action-{suffix}",
                    lead_id=lead_id,
                    action_type="comment_reply",
                    target_username=f"buyer_{suffix}",
                    target_url=content.video_url,
                )
            )
            execution_id = self.storage.create_outreach_execution(
                action_id,
                "comment_reply",
                f"buyer_{suffix}",
                status="success",
                profile_id=f"profile-{suffix}",
                execution_mode="preflight",
                submission_state="not_attempted",
            )
            return {"content": content.id, "candidate": candidate.id, "lead": lead_id, "action": action_id, "execution": execution_id}

        first_ids = populate_run(first, "first", 81)
        second_ids = populate_run(second, "second", 91)

        workflow = GrowthWorkflowService(ExportService(self.storage, Path(self.tmpdir.name) / "reports"))
        first_artifacts = workflow.export_campaign_artifacts(campaign_id=campaign.id, batch_id=first.id)
        second_artifacts = workflow.export_campaign_artifacts(campaign_id=campaign.id, run_id=second.run_id)

        with open(first_artifacts["json_path"], "r", encoding="utf-8") as fh:
            first_payload = json.load(fh)
        with open(second_artifacts["json_path"], "r", encoding="utf-8") as fh:
            second_payload = json.load(fh)

        self.assertEqual(first_artifacts["run_id"], first.run_id)
        self.assertEqual(second_artifacts["run_id"], second.run_id)
        self.assertEqual(first_payload["export_scope"]["run_id"], first.run_id)
        self.assertEqual(second_payload["export_scope"]["run_id"], second.run_id)
        self.assertEqual([row["id"] for row in first_payload["candidate_users"]], [first_ids["candidate"]])
        self.assertEqual([row["id"] for row in second_payload["candidate_users"]], [second_ids["candidate"]])
        self.assertEqual([row["id"] for row in first_payload["action_queue"]], [first_ids["action"]])
        self.assertEqual([row["id"] for row in second_payload["action_queue"]], [second_ids["action"]])
        self.assertEqual([row["id"] for row in first_payload["outreach_executions"]], [first_ids["execution"]])
        self.assertEqual([row["id"] for row in second_payload["outreach_executions"]], [second_ids["execution"]])
        self.assertEqual(first_payload["execution_summary"]["total"], 1)
        self.assertEqual(second_payload["execution_summary"]["total"], 1)

        with open(first_artifacts["customers_csv_path"], "r", encoding="utf-8", newline="") as fh:
            first_customers = list(csv.DictReader(fh))
        with open(second_artifacts["actions_csv_path"], "r", encoding="utf-8", newline="") as fh:
            second_actions = list(csv.DictReader(fh))
        with open(second_artifacts["executions_csv_path"], "r", encoding="utf-8", newline="") as fh:
            second_executions = list(csv.DictReader(fh))
        self.assertEqual(first_customers[0]["run_id"], first.run_id)
        self.assertEqual(first_customers[0]["username"], "buyer_first")
        self.assertEqual(second_actions[0]["run_id"], second.run_id)
        self.assertEqual(second_actions[0]["target_username"], "buyer_second")
        self.assertEqual(second_executions[0]["run_id"], second.run_id)
        self.assertEqual(second_executions[0]["id"], second_ids["execution"])

    def test_observation_idempotency_and_lead_decision_versioning(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        run = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)

        source_first = self.storage.record_source_observation(
            run.run_id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            observation_key="planned",
            payload={"priority": 1},
        )
        source_duplicate = self.storage.record_source_observation(
            run.run_id,
            source_id="source-1",
            source_type="keyword",
            source_value="serum",
            observation_key="planned",
            payload={"priority": 99},
        )
        content_first = self.storage.record_content_observation(run.run_id, "content-1", "content_seen")
        content_duplicate = self.storage.record_content_observation(run.run_id, "content-1", "content_seen")
        comment_first = self.storage.record_comment_observation(run.run_id, "content-1", "candidate-1", "user", "comment", "comment_seen")
        comment_duplicate = self.storage.record_comment_observation(run.run_id, "content-1", "candidate-1", "user", "comment", "comment_seen")
        comment_same_user_second_text = self.storage.record_comment_observation(
            run.run_id,
            "content-1",
            "candidate-2",
            "user",
            "different comment",
            "comment_seen",
        )
        candidate_first = self.storage.record_candidate_observation(run.run_id, "candidate-1", "user", 80, ["buy"], "scored")
        candidate_duplicate = self.storage.record_candidate_observation(run.run_id, "candidate-1", "user", 90, ["urgent"], "scored")

        first_decision = self.storage.record_lead_decision(run.run_id, "candidate-1", "high_intent", score=80, reason="first")
        second_decision = self.storage.record_lead_decision(run.run_id, "candidate-1", "high_intent", score=90, reason="second")

        self.assertEqual(source_first, source_duplicate)
        self.assertEqual(content_first, content_duplicate)
        self.assertEqual(comment_first, comment_duplicate)
        self.assertNotEqual(comment_first, comment_same_user_second_text)
        self.assertEqual(candidate_first, candidate_duplicate)
        self.assertNotEqual(first_decision, second_decision)

        trace = self.storage.list_observations_for_run(run.run_id)
        self.assertEqual(len(trace["source_observations"]), 1)
        self.assertEqual(len(trace["content_observations"]), 1)
        self.assertEqual(len(trace["comment_observations"]), 2)
        self.assertEqual(len(trace["candidate_observations"]), 1)
        self.assertEqual([row["decision_version"] for row in trace["lead_decisions"]], [1, 2])

    def test_repeated_candidate_can_generate_independent_run_scoped_leads_actions_and_evidence(self):
        campaign = self.storage.create_campaign("keyword", "serum")
        first = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)
        second = self.storage.create_collection_batch(1, profile_group="US", campaign_id=campaign.id)

        def record_run(batch, score):
            self.storage.set_active_collection_batch(batch.id)
            candidate, _created = self.storage.upsert_candidate(
                CandidateUser(
                    id=f"candidate-{batch.id}",
                    content_id="content-shared",
                    username="repeat_buyer",
                    profile_url="https://example.test/@repeat_buyer",
                    comment_text="where can I buy this",
                    qualify_score=score,
                    intent_tags=["buy"],
                )
            )
            lead_id, lead_created = self.storage.upsert_operation_lead(
                candidate.id,
                "high_intent",
                "high",
                score,
                f"run {batch.id} buying signal",
            )
            action_id, action_created = self.storage.upsert_action_queue_item(
                ActionQueueItem(
                    id=f"action-{batch.id}",
                    lead_id=lead_id,
                    action_type="comment_reply",
                    target_username="repeat_buyer",
                    target_url="https://example.test/video/shared",
                )
            )
            execution_id = self.storage.create_outreach_execution(
                action_id,
                "comment_reply",
                "repeat_buyer",
                status="success",
                profile_id=f"profile-{batch.id}",
                execution_mode="preflight",
                submission_state="not_attempted",
                evidence_path=f"/tmp/reachops/redacted/{batch.run_id}.png",
            )
            return lead_id, lead_created, action_id, action_created, execution_id

        first_lead, first_lead_created, first_action, first_action_created, first_execution = record_run(first, 81)
        second_lead, second_lead_created, second_action, second_action_created, second_execution = record_run(second, 91)

        self.assertTrue(first_lead_created)
        self.assertTrue(second_lead_created)
        self.assertTrue(first_action_created)
        self.assertTrue(second_action_created)
        self.assertNotEqual(first_lead, second_lead)
        self.assertNotEqual(first_action, second_action)
        self.assertNotEqual(first_execution, second_execution)

        first_leads = self.storage.list_operation_leads(run_id=first.run_id)
        second_leads = self.storage.list_operation_leads(run_id=second.run_id)
        first_actions = self.storage.list_action_queue(run_id=first.run_id)
        second_actions = self.storage.list_action_queue(run_id=second.run_id)
        first_executions = self.storage.list_outreach_executions(run_id=first.run_id)
        second_executions = self.storage.list_outreach_executions(run_id=second.run_id)

        self.assertEqual([row["id"] for row in first_leads], [first_lead])
        self.assertEqual([row["id"] for row in second_leads], [second_lead])
        self.assertEqual([row["id"] for row in first_actions], [first_action])
        self.assertEqual([row["id"] for row in second_actions], [second_action])
        self.assertEqual([row["id"] for row in first_executions], [first_execution])
        self.assertEqual([row["id"] for row in second_executions], [second_execution])
        self.assertEqual(first_executions[0]["evidence_path"], f"/tmp/reachops/redacted/{first.run_id}.png")
        self.assertEqual(second_executions[0]["evidence_path"], f"/tmp/reachops/redacted/{second.run_id}.png")

    def test_migration_compatibility_uses_legacy_run_ids_without_rewriting_old_entities(self):
        old_db = Path(self.tmpdir.name) / "legacy.sqlite3"
        with sqlite3.connect(old_db) as conn:
            conn.execute(
                """
                CREATE TABLE collection_batches (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'running',
                    total_sources INTEGER DEFAULT 0,
                    processed_sources INTEGER DEFAULT 0,
                    failed_sources INTEGER DEFAULT 0,
                    profile_group TEXT DEFAULT '',
                    config_json TEXT DEFAULT '{}',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE candidate_users (
                    id TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    comment_text TEXT DEFAULT '',
                    comment_likes INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    qualify_score INTEGER DEFAULT 0,
                    intent_tags TEXT DEFAULT '[]',
                    batch_id TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(content_id, username, comment_text)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE operation_leads (
                    id TEXT PRIMARY KEY,
                    candidate_user_id TEXT NOT NULL,
                    lead_type TEXT NOT NULL,
                    priority TEXT DEFAULT 'normal',
                    score INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    lifecycle_stage TEXT DEFAULT 'new',
                    source_path TEXT DEFAULT '',
                    status TEXT DEFAULT 'new',
                    batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(candidate_user_id, lead_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE action_queue (
                    id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    target_url TEXT DEFAULT '',
                    suggested_text TEXT DEFAULT '',
                    reason TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending_review',
                    risk_level TEXT DEFAULT 'medium',
                    batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(lead_id, action_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE outreach_executions (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    execution_mode TEXT DEFAULT 'simulated',
                    submission_state TEXT DEFAULT 'not_attempted',
                    verification_state TEXT DEFAULT 'not_required',
                    evidence_verified INTEGER DEFAULT 0,
                    profile_id TEXT DEFAULT '',
                    evidence_path TEXT DEFAULT '',
                    error_code TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE growth_errors (
                    id TEXT PRIMARY KEY,
                    error_code TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    source_id TEXT DEFAULT '',
                    creator_id TEXT DEFAULT '',
                    profile_id TEXT DEFAULT '',
                    batch_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO collection_batches
                (id, campaign_id, status, total_sources, processed_sources, failed_sources, profile_group,
                 config_json, started_at, completed_at, created_at, updated_at)
                VALUES ('gb_legacy1', 'acq_legacy', 'completed', 1, 1, 0, 'US', '{}',
                        '2026-07-01T00:00:00Z', '2026-07-01T00:01:00Z',
                        '2026-07-01T00:00:00Z', '2026-07-01T00:01:00Z')
                """
            )
            conn.execute(
                """
                INSERT INTO candidate_users
                (id, content_id, username, profile_url, comment_text, batch_id, status, created_at)
                VALUES ('candidate_legacy1', 'content_legacy1', 'legacy_user',
                        'https://example.test/@legacy_user', 'legacy comment',
                        'gb_legacy1', 'new', '2026-07-01T00:00:30Z')
                """
            )
            conn.execute(
                """
                INSERT INTO operation_leads
                (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage,
                 source_path, status, batch_id, created_at, updated_at)
                VALUES ('lead_legacy1', 'candidate_legacy1', 'high_intent', 'high', 77,
                        'legacy lead', 'new', 'https://example.test/video/legacy',
                        'new', 'gb_legacy1', '2026-07-01T00:00:40Z', '2026-07-01T00:00:40Z')
                """
            )
            conn.execute(
                """
                INSERT INTO action_queue
                (id, lead_id, action_type, target_username, target_url, suggested_text,
                 reason, status, risk_level, batch_id, created_at)
                VALUES ('action_legacy1', 'lead_legacy1', 'comment_reply', 'legacy_user',
                        'https://example.test/video/legacy', 'legacy text',
                        'legacy action', 'pending_review', 'medium',
                        'gb_legacy1', '2026-07-01T00:00:45Z')
                """
            )
            conn.execute(
                """
                INSERT INTO outreach_executions
                (id, action_id, action_type, target_username, status, execution_mode,
                 submission_state, verification_state, evidence_verified, profile_id,
                 evidence_path, error_code, error_message, batch_id, started_at, completed_at, created_at)
                VALUES ('exec_legacy1', 'action_legacy1', 'comment_reply', 'legacy_user',
                        'success', 'preflight', 'not_attempted', 'not_required', 0,
                        'profile_legacy1', '/tmp/reachops/legacy/evidence.png', '', '',
                        'gb_legacy1', '2026-07-01T00:00:50Z', '2026-07-01T00:00:55Z',
                        '2026-07-01T00:00:50Z')
                """
            )
            conn.execute(
                """
                INSERT INTO growth_errors
                (id, error_code, message, source_id, creator_id, profile_id, batch_id, created_at)
                VALUES ('err_legacy1', 'LEGACY_NOTE', 'legacy error', 'source_legacy1',
                        '', 'profile_legacy1', 'gb_legacy1', '2026-07-01T00:00:58Z')
                """
            )

        migrated = GrowthStorage(str(old_db))
        run_id = migrated.run_id_for_batch("gb_legacy1")
        self.assertEqual(run_id, "legacy_run_gb_legacy1")

        campaign_run = migrated.get_campaign_run(run_id=run_id)
        config = json.loads(campaign_run["config_json"])
        self.assertTrue(config["legacy_backfill"])
        self.assertEqual(config["legacy_handling_strategy"], "deterministic_legacy_run_id_for_existing_batch_only")
        self.assertEqual(config["legacy_original_batch_id"], "gb_legacy1")

        candidate = migrated.list_candidates()[0]
        self.assertEqual(candidate.batch_id, "gb_legacy1")
        self.assertEqual(candidate.run_id, "")
        with sqlite3.connect(old_db) as conn:
            conn.row_factory = sqlite3.Row
            legacy_rows = {
                "operation_leads": conn.execute("SELECT batch_id, run_id FROM operation_leads WHERE id='lead_legacy1'").fetchone(),
                "action_queue": conn.execute("SELECT batch_id, run_id FROM action_queue WHERE id='action_legacy1'").fetchone(),
                "outreach_executions": conn.execute("SELECT batch_id, run_id, evidence_path FROM outreach_executions WHERE id='exec_legacy1'").fetchone(),
                "growth_errors": conn.execute("SELECT batch_id, run_id FROM growth_errors WHERE id='err_legacy1'").fetchone(),
            }
        for row in legacy_rows.values():
            self.assertEqual(row["batch_id"], "gb_legacy1")
            self.assertEqual(row["run_id"], "")
        self.assertEqual(legacy_rows["outreach_executions"]["evidence_path"], "/tmp/reachops/legacy/evidence.png")
        legacy_trace = migrated.list_observations_for_run(run_id)
        self.assertEqual(legacy_trace["lead_decisions"], [])
        self.assertEqual(legacy_trace["outreach_executions"], [])
        self.assertEqual(legacy_trace["growth_errors"], [])
        self.assertEqual(migrated.list_action_queue(run_id=run_id), [])
        self.assertEqual(migrated.list_outreach_executions(run_id=run_id), [])

        reopened = GrowthStorage(str(old_db))
        self.assertEqual(reopened.run_id_for_batch("gb_legacy1"), "legacy_run_gb_legacy1")
        self.assertEqual(reopened.count_table("campaign_runs"), 1)

        new_batch = reopened.create_collection_batch(1, profile_group="US", campaign_id="acq_legacy")
        reopened.set_active_collection_batch(new_batch.id)
        new_lead_id, new_lead_created = reopened.upsert_operation_lead(
            "candidate_legacy1",
            "high_intent",
            "high",
            88,
            "new run decision for legacy candidate",
        )
        new_action_id, new_action_created = reopened.upsert_action_queue_item(
            ActionQueueItem(
                id="action_new_run",
                lead_id=new_lead_id,
                action_type="comment_reply",
                target_username="legacy_user",
                target_url="https://example.test/video/new-run",
            )
        )
        self.assertTrue(new_lead_created)
        self.assertTrue(new_action_created)
        self.assertNotEqual(new_lead_id, "lead_legacy1")
        self.assertNotEqual(new_action_id, "action_legacy1")
        self.assertEqual([row["id"] for row in reopened.list_operation_leads(run_id=new_batch.run_id)], [new_lead_id])
        self.assertEqual([row["id"] for row in reopened.list_action_queue(run_id=new_batch.run_id)], [new_action_id])
        with sqlite3.connect(old_db) as conn:
            conn.row_factory = sqlite3.Row
            legacy_lead = conn.execute("SELECT run_id FROM operation_leads WHERE id='lead_legacy1'").fetchone()
            legacy_action = conn.execute("SELECT run_id FROM action_queue WHERE id='action_legacy1'").fetchone()
        self.assertEqual(legacy_lead["run_id"], "")
        self.assertEqual(legacy_action["run_id"], "")


if __name__ == "__main__":
    unittest.main()
