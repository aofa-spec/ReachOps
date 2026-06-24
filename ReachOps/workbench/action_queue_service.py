# -*- coding: utf-8 -*-
from __future__ import annotations

from ReachOps.intelligence.storage import GrowthStorage


class ActionQueueService:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def list_pending(self, limit: int = 100) -> list[dict]:
        return [row for row in self.storage.list_action_queue(limit) if row.get("status") == "pending_review"]

    def list_retryable(self, limit: int = 100) -> list[dict]:
        return [row for row in self.storage.list_action_queue(limit) if row.get("status") in {"failed", "retryable"}]

    def approve(self, action_id: str, note: str = ""):
        self.storage.update_action_status(action_id, "approved", note or "approved by operator")

    def reject(self, action_id: str, note: str = ""):
        self.storage.update_action_status(action_id, "rejected", note or "rejected by operator")

    def confirm_execution(self, action_id: str, confirmed_by: str = "operator", note: str = ""):
        self.storage.confirm_action_execution(action_id, confirmed_by=confirmed_by, note=note)

    def bulk_approve(self, action_ids: list[str], note: str = "") -> dict:
        return self._bulk_update(action_ids, "approved", note or "bulk approved by operator")

    def bulk_reject(self, action_ids: list[str], note: str = "") -> dict:
        return self._bulk_update(action_ids, "rejected", note or "bulk rejected by operator")

    def bulk_confirm_execution(self, action_ids: list[str], confirmed_by: str = "operator", note: str = "") -> dict:
        updated = 0
        skipped = 0
        for action_id in self._unique_ids(action_ids):
            if not action_id:
                skipped += 1
                continue
            self.confirm_execution(action_id, confirmed_by=confirmed_by, note=note or "bulk execution confirmed")
            updated += 1
        return {"updated": updated, "skipped": skipped}

    def add_exclusion(self, target_username: str = "", target_url: str = "", reason: str = "") -> str:
        return self.storage.add_exclusion(target_username=target_username, target_url=target_url, reason=reason)

    def save_template(self, action_type: str, name: str, body: str, status: str = "active") -> str:
        return self.storage.upsert_action_template(action_type, name, body, status=status)

    def mark_completed(self, action_id: str, note: str = ""):
        self.storage.update_action_status(action_id, "completed", note)

    def mark_failed(self, action_id: str, note: str = ""):
        self.storage.update_action_status(action_id, "failed", note)

    def schedule_retry(self, action_id: str, note: str = ""):
        self.storage.reset_action_for_retry(action_id, note or "retry from GrowthOps")

    def bulk_schedule_retry(self, action_ids: list[str], note: str = "") -> dict:
        updated = 0
        skipped = 0
        for action_id in self._unique_ids(action_ids):
            if not action_id:
                skipped += 1
                continue
            self.schedule_retry(action_id, note or "bulk retry from GrowthOps")
            updated += 1
        return {"updated": updated, "skipped": skipped}

    def _bulk_update(self, action_ids: list[str], status: str, note: str) -> dict:
        updated = 0
        skipped = 0
        for action_id in self._unique_ids(action_ids):
            if not action_id:
                skipped += 1
                continue
            self.storage.update_action_status(action_id, status, note)
            updated += 1
        return {"updated": updated, "skipped": skipped}

    def _unique_ids(self, action_ids: list[str]) -> list[str]:
        seen = set()
        unique = []
        for action_id in action_ids or []:
            item = str(action_id or "").strip()
            if item and item not in seen:
                seen.add(item)
                unique.append(item)
        return unique
