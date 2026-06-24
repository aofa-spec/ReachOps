# -*- coding: utf-8 -*-
from __future__ import annotations

from ReachOps.collectors.normalizer import detect_text_language, normalize_comment_text, normalize_tiktok_username


class LiveRoomUserCollector:
    """Convert live-room chat participants into CandidateUser-compatible rows."""

    def __init__(self, collector=None):
        self.collector = collector

    def collect_active_users(self, driver, datasource: dict, config, max_users: int = 50) -> tuple[list[dict], object | None]:
        if not self.collector:
            return [], None
        limit = max(1, min(int(max_users or 50), 50))
        url = str(datasource.get("value") or datasource.get("url") or "")
        payload = self.collector.collect(
            driver,
            {"source": datasource, "url": url, "max_live_users": limit},
            {"config": config, "max_live_users": limit},
        ) or {}
        active_users = payload.get("active_users", []) if isinstance(payload, dict) else []
        evidence = self.collector.evidence(driver, len(active_users), str(active_users[:2]))
        return self.to_candidate_rows(active_users, url)[:limit], evidence

    def to_candidate_rows(self, active_users: list[dict], source_url: str) -> list[dict]:
        rows = []
        for item in active_users or []:
            username = normalize_tiktok_username(item.get("profile_url") or item.get("username") or "")
            text = normalize_comment_text(item.get("text") or item.get("comment_text") or "")
            if not username or not text:
                continue
            rows.append(
                {
                    "username": username,
                    "profile_url": str(item.get("profile_url") or f"https://www.tiktok.com/@{username}"),
                    "comment_text": text,
                    "comment_likes": 0,
                    "reply_count": 0,
                    "comment_language": str(item.get("comment_language") or detect_text_language(text)),
                    "author_profile_completed": True,
                    "collector_level": "selenium_dom",
                    "source_path": source_url,
                    "raw_meta": {
                        "source": "live_room",
                        "matched_keyword": bool(item.get("matched_keyword")),
                        "comment_page_state": "normal",
                        "stop_reason": "live_room_scan",
                    },
                }
            )
        return rows
