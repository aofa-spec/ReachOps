# -*- coding: utf-8 -*-
"""Deterministic public-reply replay parser for ReachOps lead lifecycle."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .storage import GrowthStorage


QUALIFIED_PATTERNS = [
    ("purchase_link", re.compile(r"\b(send|share|drop|dm|need|want|where).{0,24}\b(link|url|site|product)\b", re.I)),
    ("price_request", re.compile(r"\b(price|cost|how much|shipping|discount|coupon)\b", re.I)),
    ("availability_request", re.compile(r"\b(available|in stock|ship to|shipping to|can i buy|where to buy)\b", re.I)),
    ("spanish_purchase", re.compile(r"\b(precio|comprar|enlace|link|disponible|cu[aá]nto cuesta)\b", re.I)),
    ("portuguese_purchase", re.compile(r"\b(pre[cç]o|comprar|link|dispon[ií]vel|quanto custa)\b", re.I)),
    ("chinese_purchase", re.compile(r"(价格|多少钱|链接|购买|怎么买|有货|发货|优惠|折扣)")),
]

NEGATIVE_PATTERNS = [
    re.compile(r"\b(no|not|don't|do not|never)\s+(need|want|buy|send|share)\b", re.I),
    re.compile(r"\b(already bought|not interested|just browsing|spam)\b", re.I),
    re.compile(r"(不需要|不用了|没兴趣|已经买了)"),
]


@dataclass
class PublicReplyClassification:
    intent_confirmed: bool
    qualification_state: str
    confidence: int = 0
    reason_codes: list[str] = field(default_factory=list)


class PublicReplyMonitor:
    classifier_version = "rules_public_reply_v1"

    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def classify_reply(self, reply_text: str) -> PublicReplyClassification:
        text = str(reply_text or "").strip()
        if not text:
            return PublicReplyClassification(False, "ignored", 0, ["empty_reply"])
        for pattern in NEGATIVE_PATTERNS:
            if pattern.search(text):
                return PublicReplyClassification(False, "reply_received", 20, ["negative_or_not_interested"])
        reasons = [code for code, pattern in QUALIFIED_PATTERNS if pattern.search(text)]
        if reasons:
            confidence = min(95, 55 + len(reasons) * 15)
            return PublicReplyClassification(True, "qualified", confidence, reasons)
        return PublicReplyClassification(False, "reply_received", 25, ["reply_without_confirmed_need"])

    def ingest_replay_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        created = 0
        updated = 0
        skipped = 0
        qualified = 0
        events: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                skipped += 1
                continue
            lead_id = str(row.get("lead_id") or "").strip()
            reply_text = str(row.get("reply_text") or row.get("text") or "").strip()
            if not lead_id or not reply_text:
                skipped += 1
                continue
            classification = self.classify_reply(reply_text)
            if classification.qualification_state == "ignored":
                skipped += 1
                continue
            event_id, inserted = self.storage.record_public_reply_event(
                lead_id=lead_id,
                action_id=str(row.get("action_id") or ""),
                execution_id=str(row.get("execution_id") or ""),
                target_username=str(row.get("target_username") or ""),
                reply_author_username=str(row.get("reply_author_username") or row.get("author_username") or ""),
                reply_text=reply_text,
                reply_language=str(row.get("reply_language") or row.get("language") or "unknown"),
                source_url=str(row.get("source_url") or row.get("url") or ""),
                replied_at=str(row.get("replied_at") or row.get("created_at") or ""),
                intent_confirmed=classification.intent_confirmed,
                confidence=classification.confidence,
                reason_codes=classification.reason_codes,
                evidence_id=str(row.get("evidence_id") or ""),
                evidence=row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
                classifier_version=self.classifier_version,
                campaign_id=str(row.get("campaign_id") or ""),
                run_id=str(row.get("run_id") or ""),
                batch_id=str(row.get("batch_id") or ""),
            )
            created += 1 if inserted else 0
            updated += 0 if inserted else 1
            stored_event = self.storage.get_public_reply_event(event_id) or {}
            stored_state = str(stored_event.get("qualification_state") or classification.qualification_state)
            stored_verified_contact = bool(int(stored_event.get("verified_contact") or 0))
            qualified += 1 if stored_state == "qualified" else 0
            events.append(
                {
                    "id": event_id,
                    "lead_id": lead_id,
                    "inserted": inserted,
                    "qualification_state": stored_state,
                    "intent_confirmed": classification.intent_confirmed,
                    "verified_contact": stored_verified_contact,
                    "confidence": classification.confidence,
                    "reason_codes": classification.reason_codes,
                }
            )
        return {
            "status": "ok",
            "processed": len(rows or []),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "qualified": qualified,
            "classifier_version": self.classifier_version,
            "events": events,
        }
