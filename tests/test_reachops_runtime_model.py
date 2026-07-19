# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
import tempfile
import unittest
import csv
import json
from pathlib import Path

from ReachOps.intelligence.growth_reporter import GrowthReporter
from ReachOps.intelligence.growth_task_router import GrowthTaskRouter
from ReachOps.intelligence.operation_lead_manager import OperationLeadManager
from ReachOps.intelligence.schemas import ActionQueueItem, CandidateUser, DiscoveredContent, GrowthTaskConfig
from ReachOps.intelligence.storage import GrowthStorage


class ReachOpsRuntimeModelTests(unittest.TestCase):
    def make_storage(self) -> GrowthStorage:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return GrowthStorage(str(Path(tmp.name) / "growth.db"))

    def test_campaign_and_run_isolation_for_observations_and_evidence(self) -> None:
        storage = self.make_storage()
        campaign_a = storage.create_campaign("keyword", "running shoes")
        campaign_b = storage.create_campaign("keyword", "trail shoes")
        run_a1 = storage.create_campaign_run(campaign_a.id, idempotency_key="campaign-a-run-1")
        run_a2 = storage.create_campaign_run(campaign_a.id, idempotency_key="campaign-a-run-2")
        run_b1 = storage.create_campaign_run(campaign_b.id, idempotency_key="campaign-b-run-1")

        ev_a1 = storage.record_evidence_artifact(
            campaign_id=campaign_a.id,
            run_id=run_a1["id"],
            entity_type="candidate",
            entity_id="candidate_same_user",
            local_path="evidence/a1.json",
            sha256="sha-a1",
            sidecar={"comment_visible_confirmed": False},
        )
        ev_a2 = storage.record_evidence_artifact(
            campaign_id=campaign_a.id,
            run_id=run_a2["id"],
            entity_type="candidate",
            entity_id="candidate_same_user",
            local_path="evidence/a2.json",
            sha256="sha-a2",
        )
        ev_b1 = storage.record_evidence_artifact(
            campaign_id=campaign_b.id,
            run_id=run_b1["id"],
            entity_type="candidate",
            entity_id="candidate_same_user",
            local_path="evidence/b1.json",
            sha256="sha-b1",
        )

        obs_a1 = storage.record_candidate_observation(
            campaign_id=campaign_a.id,
            run_id=run_a1["id"],
            candidate_user_id="candidate_same_user",
            content_id="video-1",
            evidence_id=ev_a1["id"],
            collector_version="collector-v1",
            classifier_version="rules-v1",
        )
        obs_a2 = storage.record_candidate_observation(
            campaign_id=campaign_a.id,
            run_id=run_a2["id"],
            candidate_user_id="candidate_same_user",
            content_id="video-1",
            evidence_id=ev_a2["id"],
        )
        obs_b1 = storage.record_candidate_observation(
            campaign_id=campaign_b.id,
            run_id=run_b1["id"],
            candidate_user_id="candidate_same_user",
            content_id="video-1",
            evidence_id=ev_b1["id"],
        )

        self.assertNotEqual(obs_a1["id"], obs_a2["id"])
        self.assertNotEqual(obs_a1["id"], obs_b1["id"])
        self.assertEqual(storage.runtime_traceability_summary(campaign_a.id, run_a1["id"])["counts"]["candidate_observations"], 1)
        self.assertEqual(storage.runtime_traceability_summary(campaign_a.id)["counts"]["candidate_observations"], 2)
        self.assertEqual(storage.runtime_traceability_summary(campaign_b.id)["counts"]["candidate_observations"], 1)

    def test_observation_evidence_and_run_creation_are_idempotent(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("hashtag", "skincare")
        run_1 = storage.create_campaign_run(campaign.id, idempotency_key="same-run")
        run_2 = storage.create_campaign_run(campaign.id, idempotency_key="same-run")
        self.assertEqual(run_1["id"], run_2["id"])
        self.assertEqual(storage.runtime_traceability_summary(campaign.id)["counts"]["campaign_runs"], 1)

        evidence_1 = storage.record_evidence_artifact(
            campaign_id=campaign.id,
            run_id=run_1["id"],
            entity_type="comment",
            entity_id="comment-1",
            local_path="evidence/comment-1.json",
            sha256="sha-comment",
        )
        evidence_2 = storage.record_evidence_artifact(
            campaign_id=campaign.id,
            run_id=run_1["id"],
            entity_type="comment",
            entity_id="comment-1",
            local_path="evidence/comment-1.json",
            sha256="sha-comment",
        )
        self.assertEqual(evidence_1["id"], evidence_2["id"])

        obs_1 = storage.record_candidate_observation(
            campaign_id=campaign.id,
            run_id=run_1["id"],
            candidate_user_id="candidate-1",
            content_id="video-1",
            evidence_id=evidence_1["id"],
        )
        obs_2 = storage.record_candidate_observation(
            campaign_id=campaign.id,
            run_id=run_1["id"],
            candidate_user_id="candidate-1",
            content_id="video-1",
            evidence_id=evidence_1["id"],
        )
        self.assertEqual(obs_1["id"], obs_2["id"])
        summary = storage.runtime_traceability_summary(campaign.id, run_1["id"])
        self.assertEqual(summary["counts"]["evidence_artifacts"], 1)
        self.assertEqual(summary["counts"]["candidate_observations"], 1)

    def test_lead_decision_is_traceable_versioned_and_not_overwritten(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("creator_url", "https://www.tiktok.com/@creator")
        run = storage.create_campaign_run(campaign.id, idempotency_key="decision-run")
        evidence = storage.record_evidence_artifact(
            campaign_id=campaign.id,
            run_id=run["id"],
            entity_type="candidate",
            entity_id="candidate-2",
            local_path="evidence/candidate-2.json",
            sha256="sha-candidate-2",
        )
        observation = storage.record_candidate_observation(
            campaign_id=campaign.id,
            run_id=run["id"],
            candidate_user_id="candidate-2",
            content_id="video-2",
            evidence_id=evidence["id"],
            feature_snapshot={"comment_text": "Need this for my shop"},
        )

        first = storage.record_lead_decision(
            campaign_id=campaign.id,
            run_id=run["id"],
            candidate_observation_id=observation["id"],
            intent_type="purchase_need",
            intent_score=80,
            product_fit_score=70,
            contactability_score=60,
            source_quality_score=50,
            total_lead_score=72,
            confidence=75,
            reason_codes=["need_signal"],
            feature_snapshot={"comment_text": "Need this for my shop"},
            classifier_provider_version="rules-v1",
            decision_key="primary",
        )
        duplicate = storage.record_lead_decision(
            campaign_id=campaign.id,
            run_id=run["id"],
            candidate_observation_id=observation["id"],
            intent_type="purchase_need",
            intent_score=10,
            total_lead_score=10,
            classifier_provider_version="rules-v1",
            decision_key="primary",
        )
        second_version = storage.record_lead_decision(
            campaign_id=campaign.id,
            run_id=run["id"],
            candidate_observation_id=observation["id"],
            intent_type="purchase_need",
            intent_score=82,
            total_lead_score=74,
            classifier_provider_version="rules-v2",
            decision_key="primary",
        )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(int(duplicate["intent_score"]), 80)
        self.assertNotEqual(first["id"], second_version["id"])
        self.assertEqual(storage.runtime_traceability_summary(campaign.id, run["id"])["counts"]["lead_decisions"], 2)

    def test_new_observation_and_evidence_require_real_run_id(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("keyword", "tea")
        with self.assertRaises(ValueError):
            storage.record_evidence_artifact(
                campaign_id=campaign.id,
                entity_type="candidate",
                entity_id="candidate-without-run",
            )
        with self.assertRaises(ValueError):
            storage.record_candidate_observation(
                campaign_id=campaign.id,
                candidate_user_id="candidate-without-run",
                evidence_id="ev_missing",
            )

    def test_run_scoped_leads_actions_and_execution_queries(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("keyword", "running socks")
        run_a = storage.create_campaign_run(campaign.id, idempotency_key="run-a")
        run_b = storage.create_campaign_run(campaign.id, idempotency_key="run-b")

        storage.set_active_campaign_run(run_a["id"])
        lead_a, _ = storage.upsert_operation_lead("candidate-a", "purchase_need", "high", 88, "need signal")
        action_a, _ = storage.upsert_action_queue_item(
            ActionQueueItem(
                id="aq_run_a",
                lead_id=lead_a,
                action_type="comment_reply",
                target_username="redacted_a",
            )
        )
        execution_a = storage.create_outreach_execution(
            action_a,
            "comment_reply",
            "redacted_a",
            status="success",
            execution_mode="preflight",
        )

        storage.set_active_campaign_run(run_b["id"])
        lead_b, _ = storage.upsert_operation_lead("candidate-b", "purchase_need", "normal", 66, "possible fit")
        action_b, _ = storage.upsert_action_queue_item(
            ActionQueueItem(
                id="aq_run_b",
                lead_id=lead_b,
                action_type="comment_reply",
                target_username="redacted_b",
            )
        )
        storage.create_outreach_execution(
            action_b,
            "comment_reply",
            "redacted_b",
            status="success",
            execution_mode="preflight",
        )

        leads_a = storage.list_operation_leads(run_id=run_a["id"])
        executions_a = storage.list_outreach_executions(run_id=run_a["id"])
        self.assertEqual([row["id"] for row in leads_a], [lead_a])
        self.assertEqual([row["id"] for row in executions_a], [execution_a])
        self.assertEqual(leads_a[0]["run_id"], run_a["id"])
        self.assertEqual(executions_a[0]["run_id"], run_a["id"])

    def test_growth_task_router_creates_and_binds_campaign_run(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("keyword", "running gear")
        with tempfile.TemporaryDirectory() as report_dir:
            router = GrowthTaskRouter(storage, report_dir=report_dir)
            result = router.run([], [], GrowthTaskConfig(campaign_id=campaign.id, test_mode=True))

        self.assertEqual(result.processed_sources, 0)
        summary = storage.runtime_traceability_summary(campaign.id)
        self.assertEqual(summary["counts"]["campaign_runs"], 1)
        with storage.connect() as conn:
            batch = conn.execute("SELECT campaign_id, run_id FROM collection_batches").fetchone()
        self.assertEqual(batch["campaign_id"], campaign.id)
        self.assertTrue(batch["run_id"].startswith("run_"))

    def test_scoring_and_lead_pipeline_write_runtime_traceability(self) -> None:
        storage = self.make_storage()
        campaign = storage.create_campaign("keyword", "shopify tool")
        batch = storage.create_collection_batch(1, campaign_id=campaign.id)
        run = storage.create_campaign_run(campaign.id, batch_id=batch.id, idempotency_key="trace-pipeline")
        storage.bind_collection_batch_run(batch.id, run["id"])
        storage.set_active_collection_batch(batch.id)
        storage.set_active_campaign_run(run["id"])

        content, _ = storage.upsert_content(
            DiscoveredContent(
                id="dc_trace",
                creator_id="creator_trace",
                video_id="video_trace",
                video_url="https://www.tiktok.com/@creator/video/1",
                caption="Demo",
                views=50000,
                comments=500,
                source_path="https://www.tiktok.com/@creator/video/1",
            )
        )
        storage.upsert_candidate(
            CandidateUser(
                id="cu_trace",
                content_id=content.id,
                username="redacted_trace",
                profile_url="https://www.tiktok.com/@redacted_trace",
                comment_text="where can I buy this app",
                comment_likes=2,
                source_path=content.source_path,
            )
        )
        config = GrowthTaskConfig(campaign_id=campaign.id, active_batch_id=batch.id, active_run_id=run["id"])
        OperationLeadManager(storage).build_from_scored_candidates(config)

        summary = storage.runtime_traceability_summary(campaign.id, run["id"])
        self.assertEqual(summary["counts"]["evidence_artifacts"], 1)
        self.assertEqual(summary["counts"]["candidate_observations"], 1)
        self.assertEqual(summary["counts"]["lead_decisions"], 1)
        self.assertEqual(storage.list_operation_leads(run_id=run["id"])[0]["run_id"], run["id"])

    def test_runtime_traceability_is_scoped_in_reports_and_exports(self) -> None:
        storage = self.make_storage()
        campaign_a = storage.create_campaign("keyword", "shopify app")
        campaign_b = storage.create_campaign("keyword", "fitness app")
        batch_a = storage.create_collection_batch(1, campaign_id=campaign_a.id)
        run_a = storage.create_campaign_run(campaign_a.id, batch_id=batch_a.id, idempotency_key="report-run-a")
        storage.bind_collection_batch_run(batch_a.id, run_a["id"])
        batch_b = storage.create_collection_batch(1, campaign_id=campaign_b.id)
        run_b = storage.create_campaign_run(campaign_b.id, batch_id=batch_b.id, idempotency_key="report-run-b")
        storage.bind_collection_batch_run(batch_b.id, run_b["id"])

        def add_traceable_candidate(batch_id: str, run_id: str, username: str, video_id: str, score: int) -> None:
            storage.set_active_collection_batch(batch_id)
            storage.set_active_campaign_run(run_id)
            content, _ = storage.upsert_content(
                DiscoveredContent(
                    id=f"dc_{video_id}",
                    creator_id=f"creator_{video_id}",
                    video_id=video_id,
                    video_url=f"https://www.tiktok.com/@creator/video/{video_id}",
                    caption="Demo",
                    views=10000,
                    comments=100,
                    source_path=f"https://www.tiktok.com/@creator/video/{video_id}",
                )
            )
            storage.upsert_candidate(
                CandidateUser(
                    id=f"cu_{username}",
                    content_id=content.id,
                    username=username,
                    profile_url=f"https://www.tiktok.com/@{username}",
                    comment_text="where can I buy this",
                    qualify_score=score,
                    intent_tags=["intent:purchase_need"],
                    source_path=content.source_path,
                )
            )
            evidence = storage.record_evidence_artifact(
                campaign_id=campaign_a.id if run_id == run_a["id"] else campaign_b.id,
                run_id=run_id,
                entity_type="candidate",
                entity_id=f"cu_{username}",
                local_path=f"evidence/{username}.json",
                sha256=f"sha-{username}",
            )
            observation = storage.record_candidate_observation(
                campaign_id=campaign_a.id if run_id == run_a["id"] else campaign_b.id,
                run_id=run_id,
                candidate_user_id=f"cu_{username}",
                content_id=content.id,
                evidence_id=evidence["id"],
            )
            storage.record_lead_decision(
                campaign_id=campaign_a.id if run_id == run_a["id"] else campaign_b.id,
                run_id=run_id,
                candidate_observation_id=observation["id"],
                intent_type="purchase_need",
                total_lead_score=score,
                classifier_provider_version="rules-v1",
            )
            lead_id, _ = storage.upsert_operation_lead(f"cu_{username}", "purchase_need", "high", score, "need signal")
            storage.upsert_action_queue_item(
                ActionQueueItem(
                    id=f"aq_{username}",
                    lead_id=lead_id,
                    action_type="comment_reply",
                    target_username=username,
                )
            )

        add_traceable_candidate(batch_a.id, run_a["id"], "redacted_a", "video_a", 88)
        add_traceable_candidate(batch_b.id, run_b["id"], "redacted_b", "video_b", 92)

        with tempfile.TemporaryDirectory() as report_dir:
            reporter = GrowthReporter(storage, report_dir)
            report_a = reporter.build_report(campaign_id=campaign_a.id, run_id=run_a["id"], batch_id=batch_a.id)
            json_path, csv_path, markdown_path = reporter.export(report_a)
            action_csv_path = next(Path(report_dir).glob("*_action_queue.csv"))

            self.assertEqual(report_a.summary["runtime_scope"]["campaign_id"], campaign_a.id)
            self.assertEqual(report_a.summary["runtime_scope"]["run_id"], run_a["id"])
            self.assertEqual(report_a.summary["candidate_user_count"], 1)
            self.assertEqual(report_a.summary["operation_lead_count"], 1)
            self.assertEqual(report_a.summary["action_queue_count"], 1)
            traceability = report_a.summary["runtime_traceability"]
            self.assertEqual(traceability["counts"]["evidence_artifacts"], 1)
            self.assertEqual(traceability["counts"]["candidate_observations"], 1)
            self.assertEqual(traceability["counts"]["lead_decisions"], 1)
            self.assertFalse(traceability["legacy_run_id_fabricated"])
            self.assertEqual([row["username"] for row in report_a.high_value_users], ["redacted_a"])
            self.assertEqual([row["target_username"] for row in report_a.operation_actions], ["redacted_a"])

            with open(json_path, "r", encoding="utf-8") as fh:
                exported_json = json.load(fh)
            self.assertEqual(exported_json["summary"]["runtime_scope"]["run_id"], run_a["id"])
            self.assertEqual(exported_json["summary"]["runtime_traceability"]["counts"]["candidate_observations"], 1)
            markdown = Path(markdown_path).read_text(encoding="utf-8")
            self.assertIn(f"campaign={campaign_a.id}", markdown)
            self.assertIn("observations=1", markdown)
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
                high_value_rows = list(csv.DictReader(fh))
            with open(action_csv_path, "r", encoding="utf-8-sig", newline="") as fh:
                action_rows = list(csv.DictReader(fh))
            self.assertEqual(high_value_rows[0]["run_id"], run_a["id"])
            self.assertEqual(action_rows[0]["run_id"], run_a["id"])
            self.assertNotIn("redacted_b", json.dumps(exported_json, ensure_ascii=False))

    def test_legacy_migration_keeps_run_id_empty_instead_of_fabricating_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
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
                INSERT INTO candidate_users
                (id, content_id, username, profile_url, comment_text, batch_id, status, created_at)
                VALUES ('cu_legacy', 'content-legacy', 'redacted_user', 'https://example.test/user', 'legacy comment', 'gb_legacy', 'new', '2026-07-01T00:00:00Z')
                """
            )
            conn.commit()
            conn.close()

            storage = GrowthStorage(str(db_path))
            with storage.connect() as check:
                row = check.execute("SELECT run_id FROM candidate_users WHERE id='cu_legacy'").fetchone()
            self.assertEqual(row["run_id"], "")
            summary = storage.runtime_traceability_summary()
            self.assertFalse(summary["legacy_run_id_fabricated"])
            self.assertGreaterEqual(summary["legacy_rows_with_empty_run_id"]["candidate_users"], 1)


if __name__ == "__main__":
    unittest.main()
