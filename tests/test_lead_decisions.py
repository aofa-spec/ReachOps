# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ReachOps.intelligence.schemas import CandidateUser
from ReachOps.intelligence.storage import GrowthStorage, LEAD_DECISION_SCHEMA_VERSION


def add_candidate(storage: GrowthStorage, candidate_id: str = "candidate-1", content_id: str = "content-1") -> CandidateUser:
    candidate = CandidateUser(
        id=candidate_id,
        content_id=content_id,
        username=f"user-{candidate_id}",
        profile_url=f"https://www.tiktok.com/@user-{candidate_id}",
        comment_text="where can I buy this?",
        qualify_score=72,
        intent_tags=["intent:buy"],
    )
    saved, _created = storage.upsert_candidate(candidate)
    return saved


class LeadDecisionTests(unittest.TestCase):
    def temp_storage(self) -> GrowthStorage:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return GrowthStorage(str(Path(td.name) / "runtime.sqlite"))

    def test_operation_lead_records_traceable_decision(self) -> None:
        storage = self.temp_storage()
        storage.set_active_collection_batch("batch-a")
        candidate = add_candidate(storage)

        lead_id, created = storage.upsert_operation_lead(
            candidate.id,
            "购买意图",
            "high",
            88,
            "评论命中意图: 购买意图",
            source_path="https://www.tiktok.com/@creator/video/1",
            decision_context={
                "confidence": 82,
                "evidence": "keyword=buy",
                "decision_source": "test_rules",
                "rule_version": "rules.v1",
            },
        )

        self.assertTrue(created)
        decisions = storage.list_lead_decisions(lead_id=lead_id)
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision["decision_schema_version"], LEAD_DECISION_SCHEMA_VERSION)
        self.assertEqual(decision["decision_version"], 1)
        self.assertEqual(decision["decision_type"], "created")
        self.assertEqual(decision["candidate_user_id"], candidate.id)
        self.assertEqual(decision["content_id"], "content-1")
        self.assertEqual(decision["batch_id"], "batch-a")
        self.assertEqual(decision["confidence"], 82)
        self.assertEqual(decision["rule_version"], "rules.v1")
        self.assertTrue(decision["decision"]["local_data_only"])
        lead = next(row for row in storage.list_operation_leads() if row["id"] == lead_id)
        self.assertEqual(lead["latest_decision_version"], 1)

    def test_lead_decision_records_master_contract_fields(self) -> None:
        storage = self.temp_storage()
        campaign = storage.create_campaign("keyword", "anti aging serum")
        batch = storage.create_collection_batch(1, campaign_id=campaign.id)
        storage.set_active_collection_batch(batch.id)
        candidate = add_candidate(storage, "candidate-contract", "content-contract")

        lead_id, _created = storage.upsert_operation_lead(
            candidate.id,
            "buying_intent",
            "high",
            93,
            "contract evidence",
            decision_context={
                "run_id": "run-contract-1",
                "candidate_observation_id": "candidate-observation-1",
                "intent_type": "purchase_question",
                "intent_score": 91,
                "product_fit_score": 82,
                "contactability_score": 77,
                "source_quality_score": 64,
                "total_lead_score": 88,
                "confidence": 86,
                "feature_snapshot": {"language": "en", "matched_terms": ["buy"]},
                "classifier_version": "intent-classifier.v2",
                "provider_version": "local-rules.v2",
                "human_review_status": "pending_review",
            },
        )

        decision = storage.list_lead_decisions(lead_id=lead_id)[0]
        self.assertEqual(decision["campaign_id"], campaign.id)
        self.assertEqual(decision["run_id"], "run-contract-1")
        self.assertEqual(decision["candidate_observation_id"], "candidate-observation-1")
        self.assertEqual(decision["intent_type"], "purchase_question")
        self.assertEqual(decision["intent_score"], 91)
        self.assertEqual(decision["product_fit_score"], 82)
        self.assertEqual(decision["contactability_score"], 77)
        self.assertEqual(decision["source_quality_score"], 64)
        self.assertEqual(decision["total_lead_score"], 88)
        self.assertEqual(decision["classifier_version"], "intent-classifier.v2")
        self.assertEqual(decision["provider_version"], "local-rules.v2")
        self.assertEqual(decision["human_review_status"], "pending_review")
        self.assertEqual(decision["decision"]["campaign_id"], campaign.id)
        self.assertEqual(decision["decision"]["run_id"], "run-contract-1")
        self.assertEqual(decision["decision"]["feature_snapshot"]["language"], "en")
        self.assertEqual(decision["decision"]["feature_snapshot"]["qualify_score"], 72)

    def test_repeated_same_lead_decision_is_idempotent(self) -> None:
        storage = self.temp_storage()
        candidate = add_candidate(storage)

        kwargs = dict(
            candidate_id=candidate.id,
            lead_type="购买意图",
            priority="high",
            score=88,
            reason="same evidence",
            source_path="https://www.tiktok.com/@creator/video/1",
            decision_context={"confidence": 80, "evidence": "same evidence"},
        )
        lead_id, first_created = storage.upsert_operation_lead(**kwargs)
        second_lead_id, second_created = storage.upsert_operation_lead(**kwargs)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(second_lead_id, lead_id)
        self.assertEqual(storage.count_table("lead_decisions"), 1)

    def test_changed_lead_decision_appends_next_version_without_rewriting_history(self) -> None:
        storage = self.temp_storage()
        candidate = add_candidate(storage)

        lead_id, _created = storage.upsert_operation_lead(
            candidate.id,
            "购买意图",
            "normal",
            60,
            "initial score",
            decision_context={"confidence": 60, "evidence": "initial evidence"},
        )
        storage.upsert_operation_lead(
            candidate.id,
            "购买意图",
            "high",
            91,
            "stronger repeat evidence",
            decision_context={"confidence": 91, "evidence": "repeat buyer question"},
        )

        decisions = storage.list_lead_decisions(lead_id=lead_id)
        self.assertEqual([row["decision_version"] for row in decisions], [1, 2])
        self.assertEqual(decisions[0]["score"], 60)
        self.assertEqual(decisions[0]["priority"], "normal")
        self.assertEqual(decisions[1]["score"], 91)
        self.assertEqual(decisions[1]["priority"], "high")
        lead = next(row for row in storage.list_operation_leads() if row["id"] == lead_id)
        self.assertEqual(lead["latest_decision_version"], 2)

    def test_lead_decisions_are_batch_isolated(self) -> None:
        storage = self.temp_storage()
        storage.set_active_collection_batch("batch-a")
        candidate_a = add_candidate(storage, "candidate-a", "content-a")
        storage.upsert_operation_lead(candidate_a.id, "engaged_commenter", "normal", 50, "batch a")

        storage.set_active_collection_batch("batch-b")
        candidate_b = add_candidate(storage, "candidate-b", "content-b")
        storage.upsert_operation_lead(candidate_b.id, "engaged_commenter", "normal", 50, "batch b")

        self.assertEqual(len(storage.list_lead_decisions(batch_id="batch-a")), 1)
        self.assertEqual(len(storage.list_lead_decisions(batch_id="batch-b")), 1)
        self.assertEqual(storage.list_lead_decisions(batch_id="batch-a")[0]["candidate_user_id"], "candidate-a")
        self.assertEqual(storage.list_lead_decisions(batch_id="batch-b")[0]["candidate_user_id"], "candidate-b")

    def test_candidate_batch_remains_authoritative_when_active_batch_changes(self) -> None:
        storage = self.temp_storage()
        storage.set_active_collection_batch("batch-original")
        candidate = add_candidate(storage, "candidate-original", "content-original")

        storage.set_active_collection_batch("batch-later")
        lead_id, created = storage.upsert_operation_lead(
            candidate.id,
            "engaged_commenter",
            "normal",
            50,
            "evaluated after active batch moved",
        )

        self.assertTrue(created)
        self.assertEqual(storage.list_lead_decisions(lead_id=lead_id)[0]["batch_id"], "batch-original")
        self.assertEqual(storage.list_operation_leads(batch_id="batch-original")[0]["id"], lead_id)
        self.assertEqual(storage.list_operation_leads(batch_id="batch-later"), [])

    def test_legacy_database_migration_does_not_fabricate_historical_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.sqlite"
            conn = sqlite3.connect(db_path)
            try:
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
                    INSERT INTO operation_leads
                    (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage,
                     source_path, status, batch_id, created_at, updated_at)
                    VALUES ('legacy-lead', 'legacy-candidate', 'engaged_commenter', 'normal',
                            50, 'legacy latest state only', 'new', '', 'new', 'legacy-batch',
                            '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            storage = GrowthStorage(str(db_path))

            self.assertEqual(storage.count_table("operation_leads"), 1)
            self.assertEqual(storage.count_table("lead_decisions"), 0)
            self.assertEqual(storage.list_lead_decisions(), [])


if __name__ == "__main__":
    unittest.main()
