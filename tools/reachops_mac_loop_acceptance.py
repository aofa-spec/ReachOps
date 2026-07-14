# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_client_delivery_check import build_delivery_check
from tools.reachops_live_acceptance_status import build_status as build_live_acceptance_status


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_url(url: str, timeout: int = 20) -> tuple[dict[str, Any], str]:
    try:
        with urlopen(url, timeout=max(1, int(timeout or 20))) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else {}, ""
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _payload_needs_retry(payload: dict[str, Any], error: str) -> bool:
    text = json.dumps(payload, ensure_ascii=False) + " " + str(error or "")
    lowered = text.lower()
    return bool(
        error
        or payload.get("stale_cache")
        or payload.get("background_refresh")
        or payload.get("ready") is False
        and ("busy" in lowered or "繁忙" in text)
        or "server busy" in lowered
        or "繁忙" in text
    )


def read_json_url_retry(url: str, *, timeout: int = 20, attempts: int = 3, delay: float = 2.5) -> tuple[dict[str, Any], str]:
    last_payload: dict[str, Any] = {}
    last_error = ""
    for index in range(max(1, attempts)):
        payload, error = read_json_url(url, timeout=timeout)
        last_payload, last_error = payload, error
        if not _payload_needs_retry(payload, error):
            return payload, error
        if index < attempts - 1:
            time.sleep(delay)
    return last_payload, last_error


def build_report(
    base_url: str = "http://127.0.0.1:8769",
    *,
    read_timeout: int = 20,
    groups_timeout: int = 180,
    ix_status_timeout: int = 30,
    retry_attempts: int = 4,
    retry_delay: float = 3.0,
) -> dict[str, Any]:
    base = str(base_url or "http://127.0.0.1:8769").rstrip("/")
    logs, logs_error = read_json_url(f"{base}/api/logs", timeout=read_timeout)
    acceptance, acceptance_error = read_json_url(f"{base}/api/acceptance", timeout=read_timeout)
    groups, groups_error = read_json_url_retry(
        f"{base}/api/groups?refresh=1",
        timeout=groups_timeout,
        attempts=retry_attempts,
        delay=retry_delay,
    )
    ix_status, ix_status_error = read_json_url_retry(
        f"{base}/api/ixbrowser-status",
        timeout=ix_status_timeout,
        attempts=retry_attempts,
        delay=retry_delay,
    )
    client_delivery = build_delivery_check()
    live_status = build_live_acceptance_status(
        argparse.Namespace(
            profile_group="",
            profile_ids="",
            profile_limit=3,
            max_pages=1,
            profile_scan_timeout=8,
            target="",
            comment_video_url="",
            target_profile_url="",
            dm_profile_url="",
            target_username="",
            activation_status_path="",
            activation_template_path="",
            local_inputs_path="",
            acceptance_reports_dir="",
            limit=3,
            allow_pressure_submit="",
            confirm_authorized_targets=False,
            require_final=False,
        ),
        snapshot={
            "available": False,
            "error": "profile snapshot skipped: mac_loop_read_only",
            "profiles": [],
            "groups": [],
            "profile_count": 0,
            "group_count": 0,
        },
    )
    log_lines = [str(item) for item in (logs.get("lines") or [])]
    latest_batch = acceptance.get("latest_batch") if isinstance(acceptance.get("latest_batch"), dict) else {}
    acceptance_payload = acceptance.get("acceptance") if isinstance(acceptance.get("acceptance"), dict) else {}
    acceptance_checks = acceptance_payload.get("checks") if isinstance(acceptance_payload.get("checks"), dict) else {}
    no_action_reason = (
        acceptance_payload.get("no_action_reason")
        if isinstance(acceptance_payload.get("no_action_reason"), dict)
        else {}
    )
    start_contract_evidence = {
        "target_planned": bool(acceptance_checks.get("target_planned")),
        "campaign_started": bool(acceptance_checks.get("campaign_started")),
        "profile_preflight_checked": bool(
            acceptance_checks.get("profile_preflight_fresh")
            and int(acceptance_checks.get("profile_available_count") or 0) >= 0
        ),
        "collection_done": bool(acceptance_checks.get("collection_done")),
        "action_terminal_or_no_submit_reason": bool(
            acceptance_checks.get("action_started") or str(no_action_reason.get("code") or "").strip()
        ),
        "scoped_log_lines": int(acceptance_payload.get("scoped_log_lines") or 0),
    }
    client_payload = acceptance.get("client_delivery") if isinstance(acceptance.get("client_delivery"), dict) else {}
    operations = acceptance.get("operations") if isinstance(acceptance.get("operations"), dict) else {}
    counts = operations.get("counts") if isinstance(operations.get("counts"), dict) else {}
    action_count = int(counts.get("actions") or 0)
    group_rows = [row for row in (groups.get("groups") or []) if isinstance(row, dict)]
    known_group_count = int(groups.get("live_known_group_count") or groups.get("known_group_count") or 0)
    all_group_counts_known = (
        groups.get("live_all_group_counts_known") is True
        or groups.get("all_group_counts_known") is True
        or (bool(group_rows) and known_group_count == len(group_rows))
    )
    checks = {
        "web_ui_reachable": not logs_error and not acceptance_error,
        "ixbrowser_status_reachable": not ix_status_error,
        "ixbrowser_api_ready": ix_status.get("ready") is True,
        "groups_available": len(group_rows) > 0,
        "group_counts_known": known_group_count > 0,
        "all_group_counts_known": all_group_counts_known,
        "groups_fresh": not groups.get("stale_cache") and not groups.get("background_refresh") and not groups.get("error"),
        "last_run_not_running": logs.get("running") is False,
        "last_run_not_failed": logs.get("run_failed") is False,
        "last_run_completed": str(logs.get("run_result_status") or "") == "completed",
        "client_delivery_passed": client_delivery.get("status") == "passed",
        "client_delivery_clean": not client_delivery.get("failed_checks") and not client_delivery.get("blockers"),
        "acceptance_pass": acceptance_payload.get("readiness") == "pass",
        "loop_terminal_evidence": (
            any("DONE   collection" in line for line in log_lines)
            and any("DONE   action_preflight" in line or "DONE   action_submit" in line for line in log_lines)
        )
        or (bool(acceptance_checks.get("collection_done")) and bool(acceptance_checks.get("action_started"))),
        "start_contract_evidence_complete": all(
            bool(start_contract_evidence.get(name))
            for name in [
                "target_planned",
                "campaign_started",
                "profile_preflight_checked",
                "collection_done",
                "action_terminal_or_no_submit_reason",
            ]
        ),
        "no_headless_timeout_in_current_result": "HEADLESS_TIMEOUT" not in json.dumps(logs.get("run_result") or {}, ensure_ascii=False),
        "no_action_reason_present_when_no_actions": action_count > 0 or bool(str(no_action_reason.get("code") or "").strip()),
        "live_final_still_blocked": live_status.get("final_delivery_ready") is False,
    }
    local_required_checks = [
        "web_ui_reachable",
        "ixbrowser_status_reachable",
        "ixbrowser_api_ready",
        "groups_available",
        "group_counts_known",
        "all_group_counts_known",
        "groups_fresh",
        "last_run_not_running",
        "last_run_not_failed",
        "last_run_completed",
        "acceptance_pass",
        "loop_terminal_evidence",
        "start_contract_evidence_complete",
        "no_headless_timeout_in_current_result",
        "no_action_reason_present_when_no_actions",
    ]
    passed = all(checks[name] for name in local_required_checks)
    next_actions = []
    ix_error = str(ix_status.get("error") or "")
    if not checks["ixbrowser_api_ready"]:
        if "繁忙" in ix_error or "busy" in ix_error.lower():
            next_actions.append("ixBrowser Local API 当前繁忙，等待正在运行的分组刷新/配置读取完成后重新刷新分组。")
        else:
            next_actions.append("启动 ixBrowser 客户端并开启 Local API，确认 http://127.0.0.1:53200/api/v2/ 可访问。")
    if not checks["groups_fresh"]:
        next_actions.append("Local API 连通后点击“刷新分组”，直到分组列表不是缓存且每组账号数显示完整。")
    if not checks["all_group_counts_known"]:
        next_actions.append("当前 /api/groups 未证明全部分组账号数量完整，必须重新刷新直到 known_group_count 等于 group_count。")
    if not checks["last_run_completed"] or not checks["loop_terminal_evidence"]:
        next_actions.append("重新点击开始获客后等待 /api/logs 显示 run_result_status=completed，并出现 DONE collection 与 DONE action_preflight/action_submit。")
    if not checks["start_contract_evidence_complete"]:
        next_actions.append("最近一次开始获客必须在 /api/acceptance 中证明目标规划、批次启动、账号预检、采集完成和触达预检/跳过原因。")
    if not checks["no_headless_timeout_in_current_result"]:
        next_actions.append("若再次出现 HEADLESS_TIMEOUT，降低目标数量或检查 ixBrowser/TikTok 页面加载。")
    if not checks["no_action_reason_present_when_no_actions"]:
        next_actions.append("当前批次没有触达动作时，/api/acceptance 必须返回 no_action_reason 说明无候选、低意向或账号不可用等原因。")
    if not checks["acceptance_pass"]:
        if no_action_reason.get("code"):
            next_actions.append(
                "当前开始获客链路已执行到终态，但有效获客/触达未达标："
                f"{no_action_reason.get('message')}"
            )
        next_actions.append("要通过 Mac 本地 MVP 门禁，/api/acceptance 必须达到 readiness=pass。")
    return {
        "generated_at": utc_now(),
        "status": "passed" if passed else "failed",
        "mac_loop_ready": bool(passed),
        "final_delivery_ready": False,
        "probe_contract": {
            "read_timeout_seconds": int(read_timeout),
            "groups_timeout_seconds": int(groups_timeout),
            "ix_status_timeout_seconds": int(ix_status_timeout),
            "retry_attempts": int(retry_attempts),
            "retry_delay_seconds": float(retry_delay),
            "does_not_submit": True,
            "does_not_open_browser_profile": True,
        },
        "web_ui": {
            "base_url": base,
            "logs_error": logs_error,
            "acceptance_error": acceptance_error,
            "groups_error": groups_error,
            "ixbrowser_status_error": ix_status_error,
            "ixbrowser_ready": ix_status.get("ready"),
            "ixbrowser_error": ix_status.get("error", ""),
            "run_result_status": logs.get("run_result_status", ""),
            "running": bool(logs.get("running")),
            "run_failed": bool(logs.get("run_failed")),
            "last_stage": logs.get("last_stage", ""),
        },
        "latest_batch": {
            "id": latest_batch.get("id", ""),
            "status": latest_batch.get("status", ""),
            "profile_group": latest_batch.get("profile_group", ""),
        },
        "groups": {
            "group_count": len(group_rows),
            "known_group_count": known_group_count,
            "all_group_counts_known": all_group_counts_known,
            "profile_count": groups.get("profile_count", 0),
            "count_resolution_error": groups.get("count_resolution_error") or "",
        },
        "operations": {
            "candidates": counts.get("candidates", 0),
            "actions": action_count,
            "touch_success": counts.get("touch_success", 0),
            "touch_failed": counts.get("touch_failed", 0),
            "no_action_reason": no_action_reason,
        },
        "start_contract_evidence": start_contract_evidence,
        "client_delivery": {
            "status": client_delivery.get("status", ""),
            "readiness": client_delivery.get("readiness", ""),
            "acceptance_ready": bool(client_delivery.get("acceptance_ready")),
            "failed_checks": client_delivery.get("failed_checks") or [],
            "blockers": client_delivery.get("blockers") or [],
        },
        "acceptance": {
            "readiness": acceptance_payload.get("readiness", ""),
            "checks": acceptance_checks,
            "blockers": acceptance_payload.get("blockers") or [],
            "client_delivery_status_from_web": client_payload.get("status", ""),
        },
        "live_delivery_boundary": {
            "status": live_status.get("status", ""),
            "ready_for_live_preflight": bool(live_status.get("ready_for_live_preflight")),
            "final_delivery_ready": bool(live_status.get("final_delivery_ready")),
            "failed_checks": live_status.get("failed_checks") or [],
        },
        "checks": checks,
        "local_required_checks": local_required_checks,
        "next_actions": [] if passed else next_actions,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the latest Mac Web UI acquisition loop reached a stable terminal state.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument(
        "--pm-fast",
        action="store_true",
        help="Use short read-only probe timeouts for PM aggregate gates. This never submits or opens browser profiles.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.pm_fast:
        report = build_report(
            args.base_url,
            read_timeout=2,
            groups_timeout=3,
            ix_status_timeout=3,
            retry_attempts=1,
            retry_delay=0,
        )
    else:
        report = build_report(args.base_url)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps Mac loop acceptance: {report['status']}")
        print(f"run_result_status={report['web_ui']['run_result_status']} client_delivery={report['client_delivery']['status']}")
    return 0 if report.get("mac_loop_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
