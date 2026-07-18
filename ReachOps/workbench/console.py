# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from .view_models import GrowthOpsSnapshot, status_label


LANGUAGE_FILTER_VALUES = ["all", "en", "pt", "es", "fr", "de", "it", "id", "vi", "zh", "ja", "ko", "th", "ar", "ru", "latin", "unknown"]
LANGUAGE_FILTER_LABELS = {
    "all": "全部语言",
    "en": "英语",
    "pt": "葡语",
    "es": "西语",
    "fr": "法语",
    "de": "德语",
    "it": "意语",
    "id": "印尼语",
    "vi": "越南语",
    "zh": "中文",
    "ja": "日语",
    "ko": "韩语",
    "th": "泰语",
    "ar": "阿语",
    "ru": "俄语",
    "latin": "拉丁语系",
    "unknown": "未识别",
}
LEAD_TIER_LABELS = {"all": "全部线索", "high": "高价值", "observe": "可观察", "low": "低价值"}
PROFILE_COMPLETED_LABELS = {"all": "全部主页", "yes": "有主页", "no": "无主页"}
ACTION_STATUS_LABELS = {
    "all": "全部状态",
    "pending": "待处理",
    "running": "执行中",
    "success": "成功",
    "failed": "失败",
    "skipped": "已跳过",
    "account_switched": "已换号",
    "pending_review": "待审核",
    "approved": "已批准",
    "retryable": "可重试",
    "completed": "已完成",
    "rejected": "已拒绝",
}
RISK_FILTER_LABELS = {"all": "全部风险", "low": "低风险", "medium": "中风险", "high": "高风险"}
REVIEW_FILTER_LABELS = {"all": "全部审核", "pending": "待审核", "approved": "已批准", "rejected": "已拒绝"}
TEMPLATE_STATUS_LABELS = {"active": "启用", "paused": "暂停"}

OPERATOR_VIEW_NAMES = ["获客任务", "信息沙漏", "线索分析", "触达执行", "账号诊断", "报告中心"]


def safe_tk_option(value: str) -> str:
    text = str(value or "").replace("\ufffd", "?")
    text = "".join(ch if (ch == "\t" or ord(ch) >= 32) else " " for ch in text)
    return text.strip()


def is_stable_combobox_option(value: str) -> bool:
    text = str(value or "")
    return bool(text)


def group_name_from_display(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("[") and "] " in text:
        text = text.split("] ", 1)[1].strip()
    if " 个账号 | " in text or text.startswith("待读取账号数 | "):
        text = text.split(" | ", 1)[1].strip()
    if " · " in text:
        return text.split(" · ", 1)[0].strip()
    if text.endswith(")") and "(ID:" in text:
        text = text.rsplit("(ID:", 1)[0].strip()
        return text
    if text.endswith(")") and "(" in text:
        text = text.rsplit("(", 1)[0].strip()
    if " | ID " in text:
        text = text.split(" | ID ", 1)[0].strip()
    return text

UI_COLORS = {
    "bg": "#1f2327",
    "surface": "#2b3036",
    "surface_alt": "#343a40",
    "border": "#59616a",
    "text": "#ffffff",
    "muted": "#d1d5db",
    "nav": "#2b3036",
    "nav_text": "#ffffff",
    "nav_muted": "#d1d5db",
    "accent": "#ffffff",
    "accent_soft": "#4b5563",
    "warning_bg": "#3f3f46",
    "warning": "#f8fafc",
    "terminal_bg": "#0c0d0e",
    "terminal_text": "#d1d5db",
    "terminal_muted": "#9ca3af",
    "terminal_info": "#60a5fa",
    "terminal_success": "#22c55e",
    "terminal_warning": "#fbbf24",
    "terminal_error": "#f87171",
    "fullscreen_bg": "#1f2327",
}


def ui_font(size: int = 10, weight: str = "normal"):
    family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
    if weight and weight != "normal":
        return (family, size, weight)
    return (family, size)

PAGE_SUBTITLES = {
    "获客任务": "输入产品、关键词、达人、视频或直播间，系统自动规划来源、采集互动用户并沉淀客户线索。",
    "信息沙漏": "用上中下三层展示输入、判断和沉淀结果，快速判断任务卡在采集、风控还是触达。",
    "潜在客户池": "按分数、语言、关键词筛选高意向用户，支持导出和排除。",
    "意图分析": "查看购买、咨询、兴趣和低质量评论分布，判断下一轮采集方向。",
    "待执行动作": "动作进入复核和执行前预检；当前版本不会误提交评论、关注或私信。",
    "账号状态": "查看账号可用性、失败原因、冷却状态和执行记录。",
    "报告中心": "导出日报、JSON、线索 CSV 和动作计划，方便运营交接。",
}

ACTION_TYPE_LABELS = {
    "comment_reply": "评论",
    "follow_review": "关注",
    "dm_review": "私信",
}

RISK_LABELS = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}

ERROR_CODE_HELP = {
    "": "",
    "ACTION_REQUIRES_REVIEW": "需要先人工复核",
    "ACTION_REQUIRES_EXECUTION_CONFIRMATION": "需要执行前确认",
    "COMMENT_EXECUTION_DISABLED": "评论执行未开启",
    "FOLLOW_EXECUTION_DISABLED": "关注执行未开启",
    "DM_EXECUTION_DISABLED": "私信执行未开启",
    "DAILY_QUOTA_EXCEEDED": "账号今日额度已满",
    "TARGET_EXCLUDED": "目标在排除名单",
    "PROFILE_IN_COOLDOWN": "账号正在冷却",
    "PUBLISH_PROFILE_BLOCKED": "发布主账号被保护拦截",
    "LOGIN_REQUIRED": "账号登录失效",
    "CAPTCHA_DETECTED": "出现验证码",
    "PROXY_FAILED": "代理不可用",
    "PROFILE_START_FAILED": "账号环境启动失败",
    "EMPTY_RESULT_RETRY": "账号已打开页面但没有采到内容，系统会自动换号继续",
    "COMMENT_BOX_NOT_FOUND": "评论输入框未找到",
    "COMMENT_SUBMIT_FAILED": "评论提交失败",
    "COMMENT_BLOCKED": "评论被平台限制",
    "FOLLOW_BUTTON_MISSING": "关注按钮不可用",
    "FOLLOW_RATE_LIMITED": "关注被限频",
    "DM_ENTRY_NOT_FOUND": "私信入口不可用",
    "DM_NOT_ALLOWED": "对方不允许私信",
    "DM_RATE_LIMITED": "私信被限频",
    "VIDEO_HOURLY_LIMIT_EXCEEDED": "同视频触达过于频繁",
    "PROFILE_HOURLY_LIMIT_EXCEEDED": "账号小时额度已满",
}

SOURCE_TYPE_LABELS = {
    "auto": "自动识别",
    "creator_url": "达人主页",
    "content_url": "视频链接",
    "live_room_url": "直播间活跃用户",
    "keyword": "关键词搜索",
    "topic": "话题/趋势",
    "hashtag": "标签",
    "product_url": "商品页",
    "shop_url": "店铺页",
}
SOURCE_TYPE_ALIASES = {
    **{key: key for key in SOURCE_TYPE_LABELS},
    **{value: key for key, value in SOURCE_TYPE_LABELS.items()},
    "达人主页链接": "creator_url",
    "竞品达人": "creator_url",
    "视频链接": "content_url",
    "video": "content_url",
    "video_url": "content_url",
    "content": "content_url",
    "content_url": "content_url",
    "视频评论": "content_url",
    "单条视频": "content_url",
    "单条视频/内容链接": "content_url",
    "视频评论区": "content_url",
    "直播间": "live_room_url",
    "直播链接": "live_room_url",
    "关键词": "keyword",
    "搜索词": "keyword",
    "话题": "topic",
    "标签": "hashtag",
    "推广目标": "auto",
    "产品/关键词": "auto",
}

QUICK_SEND_MODE_LABELS = ["只采集", "采集 + 触达预检", "采集 + 真实评论"]
QUICK_SEND_VOLUME_PRESETS = {
    "快速": {"max_videos": 3, "max_comments": 20, "profile_limit": 3, "workers": 2, "task_interval": 3},
    "标准": {"max_videos": 10, "max_comments": 50, "profile_limit": 6, "workers": 4, "task_interval": 8},
    "压测": {"max_videos": 20, "max_comments": 100, "profile_limit": 10, "workers": 6, "task_interval": 1},
}


def normalize_source_type(source_type: str, default: str = "creator_url") -> str:
    value = str(source_type or "").strip()
    return SOURCE_TYPE_ALIASES.get(value, value if value in SOURCE_TYPE_LABELS else default)


def display_source_type(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(str(source_type or "").strip(), str(source_type or ""))


def display_action_type(action_type: str) -> str:
    return ACTION_TYPE_LABELS.get(str(action_type or "").strip(), str(action_type or ""))


def quick_send_preset(label: str) -> dict:
    value = str(label or "").strip()
    return dict(QUICK_SEND_VOLUME_PRESETS.get(value) or QUICK_SEND_VOLUME_PRESETS["快速"])


def quick_send_mode_key(label: str) -> str:
    value = str(label or "").strip()
    if value == "只采集":
        return "collect_only"
    if value == "采集 + 真实评论":
        return "live_comment"
    return "preflight"


def display_risk_level(risk_level: str) -> str:
    return RISK_LABELS.get(str(risk_level or "").strip(), str(risk_level or ""))


def display_error_code(error_code: str) -> str:
    code = str(error_code or "").strip()
    help_text = ERROR_CODE_HELP.get(code, "")
    return f"{code}（{help_text}）" if code and help_text else code


def format_campaign_plan_summary(plan: dict, range_config: dict | None = None, profile_group: str = "") -> str:
    plan = plan or {}
    range_config = range_config or {}
    campaign = plan.get("campaign") or {}
    persona = plan.get("persona") or {}
    sources = list(plan.get("sources") or [])
    input_label = display_source_type(str(campaign.get("input_type") or "auto"))
    product_name = str(campaign.get("product_name") or campaign.get("input_value") or "").strip()
    group = str(profile_group or "").strip() or "未选择"
    max_videos = int(range_config.get("max_videos") or 0)
    max_comments = int(range_config.get("max_comments") or 0)
    profile_limit = int(range_config.get("profile_limit") or 0)
    task_interval = int(range_config.get("task_interval") or 0)
    source_labels = []
    for row in sources[:6]:
        source_type = display_source_type(str(row.get("source_type") or ""))
        source_value = str(row.get("source_value") or "").strip()
        if source_value:
            source_labels.append(f"{source_type}: {source_value}")
    source_layers = _campaign_source_layer_summary(sources)
    intent_keywords = [str(item).strip() for item in (persona.get("intent_keywords") or []) if str(item).strip()]
    exclude_keywords = [str(item).strip() for item in (persona.get("exclude_keywords") or []) if str(item).strip()]
    lines = [
        f"识别结果：{input_label}  |  推广对象：{product_name or '待识别'}",
        f"执行路径：分析目标 -> 规划来源 -> 找相关视频/达人/话题 -> 扫评论区 -> 去重 -> 意图识别 -> 客户线索 -> 触达动作预检",
        f"采集来源：{'；'.join(source_labels) if source_labels else '暂无可执行来源'}",
        f"来源分层：{source_layers or '等待系统规划'}",
        f"本轮范围：账号分组 {group}；参与账号 {profile_limit or '-'}；每来源最多 {max_videos or '-'} 条视频；每视频最多 {max_comments or '-'} 条评论；间隔 {task_interval or '-'} 秒",
        f"意向判断：{', '.join(intent_keywords[:10]) if intent_keywords else '使用默认购买/咨询意向词'}",
    ]
    if exclude_keywords:
        lines.append(f"排除规则：{', '.join(exclude_keywords[:8])}")
    return "\n".join(lines)


def _campaign_source_layer_summary(sources: list[dict]) -> str:
    layers = []
    for row in sources or []:
        reason = str(row.get("reason") or "")
        source_type = str(row.get("source_type") or "")
        if "核心产品词" in reason:
            layers.append("核心产品内容")
        elif "评测内容" in reason or "review" in str(row.get("source_value") or "").lower():
            layers.append("评测/对比内容")
        elif "效果对比" in reason or "before after" in str(row.get("source_value") or "").lower():
            layers.append("效果验证内容")
        elif "使用场景" in reason or "routine" in str(row.get("source_value") or "").lower():
            layers.append("使用场景内容")
        elif source_type == "hashtag":
            layers.append("话题标签内容")
        elif source_type == "creator_url":
            layers.append("达人主页内容")
        elif source_type == "content_url":
            layers.append("单条视频评论区")
        elif source_type == "live_room_url":
            layers.append("直播间活跃用户")
        elif source_type == "keyword":
            layers.append("关键词相关内容")
    seen = set()
    result = []
    for layer in layers:
        if layer not in seen:
            seen.add(layer)
            result.append(layer)
    return " -> ".join(result[:6])


def _value_from_label(value: str, labels: dict[str, str], default: str = "all") -> str:
    text = str(value or "").strip()
    if text in labels:
        return text
    inverse = {label: key for key, label in labels.items()}
    return inverse.get(text, default)


def action_type_from_label(value: str) -> str:
    text = str(value or "").strip()
    for key in ACTION_TYPE_LABELS:
        if text == key or text == display_action_type(key):
            return key
    return text or "comment_reply"


def template_status_from_label(value: str) -> str:
    return _value_from_label(value, TEMPLATE_STATUS_LABELS, default="active")


def block_reason_from_label(value: str) -> str:
    text = str(value or "").strip()
    if not text or text == "全部阻断" or text == "all":
        return "all"
    if "（" in text:
        return text.split("（", 1)[0].strip()
    return text


def evidence_uri_for_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "file://")):
        return value
    try:
        return Path(os.path.abspath(os.path.expanduser(value))).as_uri()
    except Exception:
        return value


def parse_bulk_scan_sources(text: str, default_type: str = "creator_url") -> list[dict]:
    sources = []
    seen = set()
    fallback_type = normalize_source_type(default_type)
    for raw_line in str(text or "").replace(";", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        source_type = fallback_type
        value = line
        if "," in line:
            first, rest = line.split(",", 1)
            candidate_type = normalize_source_type(first.strip(), default="")
            if candidate_type:
                source_type = candidate_type
                value = rest.strip()
        elif "\t" in line:
            first, rest = line.split("\t", 1)
            candidate_type = normalize_source_type(first.strip(), default="")
            if candidate_type:
                source_type = candidate_type
                value = rest.strip()
        value = value.strip()
        if not value:
            continue
        key = (source_type, value)
        if key in seen:
            continue
        seen.add(key)
        sources.append({"type": source_type, "value": value})
    return sources


class GrowthOpsConsole(ttk.Frame):
    """Tkinter ReachOps operator console."""

    def __init__(
        self,
        master,
        workflow_service=None,
        on_start_collection=None,
        on_export_report=None,
        on_rerun_error=None,
        on_rerun_tasks=None,
        on_run_due_scans=None,
        on_run_selected_scan=None,
        on_refresh_profiles=None,
        operator_status_var=None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.workflow_service = workflow_service
        self.on_start_collection = on_start_collection
        self.on_export_report = on_export_report
        self.on_rerun_error = on_rerun_error
        self.on_rerun_tasks = on_rerun_tasks
        self.on_run_due_scans = on_run_due_scans
        self.on_run_selected_scan = on_run_selected_scan
        self.on_refresh_profiles = on_refresh_profiles
        self.operator_status_var = operator_status_var or tk.StringVar(value="")
        self.nav_var = tk.StringVar(value="获客任务")
        self.lead_tier_var = tk.StringVar(value=LEAD_TIER_LABELS["all"])
        self.lead_language_var = tk.StringVar(value=LANGUAGE_FILTER_LABELS["all"])
        self.lead_profile_var = tk.StringVar(value=PROFILE_COMPLETED_LABELS["all"])
        self.lead_keyword_var = tk.StringVar(value="")
        self.lead_preset_name_var = tk.StringVar(value="default")
        self.action_status_var = tk.StringVar(value=ACTION_STATUS_LABELS["all"])
        self.action_risk_var = tk.StringVar(value=RISK_FILTER_LABELS["all"])
        self.action_review_var = tk.StringVar(value=REVIEW_FILTER_LABELS["all"])
        self.action_block_reason_var = tk.StringVar(value="全部阻断")
        self.action_keyword_var = tk.StringVar(value="")
        self.action_preset_name_var = tk.StringVar(value="default")
        self.action_execution_mode_var = tk.StringVar(value="预检，不提交")
        self.action_execution_group_var = tk.StringVar(value="")
        self.action_execution_workers_var = tk.IntVar(value=2)
        self.action_execution_per_profile_var = tk.IntVar(value=5)
        self.action_execution_hour_limit_var = tk.IntVar(value=10)
        self.action_execution_video_hour_limit_var = tk.IntVar(value=1)
        self.action_execution_live_confirm_var = tk.BooleanVar(value=False)
        self.action_review_summary_vars = {}
        self.execution_readiness_summary_vars = {}
        self.scan_source_type_var = tk.StringVar(value=display_source_type("auto"))
        self.scan_source_value_var = tk.StringVar(value="")
        self.scan_profile_group_var = tk.StringVar(value="")
        self.scan_profile_group_display_var = tk.StringVar(value="")
        self.scan_profile_group_detail_var = tk.StringVar(value="当前账号分组：请刷新账号分组")
        self.quick_send_mode_var = tk.StringVar(value="采集 + 触达预检")
        self.quick_send_volume_var = tk.StringVar(value="快速")
        default_quick_send = quick_send_preset(self.quick_send_volume_var.get())
        self.scan_interval_var = tk.IntVar(value=int(default_quick_send["task_interval"]))
        self.scan_max_videos_var = tk.IntVar(value=int(default_quick_send["max_videos"]))
        self.scan_max_comments_var = tk.IntVar(value=int(default_quick_send["max_comments"]))
        self.scan_profile_limit_var = tk.IntVar(value=3)
        self.scan_intent_keywords_var = tk.StringVar(value="price, buy, link, download, app, coupon")
        self.scan_exclude_keywords_var = tk.StringVar(value="haha, lol, spam")
        self.quick_comment_text_var = tk.StringVar(value="")
        self.comment_reply_strategy_var = tk.StringVar(value="规则模板（默认）")
        self.comment_reply_ai_endpoint_var = tk.StringVar(value=os.environ.get("REACHOPS_AI_ENDPOINT", ""))
        self.comment_reply_ai_model_var = tk.StringVar(value=os.environ.get("REACHOPS_AI_MODEL", "reachops-default"))
        self.comment_reply_ai_key_var = tk.StringVar(value="")
        self.comment_reply_ai_status_var = tk.StringVar(
            value="AI Key 已配置" if os.environ.get("REACHOPS_AI_API_KEY") else "AI Key 未配置"
        )
        self.recommended_source_value_var = tk.StringVar(value="")
        self.template_action_type_var = tk.StringVar(value=display_action_type("comment_reply"))
        self.template_name_var = tk.StringVar(value="")
        self.template_status_var = tk.StringVar(value=TEMPLATE_STATUS_LABELS["active"])
        self.template_body_text = None
        self.exclusion_username_var = tk.StringVar(value="")
        self.exclusion_url_var = tk.StringVar(value="")
        self.exclusion_reason_var = tk.StringVar(value="")
        self.scan_bulk_text = None
        self.runtime_log_text = None
        self.runtime_stage_texts = {}
        self.runtime_fullscreen_window = None
        self.runtime_fullscreen_stage_texts = {}
        self.runtime_fullscreen_funnel_text = None
        self.funnel_terminal_text = None
        self.campaign_plan_text = None
        self.report_text = None
        self.funnel_result_vars = {}
        self.hourglass_canvas = None
        self.hourglass_metric_vars = {}
        self.hourglass_layer_vars = {}
        self.hourglass_decision_var = tk.StringVar(value="等待开始获客。")
        self.hourglass_state_var = tk.StringVar(value="待执行")
        self.start_group_combobox = None
        self.start_group_listbox = None
        self.start_refresh_groups_button = None
        self._trees = {}
        self._nav_buttons = {}
        self._nested_views = {}
        self.page_title_var = tk.StringVar(value="获客任务")
        self.page_subtitle_var = tk.StringVar(value=PAGE_SUBTITLES["获客任务"])
        self.last_snapshot = GrowthOpsSnapshot()
        self._build()

    def _build(self):
        self._configure_style()
        self.configure(style="App.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        nav = tk.Frame(self, bg=UI_COLORS["nav"], highlightthickness=1, highlightbackground=UI_COLORS["border"])
        nav.grid(row=0, column=0, sticky="ew")
        nav.columnconfigure(0, weight=1)

        tabs = tk.Frame(nav, bg=UI_COLORS["nav"])
        tabs.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=4)
        view_names = list(OPERATOR_VIEW_NAMES)
        for idx in range(len(view_names)):
            tabs.columnconfigure(idx, weight=1, uniform="nav")
        for idx, name in enumerate(view_names):
            button = tk.Radiobutton(
                tabs,
                text=name,
                value=name,
                variable=self.nav_var,
                command=self._switch_view,
                indicatoron=False,
                anchor="center",
                relief="flat",
                bd=0,
                padx=12,
                pady=5,
                bg=UI_COLORS["nav"],
                fg=UI_COLORS["nav_text"],
                activebackground=UI_COLORS["accent_soft"],
                activeforeground=UI_COLORS["accent"],
                selectcolor=UI_COLORS["accent_soft"],
                font=ui_font(10),
            )
            button.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 4, 0))
            self._nav_buttons[name] = button
        content = tk.Frame(
            self,
            bg=UI_COLORS["bg"],
            highlightthickness=0,
            padx=8,
            pady=6,
        )
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        page_header = tk.Frame(
            content,
            bg=UI_COLORS["surface"],
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
            padx=12,
            pady=8,
        )
        page_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        page_header.columnconfigure(0, weight=1)
        tk.Label(
            page_header,
            textvariable=self.page_title_var,
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["text"],
            font=ui_font(14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            page_header,
            textvariable=self.operator_status_var,
            bg=UI_COLORS["accent_soft"],
            fg=UI_COLORS["accent"],
            font=ui_font(9, "bold"),
            padx=10,
            pady=4,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        self.stack = tk.Frame(content, bg=UI_COLORS["bg"], highlightthickness=0)
        self.stack.grid(row=1, column=0, sticky="nsew")
        self.stack.columnconfigure(0, weight=1)
        self.stack.rowconfigure(0, weight=1)
        self.views = {}
        hidden_view_names = ["数据源", "定时扫描", "采集批次", "采集任务", "执行计划", "执行记录", "设置/风控"]
        for name in view_names + hidden_view_names:
            frame = tk.Frame(self.stack, bg=UI_COLORS["bg"], highlightthickness=0)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.views[name] = frame
        self._build_nested_tab_view(
            "线索分析",
            [
                ("线索池", "潜在客户池"),
                ("意图分析", "意图分析"),
                ("素材", "内容/素材"),
                ("创作者", "创作者池"),
                ("运营线索", "运营线索"),
            ],
        )
        self._build_nested_tab_view(
            "触达执行",
            [
                ("待执行动作", "待执行动作"),
                ("执行计划", "执行计划"),
                ("执行记录", "执行记录"),
                ("话术/排除", "模板/排除"),
            ],
        )
        self._build_nested_tab_view(
            "账号诊断",
            [
                ("账号状态", "账号状态"),
                ("错误诊断", "错误诊断"),
                ("账号健康", "账号健康"),
                ("账号推荐", "账号推荐"),
            ],
        )
        self.views["总览"] = self.views["获客任务"]
        self.views["线索池"] = self.views["潜在客户池"]
        self.views["动作队列"] = self.views["待执行动作"]
        self.views["报告"] = self.views["报告中心"]
        self._build_start_collection_page(self.views["获客任务"])
        self._build_hourglass_page(self.views["信息沙漏"])
        self._switch_view()
        self._build_table_view("数据源", ["type", "value", "status", "updated_at"])
        self._build_table_view("定时扫描", ["id", "source_type", "source_value", "profile_group", "schedule_interval_minutes", "next_run_at", "status", "last_batch_id"])
        self._hide_tree_column("定时扫描", "id")
        self._build_scheduled_scan_actions(self.views["定时扫描"])
        self._build_table_view("采集批次", ["id", "status", "total_sources", "processed_sources", "failed_sources", "profile_group", "started_at", "completed_at"], detail=True)
        self._build_collection_batch_actions(self.views["采集批次"])
        self._build_table_view(
            "采集任务",
            ["id", "batch_id", "source_type", "source_value", "profile_id", "status", "error_code", "error_message", "updated_at"],
            detail=True,
        )
        self._hide_tree_column("采集任务", "id")
        self._build_collection_task_actions(self.views["采集任务"])
        self._build_table_view("账号健康", ["profile_id", "group_name", "health_score", "status", "last_error_code"])
        self._build_table_view("账号推荐", ["group_name", "recommended_profile_id", "status", "health_score", "healthy_count", "degraded_count", "cooldown_count", "reason", "last_error_code"], detail=True)
        self._build_table_view(
            "错误诊断",
            [
                "severity",
                "error_code",
                "count",
                "profile_id",
                "batch_id",
                "failed_task_count",
                "rerun_available",
                "latest_source_value",
                "page_state",
                "stop_reason",
                "visible_node_count",
                "screenshot_path",
                "cause",
                "suggested_action",
            ],
            detail=True,
        )
        self._build_error_diagnostics_actions(self.views["错误诊断"])
        self._build_table_view(
            "内容/素材",
            ["video_id", "caption", "views", "comments", "signal_score", "content_kind", "shop_name", "commerce_title", "video_url", "signal_tags"],
            detail=True,
        )
        self._hide_tree_column("内容/素材", "video_url")
        self._hide_tree_column("内容/素材", "signal_tags")
        self._build_content_actions(self.views["内容/素材"])
        self._build_table_view(
            "创作者池",
            ["username", "profile_url", "followers", "likes_total", "vertical", "country", "language", "status", "source_path", "batch_id", "last_checked_at"],
            detail=True,
        )
        self._hide_tree_column("创作者池", "profile_url")
        self._hide_tree_column("创作者池", "source_path")
        self._build_creator_actions(self.views["创作者池"])
        self._build_candidate_view(self.views["潜在客户池"])
        self._build_intent_analysis_view(self.views["意图分析"])
        self._build_table_view("运营线索", ["username", "lead_type", "priority", "score", "lifecycle_stage", "action_count", "source_path", "reason"], detail=True)
        self._build_action_queue_view(self.views["待执行动作"])
        self._build_table_view("执行计划", ["id", "profile_id", "selected_count", "planned_count", "executable_count", "skipped_count", "status", "export_path", "created_at"], detail=True)
        self._hide_tree_column("执行计划", "id")
        self._build_execution_plan_actions(self.views["执行计划"])
        self._build_table_view("执行记录", ["action_type", "target_username", "status", "profile_id", "error_code"])
        self._build_policy_data_view(self.views["模板/排除"])
        self._build_account_status_view(self.views["账号状态"])
        self._build_report_view(self.views["报告中心"])
        self._build_policy_view(self.views["设置/风控"])
        self._switch_view()

    def _build_nested_tab_view(self, parent_name: str, tabs: list[tuple[str, str]]):
        parent = self.views[parent_name]
        self._configure_content_container(parent)
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")
        for index, (tab_label, view_name) in enumerate(tabs):
            frame = ttk.Frame(notebook, style="Content.TFrame")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            notebook.add(frame, text=tab_label)
            self.views[view_name] = frame
            self._nested_views[view_name] = (parent_name, notebook, index)

    def _configure_content_container(self, frame):
        try:
            frame.configure(style="Content.TFrame")
        except tk.TclError:
            try:
                frame.configure(bg=UI_COLORS["bg"])
            except Exception:
                pass

    def _configure_style(self):
        style = ttk.Style(self)
        font = ui_font(10)
        style.configure(".", font=font)
        style.configure("App.TFrame", background=UI_COLORS["bg"])
        style.configure("Content.TFrame", background=UI_COLORS["bg"])
        style.configure("Panel.TFrame", background=UI_COLORS["bg"])
        style.configure("Metric.TFrame", background=UI_COLORS["bg"])
        style.configure("TLabel", background=UI_COLORS["bg"], foreground=UI_COLORS["text"])
        style.configure("Muted.TLabel", background=UI_COLORS["bg"], foreground=UI_COLORS["muted"])
        style.configure("PageTitle.TLabel", background=UI_COLORS["bg"], foreground=UI_COLORS["text"], font=ui_font(14, "bold"))
        style.configure("PageSubtitle.TLabel", background=UI_COLORS["bg"], foreground=UI_COLORS["muted"], font=ui_font(9))
        style.configure(
            "Badge.TLabel",
            background=UI_COLORS["accent_soft"],
            foreground=UI_COLORS["accent"],
            padding=(10, 4),
            font=ui_font(9, "bold"),
        )
        style.configure(
            "Panel.TLabelframe",
            background=UI_COLORS["bg"],
            padding=8,
        )
        style.configure(
            "Panel.TLabelframe.Label",
            background=UI_COLORS["bg"],
            foreground=UI_COLORS["text"],
            font=ui_font(10, "bold"),
        )
        style.configure("TButton", padding=(10, 5), font=ui_font(10))
        style.configure("Primary.TButton", padding=(12, 6), font=ui_font(10, "bold"))
        style.configure("Treeview", rowheight=25, font=ui_font(10))
        style.configure("Treeview.Heading", font=ui_font(10, "bold"))

    def _style_nav_buttons(self):
        selected = self.nav_var.get()
        for name, button in self._nav_buttons.items():
            is_selected = name == selected
            button.configure(
                bg=UI_COLORS["accent_soft"] if is_selected else UI_COLORS["nav"],
                fg=UI_COLORS["accent"] if is_selected else UI_COLORS["nav_text"],
                font=ui_font(10, "bold" if is_selected else "normal"),
            )

    def _build_overview(self, frame):
        frame.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="开始获客", command=self._start_collection).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="刷新工作台", command=self.refresh).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="导出报告", command=self._export_report).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="执行到期扫描", command=self._run_due_scans).pack(side=tk.LEFT, padx=(8, 0))
        self.summary_frame = ttk.LabelFrame(frame, text="今日增长机会", padding=10)
        self.summary_frame.grid(row=1, column=0, sticky="ew")
        self.summary_vars = {}
        for idx, key in enumerate(["data_sources", "scheduled_scans", "collection_batches", "collection_tasks", "profile_health", "error_diagnostics", "creators", "contents", "topic_contents", "candidates", "operation_leads", "action_queue", "execution_plans", "outreach_executions", "exclusions", "daily_quota", "rate_limits", "filter_presets"]):
            box = ttk.Frame(self.summary_frame)
            box.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=8, pady=4)
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.summary_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 14, "bold")).pack(anchor="w")
        self.operational_status_frame = ttk.LabelFrame(frame, text="本轮采集状态", padding=8)
        self.operational_status_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.operational_status_vars = {}
        for idx, key in enumerate(
            [
                "status",
                "completion_rate",
                "candidate_user_count",
                "high_value_candidate_count",
                "comment_quality",
                "top_error_code",
                "next_operator_action",
            ]
        ):
            box = ttk.Frame(self.operational_status_frame)
            box.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=8, pady=4)
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="")
            self.operational_status_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 12, "bold"), wraplength=260, justify="left").pack(anchor="w")
        self.brief_frame = ttk.LabelFrame(frame, text="运营简报", padding=8)
        self.brief_frame.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(4, weight=1)
        self.overview_brief_text = tk.Text(self.brief_frame, height=12, wrap="word")
        self.overview_brief_text.pack(fill=tk.BOTH, expand=True)
        self.source_recommendation_frame = ttk.LabelFrame(frame, text="下一轮采集源", padding=8)
        self.source_recommendation_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        columns = ["priority", "source_type", "source_value", "scenario", "reason"]
        tree = ttk.Treeview(self.source_recommendation_frame, columns=columns, show="headings", height=3)
        for column in columns:
            tree.heading(column, text=self._label(column))
            tree.column(column, width=160, anchor="w")
        tree.column("source_value", width=260)
        tree.column("scenario", width=240)
        tree.column("reason", width=360)
        tree.grid(row=0, column=0, sticky="ew")
        action_bar = ttk.Frame(self.source_recommendation_frame)
        action_bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(action_bar, text="具体链接/关键词").pack(side=tk.LEFT)
        ttk.Entry(action_bar, textvariable=self.recommended_source_value_var, width=44).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(action_bar, text="按推荐新增扫描", command=self._create_scan_from_selected_recommendation).pack(side=tk.LEFT)
        ttk.Button(action_bar, text="查看定时扫描", command=lambda: self.nav_var.set("获客任务") or self._switch_view()).pack(side=tk.LEFT, padx=(8, 0))
        self.source_recommendation_frame.columnconfigure(0, weight=1)
        self._trees["下一轮采集源"] = tree

    def _build_start_collection_page(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=0)
        frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(frame, style="Content.TFrame")
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(0, weight=1, uniform="control")
        controls.columnconfigure(1, weight=1, uniform="control")

        task_box = ttk.LabelFrame(controls, text="任务启动", padding=6, style="Panel.TLabelframe")
        task_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        task_box.columnconfigure(1, weight=3)
        task_box.columnconfigure(3, weight=2)
        self.scan_source_type_var.set("自动识别")
        ttk.Label(task_box, text="推广目标").grid(row=0, column=0, sticky="w")
        ttk.Entry(task_box, textvariable=self.scan_source_value_var).grid(row=0, column=1, sticky="ew", padx=(6, 12))
        ttk.Label(task_box, text="账号分组").grid(row=0, column=2, sticky="w")
        group_row = ttk.Frame(task_box, style="Panel.TFrame")
        group_row.grid(row=0, column=3, sticky="ew", padx=(6, 8))
        group_row.columnconfigure(0, weight=1)
        self.start_group_combobox = ttk.Combobox(
            group_row,
            textvariable=self.scan_profile_group_display_var,
            values=["请刷新账号分组"],
            state="readonly",
            width=34,
        )
        self.start_group_combobox.grid(row=0, column=0, sticky="ew")
        self.start_group_combobox.bind("<<ComboboxSelected>>", self._on_start_group_selected)
        self.start_refresh_groups_button = ttk.Button(group_row, text="刷新", command=self._refresh_profile_groups)
        self.start_refresh_groups_button.grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.start_group_listbox = tk.Listbox(
            task_box,
            height=1,
            exportselection=False,
            activestyle="dotbox",
            font=ui_font(9),
        )
        self.start_group_listbox.bind("<<ListboxSelect>>", self._on_start_group_list_selected)
        task_actions = ttk.Frame(task_box, style="Panel.TFrame")
        task_actions.grid(row=0, column=4, sticky="e")
        ttk.Button(task_actions, text="开始获客", command=self._start_collection, style="Primary.TButton").pack(side=tk.LEFT)
        ttk.Button(task_actions, text="导出报告", command=self._export_report).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(
            task_box,
            textvariable=self.scan_profile_group_detail_var,
            foreground=UI_COLORS["muted"],
            wraplength=620,
        ).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        left_stack = ttk.Frame(controls, style="Content.TFrame")
        left_stack.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        left_stack.columnconfigure(0, weight=1)

        right_stack = ttk.Frame(controls, style="Content.TFrame")
        right_stack.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        right_stack.columnconfigure(0, weight=1)

        rule_box = ttk.LabelFrame(left_stack, text="运营设置", padding=6, style="Panel.TLabelframe")
        rule_box.grid(row=0, column=0, sticky="ew")
        for idx in range(6):
            rule_box.columnconfigure(idx, weight=1)
        ttk.Label(rule_box, text="执行模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            rule_box,
            textvariable=self.quick_send_mode_var,
            values=QUICK_SEND_MODE_LABELS,
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(rule_box, text="目标数量").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            rule_box,
            textvariable=self.quick_send_volume_var,
            values=list(QUICK_SEND_VOLUME_PRESETS.keys()),
            state="readonly",
            width=8,
        ).grid(row=0, column=3, sticky="w")
        ttk.Button(rule_box, text="应用预设", command=self.apply_quick_send_preset).grid(row=0, column=4, columnspan=2, sticky="w")
        ttk.Label(rule_box, text="参与账号数").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(rule_box, from_=1, to=50, width=5, textvariable=self.scan_profile_limit_var).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(rule_box, text="每个目标最多视频").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(rule_box, from_=1, to=100, width=5, textvariable=self.scan_max_videos_var).grid(row=1, column=3, sticky="w", pady=(6, 0))
        ttk.Label(rule_box, text="每条视频最多评论").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Spinbox(rule_box, from_=1, to=500, width=5, textvariable=self.scan_max_comments_var).grid(row=1, column=5, sticky="w", pady=(6, 0))
        ttk.Label(rule_box, text="任务间隔秒").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(rule_box, from_=1, to=3600, width=5, textvariable=self.scan_interval_var).grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(rule_box, text="评论回复").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Combobox(
            rule_box,
            textvariable=self.comment_reply_strategy_var,
            values=("规则模板（默认）", "外部AI生成建议", "固定文案"),
            state="readonly",
            width=16,
        ).grid(row=2, column=3, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(rule_box, text="固定文案").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(rule_box, textvariable=self.quick_comment_text_var).grid(row=3, column=1, columnspan=5, sticky="ew", pady=(6, 0))
        ttk.Label(rule_box, text="意向词").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(rule_box, textvariable=self.scan_intent_keywords_var).grid(row=4, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(rule_box, text="排除词").grid(row=4, column=3, sticky="w", pady=(6, 0))
        ttk.Entry(rule_box, textvariable=self.scan_exclude_keywords_var).grid(row=4, column=4, columnspan=2, sticky="ew", pady=(6, 0))
        ai_box = ttk.LabelFrame(left_stack, text="评论回复 AI 接入点", padding=6, style="Panel.TLabelframe")
        ai_box.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for idx in range(6):
            ai_box.columnconfigure(idx, weight=1)
        ttk.Label(ai_box, text="Endpoint").grid(row=0, column=0, sticky="w")
        ttk.Entry(ai_box, textvariable=self.comment_reply_ai_endpoint_var).grid(row=0, column=1, columnspan=5, sticky="ew")
        ttk.Label(ai_box, text="模型").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(ai_box, textvariable=self.comment_reply_ai_model_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(ai_box, text="API Key").grid(row=1, column=3, sticky="w", pady=(6, 0))
        ttk.Entry(ai_box, textvariable=self.comment_reply_ai_key_var, show="*").grid(row=1, column=4, sticky="ew", pady=(6, 0))
        ttk.Button(ai_box, text="应用AI设置", command=self.apply_comment_reply_ai_settings).grid(row=1, column=5, sticky="e", pady=(6, 0))
        ttk.Label(ai_box, textvariable=self.comment_reply_ai_status_var, foreground=UI_COLORS["muted"]).grid(
            row=2,
            column=0,
            columnspan=6,
            sticky="w",
            pady=(6, 0),
        )
        result_box = ttk.LabelFrame(right_stack, text="执行 / 结果", padding=6, style="Panel.TLabelframe")
        result_box.grid(row=0, column=0, sticky="nsew")
        result_box.rowconfigure(1, weight=1)
        for idx in range(6):
            result_box.columnconfigure(idx, weight=1, uniform="result")

        self.summary_vars = {}
        summary_keys = ["data_sources", "contents", "candidates", "operation_leads", "action_queue", "error_diagnostics"]
        for idx, key in enumerate(summary_keys):
            box = ttk.Frame(result_box, style="Metric.TFrame")
            box.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0), pady=(2, 0))
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.summary_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 10, "bold")).pack(anchor="w")
        self.operational_status_vars = {}

        plan_box = ttk.LabelFrame(result_box, text="自动采集方案", padding=6, style="Panel.TLabelframe")
        plan_box.grid(row=1, column=0, columnspan=6, sticky="nsew", pady=(6, 0))
        plan_box.columnconfigure(0, weight=1)
        plan_box.rowconfigure(0, weight=1)
        self.campaign_plan_text = tk.Text(
            plan_box,
            height=8,
            wrap="word",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["text"],
            relief="sunken",
            bd=1,
            padx=6,
            pady=5,
            font=ui_font(9),
        )
        self.campaign_plan_text.grid(row=0, column=0, sticky="nsew")
        self.show_campaign_plan({})

        terminal = ttk.LabelFrame(frame, text="量化执行终端", padding=8, style="Panel.TLabelframe")
        terminal.grid(row=1, column=0, sticky="nsew")
        terminal.columnconfigure(0, weight=1)
        terminal.rowconfigure(1, weight=1)
        runtime_toolbar = ttk.Frame(terminal, style="Panel.TFrame")
        runtime_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(runtime_toolbar, text="清空日志", command=self.clear_runtime_log).pack(side=tk.LEFT)
        ttk.Button(runtime_toolbar, text="复制日志", command=self.copy_runtime_log).pack(side=tk.LEFT, padx=(8, 0))
        funnel_body = ttk.Frame(terminal, style="Panel.TFrame")
        funnel_body.grid(row=1, column=0, sticky="nsew")
        funnel_body.columnconfigure(0, weight=0, minsize=230)
        funnel_body.columnconfigure(1, weight=1)
        funnel_body.rowconfigure(0, weight=1)

        result_panel = ttk.Frame(funnel_body, style="Panel.TFrame")
        result_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        result_panel.columnconfigure(0, weight=1)
        result_panel.rowconfigure(1, weight=1)
        ttk.Label(result_panel, text="本轮漏斗", font=("", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        funnel_keys = [
            ("data_sources", "来源"),
            ("contents", "视频"),
            ("candidates", "用户"),
            ("operation_leads", "高意向"),
            ("action_queue", "待触达"),
            ("error_diagnostics", "异常"),
        ]
        self.funnel_result_vars = {}
        for key, _label in funnel_keys:
            self.funnel_result_vars[key] = tk.StringVar(value="0")
        self.funnel_terminal_text = tk.Text(
            result_panel,
            height=20,
            width=28,
            wrap="none",
            bg=UI_COLORS["terminal_bg"],
            fg=UI_COLORS["terminal_text"],
            insertbackground=UI_COLORS["terminal_muted"],
            relief="sunken",
            bd=1,
            padx=8,
            pady=8,
            font=("Consolas", 9),
        )
        self._configure_terminal_tags(self.funnel_terminal_text)
        self.funnel_terminal_text.grid(row=1, column=0, sticky="nsew")

        stage_frame = ttk.Frame(funnel_body, style="Panel.TFrame")
        stage_frame.grid(row=0, column=1, sticky="nsew")
        stage_frame.rowconfigure(0, weight=1)
        stages = [
            ("all", "总日志"),
            ("collect", "采集"),
            ("content", "视频"),
            ("comment", "评论"),
            ("lead", "线索"),
            ("action", "触达"),
            ("error", "异常"),
        ]
        self.runtime_stage_texts = {}
        for idx, (key, label) in enumerate(stages):
            stage_frame.columnconfigure(idx, weight=1, uniform="runtime_stage")
            panel = ttk.Frame(stage_frame, style="Panel.TFrame")
            panel.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 5, 0))
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)
            ttk.Label(panel, text=label, anchor="center").grid(row=0, column=0, sticky="ew", pady=(0, 2))
            text = tk.Text(
                panel,
                height=20,
                width=18,
                wrap="none",
                bg=UI_COLORS["terminal_bg"],
                fg=UI_COLORS["terminal_text"],
                insertbackground=UI_COLORS["terminal_muted"],
                relief="sunken",
                bd=1,
                padx=5,
                pady=5,
                font=("Consolas", 8),
            )
            self._configure_terminal_tags(text)
            text.grid(row=1, column=0, sticky="nsew")
            self.runtime_stage_texts[key] = text
        self.runtime_log_text = self.runtime_stage_texts["all"]
        self._bind_runtime_fullscreen([funnel_body, result_panel, stage_frame, self.funnel_terminal_text, *self.runtime_stage_texts.values()])
        self._refresh_funnel_results(self.last_snapshot)
        self._refresh_hourglass(self.last_snapshot)
        self.append_runtime_log("READY  等待任务。左侧显示漏斗结果，右侧显示分阶段执行日志。")

    def _build_hourglass_page(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        headline = tk.Frame(frame, bg=UI_COLORS["surface"], highlightthickness=1, highlightbackground=UI_COLORS["border"], padx=14, pady=10)
        headline.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        headline.columnconfigure(0, weight=1)
        tk.Label(
            headline,
            textvariable=self.hourglass_state_var,
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["text"],
            font=ui_font(16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            headline,
            textvariable=self.hourglass_decision_var,
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["muted"],
            font=ui_font(10),
            anchor="w",
            justify="left",
            wraplength=1160,
        ).grid(row=1, column=0, sticky="ew", pady=(5, 0))

        body = ttk.Frame(frame, style="Content.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=300)
        body.rowconfigure(0, weight=1)

        flow = ttk.Frame(body, style="Content.TFrame")
        flow.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        flow.columnconfigure(0, weight=1)
        for row in range(3):
            flow.rowconfigure(row, weight=1, uniform="hourglass_layer")

        layer_specs = [
            ("top", "上层：输入与采集", "来源、页面、视频、评论用户是否正在进入系统。", "#18313a"),
            ("middle", "中层：判断与阻断", "账号、页面、风控、重试和可用性判断集中在这里。", "#3a2f18"),
            ("bottom", "下层：线索与触达沉淀", "高意向线索、动作队列和成功触达沉淀为可交付结果。", "#183320"),
        ]
        self.hourglass_layer_vars = {}
        for idx, (key, title, subtitle, color) in enumerate(layer_specs):
            layer = tk.Frame(flow, bg=color, highlightthickness=1, highlightbackground=UI_COLORS["border"], padx=14, pady=12)
            layer.grid(row=idx, column=0, sticky="nsew", pady=(0 if idx == 0 else 8, 0))
            layer.columnconfigure(1, weight=1)
            tk.Label(layer, text=title, bg=color, fg=UI_COLORS["text"], font=ui_font(13, "bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew")
            tk.Label(layer, text=subtitle, bg=color, fg=UI_COLORS["muted"], font=ui_font(9), anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 10))
            value_var = tk.StringVar(value="0")
            detail_var = tk.StringVar(value="等待执行数据。")
            self.hourglass_layer_vars[key] = {"value": value_var, "detail": detail_var}
            tk.Label(layer, textvariable=value_var, bg=color, fg=UI_COLORS["text"], font=ui_font(28, "bold"), width=8, anchor="w").grid(row=2, column=0, sticky="nw", padx=(0, 14))
            tk.Label(layer, textvariable=detail_var, bg=color, fg=UI_COLORS["text"], font=ui_font(11), anchor="nw", justify="left", wraplength=760).grid(row=2, column=1, sticky="nsew")

        side = ttk.LabelFrame(body, text="关键指标", padding=10, style="Panel.TLabelframe")
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        metrics = [
            ("source", "来源"),
            ("user", "用户"),
            ("lead", "线索"),
            ("action", "动作"),
            ("blocked", "阻断"),
            ("success", "成功"),
        ]
        self.hourglass_metric_vars = {}
        for idx, (key, label) in enumerate(metrics):
            box = ttk.Frame(side, style="Metric.TFrame")
            box.grid(row=idx, column=0, sticky="ew", pady=(0, 8))
            ttk.Label(box, text=label, foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.hourglass_metric_vars[key] = var
            ttk.Label(box, textvariable=var, font=ui_font(18, "bold")).pack(anchor="w")

        self.hourglass_canvas = tk.Canvas(
            side,
            width=260,
            height=220,
            bg=UI_COLORS["terminal_bg"],
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
        )
        self.hourglass_canvas.grid(row=len(metrics), column=0, sticky="ew", pady=(6, 0))
        self.hourglass_canvas.bind("<Configure>", lambda _event: self._draw_hourglass())
        self._refresh_hourglass(self.last_snapshot)

    def apply_quick_send_preset(self):
        preset = quick_send_preset(self.quick_send_volume_var.get())
        self.scan_max_videos_var.set(int(preset["max_videos"]))
        self.scan_max_comments_var.set(int(preset["max_comments"]))
        self.scan_profile_limit_var.set(int(preset["profile_limit"]))
        self.scan_interval_var.set(int(preset["task_interval"]))
        self.action_execution_workers_var.set(int(preset["workers"]))
        mode_key = quick_send_mode_key(self.quick_send_mode_var.get())
        if mode_key == "live_comment":
            self.action_execution_mode_var.set("真实提交")
            self.action_execution_live_confirm_var.set(True)
        else:
            self.action_execution_mode_var.set("预检，不提交")
            self.action_execution_live_confirm_var.set(False)

    def apply_comment_reply_ai_settings(self):
        endpoint = self.comment_reply_ai_endpoint_var.get().strip()
        model = self.comment_reply_ai_model_var.get().strip()
        key = self.comment_reply_ai_key_var.get().strip()

        if endpoint:
            os.environ["REACHOPS_AI_ENDPOINT"] = endpoint
        else:
            os.environ.pop("REACHOPS_AI_ENDPOINT", None)
        if model:
            os.environ["REACHOPS_AI_MODEL"] = model
        else:
            os.environ.pop("REACHOPS_AI_MODEL", None)
        if key:
            os.environ["REACHOPS_AI_API_KEY"] = key

        key_configured = bool(os.environ.get("REACHOPS_AI_API_KEY") or key)
        if endpoint:
            status = f"外部AI已配置：model={model or '未指定'}，key={'已配置' if key_configured else '未配置'}"
        else:
            status = "外部AI未启用：未填写Endpoint"
        self.comment_reply_ai_status_var.set(status)
        self.append_runtime_log(
            f"CONFIG comment_reply_ai strategy={self.comment_reply_strategy_var.get()} "
            f"endpoint_configured={str(bool(endpoint)).lower()} model={model or 'none'} "
            f"key_configured={str(key_configured).lower()} ai_suggestion_only=true"
        )

    def comment_reply_ai_settings(self) -> dict:
        endpoint = self.comment_reply_ai_endpoint_var.get().strip()
        model = self.comment_reply_ai_model_var.get().strip()
        key_configured = bool(os.environ.get("REACHOPS_AI_API_KEY") or self.comment_reply_ai_key_var.get().strip())
        return {
            "strategy": self.comment_reply_strategy_var.get(),
            "endpoint_configured": bool(endpoint),
            "model": model,
            "api_key_configured": key_configured,
            "fixed_comment_text_configured": bool(self.quick_comment_text_var.get().strip()),
            "execution_policy": "ai_suggestion_only_live_submit_requires_confirmation",
            "no_auto_ai_submit": True,
        }

    def set_profile_group_options(self, display_values: list[str], selected: str = ""):
        values = [safe_tk_option(item) for item in (display_values or [])]
        stable_values = [item for item in values if is_stable_combobox_option(item)]
        values = stable_values or values
        if not values:
            values = ["请刷新账号分组"]
        if self.start_group_combobox:
            self.start_group_combobox.configure(values=tuple(values))
        if self.start_group_listbox:
            self.start_group_listbox.delete(0, tk.END)
            for item in values:
                self.start_group_listbox.insert(tk.END, item)
        selected_value = safe_tk_option(selected)
        selected_value = selected_value if selected_value in values else values[0]
        self.scan_profile_group_display_var.set(selected_value)
        if self.start_group_listbox:
            try:
                selected_index = values.index(selected_value)
                self.start_group_listbox.selection_clear(0, tk.END)
                self.start_group_listbox.selection_set(selected_index)
                self.start_group_listbox.see(selected_index)
            except Exception:
                pass
        self.scan_profile_group_detail_var.set(f"已读取账号分组：{len(values)} 个；当前账号分组：{selected_value}")
        group = "" if selected_value in {"请刷新账号分组", "正在刷新...", "正在读取分组..."} else group_name_from_display(selected_value)
        self.scan_profile_group_var.set(group)
        self.action_execution_group_var.set(group)

    def _on_start_group_selected(self, _event=None):
        group = group_name_from_display(self.scan_profile_group_display_var.get())
        if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
            group = ""
        self.scan_profile_group_detail_var.set(f"当前账号分组：{self.scan_profile_group_display_var.get() or '未选择'}")
        self.scan_profile_group_var.set(group)
        self.action_execution_group_var.set(group)

    def _on_start_group_list_selected(self, _event=None):
        if not self.start_group_listbox:
            return
        selection = self.start_group_listbox.curselection()
        if not selection:
            return
        value = self.start_group_listbox.get(selection[0])
        self.scan_profile_group_display_var.set(value)
        self._on_start_group_selected()

    def _selected_profile_group(self) -> str:
        group = group_name_from_display(self.scan_profile_group_display_var.get())
        if group in {"请刷新账号分组", "正在刷新...", "正在读取分组..."}:
            group = ""
        if not group:
            group = self.scan_profile_group_var.get().strip()
        self.scan_profile_group_var.set(group)
        self.action_execution_group_var.set(group)
        return group

    def _refresh_profile_groups(self):
        if self.on_refresh_profiles:
            self.on_refresh_profiles()
            return
        self.append_runtime_log("WARN   refresh_profiles unavailable message=当前窗口未接入账号分组刷新")

    def show_campaign_plan(self, plan: dict, range_config: dict | None = None, profile_group: str = ""):
        if not self.campaign_plan_text:
            return
        text = "输入推广目标并点击开始后，系统会在这里显示自动识别结果、采集来源和本轮范围。"
        if plan:
            text = format_campaign_plan_summary(plan, range_config, profile_group)
        try:
            self.campaign_plan_text.configure(state=tk.NORMAL)
            self.campaign_plan_text.delete("1.0", tk.END)
            self.campaign_plan_text.insert(tk.END, text)
            self.campaign_plan_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _runtime_stage_specs(self):
        return [
            ("all", "总日志"),
            ("collect", "采集"),
            ("content", "视频"),
            ("comment", "评论"),
            ("lead", "线索"),
            ("action", "触达"),
            ("error", "异常"),
        ]

    def _bind_runtime_fullscreen(self, widgets):
        for widget in widgets:
            try:
                widget.bind("<Double-Button-1>", self._open_runtime_fullscreen, add="+")
            except Exception:
                pass

    def _make_runtime_text(self, master, stage_key: str, *, height: int = 20, width: int = 18):
        return tk.Text(
            master,
            height=height,
            width=width,
            wrap="none",
            bg=UI_COLORS["terminal_bg"],
            fg=UI_COLORS["terminal_text"],
            insertbackground=UI_COLORS["terminal_muted"],
            relief="sunken",
            bd=1,
            padx=5,
            pady=5,
            font=("Consolas", 8 if width <= 18 else 10),
        )

    def _open_runtime_fullscreen(self, _event=None):
        if self.runtime_fullscreen_window and self.runtime_fullscreen_window.winfo_exists():
            self.runtime_fullscreen_window.lift()
            try:
                self.runtime_fullscreen_window.state("zoomed")
            except Exception:
                pass
            return
        window = tk.Toplevel(self)
        self.runtime_fullscreen_window = window
        self.runtime_fullscreen_stage_texts = {}
        window.title("量化执行漏斗日志 - 全屏")
        window.configure(bg=UI_COLORS["fullscreen_bg"])
        try:
            window.state("zoomed")
        except Exception:
            try:
                window.attributes("-fullscreen", True)
            except Exception:
                pass
        window.bind("<Escape>", lambda _event: window.destroy())
        window.protocol("WM_DELETE_WINDOW", self._close_runtime_fullscreen)
        window.columnconfigure(0, weight=0, minsize=280)
        window.columnconfigure(1, weight=1)
        window.rowconfigure(1, weight=1)
        header = tk.Label(
            window,
            text="量化执行漏斗终端    双击主界面日志打开 | Esc 关闭",
            bg=UI_COLORS["fullscreen_bg"],
            fg=UI_COLORS["terminal_muted"],
            anchor="w",
            font=ui_font(11, "bold"),
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        self.runtime_fullscreen_funnel_text = tk.Text(
            window,
            height=28,
            width=32,
            wrap="none",
            bg=UI_COLORS["terminal_bg"],
            fg=UI_COLORS["terminal_text"],
            insertbackground=UI_COLORS["terminal_muted"],
            relief="sunken",
            bd=1,
            padx=10,
            pady=10,
            font=("Consolas", 11),
        )
        self._configure_terminal_tags(self.runtime_fullscreen_funnel_text)
        self.runtime_fullscreen_funnel_text.grid(row=1, column=0, sticky="nsew", padx=(8, 6), pady=(0, 8))
        stages = ttk.Frame(window)
        stages.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=(0, 8))
        stages.rowconfigure(0, weight=1)
        for idx, (key, label) in enumerate(self._runtime_stage_specs()):
            stages.columnconfigure(idx, weight=1, uniform="runtime_fullscreen_stage")
            panel = tk.Frame(stages, bg=UI_COLORS["fullscreen_bg"])
            panel.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 5, 0))
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)
            tk.Label(panel, text=label, bg=UI_COLORS["fullscreen_bg"], fg=UI_COLORS["terminal_muted"], anchor="center").grid(row=0, column=0, sticky="ew")
            text = self._make_runtime_text(panel, key, height=30, width=22)
            self._configure_terminal_tags(text)
            text.grid(row=1, column=0, sticky="nsew")
            source = self.runtime_stage_texts.get(key)
            if source:
                text.insert(tk.END, source.get("1.0", tk.END).strip() + "\n")
                text.see(tk.END)
            self.runtime_fullscreen_stage_texts[key] = text
        self._render_funnel_terminal()

    def _close_runtime_fullscreen(self):
        try:
            if self.runtime_fullscreen_window and self.runtime_fullscreen_window.winfo_exists():
                self.runtime_fullscreen_window.destroy()
        finally:
            self.runtime_fullscreen_window = None
            self.runtime_fullscreen_stage_texts = {}
            self.runtime_fullscreen_funnel_text = None

    def append_runtime_log(self, message: str):
        if not self.runtime_log_text:
            return
        try:
            from datetime import datetime

            ts = datetime.now().strftime("%H:%M:%S")
            line = f"{ts}  {message}\n"
            stage = self._runtime_stage_for_message(message)
            self._insert_runtime_line(self.runtime_stage_texts, stage, line)
            self._insert_runtime_line(self.runtime_fullscreen_stage_texts, stage, line)
            self._refresh_hourglass(getattr(self, "last_snapshot", GrowthOpsSnapshot()) or GrowthOpsSnapshot())
        except Exception:
            pass

    def _log_operator_event(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        try:
            self.operator_status_var.set(text)
        except Exception:
            pass
        self.append_runtime_log(text)

    def _notify(self, level: str, title: str, message: str = ""):
        level_text = str(level or "INFO").upper()
        title_text = str(title or "").strip()
        body = str(message or "").strip()
        if "\n" in body:
            body = " | ".join(part.strip() for part in body.splitlines() if part.strip())
        text = f"{level_text}  {title_text}"
        if body:
            text = f"{text} message={body}"
        self._log_operator_event(text)

    def _insert_runtime_line(self, text_map: dict, stage: str, line: str):
        if not text_map:
            return
        tag = self._runtime_line_tag(line)
        all_text = text_map.get("all")
        if all_text and self._widget_exists(all_text):
            all_text.insert(tk.END, line, tag)
            all_text.see(tk.END)
        stage_text = text_map.get(stage)
        if stage_text and stage_text is not all_text and self._widget_exists(stage_text):
            stage_text.insert(tk.END, line, tag)
            stage_text.see(tk.END)

    def _configure_terminal_tags(self, widget):
        if not widget:
            return
        try:
            widget.tag_configure("terminal_default", foreground=UI_COLORS["terminal_text"])
            widget.tag_configure("terminal_info", foreground=UI_COLORS["terminal_info"])
            widget.tag_configure("terminal_success", foreground=UI_COLORS["terminal_success"])
            widget.tag_configure("terminal_warning", foreground=UI_COLORS["terminal_warning"])
            widget.tag_configure("terminal_error", foreground=UI_COLORS["terminal_error"])
            widget.tag_configure("terminal_muted", foreground=UI_COLORS["terminal_muted"])
        except Exception:
            pass

    def _runtime_line_tag(self, line: str) -> str:
        text = str(line or "").lower()
        if any(item in text for item in ["error", "failed", "失败", "异常", "block", "captcha", "login_required", "proxy"]):
            return "terminal_error"
        if any(item in text for item in ["warn", "warning", "跳过", "skipped", "retry", "cooldown"]):
            return "terminal_warning"
        if any(item in text for item in ["done", "success", "passed", "ready", "ok", "成功", "完成", "通过"]):
            return "terminal_success"
        if any(item in text for item in ["plan", "start", "check", "config", "run", "touch", "video", "queue"]):
            return "terminal_info"
        if not text.strip():
            return "terminal_muted"
        return "terminal_default"

    def _widget_exists(self, widget) -> bool:
        try:
            return bool(widget and widget.winfo_exists())
        except Exception:
            return False

    def _runtime_stage_for_message(self, message: str) -> str:
        text = str(message or "").lower()
        if any(item in text for item in ["error", "failed", "失败", "异常", "captcha", "proxy", "login_required", "failed:"]):
            return "error"
        if any(item in text for item in ["comment", "评论"]):
            return "comment"
        if any(item in text for item in ["candidate", "lead", "score", "线索", "意向", "评分"]):
            return "lead"
        if any(item in text for item in ["action", "follow", "dm", "私信", "关注", "触达", "执行前预检"]):
            return "action"
        if any(item in text for item in ["video", "content", "素材", "视频"]):
            return "content"
        if any(item in text for item in ["source", "creator", "profile", "采集", "达人", "账号", "分组"]):
            return "collect"
        return "collect"

    def clear_runtime_log(self):
        try:
            targets = []
            if self.runtime_stage_texts:
                targets.extend(self.runtime_stage_texts.values())
            elif self.runtime_log_text:
                targets.append(self.runtime_log_text)
            if self.runtime_fullscreen_stage_texts:
                targets.extend(self.runtime_fullscreen_stage_texts.values())
            for text in targets:
                if text:
                    text.delete("1.0", tk.END)
        except Exception:
            pass

    def copy_runtime_log(self):
        try:
            if self.runtime_stage_texts:
                parts = []
                if self.funnel_terminal_text:
                    parts.append(f"[漏斗结果]\n{self.funnel_terminal_text.get('1.0', tk.END).strip()}")
                for key, title in self._runtime_stage_specs():
                    widget = self.runtime_stage_texts.get(key)
                    if widget:
                        parts.append(f"[{title}]\n{widget.get('1.0', tk.END).strip()}")
                text = "\n\n".join(parts).strip()
            elif self.runtime_log_text:
                text = self.runtime_log_text.get("1.0", tk.END).strip()
            else:
                text = ""
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _refresh_funnel_results(self, snapshot: GrowthOpsSnapshot):
        if not self.funnel_result_vars and not self.funnel_terminal_text:
            return
        funnel = getattr(snapshot, "campaign_funnel", {}) or {}
        summary = getattr(snapshot, "summary", {}) or {}
        values = {
            "data_sources": funnel.get("target_sources", summary.get("data_sources", 0)),
            "contents": funnel.get("content_found", summary.get("contents", 0)),
            "candidates": funnel.get("comment_users", summary.get("candidates", 0)),
            "operation_leads": funnel.get("customer_leads", summary.get("operation_leads", 0)),
            "action_queue": funnel.get("outreach_actions", summary.get("action_queue", 0)),
            "error_diagnostics": funnel.get("failed", summary.get("error_diagnostics", 0)),
        }
        for key, var in self.funnel_result_vars.items():
            var.set(str(values.get(key, 0)))
        self._render_funnel_terminal(values, funnel)
        self._refresh_hourglass(snapshot, values=values, funnel=funnel)

    def _refresh_hourglass(self, snapshot: GrowthOpsSnapshot | None = None, values: dict | None = None, funnel: dict | None = None):
        if not self.hourglass_metric_vars and not self.hourglass_canvas:
            return
        snapshot = snapshot or self.last_snapshot or GrowthOpsSnapshot()
        funnel = funnel or (getattr(snapshot, "campaign_funnel", {}) or {})
        summary = getattr(snapshot, "summary", {}) or {}
        values = values or {
            "data_sources": funnel.get("target_sources", summary.get("data_sources", 0)),
            "contents": funnel.get("content_found", summary.get("contents", 0)),
            "candidates": funnel.get("comment_users", summary.get("candidates", 0)),
            "operation_leads": funnel.get("customer_leads", summary.get("operation_leads", 0)),
            "action_queue": funnel.get("outreach_actions", summary.get("action_queue", 0)),
            "error_diagnostics": funnel.get("failed", summary.get("error_diagnostics", 0)),
        }
        metric_values = {
            "source": self._safe_int(values.get("data_sources")),
            "user": self._safe_int(values.get("candidates")),
            "lead": self._safe_int(values.get("operation_leads")),
            "action": self._safe_int(values.get("action_queue")),
            "blocked": self._safe_int(values.get("error_diagnostics")) + self._safe_int(funnel.get("failed")),
            "success": self._safe_int(funnel.get("execution_success")),
        }
        for key, var in self.hourglass_metric_vars.items():
            var.set(str(metric_values.get(key, 0)))
        top_total = metric_values["source"] + metric_values["user"]
        middle_total = metric_values["blocked"]
        bottom_total = metric_values["lead"] + metric_values["action"] + metric_values["success"]
        layer_values = {
            "top": (
                str(top_total),
                f"来源 {metric_values['source']} / 用户 {metric_values['user']}。这一层代表输入是否进入系统，页面、视频和评论用户是否被采集到。",
            ),
            "middle": (
                str(middle_total),
                f"阻断 {metric_values['blocked']}。这一层集中展示账号登录态、页面加载、风控、重试和跳过判断。",
            ),
            "bottom": (
                str(bottom_total),
                f"线索 {metric_values['lead']} / 动作 {metric_values['action']} / 成功 {metric_values['success']}。这一层代表可沉淀、可复核、可交付的结果。",
            ),
        }
        for key, payload in layer_values.items():
            widgets = self.hourglass_layer_vars.get(key) or {}
            if widgets.get("value"):
                widgets["value"].set(payload[0])
            if widgets.get("detail"):
                widgets["detail"].set(payload[1])
        status = status_label(str(funnel.get("batch_status") or "ready"))
        batch_id = str(funnel.get("batch_id") or "")
        top_error = "-"
        error_counts = funnel.get("error_counts") or {}
        if isinstance(error_counts, dict) and error_counts:
            top_error = display_error_code(str(sorted(error_counts.items(), key=lambda item: int(item[1] or 0), reverse=True)[0][0] or "-"))
        if metric_values["blocked"]:
            state = f"阻断待处理 / {status}"
            decision = f"中层出现阻断：{metric_values['blocked']}。首要错误：{top_error}。处理账号、页面或风控阻断后再次执行。"
        elif metric_values["success"]:
            state = f"执行完成 / {status}"
            decision = f"已产生成功触达 {metric_values['success']}。可导出报告并检查执行记录。"
        elif metric_values["action"]:
            state = f"动作已入队 / {status}"
            decision = f"已形成待触达动作 {metric_values['action']}，下一步进入触达预检或执行。"
        elif metric_values["lead"]:
            state = f"线索已沉淀 / {status}"
            decision = f"已识别线索 {metric_values['lead']}，系统会继续生成可执行动作。"
        elif metric_values["user"]:
            state = f"用户采集中 / {status}"
            decision = f"已采集用户 {metric_values['user']}，正在筛选高意向线索。"
        elif metric_values["source"]:
            state = f"来源已进入 / {status}"
            decision = f"已规划来源 {metric_values['source']}，等待页面打开、内容采集和评论用户解析。"
        else:
            state = "待执行"
            decision = "开始获客后，上层显示来源和用户输入；中层显示判断、重试与阻断；下层显示线索、动作和成功触达。"
        if batch_id:
            decision = f"批次 {batch_id[-10:]}：{decision}"
        self.hourglass_state_var.set(state)
        self.hourglass_decision_var.set(decision)
        self._draw_hourglass(metric_values)

    def _draw_hourglass(self, metric_values: dict | None = None):
        canvas = self.hourglass_canvas
        if not canvas:
            return
        try:
            canvas.delete("all")
            width = max(260, int(canvas.winfo_width() or 300))
            height = max(200, int(canvas.winfo_height() or 220))
            metric_values = metric_values or {key: self._safe_int(var.get()) for key, var in self.hourglass_metric_vars.items()}
            layers = [
                ("上层", "输入与采集", self._safe_int(metric_values.get("source")) + self._safe_int(metric_values.get("user")), "#18313a"),
                ("中层", "判断与阻断", self._safe_int(metric_values.get("blocked")), "#3a2f18"),
                ("下层", "线索与触达", self._safe_int(metric_values.get("lead")) + self._safe_int(metric_values.get("action")) + self._safe_int(metric_values.get("success")), "#183320"),
            ]
            max_value = max(1, *[value for _name, _label, value, _color in layers])
            margin = 14
            gap = 10
            layer_height = max(48, int((height - margin * 2 - gap * 2) / 3))
            for idx, (name, label, value, color) in enumerate(layers):
                y = margin + idx * (layer_height + gap)
                canvas.create_rectangle(margin, y, width - margin, y + layer_height, fill=color, outline=UI_COLORS["border"], width=1)
                fill_width = int((width - margin * 2 - 12) * (value / max_value)) if value else 0
                if fill_width:
                    canvas.create_rectangle(margin + 6, y + layer_height - 11, margin + 6 + fill_width, y + layer_height - 6, fill=UI_COLORS["accent"], outline="")
                canvas.create_text(margin + 10, y + 14, text=name, fill=UI_COLORS["text"], font=ui_font(10, "bold"), anchor="w")
                canvas.create_text(margin + 10, y + 33, text=label, fill=UI_COLORS["muted"], font=ui_font(8), anchor="w")
                canvas.create_text(width - margin - 10, y + layer_height / 2, text=str(value), fill=UI_COLORS["text"], font=ui_font(18, "bold"), anchor="e")
        except Exception:
            pass

    def _render_funnel_terminal(self, values: dict | None = None, funnel: dict | None = None):
        if values is None:
            values = {key: var.get() for key, var in self.funnel_result_vars.items()}
        funnel = funnel or {}
        numbers = {key: self._safe_int(value) for key, value in values.items()}
        data_sources = numbers.get("data_sources", 0)
        contents = numbers.get("contents", 0)
        candidates = numbers.get("candidates", 0)
        operation_leads = numbers.get("operation_leads", 0)
        action_queue = numbers.get("action_queue", 0)
        errors = numbers.get("error_diagnostics", 0)
        execution_success = self._safe_int(funnel.get("execution_success"))
        error_counts = funnel.get("error_counts") or {}
        top_error_code = "-"
        if isinstance(error_counts, dict) and error_counts:
            top_error_code = str(sorted(error_counts.items(), key=lambda item: int(item[1] or 0), reverse=True)[0][0] or "-")
        lines = [
            "REACHOPS 本轮获客",
            "================",
            f"任务ID   {str(funnel.get('campaign_id') or '-')[-10:]:>10}",
            f"批次ID   {str(funnel.get('batch_id') or '-')[-10:]:>10}",
            f"状态     {status_label(str(funnel.get('batch_status') or 'ready'))[:10]:>10}",
            "",
            f"目标来源 {data_sources:>8}",
            f"可用账号 {self._safe_int(funnel.get('profile_ok')):>8}",
            f"打开页面 {self._safe_int(funnel.get('page_opened')):>8}",
            f"发现内容 {contents:>8}",
            f"评论用户 {candidates:>8}",
            f"去重用户 {self._safe_int(funnel.get('dedup_users', candidates)):>8}",
            f"高意向   {self._safe_int(funnel.get('high_intent')):>8}",
            f"客户线索 {operation_leads:>8}",
            f"待触达   {action_queue:>8}",
            f"预检通过 {self._safe_int(funnel.get('preflight_ok')):>8}",
            f"执行成功 {execution_success:>8}",
            f"失败异常 {errors:>8}",
            f"换号次数 {self._safe_int(funnel.get('account_switches')):>8}",
            f"首要错误 {display_error_code(top_error_code)[:14]:>8}",
            "",
            "转化率",
            f"来源到内容 {self._rate(contents, data_sources):>7}",
            f"内容到用户 {self._rate(candidates, contents):>7}",
            f"用户到线索 {self._rate(operation_leads, candidates):>7}",
            f"线索到动作 {self._rate(action_queue, operation_leads):>7}",
            "",
            "当前状态",
            str(self.operator_status_var.get() or "已就绪")[:24],
            "",
            "双击日志区域",
            "打开全屏终端",
        ]
        text = "\n".join(lines)
        for widget in [self.funnel_terminal_text, self.runtime_fullscreen_funnel_text]:
            if self._widget_exists(widget):
                self._configure_terminal_tags(widget)
                widget.delete("1.0", tk.END)
                for line in lines:
                    tag = "terminal_success" if line.startswith("REACHOPS") else self._runtime_line_tag(line)
                    widget.insert(tk.END, f"{line}\n", tag)
                widget.see(tk.END)

    def _safe_int(self, value) -> int:
        try:
            return int(float(value or 0))
        except Exception:
            return 0

    def _rate(self, numerator: int, denominator: int) -> str:
        if not denominator:
            return "0.0%"
        return f"{(numerator / denominator) * 100:.1f}%"

    def _build_intent_analysis_view(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        self.intent_summary_frame = ttk.LabelFrame(frame, text="这批用户有没有价值？", padding=14, style="Panel.TLabelframe")
        self.intent_summary_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.intent_summary_vars = {}
        for idx, key in enumerate(["high", "observe", "low", "purchase", "consult", "interest", "entertainment", "spam"]):
            self.intent_summary_frame.columnconfigure(idx % 4, weight=1, uniform="intent")
            box = ttk.Frame(self.intent_summary_frame, style="Panel.TFrame")
            box.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=8, pady=4)
            ttk.Label(box, text=self._intent_label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.intent_summary_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 14, "bold")).pack(anchor="w")

        split = ttk.Frame(frame, style="Content.TFrame")
        split.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        split.columnconfigure(0, weight=1)
        split.rowconfigure(0, weight=1)
        split.rowconfigure(1, weight=1)
        keyword_box = ttk.LabelFrame(split, text="Top 评论关键词", padding=10, style="Panel.TLabelframe")
        keyword_box.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        video_box = ttk.LabelFrame(split, text="Top 视频 / 素材", padding=10, style="Panel.TLabelframe")
        video_box.grid(row=1, column=0, sticky="nsew")
        keyword_tree = ttk.Treeview(keyword_box, columns=["keyword", "count"], show="headings", height=5)
        keyword_tree.heading("keyword", text="关键词")
        keyword_tree.heading("count", text="出现次数")
        keyword_tree.column("keyword", width=220, anchor="w")
        keyword_tree.column("count", width=80, anchor="w")
        keyword_tree.pack(fill=tk.BOTH, expand=True)
        video_tree = ttk.Treeview(video_box, columns=["video_id", "caption", "views", "comments"], show="headings", height=6)
        for column in ["video_id", "caption", "views", "comments"]:
            video_tree.heading(column, text=self._label(column))
            video_tree.column(column, width=130, anchor="w")
        video_tree.column("caption", width=320)
        video_tree.pack(fill=tk.BOTH, expand=True)
        self._trees["意图分析__keywords"] = keyword_tree
        self._trees["意图分析__videos"] = video_tree

        self.intent_next_text = tk.Text(frame, height=8, wrap="word", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], relief="flat", padx=8, pady=8)
        self.intent_next_text.grid(row=2, column=0, sticky="nsew")
        self.intent_next_text.insert(tk.END, "采集后这里会显示线索价值判断和下一步建议。")

    def _build_account_status_view(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        top = ttk.LabelFrame(frame, text="账号为什么能跑 / 为什么不能跑", padding=14, style="Panel.TLabelframe")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.account_status_vars = {}
        for idx, key in enumerate(["profile_health", "healthy_count", "degraded_count", "cooldown_count", "top_error_code", "next_execution_action"]):
            top.columnconfigure(idx, weight=1, uniform="account")
            box = ttk.Frame(top, style="Panel.TFrame")
            box.grid(row=0, column=idx, sticky="ew", padx=8)
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.account_status_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 12, "bold"), wraplength=180).pack(anchor="w")
        notebook = ttk.Notebook(frame)
        notebook.grid(row=1, column=0, sticky="nsew")
        health_frame = ttk.Frame(notebook)
        error_frame = ttk.Frame(notebook)
        execution_frame = ttk.Frame(notebook)
        notebook.add(health_frame, text="账号健康")
        notebook.add(error_frame, text="失败原因")
        notebook.add(execution_frame, text="执行记录")
        for sub in [health_frame, error_frame, execution_frame]:
            sub.columnconfigure(0, weight=1)
            sub.rowconfigure(0, weight=1)
        self._build_simple_tree(health_frame, "账号状态__health", ["profile_id", "group_name", "health_score", "status", "consecutive_failures", "last_error_code"])
        self._build_simple_tree(error_frame, "账号状态__errors", ["severity", "error_code", "count", "profile_id", "cause", "suggested_action"])
        self._build_simple_tree(execution_frame, "账号状态__executions", ["action_type", "target_username", "status", "profile_id", "error_code"])

    def _build_simple_tree(self, frame, key: str, columns: list[str]):
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for column in columns:
            tree.heading(column, text=self._label(column))
            tree.column(column, width=140, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=yscroll.set)
        self._trees[key] = tree

    def _build_table_view(self, name, columns, detail: bool = False):
        frame = self.views[name]
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for column in columns:
            tree.heading(column, text=self._label(column))
            tree.column(column, width=140, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=yscroll.set)
        if detail:
            frame.rowconfigure(1, weight=0)
            detail_text = tk.Text(frame, height=7, wrap="word", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], relief="flat", padx=8, pady=8)
            detail_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            detail_text.insert(tk.END, "选择一行查看详情")
            tree.bind("<<TreeviewSelect>>", lambda _event, view_name=name: self._show_selected_detail(view_name))
            self._trees[f"{name}__detail"] = detail_text
        else:
            frame.rowconfigure(1, weight=0)
            ttk.Label(
                frame,
                text=f"{name} 暂无数据；开始获客或刷新工作台后会在这里显示结果。",
                style="Muted.TLabel",
                anchor="w",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._trees[name] = tree

    def _hide_tree_column(self, name: str, column_name: str):
        tree = self._trees.get(name)
        if not tree:
            return
        try:
            tree.column(column_name, width=0, stretch=False)
        except Exception:
            pass

    def _build_scheduled_scan_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="暂停所选", command=lambda: self._update_selected_scheduled_scan("pause")).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="恢复所选", command=lambda: self._update_selected_scheduled_scan("resume")).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="立即执行所选", command=self._run_selected_scheduled_scan).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="执行到期扫描", command=self._run_due_scans).pack(side=tk.LEFT, padx=(8, 0))
        create_bar = ttk.Frame(frame)
        create_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(create_bar, text="类型").pack(side=tk.LEFT)
        ttk.Combobox(
            create_bar,
            textvariable=self.scan_source_type_var,
            values=[display_source_type(item) for item in SOURCE_TYPE_LABELS],
            width=16,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(create_bar, text="数据源").pack(side=tk.LEFT)
        ttk.Entry(create_bar, textvariable=self.scan_source_value_var, width=30).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(create_bar, text="账号").pack(side=tk.LEFT)
        ttk.Entry(create_bar, textvariable=self.scan_profile_group_var, width=12, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(create_bar, text="间隔").pack(side=tk.LEFT)
        ttk.Spinbox(create_bar, from_=5, to=1440, width=6, textvariable=self.scan_interval_var).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(create_bar, text="视频").pack(side=tk.LEFT)
        ttk.Spinbox(create_bar, from_=1, to=20, width=4, textvariable=self.scan_max_videos_var).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(create_bar, text="评论").pack(side=tk.LEFT)
        ttk.Spinbox(create_bar, from_=1, to=50, width=4, textvariable=self.scan_max_comments_var).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(create_bar, text="新增扫描", command=self._create_scheduled_scan).pack(side=tk.LEFT)
        bulk_frame = ttk.Frame(frame)
        bulk_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(bulk_frame, text="批量").pack(side=tk.LEFT)
        self.scan_bulk_text = tk.Text(bulk_frame, height=3, width=70, wrap="word")
        self.scan_bulk_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
        ttk.Button(bulk_frame, text="批量新增", command=self._create_scheduled_scans_bulk).pack(side=tk.LEFT)

    def _build_candidate_view(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        toolbar = ttk.LabelFrame(frame, text="线索筛选", padding=8, style="Panel.TLabelframe")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        filter_row = ttk.Frame(toolbar, style="Panel.TFrame")
        filter_row.pack(fill=tk.X)
        action_row = ttk.Frame(toolbar, style="Panel.TFrame")
        action_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(filter_row, text="分层").pack(side=tk.LEFT)
        ttk.Combobox(filter_row, textvariable=self.lead_tier_var, values=list(LEAD_TIER_LABELS.values()), width=10, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(filter_row, text="语言").pack(side=tk.LEFT)
        ttk.Combobox(filter_row, textvariable=self.lead_language_var, values=[LANGUAGE_FILTER_LABELS[item] for item in LANGUAGE_FILTER_VALUES], width=10, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(filter_row, text="主页").pack(side=tk.LEFT)
        ttk.Combobox(filter_row, textvariable=self.lead_profile_var, values=list(PROFILE_COMPLETED_LABELS.values()), width=8, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Entry(filter_row, textvariable=self.lead_keyword_var, width=24).pack(side=tk.LEFT, padx=(0, 8), fill=tk.X, expand=True)
        ttk.Button(filter_row, text="筛选", command=self._refresh_filtered_tables).pack(side=tk.LEFT)
        ttk.Button(action_row, text="导出筛选", command=self._export_filtered_candidates).pack(side=tk.LEFT)
        ttk.Button(action_row, text="打开主页", command=self._open_selected_candidate_profile).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(action_row, text="打开来源", command=self._open_selected_candidate_source).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(action_row, text="加入排除", command=self._exclude_selected_candidate).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(action_row, text="预设").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Entry(action_row, textvariable=self.lead_preset_name_var, width=14).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(action_row, text="保存预设", command=self._save_candidate_filter_preset).pack(side=tk.LEFT)
        ttk.Button(action_row, text="加载预设", command=self._load_candidate_filter_preset).pack(side=tk.LEFT, padx=(4, 0))
        columns = [
            "username",
            "qualify_score",
            "status",
            "intent_tags",
            "comment_language",
            "profile_completed",
            "profile_url",
            "source",
            "video_id",
            "views",
            "comment_text",
        ]
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for column in columns:
            tree.heading(column, text=self._label(column))
            tree.column(column, width=140, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=yscroll.set)
        detail_text = tk.Text(frame, height=7, wrap="word", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], relief="flat", padx=8, pady=8)
        detail_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        detail_text.insert(tk.END, "选择一行查看详情")
        tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_candidate_detail())
        self._trees["线索池"] = tree
        self._trees["线索池__detail"] = detail_text

    def _build_action_queue_view(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        toolbar = ttk.LabelFrame(frame, text="动作筛选与审核", padding=8, style="Panel.TLabelframe")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        filter_row = ttk.Frame(toolbar, style="Panel.TFrame")
        filter_row.pack(fill=tk.X)
        action_row = ttk.Frame(toolbar, style="Panel.TFrame")
        action_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(filter_row, text="状态").pack(side=tk.LEFT)
        ttk.Combobox(
            filter_row,
            textvariable=self.action_status_var,
            values=list(ACTION_STATUS_LABELS.values()),
            width=16,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(filter_row, text="风险").pack(side=tk.LEFT)
        ttk.Combobox(filter_row, textvariable=self.action_risk_var, values=list(RISK_FILTER_LABELS.values()), width=10, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(filter_row, text="审核").pack(side=tk.LEFT)
        ttk.Combobox(filter_row, textvariable=self.action_review_var, values=list(REVIEW_FILTER_LABELS.values()), width=10, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(filter_row, text="阻断").pack(side=tk.LEFT)
        ttk.Combobox(
            filter_row,
            textvariable=self.action_block_reason_var,
            values=["全部阻断"] + [display_error_code(item) for item in [
                "ACTION_REQUIRES_REVIEW",
                "ACTION_REQUIRES_EXECUTION_CONFIRMATION",
                "COMMENT_EXECUTION_DISABLED",
                "FOLLOW_EXECUTION_DISABLED",
                "DM_EXECUTION_DISABLED",
                "DAILY_QUOTA_EXCEEDED",
                "TARGET_EXCLUDED",
                "PROFILE_IN_COOLDOWN",
                "LOGIN_REQUIRED",
                "CAPTCHA_DETECTED",
                "PROXY_FAILED",
            ]],
            width=22,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Entry(filter_row, textvariable=self.action_keyword_var, width=18).pack(side=tk.LEFT, padx=(0, 8), fill=tk.X, expand=True)
        ttk.Button(filter_row, text="筛选", command=self._refresh_filtered_tables).pack(side=tk.LEFT)
        ttk.Button(action_row, text="导出筛选", command=self._export_filtered_actions).pack(side=tk.LEFT)
        ttk.Label(action_row, text="预设").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(action_row, textvariable=self.action_preset_name_var, width=12).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(action_row, text="保存预设", command=self._save_action_filter_preset).pack(side=tk.LEFT)
        ttk.Button(action_row, text="加载预设", command=self._load_action_filter_preset).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(action_row, text="批准", command=lambda: self._review_selected_action("approve")).pack(side=tk.LEFT)
        ttk.Button(action_row, text="拒绝", command=lambda: self._review_selected_action("reject")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="确认", command=lambda: self._review_selected_action("confirm")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="重试", command=lambda: self._review_selected_action("retry")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="预览", command=self._preview_selected_actions).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="计划", command=self._show_execution_plan).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="导出计划", command=self._export_execution_plan).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(action_row, text="执行前预检", command=self._run_action_router_from_ui).pack(side=tk.LEFT, padx=(6, 0))
        summary_frame = ttk.LabelFrame(frame, text="审核摘要", padding=12, style="Panel.TLabelframe")
        summary_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for idx, key in enumerate(
            [
                "pending_review_count",
                "approved_count",
                "ready_to_execute_count",
                "high_risk_count",
                "retryable_count",
                "next_operator_action",
            ]
        ):
            summary_frame.columnconfigure(idx, weight=1, uniform="review")
            box = ttk.Frame(summary_frame, style="Panel.TFrame")
            box.grid(row=0, column=idx, sticky="ew", padx=8)
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.action_review_summary_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 12, "bold")).pack(anchor="w")
        readiness_frame = ttk.LabelFrame(frame, text="执行准备", padding=12, style="Panel.TLabelframe")
        readiness_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for idx, key in enumerate(
            [
                "ready_count",
                "blocked_count",
                "quota_blocked_count",
                "excluded_count",
                "profile_id",
                "next_execution_action",
            ]
        ):
            readiness_frame.columnconfigure(idx, weight=1, uniform="ready")
            box = ttk.Frame(readiness_frame, style="Panel.TFrame")
            box.grid(row=0, column=idx, sticky="ew", padx=8)
            ttk.Label(box, text=self._label(key), foreground=UI_COLORS["muted"]).pack(anchor="w")
            var = tk.StringVar(value="0")
            self.execution_readiness_summary_vars[key] = var
            ttk.Label(box, textvariable=var, font=("", 12, "bold")).pack(anchor="w")
        execution_frame = ttk.LabelFrame(frame, text="自动执行设置", padding=12, style="Panel.TLabelframe")
        execution_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(execution_frame, text="执行模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            execution_frame,
            textvariable=self.action_execution_mode_var,
            values=["预检，不提交", "真实提交"],
            width=14,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(execution_frame, text="账号分组").grid(row=0, column=2, sticky="w")
        ttk.Entry(execution_frame, textvariable=self.action_execution_group_var, width=12).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Label(execution_frame, text="线程数").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(execution_frame, from_=1, to=10, textvariable=self.action_execution_workers_var, width=5).grid(row=0, column=5, sticky="w", padx=(4, 12))
        ttk.Label(execution_frame, text="单账号本轮").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(execution_frame, from_=1, to=50, textvariable=self.action_execution_per_profile_var, width=5).grid(row=0, column=7, sticky="w", padx=(4, 12))
        ttk.Label(execution_frame, text="每小时").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(execution_frame, from_=1, to=200, textvariable=self.action_execution_hour_limit_var, width=6).grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))
        ttk.Label(execution_frame, text="同视频/小时").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(execution_frame, from_=1, to=20, textvariable=self.action_execution_video_hour_limit_var, width=6).grid(row=1, column=3, sticky="w", padx=(4, 12), pady=(6, 0))
        self.action_execution_live_confirm_var.set(
            quick_send_mode_key(self.quick_send_mode_var.get()) == "live_comment"
        )
        ttk.Checkbutton(
            execution_frame,
            text="确认真实提交",
            variable=self.action_execution_live_confirm_var,
        ).grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Label(
            execution_frame,
            text="真实提交会在采集后自动执行本轮评论动作。",
            foreground=UI_COLORS["warning"],
        ).grid(row=1, column=5, columnspan=3, sticky="w", pady=(6, 0))
        columns = [
            "id",
            "action_type",
            "target_username",
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
            "suggested_text",
        ]
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14, selectmode="extended")
        for column in columns:
            tree.heading(column, text=self._label(column))
            tree.column(column, width=120, anchor="w")
        tree.column("id", width=0, stretch=False)
        tree.grid(row=4, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        yscroll.grid(row=4, column=1, sticky="ns")
        tree.configure(yscrollcommand=yscroll.set)
        detail_text = tk.Text(frame, height=7, wrap="word", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], relief="flat", padx=8, pady=8)
        detail_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        detail_text.insert(tk.END, "选择动作查看审核详情")
        tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_action_detail())
        self._trees["动作队列"] = tree
        self._trees["动作队列__detail"] = detail_text

    def _build_error_diagnostics_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="重跑所选错误", command=self._rerun_selected_error).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="打开截图证据", command=self._open_selected_evidence).pack(side=tk.LEFT, padx=(8, 0))

    def _build_collection_task_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="重跑所选失败任务", command=self._rerun_selected_collection_tasks).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="按错误码重跑", command=self._rerun_selected_collection_task_error).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="查看任务时间线", command=self._show_selected_collection_task_timeline).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="打开最近证据", command=self._open_selected_collection_task_evidence).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="查看错误诊断", command=lambda: self.nav_var.set("账号诊断") or self._switch_view()).pack(side=tk.LEFT, padx=(8, 0))

    def _build_collection_batch_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="查看批次进度", command=self._show_selected_collection_batch_progress).pack(side=tk.LEFT)

    def _build_content_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="打开素材", command=self._open_selected_content_source).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="查看素材详情", command=self._show_selected_content_detail_popup).pack(side=tk.LEFT, padx=(8, 0))

    def _build_creator_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="打开主页", command=self._open_selected_creator_profile).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="查看创作者详情", command=self._show_selected_creator_detail_popup).pack(side=tk.LEFT, padx=(8, 0))

    def _build_execution_plan_actions(self, frame):
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(toolbar, text="Dry-Run执行所选计划", command=self._execute_selected_plan_dry_run).pack(side=tk.LEFT)

    def _build_policy_data_view(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(frame)
        notebook.grid(row=0, column=0, sticky="nsew")
        for name, columns in [
            ("话术模板", ["action_type", "name", "status", "body"]),
            ("排除名单", ["target_username", "target_url", "status", "reason"]),
            ("日配额", ["profile_id", "action_type", "quota_date", "used_count", "limit_count"]),
            ("小时限频", ["profile_id", "action_type", "scope_type", "scope_value", "window_key", "used_count", "limit_count"]),
        ]:
            sub = ttk.Frame(notebook)
            sub.columnconfigure(0, weight=1)
            sub.rowconfigure(0, weight=1)
            notebook.add(sub, text=name)
            tree = ttk.Treeview(sub, columns=columns, show="headings", height=12)
            for column in columns:
                tree.heading(column, text=self._label(column))
                tree.column(column, width=140, anchor="w")
            tree.grid(row=0, column=0, sticky="nsew")
            yscroll = ttk.Scrollbar(sub, orient="vertical", command=tree.yview)
            yscroll.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=yscroll.set)
            self._trees[name] = tree
            if name == "话术模板":
                self._build_template_editor(sub)
            if name == "排除名单":
                self._build_exclusion_editor(sub)

    def _build_report_view(self, frame):
        self._configure_content_container(frame)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        toolbar = ttk.LabelFrame(frame, text="报告文件", padding=10, style="Panel.TLabelframe")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(toolbar, text="打开日报", command=lambda: self._open_report_artifact("daily_brief")).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="打开 JSON", command=lambda: self._open_report_artifact("json_report")).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="打开线索 CSV", command=lambda: self._open_report_artifact("high_value_users")).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="打开动作 CSV", command=lambda: self._open_report_artifact("action_queue")).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="打开目录", command=lambda: self._open_report_artifact("directory")).pack(side=tk.LEFT, padx=(8, 0))
        self.report_text = tk.Text(frame, height=12, wrap="word", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], relief="flat", padx=8, pady=8)
        self.report_text.grid(row=1, column=0, sticky="nsew")

    def _build_policy_view(self, frame):
        text = (
            "自动执行编排默认使用 Dry-Run/预检模式，不会真实提交评论、关注、私信。\n"
            "执行前必须满足 账号分组、单轮上限、失败冷却、登录/验证码/代理状态检查。\n"
            "评论优先，关注/私信不可用会降级到更稳的触达动作；账号失败会自动换号并记录证据。"
        )
        ttk.Label(frame, text=text, justify="left").pack(anchor="nw", padx=8, pady=8)

    def _build_template_editor(self, frame):
        editor = ttk.LabelFrame(frame, text="模板编辑", padding=8)
        editor.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(editor, text="动作").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            editor,
            textvariable=self.template_action_type_var,
            values=[display_action_type(item) for item in ["comment_reply", "follow_review", "dm_review"]],
            width=16,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=(4, 8))
        ttk.Label(editor, text="名称").grid(row=0, column=2, sticky="w")
        ttk.Entry(editor, textvariable=self.template_name_var, width=18).grid(row=0, column=3, sticky="w", padx=(4, 8))
        ttk.Label(editor, text="状态").grid(row=0, column=4, sticky="w")
        ttk.Combobox(editor, textvariable=self.template_status_var, values=list(TEMPLATE_STATUS_LABELS.values()), width=10, state="readonly").grid(row=0, column=5, sticky="w", padx=(4, 8))
        ttk.Button(editor, text="保存模板", command=self._save_action_template).grid(row=0, column=6, sticky="w")
        self.template_body_text = tk.Text(editor, height=4, wrap="word")
        self.template_body_text.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(6, 0))
        editor.columnconfigure(3, weight=1)

    def _build_exclusion_editor(self, frame):
        editor = ttk.LabelFrame(frame, text="排除名单编辑", padding=8)
        editor.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(editor, text="用户名").grid(row=0, column=0, sticky="w")
        ttk.Entry(editor, textvariable=self.exclusion_username_var, width=20).grid(row=0, column=1, sticky="w", padx=(4, 8))
        ttk.Label(editor, text="主页/目标链接").grid(row=0, column=2, sticky="w")
        ttk.Entry(editor, textvariable=self.exclusion_url_var, width=34).grid(row=0, column=3, sticky="ew", padx=(4, 8))
        ttk.Label(editor, text="原因").grid(row=0, column=4, sticky="w")
        ttk.Entry(editor, textvariable=self.exclusion_reason_var, width=24).grid(row=0, column=5, sticky="w", padx=(4, 8))
        ttk.Button(editor, text="加入排除", command=self._save_exclusion).grid(row=0, column=6, sticky="w")
        editor.columnconfigure(3, weight=1)

    def refresh(self, snapshot: GrowthOpsSnapshot | None = None):
        if snapshot is None and self.workflow_service:
            snapshot = self.workflow_service.build_snapshot()
        if snapshot is None:
            snapshot = GrowthOpsSnapshot()
        self.last_snapshot = snapshot
        for key, var in self.summary_vars.items():
            var.set(str(self._summary_value(snapshot, key)))
        self._refresh_funnel_results(snapshot)
        for key, var in getattr(self, "operational_status_vars", {}).items():
            var.set(str(self._format_operational_status_value(key, snapshot.operational_status.get(key, ""))))
        for key, var in self.action_review_summary_vars.items():
            var.set(str(snapshot.action_review_summary.get(key, 0)))
        for key, var in self.execution_readiness_summary_vars.items():
            var.set(str(snapshot.execution_readiness_summary.get(key, 0)))
        self._fill_tree("数据源", snapshot.sources)
        self._fill_tree("定时扫描", snapshot.scheduled_scans)
        self._fill_tree("采集批次", snapshot.collection_batches)
        self._fill_tree("采集任务", snapshot.collection_tasks)
        self._fill_tree("账号健康", snapshot.profile_health)
        self._fill_tree("账号推荐", snapshot.profile_recommendations)
        self._fill_tree("错误诊断", snapshot.error_diagnostics)
        self._fill_tree("内容/素材", snapshot.top_contents)
        self._fill_tree("创作者池", snapshot.creators)
        self._fill_tree("下一轮采集源", snapshot.source_recommendations)
        self._fill_tree("运营线索", snapshot.operation_leads)
        self._refresh_filtered_tables()
        self._fill_tree("执行计划", snapshot.execution_plans)
        self._fill_tree("执行记录", snapshot.executions)

        self._fill_tree("账号状态__health", snapshot.profile_health)
        self._fill_tree("账号状态__errors", snapshot.error_diagnostics)
        self._fill_tree("账号状态__executions", snapshot.executions)
        self._fill_tree("话术模板", snapshot.action_templates)
        self._fill_tree("排除名单", snapshot.exclusions)
        self._fill_tree("日配额", snapshot.daily_quota)
        self._fill_tree("小时限频", snapshot.rate_limits)
        self._refresh_intent_analysis(snapshot)
        self._refresh_account_status(snapshot)
        if self.report_text:
            self.report_text.delete("1.0", tk.END)
            self.report_text.insert(tk.END, snapshot.report_brief or "暂无运营简报")
            self.report_text.insert(tk.END, "\n\n目标快发验收:\n")
            for line in self._quick_send_acceptance_lines(snapshot):
                self.report_text.insert(tk.END, f"- {line}\n")
            self.report_text.insert(tk.END, "\n\n错误统计:\n")
            for key, value in snapshot.errors.items():
                self.report_text.insert(tk.END, f"- {key}: {value}\n")
            if snapshot.report_artifacts:
                self.report_text.insert(tk.END, "\n报告文件:\n")
                for item in snapshot.report_artifacts:
                    path = item.get("path") or "未生成"
                    self.report_text.insert(tk.END, f"- {item.get('label', item.get('kind', ''))}: {path}\n")
        if hasattr(self, "overview_brief_text"):
            self.overview_brief_text.delete("1.0", tk.END)
            self.overview_brief_text.insert(tk.END, snapshot.report_brief or "暂无运营简报")

    def _quick_send_acceptance_lines(self, snapshot: GrowthOpsSnapshot) -> list[str]:
        funnel = dict(getattr(snapshot, "campaign_funnel", {}) or {})
        executions = list(getattr(snapshot, "executions", []) or [])
        errors = dict(getattr(snapshot, "errors", {}) or {})
        video_ok = int(funnel.get("content_found") or 0) > 0
        comments = int(funnel.get("comment_users") or 0)
        leads = int(funnel.get("customer_leads") or funnel.get("high_intent") or 0)
        actions = int(funnel.get("outreach_actions") or 0)
        touch_ok = bool(executions) or int(funnel.get("preflight_ok") or 0) > 0
        error_counts = dict(funnel.get("error_counts") or {})
        clear_no_lead_reasons = [
            code
            for code in ("URL_MISMATCH_DISCARDED", "COMMENT_SCAN_EMPTY", "LOGIN_REQUIRED", "CAPTCHA_DETECTED", "PROXY_FAILED")
            if int(error_counts.get(code) or errors.get(code) or 0) > 0
        ]
        no_leads_explained = comments == 0 and leads == 0 and bool(clear_no_lead_reasons)
        status = "passed" if video_ok and (leads > 0 or comments > 0) and (touch_ok or actions == 0) else "pending"
        if no_leads_explained and int(funnel.get("page_opened") or 0) > 0:
            status = "passed"
        elif errors and not video_ok and not no_leads_explained:
            status = "failed"
        reason_text = "无"
        if no_leads_explained:
            reason_text = "无高意向线索原因明确: " + ", ".join(clear_no_lead_reasons)
        return [
            f"总体状态: {status}",
            f"目标类型: {funnel.get('campaign_type', '') or '未识别'}",
            f"视频/内容: {funnel.get('content_found', 0)}，评论用户: {comments}，高意向/运营线索: {leads}",
            f"触达动作: {actions}，预检/执行成功: {funnel.get('preflight_ok', 0)}，失败: {funnel.get('failed', 0)}",
            f"无线索说明: {reason_text}",
            "证据规则: no-submit 不计真实提交；真实评论必须页面可见同文本才算 success",
        ]

    def _summary_value(self, snapshot: GrowthOpsSnapshot, key: str) -> int:
        """Return current campaign values for the start-page KPI cards."""
        funnel = getattr(snapshot, "campaign_funnel", {}) or {}
        funnel_keys = {
            "data_sources": "target_sources",
            "contents": "content_found",
            "candidates": "comment_users",
            "operation_leads": "customer_leads",
            "action_queue": "outreach_actions",
            "error_diagnostics": "failed",
        }
        funnel_key = funnel_keys.get(key)
        if funnel_key and (funnel.get("campaign_id") or funnel.get("batch_id")):
            return self._safe_int(funnel.get(funnel_key))
        return self._safe_int((getattr(snapshot, "summary", {}) or {}).get(key, 0))

    def _active_snapshot(self) -> GrowthOpsSnapshot:
        if not self.workflow_service:
            return getattr(self, "last_snapshot", GrowthOpsSnapshot()) or GrowthOpsSnapshot()
        funnel = getattr(getattr(self, "last_snapshot", None), "campaign_funnel", {}) or {}
        return self.workflow_service.build_snapshot(
            campaign_id=str(funnel.get("campaign_id") or ""),
            batch_id=str(funnel.get("batch_id") or ""),
        )

    def _active_campaign_batch_id(self) -> str:
        funnel = getattr(getattr(self, "last_snapshot", None), "campaign_funnel", {}) or {}
        return str(funnel.get("batch_id") or "")

    def _refresh_intent_analysis(self, snapshot: GrowthOpsSnapshot):
        if not hasattr(self, "intent_summary_vars"):
            return
        intent_counts = self._intent_counts(snapshot.candidate_users)
        tier_counts = {
            "high": int(snapshot.lead_tiers.get("high") or 0),
            "observe": int(snapshot.lead_tiers.get("observe") or 0),
            "low": int(snapshot.lead_tiers.get("low") or 0),
        }
        if not any(tier_counts.values()):
            for row in snapshot.candidate_users:
                status = str(row.get("status") or "")
                if status == "high_value":
                    tier_counts["high"] += 1
                elif status in {"observable", "observe"}:
                    tier_counts["observe"] += 1
                else:
                    tier_counts["low"] += 1
        values = {**tier_counts, **intent_counts}
        for key, var in self.intent_summary_vars.items():
            var.set(str(values.get(key, 0)))
        self._fill_tree("意图分析__keywords", self._keyword_rows(snapshot.candidate_users))
        self._fill_tree("意图分析__videos", snapshot.top_contents[:20])
        if hasattr(self, "intent_next_text"):
            self.intent_next_text.delete("1.0", tk.END)
            lines = ["运营判断"]
            high = int(values.get("high") or 0)
            observe = int(values.get("observe") or 0)
            if high:
                lines.append(f"- 已发现 {high} 个高意向用户，建议进入“待执行动作”做复核和执行前预检。")
            elif observe:
                lines.append(f"- 当前有 {observe} 个可观察用户，建议扩大同类达人/视频评论采集。")
            else:
                lines.append("- 当前线索偏低意向，建议换更贴近业务的达人视频或高意图关键词。")
            if intent_counts.get("purchase"):
                lines.append(f"- 购买意向评论 {intent_counts['purchase']} 条，可优先导出给运营跟进。")
            if intent_counts.get("consult"):
                lines.append(f"- 咨询意向评论 {intent_counts['consult']} 条，适合用评论模板补充信息。")
            if snapshot.next_actions:
                lines.append("")
                lines.append("系统建议")
                lines.extend([f"- {item.get('action', '')}" for item in snapshot.next_actions[:5]])
            self.intent_next_text.insert(tk.END, "\n".join(lines))

    def _refresh_account_status(self, snapshot: GrowthOpsSnapshot):
        if not hasattr(self, "account_status_vars"):
            return
        status_counts = {"healthy_count": 0, "degraded_count": 0, "cooldown_count": 0}
        for row in snapshot.profile_health:
            status = str(row.get("status") or "")
            if status == "healthy":
                status_counts["healthy_count"] += 1
            elif status == "cooldown":
                status_counts["cooldown_count"] += 1
            else:
                status_counts["degraded_count"] += 1
        values = {
            "profile_health": len(snapshot.profile_health),
            "top_error_code": self._format_error_for_operator(snapshot.operational_status.get("top_error_code", "")),
            "next_execution_action": snapshot.execution_readiness_summary.get("next_execution_action", ""),
            **status_counts,
        }
        for key, var in self.account_status_vars.items():
            var.set(str(values.get(key, 0)))

    def _intent_counts(self, rows: list[dict]) -> dict:
        counts = {"purchase": 0, "consult": 0, "interest": 0, "entertainment": 0, "spam": 0}
        for row in rows or []:
            intent = self._classify_intent(row)
            counts[intent] = counts.get(intent, 0) + 1
        return counts

    def _classify_intent(self, row: dict) -> str:
        text = " ".join([str(row.get("intent_tags") or ""), str(row.get("comment_text") or "")]).lower()
        if not text.strip() or len(text.strip()) <= 2:
            return "spam"
        if any(token in text for token in ["buy", "price", "shop", "order", "link", "where to buy", "购买", "价格", "怎么买"]):
            return "purchase"
        if any(token in text for token in ["how", "where", "which", "name", "tutorial", "can i", "怎么", "哪里", "教程", "名字"]):
            return "consult"
        if any(token in text for token in ["download", "watch", "episode", "part 2", "free", "app", "下载", "观看", "第二集"]):
            return "interest"
        if any(token in text for token in ["haha", "lol", "nice", "love", "beautiful", "😂", "❤️", "好看", "哈哈"]):
            return "entertainment"
        return "interest"

    def _keyword_rows(self, rows: list[dict]) -> list[dict]:
        from collections import Counter

        stopwords = {"the", "and", "you", "for", "this", "that", "with", "are", "was", "were", "uma", "para", "que", "com", "comment", "reply"}
        counter = Counter()
        for row in rows or []:
            text = str(row.get("comment_text") or "").lower()
            clean = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
            for token in clean.split():
                if len(token) < 3 or token in stopwords:
                    continue
                counter[token] += 1
        return [{"keyword": key, "count": value} for key, value in counter.most_common(20)]

    def _intent_label(self, key: str) -> str:
        labels = {
            "high": "高意向用户",
            "observe": "可观察用户",
            "low": "低价值用户",
            "purchase": "购买意向",
            "consult": "咨询意向",
            "interest": "内容兴趣",
            "entertainment": "娱乐评论",
            "spam": "垃圾/无效评论",
        }
        return labels.get(key, key)

    def _format_operational_status_value(self, key: str, value):
        if key == "status":
            labels = {
                "lead_ready": "有可跟进线索",
                "needs_attention": "需处理失败",
                "no_leads": "暂无线索",
                "needs_source_tuning": "需优化数据源",
                "ready": "待采集/已就绪",
            }
            return labels.get(str(value or ""), str(value or "待采集/已就绪"))
        if key == "completion_rate":
            try:
                return f"{float(value or 0) * 100:.0f}%"
            except Exception:
                return "0%"
        if key == "top_error_code":
            return self._format_error_for_operator(value)
        return value

    def _format_error_for_operator(self, value) -> str:
        return display_error_code(str(value or ""))

    def _fill_tree(self, name, rows):
        tree = self._trees.get(name)
        if not tree:
            return
        tree.delete(*tree.get_children())
        columns = tree["columns"]
        for row in rows:
            values = []
            for column in columns:
                value = row.get(column, "")
                if column in {"status", "public_status"}:
                    value = status_label(str(value))
                if column == "source_type":
                    value = display_source_type(str(value))
                if column == "type" and str(value) in SOURCE_TYPE_LABELS:
                    value = display_source_type(str(value))
                if column == "action_type":
                    value = display_action_type(str(value))
                if column == "risk_level":
                    value = display_risk_level(str(value))
                if column in {"error_code", "last_error_code", "block_reason"}:
                    value = self._format_error_for_operator(value)
                values.append(value)
            tree.insert("", tk.END, values=values)

    def _refresh_filtered_tables(self):
        snapshot = self.last_snapshot
        candidates = snapshot.candidate_users
        actions = snapshot.action_queue
        if self.workflow_service:
            candidates = self.workflow_service.filter_candidate_rows(
                candidates,
                tier=_value_from_label(self.lead_tier_var.get(), LEAD_TIER_LABELS),
                language=_value_from_label(self.lead_language_var.get(), LANGUAGE_FILTER_LABELS),
                profile_completed=_value_from_label(self.lead_profile_var.get(), PROFILE_COMPLETED_LABELS),
                keyword=self.lead_keyword_var.get(),
            )
            actions = self.workflow_service.filter_action_rows(
                actions,
                status=_value_from_label(self.action_status_var.get(), ACTION_STATUS_LABELS),
                risk_level=_value_from_label(self.action_risk_var.get(), RISK_FILTER_LABELS),
                review_status=_value_from_label(self.action_review_var.get(), REVIEW_FILTER_LABELS),
                block_reason=block_reason_from_label(self.action_block_reason_var.get()),
                keyword=self.action_keyword_var.get(),
            )
        self._last_filtered_candidates = candidates
        self._last_filtered_actions = actions
        self._fill_tree("线索池", candidates)
        self._fill_tree("动作队列", actions)

    def _candidate_filter_payload(self) -> dict:
        return {
            "tier": _value_from_label(self.lead_tier_var.get(), LEAD_TIER_LABELS),
            "language": _value_from_label(self.lead_language_var.get(), LANGUAGE_FILTER_LABELS),
            "profile_completed": _value_from_label(self.lead_profile_var.get(), PROFILE_COMPLETED_LABELS),
            "keyword": self.lead_keyword_var.get(),
        }

    def _action_filter_payload(self) -> dict:
        return {
            "status": _value_from_label(self.action_status_var.get(), ACTION_STATUS_LABELS),
            "risk_level": _value_from_label(self.action_risk_var.get(), RISK_FILTER_LABELS),
            "review_status": _value_from_label(self.action_review_var.get(), REVIEW_FILTER_LABELS),
            "block_reason": block_reason_from_label(self.action_block_reason_var.get()),
            "keyword": self.action_keyword_var.get(),
        }

    def _export_filtered_candidates(self):
        if not self.workflow_service:
            return ""
        self._refresh_filtered_tables()
        path = self.workflow_service.export_filtered_rows(
            "candidate_users",
            getattr(self, "_last_filtered_candidates", []),
            self._candidate_filter_payload(),
        )
        if path:
            self._notify("INFO", "线索已导出", path)
        return path

    def _export_filtered_actions(self):
        if not self.workflow_service:
            return
        self._refresh_filtered_tables()
        self.workflow_service.export_filtered_rows(
            "action_queue",
            getattr(self, "_last_filtered_actions", []),
            self._action_filter_payload(),
        )

    def _save_candidate_filter_preset(self):
        if not self.workflow_service:
            return
        self.workflow_service.save_filter_preset(
            "candidate_users",
            self.lead_preset_name_var.get(),
            self._candidate_filter_payload(),
        )
        self.refresh(self._active_snapshot())

    def _load_candidate_filter_preset(self):
        if not self.workflow_service:
            return
        filters = self.workflow_service.load_filter_preset("candidate_users", self.lead_preset_name_var.get())
        if not filters:
            return
        self.lead_tier_var.set(LEAD_TIER_LABELS.get(str(filters.get("tier") or "all"), LEAD_TIER_LABELS["all"]))
        self.lead_language_var.set(LANGUAGE_FILTER_LABELS.get(str(filters.get("language") or "all"), LANGUAGE_FILTER_LABELS["all"]))
        self.lead_profile_var.set(PROFILE_COMPLETED_LABELS.get(str(filters.get("profile_completed") or "all"), PROFILE_COMPLETED_LABELS["all"]))
        self.lead_keyword_var.set(str(filters.get("keyword") or ""))
        self._refresh_filtered_tables()

    def focus_high_value_candidates(self):
        self.nav_var.set("线索池")
        self.lead_tier_var.set(LEAD_TIER_LABELS["high"])
        self.lead_language_var.set(LANGUAGE_FILTER_LABELS["all"])
        self.lead_profile_var.set(PROFILE_COMPLETED_LABELS["all"])
        self.lead_keyword_var.set("")
        self._switch_view()
        self._refresh_filtered_tables()

    def export_high_value_candidates(self):
        self.focus_high_value_candidates()
        return self._export_filtered_candidates()

    def _save_action_filter_preset(self):
        if not self.workflow_service:
            return
        self.workflow_service.save_filter_preset(
            "action_queue",
            self.action_preset_name_var.get(),
            self._action_filter_payload(),
        )
        self.refresh(self._active_snapshot())

    def _load_action_filter_preset(self):
        if not self.workflow_service:
            return
        filters = self.workflow_service.load_filter_preset("action_queue", self.action_preset_name_var.get())
        if not filters:
            return
        self.action_status_var.set(ACTION_STATUS_LABELS.get(str(filters.get("status") or "all"), ACTION_STATUS_LABELS["all"]))
        self.action_risk_var.set(RISK_FILTER_LABELS.get(str(filters.get("risk_level") or "all"), RISK_FILTER_LABELS["all"]))
        self.action_review_var.set(REVIEW_FILTER_LABELS.get(str(filters.get("review_status") or "all"), REVIEW_FILTER_LABELS["all"]))
        block_reason = str(filters.get("block_reason") or "all")
        self.action_block_reason_var.set("全部阻断" if block_reason == "all" else display_error_code(block_reason))
        self.action_keyword_var.set(str(filters.get("keyword") or ""))
        self._refresh_filtered_tables()

    def _show_selected_detail(self, name: str):
        tree = self._trees.get(name)
        detail = self._trees.get(f"{name}__detail")
        if not tree or not detail:
            return
        selected = tree.selection()
        detail.delete("1.0", tk.END)
        if not selected:
            detail.insert(tk.END, "选择一行查看详情")
            return
        columns = list(tree["columns"])
        values = tree.item(selected[0], "values")
        row = {columns[index]: values[index] if index < len(values) else "" for index in range(len(columns))}
        if name == "内容/素材":
            detail.insert(tk.END, self._format_content_detail(row))
            return
        if name == "创作者池":
            detail.insert(tk.END, self._format_creator_detail(row))
            return
        detail.insert(tk.END, self._format_detail(row))

    def _show_selected_candidate_detail(self):
        tree = self._trees.get("线索池")
        detail = self._trees.get("线索池__detail")
        if not tree or not detail:
            return
        selected = tree.selection()
        detail.delete("1.0", tk.END)
        if not selected:
            detail.insert(tk.END, "选择一行查看详情")
            return
        columns = list(tree["columns"])
        values = tree.item(selected[0], "values")
        row = {columns[index]: values[index] if index < len(values) else "" for index in range(len(columns))}
        detail.insert(tk.END, self._format_candidate_detail(row))

    def _format_detail(self, row: dict) -> str:
        lines = []
        for key, value in row.items():
            lines.append(f"{self._label(key)}: {value}")
        return "\n".join(lines)

    def _format_candidate_detail(self, row: dict) -> str:
        lines = [
            f"用户: @{row.get('username', '')}",
            f"评分/状态: {row.get('qualify_score', '')} / {row.get('status', '')}",
            f"意图标签: {row.get('intent_tags', '')}",
            f"语言/主页补全: {row.get('comment_language', '')} / {row.get('profile_completed', '')}",
            f"主页: {row.get('profile_url', '')}",
            f"来源: {row.get('source', '')}",
            f"视频: {row.get('video_id', '')} / 播放 {row.get('views', '')}",
            "",
            "评论:",
            str(row.get("comment_text") or ""),
        ]
        return "\n".join(lines)

    def _open_selected_candidate_profile(self):
        profile_url = self._selected_tree_value("线索池", "profile_url")
        if profile_url:
            webbrowser.open(profile_url)

    def _open_selected_candidate_source(self):
        source = self._selected_tree_value("线索池", "source")
        if source:
            webbrowser.open(source)

    def _open_selected_content_source(self):
        source = self._selected_tree_value("内容/素材", "video_url")
        if source:
            webbrowser.open(source)

    def _show_selected_content_detail_popup(self):
        row = self._selected_tree_row("内容/素材")
        if not row:
            return
        self._notify("INFO", "素材详情", self._format_content_detail(row))

    def _format_content_detail(self, row: dict) -> str:
        lines = [
            f"内容ID: {row.get('video_id', '')}",
            f"类型: {row.get('content_kind', '')}",
            f"播放/评论: {row.get('views', '')} / {row.get('comments', '')}",
            f"信号分: {row.get('signal_score', '')}",
            f"店铺/商品: {row.get('shop_name', '')} / {row.get('commerce_title', '')}",
            f"来源: {row.get('video_url', '')}",
        ]
        if row.get("signal_tags"):
            lines.append(f"信号标签: {row.get('signal_tags', '')}")
        lines.extend(["", "文案:", str(row.get("caption") or "")])
        return "\n".join(lines)

    def _open_selected_creator_profile(self):
        profile_url = self._selected_tree_value("创作者池", "profile_url")
        if profile_url:
            webbrowser.open(profile_url)

    def _show_selected_creator_detail_popup(self):
        row = self._selected_tree_row("创作者池")
        if not row:
            return
        self._notify("INFO", "创作者详情", self._format_creator_detail(row))

    def _format_creator_detail(self, row: dict) -> str:
        lines = [
            f"创作者: @{str(row.get('username') or '').lstrip('@')}",
            f"主页: {row.get('profile_url', '')}",
            f"粉丝/点赞: {row.get('followers', '')} / {row.get('likes_total', '')}",
            f"垂类/国家/语言: {row.get('vertical', '')} / {row.get('country', '')} / {row.get('language', '')}",
            f"状态: {status_label(str(row.get('status') or ''))}",
            f"来源路径: {row.get('source_path', '')}",
            f"批次: {row.get('batch_id', '')}",
            f"最近检查: {row.get('last_checked_at', '')}",
        ]
        return "\n".join(lines)

    def _exclude_selected_candidate(self):
        if not self.workflow_service:
            return
        username = self._selected_tree_value("线索池", "username")
        profile_url = self._selected_tree_value("线索池", "profile_url")
        if not username and not profile_url:
            self._notify("WARN", "未选择线索", "请先在线索池选择一个用户。")
            return
        label = f"@{username.lstrip('@')}" if username else profile_url
        reason = simpledialog.askstring("加入排除名单", f"请输入排除 {label} 的原因：")
        if not str(reason or "").strip():
            self._notify("WARN", "加入排除未完成", "加入排除名单必须填写原因。")
            return
        item_id = self.workflow_service.add_exclusion(
            target_username=username,
            target_url=profile_url,
            reason=str(reason).strip(),
        )
        if not item_id:
            self._notify("WARN", "排除名单未保存", "请填写用户名或目标链接。")
            return
        self._notify("INFO", "排除名单已保存", item_id)
        self.refresh(self._active_snapshot())

    def _switch_view(self):
        view_name = self.nav_var.get()
        nested = self._nested_views.get(view_name)
        if nested:
            parent_name, notebook, index = nested
            try:
                notebook.select(index)
            except Exception:
                pass
            view_name = parent_name
            self.nav_var.set(parent_name)
        view = self.views.get(view_name) or self.views.get("获客任务")
        if view is None:
            return
        self.page_title_var.set(view_name)
        self.page_subtitle_var.set(PAGE_SUBTITLES.get(view_name, ""))
        self._style_nav_buttons()
        view.tkraise()
        view.lift()
        try:
            self.stack.update_idletasks()
        except Exception:
            pass

    def _review_selected_action(self, action: str):
        tree = self._trees.get("动作队列")
        if not tree or not self.workflow_service:
            return
        action_ids = self._selected_action_ids(tree)
        if not action_ids:
            return
        if action == "confirm" and not self._confirm_bulk_action(action_ids):
            return
        if action == "reject":
            note = simpledialog.askstring("拒绝原因", "请输入拒绝所选动作的原因：")
            if not str(note or "").strip():
                self._notify("WARN", "拒绝未完成", "拒绝动作必须填写原因。")
                return
            note = str(note).strip()
        else:
            note = getattr(self, "_last_confirmation_note", "") if action == "confirm" else f"bulk {action} from operator console"
        result = self.workflow_service.bulk_review_actions(action_ids, action, note or f"bulk {action} from operator console")
        if result.get("error") == "HIGH_RISK_CONFIRMATION_NOTE_REQUIRED":
            self._notify("WARN", "确认未完成", "高风险动作必须填写确认备注。")
            return
        if result.get("error") == "ACTION_REJECTION_NOTE_REQUIRED":
            self._notify("WARN", "拒绝未完成", "拒绝动作必须填写原因。")
            return
        self.refresh(self._active_snapshot())

    def _preview_selected_actions(self):
        tree = self._trees.get("动作队列")
        if not tree or not self.workflow_service:
            return
        action_ids = self._selected_action_ids(tree)
        if not action_ids:
            return
        preview = self.workflow_service.build_bulk_confirmation_preview(action_ids)
        self._notify("INFO", "所选动作预览", self._format_bulk_confirmation_preview(preview))

    def _show_selected_action_detail(self):
        tree = self._trees.get("动作队列")
        detail = self._trees.get("动作队列__detail")
        if not tree or not detail:
            return
        selected = tree.selection()
        detail.delete("1.0", tk.END)
        if not selected:
            detail.insert(tk.END, "选择动作查看审核详情")
            return
        columns = list(tree["columns"])
        values = tree.item(selected[0], "values")
        row = {columns[index]: values[index] if index < len(values) else "" for index in range(len(columns))}
        detail.insert(tk.END, self._format_action_detail(row))

    def _format_action_detail(self, row: dict) -> str:
        lines = [
            f"动作: {row.get('action_type', '')}",
            f"目标: @{row.get('target_username', '')}",
            f"执行状态: {row.get('public_status', '')}",
            f"状态/审核/确认: {row.get('status', '')} / {row.get('review_status', '')} / {row.get('execution_confirmed', '')}",
            f"风险: {row.get('risk_level', '')}",
            f"准备状态: {row.get('readiness_status', '')}",
            f"阻断原因: {row.get('block_reason', '')}",
            f"推荐账号: {row.get('recommended_profile_id', '')}",
            f"剩余额度: {row.get('quota_remaining', '')}",
            f"最近错误: {row.get('last_error_code', '')}",
            "",
            "建议文案:",
            str(row.get("suggested_text") or ""),
        ]
        return "\n".join(lines)

    def _confirm_bulk_action(self, action_ids: list[str]) -> bool:
        preview = self.workflow_service.build_bulk_confirmation_preview(action_ids)
        self._last_confirmation_note = ""
        if not preview.get("requires_attention"):
            return True
        message = self._format_bulk_confirmation_preview(preview)
        if not messagebox.askyesno("确认执行前复核", message):
            return False
        if int(preview.get("high_risk_count") or 0) > 0:
            note = simpledialog.askstring("高风险确认备注", "请输入高风险动作确认备注：")
            if not str(note or "").strip():
                self._notify("WARN", "确认未完成", "高风险动作必须填写确认备注。")
                return False
            self._last_confirmation_note = str(note).strip()
        return True

    def _format_bulk_confirmation_preview(self, preview: dict) -> str:
        lines = [
            f"选中动作: {preview.get('selected_count', 0)}",
            f"已批准: {preview.get('approved_count', 0)}",
            f"高风险: {preview.get('high_risk_count', 0)}",
            f"确认后可执行: {preview.get('ready_after_confirmation_count', 0)}",
            f"确认后仍阻断: {preview.get('post_confirm_blocked_count', 0)}",
        ]
        if preview.get("warnings"):
            lines.append("")
            lines.append("风险提示:")
            lines.extend([f"- {item}" for item in preview.get("warnings", [])])
        if preview.get("profile_quota_summary"):
            lines.append("")
            lines.append("账号配额:")
            for item in preview.get("profile_quota_summary", [])[:5]:
                marker = " / 超额" if item.get("will_exceed") else ""
                lines.append(
                    f"- {item.get('profile_id')} {item.get('action_type')}: "
                    f"已用 {item.get('used')} / 上限 {item.get('limit')} / 剩余 {item.get('remaining')} / "
                    f"确认后需要 {item.get('demand_after_confirmation')}{marker}"
                )
        if preview.get("template_previews"):
            lines.append("")
            lines.append("话术预览:")
            for item in preview.get("template_previews", [])[:5]:
                text = str(item.get("rendered_text") or item.get("suggested_text") or "")
                if len(text) > 80:
                    text = text[:77] + "..."
                mismatch = "" if item.get("matches_suggested") else " / 与队列文案不一致"
                lines.append(f"- {item.get('action_type')} @{item.get('target_username')}: {text}{mismatch}")
        lines.append("")
        lines.append("是否继续确认所选动作？")
        return "\n".join(lines)

    def _show_execution_plan(self):
        tree = self._trees.get("动作队列")
        if not tree or not self.workflow_service:
            return
        action_ids = self._selected_action_ids(tree)
        if not action_ids:
            return
        plan = self.workflow_service.build_execution_plan(action_ids)
        self._notify("INFO", "执行计划 Dry-Run", self._format_execution_plan(plan))

    def _export_execution_plan(self):
        tree = self._trees.get("动作队列")
        if not tree or not self.workflow_service:
            return
        action_ids = self._selected_action_ids(tree)
        if not action_ids:
            return
        path = self.workflow_service.export_execution_plan(action_ids)
        self._notify("INFO", "执行计划已导出", path)

    def _format_execution_plan(self, plan: dict) -> str:
        lines = [
            f"账号: {plan.get('profile_id', '')}",
            f"选中动作: {plan.get('selected_count', 0)}",
            f"纳入计划: {plan.get('planned_count', 0)}",
            f"将执行: {plan.get('executable_count', 0)}",
            f"将跳过: {plan.get('skipped_count', 0)}",
        ]
        if plan.get("quota_summary"):
            lines.append("")
            lines.append("配额预估:")
            for item in plan.get("quota_summary", [])[:6]:
                lines.append(
                    f"- {item.get('action_type')}: 本轮 {item.get('planned')} / "
                    f"执行前剩余 {item.get('remaining_before')} / 执行后剩余 {item.get('remaining_after')}"
                )
        skipped = [item for item in plan.get("items", []) if item.get("status") == "skipped"]
        if skipped:
            lines.append("")
            lines.append("跳过原因:")
            for item in skipped[:6]:
                lines.append(f"- {item.get('action_type')} @{item.get('target_username')}: {item.get('skip_reason')}")
        return "\n".join(lines)

    def _execute_selected_plan_dry_run(self):
        if not self.workflow_service:
            return
        plan_id = self._selected_tree_value("执行计划", "id")
        if not plan_id:
            return
        result = self.workflow_service.execute_plan_dry_run(plan_id)
        self._log_operator_event("DONE   execution_plan_dry_run " + self._format_execution_result(result).replace("\n", " | "))
        self.refresh(self._active_snapshot())

    def _run_action_router_dry_run(self):
        self.action_execution_mode_var.set("预检，不提交")
        self.action_execution_live_confirm_var.set(False)
        return self._run_action_router_from_ui()

    def _run_action_router_from_ui(self):
        if not self.workflow_service:
            return
        self._selected_profile_group()
        profiles = [
            {
                "profile_id": row.get("profile_id", ""),
                "group_name": row.get("group_name", ""),
                "name": row.get("name", ""),
                "group_id": row.get("group_id", ""),
            }
            for row in (self.last_snapshot.profile_health or [])
            if row.get("profile_id")
        ]
        group = self.action_execution_group_var.get().strip()
        if group:
            profiles = [profile for profile in profiles if str(profile.get("group_name", "")).lower() == group.lower()]
        if not profiles:
            self._log_operator_event("BLOCK  action_router not_started reason=缺少可用账号 next=刷新账号分组或先完成一次采集")
            return
        try:
            from .action_router import ActionRouterConfig
            from .tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor

            mode = self.action_execution_mode_var.get()
            live_mode = mode == "真实提交"
            confirmed = bool(self.action_execution_live_confirm_var.get())
            if live_mode and not confirmed:
                self._log_operator_event("WARN   action_router live_submit_not_confirmed mode=preflight_only no_submit=true")
            platform_executor = TikTokSeleniumActionExecutor(
                TikTokActionExecutorConfig(
                    close_browser_after_action=True,
                    preflight_only=not (live_mode and confirmed),
                )
            )

            result = self.workflow_service.run_action_router(
                profiles,
                config=ActionRouterConfig(
                    batch_id=self._active_campaign_batch_id(),
                    max_workers=max(1, min(int(self.action_execution_workers_var.get() or 1), len(profiles))),
                    per_profile_action_limit=max(1, int(self.action_execution_per_profile_var.get() or 1)),
                    max_switch_attempts=2,
                    dry_run=False,
                    live_preflight_only=not live_mode,
                    allow_live_submit=live_mode and confirmed,
                    require_action_review=live_mode,
                    auto_approve=False,
                    auto_confirm=False,
                    min_delay_seconds=0,
                    max_delay_seconds=0,
                    profile_group=group,
                    per_profile_hour_limit=max(1, int(self.action_execution_hour_limit_var.get() or 1)),
                    per_profile_video_hour_limit=max(1, int(self.action_execution_video_hour_limit_var.get() or 1)),
                ),
                platform_executor=platform_executor,
                export_report=True,
            )
            title = "自动执行编排结果" if live_mode else "自动执行预检结果"
            self._log_operator_event(f"DONE   {title} " + self._format_action_router_result(result).replace("\n", " | "))
            self.refresh(self._active_snapshot())
        except Exception as exc:
            self._log_operator_event(f"ERROR  action_router failed error={exc}")

    def _format_action_router_result(self, result: dict) -> str:
        lines = [
            f"选择动作: {result.get('selected_actions', 0)}",
            f"执行线程: {result.get('worker_count', 0)}",
            f"尝试次数: {result.get('attempt_count', 0)}",
            f"成功: {result.get('success', 0)}",
            f"失败: {result.get('failed', 0)}",
            f"跳过: {result.get('skipped', 0)}",
            f"换号: {result.get('account_switched', 0)}",
        ]
        if result.get("errors"):
            lines.append("")
            lines.append("错误统计:")
            for code, count in sorted(result.get("errors", {}).items()):
                lines.append(f"- {code}: {count}")
        report = result.get("report") or {}
        if report.get("json_path"):
            lines.append("")
            lines.append(f"报告: {report.get('json_path')}")
        return "\n".join(lines)

    def _format_execution_result(self, result: dict) -> str:
        lines = [
            f"计划: {result.get('plan_id', '')}",
            f"状态: {result.get('status', '')}",
            f"账号: {result.get('profile_id', '')}",
            f"已执行: {result.get('executed_count', 0)}",
            f"已跳过: {result.get('skipped_count', 0)}",
        ]
        failed = [item for item in result.get("results", []) if item.get("status") != "completed"]
        if failed:
            lines.append("")
            lines.append("异常/跳过:")
            for item in failed[:6]:
                lines.append(f"- {item.get('action_id', '')}: {item.get('error_code', item.get('status', ''))}")
        return "\n".join(lines)

    def _rerun_selected_error(self):
        error_code = self._selected_tree_value("错误诊断", "error_code")
        if not error_code:
            return
        if self.on_rerun_error:
            self.on_rerun_error(error_code)

    def _rerun_selected_collection_task_error(self):
        status = self._selected_tree_value("采集任务", "status")
        error_code = self._selected_tree_value("采集任务", "error_code")
        if not error_code or ("失败" not in status and status != "failed"):
            return
        if self.on_rerun_error:
            self.on_rerun_error(error_code)

    def _rerun_selected_collection_tasks(self):
        task_ids = self._selected_collection_task_ids()
        if task_ids and self.on_rerun_tasks:
            self.on_rerun_tasks(task_ids)
            return
        self._rerun_selected_collection_task_error()

    def _show_selected_collection_batch_progress(self):
        if not self.workflow_service:
            return
        batch_id = self._selected_tree_value("采集批次", "id")
        if not batch_id:
            return
        progress = self.workflow_service.build_collection_batch_progress(batch_id)
        self._notify("INFO", "采集批次进度", self._format_collection_batch_progress(progress))

    def _format_collection_batch_progress(self, progress: dict) -> str:
        batch = progress.get("batch") or {}
        summary = progress.get("summary") or {}
        if not summary.get("found"):
            return "未找到采集批次。"
        lines = [
            f"批次: {progress.get('batch_id', '')}",
            f"状态: {status_label(str(batch.get('status') or ''))}",
            f"账号分组: {batch.get('profile_group', '')}",
            f"总数据源: {summary.get('total_sources', 0)}",
            f"完成/失败: {summary.get('processed_sources', 0)} / {summary.get('failed_sources', 0)}",
            f"完成率: {round(float(summary.get('completion_rate', 0)) * 100, 2)}%",
            f"失败率: {round(float(summary.get('failure_rate', 0)) * 100, 2)}%",
            f"下一步: {summary.get('next_operator_action', '')}",
        ]
        if progress.get("status_counts"):
            lines.append("")
            lines.append("任务状态:")
            for key, value in progress.get("status_counts", {}).items():
                lines.append(f"- {status_label(str(key))}: {value}")
        if progress.get("error_counts"):
            lines.append("")
            lines.append("错误分布:")
            for key, value in progress.get("error_counts", {}).items():
                lines.append(f"- {key}: {value}")
        if progress.get("profile_counts"):
            lines.append("")
            lines.append("账号分布:")
            for key, value in list(progress.get("profile_counts", {}).items())[:8]:
                lines.append(f"- {key}: {value}")
        recent_tasks = progress.get("recent_tasks") or []
        if recent_tasks:
            lines.append("")
            lines.append("最近任务:")
            for task in recent_tasks[:8]:
                label = f"{task.get('source_type', '')} {task.get('source_value', '')}".strip()
                err = f" / {task.get('error_code', '')}" if task.get("error_code") else ""
                lines.append(f"- {status_label(str(task.get('status') or ''))}: {label}{err}")
        return "\n".join(lines)

    def _show_selected_collection_task_timeline(self):
        if not self.workflow_service:
            return
        task_id = self._selected_tree_value("采集任务", "id")
        if not task_id:
            return
        timeline = self.workflow_service.build_collection_task_timeline(task_id)
        self._notify("INFO", "采集任务时间线", self._format_collection_task_timeline(timeline))

    def _open_selected_collection_task_evidence(self):
        if not self.workflow_service:
            return
        task_id = self._selected_tree_value("采集任务", "id")
        if not task_id:
            return
        timeline = self.workflow_service.build_collection_task_timeline(task_id)
        screenshot_path = self._latest_timeline_screenshot_path(timeline)
        if not screenshot_path:
            self._notify("INFO", "采集任务证据", "该任务暂无截图证据。")
            return
        uri = evidence_uri_for_path(screenshot_path)
        if uri:
            webbrowser.open(uri)

    def _format_collection_task_timeline(self, timeline: dict) -> str:
        task = timeline.get("task") or {}
        summary = timeline.get("summary") or {}
        if not summary.get("found"):
            return "未找到采集任务。"
        lines = [
            f"任务: {timeline.get('task_id', '')}",
            f"数据源: {task.get('source_type', '')} {task.get('source_value', '')}",
            f"账号: {task.get('profile_id', '')}",
            f"状态: {status_label(str(task.get('status') or ''))}",
            f"错误码: {task.get('error_code', '')}",
            f"事件/错误/证据: {summary.get('event_count', 0)} / {summary.get('error_count', 0)} / {summary.get('evidence_count', 0)}",
        ]
        if summary.get("error_codes"):
            lines.append("错误集合: " + ", ".join(summary.get("error_codes") or []))
        lines.append("")
        lines.append("最近时间线:")
        for item in (timeline.get("timeline") or [])[-12:]:
            marker = "ERR" if item.get("kind") == "error" else "EVT"
            event_name = item.get("event", "")
            detail = item.get("message") or item.get("error_code") or ""
            if item.get("event") == "collector_evidence":
                detail = f"{item.get('collector_level', '')}/{item.get('adapter_name', '')} items={item.get('item_count', 0)}"
                if item.get("screenshot_path"):
                    detail += f" screenshot={item.get('screenshot_path')}"
            lines.append(f"- [{marker}] {item.get('time', '')} {event_name} {detail}".rstrip())
        return "\n".join(lines)

    def _latest_timeline_screenshot_path(self, timeline: dict) -> str:
        for item in reversed(timeline.get("timeline") or []):
            screenshot_path = str(item.get("screenshot_path") or "").strip()
            if screenshot_path:
                return screenshot_path
        return ""

    def _selected_collection_task_ids(self) -> list[str]:
        tree = self._trees.get("采集任务")
        if not tree:
            return []
        selected = tree.selection()
        if not selected:
            return []
        columns = list(tree["columns"])
        try:
            id_index = columns.index("id")
            status_index = columns.index("status")
        except Exception:
            return []
        task_ids = []
        for item_id in selected:
            values = tree.item(item_id, "values")
            if id_index >= len(values) or status_index >= len(values):
                continue
            status = str(values[status_index] or "")
            if "失败" not in status and status != "failed":
                continue
            task_id = str(values[id_index] or "").strip()
            if task_id:
                task_ids.append(task_id)
        return task_ids

    def _update_selected_scheduled_scan(self, action: str):
        if not self.workflow_service:
            return
        scan_id = self._selected_tree_value("定时扫描", "id")
        if not scan_id:
            return
        if action == "pause":
            self.workflow_service.pause_scheduled_scan(scan_id)
        elif action == "resume":
            self.workflow_service.resume_scheduled_scan(scan_id)
        self.refresh(self._active_snapshot())

    def _create_scheduled_scan(self):
        if not self.workflow_service:
            return
        source_value = self.scan_source_value_var.get().strip()
        if not source_value:
            return
        group = self._selected_profile_group()
        self.workflow_service.create_scheduled_scan(
            normalize_source_type(self.scan_source_type_var.get()),
            source_value,
            profile_group=group,
            interval_minutes=max(1, int(self.scan_interval_var.get() or 60)),
            max_videos=max(1, int(self.scan_max_videos_var.get() or 5)),
            max_comments=max(1, int(self.scan_max_comments_var.get() or 10)),
        )
        self.scan_source_value_var.set("")
        self.refresh(self._active_snapshot())

    def _create_scheduled_scans_bulk(self):
        if not self.workflow_service or not self.scan_bulk_text:
            return
        sources = parse_bulk_scan_sources(self.scan_bulk_text.get("1.0", tk.END), normalize_source_type(self.scan_source_type_var.get()))
        if not sources:
            return
        group = self._selected_profile_group()
        self.workflow_service.create_scans_bulk(
            sources,
            profile_group=group,
            interval_minutes=max(1, int(self.scan_interval_var.get() or 60)),
            max_videos=max(1, int(self.scan_max_videos_var.get() or 5)),
            max_comments=max(1, int(self.scan_max_comments_var.get() or 10)),
        )
        self.scan_bulk_text.delete("1.0", tk.END)
        self.refresh(self._active_snapshot())

    def _create_scan_from_selected_recommendation(self):
        if not self.workflow_service:
            return
        row = self._selected_tree_row("下一轮采集源")
        if not row:
            self._notify("WARN", "未选择推荐", "请先选择一个下一轮采集源推荐。")
            return
        source_value = self.recommended_source_value_var.get().strip() or str(row.get("source_value") or "").strip()
        if not source_value:
            self._notify("WARN", "缺少数据源", "请输入具体达人主页、内容链接或关键词。")
            return
        group = self._selected_profile_group()
        scan = self.workflow_service.create_scan_from_recommendation(
            {**row, "source_type": normalize_source_type(row.get("source_type", ""))},
            source_value,
            profile_group=group,
            interval_minutes=max(1, int(self.scan_interval_var.get() or 60)),
            max_videos=max(1, int(self.scan_max_videos_var.get() or 5)),
            max_comments=max(1, int(self.scan_max_comments_var.get() or 10)),
        )
        self.recommended_source_value_var.set("")
        self.refresh(self._active_snapshot())
        self._notify("INFO", "已新增扫描", f"已创建定时扫描: {display_source_type(scan.get('source_type'))} {scan.get('source_value')}")

    def _open_selected_evidence(self):
        screenshot_path = self._selected_tree_value("错误诊断", "screenshot_path")
        if not screenshot_path:
            return
        uri = evidence_uri_for_path(screenshot_path)
        if uri:
            webbrowser.open(uri)

    def _open_report_artifact(self, kind: str):
        artifacts = list(getattr(getattr(self, "last_snapshot", None), "report_artifacts", []) or [])
        if not artifacts and self.workflow_service:
            artifacts = self.workflow_service.latest_report_artifacts()
        target = next((item for item in artifacts if item.get("kind") == kind), {})
        path = str(target.get("path") or "").strip()
        if not path:
            self._notify("WARN", "报告未生成", "请先导出或运行增长情报报告。")
            return
        expanded = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(expanded):
            self._notify("WARN", "报告不存在", path)
            return
        uri = evidence_uri_for_path(expanded)
        if uri:
            webbrowser.open(uri)

    def _selected_tree_value(self, tree_name: str, column_name: str) -> str:
        tree = self._trees.get(tree_name)
        if not tree:
            return ""
        selected = tree.selection()
        if not selected:
            return ""
        columns = list(tree["columns"])
        try:
            column_index = columns.index(column_name)
        except Exception:
            return ""
        values = tree.item(selected[0], "values")
        if column_index >= len(values):
            return ""
        return str(values[column_index] or "").strip()

    def _selected_tree_row(self, tree_name: str) -> dict:
        tree = self._trees.get(tree_name)
        if not tree:
            return {}
        selected = tree.selection()
        if not selected:
            return {}
        columns = list(tree["columns"])
        values = tree.item(selected[0], "values")
        return {columns[index]: values[index] if index < len(values) else "" for index in range(len(columns))}

    def _selected_action_ids(self, tree) -> list[str]:
        selected = tree.selection()
        if not selected:
            return []
        columns = list(tree["columns"])
        try:
            id_index = columns.index("id")
        except Exception:
            return []
        action_ids = []
        for item_id in selected:
            values = tree.item(item_id, "values")
            if id_index < len(values):
                action_ids.append(str(values[id_index] or ""))
        return action_ids

    def _start_collection(self):
        self.append_runtime_log("CLICK  start_button source=operator_console")
        if self.on_start_collection:
            self.on_start_collection()
        else:
            self.append_runtime_log("BLOCK  start_button_no_callback source=operator_console")

    def _export_report(self):
        if self.on_export_report:
            self.on_export_report()

    def _run_due_scans(self):
        if self.on_run_due_scans:
            self.on_run_due_scans()

    def _run_selected_scheduled_scan(self):
        if not self.on_run_selected_scan:
            return
        scan_id = self._selected_tree_value("定时扫描", "id")
        if scan_id:
            self.on_run_selected_scan(scan_id)

    def _save_action_template(self):
        if not self.workflow_service or not self.template_body_text:
            return
        action_type = action_type_from_label(self.template_action_type_var.get())
        name = self.template_name_var.get().strip()
        body = self.template_body_text.get("1.0", tk.END).strip()
        status = template_status_from_label(self.template_status_var.get())
        template_id = self.workflow_service.save_action_template(action_type, name, body, status=status)
        if not template_id:
            self._notify("WARN", "模板未保存", "请填写动作、名称和模板正文。")
            return
        self._notify("INFO", "模板已保存", template_id)
        self.refresh(self._active_snapshot())

    def _save_exclusion(self):
        if not self.workflow_service:
            return
        item_id = self.workflow_service.add_exclusion(
            target_username=self.exclusion_username_var.get(),
            target_url=self.exclusion_url_var.get(),
            reason=self.exclusion_reason_var.get(),
        )
        if not item_id:
            self._notify("WARN", "排除名单未保存", "请填写用户名或目标链接。")
            return
        self._notify("INFO", "排除名单已保存", item_id)
        self.exclusion_username_var.set("")
        self.exclusion_url_var.set("")
        self.exclusion_reason_var.set("")
        self.refresh(self._active_snapshot())

    def _label(self, key):
        labels = {
            "data_sources": "数据源",
            "scheduled_scans": "定时扫描",
            "collection_batches": "采集批次",
            "collection_tasks": "采集任务",
            "profile_health": "账号健康",
            "profile_recommendations": "账号推荐",
            "error_diagnostics": "错误诊断",
            "creators": "创作者",
            "contents": "视频内容",
            "topic_contents": "话题内容",
            "candidates": "线索用户",
            "operation_leads": "运营线索",
            "action_queue": "动作队列",
            "execution_plans": "执行计划",
            "outreach_executions": "执行记录",
            "action_templates": "话术模板",
            "exclusions": "排除名单",
            "daily_quota": "日配额",
            "rate_limits": "小时限频",
            "filter_presets": "筛选预设",
            "id": "ID",
            "type": "类型",
            "value": "值",
            "source_type": "来源",
            "source_value": "目标",
            "profile_group": "账号分组",
            "schedule_interval_minutes": "间隔分钟",
            "next_run_at": "下次运行",
            "last_batch_id": "最近批次",
            "total_sources": "总数据源",
            "processed_sources": "已处理",
            "failed_sources": "失败数",
            "completion_rate": "完成率",
            "candidate_user_count": "线索用户",
            "high_value_candidate_count": "高价值线索",
            "comment_quality": "评论质量",
            "top_error_code": "首要错误",
            "planned_count": "计划动作",
            "executable_count": "可执行",
            "skipped_count": "跳过",
            "started_at": "开始时间",
            "completed_at": "完成时间",
            "status": "状态",
            "vertical": "垂类",
            "language": "语言",
            "updated_at": "更新时间",
            "group_name": "分组",
            "health_score": "健康分",
            "last_error_code": "最近错误",
            "recommended_profile_id": "推荐账号",
            "healthy_count": "健康数",
            "degraded_count": "降级数",
            "cooldown_count": "冷却数",
            "severity": "级别",
            "count": "次数",
            "cause": "原因",
            "suggested_action": "建议动作",
            "page_state": "页面状态",
            "stop_reason": "停止原因",
            "visible_node_count": "可见节点",
            "comment_container_count": "评论容器",
            "screenshot_path": "截图证据",
            "collector_level": "采集阶段",
            "collector_adapter": "采集方式",
            "batch_id": "批次",
            "failed_task_count": "失败任务",
            "rerun_available": "可重跑",
            "latest_source_value": "最近数据源",
            "source": "来源",
            "video_id": "内容ID",
            "caption": "标题/文案",
            "views": "播放",
            "comments": "评论",
            "signal_score": "信号分",
            "username": "用户",
            "profile_url": "主页",
            "followers": "粉丝",
            "qualify_score": "线索分",
            "intent_tags": "意图标签",
            "comment_language": "评论语言",
            "profile_completed": "主页补全",
            "comment_text": "评论",
            "video_url": "来源视频",
            "lead_type": "线索类型",
            "priority": "优先级",
            "source_type": "来源",
            "scenario": "适用场景",
            "score": "线索分",
            "lifecycle_stage": "生命周期",
            "action_count": "动作数",
            "source_path": "来源路径",
            "action_type": "动作",
            "target_username": "目标用户",
            "public_status": "执行状态",
            "raw_status": "系统状态",
            "risk_level": "风险",
            "review_status": "审核",
            "execution_confirmed": "执行确认",
            "readiness_status": "准备状态",
            "block_reason": "阻断原因",
            "quota_remaining": "剩余额度",
            "retry_count": "重试次数",
            "last_error_code": "最近错误",
            "suggested_text": "建议文案",
            "pending_review_count": "待审核",
            "approved_count": "已批准",
            "ready_to_execute_count": "可执行",
            "high_risk_count": "高风险",
            "retryable_count": "可重试",
            "next_operator_action": "下一步",
            "ready_count": "可执行",
            "blocked_count": "被阻断",
            "quota_blocked_count": "配额阻断",
            "excluded_count": "排除命中",
            "next_execution_action": "执行建议",
            "profile_id": "账号",
            "name": "名称",
            "body": "内容",
            "target_url": "目标链接",
            "reason": "原因",
            "quota_date": "日期",
            "used_count": "已用",
            "limit_count": "上限",
            "export_path": "导出路径",
            "error_code": "错误码",
            "error_message": "错误信息",
        }
        return labels.get(key, key)
