# -*- coding: utf-8 -*-
from .schemas import DiscoveredContent
from .storage import GrowthStorage, new_id
from ReachOps.collectors.normalizer import detect_text_language


class ContentMonitor:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def save_content(self, creator_id: str, video_data: dict):
        video_id = str(video_data.get("video_id") or "").strip()
        video_url = str(video_data.get("video_url") or "").strip()
        if not video_id and video_url:
            video_id = video_url.rstrip("/").split("/")[-1]
        content = DiscoveredContent(
            id=new_id("ct"),
            creator_id=creator_id,
            video_id=video_id,
            video_url=video_url,
            caption=str(video_data.get("caption") or ""),
            views=int(video_data.get("views") or 0),
            likes=int(video_data.get("likes") or 0),
            comments=int(video_data.get("comments") or 0),
            shares=int(video_data.get("shares") or 0),
            content_language=str(video_data.get("content_language") or video_data.get("language") or detect_text_language(video_data.get("caption") or "")),
            country=str(video_data.get("country") or ""),
            material_type=str(video_data.get("material_type") or "creator_video"),
            collector_level=str(video_data.get("collector_level") or "selenium_dom"),
            source_path=str(video_data.get("source_path") or video_url),
            raw_meta=video_data.get("raw_meta") if isinstance(video_data.get("raw_meta"), dict) else {},
            published_at=video_data.get("published_at"),
        )
        saved, created = self.storage.upsert_content(content)
        if created:
            self.storage.log_event("video_discovered", saved.id, {"video_id": saved.video_id, "views": saved.views})
        return saved, created
