# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from ReachOps.execution_plan import (
    adversarial_cli_args_for_contract_preview,
    attach_autonomous_preflight_forecast,
    build_autonomous_preflight_forecast,
    build_execution_plan,
    build_execution_plan_runtime_contract,
    read_execution_plan,
    write_execution_plan,
)
from ReachOps.ai_console import LocalAIConsole
from ReachOps.run_session import (
    RUN_SESSION_STATE_RANK,
    TERMINAL_RUN_SESSION_STATES,
    create_run_session,
    infer_run_state,
    read_run_session,
    transition_run_session,
    write_run_session,
)
from ReachOps.run_recovery import recover_interrupted_run_session

DATA_DIR = ROOT_DIR / "reports/reachops/mac_gui/runtime"
LOG_PATH = DATA_DIR / "logs/growth_ops_runtime.log"
RESULT_PATH = DATA_DIR / "reachops_web_ui_last_run.json"
PROGRESS_PATH = DATA_DIR / "reachops_web_ui_progress.json"
HEARTBEAT_PATH = DATA_DIR / "reachops_web_ui_heartbeat.json"
LATEST_EXECUTION_PLAN_PATH = DATA_DIR / "plans/latest_execution_plan.json"
LATEST_RUN_SESSION_PATH = DATA_DIR / "runs/latest_run_session.json"
LATEST_EVIDENCE_BUNDLE_PATH = DATA_DIR / "evidence_bundles/latest_evidence_bundle.json"
LATEST_EVIDENCE_BUNDLE_MD_PATH = DATA_DIR / "evidence_bundles/latest_evidence_bundle.md"
CONTROL_DIR = DATA_DIR / "control"
DEFAULT_TARGET = ""
WEB_UI_VERSION = "reachops-unified-ui-2026-07-05-v20-ai-machine-actions"
CLIENT_DISPLAY_VERSION = "客户端 v20"
MAX_JSON_PAYLOAD_BYTES = 64 * 1024
MAX_START_PROFILE_LIMIT = 20
STARTUP_HEALTHCHECK_SECONDS = 0.2
LOCAL_API_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_MODES = {"preflight", "collect", "live_comment"}
ALLOWED_VOLUMES = {"quick", "standard", "stress"}
FAILED_RUN_RESULT_STATUSES = {"timeout_finalized"}
HEARTBEAT_STALE_SECONDS = int(os.environ.get("REACHOPS_HEARTBEAT_STALE_SECONDS") or "90")
WATCHDOG_INTERVAL_SECONDS = float(os.environ.get("REACHOPS_WATCHDOG_INTERVAL_SECONDS") or "10")
PAUSE_SIGNAL = getattr(signal, "SIGSTOP", None)
RESUME_SIGNAL = getattr(signal, "SIGCONT", None)
TERM_SIGNAL = getattr(signal, "SIGTERM", signal.SIGINT)
KILL_SIGNAL = getattr(signal, "SIGKILL", None)

RUN_PROCESS: subprocess.Popen | None = None
RUN_STARTED_AT = 0.0
RUN_LOG_OFFSET = 0
RUN_PAUSED = False
CURRENT_RUN_SESSION_PATH = ""
RUN_STATE_LOCK = threading.Lock()
WATCHDOG_THREAD: threading.Thread | None = None
WATCHDOG_STOP_EVENT = threading.Event()
WATCHDOG_LAST_EVENT: dict = {"signature": "", "logged_at": 0.0}
GROUP_CACHE: dict = {"loaded_at": 0.0, "groups": [], "error": ""}
GROUP_REFRESH_STATE_LOCK = threading.Lock()
GROUP_REFRESH_THREAD: threading.Thread | None = None
GROUP_REFRESH_LOG_SIGNATURE = ""
IXBROWSER_API_PORT_OVERRIDE = ""
WEB_SETTINGS_PATH = DATA_DIR / "config/reachops_web_settings.json"
LATEST_GROUPS_PATH = DATA_DIR / "config/latest_ixbrowser_groups.json"
GROUP_REFRESH_TIMEOUT_SECONDS = 10.0
GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS = 20.0
GROUP_COUNT_RESOLVE_WORKERS = 1
ACCEPTANCE_INPUT_TEMPLATE_PATH = ROOT_DIR / "tools" / "reachops_acceptance_inputs.example.ps1"
ACCEPTANCE_INPUT_LOCAL_PATH = ROOT_DIR / "tools" / "reachops_acceptance_inputs.local.ps1"
MVP_ACCEPTANCE_SUMMARY_PATH = DATA_DIR / "reports/acceptance_remediation/latest_mvp_acceptance_summary.json"
GOAL_DELIVERY_REPORT_PATH = DATA_DIR / "reports/acceptance_remediation/latest_goal_delivery_report.json"
GOAL_DELIVERY_SUMMARY_PATH = DATA_DIR / "reports/acceptance_remediation/latest_goal_delivery_summary.md"
TWO_PHASE_MATRIX_JSON_PATH = DATA_DIR / "reports/acceptance_remediation/latest_two_phase_acceptance_matrix.json"
TWO_PHASE_MATRIX_MD_PATH = DATA_DIR / "reports/acceptance_remediation/latest_two_phase_acceptance_matrix.md"
FINAL_VERIFICATION_COMMANDS = [
    "python tools\\reachops_client_delivery_check.py --json",
    "python tools\\reachops_goal_delivery_runner.py --json",
    "python tools\\reachops_two_phase_acceptance_matrix.py --refresh --write --require-final --json",
    "python tools\\reachops_delivery_package_check.py --json",
    "python tools\\reachops_issue_closure_audit.py --json",
    "python tools\\reachops_final_acceptance_gate.py --json",
]


def build_version_payload() -> dict:
    return {
        "status": "ok",
        "version": WEB_UI_VERSION,
        "display_version": CLIENT_DISPLAY_VERSION,
        "client_surface": "local_client_console",
        "display_name": "ReachOps Local Client Console",
        "loopback_host": "127.0.0.1",
        "pid": os.getpid(),
        "no_browser_started": True,
        "no_submit": True,
    }


def live_acceptance_readiness_report_path() -> Path:
    return DATA_DIR / "reports/acceptance_remediation/latest_live_acceptance_readiness.md"


def live_acceptance_readiness_json_path() -> Path:
    return DATA_DIR / "reports/acceptance_remediation/latest_live_acceptance_readiness.json"


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def read_text_tail(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-limit:]


def read_runtime_progress_payload() -> dict:
    if not PROGRESS_PATH.is_file():
        return {}
    try:
        payload = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def read_runtime_heartbeat_payload() -> dict:
    if not HEARTBEAT_PATH.is_file():
        return {}
    try:
        payload = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "read_failed", "path": str(HEARTBEAT_PATH)}
    if not isinstance(payload, dict):
        return {}
    return payload


def runtime_heartbeat_age_seconds(payload: dict | None = None) -> int | None:
    heartbeat = payload if isinstance(payload, dict) else read_runtime_heartbeat_payload()
    if not heartbeat:
        return None
    heartbeat_at = parse_utc(str(heartbeat.get("heartbeat_at") or heartbeat.get("generated_at") or ""))
    if heartbeat_at is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - heartbeat_at).total_seconds()))


def build_runtime_heartbeat_payload() -> dict:
    heartbeat = read_runtime_heartbeat_payload()
    age = runtime_heartbeat_age_seconds(heartbeat)
    running = run_is_active()
    run_age = int(time.time() - RUN_STARTED_AT) if RUN_STARTED_AT and running else 0
    session = read_current_run_session()
    terminal = str((session or {}).get("state") or "") in TERMINAL_RUN_SESSION_STATES
    missing_stale = bool(running and not heartbeat and run_age > HEARTBEAT_STALE_SECONDS and not terminal)
    stale = bool(
        running
        and not terminal
        and (
            missing_stale
            or (age is not None and age > HEARTBEAT_STALE_SECONDS)
        )
    )
    return {
        "schema_version": "reachops.web_runtime_heartbeat.v1",
        "status": "missing_stale" if missing_stale else ("missing" if not heartbeat else ("stale" if stale else "healthy")),
        "running": running,
        "stale": stale,
        "stale_after_seconds": HEARTBEAT_STALE_SECONDS,
        "age_seconds": age,
        "run_age_seconds": run_age,
        "heartbeat": heartbeat,
        "run_session_state": str((session or {}).get("state") or ""),
        "run_session_id": str((session or {}).get("session_id") or ""),
        "path": str(HEARTBEAT_PATH),
        "no_ai_token_used": True,
    }


def read_json_file(path: Path) -> dict:
    try:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {"status": "read_failed"}
    return {}


def summarize_mvp_acceptance(path: Path | None = None) -> dict:
    path = path or MVP_ACCEPTANCE_SUMMARY_PATH
    payload = read_json_file(path)
    return {
        "status": payload.get("status", ""),
        "mvp_local_ready": bool(payload.get("mvp_local_ready")),
        "final_delivery_ready": bool(payload.get("final_delivery_ready")),
        "failed_checks": payload.get("failed_checks") or [],
        "path": str(path) if path.is_file() else "",
    }


def summarize_goal_delivery(path: Path | None = None) -> dict:
    path = path or GOAL_DELIVERY_REPORT_PATH
    payload = read_json_file(path)
    evidence_files = payload.get("evidence_files") if isinstance(payload.get("evidence_files"), dict) else {}
    summary_path = str(evidence_files.get("goal_delivery_summary") or GOAL_DELIVERY_SUMMARY_PATH)
    sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
    windows_section = sections.get("windows_package_preflight") if isinstance(sections.get("windows_package_preflight"), dict) else {}
    windows_payload = windows_section.get("payload") if isinstance(windows_section.get("payload"), dict) else {}
    build_contract = windows_payload.get("build_contract") if isinstance(windows_payload.get("build_contract"), dict) else {}
    delivery_boundary = payload.get("delivery_boundary") if isinstance(payload.get("delivery_boundary"), dict) else {}
    return {
        "status": payload.get("status", ""),
        "local_mvp_ready": bool(payload.get("local_mvp_ready")),
        "windows_build_ready": bool(payload.get("windows_build_ready")),
        "final_delivery_ready": bool(payload.get("final_delivery_ready")),
        "delivery_boundary": delivery_boundary,
        "deliverable_index": payload.get("deliverable_index") if isinstance(payload.get("deliverable_index"), dict) else {},
        "failed_checks": payload.get("failed_checks") or [],
        "final_delivery_blockers": payload.get("final_delivery_blockers") if isinstance(payload.get("final_delivery_blockers"), list) else [],
        "blockers": payload.get("blockers") or [],
        "next_actions": payload.get("next_actions") or [],
        "evidence_files": evidence_files,
        "summary_path": summary_path if Path(summary_path).is_file() else "",
        "windows_package_preflight": {
            "status": windows_payload.get("status", ""),
            "ready_for_windows_build": bool(windows_payload.get("ready_for_windows_build")),
            "final_delivery_ready": bool(windows_payload.get("final_delivery_ready")),
            "missing_final_artifacts": windows_payload.get("missing_final_artifacts") or [],
            "default_build_requires_installer": bool(build_contract.get("default_build_requires_installer")),
            "skip_installer_is_non_final": bool(build_contract.get("skip_installer_is_non_final")),
            "preflight_report_path": build_contract.get("preflight_report_path", ""),
        },
        "path": str(path) if path.is_file() else "",
    }


def summarize_two_phase_acceptance(path: Path | None = None) -> dict:
    path = path or TWO_PHASE_MATRIX_JSON_PATH
    payload = read_json_file(path)
    return {
        "status": payload.get("status", ""),
        "local_mvp_ready": bool(payload.get("local_mvp_ready")),
        "final_delivery_ready": bool(payload.get("final_delivery_ready")),
        "failed_items": payload.get("failed_items") or [],
        "blocking_scopes": payload.get("blocking_scopes") or [],
        "path": str(path) if path.is_file() else "",
        "markdown_path": str(TWO_PHASE_MATRIX_MD_PATH) if TWO_PHASE_MATRIX_MD_PATH.is_file() else "",
    }


def fallback_final_delivery_evidence_plan(final_blockers: list[dict]) -> dict:
    items = []
    commands_by_scope = {
        "external_authorized_execution": [
            "python tools\\reachops_live_acceptance_status.py --local-inputs-path tools\\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json",
            "python tools\\reachops_goal_status_report.py --strict-external --json",
        ],
        "client_delivery_gate": ["python tools\\reachops_client_delivery_check.py --json"],
        "windows_final_artifacts": [
            "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
            "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
            "python tools\\reachops_delivery_package_check.py --json",
        ],
        "commercial_issue_closure": ["python tools\\reachops_issue_closure_audit.py --json"],
    }
    proof_by_scope = {
        "external_authorized_execution": [
            "goal_status.status=passed",
            "goal_status.pending_external_validation=[]",
            "live_submit.status=completed",
            "live_submit.platform_validation=true",
        ],
        "client_delivery_gate": [
            "client_delivery.status=passed",
            "client_delivery.readiness=pass",
            "client_delivery.acceptance_ready=true",
            "client_delivery.final_delivery_ready=true",
            "client_delivery.failed_checks=[]",
        ],
        "windows_final_artifacts": [
            "delivery_package.status=passed",
            "delivery_package.final_delivery_ready=true",
            "delivery_package.missing_artifacts=[]",
            "delivery_package.acceptance_verification.passed=true",
            "delivery_package.acceptance_verification.failures=[]",
            "delivery_package.acceptance_verification.pending=[]",
        ],
        "commercial_issue_closure": [
            "issue_closure.summary.issues_total=7",
            "issue_closure.summary.acceptance_criteria_total=53",
            "issue_closure.summary.acceptance_criteria_external_pending=0",
            "issue_closure.summary.external_pending_count=0",
            "issue_closure.github_issues.closure_requires_external_validation=false",
        ],
    }
    title_by_scope = {
        "external_authorized_execution": "授权真实平台执行证据",
        "client_delivery_gate": "客户端交付门禁证据",
        "windows_final_artifacts": "Windows 最终客户端包证据",
        "commercial_issue_closure": "Issues #1-#7 商业交付闭环证据",
    }
    for blocker in final_blockers:
        if not isinstance(blocker, dict):
            continue
        scope = str(blocker.get("scope") or "final_delivery").strip()
        items.append(
            {
                "scope": scope,
                "title": title_by_scope.get(scope, scope),
                "ready": False,
                "status": str(blocker.get("status") or "blocked"),
                "required_evidence": blocker.get("required_evidence") or [],
                "required_artifacts": blocker.get("required_artifacts") or [],
                "commands": commands_by_scope.get(scope, []),
                "proof_fields": proof_by_scope.get(scope, []),
                "blocker_codes": [
                    *[str(item) for item in (blocker.get("pending_external_validation") or [])],
                    *[str(item) for item in (blocker.get("failed_checks") or [])],
                    *[str(item) for item in (blocker.get("failures") or [])],
                ],
                "next_action": str(blocker.get("next_action") or ""),
            }
        )
    return {
        "schema_version": "reachops.final_delivery_evidence_plan.v1",
        "ready": not items,
        "item_count": len(items),
        "ready_count": 0,
        "pending_count": len(items),
        "pending_scopes": [item["scope"] for item in items],
        "items": items,
        "next_actions": [item["next_action"] for item in items if item.get("next_action")],
        "source": "delivery_boundary_fallback",
    }


def build_delivery_boundary_payload(
    *,
    product_capability: dict | None = None,
    product_development_goals: dict | None = None,
    final_status: dict | None = None,
) -> dict:
    """Expose the boundary between local capability readiness and final delivery."""
    product_capability = product_capability if isinstance(product_capability, dict) else {}
    product_development_goals = product_development_goals if isinstance(product_development_goals, dict) else {}
    if not isinstance(final_status, dict):
        try:
            final_status = build_final_status_payload()
        except Exception as exc:
            final_status = {
                "status": "blocked",
                "final_delivery_ready": False,
                "failed_checks": ["final_status:read_failed"],
                "blocked_reasons": [str(exc)],
                "next_required_actions": ["检查最终验收状态读取链路。"],
                "no_browser_started": True,
                "no_submit": True,
            }
    goal_delivery = final_status.get("goal_delivery") if isinstance(final_status.get("goal_delivery"), dict) else summarize_goal_delivery()
    mvp_acceptance = (
        final_status.get("mvp_acceptance") if isinstance(final_status.get("mvp_acceptance"), dict) else summarize_mvp_acceptance()
    )
    two_phase = (
        final_status.get("two_phase_acceptance")
        if isinstance(final_status.get("two_phase_acceptance"), dict)
        else summarize_two_phase_acceptance()
    )
    goal_boundary = goal_delivery.get("delivery_boundary") if isinstance(goal_delivery.get("delivery_boundary"), dict) else {}
    final_blockers = (
        goal_delivery.get("final_delivery_blockers")
        if isinstance(goal_delivery.get("final_delivery_blockers"), list)
        else final_status.get("final_delivery_blockers")
        if isinstance(final_status.get("final_delivery_blockers"), list)
        else []
    )
    final_evidence_plan = (
        final_status.get("final_delivery_evidence_plan")
        if isinstance(final_status.get("final_delivery_evidence_plan"), dict)
        else goal_delivery.get("final_delivery_evidence_plan")
        if isinstance(goal_delivery.get("final_delivery_evidence_plan"), dict)
        else {}
    )
    if not final_evidence_plan:
        final_evidence_plan = fallback_final_delivery_evidence_plan(final_blockers)
    pending_scopes = [
        str(scope)
        for scope in (
            goal_boundary.get("blocking_scopes")
            or two_phase.get("blocking_scopes")
            or [row.get("scope") for row in final_blockers if isinstance(row, dict)]
        )
        if str(scope or "").strip()
    ]
    for scope in final_evidence_plan.get("pending_scopes") or []:
        text = str(scope or "").strip()
        if text:
            pending_scopes.append(text)
    pending_scopes = list(dict.fromkeys(pending_scopes))
    external_pending = any(scope == "external_authorized_execution" for scope in pending_scopes) or any(
        (row or {}).get("scope") == "external_authorized_execution" for row in final_blockers if isinstance(row, dict)
    )
    windows_pending = any(scope == "windows_final_artifacts" for scope in pending_scopes) or any(
        (row or {}).get("scope") == "windows_final_artifacts" for row in final_blockers if isinstance(row, dict)
    )
    next_actions = []
    for source in (final_status, goal_delivery):
        for action in source.get("next_actions") or source.get("next_required_actions") or []:
            text = str(action or "").strip()
            if text and text not in next_actions:
                next_actions.append(text)
    for row in final_blockers:
        if isinstance(row, dict):
            text = str(row.get("next_action") or "").strip()
            if text and text not in next_actions:
                next_actions.append(text)
    local_ready = bool(product_capability.get("ready") and product_development_goals.get("ready"))
    final_ready = bool(final_status.get("final_delivery_ready") and goal_delivery.get("final_delivery_ready"))
    return {
        "schema_version": "reachops.delivery_boundary.v1",
        "status": "final_delivery_ready" if final_ready else "local_capability_ready_final_pending" if local_ready else "local_capability_needs_work",
        "local_product_capability_ready": local_ready,
        "product_capability_ready": bool(product_capability.get("ready")),
        "product_development_ready": bool(product_development_goals.get("ready")),
        "final_delivery_ready": final_ready,
        "external_validation_pending": bool(external_pending),
        "windows_final_artifacts_pending": bool(windows_pending),
        "pending_scopes": list(dict.fromkeys(pending_scopes)),
        "mvp_local_ready": bool(mvp_acceptance.get("mvp_local_ready")),
        "goal_delivery_status": str(goal_delivery.get("status") or ""),
        "goal_delivery_final_ready": bool(goal_delivery.get("final_delivery_ready")),
        "two_phase_status": str(two_phase.get("status") or ""),
        "two_phase_final_ready": bool(two_phase.get("final_delivery_ready")),
        "final_status": str(final_status.get("status") or ""),
        "final_status_failed_checks": final_status.get("failed_checks") or [],
        "final_delivery_blockers": final_blockers,
        "final_delivery_evidence_plan": final_evidence_plan,
        "evidence_pending_scopes": final_evidence_plan.get("pending_scopes") if isinstance(final_evidence_plan, dict) else [],
        "next_actions": next_actions[:8]
        or ["八阶段本地能力可继续验收；最终交付仍需真实授权执行和 Windows 最终包证据。"],
        "boundary_note": "本地产品能力 ready 只证明自治链路闭环；final_delivery_ready=true 才代表真实授权执行和最终客户端交付完成。",
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }


def extract_last_json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    last_payload: dict = {}
    last_status_payload: dict = {}
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except Exception:
            continue
        if isinstance(payload, dict):
            last_payload = payload
            if str(payload.get("status") or ""):
                last_status_payload = payload
    return last_status_payload or last_payload


def read_run_result_payload(path: Path | None = None) -> dict:
    path = path or RESULT_PATH
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    try:
        payload = json.loads(text or "{}")
    except Exception:
        return extract_last_json_object(text)
    return payload if isinstance(payload, dict) else {}


def write_run_result_payload(payload: dict, path: Path | None = None) -> bool:
    path = path or RESULT_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def run_session_path_for(session: dict) -> Path:
    session_id = str((session or {}).get("session_id") or "run_session")
    return DATA_DIR / "runs" / f"{session_id}.json"


def read_current_run_session() -> dict:
    if CURRENT_RUN_SESSION_PATH:
        payload = read_run_session(CURRENT_RUN_SESSION_PATH)
        if payload:
            return payload
    return read_run_session(LATEST_RUN_SESSION_PATH)


def persist_run_session(session: dict) -> dict:
    global CURRENT_RUN_SESSION_PATH
    path = run_session_path_for(session)
    write_run_session(session, path, LATEST_RUN_SESSION_PATH)
    CURRENT_RUN_SESSION_PATH = str(path)
    return session


def update_current_run_session(state: str, **kwargs) -> dict:
    session = read_current_run_session()
    if not session:
        return {}
    updated = transition_run_session(session, state, **kwargs)
    return persist_run_session(updated)


def cooperative_control_path(name: str) -> Path:
    return CONTROL_DIR / name


def write_cooperative_control(name: str, payload: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    cooperative_control_path(name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_cooperative_control() -> None:
    try:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        for name in ["pause.request", "resume.request"]:
            path = cooperative_control_path(name)
            if path.exists():
                path.unlink()
    except Exception as exc:
        append_web_log(f"WARN   web_ui_control_file_cleanup_failed error={exc}")


def write_precheck_page_state_bundle(*, reason: str, message: str, metadata: dict | None = None) -> dict:
    page_state_dir = DATA_DIR / "page_state"
    page_state_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(reason or "precheck_blocked"))[:80]
    sidecar_path = page_state_dir / f"precheck_{safe_reason}_{timestamp}.json"
    body_text = f"Local precheck blocked before browser start. reason={reason} message={message}"
    page_state = {
        "schema_version": "reachops.page_state.v1",
        "state": "UNKNOWN_PAGE_STATE",
        "current_url": "",
        "title": "Local precheck blocked before browser start",
        "body_text_sample": body_text[:500],
        "body_text_sha256": hashlib.sha256(body_text.encode("utf-8", errors="ignore")).hexdigest(),
        "button_status": {"visible_button_count": 0, "labels": []},
        "modal_status": {"blocking_modal_visible": False, "dismissible_modal_visible": False, "close_candidates": []},
        "selector_counts": {},
        "signals": ["local_precheck_blocked", "no_browser_started", str(reason or "PROFILE_GROUP_PRECHECK_BLOCKED")],
        "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "no_ai_token_used": True,
    }
    payload = {
        "schema_version": "reachops.page_state.v1",
        "captured_at": page_state["observed_at"],
        "metadata": dict(metadata or {}),
        "page_state": page_state,
        "dom_summary": {
            "available": False,
            "reason": "browser_not_started_by_precheck",
            "node_count": 0,
            "interactive_count": 0,
            "text_sample": "",
        },
        "screenshot": {
            "path": "",
            "captured": False,
            "size": 0,
            "sha256": "",
            "unavailable_reason": "browser_not_started_by_precheck",
        },
        "sidecar_path": str(sidecar_path),
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
    }
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def persist_precheck_blocked_start(
    *,
    target: str,
    source_type: str,
    mode: str,
    profile_group: str,
    volume: str,
    profile_limit: int,
    max_videos: int,
    max_comments: int,
    timeout_seconds: int,
    comment_text: str,
    live_confirmed: bool,
    account_repair_confirmed: bool,
    block: dict,
) -> dict:
    execution_plan = build_execution_plan(
        target=target,
        source_type=source_type,
        mode=mode,
        profile_group=profile_group,
        volume=volume,
        profile_limit=profile_limit,
        max_videos=max_videos,
        max_comments=max_comments,
        timeout_seconds=timeout_seconds,
        comment_text=comment_text,
        live_confirmed=live_confirmed,
        account_repair_confirmed=account_repair_confirmed,
        base_dir=str(DATA_DIR),
        origin="web_ui_start_precheck_blocked",
    )
    preflight_decision = build_start_preflight_decision_for_plan(
        execution_plan,
        start_allowed=False,
        gate_state="启动预检阻断",
        blockers=[str(block.get("error") or "PROFILE_GROUP_PRECHECK_BLOCKED")],
        next_actions=[str(block.get("message") or "处理启动前门禁后重新预检。")],
    )
    execution_plan = attach_autonomous_preflight_forecast(
        execution_plan,
        preflight_decision=preflight_decision,
    )
    plan_id = str(execution_plan.get("plan_id") or "")
    plan_path = DATA_DIR / "plans" / f"{plan_id or 'execution_plan'}.json"
    write_execution_plan(execution_plan, plan_path)
    write_execution_plan(execution_plan, LATEST_EXECUTION_PLAN_PATH)
    run_session = create_run_session(
        execution_plan,
        execution_plan_path=str(plan_path),
        result_path=str(RESULT_PATH),
        log_path=str(LOG_PATH),
        log_offset=len(read_lines(LOG_PATH)),
    )
    result = {
        "status": "blocked",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "error": str(block.get("error") or "PROFILE_GROUP_PRECHECK_BLOCKED"),
        "message": str(block.get("message") or "启动预检阻断。"),
        "reason": str(block.get("error") or "PROFILE_GROUP_PRECHECK_BLOCKED"),
        "target": target,
        "source_type": source_type,
        "profile_group": profile_group,
        "mode": mode,
        "volume": volume,
        "execution_plan": {
            "plan_id": execution_plan.get("plan_id", ""),
            "schema_version": execution_plan.get("schema_version", ""),
            "path": str(plan_path),
        },
        "run_session": {},
        "precheck_block": dict(block or {}),
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_during_execution": True,
    }
    page_state_bundle = write_precheck_page_state_bundle(
        reason=result["error"],
        message=result["message"],
        metadata={
            "source": "web_ui_start_precheck_blocked",
            "target": target,
            "profile_group": profile_group,
            "mode": mode,
            "plan_id": execution_plan.get("plan_id", ""),
        },
    )
    from ReachOps.workbench.repair_policy_engine import RepairPolicyEngine
    from ReachOps.workbench.risk_gate import RiskGate

    repair_decision = RepairPolicyEngine().decide(
        result["error"],
        action_type="start_precheck",
        attempt=1,
        page_state=page_state_bundle.get("page_state") if isinstance(page_state_bundle.get("page_state"), dict) else {},
        max_retries=0,
    )
    repair_audit = {
        "schema_version": "reachops.repair_audit.v1",
        "stage": "precheck",
        "action_id": "start_precheck",
        "action_type": "start_precheck",
        "profile_id": "",
        "attempt": 1,
        "status": "blocked",
        "error_code": result["error"],
        "repair_action": repair_decision.get("action", ""),
        "repair_reason": repair_decision.get("reason", ""),
        "retry_same_profile": bool(repair_decision.get("retry_same_profile")),
        "switch_profile": bool(repair_decision.get("switch_profile")),
        "cooldown_profile": bool(repair_decision.get("cooldown_profile")),
        "fallback_available": bool(repair_decision.get("fallback_allowed")),
        "degrade_to": str(repair_decision.get("degrade_to") or ""),
        "block_execution": bool(repair_decision.get("block_execution")),
        "requires_human_review": bool(repair_decision.get("requires_human_review")),
        "evidence_bundle_required": bool(repair_decision.get("evidence_bundle_required", True)),
        "executable_steps": list(repair_decision.get("executable_steps") or []),
        "repair_step_results": [
            {
                "step": str(step.get("step") or ""),
                "status": "executed" if str(step.get("step") or "") == "capture_page_state_bundle" else "blocked_until_operator_action",
                "no_ai_token_used": True,
            }
            for step in repair_decision.get("executable_steps") or []
            if isinstance(step, dict)
        ],
        "page_state": (page_state_bundle.get("page_state") or {}).get("state", "UNKNOWN_PAGE_STATE"),
        "evidence_path": str(page_state_bundle.get("sidecar_path") or ""),
        "next_actions": list(repair_decision.get("next_actions") or []),
        "no_ai_token_used": True,
    }
    risk_gate = RiskGate().block_precheck(
        result["error"],
        result["message"],
        action_type="start_precheck",
        evidence={
            "profile_group": profile_group,
            "mode": mode,
            "plan_id": execution_plan.get("plan_id", ""),
            "page_state_sidecar": str(page_state_bundle.get("sidecar_path") or ""),
        },
        next_actions=list(repair_decision.get("next_actions") or []),
    )
    result["page_state"] = page_state_bundle.get("page_state") or {}
    result["page_state_bundle"] = page_state_bundle
    result["repair_decision"] = repair_decision
    result["repair_audit"] = repair_audit
    result["risk_gate"] = risk_gate
    run_session = transition_run_session(
        run_session,
        "PRECHECK",
        last_stage=f"PRECHECK start blocked reason={result['error']}",
        evidence={"execution_plan_path": str(plan_path), "page_state_bundle": page_state_bundle, "repair_decision": repair_decision, "repair_audit": repair_audit, "risk_gate": risk_gate},
    )
    run_session = transition_run_session(
        run_session,
        "BLOCKED",
        last_stage=f"PRECHECK_BLOCKED reason={result['error']}",
        result=result,
        evidence={"execution_plan_path": str(plan_path), "page_state_bundle": page_state_bundle, "repair_decision": repair_decision, "repair_audit": repair_audit, "risk_gate": risk_gate},
    )
    run_session_path = run_session_path_for(run_session)
    result["run_session"] = {"path": str(run_session_path), "session_id": run_session.get("session_id", "")}
    write_run_result_payload(result)
    persist_run_session(run_session)
    return {
        **dict(block or {}),
        "run_session": result["run_session"],
        "execution_plan": result["execution_plan"],
        "run_result": result,
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
    }


def append_web_log(message: str):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts}  {message}\n")
    except Exception:
        pass


def append_group_refresh_log(payload: dict, *, refresh: bool):
    global GROUP_REFRESH_LOG_SIGNATURE
    groups = list(payload.get("groups") or [])
    known = [row for row in groups if row.get("count_known")]
    signature = "|".join(
        [
            str(refresh),
            str(payload.get("error") or ""),
            str(payload.get("stale_cache") or ""),
            str(payload.get("background_refresh") or ""),
            str(len(groups)),
            str(len(known)),
            str(payload.get("profile_count", "deferred")),
        ]
    )
    if not refresh and not payload.get("error") and signature == GROUP_REFRESH_LOG_SIGNATURE:
        return
    GROUP_REFRESH_LOG_SIGNATURE = signature
    names = ",".join(str(row.get("name") or "") for row in groups[:12])
    if len(groups) > 12:
        names += ",..."
    level = "ERROR" if payload.get("error") else "CONFIG"
    append_web_log(
        f"{level}  refresh_groups source=web_ui refresh={str(refresh).lower()} "
        f"groups={len(groups)} known_counts={len(known)} "
        f"profile_count={payload.get('profile_count', 'deferred')} "
        f"profiles_deferred={str(bool(payload.get('profiles_deferred'))).lower()} "
        f"counts_resolved={str(bool(payload.get('counts_resolved'))).lower()} "
        f"count_error={payload.get('count_resolution_error') or '-'} "
        f"error={payload.get('error') or '-'} detail={payload.get('error_detail') or '-'} names={names or '-'}"
    )


def normalize_group_refresh_error(message: str) -> tuple[str, str]:
    text = str(message or "").strip()
    if not text:
        return "", ""
    if "Connection refused" in text or "Failed to establish a new connection" in text:
        return (
            "ixBrowser Local API 未启动或端口不可连接",
            text,
        )
    if "Server busy" in text or "code=1008" in text or "please try again later" in text:
        return ("ixBrowser Local API 繁忙，请稍后重试", text)
    if "timed out" in text or "timeout" in text.lower():
        return ("ixBrowser Local API 读取超时", text)
    if "ixbrowser_group_list_unavailable" in text:
        return ("ixBrowser 分组列表接口不可用", text)
    return (text[:180], text)


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def safe_report_download_path(raw_path: str) -> Path | None:
    try:
        path = Path(str(raw_path or "")).expanduser().resolve()
        allowed_roots = [
            (DATA_DIR / "reports").resolve(),
            (DATA_DIR / "data/growth_intelligence/reports").resolve(),
        ]
        if not any(_is_relative_to(path, root) for root in allowed_roots):
            return None
    except Exception:
        return None
    if not path.is_file():
        return None
    return path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False


def mode_label(value: str) -> str:
    return {
        "preflight": "采集 + 触达预检",
        "collect": "只采集",
        "live_comment": "采集 + 真实评论",
    }.get(value, "采集 + 触达预检")


def normalize_mode(value: str) -> str:
    text = str(value or "").strip()
    return text if text in ALLOWED_MODES else "preflight"


def normalize_volume(value: str) -> str:
    text = str(value or "").strip()
    return text if text in ALLOWED_VOLUMES else "quick"


def normalize_profile_limit(value) -> int:
    return max(1, min(MAX_START_PROFILE_LIMIT, safe_int(value, 3)))


def truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def live_comment_activation_status() -> dict:
    try:
        from ReachOps.runtime_paths import RuntimePaths
        from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate

        activation_path = Path(RuntimePaths.build(str(DATA_DIR)).activation_status_path)
        gate = LiveSubmitAuthorizationGate(str(activation_path))
        decision = gate.authorize_live_submit(
            {
                "id": "web_live_comment_activation_check",
                "action_type": "comment_reply",
                "target_url": "https://www.tiktok.com/@reachops_activation_check",
                "source_path": "https://www.tiktok.com/@reachops_activation_check/video/0",
                "target_username": "reachops_activation_check",
            },
            {"profile_id": "web-live-comment-check", "group_name": "WEB"},
            feature="live_submit",
        )
        activation_payload = build_activation_payload()
        return {
            "allowed": bool(decision.allowed),
            "error_code": decision.error_code,
            "error_message": decision.error_message,
            "activation_status_path": str(activation_path),
            "evidence": decision.evidence,
            "next_actions": activation_payload.get("next_actions") or [],
            "failed_checks": activation_payload.get("failed_checks") or [],
        }
    except Exception as exc:
        return {
            "allowed": False,
            "error_code": "LIVE_SUBMIT_NOT_AUTHORIZED",
            "error_message": str(exc),
            "activation_status_path": str(Path(DATA_DIR) / "config" / "reachops_activation_status.json"),
            "evidence": {},
            "next_actions": ["生成或放置真实激活状态文件，并设置 ActivationStatusPath。"],
            "failed_checks": ["activation_status_read_failed"],
        }


def build_activation_payload() -> dict:
    try:
        from ReachOps.runtime_paths import RuntimePaths
        from tools.reachops_activation_status_check import check_activation_status
        from tools.reachops_live_acceptance_status import activation_actions, activation_failed_checks

        activation_path = Path(RuntimePaths.build(str(DATA_DIR)).activation_status_path)
        payload = check_activation_status(activation_path)
        payload["failed_checks"] = activation_failed_checks(payload)
        payload["next_actions"] = activation_actions(payload)
        return payload
    except Exception as exc:
        return {
            "status": "blocked",
            "ready": False,
            "no_browser_started": True,
            "no_submit": True,
            "error": str(exc),
            "activation_status_path": str(Path(DATA_DIR) / "config" / "reachops_activation_status.json"),
            "checks": [],
            "failed_checks": ["activation_status_read_failed"],
            "next_actions": ["检查激活状态文件路径和 JSON 格式。"],
        }


def build_ixbrowser_status_payload() -> dict:
    try:
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        os.environ["REACHOPS_IXBROWSER_API_PORT"] = active_ixbrowser_api_port()
        from ReachOps.workbench.standalone_app import create_ixbrowser_client, require_ixbrowser_response

        client = create_ixbrowser_client()
        base_url = str(getattr(client, "base_url", ""))
        response = require_ixbrowser_response(
            client,
            client.get_group_list(page=1, limit=1),
            "ixbrowser_group_list",
        )
        rows, total = extract_ixbrowser_status_rows(response)
        return {
            "status": "ready",
            "ready": True,
            "base_url": base_url,
            "group_sample_count": len(rows),
            "reported_total": total,
            "no_browser_started": True,
            "no_submit": True,
            "next_actions": ["ixBrowser Local API 已连通，可以点击“刷新分组”读取配置列表。"],
        }
    except Exception as exc:
        error, detail = normalize_group_refresh_error(str(exc))
        return {
            "status": "blocked",
            "ready": False,
            "base_url": ix_browser_default_base_url(),
            "error": error,
            "error_detail": detail,
            "no_browser_started": True,
            "no_submit": True,
            "next_actions": ixbrowser_status_next_actions(error),
        }


def ixbrowser_status_next_actions(error: str) -> list[str]:
    actions = [
        "确认 ixBrowser 客户端已启动，并在 ixBrowser 设置中开启 Local API。",
        "确认本机可访问默认地址 http://127.0.0.1:53200/api/v2/；如果 ixBrowser 使用其他端口，先设置 REACHOPS_IXBROWSER_API_PORT 后重启 Web UI。",
        "Local API 连通后，回到网页端点击“刷新分组”，确认分组列表和每组账号数显示完整。",
    ]
    if "超时" in str(error or ""):
        actions.insert(1, "Local API 已有响应但读取超时，检查 ixBrowser 是否繁忙或配置列表过大。")
    return actions


def ix_browser_default_base_url() -> str:
    target = str(os.environ.get("REACHOPS_IXBROWSER_API_TARGET") or "127.0.0.1").strip() or "127.0.0.1"
    port = active_ixbrowser_api_port()
    return f"http://{target}:{port}/api/v2/"


def active_ixbrowser_api_port() -> str:
    persisted = load_ixbrowser_api_port_setting()
    return str(
        IXBROWSER_API_PORT_OVERRIDE
        or persisted
        or os.environ.get("REACHOPS_IXBROWSER_API_PORT")
        or os.environ.get("IXBROWSER_API_PORT")
        or "53200"
    ).strip()


def load_web_settings() -> dict:
    try:
        return json.loads(WEB_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_web_settings(settings: dict):
    WEB_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def write_latest_groups_payload(payload: dict):
    try:
        payload = dict(payload or {})
        groups = [dict(row) for row in (payload.get("groups") or []) if isinstance(row, dict)]
        if not groups:
            return
        if groups and LATEST_GROUPS_PATH.exists():
            try:
                previous = json.loads(LATEST_GROUPS_PATH.read_text(encoding="utf-8"))
            except Exception:
                previous = {}
            previous_groups = {
                str(row.get("group_id") or row.get("name") or ""): row
                for row in (previous.get("groups") or [])
                if isinstance(row, dict)
            }
            merged_groups = []
            for row in groups:
                key = str(row.get("group_id") or row.get("name") or "")
                old = previous_groups.get(key) or {}
                if old.get("count_known") and not row.get("count_known"):
                    row["count"] = int(old.get("count") or 0)
                    row["count_known"] = True
                    row["count_label"] = str(old.get("count_label") or f"{row['count']}账号")
                    row["count_status"] = str(old.get("count_status") or "known")
                    row["count_source"] = str(old.get("count_source") or "cached_known_count")
                merged_groups.append(row)
            payload["groups"] = merged_groups
            known_total = sum(int(row.get("count") or 0) for row in merged_groups if row.get("count_known"))
            if known_total and int(payload.get("profile_count") or 0) < known_total:
                payload["profile_count"] = known_total
            payload["known_group_count"] = len([row for row in merged_groups if row.get("count_known")])
        LATEST_GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_GROUPS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def cached_groups_payload_with_error(error: str, detail: str) -> dict:
    global GROUP_CACHE
    cached = GROUP_CACHE if GROUP_CACHE.get("groups") else {}
    if not cached:
        try:
            previous = json.loads(LATEST_GROUPS_PATH.read_text(encoding="utf-8"))
            if previous.get("groups"):
                cached = previous
        except Exception:
            cached = {}
    if cached.get("groups"):
        GROUP_CACHE = dict(cached)
        GROUP_CACHE["loaded_at"] = time.time()
        GROUP_CACHE["error"] = error
        GROUP_CACHE["error_detail"] = detail
        GROUP_CACHE["stale_cache"] = True
        return GROUP_CACHE
    GROUP_CACHE = {
        "loaded_at": time.time(),
        "groups": [],
        "error": error,
        "error_detail": detail,
        "stale_cache": False,
    }
    return GROUP_CACHE


def known_group_count(payload: dict) -> int:
    return len([row for row in (payload.get("groups") or []) if isinstance(row, dict) and row.get("count_known")])


def all_group_counts_known(payload: dict) -> bool:
    groups = [row for row in (payload.get("groups") or []) if isinstance(row, dict)]
    return bool(groups) and known_group_count(payload) == len(groups)


def normalize_group_count_payload(payload: dict) -> dict:
    data = dict(payload or {})
    groups = [row for row in data.get("groups") or [] if isinstance(row, dict)]
    known_total = sum(safe_int(row.get("count"), 0) for row in groups if row.get("count_known"))
    if known_total and safe_int(data.get("profile_count"), 0) < known_total:
        data["profile_count"] = known_total
    if groups:
        data["known_group_count"] = len([row for row in groups if row.get("count_known")])
        data["all_group_counts_known"] = all_group_counts_known(data)
    return data


def group_cache_quality(payload: dict) -> tuple[int, int]:
    return known_group_count(payload), safe_int((payload or {}).get("profile_count"), 0)


def read_cached_groups_payload() -> dict:
    global GROUP_CACHE
    cached = GROUP_CACHE if GROUP_CACHE.get("groups") else {}
    try:
        previous = json.loads(LATEST_GROUPS_PATH.read_text(encoding="utf-8"))
        if previous.get("groups") and group_cache_quality(previous) > group_cache_quality(cached):
            cached = previous
            GROUP_CACHE = dict(previous)
    except Exception:
        pass
    return dict(cached) if cached.get("groups") else {}


def apply_cached_counts_to_live_groups(groups: list[dict], cached_payload: dict | None = None) -> list[dict]:
    cached = cached_payload or read_cached_groups_payload()
    cached_rows = [row for row in (cached.get("groups") or []) if isinstance(row, dict)]
    if not groups or not cached_rows:
        return groups
    by_group_id = {str(row.get("group_id") or ""): row for row in cached_rows if row.get("group_id")}
    by_name = {str(row.get("name") or row.get("group_name") or "").strip().lower(): row for row in cached_rows}
    merged = []
    for row in groups:
        live = dict(row)
        if live.get("count_known"):
            merged.append(live)
            continue
        group_id = str(live.get("group_id") or "")
        group_name = str(live.get("group_name") or live.get("name") or "").strip().lower()
        cached_row = by_group_id.get(group_id) or by_name.get(group_name) or {}
        if cached_row.get("count_known"):
            live["count"] = safe_int(cached_row.get("count"), 0)
            live["count_known"] = True
            live["count_source"] = "cached_known_count_after_live_group_list"
        merged.append(live)
    return merged


def group_refresh_background_active() -> bool:
    with GROUP_REFRESH_STATE_LOCK:
        return bool(GROUP_REFRESH_THREAD and GROUP_REFRESH_THREAD.is_alive())


def payload_with_background_refresh_state(payload: dict, *, refresh_started: bool = False) -> dict:
    data = normalize_group_count_payload(payload)
    if data.get("groups") and (refresh_started or group_refresh_background_active()):
        data["background_refresh"] = True
        data["refresh_started"] = bool(refresh_started)
        if data.get("error") or not all_group_counts_known(data):
            data["stale_cache"] = True
            data["operator_notice"] = "正在后台刷新 ixBrowser 配置列表，当前保留上次成功读取结果。"
        else:
            data["stale_cache"] = False
            data["operator_notice"] = "ixBrowser 分组和数量已可用，后台刷新继续校验最新配置。"
    return data


def cached_groups_payload_for_read(payload: dict) -> dict:
    data = normalize_group_count_payload(payload)
    if data.get("groups") and known_group_count(data):
        data["error"] = ""
        data["error_detail"] = ""
        if not group_refresh_background_active():
            data["stale_cache"] = False
            data["background_refresh"] = False
            data["refresh_started"] = False
    return data


def run_group_refresh_background():
    try:
        payload = load_groups(refresh=True, allow_async=False)
        append_group_refresh_log(payload, refresh=True)
    except Exception as exc:
        error, detail = normalize_group_refresh_error(str(exc))
        append_group_refresh_log(cached_groups_payload_with_error(error, detail), refresh=True)


def start_group_refresh_background() -> bool:
    global GROUP_REFRESH_THREAD
    with GROUP_REFRESH_STATE_LOCK:
        if GROUP_REFRESH_THREAD and GROUP_REFRESH_THREAD.is_alive():
            return False
        GROUP_REFRESH_THREAD = threading.Thread(
            target=run_group_refresh_background,
            name="reachops-group-refresh",
            daemon=True,
        )
        GROUP_REFRESH_THREAD.start()
        return True


def load_ixbrowser_api_port_setting() -> str:
    settings = load_web_settings()
    return str(settings.get("ixbrowser_api_port") or "").strip()


def persist_ixbrowser_api_port_setting(port: int):
    settings = load_web_settings()
    settings["ixbrowser_api_port"] = int(port)
    settings["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_web_settings(settings)


def initialize_ixbrowser_api_port_from_settings():
    global IXBROWSER_API_PORT_OVERRIDE
    port = load_ixbrowser_api_port_setting()
    if port:
        IXBROWSER_API_PORT_OVERRIDE = port
        os.environ["REACHOPS_IXBROWSER_API_PORT"] = port


def apply_ixbrowser_api_port(port: str | int) -> dict:
    global GROUP_CACHE, IXBROWSER_API_PORT_OVERRIDE
    text = str(port or "").strip()
    if not text.isdigit():
        return {"status": "rejected", "error": "invalid_ixbrowser_api_port", "message": "端口必须是 1-65535 的数字。"}
    number = int(text)
    if number < 1 or number > 65535:
        return {"status": "rejected", "error": "invalid_ixbrowser_api_port", "message": "端口必须是 1-65535 的数字。"}
    IXBROWSER_API_PORT_OVERRIDE = str(number)
    os.environ["REACHOPS_IXBROWSER_API_PORT"] = str(number)
    persist_ixbrowser_api_port_setting(number)
    GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
    append_web_log(f"CONFIG ixbrowser_api_port_set port={number} source=web_ui no_browser_started=true no_submit=true")
    return {
        "status": "saved",
        "port": number,
        "base_url": ix_browser_default_base_url(),
        "no_browser_started": True,
        "no_submit": True,
        "next_actions": ["端口已应用。点击“刷新分组”重新读取 ixBrowser 配置列表。"],
    }


def extract_ixbrowser_status_rows(response) -> tuple[list[dict], int]:
    try:
        from ReachOps.workbench.standalone_app import extract_ixbrowser_rows

        return extract_ixbrowser_rows(response)
    except Exception:
        if isinstance(response, list):
            return response, len(response)
        return [], 0


def skipped_profile_snapshot(reason: str = "web_status_read_only") -> dict:
    return {
        "available": False,
        "error": f"profile snapshot skipped: {reason}",
        "profiles": [],
        "groups": [],
        "profile_count": 0,
        "group_count": 0,
    }


def build_final_status_payload() -> dict:
    try:
        from tools.reachops_authorization_handoff_bundle import build_handoff_bundle, verify_handoff_bundle
        from tools.reachops_live_acceptance_status import build_status, write_json_report, write_markdown_report

        payload = build_status(
            argparse.Namespace(
                profile_group="United States",
                profile_ids="",
                profile_limit=3,
                max_pages=50,
                profile_scan_timeout=8,
                target="anti aging serum",
                comment_video_url="",
                target_profile_url="",
                dm_profile_url="",
                target_username="",
                activation_status_path="",
                activation_template_path="",
                local_inputs_path=str(ACCEPTANCE_INPUT_LOCAL_PATH),
                acceptance_reports_dir="",
                limit=3,
                allow_pressure_submit="",
                confirm_authorized_targets=False,
                require_final=False,
            ),
            snapshot=skipped_profile_snapshot(),
        )
        existing_commands = [str(item) for item in payload.get("verification_commands") or [] if str(item or "").strip()]
        payload["verification_commands"] = list(dict.fromkeys(existing_commands + list(FINAL_VERIFICATION_COMMANDS)))
        payload["report_path"] = str(write_markdown_report(payload, live_acceptance_readiness_report_path()))
        payload["json_report_path"] = str(write_json_report(payload, live_acceptance_readiness_json_path()))
        handoff = build_handoff_bundle(
            argparse.Namespace(
                output_path=str(DATA_DIR / "reports/acceptance_remediation/latest_reachops_authorization_handoff.zip"),
                profile_group="United States",
                profile_ids="",
                profile_limit=3,
                max_pages=50,
                profile_scan_timeout=8,
                target="anti aging serum",
                comment_video_url="",
                target_profile_url="",
                dm_profile_url="",
                target_username="",
                activation_status_path="",
                activation_template_path="",
                local_inputs_path=str(ACCEPTANCE_INPUT_LOCAL_PATH),
                acceptance_reports_dir="",
                limit=3,
                allow_pressure_submit="",
                confirm_authorized_targets=False,
            ),
            snapshot=skipped_profile_snapshot("authorization_handoff_web_status"),
        )
        payload["handoff_bundle_path"] = str(handoff.get("bundle_path") or "")
        payload["handoff_bundle_size"] = int(handoff.get("size") or 0)
        payload["handoff_bundle_verification"] = verify_handoff_bundle(payload["handoff_bundle_path"])
        payload["mvp_acceptance"] = summarize_mvp_acceptance()
        payload["goal_delivery"] = summarize_goal_delivery()
        payload["two_phase_acceptance"] = summarize_two_phase_acceptance()
        goal_delivery = payload["goal_delivery"] if isinstance(payload.get("goal_delivery"), dict) else {}
        final_blockers = goal_delivery.get("final_delivery_blockers") if isinstance(goal_delivery.get("final_delivery_blockers"), list) else []
        payload["final_delivery_evidence_plan"] = (
            goal_delivery.get("final_delivery_evidence_plan")
            if isinstance(goal_delivery.get("final_delivery_evidence_plan"), dict)
            else fallback_final_delivery_evidence_plan(final_blockers)
        )
        evidence_bundle = build_current_evidence_bundle()
        product_capability = (
            evidence_bundle.get("product_capability_summary")
            if isinstance(evidence_bundle.get("product_capability_summary"), dict)
            else {}
        )
        product_development_goals = (
            evidence_bundle.get("product_development_goals")
            if isinstance(evidence_bundle.get("product_development_goals"), dict)
            else {}
        )
        delivery_boundary = build_delivery_boundary_payload(
            product_capability=product_capability,
            product_development_goals=product_development_goals,
            final_status=payload,
        )
        payload["delivery_boundary"] = delivery_boundary
        payload["delivery_boundary_status"] = str(delivery_boundary.get("status") or "")
        payload["local_product_capability_ready"] = bool(delivery_boundary.get("local_product_capability_ready"))
        payload["product_capability_ready"] = bool(delivery_boundary.get("product_capability_ready"))
        payload["product_development_ready"] = bool(delivery_boundary.get("product_development_ready"))
        payload["external_validation_pending"] = bool(delivery_boundary.get("external_validation_pending"))
        payload["windows_final_artifacts_pending"] = bool(delivery_boundary.get("windows_final_artifacts_pending"))
        payload["pending_scopes"] = delivery_boundary.get("pending_scopes") or []
        payload["product_capability_summary"] = product_capability
        payload["product_development_goals"] = product_development_goals
        return payload
    except Exception as exc:
        return {
            "status": "blocked",
            "final_delivery_ready": False,
            "no_browser_started": True,
            "no_submit": True,
            "error": str(exc),
            "blocked_reasons": ["最终验收状态读取失败。"],
            "failed_checks": ["final_status:read_failed"],
            "next_required_actions": ["检查 tools/reachops_live_acceptance_status.py 是否可运行。"],
            "verification_commands": list(FINAL_VERIFICATION_COMMANDS),
        }


def acceptance_input_template_bytes() -> bytes:
    return ACCEPTANCE_INPUT_TEMPLATE_PATH.read_bytes()


def write_acceptance_input_readiness_report() -> dict:
    try:
        from tools.reachops_live_acceptance_status import build_status, write_markdown_report

        status = build_status(
            argparse.Namespace(
                profile_group="United States",
                profile_ids="",
                profile_limit=3,
                max_pages=50,
                profile_scan_timeout=8,
                target="anti aging serum",
                comment_video_url="",
                target_profile_url="",
                dm_profile_url="",
                target_username="",
                activation_status_path="",
                activation_template_path="",
                local_inputs_path=str(ACCEPTANCE_INPUT_LOCAL_PATH),
                acceptance_reports_dir="",
                limit=3,
                allow_pressure_submit="",
                confirm_authorized_targets=False,
                require_final=False,
            ),
            snapshot=skipped_profile_snapshot("acceptance_input_readiness"),
        )
        status["report_path"] = str(write_markdown_report(status, live_acceptance_readiness_report_path()))
        return status
    except Exception as exc:
        return {
            "status": "blocked",
            "error": str(exc),
            "next_required_actions": ["检查 tools\\reachops_live_acceptance_status.py 是否可运行。"],
        }


def init_acceptance_input_file() -> dict:
    if ACCEPTANCE_INPUT_LOCAL_PATH.exists():
        readiness = write_acceptance_input_readiness_report()
        return {
            "status": "already_exists",
            "created": False,
            "path": str(ACCEPTANCE_INPUT_LOCAL_PATH),
            "no_browser_started": True,
            "no_submit": True,
            "readiness": readiness,
            "report_path": readiness.get("report_path", ""),
            "next_required_actions": [
                "打开 tools\\reachops_acceptance_inputs.local.ps1，填入已授权 TikTok 目标和真实激活状态路径。",
                "查看授权准备报告，按字段状态替换占位值并确认激活状态。",
            ],
        }
    ACCEPTANCE_INPUT_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCEPTANCE_INPUT_LOCAL_PATH.write_bytes(acceptance_input_template_bytes())
    readiness = write_acceptance_input_readiness_report()
    return {
        "status": "created",
        "created": True,
        "path": str(ACCEPTANCE_INPUT_LOCAL_PATH),
        "no_browser_started": True,
        "no_submit": True,
        "readiness": readiness,
        "report_path": readiness.get("report_path", ""),
        "next_required_actions": [
            "打开 tools\\reachops_acceptance_inputs.local.ps1，替换所有占位值。",
            "填入已授权 TikTok 视频、主页、目标用户名和真实激活状态路径。",
            "保存后刷新最终交付门禁，再运行 readiness/preflight。",
        ],
    }


def is_local_api_host(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith("[::1]"):
        return text == "[::1]" or text.startswith("[::1]:")
    if text == "::1":
        return True
    if "://" in text:
        host = urlparse(text).hostname or ""
    elif text in LOCAL_API_HOSTS:
        host = text
    elif ":" in text and text.count(":") == 1:
        host = text.rsplit(":", 1)[0]
    else:
        host = text
    return host.strip("[]") in LOCAL_API_HOSTS


def normalize_local_bind_host(value: str) -> str:
    text = str(value or "").strip().lower()
    if "://" in text:
        text = urlparse(text).hostname or ""
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    if ":" in text and text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    if not is_local_api_host(text):
        raise ValueError("ReachOps Web UI only supports local loopback hosts: 127.0.0.1, localhost, ::1")
    return text.strip("[]")


def format_url_host(host: str) -> str:
    text = str(host or "").strip("[]")
    if ":" in text:
        return f"[{text}]"
    return text


def volume_limits(volume: str) -> tuple[int, int]:
    return {
        "quick": (3, 20),
        "standard": (10, 50),
        "stress": (20, 100),
    }.get(volume, (3, 20))


def headless_timeout_seconds(volume: str, profile_limit: int, max_videos: int, max_comments: int) -> int:
    """Budget enough time for real ixBrowser page work while still bounding stuck runs."""
    volume_key = normalize_volume(volume)
    profiles = max(1, int(profile_limit or 1))
    videos = max(1, int(max_videos or 1))
    comments = max(1, int(max_comments or 1))
    estimated = 300 + profiles * 120 + videos * 90 + comments * 3
    minimums = {
        "quick": 900,
        "standard": 1800,
        "stress": 3600,
    }
    maximums = {
        "quick": 1800,
        "standard": 3600,
        "stress": 7200,
    }
    return max(minimums[volume_key], min(maximums[volume_key], estimated))


def build_start_preview(payload: dict | None) -> dict:
    payload = payload or {}
    target = str(payload.get("target") or "")
    volume = normalize_volume(str(payload.get("volume") or "quick"))
    mode = normalize_mode(str(payload.get("mode") or "preflight"))
    profile_limit = normalize_profile_limit(payload.get("profiles"))
    max_videos, max_comments = volume_limits(volume)
    timeout_seconds = headless_timeout_seconds(volume, profile_limit, max_videos, max_comments)
    source_type = str(payload.get("source_type") or payload.get("sourceType") or "auto")
    profile_group = str(payload.get("group") or "United States")
    comment_text = str(payload.get("comment_text") or payload.get("commentText") or "")
    live_confirmed = truthy(payload.get("live_confirm", payload.get("liveConfirm")))
    account_repair_confirmed = truthy(payload.get("account_repair_confirmed", payload.get("accountRepairConfirmed")))
    force_account_recheck = (
        account_repair_confirmed
        and truthy(payload.get("account_gate_blocked", payload.get("accountGateBlocked")))
    )
    submit_policy = "真实评论提交" if mode == "live_comment" and live_confirmed else "预检，不提交"
    gate_state = "分组未刷新"
    if payload.get("group_list_ready") or payload.get("groupListReady"):
        gate_state = "可启动"
    if mode == "live_comment" and not live_confirmed:
        gate_state = "需确认真实评论"
    if (payload.get("account_gate_blocked") or payload.get("accountGateBlocked")) and not account_repair_confirmed:
        gate_state = "账号修复后启动"
    blockers: list[str] = []
    next_actions: list[str] = []
    if not target.strip():
        blockers.append("target_required")
        next_actions.append("输入产品链接、关键词、达人主页、视频链接、话题或直播间。")
    if not (payload.get("group_list_ready") or payload.get("groupListReady")):
        blockers.append("profile_group_list_not_ready")
        next_actions.append("先刷新 ixBrowser 配置分组，确认所选分组账号数量。")
    if mode == "live_comment" and not live_confirmed:
        blockers.append("live_comment_confirmation_required")
        next_actions.append("真实评论前必须勾选授权确认。")
    if (payload.get("account_gate_blocked") or payload.get("accountGateBlocked")) and not account_repair_confirmed:
        blockers.append("account_repair_required")
        next_actions.append("执行账号修复计划或勾选已修复账号后重新预检。")
    start_allowed = not blockers
    preflight_decision = {
        "schema_version": "reachops.start_preflight_decision.v1",
        "status": "ready" if start_allowed else "blocked",
        "start_allowed": start_allowed,
        "gate_state": gate_state,
        "blockers": blockers,
        "next_actions": list(dict.fromkeys(next_actions)) or ["可以启动本地执行。"],
        "submit_policy": submit_policy,
        "mode": mode,
        "profile_group": profile_group,
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }
    execution_plan = build_execution_plan(
        target=target,
        source_type=source_type,
        mode=mode,
        profile_group=profile_group,
        volume=volume,
        profile_limit=profile_limit,
        max_videos=max_videos,
        max_comments=max_comments,
        timeout_seconds=timeout_seconds,
        comment_text=comment_text,
        live_confirmed=live_confirmed,
        account_repair_confirmed=account_repair_confirmed,
        force_account_recheck=force_account_recheck,
        base_dir=str(DATA_DIR),
        origin="web_ui_preview",
    )
    autonomous_preflight_forecast = build_autonomous_preflight_forecast(
        execution_plan,
        preflight_decision=preflight_decision,
    )
    execution_plan = attach_autonomous_preflight_forecast(
        execution_plan,
        preflight_decision=preflight_decision,
    )
    return {
        "status": "ok",
        "mode": mode,
        "mode_label": mode_label(mode),
        "volume": volume,
        "volume_label": {"quick": "快速", "standard": "标准", "stress": "压测"}.get(volume, volume),
        "source_type": source_type,
        "profile_group": profile_group,
        "profile_limit": profile_limit,
        "max_videos": max_videos,
        "max_comments": max_comments,
        "timeout_seconds": timeout_seconds,
        "comment_text_present": bool(comment_text.strip()),
        "live_confirmed": live_confirmed,
        "account_repair_confirmed": account_repair_confirmed,
        "execution_plan": execution_plan,
        "execution_plan_schema": execution_plan.get("schema_version"),
        "execution_plan_id": execution_plan.get("plan_id"),
        "runtime_contract": execution_plan.get("runtime_contract") if isinstance(execution_plan.get("runtime_contract"), dict) else {},
        "preflight_decision": preflight_decision,
        "autonomous_preflight_forecast": autonomous_preflight_forecast,
        "start_allowed": start_allowed,
        "blockers": blockers,
        "next_actions": preflight_decision["next_actions"],
        "submit_policy": submit_policy,
        "gate_state": gate_state,
        "no_browser_started": True,
        "no_submit": True,
    }


def build_start_preflight_decision_for_plan(
    execution_plan: dict,
    *,
    start_allowed: bool,
    gate_state: str,
    blockers: list[str] | None = None,
    next_actions: list[str] | None = None,
    no_submit: bool = True,
) -> dict:
    authorization = execution_plan.get("authorization") if isinstance(execution_plan.get("authorization"), dict) else {}
    return {
        "schema_version": "reachops.start_preflight_decision.v1",
        "status": "ready" if start_allowed else "blocked",
        "start_allowed": bool(start_allowed),
        "gate_state": str(gate_state or ("可启动" if start_allowed else "启动前阻断")),
        "blockers": list(blockers or []),
        "next_actions": list(dict.fromkeys(next_actions or [])) or ["可以启动本地执行。"],
        "submit_policy": "真实评论提交"
        if execution_plan.get("mode") == "live_comment" and authorization.get("live_submit_allowed")
        else "预检，不提交",
        "mode": str(execution_plan.get("mode") or ""),
        "profile_group": str(execution_plan.get("profile_group") or ""),
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": bool(no_submit),
    }


def build_start_from_plan_preview(path: str | Path | None = None) -> dict:
    plan_path = Path(path or LATEST_EXECUTION_PLAN_PATH)
    if not plan_path.is_file():
        return {
            "status": "missing",
            "error": "execution_plan_missing",
            "execution_plan_path": str(plan_path),
            "preflight_decision": {
                "schema_version": "reachops.start_preflight_decision.v1",
                "status": "blocked",
                "start_allowed": False,
                "gate_state": "计划缺失",
                "blockers": ["execution_plan_missing"],
                "next_actions": ["先生成或保存 ExecutionPlan，再执行计划重放。"],
                "submit_policy": "预检，不提交",
                "mode": "",
                "profile_group": "",
                "no_ai_token_used": True,
                "no_browser_started": True,
                "no_submit": True,
            },
            "execution_plan_replay": True,
            "no_browser_started": True,
            "no_submit": True,
        }
    try:
        plan = read_execution_plan(plan_path)
        payload = payload_from_execution_plan(plan)
        payload["groupListReady"] = True
        preview = build_start_preview(payload)
        preview["status"] = "ok"
        preview["execution_plan"] = plan
        preview["execution_plan_id"] = plan.get("plan_id")
        preview["execution_plan_schema"] = plan.get("schema_version")
        preview["execution_plan_path"] = str(plan_path)
        preview["execution_plan_replay"] = True
        preview["plan_fingerprint_sha256"] = plan.get("plan_fingerprint_sha256", "")
        preview["replay_source"] = "latest_execution_plan"
        return preview
    except Exception as exc:
        return {
            "status": "failed",
            "error": "execution_plan_invalid",
            "message": str(exc),
            "execution_plan_path": str(plan_path),
            "execution_plan_replay": True,
            "preflight_decision": {
                "schema_version": "reachops.start_preflight_decision.v1",
                "status": "blocked",
                "start_allowed": False,
                "gate_state": "计划无效",
                "blockers": ["execution_plan_invalid"],
                "next_actions": ["修复 ExecutionPlan schema、plan_id 或 fingerprint 后再重放。"],
                "submit_policy": "预检，不提交",
                "mode": "",
                "profile_group": "",
                "no_ai_token_used": True,
                "no_browser_started": True,
                "no_submit": True,
            },
            "no_browser_started": True,
            "no_submit": True,
        }


def build_execution_plan_contract_preview(path: str | Path | None = None) -> dict:
    plan_path = Path(path or LATEST_EXECUTION_PLAN_PATH)
    if not plan_path.is_absolute():
        plan_path = (ROOT_DIR / plan_path).resolve()
    if not plan_path.is_file():
        return {
            "status": "missing",
            "error": "execution_plan_missing",
            "execution_plan_path": str(plan_path),
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
        }
    try:
        plan = read_execution_plan(plan_path)
        before = adversarial_cli_args_for_contract_preview(plan)
        contract = build_execution_plan_runtime_contract(
            plan,
            before,
            source="execution_plan_contract_preview",
            audit_preview=True,
        )
        after = contract.get("after") if isinstance(contract.get("after"), dict) else {}
        limits = plan.get("limits") if isinstance(plan.get("limits"), dict) else {}
        field_matches = {
            "target": after.get("target") == plan.get("target"),
            "source_type": after.get("source_type") == plan.get("source_type"),
            "profile_group": after.get("profile_group") == plan.get("profile_group"),
            "mode": after.get("mode") == plan.get("mode"),
            "volume": after.get("volume") == plan.get("volume"),
            "profile_limit": int(after.get("profile_limit") or 0) == int(limits.get("profile_limit") or 0),
            "max_videos": int(after.get("max_videos") or 0) == int(limits.get("max_videos") or 0),
            "max_comments": int(after.get("max_comments") or 0) == int(limits.get("max_comments") or 0),
            "timeout": int(after.get("timeout") or 0) == int(limits.get("timeout_seconds") or 0),
        }
        all_plan_fields_mapped = all(field_matches.values())
        return {
            "status": "ok" if all_plan_fields_mapped else "failed",
            "schema_version": "reachops.execution_plan_contract_preview.v1",
            "execution_plan_path": str(plan_path),
            "execution_plan": plan,
            "execution_plan_id": plan.get("plan_id", ""),
            "plan_fingerprint_sha256": plan.get("plan_fingerprint_sha256", ""),
            "contract": contract,
            "field_matches": field_matches,
            "all_plan_fields_mapped": all_plan_fields_mapped,
            "uses_headless_runtime_mapper": True,
            "contract_source": "ReachOps.execution_plan.build_execution_plan_runtime_contract",
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
            "next_actions": ["该预览只验证 ExecutionPlan 到运行参数的映射；真实执行仍由 /api/start 启动。"],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error": "execution_plan_contract_preview_failed",
            "message": str(exc),
            "execution_plan_path": str(plan_path),
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
        }


def build_ai_console_payload(payload: dict | None) -> dict:
    payload = payload or {}
    form = payload.get("form") if isinstance(payload.get("form"), dict) else payload
    runtime = {
        "run_session": read_current_run_session(),
        "run_result": read_run_result_payload(),
        "run_session_state": "",
    }
    if runtime["run_session"]:
        runtime["run_session_state"] = str(runtime["run_session"].get("state") or "")
    try:
        runtime["evidence_bundle"] = build_current_evidence_bundle()
    except Exception as exc:
        runtime["evidence_bundle"] = {
            "schema_version": "reachops.evidence_bundle.v1",
            "status": "failed",
            "error": str(exc),
        }
    try:
        runtime["offline_learning"] = build_offline_learning_payload()
    except Exception as exc:
        runtime["offline_learning"] = {
            "schema_version": "reachops.offline_learning.v1",
            "status": "failed",
            "error": str(exc),
            "record_count": 0,
            "records": [],
            "no_ai_token_used": True,
        }
    try:
        runtime["acceptance"] = build_acceptance_payload()
        if isinstance(runtime["acceptance"], dict) and isinstance(runtime["acceptance"].get("operations"), dict):
            runtime["operations"] = runtime["acceptance"].get("operations") or {}
    except Exception as exc:
        runtime["acceptance"] = {
            "client_delivery": {
                "blockers": ["acceptance_status_read_failed"],
                "failed_checks": [str(exc)],
            }
        }
    evidence_bundle = runtime.get("evidence_bundle") if isinstance(runtime.get("evidence_bundle"), dict) else {}
    runtime["delivery_boundary"] = build_delivery_boundary_payload(
        product_capability=evidence_bundle.get("product_capability_summary")
        if isinstance(evidence_bundle.get("product_capability_summary"), dict)
        else {},
        product_development_goals=evidence_bundle.get("product_development_goals")
        if isinstance(evidence_bundle.get("product_development_goals"), dict)
        else {},
    )
    delivery_boundary = runtime["delivery_boundary"] if isinstance(runtime.get("delivery_boundary"), dict) else {}
    if isinstance(delivery_boundary.get("final_delivery_evidence_plan"), dict):
        runtime["final_delivery_evidence_plan"] = delivery_boundary.get("final_delivery_evidence_plan")
    console = LocalAIConsole(base_dir=str(DATA_DIR), max_profile_limit=MAX_START_PROFILE_LIMIT)
    result = console.handle(payload.get("message") or payload.get("text") or "", form=form, runtime=runtime)
    acceptance = runtime.get("acceptance") if isinstance(runtime.get("acceptance"), dict) else {}
    client_delivery = acceptance.get("client_delivery") if isinstance(acceptance.get("client_delivery"), dict) else {}
    if client_delivery:
        result.setdefault("client_delivery", client_delivery)
        next_actions = client_delivery.get("next_actions") if isinstance(client_delivery.get("next_actions"), list) else []
        result.setdefault(
            "client_delivery_summary",
            {
                "status": client_delivery.get("status"),
                "readiness": client_delivery.get("readiness"),
                "acceptance_ready": client_delivery.get("acceptance_ready"),
                "final_delivery_ready": client_delivery.get("final_delivery_ready"),
                "failed_checks": list(client_delivery.get("failed_checks") or []),
                "blocker_count": len(client_delivery.get("blockers") or []),
                "next_action_count": len(next_actions),
                "no_ai_token_used": True,
                "no_browser_started": bool(client_delivery.get("no_browser_started", True)),
                "no_submit": bool(client_delivery.get("no_submit", True)),
            },
        )
    result.setdefault("status", "ok")
    result["no_browser_started"] = True
    result["no_submit"] = True
    return result


def build_current_execution_plan_payload() -> dict:
    path = LATEST_EXECUTION_PLAN_PATH
    if not path.is_file():
        return {
            "status": "missing",
            "schema_version": "reachops.execution_plan.v1",
            "path": str(path),
            "exists": False,
            "no_browser_started": True,
            "no_submit": True,
        }
    try:
        plan = read_execution_plan(path)
        return {
            "status": "ok",
            "schema_version": plan.get("schema_version", "reachops.execution_plan.v1"),
            "exists": True,
            "path": str(path),
            "download_url": "/api/download?path=" + quote(str(path), safe=""),
            "plan_id": plan.get("plan_id", ""),
            "summary": {
                "target": plan.get("target", ""),
                "source_type": plan.get("source_type", ""),
                "mode": plan.get("mode", ""),
                "profile_group": plan.get("profile_group", ""),
                "volume": plan.get("volume", ""),
                "limits": plan.get("limits") or {},
                "authorization": plan.get("authorization") or {},
                "risk_policy": plan.get("risk_policy") or {},
            },
            "execution_plan": plan,
            "no_browser_started": True,
            "no_submit": True,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "schema_version": "reachops.execution_plan.v1",
            "path": str(path),
            "exists": True,
            "error": str(exc),
            "no_browser_started": True,
            "no_submit": True,
        }


def payload_from_execution_plan(plan: dict) -> dict:
    limits = plan.get("limits") if isinstance(plan.get("limits"), dict) else {}
    authorization = plan.get("authorization") if isinstance(plan.get("authorization"), dict) else {}
    ui = plan.get("ui") if isinstance(plan.get("ui"), dict) else {}
    return {
        "target": str(plan.get("target") or ""),
        "sourceType": str(plan.get("source_type") or "auto"),
        "group": str(plan.get("profile_group") or "United States"),
        "mode": str(plan.get("mode") or "preflight"),
        "volume": str(plan.get("volume") or "quick"),
        "profiles": limits.get("profile_limit") or 3,
        "commentText": str(ui.get("comment_text") or ""),
        "liveConfirm": bool(authorization.get("live_confirmed")),
        "accountRepairConfirmed": bool(authorization.get("account_repair_confirmed")),
    }


def build_current_run_session_payload() -> dict:
    recovery = recover_current_run_session_if_interrupted("RUN_SESSION_STATUS_RECOVERY")
    path = Path(CURRENT_RUN_SESSION_PATH) if CURRENT_RUN_SESSION_PATH else LATEST_RUN_SESSION_PATH
    if not path.is_file() and LATEST_RUN_SESSION_PATH.is_file():
        path = LATEST_RUN_SESSION_PATH
    if not path.is_file():
        return {
            "status": "missing",
            "schema_version": "reachops.run_session.v1",
            "path": str(path),
            "exists": False,
            "recovery": recovery,
            "no_browser_started": True,
            "no_submit": True,
        }
    try:
        session = read_run_session(path)
        return {
            "status": "ok",
            "schema_version": session.get("schema_version", "reachops.run_session.v1"),
            "exists": True,
            "path": str(path),
            "download_url": "/api/download?path=" + quote(str(path), safe=""),
            "session_id": session.get("session_id", ""),
            "plan_id": session.get("plan_id", ""),
            "summary": {
                "state": session.get("state", ""),
                "status": session.get("status", ""),
                "pid": session.get("pid", 0),
                "created_at": session.get("created_at", ""),
                "updated_at": session.get("updated_at", ""),
                "started_at": session.get("started_at", ""),
                "completed_at": session.get("completed_at", ""),
                "checkpoint": session.get("checkpoint") or {},
                "control": session.get("control") or {},
                "evidence": session.get("evidence") or {},
                "ai_usage_ledger": session.get("ai_usage_ledger") or {},
                "no_ai_token_during_execution": bool(session.get("no_ai_token_during_execution", True)),
            },
            "ai_usage_ledger": session.get("ai_usage_ledger") or {},
            "execution_runtime_contract": session.get("execution_runtime_contract") or {},
            "recovery": recovery,
            "run_session": session,
            "no_ai_token_used": bool((session.get("ai_usage_ledger") or {}).get("no_ai_token_used", True)),
            "no_browser_started": True,
            "no_submit": True,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "schema_version": "reachops.run_session.v1",
            "path": str(path),
            "exists": True,
            "error": str(exc),
            "recovery": recovery,
            "no_browser_started": True,
            "no_submit": True,
        }


def build_current_evidence_bundle() -> dict:
    try:
        from ReachOps.evidence_bundle import build_evidence_bundle, write_evidence_bundle, write_evidence_markdown

        run_session = read_current_run_session()
        run_session_path = CURRENT_RUN_SESSION_PATH or str(LATEST_RUN_SESSION_PATH if LATEST_RUN_SESSION_PATH.is_file() else "")
        candidate_execution_plan_path = Path(
            str(
                run_session.get("execution_plan_path")
                or (run_session.get("evidence") or {}).get("execution_plan_path")
                or ""
            )
        )
        if not candidate_execution_plan_path.is_file() and LATEST_EXECUTION_PLAN_PATH.is_file():
            candidate_execution_plan_path = LATEST_EXECUTION_PLAN_PATH
        execution_plan_path = str(candidate_execution_plan_path if candidate_execution_plan_path.is_file() else "")
        result_payload = read_run_result_payload()
        log_path = str(result_payload.get("log_path") or (run_session.get("evidence") or {}).get("log_path") or LOG_PATH)
        bundle = build_evidence_bundle(
            base_dir=DATA_DIR,
            execution_plan_path=execution_plan_path,
            run_session_path=run_session_path,
            result_path=str(RESULT_PATH if RESULT_PATH.is_file() else ""),
            log_path=log_path,
            offline_learning_path=str(DATA_DIR / "offline_learning" / "unknown_states.json"),
            extra_artifacts=[
                {"kind": "mvp_acceptance", "label": "MVP acceptance", "path": str(MVP_ACCEPTANCE_SUMMARY_PATH)},
                {"kind": "goal_delivery", "label": "Goal delivery report", "path": str(GOAL_DELIVERY_REPORT_PATH)},
                {"kind": "two_phase_matrix", "label": "Two phase matrix", "path": str(TWO_PHASE_MATRIX_JSON_PATH)},
            ],
        )
        session_id = str(bundle.get("session_id") or "latest_evidence_bundle")
        bundle_path = DATA_DIR / "evidence_bundles" / f"{session_id}.json"
        markdown_path = DATA_DIR / "evidence_bundles" / f"{session_id}.md"
        write_evidence_bundle(bundle, bundle_path, LATEST_EVIDENCE_BUNDLE_PATH)
        write_evidence_markdown(bundle, markdown_path, LATEST_EVIDENCE_BUNDLE_MD_PATH)
        bundle["path"] = str(bundle_path)
        bundle["markdown_path"] = str(markdown_path)
        bundle["latest_path"] = str(LATEST_EVIDENCE_BUNDLE_PATH)
        bundle["latest_markdown_path"] = str(LATEST_EVIDENCE_BUNDLE_MD_PATH)
        return bundle
    except Exception as exc:
        return {
            "schema_version": "reachops.evidence_bundle.v1",
            "status": "failed",
            "error": str(exc),
            "path": str(LATEST_EVIDENCE_BUNDLE_PATH),
            "markdown_path": str(LATEST_EVIDENCE_BUNDLE_MD_PATH),
        }


def build_operator_summary_payload() -> dict:
    bundle = build_current_evidence_bundle()
    operator_summary = bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {}
    return {
        "status": "ok" if operator_summary else "missing",
        "schema_version": operator_summary.get("schema_version", "reachops.operator_summary.v1"),
        "operator_summary": operator_summary,
        "evidence_bundle_id": bundle.get("bundle_id", ""),
        "evidence_bundle_path": bundle.get("path", ""),
        "evidence_bundle_markdown_path": bundle.get("markdown_path", ""),
        "evidence_bundle_download_url": "/api/download?path=" + quote(str(bundle.get("path") or ""), safe="")
        if bundle.get("path")
        else "",
        "evidence_bundle_markdown_download_url": "/api/download?path=" + quote(str(bundle.get("markdown_path") or ""), safe="")
        if bundle.get("markdown_path")
        else "",
        "audit": bundle.get("audit") if isinstance(bundle.get("audit"), dict) else {},
        "ai_usage_summary": bundle.get("ai_usage_summary") if isinstance(bundle.get("ai_usage_summary"), dict) else {},
        "summary": bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {},
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }


def build_product_capability_payload() -> dict:
    bundle = build_current_evidence_bundle()
    product_capability = (
        bundle.get("product_capability_summary") if isinstance(bundle.get("product_capability_summary"), dict) else {}
    )
    product_development_goals = (
        bundle.get("product_development_goals") if isinstance(bundle.get("product_development_goals"), dict) else {}
    )
    delivery_boundary = build_delivery_boundary_payload(
        product_capability=product_capability,
        product_development_goals=product_development_goals,
    )
    return {
        "status": "ok" if product_capability else "missing",
        "schema_version": product_capability.get("schema_version", "reachops.product_capability_summary.v1"),
        "product_capability_summary": product_capability,
        "product_development_goals": product_development_goals,
        "delivery_boundary": delivery_boundary,
        "delivery_boundary_status": str(delivery_boundary.get("status") or ""),
        "local_product_capability_ready": bool(delivery_boundary.get("local_product_capability_ready")),
        "product_capability_ready": bool(delivery_boundary.get("product_capability_ready")),
        "product_development_ready": bool(delivery_boundary.get("product_development_ready")),
        "final_delivery_ready": bool(delivery_boundary.get("final_delivery_ready")),
        "external_validation_pending": bool(delivery_boundary.get("external_validation_pending")),
        "windows_final_artifacts_pending": bool(delivery_boundary.get("windows_final_artifacts_pending")),
        "pending_scopes": delivery_boundary.get("pending_scopes") or [],
        "autonomy_readiness_summary": bundle.get("autonomy_readiness_summary")
        if isinstance(bundle.get("autonomy_readiness_summary"), dict)
        else {},
        "autonomous_execution_summary": bundle.get("autonomous_execution_summary")
        if isinstance(bundle.get("autonomous_execution_summary"), dict)
        else {},
        "operator_summary": bundle.get("operator_summary") if isinstance(bundle.get("operator_summary"), dict) else {},
        "evidence_bundle_id": bundle.get("bundle_id", ""),
        "evidence_bundle_path": bundle.get("path", ""),
        "evidence_bundle_markdown_path": bundle.get("markdown_path", ""),
        "evidence_bundle_download_url": "/api/download?path=" + quote(str(bundle.get("path") or ""), safe="")
        if bundle.get("path")
        else "",
        "evidence_bundle_markdown_download_url": "/api/download?path=" + quote(str(bundle.get("markdown_path") or ""), safe="")
        if bundle.get("markdown_path")
        else "",
        "summary": bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {},
        "audit": bundle.get("audit") if isinstance(bundle.get("audit"), dict) else {},
        "no_ai_token_used": True,
        "no_browser_started": True,
        "no_submit": True,
    }


def build_offline_learning_payload() -> dict:
    try:
        from ReachOps.workbench.offline_learning_ledger import summarize_offline_learning

        payload = summarize_offline_learning(DATA_DIR / "offline_learning" / "unknown_states.json", limit=50)
        payload.setdefault(
            "policy_candidates",
            {
                "schema_version": "reachops.offline_policy_candidates.v1",
                "candidate_count": 0,
                "candidates": [],
                "no_ai_token_used": True,
            },
        )
        payload.setdefault(
            "policy_review_summary",
            {
                "schema_version": "reachops.offline_policy_review.v1",
                "review_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "reviews": [],
                "runtime_auto_apply_count": 0,
                "no_ai_token_used": True,
            },
        )
        payload.setdefault(
            "policy_release_proposal",
            {
                "schema_version": "reachops.offline_policy_release_proposal.v1",
                "approved_count": 0,
                "ready_for_release_count": 0,
                "proposals": [],
                "release_gate": "code_or_policy_release_required",
                "runtime_auto_apply_count": 0,
                "runtime_auto_apply": False,
                "no_ai_token_used": True,
            },
        )
        payload["no_browser_started"] = True
        payload["no_submit"] = True
        return payload
    except Exception as exc:
        return {
            "schema_version": "reachops.offline_learning.v1",
            "status": "failed",
            "error": str(exc),
            "record_count": 0,
            "records": [],
            "policy_candidates": {
                "schema_version": "reachops.offline_policy_candidates.v1",
                "candidate_count": 0,
                "candidates": [],
                "no_ai_token_used": True,
            },
            "policy_review_summary": {
                "schema_version": "reachops.offline_policy_review.v1",
                "review_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "reviews": [],
                "runtime_auto_apply_count": 0,
                "no_ai_token_used": True,
            },
            "policy_release_proposal": {
                "schema_version": "reachops.offline_policy_release_proposal.v1",
                "approved_count": 0,
                "ready_for_release_count": 0,
                "proposals": [],
                "release_gate": "code_or_policy_release_required",
                "runtime_auto_apply_count": 0,
                "runtime_auto_apply": False,
                "no_ai_token_used": True,
            },
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
        }


def review_offline_policy_candidate(payload: dict) -> dict:
    try:
        from ReachOps.workbench.offline_learning_ledger import review_policy_candidate

        result = review_policy_candidate(
            DATA_DIR / "offline_learning" / "unknown_states.json",
            candidate_state=str(payload.get("candidate_state") or ""),
            candidate_action=str(payload.get("candidate_action") or ""),
            decision=str(payload.get("decision") or ""),
            reviewer=str(payload.get("reviewer") or "operator"),
            note=str(payload.get("note") or ""),
        )
        result["status"] = "review_recorded"
        result["offline_learning"] = build_offline_learning_payload()
        result["no_browser_started"] = True
        result["no_submit"] = True
        return result
    except ValueError as exc:
        return {
            "schema_version": "reachops.offline_policy_review.v1",
            "status": "rejected",
            "error": "invalid_policy_review",
            "message": str(exc),
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
        }
    except Exception as exc:
        return {
            "schema_version": "reachops.offline_policy_review.v1",
            "status": "failed",
            "error": "policy_review_failed",
            "message": str(exc),
            "no_ai_token_used": True,
            "no_browser_started": True,
            "no_submit": True,
        }


def run_result_belongs_to_session(run_result: dict, session: dict) -> bool:
    if not isinstance(run_result, dict) or not isinstance(session, dict):
        return False
    result_session = run_result.get("run_session") if isinstance(run_result.get("run_session"), dict) else {}
    result_plan = run_result.get("execution_plan") if isinstance(run_result.get("execution_plan"), dict) else {}
    result_session_id = str(run_result.get("run_session_id") or result_session.get("session_id") or "").strip()
    if result_session_id:
        return result_session_id == str(session.get("session_id") or "").strip()
    result_plan_id = str(run_result.get("plan_id") or result_plan.get("plan_id") or "").strip()
    if result_plan_id:
        return result_plan_id == str(session.get("plan_id") or "").strip()
    return False


def recover_current_run_session_if_interrupted(reason: str = "WEB_UI_RECOVERY") -> dict:
    running = run_is_active()
    raw_run_result = read_run_result_payload()
    session = read_current_run_session()
    if not session:
        return {"recovered": False}
    run_result = raw_run_result if run_result_belongs_to_session(raw_run_result, session) else {}
    session_state = str(session.get("state") or "")
    session_started = parse_utc(str(session.get("started_at") or session.get("created_at") or ""))
    if (
        not running
        and session_state not in TERMINAL_RUN_SESSION_STATES
        and session_started is not None
        and (datetime.now(timezone.utc) - session_started).total_seconds() < 30
    ):
        return {
            "recovered": False,
            "status": "startup_grace",
            "reason": "run_session_startup_grace_period",
            "session_id": session.get("session_id", ""),
        }
    updated, recovery = recover_interrupted_run_session(
        session,
        running=running,
        run_result=run_result,
        last_stage=reason,
        pid=RUN_PROCESS.pid if RUN_PROCESS is not None else int(session.get("pid") or 0),
    )
    if recovery.get("recovered"):
        persist_run_session(updated)
        write_run_result_payload(recovery.get("result") or {})
        append_web_log(
            f"WARN   run_session_recovered_interrupted session={updated.get('session_id')} reason=PROCESS_INTERRUPTED source={reason}"
        )
        finalize_stale_web_batch_if_needed(
            DATA_DIR / "data/growth_intelligence/growth_intelligence.db",
            force=True,
            reason="PROCESS_INTERRUPTED",
        )
    return recovery


def parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def external_headless_process_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "tools/run_reachops_headless_macos.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def finalize_stale_web_batch_if_needed(
    db_path: Path,
    *,
    force: bool = False,
    reason: str = "HEADLESS_PROCESS_NOT_RUNNING",
):
    if (not force and (run_is_active() or external_headless_process_running())) or not db_path.exists():
        return
    now_dt = datetime.now(timezone.utc)
    now = now_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            batch = conn.execute(
                """
                SELECT *
                FROM collection_batches
                WHERE status IN ('running', 'pending')
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
            if not batch:
                return
            updated = parse_utc(str(batch["updated_at"] or batch["created_at"] or ""))
            if not force and updated and (now_dt - updated).total_seconds() < 120:
                return
            try:
                config = json.loads(batch["config_json"] or "{}")
            except Exception:
                config = {}
            quick_send = config.get("quick_send") if isinstance(config, dict) else {}
            if not isinstance(quick_send, dict) or not quick_send.get("enabled"):
                return
            batch_id = str(batch["id"] or "")
            total = int(batch["total_sources"] or 0)
            processed = int(batch["processed_sources"] or 0)
            existing_failed = int(batch["failed_sources"] or 0)
            remaining = max(0, total - processed - existing_failed)
            candidate_row = conn.execute(
                "SELECT COUNT(*) AS count FROM candidate_users WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            candidate_count = int((candidate_row["count"] if candidate_row else 0) or 0)
            final_status = "partial_failed" if processed > 0 or candidate_count > 0 else "failed"
            failed = existing_failed + remaining
            conn.execute(
                """
                UPDATE collection_tasks
                SET status='failed', error_code='RUN_INTERRUPTED',
                    error_message=?,
                    completed_at=COALESCE(completed_at, ?), updated_at=?
                WHERE batch_id=? AND status IN ('pending', 'running')
                """,
                (f"Execution interrupted by {reason}", now, now, batch_id),
            )
            conn.execute(
                """
                UPDATE collection_batches
                SET status=?, failed_sources=?, completed_at=COALESCE(completed_at, ?), updated_at=?
                WHERE id=?
                """,
                (final_status, failed, now, now, batch_id),
            )
            conn.execute(
                """
                INSERT INTO growth_events (id, event, entity_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"ge_web_{int(time.time() * 1000)}",
                    "collection_batch_interrupted_by_web_ui",
                    batch_id,
                    json.dumps(
                        {
                            "reason": reason,
                            "status": final_status,
                            "processed_sources": processed,
                            "failed_sources": failed,
                            "candidate_count": candidate_count,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        append_web_log(
            f"WARN   campaign finalized_stale_batch batch={batch_id} status={final_status} "
            f"reason={reason} processed={processed} failed={failed} candidates={candidate_count}"
        )
    except Exception as exc:
        append_web_log(f"WARN   campaign finalize_stale_batch_failed error={exc}")


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


def html_page() -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ReachOps 统一控制台</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#151719; --surface:#202428; --surface2:#111315; --line:#343b42;
      --text:#f4f6f8; --muted:#9aa6b2; --blue:#2f7df6; --green:#42d66f;
      --amber:#f3c15f; --red:#ff6961; --cyan:#55c7d9;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:14px -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; }}
    header {{ min-height:68px; display:flex; align-items:center; justify-content:space-between; gap:18px; padding:10px 20px; border-bottom:1px solid var(--line); background:#191d20; }}
    h1 {{ margin:0; font-size:18px; font-weight:800; letter-spacing:0; }}
    .sub {{ color:var(--muted); font-size:12px; }}
    .brandBlock {{ display:flex; align-items:center; gap:12px; min-width:0; }}
    .brandMark {{ width:34px; height:34px; border-radius:8px; border:1px solid #46515c; background:#111519; display:grid; place-items:center; color:#55c7d9; font-weight:900; box-shadow:inset 0 0 0 1px rgba(255,255,255,.03); flex:0 0 auto; }}
    .brandText {{ min-width:0; }}
    .clientType {{ display:inline-flex; align-items:center; height:22px; padding:0 7px; margin-left:8px; border:1px solid #315d3c; border-radius:999px; background:#152017; color:#a4f3b9; font-size:11px; vertical-align:1px; }}
    .headerStatus {{ display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }}
    .versionPill {{ color:#9fb8e8; border-color:#365782; background:#172232; }}
    main {{ display:grid; grid-template-columns:218px minmax(0,1fr); min-height:calc(100vh - 68px); min-width:0; }}
    nav {{ border-right:1px solid var(--line); padding:14px; background:#181b1e; display:grid; align-content:start; gap:8px; }}
    .tab {{ border:1px solid transparent; background:transparent; color:var(--muted); height:38px; border-radius:7px; text-align:left; padding:0 12px; cursor:pointer; font-weight:600; min-width:0; }}
    .tab.active {{ background:#242a30; color:var(--text); border-color:var(--line); }}
    .work {{ padding:16px 18px; display:grid; gap:14px; align-content:start; min-width:0; }}
    .controlPanel {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:12px; display:grid; gap:10px; min-width:0; }}
    .clientRuntimeStrip {{ display:none; }}
    .runtimeContractItem {{ border-left:3px solid #46515c; padding:2px 8px; min-width:0; }}
    .runtimeContractItem.ok {{ border-left-color:var(--green); }}
    .runtimeContractItem.warn {{ border-left-color:var(--amber); }}
    .runtimeContractItem span {{ display:block; color:var(--muted); font-size:11px; line-height:1.25; }}
    .runtimeContractItem b {{ display:block; margin-top:5px; overflow-wrap:anywhere; line-height:1.25; }}
    .taskForm {{ display:grid; gap:12px; min-width:0; }}
    .taskForm label {{ min-width:0; }}
    .taskParams {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(176px,1fr)); gap:10px; align-items:end; min-width:0; }}
    .taskActions {{ display:grid; grid-template-columns:minmax(180px,1fr) repeat(3,minmax(86px,.42fr)); gap:10px; align-items:end; }}
    .secondaryActions {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding-top:2px; }}
    .secondaryActions button {{ height:32px; padding:0 10px; font-size:12px; color:var(--muted); background:#20262b; }}
    label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; }}
    input, select {{ height:38px; border:1px solid var(--line); border-radius:7px; background:#2a3036; color:var(--text); padding:0 11px; font-size:14px; min-width:0; }}
    .groupControl {{ display:grid; grid-template-columns:minmax(0,1fr) 96px; gap:8px; align-items:center; }}
    .groupControl select {{ width:100%; }}
    .groupControl button {{ padding:0 9px; white-space:nowrap; }}
    .checkLabel {{ min-height:38px; align-content:end; }}
    .checkLabel span {{ display:flex; align-items:center; gap:7px; height:38px; border:1px solid var(--line); border-radius:7px; background:#2a3036; padding:0 9px; color:var(--text); font-size:12px; font-weight:700; }}
    .checkLabel input {{ width:16px; height:16px; padding:0; margin:0; }}
    button {{ height:38px; border:1px solid var(--line); border-radius:7px; background:#2d343a; color:var(--text); padding:0 12px; font-weight:700; cursor:pointer; }}
    button.primary {{ background:var(--blue); border-color:var(--blue); color:white; }}
    button.warn {{ background:#3f321b; border-color:#6c5528; color:#ffd887; }}
    button.okBtn {{ background:#1c3d27; border-color:#2f6a42; color:#a4f3b9; }}
    button:disabled {{ opacity:.55; cursor:not-allowed; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(106px,1fr)); gap:10px; }}
    .metric,.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; min-width:0; }}
    .metric {{ padding:11px 12px; min-height:78px; }}
    .metric span {{ color:var(--muted); font-size:12px; display:block; }}
    .metric b {{ display:block; font-size:24px; line-height:1.2; margin-top:7px; }}
    .two {{ display:grid; grid-template-columns:390px minmax(0,1fr); gap:14px; min-width:0; }}
    .panel h2 {{ margin:0; padding:11px 13px; font-size:14px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:8px; align-items:center; }}
    .panel .body {{ padding:12px 13px; min-width:0; overflow-x:auto; }}
    .stack {{ display:grid; gap:9px; }}
    .row {{ display:grid; grid-template-columns:120px 1fr; gap:10px; align-items:center; min-height:28px; }}
    .row span:first-child {{ color:var(--muted); }}
    .row b {{ min-width:0; overflow-wrap:anywhere; }}
    .inlineConfig {{ display:grid; grid-template-columns:minmax(0,1fr) 72px; gap:8px; align-items:center; }}
    .inlineConfig input {{ height:32px; }}
    .inlineConfig button {{ height:32px; padding:0 8px; }}
	    .groupDetails {{ display:none; }}
	    .groupDetails.hasContent {{ display:block; border:1px solid #2c3540; border-radius:8px; background:#15191d; padding:8px; }}
	    .selectedGroupBar {{ display:grid; grid-template-columns:minmax(0,1.4fr) minmax(118px,.55fr) minmax(96px,.45fr); gap:8px; align-items:center; border:1px solid #314151; border-radius:8px; background:#151c22; padding:9px 10px; min-width:0; }}
	    .selectedGroupBar .barLabel {{ color:var(--muted); font-size:11px; margin-bottom:3px; }}
	    .selectedGroupBar b {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
	    .selectedGroupBar .count {{ color:var(--green); font-size:18px; }}
	    .selectedGroupBar .unknown {{ color:var(--amber); }}
	    .groupItem {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; border:1px solid #303941; background:#171b1f; border-radius:7px; padding:8px 9px; min-width:0; }}
    .groupItem.active {{ border-color:#5b8fdd; background:#182333; }}
    .groupName {{ font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .groupMeta {{ color:var(--muted); font-size:11px; margin-top:3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .groupQty {{ justify-self:end; font-weight:900; color:var(--text); white-space:nowrap; }}
    .groupQty.unknown {{ color:var(--amber); font-size:12px; }}
    .notice {{ border:1px solid #3b454e; border-radius:8px; padding:10px 11px; background:#171b1f; display:grid; gap:7px; }}
    .notice.blocked {{ border-color:#6b3434; background:#201718; }}
    .notice.ready {{ border-color:#315d3c; background:#152017; }}
    .notice strong {{ font-size:13px; }}
    .notice ul {{ margin:0; padding-left:18px; color:var(--muted); line-height:1.5; }}
    .copyNotice {{ border:1px solid #314151; border-radius:8px; background:#151c22; padding:10px 12px; display:grid; grid-template-columns:minmax(160px,.4fr) minmax(260px,1fr); gap:8px; align-items:center; }}
    .copyNotice strong {{ font-size:13px; }}
    .copyNotice span {{ color:var(--muted); line-height:1.45; }}
    .aiConsole {{ border:1px solid #314151; border-radius:8px; background:#171b1f; display:grid; grid-template-columns:minmax(260px,.85fr) minmax(280px,1.15fr); gap:10px; padding:12px; min-width:0; }}
    .aiConsoleTalk {{ display:grid; grid-template-rows:auto minmax(120px,1fr) auto; gap:9px; min-width:0; }}
    .aiConsoleHead {{ display:flex; justify-content:space-between; align-items:center; gap:8px; min-width:0; }}
    .aiConsoleHead strong {{ font-size:14px; }}
    .aiConsoleLog {{ min-height:128px; max-height:220px; overflow:auto; display:grid; align-content:start; gap:7px; padding:2px; }}
    .aiBubble {{ border:1px solid #303941; border-radius:8px; background:#20262b; padding:8px 9px; line-height:1.45; overflow-wrap:anywhere; }}
    .aiBubble.operator {{ background:#182333; border-color:#345273; }}
    .aiBubble.system {{ background:#152017; border-color:#315d3c; }}
    .aiConsoleQuick {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr)); gap:7px; }}
    .aiConsoleQuick button {{ min-height:34px; padding:7px 9px; }}
    .aiConsoleInput {{ display:grid; grid-template-columns:minmax(0,1fr) 76px; gap:8px; align-items:end; }}
    textarea {{ min-height:64px; resize:vertical; border:1px solid var(--line); border-radius:7px; background:#2a3036; color:var(--text); padding:9px 10px; font:14px -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; min-width:0; }}
    .aiConsolePlan {{ border:1px solid #303941; border-radius:8px; background:#15191d; padding:10px; display:grid; align-content:start; gap:8px; min-width:0; }}
    .aiPlanGrid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr)); gap:7px; }}
    .aiPlanItem {{ border:1px solid #303941; border-radius:7px; background:#171b1f; padding:8px 9px; min-height:54px; }}
    .aiPlanItem span {{ display:block; color:var(--muted); font-size:11px; }}
    .aiPlanItem b {{ display:block; margin-top:5px; overflow-wrap:anywhere; }}
    .policyReview {{ border:1px solid #303941; border-radius:8px; background:#171b1f; padding:9px; display:grid; gap:7px; }}
    .policyReviewHead {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
    .policyReviewHead strong {{ font-size:13px; }}
    .policyReviewBody {{ color:var(--muted); line-height:1.45; overflow-wrap:anywhere; }}
    .policyReviewActions {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }}
    .machineActions {{ border:1px solid #314151; border-radius:8px; background:#12191f; padding:9px 10px; display:grid; gap:6px; }}
    .machineActions strong {{ font-size:12px; color:var(--cyan); }}
    .machineActions ul {{ margin:0; padding-left:18px; color:var(--muted); line-height:1.45; }}
    .advancedPanel {{ border:1px solid var(--line); border-radius:8px; background:#171b1f; overflow:hidden; }}
    .advancedPanel summary {{ cursor:pointer; list-style:none; padding:11px 13px; font-weight:800; display:flex; justify-content:space-between; gap:10px; align-items:center; }}
    .advancedPanel summary::-webkit-details-marker {{ display:none; }}
    .advancedPanel summary span {{ color:var(--muted); font-size:12px; font-weight:600; }}
    .advancedPanel[open] summary {{ border-bottom:1px solid var(--line); }}
    .advancedBody {{ padding:12px; display:grid; gap:12px; }}
    .hourglassPanel {{ position:relative; min-height:360px; border:1px solid #314151; border-radius:8px; overflow:hidden; background:radial-gradient(circle at 50% 18%, rgba(85,199,217,.16), transparent 28%), linear-gradient(180deg,#151c22 0%,#111519 100%); display:grid; grid-template-columns:minmax(260px,.9fr) minmax(300px,1.1fr); gap:12px; padding:14px; }}
    .hourglassStage {{ position:relative; min-height:330px; border:1px solid #2d3944; border-radius:8px; background:rgba(12,15,18,.46); overflow:hidden; }}
    .hourglassGlass {{ position:absolute; inset:18px 30px; clip-path:polygon(18% 0,82% 0,57% 45%,57% 55%,82% 100%,18% 100%,43% 55%,43% 45%); border:1px solid rgba(159,184,232,.34); background:linear-gradient(180deg,rgba(47,125,246,.08),rgba(66,214,111,.05)); }}
    .hourglassNeck {{ position:absolute; left:50%; top:46%; width:46px; height:32px; transform:translateX(-50%); border:1px solid #3d5366; border-radius:999px; background:#11181f; box-shadow:0 0 20px rgba(85,199,217,.18); }}
    .particle {{ position:absolute; width:7px; height:7px; border-radius:50%; opacity:.9; box-shadow:0 0 12px currentColor; transform:translate(-50%,-50%); animation:particleFloat var(--dur,4s) ease-in-out infinite alternate; animation-delay:var(--delay,0s); cursor:pointer; }}
    .particle.source {{ color:#55c7d9; background:#55c7d9; }}
    .particle.user {{ color:#2f7df6; background:#2f7df6; }}
    .particle.lead {{ color:#42d66f; background:#42d66f; }}
    .particle.action {{ color:#f3c15f; background:#f3c15f; }}
    .particle.blocked {{ color:#ff6961; background:#ff6961; }}
    .particle.live {{ color:#b78cff; background:#b78cff; }}
    .particle.page {{ color:#9fb8e8; background:#9fb8e8; }}
    .particle.repair {{ color:#f08bd3; background:#f08bd3; }}
    .particle.risk {{ color:#ff9b54; background:#ff9b54; }}
    .particle.account {{ color:#ff6961; background:#ff6961; }}
    .particle.reconcile {{ color:#55c7d9; background:#55c7d9; }}
    .particle.recovery {{ color:#b78cff; background:#b78cff; }}
    .particle.autonomy {{ color:#42d66f; background:#42d66f; }}
    .particle.product {{ color:#9fb8e8; background:#9fb8e8; }}
    .particle.delivery {{ color:#f3c15f; background:#f3c15f; }}
    .particle.dim {{ opacity:.32; filter:saturate(.7); }}
    @keyframes particleFloat {{ from {{ transform:translate(-50%,-50%) translateY(-4px) scale(.9); }} to {{ transform:translate(-50%,-50%) translateY(6px) scale(1.08); }} }}
    .hourglassInfo {{ display:grid; align-content:start; gap:10px; min-width:0; }}
    .hourglassTitle {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
    .hourglassTitle strong {{ font-size:15px; }}
    .hourglassTitle span {{ color:var(--muted); font-size:12px; line-height:1.45; }}
    .hourglassLegend {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }}
    .legendItem {{ display:flex; align-items:center; justify-content:space-between; gap:8px; border:1px solid #303941; border-radius:7px; background:#171b1f; padding:8px 9px; min-width:0; }}
    .legendLeft {{ display:flex; align-items:center; gap:7px; min-width:0; }}
    .legendDot {{ width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 10px currentColor; flex:0 0 auto; }}
    .legendLabel {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .legendValue {{ font-weight:900; }}
    .hourglassDecision {{ border:1px solid #303941; border-radius:8px; background:#171b1f; padding:10px; display:grid; gap:6px; }}
    .hourglassDecision strong {{ font-size:13px; }}
    .hourglassDecision div {{ color:var(--muted); line-height:1.45; overflow-wrap:anywhere; }}
    .hourglassDecision.blocked {{ border-color:#6b3434; background:#201718; }}
    .hourglassDecision.ready {{ border-color:#315d3c; background:#152017; }}
    .runtimePreview {{ border:1px solid #314151; border-radius:8px; background:#151c22; padding:10px; display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr)); gap:8px; }}
    .previewItem {{ min-height:58px; border:1px solid #303941; border-radius:7px; background:#171b1f; padding:8px 9px; min-width:0; }}
    .previewItem span {{ display:block; color:var(--muted); font-size:11px; }}
    .previewItem b {{ display:block; margin-top:6px; font-size:14px; line-height:1.25; overflow-wrap:anywhere; }}
    .previewItem.ok {{ border-color:#315d3c; background:#152017; }}
    .previewItem.warn {{ border-color:#6c5528; background:#211b10; }}
    .previewItem.bad {{ border-color:#6b3434; background:#201718; }}
    .previewItem.wide {{ display:none; }}
    .previewItem ul {{ margin:7px 0 0; padding-left:18px; color:var(--muted); line-height:1.45; font-size:12px; }}
    .previewItem li {{ overflow-wrap:anywhere; word-break:break-word; }}
    .decision {{ display:grid; grid-template-columns:1.2fr 1fr; gap:10px; }}
    .decision .notice {{ min-height:86px; }}
    .steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(92px,1fr)); gap:8px; }}
    .step {{ min-height:76px; border:1px solid var(--line); border-radius:8px; background:#171b1f; padding:9px; display:grid; align-content:space-between; gap:6px; }}
    .step b {{ font-size:18px; }}
    .step span {{ color:var(--muted); font-size:12px; }}
	    .step.done {{ border-color:#315d3c; background:#152017; }}
	    .step.blocked {{ border-color:#6b3434; background:#201718; }}
	    .step.active {{ border-color:#5b6f92; background:#19212c; }}
	    .pill {{ display:inline-flex; align-items:center; height:24px; padding:0 8px; border:1px solid var(--line); border-radius:999px; color:var(--muted); font-size:12px; }}
	    .pill.danger {{ color:#ff9b9b; border-color:#6b3434; background:#2a1718; }}
	    .launchBoard {{ display:grid; gap:12px; }}
	    .opsSplit {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; min-width:0; }}
	    .launchCommand {{ display:grid; grid-template-columns:minmax(190px,.75fr) minmax(260px,1.25fr); gap:10px; align-items:stretch; }}
	    .launchProgress,.launchCause {{ border:1px solid #303941; border-radius:8px; background:#171b1f; padding:10px; display:grid; gap:8px; min-width:0; }}
	    .launchProgressTop {{ display:flex; justify-content:space-between; gap:8px; align-items:center; color:var(--muted); font-size:12px; }}
	    .progressTrack {{ height:8px; border-radius:999px; background:#0f1113; border:1px solid #2c3339; overflow:hidden; }}
	    .progressFill {{ height:100%; width:0%; background:var(--blue); }}
	    .launchCause strong {{ font-size:13px; }}
	    .launchCause div {{ color:var(--muted); overflow-wrap:anywhere; line-height:1.4; }}
	    .launchStats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr)); gap:8px; }}
	    .launchStat {{ border:1px solid #303941; border-radius:8px; background:#171b1f; padding:9px 10px; min-height:66px; }}
	    .launchStat span {{ display:block; color:var(--muted); font-size:11px; }}
	    .launchStat b {{ display:block; font-size:20px; line-height:1.2; margin-top:7px; }}
	    .launchStat.ok {{ border-color:#315d3c; background:#152017; }}
	    .launchStat.bad {{ border-color:#6b3434; background:#201718; }}
	    .launchStat.warn {{ border-color:#6c5528; background:#211b10; }}
	    .launchQueue {{ display:grid; gap:8px; max-height:360px; overflow:auto; padding-right:2px; }}
	    .launchRow {{ display:grid; grid-template-columns:94px 132px minmax(160px,1fr) minmax(190px,1.1fr) minmax(180px,1.2fr); gap:10px; align-items:center; border:1px solid #303941; border-radius:8px; background:#171b1f; padding:9px 10px; min-width:0; }}
	    .launchRow.ok {{ border-color:#315d3c; background:#152017; }}
	    .launchRow.blocked {{ border-color:#6b3434; background:#201718; }}
	    .launchRow.warn {{ border-color:#6c5528; background:#211b10; }}
	    .launchId {{ font-weight:800; color:var(--text); }}
	    .launchMeta {{ display:grid; gap:3px; min-width:0; }}
	    .launchLabel {{ color:var(--muted); font-size:11px; line-height:1.2; }}
	    .launchValue {{ color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
	    .statusBadge {{ display:inline-flex; align-items:center; justify-content:center; min-height:26px; padding:0 9px; border-radius:999px; border:1px solid var(--line); font-size:12px; font-weight:800; width:max-content; max-width:100%; }}
	    .statusBadge.ok {{ color:#a4f3b9; border-color:#2f6a42; background:#1b3522; }}
	    .statusBadge.blocked {{ color:#ffb4ae; border-color:#6b3434; background:#321b1d; }}
	    .statusBadge.warn {{ color:#ffd887; border-color:#6c5528; background:#3a2d17; }}
	    .statusBadge.idle {{ color:var(--muted); background:#20262b; }}
	    .launchTools {{ display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }}
	    .launchFilters {{ display:flex; gap:6px; flex-wrap:wrap; }}
	    .filterBtn {{ height:30px; padding:0 10px; border-radius:999px; color:var(--muted); background:#20262b; }}
	    .filterBtn.active {{ color:white; border-color:#5b6f92; background:#243347; }}
	    .launchCount {{ color:var(--muted); font-size:12px; }}
	    .launchEmpty {{ border:1px dashed #3a444d; border-radius:8px; padding:18px; color:var(--muted); background:#171b1f; }}
	    .tablePanel {{ display:grid; gap:10px; min-width:0; overflow-x:auto; }}
	    .tableToolbar {{ display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap; }}
	    .tableFilters {{ display:flex; gap:6px; flex-wrap:wrap; }}
	    .tableMeta {{ color:var(--muted); font-size:12px; }}
	    .chipWrap {{ display:flex; flex-wrap:wrap; gap:5px; }}
	    .chip {{ display:inline-flex; align-items:center; min-height:22px; border-radius:999px; padding:0 8px; border:1px solid #34404a; background:#20262b; color:var(--text); font-size:12px; font-weight:700; }}
	    .chip.ok {{ color:#a4f3b9; border-color:#2f6a42; background:#1b3522; }}
	    .chip.warn {{ color:#ffd887; border-color:#6c5528; background:#3a2d17; }}
	    .chip.bad {{ color:#ffb4ae; border-color:#6b3434; background:#321b1d; }}
	    .reasonText,.copyText {{ max-width:320px; line-height:1.45; overflow-wrap:anywhere; }}
	    .sourceLink {{ display:inline-flex; align-items:center; min-height:24px; padding:0 8px; border:1px solid #34404a; border-radius:999px; background:#20262b; font-weight:700; }}
	    .ok {{ color:var(--green); }} .warn {{ color:var(--amber); }} .bad {{ color:var(--red); }} .cyan {{ color:var(--cyan); }}
    pre {{ margin:0; padding:12px 13px; height:438px; overflow:auto; background:var(--surface2); color:var(--green); line-height:1.45; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; min-width:0; }}
    th,td {{ padding:8px 6px; border-bottom:1px solid #2c3339; text-align:left; vertical-align:top; overflow-wrap:anywhere; word-break:break-word; }}
    th {{ color:var(--muted); font-weight:600; font-size:12px; }}
    .page {{ display:none; min-width:0; }} .page.active {{ display:grid; gap:14px; }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns:1fr; }}
      nav {{ grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); border-right:0; border-bottom:1px solid var(--line); }}
	      .work {{ padding:12px; }}
	      .clientRuntimeStrip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
	      .taskParams {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
	      .taskActions {{ grid-template-columns:1fr 1fr; max-width:none; }}
	      .taskActions #start {{ grid-column:1 / -1; }}
	      .taskActions button {{ width:100%; }}
	      .two {{ grid-template-columns:1fr; }}
	      .copyNotice {{ grid-template-columns:1fr; }}
	      .aiConsole {{ grid-template-columns:1fr; }}
	      .hourglassPanel {{ grid-template-columns:1fr; }}
	      .grid {{ grid-template-columns:repeat(3,1fr); }}
	      .opsSplit {{ grid-template-columns:1fr; }}
	      .steps {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
	      .launchCommand {{ grid-template-columns:1fr; }}
	      .launchStats {{ grid-template-columns:repeat(2,1fr); }}
	      .launchRow {{ grid-template-columns:1fr; }}
	    }}
		    @media (max-width: 560px) {{
		      .taskParams {{ grid-template-columns:1fr; }}
		      .taskActions {{ grid-template-columns:1fr; }}
		      header {{ align-items:flex-start; flex-direction:column; }}
		      .headerStatus {{ justify-content:flex-start; }}
		      .clientRuntimeStrip {{ grid-template-columns:1fr; }}
		      .selectedGroupBar {{ grid-template-columns:1fr; }}
		      .selectedGroupBar b {{ white-space:normal; overflow-wrap:anywhere; }}
		      .grid {{ grid-template-columns:1fr 1fr; }}
		      nav {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
		    }}
  </style>
</head>
<body data-reachops-ui-version="{WEB_UI_VERSION}">
  <header>
    <div class="brandBlock">
      <div class="brandMark">R</div>
      <div class="brandText">
        <h1>ReachOps 本地客户端控制台 <span class="clientType">客户端外壳</span></h1>
        <div class="sub">桌面入口 ReachOpsApp.py 启动本机 127.0.0.1 控制台；Mac / Windows 同一客户端，后端走本地真实执行链路</div>
      </div>
    </div>
    <div class="headerStatus">
      <div class="pill ok" id="accountGateState">账号门禁已启用</div>
      <div class="pill versionPill" id="uiVersion" title="{WEB_UI_VERSION}">{CLIENT_DISPLAY_VERSION}</div>
      <div class="pill" id="runState">READY</div>
    </div>
  </header>
  <main>
    <nav>
      <button class="tab active" data-page="task">获客任务</button>
      <button class="tab" data-page="leads">线索分析</button>
      <button class="tab" data-page="outreach">触达执行</button>
      <button class="tab" data-page="accounts">账号诊断</button>
      <button class="tab" data-page="reports">报告中心</button>
    </nav>
    <section class="work">
      <div class="clientRuntimeStrip" aria-label="客户端运行合同">
        <div class="runtimeContractItem ok"><span>启动入口</span><b>ReachOpsApp.py / 本地客户端</b></div>
        <div class="runtimeContractItem ok"><span>绑定地址</span><b>127.0.0.1 控制台</b></div>
        <div class="runtimeContractItem ok"><span>执行边界</span><b>执行期 0 token</b></div>
        <div class="runtimeContractItem warn"><span>提交策略</span><b>未授权不提交</b></div>
      </div>
      <div class="controlPanel">
        <div class="taskForm">
          <label>推广目标
            <input id="target" value="{DEFAULT_TARGET}" placeholder="输入产品链接、关键词、达人主页、视频链接、话题或直播间" />
          </label>
	          <label class="groupField">账号分组
	            <span class="groupControl">
	              <select id="group"><option>United States</option></select>
	              <button id="refreshGroupsInline">刷新</button>
	            </span>
	          </label>
	          <div class="selectedGroupBar" id="selectedGroupBar">
	            <div><div class="barLabel">当前账号分组</div><b id="selectedGroupName">United States</b></div>
	            <div><div class="barLabel">可读取账号数</div><b class="count unknown" id="selectedGroupCount">未刷新</b></div>
	            <div><div class="barLabel">Group ID</div><b id="selectedGroupId">-</b></div>
	          </div>
	          <div class="groupDetails compact" id="groupDetails"></div>
          <div class="taskParams">
            <label>目标类型
              <select id="sourceType">
                <option value="auto" selected>自动识别</option>
                <option value="creator_url">达人主页</option>
                <option value="content_url">视频链接</option>
                <option value="live_room_url">直播间活跃用户</option>
                <option value="keyword">关键词搜索</option>
                <option value="topic">话题/趋势</option>
                <option value="hashtag">标签</option>
                <option value="product_url">商品页</option>
                <option value="shop_url">店铺页</option>
              </select>
            </label>
            <label>执行模式
              <select id="mode">
                <option value="preflight">采集 + 触达预检</option>
                <option value="collect">只采集</option>
                <option value="live_comment">采集 + 真实评论</option>
              </select>
            </label>
            <label>账号数
              <input id="profiles" value="3" />
            </label>
            <label>目标数量
              <select id="volume">
                <option value="quick" selected>快速</option>
                <option value="standard">标准</option>
                <option value="stress">压测</option>
              </select>
            </label>
            <label class="checkLabel">真实评论确认
              <span><input id="liveConfirm" type="checkbox" />确认真实评论</span>
            </label>
            <label class="checkLabel">账号修复确认
              <span><input id="accountRepairConfirmed" type="checkbox" />已修复账号，允许重新预检</span>
            </label>
          </div>
          <label>评论内容
            <input id="commentText" value="" placeholder="留空自动生成；可填固定评论文案" />
          </label>
          <div class="runtimePreview" id="runtimePreview">
            <div class="previewItem"><span>后端模式</span><b id="previewMode">采集 + 触达预检</b></div>
            <div class="previewItem"><span>采集范围</span><b id="previewRange">3 视频 / 20 评论</b></div>
            <div class="previewItem"><span>账号上限</span><b id="previewProfiles">3</b></div>
            <div class="previewItem"><span>预计超时</span><b id="previewTimeout">900 秒</b></div>
            <div class="previewItem"><span>提交策略</span><b id="previewSubmit">预检，不提交</b></div>
            <div class="previewItem"><span>启动门禁</span><b id="previewGate">等待刷新</b></div>
            <div class="previewItem"><span>执行计划</span><b id="previewPlan">等待生成</b></div>
            <div class="previewItem wide" id="previewAutonomyBox">
              <span>自治预判</span>
              <b id="previewAutonomy">等待 start-preview</b>
              <ul id="previewAutonomyList"><li>等待结构化预判合同。</li></ul>
            </div>
          </div>
	          <div class="taskActions">
	            <button class="primary" id="start" disabled>开始获客</button>
	            <button class="warn" id="pause">暂停</button>
	            <button class="okBtn" id="resume">继续</button>
	            <button id="stop">停止</button>
	          </div>
	          <div class="secondaryActions" aria-label="次级操作">
	            <button id="previewPlanReplay">预检重放计划</button>
	            <button class="okBtn" id="startFromPlan">重放计划执行</button>
	            <button id="downloadExecutionPlan">下载执行计划</button>
	            <button class="warn" id="applyAccountRepair" disabled>隔离坏账号</button>
	          </div>
	        </div>
	      </div>
      <div class="copyNotice" id="copyModeNotice">
        <strong>评论文案：自动识别生成</strong>
        <span>评论内容留空时，系统会根据线索意图自动生成回复；只有达到触达分数的线索才会进入评论队列，低意向用户会自动跳过。</span>
      </div>
	      <details class="advancedPanel">
	        <summary>高级诊断与本地规则 <span>状态解释、未知规则复核、信息沙漏</span></summary>
	        <div class="advancedBody">
	          <div class="aiConsole" id="aiConsolePanel">
	            <div class="aiConsoleTalk">
	              <div class="aiConsoleHead">
	                <strong>AI 操作台</strong>
	                <span class="pill" id="aiConsoleState">本地规则 / 0 token</span>
	                <span class="pill" id="aiUsageState">执行期AI 0次 / token 0</span>
	              </div>
	              <div class="aiConsoleLog" id="aiConsoleLog">
	                <div class="aiBubble system">等待指令。</div>
	              </div>
	              <div class="aiConsoleQuick">
	                <button type="button" id="aiConsoleExplainStatus">解释状态</button>
	                <button type="button" id="aiConsoleAnalyzeUnknown">分析未知</button>
	                <button type="button" id="aiConsoleProductCapability">能力矩阵</button>
	              </div>
	              <div class="aiConsoleInput">
	                <textarea id="aiConsoleInput" placeholder="例如：只采集不评论，或者：为什么停了"></textarea>
	                <button id="aiConsoleSend">发送</button>
	              </div>
	            </div>
	            <div class="aiConsolePlan">
	              <div class="aiConsoleHead">
	                <strong>计划映射</strong>
	                <span class="pill" id="aiConsoleIntent">待输入</span>
	              </div>
	              <div class="aiPlanGrid">
	                <div class="aiPlanItem"><span>模式</span><b id="aiPlanMode">-</b></div>
	                <div class="aiPlanItem"><span>分组</span><b id="aiPlanGroup">-</b></div>
	                <div class="aiPlanItem"><span>范围</span><b id="aiPlanRange">-</b></div>
	                <div class="aiPlanItem"><span>计划</span><b id="aiPlanId">-</b></div>
	              </div>
	              <div class="notice" id="aiConsoleNotice">
	                <strong id="aiConsoleNoticeTitle">本地规则引擎待命</strong>
	                <ul id="aiConsoleNextList"><li>可用自然语言调整参数或解释阻断。</li></ul>
	              </div>
	              <div class="policyReview" id="offlinePolicyReview">
	                <div class="policyReviewHead">
	                  <strong>未知状态候选规则</strong>
	                  <span class="pill" id="offlinePolicyReviewState">无候选</span>
	                </div>
	                <div class="policyReviewBody" id="offlinePolicyReviewBody">点击“分析未知”后，可在这里复核高频未知状态候选规则。复核只写入本地审计账本，不自动改变执行策略。</div>
	                <div class="policyReviewActions">
	                  <button type="button" class="okBtn" id="approveOfflinePolicyCandidate" disabled>批准候选</button>
	                  <button type="button" class="warn" id="rejectOfflinePolicyCandidate" disabled>拒绝候选</button>
	                </div>
	              </div>
	              <div class="machineActions" id="aiConsoleMachineActions">
	                <strong>本地机器动作</strong>
	                <ul id="aiConsoleMachineList"><li>等待自修复或风险门禁证据。</li></ul>
	              </div>
	              <div class="machineActions" id="aiConsoleTimeline">
	                <strong>关键时间线</strong>
	                <ul id="aiConsoleTimelineList"><li>等待结构化证据时间线。</li></ul>
	              </div>
	            </div>
	          </div>
	          <div class="hourglassPanel" id="infoHourglass">
	            <div class="hourglassStage" id="hourglassStage" aria-label="信息沙漏状态">
	              <div class="hourglassGlass"></div>
	              <div class="hourglassNeck"></div>
	              <div id="hourglassParticles"></div>
	            </div>
	            <div class="hourglassInfo">
	              <div class="hourglassTitle">
	                <div>
	                  <strong>AI 信息沙漏</strong>
	                  <span id="hourglassSubtitle">等待真实运行数据进入沙漏。</span>
	                </div>
	                <span class="pill" id="hourglassState">待执行</span>
	              </div>
	              <div class="hourglassLegend" id="hourglassLegend"></div>
	              <div class="hourglassDecision" id="hourglassDecision">
	                <strong id="hourglassDecisionTitle">信息尚未流入</strong>
	                <div id="hourglassDecisionBody">开始获客后，来源、用户、线索、动作和阻断会以粒子形式沉淀到这里。</div>
	              </div>
	            </div>
	          </div>
	        </div>
	      </details>
      <div class="grid">
        <div class="metric"><span>设置并发</span><b id="mRequestedProfiles">3</b></div>
        <div class="metric"><span>实际并发</span><b id="mActualProfiles">0</b></div>
        <div class="metric"><span>队列账号</span><b id="mQueueProfiles">0</b></div>
        <div class="metric"><span>可用账号</span><b id="mAvailableProfiles">0</b></div>
        <div class="metric"><span>采集数</span><b id="mCandidates">0</b></div>
        <div class="metric"><span>有效线索</span><b id="mQualified">0</b></div>
        <div class="metric"><span>高意向</span><b id="mHigh">0</b></div>
        <div class="metric"><span>入队数</span><b id="mActions">0</b></div>
        <div class="metric"><span>成功触达</span><b id="mTouchSuccess">0</b></div>
        <div class="metric"><span>失败</span><b id="mTouchFailed">0</b></div>
        <div class="metric"><span>跳过</span><b id="mTouchSkipped">0</b></div>
        <div class="metric"><span>成功率</span><b id="mSuccessRate">0%</b></div>
      </div>
      <div id="task" class="page active">
        <div class="decision">
          <div class="notice" id="operatorDecision">
            <strong id="operatorDecisionTitle">等待开始获客</strong>
            <div class="sub" id="operatorDecisionBody">输入推广目标并选择分组后开始执行。</div>
          </div>
          <div class="notice" id="operatorNext">
            <strong>运营下一步</strong>
            <ul id="operatorNextList"><li>等待执行结果。</li></ul>
          </div>
        </div>
        <div class="panel">
          <h2>本轮执行漏斗 <span class="pill" id="funnelBatch">未开始</span></h2>
          <div class="body">
            <div class="steps" id="funnelSteps"></div>
          </div>
        </div>
	        <div class="panel">
	          <h2>本轮配置启动列表 <span class="pill" id="profileLaunchSummary">等待预检</span></h2>
	          <div class="body"><div id="profileLaunchPanel" class="launchBoard"></div></div>
	        </div>
        <div class="opsSplit">
          <div class="panel">
            <h2>采集日志 <span class="pill" id="collectionSummary">等待采集</span></h2>
            <div class="body"><table id="collectionTable"></table></div>
          </div>
          <div class="panel">
            <h2>触达日志 <span class="pill" id="touchSummary">等待触达</span></h2>
            <div class="body"><table id="touchTable"></table></div>
          </div>
        </div>
        <div class="two">
          <div class="panel">
            <h2>执行方案 <button id="refreshGroups">刷新分组</button></h2>
            <div class="body stack">
              <div class="row"><span>目标类型</span><b id="targetType">自动识别</b></div>
              <div class="row"><span>当前分组</span><b id="currentGroup">United States</b></div>
              <div class="row"><span>分组数量</span><b id="groupCount">未刷新</b></div>
              <div class="row"><span>执行模式</span><b id="currentMode">采集 + 触达预检</b></div>
              <div class="row"><span>ixBrowser API</span><b id="ixbrowserApiState">未检查</b></div>
              <div class="row"><span>API 端口</span><span class="inlineConfig"><input id="ixbrowserApiPort" value="53200" /><button id="applyIxBrowserPort">应用</button></span></div>
              <div class="notice" id="ixbrowserStatusNotice">
                <strong>ixBrowser 环境下一步</strong>
                <ul id="ixbrowserStatusActions"><li>等待 ixBrowser Local API 检查。</li></ul>
              </div>
              <div class="row"><span>真实评论授权</span><b id="activationState">未检查</b></div>
              <div class="notice" id="activationNotice">
                <strong>真实评论授权下一步</strong>
                <ul id="activationActions"><li>等待激活状态检查。</li></ul>
              </div>
              <div class="row"><span>最终交付门禁</span><b id="finalStatusState">未检查</b></div>
	              <div class="notice" id="finalStatusNotice">
	                <strong>最终交付下一步</strong>
	                <ul id="finalStatusActions"><li>等待最终验收状态。</li></ul>
	              </div>
	              <div class="notice" id="finalCommandNotice">
	                <strong>最终复核命令</strong>
	                <ul id="finalStatusCommands"><li>等待最终验收状态。</li></ul>
	              </div>
	              <div class="row"><span>评论文案</span><b id="currentCopyMode">自动识别生成</b></div>
              <div class="row"><span>目标数量</span><b id="currentVolume">快速</b></div>
              <div class="row"><span>最近批次</span><b id="batchId">-</b></div>
              <div class="notice">
                <strong id="acceptanceState">验收状态：待执行</strong>
                <div class="sub" id="acceptanceMeta">账号预检：-</div>
                <ul id="acceptanceBlockers"><li>等待执行结果。</li></ul>
              </div>
            </div>
          </div>
          <div class="panel">
            <h2>实时执行日志 <button id="refresh">刷新</button></h2>
            <pre id="logs">等待执行...</pre>
          </div>
        </div>
      </div>
      <div id="leads" class="page">
        <div class="panel">
          <h2>线索分析 <span class="pill" id="leadPanelSummary">等待线索</span></h2>
          <div class="body tablePanel">
            <div class="tableToolbar">
              <div class="tableFilters" id="leadFilters"></div>
              <div class="tableMeta" id="leadTableMeta">未加载</div>
            </div>
            <table id="leadTable"></table>
          </div>
        </div>
      </div>
      <div id="outreach" class="page">
        <div class="panel">
          <h2>触达执行 <span class="pill" id="outreachPanelSummary">等待触达</span></h2>
          <div class="body tablePanel">
            <div class="tableToolbar">
              <div class="tableFilters" id="outreachFilters"></div>
              <div class="tableMeta" id="outreachTableMeta">未加载</div>
            </div>
            <table id="actionTable"></table>
          </div>
        </div>
      </div>
      <div id="accounts" class="page">
        <div class="panel"><h2>账号诊断</h2><div class="body"><table id="healthTable"></table></div></div>
      </div>
      <div id="reports" class="page">
        <div class="panel"><h2>报告中心 <button id="refreshGoalDelivery">刷新目标报告</button> <button id="refreshMvpAcceptance">刷新MVP验收</button> <button id="initAcceptanceInputs">生成验收输入</button></h2><div class="body"><table id="reportTable"></table></div></div>
      </div>
    </section>
  </main>
  <script>
    const $ = id => document.getElementById(id);
    const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
	    const sourceLabels = {json.dumps(SOURCE_TYPE_LABELS, ensure_ascii=False)};
	    let runtimeState = {{running:false, paused:false, elapsed_seconds:0, last_stage:''}};
	    let launchFilter = 'all';
	    let leadFilter = 'all';
	    let outreachFilter = 'all';
	    let apiNoticeUntil = 0;
	    let groupListReady = false;
	    let accountGateBlocked = false;
	    let accountGateBlockedGroup = '';
	    let accountGatePendingRecheck = false;
	    let accountGatePendingRecheckGroup = '';
	    let accountRepairConfirmedGroup = '';
	    let accountRepairSummary = null;
		    let accountRepairApplyState = {{}};
	    let loadedGroups = [];
	    let groupRefreshInFlight = false;
	    let groupRefreshPollCount = 0;
	    let hourglassData = {{}};
	    let currentOfflinePolicyCandidate = null;
    function classify(line) {{ return /ERROR|WARN|BLOCK|failed|失败|不可用/.test(line) ? 'bad' : (/DONE|READY|success|healthy/.test(line) ? 'ok' : ''); }}
    function apiNoticeActive() {{ return Date.now() < apiNoticeUntil; }}
    function isAccountRepairConfirmed() {{
      if (!($('accountRepairConfirmed') && $('accountRepairConfirmed').checked)) return false;
      const selectedGroup = normGroupName($('group') ? $('group').value : '');
      const confirmedGroup = normGroupName(accountRepairConfirmedGroup);
      return !selectedGroup || !confirmedGroup || selectedGroup === confirmedGroup;
    }}
    function normGroupName(value) {{
      return String(value || '').trim().toLowerCase();
    }}
    function accountGateAppliesToCurrentGroup() {{
      const blockedGroup = normGroupName(accountGateBlockedGroup);
      const selectedGroup = normGroupName($('group') ? $('group').value : '');
      return accountGateBlocked && (!blockedGroup || !selectedGroup || blockedGroup === selectedGroup);
    }}
    function accountGatePendingRecheckAppliesToCurrentGroup() {{
      const pendingGroup = normGroupName(accountGatePendingRecheckGroup);
      const selectedGroup = normGroupName($('group') ? $('group').value : '');
      return accountGatePendingRecheck && (!pendingGroup || !selectedGroup || pendingGroup === selectedGroup);
    }}
    function updateStartAvailability() {{
      const blockedByAccountGate = accountGateAppliesToCurrentGroup() && !isAccountRepairConfirmed();
      const pendingAccountRecheck = accountGatePendingRecheckAppliesToCurrentGroup();
      const blockedGroupLabel = String(accountGateBlockedGroup || ($('group') ? $('group').value : '') || '当前分组').trim();
      const pendingGroupLabel = String(accountGatePendingRecheckGroup || blockedGroupLabel || '当前分组').trim();
      const startBlockedReason = !groupListReady
        ? '请先刷新 ixBrowser 配置分组，并等待分组数量实时读取完成。'
        : blockedByAccountGate
          ? `${{blockedGroupLabel}} 最近一次账号预检没有可用账号；点击后会重新读取分组并自动预检筛选有效账号。`
          : '开始获客';
      if ($('start')) {{
        $('start').disabled = !groupListReady;
        $('start').title = startBlockedReason;
      }}
      if ($('accountGateState')) {{
        $('accountGateState').textContent = blockedByAccountGate ? `${{blockedGroupLabel}} 账号阻断` : (pendingAccountRecheck ? `${{pendingGroupLabel}} 等待重新预检` : '账号门禁已启用');
        $('accountGateState').className = blockedByAccountGate ? 'pill danger' : (pendingAccountRecheck ? 'pill warn' : 'pill ok');
        $('accountGateState').title = blockedByAccountGate
          ? `${{blockedGroupLabel}} 最近一次预检没有可用账号；再次开始获客会重新读取分组并重新预检账号。`
          : (pendingAccountRecheck
            ? `${{pendingGroupLabel}} 已执行账号修复，下一次开始获客会重新读取分组并重新预检账号。`
            : '启动前会校验分组和账号可用性，避免重复消耗启动次数。');
      }}
      if ($('applyAccountRepair')) {{
        $('applyAccountRepair').disabled = !blockedByAccountGate;
        $('applyAccountRepair').title = blockedByAccountGate
          ? '按最新账号修复计划把硬失败账号移入封禁账号分组。'
          : '仅在当前分组账号阻断时可执行。';
      }}
    }}
    function startPreviewPayload() {{
      return {{
        target:$('target') ? $('target').value : '',
        sourceType:$('sourceType') ? $('sourceType').value : 'auto',
        group:$('group') ? $('group').value : 'United States',
        mode:$('mode') ? $('mode').value : 'preflight',
        volume:$('volume') ? $('volume').value : 'quick',
        profiles:$('profiles') ? $('profiles').value : '3',
        commentText:$('commentText') ? $('commentText').value : '',
        liveConfirm:$('liveConfirm') ? $('liveConfirm').checked : false,
        accountRepairConfirmed:$('accountRepairConfirmed') ? $('accountRepairConfirmed').checked : false,
        groupListReady,
        accountGateBlocked: accountGateAppliesToCurrentGroup()
      }};
    }}
    function renderStartPreview(data) {{
      data = data || {{}};
      const preflightDecision = data.preflight_decision || {{}};
      const forecast = data.autonomous_preflight_forecast || {{}};
      const plan = data.execution_plan || {{}};
      const runtimeContract = data.runtime_contract || plan.runtime_contract || {{}};
      const mode = data.mode_label || (($('mode') && $('mode').selectedOptions[0]) ? $('mode').selectedOptions[0].textContent : '-');
      const range = `${{data.max_videos ?? '-'}} 视频 / ${{data.max_comments ?? '-'}} 评论`;
      const profiles = data.profile_limit ?? ($('profiles') ? $('profiles').value : '-');
      const timeout = data.timeout_seconds ? `${{data.timeout_seconds}} 秒` : '-';
      const submit = preflightDecision.submit_policy || data.submit_policy || '预检，不提交';
      const gate = preflightDecision.gate_state || data.gate_state || '等待刷新';
      if ($('previewMode')) $('previewMode').textContent = mode;
      if ($('previewRange')) $('previewRange').textContent = range;
      if ($('previewProfiles')) $('previewProfiles').textContent = profiles;
      if ($('previewTimeout')) $('previewTimeout').textContent = timeout;
      if ($('previewSubmit')) $('previewSubmit').textContent = submit;
      if ($('previewGate')) $('previewGate').textContent = gate;
      if ($('previewPlan')) {{
        const planId = data.execution_plan_id || (data.execution_plan && data.execution_plan.plan_id) || '-';
        $('previewPlan').textContent = planId;
        $('previewPlan').title = data.execution_plan_schema ? `schema=${{data.execution_plan_schema}}` : 'ExecutionPlan';
      }}
      if ($('previewAutonomy')) {{
        const forecastStatus = forecast.status || (preflightDecision.start_allowed === false ? 'blocked' : 'ready');
        const forecastSchema = forecast.schema_version || 'reachops.autonomous_preflight_forecast.v1';
        $('previewAutonomy').textContent = `${{forecastSchema}} / ${{forecastStatus}}`;
      }}
      if ($('previewAutonomyList')) {{
        const states = Array.isArray(forecast.predicted_state_sequence) ? forecast.predicted_state_sequence : [];
        const routes = Array.isArray(forecast.repair_routes) ? forecast.repair_routes : [];
        const blockers = Array.isArray(forecast.predicted_blockers) ? forecast.predicted_blockers : [];
        const evidence = Array.isArray(forecast.evidence_requirements) ? forecast.evidence_requirements : [];
        const invariants = forecast.runtime_invariants || {{}};
        const forecastItems = [];
        if (states.length) forecastItems.push(`状态链：${{states.slice(0, 7).join(' -> ')}}`);
        if (routes.length) forecastItems.push(`自修复：${{routes.slice(0, 5).map(row => `${{row.state || '-'}}:${{row.action || '-'}}`).join(' / ')}}`);
        if (blockers.length) forecastItems.push(`预判阻断：${{blockers.slice(0, 5).join(', ')}}`);
        if (evidence.length) forecastItems.push(`证据要求：${{evidence.slice(0, 4).join(', ')}}`);
        if (runtimeContract.schema_version) forecastItems.push(`执行合同：${{runtimeContract.schema_version}} / executor=${{runtimeContract.executor || '-'}} / AI仅控制面=${{String(runtimeContract.ai_console_is_execution_dependency === false)}}`);
        forecastItems.push(`运行约束：0 token=${{String(!!invariants.no_ai_token_during_execution)}} / 不预览提交=${{String(forecast.no_submit !== false)}}`);
        $('previewAutonomyList').innerHTML = listItems(forecastItems);
      }}
      const submitBox = $('previewSubmit') ? $('previewSubmit').closest('.previewItem') : null;
      const gateBox = $('previewGate') ? $('previewGate').closest('.previewItem') : null;
      const autonomyBox = $('previewAutonomyBox');
      if (submitBox) submitBox.className = data.mode === 'live_comment' ? (data.live_confirmed ? 'previewItem warn' : 'previewItem bad') : 'previewItem ok';
      if (gateBox) {{
        const blocked = preflightDecision.start_allowed === false || /需|修复|未刷新/.test(String(gate));
        gateBox.className = blocked ? 'previewItem warn' : 'previewItem ok';
      }}
      if (autonomyBox) autonomyBox.className = `previewItem wide ${{forecast.status === 'blocked' ? 'warn' : 'ok'}}`;
    }}
    async function refreshStartPreview() {{
      try {{
        const data = await postJson('/api/start-preview', startPreviewPayload());
        renderStartPreview(data);
      }} catch (err) {{
        renderStartPreview({{gate_state:'预览不可用'}});
      }}
    }}
    async function previewPlanReplay() {{
      let result = {{}};
      try {{
        result = await getJson('/api/start-from-plan-preview');
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err), next_actions:['检查本地 Web 服务。']}};
      }}
      renderStartPreview(result);
      const decision = result.preflight_decision || {{}};
      const tone = decision.start_allowed === true ? 'ready' : 'blocked';
      showApiNotice(
        decision.start_allowed === true ? '重放计划可启动' : '重放计划被门禁拦截',
        {{
          status:result.status || '-',
          message:`plan=${{result.execution_plan_id || '-'}} fingerprint=${{result.plan_fingerprint_sha256 || '-'}}`,
          blockers:decision.blockers || [],
          next_actions:decision.next_actions || [],
        }},
        tone,
        12000
      );
      return result;
    }}
    async function startFromPlan() {{
      const preview = await previewPlanReplay();
      const decision = preview.preflight_decision || {{}};
      if (decision.start_allowed !== true) return;
      let result = {{}};
      try {{
        result = await postJson('/api/start-from-plan', {{}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      if (result.status === 'started') {{
        showApiNotice('计划重放已启动', result, 'ready');
        setTimeout(() => {{
          apiNoticeUntil = 0;
          refreshLogs();
          refreshSnapshot();
        }}, 1200);
      }} else {{
        showApiNotice('计划重放未启动', result, 'blocked', 30000);
      }}
      updateStartAvailability();
    }}
    async function downloadExecutionPlan() {{
      let result = {{}};
      try {{
        result = await getJson('/api/execution-plan');
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err), next_actions:['检查本地 Web 服务。']}};
      }}
      if (result.exists === true && result.download_url) {{
        window.__reachopsLastDownloadUrl = result.download_url;
        if (typeof window.open === 'function') window.open(result.download_url, '_blank', 'noopener');
        showApiNotice(
          '执行计划已准备下载',
          {{
            ...result,
            message:`plan=${{result.plan_id || '-'}} schema=${{result.schema_version || '-'}}`,
            next_actions:['该 JSON 是本轮执行的可复现计划快照，可用于审计或计划重放。']
          }},
          'ready',
          12000
        );
      }} else {{
        showApiNotice(
          '执行计划不可下载',
          {{
            ...result,
            message:result.message || '还没有生成 ExecutionPlan。',
            next_actions:result.next_actions || ['先执行开始预览或开始获客，生成结构化 ExecutionPlan。']
          }},
          'blocked',
          30000
        );
      }}
      return result;
    }}
    function appendAiBubble(kind, text) {{
      if (!$('aiConsoleLog')) return;
      const node = document.createElement('div');
      node.className = `aiBubble ${{kind || 'system'}}`;
      node.textContent = text || '';
      $('aiConsoleLog').appendChild(node);
      $('aiConsoleLog').scrollTop = $('aiConsoleLog').scrollHeight;
    }}
    function applyAiPlanPatch(patch) {{
      patch = patch || {{}};
      if (patch.mode && $('mode')) {{
        $('mode').value = patch.mode;
        $('currentMode').textContent = $('mode').selectedOptions[0] ? $('mode').selectedOptions[0].textContent : patch.mode;
      }}
      if (patch.volume && $('volume')) {{
        $('volume').value = patch.volume;
        $('currentVolume').textContent = $('volume').selectedOptions[0] ? $('volume').selectedOptions[0].textContent : patch.volume;
      }}
      if (patch.group && $('group')) {{
        const option = Array.from($('group').options || []).find(opt => opt.value === patch.group);
        if (option) $('group').value = patch.group;
      }}
      if ('liveConfirm' in patch && $('liveConfirm')) $('liveConfirm').checked = !!patch.liveConfirm;
      updateCopyModeNotice();
      updateSelectedGroupQuantity();
      updateStartAvailability();
    }}
    function renderOfflinePolicyReview(data) {{
      const offline = (data && data.offline_learning) || {{}};
      const policyCandidates = offline.policy_candidates || {{}};
      const candidates = Array.isArray(policyCandidates.candidates) ? policyCandidates.candidates : [];
      const candidate = candidates.length ? candidates[0] : null;
      currentOfflinePolicyCandidate = candidate;
      const stateEl = $('offlinePolicyReviewState');
      const bodyEl = $('offlinePolicyReviewBody');
      const approveBtn = $('approveOfflinePolicyCandidate');
      const rejectBtn = $('rejectOfflinePolicyCandidate');
      if (!candidate) {{
        if (stateEl) {{
          stateEl.textContent = '无候选';
          stateEl.className = 'pill';
        }}
        if (bodyEl) bodyEl.textContent = '点击“分析未知”后，可在这里复核高频未知状态候选规则。复核只写入本地审计账本，不自动改变执行策略。';
        if (approveBtn) approveBtn.disabled = true;
        if (rejectBtn) rejectBtn.disabled = true;
        return;
      }}
      const review = candidate.review || {{}};
      const reviewStatus = candidate.review_status || review.decision || '待复核';
      if (stateEl) {{
        stateEl.textContent = reviewStatus === 'approved' ? '已批准' : (reviewStatus === 'rejected' ? '已拒绝' : '待复核');
        stateEl.className = reviewStatus === 'approved' ? 'pill ok' : (reviewStatus === 'rejected' ? 'pill warn' : 'pill');
      }}
      if (bodyEl) {{
        const releaseProposal = offline.policy_release_proposal || {{}};
        const releaseReady = releaseProposal.ready_for_release_count || 0;
        const releaseGate = releaseProposal.release_gate || 'code_or_policy_release_required';
        bodyEl.textContent = `${{candidate.candidate_state || 'UNKNOWN_PAGE_STATE'}} -> ${{candidate.candidate_action || 'capture_unknown_state_bundle'}} / occurrences=${{candidate.occurrence_count || 0}} / release_ready=${{releaseReady}} / gate=${{releaseGate}} / auto_apply=false。复核只记录到本地账本，策略发布前不会改变执行。`;
      }}
      if (approveBtn) approveBtn.disabled = reviewStatus === 'approved';
      if (rejectBtn) rejectBtn.disabled = reviewStatus === 'rejected';
    }}
    async function reviewOfflinePolicyCandidate(decision) {{
      const candidate = currentOfflinePolicyCandidate || {{}};
      const candidateState = candidate.candidate_state || '';
      const candidateAction = candidate.candidate_action || '';
      if (!candidateState || !candidateAction) {{
        showApiNotice('没有可复核候选规则', {{status:'rejected', message:'请先点击“分析未知”，让本地账本生成候选规则。'}}, 'blocked', 8000);
        return;
      }}
      let result = {{}};
      try {{
        result = await postJson('/api/offline-learning/review', {{
          candidate_state:candidateState,
          candidate_action:candidateAction,
          decision,
          reviewer:'operator',
          note:'Reviewed from ReachOps AI console.'
        }});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      if (result.offline_learning) renderOfflinePolicyReview({{offline_learning:result.offline_learning}});
      const ok = result.status === 'review_recorded';
      showApiNotice(
        ok ? '候选规则复核已记录' : '候选规则复核失败',
        {{
          ...result,
          message: ok ? '复核只写入本地审计账本；auto_apply=false，运行时不会自动绕过 RiskGate。' : (result.message || result.error || '复核失败'),
        }},
        ok ? 'ready' : 'blocked',
        ok ? 12000 : 30000
      );
      appendAiBubble('system', ok ? `已记录候选规则复核：${{candidateState}} -> ${{candidateAction}} / ${{decision}}。` : '候选规则复核失败。');
    }}
    function renderAiConsoleResult(data) {{
      data = data || {{}};
      const plan = data.execution_plan || {{}};
      const limits = plan.limits || {{}};
      if ($('aiConsoleState')) {{
        $('aiConsoleState').textContent = data.no_ai_token_used ? '本地规则 / 0 token' : '外部AI';
        $('aiConsoleState').className = data.no_ai_token_used ? 'pill ok' : 'pill warn';
      }}
      if ($('aiConsoleIntent')) $('aiConsoleIntent').textContent = data.intent || '-';
      if ($('aiPlanMode')) $('aiPlanMode').textContent = plan.mode || '-';
      if ($('aiPlanGroup')) $('aiPlanGroup').textContent = plan.profile_group || '-';
      if ($('aiPlanRange')) $('aiPlanRange').textContent = `${{limits.max_videos ?? '-'}} 视频 / ${{limits.max_comments ?? '-'}} 评论`;
      if ($('aiPlanId')) {{
        $('aiPlanId').textContent = plan.plan_id || data.execution_plan_id || '-';
        $('aiPlanId').title = data.execution_plan_schema || '';
      }}
      if ($('aiConsoleNoticeTitle')) {{
        $('aiConsoleNoticeTitle').textContent = data.intent === 'explain_status' ? '状态解释' : (data.intent === 'unknown_state_analysis' ? '未知状态分析' : (data.intent === 'product_capability_status' ? '产品能力矩阵' : '计划已映射'));
      }}
      const gate = data.client_delivery_summary || {{}};
      const gateActions = gate.status
        ? [`客户端门禁：${{gate.status || '-'}} / acceptance_ready=${{gate.acceptance_ready === true ? 'true' : 'false'}} / final_delivery_ready=${{gate.final_delivery_ready === true ? 'true' : 'false'}}`]
        : [];
      const actions = [...gateActions, ...(data.blockers || []).map(x => '阻断：' + x), ...(data.next_actions || [])];
      if ($('aiConsoleNextList')) $('aiConsoleNextList').innerHTML = listItems(actions.length ? actions : ['等待下一步。']);
      const machineActions = data.machine_actions || [];
      const forecast = data.autonomous_preflight_forecast || {{}};
      const forecastActions = [];
      if (forecast.schema_version) {{
        forecastActions.push(`自治预判：${{forecast.schema_version}} / ${{forecast.status || '-'}}`);
        if (Array.isArray(forecast.repair_routes) && forecast.repair_routes.length) {{
          forecastActions.push(`预判修复路线：${{forecast.repair_routes.slice(0, 4).map(row => `${{row.state || '-'}}:${{row.action || '-'}}`).join(' / ')}}`);
        }}
      }}
      if ($('aiConsoleMachineList')) $('aiConsoleMachineList').innerHTML = listItems((machineActions.length || forecastActions.length) ? [...machineActions, ...forecastActions] : ['暂无本地机器动作。']);
      const timelineSummary = data.timeline_summary || ((data.evidence_bundle || {{}}).timeline_summary || []);
      if ($('aiConsoleTimelineList')) $('aiConsoleTimelineList').innerHTML = listItems(timelineSummary.length ? timelineSummary : ['暂无关键时间线。']);
      renderOfflinePolicyReview(data);
      if ($('aiConsoleNotice')) {{
        $('aiConsoleNotice').className = (data.blockers || []).length ? 'notice blocked' : 'notice ready';
      }}
    }}
    async function sendAiConsoleMessage(messageOverride) {{
      const input = $('aiConsoleInput');
      const explicitMessage = typeof messageOverride === 'string' ? messageOverride : '';
      const message = (explicitMessage || (input ? input.value : '')).trim();
      if (!message) return;
      appendAiBubble('operator', message);
      if (!explicitMessage && input) input.value = '';
      let result = {{}};
      try {{
        result = await postJson('/api/ai-console', {{message, form:startPreviewPayload()}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', reply:String(err), next_actions:['检查本地 Web 服务。']}};
      }}
      if (result.plan_patch && Object.keys(result.plan_patch).length) {{
        applyAiPlanPatch(result.plan_patch);
      }}
      renderAiConsoleResult(result);
      appendAiBubble('system', result.reply || result.message || '已处理。');
      if (result.execution_plan) renderStartPreview(result);
      else refreshStartPreview();
    }}
    function accountRepairActionItems(summary) {{
      if (!summary || typeof summary !== 'object') return [];
      const items = [];
      const safety = summary.safety_contract || {{}};
      if (safety.no_browser_started || safety.no_submit || safety.no_ai_token_used) {{
        items.push(
          `账号修复安全边界：人工确认后只隔离硬阻断账号；no_browser_started=${{safety.no_browser_started === true ? 'true' : 'false'}}，no_submit=${{safety.no_submit === true ? 'true' : 'false'}}，no_ai_token_used=${{safety.no_ai_token_used === true ? 'true' : 'false'}}。`
        );
      }}
      (summary.operator_steps || []).forEach(step => items.push(step));
      (summary.error_groups || []).slice(0, 6).forEach(group => {{
        const ids = (group.profile_ids_sample || []).length ? `，样例账号：${{group.profile_ids_sample.join(', ')}}` : '';
        items.push(`${{group.error}}：${{group.count || 0}} 个${{ids}}。${{group.recommended_action || ''}}`);
      }});
      return items;
    }}
    function accountRepairApplyItems(repairApply) {{
      if (!repairApply || typeof repairApply !== 'object') return [];
      if (repairApply.stale) {{
        return ['旧账号修复结果已失效：系统已产生新的账号阻断批次，请按最新账号修复计划处理当前失败账号，不要继续勾选旧的重新预检。'];
      }}
      if (repairApply.pending_recheck) {{
        const group = repairApply.profile_group || '当前分组';
        const moved = Number(repairApply.moved_count || 0);
        const safety = repairApply.safety_contract || {{}};
        const safetyText = safety.no_submit || safety.no_browser_started || safety.no_ai_token_used
          ? `安全边界：no_browser_started=${{safety.no_browser_started === true ? 'true' : 'false'}}，no_submit=${{safety.no_submit === true ? 'true' : 'false'}}，no_ai_token_used=${{safety.no_ai_token_used === true ? 'true' : 'false'}}。`
          : '';
        return [`账号修复已执行：${{group}} 已隔离 ${{moved}} 个硬失败账号，等待重新预检。${{safetyText}}`];
      }}
      return [];
    }}
    function table(id, headers, rows) {{
      const head = '<tr>' + headers.map(h => `<th>${{esc(h)}}</th>`).join('') + '</tr>';
      const body = rows.length ? rows.map(r => '<tr>' + r.map(c => `<td>${{formatCell(c)}}</td>`).join('') + '</tr>').join('') : `<tr><td colspan="${{headers.length}}" class="warn">暂无数据，先执行一次采集或刷新状态。</td></tr>`;
      $(id).innerHTML = head + body;
    }}
    function formatCell(value) {{
      if (value && typeof value === 'object' && value.href) {{
        return `<a href="${{esc(value.href)}}" target="_blank" rel="noopener">${{esc(value.text || value.href)}}</a>`;
      }}
      if (value && typeof value === 'object' && value.html) {{
        return value.html;
      }}
      return esc(value);
    }}
    function listItems(items) {{
        return (items && items.length ? items : ['暂无阻断。']).map(item => `<li>${{formatCell(item)}}</li>`).join('');
      }}
    function updateCopyModeNotice() {{
      const text = ($('commentText')?.value || '').trim();
      const mode = $('mode')?.value || 'preflight';
      const manual = !!text;
      const modeLabel = mode === 'live_comment' ? '真实评论' : (mode === 'preflight' ? '触达预检' : '只采集');
      const title = manual ? '评论文案：使用手动填写内容' : '评论文案：自动识别生成';
      const body = manual
        ? (mode === 'live_comment'
          ? `本轮${{modeLabel}}会优先使用你填写的固定文案；仍只对达到触达分数的线索执行。`
          : `已保存手动评论文案，但当前是${{modeLabel}}模式，不会真实提交评论；要发布评论请切换到“采集 + 真实评论”并勾选确认。`)
        : `本轮${{modeLabel}}会根据线索意图自动生成回复；低意向或无效线索不会进入评论队列。`;
      $('copyModeNotice').innerHTML = `<strong>${{esc(title)}}</strong><span>${{esc(body)}}</span>`;
      if ($('currentCopyMode')) $('currentCopyMode').textContent = manual ? `手动文案：${{text.slice(0, 24)}}${{text.length > 24 ? '...' : ''}}` : '自动识别生成';
    }}
    function mergeHourglassData(data) {{
      if (!data || typeof data !== 'object') return;
      hourglassData = {{...hourglassData, ...data}};
      if (data.operations) hourglassData.operations = data.operations;
      if (data.acceptance) hourglassData.acceptance = data.acceptance;
      if (data.client_delivery) hourglassData.client_delivery = data.client_delivery;
      if (data.latest_profile_preflight) hourglassData.latest_profile_preflight = data.latest_profile_preflight;
      if (data.latest_batch) hourglassData.latest_batch = data.latest_batch;
      if (data.campaign_funnel) hourglassData.campaign_funnel = data.campaign_funnel;
      if (data.run_session) hourglassData.run_session = data.run_session;
      if (data.run_session_state) hourglassData.run_session_state = data.run_session_state;
      if (data.run_result) hourglassData.run_result = data.run_result;
      if (data.evidence_bundle) hourglassData.evidence_bundle = data.evidence_bundle;
      if (data.product_capability_summary || data.product_development_goals || data.delivery_boundary) {{
        const mergedBundle = {{...(hourglassData.evidence_bundle || {{}})}};
        if (data.product_capability_summary) mergedBundle.product_capability_summary = data.product_capability_summary;
        if (data.product_development_goals) mergedBundle.product_development_goals = data.product_development_goals;
        if (data.delivery_boundary) mergedBundle.delivery_boundary = data.delivery_boundary;
        hourglassData.evidence_bundle = mergedBundle;
      }}
      renderInfoHourglass(hourglassData);
    }}
    function clampCount(value, min = 0, max = 24) {{
      const n = Number(value || 0);
      if (!Number.isFinite(n) || n <= 0) return min;
      return Math.max(min, Math.min(max, Math.ceil(Math.log2(n + 1) * 3)));
    }}
    function hourglassMetrics(data) {{
      const ops = data.operations || {{}};
      const counts = ops.counts || {{}};
      const funnel = data.campaign_funnel || {{}};
      const acceptance = data.acceptance || {{}};
      const gate = data.client_delivery || {{}};
      const preflight = data.latest_profile_preflight || {{}};
      const bundle = data.evidence_bundle || {{}};
      const pageState = bundle.page_state_summary || {{}};
      const repair = bundle.repair_summary || {{}};
      const risk = bundle.risk_summary || {{}};
      const accountHealth = bundle.account_health_summary || {{}};
      const runRecovery = bundle.run_recovery_summary || {{}};
      const preflightReconciliation = bundle.autonomous_preflight_reconciliation || {{}};
      const autonomy = bundle.autonomy_readiness_summary || {{}};
      const product = bundle.product_capability_summary || {{}};
      const delivery = bundle.delivery_boundary || data.delivery_boundary || {{}};
      const sourceCount = Number(funnel.target_sources || (ops.collection_tasks || []).length || 0);
      const userCount = Number(counts.candidates || funnel.comment_users || 0);
      const leadCount = Number(counts.qualified_leads || funnel.customer_leads || 0);
      const actionCount = Number(counts.actions || funnel.outreach_actions || 0);
      const pageBlockCount = Number((pageState.blocking_count || 0) + (pageState.unknown_count || 0));
      const repairCount = Number(repair.decision_count || (repair.audit_events || []).length || 0);
      const riskCount = Number((risk.risk_action_count || 0) + (risk.blocked_count || 0));
      const accountHealthCount = Number((accountHealth.cooldown_event_count || 0) + (accountHealth.event_count || 0));
      const recoveryCount = Number(runRecovery.recovery_count || (runRecovery.recovered ? 1 : 0));
      const reconciliationCount = Number((preflightReconciliation.matched_route_count || 0) + (preflightReconciliation.unobserved_route_count || 0));
      const reconciliationStage = ['not_observed', 'forecast_missing'].includes(preflightReconciliation.status || '') ? 'middle' : 'bottom';
      const autonomyFailedCount = Number(autonomy.failed_count || ((autonomy.failed_checks || []).length) || 0);
      const autonomyCount = Number((autonomy.passed_count || 0) + autonomyFailedCount);
      const productFailedCount = Number(product.failed_count || ((product.failed_phases || []).length) || 0);
      const productCount = Number((product.passed_count || 0) + productFailedCount);
      const deliveryPendingCount = delivery.final_delivery_ready === false
        ? Number((delivery.pending_scopes || []).length || (delivery.final_delivery_blockers || []).length || delivery.external_validation_pending || delivery.windows_final_artifacts_pending || 0)
        : 0;
      const blockedCount = Number((preflight.unavailable || 0) + (counts.touch_failed || 0) + ((acceptance.blockers || []).length || 0) + ((gate.failed_checks || []).length || 0) + pageBlockCount + (repair.block_count || 0) + (risk.block_execution_count || 0));
      const liveCount = Number(counts.touch_success || funnel.execution_success || 0);
      return [
        {{key:'source', label:'信息源', value:sourceCount, stage:'top'}},
        {{key:'user', label:'互动用户', value:userCount, stage:'top'}},
        {{key:'page', label:'页面状态', value:Number(pageState.snapshot_count || pageBlockCount || 0), stage:pageBlockCount ? 'middle' : 'top'}},
        {{key:'lead', label:'有效线索', value:leadCount, stage:'bottom'}},
        {{key:'action', label:'动作队列', value:actionCount, stage:'bottom'}},
        {{key:'repair', label:'自修复', value:repairCount, stage:(repair.block_count || 0) > 0 ? 'middle' : 'bottom'}},
        {{key:'risk', label:'风险动作', value:riskCount, stage:riskCount ? 'middle' : 'bottom'}},
        {{key:'account', label:'账号健康', value:accountHealthCount, stage:accountHealthCount ? 'middle' : 'bottom'}},
        {{key:'recovery', label:'中断恢复', value:recoveryCount, stage:recoveryCount ? 'middle' : 'bottom'}},
        {{key:'reconcile', label:'预判对账', value:reconciliationCount, stage:reconciliationStage}},
        {{key:'autonomy', label:'自治链路', value:autonomyCount, stage:autonomyFailedCount ? 'middle' : 'bottom'}},
        {{key:'product', label:'产品闭环', value:productCount, stage:productFailedCount ? 'middle' : 'bottom'}},
        {{key:'delivery', label:'交付边界', value:deliveryPendingCount, stage:deliveryPendingCount ? 'middle' : 'bottom'}},
        {{key:'blocked', label:'阻断原因', value:blockedCount, stage:'middle'}},
        {{key:'live', label:'真实触达', value:liveCount, stage:'bottom'}},
      ];
    }}
    function particlePosition(kind, index, total, stage) {{
      const spread = Math.max(1, total - 1);
      const lane = index / spread;
      const jitter = ((index * 37 + kind.length * 11) % 17) - 8;
      const leftBase = stage === 'middle' ? 50 : 28 + lane * 44;
      const topBase = stage === 'top' ? 18 + ((index * 13) % 22) : (stage === 'middle' ? 45 + ((index * 5) % 10) : 66 + ((index * 11) % 22));
      return {{left: Math.max(16, Math.min(84, leftBase + jitter * .42)), top: Math.max(10, Math.min(92, topBase))}};
    }}
    function renderInfoHourglass(data) {{
      const metrics = hourglassMetrics(data || {{}});
      const particles = [];
      metrics.forEach(metric => {{
        const count = clampCount(metric.value, metric.value > 0 ? 1 : 0, metric.key === 'blocked' ? 18 : 26);
        for (let i = 0; i < count; i += 1) {{
          const pos = particlePosition(metric.key, i, count, metric.stage);
          const dim = metric.value <= 0 ? ' dim' : '';
          particles.push(`<span class="particle ${{metric.key}}${{dim}}" title="${{esc(metric.label)}}：${{esc(metric.value)}}" style="left:${{pos.left}}%;top:${{pos.top}}%;--delay:${{((i % 7) * .18).toFixed(2)}}s;--dur:${{(3.2 + ((i + metric.key.length) % 5) * .45).toFixed(2)}}s"></span>`);
        }}
      }});
      $('hourglassParticles').innerHTML = particles.join('');
      $('hourglassLegend').innerHTML = metrics.map(metric => {{
        return `<div class="legendItem" style="color:var(${{metric.key === 'source' ? '--cyan' : metric.key === 'user' ? '--blue' : metric.key === 'lead' ? '--green' : metric.key === 'action' ? '--amber' : metric.key === 'blocked' ? '--red' : metric.key === 'risk' ? '--amber' : metric.key === 'repair' ? '--cyan' : metric.key === 'account' ? '--red' : metric.key === 'recovery' ? '--blue' : metric.key === 'reconcile' ? '--cyan' : metric.key === 'autonomy' ? '--green' : metric.key === 'product' ? '--blue' : metric.key === 'delivery' ? '--amber' : '--muted'}})"><div class="legendLeft"><span class="legendDot"></span><span class="legendLabel">${{esc(metric.label)}}</span></div><span class="legendValue">${{esc(metric.value)}}</span></div>`;
      }}).join('');
      const acceptance = (data || {{}}).acceptance || {{}};
      const gate = (data || {{}}).client_delivery || {{}};
      const preflight = (data || {{}}).latest_profile_preflight || {{}};
      const bundle = (data || {{}}).evidence_bundle || {{}};
      const pageState = bundle.page_state_summary || {{}};
      const repair = bundle.repair_summary || {{}};
      const risk = bundle.risk_summary || {{}};
      const accountHealth = bundle.account_health_summary || {{}};
      const runRecovery = bundle.run_recovery_summary || {{}};
      const preflightReconciliation = bundle.autonomous_preflight_reconciliation || {{}};
      const autonomy = bundle.autonomy_readiness_summary || {{}};
      const product = bundle.product_capability_summary || {{}};
      const delivery = bundle.delivery_boundary || (data || {{}}).delivery_boundary || {{}};
      const runSession = (data || {{}}).run_session || {{}};
      const sessionState = (data || {{}}).run_session_state || runSession.state || '';
      const pageBlocked = Number(pageState.blocking_count || 0) > 0 || Number(pageState.unknown_count || 0) > 0;
      const repairBlocked = Number(repair.block_count || 0) > 0;
      const riskBlocked = Number(risk.block_execution_count || 0) > 0 || Number(risk.blocked_count || 0) > 0;
      const accountHealthBlocked = Number(accountHealth.cooldown_event_count || 0) > 0 || Number(accountHealth.forced_cooldown_count || 0) > 0;
      const recoveredInterrupted = runRecovery.recovered === true;
      const reconciliationObserved = Boolean(preflightReconciliation.schema_version);
      const reconciliationNeedsReview = ['not_observed', 'forecast_missing'].includes(preflightReconciliation.status || '');
      const autonomyFailed = Number(autonomy.failed_count || ((autonomy.failed_checks || []).length) || 0) > 0;
      const productFailed = Number(product.failed_count || ((product.failed_phases || []).length) || 0) > 0;
      const deliveryPending = delivery.final_delivery_ready === false && (
        delivery.external_validation_pending === true
        || delivery.windows_final_artifacts_pending === true
        || (delivery.pending_scopes || []).length > 0
        || (delivery.final_delivery_blockers || []).length > 0
      );
      const accountBlocked = acceptance.readiness === 'blocked_by_accounts' || gate.status === 'blocked_by_accounts' || accountHealthBlocked || Number(preflight.available || 0) <= 0 && Number(preflight.checked || 0) > 0;
      const blocked = pageBlocked || repairBlocked || riskBlocked || recoveredInterrupted || reconciliationNeedsReview || autonomyFailed || productFailed || accountBlocked || ['BLOCKED', 'DEGRADED'].includes(sessionState);
      const ready = !autonomyFailed && !productFailed && (sessionState === 'COMPLETED' || acceptance.readiness === 'pass' || gate.final_delivery_ready === true || autonomy.ready === true || product.ready === true);
      $('hourglassState').textContent = blocked ? (pageBlocked ? '页面状态阻断' : (repairBlocked ? '自修复阻断' : (riskBlocked ? '风险门禁阻断' : (recoveredInterrupted ? '中断恢复已归档' : (reconciliationNeedsReview ? '预判对账待复核' : (autonomyFailed ? '自治链路未就绪' : (productFailed ? '产品闭环未就绪' : '信息卡在账号门'))))))) : (deliveryPending && ready ? '最终交付待验' : (ready ? '自治链路就绪' : (runtimeState.running ? '信息流动中' : '待执行')));
      $('hourglassState').className = blocked ? 'pill danger' : (deliveryPending && ready ? 'pill warn' : (ready ? 'pill ok' : 'pill cyan'));
      $('hourglassSubtitle').textContent = runtimeState.running
        ? `当前阶段：${{sessionState || runtimeState.last_stage || '采集/预检'}}`
        : `批次：${{((data || {{}}).latest_batch || {{}}).id || ((data || {{}}).campaign_funnel || {{}}).batch_id || '-'}}`;
      $('hourglassDecision').className = blocked ? 'hourglassDecision blocked' : (deliveryPending && ready ? 'hourglassDecision' : (ready ? 'hourglassDecision ready' : 'hourglassDecision'));
      if (pageBlocked) {{
        $('hourglassDecisionTitle').textContent = Number(pageState.unknown_count || 0) > 0 ? '未知页面状态进入证据包' : '页面状态阻断执行';
        $('hourglassDecisionBody').textContent = `page_snapshots=${{pageState.snapshot_count || 0}} / blocking=${{pageState.blocking_count || 0}} / unknown=${{pageState.unknown_count || 0}}。查看截图、DOM 摘要和 sidecar 后再继续。`;
      }} else if (repairBlocked) {{
        const events = repair.audit_events || repair.decisions || [];
        const first = events.length ? events[0] : {{}};
        const steps = (first.executable_steps || []).map(step => step.step || step).filter(Boolean).slice(0, 4).join(', ');
        $('hourglassDecisionTitle').textContent = '自修复策略阻断继续执行';
        $('hourglassDecisionBody').textContent = `repair_decisions=${{repair.decision_count || events.length || 0}} / retries=${{repair.retry_count || 0}} / degrade=${{repair.degrade_count || 0}}。机器步骤：${{steps || '查看 repair_summary'}}。`;
      }} else if (riskBlocked) {{
        const decisions = risk.decisions || [];
        const first = decisions.length ? decisions[0] : {{}};
        const actions = (first.risk_actions || []).map(step => step.step || step).filter(Boolean).slice(0, 4).join(', ');
        $('hourglassDecisionTitle').textContent = '风险门禁阻断执行';
        $('hourglassDecisionBody').textContent = `risk_decisions=${{risk.decision_count || decisions.length || 0}} / risk_actions=${{risk.risk_action_count || 0}} / human_review=${{risk.human_review_required_count || 0}}。门禁动作：${{actions || '查看 risk_summary'}}。`;
      }} else if (accountHealthBlocked) {{
        $('hourglassDecisionTitle').textContent = '账号健康进入冷却';
        $('hourglassDecisionBody').textContent = `account_health_events=${{accountHealth.event_count || 0}} / cooldown=${{accountHealth.cooldown_event_count || 0}} / consecutive_failure=${{accountHealth.consecutive_failure_cooldown_count || 0}}。查看 account_health_summary 和账号修复清单。`;
      }} else if (recoveredInterrupted) {{
        $('hourglassDecisionTitle').textContent = '中断会话已自动归档';
        $('hourglassDecisionBody').textContent = `recovered=true / reason=${{runRecovery.latest_reason || '-'}} / last_stage=${{runRecovery.last_stage || '-'}} / result=${{runRecovery.result_error || '-'}}。查看 run_recovery_summary 和最后 checkpoint。`;
      }} else if (reconciliationNeedsReview) {{
        const states = (preflightReconciliation.actual_page_states || []).slice(0, 4).join(', ');
        const reasons = (preflightReconciliation.actual_risk_reasons || []).slice(0, 4).join(', ');
        $('hourglassDecisionTitle').textContent = '启动前预判未被实际证据命中';
        $('hourglassDecisionBody').textContent = `status=${{preflightReconciliation.status || '-'}} / matched=${{preflightReconciliation.matched_route_count || 0}} / unobserved=${{preflightReconciliation.unobserved_route_count || 0}}。实际页面：${{states || '-'}}；风险原因：${{reasons || '-'}}。`;
      }} else if (autonomyFailed) {{
        const failed = (autonomy.failed_checks || []).slice(0, 4).join(', ');
        $('hourglassDecisionTitle').textContent = '自治链路未达到自动执行标准';
        $('hourglassDecisionBody').textContent = `autonomy_ready=${{autonomy.ready === true}} / passed=${{autonomy.passed_count || 0}} / failed=${{autonomy.failed_count || (autonomy.failed_checks || []).length || 0}}。失败检查：${{failed || '查看 autonomy_readiness_summary'}}。`;
      }} else if (productFailed) {{
        const failed = (product.failed_phases || []).slice(0, 4).join(', ');
        $('hourglassDecisionTitle').textContent = '产品能力闭环未完成';
        $('hourglassDecisionBody').textContent = `product_ready=${{product.ready === true}} / passed=${{product.passed_count || 0}} / failed=${{product.failed_count || (product.failed_phases || []).length || 0}}。未闭环阶段：${{failed || '查看 product_capability_summary'}}。`;
      }} else if (blocked) {{
        $('hourglassDecisionTitle').textContent = '粒子在账号门堆积';
        $('hourglassDecisionBody').textContent = `checked=${{preflight.checked || 0}} / available=${{preflight.available || 0}}。请先处理账号内核、登录或代理问题，再重新预检。`;
      }} else if (deliveryPending && ready) {{
        const scopes = (delivery.pending_scopes || []).slice(0, 4).join(', ') || 'external_authorized_execution, windows_final_artifacts';
        const next = (delivery.next_actions || []).slice(0, 2).join('；') || delivery.boundary_note || '补齐真实授权执行和 Windows 最终包证据。';
        $('hourglassDecisionTitle').textContent = '本地自治已就绪，最终交付仍待验';
        $('hourglassDecisionBody').textContent = `local_ready=${{delivery.local_product_capability_ready === true}} / final_delivery_ready=${{delivery.final_delivery_ready === true}} / pending=${{scopes}}。下一步：${{next}}`;
      }} else if (ready) {{
        $('hourglassDecisionTitle').textContent = '自治链路可审计';
        const reconciliationText = reconciliationObserved ? ` / 预判对账=${{preflightReconciliation.status || '-'}} / matched=${{preflightReconciliation.matched_route_count || 0}}` : '';
        const recoveryText = runRecovery.schema_version ? ` / 中断恢复=${{runRecovery.recovered === true}}` : '';
        $('hourglassDecisionBody').textContent = `autonomy_ready=${{autonomy.ready === true}} / product_ready=${{product.ready === true}} / passed=${{autonomy.passed_count || 0}} / failed=${{autonomy.failed_count || 0}}${{reconciliationText}}${{recoveryText}}。当前批次已有可审计结果，可进入报告中心查看证据和验收状态。`;
      }} else {{
        $('hourglassDecisionTitle').textContent = runtimeState.running ? 'AI 正在筛选信息' : '等待信息流入';
        $('hourglassDecisionBody').textContent = runtimeState.running ? '来源和用户粒子会进入上半区，线索和动作会沉淀到下半区，阻断会在中部堆积。' : '开始获客后，来源、用户、线索、动作和阻断会以粒子形式实时更新。';
      }}
    }}
    function renderDecision(data) {{
      if (apiNoticeActive()) return;
      const a = data.acceptance || {{}};
      const gate = data.client_delivery || {{}};
      const batch = data.latest_batch || {{}};
      const ctx = a.execution_context || {{}};
      const p = data.latest_profile_preflight || {{}};
      const decision = $('operatorDecision');
      const title = $('operatorDecisionTitle');
      const body = $('operatorDecisionBody');
      decision.className = 'notice';
      if (runtimeState.running) {{
        if (runtimeState.paused) {{
          title.textContent = '自动执行已暂停';
          body.textContent = `已等待 ${{runtimeState.elapsed_seconds || 0}} 秒。点击继续后会恢复当前自动流程。`;
        }} else {{
          title.textContent = '自动执行中：正在启动/检测配置';
          body.textContent = `已等待 ${{runtimeState.elapsed_seconds || 0}} 秒。当前阶段：${{runtimeState.last_stage || '配置预检/页面检测'}}。`;
        }}
      }} else if (a.readiness === 'pass') {{
        decision.classList.add('ready');
        title.textContent = '可以进入客户验收';
        body.textContent = `已完成采集和触达链路。批次：${{batch.id || '-'}}`;
      }} else if (a.readiness === 'partial') {{
        title.textContent = '账号可用，继续观察采集/触达';
        body.textContent = `账号 available=${{p.available || 0}}，需要看到 DONE collection 和 START action_*。`;
      }} else if (a.readiness === 'blocked_by_accounts') {{
        decision.classList.add('blocked');
        title.textContent = '账号池无可执行账号，已禁止重复启动';
        body.textContent = `目标规划已完成 ${{ctx.planned_source_count || 0}} 个来源；账号预检 checked=${{p.checked || 0}} / available=${{p.available || 0}}。为避免消耗 ixBrowser 启动次数，修复账号前不会再启动配置。`;
      }} else if (a.readiness === 'blocked_by_environment') {{
        decision.classList.add('blocked');
        title.textContent = '本地执行环境阻断';
        body.textContent = `客户端门禁：${{gate.status || 'blocked_by_environment'}}；失败检查：${{(gate.failed_checks || []).join(',') || '-'}}。`;
      }} else {{
        title.textContent = '等待开始获客';
        body.textContent = '输入推广目标并选择分组后开始执行。';
      }}
      $('operatorNextList').innerHTML = listItems([...(a.blockers || []), ...(a.next_actions || []).map(x => '下一步：' + x)]);
    }}
    function renderFunnelFromSnapshot(data) {{
      const f = data.campaign_funnel || {{}};
      const items = [
        ['账号可用', f.profile_ok || 0, (f.profile_ok || 0) > 0],
        ['打开页面', f.page_opened || 0, (f.page_opened || 0) > 0],
        ['发现内容', f.content_found || 0, (f.content_found || 0) > 0],
        ['评论用户', f.comment_users || 0, (f.comment_users || 0) > 0],
        ['高意向', f.high_intent || 0, (f.high_intent || 0) > 0],
        ['触达队列', f.outreach_actions || 0, (f.outreach_actions || 0) > 0],
        ['执行成功', f.execution_success || 0, (f.execution_success || 0) > 0],
      ];
      const firstZero = items.findIndex(row => !row[2]);
      $('funnelBatch').textContent = f.batch_id ? `${{f.batch_id}} / ${{f.batch_status || '-'}}` : '未开始';
      $('funnelSteps').innerHTML = items.map((row, index) => {{
        const cls = row[2] ? 'done' : (index === firstZero ? 'blocked' : 'active');
        return `<div class="step ${{cls}}"><span>${{esc(row[0])}}</span><b>${{esc(row[1])}}</b></div>`;
      }}).join('');
    }}
    function renderFunnelFromAcceptance(data) {{
      const a = data.acceptance || {{}};
      const p = data.latest_profile_preflight || {{}};
      const checks = a.checks || {{}};
      const currentAvailable = Number(p.available || checks.profile_available_count || 0);
      const currentChecked = Number(p.checked || 0);
      const items = [
        ['账号可用', currentAvailable, currentAvailable > 0, currentChecked ? `checked=${{currentChecked}}` : '未预检'],
        ['任务规划', checks.target_planned ? 1 : 0, !!checks.target_planned, 'PLAN'],
        ['开始批次', checks.campaign_started ? 1 : 0, !!checks.campaign_started, 'START'],
        ['采集完成', checks.collection_done ? 1 : 0, !!checks.collection_done, 'DONE'],
        ['触达启动', checks.action_started ? 1 : 0, !!checks.action_started, 'ACTION'],
        ['可验收', a.readiness === 'pass' ? 1 : 0, a.readiness === 'pass', a.readiness || 'not_started'],
      ];
      const firstZero = items.findIndex(row => !row[2]);
      $('funnelSteps').innerHTML = items.map((row, index) => {{
        const cls = row[2] ? 'done' : (index === firstZero ? 'blocked' : 'active');
        return `<div class="step ${{cls}}"><span>${{esc(row[0])}}</span><b>${{esc(row[1])}}</b><span>${{esc(row[3])}}</span></div>`;
      }}).join('');
    }}
	    function renderProfileLaunchList(data) {{
	      const a = data.acceptance || {{}};
	      const p = data.latest_profile_preflight || {{}};
      const ops = data.operations || {{}};
      const queueRows = ops.profile_queue || [];
      const details = a.profile_preflight_details || [];
	      const checked = Math.max(Number(p.checked || 0), details.length);
	      const available = Math.max(Number(p.available || 0), details.filter(item => item.status === '可用').length);
	      const moved = details.filter(item => item.quarantine_move && item.quarantine_move.ok).length;
	      const loginRequired = details.filter(item => item.error === 'LOGIN_REQUIRED').length;
	      const transient = details.filter(item => ['PAGE_OPEN_FAILED','PROFILE_PREFLIGHT_TIMEOUT','IXBROWSER_NETWORK_ERROR','IXBROWSER_SERVER_BUSY'].includes(item.error)).length;
	      const blocked = Math.max(0, checked - available);
	      $('profileLaunchSummary').textContent = runtimeState.running
	        ? `自动检测中 / ${{checked}} 已返回 / ${{available}} 可用`
	        : `已检查 ${{checked}} / 可用 ${{available}}`;
		      const autoLimit = inferAutoLimit(runtimeState.last_stage, checked);
		      const progressPct = autoLimit ? Math.min(100, Math.round((checked / autoLimit) * 100)) : (checked ? 100 : 0);
		      const primary = primaryLaunchIssue(details);
			      const stats = [
			        ['已检查', checked, ''],
			        ['可执行', available, 'ok'],
			        ['已关闭/跳过', blocked, blocked ? 'warn' : ''],
			        ['已移组', moved, moved ? 'bad' : ''],
			        ['临时异常', transient, transient ? 'warn' : ''],
			      ].map(([label, value, cls]) => `<div class="launchStat ${{cls}}"><span>${{esc(label)}}</span><b>${{esc(value)}}</b></div>`).join('');
		      const filtered = filterLaunchDetails(details, queueRows);
		      const rows = filtered.length
		        ? filtered.slice(0, 80).map(renderProfileLaunchRow).join('')
		        : `<div class="launchEmpty">${{runtimeState.running ? '正在启动配置并检测 TikTok 登录态，结果会按账号返回。' : '点击开始获客后，这里会显示本轮配置启动、登录态、移组和跳过原因。'}}</div>`;
		      $('profileLaunchPanel').innerHTML = `
		        <div class="launchCommand">
		          <div class="launchProgress">
		            <div class="launchProgressTop"><span>自动检测进度</span><b>${{checked}} / ${{autoLimit || checked || '-'}}</b></div>
		            <div class="progressTrack"><div class="progressFill" style="width:${{progressPct}}%"></div></div>
		          </div>
		          <div class="launchCause">
		            <strong>${{esc(primary.title)}}</strong>
		            <div>${{esc(primary.body)}}</div>
		          </div>
		        </div>
		        <div class="launchStats">${{stats}}</div>
		        <div class="launchTools">
		          <div class="launchFilters">${{renderLaunchFilters(details)}}</div>
		        <div class="launchCount">显示 ${{filtered.length}} / ${{Math.max(details.length, queueRows.length)}} 个配置</div>
		        </div>
		        <div class="launchQueue">${{rows}}</div>`;
		    }}
		    function inferAutoLimit(stage, checked) {{
		      const text = String(stage || '');
		      const match = text.match(/auto_limit=(\\d+)|max_checked=(\\d+)/);
		      return match ? Number(match[1] || match[2]) : (checked ? Math.max(checked, 60) : 0);
		    }}
		    function renderLaunchFilters(details) {{
		      const counts = {{
		        all: details.length,
		        usable: details.filter(item => item.status === '可用').length,
		        login: details.filter(item => item.error === 'LOGIN_REQUIRED').length,
		        transient: details.filter(item => ['PAGE_OPEN_FAILED','PROFILE_PREFLIGHT_TIMEOUT','IXBROWSER_NETWORK_ERROR','IXBROWSER_SERVER_BUSY'].includes(item.error)).length,
		        moved: details.filter(item => item.quarantine_move && item.quarantine_move.ok).length,
		      }};
		      const labels = [
		        ['all', '全部'],
		        ['usable', '可执行'],
		        ['login', '未登录'],
		        ['transient', '临时异常'],
		        ['moved', '已移组'],
		      ];
		      return labels.map(([key, label]) => `<button class="filterBtn ${{launchFilter === key ? 'active' : ''}}" data-launch-filter="${{key}}">${{esc(label)}} ${{counts[key] || 0}}</button>`).join('');
		    }}
		    function filterLaunchDetails(details, queueRows) {{
		      const byId = {{}};
		      details.forEach(item => byId[item.profile_id] = {{...item}});
		      queueRows.forEach(item => {{
		        const base = byId[item.profile_id] || {{profile_id:item.profile_id, status:'排队中', error:''}};
		        byId[item.profile_id] = {{...base, queue_status:item.status, queue_index:item.queue_index, sources_done:item.sources_done, source_value:item.source_value}};
		      }});
		      const merged = Object.values(byId).sort((a,b) => Number(a.queue_index || 9999) - Number(b.queue_index || 9999));
		      if (launchFilter === 'usable') return merged.filter(item => item.status === '可用' || ['running','completed','quota_reached'].includes(item.queue_status));
		      if (launchFilter === 'login') return merged.filter(item => item.error === 'LOGIN_REQUIRED');
		      if (launchFilter === 'transient') return merged.filter(item => ['PAGE_OPEN_FAILED','PROFILE_PREFLIGHT_TIMEOUT','IXBROWSER_NETWORK_ERROR','IXBROWSER_SERVER_BUSY'].includes(item.error));
		      if (launchFilter === 'moved') return merged.filter(item => item.quarantine_move && item.quarantine_move.ok);
		      return merged;
		    }}
		    function primaryLaunchIssue(details) {{
		      if (!details.length) return runtimeState.running
		        ? {{title:'正在建立账号队列', body:'系统正在启动配置并读取 TikTok 登录态。'}}
		        : {{title:'等待执行', body:'点击开始获客后，系统会自动启动配置、跳过异常账号并记录处理结果。'}};
		      const usable = details.filter(item => item.status === '可用').length;
			      if (usable > 0) return {{title:'已有可执行账号', body:`找到 ${{usable}} 个可用账号；已关闭的配置是预检回收或异常换号，不是程序闪退。`}};
		      const counts = details.reduce((acc, item) => {{ acc[item.error || 'UNKNOWN'] = (acc[item.error || 'UNKNOWN'] || 0) + 1; return acc; }}, {{}});
		      const top = Object.entries(counts).sort((a,b) => b[1] - a[1])[0] || ['UNKNOWN', 0];
		      const info = profileStatusInfo({{error: top[0]}});
		      return {{title:`主阻断：${{info.label}} ${{top[1]}} 个`, body:`${{info.reason}}。${{info.action}}；系统会继续跳过异常账号并寻找可用账号。`}};
		    }}
	    function renderProfileLaunchRow(item) {{
	      const status = profileStatusInfo(item);
		      const move = formatQuarantineMove(item.quarantine_move);
		      const evidence = item.evidence ? `<a href="/api/download?path=${{encodeURIComponent(item.evidence)}}" target="_blank" rel="noopener">查看证据</a>` : '-';
		      const message = compactProfileMessage(item.message || item.error || '-');
		      const closeText = closeActionLabel(item);
		      return `
	        <div class="launchRow ${{status.rowClass}}">
	          <div class="launchMeta">
	            <span class="launchLabel">配置${{item.queue_index ? ' / 队列' : ''}}</span>
	            <span class="launchId">#${{esc(item.profile_id || '-')}}${{item.queue_index ? ' · ' + esc(item.queue_index) : ''}}</span>
	          </div>
	          <div><span class="statusBadge ${{status.badgeClass}}">${{esc(status.label)}}</span></div>
	          <div class="launchMeta">
	            <span class="launchLabel">判断原因</span>
	            <span class="launchValue" title="${{esc(message)}}">${{esc(queueStatusLabel(item) || status.reason)}}</span>
	          </div>
		          <div class="launchMeta">
		            <span class="launchLabel">浏览器处理</span>
		            <span class="launchValue" title="${{esc(closeText)}}">${{esc(closeText)}}</span>
		          </div>
		          <div class="launchMeta">
		            <span class="launchLabel">运营动作</span>
		            <span class="launchValue" title="${{esc(item.source_value || status.action || move)}}">${{esc(item.sources_done ? '已处理来源 ' + item.sources_done : status.action)}} · ${{evidence}}</span>
		          </div>
		        </div>`;
		    }}
		    function closeActionLabel(item) {{
		      const hint = String(item.operator_hint || '').trim();
		      if (hint) return hint;
		      const action = String(item.close_action || '');
		      if (action === 'preflight_ok_released') return '预检通过后自动关闭，不是闪退';
		      if (action === 'closed_and_switched') return '已关闭并自动换号';
		      if (action === 'closed_and_skipped') return '异常关闭并跳过';
		      if ((item.status || '') === '可用') return '预检通过后自动回收';
		      if (item.error === 'LOGIN_REQUIRED') return '登录态不足，关闭换号';
		      if (item.error) return '预检异常，关闭跳过';
		      return '-';
		    }}
	    function queueStatusLabel(item) {{
	      const status = String(item.queue_status || '');
	      if (status === 'waiting') return '等待进入自动执行队列';
	      if (status === 'running') return '正在执行本配置';
	      if (status === 'completed') return '本配置完成一个来源';
	      if (status === 'quota_reached') return '已达本配置采集配额，自动切下一个';
	      if (status === 'skipped') return '异常已跳过，不阻断后续队列';
	      if (status === 'failed') return '本配置执行失败，继续下一个';
	      return '';
	    }}
	    function profileStatusInfo(item) {{
		      if ((item.status || '') === '可用') return {{label:'可执行', reason:'登录态正常', action:'继续采集触达', rowClass:'ok', badgeClass:'ok'}};
	      const error = String(item.error || '');
	      const map = {{
		        LOGIN_REQUIRED: ['未登录', '出现登录页/登录弹窗', '已关闭并换号，需重新登录'],
	        PAGE_OPEN_FAILED: ['页面失败', 'TikTok 页面打开超时', '系统继续下一个账号'],
	        PROFILE_PREFLIGHT_TIMEOUT: ['检测超时', '账号启动或页面检测超时', '系统继续下一个账号'],
	        IXBROWSER_NETWORK_ERROR: ['网络异常', 'ixBrowser 本地连接中断', '稍后自动重试或检查代理'],
	        IXBROWSER_SERVER_BUSY: ['浏览器繁忙', 'ixBrowser 返回繁忙', '稍后自动重试'],
	        IXBROWSER_KERNEL_MISMATCH: ['内核不匹配', '配置内核版本不符合当前环境', '调整内核版本后再用'],
	        CAPTCHA_DETECTED: ['验证拦截', '出现验证码或风控', '人工处理后再用'],
	        PROXY_FAILED: ['代理异常', '代理不可用或连接失败', '修复代理后再用'],
	      }};
	      const picked = map[error] || ['不可用', error || '未知异常', '系统已跳过'];
	      const hard = ['LOGIN_REQUIRED','IXBROWSER_KERNEL_MISMATCH','CAPTCHA_DETECTED','PROXY_FAILED'].includes(error);
	      return {{label:picked[0], reason:picked[1], action:picked[2], rowClass: hard ? 'blocked' : 'warn', badgeClass: hard ? 'blocked' : 'warn'}};
	    }}
	    function compactProfileMessage(message) {{
	      return String(message || '').replace(/\\s+/g, ' ').slice(0, 180);
	    }}
    function formatQuarantineMove(move) {{
      if (!move || !move.attempted) return '-';
      if (move.ok) return `已移入${{move.group_name || '封禁账号'}}`;
      return `移动失败：${{move.error_message || move.error_code || '未知错误'}}`;
    }}
    function remediationRows(data) {{
      const a = data.acceptance || {{}};
      const mvp = data.mvp_acceptance || {{}};
      const rows = [
        ['本地验收输入模板', '可下载', {{text:'reachops_acceptance_inputs.example.ps1', href:'/api/acceptance-input-template'}}],
      ];
      if (mvp.path) rows.push(['产品经理 MVP 验收摘要', mvp.mvp_local_ready ? '本地MVP通过' : (mvp.status || '未生成'), {{text:mvp.path, href:'/api/download?path=' + encodeURIComponent(mvp.path)}}]);
      Object.entries(a.profile_error_summary || {{}}).forEach(([error, item]) => {{
        rows.push([
          '账号修复',
          error,
          `count=${{item.count || 0}} profiles=${{(item.profile_ids || []).slice(0, 16).join(',') || '-'}}`
        ]);
      }});
      const report = data.remediation_report || {{}};
      if (report.csv_path) rows.push(['修复清单 CSV', '已生成', {{text: report.csv_path, href: '/api/download?path=' + encodeURIComponent(report.csv_path)}}]);
      if (report.json_path) rows.push(['修复清单 JSON', '已生成', {{text: report.json_path, href: '/api/download?path=' + encodeURIComponent(report.json_path)}}]);
      if (report.markdown_path) rows.push(['验收报告 Markdown', '已生成', {{text: report.markdown_path, href: '/api/download?path=' + encodeURIComponent(report.markdown_path)}}]);
      if (report.account_plan_markdown_path) rows.push(['账号修复计划 Markdown', '已生成', {{text: report.account_plan_markdown_path, href: '/api/download?path=' + encodeURIComponent(report.account_plan_markdown_path)}}]);
      if (report.account_plan_json_path) rows.push(['账号修复计划 JSON', '已生成', {{text: report.account_plan_json_path, href: '/api/download?path=' + encodeURIComponent(report.account_plan_json_path)}}]);
      if (report.guide_path) rows.push(['客户验收指南', '已生成', {{text: report.guide_path, href: '/api/download?path=' + encodeURIComponent(report.guide_path)}}]);
      if (report.index_path) rows.push(['验收包首页 HTML', '已生成', {{text: report.index_path, href: '/api/download?path=' + encodeURIComponent(report.index_path)}}]);
      if (report.manifest_path) rows.push(['验收包 Manifest', '已生成', {{text: report.manifest_path, href: '/api/download?path=' + encodeURIComponent(report.manifest_path)}}]);
      if (report.latest_account_plan_markdown_path) rows.push(['最新账号修复计划', '已生成', {{text: report.latest_account_plan_markdown_path, href: '/api/download?path=' + encodeURIComponent(report.latest_account_plan_markdown_path)}}]);
      if (report.latest_account_plan_json_path) rows.push(['最新账号修复计划 JSON', '已生成', {{text: report.latest_account_plan_json_path, href: '/api/download?path=' + encodeURIComponent(report.latest_account_plan_json_path)}}]);
      if (report.latest_guide_path) rows.push(['最新验收指南', '已生成', {{text: report.latest_guide_path, href: '/api/download?path=' + encodeURIComponent(report.latest_guide_path)}}]);
      if (report.latest_index_path) rows.push(['最新验收包首页', '已生成', {{text: report.latest_index_path, href: '/api/download?path=' + encodeURIComponent(report.latest_index_path)}}]);
      if (report.latest_manifest_path) rows.push(['最新 Manifest', '已生成', {{text: report.latest_manifest_path, href: '/api/download?path=' + encodeURIComponent(report.latest_manifest_path)}}]);
      return rows;
    }}
    function statusChip(label, tone='') {{
      return {{html:`<span class="chip ${{esc(tone)}}">${{esc(label)}}</span>`}};
    }}
    function chipList(items) {{
      const chips = (items || []).filter(Boolean).map(item => {{
        const tone = item.tone || '';
        return `<span class="chip ${{esc(tone)}}">${{esc(item.label || item)}}</span>`;
      }}).join('');
      return {{html:`<div class="chipWrap">${{chips || '<span class="chip">未识别</span>'}}</div>`}};
    }}
    function actionLink(text, href) {{
      if (!href) return '-';
      return {{html:`<a class="sourceLink" href="${{esc(href)}}" target="_blank" rel="noopener">${{esc(text || '查看')}}</a>`}};
    }}
    function compactText(text, fallback='-') {{
      const value = String(text || '').replace(/\\s+/g, ' ').trim();
      return value || fallback;
    }}
    function safeDownload(path) {{
      const value = String(path || '').trim();
      if (!value) return '';
      if (/^https?:\\/\\//.test(value)) return value;
      if (value.startsWith('evidence://')) return '';
      return '/api/download?path=' + encodeURIComponent(value);
    }}
    function groupOptionLabel(group) {{
      const name = String(group.name || '');
      const label = String(group.count_label || (group.count_known ? `${{Number(group.count || 0)}}账号` : '数量未返回'));
      return `${{name}}（${{label}}）`;
    }}
    function selectedGroupPayload(name) {{
      const target = String(name || '').toLowerCase();
      return (loadedGroups || []).find(g => String(g.name || '').toLowerCase() === target) || {{}};
    }}
	    function updateSelectedGroupQuantity() {{
	      const group = selectedGroupPayload($('group').value);
	      const label = group && group.name ? groupOptionLabel(group) : ($('group').value || '-');
	      const countKnown = group && group.count_known;
	      const countLabel = group && group.name
	        ? String(group.count_label || (countKnown ? `${{Number(group.count || 0)}}账号` : '数量未返回'))
	        : '未刷新';
	      $('currentGroup').textContent = label;
	      $('selectedGroupName').textContent = group && group.name ? String(group.name) : ($('group').value || '-');
	      $('selectedGroupCount').textContent = countLabel;
	      $('selectedGroupCount').className = countKnown ? 'count' : 'count unknown';
	      $('selectedGroupId').textContent = group && group.group_id ? String(group.group_id) : '-';
	    }}
    function formatGroupSummary(groups, data) {{
      const known = groups.filter(g => g.count_known).length;
      const knownTotal = groups.reduce((sum, group) => sum + (group.count_known ? Number(group.count || 0) : 0), 0);
      const totalProfiles = Number(data.profile_count || 0) || (known === groups.length ? knownTotal : 0);
      const suffix = totalProfiles > 0 ? ` / 账号 ${{totalProfiles}}` : '';
      if (!groups.length) return '未读取到 ixBrowser 配置分组；不可启动';
      if (known) return `分组 ${{groups.length}} / 已统计 ${{known}}${{suffix}}`;
      const error = data.count_resolution_error ? `：${{data.count_resolution_error}}` : '';
      return `分组 ${{groups.length}} / 账号数未返回${{error}}`;
    }}
	    function renderGroupError(data) {{
	      const error = String(data.error || '读取失败');
	      const detail = String(data.error_detail || data.count_resolution_error || '');
	      $('groupCount').textContent = '读取失败：' + error;
	      $('groupCount').title = detail || error;
	      $('selectedGroupName').textContent = '-';
	      $('selectedGroupCount').textContent = '读取失败';
	      $('selectedGroupCount').className = 'count unknown';
	      $('selectedGroupId').textContent = '-';
		      const box = $('groupDetails');
	      if (box) {{
	        box.classList.add('hasContent');
	        box.innerHTML = `<div class="notice blocked"><strong>${{esc(error)}}</strong><div class="sub">确认 ixBrowser 已启动，并开启 Local API；默认端口为 53200。如端口不同，在面板 API 端口输入框应用后再刷新分组。</div></div>`;
	      }}
	    }}
	    function renderGroupDetails(groups, selectedName='') {{
	      const box = $('groupDetails');
	      if (!box) return;
	      box.classList.remove('hasContent');
	      box.innerHTML = '';
	    }}
    function leadIntentChips(row) {{
      const labels = [];
      const score = Number(row.score || row.qualify_score || 0);
      const leadType = String(row.lead_type_label || row.lead_type || '');
      if (leadType) labels.push({{label: leadType, tone: score >= 70 ? 'ok' : (score >= 50 ? 'warn' : '')}});
      const confidence = Number(row.intent_confidence || 0);
      if (confidence > 0) labels.push({{label: `意图置信 ${{confidence}}%`, tone: confidence >= 70 ? 'ok' : 'warn'}});
      const tags = Array.isArray(row.intent_labels) ? row.intent_labels : [];
      tags.slice(0, 3).forEach(label => labels.push({{label}}));
      if (!labels.length) labels.push({{label: score >= 70 ? `购买意图 ${{score}}%` : (score >= 50 ? `有效线索 ${{score}}%` : '低意向'), tone: score >= 70 ? 'ok' : (score >= 50 ? 'warn' : '')}});
      return chipList(labels);
    }}
    function statusTone(status) {{
      const value = String(status || '').toLowerCase();
      if (['contacted','completed','success'].includes(value)) return 'ok';
      if (['failed','needs_retry','retryable','skipped','rejected'].includes(value)) return value === 'skipped' ? 'warn' : 'bad';
      if (['queued','pending_review','approved','ready_to_execute','running'].includes(value)) return 'warn';
      return '';
    }}
    function leadStatusLabel(row) {{
      const stage = String(row.current_status || row.lifecycle_stage || row.status || 'new');
      const map = {{
        new:'新线索',
        pending_review:'待入队',
        approved:'已批准',
        ready_to_execute:'待执行',
        queued:'已入队',
        contacted:'已触达',
        needs_retry:'失败待重试',
        rejected:'已跳过',
        skipped:'已跳过',
      }};
      return statusChip(map[stage] || stage, statusTone(stage));
    }}
    function outreachStatusLabel(row) {{
      const status = String(row.status || 'queued');
      const map = {{
        pending_review:'待复核',
        approved:'已批准',
        ready_to_execute:'待执行',
        queued:'已入队',
        running:'执行中',
        completed:'成功',
        success:'成功',
        failed:'失败',
        skipped:'已跳过',
        retryable:'可重试',
        account_switched:'已切换账号',
      }};
      return statusChip(map[status] || status, statusTone(status));
    }}
    function applyLeadFilter(rows) {{
      if (leadFilter === 'high') return rows.filter(row => Number(row.score || 0) >= 70);
      if (leadFilter === 'untouched') return rows.filter(row => !['contacted','completed','success'].includes(String(row.current_status || row.lifecycle_stage || row.status || '')));
      if (leadFilter === 'touched') return rows.filter(row => ['contacted','completed','success'].includes(String(row.current_status || row.lifecycle_stage || row.status || '')));
      if (leadFilter === 'failed') return rows.filter(row => ['needs_retry','failed','retryable'].includes(String(row.current_status || row.lifecycle_stage || row.status || '')));
      if (leadFilter === 'skipped') return rows.filter(row => ['rejected','skipped'].includes(String(row.current_status || row.lifecycle_stage || row.status || '')));
      return rows;
    }}
    function applyOutreachFilter(rows) {{
      if (outreachFilter === 'high') return rows.filter(row => Number(row.lead_score || row.score || 0) >= 70);
      if (outreachFilter === 'untouched') return rows.filter(row => ['queued','pending_review','approved','ready_to_execute','running'].includes(String(row.status || 'queued')));
      if (outreachFilter === 'touched') return rows.filter(row => ['completed','success'].includes(String(row.status || '')));
      if (outreachFilter === 'failed') return rows.filter(row => ['failed','retryable'].includes(String(row.status || '')));
      if (outreachFilter === 'skipped') return rows.filter(row => String(row.status || '') === 'skipped');
      return rows;
    }}
    function filterButtons(containerId, active, counts, attr) {{
      const labels = [
        ['all', '全部'],
        ['high', '高意向'],
        ['untouched', '未触达'],
        ['touched', '已触达'],
        ['failed', '失败'],
        ['skipped', '已跳过'],
      ];
      $(containerId).innerHTML = labels.map(([key, label]) => `<button class="filterBtn ${{active === key ? 'active' : ''}}" data-${{attr}}="${{key}}">${{esc(label)}} ${{counts[key] || 0}}</button>`).join('');
    }}
    function renderLeadPanel(ops) {{
      const rows = ops.lead_view || [];
      const counts = {{
        all: rows.length,
        high: rows.filter(row => Number(row.score || 0) >= 70).length,
        untouched: rows.filter(row => !['contacted','completed','success'].includes(String(row.current_status || row.lifecycle_stage || row.status || ''))).length,
        touched: rows.filter(row => ['contacted','completed','success'].includes(String(row.current_status || row.lifecycle_stage || row.status || ''))).length,
        failed: rows.filter(row => ['needs_retry','failed','retryable'].includes(String(row.current_status || row.lifecycle_stage || row.status || ''))).length,
        skipped: rows.filter(row => ['rejected','skipped'].includes(String(row.current_status || row.lifecycle_stage || row.status || ''))).length,
      }};
      filterButtons('leadFilters', leadFilter, counts, 'lead-filter');
      const filtered = applyLeadFilter(rows);
      $('leadPanelSummary').textContent = `有效 ${{counts.all}} / 高意向 ${{counts.high}} / 已触达 ${{counts.touched}}`;
      $('leadTableMeta').textContent = `显示 ${{filtered.length}} / ${{rows.length}} 条`;
      table('leadTable', ['用户', '评分', '意图', '命中原因', '来源视频', '推荐触达', '当前状态'], filtered.slice(0, 80).map(row => [
        row.username || '-',
        row.score || 0,
        leadIntentChips(row),
        {{html:`<div class="reasonText">${{esc(compactText(row.reason || row.comment_text || row.matched_reason))}}</div>`}},
        actionLink(row.source_label || '查看来源', row.source_url || row.source_path),
        chipList((row.recommended_actions || []).map(label => ({{label}}))),
        leadStatusLabel(row),
      ]));
    }}
    function renderOutreachPanel(ops) {{
      const rows = ops.outreach_view || [];
      const counts = {{
        all: rows.length,
        high: rows.filter(row => Number(row.lead_score || row.score || 0) >= 70).length,
        untouched: rows.filter(row => ['queued','pending_review','approved','ready_to_execute','running'].includes(String(row.status || 'queued'))).length,
        touched: rows.filter(row => ['completed','success'].includes(String(row.status || ''))).length,
        failed: rows.filter(row => ['failed','retryable'].includes(String(row.status || ''))).length,
        skipped: rows.filter(row => String(row.status || '') === 'skipped').length,
      }};
      filterButtons('outreachFilters', outreachFilter, counts, 'outreach-filter');
      const filtered = applyOutreachFilter(rows);
      $('outreachPanelSummary').textContent = `入队 ${{rows.length}} / 成功 ${{counts.touched}} / 失败 ${{counts.failed}} / 跳过 ${{counts.skipped}}`;
      $('outreachTableMeta').textContent = `显示 ${{filtered.length}} / ${{rows.length}} 条`;
      table('actionTable', ['目标用户', '执行账号', '动作', '模式', '状态', '触达文案', '证据', '风险/失败原因', '下一步'], filtered.slice(0, 80).map(row => [
        row.target_username || '-',
        row.profile_id || '待分配',
        row.action_label || row.action_type || '-',
        row.execution_mode_label || '-',
        outreachStatusLabel(row),
        {{html:`<div class="copyText">${{esc(compactText(row.suggested_text || row.executed_text || row.message))}}</div>`}},
        actionLink(row.evidence_label || '查看证据', safeDownload(row.evidence_path)),
        row.risk_gate_summary || (['failed','retryable','skipped'].includes(String(row.status || '')) ? (row.failure_reason || row.error_message || row.last_error_message || '-') : '-'),
        row.next_step || '-',
      ]));
    }}
    function renderOperations(data) {{
      const ops = data.operations || {{}};
      const counts = ops.counts || {{}};
      const batch = data.latest_batch || {{}};
      $('mRequestedProfiles').textContent = ops.requested_concurrency || $('profiles').value || 0;
      $('mActualProfiles').textContent = ops.actual_concurrency || 0;
      $('mQueueProfiles').textContent = (ops.profile_queue || []).length || 0;
      $('mAvailableProfiles').textContent = ops.available_profiles || 0;
      $('mCandidates').textContent = counts.candidates || 0;
      $('mQualified').textContent = counts.qualified_leads || 0;
      $('mHigh').textContent = counts.high_intent || 0;
      $('mActions').textContent = counts.actions || 0;
      $('mTouchSuccess').textContent = counts.touch_success || 0;
      $('mTouchFailed').textContent = counts.touch_failed || 0;
      $('mTouchSkipped').textContent = counts.touch_skipped || 0;
      $('mSuccessRate').textContent = `${{ops.success_rate || 0}}%`;
      const tasks = ops.collection_tasks || [];
      const executions = ops.outreach_executions || [];
      const actions = ops.action_queue || [];
      const taskDone = tasks.filter(row => ['completed','success'].includes(String(row.status || ''))).length;
      const taskFailed = tasks.filter(row => String(row.status || '') === 'failed').length;
      $('collectionSummary').textContent = tasks.length ? `完成 ${{taskDone}} / 失败 ${{taskFailed}} / 共 ${{tasks.length}}` : '等待采集';
      $('touchSummary').textContent = executions.length
        ? `成功 ${{counts.touch_success || 0}} / 失败 ${{counts.touch_failed || 0}} / 共 ${{counts.touched || 0}}`
        : (actions.length ? `队列 ${{actions.length}} / 等待执行` : '等待触达');
      table('collectionTable', ['来源关键词', '账号', '状态', '候选/失败原因'], tasks.map(row => [
        `${{row.source_type || '-'}}:${{row.source_value || '-'}}`,
        row.profile_id || '-',
        row.status || '-',
        row.error_code ? `${{row.error_code}} ${{row.error_message || ''}}` : '已进入扫描/完成'
      ]));
      const touchRows = executions.length
        ? executions.map(row => [
            row.target_username || '-',
            row.action_type || '-',
            row.profile_id || '-',
            row.status || '-',
            row.error_code ? `${{row.error_code}} ${{row.error_message || ''}}` : (row.evidence_path ? {{text:'证据', href:'/api/download?path=' + encodeURIComponent(row.evidence_path)}} : '-')
          ])
        : actions.map(row => [
            row.target_username || '-',
            row.action_type || '-',
            '-',
            row.status || '-',
            row.suggested_text || row.last_error_message || '-'
          ]);
      table('touchTable', ['目标用户', '方式', '账号', '状态', '文案/证据/失败原因'], touchRows);
      renderLeadPanel(ops);
      renderOutreachPanel(ops);
      renderNoActionDecision(batch, counts);
      renderPressureDecision(data);
      updateCopyModeNotice();
    }}
    function renderPressureDecision(data) {{
      if (apiNoticeActive()) return;
      const ops = data.operations || {{}};
      const ctx = (data.acceptance || {{}}).execution_context || {{}};
      const requested = Number(ops.requested_concurrency || 0);
      const actual = Number(ops.actual_concurrency || 0);
      const isPressure = ['压测','stress'].includes(String(ctx.volume || '').toLowerCase()) || String(ctx.volume || '') === '压测';
      if (!isPressure || requested <= 0 || actual >= requested) return;
      $('operatorDecision').className = 'notice blocked';
      $('operatorDecisionTitle').textContent = '压测未达到设置并发';
      $('operatorDecisionBody').textContent = `本轮设置并发 ${{requested}}，实际可执行账号 ${{actual}}。系统已降级继续执行，不会因为不可用账号中断整轮，但当前不能代表满负载压测结果。原因：${{ops.degraded_reason || '可用账号不足'}}。`;
      $('operatorNextList').innerHTML = listItems([
        '验收前先刷新分组并确认美国分组有足够已登录账号。',
        '未登录、内核不匹配、浏览器繁忙账号应自动跳过并进入下一个配置。',
        '并发验收至少需要实际可执行账号数达到设置并发数。'
      ]);
    }}
    function renderNoActionDecision(batch, counts) {{
      if (apiNoticeActive()) return;
      const finished = ['completed','partial_failed','failed'].includes(String(batch.status || ''));
      if (!finished || Number(counts.actions || 0) > 0) return;
      if (Number(counts.candidates || 0) > 0 && Number(counts.qualified_leads || 0) <= 0) {{
        $('operatorDecision').className = 'notice';
        $('operatorDecisionTitle').textContent = '本轮已采集，但没有合格触达线索';
        $('operatorDecisionBody').textContent = `采集到 ${{counts.candidates || 0}} 个候选，但有效线索为 0，系统已按触达策略跳过评论，避免对低意向用户误触达。`;
        $('operatorNextList').innerHTML = listItems([
          '下一步：换更明确的推广关键词，例如产品型号 + review / unboxing / where to buy。',
          '下一步：补充更多已登录账号，避免实际并发降级后覆盖面不足。',
	          '下一步：如需固定评论文案，可在评论内容中填写已审核话术，并选择更高意向的视频/达人链接。'
        ]);
      }} else if (Number(counts.candidates || 0) <= 0) {{
        $('operatorDecision').className = 'notice blocked';
        $('operatorDecisionTitle').textContent = '本轮没有采集到候选用户';
        $('operatorDecisionBody').textContent = '当前来源没有有效评论用户或页面跳转不稳定，系统没有进入触达，避免空评论或误触达。';
      }}
    }}
    async function refreshAcceptance() {{
      let data = {{}};
      try {{
        const res = await fetch('/api/acceptance');
        data = await res.json();
      }} catch (err) {{
        $('acceptanceState').textContent = '验收状态：本地服务连接失败';
        $('acceptanceState').className = 'bad';
        $('acceptanceMeta').textContent = String(err);
        $('acceptanceBlockers').innerHTML = listItems(['本地服务暂时不可用，等待自动重连或刷新页面。']);
        return;
      }}
      if (data.error) return;
      const a = data.acceptance || {{}};
      const gate = data.client_delivery || {{}};
      const mvp = data.mvp_acceptance || {{}};
      const goal = data.goal_delivery || {{}};
      const twoPhase = data.two_phase_acceptance || {{}};
      const winPreflight = goal.windows_package_preflight || {{}};
      const p = data.latest_profile_preflight || {{}};
      const batch = data.latest_batch || {{}};
      const checks = a.checks || {{}};
      const availableForGate = Number(p.available || checks.profile_available_count || 0);
      mergeHourglassData(data);
      accountRepairSummary = data.account_repair_summary || accountRepairSummary;
      accountGateBlocked = (a.readiness === 'blocked_by_accounts' || gate.readiness === 'blocked_by_accounts' || gate.status === 'blocked_by_accounts') && availableForGate <= 0;
      accountGateBlockedGroup = accountGateBlocked ? String(batch.profile_group || '') : '';
      const repairApply = gate.account_repair_apply || data.account_repair_apply || {{}};
      accountRepairApplyState = repairApply || {{}};
      const repairApplyGroup = String(repairApply.profile_group || batch.profile_group || '');
      accountGatePendingRecheck = repairApply.pending_recheck === true;
      accountGatePendingRecheckGroup = accountGatePendingRecheck ? repairApplyGroup : '';
      if (typeof window !== 'undefined') {{
        window.__reachopsAccountRepairDebug = {{
          pending_recheck: accountGatePendingRecheck,
          pending_group: accountGatePendingRecheckGroup,
          repair_apply: repairApply,
          selected_group: $('group') ? $('group').value : '',
          account_gate_blocked: accountGateBlocked,
          account_gate_group: accountGateBlockedGroup
        }};
      }}
      if (accountGatePendingRecheck && $('accountRepairConfirmed')) {{
        const selectedGroup = normGroupName($('group') ? $('group').value : '');
        const repairGroup = normGroupName(repairApplyGroup);
        if (!repairGroup || !selectedGroup || repairGroup === selectedGroup) {{
          $('accountRepairConfirmed').checked = true;
          accountRepairConfirmedGroup = repairApplyGroup || ($('group') ? $('group').value : '');
        }}
      }}
      updateStartAvailability();
      refreshStartPreview();
      const label = {{
        pass:'可验收',
        partial:'部分可执行',
        blocked_by_accounts:'账号阻断',
        blocked_by_environment:'环境阻断',
        not_started:'未开始'
      }}[a.readiness] || a.readiness || '待执行';
      const gateReady = gate.final_delivery_ready === true;
      const mvpLabel = mvp.mvp_local_ready ? 'MVP已通过' : (mvp.status || 'MVP待验');
      const goalLabel = goal.status ? `目标：${{goal.status}}` : '目标待验';
      $('acceptanceState').textContent = `验收状态：${{label}} / ${{mvpLabel}} / ${{goalLabel}} / 客户端门禁：${{gate.status || '-'}}`;
      $('acceptanceState').className = (a.readiness === 'pass' && gateReady) ? 'ok' : (['blocked_by_accounts','blocked_by_environment','failed'].includes(a.readiness) || gate.status === 'failed' ? 'bad' : 'warn');
      $('acceptanceMeta').textContent = `批次：${{batch.id || '-'}} / 状态：${{batch.status || '-'}} / 账号：checked=${{p.checked || 0}} available=${{p.available || 0}} / local_mvp_ready=${{goal.local_mvp_ready === true ? 'true' : 'false'}} / windows_build_ready=${{goal.windows_build_ready === true ? 'true' : 'false'}} / windows_preflight=${{winPreflight.status || '-'}} / final_delivery_ready=${{gateReady ? 'true' : 'false'}}`;
      const gateFailures = (gate.failed_checks || []).map(x => '客户端门禁失败：' + x);
      const mvpFailures = (mvp.failed_checks || []).map(x => 'MVP验收失败：' + x);
      const goalFailures = (goal.failed_checks || []).map(x => '目标门禁失败：' + x);
      const goalBlockers = (goal.blockers || []).map(x => '目标阻断：' + x);
      const winMissing = (winPreflight.missing_final_artifacts || []).length ? ['Windows缺失最终产物：' + winPreflight.missing_final_artifacts.join(', ')] : [];
      const winContract = winPreflight.skip_installer_is_non_final ? ['Windows构建合同：-SkipInstaller 仅为非最终 EXE-only 构建。'] : [];
      const accountRepairActions = accountGateBlocked ? [...accountRepairApplyItems(repairApply), ...accountRepairActionItems(accountRepairSummary)] : [];
      $('acceptanceBlockers').innerHTML = listItems([...(a.blockers || []), ...accountRepairActions, ...goalBlockers, ...winMissing, ...winContract, ...mvpFailures, ...goalFailures, ...gateFailures, ...(a.next_actions || []).map(x => '下一步：' + x)]);
      renderDecision(data);
      renderFunnelFromAcceptance(data);
      renderProfileLaunchList(data);
      renderOperations(data);
	      const rows = remediationRows(data);
	      const goalRows = [];
	      if (goal.path) goalRows.push(['目标模式总报告', goal.status || '-', {{text: goal.path, href: safeDownload(goal.path)}}]);
	      if (goal.summary_path) goalRows.push(['目标模式PM摘要', goal.status || '-', {{text: goal.summary_path, href: safeDownload(goal.summary_path)}}]);
	      if (twoPhase.path) goalRows.push(['两阶段验收矩阵 JSON', twoPhase.status || '-', {{text: twoPhase.path, href: safeDownload(twoPhase.path)}}]);
	      if (twoPhase.markdown_path) goalRows.push(['两阶段验收矩阵 Markdown', twoPhase.status || '-', {{text: twoPhase.markdown_path, href: safeDownload(twoPhase.markdown_path)}}]);
	      if (winPreflight.preflight_report_path) goalRows.push(['Windows打包前置门禁', winPreflight.status || '-', {{text: winPreflight.preflight_report_path, href: safeDownload(winPreflight.preflight_report_path)}}]);
	      if (mvp.path) goalRows.push(['MVP验收摘要', mvp.status || '-', {{text: mvp.path, href: safeDownload(mvp.path)}}]);
      if (rows.length) table('healthTable', ['类型', '错误/状态', '账号/路径'], rows);
      if (goalRows.length || rows.length) table('reportTable', ['类型', '状态', '路径'], [...goalRows, ...rows]);
    }}
    async function refreshLogs() {{
      let data = {{}};
      try {{
        const res = await fetch('/api/logs');
        data = await res.json();
      }} catch (err) {{
        runtimeState = {{running:false, paused:false, elapsed_seconds:0, last_stage:'', lines:[]}};
        $('runState').textContent = 'OFFLINE';
        $('runState').className = 'pill danger';
        $('pause').disabled = true;
        $('resume').disabled = true;
        $('stop').disabled = true;
        $('logs').innerHTML = `<span class="bad">本地服务连接失败：${{esc(String(err))}}</span>`;
        return;
      }}
      runtimeState = data;
      const sessionState = data.run_session_state || (data.run_session && data.run_session.state) || '';
      const label = data.paused
        ? `PAUSED${{sessionState ? ' / ' + sessionState : ''}}`
        : (data.running
          ? `RUNNING${{sessionState ? ' / ' + sessionState : ''}}`
          : (data.run_failed ? `FAILED${{sessionState ? ' / ' + sessionState : ''}}` : (sessionState || 'READY')));
      $('runState').textContent = label;
      $('runState').className = data.paused ? 'pill warn' : (data.running ? 'pill cyan' : (data.run_failed ? 'pill danger' : 'pill ok'));
      const ai_usage_summary = (data.evidence_bundle && data.evidence_bundle.ai_usage_summary) || {{}};
      const ai_usage_ledger = (data.run_session && data.run_session.ai_usage_ledger) || {{}};
      const execution_phase = ai_usage_ledger.execution_phase || {{}};
      const aiCalls = ai_usage_summary.execution_phase_ai_call_count ?? execution_phase.ai_call_count ?? 0;
      const aiTokens = ai_usage_summary.execution_phase_token_estimate ?? execution_phase.token_estimate ?? 0;
      if ($('aiUsageState')) {{
        $('aiUsageState').textContent = `执行期AI ${{aiCalls}}次 / token ${{aiTokens}}`;
        $('aiUsageState').className = (Number(aiCalls) === 0 && Number(aiTokens) === 0) ? 'pill ok' : 'pill warn';
        $('aiUsageState').title = 'ai_usage_summary / ai_usage_ledger';
      }}
      $('pause').disabled = !data.running || data.paused;
      $('resume').disabled = !data.running || !data.paused;
      $('stop').disabled = !data.running;
      $('logs').innerHTML = (data.lines.length ? data.lines : ['等待本轮执行日志...']).map(l => `<span class="${{classify(l)}}">${{esc(l)}}</span>`).join('\\n');
      $('logs').scrollTop = $('logs').scrollHeight;
      mergeHourglassData(data);
    }}
    async function refreshSnapshot() {{
      let data = {{}};
      try {{
        const res = await fetch('/api/snapshot');
        data = await res.json();
      }} catch (err) {{
        $('targetType').textContent = '本地服务连接失败';
        return;
      }}
      if (data.error) return;
      mergeHourglassData(data);
      const s = data.summary || {{}}, f = data.campaign_funnel || {{}};
      $('batchId').textContent = f.batch_id || '-';
      $('targetType').textContent = sourceLabels[f.campaign_type] || $('sourceType').selectedOptions[0].textContent;
      renderFunnelFromSnapshot(data);
      table('leadTable', ['用户', '评分', '意图', '来源'], (data.candidate_users || []).slice(0, 30).map(r => [r.username || r.author || '-', r.qualify_score || 0, r.intent_tags || r.comment_text || '-', r.source_path || r.content_url || '-']));
      table('actionTable', ['目标', '动作', '状态', '文案'], (data.action_queue || []).slice(0, 40).map(r => [r.target_username || r.username || '-', r.action_type || '-', r.status || '-', r.message || r.comment_text || '-']));
      table('healthTable', ['账号', '状态', '错误', '更新时间'], (data.profile_health || []).slice(0, 40).map(r => [r.profile_id || '-', r.status || '-', r.last_error || '-', r.updated_at || '-']));
      const artifactRows = (data.report_artifacts || []).map(r => [r.label || r.kind || '-', r.exists ? '已生成' : '未生成', r.path || '-']);
      table('reportTable', ['类型', '状态', '路径'], artifactRows);
      refreshAcceptance();
	    }}
    async function refreshProductCapability() {{
      try {{
        const res = await fetch('/api/product-capability');
        const data = await res.json();
        if (!data || data.error) return;
        mergeHourglassData(data);
      }} catch (_err) {{
      }}
    }}
	    function setGroupRefreshBusy(busy) {{
	      groupRefreshInFlight = busy;
	      if ($('refreshGroupsInline')) $('refreshGroupsInline').disabled = busy;
	      if ($('refreshGroups')) $('refreshGroups').disabled = busy;
	    }}
	    async function refreshGroups(force = true) {{
	      if (force) groupRefreshPollCount = 0;
	      if (groupRefreshInFlight) {{
	        $('groupCount').textContent = loadedGroups.length
	          ? `刷新中，保留上次读取：${{loadedGroups.length}} 个分组`
	          : '正在读取 ixBrowser 配置分组，请稍候...';
	        updateSelectedGroupQuantity();
	        return;
	      }}
	      setGroupRefreshBusy(true);
	      $('groupCount').textContent = force ? '正在读取 ixBrowser 配置分组，请稍候...' : '正在同步最新分组状态...';
	      let data = {{}};
	      try {{
	        const res = await fetch(force ? '/api/groups?refresh=1' : '/api/groups');
	        data = await res.json();
	      }} catch (err) {{
	        groupListReady = false;
	        loadedGroups = [];
	        $('group').innerHTML = '<option value="">请先刷新账号分组</option>';
	        $('groupCount').textContent = '读取失败：本地服务连接失败';
	        $('groupCount').title = String(err);
	        $('currentGroup').textContent = '-';
	        $('selectedGroupName').textContent = '-';
	        $('selectedGroupCount').textContent = '读取失败';
	        $('selectedGroupCount').className = 'count unknown';
	        $('selectedGroupId').textContent = '-';
	        renderGroupDetails([], '');
	        updateStartAvailability();
	        refreshLogs();
	        return;
	      }} finally {{
	        setGroupRefreshBusy(false);
	      }}
	      const groups = data.groups || [];
	      loadedGroups = groups;
		      const completeGroupCounts = data.all_group_counts_known === true || data.live_all_group_counts_known === true || data.counts_resolved === true;
		      groupListReady = groups.length > 0 && !data.error && data.stale_cache !== true && (data.background_refresh !== true || completeGroupCounts);
	      $('group').innerHTML = groups.length
	        ? groups.map(g => `<option value="${{esc(g.name)}}">${{esc(groupOptionLabel(g))}}</option>`).join('')
	        : '<option value="">请先刷新账号分组</option>';
	      const selected = groups.find(g => String(g.name).toLowerCase() === 'united states') || groups[0];
	      if (selected) $('group').value = selected.name;
	      if (data.error && !groups.length) {{
	        renderGroupError(data);
	      }} else if (!groups.length) {{
	        $('groupCount').textContent = '未读取到 ixBrowser 配置分组；不可启动';
	        $('groupCount').title = '';
	        renderGroupDetails([], '');
	      }} else {{
	        let summary = formatGroupSummary(groups, data);
	        if (data.background_refresh) summary += ' / 同步确认中';
	        else if (data.error || data.stale_cache) summary += ' / 缓存展示，暂不可启动';
	        $('groupCount').textContent = summary;
	        $('groupCount').title = String(data.operator_notice || data.error_detail || data.count_resolution_error || '');
	        renderGroupDetails(groups, $('group').value);
	      }}
	      if (data.error || data.stale_cache) {{
	        showApiNotice(
	          'ixBrowser 分组未实时确认',
	          {{
	            status:'rejected',
	            error:data.error || 'stale_group_cache',
	            message:'当前仅显示缓存分组或本次刷新失败，开始获客已禁用。',
	            next_actions:['确认 ixBrowser 客户端已启动并开启 Local API。','Local API 连通后重新点击“刷新分组”，直到分组数量实时读取成功。']
	          }},
	          'blocked'
	        );
	      }}
		      updateSelectedGroupQuantity();
		      updateStartAvailability();
		      refreshLogs();
		      if (data.background_refresh) {{
	        groupRefreshPollCount += 1;
	        if (groupRefreshPollCount < 60) {{
	          setTimeout(() => refreshGroups(false), 2500);
	        }} else {{
	          $('groupCount').textContent += ' / 后台统计超时，请稍后再次刷新';
	        }}
	      }} else {{
	        groupRefreshPollCount = 0;
		      }}
		    }}
	    async function logClientEvent(event, payload = {{}}) {{
	      try {{
	        await postJson('/api/client-event', {{event, ...payload}});
	      }} catch (_err) {{}}
	    }}
	    async function refreshActivation() {{
      try {{
        const res = await fetch('/api/activation');
        const data = await res.json();
        const ready = data.ready === true;
        const exists = data.activation_status_exists === true;
        const status = data.status || (ready ? 'ready' : 'blocked');
        const path = data.activation_status_path || '-';
        $('activationState').textContent = ready
          ? `ready / ${{data.license_tier || 'licensed'}}`
          : `${{status}} / ${{exists ? '未授权' : '无激活文件'}}`;
        $('activationState').className = ready ? 'ok' : 'bad';
        $('activationState').title = (data.failed_checks || []).join(', ') || path;
        $('activationNotice').className = ready ? 'notice ready' : 'notice blocked';
        $('activationActions').innerHTML = listItems((data.next_actions || []).length ? data.next_actions : [ready ? '激活状态已就绪。' : '生成或放置真实激活状态文件，并设置 ActivationStatusPath。']);
      }} catch (err) {{
        $('activationState').textContent = '读取失败';
        $('activationState').className = 'bad';
        $('activationState').title = String(err);
        $('activationNotice').className = 'notice blocked';
        $('activationActions').innerHTML = listItems(['激活状态读取失败：' + String(err)]);
      }}
    }}
    async function refreshIxBrowserStatus() {{
      try {{
        const res = await fetch('/api/ixbrowser-status');
        const data = await res.json();
        const ready = data.ready === true;
        const portMatch = String(data.base_url || '').match(/:(\\d+)\\/api\\/v2\\//);
        if (portMatch && $('ixbrowserApiPort')) $('ixbrowserApiPort').value = portMatch[1];
        $('ixbrowserApiState').textContent = ready
          ? `ready / ${{data.base_url || 'local'}}`
          : `blocked / ${{data.error || 'Local API 不可用'}}`;
        $('ixbrowserApiState').className = ready ? 'ok' : 'bad';
        $('ixbrowserApiState').title = (data.next_actions || []).join(' / ') || data.error_detail || data.base_url || '只读检查，不打开浏览器';
        $('ixbrowserStatusNotice').className = ready ? 'notice ready' : 'notice blocked';
        $('ixbrowserStatusActions').innerHTML = listItems((data.next_actions || []).length ? data.next_actions : [ready ? 'ixBrowser Local API 已连通。' : '确认 ixBrowser Local API 已开启。']);
      }} catch (err) {{
        $('ixbrowserApiState').textContent = '读取失败';
        $('ixbrowserApiState').className = 'bad';
        $('ixbrowserApiState').title = String(err);
        $('ixbrowserStatusNotice').className = 'notice blocked';
        $('ixbrowserStatusActions').innerHTML = listItems(['ixBrowser Local API 状态读取失败：' + String(err)]);
      }}
    }}
    async function applyIxBrowserPort() {{
      const port = $('ixbrowserApiPort').value;
      let result = {{}};
      try {{
        result = await postJson('/api/ixbrowser-config', {{port}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      const ok = result.status === 'saved';
      showApiNotice(ok ? 'ixBrowser端口已应用' : 'ixBrowser端口未应用', result, ok ? '' : 'blocked');
      await refreshIxBrowserStatus();
      if (ok) await refreshGroups();
    }}
    async function refreshFinalStatus() {{
      try {{
        const res = await fetch('/api/final-status');
        const data = await res.json();
        const ready = data.final_delivery_ready === true;
        const mvp = data.mvp_acceptance || {{}};
        const goal = data.goal_delivery || {{}};
        const twoPhase = data.two_phase_acceptance || {{}};
        const winPreflight = goal.windows_package_preflight || {{}};
        const finalEvidencePlan = data.final_delivery_evidence_plan || goal.final_delivery_evidence_plan || {{}};
        const liveValidation = data.live_validation || {{}};
        const liveBlocking = liveValidation.blocking_summary || {{}};
        const localInputs = data.local_inputs || {{}};
        const fieldStatus = localInputs.field_status || {{}};
        const status = data.status || (ready ? 'passed' : 'blocked');
	        const failedChecks = data.failed_checks || [];
	        const failed = failedChecks.join(', ');
		        const blocked = (data.blocked_reasons || data.next_required_actions || []).join(' / ');
		        const liveRows = [];
		        if (liveValidation.status || Array.isArray(liveValidation.missing_inputs)) {{
		          liveRows.push(`授权输入：账号=${{liveValidation.selected_profile_count || 0}} / 目标=${{liveBlocking.target_ready === true ? 'ready' : 'blocked'}} / 激活=${{liveBlocking.activation_ready === true ? 'ready' : 'blocked'}} / 授权确认=${{liveBlocking.authorization_confirmed === true ? 'YES' : 'NO'}}`);
		          if (liveBlocking.next_blocking_item) liveRows.push('当前首要阻断：' + liveBlocking.next_blocking_item);
		        }}
		        const fieldRows = [];
		        const fieldLabels = {{
		          ProfileIds: 'ProfileIds',
		          CommentVideoUrl: 'CommentVideoUrl',
		          FollowProfileUrl: 'FollowProfileUrl',
		          DmProfileUrl: 'DmProfileUrl',
		          TargetUsername: 'TargetUsername',
		          ActivationStatusPath: 'ActivationStatusPath',
		          ConfirmAuthorizedTargets: 'ConfirmAuthorizedTargets'
		        }};
		        Object.keys(fieldLabels).forEach(key => {{
		          const row = fieldStatus[key] || {{}};
		          if (!row.state) return;
		          const marker = row.ready === true ? 'ready' : row.state;
		          const action = row.required_action ? ' / ' + row.required_action : '';
		          fieldRows.push(`字段：${{fieldLabels[key]}} = ${{marker}}${{action}}`);
		        }});
		        const planRows = [];
		        (data.blocking_plan || []).forEach(stage => {{
		          const title = `阶段：${{stage.stage || '-'}} / ${{stage.status || '-'}}`;
		          planRows.push(title);
		          (stage.blockers || []).forEach(item => planRows.push(`  阻断：${{item}}`));
		          (stage.actions || []).forEach(item => planRows.push(`  动作：${{item}}`));
		        }});
		        const mvpRows = mvp.mvp_local_ready ? ['本地MVP已验收：' + (mvp.status || 'passed')] : [];
	        const goalRows = goal.status ? [`目标模式：${{goal.status}} / 本地MVP=${{goal.local_mvp_ready === true ? 'true' : 'false'}} / Windows构建输入=${{goal.windows_build_ready === true ? 'true' : 'false'}} / 最终交付=${{goal.final_delivery_ready === true ? 'true' : 'false'}}`] : [];
	        const boundary = goal.delivery_boundary || {{}};
	        const localProductBoundary = data.delivery_boundary || {{}};
	        const deliverableIndex = goal.deliverable_index || {{}};
	        const boundaryRows = [];
	        if (localProductBoundary.schema_version || data.delivery_boundary_status) {{
	          boundaryRows.push(`本地产品边界：${{data.delivery_boundary_status || localProductBoundary.status || '-'}} / 产品能力=${{data.product_capability_ready === true ? 'true' : 'false'}} / 开发目标=${{data.product_development_ready === true ? 'true' : 'false'}} / 最终交付=${{data.final_delivery_ready === true ? 'true' : 'false'}}`);
	        }}
	        if ((data.pending_scopes || []).length) boundaryRows.push('本地边界待完成：' + data.pending_scopes.join(', '));
	        if (localProductBoundary.boundary_note) boundaryRows.push('本地边界说明：' + localProductBoundary.boundary_note);
	        if (boundary.summary) boundaryRows.push('交付边界：' + boundary.summary);
	        if (goal.summary_path) boundaryRows.push('目标摘要：' + goal.summary_path);
	        if (twoPhase.status) boundaryRows.push(`两阶段矩阵：${{twoPhase.status}} / 本地MVP=${{twoPhase.local_mvp_ready === true ? 'true' : 'false'}} / 最终交付=${{twoPhase.final_delivery_ready === true ? 'true' : 'false'}}`);
	        if ((twoPhase.blocking_scopes || []).length) boundaryRows.push('两阶段阻断：' + twoPhase.blocking_scopes.join(', '));
	        if (twoPhase.path) boundaryRows.push({{text:'两阶段矩阵JSON：' + twoPhase.path, href:safeDownload(twoPhase.path)}});
	        if (twoPhase.markdown_path) boundaryRows.push({{text:'两阶段矩阵Markdown：' + twoPhase.markdown_path, href:safeDownload(twoPhase.markdown_path)}});
	        if ('overall_final_delivery_scope_ready' in boundary) boundaryRows.push(`PM边界：本地MVP=${{boundary.local_mvp_scope_ready === true ? 'true' : 'false'}} / 客户端门禁=${{boundary.client_gate_scope_ready === true ? 'true' : 'false'}} / Windows构建输入=${{boundary.windows_build_input_scope_ready === true ? 'true' : 'false'}} / 整体最终交付=${{boundary.overall_final_delivery_scope_ready === true ? 'true' : 'false'}}`);
	        if (boundary.client_gate_final_delivery_ready_is_not_overall_final_delivery) boundaryRows.push('边界说明：client_delivery.final_delivery_ready 只代表客户端门禁自身通过，不代表整项目最终交付完成。');
	        if (deliverableIndex.windows_final_package) boundaryRows.push(`交付索引：本地MVP=${{deliverableIndex.local_mvp_acceptance && deliverableIndex.local_mvp_acceptance.ready === true ? 'ready' : 'blocked'}} / Windows最终包=${{deliverableIndex.windows_final_package.ready === true ? 'ready' : 'missing'}} / 最终门禁=${{deliverableIndex.final_acceptance_gate && deliverableIndex.final_acceptance_gate.ready === true ? 'ready' : 'blocked'}}`);
	        const localMvpIndex = deliverableIndex.local_mvp_acceptance || {{}};
	        const localMvpBlocker = localMvpIndex.blocker_summary || {{}};
	        if (localMvpBlocker.schema_version) {{
	          boundaryRows.push(`本地MVP账号交接：${{localMvpBlocker.status || '-'}} / ${{localMvpBlocker.priority_action || '-'}} / ${{localMvpBlocker.support_case || '-'}}`);
	          if (localMvpIndex.account_support_handoff_path) boundaryRows.push('本地MVP账号交接文件：' + localMvpIndex.account_support_handoff_path);
	          if (localMvpBlocker.next_required_command) boundaryRows.push('本地MVP账号复验命令：' + localMvpBlocker.next_required_command);
	        }}
	        const finalBlockerRows = [];
	        (goal.final_delivery_blockers || []).forEach(blocker => {{
	          finalBlockerRows.push(`最终阻断：${{blocker.scope || '-'}} / ${{blocker.status || '-'}}`);
	          if (blocker.next_action) finalBlockerRows.push('  下一步：' + blocker.next_action);
	          const handoff = blocker.account_support_handoff || {{}};
	          if (handoff.schema_version) {{
	            finalBlockerRows.push(`  账号支持交接：${{handoff.status || '-'}} / ${{handoff.priority_action || '-'}} / 分组=${{handoff.profile_group || '-'}}`);
	            const repairPlan = handoff.repair_plan || {{}};
	            if (repairPlan.available) finalBlockerRows.push(`    修复计划：账号=${{repairPlan.profile_count || 0}} 事件=${{repairPlan.event_count || 0}} 自动可处理=${{repairPlan.auto_apply_profile_count || 0}} 非自动错误=${{(repairPlan.non_auto_error_codes || []).join(', ') || '-'}}`);
	            ((handoff.impacted_accounts || {{}}).error_groups || []).slice(0, 3).forEach(group => finalBlockerRows.push(`    账号错误：${{group.error || '-'}} count=${{group.count || 0}} sample=${{(group.profile_ids_sample || []).slice(0, 4).join(',') || '-'}}`));
	            (handoff.retest_commands || []).slice(0, 3).forEach(cmd => finalBlockerRows.push('    账号复测命令：' + cmd));
	          }}
	          (blocker.required_evidence || []).forEach(item => finalBlockerRows.push('  必需证据：' + item));
	          (blocker.required_artifacts || []).forEach(item => finalBlockerRows.push('  必需产物：' + item));
	        }});
	        const evidencePlanRows = [];
	        if (finalEvidencePlan.schema_version) {{
	          evidencePlanRows.push(`证据计划：${{finalEvidencePlan.schema_version}} / ready=${{finalEvidencePlan.ready === true ? 'true' : 'false'}} / pending=${{(finalEvidencePlan.pending_scopes || []).join(', ') || '-'}}`);
	          (finalEvidencePlan.items || []).slice(0, 6).forEach(item => {{
	            evidencePlanRows.push(`  证据项：${{item.scope || '-'}} / ${{item.status || '-'}}`);
	            (item.required_evidence || []).slice(0, 4).forEach(value => evidencePlanRows.push('    需要证据：' + value));
	            (item.required_artifacts || []).slice(0, 4).forEach(value => evidencePlanRows.push('    需要产物：' + value));
	            (item.proof_fields || []).slice(0, 4).forEach(value => evidencePlanRows.push('    验收字段：' + value));
	            (item.commands || []).slice(0, 3).forEach(value => evidencePlanRows.push('    验收命令：' + value));
	          }});
	        }}
	        if (data.report_path) boundaryRows.push({{text:'授权准备报告：' + data.report_path, href:safeDownload(data.report_path)}});
	        if (data.json_report_path) boundaryRows.push({{text:'授权交接JSON：' + data.json_report_path, href:safeDownload(data.json_report_path)}});
	        if (data.handoff_bundle_path) boundaryRows.push({{text:'授权交接包：' + data.handoff_bundle_path, href:safeDownload(data.handoff_bundle_path)}});
	        const handoffVerification = data.handoff_bundle_verification || {{}};
	        if (handoffVerification.status) {{
	          const failures = (handoffVerification.failures || []).join(', ');
	          boundaryRows.push(`授权交接包校验：${{handoffVerification.status}}${{failures ? ' / ' + failures : ''}}`);
	        }}
	        const operatorCommandRows = (data.operator_commands || []).map(item => '操作命令：' + item);
	        const failedSummary = failedChecks.length ? [`失败检查摘要：${{failedChecks.length}} 项，见最终复核命令输出。`] : [];
	        const commands = data.verification_commands || [];
	        $('finalStatusState').textContent = ready ? 'passed / 可最终交付' : `${{status}} / 不可最终交付`;
	        $('finalStatusState').className = ready ? 'ok' : 'bad';
	        $('finalStatusState').title = failed || blocked || '等待最终验收证据';
	        $('finalStatusNotice').className = ready ? 'notice ready' : 'notice blocked';
		        $('finalStatusActions').innerHTML = listItems(ready ? ['最终交付门禁已通过。'] : [...goalRows, ...boundaryRows, ...finalBlockerRows, ...evidencePlanRows, ...liveRows, ...fieldRows, ...planRows, ...operatorCommandRows, ...mvpRows, ...failedSummary]);
	        $('finalCommandNotice').className = ready ? 'notice ready' : 'notice blocked';
	        $('finalStatusCommands').innerHTML = listItems(commands.length ? commands : ['等待最终验收命令。']);
	      }} catch (err) {{
	        $('finalStatusState').textContent = '读取失败';
	        $('finalStatusState').className = 'bad';
	        $('finalStatusState').title = String(err);
	        $('finalStatusNotice').className = 'notice blocked';
	        $('finalStatusActions').innerHTML = listItems(['最终验收状态读取失败：' + String(err)]);
	        $('finalCommandNotice').className = 'notice blocked';
	        $('finalStatusCommands').innerHTML = listItems(['python tools\\\\reachops_issue_closure_audit.py --json', 'python tools\\\\reachops_final_acceptance_gate.py --json']);
	      }}
    }}
    async function getJson(url) {{
      const res = await fetch(url);
      let data = {{}};
      try {{
        data = await res.json();
      }} catch (err) {{
        data = {{status:'failed', error:'invalid_response', message:String(err)}};
      }}
      data.http_ok = res.ok;
      data.http_status = res.status;
      return data;
    }}
    async function postJson(url, payload) {{
      const res = await fetch(url, {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify(payload)
      }});
      let data = {{}};
      try {{
        data = await res.json();
      }} catch (err) {{
        data = {{status:'failed', error:'invalid_response', message:String(err)}};
      }}
      data.http_ok = res.ok;
      data.http_status = res.status;
      return data;
    }}
    function showApiNotice(title, payload, tone='blocked', ttlMs=3500) {{
      apiNoticeUntil = Date.now() + Math.max(0, Number(ttlMs || 0));
      $('operatorDecision').className = tone ? `notice ${{tone}}` : 'notice';
      $('operatorDecisionTitle').textContent = title;
      const parts = [];
      if (payload.http_status) parts.push(`HTTP ${{payload.http_status}}`);
      if (payload.status) parts.push(String(payload.status));
      if (payload.error) parts.push(`错误：${{payload.error}}`);
      if (payload.group_error) parts.push(`分组读取：${{payload.group_error}}`);
      if (payload.message) parts.push(payload.message);
      if (payload.selected_count !== undefined) parts.push(`选中=${{payload.selected_count}}`);
      if (payload.moved_count !== undefined) parts.push(`已隔离=${{payload.moved_count}}`);
      if (payload.failed_count !== undefined) parts.push(`失败=${{payload.failed_count}}`);
      if (!parts.length) parts.push(`HTTP ${{payload.http_status || '-'}}`);
      if (payload.pid) parts.push('pid=' + payload.pid);
      $('operatorDecisionBody').textContent = parts.join(' / ');
      const actions = [
        ...(payload.next_actions || []),
        ...(payload.blockers || []),
        ...accountRepairActionItems(payload.account_repair_summary || accountRepairSummary),
        ...(payload.failed_checks || []).map(x => '失败检查：' + x),
      ];
      const repairPaths = [
        payload.account_plan_markdown_path,
        payload.account_plan_json_path,
        payload.latest_account_plan_markdown_path,
        payload.latest_account_plan_json_path,
      ].filter(Boolean);
      repairPaths.forEach(path => actions.push({{text:'账号修复计划：' + path, href:safeDownload(path)}}));
      (payload.results || []).slice(0, 8).forEach(row => {{
        if (row.ok) actions.push(`已隔离账号 ${{row.profile_id}} -> ${{row.group_name || row.group_id || '封禁账号'}}`);
        else actions.push(`账号 ${{row.profile_id}} 未隔离：${{row.error_code || '-'}} ${{row.error_message || ''}}`);
      }});
      $('operatorNextList').innerHTML = listItems(actions);
    }}
		    async function start() {{
	      if (!$('target').value.trim()) {{
	        $('operatorDecision').className = 'notice blocked';
	        $('operatorDecisionTitle').textContent = '请先输入推广目标';
	        $('operatorDecisionBody').textContent = '支持产品链接、关键词、达人主页、视频链接、话题或直播间。';
	        logClientEvent('start_blocked', {{reason:'target_required', mode:$('mode').value, group:$('group').value}});
	        return;
	      }}
      if (!groupListReady || !$('group').value.trim()) {{
	        showApiNotice(
	          '正在刷新账号分组',
	          {{status:'refreshing', message:'启动前正在从 ixBrowser 本地 API 读取配置分组。'}},
	          '',
	          8000
	        );
	        await refreshGroups();
      }}
      if (!groupListReady || !$('group').value.trim()) {{
	        showApiNotice(
	          '未读取到账号分组',
	          {{status:'rejected', error:'profile_group_list_unavailable', message:'启动前已自动刷新 ixBrowser 配置分组，但没有读取到可用分组。', next_actions:['确认 ixBrowser 本地服务已启动，并在 ixBrowser 中存在配置分组。']}},
	          'blocked',
	          30000
	        );
	        return;
      }}
      if (accountGateAppliesToCurrentGroup() && !isAccountRepairConfirmed()) {{
        showApiNotice(
          '重新预检账号',
          {{
            status:'ready_for_account_recheck',
            message:'当前分组上次账号预检未通过；本次会重新读取 ixBrowser 分组并自动筛选有效登录账号。',
            account_repair_apply: accountRepairApplyState || {{}},
            next_actions:['系统会跳过未登录、内核不匹配、代理异常账号。','如果仍无可用账号，本轮会生成新的阻断证据。']
          }},
          'warning',
          12000
        );
      }}
	      if ($('liveConfirm').checked && $('mode').value !== 'live_comment') {{
	        $('mode').value = 'live_comment';
	        $('currentMode').textContent = $('mode').selectedOptions[0].textContent;
	        updateCopyModeNotice();
	      }}
		      if ($('mode').value === 'live_comment' && !$('liveConfirm').checked) {{
		        showApiNotice(
		          '真实评论未确认',
		          {{status:'rejected', error:'live_comment_confirmation_required', message:'选择采集 + 真实评论前必须勾选确认真实评论。'}},
		          'blocked',
		          30000
		        );
	        logClientEvent('start_blocked', {{reason:'live_comment_confirmation_required', target:$('target').value, group:$('group').value}});
	        return;
		      }}
	      $('start').disabled = true;
	      updateSelectedGroupQuantity();
	      $('currentMode').textContent = $('mode').selectedOptions[0].textContent;
      updateCopyModeNotice();
      refreshActivation();
      refreshFinalStatus();
      $('currentVolume').textContent = $('volume').selectedOptions[0].textContent;
      $('targetType').textContent = $('sourceType').selectedOptions[0].textContent;
      let result = {{}};
      try {{
        result = await postJson('/api/start', {{
          target:$('target').value,
          sourceType:$('sourceType').value,
          group:$('group').value,
          mode:$('mode').value,
          volume:$('volume').value,
          profiles:$('profiles').value,
          commentText:$('commentText').value,
          liveConfirm:$('liveConfirm').checked,
          accountRepairConfirmed:$('accountRepairConfirmed').checked
        }});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
	      if (result.status === 'started') {{
	        showApiNotice('自动执行已启动', result, 'ready');
        setTimeout(() => {{
          apiNoticeUntil = 0;
          refreshLogs();
          refreshSnapshot();
          refreshAcceptance();
        }}, 4200);
	      }} else if (result.status === 'already_running') {{
	        showApiNotice('已有执行在运行', result, '', 12000);
	      }} else {{
	        showApiNotice('启动被系统拦截', result, 'blocked', 30000);
	      }}
	      updateStartAvailability();
	      refreshLogs(); refreshSnapshot();
    }}
    async function control(action) {{
      let result = {{}};
      try {{
        result = await postJson('/api/control', {{action}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      if (['paused','running','stopped'].includes(result.status)) {{
        showApiNotice(`控制已执行：${{action}}`, result, '');
      }} else {{
        showApiNotice(`控制未执行：${{action}}`, result, 'blocked');
      }}
      refreshLogs(); refreshSnapshot(); refreshAcceptance();
    }}
    async function applyAccountRepairPlan() {{
      if (!accountGateAppliesToCurrentGroup()) {{
        showApiNotice(
          '当前无需隔离坏账号',
          {{status:'skipped', message:'当前分组没有账号阻断，或阻断分组与所选分组不一致。'}},
          '',
          8000
        );
        return;
      }}
      if ($('applyAccountRepair')) $('applyAccountRepair').disabled = true;
      let result = {{}};
      try {{
        result = await postJson('/api/account-repair-apply', {{group:$('group').value, confirm:true}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      const ok = result.status === 'applied' && Number(result.failed_count || 0) === 0;
      showApiNotice(ok ? '账号修复计划已执行' : '账号修复计划执行失败', result, ok ? '' : 'blocked', 30000);
      if ($('accountRepairConfirmed')) $('accountRepairConfirmed').checked = ok;
      accountRepairConfirmedGroup = ok && $('group') ? $('group').value : '';
      if (ok) {{
        showApiNotice(
          '账号修复计划已执行',
          {{
            ...result,
            message:'已隔离硬失败账号；当前分组已进入重新预检状态，可以直接点击开始获客复测。',
            next_actions:[
              '安全边界：账号修复只移动硬阻断账号到隔离分组，不打开浏览器、不提交平台动作、执行期 0 token。',
              '点击开始获客，系统会重新预检当前分组剩余账号。',
              '如果仍没有可用账号，系统会再次阻断并生成新的账号修复计划。',
              ...(result.next_actions || [])
            ]
          }},
          '',
          30000
        );
      }}
      refreshGroups();
      refreshAcceptance();
      updateStartAvailability();
    }}
    async function initAcceptanceInputs() {{
      let result = {{}};
      try {{
        result = await postJson('/api/acceptance-input-init', {{}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      const ok = ['created','already_exists'].includes(result.status);
      const title = result.status === 'created' ? '已生成本地验收输入' : (result.status === 'already_exists' ? '本地验收输入已存在' : '生成验收输入失败');
      showApiNotice(title, result, ok ? '' : 'blocked');
      if (result.next_required_actions) {{
        $('finalStatusNotice').className = 'notice blocked';
        $('finalStatusActions').innerHTML = listItems(result.next_required_actions.map(x => '下一步：' + x));
      }}
      refreshFinalStatus();
    }}
    async function refreshMvpAcceptance() {{
      let result = {{}};
      try {{
        result = await postJson('/api/mvp-acceptance-refresh', {{}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      const ok = result.status === 'mvp_accepted_external_pending' || result.status === 'final_delivery_ready';
      showApiNotice(ok ? 'MVP验收已刷新' : 'MVP验收未通过', result, ok ? '' : 'blocked');
      refreshAcceptance();
    }}
    async function refreshGoalDelivery() {{
      let result = {{}};
      try {{
        result = await postJson('/api/goal-delivery-refresh', {{}});
      }} catch (err) {{
        result = {{status:'failed', error:'network_error', message:String(err)}};
      }}
      const ok = result.local_mvp_ready === true && result.windows_build_ready === true;
      showApiNotice(ok ? '目标报告已刷新' : '目标报告未通过', result, ok ? '' : 'blocked');
      refreshAcceptance();
      refreshFinalStatus();
    }}
    document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => {{
      document.querySelectorAll('.tab,.page').forEach(el => el.classList.remove('active'));
      btn.classList.add('active'); $(btn.dataset.page).classList.add('active');
    }});
	    $('start').onclick = start; $('previewPlanReplay').onclick = previewPlanReplay; $('startFromPlan').onclick = startFromPlan; $('downloadExecutionPlan').onclick = downloadExecutionPlan; $('applyAccountRepair').onclick = applyAccountRepairPlan; $('pause').onclick = () => control('pause'); $('resume').onclick = () => control('resume'); $('stop').onclick = () => control('stop');
	    $('refresh').onclick = () => {{ refreshLogs(); refreshSnapshot(); refreshAcceptance(); refreshIxBrowserStatus(); refreshActivation(); refreshFinalStatus(); }};
	    $('refreshGroups').onclick = refreshGroups;
	    $('refreshGroupsInline').onclick = () => {{ refreshIxBrowserStatus(); refreshGroups(); }};
	    $('applyIxBrowserPort').onclick = applyIxBrowserPort;
	    $('initAcceptanceInputs').onclick = initAcceptanceInputs;
	    $('refreshMvpAcceptance').onclick = refreshMvpAcceptance;
	    $('refreshGoalDelivery').onclick = refreshGoalDelivery;
	    $('aiConsoleSend').onclick = sendAiConsoleMessage;
	    $('aiConsoleExplainStatus').onclick = () => sendAiConsoleMessage('为什么停了');
	    $('aiConsoleAnalyzeUnknown').onclick = () => sendAiConsoleMessage('分析未知错误');
	    $('aiConsoleProductCapability').onclick = () => sendAiConsoleMessage('产品能力矩阵现在做到哪了');
	    $('approveOfflinePolicyCandidate').onclick = () => reviewOfflinePolicyCandidate('approved');
	    $('rejectOfflinePolicyCandidate').onclick = () => reviewOfflinePolicyCandidate('rejected');
	    $('aiConsoleInput').onkeydown = event => {{
	      if (event.key === 'Enter' && !event.shiftKey) {{
	        event.preventDefault();
	        sendAiConsoleMessage();
	      }}
	    }};
	    $('target').oninput = refreshStartPreview;
	    $('profiles').oninput = refreshStartPreview;
	    $('volume').onchange = () => {{ $('currentVolume').textContent = $('volume').selectedOptions[0].textContent; refreshStartPreview(); }};
	    $('commentText').oninput = () => {{ updateCopyModeNotice(); refreshStartPreview(); }};
	    $('mode').onchange = () => {{ $('currentMode').textContent = $('mode').selectedOptions[0].textContent; updateCopyModeNotice(); refreshStartPreview(); refreshIxBrowserStatus(); refreshActivation(); refreshFinalStatus(); }};
	    $('liveConfirm').onchange = () => {{
	      if ($('liveConfirm').checked && $('mode').value !== 'live_comment') {{
	        $('mode').value = 'live_comment';
	        $('currentMode').textContent = $('mode').selectedOptions[0].textContent;
	      }}
	      updateCopyModeNotice();
	      refreshStartPreview();
	      refreshActivation();
	      refreshFinalStatus();
	    }};
	    $('accountRepairConfirmed').onchange = () => {{
	      accountRepairConfirmedGroup = $('accountRepairConfirmed').checked && $('group') ? $('group').value : '';
	      updateStartAvailability();
	      if ($('accountRepairConfirmed').checked) {{
	        showApiNotice(
	          '账号修复确认已开启',
	          {{status:'ready_for_account_recheck', message:`${{accountRepairConfirmedGroup || '当前分组'}} 下一次开始获客会重新预检账号；如果账号仍未修复，系统会再次阻断并生成修复计划。`}},
	          '',
	          12000
	        );
	      }}
	      refreshStartPreview();
	    }};
	    $('group').onchange = () => {{
	      if ($('accountRepairConfirmed') && $('accountRepairConfirmed').checked && normGroupName(accountRepairConfirmedGroup) !== normGroupName($('group').value)) {{
	        $('accountRepairConfirmed').checked = false;
	        accountRepairConfirmedGroup = '';
	      }}
	      updateSelectedGroupQuantity();
	      renderGroupDetails(loadedGroups, $('group').value);
	      updateStartAvailability();
	      refreshStartPreview();
	    }};
	    document.addEventListener('click', event => {{
	      const btn = event.target.closest('[data-launch-filter]');
	      if (!btn) return;
	      launchFilter = btn.dataset.launchFilter || 'all';
	      refreshAcceptance();
	    }});
	    document.addEventListener('click', event => {{
	      const leadBtn = event.target.closest('[data-lead-filter]');
	      const outreachBtn = event.target.closest('[data-outreach-filter]');
	      if (leadBtn) {{
	        leadFilter = leadBtn.dataset.leadFilter || 'all';
	        refreshAcceptance();
	      }}
	      if (outreachBtn) {{
	        outreachFilter = outreachBtn.dataset.outreachFilter || 'all';
	        refreshAcceptance();
	      }}
	    }});
	    $('sourceType').onchange = () => {{ $('targetType').textContent = $('sourceType').selectedOptions[0].textContent; refreshStartPreview(); }};
    setInterval(refreshLogs, 2000); setInterval(refreshSnapshot, 5000); setInterval(refreshAcceptance, 5000); setInterval(refreshProductCapability, 10000); setInterval(refreshIxBrowserStatus, 10000); setInterval(refreshActivation, 10000); setInterval(refreshFinalStatus, 10000);
	    updateCopyModeNotice(); refreshStartPreview(); refreshLogs(); refreshSnapshot(); refreshAcceptance(); refreshProductCapability(); refreshIxBrowserStatus(); refreshActivation(); refreshFinalStatus(); refreshGroups();
  </script>
</body>
</html>""".encode("utf-8")


def build_snapshot_payload() -> dict:
    try:
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        from ReachOps.intelligence import GrowthIntelligenceService
        from ReachOps.workbench.workflow_service import GrowthWorkflowService

        service = GrowthIntelligenceService(base_dir=DATA_DIR)
        snapshot = GrowthWorkflowService(service).build_snapshot()
        payload = asdict(snapshot)
        acceptance_payload = build_acceptance_payload()
        if isinstance(acceptance_payload, dict):
            payload["acceptance"] = acceptance_payload
            payload["latest_batch"] = acceptance_payload.get("latest_batch") or {}
            payload["latest_profile_preflight"] = acceptance_payload.get("latest_profile_preflight") or {}
            payload["operations"] = acceptance_payload.get("operations") or {}
        for key in ("candidate_users", "action_queue", "profile_health", "report_artifacts"):
            payload[key] = list(payload.get(key) or [])[:80]
        evidence_bundle = build_current_evidence_bundle()
        execution_plan_payload = build_current_execution_plan_payload()
        run_session_payload = build_current_run_session_payload()
        report_artifacts = list(payload.get("report_artifacts") or [])
        if execution_plan_payload.get("path"):
            report_artifacts.append(
                {
                    "kind": "execution_plan",
                    "label": "本轮执行计划 JSON",
                    "exists": Path(str(execution_plan_payload.get("path"))).is_file(),
                    "path": str(execution_plan_payload.get("path")),
                }
            )
        if run_session_payload.get("path"):
            report_artifacts.append(
                {
                    "kind": "run_session",
                    "label": "本轮运行会话 JSON",
                    "exists": Path(str(run_session_payload.get("path"))).is_file(),
                    "path": str(run_session_payload.get("path")),
                }
            )
        if evidence_bundle.get("path"):
            report_artifacts.append(
                {
                    "kind": "evidence_bundle",
                    "label": "本轮证据包 JSON",
                    "exists": Path(str(evidence_bundle.get("path"))).is_file(),
                    "path": str(evidence_bundle.get("path")),
                }
            )
        if evidence_bundle.get("markdown_path"):
            report_artifacts.append(
                {
                    "kind": "evidence_bundle_markdown",
                    "label": "本轮证据包 Markdown",
                    "exists": Path(str(evidence_bundle.get("markdown_path"))).is_file(),
                    "path": str(evidence_bundle.get("markdown_path")),
                }
            )
        payload["report_artifacts"] = report_artifacts[:84]
        payload["execution_plan"] = execution_plan_payload
        payload["run_session"] = run_session_payload
        payload["evidence_bundle"] = evidence_bundle
        payload["operator_summary"] = build_operator_summary_payload()
        return payload
    except Exception as exc:
        return {"error": str(exc)}


def summarize_account_repair_plan(path_value: str | Path) -> dict:
    path = Path(str(path_value or ""))
    if not path.exists():
        return {}
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "path": str(path)}
    groups = []
    for row in plan.get("groups") or []:
        if not isinstance(row, dict):
            continue
        profile_ids = [str(item) for item in (row.get("profile_ids") or []) if str(item).strip()]
        count = safe_int(row.get("count"), 0)
        profile_ids_total = safe_int(row.get("profile_ids_total"), len(profile_ids))
        summary_only_count = safe_int(row.get("summary_only_count"), max(0, count - len(profile_ids)))
        groups.append(
            {
                "error": str(row.get("error") or ""),
                "count": count,
                "profile_ids_sample": profile_ids[:12],
                "profile_ids_total": profile_ids_total,
                "summary_only_count": summary_only_count,
                "count_source": str(row.get("count_source") or ""),
                "recommended_action": str(row.get("recommended_action") or ""),
                "sample_message": str(row.get("sample_message") or ""),
            }
        )
    computed_total_events = sum(safe_int(row.get("count"), 0) for row in groups)
    computed_summary_only = sum(safe_int(row.get("summary_only_count"), 0) for row in groups)
    return {
        "status": "ok",
        "path": str(path),
        "batch_id": str(plan.get("batch_id") or ""),
        "batch_status": str(plan.get("batch_status") or ""),
        "profile_group": str(plan.get("profile_group") or ""),
        "total_unique_profiles_by_error": safe_int(plan.get("total_unique_profiles_by_error"), 0),
        "total_error_events_by_error": safe_int(
            plan.get("total_error_events_by_error"),
            computed_total_events or safe_int(plan.get("total_unique_profiles_by_error"), 0),
        ),
        "summary_only_error_count": safe_int(plan.get("summary_only_error_count"), computed_summary_only),
        "safety_contract": {
            "schema_version": "reachops.account_repair_safety_contract.v1",
            "manual_apply_required": True,
            "operator_confirmed_apply": False,
            "hard_blocker_only": True,
            "moves_only_to_quarantine_group": True,
            "no_browser_started": True,
            "no_submit": True,
            "no_ai_token_used": True,
        },
        "operator_steps": [str(item) for item in (plan.get("operator_steps") or [])],
        "error_groups": groups,
        "acceptance_after_repair": [str(item) for item in (plan.get("acceptance_after_repair") or [])],
    }


def apply_latest_account_repair_plan_from_web(profile_group: str = "") -> dict:
    with RUN_STATE_LOCK:
        if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
            return {
                "status": "rejected",
                "ok": False,
                "error": "run_in_progress",
                "message": "当前有执行任务在运行，不能同时移动账号分组。",
            }
    try:
        from tools.reachops_apply_account_repair_plan import (
            DEFAULT_PLAN_PATH,
            apply_account_repair_plan,
            load_plan,
            write_account_repair_apply_result,
        )

        plan = load_plan(DEFAULT_PLAN_PATH)
        if plan.get("status") == "error":
            return {
                "status": "failed",
                "ok": False,
                "error": plan.get("error_code") or "account_repair_plan_unavailable",
                "message": plan.get("error_message") or "账号修复计划不可读取。",
                "plan_path": str(DEFAULT_PLAN_PATH),
            }
        requested_group = str(profile_group or "").strip()
        plan_group = str(plan.get("profile_group") or "").strip()
        if requested_group and plan_group and requested_group.lower() != plan_group.lower():
            return {
                "status": "rejected",
                "ok": False,
                "error": "account_repair_group_mismatch",
                "message": f"当前分组 {requested_group} 与最新账号修复计划分组 {plan_group} 不一致，已拒绝执行。",
                "profile_group_requested": requested_group,
                "profile_group": plan_group,
                "plan_path": str(DEFAULT_PLAN_PATH),
                "next_actions": ["切回修复计划对应分组后再执行，或重新开始获客生成当前分组的修复计划。"],
            }

        old_no_proxy = os.environ.get("NO_PROXY", "")
        old_no_proxy_lower = os.environ.get("no_proxy", "")
        try:
            for key, old_value in (("NO_PROXY", old_no_proxy), ("no_proxy", old_no_proxy_lower)):
                items = [item.strip() for item in old_value.split(",") if item.strip()]
                for host in ["127.0.0.1", "localhost", "::1"]:
                    if host not in items:
                        items.append(host)
                os.environ[key] = ",".join(items)
            result = apply_account_repair_plan(DEFAULT_PLAN_PATH, apply=True)
        finally:
            os.environ["NO_PROXY"] = old_no_proxy
            os.environ["no_proxy"] = old_no_proxy_lower
    except Exception as exc:
        return {
            "status": "failed",
            "ok": False,
            "error": "account_repair_apply_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }
    result["profile_group_requested"] = str(profile_group or "")
    result_path = write_account_repair_apply_result(result)
    result["apply_result_path"] = str(result_path)
    if result.get("status") == "applied":
        append_web_log(
            f"CONFIG account_repair_apply status=applied group={result.get('profile_group') or profile_group or '-'} "
            f"selected={result.get('selected_count', 0)} moved={result.get('moved_count', 0)} failed={result.get('failed_count', 0)}"
        )
        result.setdefault("next_actions", []).extend(
            [
                "点击刷新分组确认坏账号已移入封禁账号分组。",
                "确认至少 1 个可用账号保留在执行分组后，再勾选重新预检并开始获客。",
            ]
        )
    elif result.get("status") == "no_applicable_profiles":
        append_web_log(
            f"WARN   account_repair_apply status=no_applicable_profiles group={result.get('profile_group') or profile_group or '-'} "
            f"selected={result.get('selected_count', 0)} moved={result.get('moved_count', 0)} failed={result.get('failed_count', 0)} "
            f"errors={','.join(result.get('non_auto_error_codes') or []) or '-'}"
        )
        result.setdefault("next_actions", []).extend(
            [
                "最新账号修复计划没有默认可自动隔离的账号，未移动任何 ixBrowser 配置。",
                "手动打开受影响账号，确认登录状态、内核版本、代理和 TikTok 页面加载；不可用账号再移入封禁账号分组。",
                "至少保留 1 个已登录、内核匹配、可手动打开 TikTok 的账号在执行分组内，再复跑真实执行复测。",
            ]
        )
    else:
        first_error = ""
        for row in result.get("results") or []:
            if row.get("error_code"):
                first_error = f"{row.get('error_code')}:{row.get('error_message')}"
                break
        append_web_log(
            f"WARN   account_repair_apply status={result.get('status')} group={result.get('profile_group') or profile_group or '-'} "
            f"selected={result.get('selected_count', 0)} moved={result.get('moved_count', 0)} failed={result.get('failed_count', 0)} "
            f"error={first_error or '-'}"
        )
        result.setdefault("next_actions", []).extend(
            [
                "确认 ixBrowser 客户端已启动，Local API 端口可连接。",
                "如果仍失败，请在 ixBrowser 手动把修复计划账号移入封禁账号分组。",
            ]
        )
    return result


def build_acceptance_payload() -> dict:
    try:
        from tools.reachops_client_acceptance_status import (
            derive_acceptance,
            latest_batch,
            latest_profile_preflight,
            read_lines as read_acceptance_lines,
            write_remediation_report,
        )

        db_path = DATA_DIR / "data/growth_intelligence/growth_intelligence.db"
        finalize_stale_web_batch_if_needed(db_path)
        batch = latest_batch(db_path)
        preflight = latest_profile_preflight(db_path)
        if batch.get("created_at") and preflight.get("created_at"):
            if str(preflight.get("created_at")) < str(batch.get("created_at")):
                preflight = {}
        runtime_progress = read_runtime_progress_payload()
        runtime_preflight = (
            runtime_progress.get("profile_preflight_progress")
            if isinstance(runtime_progress.get("profile_preflight_progress"), dict)
            else {}
        )
        acceptance = derive_acceptance(batch, preflight, read_acceptance_lines(LOG_PATH))
        db_details = load_batch_profile_preflight_details(db_path, batch)
        acceptance["profile_preflight_details"] = db_details or enrich_profile_quarantine_moves(
            db_path,
            acceptance.get("profile_preflight_details") or [],
        )
        remediation_report = write_remediation_report(
            DATA_DIR,
            batch,
            acceptance.get("profile_preflight_details") or [],
            preflight_errors=(acceptance.get("profile_preflight_summary") or {}).get("errors") or {},
        )
        account_repair_summary = summarize_account_repair_plan(
            remediation_report.get("latest_account_plan_json_path")
            or remediation_report.get("account_plan_json_path")
            or ""
        )
        operations = build_operations_payload(db_path, batch, acceptance, read_acceptance_lines(LOG_PATH, limit=800))
        annotate_acceptance_with_operations(acceptance, operations, batch)
        from tools.reachops_client_delivery_check import build_delivery_check, write_delivery_check

        client_delivery = build_delivery_check(DATA_DIR)
        write_delivery_check(client_delivery)
        ix_metadata = client_delivery.get("ixbrowser_metadata") if isinstance(client_delivery.get("ixbrowser_metadata"), dict) else {}
        preflight_for_display = acceptance.get("profile_preflight_summary") or preflight
        if runtime_preflight and runtime_progress.get("running"):
            merged_preflight = dict(preflight_for_display or {})
            for key in ("checked", "available", "unavailable", "errors"):
                value = runtime_preflight.get(key)
                if value not in (None, ""):
                    merged_preflight[key] = value
            if runtime_progress.get("timestamp"):
                merged_preflight["created_at"] = runtime_progress.get("timestamp")
            preflight_for_display = merged_preflight
        return {
            "latest_batch": batch,
            "latest_profile_preflight": {
                "checked": preflight_for_display.get("checked", 0),
                "available": preflight_for_display.get("available", 0),
                "unavailable": preflight_for_display.get("unavailable", 0),
                "errors": preflight_for_display.get("errors", {}),
                "created_at": preflight_for_display.get("created_at", preflight.get("created_at", "")),
            },
            "acceptance": acceptance,
            "client_delivery": {
                "status": client_delivery.get("status"),
                "readiness": client_delivery.get("readiness"),
                "contract_ok": client_delivery.get("contract_ok"),
                "acceptance_ready": client_delivery.get("acceptance_ready"),
                "final_delivery_ready": client_delivery.get("final_delivery_ready"),
                "failed_checks": client_delivery.get("failed_checks") or [],
                "blockers": client_delivery.get("blockers") or [],
                "next_actions": client_delivery.get("next_actions") or [],
                "account_blocker_resolution": client_delivery.get("account_blocker_resolution") or {},
                "account_support_handoff": client_delivery.get("account_support_handoff") or {},
                "account_repair_apply": client_delivery.get("account_repair_apply") or {},
                "delivery_check_path": client_delivery.get("delivery_check_path", ""),
                "ixbrowser_metadata": {
                    "status": ix_metadata.get("status", ""),
                    "profile_count": ix_metadata.get("profile_count", 0),
                    "group_count": ix_metadata.get("group_count", 0),
                    "selected_profile_count": ix_metadata.get("selected_profile_count", 0),
                    "safe_read_only": ix_metadata.get("safe_read_only", False),
                    "open_profile_called": ix_metadata.get("open_profile_called", False),
                } if ix_metadata else {},
            },
            "mvp_acceptance": summarize_mvp_acceptance(),
            "goal_delivery": summarize_goal_delivery(),
            "two_phase_acceptance": summarize_two_phase_acceptance(),
            "operations": operations,
            "runtime_progress": runtime_progress,
            "remediation_report": remediation_report,
            "account_repair_summary": account_repair_summary,
            "account_repair_apply": client_delivery.get("account_repair_apply") or {},
        }
    except Exception as exc:
        return {"error": str(exc)}


def annotate_acceptance_with_operations(acceptance: dict, operations: dict, batch: dict) -> None:
    counts = (operations or {}).get("counts") or {}
    status = str((batch or {}).get("status") or "")
    finished = status in {"completed", "partial_failed", "failed"}
    if not finished:
        return
    if safe_int(counts.get("actions"), 0) > 0:
        return
    next_actions = list(acceptance.get("next_actions") or [])
    generic = "重新点击开始获客，观察是否出现 DONE collection 和 START action_*。"
    success_message = "已达到客户端验收：目标识别、账号跳过、采集、触达和批次收口均有证据。"
    next_actions = [item for item in next_actions if item not in {generic, success_message}]
    no_action_reason = {
        "code": "",
        "message": "",
        "candidate_count": safe_int(counts.get("candidates"), 0),
        "qualified_lead_count": safe_int(counts.get("qualified_leads"), 0),
        "action_count": safe_int(counts.get("actions"), 0),
        "no_submit": True,
    }
    if safe_int(counts.get("candidates"), 0) > 0 and safe_int(counts.get("qualified_leads"), 0) <= 0:
        no_action_reason.update(
            {
                "code": "low_intent_candidates",
                "message": "本轮采集到候选用户，但评分未达到触达线，系统已跳过评论以避免误触达。",
            }
        )
        next_actions.extend(
            [
                no_action_reason["message"],
                "换更明确的推广目标或关键词，例如 产品型号 + review / unboxing / where to buy。",
                "补充更多已登录可用账号，避免实际并发降级导致覆盖面不足。",
            ]
        )
    elif safe_int(counts.get("candidates"), 0) <= 0:
        no_action_reason.update(
            {
                "code": "no_candidates",
                "message": "本轮没有采集到候选用户，当前来源没有有效评论用户或页面跳转不稳定，系统没有进入触达。",
            }
        )
        if str(acceptance.get("readiness") or "") == "pass":
            acceptance["readiness"] = "partial"
        blockers = list(acceptance.get("blockers") or [])
        if no_action_reason["message"] not in blockers:
            blockers.append(no_action_reason["message"])
        acceptance["blockers"] = blockers
        next_actions.extend(
            [
                "本轮没有采集到候选用户，建议更换关键词或直接输入相关 TikTok 视频/达人链接。",
                "检查可用账号数量和页面跳转稳定性，当前账号覆盖面不足时会影响采集结果。",
            ]
        )
    if no_action_reason["code"]:
        acceptance["no_action_reason"] = no_action_reason
    acceptance["next_actions"] = next_actions or [generic]


def build_operations_payload(db_path: Path, batch: dict, acceptance: dict, log_lines: list[str]) -> dict:
    batch_id = str((batch or {}).get("id") or "")
    config = {}
    try:
        config = json.loads(str((batch or {}).get("config_json") or "{}"))
    except Exception:
        config = {}
    quick_send = config.get("quick_send") if isinstance(config, dict) else {}
    requested = safe_int((quick_send or {}).get("requested_concurrency") or (quick_send or {}).get("requested_profiles"), 0)
    if requested <= 0:
        requested = extract_requested_profile_count(batch_id, log_lines)
    actual = extract_actual_profile_count(batch_id, log_lines)
    details = list((acceptance or {}).get("profile_preflight_details") or [])
    available = len([row for row in details if str(row.get("status") or "") == "可用"])
    if available <= 0:
        available = safe_int(((acceptance or {}).get("checks") or {}).get("profile_available_count"), 0)
    if actual <= 0:
        actual = available
    rows = {
        "collection_tasks": [],
        "action_queue": [],
        "outreach_executions": [],
        "profile_queue": [],
        "lead_view": [],
        "outreach_view": [],
    }
    counts = {
        "candidates": 0,
        "actions": 0,
        "touched": 0,
        "touch_success": 0,
        "touch_failed": 0,
        "touch_skipped": 0,
        "high_intent": 0,
        "qualified_leads": 0,
    }
    if db_path.exists() and batch_id:
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                count_row = conn.execute(
                    "SELECT COUNT(*) AS count FROM candidate_users WHERE batch_id=?",
                    (batch_id,),
                ).fetchone()
                counts["candidates"] = safe_int(count_row["count"] if count_row else 0, 0)
                high_row = conn.execute(
                    "SELECT COUNT(*) AS count FROM candidate_users WHERE batch_id=? AND qualify_score>=50",
                    (batch_id,),
                ).fetchone()
                counts["high_intent"] = safe_int(high_row["count"] if high_row else 0, 0)
                rows["collection_tasks"] = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT source_type, source_value, profile_id, status, error_code, error_message, updated_at
                        FROM collection_tasks
                        WHERE batch_id=?
                        ORDER BY created_at ASC, rowid ASC
                        LIMIT 80
                        """,
                        (batch_id,),
                    ).fetchall()
                ]
                rows["action_queue"] = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT aq.id, aq.lead_id, aq.target_username, aq.action_type, aq.target_url,
                               aq.suggested_text, aq.reason, aq.status, aq.risk_level,
                               aq.last_error_code, aq.last_error_message, aq.last_executed_at,
                               ol.score AS lead_score, ol.lead_type, ol.priority
                        FROM action_queue aq
                        LEFT JOIN operation_leads ol ON ol.id = aq.lead_id
                        WHERE aq.batch_id=?
                        ORDER BY aq.created_at DESC, aq.rowid DESC
                        LIMIT 80
                        """,
                        (batch_id,),
                    ).fetchall()
                ]
                rows["outreach_executions"] = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT oe.id, oe.action_id, oe.target_username, oe.action_type, oe.profile_id,
                               oe.status, oe.evidence_path, oe.error_code, oe.error_message,
                               oe.risk_gate_json, oe.completed_at, oe.created_at,
                               aq.suggested_text, aq.reason AS action_reason, aq.target_url,
                               aq.last_error_code, aq.last_error_message,
                               ol.score AS lead_score, ol.lead_type, ol.priority
                        FROM outreach_executions oe
                        LEFT JOIN action_queue aq ON aq.id = oe.action_id
                        LEFT JOIN operation_leads ol ON ol.id = aq.lead_id
                        WHERE oe.batch_id=?
                        ORDER BY oe.created_at DESC, oe.rowid DESC
                        LIMIT 80
                        """,
                        (batch_id,),
                    ).fetchall()
                ]
                rows["lead_view"] = load_operator_lead_rows(conn, batch_id)
                if not rows["lead_view"]:
                    rows["lead_view"] = load_candidate_lead_rows(conn, batch_id)
                rows["outreach_view"] = build_operator_outreach_rows(rows["action_queue"], rows["outreach_executions"], config)
                rows["profile_queue"] = load_profile_queue_rows(conn, batch_id)
        except Exception:
            pass
    counts["qualified_leads"] = len([row for row in rows["lead_view"] if safe_int(row.get("score") or row.get("qualify_score"), 0) >= 50])
    counts["actions"] = len(rows["action_queue"])
    counts["touched"] = len(rows["outreach_executions"])
    counts["touch_success"] = len([row for row in rows["outreach_executions"] if str(row.get("status") or "") in {"success", "completed"}])
    counts["touch_failed"] = len([row for row in rows["outreach_executions"] if str(row.get("status") or "") == "failed"])
    counts["touch_skipped"] = len([row for row in rows["outreach_executions"] if str(row.get("status") or "") == "skipped"])
    success_rate = 0
    if counts["touched"]:
        success_rate = round((counts["touch_success"] / counts["touched"]) * 100)
    exception_counts = summarize_profile_detail_counts(details)
    return {
        "requested_concurrency": requested,
        "actual_concurrency": actual,
        "available_profiles": available,
        "degraded_reason": "" if requested <= 0 or actual >= requested else "可用账号不足，已自动降级执行",
        "success_rate": success_rate,
        "counts": counts,
        "exception_counts": exception_counts,
        "collection_tasks": rows["collection_tasks"],
        "action_queue": rows["action_queue"],
        "outreach_executions": rows["outreach_executions"],
        "lead_view": rows["lead_view"],
        "outreach_view": rows["outreach_view"],
        "profile_queue": rows["profile_queue"],
    }


def load_operator_lead_rows(conn: sqlite3.Connection, batch_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT ol.id, ol.candidate_user_id, ol.lead_type, ol.priority, ol.score, ol.reason,
               ol.lifecycle_stage, ol.status, ol.source_path, ol.created_at, ol.updated_at,
               cu.username, cu.profile_url, cu.comment_text, cu.qualify_score, cu.intent_tags,
               cu.source_path AS candidate_source_path,
               dc.video_url, dc.video_id, dc.caption,
               COUNT(aq.id) AS action_count,
               GROUP_CONCAT(aq.action_type) AS action_types,
               SUM(CASE WHEN aq.status IN ('completed','success') THEN 1 ELSE 0 END) AS success_action_count,
               SUM(CASE WHEN aq.status IN ('failed','retryable') THEN 1 ELSE 0 END) AS failed_action_count,
               SUM(CASE WHEN aq.status='skipped' OR aq.status='rejected' THEN 1 ELSE 0 END) AS skipped_action_count
        FROM operation_leads ol
        LEFT JOIN candidate_users cu ON cu.id = ol.candidate_user_id
        LEFT JOIN discovered_contents dc ON dc.id = cu.content_id
        LEFT JOIN action_queue aq ON aq.lead_id = ol.id
        WHERE ol.batch_id=?
        GROUP BY ol.id
        ORDER BY ol.score DESC, ol.updated_at DESC, ol.created_at DESC
        LIMIT 120
        """,
        (batch_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        source = item.get("source_path") or item.get("candidate_source_path") or item.get("video_url") or item.get("profile_url") or ""
        tags = parse_json_list(item.get("intent_tags"))
        item["source_path"] = source
        item["source_url"] = source if str(source).startswith(("http://", "https://")) else ""
        item["source_label"] = "查看视频" if item.get("video_url") else ("查看主页" if item.get("profile_url") else "查看来源")
        item["lead_type_label"] = human_lead_type(item.get("lead_type"), tags, safe_int(item.get("score"), 0))
        item["intent_labels"] = human_intent_labels(tags)
        item["intent_confidence"] = extract_intent_confidence(tags)
        item["matched_reason"] = item.get("reason") or item.get("comment_text") or item.get("caption") or ""
        item["recommended_actions"] = [human_action_type(value) for value in compact_csv(item.get("action_types"))]
        item["current_status"] = operator_lead_status(item)
        result.append(item)
    return result


def load_candidate_lead_rows(conn: sqlite3.Connection, batch_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT cu.id, cu.username, cu.profile_url, cu.comment_text, cu.qualify_score,
               cu.intent_tags, cu.status, cu.created_at,
               dc.video_url, dc.video_id, dc.caption, dc.source_path
        FROM candidate_users cu
        LEFT JOIN discovered_contents dc ON dc.id = cu.content_id
        WHERE cu.batch_id=?
        ORDER BY cu.qualify_score DESC, cu.created_at DESC
        LIMIT 120
        """,
        (batch_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        score = safe_int(item.get("qualify_score"), 0)
        tags = parse_json_list(item.get("intent_tags"))
        source = item.get("video_url") or item.get("source_path") or item.get("profile_url") or ""
        item["score"] = score
        item["source_url"] = source if str(source).startswith(("http://", "https://")) else ""
        item["source_label"] = "查看视频" if item.get("video_url") else ("查看主页" if item.get("profile_url") else "查看来源")
        item["lead_type"] = "candidate"
        item["lead_type_label"] = human_lead_type("", tags, score)
        item["intent_labels"] = human_intent_labels(tags)
        item["intent_confidence"] = extract_intent_confidence(tags)
        item["matched_reason"] = item.get("comment_text") or item.get("caption") or "采集候选用户，等待线索入队"
        item["recommended_actions"] = ["评论回复"] if score >= 50 else ["继续观察"]
        item["current_status"] = "new"
        result.append(item)
    return result


def build_operator_outreach_rows(action_rows: list[dict], execution_rows: list[dict], config: dict) -> list[dict]:
    mode = str(((config or {}).get("quick_send") or {}).get("mode") or (config or {}).get("mode") or "")
    mode_label = human_execution_mode(mode)
    by_action = {str(row.get("action_id") or ""): row for row in execution_rows if row.get("action_id")}
    result = []
    seen_actions: set[str] = set()
    for action in action_rows:
        action_id = str(action.get("id") or "")
        execution = by_action.get(action_id, {})
        if action_id:
            seen_actions.add(action_id)
        row = {**action, **{k: v for k, v in execution.items() if v not in (None, "")}}
        row["status"] = outreach_operator_status(action, execution)
        row["action_label"] = human_action_type(row.get("action_type"))
        row["execution_mode_label"] = mode_label
        row["failure_reason"] = human_failure_reason(row)
        row["risk_gate"] = extract_risk_gate(row)
        row["risk_gate_summary"] = human_risk_gate_summary(row)
        row["evidence_label"] = "查看证据" if row.get("evidence_path") and not str(row.get("evidence_path")).startswith("evidence://") else ""
        row["next_step"] = outreach_next_step(row)
        result.append(row)
    for execution in execution_rows:
        action_id = str(execution.get("action_id") or "")
        if action_id and action_id in seen_actions:
            continue
        row = dict(execution)
        row["status"] = outreach_operator_status({}, execution)
        row["action_label"] = human_action_type(row.get("action_type"))
        row["execution_mode_label"] = mode_label
        row["failure_reason"] = human_failure_reason(row)
        row["risk_gate"] = extract_risk_gate(row)
        row["risk_gate_summary"] = human_risk_gate_summary(row)
        row["evidence_label"] = "查看证据" if row.get("evidence_path") and not str(row.get("evidence_path")).startswith("evidence://") else ""
        row["next_step"] = outreach_next_step(row)
        result.append(row)
    return sorted(result, key=lambda item: str(item.get("created_at") or item.get("last_executed_at") or ""), reverse=True)[:120]


def parse_json_list(value) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def parse_json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def extract_risk_gate(row: dict) -> dict:
    existing = row.get("risk_gate")
    if isinstance(existing, dict):
        return existing
    return parse_json_dict(row.get("risk_gate_json"))


def compact_csv(value) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def extract_intent_confidence(tags: list[str]) -> int:
    for tag in tags:
        if tag.startswith("intent_confidence:"):
            try:
                return round(float(tag.split(":", 1)[1]) * 100)
            except Exception:
                return 0
    return 0


def human_intent_labels(tags: list[str]) -> list[str]:
    labels = []
    mapping = {
        "liked_comment": "互动评论",
        "custom_intent:size": "询问规格",
        "custom_intent:price": "询问价格",
        "custom_intent:link": "询问链接",
        "intent_type:purchase": "购买意图",
        "intent_type:low_intent": "低意向",
        "intent_type:link": "询问链接",
    }
    for tag in tags:
        if tag in mapping and mapping[tag] not in labels:
            labels.append(mapping[tag])
    return labels


def human_lead_type(lead_type, tags: list[str], score: int) -> str:
    value = str(lead_type or "")
    mapping = {
        "purchase": "购买意图",
        "low_intent": "低意向",
        "link": "询问链接",
        "price": "询问价格",
        "engaged_commenter": "互动用户",
    }
    if value in mapping:
        return mapping[value]
    if "intent_type:purchase" in tags:
        return f"购买意图 {extract_intent_confidence(tags) or score}%"
    if "intent_type:low_intent" in tags or score < 50:
        return "低意向"
    return value or ("高意向" if score >= 70 else "有效线索")


def human_action_type(action_type) -> str:
    return {
        "comment_reply": "评论回复",
        "follow_review": "关注复核",
        "dm_review": "私信复核",
        "profile_visit": "访问主页",
    }.get(str(action_type or ""), str(action_type or "待定"))


def human_execution_mode(mode: str) -> str:
    return {
        "preflight": "预检",
        "collect": "只采集",
        "live_comment": "真实评论",
    }.get(str(mode or ""), "预检")


def operator_lead_status(row: dict) -> str:
    if safe_int(row.get("success_action_count"), 0) > 0:
        return "contacted"
    if safe_int(row.get("failed_action_count"), 0) > 0:
        return "needs_retry"
    if safe_int(row.get("skipped_action_count"), 0) > 0:
        return "skipped"
    if safe_int(row.get("action_count"), 0) > 0:
        return "queued"
    return str(row.get("lifecycle_stage") or row.get("status") or "new")


def outreach_operator_status(action: dict, execution: dict) -> str:
    execution_status = str((execution or {}).get("status") or "")
    if execution_status:
        return execution_status
    status = str((action or {}).get("status") or "")
    return status or "queued"


def human_failure_reason(row: dict) -> str:
    if str(row.get("status") or "") in {"completed", "success"}:
        return ""
    code = str(row.get("error_code") or row.get("last_error_code") or "")
    message = str(row.get("error_message") or row.get("last_error_message") or "")
    if not code and not message:
        return ""
    mapping = {
        "LOGIN_REQUIRED": "账号未登录，已跳过并切换下一个账号",
        "COMMENT_SUBMIT_FAILED": "评论提交失败，系统记录证据并进入重试/跳过处理",
        "OUTREACH_EXECUTION_FAILED": "触达执行失败，系统记录失败原因",
        "DAILY_QUOTA_EXCEEDED": "账号当日额度已满，自动切换账号",
        "TARGET_EXCLUDED": "目标命中排除规则，已跳过",
    }
    return mapping.get(code, f"{code} {message}".strip())


def human_risk_gate_summary(row: dict) -> str:
    risk_gate = extract_risk_gate(row)
    if not risk_gate:
        return ""
    reason_code = str(risk_gate.get("reason_code") or "").strip()
    reason = str(risk_gate.get("reason") or "").strip()
    category = str(risk_gate.get("risk_category") or "").strip()
    outcome = str(risk_gate.get("terminal_outcome") or "").strip()
    if bool(risk_gate.get("allowed")):
        return "风险门禁通过"
    parts = ["风险门禁阻断"]
    if reason_code:
        parts.append(reason_code)
    if category:
        parts.append(f"类别：{category}")
    if outcome:
        parts.append(f"结果：{outcome}")
    if reason and reason != reason_code:
        parts.append(reason)
    return " / ".join(parts)


def outreach_next_step(row: dict) -> str:
    risk_gate = extract_risk_gate(row)
    risk_actions = risk_gate.get("risk_actions") if isinstance(risk_gate, dict) else []
    if isinstance(risk_actions, list) and risk_actions:
        mapping = {
            "request_operator_authorization": "等待人工授权后再执行",
            "rewrite_or_rotate_message": "改写或轮换话术后重试",
            "cooldown_scope": "账号进入冷却，切换账号或等待",
            "wait_or_switch_profile": "等待冷却或自动切换账号",
            "switch_profile_group": "切换到非发布主账号分组",
            "request_review_note": "补充高风险复核说明",
            "refresh_profile_groups": "刷新账号分组后重试",
            "reselect_profile_group": "重新选择可用账号分组",
            "block_execution": "保持阻断，等待处理",
        }
        labels = []
        for action in risk_actions:
            step = str((action or {}).get("step") or "")
            if step:
                labels.append(mapping.get(step, step))
        if labels:
            return "；".join(labels[:3])
    status = str(row.get("status") or "")
    if status in {"completed", "success"}:
        return "复核证据，继续下一条"
    if status in {"failed", "retryable"}:
        return "查看失败原因，自动重试或切换账号"
    if status == "skipped":
        return "已跳过，不影响后续队列"
    if status in {"pending_review", "approved", "ready_to_execute", "queued"}:
        return "等待自动执行"
    if status == "running":
        return "正在执行，等待证据"
    return "继续观察"


def load_profile_queue_rows(conn: sqlite3.Connection, batch_id: str) -> list[dict]:
    events = conn.execute(
        """
        SELECT event, entity_id, payload, created_at
        FROM growth_events
        WHERE event IN (
          'profile_queue_enqueued',
          'profile_queue_started',
          'profile_queue_source_completed',
          'profile_queue_source_failed',
          'profile_queue_quota_reached',
          'profile_queue_skipped'
        )
        ORDER BY rowid ASC
        LIMIT 600
        """
    ).fetchall()
    by_profile: dict[str, dict] = {}
    order: list[str] = []
    for row in events:
        try:
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            payload = {}
        if str(payload.get("batch_id") or "") != batch_id:
            continue
        profile_id = str(payload.get("profile_id") or row["entity_id"] or "")
        if not profile_id:
            continue
        if profile_id not in by_profile:
            order.append(profile_id)
            by_profile[profile_id] = {
                "profile_id": profile_id,
                "queue_index": safe_int(payload.get("queue_index"), len(order)),
                "status": "waiting",
                "sources_done": 0,
                "max_sources_per_profile": safe_int(payload.get("max_sources_per_profile"), 1),
                "requested_concurrency": safe_int(payload.get("requested_concurrency"), 1),
                "source_type": "",
                "source_value": "",
                "reason": "",
                "updated_at": row["created_at"],
            }
        item = by_profile[profile_id]
        if payload.get("queue_index"):
            item["queue_index"] = safe_int(payload.get("queue_index"), item.get("queue_index", 0))
        item["status"] = str(payload.get("status") or row["event"].replace("profile_queue_", ""))
        item["sources_done"] = max(safe_int(item.get("sources_done"), 0), safe_int(payload.get("sources_done"), 0))
        item["max_sources_per_profile"] = safe_int(payload.get("max_sources_per_profile"), item.get("max_sources_per_profile", 1))
        item["requested_concurrency"] = safe_int(payload.get("requested_concurrency"), item.get("requested_concurrency", 1))
        item["source_type"] = str(payload.get("source_type") or item.get("source_type") or "")
        item["source_value"] = str(payload.get("source_value") or item.get("source_value") or "")
        item["reason"] = str(payload.get("reason") or item.get("reason") or "")
        item["event"] = row["event"]
        item["updated_at"] = row["created_at"]
    return sorted(
        [by_profile[profile_id] for profile_id in order if profile_id in by_profile],
        key=lambda item: (safe_int(item.get("queue_index"), 9999), str(item.get("profile_id") or "")),
    )


def extract_actual_profile_count(batch_id: str, log_lines: list[str]) -> int:
    if not batch_id:
        return 0
    actual = 0
    active = False
    for line in log_lines:
        if batch_id in line:
            active = True
        if not active:
            continue
        if "START  campaign" in line and " profiles=" in line:
            marker = " profiles="
            value = line.split(marker, 1)[1].split(" ", 1)[0].strip()
            actual = max(actual, safe_int(value, 0))
        if "FAST   collection_result" in line and "used_profiles=" in line:
            value = line.split("used_profiles=", 1)[1].split(" ", 1)[0].strip()
            actual = max(actual, safe_int(value, 0))
    return actual


def extract_requested_profile_count(batch_id: str, log_lines: list[str]) -> int:
    if not batch_id:
        return 0
    requested = 0
    active = False
    for line in log_lines:
        if batch_id in line:
            active = True
        if not active and "FAST   target_quick_send" in line and "requested_profiles=" in line:
            requested = safe_int(line.split("requested_profiles=", 1)[1].split(" ", 1)[0].strip(), requested)
        if active and "requested_profiles=" in line:
            requested = safe_int(line.split("requested_profiles=", 1)[1].split(" ", 1)[0].strip(), requested)
        if active and "START  campaign" in line and " profiles=" in line:
            break
    return requested


def summarize_profile_detail_counts(details: list[dict]) -> dict:
    counts = {
        "available": 0,
        "login_required": 0,
        "timeout": 0,
        "kernel_mismatch": 0,
        "server_busy": 0,
        "page_open_failed": 0,
        "moved": 0,
        "skipped": 0,
    }
    for row in details:
        error = str(row.get("error") or "")
        if str(row.get("status") or "") == "可用":
            counts["available"] += 1
        else:
            counts["skipped"] += 1
        if error == "LOGIN_REQUIRED":
            counts["login_required"] += 1
        elif error == "PROFILE_PREFLIGHT_TIMEOUT":
            counts["timeout"] += 1
        elif error == "IXBROWSER_KERNEL_MISMATCH":
            counts["kernel_mismatch"] += 1
        elif error == "IXBROWSER_SERVER_BUSY":
            counts["server_busy"] += 1
        elif error == "PAGE_OPEN_FAILED":
            counts["page_open_failed"] += 1
        if (row.get("quarantine_move") or {}).get("ok"):
            counts["moved"] += 1
    return counts


def enrich_profile_quarantine_moves(db_path: Path, details: list[dict]) -> list[dict]:
    if not db_path.exists() or not details:
        return details
    profile_ids = [str(row.get("profile_id") or "") for row in details if row.get("profile_id")]
    if not profile_ids:
        return details
    placeholders = ",".join("?" for _ in profile_ids)
    moves: dict[str, dict] = {}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT event, entity_id, payload, created_at
                FROM growth_events
                WHERE event IN ('profile_quarantine_move_completed', 'profile_quarantine_move_failed')
                  AND entity_id IN ({placeholders})
                ORDER BY rowid DESC
                """,
                profile_ids,
            ).fetchall()
    except Exception:
        return details
    for row in rows:
        profile_id = str(row["entity_id"] or "")
        if profile_id in moves:
            continue
        try:
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            payload = {}
        payload["event"] = row["event"]
        payload["created_at"] = row["created_at"]
        moves[profile_id] = payload
    enriched = []
    for item in details:
        row = dict(item)
        row["quarantine_move"] = moves.get(str(item.get("profile_id") or ""), {"attempted": False})
        enriched.append(row)
    return enriched


def load_batch_profile_preflight_details(db_path: Path, batch: dict) -> list[dict]:
    if not db_path.exists() or not batch:
        return []
    start = str(batch.get("created_at") or "")
    end = str(batch.get("completed_at") or "")
    if not end:
        end = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not start:
        return []
    params: list[str] = [start]
    where = "created_at >= ?"
    if end:
        where += " AND created_at <= ?"
        params.append(end)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT entity_id, payload, created_at
                FROM growth_events
                WHERE event='profile_preflight_checked'
                  AND {where}
                ORDER BY rowid ASC
                """,
                params,
            ).fetchall()
    except Exception:
        return []
    detail_by_profile: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            payload = {}
        profile_id = str(payload.get("profile_id") or row["entity_id"] or "")
        if not profile_id:
            continue
        if profile_id not in detail_by_profile:
            order.append(profile_id)
        ok = bool(payload.get("ok"))
        error = str(payload.get("error_code") or "")
        if ok:
            close_action = "preflight_ok_released"
            operator_hint = "预检通过后自动关闭浏览器实例，不是闪退"
        elif error == "LOGIN_REQUIRED":
            close_action = "closed_and_switched"
            operator_hint = "TikTok登录态不足，已关闭并自动换号"
        elif error:
            close_action = "closed_and_skipped"
            operator_hint = "配置预检异常，已关闭并继续下一个账号"
        else:
            close_action = "closed_after_check"
            operator_hint = "预检结束后自动回收浏览器实例"
        detail_by_profile[profile_id] = {
            "profile_id": profile_id,
            "status": "可用" if ok else "不可用",
            "error": "无" if ok else error,
            "evidence": str(payload.get("evidence_path") or ""),
            "close_action": str(payload.get("close_action") or close_action),
            "operator_hint": str(payload.get("operator_hint") or operator_hint),
            "message": str(payload.get("error_message") or error or payload.get("message") or ""),
            "quarantine_move": payload.get("quarantine_move") or {"attempted": False},
            "created_at": row["created_at"],
        }
    return [detail_by_profile[profile_id] for profile_id in order if profile_id in detail_by_profile]


def load_groups(refresh: bool = False, *, allow_async: bool = False) -> dict:
    global GROUP_CACHE
    if not refresh and GROUP_CACHE.get("groups") and time.time() - float(GROUP_CACHE.get("loaded_at") or 0) < 60:
        return payload_with_background_refresh_state(cached_groups_payload_for_read(GROUP_CACHE))
    if not refresh:
        cached = read_cached_groups_payload()
        if cached.get("groups") and known_group_count(cached):
            return payload_with_background_refresh_state(cached_groups_payload_for_read(cached))
    if refresh and allow_async:
        cached = read_cached_groups_payload()
        if cached.get("groups"):
            started = start_group_refresh_background()
            data = payload_with_background_refresh_state(cached, refresh_started=started)
            data["error"] = ""
            data["error_detail"] = ""
            return data
    try:
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        os.environ["REACHOPS_IXBROWSER_API_PORT"] = active_ixbrowser_api_port()
        from ReachOps.workbench.standalone_app import (
            StandaloneProfileRegistry,
            group_display_name,
            group_name_from_display,
            resolve_ixbrowser_group_counts,
        )

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            lambda: StandaloneProfileRegistry().refresh(
                include_profiles=False,
                resolve_group_counts=False,
            )
        )
        try:
            snapshot = future.result(timeout=GROUP_REFRESH_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            future.cancel()
            GROUP_CACHE = cached_groups_payload_with_error(
                f"ixBrowser Local API 读取超时（{GROUP_REFRESH_TIMEOUT_SECONDS:g}s）",
                f"profile_group_list_timeout_after_{GROUP_REFRESH_TIMEOUT_SECONDS:g}s",
            )
            return GROUP_CACHE
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if refresh and snapshot.get("groups"):
            snapshot = dict(snapshot)
            groups_for_count = apply_cached_counts_to_live_groups(
                [dict(row) for row in snapshot.get("groups") or []]
            )
            snapshot["groups"] = groups_for_count
            originally_known = {
                str(row.get("group_id") or row.get("group_name") or ""): bool(row.get("count_known"))
                for row in groups_for_count
            }
            for row in groups_for_count:
                if row.get("count_known"):
                    row["count_source"] = row.get("count_source") or "ixbrowser_group_list"
            unresolved = [row for row in groups_for_count if row.get("group_id") and not row.get("count_known")]
            if unresolved:
                try:
                    snapshot["groups"] = resolve_ixbrowser_group_counts(
                        groups_for_count,
                        max_workers=GROUP_COUNT_RESOLVE_WORKERS,
                        timeout_seconds=GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS,
                    )
                    snapshot["group_count"] = len(snapshot["groups"])
                    countable_groups = [row for row in snapshot["groups"] if row.get("group_id")]
                    known_count = len([row for row in countable_groups if row.get("count_known")])
                    snapshot["counts_resolved"] = bool(countable_groups) and known_count == len(countable_groups)
                    if known_count <= 0:
                        snapshot["count_resolution_error"] = (
                            f"ixbrowser_profile_count_unavailable_or_timed_out_after_{GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS:g}s"
                        )
                    elif known_count < len(countable_groups):
                        snapshot["count_resolution_error"] = (
                            f"ixbrowser_profile_count_partial_{known_count}_of_{len(countable_groups)}"
                        )
                except Exception as exc:
                    snapshot = dict(snapshot)
                    snapshot["count_resolution_error"] = str(exc)
            for row in snapshot.get("groups") or []:
                key = str(row.get("group_id") or row.get("group_name") or "")
                if row.get("count_known") and not row.get("count_source"):
                    row["count_source"] = "ixbrowser_group_list" if originally_known.get(key) else "ixbrowser_profile_list"
        groups = []
        for row in snapshot.get("groups") or []:
            label = group_display_name(row)
            count_known = bool(row.get("count_known"))
            group_name = group_name_from_display(label)
            count = safe_int(row.get("count"), 0)
            count_label = f"{count}账号" if count_known else "数量未返回"
            groups.append(
                {
                    "label": (
                        f"{group_name} / {count_label}"
                        if count_known
                        else f"{group_name} / {count_label}"
                    ),
                    "name": group_name,
                    "group_id": str(row.get("group_id") or ""),
                    "count": count,
                    "count_known": count_known,
                    "count_label": count_label,
                    "count_status": "known" if count_known else "unknown",
                    "count_source": str(row.get("count_source") or ""),
                }
            )
        known_count = len([row for row in groups if row.get("count_known")])
        live_all_counts_known = bool(groups) and known_count == len(groups)
        GROUP_CACHE = normalize_group_count_payload({
            "loaded_at": time.time(),
            "groups": groups,
            "profile_count": snapshot.get("profile_count"),
            "group_count": snapshot.get("group_count"),
            "known_group_count": known_count,
            "all_group_counts_known": live_all_counts_known,
            "live_known_group_count": known_count,
            "live_all_group_counts_known": live_all_counts_known,
            "profiles_deferred": snapshot.get("profiles_deferred"),
            "counts_resolved": snapshot.get("counts_resolved"),
            "count_resolution_error": snapshot.get("count_resolution_error"),
            "error": str(snapshot.get("error") or ""),
            "error_detail": str(snapshot.get("error_detail") or ""),
            "stale_cache": False,
            "background_refresh": False,
        })
        write_latest_groups_payload(GROUP_CACHE)
        return GROUP_CACHE
    except Exception as exc:
        error, detail = normalize_group_refresh_error(str(exc))
        return cached_groups_payload_with_error(error, detail)


def validate_profile_group_for_start(profile_group: str) -> tuple[bool, dict]:
    group_payload = load_groups(refresh=True)
    groups = list(group_payload.get("groups") or [])
    error = str(group_payload.get("error") or "")
    if error or group_payload.get("stale_cache"):
        time.sleep(0.8)
        retry_payload = load_groups(refresh=True)
        retry_groups = list(retry_payload.get("groups") or [])
        retry_error = str(retry_payload.get("error") or "")
        if not retry_error and not retry_payload.get("stale_cache"):
            group_payload = retry_payload
            groups = retry_groups
            error = ""
        else:
            return False, {
                "status": "rejected",
                "error": "profile_group_live_refresh_required",
                "message": "启动前必须成功连接 ixBrowser Local API 并实时确认配置分组；当前仅有缓存或刷新失败，已拒绝启动。",
                "profile_group": profile_group,
                "group_error": retry_error or error,
                "stale_cache": bool(retry_payload.get("stale_cache", group_payload.get("stale_cache"))),
                "next_actions": ["确认 ixBrowser 客户端已启动且 Local API 可访问，然后重新点击“刷新分组”。"],
            }
    if not groups:
        return False, {
            "status": "rejected",
            "error": "profile_group_list_unavailable",
            "message": "启动前必须先读取到 ixBrowser 配置分组列表，不能用未验证分组执行采集。",
            "profile_group": profile_group,
            "group_error": error,
            "next_actions": ["确认 ixBrowser 本地服务已启动，然后在网页端点击“刷新分组”。"],
        }
    names = {str(row.get("name") or "").strip().lower(): row for row in groups}
    if profile_group.strip().lower() not in names:
        return False, {
            "status": "rejected",
            "error": "profile_group_not_found",
            "message": "选中的账号分组不在当前 ixBrowser 配置列表中，已拒绝启动。",
            "profile_group": profile_group,
            "available_groups": [str(row.get("name") or "") for row in groups],
            "next_actions": ["点击“刷新分组”后重新选择账号分组，再启动采集。"],
        }
    if group_payload.get("live_all_group_counts_known") is not True:
        return False, {
            "status": "rejected",
            "error": "profile_group_counts_incomplete",
            "message": "启动前必须通过 ixBrowser Local API 完整读取全部配置分组账号数量；当前分组数量不完整，已拒绝启动。",
            "profile_group": profile_group,
            "group_count": len(groups),
            "known_group_count": int(group_payload.get("live_known_group_count") or group_payload.get("known_group_count") or 0),
            "count_resolution_error": group_payload.get("count_resolution_error") or "",
            "next_actions": ["重新点击“刷新分组”，等待全部分组账号数量读取完成后再启动采集。"],
        }
    selected_group = names[profile_group.strip().lower()]
    if not selected_group.get("count_known"):
        return False, {
            "status": "rejected",
            "error": "profile_group_count_unknown",
            "message": "选中的账号分组账号数量未知，不能证明配置列表可用于本次采集，已拒绝启动。",
            "profile_group": profile_group,
            "group_id": selected_group.get("group_id") or "",
            "next_actions": ["重新刷新分组，确认该分组显示账号数量后再启动采集。"],
        }
    return True, {"group": selected_group}


def validate_account_repair_for_start(profile_group: str, account_repair_confirmed: bool) -> tuple[bool, dict]:
    try:
        from tools.reachops_client_delivery_check import build_delivery_check, write_delivery_check

        delivery = build_delivery_check(DATA_DIR)
        write_delivery_check(delivery)
    except Exception as exc:
        append_web_log(f"WARN   web_ui_account_gate_unavailable error={exc}")
        return True, {"status": "skipped", "error": str(exc)}

    ix_metadata = delivery.get("ixbrowser_metadata") if isinstance(delivery.get("ixbrowser_metadata"), dict) else {}
    selected_group_name = str(ix_metadata.get("selected_group_name") or ix_metadata.get("group_name_filter") or "").strip()
    same_group = not selected_group_name or selected_group_name.lower() == profile_group.strip().lower()
    status = str(delivery.get("status") or delivery.get("readiness") or "")
    profile_available = safe_int(delivery.get("profile_available"), 0)
    blockers = list(delivery.get("blockers") or [])
    next_actions = list(delivery.get("next_actions") or [])
    account_repair_apply = delivery.get("account_repair_apply") if isinstance(delivery.get("account_repair_apply"), dict) else {}
    remediation = delivery.get("remediation_report") if isinstance(delivery.get("remediation_report"), dict) else {}
    report_paths = {
        str((item or {}).get("name") or "").replace("report:", ""): str((item or {}).get("path") or "")
        for item in (delivery.get("checks") or [])
        if isinstance(item, dict) and str(item.get("name") or "").startswith("report:")
    }

    blocked = status == "blocked_by_accounts" and profile_available <= 0 and same_group
    if blocked and not account_repair_confirmed:
        plan_paths = [
            str(remediation.get("account_plan_markdown_path") or report_paths.get("account_plan_markdown_path") or ""),
            str(remediation.get("account_plan_json_path") or report_paths.get("account_plan_json_path") or ""),
            str(remediation.get("latest_account_plan_markdown_path") or report_paths.get("latest_account_plan_markdown_path") or ""),
            str(remediation.get("latest_account_plan_json_path") or report_paths.get("latest_account_plan_json_path") or ""),
        ]
        visible_paths = [path for path in plan_paths if path]
        account_repair_summary = summarize_account_repair_plan(plan_paths[3] or plan_paths[1])
        stale_repair = account_repair_apply.get("stale") is True
        append_web_log(
            f"WARN   web_ui_account_gate_blocked group={profile_group} "
            "policy=repair_required_before_start"
        )
        return False, {
            "status": "rejected",
            "error": "account_repair_required",
            "message": (
                "旧账号修复结果已失效；请先执行最新账号修复计划并重新预检。"
                if stale_repair
                else "当前分组最近一次预检没有可用账号；请先修复账号并重新预检。"
            ),
            "profile_group": profile_group,
            "profile_available": profile_available,
            "same_group": same_group,
            "force_account_recheck": False,
            "blockers": blockers,
            "next_actions": next_actions
            or [
                "在 ixBrowser 中修复该分组账号登录状态、内核版本和代理可用性。",
                "确认至少 1 个账号可正常打开 TikTok 后再次启动；程序会重新筛选可用账号。",
            ],
            "account_repair_apply": account_repair_apply,
            "account_repair_plan_paths": visible_paths,
            "account_plan_markdown_path": plan_paths[0],
            "account_plan_json_path": plan_paths[1],
            "latest_account_plan_markdown_path": plan_paths[2],
            "latest_account_plan_json_path": plan_paths[3],
            "account_repair_summary": account_repair_summary,
            "no_browser_started": True,
            "no_submit": True,
        }
    if blocked and account_repair_confirmed:
        append_web_log(
            f"WARN   web_ui_account_recheck_confirmed group={profile_group} "
            "policy=operator_confirmed_account_repair"
        )
    return True, {"status": status, "profile_available": profile_available, "same_group": same_group}


def run_is_active() -> bool:
    return RUN_PROCESS is not None and RUN_PROCESS.poll() is None


def _watchdog_should_log(signature: str, min_interval_seconds: int = 60) -> bool:
    now = time.time()
    if WATCHDOG_LAST_EVENT.get("signature") == signature and now - float(WATCHDOG_LAST_EVENT.get("logged_at") or 0) < min_interval_seconds:
        return False
    WATCHDOG_LAST_EVENT["signature"] = signature
    WATCHDOG_LAST_EVENT["logged_at"] = now
    return True


def mark_run_session_blocked_by_watchdog(reason: str, heartbeat_payload: dict | None = None) -> dict:
    session = read_current_run_session()
    if not session:
        return {"blocked": False, "reason": "missing_run_session"}
    if str(session.get("state") or "") in TERMINAL_RUN_SESSION_STATES:
        return {"blocked": False, "reason": "terminal_run_session", "state": str(session.get("state") or "")}
    heartbeat = heartbeat_payload if isinstance(heartbeat_payload, dict) else build_runtime_heartbeat_payload()
    result = {
        "status": "blocked",
        "error": reason,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "run_session": {"session_id": session.get("session_id", ""), "path": str(run_session_path_for(session))},
        "runtime_heartbeat": heartbeat,
        "no_ai_token_used": True,
    }
    updated = transition_run_session(
        session,
        "BLOCKED",
        pid=RUN_PROCESS.pid if RUN_PROCESS is not None else int(session.get("pid") or 0),
        last_stage=reason,
        checkpoint_update={
            "watchdog_reason": reason,
            "heartbeat_stale": bool((heartbeat or {}).get("stale")),
            "heartbeat_age_seconds": (heartbeat or {}).get("age_seconds"),
            "heartbeat_path": str(HEARTBEAT_PATH),
            "running": run_is_active(),
            "no_ai_token_used": True,
        },
        result=result,
        control={
            "watchdog": True,
            "last_action": "watchdog_blocked",
            "reason": reason,
            "ok": False,
            "paused": False,
        },
    )
    persist_run_session(updated)
    write_run_result_payload(result)
    finalize_stale_web_batch_if_needed(
        DATA_DIR / "data/growth_intelligence/growth_intelligence.db",
        force=True,
        reason=reason,
    )
    return {"blocked": True, "reason": reason, "run_session": updated}


def watchdog_tick() -> dict:
    running = run_is_active()
    if not running:
        recovery = recover_current_run_session_if_interrupted("WATCHDOG_PROCESS_INTERRUPTED")
        if recovery.get("recovered") and _watchdog_should_log("process_interrupted"):
            append_web_log("WARN   watchdog_recovered_interrupted_process reason=PROCESS_INTERRUPTED")
        return {"running": False, "recovery": recovery}

    heartbeat = build_runtime_heartbeat_payload()
    if heartbeat.get("stale"):
        age = heartbeat.get("age_seconds")
        signature = f"heartbeat_stale:{heartbeat.get('run_session_id') or '-'}"
        if _watchdog_should_log(signature):
            append_web_log(
                f"WARN   watchdog_heartbeat_stale age={age} threshold={HEARTBEAT_STALE_SECONDS} "
                f"session={heartbeat.get('run_session_id') or '-'}"
            )
        if age is not None and int(age) >= HEARTBEAT_STALE_SECONDS * 2:
            signal_run_process(TERM_SIGNAL)
            blocked = mark_run_session_blocked_by_watchdog("HEARTBEAT_STALE", heartbeat)
            append_web_log(
                f"BLOCK  watchdog_blocked_stale_run reason=HEARTBEAT_STALE age={age} "
                f"session={heartbeat.get('run_session_id') or '-'}"
            )
            return {"running": True, "heartbeat": heartbeat, "blocked": blocked}
    return {"running": True, "heartbeat": heartbeat}


def watchdog_loop() -> None:
    while not WATCHDOG_STOP_EVENT.wait(WATCHDOG_INTERVAL_SECONDS):
        try:
            watchdog_tick()
        except Exception as exc:
            if _watchdog_should_log(f"watchdog_error:{type(exc).__name__}", min_interval_seconds=120):
                append_web_log(f"WARN   watchdog_tick_failed error={exc}")


def start_watchdog_thread() -> None:
    global WATCHDOG_THREAD
    if WATCHDOG_THREAD is not None and WATCHDOG_THREAD.is_alive():
        return
    WATCHDOG_STOP_EVENT.clear()
    WATCHDOG_THREAD = threading.Thread(target=watchdog_loop, name="reachops-watchdog", daemon=True)
    WATCHDOG_THREAD.start()


def signal_run_process(sig: int | None):
    if RUN_PROCESS is None or RUN_PROCESS.poll() is not None:
        return False
    if sig is None:
        return False
    try:
        if hasattr(os, "killpg"):
            os.killpg(RUN_PROCESS.pid, sig)
        else:
            RUN_PROCESS.send_signal(sig)
        return True
    except OSError:
        return False


class Handler(BaseHTTPRequestHandler):
    def _read_json_payload(self) -> tuple[dict, str]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            return {}, "invalid_content_length"
        if length < 0:
            return {}, "invalid_content_length"
        if length > MAX_JSON_PAYLOAD_BYTES:
            return {}, "payload_too_large"
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            return {}, "invalid_json"
        if not isinstance(payload, dict):
            return {}, "json_object_required"
        return payload, ""

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_untrusted_api_request(self) -> bool:
        if not is_local_api_host(self.headers.get("Host", "")):
            self._send_json(
                {"status": "rejected", "error": "untrusted_host", "no_browser_started": True, "no_submit": True},
                403,
            )
            return True
        for header_name, error_code in (("Origin", "untrusted_origin"), ("Referer", "untrusted_referer")):
            header_value = self.headers.get(header_name, "")
            if header_value and not is_local_api_host(header_value):
                self._send_json(
                    {"status": "rejected", "error": error_code, "no_browser_started": True, "no_submit": True},
                    403,
                )
                return True
        return False

    def _send_file(self, path: Path):
        body = path.read_bytes()
        suffix = path.suffix.lower()
        if suffix == ".csv":
            content_type = "text/csv; charset=utf-8"
        elif suffix in {".png", ".jpg", ".jpeg"}:
            content_type = "image/png" if suffix == ".png" else "image/jpeg"
        elif suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        elif suffix == ".html":
            content_type = "text/html; charset=utf-8"
        else:
            content_type = "application/json; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def _send_acceptance_input_template(self):
        body = acceptance_input_template_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header('Content-Disposition', 'attachment; filename="reachops_acceptance_inputs.example.ps1"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global RUN_PAUSED
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and self._reject_untrusted_api_request():
            return
        if parsed.path == "/api/version":
            self._send_json(build_version_payload())
            return
        if parsed.path == "/api/heartbeat":
            self._send_json(build_runtime_heartbeat_payload())
            return
        if parsed.path == "/api/logs":
            running = run_is_active()
            if not running:
                RUN_PAUSED = False
            all_lines = read_lines(LOG_PATH)
            lines = all_lines[RUN_LOG_OFFSET:] if RUN_LOG_OFFSET and RUN_LOG_OFFSET <= len(all_lines) else all_lines[-80:]
            last_stage = ""
            for line in reversed(lines):
                if line.startswith(("CHECK ", "START ", "PLAN ", "BLOCK ", "DONE ", "FAST ")) or any(
                    marker in line for marker in (" CHECK ", " START ", " PLAN ", " BLOCK ", " DONE ", " FAST ")
                ):
                    last_stage = line[:240]
                    break
            run_result = read_run_result_payload()
            run_result_status = str(run_result.get("status") or "")
            exit_code = None if RUN_PROCESS is None else RUN_PROCESS.poll()
            run_session = read_current_run_session()
            recovery = {"recovered": False}
            if run_session:
                run_session, recovery = recover_interrupted_run_session(
                    run_session,
                    running=running,
                    run_result=run_result,
                    last_stage=last_stage,
                    pid=RUN_PROCESS.pid if RUN_PROCESS is not None else int(run_session.get("pid") or 0),
                )
                if recovery.get("recovered"):
                    persist_run_session(run_session)
                    run_result = recovery.get("result") or {}
                    run_result_status = str(run_result.get("status") or "")
                    write_run_result_payload(run_result)
                    append_web_log(
                        f"WARN   run_session_recovered_interrupted session={run_session.get('session_id')} reason=PROCESS_INTERRUPTED"
                    )
                    finalize_stale_web_batch_if_needed(
                        DATA_DIR / "data/growth_intelligence/growth_intelligence.db",
                        force=True,
                        reason="PROCESS_INTERRUPTED",
                    )
                else:
                    inferred_state = infer_run_state(lines, running, run_result)
                    session_state = str(run_session.get("state") or "")
                    if session_state in TERMINAL_RUN_SESSION_STATES:
                        pass
                    elif RUN_PAUSED and running:
                        run_session = transition_run_session(
                            run_session,
                            session_state or inferred_state,
                            pid=RUN_PROCESS.pid if RUN_PROCESS is not None else int(run_session.get("pid") or 0),
                            last_stage=last_stage,
                            control={"paused": True},
                        )
                        persist_run_session(run_session)
                    elif inferred_state != session_state or last_stage:
                        run_session = transition_run_session(
                            run_session,
                            inferred_state,
                            pid=RUN_PROCESS.pid if RUN_PROCESS is not None else int(run_session.get("pid") or 0),
                            last_stage=last_stage,
                            result=run_result if run_result_status else None,
                            control={"paused": False},
                        )
                        persist_run_session(run_session)
            evidence_bundle = build_current_evidence_bundle() if (run_result_status or run_session) else {}
            runtime_heartbeat = build_runtime_heartbeat_payload()
            self._send_json(
                {
                    "running": running,
                    "paused": bool(RUN_PAUSED and running),
                    "started_at": RUN_STARTED_AT,
                    "elapsed_seconds": int(time.time() - RUN_STARTED_AT) if RUN_STARTED_AT and running else 0,
                    "last_stage": last_stage,
                    "exit_code": exit_code,
                    "run_result": run_result,
                    "run_result_status": run_result_status,
                    "run_session": run_session,
                    "run_session_state": str((run_session or {}).get("state") or ""),
                    "runtime_heartbeat": runtime_heartbeat,
                    "recovery": recovery,
                    "evidence_bundle": evidence_bundle,
                    "run_failed": bool(
                        (exit_code not in (None, 0))
                        or run_result_status in FAILED_RUN_RESULT_STATUSES
                        or (run_result_status and run_result_status != "completed")
                    ),
                    "lines": lines[-180:],
                }
            )
            return
        if parsed.path == "/api/snapshot":
            self._send_json(build_snapshot_payload())
            return
        if parsed.path == "/api/execution-plan":
            self._send_json(build_current_execution_plan_payload())
            return
        if parsed.path == "/api/execution-plan-contract-preview":
            params = parse_qs(parsed.query)
            self._send_json(build_execution_plan_contract_preview((params.get("path") or [""])[0] or None))
            return
        if parsed.path == "/api/start-from-plan-preview":
            params = parse_qs(parsed.query)
            self._send_json(build_start_from_plan_preview((params.get("path") or [""])[0] or None))
            return
        if parsed.path == "/api/run-session":
            self._send_json(build_current_run_session_payload())
            return
        if parsed.path == "/api/evidence-bundle":
            self._send_json(build_current_evidence_bundle())
            return
        if parsed.path == "/api/operator-summary":
            self._send_json(build_operator_summary_payload())
            return
        if parsed.path == "/api/product-capability":
            self._send_json(build_product_capability_payload())
            return
        if parsed.path == "/api/offline-learning":
            self._send_json(build_offline_learning_payload())
            return
        if parsed.path == "/api/acceptance":
            self._send_json(build_acceptance_payload())
            return
        if parsed.path == "/api/activation":
            self._send_json(build_activation_payload())
            return
        if parsed.path == "/api/ixbrowser-status":
            self._send_json(build_ixbrowser_status_payload())
            return
        if parsed.path == "/api/final-status":
            self._send_json(build_final_status_payload())
            return
        if parsed.path == "/api/acceptance-input-template":
            try:
                self._send_acceptance_input_template()
            except Exception as exc:
                append_web_log(f"ERROR  web_ui_acceptance_template_failed error={exc}")
                self._send_json({"status": "failed", "error": "template_download_failed", "message": str(exc)}, 500)
            return
        if parsed.path == "/api/download":
            params = parse_qs(parsed.query)
            path = safe_report_download_path((params.get("path") or [""])[0])
            if not path:
                self._send_json({"error": "not_found"}, 404)
                return
            try:
                self._send_file(path)
            except Exception as exc:
                append_web_log(f"ERROR  web_ui_download_failed path={path} error={exc}")
                self._send_json({"status": "failed", "error": "download_failed", "message": str(exc)}, 500)
            return
        if parsed.path == "/api/groups":
            refresh = "refresh=1" in parsed.query
            payload = load_groups(refresh=refresh, allow_async="background=1" in parsed.query)
            append_group_refresh_log(payload, refresh=refresh)
            self._send_json(payload)
            return
        if parsed.path.startswith("/api/"):
            self._send_json({"status": "rejected", "error": "unknown_api"}, 404)
            return
        body = html_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global RUN_PROCESS, RUN_STARTED_AT, RUN_LOG_OFFSET, RUN_PAUSED, CURRENT_RUN_SESSION_PATH
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and self._reject_untrusted_api_request():
            return
        if parsed.path == "/api/start-preview":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            self._send_json(build_start_preview(payload))
            return
        if parsed.path == "/api/ai-console":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            result = build_ai_console_payload(payload)
            append_web_log(
                f"CHECK  local_ai_console intent={result.get('intent') or '-'} "
                f"plan_id={result.get('execution_plan_id') or '-'} no_ai_token_used=true"
            )
            self._send_json(result)
            return
        if parsed.path == "/api/acceptance-input-init":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            self._send_json(init_acceptance_input_file())
            return
        if parsed.path == "/api/mvp-acceptance-refresh":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            try:
                from tools.reachops_mvp_acceptance_summary import OUT_PATH, build_summary

                summary = build_summary()
                OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                append_web_log(
                    f"CHECK  mvp_acceptance_refresh status={summary.get('status')} mvp_local_ready={str(bool(summary.get('mvp_local_ready'))).lower()}"
                )
                self._send_json(summary)
            except Exception as exc:
                append_web_log(f"ERROR  mvp_acceptance_refresh_failed error={exc}")
                self._send_json({"status": "failed", "error": "mvp_acceptance_refresh_failed", "message": str(exc)}, 500)
            return
        if parsed.path == "/api/goal-delivery-refresh":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            try:
                from tools.reachops_goal_delivery_runner import build_report, render_markdown_summary
                from tools.reachops_two_phase_acceptance_matrix import build_matrix, render_markdown

                report = build_report()
                report.setdefault("execution_contract", {})["authoritative_report"] = str(GOAL_DELIVERY_REPORT_PATH)
                report.setdefault("execution_contract", {})["operator_summary"] = str(GOAL_DELIVERY_SUMMARY_PATH)
                report.setdefault("evidence_files", {})["goal_delivery_report"] = str(GOAL_DELIVERY_REPORT_PATH)
                report.setdefault("evidence_files", {})["goal_delivery_summary"] = str(GOAL_DELIVERY_SUMMARY_PATH)
                GOAL_DELIVERY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                GOAL_DELIVERY_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                GOAL_DELIVERY_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
                GOAL_DELIVERY_SUMMARY_PATH.write_text(render_markdown_summary(report), encoding="utf-8")
                matrix = build_matrix(report)
                TWO_PHASE_MATRIX_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
                TWO_PHASE_MATRIX_JSON_PATH.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
                TWO_PHASE_MATRIX_MD_PATH.write_text(render_markdown(matrix), encoding="utf-8")
                append_web_log(
                    f"CHECK  goal_delivery_refresh status={report.get('status')} local_mvp_ready={str(bool(report.get('local_mvp_ready'))).lower()} windows_build_ready={str(bool(report.get('windows_build_ready'))).lower()} final_delivery_ready={str(bool(report.get('final_delivery_ready'))).lower()} two_phase={matrix.get('status')}"
                )
                self._send_json(report)
            except Exception as exc:
                append_web_log(f"ERROR  goal_delivery_refresh_failed error={exc}")
                self._send_json({"status": "failed", "error": "goal_delivery_refresh_failed", "message": str(exc)}, 500)
            return
        if parsed.path == "/api/ixbrowser-config":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            result = apply_ixbrowser_api_port((payload or {}).get("port"))
            self._send_json(result, 200 if result.get("status") == "saved" else 400)
            return
        if parsed.path == "/api/account-repair-apply":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            if not truthy((payload or {}).get("confirm")):
                self._send_json(
                    {
                        "status": "rejected",
                        "ok": False,
                        "error": "confirmation_required",
                        "message": "执行账号修复计划需要 confirm=true。",
                    },
                    400,
                )
                return
            result = apply_latest_account_repair_plan_from_web(str((payload or {}).get("group") or ""))
            self._send_json(result, 200 if result.get("status") == "applied" else 409)
            return
        if parsed.path == "/api/control":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            action = str(payload.get("action") or "").lower()
            with RUN_STATE_LOCK:
                if not run_is_active():
                    RUN_PAUSED = False
                    self._send_json({"status": "not_running"})
                    return
                if action == "pause":
                    if PAUSE_SIGNAL is None:
                        RUN_PAUSED = True
                        write_cooperative_control(
                            "pause.request",
                            {
                                "schema_version": "reachops.cooperative_control.v1",
                                "action": "pause",
                                "pid": RUN_PROCESS.pid,
                                "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                                "no_ai_token_used": True,
                            },
                        )
                        session = update_current_run_session(
                            str((read_current_run_session() or {}).get("state") or "PRECHECK"),
                            pid=RUN_PROCESS.pid,
                            control={
                                "paused": True,
                                "last_action": "pause",
                                "status": "paused",
                                "ok": True,
                                "reason": "WEB_UI_COOPERATIVE_PAUSE_REQUESTED",
                                "cooperative_control": True,
                            },
                        )
                        self._send_json({"status": "paused", "pid": RUN_PROCESS.pid, "run_session": session, "cooperative_control": True})
                        return
                    ok = signal_run_process(PAUSE_SIGNAL)
                    RUN_PAUSED = bool(ok)
                    session = update_current_run_session(
                        str((read_current_run_session() or {}).get("state") or "PRECHECK"),
                        pid=RUN_PROCESS.pid,
                        control={
                            "paused": bool(ok),
                            "last_action": "pause",
                            "status": "paused" if ok else "failed",
                            "ok": bool(ok),
                            "reason": "WEB_UI_PAUSE_REQUESTED",
                        },
                    )
                    self._send_json(
                        {"status": "paused" if ok else "failed", "pid": RUN_PROCESS.pid, "run_session": session}
                    )
                    return
                if action == "resume":
                    if RESUME_SIGNAL is None:
                        RUN_PAUSED = False
                        try:
                            pause_path = cooperative_control_path("pause.request")
                            if pause_path.exists():
                                pause_path.unlink()
                        except Exception as exc:
                            append_web_log(f"WARN   web_ui_control_file_resume_cleanup_failed error={exc}")
                        write_cooperative_control(
                            "resume.request",
                            {
                                "schema_version": "reachops.cooperative_control.v1",
                                "action": "resume",
                                "pid": RUN_PROCESS.pid,
                                "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                                "no_ai_token_used": True,
                            },
                        )
                        session = update_current_run_session(
                            str((read_current_run_session() or {}).get("state") or "PRECHECK"),
                            pid=RUN_PROCESS.pid,
                            control={
                                "paused": False,
                                "last_action": "resume",
                                "status": "running",
                                "ok": True,
                                "reason": "WEB_UI_COOPERATIVE_RESUME_REQUESTED",
                                "cooperative_control": True,
                            },
                        )
                        self._send_json({"status": "running", "pid": RUN_PROCESS.pid, "run_session": session, "cooperative_control": True})
                        return
                    ok = signal_run_process(RESUME_SIGNAL)
                    if ok:
                        RUN_PAUSED = False
                    session = update_current_run_session(
                        str((read_current_run_session() or {}).get("state") or "PRECHECK"),
                        pid=RUN_PROCESS.pid,
                        control={
                            "paused": False,
                            "last_action": "resume",
                            "status": "running" if ok else "failed",
                            "ok": bool(ok),
                            "reason": "WEB_UI_RESUME_REQUESTED",
                        },
                    )
                    self._send_json(
                        {"status": "running" if ok else "failed", "pid": RUN_PROCESS.pid, "run_session": session}
                    )
                    return
                if action == "stop":
                    pid = RUN_PROCESS.pid
                    ok = signal_run_process(TERM_SIGNAL)
                    RUN_PAUSED = False
                    if not ok and RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                        append_web_log(f"WARN   web_ui_stop_signal_failed pid={pid}")
                        self._send_json({"status": "failed", "pid": pid, "running": True})
                        return
                    time.sleep(0.5)
                    if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                        if KILL_SIGNAL is not None:
                            signal_run_process(KILL_SIGNAL)
                        elif hasattr(RUN_PROCESS, "kill"):
                            try:
                                RUN_PROCESS.kill()
                            except Exception:
                                pass
                    if RUN_PROCESS is not None:
                        try:
                            RUN_PROCESS.wait(timeout=2)
                        except Exception:
                            pass
                    if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                        append_web_log(f"WARN   web_ui_stop_process_still_running pid={pid}")
                        self._send_json({"status": "failed", "pid": pid, "running": True})
                        return
                    append_web_log(f"WARN   web_ui_stop_requested pid={pid} result={str(ok).lower()}")
                    RUN_PROCESS = None
                    session = update_current_run_session(
                        "BLOCKED",
                        pid=pid,
                        control={
                            "paused": False,
                            "last_action": "stop",
                            "status": "stopped" if ok else "failed",
                            "ok": bool(ok),
                            "reason": "WEB_UI_STOP_REQUESTED",
                        },
                        result={"status": "stopped", "reason": "WEB_UI_STOP_REQUESTED"},
                    )
                    finalize_stale_web_batch_if_needed(
                        DATA_DIR / "data/growth_intelligence/growth_intelligence.db",
                        force=True,
                        reason="WEB_UI_STOP_REQUESTED",
                    )
                    self._send_json({"status": "stopped" if ok else "failed", "pid": pid, "run_session": session})
                    return
                self._send_json({"status": "rejected", "error": "unknown_action"}, 400)
            return
        if parsed.path == "/api/client-event":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            event = str(payload.get("event") or "client_event").strip()[:80]
            reason = str(payload.get("reason") or "").strip()[:160]
            mode = str(payload.get("mode") or "").strip()[:80]
            group = str(payload.get("group") or "").strip()[:120]
            target_present = bool(str(payload.get("target") or "").strip())
            append_web_log(
                f"WARN   web_ui_client_event event={event or 'client_event'} reason={reason or '-'} "
                f"mode={mode or '-'} group={group or '-'} target_present={str(target_present).lower()}"
            )
            self._send_json({"status": "logged"})
            return
        if parsed.path == "/api/offline-learning/review":
            payload, error = self._read_json_payload()
            if error:
                self._send_json({"status": "rejected", "error": error}, 400)
                return
            result = review_offline_policy_candidate(payload)
            status_code = 200 if result.get("status") == "review_recorded" else 400
            self._send_json(result, status_code)
            return
        start_from_plan = parsed.path == "/api/start-from-plan"
        if parsed.path not in {"/api/start", "/api/start-from-plan"}:
            self._send_json({"status": "rejected", "error": "unknown_api"}, 404)
            return
        payload, error = self._read_json_payload()
        if error:
            self._send_json({"status": "rejected", "error": error, "no_browser_started": True, "no_submit": True}, 400)
            return
        replay_execution_plan: dict = {}
        replay_source_path = ""
        if start_from_plan:
            replay_source_path = str((payload or {}).get("execution_plan_path") or LATEST_EXECUTION_PLAN_PATH)
            try:
                replay_execution_plan = read_execution_plan(replay_source_path)
                payload = payload_from_execution_plan(replay_execution_plan)
            except Exception as exc:
                append_web_log(f"WARN   web_ui_start_from_plan_rejected error=execution_plan_unavailable path={replay_source_path} detail={exc}")
                self._send_json(
                    {
                        "status": "rejected",
                        "error": "execution_plan_unavailable",
                        "message": str(exc),
                        "execution_plan_path": replay_source_path,
                        "no_browser_started": True,
                        "no_submit": True,
                    },
                    400,
                )
                return
        target = str(payload.get("target") or "").strip()
        if not target:
            append_web_log("WARN   web_ui_start_rejected error=target_required target_present=false")
            self._send_json(
                {
                    "status": "rejected",
                    "error": "target_required",
                    "message": "请输入产品链接、关键词、达人主页、视频链接、话题或直播间后再开始获客。",
                    "no_browser_started": True,
                    "no_submit": True,
                },
                400,
            )
            return
        volume = normalize_volume(str(payload.get("volume") or "quick"))
        mode = normalize_mode(str(payload.get("mode") or "preflight"))
        if mode == "live_comment" and not truthy(payload.get("live_confirm", payload.get("liveConfirm"))):
            append_web_log("WARN   web_ui_start_rejected error=live_comment_confirmation_required mode=live_comment")
            self._send_json(
                {
                    "status": "rejected",
                    "error": "live_comment_confirmation_required",
                    "message": "选择采集 + 真实评论前必须勾选确认真实评论。",
                    "no_browser_started": True,
                    "no_submit": True,
                },
                400,
            )
            return
        if mode == "live_comment":
            activation = live_comment_activation_status()
            if not activation.get("allowed"):
                append_web_log(
                    f"WARN   web_ui_start_rejected error={activation.get('error_code') or 'LIVE_SUBMIT_NOT_AUTHORIZED'} mode=live_comment"
                )
                self._send_json(
                    {
                        "status": "rejected",
                        "error": activation.get("error_code") or "LIVE_SUBMIT_NOT_AUTHORIZED",
                        "message": activation.get("error_message") or "真实评论需要有效激活状态。",
                        "activation_status_path": activation.get("activation_status_path"),
                        "failed_checks": activation.get("failed_checks") or [],
                        "next_actions": activation.get("next_actions")
                        or ["生成或放置真实激活状态文件，并设置 ActivationStatusPath。"],
                        "no_browser_started": True,
                        "no_submit": True,
                    },
                    403,
                )
                return
        profile_limit = normalize_profile_limit(payload.get("profiles"))
        max_videos, max_comments = volume_limits(volume)
        source_type = str(payload.get("source_type") or payload.get("sourceType") or "auto")
        profile_group = str(payload.get("group") or "United States")
        comment_text = str(payload.get("comment_text") or payload.get("commentText") or "")
        account_repair_confirmed = truthy(
            payload.get("account_repair_confirmed", payload.get("accountRepairConfirmed"))
        )
        append_web_log(
            f"START  web_ui_start_request target_present=true source_type={source_type} group={profile_group} "
            f"mode={mode} volume={volume} profiles={profile_limit} "
            f"comment_text_present={str(bool(comment_text.strip())).lower()} "
            f"account_repair_confirmed={str(account_repair_confirmed).lower()}"
        )
        with RUN_STATE_LOCK:
            if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                self._send_json({"status": "already_running", "pid": RUN_PROCESS.pid})
                return
        recover_current_run_session_if_interrupted("before_start")
        group_ok, group_check = validate_profile_group_for_start(profile_group)
        if not group_ok:
            append_web_log(
                f"WARN   web_ui_start_rejected_profile_group error={group_check.get('error')} group={profile_group}"
            )
            try:
                blocked_payload = persist_precheck_blocked_start(
                    target=target,
                    source_type=source_type,
                    mode=mode,
                    profile_group=profile_group,
                    volume=volume,
                    profile_limit=profile_limit,
                    max_videos=max_videos,
                    max_comments=max_comments,
                    timeout_seconds=headless_timeout_seconds(volume, profile_limit, max_videos, max_comments),
                    comment_text=comment_text,
                    live_confirmed=truthy(payload.get("live_confirm", payload.get("liveConfirm"))),
                    account_repair_confirmed=account_repair_confirmed,
                    block=group_check,
                )
            except Exception as exc:
                blocked_payload = {**group_check, "archive_error": str(exc), "no_browser_started": True, "no_submit": True}
            self._send_json(blocked_payload, 409 if group_check.get("error") == "profile_group_list_unavailable" else 400)
            return
        account_ok, account_check = validate_account_repair_for_start(profile_group, account_repair_confirmed)
        if not account_ok:
            append_web_log(
                f"WARN   web_ui_start_rejected_account_gate error={account_check.get('error')} group={profile_group}"
            )
            self._send_json(account_check, 409)
            return
        force_account_recheck = truthy(account_check.get("force_account_recheck")) or (
            account_repair_confirmed
            and account_check.get("same_group") is True
            and str(account_check.get("status") or "") == "blocked_by_accounts"
            and safe_int(account_check.get("profile_available"), 0) <= 0
        )
        with RUN_STATE_LOCK:
            if RUN_PROCESS is not None and RUN_PROCESS.poll() is None:
                self._send_json({"status": "already_running", "pid": RUN_PROCESS.pid})
                return
            RUN_PAUSED = False
            RUN_LOG_OFFSET = len(read_lines(LOG_PATH))
            timeout_seconds = headless_timeout_seconds(volume, profile_limit, max_videos, max_comments)
            execution_plan = dict(replay_execution_plan) if replay_execution_plan else build_execution_plan(
                target=target,
                source_type=source_type,
                mode=mode,
                profile_group=profile_group,
                volume=volume,
                profile_limit=profile_limit,
                max_videos=max_videos,
                max_comments=max_comments,
                timeout_seconds=timeout_seconds,
                comment_text=comment_text,
                live_confirmed=truthy(payload.get("live_confirm", payload.get("liveConfirm"))),
                account_repair_confirmed=account_repair_confirmed,
                force_account_recheck=force_account_recheck,
                base_dir=str(DATA_DIR),
                origin="web_ui_start",
            )
            if not replay_execution_plan:
                preflight_decision = build_start_preflight_decision_for_plan(
                    execution_plan,
                    start_allowed=True,
                    gate_state="可启动",
                    blockers=[],
                    next_actions=["可以启动本地执行。"],
                    no_submit=mode != "live_comment",
                )
                execution_plan = attach_autonomous_preflight_forecast(
                    execution_plan,
                    preflight_decision=preflight_decision,
                )
            plan_id = str(execution_plan.get("plan_id") or "")
            plan_path = DATA_DIR / "plans" / f"{plan_id or 'execution_plan'}.json"
            try:
                write_execution_plan(execution_plan, plan_path)
                write_execution_plan(execution_plan, LATEST_EXECUTION_PLAN_PATH)
            except Exception as exc:
                RUN_PROCESS = None
                RUN_PAUSED = False
                append_web_log(f"ERROR  web_ui_execution_plan_write_failed plan_id={plan_id} error={exc}")
                self._send_json(
                    {
                        "status": "failed",
                        "error": "execution_plan_write_failed",
                        "message": str(exc),
                        "no_browser_started": True,
                        "no_submit": True,
                    },
                    500,
                )
                return
            run_session = create_run_session(
                execution_plan,
                execution_plan_path=str(plan_path),
                result_path=str(RESULT_PATH),
                log_path=str(LOG_PATH),
                log_offset=RUN_LOG_OFFSET,
            )
            run_session_path = run_session_path_for(run_session)
            try:
                persist_run_session(run_session)
                run_session = persist_run_session(
                    transition_run_session(
                        run_session,
                        "PRECHECK",
                        evidence={"execution_plan_path": str(plan_path), "run_session_path": str(run_session_path)},
                    )
                )
            except Exception as exc:
                RUN_PROCESS = None
                RUN_PAUSED = False
                append_web_log(f"ERROR  web_ui_run_session_write_failed plan_id={plan_id} error={exc}")
                self._send_json(
                    {
                        "status": "failed",
                        "error": "run_session_write_failed",
                        "message": str(exc),
                        "no_browser_started": True,
                        "no_submit": True,
                    },
                    500,
                )
                return
            cmd = [
                sys.executable,
                str(ROOT_DIR / "tools/run_reachops_headless_macos.py"),
                "--base-dir",
                str(DATA_DIR),
                "--control-dir",
                str(CONTROL_DIR),
                "--execution-plan",
                str(plan_path),
                "--run-session",
                str(run_session_path),
                "--target",
                target,
                "--source-type",
                source_type,
                "--profile-group",
                profile_group,
                "--profile-limit",
                str(profile_limit),
                "--max-videos",
                str(max_videos),
                "--max-comments",
                str(max_comments),
                "--mode",
                mode,
                "--volume",
                volume,
                "--comment-text",
                comment_text,
                "--timeout",
                str(timeout_seconds),
                "--json",
            ]
            try:
                RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
                out = RESULT_PATH.open("w", encoding="utf-8")
            except Exception as exc:
                RUN_PROCESS = None
                RUN_PAUSED = False
                append_web_log(f"ERROR  web_ui_result_file_open_failed path={RESULT_PATH} error={exc}")
                self._send_json({"status": "failed", "error": "result_file_open_failed", "message": str(exc)}, 500)
                return
            env = os.environ.copy()
            env["TK_SILENCE_DEPRECATION"] = "1"
            env["NO_PROXY"] = ",".join([item for item in [env.get("NO_PROXY", ""), "127.0.0.1", "localhost", "::1"] if item])
            env["no_proxy"] = env["NO_PROXY"]
            if force_account_recheck:
                env["REACHOPS_FORCE_ACCOUNT_RECHECK"] = "1"
            try:
                clear_cooperative_control()
                process = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=hasattr(os, "setsid"),
                )
            except Exception as exc:
                RUN_PROCESS = None
                RUN_PAUSED = False
                try:
                    out.close()
                except Exception:
                    pass
                write_run_result_payload(
                    {
                        "status": "launch_failed",
                        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "error": "launch_failed",
                        "message": str(exc),
                        "target": target,
                        "source_type": source_type,
                        "profile_group": profile_group,
                        "mode": mode,
                        "volume": volume,
                        "execution_plan_id": plan_id,
                        "execution_plan_path": str(plan_path),
                    }
                )
                persist_run_session(
                    transition_run_session(
                        run_session,
                        "BLOCKED",
                        result={"status": "launch_failed", "message": str(exc)},
                        evidence={"execution_plan_path": str(plan_path), "run_session_path": str(run_session_path)},
                    )
                )
                append_web_log(f"ERROR  web_ui_launch_failed error={exc}")
                self._send_json({"status": "failed", "error": "launch_failed", "message": str(exc)}, 500)
                return
            finally:
                out.close()
            time.sleep(STARTUP_HEALTHCHECK_SECONDS)
            early_exit = process.poll()
            if early_exit is not None:
                RUN_PROCESS = None
                RUN_STARTED_AT = 0.0
                RUN_PAUSED = False
                output_tail = read_text_tail(RESULT_PATH)
                write_run_result_payload(
                    {
                        "status": "headless_exited_immediately",
                        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "error": "headless_exited_immediately",
                        "exit_code": early_exit,
                        "message": "本地执行器启动后立即退出，未进入真实获客执行。",
                        "target": target,
                        "source_type": source_type,
                        "profile_group": profile_group,
                        "mode": mode,
                        "volume": volume,
                        "execution_plan_id": plan_id,
                        "execution_plan_path": str(plan_path),
                        "output_tail": output_tail,
                    }
                )
                persist_run_session(
                    transition_run_session(
                        run_session,
                        "BLOCKED",
                        pid=process.pid,
                        result={
                            "status": "headless_exited_immediately",
                            "exit_code": early_exit,
                            "output_tail": output_tail,
                        },
                        evidence={"execution_plan_path": str(plan_path), "run_session_path": str(run_session_path)},
                    )
                )
                append_web_log(
                    f"ERROR  web_ui_headless_exited_immediately pid={process.pid} exit_code={early_exit}"
                )
                self._send_json(
                    {
                        "status": "failed",
                        "error": "headless_exited_immediately",
                        "exit_code": early_exit,
                        "message": "本地执行器启动后立即退出，未进入真实获客执行。",
                        "output_tail": output_tail,
                    },
                    500,
                )
                return
            RUN_PROCESS = process
            RUN_STARTED_AT = time.time()
            current_run_session = read_run_session(run_session_path) or run_session
            current_state = str(current_run_session.get("state") or "CREATED")
            next_state = (
                current_state
                if RUN_SESSION_STATE_RANK.get(current_state, 0) > RUN_SESSION_STATE_RANK.get("PRECHECK", 0)
                else "PRECHECK"
            )
            run_session = persist_run_session(
                transition_run_session(
                    current_run_session,
                    next_state,
                    pid=RUN_PROCESS.pid,
                    evidence={"execution_plan_path": str(plan_path), "run_session_path": str(run_session_path)},
                )
            )
            self._send_json(
                {
                    "status": "started",
                    "pid": RUN_PROCESS.pid,
                    "mode": mode_label(mode),
                    "timeout_seconds": timeout_seconds,
                    "volume": volume,
                    "max_videos": max_videos,
                    "max_comments": max_comments,
                    "profile_limit": profile_limit,
                    "execution_plan_id": plan_id,
                    "execution_plan_path": str(plan_path),
                    "execution_plan_replay": bool(replay_execution_plan),
                    "execution_plan_replay_source_path": replay_source_path,
                    "run_session_id": run_session.get("session_id"),
                    "run_session_path": str(run_session_path),
                    "run_session": run_session,
                }
            )

    def log_message(self, *_args):
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the ReachOps unified local Web UI.")
    parser.add_argument("--web", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", default=os.environ.get("REACHOPS_WEB_HOST") or "127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("REACHOPS_WEB_PORT") or os.environ.get("REACHOPS_MAC_WEB_PORT") or "8769"),
    )
    parser.add_argument("--no-browser", action="store_true")
    args, _unknown = parser.parse_known_args()
    try:
        host = normalize_local_bind_host(args.host)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 2
    port = int(args.port)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    initialize_ixbrowser_api_port_from_settings()
    start_watchdog_thread()
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{format_url_host(host)}:{port}/"
    print(f"ReachOps Web UI: {url}", flush=True)
    if not args.no_browser and os.environ.get("REACHOPS_WEB_NO_BROWSER") != "1":
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
