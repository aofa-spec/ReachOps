# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from .storage import GrowthStorage
from ReachOps.collectors.normalizer import normalize_language_text
from .comment_intent import CommentIntentClassifier, RuleBasedCommentIntentClassifier
from .lead_quality import looks_like_seller_promo


class CandidateUserScorer:
    def __init__(self, storage: GrowthStorage, intent_classifier: CommentIntentClassifier | None = None):
        self.storage = storage
        self.intent_classifier = intent_classifier or RuleBasedCommentIntentClassifier()

    def score_all(self, config=None) -> int:
        custom_intent_keywords = self._normalize_keywords(getattr(config, "intent_keywords", []) if config else [])
        exclude_keywords = self._normalize_keywords(getattr(config, "exclude_keywords", []) if config else [])
        persisted_repeat_counts = self.storage.refresh_candidate_repeat_counts()
        rows = self.storage.list_candidates_with_content()
        repeat_counts = Counter(str(row.get("username") or "").lower() for row in rows)
        updated = 0
        for row in rows:
            username = str(row.get("username") or "").lower()
            if persisted_repeat_counts.get(username):
                repeat_counts[username] = max(repeat_counts[username], persisted_repeat_counts[username])
            score, tags, status = self.score_candidate(row, repeat_counts, custom_intent_keywords, exclude_keywords)
            self.storage.update_candidate_score(row["id"], score, tags, status)
            self.storage.log_event("candidate_user_scored", row["id"], {"score": score, "status": status, "tags": tags})
            updated += 1
        return updated

    def score_candidate(self, row: dict, repeat_counts: Counter, custom_intent_keywords: Optional[list[str]] = None, exclude_keywords: Optional[list[str]] = None) -> tuple[int, list[str], str]:
        tags = []
        score = 10
        if looks_like_seller_promo(str(row.get("comment_text") or "")):
            return 0, ["excluded_seller_promo", "intent_type:exclude", "intent_confidence:0.95"], "low_value"

        classifier = getattr(self, "intent_classifier", None) or RuleBasedCommentIntentClassifier()
        intent = classifier.classify(row, custom_intent_keywords, exclude_keywords)
        tags.extend(intent.tags)
        tags.append(f"intent_type:{intent.intent_type}")
        tags.append(f"intent_confidence:{intent.confidence:.2f}")
        if intent.excluded:
            return 0, self._dedupe_tags(tags), "low_value"
        score += int(intent.score_delta or 0)
        if int(row.get("comment_likes") or 0) > 0:
            tags.append("liked_comment")
            score += min(15, 5 + int(row.get("comment_likes") or 0))
        if int(row.get("reply_count") or 0) > 0:
            tags.append("has_replies")
            score += min(10, 4 + int(row.get("reply_count") or 0) * 2)

        views = int(row.get("views") or 0)
        video_comments = int(row.get("video_comments") or 0)
        if views >= 100000:
            tags.append("high_view_video")
            score += 15
        elif views >= 10000:
            tags.append("medium_view_video")
            score += 8
        if video_comments >= 1000:
            tags.append("high_comment_video")
            score += 15
        elif video_comments >= 100:
            tags.append("medium_comment_video")
            score += 8

        username = str(row.get("username") or "").lower()
        if repeat_counts[username] > 1:
            tags.append("repeat_commenter")
            score += min(15, repeat_counts[username] * 5)

        score = max(0, min(100, score))
        if score >= 70:
            status = "high_value"
        elif score >= 40:
            status = "watch"
        else:
            status = "low_value"
        return score, self._dedupe_tags(tags), status

    def _normalize_keywords(self, keywords) -> list[str]:
        if isinstance(keywords, str):
            raw_items = re.split(r"[,，;；\n]", keywords)
        else:
            raw_items = list(keywords or [])
        normalized = []
        seen = set()
        for item in raw_items:
            keyword = normalize_language_text(str(item or "").strip().lower())
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            normalized.append(keyword)
        return normalized

    def _contains_intent(self, text: str, keyword: str) -> bool:
        if not text or not keyword:
            return False
        if re.search(r"[a-z0-9]", keyword):
            return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
        return keyword in text

    def _dedupe_tags(self, tags: list[str]) -> list[str]:
        seen = set()
        result = []
        for tag in tags or []:
            value = str(tag or "").strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
