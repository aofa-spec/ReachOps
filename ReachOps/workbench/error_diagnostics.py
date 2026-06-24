# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from collections import Counter

from ReachOps.intelligence.storage import GrowthStorage


DIAGNOSTIC_RULES = {
    "PROFILE_START_FAILED": {
        "severity": "high",
        "cause": "Profile 启动失败或 ixBrowser 返回不可用实例。",
        "action": "优先探测同分组其他 Profile；检查 ixBrowser API、Profile 状态、代理和 DevTools 端口。",
    },
    "CREATOR_PAGE_OPEN_FAILED": {
        "severity": "medium",
        "cause": "创作者页或内容页打开失败。",
        "action": "重试该数据源；若持续失败，检查 URL、地区可访问性和 Profile 网络状态。",
    },
    "LOGIN_REQUIRED": {
        "severity": "high",
        "cause": "页面要求登录或会话失效。",
        "action": "将 Profile 标记为降级，换 discovery/comment 分组健康 Profile，并人工检查登录状态。",
    },
    "CAPTCHA_DETECTED": {
        "severity": "high",
        "cause": "触发验证码或平台验证。",
        "action": "停止该 Profile 高频任务，进入 cooldown，保留截图证据并人工处理验证。",
    },
    "PROXY_FAILED": {
        "severity": "high",
        "cause": "代理或网络失败。",
        "action": "自动换同分组 Profile；检查代理线路，避免继续使用该 Profile 执行触达。",
    },
    "VIDEO_SCAN_FAILED": {
        "severity": "medium",
        "cause": "视频列表解析失败或页面结构变化。",
        "action": "查看 collector_evidence；尝试 injected_script/CDP 采集路径并更新选择器。",
    },
    "VIDEO_SCAN_EMPTY": {
        "severity": "info",
        "cause": "创作者页可打开，但本轮没有解析到公开视频链接。",
        "action": "检查 Profile 登录/地区可见性、账号公开视频状态和视频列表截图；可改用 content_url 或 keyword 补采。",
    },
    "COMMENT_SCAN_FAILED": {
        "severity": "medium",
        "cause": "评论区解析失败、懒加载失败或评论区不可见。",
        "action": "降低单视频评论采集量，重试滚动；若仍失败，检查登录/语言/评论权限状态。",
    },
    "COMMENT_SCAN_EMPTY": {
        "severity": "info",
        "cause": "视频页可打开，但本轮评论区为空或没有可解析评论。",
        "action": "确认视频是否关闭评论、是否需要登录/地区权限；保留截图证据，必要时改用评论接口/CDP 采集。",
    },
    "COMMENT_ACCESS_GATED": {
        "severity": "high",
        "cause": "视频能打开，但评论区被登录页、注册弹窗或评论权限挡住。",
        "action": "自动换同分组下一个可读评论的 Profile；若连续出现，人工检查该分组登录状态和地区权限。",
    },
    "TOPIC_CONTENT_SCAN_FAILED": {
        "severity": "medium",
        "cause": "搜索/话题页素材解析失败。",
        "action": "检查关键词/hashtag 是否有结果；查看页面地区语言和 collector evidence。",
    },
    "REPORT_EXPORT_FAILED": {
        "severity": "medium",
        "cause": "报告文件写入失败。",
        "action": "检查 reports 目录权限、文件占用和磁盘空间。",
    },
    "OUTREACH_POLICY_BLOCKED": {
        "severity": "low",
        "cause": "触达动作被审核、确认、排除名单、配额或风控策略阻断。",
        "action": "进入动作队列复核；按错误码处理二次确认、排除名单或日配额。",
    },
}


class ErrorDiagnosticService:
    def __init__(self, storage: GrowthStorage):
        self.storage = storage

    def build_diagnostics(self, limit: int = 200) -> list[dict]:
        rows = self.storage.list_errors(limit=limit)
        counts = Counter(row.get("error_code") for row in rows)
        latest_by_code = {}
        for row in rows:
            latest_by_code.setdefault(row.get("error_code"), row)
        comment_diagnostics = self._recent_comment_diagnostics()
        evidence_by_entity = self._recent_collector_evidence()
        diagnostics = []
        for error_code, count in counts.most_common():
            latest = latest_by_code.get(error_code) or {}
            comment_detail = self._matching_comment_diagnostic(error_code, comment_diagnostics)
            evidence = evidence_by_entity.get(comment_detail.get("content_id") or latest.get("creator_id") or latest.get("source_id") or "", {})
            batch_id = latest.get("batch_id", "") or self.storage.latest_failed_batch_for_error(error_code).get("batch_id", "")
            failed_tasks = self.storage.list_failed_collection_tasks(batch_id=batch_id, error_code=error_code, limit=50) if batch_id else []
            rule = DIAGNOSTIC_RULES.get(
                error_code,
                {
                    "severity": "medium",
                    "cause": "未归类错误。",
                    "action": "查看错误消息和相关任务日志，必要时重跑失败任务。",
                },
            )
            diagnostics.append(
                {
                    "error_code": error_code,
                    "count": int(count),
                    "severity": rule["severity"],
                    "cause": rule["cause"],
                    "suggested_action": rule["action"],
                    "latest_message": latest.get("message", ""),
                    "source_id": latest.get("source_id", ""),
                    "creator_id": latest.get("creator_id", ""),
                    "profile_id": latest.get("profile_id", ""),
                    "batch_id": batch_id,
                    "failed_task_count": len(failed_tasks),
                    "rerun_available": bool(failed_tasks),
                    "latest_source_value": failed_tasks[0].get("source_value", "") if failed_tasks else "",
                    "latest_at": latest.get("created_at", ""),
                    "page_state": comment_detail.get("page_state", ""),
                    "stop_reason": comment_detail.get("stop_reason", ""),
                    "visible_node_count": comment_detail.get("visible_node_count", ""),
                    "comment_container_count": comment_detail.get("comment_container_count", ""),
                    "screenshot_path": evidence.get("screenshot_path", ""),
                    "collector_level": evidence.get("level", ""),
                    "collector_adapter": evidence.get("adapter_name", ""),
                }
            )
        return diagnostics

    def _recent_comment_diagnostics(self) -> list[dict]:
        rows = self.storage.list_recent_events("comments_collected", limit=100)
        diagnostics = []
        for row in rows:
            payload = self._parse_json(row.get("payload"))
            item = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
            if not item:
                continue
            diagnostics.append(
                {
                    "content_id": row.get("entity_id", ""),
                    "page_state": item.get("page_state", ""),
                    "error_code": item.get("error_code", ""),
                    "stop_reason": item.get("stop_reason", ""),
                    "visible_node_count": item.get("visible_node_count", item.get("max_visible_nodes", "")),
                    "comment_container_count": item.get("comment_container_count", ""),
                    "created_at": row.get("created_at", ""),
                }
            )
        return diagnostics

    def _recent_collector_evidence(self) -> dict[str, dict]:
        rows = self.storage.list_recent_events("collector_evidence", limit=200)
        evidence_by_entity = {}
        for row in rows:
            payload = self._parse_json(row.get("payload"))
            if not isinstance(payload, dict):
                continue
            evidence_by_entity.setdefault(str(row.get("entity_id") or ""), payload)
        return evidence_by_entity

    def _matching_comment_diagnostic(self, error_code: str, diagnostics: list[dict]) -> dict:
        for item in diagnostics:
            if item.get("error_code") == error_code:
                return item
        if error_code in {"COMMENT_SCAN_EMPTY", "LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED"} and diagnostics:
            return diagnostics[0]
        return {}

    def _parse_json(self, value):
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
