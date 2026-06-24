# -*- coding: utf-8 -*-
from .storage import GrowthStorage


class DataSourceManager:
    def __init__(self, storage: GrowthStorage, platform: str = "tiktok"):
        self.storage = storage
        self.platform = platform

    def create(self, source_type: str, value: str):
        value = (value or "").strip()
        aliases = {
            "shop_keyword": "keyword",
            "tag": "hashtag",
            "video_url": "content_url",
            "live_url": "live_room_url",
            "live": "live_room_url",
        }
        source_type = aliases.get(source_type, source_type)
        if source_type not in {"creator_url", "hashtag", "keyword", "topic", "content_url", "live_room_url", "search_url", "product_url", "shop_url", "custom_list"}:
            raise ValueError(f"unsupported datasource type: {source_type}")
        if not value:
            raise ValueError("datasource value is required")
        datasource = self.storage.upsert_datasource(self.platform, source_type, value)
        self.storage.log_event("datasource_created", datasource.id, {"type": source_type, "value": value})
        return datasource
