# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from ReachOps.collectors.cdp_network_collector import CDPNetworkCollector
from ReachOps.collectors.collector_runtime import CollectorRuntime
from ReachOps.collectors.injected_script_collector import InjectedScriptCollector, TIKTOK_COMMENT_SCRIPT
from ReachOps.collectors.normalizer import (
    absolute_tiktok_url,
    detect_text_language,
    is_comment_noise_text,
    is_placeholder_comment_text,
    normalize_comment_text,
    normalize_tiktok_username,
)
from ReachOps.collectors.tiktok_comment_collector import TikTokCommentCollector
from ReachOps.collectors.tiktok_live_room_collector import TikTokLiveRoomCollector
from ReachOps.collectors.tiktok_profile_collector import TikTokProfileCollector
from ReachOps.collectors.tiktok_search_collector import TikTokSearchCollector
from ReachOps.collectors.tiktok_topic_content_collector import TikTokTopicContentCollector
from ReachOps.collectors.tiktok_video_collector import TikTokVideoCollector
from ReachOps.adapters.ix_profile_group_manager import IxProfileGroupManager

from .candidate_user_scorer import CandidateUserScorer
from .checkpoint_manager import CheckpointManager
from .comment_intent import CommentIntentClassifier
from .comment_user_extractor import CommentUserExtractor
from .content_monitor import ContentMonitor
from .creator_pool_manager import CreatorPoolManager
from .datasource_manager import DataSourceManager
from .growth_reporter import GrowthReporter
from .live_room_user_collector import LiveRoomUserCollector
from .operation_lead_manager import OperationLeadManager
from .outreach_copy import OutreachCopyRecommender
from .schemas import GrowthTaskConfig, GrowthTaskResult
from .topic_content_manager import TopicContentManager
from .storage import GrowthStorage


class GrowthTaskRouter:
    def __init__(
        self,
        storage: GrowthStorage,
        report_dir: str,
        browser_factory: Optional[Callable[[str], Any]] = None,
        logger: Optional[Callable[[str], None]] = None,
        collectors: Optional[Dict[str, Any]] = None,
        intent_classifier: Optional[CommentIntentClassifier] = None,
        copy_recommender: Optional[OutreachCopyRecommender] = None,
    ):
        self.storage = storage
        self.datasource_manager = DataSourceManager(storage)
        self.creator_manager = CreatorPoolManager(storage)
        self.content_monitor = ContentMonitor(storage)
        self.comment_extractor = CommentUserExtractor(storage)
        self.topic_contents = TopicContentManager(storage)
        self.operation_leads = OperationLeadManager(storage, copy_recommender=copy_recommender)
        self.checkpoints = CheckpointManager(storage)
        self.scorer = CandidateUserScorer(storage, intent_classifier=intent_classifier)
        self.reporter = GrowthReporter(storage, report_dir)
        self.collector_runtime = CollectorRuntime(report_dir)
        self.profile_group_manager = IxProfileGroupManager(logger=lambda message: self.storage.log_event("ix_profile_group_manager", "", {"message": message}))
        self.browser_factory = browser_factory
        self.logger = logger or (lambda message: None)
        self.collectors = collectors or {
            "profile": TikTokProfileCollector(),
            "video": TikTokVideoCollector(),
            "comment": TikTokCommentCollector(),
            "comment_fallbacks": [
                InjectedScriptCollector(TIKTOK_COMMENT_SCRIPT, normalizer=self._normalize_injected_comments),
                CDPNetworkCollector(["comment/list", "comment", "reply"]),
            ],
            "search": TikTokSearchCollector(),
            "live_room": TikTokLiveRoomCollector(),
            "topic_content": TikTokTopicContentCollector(),
        }
        self.live_room_users = LiveRoomUserCollector(self.collectors.get("live_room"))
        self.profile_failures: Dict[str, int] = {}

    def run(self, sources: Iterable[dict], profiles: List[dict], config: GrowthTaskConfig) -> GrowthTaskResult:
        processed = 0
        source_list = list(sources)
        before_counts = self._snapshot_counts()
        batch = self.storage.create_collection_batch(
            len(source_list),
            profile_group=getattr(config, "profile_group", "") or "",
            config={
                "max_videos_per_creator": config.max_videos_per_creator,
                "max_comments_per_video": config.max_comments_per_video,
                "min_views": config.min_views,
                "min_comments": config.min_comments,
                "target_mode": config.target_mode,
                "vertical": config.vertical,
                "campaign_id": getattr(config, "campaign_id", "") or "",
            },
            campaign_id=getattr(config, "campaign_id", "") or "",
        )
        self.storage.set_active_collection_batch(batch.id)
        try:
            setattr(config, "active_batch_id", batch.id)
        except Exception:
            pass
        if not profiles:
            self.storage.log_error("PROFILE_START_FAILED", "no profile available")
        for index, source_input in enumerate(source_list):
            datasource = self.datasource_manager.create(source_input["type"], source_input["value"])
            ok, error = self._run_source_with_profile_fallback(datasource, batch.id, profiles, index, config)
            if ok:
                processed += 1
                self.storage.update_collection_batch(batch.id, "running", processed_delta=1)
            else:
                if not error:
                    error = {"error_code": "UNKNOWN", "message": ""}
                self.storage.update_collection_batch(batch.id, "running", failed_delta=1)
            self._sleep_between_tasks(config)
        final_status = "completed"
        if processed < len(source_list):
            final_status = "failed" if processed == 0 and source_list else "partial_failed"
        self.storage.update_collection_batch(batch.id, final_status)
        self.scorer.score_all(config)
        self.operation_leads.build_from_scored_candidates(config)
        report = self.reporter.build_report()
        after_counts = self._snapshot_counts()
        report.summary.update(
            {
                "datasource_count": len(source_list),
                "new_creator_count": after_counts["creators"] - before_counts["creators"],
                "new_content_count": after_counts["contents"] - before_counts["contents"],
                "candidate_user_count": after_counts["candidates"] - before_counts["candidates"],
                "high_value_candidate_count": after_counts["high_value"] - before_counts["high_value"],
                "commerce_signal_count": after_counts["commerce_signals"] - before_counts["commerce_signals"],
                "topic_content_count": after_counts["topic_contents"] - before_counts["topic_contents"],
                "operation_lead_count": after_counts["operation_leads"] - before_counts["operation_leads"],
                "action_queue_count": after_counts["action_queue"] - before_counts["action_queue"],
                "outreach_execution_count": after_counts["outreach_executions"] - before_counts["outreach_executions"],
                "collection_task_count": after_counts["collection_tasks"] - before_counts["collection_tasks"],
                "profile_health_count": after_counts["profile_health"],
            }
        )
        try:
            json_path, csv_path, markdown_path = self.reporter.export(report)
        except Exception as exc:
            self.storage.log_error("REPORT_EXPORT_FAILED", str(exc))
            json_path, csv_path, markdown_path = "", "", ""
        self.storage.set_active_collection_batch("")
        return GrowthTaskResult(
            report=report,
            report_json_path=json_path,
            report_csv_path=csv_path,
            report_markdown_path=markdown_path,
            processed_sources=processed,
            errors=self.storage.error_counts(),
        )

    def _run_source_with_profile_fallback(self, datasource, batch_id: str, profiles: List[dict], index: int, config: GrowthTaskConfig):
        last_error = {}
        attempted_profile_ids = set()
        for profile in self._profile_candidates_for_index(profiles, index):
            profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
            if profile_id in attempted_profile_ids:
                continue
            attempted_profile_ids.add(profile_id)
            if self._is_profile_in_cooldown(profile_id, config):
                self.storage.log_event("profile_runtime_retry_skipped", datasource.id, {"profile_id": profile_id, "reason": "cooldown"})
                continue
            task = self.storage.create_collection_task(batch_id, datasource.id, datasource.type, datasource.value, profile_id)
            browser = self._open_browser(profile_id, datasource.id)
            if not browser:
                self._record_profile_failure(profile_id)
                self._record_blocking_profile_state(
                    profile_id,
                    str(profile.get("group_name") or getattr(config, "profile_group", "") or ""),
                    "PROFILE_START_FAILED",
                    "profile start failed",
                )
                self.storage.update_collection_task(task.id, "failed", "PROFILE_START_FAILED", "profile start failed")
                last_error = {"error_code": "PROFILE_START_FAILED", "message": "profile start failed"}
                self.storage.log_event("profile_start_failed_retry", datasource.id, {"profile_id": profile_id, "reason": "start_failed"})
                continue
            driver = getattr(browser, "driver", browser)
            self.storage.record_profile_health(
                profile_id,
                group_name=str(profile.get("group_name") or getattr(config, "profile_group", "") or ""),
                ok=True,
            )
            self.storage.update_collection_task(task.id, "running")
            try:
                attempt_before_counts = self._snapshot_counts()
                ok = self._run_datasource(datasource, driver, config, profile_id)
                if ok:
                    if self._should_retry_empty_profile_result(attempt_before_counts, config):
                        self.storage.update_collection_task(task.id, "failed", "EMPTY_RESULT_RETRY", "no content or comment users collected; trying next profile")
                        self.storage.log_event(
                            "profile_empty_result_retry",
                            datasource.id,
                            {"profile_id": profile_id, "reason": "empty_content_or_comments"},
                        )
                        last_error = {"error_code": "EMPTY_RESULT_RETRY", "message": "no content or comment users collected; trying next profile"}
                        continue
                    self.storage.update_collection_task(task.id, "completed")
                    if attempted_profile_ids and len(attempted_profile_ids) > 1:
                        self.storage.log_event("profile_runtime_retry_succeeded", datasource.id, {"profile_id": profile_id})
                    return True, {}
                last_error = self._last_error_for_source(datasource.id)
                error_code = str(last_error.get("error_code") or "UNKNOWN")
                self.storage.update_collection_task(task.id, "failed", error_code, last_error.get("message", ""))
                if error_code in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED", "COMMENT_ACCESS_GATED"}:
                    self._record_profile_failure(profile_id)
                    self._record_blocking_profile_state(
                        profile_id,
                        str(profile.get("group_name") or getattr(config, "profile_group", "") or ""),
                        error_code,
                        str(last_error.get("message") or error_code),
                    )
                    self.storage.log_event("profile_runtime_failed_retry", datasource.id, {"profile_id": profile_id, "error_code": error_code})
                    continue
                return False, last_error
            finally:
                self._close_browser(browser, profile_id)
        return False, last_error or {"error_code": "PROFILE_START_FAILED", "message": "no available profile"}

    def _should_retry_empty_profile_result(self, before_counts: Dict[str, int], config: GrowthTaskConfig) -> bool:
        if getattr(config, "test_mode", False):
            return False
        if not getattr(config, "retry_empty_result_with_next_profile", True):
            return False
        after_counts = self._snapshot_counts()
        content_delta = int(after_counts.get("contents", 0) or 0) - int(before_counts.get("contents", 0) or 0)
        topic_delta = int(after_counts.get("topic_contents", 0) or 0) - int(before_counts.get("topic_contents", 0) or 0)
        candidate_delta = int(after_counts.get("candidates", 0) or 0) - int(before_counts.get("candidates", 0) or 0)
        return content_delta <= 0 and topic_delta <= 0 and candidate_delta <= 0

    def _run_datasource(self, datasource, driver, config: GrowthTaskConfig, profile_id: str):
        if datasource.type == "creator_url":
            return self._run_creator_url(datasource, driver, config, profile_id)
        if datasource.type == "content_url":
            return self._run_content_url(datasource, driver, config, profile_id)
        if datasource.type == "live_room_url":
            return self._run_live_room_url(datasource, driver, config, profile_id)
        return self._run_topic_source(datasource, driver, config, profile_id)

    def _run_creator_url(self, datasource, driver, config: GrowthTaskConfig, profile_id: str):
        try:
            self._navigate(driver, datasource.value)
            self._wait_for_page(driver, "creator", timeout=0 if config.test_mode else 25)
            self.storage.log_event("creator_profile_opened", datasource.id, {"url": datasource.value, "profile_id": profile_id})
        except Exception as exc:
            self.storage.log_error("CREATOR_PAGE_OPEN_FAILED", str(exc), datasource.id, profile_id=profile_id)
            return False
        state = self._detect_page_state(driver)
        if state:
            self.storage.log_error(state, f"page state detected: {state}", datasource.id, profile_id=profile_id)
            return False
        try:
            profile_data = self.collectors["profile"].collect(driver, {"source": datasource.__dict__}, {"config": config})
            creator = self.creator_manager.save_creator(datasource.id, profile_data)
        except Exception as exc:
            self.storage.log_error("CREATOR_PAGE_OPEN_FAILED", str(exc), datasource.id, profile_id=profile_id)
            return False
        try:
            videos, evidence = self._collect_with_evidence(
                driver,
                [self.collectors["video"]],
                {"creator": creator.__dict__},
                {"config": config},
                "video_scan",
                fallback_on_empty=True,
            )
            self.storage.log_event("collector_evidence", creator.id, self.collector_runtime.evidence_payload(evidence))
        except Exception as exc:
            self.storage.log_error("VIDEO_SCAN_FAILED", str(exc), datasource.id, creator.id, profile_id)
            return False
        if not videos:
            self.storage.log_error("VIDEO_SCAN_EMPTY", "no public videos discovered on creator page", datasource.id, creator.id, profile_id)
            self.storage.log_event("video_scan_empty", creator.id, {"source_id": datasource.id, "profile_id": profile_id})
        max_videos = min(int(config.max_videos_per_creator or 20), 20)
        handled_video_ids: List[str] = []
        for video_data in videos[:max_videos]:
            if int(video_data.get("views") or 0) < int(config.min_views or 0):
                continue
            if int(video_data.get("comments") or 0) < int(config.min_comments or 0):
                continue
            video_id = str(video_data.get("video_id") or video_data.get("video_url") or "")
            if self.checkpoints.should_skip_video(datasource.id, creator.id, video_id):
                self.storage.log_event("video_skipped_by_checkpoint", creator.id, {"video_id": video_id})
                continue
            content, created = self.content_monitor.save_content(creator.id, video_data)
            if not created and self._content_has_candidates(content.id):
                self.storage.log_event("video_skipped_by_checkpoint", content.id, {"video_id": content.video_id})
                continue
            handled_video_ids.append(content.video_id)
            try:
                self._navigate(driver, content.video_url)
                self._wait_for_page(driver, "comments", timeout=0 if config.test_mode else 25)
                comments, evidence = self._collect_comments_with_retry(
                    driver,
                    content.__dict__,
                    config,
                    "comment_scan",
                )
                self.storage.log_event("collector_evidence", content.id, self.collector_runtime.evidence_payload(evidence))
                diagnostics = self._comment_diagnostics_with_context(
                    getattr(evidence, "diagnostics", None),
                    profile_id=profile_id,
                    source_id=datasource.id,
                    creator_id=creator.id,
                    content_id=content.id,
                )
                self.comment_extractor.save_candidates(
                    content.id,
                    comments[: min(int(config.max_comments_per_video or 50), 50)],
                    diagnostics=diagnostics,
                )
            except Exception as exc:
                self.storage.log_error("COMMENT_SCAN_FAILED", str(exc), datasource.id, creator.id, profile_id)
        if handled_video_ids:
            if self._recent_comment_access_blocked(datasource.id, profile_id):
                self.storage.log_event(
                    "profile_comment_access_retry",
                    datasource.id,
                    {"profile_id": profile_id, "reason": "comment_access_gated", "handled_video_count": len(handled_video_ids)},
                )
                return False
            try:
                self.checkpoints.update(datasource.id, creator.id, handled_video_ids[0])
            except Exception as exc:
                self.storage.log_error("CHECKPOINT_WRITE_FAILED", str(exc), datasource.id, creator.id, profile_id)
        return True

    def _run_content_url(self, datasource, driver, config: GrowthTaskConfig, profile_id: str):
        url = datasource.value
        try:
            self._navigate(driver, url)
            self._wait_for_page(driver, "comments", timeout=0 if config.test_mode else 25)
            self.storage.log_event("creator_profile_opened", datasource.id, {"url": url, "profile_id": profile_id, "source_type": datasource.type})
        except Exception as exc:
            self.storage.log_error("CREATOR_PAGE_OPEN_FAILED", str(exc), datasource.id, profile_id=profile_id)
            return False
        state = self._detect_page_state(driver)
        if state:
            self.storage.log_error(state, f"page state detected: {state}", datasource.id, profile_id=profile_id)
            return False

        creator_username = self._extract_creator_from_url(url) or "unknown"
        creator = self.creator_manager.save_creator(
            datasource.id,
            {
                "username": creator_username,
                "profile_url": f"https://www.tiktok.com/@{creator_username}" if creator_username != "unknown" else "",
            },
        )
        video_data = {
            "video_id": self._extract_video_id_from_url(url),
            "video_url": url,
            "caption": self._read_page_caption(driver),
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
        }
        content, _created = self.content_monitor.save_content(creator.id, video_data)
        try:
            comments, evidence = self._collect_comments_with_retry(
                driver,
                content.__dict__,
                config,
                "content_comment_scan",
            )
            self.storage.log_event("collector_evidence", content.id, self.collector_runtime.evidence_payload(evidence))
            diagnostics = self._comment_diagnostics_with_context(
                getattr(evidence, "diagnostics", None),
                profile_id=profile_id,
                source_id=datasource.id,
                creator_id=creator.id,
                content_id=content.id,
            )
            self.comment_extractor.save_candidates(
                content.id,
                comments[: min(int(config.max_comments_per_video or 50), 50)],
                diagnostics=diagnostics,
            )
            if not comments and self._is_comment_access_error(diagnostics.get("error_code", "")):
                self.storage.log_event(
                    "profile_comment_access_retry",
                    datasource.id,
                    {"profile_id": profile_id, "reason": diagnostics.get("error_code", ""), "content_id": content.id},
                )
                return False
            return True
        except Exception as exc:
            self.storage.log_error("COMMENT_SCAN_FAILED", str(exc), datasource.id, creator.id, profile_id)
            return False

    def _run_live_room_url(self, datasource, driver, config: GrowthTaskConfig, profile_id: str):
        url = datasource.value
        try:
            self._navigate(driver, url)
            self._wait_for_page(driver, "live", timeout=0 if config.test_mode else 25)
            self.storage.log_event("creator_profile_opened", datasource.id, {"url": url, "profile_id": profile_id, "source_type": datasource.type})
        except Exception as exc:
            self.storage.log_error("LIVE_ROOM_OPEN_FAILED", str(exc), datasource.id, profile_id=profile_id)
            return False
        state = self._detect_page_state(driver)
        if state:
            self.storage.log_error(state, f"page state detected: {state}", datasource.id, profile_id=profile_id)
            return False

        creator_username = self._extract_creator_from_url(url) or "live_room"
        creator = self.creator_manager.save_creator(
            datasource.id,
            {
                "username": creator_username,
                "profile_url": f"https://www.tiktok.com/@{creator_username}" if creator_username != "live_room" else url,
                "status": "active",
            },
        )
        content, _created = self.content_monitor.save_content(
            creator.id,
            {
                "video_id": f"live-{creator_username}",
                "video_url": url,
                "caption": self._read_page_caption(driver) or "live room active users",
                "material_type": "live_room",
                "source_path": url,
                "comments": 0,
            },
        )
        try:
            self.live_room_users.collector = self.collectors.get("live_room")
            comments, evidence = self.live_room_users.collect_active_users(
                driver,
                datasource.__dict__,
                config,
                max_users=min(int(config.max_comments_per_video or 50), 50),
            )
            self.storage.log_event("collector_evidence", content.id, self.collector_runtime.evidence_payload(evidence))
            diagnostics = self._comment_diagnostics_with_context(
                getattr(evidence, "diagnostics", None),
                profile_id=profile_id,
                source_id=datasource.id,
                creator_id=creator.id,
                content_id=content.id,
            )
            self.comment_extractor.save_candidates(
                content.id,
                comments,
                diagnostics=diagnostics,
            )
            self.storage.log_event("live_users_collected", content.id, {"candidate_rows": len(comments)})
            return True
        except Exception as exc:
            self.storage.log_error("LIVE_ROOM_SCAN_FAILED", str(exc), datasource.id, creator.id, profile_id)
            return False

    def _run_topic_source(self, datasource, driver, config: GrowthTaskConfig, profile_id: str):
        last_error = ""
        for index, url in enumerate(self._topic_url_candidates(datasource.type, datasource.value)):
            try:
                self._navigate(driver, url)
                self._wait_for_page(driver, "topic", timeout=0 if config.test_mode else 25)
                self.storage.log_event(
                    "creator_profile_opened",
                    datasource.id,
                    {"url": url, "profile_id": profile_id, "source_type": datasource.type, "candidate_index": index},
                )
            except Exception as exc:
                last_error = str(exc)
                self.storage.log_error("TOPIC_CONTENT_SCAN_FAILED", str(exc), datasource.id, profile_id=profile_id)
                continue
            state = self._detect_page_state(driver)
            if state:
                last_error = state
                self.storage.log_error(state, f"page state detected: {state}", datasource.id, profile_id=profile_id)
                if state in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED"}:
                    return False
                continue
            try:
                materials, evidence = self._collect_with_evidence(
                    driver,
                    [self.collectors["topic_content"], self.collectors["search"]],
                    {"source": datasource.__dict__, "url": url},
                    {"config": config, "limit": min(int(config.max_videos_per_creator or 20), 20)},
                    f"topic_content_scan_{index}",
                    fallback_on_empty=True,
                )
                self.storage.log_event("collector_evidence", datasource.id, self.collector_runtime.evidence_payload(evidence))
                if not materials:
                    last_error = "empty topic/search result"
                    self.storage.log_event(
                        "topic_content_scan_empty",
                        datasource.id,
                        {"url": url, "profile_id": profile_id, "candidate_index": index},
                    )
                    continue
                self.topic_contents.save_contents(datasource.id, materials)
                topic_result = self._scan_topic_material_comments(datasource, driver, config, profile_id, materials)
                if topic_result.get("access_blocked"):
                    last_error = str(topic_result.get("error_code") or "COMMENT_ACCESS_GATED")
                    return False
                return True
            except Exception as exc:
                last_error = str(exc)
                self.storage.log_error("TOPIC_CONTENT_SCAN_FAILED", str(exc), datasource.id, profile_id=profile_id)
                continue
        if last_error:
            self.storage.log_error("TOPIC_CONTENT_SCAN_FAILED", last_error, datasource.id, profile_id=profile_id)
        return False

    def _scan_topic_material_comments(self, datasource, driver, config: GrowthTaskConfig, profile_id: str, materials: list[dict]):
        max_videos = min(int(config.max_videos_per_creator or 20), 20)
        handled_video_ids: List[str] = []
        scanned = 0
        access_blocked = False
        access_error_code = ""
        for material in materials or []:
            content_data = dict(material.get("content") or material)
            video_url = str(content_data.get("video_url") or "").strip()
            if not video_url:
                continue
            views = int(content_data.get("views") or 0)
            comments_count = int(content_data.get("comments") or 0)
            if views < int(config.min_views or 0):
                continue
            if comments_count < int(config.min_comments or 0):
                continue
            relevant, relevance = self._is_topic_content_relevant(datasource, content_data, config)
            if not relevant:
                self.storage.log_event(
                    "topic_video_skipped_by_relevance",
                    datasource.id,
                    {
                        "video_url": video_url,
                        "caption": str(content_data.get("caption") or "")[:180],
                        "source_type": datasource.type,
                        "source_value": datasource.value,
                        "score": relevance.get("score", 0),
                        "matched_terms": relevance.get("matched_terms", []),
                        "required_terms": relevance.get("required_terms", []),
                        "reason": relevance.get("reason", ""),
                    },
                )
                continue
            creator_username = normalize_tiktok_username(
                content_data.get("creator_username")
                or content_data.get("username")
                or self._extract_creator_from_url(video_url)
                or "unknown"
            )
            creator = self.creator_manager.save_creator(
                datasource.id,
                {
                    "username": creator_username or "unknown",
                    "profile_url": f"https://www.tiktok.com/@{creator_username}" if creator_username and creator_username != "unknown" else "",
                    "vertical": getattr(config, "vertical", "") or "topic",
                    "source_path": video_url,
                    "raw_meta": {"source": "topic_material", "topic_source": datasource.value},
                },
            )
            video_id = str(content_data.get("video_id") or self._extract_video_id_from_url(video_url) or video_url)
            if self.checkpoints.should_skip_video(datasource.id, creator.id, video_id):
                self.storage.log_event("video_skipped_by_checkpoint", creator.id, {"video_id": video_id, "source_type": datasource.type})
                continue
            content_data.update(
                {
                    "video_id": video_id,
                    "video_url": video_url,
                    "material_type": content_data.get("material_type") or "topic_video",
                    "collector_level": content_data.get("collector_level") or "topic_to_comment",
                    "source_path": content_data.get("source_path") or datasource.value,
                }
            )
            content, created = self.content_monitor.save_content(creator.id, content_data)
            if not created and self._content_has_candidates(content.id):
                self.storage.log_event("video_skipped_by_checkpoint", content.id, {"video_id": content.video_id, "source_type": datasource.type})
                continue
            scanned += 1
            handled_video_ids.append(content.video_id)
            try:
                self.storage.log_event(
                    "topic_video_comment_scan_started",
                    content.id,
                    {"video_url": content.video_url, "profile_id": profile_id, "source_value": datasource.value},
                )
                self._navigate(driver, content.video_url)
                self._wait_for_page(driver, "comments", timeout=0 if config.test_mode else 25)
                comments, evidence = self._collect_comments_with_retry(
                    driver,
                    content.__dict__,
                    config,
                    "topic_comment_scan",
                )
                self.storage.log_event("collector_evidence", content.id, self.collector_runtime.evidence_payload(evidence))
                diagnostics = self._comment_diagnostics_with_context(
                    getattr(evidence, "diagnostics", None),
                    profile_id=profile_id,
                    source_id=datasource.id,
                    creator_id=creator.id,
                    content_id=content.id,
                )
                self.comment_extractor.save_candidates(
                    content.id,
                    comments[: min(int(config.max_comments_per_video or 50), 50)],
                    diagnostics=diagnostics,
                )
                if not comments and self._is_comment_access_error(diagnostics.get("error_code", "")):
                    access_blocked = True
                    access_error_code = str(diagnostics.get("error_code") or "COMMENT_ACCESS_GATED")
            except Exception as exc:
                self.storage.log_error("COMMENT_SCAN_FAILED", str(exc), datasource.id, creator.id, profile_id)
            if scanned >= max_videos:
                break
        if handled_video_ids:
            if access_blocked:
                self.storage.log_event(
                    "profile_comment_access_retry",
                    datasource.id,
                    {"profile_id": profile_id, "reason": access_error_code, "handled_video_count": len(handled_video_ids)},
                )
                return {"scanned": scanned, "handled_video_ids": handled_video_ids, "access_blocked": True, "error_code": access_error_code}
            try:
                first_creator_id = ""
                with self.storage.connect() as conn:
                    row = conn.execute(
                        "SELECT creator_id FROM discovered_contents WHERE video_id=? ORDER BY collected_at DESC LIMIT 1",
                        (handled_video_ids[0],),
                    ).fetchone()
                    first_creator_id = row["creator_id"] if row else ""
                if first_creator_id:
                    self.checkpoints.update(datasource.id, first_creator_id, handled_video_ids[0])
            except Exception as exc:
                self.storage.log_error("CHECKPOINT_WRITE_FAILED", str(exc), datasource.id, profile_id=profile_id)
        return {"scanned": scanned, "handled_video_ids": handled_video_ids, "access_blocked": access_blocked, "error_code": access_error_code}

    def _is_topic_content_relevant(self, datasource, content_data: dict, config: GrowthTaskConfig) -> tuple[bool, dict]:
        source_type = str(getattr(datasource, "type", "") or "").strip()
        if source_type not in {"keyword", "hashtag", "tag"}:
            return True, {"score": 100, "reason": "direct_source"}
        source_value = str(getattr(datasource, "value", "") or "").strip()
        text = self._normalize_relevance_text(
            " ".join(
                [
                    str(content_data.get("caption") or ""),
                    str(content_data.get("hook_text") or ""),
                    str(content_data.get("creator_username") or ""),
                    str(content_data.get("username") or ""),
                    str(content_data.get("material_type") or ""),
                ]
            )
        )
        terms = self._campaign_relevance_terms(source_value, config)
        if not terms:
            return True, {"score": 100, "reason": "no_terms"}
        matched = []
        score = 0
        for term in terms:
            normalized = self._normalize_relevance_text(term)
            if not normalized:
                continue
            if self._relevance_term_matches(normalized, text):
                matched.append(term)
                score += 3 if " " in normalized else 1
        if matched:
            return True, {"score": score, "matched_terms": matched[:12], "required_terms": terms[:12], "reason": "matched_campaign_terms"}
        return False, {"score": 0, "matched_terms": [], "required_terms": terms[:12], "reason": "no_campaign_term_match"}

    def _content_has_candidates(self, content_id: str) -> bool:
        try:
            return self.storage.count_candidates_for_content(content_id) > 0
        except Exception:
            return False

    def _comment_diagnostics_with_context(
        self,
        diagnostics: dict | None,
        profile_id: str = "",
        source_id: str = "",
        creator_id: str = "",
        content_id: str = "",
    ) -> dict:
        item = dict(diagnostics) if isinstance(diagnostics, dict) else {}
        if self._looks_like_comment_access_gate(item):
            item["page_state"] = "comment_access_gated"
            item["error_code"] = "COMMENT_ACCESS_GATED"
        item["profile_id"] = str(profile_id or item.get("profile_id") or "")
        item["source_id"] = str(source_id or item.get("source_id") or "")
        item["creator_id"] = str(creator_id or item.get("creator_id") or "")
        item["content_id"] = str(content_id or item.get("content_id") or "")
        return item

    def _looks_like_comment_access_gate(self, diagnostics: dict) -> bool:
        if not isinstance(diagnostics, dict):
            return False
        error_code = str(diagnostics.get("error_code") or "")
        if error_code in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED", "COMMENT_ACCESS_GATED"}:
            return True
        if not bool(diagnostics.get("login_prompt_detected") or diagnostics.get("login_dialog_detected")):
            return False
        visible_nodes = int(diagnostics.get("max_visible_nodes") or diagnostics.get("visible_node_count") or 0)
        panel_seen = bool(diagnostics.get("comment_panel_seen"))
        return visible_nodes == 0 or not panel_seen

    def _is_comment_access_error(self, error_code: str) -> bool:
        return str(error_code or "") in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED", "COMMENT_ACCESS_GATED"}

    def _record_blocking_profile_state(self, profile_id: str, group_name: str, error_code: str, message: str = ""):
        if error_code in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED", "COMMENT_ACCESS_GATED", "PROFILE_START_FAILED"}:
            self.storage.force_profile_cooldown(
                profile_id,
                group_name=group_name,
                error_code=error_code,
                error_message=message or f"page state detected: {error_code}",
            )
            self._move_profile_to_quarantine(profile_id, error_code, message or f"page state detected: {error_code}")
            return
        self.storage.record_profile_health(
            profile_id,
            group_name,
            ok=False,
            error_code=error_code,
            error_message=message or f"page state detected: {error_code}",
        )

    def _move_profile_to_quarantine(self, profile_id: str, error_code: str, message: str = ""):
        try:
            result = self.profile_group_manager.move_profile_to_quarantine(profile_id, reason=error_code)
        except Exception as exc:
            self.storage.log_event(
                "profile_quarantine_move_failed",
                profile_id,
                {"error_code": "IX_PROFILE_GROUP_MOVE_FAILED", "error_message": str(exc), "reason": error_code},
            )
            return
        payload = {
            "ok": result.ok,
            "profile_id": result.profile_id,
            "group_id": result.group_id,
            "group_name": result.group_name,
            "reason": error_code,
            "message": message,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
        self.storage.log_event("profile_quarantine_move_completed" if result.ok else "profile_quarantine_move_failed", profile_id, payload)

    def _recent_comment_access_blocked(self, source_id: str, profile_id: str) -> bool:
        try:
            rows = self.storage.list_errors(limit=40)
        except Exception:
            return False
        for row in rows:
            if str(row.get("source_id") or "") != str(source_id or ""):
                continue
            if str(row.get("profile_id") or "") != str(profile_id or ""):
                continue
            if self._is_comment_access_error(str(row.get("error_code") or "")):
                return True
        return False

    def _campaign_relevance_terms(self, source_value: str, config: GrowthTaskConfig) -> list[str]:
        campaign = {}
        persona = {}
        campaign_id = str(getattr(config, "campaign_id", "") or "").strip()
        if campaign_id:
            campaign = next((row for row in self.storage.list_campaigns(limit=500) if row.get("id") == campaign_id), {})
            persona = self.storage.get_audience_persona(campaign_id)
        raw_terms: list[str] = []
        raw_terms.extend([source_value, str(campaign.get("input_value") or ""), str(campaign.get("product_name") or ""), str(campaign.get("category") or "")])
        for key in ("search_keywords", "hashtags", "interests", "pain_points", "buying_triggers"):
            raw_terms.extend([str(item or "") for item in (persona.get(key) or [])])
        raw_terms.extend([str(item or "") for item in getattr(config, "intent_keywords", []) or []])
        stop_terms = {
            "where",
            "link",
            "buy",
            "price",
            "need",
            "name",
            "how",
            "how to use",
            "does it work",
            "help",
            "recommend",
            "which",
            "size",
            "shipping",
            "coupon",
            "discount",
            "review",
            "best",
            "product",
            "shopping",
            "fyp",
            "general",
            "auto",
        }
        terms: list[str] = []
        seen = set()
        for raw in raw_terms:
            for part in self._split_relevance_terms(raw):
                normalized = self._normalize_relevance_text(part)
                if not normalized or normalized in stop_terms:
                    continue
                if len(normalized) < 4 and not re.search(r"[\u4e00-\u9fff]", normalized):
                    continue
                if normalized not in seen:
                    seen.add(normalized)
                    terms.append(part.strip().lstrip("#"))
        return terms[:40]

    def _split_relevance_terms(self, value: str) -> list[str]:
        value = str(value or "").strip()
        if not value:
            return []
        cleaned = value.replace("#", " ")
        parts = [value.strip().lstrip("#")]
        parts.extend(re.split(r"[,;/|]+", cleaned))
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+-]{3,}|[\u4e00-\u9fff]{2,}", cleaned)
        parts.extend(words)
        return [part.strip() for part in parts if part and part.strip()]

    def _normalize_relevance_text(self, value: str) -> str:
        text = str(value or "").lower()
        text = re.sub(r"https?://\\S+", " ", text)
        text = text.replace("_", " ")
        text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
        return re.sub(r"\\s+", " ", text).strip()

    def _relevance_term_matches(self, term: str, text: str) -> bool:
        if not term or not text:
            return False
        if re.search(r"[\u4e00-\u9fff]", term):
            return term in text
        if " " in term:
            return term in text
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    def _build_topic_url(self, source_type: str, value: str) -> str:
        return self._topic_url_candidates(source_type, value)[0]

    def _topic_url_candidates(self, source_type: str, value: str) -> list[str]:
        value = (value or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return [value]
        if source_type in {"hashtag", "tag"}:
            tag = value.lstrip("#")
            return [
                f"https://www.tiktok.com/tag/{tag}",
                f"https://www.tiktok.com/search/video?q=%23{tag}",
                f"https://www.tiktok.com/search?q=%23{tag}",
            ]
        keyword = value.replace(" ", "%20")
        return [
            f"https://www.tiktok.com/search/video?q={keyword}",
            f"https://www.tiktok.com/search?q={keyword}",
            f"https://www.tiktok.com/tag/{value.replace(' ', '').lstrip('#')}",
        ]

    def _wait_for_page(self, driver, page_kind: str, timeout: int = 25):
        if timeout <= 0:
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._dismiss_blocking_overlays(driver)
                ready = driver.execute_script("return document.readyState") == "complete"
                if page_kind == "topic":
                    found = driver.execute_script("return document.querySelectorAll(\"a[href*='/video/']\").length")
                elif page_kind == "live":
                    found = driver.execute_script("return document.body ? document.body.innerText.length : 0")
                elif page_kind == "comments":
                    found = driver.execute_script(
                        "return document.querySelectorAll(\"[data-e2e*='comment'], div[class*='comment'], a[href*='/@']\").length"
                    )
                else:
                    found = driver.execute_script("return document.body ? document.body.innerText.length : 0")
                if ready and int(found or 0) > 0:
                    return True
                try:
                    driver.execute_script("window.scrollBy(0, Math.max(300, window.innerHeight || 600));")
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(1)
        return False

    def _navigate(self, driver, url: str):
        try:
            try:
                driver.set_page_load_timeout(45)
            except Exception:
                pass
            driver.get(url)
            self._dismiss_blocking_overlays(driver)
        except Exception as exc:
            message = str(exc).lower()
            if "timeout" in message or "timed out receiving message" in message:
                try:
                    driver.execute_script("window.stop();")
                    self._dismiss_blocking_overlays(driver)
                except Exception:
                    pass
                return
            raise

    def _dismiss_blocking_overlays(self, driver) -> dict:
        if not driver:
            return {"dismissed": 0, "labels": []}
        labels: list[str] = []
        for _attempt in range(2):
            try:
                result = driver.execute_script(
                    """
                    const dismissLabels = [
                      'not now', 'maybe later', 'later', 'skip', 'cancel', 'close', 'ok', 'got it',
                      'accept all', 'accept', 'agree', 'continue',
                      'agora não', 'não agora', 'nao agora', 'talvez mais tarde', 'pular',
                      'cancelar', 'fechar', 'entendi', 'aceitar tudo', 'aceitar', 'concordo', 'continuar',
                      '以后再说', '稍后', '取消', '关闭', '我知道了', '同意', '接受'
                    ];
                    const unsafeLabels = [
                      'log in', 'login', 'sign up', 'sign in', 'follow', 'following', 'message',
                      'entrar', 'inscrever', 'criar conta', 'seguir', 'mensagem',
                      '登录', '注册', '关注', '私信'
                    ];
                    const visible = el => {
                      if (!el || !el.getBoundingClientRect) return false;
                      const rect = el.getBoundingClientRect();
                      const style = window.getComputedStyle(el);
                      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && rect.bottom > 0 && rect.right > 0;
                    };
                    const norm = value => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const labelOf = el => norm([
                      el.innerText,
                      el.textContent,
                      el.getAttribute('aria-label'),
                      el.getAttribute('title'),
                      el.getAttribute('data-e2e')
                    ].filter(Boolean).join(' '));
                    const click = el => {
                      const rect = el.getBoundingClientRect();
                      const x = rect.left + rect.width / 2;
                      const y = rect.top + rect.height / 2;
                      const target = document.elementFromPoint(x, y) || el;
                      for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
                      }
                    };
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, [aria-label], [data-e2e]'))
                      .filter(visible)
                      .map(el => ({el, label: labelOf(el), rect: el.getBoundingClientRect()}))
                      .filter(item => item.label && !unsafeLabels.some(token => item.label.includes(token)));
                    const exact = nodes.find(item => dismissLabels.includes(item.label));
                    const fuzzy = nodes.find(item => dismissLabels.some(token => item.label.includes(token)) && item.label.length <= 80);
                    const topRightClose = nodes.find(item => {
                      const symbol = ['×', 'x', '✕'].includes(item.label);
                      return symbol && item.rect.top < window.innerHeight * 0.35 && item.rect.left > window.innerWidth * 0.55;
                    });
                    const target = exact || fuzzy || topRightClose;
                    if (target) {
                      click(target.el);
                      return {dismissed: 1, label: target.label};
                    }
                    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
                    return {dismissed: 0, label: ''};
                    """
                )
                if isinstance(result, dict) and int(result.get("dismissed") or 0) > 0:
                    labels.append(str(result.get("label") or ""))
                    time.sleep(0.25)
                    continue
            except Exception:
                pass
            break
        if labels:
            self.storage.log_event("blocking_overlay_dismissed", "", {"labels": labels})
        return {"dismissed": len(labels), "labels": labels}

    def _collect_with_evidence(self, driver, adapters: list, task: dict, context: dict, evidence_name: str, fallback_on_empty: bool = False):
        return self.collector_runtime.collect_with_fallback(
            driver,
            adapters,
            task,
            context,
            evidence_name=evidence_name,
            fallback_on_empty=fallback_on_empty,
        )

    def _collect_comments_with_retry(self, driver, content: dict, config: GrowthTaskConfig, evidence_name: str):
        limit = min(int(config.max_comments_per_video or 50), 50)
        configured_attempts = max(1, int(getattr(config, "comment_retry_attempts", 2) or 1))
        attempts = configured_attempts if not config.test_mode else max(1, min(configured_attempts, 2))
        last_comments = []
        last_evidence = None
        for attempt in range(1, attempts + 1):
            comments, evidence = self._collect_with_evidence(
                driver,
                self._collector_chain("comment"),
                {"content": content},
                {"config": config, "limit": limit, "attempt": attempt},
                evidence_name if attempt == 1 else f"{evidence_name}_retry_{attempt}",
                fallback_on_empty=True,
            )
            last_comments = comments
            last_evidence = evidence
            if comments and not self._comments_match_expected_content_url(content, evidence):
                expected_video_id = str(content.get("video_id") or self._extract_video_id_from_url(str(content.get("video_url") or "")) or "")
                final_url = str(getattr(evidence, "final_url", "") or getattr(driver, "current_url", "") or "")
                self.storage.log_event(
                    "comment_scan_discarded_url_mismatch",
                    str(content.get("id") or ""),
                    {
                        "attempt": attempt,
                        "expected_video_id": expected_video_id,
                        "expected_url": str(content.get("video_url") or ""),
                        "final_url": final_url,
                        "discarded_comment_count": len(comments),
                    },
                )
                comments = []
                last_comments = []
                try:
                    diagnostics = getattr(evidence, "diagnostics", None)
                    if isinstance(diagnostics, dict):
                        diagnostics["url_mismatch_discarded"] = True
                        diagnostics["expected_video_id"] = expected_video_id
                        diagnostics["final_url_before_discard"] = final_url
                except Exception:
                    pass
            if comments:
                if attempt > 1:
                    self.storage.log_event(
                        "comment_scan_retry_succeeded",
                        str(content.get("id") or ""),
                        {"attempt": attempt, "comment_count": len(comments)},
                    )
                break
            diagnostics = getattr(evidence, "diagnostics", None)
            page_state = str((diagnostics or {}).get("page_state") or "")
            error_code = str(getattr(evidence, "error_code", "") or (diagnostics or {}).get("error_code") or "")
            if page_state in {"login_required", "captcha", "proxy_failed"} or error_code in {
                "LOGIN_REQUIRED",
                "CAPTCHA_DETECTED",
                "PROXY_FAILED",
            }:
                break
            if attempt < attempts:
                self.storage.log_event(
                    "comment_scan_retry",
                    str(content.get("id") or ""),
                    {"attempt": attempt + 1, "previous_level": getattr(evidence, "level", ""), "error_code": error_code},
                )
                if not comments:
                    try:
                        target_url = str(content.get("video_url") or "")
                        if target_url:
                            self._navigate(driver, target_url)
                    except Exception:
                        pass
                try:
                    driver.execute_script("window.scrollBy(0, Math.max(700, window.innerHeight || 700));")
                except Exception:
                    pass
                time.sleep(0 if config.test_mode else 3)
                self._wait_for_page(driver, "comments", timeout=0 if config.test_mode else 8)
        return last_comments, last_evidence

    def _comments_match_expected_content_url(self, content: dict, evidence) -> bool:
        expected_ids = []
        for value in (
            str(content.get("video_id") or ""),
            self._extract_video_id_from_url(str(content.get("video_url") or "")),
        ):
            item = str(value or "").strip()
            if item and item not in expected_ids:
                expected_ids.append(item)
        if not expected_ids or any(item.startswith("live-") for item in expected_ids):
            return True
        final_url = str(getattr(evidence, "final_url", "") or "").strip()
        if not final_url:
            return True
        return any(item in final_url for item in expected_ids)

    def _collector_chain(self, key: str) -> list:
        primary = self.collectors.get(key)
        fallbacks = self.collectors.get(f"{key}_fallbacks") or []
        if isinstance(primary, list):
            return primary + list(fallbacks)
        return ([primary] if primary else []) + list(fallbacks)

    def _normalize_injected_comments(self, rows: list, task: dict, context: dict) -> list[dict]:
        normalized = []
        source_path = str(task.get("content", {}).get("video_url") or task.get("content", {}).get("id") or "")
        source_creator = normalize_tiktok_username(self._extract_creator_from_url(source_path) or "")
        seen = set()
        skipped_placeholder = 0
        skipped_no_user = 0
        skipped_no_text = 0
        skipped_aggregate = 0
        skipped_noise = 0
        skipped_source_creator = 0
        for row in rows or []:
            username = normalize_tiktok_username(row.get("profile_url") or row.get("username") or "")
            comment_text = normalize_comment_text(row.get("comment_text") or "")
            if not username:
                skipped_no_user += 1
                continue
            if source_creator and username.lower() == source_creator.lower():
                skipped_source_creator += 1
                continue
            if not comment_text:
                skipped_no_text += 1
                continue
            if is_placeholder_comment_text(comment_text):
                skipped_placeholder += 1
                continue
            if self._looks_like_aggregate_comment_text(comment_text):
                skipped_aggregate += 1
                continue
            if is_comment_noise_text(comment_text):
                skipped_noise += 1
                continue
            key = (username.lower(), comment_text.lower())
            if key in seen:
                continue
            seen.add(key)
            profile_url = absolute_tiktok_url(row.get("profile_url") or f"/@{username}")
            language = detect_text_language(comment_text)
            normalized.append(
                {
                    "username": username,
                    "profile_url": profile_url,
                    "comment_text": comment_text,
                    "comment_likes": 0,
                    "reply_count": 0,
                    "comment_language": language,
                    "author_profile_completed": bool(profile_url and f"/@{username}" in profile_url),
                    "collector_level": "injected_script",
                    "source_path": source_path,
                    "raw_meta": {
                        "node_index": row.get("node_index"),
                        "source": "injected_script",
                        "language": language,
                        "skipped_placeholder": skipped_placeholder,
                        "skipped_no_user": skipped_no_user,
                        "skipped_no_text": skipped_no_text,
                        "skipped_aggregate": skipped_aggregate,
                        "skipped_noise": skipped_noise,
                        "skipped_source_creator": skipped_source_creator,
                        "visible_node_count": int(row.get("visible_node_count") or 0),
                        "max_visible_nodes": int(row.get("max_visible_nodes") or row.get("visible_node_count") or 0),
                        "scroll_rounds": int(row.get("scroll_rounds") or 0),
                        "growth_rounds": int(row.get("growth_rounds") or 0),
                        "stop_reason": str(row.get("stop_reason") or "injected_script"),
                    },
                }
            )
        return normalized

    def _looks_like_aggregate_comment_text(self, text: str) -> bool:
        value = str(text or "").strip()
        lowered = value.lower()
        if len(value) > 700:
            return True
        reply_markers = ["responder", "reply", "replies", "visualizar", "view", "resposta", "responses"]
        marker_count = sum(lowered.count(marker) for marker in reply_markers)
        if marker_count >= 4 and len(value) > 180:
            return True
        if lowered.count("tiktok") >= 3 and len(value) > 180:
            return True
        return False

    def _extract_creator_from_url(self, url: str) -> str:
        try:
            for part in str(url or "").split("/"):
                if part.startswith("@"):
                    return part.lstrip("@").split("?")[0]
        except Exception:
            pass
        return ""

    def _extract_video_id_from_url(self, url: str) -> str:
        value = str(url or "").split("?")[0].rstrip("/")
        return value.split("/")[-1] if value else ""

    def _read_page_caption(self, driver) -> str:
        try:
            text = driver.execute_script(
                """
                const candidates = [
                  '[data-e2e*="browse-video-desc"]',
                  '[data-e2e*="video-desc"]',
                  'h1',
                  'meta[property="og:description"]'
                ];
                for (const selector of candidates) {
                  const node = document.querySelector(selector);
                  const value = node ? (node.innerText || node.content || node.getAttribute('content') || '') : '';
                  if (value && value.trim()) return value.trim();
                }
                return document.title || '';
                """
            )
            return str(text or "")[:500]
        except Exception:
            return ""

    def _open_browser(self, profile_id: str, source_id: str):
        if not profile_id:
            self.storage.log_error("PROFILE_START_FAILED", "empty profile_id", source_id)
            return None
        try:
            if self.browser_factory:
                browser = self.browser_factory(profile_id)
                if browser:
                    return browser
            from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

            manager = get_workbench_browser_adapter()
            inst = manager.acquire(profile_id=profile_id, account_id=f"growth-{profile_id}", trace_id=source_id, max_instances=3)
            if inst and inst.driver:
                return inst
            last_error = ""
            try:
                last_error = manager.last_error()
            except Exception:
                last_error = ""
            if last_error:
                self.storage.log_error("PROFILE_START_FAILED", last_error, source_id, profile_id=profile_id)
                return None
        except Exception as exc:
            self.storage.log_error("PROFILE_START_FAILED", str(exc), source_id, profile_id=profile_id)
            return None
        self.storage.log_error("PROFILE_START_FAILED", "browser factory returned empty", source_id, profile_id=profile_id)
        return None

    def _close_browser(self, browser: Any, profile_id: str):
        try:
            instance_id = getattr(browser, "instance_id", "")
            if instance_id:
                from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

                get_workbench_browser_adapter().release(instance_id, "growth_intelligence_done")
            elif hasattr(browser, "quit"):
                browser.quit()
        except Exception:
            pass

    def _detect_page_state(self, driver) -> str:
        try:
            url = str(getattr(driver, "current_url", "") or "").lower()
            state = driver.execute_script(
                """
                const text = String(document.body ? document.body.innerText : '').toLowerCase();
                const title = String(document.title || '').toLowerCase();
                const url = String(location.href || '').toLowerCase();
                const pumbaaCtx = String(document.querySelector('meta[name="pumbaa-ctx"]')?.getAttribute('content') || '').toLowerCase();
                const loginStaticAsset = Array.from(document.querySelectorAll('script[src], link[href]')).some((node) => {
                  const value = String(node.getAttribute('src') || node.getAttribute('href') || '').toLowerCase();
                  return /website-login|tiktok_web_login_static/.test(value);
                });
                const videoLinks = document.querySelectorAll("a[href*='/video/']").length;
                const profileLinks = document.querySelectorAll("a[href*='/@']").length;
                const visible = el => {
                  if (!el || !el.getBoundingClientRect) return false;
                  const rect = el.getBoundingClientRect();
                  const style = window.getComputedStyle(el);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' &&
                    rect.bottom > 0 && rect.right > 0 && rect.top < (window.innerHeight || 900);
                };
                const label = el => String([
                  el.innerText,
                  el.textContent,
                  el.getAttribute('aria-label'),
                  el.getAttribute('title'),
                  el.getAttribute('data-e2e')
                ].filter(Boolean).join(' ')).replace(/\\s+/g, ' ').trim().toLowerCase();
                const labels = Array.from(document.querySelectorAll('button, a, [role="button"], [role="dialog"], input'))
                  .filter(visible).map(label).filter(Boolean).slice(0, 80);
                const dialogTexts = Array.from(document.querySelectorAll('[role="dialog"], [data-e2e*="modal"], div'))
                  .filter(visible).map(label).filter(v => v.length >= 4 && v.length <= 600).slice(0, 30);
                const loginDialog = Array.from(document.querySelectorAll('[role="dialog"], [data-e2e*="modal"], div'))
                  .some((node) => {
                    const value = String(node.innerText || '').toLowerCase();
                    const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : {width: 0, height: 0};
                    const authActionCount = [
                      /(^|\\s)(log in|login|sign in)(\\s|$)/,
                      /(^|\\s)(sign up|create account|register)(\\s|$)/,
                      /(登录|登入|注册|註冊|entrar|inscrever|criar conta|iniciar sesión|registrarse)/
                    ].filter(pattern => pattern.test(value)).length;
                    const authSpecificText =
                      /(log in to tiktok|sign up for tiktok|continue with (google|facebook|apple|phone|email)|use phone \\/ email|don't have an account|already have an account|管理你的账号|创建账号|使用手机|使用邮箱|继续使用)/.test(value);
                    return rect.width > 240 && rect.height > 160 && (authActionCount >= 2 || authSpecificText);
                  });
                const combined = [text, title, labels.join(' '), dialogTexts.join(' ')].join(' ');
                const exactLoginButton = labels.some(v => /^(log in|login|sign in|sign up|entrar|inscrever-se|criar conta|iniciar sesión|registrarse)$/.test(v));
                const forcedLoginText = /(log in to|login to|sign up for|sign up \\| tiktok|log in to follow creators|log in to like videos|log in to comment|log in to view comments|登录后即可|登入後即可|entrar para|faça login|inicia sesión)/.test(combined);
                const accountSetupGate =
                  (/login=1/.test(pumbaaCtx) || loginStaticAsset) &&
                  /(got it|how face or voice data is used|important things to know|location services|allow cookies from tiktok|privacy policy|terms of service)/.test(combined);
                const loginPage = /\\/login|\\/signup|login\\?/.test(url) || /(^|\\|\\s*)(sign up|log in|login)(\\s*\\||$)/.test(title);
                const captcha = /captcha|verify to continue|verification|security check|验证码|验证/.test(text);
                const proxy = /proxy|tunnel connection failed|err_tunnel|err_proxy|dns_probe|site can't be reached|无法访问/.test(text);
                return {url, text, title, videoLinks, profileLinks, loginDialog, exactLoginButton, forcedLoginText, accountSetupGate, loginPage, captcha, proxy};
                """
            ) or {}
            text = str(state.get("text") or "").lower()
            url = str(state.get("url") or url).lower()
        except Exception:
            return ""
        if bool(state.get("proxy")):
            return "PROXY_FAILED"
        if bool(state.get("captcha")):
            return "CAPTCHA_DETECTED"
        has_page_entities = int(state.get("videoLinks") or 0) > 0 or int(state.get("profileLinks") or 0) > 0
        if bool(state.get("loginPage")) or bool(state.get("loginDialog")) or bool(state.get("forcedLoginText")) or bool(state.get("accountSetupGate")):
            return "LOGIN_REQUIRED"
        if bool(state.get("exactLoginButton")) and not has_page_entities:
            return "LOGIN_REQUIRED"
        return ""

    def _record_profile_failure(self, profile_id: str):
        if not profile_id:
            return
        self.profile_failures[profile_id] = self.profile_failures.get(profile_id, 0) + 1

    def _is_profile_in_cooldown(self, profile_id: str, config: GrowthTaskConfig) -> bool:
        if not profile_id:
            return False
        return self.profile_failures.get(profile_id, 0) >= int(config.failure_cooldown_threshold or 3)

    def _profile_candidates_for_index(self, profiles: List[dict], index: int) -> List[dict]:
        rows = list(profiles or [])
        if not rows:
            return [{}]
        start = index % len(rows)
        return rows[start:] + rows[:start]

    def _open_browser_with_fallback(self, profiles: List[dict], index: int, config: GrowthTaskConfig, source_id: str):
        last_profile = {}
        for profile in self._profile_candidates_for_index(profiles, index):
            profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
            last_profile = profile
            if self._is_profile_in_cooldown(profile_id, config):
                self.storage.log_event("profile_start_failed_retry", source_id, {"profile_id": profile_id, "reason": "cooldown"})
                continue
            browser = self._open_browser(profile_id, source_id)
            if browser:
                return browser, profile
            self._record_profile_failure(profile_id)
            self._record_blocking_profile_state(
                profile_id,
                str(profile.get("group_name") or getattr(config, "profile_group", "") or ""),
                "PROFILE_START_FAILED",
                "profile start failed",
            )
            self.storage.log_event("profile_start_failed_retry", source_id, {"profile_id": profile_id, "reason": "start_failed"})
        return None, last_profile

    def _sleep_between_tasks(self, config: GrowthTaskConfig):
        if config.test_mode:
            return
        low = int(config.task_delay_min_seconds if config.task_delay_min_seconds is not None else 30)
        high = int(config.task_delay_max_seconds if config.task_delay_max_seconds is not None else 90)
        if low <= 0 and high <= 0:
            return
        time.sleep(random.randint(min(low, high), max(low, high)))

    def _last_error_for_source(self, source_id: str) -> Dict[str, str]:
        try:
            with self.storage.connect() as conn:
                row = conn.execute(
                    """
                    SELECT error_code, message
                    FROM growth_errors
                    WHERE source_id=?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (source_id,),
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    def _snapshot_counts(self) -> Dict[str, int]:
        return {
            "sources": self.storage.count_table("data_sources"),
            "creators": self.storage.count_table("discovered_creators"),
            "contents": self.storage.count_table("discovered_contents"),
            "candidates": self.storage.count_table("candidate_users"),
            "high_value": self.storage.count_high_value_candidates(),
            "commerce_signals": self.storage.count_table("shop_products"),
            "topic_contents": self.storage.count_table("shop_contents"),
            "operation_leads": self.storage.count_table("operation_leads"),
            "action_queue": self.storage.count_table("action_queue"),
            "outreach_executions": self.storage.count_table("outreach_executions"),
            "collection_batches": self.storage.count_table("collection_batches"),
            "collection_tasks": self.storage.count_table("collection_tasks"),
            "profile_health": self.storage.count_table("profile_health"),
        }
