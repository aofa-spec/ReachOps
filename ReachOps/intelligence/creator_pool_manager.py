# -*- coding: utf-8 -*-
from .schemas import DiscoveredCreator, utc_now_iso
from .storage import GrowthStorage, new_id
from ReachOps.collectors.normalizer import classify_vertical, detect_text_language


class CreatorPoolManager:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def save_creator(self, source_id: str, profile_data: dict) -> DiscoveredCreator:
        username = (profile_data.get("username") or profile_data.get("page_username") or "").strip().lstrip("@")
        profile_url = (profile_data.get("profile_url") or "").strip()
        if not username and profile_url:
            username = profile_url.rstrip("/").split("/")[-1].lstrip("@")
        creator = DiscoveredCreator(
            id=new_id("cr"),
            source_id=source_id,
            username=username or "unknown",
            profile_url=profile_url,
            followers=int(profile_data.get("followers") or 0),
            likes_total=int(profile_data.get("likes_total") or 0),
            vertical=str(profile_data.get("vertical") or classify_vertical("creator", username or profile_url) or "general"),
            country=str(profile_data.get("country") or ""),
            language=str(profile_data.get("language") or detect_text_language(profile_data.get("bio") or username or "")),
            source_path=str(profile_data.get("source_path") or profile_url),
            raw_meta=profile_data.get("raw_meta") if isinstance(profile_data.get("raw_meta"), dict) else {},
            status=profile_data.get("status") or "active",
            last_checked_at=utc_now_iso(),
        )
        saved = self.storage.upsert_creator(creator)
        self.storage.log_event("creator_collected", saved.id, {"username": saved.username})
        return saved
