# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from ReachOps.intelligence.service import GrowthIntelligenceService
from ReachOps.intelligence.schemas import CampaignFunnel, utc_now_iso

from .action_queue_service import ActionQueueService
from .action_router import ActionRouter, ActionRouterConfig, FixtureActionExecutor, PlatformActionExecutor as RoutedPlatformActionExecutor
from .error_diagnostics import ErrorDiagnosticService
from .execution_controller import ExecutionMVPConfig, ExecutionMVPController, FixturePlatformActionExecutor, PlatformActionExecutor
from .execution_reporter import ExecutionReport
from .execution_guard import ExecutionGuard
from .outreach_executor import OutreachExecutor
from .outreach_policy import OutreachPolicy
from .task_scheduler import GrowthTaskScheduler
from .view_models import GrowthOpsSnapshot


class GrowthWorkflowService:
    def __init__(self, intelligence_service: GrowthIntelligenceService, policy: OutreachPolicy | None = None):
        self.intelligence_service = intelligence_service
        self.storage = intelligence_service.storage
        self.policy = policy or OutreachPolicy()
        self.action_queue = ActionQueueService(self.storage)
        self.executor = OutreachExecutor(self.storage, ExecutionGuard(self.policy))
        self.scheduler = GrowthTaskScheduler(intelligence_service)
        self.error_diagnostics = ErrorDiagnosticService(self.storage)
        self.execution_reporter = ExecutionReport(self.storage, intelligence_service.report_dir)

    def build_snapshot(self, campaign_id: str = "", batch_id: str = "") -> GrowthOpsSnapshot:
        report = self.intelligence_service.router.reporter.build_report()
        campaign_id = str(campaign_id or "")
        campaign = {}
        if campaign_id:
            campaign = next((row for row in self.storage.list_campaigns(limit=200) if row.get("id") == campaign_id), {})
        if not campaign:
            campaign = self.storage.latest_campaign()
            campaign_id = str(campaign.get("id") or "")
        current_batch_id = str(batch_id or self._campaign_batch_id(campaign_id))
        if campaign_id and not current_batch_id:
            current_batch_id = "__no_batch__"
        return GrowthOpsSnapshot(
            summary={
                "data_sources": self.storage.count_table("data_sources"),
                "creators": self.storage.count_table("discovered_creators"),
                "contents": self.storage.count_table("discovered_contents"),
                "topic_contents": self.storage.count_table("shop_contents"),
                "candidates": self.storage.count_table("candidate_users"),
                "operation_leads": self.storage.count_table("operation_leads"),
                "action_queue": self.storage.count_table("action_queue"),
                "execution_plans": self.storage.count_table("execution_plans"),
                "outreach_executions": self.storage.count_table("outreach_executions"),
                "collection_batches": self.storage.count_table("collection_batches"),
                "collection_tasks": self.storage.count_table("collection_tasks"),
                "profile_health": self.storage.count_table("profile_health"),
                "scheduled_scans": self.storage.count_table("scheduled_scans"),
                "action_templates": self.storage.count_table("action_templates"),
                "exclusions": self.storage.count_table("exclusion_rules"),
                "daily_quota": self.storage.count_table("outreach_daily_quota"),
                "rate_limits": self.storage.count_table("outreach_rate_limits"),
                "filter_presets": self.storage.count_table("growth_filter_presets"),
                "error_diagnostics": len(self.error_diagnostics.build_diagnostics()),
                "campaigns": self.storage.count_table("acquisition_campaigns"),
                "acquisition_sources": self.storage.count_table("acquisition_sources"),
            },
            campaign_funnel=self.build_campaign_funnel(campaign_id=campaign_id, batch_id=current_batch_id if current_batch_id != "__no_batch__" else ""),
            campaigns=self.storage.list_campaigns(limit=50),
            audience_personas=self.storage.list_audience_personas(limit=50),
            acquisition_sources=self.storage.list_acquisition_sources(limit=200),
            report_summary=report.summary,
            lead_tiers=report.lead_tiers,
            comment_quality=report.comment_quality,
            action_review_summary=self._action_review_summary(current_batch_id),
            execution_readiness_summary=self._execution_readiness_summary(current_batch_id),
            operational_status=self._build_operational_status(report),
            source_recommendations=self._build_source_recommendations(report),
            next_actions=report.next_actions,
            content_insights=report.content_insights,
            report_brief=self._build_report_brief(report),
            report_artifacts=self.latest_report_artifacts(),
            sources=[source.__dict__ for source in self.storage.recent_sources()],
            scheduled_scans=self.storage.list_scheduled_scans(),
            collection_batches=self.storage.list_collection_batches(),
            collection_tasks=self.storage.list_collection_tasks(),
            profile_health=self.storage.list_profile_health(),
            profile_recommendations=self._profile_recommendations(),
            top_contents=report.top_topic_contents,
            creators=[creator.__dict__ for creator in self.storage.list_creators()],
            candidate_users=self._candidate_rows(current_batch_id),
            high_value_users=report.high_value_users,
            operation_leads=self.storage.list_operation_leads(batch_id=current_batch_id),
            action_queue=self._action_rows(current_batch_id),
            execution_plans=self.storage.list_execution_plans(),
            executions=self.storage.list_outreach_executions(batch_id=current_batch_id),
            action_templates=self.storage.list_action_templates(),
            exclusions=self.storage.list_exclusions(),
            daily_quota=self.storage.list_daily_quota(),
            rate_limits=self.storage.list_rate_limits(),
            filter_presets=self.storage.list_filter_presets(),
            error_diagnostics=self.error_diagnostics.build_diagnostics(),
            errors=self.storage.error_counts(),
        )

    def build_campaign_funnel(self, campaign_id: str = "", batch_id: str = "") -> dict:
        campaign = self.storage.latest_campaign() if not campaign_id else next(
            (row for row in self.storage.list_campaigns(limit=200) if row.get("id") == campaign_id),
            {},
        )
        campaign_id = str(campaign.get("id") or campaign_id or "")
        latest_batch = self.storage.latest_collection_batch_for_campaign(campaign_id) if campaign_id else {}
        if not latest_batch and not campaign_id:
            latest_batch = (self.storage.list_collection_batches(limit=1) or [{}])[0]
        batch_id = str(batch_id or latest_batch.get("id") or "")
        batch_metrics = self.storage.collection_batch_entity_metrics(batch_id) if batch_id else {}
        progress = self.storage.collection_batch_progress(batch_id) if batch_id else {}
        execution_status_counts = self.storage.outreach_execution_status_counts(batch_id) if batch_id else {}
        batch = progress.get("batch") or latest_batch or {}
        status_counts = progress.get("status_counts") or {}
        error_counts = progress.get("error_counts") or {}
        sources = self.storage.list_acquisition_sources(campaign_id=campaign_id, limit=200) if campaign_id else []
        profile_ok = 0
        try:
            profile_ok = len([row for row in self.storage.list_profile_health(limit=1000) if str(row.get("status") or "") == "healthy"])
        except Exception:
            profile_ok = 0
        return asdict(
            CampaignFunnel(
                campaign_id=campaign_id,
                campaign_input=campaign.get("input_value", ""),
                campaign_type=campaign.get("input_type", ""),
                batch_id=batch_id,
                batch_status=batch.get("status", ""),
                target_sources=len(sources) or int(batch.get("total_sources") or 0),
                profile_ok=profile_ok,
                page_opened=int(status_counts.get("running", 0) or 0)
                + int(status_counts.get("completed", 0) or 0)
                + int(status_counts.get("failed", 0) or 0),
                content_found=int(batch_metrics.get("new_contents", 0) or 0) + int(batch_metrics.get("topic_contents", 0) or 0),
                comment_users=int(batch_metrics.get("candidate_users", 0) or 0),
                dedup_users=int(batch_metrics.get("candidate_users", 0) or 0),
                high_intent=int(batch_metrics.get("high_value_candidates", 0) or 0),
                customer_leads=int(batch_metrics.get("operation_leads", 0) or 0),
                outreach_actions=int(batch_metrics.get("action_queue", 0) or 0),
                preflight_ok=int(execution_status_counts.get("success", 0) or 0),
                execution_success=int(execution_status_counts.get("success", 0) or 0),
                failed=int(batch.get("failed_sources", 0) or 0)
                + int(batch_metrics.get("errors", 0) or 0)
                + int(execution_status_counts.get("failed", 0) or 0)
                + int(execution_status_counts.get("skipped", 0) or 0),
                account_switches=int(execution_status_counts.get("account_switched", 0) or 0),
                error_counts=error_counts,
            )
        )

    def run_action_router(
        self,
        profiles: list[dict],
        config: ActionRouterConfig | None = None,
        fixture_outcomes: list[dict] | None = None,
        platform_executor: RoutedPlatformActionExecutor | None = None,
        limit: int = 100,
        export_report: bool = True,
        campaign_id: str = "",
        batch_id: str = "",
    ) -> dict:
        router = ActionRouter(
            self.storage,
            executor=platform_executor or FixtureActionExecutor(fixture_outcomes),
        )
        config = config or ActionRouterConfig()
        if not str(config.batch_id or ""):
            if batch_id:
                config.batch_id = str(batch_id)
            elif campaign_id:
                config.batch_id = self._campaign_batch_id(str(campaign_id)) or "__no_batch__"
            else:
                config.batch_id = self._current_campaign_batch_id()
        summary = router.run(profiles, config=config, limit=limit)
        if export_report:
            summary["report"] = self.execution_reporter.export(summary, batch_id=str(config.batch_id or ""))
        return summary

    def latest_report_artifacts(self) -> list[dict]:
        report_dir = self.intelligence_service.report_dir
        os.makedirs(report_dir, exist_ok=True)
        specs = [
            ("daily_brief", "最新运营日报", lambda name: name.startswith("growth_report_") and name.endswith("_daily_brief.md")),
            ("json_report", "最新 JSON 报告", lambda name: name.startswith("growth_report_") and name.endswith(".json")),
            ("high_value_users", "高价值线索 CSV", lambda name: name.startswith("growth_report_") and name.endswith("_high_value_users.csv")),
            ("action_queue", "动作队列 CSV", lambda name: name.startswith("growth_report_") and name.endswith("_action_queue.csv")),
            ("campaign_json", "最新获客任务 JSON", lambda name: name.startswith("reachops_campaign_") and name.endswith(".json")),
            ("campaign_sources", "获客来源 CSV", lambda name: name.startswith("reachops_sources_") and name.endswith(".csv")),
            ("campaign_customers", "本轮客户 CSV", lambda name: name.startswith("reachops_customers_") and name.endswith(".csv")),
            ("campaign_actions", "本轮动作 CSV", lambda name: name.startswith("reachops_actions_") and name.endswith(".csv")),
        ]
        artifacts = []
        for kind, label, matcher in specs:
            path = self._latest_report_file(report_dir, matcher)
            artifacts.append(
                {
                    "kind": kind,
                    "label": label,
                    "path": path,
                    "updated_at": self._file_updated_at(path),
                    "exists": bool(path and os.path.exists(path)),
                }
            )
        artifacts.append(
            {
                "kind": "directory",
                "label": "报告目录",
                "path": report_dir,
                "updated_at": self._file_updated_at(report_dir),
                "exists": os.path.isdir(report_dir),
            }
        )
        return artifacts

    def export_campaign_artifacts(self, campaign_id: str = "") -> dict:
        report_dir = self.intelligence_service.report_dir
        os.makedirs(report_dir, exist_ok=True)
        campaign = self.storage.latest_campaign() if not campaign_id else next(
            (row for row in self.storage.list_campaigns(limit=200) if row.get("id") == campaign_id),
            {},
        )
        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            return {}
        persona = self.storage.get_audience_persona(campaign_id)
        sources = self.storage.list_acquisition_sources(campaign_id=campaign_id, limit=500)
        strategy = self._build_export_strategy(campaign, persona, sources)
        funnel = self.build_campaign_funnel(campaign_id=campaign_id)
        batch_id = str(funnel.get("batch_id") or "")
        batch_filter = batch_id or "__no_batch__"
        candidate_users = self.storage.list_candidates_with_content(batch_id=batch_filter)
        operation_leads = self.storage.list_operation_leads(limit=1000, batch_id=batch_filter)
        action_queue = self.storage.list_action_queue(limit=1000, batch_id=batch_filter)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        campaign_slug = "".join(ch if ch.isalnum() else "_" for ch in campaign_id)[-12:] or "campaign"
        file_key = f"{campaign_slug}_{stamp}"
        json_path = os.path.join(report_dir, f"reachops_campaign_{file_key}.json")
        sources_csv_path = os.path.join(report_dir, f"reachops_sources_{file_key}.csv")
        customers_csv_path = os.path.join(report_dir, f"reachops_customers_{file_key}.csv")
        actions_csv_path = os.path.join(report_dir, f"reachops_actions_{file_key}.csv")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "campaign": campaign,
                    "persona": persona,
                    "strategy": strategy,
                    "sources": sources,
                    "funnel": funnel,
                    "candidate_users": candidate_users,
                    "operation_leads": operation_leads,
                    "action_queue": action_queue,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        with open(sources_csv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["campaign_id", "source_type", "source_value", "reason", "priority", "status"])
            writer.writeheader()
            for row in sources:
                writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
        with open(customers_csv_path, "w", encoding="utf-8", newline="") as fh:
            fieldnames = [
                "username",
                "profile_url",
                "qualify_score",
                "intent_tags",
                "comment_text",
                "comment_likes",
                "reply_count",
                "video_url",
                "video_id",
                "caption",
                "views",
                "video_comments",
                "batch_id",
                "created_at",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in candidate_users:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        with open(actions_csv_path, "w", encoding="utf-8", newline="") as fh:
            fieldnames = [
                "target_username",
                "action_type",
                "status",
                "risk_level",
                "review_status",
                "last_error_code",
                "last_error_message",
                "suggested_text",
                "target_url",
                "batch_id",
                "created_at",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in action_queue:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        self.storage.log_event(
            "campaign_artifacts_exported",
            campaign_id,
            {
                "json_path": json_path,
                "sources_csv_path": sources_csv_path,
                "customers_csv_path": customers_csv_path,
                "actions_csv_path": actions_csv_path,
                "candidate_count": len(candidate_users),
                "action_count": len(action_queue),
            },
        )
        return {
            "json_path": json_path,
            "sources_csv_path": sources_csv_path,
            "customers_csv_path": customers_csv_path,
            "actions_csv_path": actions_csv_path,
            "csv_path": customers_csv_path,
        }

    def _build_export_strategy(self, campaign: dict, persona: dict, sources: list[dict]) -> dict:
        try:
            strategy = self.intelligence_service.build_campaign_strategy(str(campaign.get("id") or ""))
            if strategy:
                return strategy
            return {"campaign_id": str(campaign.get("id") or ""), "generator": "rules_v1"}
        except Exception as exc:
            return {"campaign_id": str(campaign.get("id") or ""), "generator": "rules_v1", "error": str(exc)}

    def _latest_report_file(self, report_dir: str, matcher) -> str:
        try:
            paths = [os.path.join(report_dir, name) for name in os.listdir(report_dir) if matcher(name)]
            paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            return paths[0] if paths else ""
        except Exception:
            return ""

    def _file_updated_at(self, path: str) -> str:
        if not path or not os.path.exists(path):
            return ""
        try:
            return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            return ""

    def _candidate_rows(self, batch_id: str = "") -> list[dict]:
        rows = self.storage.list_candidates_with_content(batch_id=batch_id or self._current_campaign_batch_id())
        rows = sorted(rows, key=lambda row: int(row.get("qualify_score") or 0), reverse=True)
        for row in rows:
            row["profile_completed"] = "是" if row.get("author_profile_completed") else "否"
            row["source"] = row.get("source_path") or row.get("video_url") or row.get("content_source_path") or ""
            row["creator_vertical"] = row.get("creator_vertical") or "general"
        return rows[:300]

    def _action_rows(self, batch_id: str = "") -> list[dict]:
        rows = self.storage.list_action_queue(batch_id=batch_id or self._current_campaign_batch_id())
        profile = self._recommended_execution_profile()
        for row in rows:
            readiness = self._evaluate_action_readiness(row, profile)
            row["public_status"] = self._public_action_status(str(row.get("status") or ""))
            row.update(readiness)
        return rows

    def _current_campaign_batch_id(self) -> str:
        campaign = self.storage.latest_campaign()
        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            return ""
        return self._campaign_batch_id(campaign_id) or "__no_batch__"

    def _campaign_batch_id(self, campaign_id: str) -> str:
        if not campaign_id:
            return ""
        batch = self.storage.latest_collection_batch_for_campaign(campaign_id)
        return str(batch.get("id") or "")

    def _public_action_status(self, status: str) -> str:
        value = str(status or "")
        if value == "completed":
            return "success"
        if value in {"retryable", "rejected"}:
            return "failed"
        if value in {"pending_review", "approved"}:
            return "pending"
        if value in {"pending", "running", "success", "failed", "skipped", "account_switched"}:
            return value
        return "pending"

    def _profile_recommendations(self) -> list[dict]:
        rows = self.storage.list_profile_health(limit=1000)
        status_rank = {"healthy": 0, "degraded": 1, "cooldown": 2}
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            group = str(row.get("group_name") or "default")
            grouped.setdefault(group, []).append(row)
        recommendations = []
        for group, items in sorted(grouped.items()):
            ordered = sorted(
                items,
                key=lambda row: (
                    status_rank.get(str(row.get("status") or "healthy"), 1),
                    -int(row.get("health_score") or 0),
                    int(row.get("consecutive_failures") or 0),
                    str(row.get("profile_id") or ""),
                ),
            )
            best = ordered[0] if ordered else {}
            healthy_count = len([row for row in items if row.get("status") == "healthy"])
            degraded_count = len([row for row in items if row.get("status") == "degraded"])
            cooldown_count = len([row for row in items if row.get("status") == "cooldown"])
            reason = "优先使用健康 Profile"
            if best.get("status") == "degraded":
                reason = "无完全健康 Profile，建议低频使用并观察错误"
            if best.get("status") == "cooldown":
                reason = "该分组处于冷却风险，建议暂缓或更换分组"
            recommendations.append(
                {
                    "group_name": group,
                    "recommended_profile_id": best.get("profile_id", ""),
                    "status": best.get("status", ""),
                    "health_score": best.get("health_score", 0),
                    "consecutive_failures": best.get("consecutive_failures", 0),
                    "healthy_count": healthy_count,
                    "degraded_count": degraded_count,
                    "cooldown_count": cooldown_count,
                    "reason": reason,
                    "last_error_code": best.get("last_error_code", ""),
                }
            )
        return recommendations

    def _action_review_summary(self, batch_id: str = "") -> dict:
        rows = self.storage.list_action_queue(limit=1000, batch_id=batch_id or self._current_campaign_batch_id())
        action_type_counts: dict[str, int] = {}
        risk_counts: dict[str, int] = {}
        pending_review_count = 0
        approved_count = 0
        rejected_count = 0
        ready_to_execute_count = 0
        high_risk_count = 0
        retryable_count = 0
        failed_count = 0
        confirmed_count = 0
        for row in rows:
            status = str(row.get("status") or "")
            review_status = str(row.get("review_status") or "")
            risk_level = str(row.get("risk_level") or "unknown")
            action_type = str(row.get("action_type") or "unknown")
            execution_confirmed = bool(row.get("execution_confirmed"))
            action_type_counts[action_type] = action_type_counts.get(action_type, 0) + 1
            risk_counts[risk_level] = risk_counts.get(risk_level, 0) + 1
            if status == "pending_review" or review_status == "pending":
                pending_review_count += 1
            if status == "approved" or review_status == "approved":
                approved_count += 1
            if status == "rejected" or review_status == "rejected":
                rejected_count += 1
            if risk_level == "high":
                high_risk_count += 1
            if status == "retryable":
                retryable_count += 1
            if status == "failed":
                failed_count += 1
            if execution_confirmed:
                confirmed_count += 1
            if status == "approved" and execution_confirmed:
                ready_to_execute_count += 1

        next_operator_action = "暂无待处理动作"
        if pending_review_count:
            next_operator_action = "先审核待复核动作"
        elif approved_count > ready_to_execute_count:
            next_operator_action = "对已批准动作做执行前确认"
        elif ready_to_execute_count:
            next_operator_action = "可执行已确认动作"
        elif retryable_count or failed_count:
            next_operator_action = "处理失败/可重试动作"

        return {
            "total": len(rows),
            "pending_review_count": pending_review_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "ready_to_execute_count": ready_to_execute_count,
            "confirmed_count": confirmed_count,
            "high_risk_count": high_risk_count,
            "retryable_count": retryable_count,
            "failed_count": failed_count,
            "action_type_counts": [
                {"action_type": key, "count": value}
                for key, value in sorted(action_type_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "risk_counts": [
                {"risk_level": key, "count": value}
                for key, value in sorted(risk_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "next_operator_action": next_operator_action,
        }

    def _execution_readiness_summary(self, batch_id: str = "") -> dict:
        rows = self.storage.list_action_queue(limit=1000, batch_id=batch_id or self._current_campaign_batch_id())
        profile = self._recommended_execution_profile()
        profile_id = str(profile.get("profile_id") or "")
        ready_count = 0
        blocked_count = 0
        excluded_count = 0
        quota_blocked_count = 0
        confirmation_required_count = 0
        high_risk_ready_count = 0
        reason_counts: dict[str, int] = {}
        action_type_ready: dict[str, int] = {}
        for row in rows:
            readiness = self._evaluate_action_readiness(row, profile)
            allowed = readiness["readiness_status"] == "ready"
            reason = readiness["block_reason"]
            if allowed:
                ready_count += 1
                action_type = str(row.get("action_type") or "unknown")
                action_type_ready[action_type] = action_type_ready.get(action_type, 0) + 1
                if row.get("risk_level") == "high":
                    high_risk_ready_count += 1
                continue
            blocked_count += 1
            reason = reason or "UNKNOWN_BLOCK"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if reason == "TARGET_EXCLUDED":
                excluded_count += 1
            if reason == "DAILY_QUOTA_EXCEEDED":
                quota_blocked_count += 1
            if reason == "ACTION_REQUIRES_EXECUTION_CONFIRMATION":
                confirmation_required_count += 1

        top_block_reason = ""
        if reason_counts:
            top_block_reason = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        next_execution_action = "暂无可执行动作"
        if ready_count:
            next_execution_action = "可执行已确认动作"
        elif confirmation_required_count:
            next_execution_action = "先做执行前二次确认"
        elif quota_blocked_count:
            next_execution_action = "等待配额恢复或更换 Profile"
        elif excluded_count:
            next_execution_action = "复核排除名单命中目标"
        elif top_block_reason:
            next_execution_action = f"处理阻断原因: {top_block_reason}"

        return {
            "profile_id": profile_id,
            "profile_status": profile.get("status", ""),
            "total": len(rows),
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "excluded_count": excluded_count,
            "quota_blocked_count": quota_blocked_count,
            "confirmation_required_count": confirmation_required_count,
            "high_risk_ready_count": high_risk_ready_count,
            "top_block_reason": top_block_reason,
            "next_execution_action": next_execution_action,
            "reason_counts": [
                {"reason": key, "count": value}
                for key, value in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "action_type_ready": [
                {"action_type": key, "count": value}
                for key, value in sorted(action_type_ready.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    def _evaluate_action_readiness(self, row: dict, profile: dict | None = None) -> dict:
        profile = profile or self._recommended_execution_profile()
        profile_id = str(profile.get("profile_id") or "")
        quota_used = 0
        quota_limit = self.policy.max_actions_per_profile_day
        quota_remaining = quota_limit
        excluded = self.storage.is_target_excluded(row.get("target_username", ""), row.get("target_url", ""))
        if excluded:
            allowed = False
            reason = "TARGET_EXCLUDED"
        else:
            allowed, reason = self.executor.guard.check(row, profile_id, profile_state=self._profile_state_from_health(profile))
        if allowed:
            quota_ok, quota_used, quota_limit = self.storage.check_daily_quota(
                profile_id,
                str(row.get("action_type") or ""),
                self.policy.max_actions_per_profile_day,
            )
            quota_remaining = max(0, int(quota_limit or 0) - int(quota_used or 0))
            if not quota_ok:
                allowed = False
                reason = "DAILY_QUOTA_EXCEEDED"
                quota_remaining = 0
        return {
            "readiness_status": "ready" if allowed else "blocked",
            "block_reason": "" if allowed else reason or "UNKNOWN_BLOCK",
            "recommended_profile_id": profile_id,
            "recommended_profile_status": profile.get("status", ""),
            "quota_used": quota_used,
            "quota_limit": quota_limit,
            "quota_remaining": quota_remaining,
        }

    def _recommended_execution_profile(self) -> dict:
        rows = self.storage.list_profile_health(limit=1000)
        if not rows:
            return {}
        status_rank = {"healthy": 0, "degraded": 1, "cooldown": 2}
        return sorted(
            rows,
            key=lambda row: (
                status_rank.get(str(row.get("status") or "healthy"), 1),
                -int(row.get("health_score") or 0),
                int(row.get("consecutive_failures") or 0),
                str(row.get("profile_id") or ""),
            ),
        )[0]

    def _profile_state_from_health(self, profile: dict) -> dict:
        error_code = str(profile.get("last_error_code") or "")
        status = str(profile.get("status") or "")
        return {
            "login_required": error_code == "LOGIN_REQUIRED",
            "captcha_detected": error_code == "CAPTCHA_DETECTED",
            "proxy_failed": error_code == "PROXY_FAILED",
            "cooldown": status == "cooldown",
        }

    def filter_candidate_rows(
        self,
        rows: list[dict],
        tier: str = "all",
        language: str = "all",
        profile_completed: str = "all",
        keyword: str = "",
    ) -> list[dict]:
        keyword = str(keyword or "").strip().lower()
        filtered = []
        for row in rows or []:
            score = int(row.get("qualify_score") or 0)
            if tier == "high" and score < 70:
                continue
            if tier == "observe" and not (40 <= score < 70):
                continue
            if tier == "low" and score >= 40:
                continue
            if language != "all" and str(row.get("comment_language") or "unknown") != language:
                continue
            completed = bool(row.get("author_profile_completed")) or str(row.get("profile_completed") or "") == "是"
            if profile_completed == "yes" and not completed:
                continue
            if profile_completed == "no" and completed:
                continue
            haystack = " ".join(
                [
                    str(row.get("username") or ""),
                    str(row.get("comment_text") or ""),
                    str(row.get("intent_tags") or ""),
                    str(row.get("video_url") or ""),
                ]
            ).lower()
            if keyword and keyword not in haystack:
                continue
            filtered.append(row)
        return filtered

    def filter_action_rows(
        self,
        rows: list[dict],
        status: str = "all",
        risk_level: str = "all",
        review_status: str = "all",
        block_reason: str = "all",
        keyword: str = "",
    ) -> list[dict]:
        keyword = str(keyword or "").strip().lower()
        filtered = []
        public_statuses = {"pending", "running", "success", "failed", "skipped", "account_switched"}
        for row in rows or []:
            if status != "all":
                if status in public_statuses:
                    if str(row.get("public_status") or self._public_action_status(str(row.get("status") or ""))) != status:
                        continue
                elif str(row.get("status") or "") != status:
                    continue
            if risk_level != "all" and str(row.get("risk_level") or "") != risk_level:
                continue
            if review_status != "all" and str(row.get("review_status") or "") != review_status:
                continue
            if block_reason != "all" and str(row.get("block_reason") or "") != block_reason:
                continue
            haystack = " ".join(
                [
                    str(row.get("action_type") or ""),
                    str(row.get("target_username") or ""),
                    str(row.get("suggested_text") or ""),
                    str(row.get("reason") or ""),
                    str(row.get("last_error_code") or ""),
                    str(row.get("block_reason") or ""),
                    str(row.get("readiness_status") or ""),
                ]
            ).lower()
            if keyword and keyword not in haystack:
                continue
            filtered.append(row)
        return filtered

    def build_bulk_confirmation_preview(self, action_ids: list[str]) -> dict:
        selected_ids = self._unique_action_ids(action_ids)
        selected_set = set(selected_ids)
        profile = self._recommended_execution_profile()
        rows = []
        for row in self.storage.list_action_queue(limit=1000):
            if row.get("id") in selected_set:
                enriched = dict(row)
                enriched.update(self._evaluate_action_readiness(enriched, profile))
                rows.append(enriched)

        reason_counts: dict[str, int] = {}
        post_confirm_reason_counts: dict[str, int] = {}
        high_risk_count = 0
        unapproved_count = 0
        ready_now_count = 0
        ready_after_confirmation_count = 0
        for row in rows:
            if row.get("risk_level") == "high":
                high_risk_count += 1
            if row.get("status") != "approved":
                unapproved_count += 1
            if row.get("readiness_status") == "ready":
                ready_now_count += 1
            reason = str(row.get("block_reason") or "")
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            simulated = dict(row)
            if simulated.get("status") == "approved":
                simulated["execution_confirmed"] = 1
            post = self._evaluate_action_readiness(simulated, profile)
            if post["readiness_status"] == "ready":
                ready_after_confirmation_count += 1
            else:
                post_reason = post["block_reason"] or "UNKNOWN_BLOCK"
                post_confirm_reason_counts[post_reason] = post_confirm_reason_counts.get(post_reason, 0) + 1

        post_confirm_blocked_count = len(rows) - ready_after_confirmation_count
        quota_summary = self._profile_quota_summary(profile, rows)
        requires_attention = bool(high_risk_count or unapproved_count or post_confirm_blocked_count)
        warnings = []
        if high_risk_count:
            warnings.append(f"{high_risk_count} 个高风险动作")
        if unapproved_count:
            warnings.append(f"{unapproved_count} 个动作尚未批准")
        if post_confirm_blocked_count:
            top_reason = sorted(post_confirm_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            warnings.append(f"{post_confirm_blocked_count} 个动作确认后仍会被阻断: {top_reason}")
        for item in quota_summary:
            if item["demand_after_confirmation"] > item["remaining"]:
                warnings.append(
                    f"{item['profile_id']} 的 {item['action_type']} 配额不足: 需要 {item['demand_after_confirmation']} / 剩余 {item['remaining']}"
                )

        preview = {
            "selected_count": len(rows),
            "missing_count": max(0, len(selected_ids) - len(rows)),
            "approved_count": len([row for row in rows if row.get("status") == "approved"]),
            "unapproved_count": unapproved_count,
            "high_risk_count": high_risk_count,
            "ready_now_count": ready_now_count,
            "ready_after_confirmation_count": ready_after_confirmation_count,
            "post_confirm_blocked_count": post_confirm_blocked_count,
            "requires_attention": requires_attention,
            "recommended_profile_id": profile.get("profile_id", ""),
            "reason_counts": [
                {"reason": key, "count": value}
                for key, value in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "post_confirm_reason_counts": [
                {"reason": key, "count": value}
                for key, value in sorted(post_confirm_reason_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "warnings": warnings,
            "template_previews": self.build_action_template_preview(selected_ids, limit=5),
            "profile_quota_summary": quota_summary,
        }
        self.storage.log_event("bulk_confirmation_previewed", "", preview)
        return preview

    def _profile_quota_summary(self, profile: dict, rows: list[dict]) -> list[dict]:
        profile_id = str(profile.get("profile_id") or "")
        grouped: dict[str, dict] = {}
        for row in rows:
            action_type = str(row.get("action_type") or "unknown")
            bucket = grouped.setdefault(
                action_type,
                {
                    "profile_id": profile_id,
                    "action_type": action_type,
                    "selected_count": 0,
                    "ready_now_count": 0,
                    "demand_after_confirmation": 0,
                },
            )
            bucket["selected_count"] += 1
            if row.get("readiness_status") == "ready":
                bucket["ready_now_count"] += 1
            simulated = dict(row)
            if simulated.get("status") == "approved":
                simulated["execution_confirmed"] = 1
            post = self._evaluate_action_readiness(simulated, profile)
            if post["readiness_status"] == "ready":
                bucket["demand_after_confirmation"] += 1

        summary = []
        for action_type, bucket in sorted(grouped.items()):
            _quota_ok, used, limit = self.storage.check_daily_quota(
                profile_id,
                action_type,
                self.policy.max_actions_per_profile_day,
            )
            remaining = max(0, int(limit or 0) - int(used or 0))
            item = dict(bucket)
            item.update({"used": used, "limit": limit, "remaining": remaining})
            item["will_exceed"] = int(item["demand_after_confirmation"]) > remaining
            summary.append(item)
        return summary

    def build_action_template_preview(self, action_ids: list[str], limit: int = 5) -> list[dict]:
        selected_ids = set(self._unique_action_ids(action_ids))
        if not selected_ids:
            return []
        templates = self._active_template_map()
        previews = []
        for row in self.storage.list_action_queue(limit=1000):
            if row.get("id") not in selected_ids:
                continue
            action_type = str(row.get("action_type") or "")
            template = templates.get(action_type, {})
            template_body = str(template.get("body") or "")
            values = {
                "username": row.get("target_username", ""),
                "lead_type": row.get("lead_type", ""),
                "target_url": row.get("target_url", ""),
            }
            rendered_text = self._render_preview_template(template_body, values) if template_body else str(row.get("suggested_text") or "")
            suggested_text = str(row.get("suggested_text") or "")
            previews.append(
                {
                    "action_id": row.get("id", ""),
                    "action_type": action_type,
                    "target_username": row.get("target_username", ""),
                    "template_name": template.get("name", ""),
                    "template_body": template_body,
                    "rendered_text": rendered_text,
                    "suggested_text": suggested_text,
                    "matches_suggested": rendered_text == suggested_text,
                }
            )
            if len(previews) >= int(limit or 5):
                break
        return previews

    def _active_template_map(self) -> dict:
        templates = {}
        rows = sorted(
            self.storage.list_action_templates(limit=500),
            key=lambda row: (
                0 if str(row.get("name") or "").startswith("默认") else 1,
                str(row.get("created_at") or ""),
            ),
            reverse=True,
        )
        for row in rows:
            if row.get("status") != "active":
                continue
            action_type = str(row.get("action_type") or "")
            if action_type and action_type not in templates:
                templates[action_type] = row
        return templates

    def _render_preview_template(self, body: str, values: dict) -> str:
        try:
            return str(body or "").format(**{key: value or "" for key, value in values.items()})
        except Exception:
            return str(body or "")

    def build_execution_plan(self, action_ids: list[str], profile_id: str = "", limit: int = 50) -> dict:
        selected_ids = self._unique_action_ids(action_ids)
        selected_set = set(selected_ids)
        profile = self._recommended_execution_profile()
        if profile_id:
            profile = dict(profile)
            profile["profile_id"] = profile_id
            profile.setdefault("status", "healthy")
        plan_profile_id = str(profile.get("profile_id") or "")
        rows = []
        for row in self.storage.list_action_queue(limit=1000):
            if row.get("id") in selected_set:
                rows.append(dict(row))
            if len(rows) >= int(limit or 50):
                break

        quota_usage: dict[str, dict] = {}
        items = []
        executable_count = 0
        skipped_count = 0
        for row in rows:
            readiness = self._evaluate_action_readiness(row, profile)
            action_type = str(row.get("action_type") or "unknown")
            quota = quota_usage.get(action_type)
            if not quota:
                _quota_ok, used, quota_limit = self.storage.check_daily_quota(
                    plan_profile_id,
                    action_type,
                    self.policy.max_actions_per_profile_day,
                )
                quota = {"used": used, "limit": quota_limit, "planned": 0}
                quota_usage[action_type] = quota

            status = "will_execute"
            skip_reason = ""
            if readiness["readiness_status"] != "ready":
                status = "skipped"
                skip_reason = readiness["block_reason"]
            elif int(quota["used"]) + int(quota["planned"]) >= int(quota["limit"]):
                status = "skipped"
                skip_reason = "DAILY_QUOTA_EXCEEDED_IN_PLAN"

            if status == "will_execute":
                executable_count += 1
                quota["planned"] += 1
            else:
                skipped_count += 1

            items.append(
                {
                    "action_id": row.get("id", ""),
                    "action_type": action_type,
                    "target_username": row.get("target_username", ""),
                    "profile_id": plan_profile_id,
                    "status": status,
                    "skip_reason": skip_reason,
                    "risk_level": row.get("risk_level", ""),
                    "suggested_text": row.get("suggested_text", ""),
                }
            )

        quota_summary = []
        for action_type, quota in sorted(quota_usage.items()):
            remaining_before = max(0, int(quota["limit"]) - int(quota["used"]))
            remaining_after = max(0, remaining_before - int(quota["planned"]))
            quota_summary.append(
                {
                    "profile_id": plan_profile_id,
                    "action_type": action_type,
                    "used": quota["used"],
                    "limit": quota["limit"],
                    "planned": quota["planned"],
                    "remaining_before": remaining_before,
                    "remaining_after": remaining_after,
                }
            )

        plan = {
            "profile_id": plan_profile_id,
            "selected_count": len(selected_ids),
            "planned_count": len(items),
            "missing_count": max(0, len(selected_ids) - len(items)),
            "executable_count": executable_count,
            "skipped_count": skipped_count,
            "items": items,
            "quota_summary": quota_summary,
        }
        plan_id = self.storage.save_execution_plan(plan)
        plan["plan_id"] = plan_id
        self.storage.log_event("execution_plan_built", "", {key: value for key, value in plan.items() if key != "items"})
        return plan

    def export_execution_plan(self, action_ids: list[str], profile_id: str = "", limit: int = 50) -> str:
        plan = self.build_execution_plan(action_ids, profile_id=profile_id, limit=limit)
        report_dir = self.intelligence_service.report_dir
        os.makedirs(report_dir, exist_ok=True)
        stamp = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "")
        path = os.path.join(report_dir, f"growth_ops_execution_plan_{stamp}.json")
        plan["export_path"] = path
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        self.storage.update_execution_plan_export_path(str(plan.get("plan_id") or ""), path)
        self.storage.log_event(
            "execution_plan_exported",
            "",
            {"path": path, "selected_count": plan.get("selected_count", 0), "executable_count": plan.get("executable_count", 0)},
        )
        return path

    def execute_plan_dry_run(self, plan_id: str, limit: int = 50) -> dict:
        stored = self.storage.get_execution_plan(plan_id)
        if not stored:
            return {"plan_id": plan_id, "status": "not_found", "executed_count": 0, "skipped_count": 0, "results": []}
        plan = stored.get("plan") or {}
        profile_id = str(plan.get("profile_id") or stored.get("profile_id") or "")
        executable_items = [item for item in plan.get("items", []) if item.get("status") == "will_execute"]
        action_ids = {item.get("action_id") for item in executable_items[: max(0, int(limit or 50))]}
        action_by_id = {row.get("id"): row for row in self.storage.list_action_queue(limit=1000) if row.get("id") in action_ids}
        results = []
        for item in executable_items[: max(0, int(limit or 50))]:
            action = action_by_id.get(item.get("action_id"))
            if not action:
                results.append({"action_id": item.get("action_id", ""), "status": "skipped", "error_code": "ACTION_NOT_FOUND"})
                continue
            results.append(self.executor.execute_action(action, profile_id=profile_id, dry_run=True))
        skipped_count = int(plan.get("skipped_count") or 0) + len([result for result in results if result.get("status") == "skipped"])
        executed_count = len([result for result in results if result.get("status") == "completed"])
        status = "completed"
        if not results and skipped_count:
            status = "skipped"
        elif skipped_count:
            status = "partial"
        execution_result = {
            "plan_id": stored.get("id", plan_id),
            "status": status,
            "profile_id": profile_id,
            "executed_count": executed_count,
            "skipped_count": skipped_count,
            "results": results,
        }
        self.storage.update_execution_plan_status(str(stored.get("id") or plan_id), status, execution_result)
        self.storage.log_event("execution_plan_executed", str(stored.get("id") or plan_id), execution_result)
        return execution_result

    def export_filtered_rows(self, kind: str, rows: list[dict], filters: dict | None = None) -> str:
        kind = str(kind or "").strip() or "rows"
        safe_kind = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in kind)[:40]
        report_dir = self.intelligence_service.report_dir
        os.makedirs(report_dir, exist_ok=True)
        stamp = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "")
        path = os.path.join(report_dir, f"growth_ops_{safe_kind}_filtered_{stamp}.csv")
        fieldnames = self._export_fieldnames(kind, rows)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows or []:
                writer.writerow({key: self._csv_value(row.get(key, "")) for key in fieldnames})
        self.storage.log_event(
            "growth_ops_filtered_exported",
            "",
            {"kind": kind, "row_count": len(rows or []), "path": path, "filters": filters or {}},
        )
        return path

    def save_filter_preset(self, view_name: str, name: str, filters: dict) -> str:
        return self.storage.upsert_filter_preset(view_name, name, filters or {})

    def load_filter_preset(self, view_name: str, name: str) -> dict:
        preset = self.storage.get_filter_preset(view_name, name)
        return dict((preset or {}).get("filters") or {})

    def list_filter_presets(self, view_name: str = "") -> list[dict]:
        return self.storage.list_filter_presets(view_name=view_name)

    def _unique_action_ids(self, action_ids: list[str]) -> list[str]:
        seen = set()
        unique = []
        for action_id in action_ids or []:
            item = str(action_id or "").strip()
            if item and item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    def _export_fieldnames(self, kind: str, rows: list[dict]) -> list[str]:
        if kind == "candidate_users":
            return [
                "username",
                "profile_url",
                "qualify_score",
                "status",
                "intent_tags",
                "comment_language",
                "profile_completed",
                "comment_text",
                "video_url",
                "source",
                "creator_vertical",
            ]
        if kind == "action_queue":
            return [
                "action_type",
                "target_username",
                "target_url",
                "public_status",
                "status",
                "review_status",
                "execution_confirmed",
                "readiness_status",
                "block_reason",
                "recommended_profile_id",
                "quota_remaining",
                "retry_count",
                "last_error_code",
                "risk_level",
                "lead_score",
                "reason",
                "suggested_text",
            ]
        keys = []
        for row in rows or []:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
        return keys or ["empty"]

    def _csv_value(self, value):
        if isinstance(value, (list, dict)):
            import json

            return json.dumps(value, ensure_ascii=False)
        return value

    def _build_report_brief(self, report) -> str:
        lead_next_step = self._build_lead_next_step(report)
        lines = [
            "GrowthOps 运营简报",
            f"数据源: {report.summary.get('datasource_count', 0)}",
            f"内容/素材: {report.summary.get('new_content_count', 0) + report.summary.get('topic_content_count', 0)}",
            f"CandidateUser: {report.summary.get('candidate_user_count', 0)}",
            f"高价值线索: {report.summary.get('high_value_candidate_count', 0)}",
            f"动作队列: {report.summary.get('action_queue_count', 0)}",
            "",
            "线索分层",
            f"高价值={report.lead_tiers.get('high', 0)} / 可观察={report.lead_tiers.get('observe', 0)} / 低价值={report.lead_tiers.get('low', 0)}",
            "",
            "评论质量",
            f"主页补全率={report.comment_quality.get('profile_completed_rate', 0)}",
            f"最大可见节点={report.comment_quality.get('max_visible_nodes', 0)}",
            f"最大滚动轮次={report.comment_quality.get('max_scroll_rounds', 0)}",
            "",
            "线索下一步",
            lead_next_step,
        ]
        if report.comment_languages:
            lines.extend(
                [
                    "",
                    "语言分布",
                    ", ".join([f"{item.get('language')}={item.get('count')}" for item in report.comment_languages[:8]]),
                ]
            )
        if report.next_actions:
            lines.extend(["", "建议动作"])
            for item in report.next_actions[:5]:
                lines.append(f"[{item.get('priority')}] {item.get('action')}")
        if report.change_summary:
            lines.extend(["", "本轮变化"])
            for item in report.change_summary.get("metrics", [])[:6]:
                lines.append(
                    f"{item.get('label')}: 当前 {item.get('current')} / 上轮 {item.get('previous')} / 变化 {item.get('delta')}"
                )
        if report.content_insights:
            lines.extend(["", "内容洞察"])
            for item in report.content_insights[:5]:
                lines.append(f"- {item.get('title')}: {item.get('insight')}")
        return "\n".join(lines)

    def _build_lead_next_step(self, report) -> str:
        high_value = int(report.summary.get("high_value_candidate_count") or 0)
        high_tier = int(report.lead_tiers.get("high") or 0)
        candidates = int(report.summary.get("candidate_user_count") or 0)
        action_queue = int(report.summary.get("action_queue_count") or 0)
        if high_value > 0 or high_tier > 0:
            if action_queue > 0:
                return "先查看/导出高价值线索，再进入动作队列做人工复核和执行前确认。"
            return "先查看/导出高价值线索，补齐主页资料后进入人工复核。"
        if candidates > 0:
            return "本轮候选偏低意图，下一轮改用竞品达人、具体内容链接或购买/下载/咨询类高意图关键词采集。"
        return "更换 creator_url、话题或内容链接，或放宽最小播放量/评论数后重新采集。"

    def approve_action(self, action_id: str, note: str = ""):
        self.action_queue.approve(action_id, note)

    def reject_action(self, action_id: str, note: str = ""):
        if not str(note or "").strip():
            self.storage.log_event("action_rejection_blocked", action_id, {"reason": "ACTION_REJECTION_NOTE_REQUIRED"})
            return {"updated": 0, "skipped": 1, "error": "ACTION_REJECTION_NOTE_REQUIRED"}
        self.action_queue.reject(action_id, note)
        return {"updated": 1, "skipped": 0}

    def confirm_action(self, action_id: str, note: str = ""):
        blocked = self._high_risk_actions_missing_note([action_id], note)
        if blocked:
            self.storage.log_event("high_risk_confirmation_blocked", action_id, {"reason": "HIGH_RISK_CONFIRMATION_NOTE_REQUIRED"})
            return {"updated": 0, "skipped": 1, "error": "HIGH_RISK_CONFIRMATION_NOTE_REQUIRED", "blocked_action_ids": blocked}
        self.action_queue.confirm_execution(action_id, note=note)
        return {"updated": 1, "skipped": 0}

    def bulk_review_actions(self, action_ids: list[str], action: str, note: str = "") -> dict:
        if action == "approve":
            return self.action_queue.bulk_approve(action_ids, note or "bulk approved in GrowthOps")
        if action == "reject":
            if not str(note or "").strip():
                self.storage.log_event(
                    "action_rejection_blocked",
                    "",
                    {"reason": "ACTION_REJECTION_NOTE_REQUIRED", "action_ids": self._unique_action_ids(action_ids)},
                )
                return {
                    "updated": 0,
                    "skipped": len(action_ids or []),
                    "error": "ACTION_REJECTION_NOTE_REQUIRED",
                }
            return self.action_queue.bulk_reject(action_ids, note)
        if action == "confirm":
            blocked = self._high_risk_actions_missing_note(action_ids, note)
            if blocked:
                self.storage.log_event(
                    "high_risk_confirmation_blocked",
                    "",
                    {"reason": "HIGH_RISK_CONFIRMATION_NOTE_REQUIRED", "blocked_action_ids": blocked},
                )
                return {
                    "updated": 0,
                    "skipped": len(action_ids or []),
                    "error": "HIGH_RISK_CONFIRMATION_NOTE_REQUIRED",
                    "blocked_action_ids": blocked,
                }
            return self.action_queue.bulk_confirm_execution(action_ids, note=note or "bulk confirmed in GrowthOps")
        if action == "retry":
            return self.action_queue.bulk_schedule_retry(action_ids, note or "bulk retry in GrowthOps")
        return {"updated": 0, "skipped": len(action_ids or []), "error": "UNSUPPORTED_BULK_ACTION"}

    def _high_risk_actions_missing_note(self, action_ids: list[str], note: str = "") -> list[str]:
        if str(note or "").strip():
            return []
        selected = set(self._unique_action_ids(action_ids))
        if not selected:
            return []
        return [
            row.get("id", "")
            for row in self.storage.list_action_queue(limit=1000)
            if row.get("id") in selected and row.get("risk_level") == "high"
        ]

    def save_action_template(self, action_type: str, name: str, body: str, status: str = "active") -> str:
        action_type = str(action_type or "").strip()
        name = str(name or "").strip()
        body = str(body or "").strip()
        status = str(status or "active").strip() or "active"
        if not action_type or not name or not body:
            return ""
        return self.action_queue.save_template(action_type, name, body, status=status)

    def add_exclusion(self, target_username: str = "", target_url: str = "", reason: str = "") -> str:
        username = str(target_username or "").strip().lstrip("@")
        url = str(target_url or "").strip()
        reason = str(reason or "").strip()
        if not username and not url:
            return ""
        return self.action_queue.add_exclusion(target_username=username, target_url=url, reason=reason)

    def execute_approved(self, profile_id: str, limit: int = 10, dry_run: bool = True) -> list[dict]:
        actions = [row for row in self.storage.list_action_queue(limit=200) if row.get("status") == "approved"]
        results = []
        for action in actions[: max(0, int(limit))]:
            results.append(self.executor.execute_action(action, profile_id=profile_id, dry_run=dry_run))
        return results

    def retry_failed_actions(self, profile_id: str, limit: int = 10, dry_run: bool = True) -> list[dict]:
        retryable = self.action_queue.list_retryable(limit=200)
        results = []
        for action in retryable[: max(0, int(limit))]:
            self.action_queue.schedule_retry(action["id"], "retry failed action")
            refreshed = next((row for row in self.storage.list_action_queue(limit=200) if row.get("id") == action["id"]), action)
            results.append(self.executor.execute_action(refreshed, profile_id=profile_id, dry_run=dry_run))
        return results

    def run_due_scans(self, profiles: list[dict], now_iso: str | None = None, limit: int = 20, test_mode: bool = False) -> list[dict]:
        return self.scheduler.run_due(profiles, now_iso=now_iso, limit=limit, test_mode=test_mode)

    def run_scheduled_scan_now(self, scan_id: str, profiles: list[dict], test_mode: bool = False) -> dict:
        return self.scheduler.run_scan_now(scan_id, profiles, test_mode=test_mode)

    def create_scans_bulk(self, sources: list[dict], profile_group: str = "", interval_minutes: int = 60, **kwargs) -> list[dict]:
        return self.scheduler.create_scans_bulk(
            sources,
            profile_group=profile_group,
            interval_minutes=interval_minutes,
            **kwargs,
        )

    def create_scheduled_scan(
        self,
        source_type: str,
        source_value: str,
        profile_group: str = "",
        interval_minutes: int = 60,
        **kwargs,
    ) -> dict:
        return self.scheduler.create_scan(
            source_type,
            source_value,
            profile_group=profile_group,
            interval_minutes=interval_minutes,
            **kwargs,
        )

    def create_scan_from_recommendation(
        self,
        recommendation: dict,
        concrete_value: str,
        profile_group: str = "",
        interval_minutes: int = 60,
        **kwargs,
    ) -> dict:
        """Turn an operator source recommendation into a concrete scheduled scan."""
        source_value = str(concrete_value or "").strip()
        if not source_value:
            raise ValueError("concrete_value is required")
        source_type = self._resolve_recommended_source_type(str((recommendation or {}).get("source_type") or ""), source_value)
        scan = self.create_scheduled_scan(
            source_type,
            source_value,
            profile_group=profile_group,
            interval_minutes=interval_minutes,
            **kwargs,
        )
        self.storage.log_event(
            "source_recommendation_scan_created",
            scan.get("id", ""),
            {
                "source_type": source_type,
                "source_value": source_value,
                "recommendation": recommendation or {},
                "profile_group": profile_group or "",
            },
        )
        return scan

    def pause_scheduled_scan(self, scan_id: str):
        self.scheduler.pause_scan(scan_id)

    def resume_scheduled_scan(self, scan_id: str):
        self.scheduler.resume_scan(scan_id)

    def run_worker_once(self, profiles: list[dict], now_iso: str | None = None, limit: int = 20, test_mode: bool = False) -> dict:
        return self.scheduler.run_worker_once(profiles, now_iso=now_iso, limit=limit, test_mode=test_mode)

    def run_execution_mvp(
        self,
        profiles: list[dict],
        config: ExecutionMVPConfig | None = None,
        limit: int = 100,
        fixture_outcomes: list[dict] | None = None,
        platform_executor: PlatformActionExecutor | None = None,
    ) -> dict:
        executor = platform_executor
        if executor is None:
            executor = FixturePlatformActionExecutor(fixture_outcomes)
        controller = ExecutionMVPController(
            self.storage,
            self.executor.guard,
            platform_executor=executor,
        )
        return controller.run(profiles, config=config or ExecutionMVPConfig(), limit=limit)

    def rerun_failed_tasks(self, batch_id: str, profiles: list[dict], config=None) -> dict:
        return self.scheduler.rerun_failed_tasks(batch_id, profiles, config=config)

    def rerun_collection_tasks(self, task_ids: list[str], profiles: list[dict], config=None) -> dict:
        return self.scheduler.rerun_collection_tasks(task_ids, profiles, config=config)

    def build_collection_batch_progress(self, batch_id: str) -> dict:
        progress = self.storage.collection_batch_progress(batch_id)
        if not progress:
            return {"batch_id": batch_id, "batch": {}, "summary": {"found": False}, "recent_tasks": []}
        batch = progress.get("batch") or {}
        total = int(batch.get("total_sources") or 0)
        processed = int(batch.get("processed_sources") or 0)
        failed = int(batch.get("failed_sources") or 0)
        completed = max(0, processed + failed)
        completion_rate = round(completed / total, 4) if total else 0
        failure_rate = round(failed / total, 4) if total else 0
        status_counts = progress.get("status_counts") or {}
        error_counts = progress.get("error_counts") or {}
        next_action = "继续等待批次完成"
        if failed:
            top_error = sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if error_counts else ""
            next_action = f"优先排查失败任务{f'，主要错误: {top_error}' if top_error else ''}"
        elif batch.get("status") in {"completed", "partial_failed"}:
            next_action = "复核报告、线索池和动作队列"
        return {
            "batch_id": batch.get("id", batch_id),
            "batch": batch,
            "status_counts": status_counts,
            "error_counts": error_counts,
            "profile_counts": progress.get("profile_counts") or {},
            "recent_tasks": progress.get("recent_tasks") or [],
            "summary": {
                "found": True,
                "total_sources": total,
                "processed_sources": processed,
                "failed_sources": failed,
                "completed_sources": completed,
                "completion_rate": completion_rate,
                "failure_rate": failure_rate,
                "task_count": sum(int(value or 0) for value in status_counts.values()),
                "next_operator_action": next_action,
            },
        }

    def _build_operational_status(self, report) -> dict:
        latest_batch = (self.storage.list_collection_batches(limit=1) or [{}])[0]
        batch_id = str(latest_batch.get("id") or "")
        batch_summary = {}
        if batch_id:
            batch_summary = self.build_collection_batch_progress(batch_id).get("summary") or {}
        diagnostics = self.error_diagnostics.build_diagnostics(limit=50)
        top_error = diagnostics[0] if diagnostics else {}
        quality = report.comment_quality or {}
        candidate_count = int(report.summary.get("candidate_user_count") or 0)
        high_value_count = int(report.summary.get("high_value_candidate_count") or 0)
        action_count = int(report.summary.get("action_queue_count") or 0)
        failed_sources = int(batch_summary.get("failed_sources") or 0)
        status = "ready"
        if failed_sources:
            status = "needs_attention"
        elif candidate_count == 0 and batch_id:
            status = "no_leads"
        elif high_value_count > 0:
            status = "lead_ready"
        elif candidate_count > 0:
            status = "needs_source_tuning"
        completion_rate = batch_summary.get("completion_rate", 0)
        quality_label = self._comment_quality_label(quality)
        next_step = self._build_lead_next_step(report)
        if failed_sources and top_error:
            next_step = f"先处理 {top_error.get('error_code', '')}，再重跑失败任务。"
        elif candidate_count > 0 and high_value_count == 0:
            next_step = "已采到评论用户但暂无高价值线索，下一轮改用竞品达人、具体内容链接或购买/下载/咨询类高意图关键词。"
        return {
            "status": status,
            "latest_batch_id": batch_id,
            "latest_batch_status": latest_batch.get("status", ""),
            "completion_rate": completion_rate,
            "processed_sources": int(batch_summary.get("processed_sources") or 0),
            "failed_sources": failed_sources,
            "candidate_user_count": candidate_count,
            "high_value_candidate_count": high_value_count,
            "action_queue_count": action_count,
            "comment_quality": quality_label,
            "profile_completed_rate": quality.get("profile_completed_rate", 0),
            "top_error_code": top_error.get("error_code", ""),
            "top_error_action": top_error.get("suggested_action", ""),
            "next_operator_action": next_step,
        }

    def _build_source_recommendations(self, report) -> list[dict]:
        candidate_count = int(report.summary.get("candidate_user_count") or 0)
        high_value_count = int(report.summary.get("high_value_candidate_count") or 0)
        has_content = int(report.summary.get("new_content_count") or 0) + int(report.summary.get("topic_content_count") or 0)
        top_content_url = self._first_value(report.top_videos, "video_url")
        high_value_source = self._first_value(report.high_value_users, "source_path") or self._first_value(report.high_value_users, "video_url")
        frequent_source = self._first_value(report.source_paths, "source_path")
        next_content_url = high_value_source or top_content_url or frequent_source
        if candidate_count > 0 and high_value_count == 0:
            return [
                {
                    "priority": "P0",
                    "source_type": "creator_url",
                    "source_value": "https://www.tiktok.com/@competitor_creator",
                    "actionable": bool(next_content_url or True),
                    "scenario": "低意图来源降权，优先改扫竞品达人",
                    "reason": "当前已能采到评论用户但意图弱；下一轮优先补充竞品达人池，再结合具体内容链接和购买/优惠关键词提纯。",
                },
                {
                    "priority": "P0",
                    "source_type": "content_url" if next_content_url else "keyword",
                    "source_value": next_content_url or "cupom desconto shopee",
                    "actionable": bool(next_content_url or True),
                    "scenario": "改扫更强意图内容或关键词",
                    "reason": "用具体视频链接或购买/优惠关键词替代泛流量来源，提升高价值线索率。",
                },
                {
                    "priority": "P0",
                    "source_type": "keyword",
                    "source_value": "cupom shopee desconto",
                    "actionable": True,
                    "scenario": "BR 葡语优惠意图关键词",
                    "reason": "用 cupom/shopee/desconto 组合过滤泛流量，提升高价值线索率。",
                },
                {
                    "priority": "P1",
                    "source_type": "hashtag",
                    "source_value": "cupomshopee",
                    "actionable": True,
                    "scenario": "BR 优惠券标签扩展",
                    "reason": "从泛 hashtag/topic 收敛到更具体的优惠券标签。",
                },
            ]
        if high_value_count > 0:
            return [
                {
                    "priority": "P0",
                    "source_type": "content_url",
                    "source_value": next_content_url or "",
                    "actionable": bool(next_content_url),
                    "scenario": "复制高价值线索来源内容",
                    "reason": "优先扩展已验证高价值内容的相似视频和评论区。",
                },
                {
                    "priority": "P1",
                    "source_type": "creator_url",
                    "source_value": self._creator_url_from_content_url(next_content_url),
                    "actionable": bool(self._creator_url_from_content_url(next_content_url)),
                    "scenario": "同垂类相似达人主页",
                    "reason": "把已验证有效的受众扩展到相似达人池。",
                },
            ]
        if not has_content:
            return [
                {
                    "priority": "P0",
                    "source_type": "keyword",
                    "source_value": "cupom shopee desconto",
                    "actionable": True,
                    "scenario": "先用业务关键词发现内容素材",
                    "reason": "当前没有内容样本，先建立素材池再提取评论线索。",
                },
                {
                    "priority": "P1",
                    "source_type": "creator_url",
                    "source_value": "",
                    "actionable": False,
                    "scenario": "输入 3-5 个竞品或垂类达人主页",
                    "reason": "用达人监控池补齐 creator -> content -> comments 闭环。",
                },
            ]
        return [
            {
                "priority": "P1",
                "source_type": "content_url" if next_content_url else "keyword",
                "source_value": next_content_url or "cupom shopee desconto",
                "actionable": True,
                "scenario": "扩大已验证来源的相似账号与相似内容",
                "reason": "维持低频扫描，继续积累可观察线索。",
            }
        ]

    def _first_value(self, rows: list[dict], key: str) -> str:
        for row in rows or []:
            value = str((row or {}).get(key) or "").strip()
            if value:
                return value
        return ""

    def _creator_url_from_content_url(self, value: str) -> str:
        text = str(value or "").strip()
        if "tiktok.com/@" not in text:
            return ""
        try:
            prefix = text.split("/video/", 1)[0]
            return prefix if "tiktok.com/@" in prefix else ""
        except Exception:
            return ""

    def _resolve_recommended_source_type(self, recommended_type: str, value: str) -> str:
        source_type = str(recommended_type or "").strip()
        value_lower = str(value or "").strip().lower()
        direct_types = {"creator_url", "content_url", "keyword", "topic", "hashtag", "product_url", "shop_url"}
        if source_type in direct_types:
            return source_type
        if "/video/" in value_lower:
            return "content_url"
        if "tiktok.com/@" in value_lower:
            return "creator_url"
        if value_lower.startswith("#"):
            return "hashtag"
        if "product" in value_lower:
            return "product_url"
        if "shop" in value_lower:
            return "shop_url"
        if "keyword" in source_type:
            return "keyword"
        if "topic" in source_type:
            return "topic"
        return "creator_url"

    def _comment_quality_label(self, quality: dict) -> str:
        profile_completed_rate = float(quality.get("profile_completed_rate") or 0)
        total_comments = int(quality.get("total_comments") or 0)
        placeholder_count = int(quality.get("placeholder_candidate_count") or 0)
        duplicate_count = int(quality.get("duplicate_comment_count") or 0)
        if total_comments <= 0:
            return "待验证"
        if placeholder_count > 0:
            return "需排查占位评论"
        if duplicate_count > max(3, total_comments // 3):
            return "需排查重复评论"
        if profile_completed_rate >= 0.6:
            return "可用"
        return "需补全主页"

    def build_collection_task_timeline(self, task_id: str) -> dict:
        tasks = self.storage.list_collection_tasks_by_ids([task_id])
        if not tasks:
            return {"task_id": task_id, "task": {}, "timeline": [], "summary": {"found": False}}
        task = tasks[0]
        entity_ids = [task.get("id", ""), task.get("source_id", "")]
        events = self.storage.list_events_for_entities(entity_ids, limit=300)
        errors = self.storage.list_errors_for_context(
            batch_id=str(task.get("batch_id") or ""),
            source_id=str(task.get("source_id") or ""),
            profile_id=str(task.get("profile_id") or ""),
            limit=100,
        )
        timeline = []
        for event in events:
            payload = self._parse_payload(event.get("payload"))
            item = {
                "kind": "event",
                "time": event.get("created_at", ""),
                "event": event.get("event", ""),
                "entity_id": event.get("entity_id", ""),
                "payload": payload,
            }
            if event.get("event") == "collector_evidence":
                item["screenshot_path"] = payload.get("screenshot_path", "")
                item["collector_level"] = payload.get("level", "")
                item["adapter_name"] = payload.get("adapter_name", "")
                item["item_count"] = payload.get("item_count", 0)
            timeline.append(item)
        for error in errors:
            timeline.append(
                {
                    "kind": "error",
                    "time": error.get("created_at", ""),
                    "event": error.get("error_code", ""),
                    "entity_id": error.get("source_id", ""),
                    "error_code": error.get("error_code", ""),
                    "message": error.get("message", ""),
                    "profile_id": error.get("profile_id", ""),
                    "batch_id": error.get("batch_id", ""),
                }
            )
        timeline = sorted(timeline, key=lambda row: (row.get("time") or "", row.get("kind") or ""))
        evidence_count = len([row for row in timeline if row.get("event") == "collector_evidence"])
        error_codes = sorted({row.get("error_code") for row in timeline if row.get("kind") == "error" and row.get("error_code")})
        return {
            "task_id": task.get("id", ""),
            "task": task,
            "timeline": timeline,
            "summary": {
                "found": True,
                "status": task.get("status", ""),
                "error_code": task.get("error_code", ""),
                "event_count": len([row for row in timeline if row.get("kind") == "event"]),
                "error_count": len([row for row in timeline if row.get("kind") == "error"]),
                "evidence_count": evidence_count,
                "error_codes": error_codes,
            },
        }

    def rerun_latest_failed_batch_for_error(self, error_code: str, profiles: list[dict], config=None) -> dict:
        task = self.storage.latest_failed_batch_for_error(error_code)
        batch_id = str(task.get("batch_id") or "")
        if not batch_id:
            return {"processed_sources": 0, "rerun_count": 0, "errors": {}, "error": "NO_FAILED_BATCH_FOR_ERROR"}
        result = self.scheduler.rerun_failed_tasks(batch_id, profiles, config=config)
        result["source_error_code"] = error_code
        result["source_batch_id"] = batch_id
        return result

    def _parse_payload(self, payload: str) -> dict:
        try:
            value = json.loads(payload or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except Exception:
            return {"raw": payload or ""}
