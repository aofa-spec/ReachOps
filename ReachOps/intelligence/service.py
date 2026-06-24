# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Any, Callable, Iterable, Optional

from ReachOps.runtime_paths import RuntimePaths

from .ai_strategy import AcquisitionIntelligenceProvider, build_default_acquisition_intelligence_provider
from .comment_intent import CommentIntentClassifier
from .growth_task_router import GrowthTaskRouter
from .outreach_copy import OutreachCopyRecommender
from .schemas import AcquisitionCampaign, AcquisitionSource, AudiencePersona, GrowthTaskConfig, GrowthTaskResult, utc_now_iso
from .source_planner import CampaignAnalyzer, SourcePlanner, StrategyBuilder
from .storage import GrowthStorage


class GrowthIntelligenceService:
    def __init__(
        self,
        base_dir: str,
        browser_factory: Optional[Callable[[str], Any]] = None,
        logger: Optional[Callable[[str], None]] = None,
        collectors: Optional[dict] = None,
        intelligence_provider: Optional[AcquisitionIntelligenceProvider] = None,
        comment_intent_classifier: Optional[CommentIntentClassifier] = None,
        outreach_copy_recommender: Optional[OutreachCopyRecommender] = None,
    ):
        self.paths = RuntimePaths.build(base_dir).ensure_dirs()
        self.base_dir = self.paths.base_dir
        self.module_dir = self.paths.module_dir
        self.report_dir = self.paths.reports_dir
        os.makedirs(self.report_dir, exist_ok=True)
        self.storage = GrowthStorage(self.paths.db_path)
        self.storage.runtime_paths = self.paths
        self.campaign_analyzer = CampaignAnalyzer()
        self.intelligence_provider = intelligence_provider or build_default_acquisition_intelligence_provider()
        self.source_planner = SourcePlanner(self.storage)
        self.strategy_builder = StrategyBuilder()
        self.router = GrowthTaskRouter(
            self.storage,
            self.report_dir,
            browser_factory=browser_factory,
            logger=logger,
            collectors=collectors,
            intent_classifier=comment_intent_classifier,
            copy_recommender=outreach_copy_recommender,
        )

    def run_collection(self, sources: Iterable[dict], profiles: list[dict], config: Optional[GrowthTaskConfig] = None) -> GrowthTaskResult:
        return self.router.run(sources, profiles, config or GrowthTaskConfig())

    def create_campaign_plan(
        self,
        input_value: str,
        target_market: str = "auto",
        target_language: str = "auto",
        intent_keywords: Optional[list[str]] = None,
        exclude_keywords: Optional[list[str]] = None,
        max_sources: int = 5,
    ) -> dict:
        campaign_template = self.campaign_analyzer.build_campaign(input_value, target_market=target_market, target_language=target_language)
        intelligence = self.intelligence_provider.analyze(
            campaign_template,
            intent_keywords=intent_keywords or [],
            exclude_keywords=exclude_keywords or [],
        )
        product_analysis = intelligence.get("product_analysis") or {}
        if product_analysis:
            campaign_template.category = str(product_analysis.get("category") or campaign_template.category)
            campaign_template.product_name = str(product_analysis.get("product_name") or campaign_template.product_name)
        campaign = self.storage.create_campaign(
            campaign_template.input_type,
            campaign_template.input_value,
            objective=campaign_template.objective,
            target_market=campaign_template.target_market,
            target_language=campaign_template.target_language,
            product_name=campaign_template.product_name,
            category=campaign_template.category,
            status=campaign_template.status,
        )
        persona = self.campaign_analyzer.build_persona(
            campaign,
            extra_intent=intent_keywords or [],
            extra_exclude=exclude_keywords or [],
            intelligence=intelligence,
        )
        persona = self.storage.upsert_audience_persona(persona)
        sources = self.source_planner.plan(campaign, persona, max_sources=max_sources, intelligence=intelligence)
        strategy = self.strategy_builder.build(campaign, persona, sources, intelligence=intelligence)
        return {
            "campaign": campaign.__dict__,
            "persona": persona.__dict__,
            "sources": [source.__dict__ for source in sources],
            "strategy": strategy.__dict__,
        }

    def save_campaign_strategy_overrides(self, campaign_id: str, overrides: dict, updated_by: str = "operator") -> dict:
        return self.storage.upsert_campaign_strategy_overrides(campaign_id, overrides or {}, updated_by=updated_by)

    def build_campaign_strategy(self, campaign_id: str) -> dict:
        campaign = next((row for row in self.storage.list_campaigns(limit=500) if row.get("id") == campaign_id), {})
        if not campaign:
            return {}
        persona = self.storage.get_audience_persona(campaign_id)
        sources = self.storage.list_acquisition_sources(campaign_id=campaign_id, limit=500)
        strategy = self.strategy_builder.build(
            self._campaign_from_row(campaign),
            self._persona_from_row(persona, campaign_id),
            [self._source_from_row(row, campaign_id) for row in sources],
        ).__dict__
        override_row = self.storage.get_campaign_strategy_overrides(campaign_id)
        overrides = override_row.get("overrides") or {}
        if overrides:
            strategy = self._merge_strategy(strategy, overrides)
            strategy["operator_overrides"] = overrides
            strategy["overrides_applied"] = True
            strategy["overrides_updated_at"] = str(override_row.get("updated_at") or "")
            strategy["overrides_updated_by"] = str(override_row.get("updated_by") or "")
        else:
            strategy["overrides_applied"] = False
        return strategy

    def _campaign_from_row(self, row: dict) -> AcquisitionCampaign:
        return AcquisitionCampaign(
            id=str(row.get("id") or ""),
            input_type=str(row.get("input_type") or ""),
            input_value=str(row.get("input_value") or ""),
            objective=str(row.get("objective") or "customer_acquisition"),
            target_market=str(row.get("target_market") or "auto"),
            target_language=str(row.get("target_language") or "auto"),
            product_name=str(row.get("product_name") or ""),
            category=str(row.get("category") or ""),
            status=str(row.get("status") or "active"),
            created_at=str(row.get("created_at") or utc_now_iso()),
            updated_at=str(row.get("updated_at") or utc_now_iso()),
        )

    def _persona_from_row(self, row: dict, campaign_id: str) -> AudiencePersona:
        return AudiencePersona(
            id=str(row.get("id") or ""),
            campaign_id=str(row.get("campaign_id") or campaign_id),
            demographics=row.get("demographics") if isinstance(row.get("demographics"), dict) else {},
            interests=list(row.get("interests") or []),
            pain_points=list(row.get("pain_points") or []),
            buying_triggers=list(row.get("buying_triggers") or []),
            intent_keywords=list(row.get("intent_keywords") or []),
            exclude_keywords=list(row.get("exclude_keywords") or []),
            search_keywords=list(row.get("search_keywords") or []),
            hashtags=list(row.get("hashtags") or []),
            competitor_terms=list(row.get("competitor_terms") or []),
            outreach_angles=list(row.get("outreach_angles") or []),
        )

    def _source_from_row(self, row: dict, campaign_id: str) -> AcquisitionSource:
        return AcquisitionSource(
            id=str(row.get("id") or ""),
            campaign_id=str(row.get("campaign_id") or campaign_id),
            source_type=str(row.get("source_type") or ""),
            source_value=str(row.get("source_value") or ""),
            reason=str(row.get("reason") or ""),
            priority=int(row.get("priority") or 50),
            status=str(row.get("status") or "active"),
        )

    def _merge_strategy(self, base: dict, overrides: dict) -> dict:
        merged = dict(base or {})
        for key, value in (overrides or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged.get(key) or {})
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value
        return merged

    def export_latest_report(self) -> GrowthTaskResult:
        report = self.router.reporter.build_report()
        try:
            json_path, csv_path, markdown_path = self.router.reporter.export(report)
        except Exception as exc:
            self.storage.log_error("REPORT_EXPORT_FAILED", str(exc))
            json_path, csv_path, markdown_path = "", "", ""
        return GrowthTaskResult(
            report=report,
            report_json_path=json_path,
            report_csv_path=csv_path,
            report_markdown_path=markdown_path,
            errors=self.storage.error_counts(),
        )
