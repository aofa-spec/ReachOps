# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from typing import Any, Dict, Tuple

from .schemas import GrowthReport, utc_now_iso
from .storage import GrowthStorage, new_id


class GrowthReporter:
    def __init__(self, storage: GrowthStorage, report_dir: str):
        self.storage = storage
        self.report_dir = report_dir
        os.makedirs(report_dir, exist_ok=True)

    def build_report(self, campaign_id: str = "", run_id: str = "", batch_id: str = "") -> GrowthReport:
        runtime_scope = self._resolve_runtime_scope(campaign_id=campaign_id, run_id=run_id, batch_id=batch_id)
        scoped_batch_id = str(runtime_scope.get("batch_id") or "")
        scoped_run_id = str(runtime_scope.get("run_id") or "")
        rows = self.storage.list_candidates_with_content(batch_id=scoped_batch_id, run_id=scoped_run_id)
        contents = self.storage.list_contents(batch_id=scoped_batch_id, run_id=scoped_run_id)
        top_topic_contents = self.storage.list_top_topic_contents(batch_id=scoped_batch_id, run_id=scoped_run_id)
        operation_actions = [
            self._with_public_action_status(row)
            for row in self.storage.list_action_queue(batch_id=scoped_batch_id, run_id=scoped_run_id)
        ]
        high_value = [row for row in rows if int(row.get("qualify_score") or 0) >= 70]
        medium_value = [row for row in rows if 40 <= int(row.get("qualify_score") or 0) < 70]
        low_value = [row for row in rows if int(row.get("qualify_score") or 0) < 40]
        keywords = Counter()
        intents = Counter()
        languages = Counter()
        creator_verticals = Counter()
        creator_countries = Counter()
        source_paths = Counter()
        profile_completed = 0
        max_js_duplicate_rows = 0
        max_python_duplicate_rows = 0
        max_visible_nodes = 0
        max_scroll_rounds = 0
        max_growth_rounds = 0
        visible_node_history = []
        skipped_no_user = 0
        skipped_no_text = 0
        page_states = Counter()
        stop_reasons = Counter()
        for row in rows:
            words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", str(row.get("comment_text") or "").lower())
            keywords.update(words)
            for tag in self._parse_json_list(row.get("intent_tags")):
                if str(tag).startswith("intent:"):
                    intents[str(tag).replace("intent:", "", 1)] += 1
            languages[str(row.get("comment_language") or "unknown")] += 1
            creator_verticals[str(row.get("creator_vertical") or "general")] += 1
            if row.get("creator_country"):
                creator_countries[str(row.get("creator_country"))] += 1
            for path_key in ("source_path", "content_source_path", "creator_source_path"):
                path = str(row.get(path_key) or "").strip()
                if path:
                    source_paths[path] += 1
            if row.get("author_profile_completed"):
                profile_completed += 1
            raw_meta = self._parse_json_dict(row.get("raw_meta"))
            max_js_duplicate_rows = max(max_js_duplicate_rows, int(raw_meta.get("duplicate_count_before_row") or 0))
            max_python_duplicate_rows = max(max_python_duplicate_rows, int(raw_meta.get("duplicate_rows_in_python") or 0))
            max_visible_nodes = max(
                max_visible_nodes,
                int(raw_meta.get("visible_node_count") or 0),
                int(raw_meta.get("max_visible_nodes") or 0),
            )
            max_scroll_rounds = max(max_scroll_rounds, int(raw_meta.get("scroll_rounds") or 0))
            max_growth_rounds = max(max_growth_rounds, int(raw_meta.get("growth_rounds") or 0))
            if isinstance(raw_meta.get("visible_node_history"), list) and len(raw_meta.get("visible_node_history")) > len(visible_node_history):
                visible_node_history = raw_meta.get("visible_node_history")
            skipped_no_user = max(skipped_no_user, int(raw_meta.get("skipped_no_user") or 0))
            skipped_no_text = max(skipped_no_text, int(raw_meta.get("skipped_no_text") or 0))
            page_state = str(raw_meta.get("comment_page_state") or "normal")
            stop_reason = str(raw_meta.get("stop_reason") or "")
            page_states[page_state] += 1
            if stop_reason:
                stop_reasons[stop_reason] += 1

        top_videos = sorted(
            [
                {
                    "video_id": c.video_id,
                    "video_url": c.video_url,
                    "caption": c.caption,
                    "views": c.views,
                    "likes": c.likes,
                    "comments": c.comments,
                    "shares": c.shares,
                    "content_language": c.content_language,
                    "country": c.country,
                    "material_type": c.material_type,
                    "source_path": c.source_path,
                }
                for c in contents
            ],
            key=lambda item: (item["views"], item["comments"]),
            reverse=True,
        )[:20]
        top_keywords = [{"keyword": kw, "count": count} for kw, count in keywords.most_common(20)]
        comment_intents = [{"intent": intent, "count": count} for intent, count in intents.most_common(20)]
        comment_languages = [{"language": language, "count": count} for language, count in languages.most_common(20)]
        creator_segments = {
            "verticals": [{"vertical": key, "count": count} for key, count in creator_verticals.most_common(20)],
            "countries": [{"country": key, "count": count} for key, count in creator_countries.most_common(20)],
        }
        source_path_items = [{"source_path": path, "count": count} for path, count in source_paths.most_common(20)]
        high_value_users = sorted(
            [
                {
                    "username": row.get("username"),
                    "profile_url": row.get("profile_url"),
                    "qualify_score": int(row.get("qualify_score") or 0),
                    "comment_text": row.get("comment_text"),
                    "video_url": row.get("video_url"),
                    "creator_vertical": row.get("creator_vertical") or "general",
                    "source_path": row.get("source_path") or row.get("content_source_path") or row.get("creator_source_path") or "",
                    "batch_id": row.get("batch_id") or "",
                    "run_id": row.get("run_id") or "",
                    "campaign_id": runtime_scope.get("campaign_id") or "",
                }
                for row in high_value
            ],
            key=lambda item: item["qualify_score"],
            reverse=True,
        )[:100]

        summary = {
            "datasource_count": self.storage.count_table("data_sources"),
            "new_creator_count": self.storage.count_table("discovered_creators"),
            "new_content_count": self.storage.count_table("discovered_contents"),
            "candidate_user_count": self.storage.count_table("candidate_users"),
            "high_value_candidate_count": len(high_value),
            "commerce_signal_count": self.storage.count_table("shop_products"),
            "topic_content_count": self.storage.count_table("shop_contents"),
            "operation_lead_count": self.storage.count_table("operation_leads"),
            "action_queue_count": self.storage.count_table("action_queue"),
            "outreach_execution_count": self.storage.count_table("outreach_executions"),
            "collection_batch_count": self.storage.count_table("collection_batches"),
            "collection_task_count": self.storage.count_table("collection_tasks"),
            "profile_health_count": self.storage.count_table("profile_health"),
            "runtime_traceability_schema_version": "reachops.runtime_traceability_report.v1",
            "runtime_scope": runtime_scope,
            "runtime_traceability": self.storage.runtime_traceability_summary(
                campaign_id=str(runtime_scope.get("campaign_id") or ""),
                run_id=scoped_run_id,
            ),
        }
        if scoped_batch_id or scoped_run_id:
            summary.update(
                {
                    "new_content_count": len(contents),
                    "candidate_user_count": len(rows),
                    "high_value_candidate_count": len(high_value),
                    "topic_content_count": len(top_topic_contents),
                    "operation_lead_count": len(self.storage.list_operation_leads(batch_id=scoped_batch_id, run_id=scoped_run_id)),
                    "action_queue_count": len(operation_actions),
                    "outreach_execution_count": len(self.storage.list_outreach_executions(batch_id=scoped_batch_id, run_id=scoped_run_id)),
                }
            )
        lead_tiers = {
            "high": len(high_value),
            "observe": len(medium_value),
            "low": len(low_value),
        }
        content_insights = self._build_content_insights(top_videos, top_topic_contents)
        comment_quality = {
            "total_comments": len(rows),
            "profile_completed_count": profile_completed,
            "profile_completed_rate": round(profile_completed / len(rows), 4) if rows else 0,
            "language_count": len([item for item in comment_languages if item["language"] != "unknown"]),
            "duplicate_rows": max_js_duplicate_rows + max_python_duplicate_rows,
            "duplicate_rate": round(
                (max_js_duplicate_rows + max_python_duplicate_rows)
                / max(1, len(rows) + max_js_duplicate_rows + max_python_duplicate_rows),
                4,
            ),
            "max_visible_nodes": max_visible_nodes,
            "max_scroll_rounds": max_scroll_rounds,
            "max_growth_rounds": max_growth_rounds,
            "visible_node_history": visible_node_history,
            "skipped_no_user": skipped_no_user,
            "skipped_no_text": skipped_no_text,
            "page_states": [{"state": state, "count": count} for state, count in page_states.most_common(10)],
            "stop_reasons": [{"reason": reason, "count": count} for reason, count in stop_reasons.most_common(10)],
        }
        change_summary = self._build_change_summary(summary)
        next_actions = self._build_next_actions(summary, comment_intents, lead_tiers, operation_actions)
        source_recommendations = self._build_source_recommendations(summary, lead_tiers)
        recommendations = self._recommend(summary, top_keywords, high_value_users, top_topic_contents, operation_actions)
        return GrowthReport(
            id=new_id("gr"),
            generated_at=utc_now_iso(),
            summary=summary,
            top_videos=top_videos,
            top_topic_contents=top_topic_contents,
            top_keywords=top_keywords,
            high_value_users=high_value_users,
            operation_actions=operation_actions,
            errors=self.storage.error_counts(),
            recommendations=recommendations,
            content_insights=content_insights,
            comment_intents=comment_intents,
            comment_languages=comment_languages,
            comment_quality=comment_quality,
            lead_tiers=lead_tiers,
            change_summary=change_summary,
            next_actions=next_actions,
            source_recommendations=source_recommendations,
            creator_segments=creator_segments,
            source_paths=source_path_items,
        )

    def export(self, report: GrowthReport) -> Tuple[str, str, str]:
        stem = f"growth_report_{report.generated_at.replace(':', '').replace('-', '').replace('Z', '')}"
        json_path = os.path.join(self.report_dir, f"{stem}.json")
        csv_path = os.path.join(self.report_dir, f"{stem}_high_value_users.csv")
        action_csv_path = os.path.join(self.report_dir, f"{stem}_action_queue.csv")
        markdown_path = os.path.join(self.report_dir, f"{stem}_daily_brief.md")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.__dict__, f, ensure_ascii=False, indent=2)
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "campaign_id",
                    "run_id",
                    "batch_id",
                    "username",
                    "profile_url",
                    "qualify_score",
                    "comment_text",
                    "video_url",
                    "creator_vertical",
                    "source_path",
                ],
            )
            writer.writeheader()
            for row in report.high_value_users:
                writer.writerow(row)
        with open(action_csv_path, "w", encoding="utf-8-sig", newline="") as f:
            fieldnames = [
                "campaign_id",
                "run_id",
                "batch_id",
                "action_type",
                "target_username",
                "target_url",
                "suggested_text",
                "public_status",
                "status",
                "risk_level",
                "priority",
                "lead_score",
                "reason",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report.operation_actions:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(self.render_markdown(report))
        self.storage.log_event(
            "report_exported",
            report.id,
            {"json_path": json_path, "csv_path": csv_path, "action_csv_path": action_csv_path, "markdown_path": markdown_path},
        )
        return json_path, csv_path, markdown_path

    def _with_public_action_status(self, row: dict) -> dict:
        item = dict(row or {})
        item["public_status"] = self._public_action_status(str(item.get("status") or ""))
        return item

    def _public_action_status(self, status: str) -> str:
        value = str(status or "")
        if value == "completed":
            return "success"
        if value in {"retryable", "partial", "rejected"}:
            return "failed"
        if value in {"pending_review", "approved"}:
            return "pending"
        if value in {"pending", "running", "success", "failed", "skipped", "account_switched"}:
            return value
        return "pending"

    def _resolve_runtime_scope(self, campaign_id: str = "", run_id: str = "", batch_id: str = "") -> Dict[str, Any]:
        campaign = str(campaign_id or "").strip()
        run = str(run_id or "").strip()
        batch = str(batch_id or "").strip()
        with self.storage.connect() as conn:
            if run and (not campaign or not batch):
                row = conn.execute(
                    "SELECT campaign_id, batch_id FROM campaign_runs WHERE id=?",
                    (run,),
                ).fetchone()
                if row:
                    campaign = campaign or str(row["campaign_id"] or "")
                    batch = batch or str(row["batch_id"] or "")
            if batch and (not campaign or not run):
                row = conn.execute(
                    "SELECT campaign_id, run_id FROM collection_batches WHERE id=?",
                    (batch,),
                ).fetchone()
                if row:
                    campaign = campaign or str(row["campaign_id"] or "")
                    run = run or str(row["run_id"] or "")
            if campaign and not batch:
                row = conn.execute(
                    "SELECT id, run_id FROM collection_batches WHERE campaign_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (campaign,),
                ).fetchone()
                if row:
                    batch = str(row["id"] or "")
                    run = run or str(row["run_id"] or "")
            if campaign and not run:
                row = conn.execute(
                    "SELECT id, batch_id FROM campaign_runs WHERE campaign_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (campaign,),
                ).fetchone()
                if row:
                    run = str(row["id"] or "")
                    batch = batch or str(row["batch_id"] or "")
        if not batch:
            batch = str(getattr(self.storage, "active_collection_batch_id", "") or "")
        if not run:
            run = str(getattr(self.storage, "active_campaign_run_id", "") or "")
        return {
            "campaign_id": campaign,
            "run_id": run,
            "batch_id": batch,
            "scope_type": "run" if run else ("campaign" if campaign else ("batch" if batch else "global")),
            "legacy_rows_preserved": True,
        }

    def render_markdown(self, report: GrowthReport) -> str:
        runtime_scope = report.summary.get("runtime_scope") or {}
        runtime_traceability = report.summary.get("runtime_traceability") or {}
        trace_counts = runtime_traceability.get("counts") or {}
        decision_count = trace_counts.get("lead_decisions", trace_counts.get("lead_decision_observations", 0))
        lines = [
            f"# GrowthOps 运营日报",
            "",
            f"- 生成时间: {report.generated_at}",
            f"- 数据源: {report.summary.get('datasource_count', 0)}",
            f"- 新内容/素材: {report.summary.get('new_content_count', 0) + report.summary.get('topic_content_count', 0)}",
            f"- CandidateUser: {report.summary.get('candidate_user_count', 0)}",
            f"- 高价值线索: {report.summary.get('high_value_candidate_count', 0)}",
            f"- 动作队列: {report.summary.get('action_queue_count', 0)}",
            f"- Runtime scope: {runtime_scope.get('scope_type', 'global')} campaign={runtime_scope.get('campaign_id', '')} run={runtime_scope.get('run_id', '')} batch={runtime_scope.get('batch_id', '')}",
            f"- Traceability: runs={trace_counts.get('campaign_runs', 0)} observations={trace_counts.get('candidate_observations', 0)} evidence={trace_counts.get('evidence_artifacts', 0)} decisions={decision_count}",
            "",
            "## 线索分层",
            "",
            f"- 高价值: {report.lead_tiers.get('high', 0)}",
            f"- 可观察: {report.lead_tiers.get('observe', 0)}",
            f"- 低价值: {report.lead_tiers.get('low', 0)}",
            "",
            "## Top 评论意图",
            "",
        ]
        if report.comment_intents:
            for item in report.comment_intents[:10]:
                lines.append(f"- {item.get('intent')}: {item.get('count')}")
        else:
            lines.append("- 暂无明显意图")
        lines.extend(["", "## 评论采集质量", ""])
        lines.append(f"- 作者主页补全率: {report.comment_quality.get('profile_completed_rate', 0)}")
        lines.append(f"- 最大可见评论节点: {report.comment_quality.get('max_visible_nodes', 0)}")
        lines.append(f"- 最大滚动轮次: {report.comment_quality.get('max_scroll_rounds', 0)}")
        lines.append(f"- 重复/跳过行: duplicate={report.comment_quality.get('duplicate_rows', 0)}, no_user={report.comment_quality.get('skipped_no_user', 0)}, no_text={report.comment_quality.get('skipped_no_text', 0)}")
        if report.comment_quality.get("page_states"):
            lines.append("- 页面状态: " + ", ".join([f"{item.get('state')}={item.get('count')}" for item in report.comment_quality.get("page_states", [])[:6]]))
        if report.comment_quality.get("stop_reasons"):
            lines.append("- 滚动停止原因: " + ", ".join([f"{item.get('reason')}={item.get('count')}" for item in report.comment_quality.get("stop_reasons", [])[:6]]))
        if report.comment_languages:
            lines.append("- 语言分布: " + ", ".join([f"{item.get('language')}={item.get('count')}" for item in report.comment_languages[:8]]))
        else:
            lines.append("- 语言分布: 暂无")
        lines.extend(["", "## 创作者/来源画像", ""])
        verticals = (report.creator_segments or {}).get("verticals") if isinstance(report.creator_segments, dict) else []
        countries = (report.creator_segments or {}).get("countries") if isinstance(report.creator_segments, dict) else []
        if verticals:
            lines.append("- 垂类分布: " + ", ".join([f"{item.get('vertical')}={item.get('count')}" for item in verticals[:8]]))
        else:
            lines.append("- 垂类分布: 暂无")
        if countries:
            lines.append("- 国家/地区: " + ", ".join([f"{item.get('country')}={item.get('count')}" for item in countries[:8]]))
        if report.source_paths:
            lines.append("- 主要来源路径: " + ", ".join([f"{item.get('source_path')}({item.get('count')})" for item in report.source_paths[:5]]))
        lines.extend(["", "## Top 内容洞察", ""])
        if report.content_insights:
            for item in report.content_insights[:10]:
                lines.append(f"- {item.get('title')}: {item.get('insight')}")
        else:
            lines.append("- 暂无可拆解内容")
        lines.extend(["", "## 下一轮采集源", ""])
        if report.source_recommendations:
            for item in report.source_recommendations[:5]:
                lines.append(
                    f"- [{item.get('priority')}] {item.get('source_type')}: {item.get('scenario')}；原因: {item.get('reason')}"
                )
        else:
            lines.append("- 暂无")
        lines.extend(["", "## 本轮变化", ""])
        if report.change_summary:
            mode = report.change_summary.get("mode", "report_total")
            if mode in {"batch_id", "batch_window"}:
                lines.append(f"- 当前批次: {report.change_summary.get('current_batch_id', '')}")
                lines.append(f"- 对比批次: {report.change_summary.get('previous_batch_id', '')}")
                for item in report.change_summary.get("metrics", []):
                    lines.append(
                        f"- {item.get('label')}: 当前 {item.get('current')} / 上轮 {item.get('previous')} / 变化 {item.get('delta')}"
                    )
            else:
                for key, value in report.change_summary.items():
                    lines.append(f"- {key}: {value}")
        else:
            lines.append("- 暂无上一轮报告可对比")
        lines.extend(["", "## 建议动作", ""])
        for item in report.next_actions or []:
            lines.append(f"- [{item.get('priority')}] {item.get('action')}")
        for rec in report.recommendations:
            lines.append(f"- {rec}")
        lines.append("")
        return "\n".join(lines)

    def _recommend(self, summary: dict, top_keywords: list[dict], high_value_users: list[dict], top_topic_contents: list[dict], operation_actions: list[dict]) -> list[str]:
        recommendations = []
        if top_topic_contents:
            recommendations.append("优先拆解 Top 话题内容的开头钩子、评论问题和互动动机，形成素材复刻清单。")
        if summary.get("high_value_candidate_count", 0) > 0:
            recommendations.append("优先人工复核高价值线索，按评论意图拆分素材选题与落地页答疑。")
        elif summary.get("candidate_user_count", 0) > 0:
            recommendations.append("本轮已采到评论用户但高价值线索不足，下一轮优先换竞品达人、单条高意图内容链接或更具体的购买/下载/咨询关键词。")
        if operation_actions:
            recommendations.append("动作队列已生成，请先人工复核评论/关注/私信建议，再小批量执行并记录结果。")
        if top_keywords:
            recommendations.append(f"围绕高频评论关键词 '{top_keywords[0]['keyword']}' 补充内容标题、评论置顶和FAQ素材。")
        if summary.get("new_content_count", 0) == 0 and summary.get("topic_content_count", 0) == 0:
            recommendations.append("本轮未发现新内容，建议扩大 creator_url、keyword、topic、content_url 或 hashtag 数据源。")
        if not recommendations:
            recommendations.append("继续扩大监控池，并保持低频、分组化采集，避免高频使用发布主账号。")
        return recommendations

    def _parse_json_list(self, value: Any) -> list:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def _parse_json_dict(self, value: Any) -> dict:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _build_content_insights(self, top_videos: list[dict], top_topic_contents: list[dict]) -> list[dict]:
        insights = []
        combined = []
        for item in top_videos:
            combined.append(
                {
                    "title": item.get("caption") or item.get("video_id") or "视频内容",
                    "url": item.get("video_url") or "",
                    "views": int(item.get("views") or 0),
                    "comments": int(item.get("comments") or 0),
                    "kind": "creator_video",
                }
            )
        for item in top_topic_contents:
            combined.append(
                {
                    "title": item.get("hook_text") or item.get("caption") or item.get("video_id") or "话题素材",
                    "url": item.get("video_url") or "",
                    "views": int(item.get("views") or 0),
                    "comments": int(item.get("comments") or 0),
                    "kind": item.get("material_type") or "topic_content",
                }
            )
        for item in sorted(combined, key=lambda row: (row["views"], row["comments"]), reverse=True)[:20]:
            title = str(item.get("title") or "")[:80]
            insight = "优先拆解开头钩子"
            if item["comments"] >= 500:
                insight = "评论区需求强，优先提炼 FAQ 和置顶评论"
            elif item["views"] >= 100000:
                insight = "播放表现强，适合拆解选题、封面和前三秒"
            elif item["views"] > 0:
                insight = "可作为轻量素材样本观察互动动机"
            insights.append(
                {
                    "title": title,
                    "url": item.get("url", ""),
                    "content_kind": item.get("kind", ""),
                    "views": item["views"],
                    "comments": item["comments"],
                    "insight": insight,
                }
            )
        return insights

    def _build_next_actions(self, summary: dict, comment_intents: list[dict], lead_tiers: dict, operation_actions: list[dict]) -> list[dict]:
        actions = []
        if lead_tiers.get("high", 0):
            actions.append({"priority": "P0", "action": "复核高价值线索，确认可评论/关注/私信的目标名单。"})
        elif summary.get("candidate_user_count", 0) > 0 and not lead_tiers.get("observe", 0):
            actions.append({"priority": "P0", "action": "本轮候选偏低意图，下一轮改用竞品达人、具体内容链接或高意图关键词采集。"})
        if comment_intents:
            actions.append({"priority": "P1", "action": f"围绕评论意图 '{comment_intents[0]['intent']}' 补充内容答疑和落地页说明。"})
        if operation_actions:
            actions.append({"priority": "P1", "action": "处理动作队列：先审核，再执行二次确认，再小批量 dry-run。"})
        if summary.get("profile_health_count", 0):
            actions.append({"priority": "P2", "action": "检查 Profile 健康视图，优先使用 healthy/discovery/comment 分组。"})
        if not actions:
            actions.append({"priority": "P2", "action": "扩大数据源池，并保留低频扫描策略。"})
        return actions

    def _build_source_recommendations(self, summary: dict, lead_tiers: dict) -> list[dict]:
        candidate_count = int(summary.get("candidate_user_count") or 0)
        high_value_count = int(summary.get("high_value_candidate_count") or 0)
        has_content = int(summary.get("new_content_count") or 0) + int(summary.get("topic_content_count") or 0)
        if candidate_count > 0 and high_value_count == 0:
            return [
                {
                    "priority": "P0",
                    "source_type": "creator_url",
                    "scenario": "竞品达人/垂类达人主页",
                    "reason": "当前已能采到评论用户，但意图弱；换更贴近业务受众的达人主页。",
                },
                {
                    "priority": "P0",
                    "source_type": "content_url",
                    "scenario": "评论区已有购买/下载/求链接问题的单条内容",
                    "reason": "单条内容评论区更容易直接沉淀高意图 CandidateUser。",
                },
                {
                    "priority": "P1",
                    "source_type": "keyword/topic",
                    "scenario": "购买、下载、价格、链接、教程、替代品等强意图关键词",
                    "reason": "用高意图词过滤泛流量，提升高价值线索率。",
                },
            ]
        if high_value_count > 0 or int(lead_tiers.get("high") or 0) > 0:
            return [
                {
                    "priority": "P0",
                    "source_type": "content_url",
                    "scenario": "复制高价值线索来源内容",
                    "reason": "优先扩展已验证高价值内容的相似视频和评论区。",
                },
                {
                    "priority": "P1",
                    "source_type": "creator_url",
                    "scenario": "同垂类相似达人主页",
                    "reason": "把已验证有效的受众扩展到相似达人池。",
                },
            ]
        if not has_content:
            return [
                {
                    "priority": "P0",
                    "source_type": "keyword/topic",
                    "scenario": "先用业务关键词发现内容素材",
                    "reason": "当前没有内容样本，先建立素材池再提取评论线索。",
                },
                {
                    "priority": "P1",
                    "source_type": "creator_url",
                    "scenario": "输入 3-5 个竞品或垂类达人主页",
                    "reason": "用达人监控池补齐 creator -> content -> comments 闭环。",
                },
            ]
        return [
            {
                "priority": "P1",
                "source_type": "creator_url/content_url",
                "scenario": "扩大已验证来源的相似账号与相似内容",
                "reason": "维持低频扫描，继续积累可观察线索。",
            }
        ]

    def _build_change_summary(self, summary: dict) -> dict:
        batch_summary = self._build_batch_change_summary()
        if batch_summary:
            return batch_summary
        previous = self._load_previous_report()
        if not previous:
            return {}
        previous_summary = previous.get("summary") or {}
        keys = [
            "candidate_user_count",
            "high_value_candidate_count",
            "topic_content_count",
            "new_content_count",
            "action_queue_count",
            "outreach_execution_count",
        ]
        changes = {"mode": "report_total", "metrics": []}
        for key in keys:
            current = int(summary.get(key) or 0)
            old = int(previous_summary.get(key) or 0)
            changes[key] = {"current": current, "previous": old, "delta": current - old}
            changes["metrics"].append(
                {
                    "key": key,
                    "label": self._metric_label(key),
                    "current": current,
                    "previous": old,
                    "delta": current - old,
                }
            )
        return changes

    def _build_batch_change_summary(self) -> dict:
        batches = self.storage.list_collection_batches(limit=2)
        if len(batches) < 2:
            return {}
        current = batches[0]
        previous = batches[1]
        current_start = str(current.get("started_at") or current.get("created_at") or "")
        previous_start = str(previous.get("started_at") or previous.get("created_at") or "")
        if not current_start or not previous_start:
            return {}
        current_metrics = self.storage.collection_batch_entity_metrics(str(current.get("id") or ""))
        previous_metrics = self.storage.collection_batch_entity_metrics(str(previous.get("id") or ""))
        mode = "batch_id"
        if not any(current_metrics.values()) and not any(previous_metrics.values()):
            current_metrics = self.storage.collection_window_metrics(current_start, utc_now_iso())
            previous_metrics = self.storage.collection_window_metrics(previous_start, current_start)
            mode = "batch_window"
        keys = [
            "new_creators",
            "new_contents",
            "topic_contents",
            "candidate_users",
            "high_value_candidates",
            "operation_leads",
            "action_queue",
            "outreach_executions",
            "errors",
        ]
        metrics = []
        for key in keys:
            current_value = int(current_metrics.get(key) or 0)
            previous_value = int(previous_metrics.get(key) or 0)
            metrics.append(
                {
                    "key": key,
                    "label": self._metric_label(key),
                    "current": current_value,
                    "previous": previous_value,
                    "delta": current_value - previous_value,
                }
            )
        summary = {
            "mode": mode,
            "current_batch_id": current.get("id", ""),
            "previous_batch_id": previous.get("id", ""),
            "current_window": {"start": current_start, "end": utc_now_iso()},
            "previous_window": {"start": previous_start, "end": current_start},
            "metrics": metrics,
        }
        aliases = {
            "new_content_count": "new_contents",
            "candidate_user_count": "candidate_users",
            "high_value_candidate_count": "high_value_candidates",
            "topic_content_count": "topic_contents",
            "operation_lead_count": "operation_leads",
            "action_queue_count": "action_queue",
            "outreach_execution_count": "outreach_executions",
        }
        by_key = {item["key"]: item for item in metrics}
        for alias, source_key in aliases.items():
            metric = by_key.get(source_key)
            if metric:
                summary[alias] = {
                    "current": metric["current"],
                    "previous": metric["previous"],
                    "delta": metric["delta"],
                }
        return summary

    def _metric_label(self, key: str) -> str:
        labels = {
            "candidate_user_count": "CandidateUser",
            "high_value_candidate_count": "高价值线索",
            "topic_content_count": "话题素材",
            "new_content_count": "创作者视频",
            "action_queue_count": "动作队列",
            "outreach_execution_count": "执行记录",
            "new_creators": "新增创作者",
            "new_contents": "新增视频",
            "topic_contents": "话题素材",
            "candidate_users": "CandidateUser",
            "high_value_candidates": "高价值线索",
            "operation_leads": "运营线索",
            "action_queue": "动作队列",
            "outreach_executions": "执行记录",
            "errors": "错误数",
        }
        return labels.get(key, key)

    def _load_previous_report(self) -> dict:
        try:
            paths = [
                os.path.join(self.report_dir, name)
                for name in os.listdir(self.report_dir)
                if name.startswith("growth_report_") and name.endswith(".json")
            ]
            paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            for path in paths:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            return {}
        return {}
