# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "reachops.p08_failure_matrix.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path) -> dict[str, Any]:
    if not path:
        return {}
    target = Path(path).expanduser()
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    if not path:
        return []
    target = Path(path).expanduser()
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def pressure_terminal_status(row: dict[str, Any]) -> str:
    if int(row.get("rc") or 0) == 0 and str(row.get("acceptance_status") or "") == "passed":
        return "passed"
    if int(row.get("rc") or 0) == 2 and str(row.get("acceptance_status") or "") == "blocked":
        if row.get("structured_terminal") is True or row.get("scenario_summaries"):
            return "degraded_terminal"
    return "failed"


def summarize_pressure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    terminal_counts = Counter(pressure_terminal_status(row) for row in rows)
    diagnosis_counts: Counter[str] = Counter()
    no_action_codes: Counter[str] = Counter()
    attempted_profiles: set[str] = set()
    usable_profiles: set[str] = set()
    blocked_profiles: set[str] = set()
    leads = actions = comment_users = auto_expansions = 0
    daily_counts: dict[str, int] = {}
    for row in rows:
        auto_expansions += int(row.get("auto_expansions") or 0)
        usable_profiles.update(str(item) for item in (row.get("usable_profile_ids") or []) if str(item))
        blocked_profiles.update(str(item) for item in (row.get("blocked_profile_ids") or []) if str(item))
        for profile_id, count in (row.get("daily_counts") or {}).items():
            daily_counts[str(profile_id)] = max(int(daily_counts.get(str(profile_id), 0) or 0), int(count or 0))
        for scenario in row.get("scenario_summaries") or []:
            if not isinstance(scenario, dict):
                continue
            diagnosis_counts[str(scenario.get("diagnosis_status") or "unknown")] += 1
            no_action = scenario.get("no_action_reason")
            if isinstance(no_action, dict) and no_action.get("code"):
                no_action_codes[str(no_action.get("code"))] += 1
            funnel = scenario.get("funnel") if isinstance(scenario.get("funnel"), dict) else {}
            leads += int(funnel.get("customer_leads") or 0)
            actions += int(funnel.get("outreach_actions") or 0)
            comment_users += int(funnel.get("comment_users") or 0)
            for group in scenario.get("attempted_profiles") or []:
                attempted_profiles.update(str(item) for item in (group or []) if str(item))
    terminal_total = int(sum(terminal_counts.values()))
    terminal_good = int(terminal_counts.get("passed", 0) + terminal_counts.get("degraded_terminal", 0))
    return {
        "row_count": len(rows),
        "terminal_counts": dict(terminal_counts),
        "terminal_ratio": round(terminal_good / terminal_total, 4) if terminal_total else 0.0,
        "unhandled_failure_count": int(terminal_counts.get("failed", 0)),
        "auto_expansions": auto_expansions,
        "attempted_profiles": sorted(attempted_profiles, key=lambda value: int(value) if value.isdigit() else value),
        "usable_profiles": sorted(usable_profiles, key=lambda value: int(value) if value.isdigit() else value),
        "blocked_profiles": sorted(blocked_profiles, key=lambda value: int(value) if value.isdigit() else value),
        "daily_counts": daily_counts,
        "daily_cap_exhausted_profile_count": sum(1 for count in daily_counts.values() if int(count or 0) >= 30),
        "total_customer_leads": leads,
        "total_outreach_actions": actions,
        "total_comment_users": comment_users,
        "diagnosis_counts": dict(diagnosis_counts),
        "no_action_codes": dict(no_action_codes),
    }


def readiness_summary(payload: dict[str, Any]) -> dict[str, Any]:
    errors = Counter()
    for row in payload.get("results") or []:
        if isinstance(row, dict) and row.get("error_code"):
            errors[str(row.get("error_code"))] += 1
    summary_errors = payload.get("summary", {}).get("errors") if isinstance(payload.get("summary"), dict) else {}
    if not errors and isinstance(summary_errors, dict):
        for code, count in summary_errors.items():
            errors[str(code)] += int(count or 0)
    return {
        "status": payload.get("status", ""),
        "terminal_reason_code": payload.get("terminal_reason_code", ""),
        "selected_profiles_count": int(payload.get("selected_profiles_count") or 0),
        "available_profile_count": int(payload.get("available_profile_count") or 0),
        "unavailable_profile_count": int(payload.get("unavailable_profile_count") or 0),
        "error_counts": dict(errors),
        "report_path": str(payload.get("outputs", {}).get("json") or payload.get("report_path") or ""),
    }


def failure_probe_summary(payload: dict[str, Any]) -> dict[str, Any]:
    errors = Counter()
    summary_errors = payload.get("summary", {}).get("errors") if isinstance(payload.get("summary"), dict) else {}
    if isinstance(summary_errors, dict):
        for code, count in summary_errors.items():
            errors[str(code)] += int(count or 0)
    if not errors and payload.get("error_code"):
        errors[str(payload.get("error_code"))] += 1
    group_refresh = payload.get("group_refresh") if isinstance(payload.get("group_refresh"), dict) else {}
    return {
        "status": payload.get("status", ""),
        "terminal_reason_code": payload.get("terminal_reason_code", ""),
        "error_counts": dict(errors),
        "refresh_attempt_count": int(group_refresh.get("refresh_attempt_count") or 0),
        "max_refresh_retries": int(group_refresh.get("max_refresh_retries") or 0),
        "bounded_retry_policy_enforced": bool(group_refresh.get("bounded_retry_policy_enforced")),
        "no_browser_started": bool(payload.get("no_browser_started", True)),
        "no_submit": bool(payload.get("no_submit", True)),
        "report_path": str(payload.get("outputs", {}).get("json") or payload.get("report_path") or ""),
    }


def web_ui_restart_summary(payload: dict[str, Any]) -> dict[str, Any]:
    errors = Counter()
    summary_errors = payload.get("summary", {}).get("errors") if isinstance(payload.get("summary"), dict) else {}
    if isinstance(summary_errors, dict):
        for code, count in summary_errors.items():
            errors[str(code)] += int(count or 0)
    if not errors and payload.get("error_code"):
        errors[str(payload.get("error_code"))] += 1
    restart = payload.get("web_ui_restart") if isinstance(payload.get("web_ui_restart"), dict) else {}
    return {
        "status": payload.get("status", ""),
        "terminal_reason_code": payload.get("terminal_reason_code", ""),
        "error_counts": dict(errors),
        "run_session_takeover_checked": bool(restart.get("run_session_takeover_checked")),
        "run_session_recovered": bool(restart.get("run_session_recovered")),
        "existing_run_duplicate_start_prevented": bool(restart.get("existing_run_duplicate_start_prevented")),
        "duplicate_task_started": bool(restart.get("duplicate_task_started")),
        "bounded_recovery_attempt_count": int(restart.get("bounded_recovery_attempt_count") or 0),
        "max_recovery_attempts": int(restart.get("max_recovery_attempts") or 0),
        "no_browser_started": bool(payload.get("no_browser_started", True)),
        "no_submit": bool(payload.get("no_submit", True)),
        "report_path": str(payload.get("outputs", {}).get("json") or payload.get("report_path") or ""),
    }


def database_busy_summary(payload: dict[str, Any]) -> dict[str, Any]:
    errors = Counter()
    summary_errors = payload.get("summary", {}).get("errors") if isinstance(payload.get("summary"), dict) else {}
    if isinstance(summary_errors, dict):
        for code, count in summary_errors.items():
            errors[str(code)] += int(count or 0)
    if not errors and payload.get("error_code"):
        errors[str(payload.get("error_code"))] += 1
    database_busy = payload.get("database_busy") if isinstance(payload.get("database_busy"), dict) else {}
    return {
        "status": payload.get("status", ""),
        "terminal_reason_code": payload.get("terminal_reason_code", ""),
        "error_counts": dict(errors),
        "write_attempt_count": int(database_busy.get("write_attempt_count") or 0),
        "max_write_retries": int(database_busy.get("max_write_retries") or 0),
        "busy_timeout_ms": int(database_busy.get("busy_timeout_ms") or 0),
        "busy_timeout_enforced": bool(database_busy.get("busy_timeout_enforced")),
        "bounded_retry_policy_enforced": bool(database_busy.get("bounded_retry_policy_enforced")),
        "real_sqlite_lock_observed": bool(database_busy.get("real_sqlite_lock_observed")),
        "no_browser_started": bool(payload.get("no_browser_started", True)),
        "no_submit": bool(payload.get("no_submit", True)),
        "report_path": str(payload.get("outputs", {}).get("json") or payload.get("report_path") or ""),
    }


def report_write_failure_summary(payload: dict[str, Any]) -> dict[str, Any]:
    errors = Counter()
    summary_errors = payload.get("summary", {}).get("errors") if isinstance(payload.get("summary"), dict) else {}
    if isinstance(summary_errors, dict):
        for code, count in summary_errors.items():
            errors[str(code)] += int(count or 0)
    if not errors and payload.get("error_code"):
        errors[str(payload.get("error_code"))] += 1
    report_write = payload.get("report_write_failure") if isinstance(payload.get("report_write_failure"), dict) else {}
    return {
        "status": payload.get("status", ""),
        "terminal_reason_code": payload.get("terminal_reason_code", ""),
        "error_counts": dict(errors),
        "write_attempt_count": int(report_write.get("write_attempt_count") or 0),
        "max_write_retries": int(report_write.get("max_write_retries") or 0),
        "bounded_retry_policy_enforced": bool(report_write.get("bounded_retry_policy_enforced")),
        "write_failure_observed": bool(report_write.get("write_failure_observed")),
        "report_preserved_after_failure": bool(report_write.get("report_preserved_after_failure")),
        "no_browser_started": bool(payload.get("no_browser_started", True)),
        "no_submit": bool(payload.get("no_submit", True)),
        "report_path": str(payload.get("outputs", {}).get("json") or payload.get("report_path") or ""),
    }


def matrix_row(
    case_id: str,
    title: str,
    status: str,
    evidence: list[str],
    next_action: str,
    *,
    source: str = "local_audit",
) -> dict[str, Any]:
    return {
        "id": case_id,
        "title": title,
        "status": status,
        "passed": status in {"passed_real", "passed_contract", "passed_fault_injection"},
        "source": source,
        "evidence": evidence,
        "next_action": next_action,
        "no_submit": True,
    }


def fault_injection_enabled(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and isinstance(payload.get("fault_injection"), dict)
        and payload.get("fault_injection", {}).get("enabled")
    )


def build_matrix(
    *,
    pressure_rows: list[dict[str, Any]],
    readiness_payload: dict[str, Any],
    runtime_audit: dict[str, Any],
    profile_missing_payload: dict[str, Any] | None = None,
    kernel_mismatch_payload: dict[str, Any] | None = None,
    proxy_failed_payload: dict[str, Any] | None = None,
    page_timeout_payload: dict[str, Any] | None = None,
    group_refresh_failure_payload: dict[str, Any] | None = None,
    web_ui_restart_payload: dict[str, Any] | None = None,
    database_busy_payload: dict[str, Any] | None = None,
    report_write_failure_payload: dict[str, Any] | None = None,
    pressure_summary_path: str = "",
    readiness_report_path: str = "",
    runtime_audit_path: str = "",
    profile_missing_report_path: str = "",
    kernel_mismatch_report_path: str = "",
    proxy_failed_report_path: str = "",
    page_timeout_report_path: str = "",
    group_refresh_failure_report_path: str = "",
    web_ui_restart_report_path: str = "",
    database_busy_report_path: str = "",
    report_write_failure_report_path: str = "",
) -> dict[str, Any]:
    pressure = summarize_pressure(pressure_rows)
    readiness = readiness_summary(readiness_payload)
    profile_missing = readiness_summary(profile_missing_payload or {})
    kernel_mismatch = readiness_summary(kernel_mismatch_payload or {})
    proxy_failed = readiness_summary(proxy_failed_payload or {})
    page_timeout = readiness_summary(page_timeout_payload or {})
    group_refresh_failure = failure_probe_summary(group_refresh_failure_payload or {})
    web_ui_restart = web_ui_restart_summary(web_ui_restart_payload or {})
    database_busy = database_busy_summary(database_busy_payload or {})
    report_write_failure = report_write_failure_summary(report_write_failure_payload or {})
    proxy_failed_is_injected = fault_injection_enabled(proxy_failed_payload)
    page_timeout_is_injected = fault_injection_enabled(page_timeout_payload)
    group_refresh_failure_is_injected = fault_injection_enabled(group_refresh_failure_payload)
    web_ui_restart_is_injected = fault_injection_enabled(web_ui_restart_payload)
    database_busy_is_injected = fault_injection_enabled(database_busy_payload)
    report_write_failure_is_injected = fault_injection_enabled(report_write_failure_payload)
    diagnoses = set(pressure.get("diagnosis_counts") or {})
    readiness_errors = set(readiness.get("error_counts") or {})
    profile_missing_errors = set(profile_missing.get("error_counts") or {})
    kernel_mismatch_errors = set(kernel_mismatch.get("error_counts") or {})
    proxy_failed_errors = set(proxy_failed.get("error_counts") or {})
    page_timeout_errors = set(page_timeout.get("error_counts") or {})
    group_refresh_failure_errors = set(group_refresh_failure.get("error_counts") or {})
    web_ui_restart_errors = set(web_ui_restart.get("error_counts") or {})
    database_busy_errors = set(database_busy.get("error_counts") or {})
    report_write_failure_errors = set(report_write_failure.get("error_counts") or {})
    terminal_ok = bool(
        pressure.get("row_count", 0) >= 100
        and pressure.get("terminal_ratio", 0) >= 0.98
        and int(pressure.get("unhandled_failure_count") or 0) == 0
    )
    runtime_ok = bool(
        runtime_audit.get("status") == "ok"
        and int(runtime_audit.get("cleanup_candidate_count") or 0) == 0
        and int(runtime_audit.get("orphan_chromedriver_candidate_count") or 0) == 0
        and int(runtime_audit.get("detached_reachops_client_process_count") or 0) == 0
    )
    rows = [
        matrix_row(
            "pressure_mode_100_real_no_submit",
            "压力模式 100 次真实 no-submit",
            "passed_real" if terminal_ok else "missing",
            [pressure_summary_path] if pressure_summary_path else [],
            "继续使用同一矩阵补齐故障注入项。" if terminal_ok else "完成 100 次真实 no-submit 并保证终态比例 >=98%。",
            source="real_mac_ixbrowser",
        ),
        matrix_row(
            "account_login_invalid",
            "登录失效账号分类",
            "passed_real" if "LOGIN_REQUIRED" in readiness_errors else "missing",
            [readiness_report_path] if readiness_report_path else [],
            "保留 LOGIN_REQUIRED 账号在修复清单中，不自动提交或改凭证。",
            source="real_profile_readiness",
        ),
        matrix_row(
            "account_switch_and_daily_cap",
            "账号自动切换和每日启动上限耗尽",
            "passed_real" if int(pressure.get("daily_cap_exhausted_profile_count") or 0) >= 10 and "no_usable_profile_remaining" in diagnoses else "missing",
            [pressure_summary_path] if pressure_summary_path else [],
            "继续保持有界账号预算，禁止重复使用已达上限账号伪造压力数量。",
            source="real_mac_ixbrowser",
        ),
        matrix_row(
            "low_intent_no_candidate_degrade",
            "低意向/无候选结构化降级",
            "passed_real" if {"low_intent_candidates", "no_candidates"}.issubset(set((pressure.get("no_action_codes") or {}).keys())) else "missing",
            [pressure_summary_path] if pressure_summary_path else [],
            "保持 no-submit 降级报告，不把无价值页面计为失败或成功线索。",
            source="real_tiktok_data",
        ),
        matrix_row(
            "runtime_process_cleanup",
            "运行结束进程清理",
            "passed_real" if runtime_ok else "missing",
            [runtime_audit_path] if runtime_audit_path else [],
            "每轮真实运行后继续执行 runtime process audit。",
            source="local_runtime_audit",
        ),
        matrix_row(
            "run_session_recovery_contract",
            "执行进程中断和 RunSession 恢复合同",
            "passed_contract",
            ["tests/test_run_recovery.py"],
            "仍需补一个真实 Web UI 中断恢复演练证据。",
            source="unit_contract",
        ),
        matrix_row(
            "mid_run_stop_contract",
            "中途停止合同",
            "passed_contract",
            ["tools/reachops_web_ui.py", "ReachOps/evidence_bundle.py"],
            "仍需在真实 Web UI 运行中执行 stop 并记录进程审计。",
            source="code_contract",
        ),
        matrix_row(
            "profile_deleted_or_missing",
            "账号被删除或 Profile 不存在",
            "passed_real" if profile_missing_errors.intersection({"PROFILE_MISSING", "PROFILE_START_FAILED"}) else "missing",
            [profile_missing_report_path] if profile_missing_report_path else [],
            "保持缺失 Profile 的修复清单，不自动删除或移动远端配置。" if profile_missing_errors else "运行无效 Profile ID 的 no-submit 探针，要求 PROFILE_MISSING 结构化终态。",
            source="real_profile_readiness" if profile_missing_errors else "local_audit",
        ),
        matrix_row(
            "kernel_mismatch",
            "ixBrowser 内核不匹配",
            "passed_real" if "IXBROWSER_KERNEL_MISMATCH" in kernel_mismatch_errors else "missing",
            [kernel_mismatch_report_path] if kernel_mismatch_report_path else [],
            "保持内核不匹配账号在修复清单中，不重复消耗坏账号。" if kernel_mismatch_errors else "使用已知内核不匹配 Profile 或 fault injection 证明 IXBROWSER_KERNEL_MISMATCH 分类和不重复重试。",
            source="real_profile_readiness" if kernel_mismatch_errors else "local_audit",
        ),
        matrix_row(
            "proxy_failed",
            "代理失败",
            (
                "passed_fault_injection"
                if "PROXY_FAILED" in proxy_failed_errors and proxy_failed_is_injected
                else "passed_real"
                if "PROXY_FAILED" in proxy_failed_errors
                else "missing"
            ),
            [proxy_failed_report_path] if proxy_failed_report_path else [],
            (
                "补充真实代理故障 Profile 证据后再升级为 passed_real。"
                if proxy_failed_is_injected and proxy_failed_errors
                else "保持代理失败账号在修复清单中，不重复消耗坏账号。"
                if proxy_failed_errors
                else "使用代理故障账号或安全 fault injection 证明 PROXY_FAILED 分类和修复清单。"
            ),
            source=(
                "safe_fault_injection"
                if proxy_failed_is_injected and proxy_failed_errors
                else "real_profile_readiness"
                if proxy_failed_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "page_timeout",
            "页面超时",
            (
                "passed_fault_injection"
                if "PAGE_TIMEOUT" in page_timeout_errors and page_timeout_is_injected
                else "passed_real"
                if "PAGE_TIMEOUT" in page_timeout_errors
                else "missing"
            ),
            [page_timeout_report_path] if page_timeout_report_path else [],
            (
                "补充真实短 timeout 或受控慢页面证据后再升级为 passed_real。"
                if page_timeout_is_injected and page_timeout_errors
                else "保持 PAGE_TIMEOUT 有界退出和修复清单。"
                if page_timeout_errors
                else "用短 timeout 或受控慢页面验证 PAGE_TIMEOUT 有界退出和截图/sidecar。"
            ),
            source=(
                "safe_fault_injection"
                if page_timeout_is_injected and page_timeout_errors
                else "real_profile_readiness"
                if page_timeout_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "group_refresh_failure",
            "分组刷新失败",
            (
                "passed_fault_injection"
                if "GROUP_REFRESH_FAILURE" in group_refresh_failure_errors
                and group_refresh_failure_is_injected
                and group_refresh_failure.get("bounded_retry_policy_enforced")
                and int(group_refresh_failure.get("max_refresh_retries") or 0) <= 1
                and group_refresh_failure.get("no_browser_started") is True
                and group_refresh_failure.get("no_submit") is True
                else "passed_real"
                if "GROUP_REFRESH_FAILURE" in group_refresh_failure_errors
                and group_refresh_failure.get("bounded_retry_policy_enforced")
                else "missing"
            ),
            [group_refresh_failure_report_path] if group_refresh_failure_report_path else [],
            (
                "补充真实 ixBrowser Local API 断开/超时证据后再升级为 passed_real。"
                if group_refresh_failure_is_injected and group_refresh_failure_errors
                else "保持分组刷新失败最多重试 1 次并结构化阻断。"
                if group_refresh_failure_errors
                else "断开或指向无效 ixBrowser Local API，验证 group refresh 失败最多重试 1 次并阻断。"
            ),
            source=(
                "safe_fault_injection"
                if group_refresh_failure_is_injected and group_refresh_failure_errors
                else "real_web_ui_group_refresh"
                if group_refresh_failure_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "web_ui_restart",
            "Web UI 重启",
            (
                "passed_fault_injection"
                if "WEB_UI_RESTART" in web_ui_restart_errors
                and web_ui_restart_is_injected
                and web_ui_restart.get("run_session_takeover_checked")
                and web_ui_restart.get("run_session_recovered")
                and web_ui_restart.get("existing_run_duplicate_start_prevented")
                and web_ui_restart.get("duplicate_task_started") is False
                and int(web_ui_restart.get("max_recovery_attempts") or 0) <= 1
                and web_ui_restart.get("no_browser_started") is True
                and web_ui_restart.get("no_submit") is True
                else "passed_real"
                if "WEB_UI_RESTART" in web_ui_restart_errors
                and web_ui_restart.get("run_session_takeover_checked")
                and web_ui_restart.get("existing_run_duplicate_start_prevented")
                else "missing"
            ),
            [web_ui_restart_report_path] if web_ui_restart_report_path else [],
            (
                "补充真实运行中 Web UI 重启接管证据后再升级为 passed_real。"
                if web_ui_restart_is_injected and web_ui_restart_errors
                else "保持最新 RunSession 可接管且重复启动不创建第二个任务。"
                if web_ui_restart_errors
                else "运行中重启 Web UI，验证最新 RunSession 可接管且不重复启动任务。"
            ),
            source=(
                "safe_fault_injection"
                if web_ui_restart_is_injected and web_ui_restart_errors
                else "real_web_ui_restart"
                if web_ui_restart_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "database_busy",
            "数据库 busy",
            (
                "passed_fault_injection"
                if "DATABASE_BUSY" in database_busy_errors
                and database_busy_is_injected
                and database_busy.get("real_sqlite_lock_observed")
                and database_busy.get("busy_timeout_enforced")
                and database_busy.get("bounded_retry_policy_enforced")
                and int(database_busy.get("max_write_retries") or 0) <= 0
                and database_busy.get("no_browser_started") is True
                and database_busy.get("no_submit") is True
                else "passed_real"
                if "DATABASE_BUSY" in database_busy_errors
                and database_busy.get("busy_timeout_enforced")
                and database_busy.get("bounded_retry_policy_enforced")
                else "missing"
            ),
            [database_busy_report_path] if database_busy_report_path else [],
            (
                "补充真实运行数据库 busy 恢复/阻断证据后再升级为 passed_real。"
                if database_busy_is_injected and database_busy_errors
                else "保持 DATABASE_BUSY 在 busy_timeout 后结构化终止或恢复。"
                if database_busy_errors
                else "持有 SQLite 写锁并运行受控任务，验证 busy_timeout 后结构化失败或恢复。"
            ),
            source=(
                "safe_fault_injection"
                if database_busy_is_injected and database_busy_errors
                else "real_runtime_database"
                if database_busy_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "report_write_failure",
            "报告写入失败",
            (
                "passed_fault_injection"
                if "REPORT_WRITE_FAILURE" in report_write_failure_errors
                and report_write_failure_is_injected
                and report_write_failure.get("write_failure_observed")
                and report_write_failure.get("report_preserved_after_failure")
                and report_write_failure.get("bounded_retry_policy_enforced")
                and int(report_write_failure.get("max_write_retries") or 0) <= 0
                and report_write_failure.get("no_browser_started") is True
                and report_write_failure.get("no_submit") is True
                else "passed_real"
                if "REPORT_WRITE_FAILURE" in report_write_failure_errors
                and report_write_failure.get("write_failure_observed")
                and report_write_failure.get("report_preserved_after_failure")
                else "missing"
            ),
            [report_write_failure_report_path] if report_write_failure_report_path else [],
            (
                "补充真实运行报告写失败 RunSession 终态证据后再升级为 passed_real。"
                if report_write_failure_is_injected and report_write_failure_errors
                else "保持报告写失败时 RunSession 终态和最终证据不丢失。"
                if report_write_failure_errors
                else "使用只读输出目录或 fault injection 验证报告写失败不丢 RunSession 终态。"
            ),
            source=(
                "safe_fault_injection"
                if report_write_failure_is_injected and report_write_failure_errors
                else "real_runtime_report_writer"
                if report_write_failure_errors
                else "local_audit"
            ),
        ),
        matrix_row(
            "disk_space_abnormal",
            "磁盘空间异常",
            "missing",
            [],
            "使用磁盘空间检查/fault injection 验证低空间时预阻断且不启动浏览器。",
        ),
    ]
    status_counts = Counter(row["status"] for row in rows)
    missing = [row["id"] for row in rows if row["status"] == "missing"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": "passed" if not missing else "partial",
        "passed": not missing,
        "no_submit": True,
        "pressure_summary": pressure,
        "readiness_summary": readiness,
        "profile_missing_summary": profile_missing,
        "kernel_mismatch_summary": kernel_mismatch,
        "proxy_failed_summary": proxy_failed,
        "page_timeout_summary": page_timeout,
        "group_refresh_failure_summary": group_refresh_failure,
        "web_ui_restart_summary": web_ui_restart,
        "database_busy_summary": database_busy,
        "report_write_failure_summary": report_write_failure,
        "runtime_audit_summary": {
            "status": runtime_audit.get("status", ""),
            "cleanup_candidate_count": int(runtime_audit.get("cleanup_candidate_count") or 0),
            "orphan_chromedriver_candidate_count": int(runtime_audit.get("orphan_chromedriver_candidate_count") or 0),
            "detached_reachops_client_process_count": int(runtime_audit.get("detached_reachops_client_process_count") or 0),
        },
        "summary": {
            "total": len(rows),
            "passed": sum(1 for row in rows if row["passed"]),
            "missing": len(missing),
            "status_counts": dict(status_counts),
            "missing_ids": missing,
        },
        "rows": rows,
    }


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the P0-8 real no-submit failure-mode matrix.")
    parser.add_argument("--pressure-summary", default="/tmp/reachops_p08_100run_summary.jsonl")
    parser.add_argument("--readiness-report", default="/tmp/reachops_profile_readiness_p08_group.json")
    parser.add_argument("--profile-missing-report", default="/tmp/reachops_profile_missing_probe.json")
    parser.add_argument("--kernel-mismatch-report", default="/tmp/reachops_kernel_mismatch_probe.json")
    parser.add_argument("--proxy-failed-report", default="/tmp/reachops_proxy_failed_probe.json")
    parser.add_argument("--page-timeout-report", default="/tmp/reachops_page_timeout_probe.json")
    parser.add_argument("--group-refresh-failure-report", default="/tmp/reachops_group_refresh_failure_probe.json")
    parser.add_argument("--web-ui-restart-report", default="/tmp/reachops_web_ui_restart_probe.json")
    parser.add_argument("--database-busy-report", default="/tmp/reachops_database_busy_probe.json")
    parser.add_argument("--report-write-failure-report", default="/tmp/reachops_report_write_failure_probe.json")
    parser.add_argument("--runtime-audit", default="/tmp/reachops_runtime_audit_after_p08_pressure.json")
    parser.add_argument("--output", default="reports/reachops/p08_failure_matrix/latest_p08_failure_matrix.json")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_matrix(
        pressure_rows=read_jsonl(args.pressure_summary),
        readiness_payload=read_json(args.readiness_report),
        runtime_audit=read_json(args.runtime_audit),
        profile_missing_payload=read_json(args.profile_missing_report),
        kernel_mismatch_payload=read_json(args.kernel_mismatch_report),
        proxy_failed_payload=read_json(args.proxy_failed_report),
        page_timeout_payload=read_json(args.page_timeout_report),
        group_refresh_failure_payload=read_json(args.group_refresh_failure_report),
        web_ui_restart_payload=read_json(args.web_ui_restart_report),
        database_busy_payload=read_json(args.database_busy_report),
        report_write_failure_payload=read_json(args.report_write_failure_report),
        pressure_summary_path=str(Path(args.pressure_summary).expanduser()),
        readiness_report_path=str(Path(args.readiness_report).expanduser()),
        runtime_audit_path=str(Path(args.runtime_audit).expanduser()),
        profile_missing_report_path=str(Path(args.profile_missing_report).expanduser()),
        kernel_mismatch_report_path=str(Path(args.kernel_mismatch_report).expanduser()),
        proxy_failed_report_path=str(Path(args.proxy_failed_report).expanduser()),
        page_timeout_report_path=str(Path(args.page_timeout_report).expanduser()),
        group_refresh_failure_report_path=str(Path(args.group_refresh_failure_report).expanduser()),
        web_ui_restart_report_path=str(Path(args.web_ui_restart_report).expanduser()),
        database_busy_report_path=str(Path(args.database_busy_report).expanduser()),
        report_write_failure_report_path=str(Path(args.report_write_failure_report).expanduser()),
    )
    write_report(args.output, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
