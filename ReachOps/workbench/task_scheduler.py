# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig


class GrowthTaskScheduler:
    """Operational task scheduler facade.

    This service is intentionally synchronous: desktop UI, smoke scripts, or a
    future background worker can call it to run due scans without adding a new
    always-on thread to the operator console.
    """

    def __init__(self, intelligence_service: GrowthIntelligenceService, max_scans_per_group_round: int = 10):
        self.intelligence_service = intelligence_service
        self.storage = intelligence_service.storage
        self.max_scans_per_group_round = max(1, int(max_scans_per_group_round or 10))

    def create_scan(
        self,
        source_type: str,
        source_value: str,
        profile_group: str = "",
        interval_minutes: int = 60,
        next_run_at: Optional[str] = None,
        max_videos: int = 5,
        max_comments: int = 10,
        min_views: int = 0,
        min_comments: int = 0,
    ) -> dict:
        scan = self.storage.create_scheduled_scan(
            source_type,
            source_value,
            profile_group=profile_group,
            schedule_interval_minutes=interval_minutes,
            next_run_at=next_run_at,
            max_videos=max_videos,
            max_comments=max_comments,
            min_views=min_views,
            min_comments=min_comments,
        )
        return scan.__dict__

    def create_scans_bulk(
        self,
        sources: Iterable[dict],
        profile_group: str = "",
        interval_minutes: int = 60,
        next_run_at: Optional[str] = None,
        max_videos: int = 5,
        max_comments: int = 10,
        min_views: int = 0,
        min_comments: int = 0,
    ) -> list[dict]:
        scans = []
        seen = set()
        for source in sources or []:
            source_type = str(source.get("type") or source.get("source_type") or "").strip()
            source_value = str(source.get("value") or source.get("source_value") or "").strip()
            if not source_type or not source_value:
                continue
            key = (source_type, source_value)
            if key in seen:
                continue
            seen.add(key)
            scans.append(
                self.create_scan(
                    source_type,
                    source_value,
                    profile_group=profile_group,
                    interval_minutes=interval_minutes,
                    next_run_at=next_run_at,
                    max_videos=max_videos,
                    max_comments=max_comments,
                    min_views=min_views,
                    min_comments=min_comments,
                )
            )
        self.storage.log_event("scheduled_scan_bulk_created", "", {"count": len(scans), "profile_group": profile_group or ""})
        return scans

    def pause_scan(self, scan_id: str):
        self.storage.update_scheduled_scan_status(scan_id, "paused")

    def resume_scan(self, scan_id: str):
        self.storage.update_scheduled_scan_status(scan_id, "active")

    def run_scan_now(self, scan_id: str, profiles: list[dict], test_mode: bool = False) -> dict:
        scan = self.storage.get_scheduled_scan(scan_id)
        if not scan:
            result = {"scan_id": scan_id, "processed_sources": 0, "errors": {"SCHEDULED_SCAN_NOT_FOUND": 1}, "batch_id": "", "next_run_at": ""}
            self.storage.log_event("scheduled_scan_manual_run_failed", scan_id, result)
            return result
        if str(scan.get("status") or "") != "active":
            result = {
                "scan_id": scan_id,
                "processed_sources": 0,
                "errors": {"SCHEDULED_SCAN_NOT_ACTIVE": 1},
                "batch_id": "",
                "next_run_at": scan.get("next_run_at", ""),
                "skipped": True,
            }
            self.storage.log_event("scheduled_scan_manual_run_skipped", scan_id, result)
            return result
        result = self._run_scan(scan, profiles, test_mode=test_mode)
        self.storage.log_event("scheduled_scan_manual_run", scan_id, result)
        return result

    def run_due(self, profiles: list[dict], now_iso: Optional[str] = None, limit: int = 20, test_mode: bool = False) -> list[dict]:
        results = []
        group_counts: dict[str, int] = {}
        for scan in self.storage.list_due_scheduled_scans(now_iso=now_iso, limit=limit):
            group_key = str(scan.get("profile_group") or "default")
            if group_counts.get(group_key, 0) >= self.max_scans_per_group_round:
                self.storage.log_event(
                    "scheduled_scan_group_rate_limited",
                    scan["id"],
                    {"profile_group": group_key, "limit": self.max_scans_per_group_round},
                )
                results.append(
                    {
                        "scan_id": scan["id"],
                        "processed_sources": 0,
                        "errors": {"GROUP_ROUND_LIMIT_REACHED": 1},
                        "batch_id": "",
                        "next_run_at": scan.get("next_run_at", ""),
                        "skipped": True,
                    }
                )
                continue
            group_counts[group_key] = group_counts.get(group_key, 0) + 1
            results.append(self._run_scan(scan, profiles, test_mode=test_mode))
        return results

    def run_worker_once(self, profiles: list[dict], now_iso: Optional[str] = None, limit: int = 20, test_mode: bool = False) -> dict:
        started_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        results = self.run_due(profiles, now_iso=now_iso, limit=limit, test_mode=test_mode)
        processed = sum(int(item.get("processed_sources") or 0) for item in results)
        skipped = len([item for item in results if item.get("skipped")])
        errors: dict[str, int] = {}
        batch_ids = []
        for item in results:
            if item.get("batch_id"):
                batch_ids.append(item["batch_id"])
            for code, count in (item.get("errors") or {}).items():
                errors[code] = errors.get(code, 0) + int(count or 0)
        completed_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        summary = {
            "started_at": started_at,
            "completed_at": completed_at,
            "due_count": len(results),
            "processed_sources": processed,
            "skipped_scans": skipped,
            "batch_ids": batch_ids,
            "errors": errors,
        }
        self.storage.log_event("scheduler_worker_once_completed", "", summary)
        return summary

    def rerun_failed_tasks(self, batch_id: str, profiles: list[dict], config: Optional[GrowthTaskConfig] = None) -> dict:
        tasks = [
            task
            for task in self.storage.list_collection_tasks(limit=500)
            if task.get("batch_id") == batch_id and task.get("status") == "failed"
        ]
        sources = [{"type": task["source_type"], "value": task["source_value"]} for task in tasks]
        if not sources:
            return {"processed_sources": 0, "rerun_count": 0, "errors": {}}
        result = self.intelligence_service.run_collection(sources, profiles, config or GrowthTaskConfig())
        return {
            "processed_sources": result.processed_sources,
            "rerun_count": len(sources),
            "errors": result.errors,
            "report_json_path": result.report_json_path,
            "report_markdown_path": result.report_markdown_path,
        }

    def rerun_collection_tasks(self, task_ids: list[str], profiles: list[dict], config: Optional[GrowthTaskConfig] = None) -> dict:
        tasks = [
            task
            for task in self.storage.list_collection_tasks_by_ids(task_ids)
            if task.get("status") == "failed"
        ]
        sources = [{"type": task["source_type"], "value": task["source_value"]} for task in tasks]
        if not sources:
            return {"processed_sources": 0, "rerun_count": 0, "errors": {}, "source_task_ids": []}
        result = self.intelligence_service.run_collection(sources, profiles, config or GrowthTaskConfig())
        return {
            "processed_sources": result.processed_sources,
            "rerun_count": len(sources),
            "errors": result.errors,
            "report_json_path": result.report_json_path,
            "report_markdown_path": result.report_markdown_path,
            "source_task_ids": [task["id"] for task in tasks],
        }

    def _run_scan(self, scan: dict, profiles: list[dict], test_mode: bool = False) -> dict:
        config = GrowthTaskConfig(
            max_videos_per_creator=int(scan.get("max_videos") or 5),
            max_comments_per_video=int(scan.get("max_comments") or 10),
            min_views=int(scan.get("min_views") or 0),
            min_comments=int(scan.get("min_comments") or 0),
            profile_group=str(scan.get("profile_group") or ""),
            task_delay_min_seconds=0,
            task_delay_max_seconds=0,
            test_mode=test_mode,
        )
        result = self.intelligence_service.run_collection(
            [{"type": scan["source_type"], "value": scan["source_value"]}],
            self._ordered_profiles_for_scan(profiles, str(scan.get("profile_group") or "")),
            config,
        )
        batch_id = self.storage.latest_collection_batch_id()
        next_run_at = self._next_run_at(scan)
        self.storage.mark_scheduled_scan_run(scan["id"], next_run_at, last_batch_id=batch_id)
        return {
            "scan_id": scan["id"],
            "processed_sources": result.processed_sources,
            "errors": result.errors,
            "batch_id": batch_id,
            "next_run_at": next_run_at,
        }

    def _ordered_profiles_for_scan(self, profiles: Iterable[dict], profile_group: str) -> list[dict]:
        rows = list(profiles or [])
        if not profile_group:
            return self._sort_profiles_by_health(rows)
        group_lower = profile_group.lower()
        matching = [
            profile
            for profile in rows
            if str(profile.get("group_name") or "").lower() == group_lower
            or str(profile.get("group_id") or "").lower() == group_lower
        ]
        return self._sort_profiles_by_health(matching or rows)

    def _sort_profiles_by_health(self, profiles: list[dict]) -> list[dict]:
        health_rows = self.storage.list_profile_health(limit=1000)
        health_by_id = {str(row.get("profile_id") or ""): row for row in health_rows}
        status_rank = {"healthy": 0, "degraded": 1, "cooldown": 2}

        def key(profile: dict):
            profile_id = str(profile.get("profile_id") or profile.get("id") or "")
            health = health_by_id.get(profile_id, {})
            status = str(health.get("status") or "healthy")
            score = int(health.get("health_score") or 100)
            failures = int(health.get("consecutive_failures") or 0)
            return (status_rank.get(status, 1), -score, failures, profile_id)

        return sorted(list(profiles or []), key=key)

    def _next_run_at(self, scan: dict) -> str:
        try:
            base = datetime.strptime(str(scan.get("next_run_at") or ""), "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            base = datetime.utcnow()
        interval = max(1, int(scan.get("schedule_interval_minutes") or 60))
        next_time = max(base, datetime.utcnow()) + timedelta(minutes=interval)
        return next_time.replace(microsecond=0).isoformat() + "Z"
