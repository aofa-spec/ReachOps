# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GrowthOpsSnapshot:
    summary: Dict[str, int] = field(default_factory=dict)
    campaign_funnel: Dict[str, Any] = field(default_factory=dict)
    campaigns: List[Dict[str, Any]] = field(default_factory=list)
    audience_personas: List[Dict[str, Any]] = field(default_factory=list)
    acquisition_sources: List[Dict[str, Any]] = field(default_factory=list)
    report_summary: Dict[str, Any] = field(default_factory=dict)
    lead_tiers: Dict[str, int] = field(default_factory=dict)
    comment_quality: Dict[str, Any] = field(default_factory=dict)
    action_review_summary: Dict[str, Any] = field(default_factory=dict)
    execution_readiness_summary: Dict[str, Any] = field(default_factory=dict)
    operational_status: Dict[str, Any] = field(default_factory=dict)
    source_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    next_actions: List[Dict[str, Any]] = field(default_factory=list)
    content_insights: List[Dict[str, Any]] = field(default_factory=list)
    report_brief: str = ""
    report_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    scheduled_scans: List[Dict[str, Any]] = field(default_factory=list)
    collection_batches: List[Dict[str, Any]] = field(default_factory=list)
    collection_tasks: List[Dict[str, Any]] = field(default_factory=list)
    profile_health: List[Dict[str, Any]] = field(default_factory=list)
    profile_recommendations: List[Dict[str, Any]] = field(default_factory=list)
    creators: List[Dict[str, Any]] = field(default_factory=list)
    top_contents: List[Dict[str, Any]] = field(default_factory=list)
    candidate_users: List[Dict[str, Any]] = field(default_factory=list)
    high_value_users: List[Dict[str, Any]] = field(default_factory=list)
    operation_leads: List[Dict[str, Any]] = field(default_factory=list)
    action_queue: List[Dict[str, Any]] = field(default_factory=list)
    execution_plans: List[Dict[str, Any]] = field(default_factory=list)
    executions: List[Dict[str, Any]] = field(default_factory=list)
    action_templates: List[Dict[str, Any]] = field(default_factory=list)
    exclusions: List[Dict[str, Any]] = field(default_factory=list)
    daily_quota: List[Dict[str, Any]] = field(default_factory=list)
    rate_limits: List[Dict[str, Any]] = field(default_factory=list)
    filter_presets: List[Dict[str, Any]] = field(default_factory=list)
    error_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)


def status_label(status: str) -> str:
    labels = {
        "pending_review": "待复核",
        "approved": "已批准",
        "rejected": "已拒绝",
        "completed": "已完成",
        "failed": "失败",
        "skipped": "已跳过",
        "running": "运行中",
        "pending": "待执行",
        "success": "成功",
        "account_switched": "已换号",
        "healthy": "健康",
        "degraded": "降级",
        "cooldown": "冷却",
        "partial_failed": "部分失败",
        "retryable": "可重试",
        "active": "启用",
        "paused": "已暂停",
    }
    return labels.get(status or "", status or "未知")
