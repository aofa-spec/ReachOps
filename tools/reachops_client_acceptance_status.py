# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIR = ROOT_DIR / "reports/reachops/mac_gui/runtime"
REMEDIATION_DIRNAME = "acceptance_remediation"


def read_lines(path: Path, limit: int = 5000) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def latest_batch(db_path: Path) -> dict:
    if not db_path.exists():
        return {}
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, campaign_id, status, total_sources, processed_sources, failed_sources,
                   profile_group, config_json, created_at, updated_at, completed_at
            FROM collection_batches
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else {}


def latest_profile_preflight(db_path: Path) -> dict:
    if not db_path.exists():
        return {}
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT payload, created_at
            FROM growth_events
            WHERE event='profile_preflight_completed'
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    try:
        payload = json.loads(row["payload"] or "{}")
    except Exception:
        payload = {}
    payload["created_at"] = row["created_at"]
    return payload


def runtime_restarted_after_batch(batch: dict, log_lines: list[str]) -> bool:
    batch_id = str(batch.get("id") or "").strip()
    if not batch_id:
        return False
    last_batch_index = -1
    last_ready_index = -1
    for index, line in enumerate(log_lines or []):
        if batch_id and batch_id in line:
            last_batch_index = index
        if "READY  app_started" in line or "READY  headless_app_started" in line:
            last_ready_index = index
    return last_batch_index >= 0 and last_ready_index > last_batch_index


def derive_acceptance(batch: dict, preflight: dict, log_lines: list[str]) -> dict:
    batch_config = parse_json(batch.get("config_json") or "{}")
    quick_send = batch_config.get("quick_send") if isinstance(batch_config, dict) else {}
    planned_sources = batch_config.get("planned_sources") if isinstance(batch_config, dict) else []
    restarted_after_batch = runtime_restarted_after_batch(batch, log_lines)
    scoped_lines = scope_log_lines(batch, log_lines)
    preflight_stale = profile_preflight_is_stale(batch, preflight)
    effective_preflight = {} if preflight_stale else preflight
    log_preflight = extract_profile_preflight_summary(scoped_lines)
    if log_preflight and int(log_preflight.get("checked") or 0) >= int(effective_preflight.get("checked") or 0):
        effective_preflight = log_preflight
        preflight_stale = False
    plan_ok = any("PLAN   campaign" in line for line in scoped_lines)
    product_auto_ok = any("PLAN   campaign" in line and "input_type=" in line for line in scoped_lines)
    start_ok = any("START  campaign" in line for line in scoped_lines)
    collection_done = any("DONE   collection" in line for line in scoped_lines)
    action_started = any(
        "START  action_submit" in line
        or "START  action_preflight" in line
        or "DONE   action_submit" in line
        or "DONE   action_preflight" in line
        for line in scoped_lines
    )
    headless_timeout = any("HEADLESS_TIMEOUT" in line for line in scoped_lines)
    available = int(effective_preflight.get("available") or 0)
    errors = effective_preflight.get("errors") or {}
    status = str(batch.get("status") or "")
    batch_completed = status == "completed"
    batch_failed = status in {"failed", "partial_failed"}
    profile_group = str(batch.get("profile_group") or "当前选择分组").strip() or "当前选择分组"
    profile_details = extract_profile_preflight_details(scoped_lines)
    profile_error_summary = summarize_profile_errors(profile_details)
    source_failure_summary = summarize_source_failures(extract_source_failures(scoped_lines, str(batch.get("id") or "")))
    top_source_error = top_error_code(source_failure_summary)
    refresh_summary = profile_refresh_summary(scoped_lines)
    selected_summary = selected_profile_summary(scoped_lines, profile_group)
    group_log_token = f"group={profile_group}"
    quick_preflight_candidates_loaded = any(
        "CONFIG quick_preflight_candidates" in line and group_log_token in line
        for line in scoped_lines
    )
    selected_profile_list_seen = bool(selected_summary.get("seen"))
    selected_profile_candidates_loaded = bool(selected_profile_list_seen and int(selected_summary.get("candidates") or 0) > 0)
    profile_list_evidence_seen = bool(quick_preflight_candidates_loaded or selected_profile_list_seen)
    profile_candidates_loaded = bool(quick_preflight_candidates_loaded or selected_profile_candidates_loaded)
    account_queue_started = any(
        "QUEUE  account_queue_start" in line and group_log_token in line
        for line in scoped_lines
    )
    profile_list_execution_evidence = bool(profile_candidates_loaded and account_queue_started and (available > 0 or profile_details))

    blockers = []
    if not plan_ok:
        blockers.append("未看到 PLAN campaign，推广目标未进入任务规划。")
    if plan_ok and not product_auto_ok:
        blockers.append("未确认产品链接自动识别为 product_url。")
    if restarted_after_batch:
        blockers.append("客户端已在最新批次之后重启，当前版本尚未产生新的真实执行批次，不能用旧批次作为本次验收证据。")
    if preflight_stale:
        blockers.append("账号预检证据早于当前批次，不能复用旧账号可用性作为本次客户端验收。")
    if start_ok and refresh_summary.get("empty"):
        blockers.append("ixBrowser 配置分组刷新成功，但本地 API 返回 groups=0/profiles=0，不能进入真实账号采集。")
    elif start_ok and not profile_list_evidence_seen:
        blockers.append("未看到从选中账号分组读取配置候选的日志，不能证明配置列表参与本次采集。")
    elif start_ok and selected_profile_list_seen and int(selected_summary.get("candidates") or 0) <= 0:
        blockers.append(f"所选账号分组 {profile_group} 候选账号为 0，无法启动真实采集。")
    if start_ok and refresh_summary.get("empty") and not account_queue_started:
        blockers.append("配置列表为空，账号队列未启动；请先确认 ixBrowser 本地服务能返回所选分组账号。")
    elif start_ok and profile_candidates_loaded and not account_queue_started:
        blockers.append("未看到账号队列按选中分组启动，不能证明采集使用了该分组。")
    if start_ok and available <= 0:
        blockers.append("账号预检没有可用账号，无法进入真实采集/触达。")
    if headless_timeout:
        blockers.append("本地复测在账号预检或采集终态前超时，需检查 ixBrowser 本地服务、账号分组和网络。")
    if errors.get("IXBROWSER_KERNEL_MISMATCH"):
        blockers.append("存在内核不匹配账号，需要把对应配置内核改到 ixBrowser 当前支持版本。")
    if errors.get("PROFILE_START_FAILED"):
        blockers.append("存在配置启动失败，需确认 ixBrowser 本地服务和账号配置可手动打开。")
    if errors.get("LOGIN_REQUIRED"):
        blockers.append("存在未登录账号，需先登录或移入封禁/不可用分组。")
    if errors.get("LOGIN_REQUIRED") and available <= 0:
        blockers.append("当前执行分组没有登录可用账号，自动循环会继续清理未登录账号，但不会进入采集。")
    if batch_failed:
        blockers.append(f"最新批次状态为 {status}，不能作为通过验收证据。")
    if top_source_error and int(batch.get("processed_sources") or 0) <= 0:
        blockers.append(source_error_blocker(top_source_error, profile_group))

    if restarted_after_batch:
        readiness = "pending_new_run"
    elif batch_completed and collection_done and action_started and not preflight_stale and profile_list_execution_evidence:
        readiness = "pass"
    elif batch_failed and collection_done and action_started and available > 0:
        readiness = "partial"
    elif refresh_summary.get("empty"):
        readiness = "blocked_by_environment"
    elif headless_timeout:
        readiness = "blocked_by_environment"
    elif preflight_stale:
        readiness = "blocked_by_environment"
    elif plan_ok and start_ok and available > 0:
        readiness = "partial"
    elif plan_ok and start_ok:
        readiness = "blocked_by_accounts"
    else:
        readiness = "not_started"

    next_actions = []
    if readiness == "pass":
        blockers = []
        next_actions.append("已达到客户端验收：目标识别、账号跳过、采集、触达和批次收口均有证据。")
    elif readiness == "pending_new_run":
        next_actions.append("当前客户端已加载新版本，请重新点击开始获客，等待生成新批次后再验收采集和触达链路。")
    elif refresh_summary.get("empty"):
        next_actions.append(f"确认 ixBrowser 本地服务已启动，并且 {profile_group} 分组至少包含 1 个配置；当前刷新结果为 groups=0/profiles=0。")
    elif headless_timeout:
        next_actions.append("先确认 ixBrowser 本地服务已启动，United States 分组可读取，至少 1 个账号能手动打开 TikTok，再运行真实执行复测。")
    elif available <= 0:
        next_actions.append(f"先在 ixBrowser 手动打开 {profile_group} 中至少 1 个账号，确认 TikTok 已登录且内核版本匹配。")
    if readiness != "pass" and errors.get("IXBROWSER_KERNEL_MISMATCH"):
        ids = profile_error_summary.get("IXBROWSER_KERNEL_MISMATCH", {}).get("profile_ids") or []
        suffix = f" 本批次账号: {','.join(ids[:12])}" if ids else ""
        next_actions.append(f"批量筛出 IXBROWSER_KERNEL_MISMATCH 账号，修改内核版本或移出执行分组。{suffix}")
    if readiness != "pass" and errors.get("PROFILE_START_FAILED"):
        ids = profile_error_summary.get("PROFILE_START_FAILED", {}).get("profile_ids") or []
        suffix = f" 本批次账号: {','.join(ids[:12])}" if ids else ""
        next_actions.append(f"降低并发后重新执行；若仍失败，重启 ixBrowser 本地服务并手动验证配置可打开。{suffix}")
    if readiness != "pass" and errors.get("LOGIN_REQUIRED") and available <= 0:
        ids = profile_error_summary.get("LOGIN_REQUIRED", {}).get("profile_ids") or []
        suffix = f" 最近未登录账号: {','.join(ids[:12])}" if ids else ""
        next_actions.append(f"向 {profile_group} 补充至少 1 个已登录 TikTok 的可用账号；系统已将未登录账号移入封禁账号分组。{suffix}")
    if readiness != "pass" and top_source_error:
        next_actions.append(source_error_next_action(top_source_error, profile_group))
    if not next_actions:
        next_actions.append("重新点击开始获客，观察是否出现 DONE collection 和 START action_*。")

    return {
        "readiness": readiness,
        "batch_status": status,
        "checks": {
            "target_planned": plan_ok,
            "product_auto_detected": product_auto_ok,
            "campaign_started": start_ok,
            "profile_available_count": available,
            "profile_preflight_fresh": not preflight_stale,
            "ixbrowser_group_refresh_seen": bool(refresh_summary.get("seen")),
            "ixbrowser_group_list_empty": bool(refresh_summary.get("empty")),
            "profile_list_evidence_seen": profile_list_evidence_seen,
            "profile_candidates_loaded_from_selected_group": profile_candidates_loaded,
            "selected_profiles_candidate_count": int(selected_summary.get("candidates") or 0),
            "account_queue_started_for_selected_group": account_queue_started,
            "profile_list_execution_evidence": profile_list_execution_evidence,
            "collection_done": collection_done,
            "action_started": action_started,
            "runtime_restarted_after_latest_batch": restarted_after_batch,
        },
        "execution_context": {
            "detected_type": (quick_send or {}).get("detected_type", ""),
            "mode": (quick_send or {}).get("mode_label", ""),
            "volume": (quick_send or {}).get("volume", ""),
            "planned_source_count": len(planned_sources or []),
            "planned_sources": [
                f"{row.get('source_type', '')}:{row.get('source_value', '')}"
                for row in (planned_sources or [])[:8]
                if isinstance(row, dict)
            ],
            "max_videos_per_creator": batch_config.get("max_videos_per_creator", ""),
            "max_comments_per_video": batch_config.get("max_comments_per_video", ""),
        },
        "blockers": blockers,
        "next_actions": next_actions,
        "profile_error_summary": profile_error_summary,
        "profile_preflight_details": profile_details,
        "profile_preflight_summary": effective_preflight,
        "ixbrowser_refresh_summary": refresh_summary,
        "selected_profile_summary": selected_summary,
        "source_failure_summary": source_failure_summary,
        "top_source_error": top_source_error,
        "scoped_log_lines": len(scoped_lines),
    }


def parse_json(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_utc_datetime(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def profile_preflight_is_stale(batch: dict, preflight: dict) -> bool:
    batch_created = parse_utc_datetime(str(batch.get("created_at") or ""))
    preflight_created = parse_utc_datetime(str(preflight.get("created_at") or ""))
    if not batch_created or not preflight_created:
        return False
    return preflight_created < batch_created


def scope_log_lines(batch: dict, log_lines: list[str]) -> list[str]:
    batch_id = str(batch.get("id") or "")
    campaign_id = str(batch.get("campaign_id") or "")
    if not batch_id and not campaign_id:
        return list(log_lines)
    candidates: list[int] = []
    for index, line in enumerate(log_lines):
        if batch_id and batch_id in line:
            candidates.append(index)
        if campaign_id and campaign_id in line and ("PLAN   campaign" in line or "START  campaign" in line):
            candidates.append(index)
    if not candidates:
        return list(log_lines)
    # The headless and Web flows refresh ixBrowser groups before the batch id exists.
    # Keep a short prelude so the selected-group evidence is not scoped away.
    start_index = max(0, min(candidates) - 20)
    return log_lines[start_index:]


PROFILE_DETAIL_RE = re.compile(
    r"profile=(?P<profile>\S+)\s+status=(?P<status>\S+)\s+error=(?P<error>\S+)\s+"
    r"evidence=(?P<evidence>\S+)"
    r"(?:\s+close_action=(?P<close_action>\S+)\s+operator_hint=(?P<operator_hint>.*?))?"
    r"\s+"
    r"message=(?P<message>.*)$"
)
REFRESH_GROUPS_RE = re.compile(r"CONFIG refresh_profiles groups_loaded groups=(?P<groups>\d+)\s+profiles=(?P<profiles>\d+|deferred)")
SELECTED_PROFILES_RE = re.compile(
    r"CONFIG selected_profiles group=(?P<group>.*?)\s+requested=(?P<requested>\d+)\s+"
    r"candidates=(?P<candidates>\d+)\s+selected=(?P<selected>\d+)"
)
PREFLIGHT_SUMMARY_RE = re.compile(
    r"CHECK\s+profile_preflight\s+checked=(?P<checked>\d+)\s+"
    r"available=(?P<available>\d+)\s+unavailable=(?P<unavailable>\d+)\s+"
    r"errors=(?P<errors>.*)$"
)
SOURCE_FAILED_RE = re.compile(
    r"SOURCE\s+failed\s+batch=(?P<batch>\S+)\s+"
    r"type=(?P<source_type>\S*)\s+value=(?P<source_value>.*?)\s+"
    r"error=(?P<error>\S+)(?:\s+message=(?P<message>.*))?$"
)


def extract_profile_preflight_summary(log_lines: list[str]) -> dict:
    latest: dict = {}
    for line in log_lines:
        match = PREFLIGHT_SUMMARY_RE.search(line)
        if not match:
            continue
        checked = int(match.group("checked") or 0)
        if latest and checked < int(latest.get("checked") or 0):
            continue
        latest = {
            "checked": checked,
            "available": int(match.group("available") or 0),
            "unavailable": int(match.group("unavailable") or 0),
            "errors": parse_error_counts(match.group("errors") or ""),
        }
    return latest


def parse_error_counts(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text or text == "无":
        return {}
    errors: dict[str, int] = {}
    for item in text.split(","):
        token = item.strip()
        if not token or "=" not in token:
            continue
        key, value = token.rsplit("=", 1)
        key = key.strip()
        try:
            count = int(value.strip())
        except Exception:
            continue
        if key:
            errors[key] = count
    return errors


def extract_profile_preflight_details(log_lines: list[str]) -> list[dict]:
    details = []
    for line in log_lines:
        if "CHECK  profile_preflight_detail" not in line or "profile=" not in line:
            continue
        match = PROFILE_DETAIL_RE.search(line)
        if not match:
            continue
        details.append(
            {
                "profile_id": match.group("profile"),
                "status": match.group("status"),
                "error": match.group("error"),
                "evidence": "" if match.group("evidence") == "-" else match.group("evidence"),
                "close_action": match.group("close_action") or "",
                "operator_hint": (match.group("operator_hint") or "").strip(),
                "message": match.group("message").strip(),
            }
        )
    return details


def extract_source_failures(log_lines: list[str], batch_id: str = "") -> list[dict]:
    failures = []
    expected_batch = str(batch_id or "").strip()
    for line in log_lines:
        if "SOURCE failed" not in line:
            continue
        match = SOURCE_FAILED_RE.search(line)
        if not match:
            continue
        if expected_batch and str(match.group("batch") or "") != expected_batch:
            continue
        failures.append(
            {
                "batch_id": match.group("batch"),
                "source_type": match.group("source_type"),
                "source_value": match.group("source_value").strip(),
                "error": match.group("error"),
                "message": (match.group("message") or "").strip(),
            }
        )
    return failures


def summarize_profile_errors(details: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for item in details:
        error = str(item.get("error") or "UNKNOWN")
        bucket = summary.setdefault(error, {"count": 0, "profile_ids": [], "sample_message": ""})
        bucket["count"] += 1
        profile_id = str(item.get("profile_id") or "")
        if profile_id and profile_id not in bucket["profile_ids"]:
            bucket["profile_ids"].append(profile_id)
        if not bucket["sample_message"] and item.get("message"):
            bucket["sample_message"] = str(item.get("message") or "")[:220]
    return summary


def summarize_source_failures(failures: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for item in failures or []:
        error = str(item.get("error") or "UNKNOWN").strip() or "UNKNOWN"
        bucket = summary.setdefault(error, {"count": 0, "sources": [], "sample_message": ""})
        bucket["count"] += 1
        source = f"{item.get('source_type', '')}:{item.get('source_value', '')}".strip(":")
        if source and source not in bucket["sources"]:
            bucket["sources"].append(source)
        if not bucket["sample_message"] and item.get("message"):
            bucket["sample_message"] = str(item.get("message") or "")[:220]
    return summary


def top_error_code(summary: dict) -> str:
    if not summary:
        return ""
    return sorted(summary.items(), key=lambda item: (-int((item[1] or {}).get("count") or 0), item[0]))[0][0]


def source_error_blocker(error_code: str, profile_group: str) -> str:
    if error_code == "URL_MISMATCH_DISCARDED":
        return "目标链接打开后跳转到其他 TikTok 视频，系统已丢弃不匹配评论，避免采集错误客户。"
    if error_code in {"LOGIN_REQUIRED", "COMMENT_ACCESS_GATED"}:
        return f"{profile_group} 分组账号无法读取该目标评论区，当前账号登录态或评论权限不足。"
    if error_code in {"BROWSER_CRASHED", "PLATFORM_TEMPORARY_ERROR"}:
        return "TikTok 页面或浏览器临时异常导致本轮 source 失败，需要换账号或稍后重试。"
    if error_code in {"COMMENT_SCAN_EMPTY", "COMMENT_USERS_EMPTY_RETRY", "EMPTY_RESULT_RETRY"}:
        return "目标评论区未采集到可用用户，系统没有生成线索和触达动作。"
    return f"采集 source 失败：{error_code}。"


def source_error_next_action(error_code: str, profile_group: str) -> str:
    if error_code == "URL_MISMATCH_DISCARDED":
        return "更换一个能稳定直达评论区的 TikTok 视频链接，或用达人主页/关键词作为采集目标；当前链接会跳到其他视频。"
    if error_code in {"LOGIN_REQUIRED", "COMMENT_ACCESS_GATED"}:
        return f"在 ixBrowser 手动打开 {profile_group} 中的可用账号，确认该账号能看到目标视频评论区，再重新开始获客。"
    if error_code in {"BROWSER_CRASHED", "PLATFORM_TEMPORARY_ERROR"}:
        return "降低并发到 1，等待页面恢复后重试；连续失败时换同分组账号执行。"
    if error_code in {"COMMENT_SCAN_EMPTY", "COMMENT_USERS_EMPTY_RETRY", "EMPTY_RESULT_RETRY"}:
        return "更换有公开评论和互动用户的 TikTok 视频/达人，当前目标没有产出可触达线索。"
    return f"按采集错误 {error_code} 排查目标链接、账号登录态和页面加载稳定性。"


def _line_group_matches(line_group: str, profile_group: str) -> bool:
    current = str(line_group or "").strip()
    wanted = str(profile_group or "").strip()
    if not wanted:
        return current in {"", "全部", "全部配置"}
    return current.lower() == wanted.lower()


def profile_refresh_summary(log_lines: list[str]) -> dict:
    latest = {"seen": False, "groups": None, "profiles": None, "profiles_deferred": False}
    for line in log_lines:
        match = REFRESH_GROUPS_RE.search(line)
        if not match:
            continue
        latest["seen"] = True
        latest["groups"] = int(match.group("groups") or 0)
        profiles_raw = match.group("profiles")
        latest["profiles_deferred"] = profiles_raw == "deferred"
        latest["profiles"] = None if profiles_raw == "deferred" else int(profiles_raw or 0)
    latest["empty"] = bool(
        latest["seen"]
        and int(latest["groups"] or 0) == 0
        and not latest["profiles_deferred"]
        and int(latest["profiles"] or 0) == 0
    )
    return latest


def selected_profile_summary(log_lines: list[str], profile_group: str) -> dict:
    latest = {"seen": False, "candidates": 0, "selected": 0}
    for line in log_lines:
        match = SELECTED_PROFILES_RE.search(line)
        if not match:
            continue
        if not _line_group_matches(match.group("group"), profile_group):
            continue
        latest = {
            "seen": True,
            "candidates": int(match.group("candidates") or 0),
            "selected": int(match.group("selected") or 0),
        }
    return latest


def recommended_profile_action(error_code: str) -> str:
    error = str(error_code or "")
    if error == "IXBROWSER_KERNEL_MISMATCH":
        return "在 ixBrowser 中把该配置内核改为当前客户端支持版本，或移出执行分组。"
    if error == "PROFILE_START_FAILED":
        return "在 ixBrowser 手动打开该配置，确认本地服务、代理和配置可启动；失败则移出执行分组。"
    if error == "LOGIN_REQUIRED":
        return "打开配置完成 TikTok 登录；无法登录则移入封禁/不可用分组。"
    if error == "IXBROWSER_NETWORK_ERROR":
        return "检查该配置代理网络，能打开 TikTok 后再放回执行分组。"
    if error == "PROFILE_PREFLIGHT_TIMEOUT":
        return "手动打开该配置确认页面加载速度，必要时降低并发或移出本轮执行。"
    return "手动打开该配置确认 TikTok 可用；不可用则移出本轮执行分组。"


def remediation_error_priority(error_code: str) -> int:
    order = {
        "IXBROWSER_KERNEL_MISMATCH": 0,
        "LOGIN_REQUIRED": 1,
        "CAPTCHA_DETECTED": 2,
        "PROXY_FAILED": 3,
        "PROFILE_START_FAILED": 4,
        "IXBROWSER_NETWORK_ERROR": 5,
        "PROFILE_PREFLIGHT_TIMEOUT": 6,
    }
    return order.get(str(error_code or ""), 9)


def dedupe_profile_remediation_details(details: list[dict]) -> list[dict]:
    by_profile: dict[str, dict] = {}
    order: list[str] = []
    for index, item in enumerate(details or []):
        profile_id = str(item.get("profile_id") or "").strip()
        if not profile_id:
            continue
        row = dict(item)
        row["_order"] = index
        if profile_id not in by_profile:
            by_profile[profile_id] = row
            order.append(profile_id)
            continue
        old = by_profile[profile_id]
        old_key = (remediation_error_priority(str(old.get("error") or "")), -int(old.get("_order") or 0))
        new_key = (remediation_error_priority(str(row.get("error") or "")), -index)
        if new_key < old_key:
            by_profile[profile_id] = row
    return [{key: value for key, value in by_profile[profile_id].items() if key != "_order"} for profile_id in order]


def build_account_repair_plan(batch: dict, details: list[dict], preflight_errors: dict | None = None) -> dict:
    groups: dict[str, dict] = {}
    for item in details or []:
        profile_id = str(item.get("profile_id") or "").strip()
        error = str(item.get("error") or "UNKNOWN").strip() or "UNKNOWN"
        if not profile_id:
            continue
        bucket = groups.setdefault(
            error,
            {
                "error": error,
                "count": 0,
                "profile_ids": [],
                "recommended_action": recommended_profile_action(error),
                "sample_message": "",
                "evidence_files": [],
            },
        )
        if profile_id not in bucket["profile_ids"]:
            bucket["profile_ids"].append(profile_id)
            bucket["count"] = len(bucket["profile_ids"])
        if not bucket["sample_message"] and item.get("message"):
            bucket["sample_message"] = str(item.get("message") or "")[:300]
        evidence = str(item.get("evidence") or "").strip()
        if evidence and evidence not in bucket["evidence_files"]:
            bucket["evidence_files"].append(evidence)
    for error, count in (preflight_errors or {}).items():
        error_key = str(error or "UNKNOWN").strip() or "UNKNOWN"
        bucket = groups.setdefault(
            error_key,
            {
                "error": error_key,
                "count": 0,
                "profile_ids": [],
                "recommended_action": recommended_profile_action(error_key),
                "sample_message": "",
                "evidence_files": [],
            },
        )
        summary_count = int(count or 0)
        if summary_count > int(bucket.get("count") or 0):
            bucket["count"] = summary_count
            bucket["count_source"] = "profile_preflight_summary"
        else:
            bucket.setdefault("count_source", "profile_preflight_detail")
    ordered = sorted(groups.values(), key=lambda row: (remediation_error_priority(row["error"]), row["error"]))
    return {
        "batch_id": str(batch.get("id") or ""),
        "batch_status": str(batch.get("status") or ""),
        "profile_group": str(batch.get("profile_group") or ""),
        "total_unique_profiles_by_error": sum(int(row.get("count") or 0) for row in ordered),
        "groups": ordered,
        "operator_steps": [
            "先处理 IXBROWSER_KERNEL_MISMATCH：把对应配置内核改为 ixBrowser 当前支持版本 138，或移出执行分组。",
            "再处理 LOGIN_REQUIRED：手动打开配置完成 TikTok 登录；无法登录则移入封禁/不可用分组。",
            "最后处理 PROFILE_PREFLIGHT_TIMEOUT/PAGE_OPEN_FAILED：确认代理和 TikTok 页面加载稳定，必要时降低并发或移出本轮执行。",
            "至少保留 1 个已登录、内核匹配、可手动打开 TikTok 的账号在执行分组内，再复跑开始获客。",
        ],
        "acceptance_after_repair": [
            "reachops_client_delivery_check.py --json 返回 status=passed。",
            "profile_available>=1。",
            "目标模式报告 local_mvp_ready=true。",
        ],
    }


def render_account_repair_plan_markdown(plan: dict, json_path: Path) -> str:
    lines = [
        "# ReachOps 账号修复计划",
        "",
        f"- 批次: `{plan.get('batch_id') or '-'}`",
        f"- 状态: `{plan.get('batch_status') or '-'}`",
        f"- 分组: `{plan.get('profile_group') or '-'}`",
        f"- JSON: `{json_path}`",
        "",
        "## 处理顺序",
        "",
    ]
    for step in plan.get("operator_steps") or []:
        lines.append(f"- {step}")
    lines.extend(["", "## 错误分组", "", "| error | count | profile_ids | 处理动作 |", "| --- | ---: | --- | --- |"])
    for row in plan.get("groups") or []:
        profile_ids = ", ".join(f"`{item}`" for item in (row.get("profile_ids") or []))
        lines.append(
            f"| `{row.get('error') or ''}` | {int(row.get('count') or 0)} | {profile_ids} | {row.get('recommended_action') or ''} |"
        )
    lines.extend(["", "## 修复后复测标准", ""])
    for item in plan.get("acceptance_after_repair") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_remediation_report(
    base_dir: Path,
    batch: dict,
    details: list[dict],
    preflight_errors: dict | None = None,
) -> dict:
    if not details:
        return {}
    report_dir = base_dir / "reports" / REMEDIATION_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    batch_id = str(batch.get("id") or "latest")
    csv_path = report_dir / f"{batch_id}_profile_remediation.csv"
    json_path = report_dir / f"{batch_id}_profile_remediation.json"
    md_path = report_dir / f"{batch_id}_acceptance_report.md"
    guide_path = report_dir / f"{batch_id}_client_acceptance_guide.md"
    index_path = report_dir / f"{batch_id}_acceptance_index.html"
    account_plan_json_path = report_dir / f"{batch_id}_account_repair_plan.json"
    account_plan_md_path = report_dir / f"{batch_id}_account_repair_plan.md"
    rows = []
    deduped_details = dedupe_profile_remediation_details(details)
    for item in deduped_details:
        row = {
            "batch_id": batch_id,
            "profile_group": str(batch.get("profile_group") or ""),
            "profile_id": str(item.get("profile_id") or ""),
            "status": str(item.get("status") or ""),
            "error": str(item.get("error") or ""),
            "recommended_action": recommended_profile_action(str(item.get("error") or "")),
            "evidence": str(item.get("evidence") or ""),
            "message": str(item.get("message") or ""),
        }
        rows.append(row)
    account_plan = build_account_repair_plan(batch, details, preflight_errors=preflight_errors)
    account_plan_json_path.write_text(json.dumps(account_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    account_plan_md_path.write_text(
        render_account_repair_plan_markdown(account_plan, account_plan_json_path),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "batch_id",
                "profile_group",
                "profile_id",
                "status",
                "error",
                "recommended_action",
                "evidence",
                "message",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        build_acceptance_markdown(batch, rows, csv_path, json_path),
        encoding="utf-8",
    )
    latest_csv_path = report_dir / "latest_profile_remediation.csv"
    latest_json_path = report_dir / "latest_profile_remediation.json"
    latest_markdown_path = report_dir / "latest_acceptance_report.md"
    latest_account_plan_json_path = report_dir / "latest_account_repair_plan.json"
    latest_account_plan_md_path = report_dir / "latest_account_repair_plan.md"
    guide_path.write_text(
        build_client_acceptance_guide(
            batch,
            rows,
            csv_path,
            json_path,
            md_path,
            account_plan_md_path=account_plan_md_path,
            account_plan_json_path=account_plan_json_path,
            latest_account_plan_md_path=latest_account_plan_md_path,
            latest_account_plan_json_path=latest_account_plan_json_path,
            latest_csv_path=latest_csv_path,
            latest_json_path=latest_json_path,
            latest_markdown_path=latest_markdown_path,
        ),
        encoding="utf-8",
    )
    index_path.write_text(
        build_acceptance_index_html(batch, rows, csv_path, json_path, md_path, guide_path, account_plan_md_path),
        encoding="utf-8",
    )
    manifest_path = report_dir / f"{batch_id}_acceptance_manifest.json"
    manifest = build_acceptance_manifest(
        batch,
        rows,
        csv_path,
        json_path,
        md_path,
        guide_path,
        index_path,
        account_plan_md_path=account_plan_md_path,
        account_plan_json_path=account_plan_json_path,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_manifest_path = report_dir / "latest_acceptance_manifest.json"
    latest_guide_path = report_dir / "latest_client_acceptance_guide.md"
    latest_index_path = report_dir / "latest_acceptance_index.html"
    latest_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_markdown_path.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_account_plan_json_path.write_text(account_plan_json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_account_plan_md_path.write_text(account_plan_md_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_guide_path.write_text(guide_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_index_path.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "guide_path": str(guide_path),
        "index_path": str(index_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(latest_csv_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "account_plan_json_path": str(account_plan_json_path),
        "account_plan_markdown_path": str(account_plan_md_path),
        "latest_account_plan_json_path": str(latest_account_plan_json_path),
        "latest_account_plan_markdown_path": str(latest_account_plan_md_path),
        "latest_manifest_path": str(latest_manifest_path),
        "latest_guide_path": str(latest_guide_path),
        "latest_index_path": str(latest_index_path),
        "count": len(rows),
        "raw_count": len(details or []),
    }


def build_acceptance_manifest(
    batch: dict,
    rows: list[dict],
    csv_path: Path,
    json_path: Path,
    md_path: Path,
    guide_path: Path,
    index_path: Path,
    *,
    account_plan_md_path: Path | None = None,
    account_plan_json_path: Path | None = None,
) -> dict:
    root = ROOT_DIR
    return {
        "batch_id": str(batch.get("id") or ""),
        "batch_status": str(batch.get("status") or ""),
        "profile_group": str(batch.get("profile_group") or ""),
        "readiness": "blocked_by_accounts" if rows else "not_started",
        "client_entrypoints": {
            "local_client_console": str(root / "启动ReachOps本地客户端.command"),
            "web_ui": str(root / "启动ReachOps统一WebUI.command"),
            "unified_mac_client": str(root / "启动ReachOps原生MacUI.command"),
            "native_mac_ui": str(root / "启动ReachOps原生MacUI.command"),
            "account_repair": str(root / "执行ReachOps账号修复.command"),
            "real_retest": str(root / "复测ReachOps真实执行.command"),
        },
        "web_operator_api": {
            "start": "/api/start",
            "control": "/api/control",
            "acceptance": "/api/acceptance",
            "final_status": "/api/final-status",
            "final_status_no_browser_started": True,
            "final_status_no_submit": True,
        },
        "reports": {
            "profile_remediation_csv": str(csv_path),
            "profile_remediation_json": str(json_path),
            "acceptance_markdown": str(md_path),
            "client_acceptance_guide": str(guide_path),
            "acceptance_index_html": str(index_path),
            "account_repair_plan_markdown": str(account_plan_md_path or ""),
            "account_repair_plan_json": str(account_plan_json_path or ""),
        },
        "acceptance_gates": {
            "target_auto_detected_product_url": True,
            "requires_profile_available": "available>=1",
            "requires_collection_done_log": "DONE collection",
            "requires_action_terminal_log": "START/DONE action_preflight or START/DONE action_submit",
        },
        "blocked_profiles": [
            {
                "profile_id": row.get("profile_id", ""),
                "error": row.get("error", ""),
                "recommended_action": row.get("recommended_action", ""),
            }
            for row in rows
        ],
    }


def build_acceptance_markdown(batch: dict, rows: list[dict], csv_path: Path, json_path: Path) -> str:
    batch_id = str(batch.get("id") or "-")
    group = str(batch.get("profile_group") or "-")
    status = str(batch.get("status") or "-")
    lines = [
        "# ReachOps Mac 真实执行验收报告",
        "",
        f"- 最新批次: `{batch_id}`",
        f"- 执行状态: `{status}`",
        f"- 账号分组: `{group}`",
        f"- 阻断类型: `blocked_by_accounts`",
        f"- 修复 CSV: `{csv_path}`",
        f"- 修复 JSON: `{json_path}`",
        "",
        "## 当前结论",
        "",
        "程序已进入真实执行链路并完成推广目标规划，但本批次账号预检没有可用账号，尚不能进入真实采集和触达验收。",
        "",
        "## 需要处理的账号",
        "",
        "| profile_id | error | 建议动作 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('profile_id', '')}` | `{row.get('error', '')}` | {row.get('recommended_action', '')} |"
        )
    lines.extend(
        [
            "",
            "## 复测通过标准",
            "",
            "- United States 分组至少 1 个账号预检 `available>=1`。",
            "- 日志出现 `DONE collection`，证明线索采集完成。",
            "- 日志出现 `START action_preflight` 或 `START action_submit`，证明触达链路进入执行。",
            "- 真实评论模式下，需看到触达结果和证据文件。",
            "",
        ]
    )
    return "\n".join(lines)


def build_acceptance_index_html(
    batch: dict,
    rows: list[dict],
    csv_path: Path,
    json_path: Path,
    md_path: Path,
    guide_path: Path,
    account_plan_md_path: Path | None = None,
) -> str:
    def esc(value: object) -> str:
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    blocked_rows = "\n".join(
        "<tr>"
        f"<td>{esc(row.get('profile_id'))}</td>"
        f"<td>{esc(row.get('error'))}</td>"
        f"<td>{esc(row.get('recommended_action'))}</td>"
        "</tr>"
        for row in rows
    )
    if not blocked_rows:
        blocked_rows = '<tr><td colspan="3">暂无账号阻断明细。</td></tr>'
    root = ROOT_DIR
    account_plan_link = (
        f'<li><a href="{esc(account_plan_md_path.name)}">账号修复计划</a></li>'
        if account_plan_md_path
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>ReachOps 验收包</title>
  <style>
    body {{ margin:0; font:14px -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; color:#202428; background:#f5f7f9; }}
    main {{ max-width:1080px; margin:0 auto; padding:28px; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    h2 {{ margin:24px 0 10px; font-size:16px; }}
    .muted {{ color:#66717d; }}
    .status {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#ffe8e5; color:#a9342b; font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
    .card {{ background:white; border:1px solid #d8dee5; border-radius:8px; padding:14px; }}
    code {{ background:#eef1f4; padding:1px 4px; border-radius:4px; }}
    table {{ width:100%; border-collapse:collapse; background:white; border:1px solid #d8dee5; }}
    th,td {{ border-bottom:1px solid #e4e8ed; padding:9px 10px; text-align:left; vertical-align:top; }}
    th {{ background:#eef1f4; }}
    a {{ color:#1d62d6; text-decoration:none; }}
  </style>
</head>
<body>
<main>
  <h1>ReachOps Mac 真实执行验收包</h1>
  <div class="muted">批次 <code>{esc(batch.get('id') or '-')}</code> / 分组 <code>{esc(batch.get('profile_group') or '-')}</code></div>
  <p><span class="status">当前状态：账号阻断</span></p>

  <h2>当前结论</h2>
  <div class="card">程序已进入真实执行链路并完成推广目标规划，但账号预检没有可用账号，尚不能进入真实采集和触达验收。</div>

  <h2>客户入口</h2>
  <div class="grid">
    <div class="card"><strong>本地客户端控制台</strong><br><code>{esc(root / '启动ReachOps本地客户端.command')}</code></div>
    <div class="card"><strong>兼容启动入口</strong><br><code>{esc(root / '启动ReachOps统一WebUI.command')}</code></div>
    <div class="card"><strong>账号修复</strong><br><code>{esc(root / '执行ReachOps账号修复.command')}</code></div>
    <div class="card"><strong>真实执行复测</strong><br><code>{esc(root / '复测ReachOps真实执行.command')}</code></div>
    <div class="card"><strong>打开验收包</strong><br><code>{esc(root / '打开ReachOps验收包.command')}</code></div>
  </div>

  <h2>需要处理的账号</h2>
  <table>
    <tr><th>profile_id</th><th>错误</th><th>建议动作</th></tr>
    {blocked_rows}
  </table>

  <h2>报告文件</h2>
  <ul>
    <li><a href="{esc(csv_path.name)}">账号修复 CSV</a></li>
    <li><a href="{esc(json_path.name)}">账号修复 JSON</a></li>
    <li><a href="{esc(md_path.name)}">验收报告 Markdown</a></li>
    <li><a href="{esc(guide_path.name)}">客户验收操作指南</a></li>
    {account_plan_link}
  </ul>

  <h2>复测通过标准</h2>
  <ul>
    <li>账号预检 <code>available&gt;=1</code></li>
    <li>日志出现 <code>DONE collection</code></li>
    <li>日志出现 <code>START action_preflight</code> 或 <code>START action_submit</code></li>
    <li>真实评论模式下，需要看到触达结果和证据文件</li>
  </ul>
</main>
</body>
</html>
"""


def build_client_acceptance_guide(
    batch: dict,
    rows: list[dict],
    csv_path: Path,
    json_path: Path,
    md_path: Path,
    *,
    account_plan_md_path: Path | None = None,
    account_plan_json_path: Path | None = None,
    latest_account_plan_md_path: Path | None = None,
    latest_account_plan_json_path: Path | None = None,
    latest_csv_path: Path | None = None,
    latest_json_path: Path | None = None,
    latest_markdown_path: Path | None = None,
) -> str:
    root = ROOT_DIR
    blocked_ids = ", ".join(str(row.get("profile_id") or "") for row in rows if row.get("profile_id")) or "-"
    stable_csv = latest_csv_path or csv_path
    stable_json = latest_json_path or json_path
    stable_md = latest_markdown_path or md_path
    stable_account_plan_md = latest_account_plan_md_path or account_plan_md_path
    stable_account_plan_json = latest_account_plan_json_path or account_plan_json_path
    lines = [
        "# ReachOps Mac 客户验收操作指南",
        "",
        "## 1. 启动客户端",
        "",
        f"- 本地客户端控制台: `{root / '启动ReachOps本地客户端.command'}`",
        f"- 兼容启动入口: `{root / '启动ReachOps统一WebUI.command'}`",
        f"- 统一 Mac 客户端: `{root / '启动ReachOps原生MacUI.command'}`",
        f"- 账号修复: `{root / '执行ReachOps账号修复.command'}`",
        f"- 真实执行复测: `{root / '复测ReachOps真实执行.command'}`",
        "",
        "## 2. 当前阻断",
        "",
        f"- 最新批次: `{batch.get('id') or '-'}`",
        f"- 当前状态: `{batch.get('status') or '-'}`",
        f"- 账号分组: `{batch.get('profile_group') or '-'}`",
        f"- 需要处理的 profile id: `{blocked_ids}`",
        "",
        "## 3. 账号处理步骤",
        "",
        "1. 打开 ixBrowser。",
        "2. 进入 United States 分组。",
        "3. 先处理 `IXBROWSER_KERNEL_MISMATCH`：把配置内核改为当前客户端支持版本 138，或移出执行分组。",
        "4. 再处理 `LOGIN_REQUIRED`：手动打开配置完成 TikTok 登录；无法登录则移入封禁/不可用分组。",
        "5. 最后处理超时或页面打开失败账号：确认代理和 TikTok 页面加载稳定，必要时降低并发或移出本轮执行。",
        "6. 至少保留 1 个可用账号在 United States 分组内。",
        "",
        "## 4. 复测步骤",
        "",
        "1. 双击 `复测ReachOps真实执行.command`。",
        "2. 直接回车执行触达预检；输入 `LIVE` 才会执行真实评论模式。",
        "3. 等待脚本输出新的验收状态和报告。",
        "",
        "## 5. 通过标准",
        "",
        "- 账号预检 `available>=1`。",
        "- 日志出现 `DONE collection`。",
        "- 日志出现 `START action_preflight` 或 `START action_submit`。",
        "- 真实评论模式下，需要看到触达结果和证据文件。",
        "",
        "## 6. 相关文件",
        "",
        f"- 修复 CSV: `{csv_path}`",
        f"- 修复 JSON: `{json_path}`",
        f"- 验收报告: `{md_path}`",
        f"- 固定最新修复 CSV: `{stable_csv}`",
        f"- 固定最新修复 JSON: `{stable_json}`",
        f"- 固定最新验收报告: `{stable_md}`",
        f"- 固定最新账号修复计划: `{stable_account_plan_md or '-'}`",
        f"- 固定最新账号修复计划 JSON: `{stable_account_plan_json or '-'}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize ReachOps client acceptance status from real runtime data.")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write-remediation", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    db_path = base_dir / "data/growth_intelligence/growth_intelligence.db"
    log_path = base_dir / "logs/growth_ops_runtime.log"
    batch = latest_batch(db_path)
    preflight = latest_profile_preflight(db_path)
    log_lines = read_lines(log_path)
    acceptance = derive_acceptance(batch, preflight, log_lines)
    remediation_report = {}
    if not args.no_write_remediation:
        remediation_report = write_remediation_report(
            base_dir,
            batch,
            acceptance.get("profile_preflight_details") or [],
            preflight_errors=(acceptance.get("profile_preflight_summary") or {}).get("errors") or {},
        )
    payload = {
        "db_path": str(db_path),
        "log_path": str(log_path),
        "latest_batch": batch,
        "latest_profile_preflight": {
            "checked": preflight.get("checked", 0),
            "available": preflight.get("available", 0),
            "unavailable": preflight.get("unavailable", 0),
            "errors": preflight.get("errors", {}),
            "created_at": preflight.get("created_at", ""),
        },
        "acceptance": acceptance,
        "remediation_report": remediation_report,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"验收状态: {acceptance['readiness']}")
        print(f"最新批次: {batch.get('id', '-')} status={batch.get('status', '-')}")
        context = acceptance.get("execution_context") or {}
        if context:
            print(
                "执行上下文: "
                f"type={context.get('detected_type') or '-'} "
                f"mode={context.get('mode') or '-'} "
                f"volume={context.get('volume') or '-'} "
                f"sources={context.get('planned_source_count', 0)} "
                f"range={context.get('max_videos_per_creator')}/{context.get('max_comments_per_video')}"
            )
        print(f"账号预检: checked={preflight.get('checked', 0)} available={preflight.get('available', 0)} errors={preflight.get('errors', {})}")
        summary = acceptance.get("profile_error_summary") or {}
        for error, item in summary.items():
            ids = ",".join((item.get("profile_ids") or [])[:16])
            print(f"账号修复: error={error} count={item.get('count', 0)} profiles={ids or '-'}")
        if remediation_report:
            print(
                "账号修复文件: "
                f"csv={remediation_report.get('csv_path')} "
                f"json={remediation_report.get('json_path')} "
                f"markdown={remediation_report.get('markdown_path')} "
                f"guide={remediation_report.get('guide_path')} "
                f"index={remediation_report.get('index_path')} "
                f"manifest={remediation_report.get('manifest_path')} "
                f"latest_csv={remediation_report.get('latest_csv_path')} "
                f"latest_json={remediation_report.get('latest_json_path')} "
                f"latest_markdown={remediation_report.get('latest_markdown_path')} "
                f"latest_guide={remediation_report.get('latest_guide_path')} "
                f"latest_index={remediation_report.get('latest_index_path')} "
                f"latest_manifest={remediation_report.get('latest_manifest_path')}"
            )
        for item in acceptance["blockers"]:
            print(f"阻断: {item}")
        for item in acceptance["next_actions"]:
            print(f"下一步: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
