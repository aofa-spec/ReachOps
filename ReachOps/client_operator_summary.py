# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any


ACCOUNT_BLOCKERS = {
    "BLOCKED_BY_ACCOUNTS",
    "INSUFFICIENT_LOGGED_IN_PROFILES",
    "NO_LOGGED_IN_PROFILE_AVAILABLE",
    "NO_PROFILE_SELECTED",
}

ACCOUNT_ATTENTION_ERRORS = {
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "ACCOUNT_RESTRICTED",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tail_text(result: dict[str, Any]) -> str:
    tail = result.get("tail")
    if isinstance(tail, list):
        return "\n".join(_text(item) for item in tail[-40:])
    return _text(tail)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _first_int(text: str, patterns: list[str]) -> int:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _int_value(match.group(1))
    return 0


def _max_int(text: str, pattern: str) -> int:
    values = [_int_value(match) for match in re.findall(pattern, text)]
    return max(values) if values else 0


def _runtime_errors(text: str) -> dict[str, int]:
    errors: dict[str, int] = {}
    for segment in re.findall(r"errors=([^\n]+)", text):
        for code, count in re.findall(r"([A-Z][A-Z0-9_]+)=(\d+)", segment):
            errors[code] = max(errors.get(code, 0), _int_value(count))
    return errors


def _runtime_counts(result: dict[str, Any], evidence_text: str) -> dict[str, Any]:
    no_submit = bool(result.get("no_submit", True))
    if re.search(r"\bno_submit=false\b", evidence_text, flags=re.IGNORECASE):
        no_submit = False
    elif re.search(r"\bno_submit=true\b", evidence_text, flags=re.IGNORECASE):
        no_submit = True

    action_success = _int_value(result.get("action_success")) or _first_int(
        evidence_text,
        [r"\b(?:DONE\s+action_preflight|FAST\s+acceptance)[^\n]*\bsuccess=(\d+)"],
    )
    action_failed = _int_value(result.get("action_failed")) or _first_int(
        evidence_text,
        [r"\b(?:DONE\s+action_preflight|FAST\s+acceptance)[^\n]*\bfailed=(\d+)"],
    )
    action_skipped = _int_value(result.get("action_skipped")) or _first_int(
        evidence_text,
        [r"\b(?:DONE\s+action_preflight|FAST\s+acceptance)[^\n]*\bskipped=(\d+)"],
    )
    action_switched = _int_value(result.get("action_switched")) or _int_value(result.get("account_switched")) or _first_int(
        evidence_text,
        [r"\bDONE\s+action_preflight[^\n]*\bswitched=(\d+)"],
    )
    action_total = _int_value(result.get("actions")) or _first_int(
        evidence_text,
        [
            r"\bFAST\s+acceptance[^\n]*\bactions=(\d+)",
            r"\bDONE\s+action_preflight[^\n]*\bselected=(\d+)",
        ],
    )
    if not action_total:
        action_total = action_success + action_failed + action_skipped

    return {
        "no_submit": no_submit,
        "used_profiles": _int_value(result.get("used_profiles") or result.get("available_profiles"))
        or _first_int(evidence_text, [r"\bcollection_result[^\n]*\bused_profiles=(\d+)"]),
        "processed_sources": _int_value(result.get("processed_sources"))
        or _first_int(evidence_text, [r"\bcollection_result[^\n]*\bprocessed_sources=(\d+)"]),
        "failed_sources": _int_value(result.get("failed_sources"))
        or _first_int(evidence_text, [r"\bcollection_result[^\n]*\bfailed_sources=(\d+)"]),
        "profile_checked": _int_value(result.get("profile_checked"))
        or _max_int(evidence_text, r"\bprofile_preflight[^\n]*\bchecked=(\d+)"),
        "profile_available": _int_value(result.get("profile_available"))
        or _max_int(evidence_text, r"\bprofile_preflight[^\n]*\bavailable=(\d+)"),
        "profile_unavailable": _int_value(result.get("profile_unavailable"))
        or _max_int(evidence_text, r"\bprofile_preflight[^\n]*\bunavailable=(\d+)"),
        "action_total": action_total,
        "action_success": action_success,
        "action_failed": action_failed,
        "action_skipped": action_skipped,
        "action_switched": action_switched,
        "runtime_errors": _runtime_errors(evidence_text),
    }


def build_client_operator_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Translate runtime result details into customer-facing M3 operating language."""

    status = _text(result.get("status") or "unknown")
    error_code = _text(result.get("error_code") or result.get("error"))
    terminal_line = _text(result.get("terminal_line") or result.get("last_stage"))
    evidence_text = "\n".join([terminal_line, _tail_text(result)])
    counts = _runtime_counts(result, evidence_text)
    no_submit = bool(counts["no_submit"])
    used_profiles = int(counts["used_profiles"] or 0)
    processed_sources = int(counts["processed_sources"] or 0)
    failed_sources = int(counts["failed_sources"] or 0)
    actions = int(counts["action_total"] or 0)
    action_success = int(counts["action_success"] or 0)
    action_failed = int(counts["action_failed"] or 0)
    action_skipped = int(counts["action_skipped"] or 0)
    action_switched = int(counts["action_switched"] or 0)
    runtime_errors = dict(counts["runtime_errors"] or {})
    account_attention = bool(ACCOUNT_ATTENTION_ERRORS.intersection(runtime_errors)) or error_code in ACCOUNT_ATTENTION_ERRORS

    customer_state = "needs_review"
    title = "本轮获客预检需要复核"
    message = "系统已安全收口，未提交真实互动。"
    next_actions = ["查看本轮运营报告和账号预检结果，再决定是否更换目标或账号分组。"]

    if not no_submit:
        customer_state = "authorization_required"
        title = "真实提交路径需要授权复核"
        message = "本轮结果包含真实提交路径标记，必须复核授权、激活和风控证据。"
        next_actions = ["暂停进入 M4/M5，先确认授权目标、激活状态和提交证据。"]
    elif status == "stopped":
        customer_state = "stopped"
        title = "本轮已停止"
        message = "用户停止了当前任务，系统应释放浏览器和子进程并保留已生成证据。"
        next_actions = ["确认运行时清理结果为 completed 或无残留后，再重新开始获客。"]
    elif error_code in ACCOUNT_BLOCKERS or "可用账号不足" in evidence_text or "没有可用账号" in evidence_text:
        customer_state = "blocked_by_accounts"
        title = "账号池不足，已停止消耗账号"
        message = "系统没有找到足够已登录且可打开 TikTok 的账号，已停止本轮获客。"
        next_actions = ["在当前分组保留至少 3 个已登录可用账号，然后重新执行一次低损耗 M3 预检。"]
    elif status in {"timeout_finalized", "blocked"} or error_code in {"HEADLESS_TIMEOUT", "CAMPAIGN_BLOCKED"}:
        customer_state = "blocked"
        title = "本轮未形成稳定终态"
        message = "系统已停止继续重试，避免无限打开页面或消耗账号。"
        next_actions = ["查看阻断原因；优先处理 ixBrowser、本地网络、页面状态或账号登录态。"]
    elif "duplicate_suppressed" in evidence_text:
        customer_state = "completed_no_duplicate"
        title = "目标已采集过，已跳过重复触达"
        message = "系统识别到同一目标已有候选、线索或动作证据，本轮保持 no-submit 并停止重复消耗账号。"
        next_actions = ["如需继续获客，请更换新目标、关键词、达人主页或视频链接。"]
    elif "no_candidates" in evidence_text or "content_found_no_comments" in evidence_text:
        customer_state = "completed_no_candidates"
        title = "已打开真实页面，但本轮没有有效候选用户"
        message = "系统完成真实页面检查并安全收口，没有生成触达动作。"
        next_actions = ["更换更相关的视频、达人主页或关键词；不要对同一目标反复高频重试。"]
    elif status in {"completed", "degraded"}:
        if account_attention or action_failed > 0:
            customer_state = "completed_with_account_attention"
            title = "本轮获客预检已完成，部分账号需处理"
            message = (
                f"系统使用 {used_profiles or '可用'} 个账号完成真实采集，处理来源 {processed_sources} 个"
                f"（来源失败 {failed_sources} 个）；no-submit 触达预检 {actions} 个动作，"
                f"成功 {action_success} 个、失败 {action_failed} 个、跳过 {action_skipped} 个、切号 {action_switched} 次。"
            )
            next_actions = ["先处理掉登录态、验证码或账号受限账号；通过低损耗 M3 复测后再进入 M4/M5。"]
        else:
            customer_state = "completed" if status == "completed" else "completed_with_notes"
            title = "本轮获客预检已完成"
            message = (
                f"系统使用 {used_profiles or '可用'} 个账号完成真实采集，处理来源 {processed_sources} 个；"
                f"no-submit 触达预检 {actions} 个动作，成功 {action_success} 个、跳过 {action_skipped} 个。"
            )
            next_actions = ["查看线索池和触达建议；进入 M4/M5 前必须完成授权和激活门禁。"]

    return {
        "schema_version": "reachops.client_operator_summary.v1",
        "scope": "m3_real_no_submit_operating_flow",
        "customer_state": customer_state,
        "title": title,
        "message": message,
        "next_actions": next_actions,
        "no_submit": no_submit,
        "account_resource_policy": {
            "low_waste_operation": True,
            "repeat_target_protection": True,
            "stop_before_unbounded_retry": True,
        },
        "technical_reference": {
            "status": status,
            "error_code": error_code,
            "terminal_line": terminal_line,
            "runtime_counts": counts,
        },
    }


def attach_client_operator_summary(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result or {})
    payload["client_operator_summary"] = build_client_operator_summary(payload)
    return payload
