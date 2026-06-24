# -*- coding: utf-8 -*-
from __future__ import annotations

from .storage import GrowthStorage


class TopicContentManager:
    """Save and score topic-driven content signals.

    Commerce data is optional metadata, not the center of the model. The
    storage methods currently keep backward-compatible table names because the
    module is still SQLite-local and may already contain first-stage data.
    """

    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def save_contents(self, source_id: str, materials: list[dict]) -> dict:
        stats = {"commerce_signals": 0, "topic_contents": 0, "signals": 0}
        for item in materials:
            commerce = item.get("commerce") or item.get("product") or {}
            content = item.get("content") or item
            commerce_id = ""
            if commerce:
                commerce_id, commerce_created = self.storage.upsert_commerce_signal(source_id, commerce)
                if commerce_created:
                    stats["commerce_signals"] += 1
                    self.storage.log_event("topic_material_discovered", commerce_id, {"type": "commerce", "title": commerce.get("title", "")})
            if commerce_id and not content.get("product_id"):
                content["product_id"] = commerce.get("product_id") or commerce_id
            content_id, content_created = self.storage.upsert_topic_content(source_id, content)
            if content_created:
                stats["topic_contents"] += 1
                self.storage.log_event("topic_material_discovered", content_id, {"type": "content", "video_url": content.get("video_url", "")})
            score, tags, evidence = self.score_content(content, commerce)
            _, signal_created = self.storage.upsert_material_signal(content_id, "topic_heat", score, tags, evidence)
            if signal_created:
                stats["signals"] += 1
        return stats

    def score_content(self, content: dict, commerce: dict) -> tuple[int, list[str], str]:
        score = 10
        tags = []
        views = int(content.get("views") or 0)
        comments = int(content.get("comments") or 0)
        shares = int(content.get("shares") or 0)
        caption = str(content.get("caption") or "").lower()
        if views >= 500000:
            score += 35
            tags.append("爆量播放")
        elif views >= 100000:
            score += 24
            tags.append("高播放")
        elif views >= 10000:
            score += 12
            tags.append("可观察播放")
        if comments >= 1000:
            score += 20
            tags.append("高评论")
        elif comments >= 100:
            score += 10
            tags.append("评论活跃")
        if shares >= 100:
            score += 10
            tags.append("高分享")
        if commerce.get("product_url") or commerce.get("title"):
            score += 8
            tags.append("商业信号")
        for keyword in ("where", "link", "download", "app", "free", "watch", "name", "episode", "buy", "discount", "coupon"):
            if keyword in caption:
                score += 3
                tags.append(f"话题词:{keyword}")
        score = max(0, min(100, score))
        evidence = f"views={views}, comments={comments}, shares={shares}, commerce={bool(commerce)}"
        return score, tags[:10], evidence
