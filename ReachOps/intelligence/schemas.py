# -*- coding: utf-8 -*-
"""Schemas for the Growth Intelligence module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


ERROR_CODES = {
    "PROFILE_START_FAILED",
    "CREATOR_PAGE_OPEN_FAILED",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "VIDEO_SCAN_FAILED",
    "VIDEO_SCAN_EMPTY",
    "COMMENT_SCAN_FAILED",
    "COMMENT_SCAN_EMPTY",
    "EMPTY_RESULT_RETRY",
    "CHECKPOINT_WRITE_FAILED",
    "REPORT_EXPORT_FAILED",
    "TOPIC_CONTENT_SCAN_FAILED",
    "SHOP_MATERIAL_SCAN_FAILED",
    "ACTION_QUEUE_WRITE_FAILED",
    "OUTREACH_POLICY_BLOCKED",
    "OUTREACH_EXECUTION_FAILED",
    "PAGE_OPEN_FAILED",
    "BROWSER_CRASHED",
    "COMMENT_BOX_NOT_FOUND",
    "COMMENT_SUBMIT_FAILED",
    "COMMENT_BLOCKED",
    "FOLLOW_BUTTON_MISSING",
    "FOLLOW_RATE_LIMITED",
    "DM_ENTRY_NOT_FOUND",
    "DM_NOT_ALLOWED",
    "DM_RATE_LIMITED",
    "RATE_LIMITED",
    "ACCOUNT_RESTRICTED",
    "DAILY_QUOTA_EXCEEDED",
    "LIVE_SUBMIT_EVIDENCE_MISSING",
    "LIVE_SUBMIT_DEVICE_MISMATCH",
    "LIVE_SUBMIT_LICENSE_EXPIRED",
    "LIVE_SUBMIT_NOT_AUTHORIZED",
}


LOG_EVENTS = {
    "datasource_created",
    "creator_profile_opened",
    "creator_collected",
    "video_discovered",
    "video_skipped_by_checkpoint",
    "video_scan_empty",
    "comments_collected",
    "comment_scan_retry",
    "comment_scan_retry_succeeded",
    "candidate_user_created",
    "candidate_user_scored",
    "report_exported",
    "topic_material_discovered",
    "topic_content_scan_empty",
    "audience_intent_created",
    "operation_lead_created",
    "action_queue_created",
    "outreach_execution_created",
    "outreach_execution_skipped",
    "outreach_execution_completed",
    "action_execution_confirmed",
    "high_risk_confirmation_blocked",
    "action_rejection_blocked",
    "action_execution_result_recorded",
    "action_retry_scheduled",
    "action_template_saved",
    "exclusion_added",
    "daily_quota_updated",
    "collection_batch_created",
    "collection_task_started",
    "collection_task_completed",
    "profile_health_updated",
    "profile_start_failed_retry",
    "profile_empty_result_retry",
    "scheduled_scan_created",
    "scheduled_scan_bulk_created",
    "source_recommendation_scan_created",
    "scheduled_scan_paused",
    "scheduled_scan_resumed",
    "scheduled_scan_run",
    "scheduled_scan_group_rate_limited",
    "scheduler_worker_once_completed",
    "growth_ops_filtered_exported",
    "growth_filter_preset_saved",
    "bulk_confirmation_previewed",
    "execution_plan_built",
    "execution_plan_exported",
    "execution_plan_saved",
    "execution_plan_executed",
    "execution_mvp_action_completed",
    "execution_mvp_action_failed",
    "execution_mvp_action_blocked",
    "execution_mvp_pressure_completed",
}


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class DataSource:
    id: str
    platform: str
    type: str
    value: str
    status: str = "active"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class DiscoveredCreator:
    id: str
    source_id: str
    username: str
    profile_url: str
    followers: int = 0
    likes_total: int = 0
    vertical: str = "general"
    country: str = ""
    language: str = "unknown"
    source_path: str = ""
    raw_meta: Dict[str, Any] = field(default_factory=dict)
    batch_id: str = ""
    status: str = "active"
    last_checked_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class DiscoveredContent:
    id: str
    creator_id: str
    video_id: str
    video_url: str
    caption: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    content_language: str = "unknown"
    country: str = ""
    material_type: str = "creator_video"
    collector_level: str = "selenium_dom"
    source_path: str = ""
    raw_meta: Dict[str, Any] = field(default_factory=dict)
    batch_id: str = ""
    published_at: Optional[str] = None
    collected_at: str = field(default_factory=utc_now_iso)


@dataclass
class CandidateUser:
    id: str
    content_id: str
    username: str
    profile_url: str
    comment_text: str = ""
    comment_likes: int = 0
    reply_count: int = 0
    qualify_score: int = 0
    intent_tags: List[str] = field(default_factory=list)
    comment_language: str = "unknown"
    author_profile_completed: bool = False
    collector_level: str = "selenium_dom"
    source_path: str = ""
    repeat_seen_count: int = 1
    raw_meta: Dict[str, Any] = field(default_factory=dict)
    batch_id: str = ""
    status: str = "new"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CommerceSignal:
    id: str
    source_id: str
    platform: str = "tiktok"
    product_id: str = ""
    product_url: str = ""
    title: str = ""
    shop_name: str = ""
    category: str = ""
    price: str = ""
    sales_text: str = ""
    rating: str = ""
    collected_at: str = field(default_factory=utc_now_iso)


@dataclass
class TopicContent:
    id: str
    source_id: str
    product_id: str = ""
    creator_username: str = ""
    video_id: str = ""
    video_url: str = ""
    caption: str = ""
    material_type: str = "unknown"
    hook_text: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collected_at: str = field(default_factory=utc_now_iso)


ShopProduct = CommerceSignal
ShopContent = TopicContent


@dataclass
class MaterialSignal:
    id: str
    content_id: str
    signal_type: str
    signal_score: int = 0
    signal_tags: List[str] = field(default_factory=list)
    evidence: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class AudienceIntent:
    id: str
    candidate_user_id: str
    content_id: str
    intent_type: str
    confidence: int = 0
    evidence: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class OperationLead:
    id: str
    candidate_user_id: str
    lead_type: str
    priority: str = "normal"
    score: int = 0
    reason: str = ""
    lifecycle_stage: str = "new"
    source_path: str = ""
    batch_id: str = ""
    status: str = "new"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ActionQueueItem:
    id: str
    lead_id: str
    action_type: str
    target_username: str
    target_url: str = ""
    suggested_text: str = ""
    reason: str = ""
    status: str = "pending_review"
    risk_level: str = "medium"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ActionTemplate:
    id: str
    action_type: str
    name: str
    body: str
    status: str = "active"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ExclusionRule:
    id: str
    target_username: str = ""
    target_url: str = ""
    reason: str = ""
    status: str = "active"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class DailyQuota:
    id: str
    profile_id: str
    action_type: str
    quota_date: str
    used_count: int = 0
    limit_count: int = 20
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ActionLog:
    id: str
    action_id: str
    status: str
    note: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class OutreachExecution:
    id: str
    action_id: str
    action_type: str
    target_username: str
    status: str = "pending"
    profile_id: str = ""
    evidence_path: str = ""
    error_code: str = ""
    error_message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CollectionBatch:
    id: str
    campaign_id: str = ""
    status: str = "running"
    total_sources: int = 0
    processed_sources: int = 0
    failed_sources: int = 0
    profile_group: str = ""
    config_json: str = "{}"
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class CollectionTask:
    id: str
    batch_id: str
    source_id: str
    source_type: str
    source_value: str
    profile_id: str = ""
    status: str = "pending"
    error_code: str = ""
    error_message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ProfileHealth:
    profile_id: str
    group_name: str = ""
    health_score: int = 100
    status: str = "healthy"
    consecutive_failures: int = 0
    last_error_code: str = ""
    last_error_message: str = ""
    last_used_at: Optional[str] = None
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ScheduledScan:
    id: str
    source_type: str
    source_value: str
    profile_group: str = ""
    schedule_interval_minutes: int = 60
    next_run_at: str = field(default_factory=utc_now_iso)
    status: str = "active"
    max_videos: int = 5
    max_comments: int = 10
    min_views: int = 0
    min_comments: int = 0
    last_batch_id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class AcquisitionCampaign:
    id: str
    input_type: str
    input_value: str
    objective: str = "customer_acquisition"
    target_market: str = "auto"
    target_language: str = "auto"
    product_name: str = ""
    category: str = ""
    status: str = "active"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class AudiencePersona:
    id: str
    campaign_id: str
    demographics: Dict[str, Any] = field(default_factory=dict)
    interests: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    buying_triggers: List[str] = field(default_factory=list)
    intent_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    search_keywords: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    competitor_terms: List[str] = field(default_factory=list)
    outreach_angles: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class AcquisitionSource:
    id: str
    campaign_id: str
    source_type: str
    source_value: str
    reason: str = ""
    priority: int = 50
    status: str = "active"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class AcquisitionStrategy:
    campaign_id: str
    product_analysis: Dict[str, Any] = field(default_factory=dict)
    audience_profile: Dict[str, Any] = field(default_factory=dict)
    intent_taxonomy: List[Dict[str, Any]] = field(default_factory=list)
    source_expansion: List[Dict[str, Any]] = field(default_factory=list)
    outreach_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    editable_fields: List[str] = field(default_factory=list)
    generator: str = "rules_v1"
    generated_at: str = field(default_factory=utc_now_iso)


@dataclass
class Checkpoint:
    id: str
    source_id: str
    creator_id: str
    last_video_id: str = ""
    last_checked_at: Optional[str] = None
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class CampaignFunnel:
    campaign_id: str = ""
    campaign_input: str = ""
    campaign_type: str = ""
    batch_id: str = ""
    batch_status: str = ""
    target_sources: int = 0
    profile_ok: int = 0
    page_opened: int = 0
    content_found: int = 0
    comment_users: int = 0
    dedup_users: int = 0
    high_intent: int = 0
    customer_leads: int = 0
    outreach_actions: int = 0
    preflight_ok: int = 0
    execution_success: int = 0
    failed: int = 0
    account_switches: int = 0
    error_counts: Dict[str, int] = field(default_factory=dict)
    generated_at: str = field(default_factory=utc_now_iso)


@dataclass
class GrowthReport:
    id: str
    generated_at: str
    summary: Dict[str, Any]
    top_videos: List[Dict[str, Any]]
    top_topic_contents: List[Dict[str, Any]]
    top_keywords: List[Dict[str, Any]]
    high_value_users: List[Dict[str, Any]]
    operation_actions: List[Dict[str, Any]]
    errors: Dict[str, int]
    recommendations: List[str]
    content_insights: List[Dict[str, Any]] = field(default_factory=list)
    comment_intents: List[Dict[str, Any]] = field(default_factory=list)
    comment_languages: List[Dict[str, Any]] = field(default_factory=list)
    comment_quality: Dict[str, Any] = field(default_factory=dict)
    lead_tiers: Dict[str, int] = field(default_factory=dict)
    change_summary: Dict[str, Any] = field(default_factory=dict)
    next_actions: List[Dict[str, Any]] = field(default_factory=list)
    source_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    creator_segments: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    source_paths: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class GrowthTaskConfig:
    platform: str = "tiktok"
    max_creators_per_profile: int = 10
    max_videos_per_creator: int = 20
    max_comments_per_video: int = 50
    min_views: int = 0
    min_comments: int = 0
    target_mode: str = "topic_growth"
    vertical: str = "general"
    enable_action_queue: bool = True
    enable_comment_queue: bool = True
    enable_follow_queue: bool = True
    enable_dm_queue: bool = True
    task_delay_min_seconds: int = 30
    task_delay_max_seconds: int = 90
    comment_retry_attempts: int = 2
    failure_cooldown_threshold: int = 3
    profile_group: str = ""
    campaign_id: str = ""
    intent_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    test_mode: bool = False
    retry_empty_result_with_next_profile: bool = True


@dataclass
class GrowthTaskResult:
    report: Optional[GrowthReport]
    report_json_path: str = ""
    report_csv_path: str = ""
    report_markdown_path: str = ""
    processed_sources: int = 0
    errors: Dict[str, int] = field(default_factory=dict)
