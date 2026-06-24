# -*- coding: utf-8 -*-
from .storage import GrowthStorage


class CheckpointManager:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def should_skip_video(self, source_id: str, creator_id: str, video_id: str) -> bool:
        checkpoint = self.storage.get_checkpoint(source_id, creator_id)
        return bool(checkpoint and checkpoint.last_video_id and checkpoint.last_video_id == video_id)

    def update(self, source_id: str, creator_id: str, last_video_id: str):
        return self.storage.update_checkpoint(source_id, creator_id, last_video_id)
