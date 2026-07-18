# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools import reachops_web_ui
from tools import reachops_mvp_acceptance_summary
from tools import reachops_goal_delivery_runner
from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.workbench.offline_learning_ledger import OfflineLearningLedger
from ReachOps.workbench.risk_gate import RiskGate

LATEST_RESULT_PATH = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation/latest_web_panel_runtime_smoke.json"


def source_mtimes() -> dict[str, float]:
    paths = {
        "web_ui": ROOT_DIR / "tools" / "reachops_web_ui.py",
        "runtime_smoke": ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py",
    }
    return {name: path.stat().st_mtime for name, path in paths.items() if path.exists()}


def temporary_directory_ignoring_cleanup_errors(prefix: str):
    try:
        return tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True)
    except TypeError:
        return tempfile.TemporaryDirectory(prefix=prefix)


def write_latest_result(result: dict):
    LATEST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["source_mtimes"] = source_mtimes()
    payload["recorded_at"] = time.time()
    if not payload.get("passed") and LATEST_RESULT_PATH.exists():
        try:
            existing = json.loads(LATEST_RESULT_PATH.read_text(encoding="utf-8"))
            existing_mtimes = existing.get("source_mtimes") if isinstance(existing.get("source_mtimes"), dict) else {}
            current_mtimes = payload["source_mtimes"]
            existing_is_current = all(
                abs(float(existing_mtimes.get(key) or 0) - float(value or 0)) < 0.001
                for key, value in current_mtimes.items()
            )
            if existing.get("passed") and existing_is_current:
                return
        except Exception:
            pass
    LATEST_RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class FakeProcess:
    pid = 54321

    def __init__(self):
        self.alive = True
        self.signals: list[int] = []
        self.signal_sink = None

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        self.alive = False
        return 0

    def send_signal(self, sig):
        self.signals.append(sig)
        if isinstance(self.signal_sink, list):
            self.signal_sink.append(sig)
        if sig in {getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)}:
            self.alive = False
        return None


def _json_request(url: str, payload: dict | None = None, *, headers: dict | None = None, expect_error: int | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if payload is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        if expect_error is not None and exc.code == expect_error:
            return exc.code, json.loads(body)
        raise


def _html_request(url: str) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _raw_request(url: str) -> tuple[int, bytes, dict[str, str]]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return response.status, response.read(), dict(response.headers.items())


def seed_snapshot_risk_gate_execution(data_dir: Path) -> dict:
    db_path = data_dir / "data/growth_intelligence/growth_intelligence.db"
    storage = GrowthStorage(str(db_path))
    batch = storage.create_collection_batch(
        1,
        profile_group="Canada",
        config={"mode": "live_comment", "quick_send": {"mode": "live_comment"}},
        initial_status="running",
    )
    storage.set_active_collection_batch(batch.id)
    gate = RiskGate().evaluate(
        {"id": "aq_runtime_risk_1", "action_type": "comment_reply", "status": "approved", "execution_confirmed": 1},
        {"profile_id": "profile-risk-1", "group_name": "Canada"},
        live_submit=True,
        duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT", "message": "same rendered text already used"},
    )
    now = "2026-07-05T00:00:00Z"
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO operation_leads
            (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage, source_path, status, batch_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ol_runtime_risk_1",
                "cu_runtime_risk_1",
                "purchase",
                "high",
                88,
                "runtime smoke risk gate lead",
                "ready_to_execute",
                "https://www.tiktok.com/@demo/video/1",
                "ready_to_execute",
                batch.id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO action_queue
            (id, lead_id, action_type, target_username, target_url, suggested_text, reason, status, risk_level, batch_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "aq_runtime_risk_1",
                "ol_runtime_risk_1",
                "comment_reply",
                "target_runtime_risk",
                "https://www.tiktok.com/@target/video/1",
                "Please check the current product page.",
                "runtime smoke duplicate text gate",
                "approved",
                "medium",
                batch.id,
                now,
            ),
        )
    execution_id = storage.create_outreach_execution(
        "aq_runtime_risk_1",
        "comment_reply",
        "target_runtime_risk",
        status="skipped",
        profile_id="profile-risk-1",
        error_code="DUPLICATE_ACTION_TEXT",
        error_message="same rendered text already used",
        risk_gate=gate,
    )
    return {"batch_id": batch.id, "execution_id": execution_id, "risk_gate": gate}


def run_runtime_smoke() -> dict:
    old_data_dir = reachops_web_ui.DATA_DIR
    old_log_path = reachops_web_ui.LOG_PATH
    old_result_path = reachops_web_ui.RESULT_PATH
    old_latest_execution_plan_path = reachops_web_ui.LATEST_EXECUTION_PLAN_PATH
    old_latest_run_session_path = reachops_web_ui.LATEST_RUN_SESSION_PATH
    old_latest_evidence_bundle_path = reachops_web_ui.LATEST_EVIDENCE_BUNDLE_PATH
    old_latest_evidence_bundle_md_path = reachops_web_ui.LATEST_EVIDENCE_BUNDLE_MD_PATH
    old_current_run_session_path = reachops_web_ui.CURRENT_RUN_SESSION_PATH
    old_process = reachops_web_ui.RUN_PROCESS
    old_paused = reachops_web_ui.RUN_PAUSED
    old_started_at = reachops_web_ui.RUN_STARTED_AT
    old_popen = reachops_web_ui.subprocess.Popen
    old_killpg = getattr(reachops_web_ui.os, "killpg", None)
    old_final_status = reachops_web_ui.build_final_status_payload
    old_ixbrowser_status = reachops_web_ui.build_ixbrowser_status_payload
    old_ixbrowser_override = reachops_web_ui.IXBROWSER_API_PORT_OVERRIDE
    old_ixbrowser_env = reachops_web_ui.os.environ.get("REACHOPS_IXBROWSER_API_PORT")
    old_require_activation_env = reachops_web_ui.os.environ.get("REACHOPS_REQUIRE_ACTIVATION")
    old_web_settings_path = reachops_web_ui.WEB_SETTINGS_PATH
    old_web_mvp_path = reachops_web_ui.MVP_ACCEPTANCE_SUMMARY_PATH
    old_web_goal_path = reachops_web_ui.GOAL_DELIVERY_REPORT_PATH
    old_web_goal_summary_path = reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH
    old_web_two_phase_json_path = reachops_web_ui.TWO_PHASE_MATRIX_JSON_PATH
    old_web_two_phase_md_path = reachops_web_ui.TWO_PHASE_MATRIX_MD_PATH
    old_load_groups = reachops_web_ui.load_groups
    old_mvp_build_summary = reachops_mvp_acceptance_summary.build_summary
    old_mvp_out_path = reachops_mvp_acceptance_summary.OUT_PATH
    old_goal_build_report = reachops_goal_delivery_runner.build_report
    old_goal_out_path = reachops_goal_delivery_runner.OUT_PATH
    old_goal_summary_path = reachops_goal_delivery_runner.SUMMARY_PATH

    server = None
    thread = None
    fake_process = FakeProcess()
    captured: dict = {"cmd": [], "cwd": "", "stdout_closed": False, "signals": []}
    checks: dict[str, bool] = {}
    diagnostics: dict[str, object] = {}

    with temporary_directory_ignoring_cleanup_errors(prefix="reachops-web-panel-smoke-") as tmpdir:
        try:
            reachops_web_ui.DATA_DIR = Path(tmpdir)
            reachops_web_ui.WEB_SETTINGS_PATH = Path(tmpdir) / "config" / "reachops_web_settings.json"
            reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
            reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
            reachops_web_ui.LATEST_EXECUTION_PLAN_PATH = Path(tmpdir) / "plans" / "latest_execution_plan.json"
            reachops_web_ui.LATEST_RUN_SESSION_PATH = Path(tmpdir) / "runs" / "latest_run_session.json"
            reachops_web_ui.LATEST_EVIDENCE_BUNDLE_PATH = Path(tmpdir) / "evidence_bundles" / "latest_evidence_bundle.json"
            reachops_web_ui.LATEST_EVIDENCE_BUNDLE_MD_PATH = Path(tmpdir) / "evidence_bundles" / "latest_evidence_bundle.md"
            reachops_web_ui.CURRENT_RUN_SESSION_PATH = ""
            reachops_web_ui.MVP_ACCEPTANCE_SUMMARY_PATH = Path(tmpdir) / "reports" / "acceptance_remediation" / "latest_mvp_acceptance_summary.json"
            reachops_web_ui.GOAL_DELIVERY_REPORT_PATH = Path(tmpdir) / "reports" / "acceptance_remediation" / "latest_goal_delivery_report.json"
            reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH = Path(tmpdir) / "reports" / "acceptance_remediation" / "latest_goal_delivery_summary.md"
            reachops_web_ui.TWO_PHASE_MATRIX_JSON_PATH = Path(tmpdir) / "reports" / "acceptance_remediation" / "latest_two_phase_acceptance_matrix.json"
            reachops_web_ui.TWO_PHASE_MATRIX_MD_PATH = Path(tmpdir) / "reports" / "acceptance_remediation" / "latest_two_phase_acceptance_matrix.md"
            reachops_web_ui.RUN_PROCESS = None
            reachops_web_ui.RUN_PAUSED = False
            reachops_web_ui.RUN_STARTED_AT = 0.0
            reachops_web_ui.os.environ["REACHOPS_REQUIRE_ACTIVATION"] = "1"
            offline_ledger = OfflineLearningLedger(Path(tmpdir) / "offline_learning" / "unknown_states.json")
            unknown_page_state = {
                "schema_version": "reachops.page_state.v1",
                "state": "UNKNOWN_PAGE_STATE",
                "current_url": "https://www.tiktok.com/@creator/video/123",
                "title": "Please log in",
                "body_text_sample": "Log in to continue",
                "body_text_sha256": "runtime-login-hash",
                "signals": ["login_text"],
                "selector_counts": {"comment_box_count": 0},
            }
            offline_ledger.record_unknown_state(
                page_state=unknown_page_state,
                error_code="UNKNOWN_PAGE_STATE",
                action_type="comment_reply",
                evidence_path=str(Path(tmpdir) / "evidence" / "unknown-1.png"),
            )
            offline_ledger.record_unknown_state(
                page_state=unknown_page_state,
                error_code="UNKNOWN_PAGE_STATE",
                action_type="comment_reply",
                evidence_path=str(Path(tmpdir) / "evidence" / "unknown-2.png"),
            )
            reachops_mvp_acceptance_summary.OUT_PATH = reachops_web_ui.MVP_ACCEPTANCE_SUMMARY_PATH
            reachops_goal_delivery_runner.OUT_PATH = reachops_web_ui.GOAL_DELIVERY_REPORT_PATH
            reachops_goal_delivery_runner.SUMMARY_PATH = reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH
            reachops_mvp_acceptance_summary.build_summary = lambda: {
                "status": "mvp_accepted_external_pending",
                "mvp_local_ready": True,
                "final_delivery_ready": False,
                "failed_checks": [],
            }
            reachops_goal_delivery_runner.build_report = lambda: {
                "status": "local_mvp_accepted_final_pending",
                "local_mvp_ready": True,
                "windows_build_ready": True,
                "final_delivery_ready": False,
                "delivery_boundary": {
                    "summary": "本地 MVP 和客户端门禁已可验收；整项目最终交付仍未完成。",
                    "local_mvp_scope_ready": True,
                    "client_gate_scope_ready": True,
                    "windows_build_input_scope_ready": True,
                    "overall_final_delivery_scope_ready": False,
                    "client_gate_final_delivery_ready_is_not_overall_final_delivery": True,
                    "blocking_scopes": ["windows_final_artifacts", "external_authorized_execution"],
                },
                "failed_checks": ["delivery_package:passed"],
                "final_delivery_blockers": [
                    {
                        "scope": "external_authorized_execution",
                        "status": "ready_for_external_validation",
                        "required_evidence": ["授权 TikTok 目标", "comment_visible_confirmed=true"],
                        "next_action": "完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。",
                    },
                    {
                        "scope": "windows_final_artifacts",
                        "status": "failed",
                        "required_artifacts": [
                            r"dist\ReachOps\ReachOps.exe",
                            r"reports\reachops_acceptance\acceptance_summary.json",
                        ],
                        "next_action": r"在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\reachops_delivery_package_check.py --json。",
                    },
                ],
                "blockers": [{"scope": "windows_final_artifacts", "status": "failed"}],
                "sections": {
                    "windows_package_preflight": {
                        "payload": {
                            "status": "ready_for_windows_build",
                            "ready_for_windows_build": True,
                            "final_delivery_ready": False,
                            "missing_final_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                            "build_contract": {
                                "default_build_requires_installer": True,
                                "skip_installer_is_non_final": True,
                                "preflight_report_path": "reports/reachops_acceptance/windows_package_preflight.json",
                            },
                        }
                    }
                },
                "next_actions": ["在 Windows 实机运行 build 和 acceptance。"],
                "evidence_files": {
                    "goal_delivery_report": str(reachops_web_ui.GOAL_DELIVERY_REPORT_PATH),
                    "goal_delivery_summary": str(reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH),
                },
            }
            reachops_web_ui.build_final_status_payload = lambda: {
                "status": "blocked",
                "final_delivery_ready": False,
                "no_browser_started": True,
                "no_submit": True,
                "delivery_boundary": {
                    "schema_version": "reachops.delivery_boundary.v1",
                    "status": "local_capability_ready_final_pending",
                    "local_product_capability_ready": True,
                    "product_capability_ready": True,
                    "product_development_ready": True,
                    "final_delivery_ready": False,
                    "external_validation_pending": True,
                    "windows_final_artifacts_pending": True,
                    "pending_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                    "boundary_note": "本地产品能力 ready 只证明自治链路闭环；final_delivery_ready=true 才代表真实授权执行和最终客户端交付完成。",
                    "no_browser_started": True,
                    "no_submit": True,
                },
                "delivery_boundary_status": "local_capability_ready_final_pending",
                "local_product_capability_ready": True,
                "product_capability_ready": True,
                "product_development_ready": True,
                "external_validation_pending": True,
                "windows_final_artifacts_pending": True,
                "pending_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                "product_capability_summary": {
                    "schema_version": "reachops.product_capability_summary.v1",
                    "ready": True,
                    "passed_count": 8,
                    "failed_count": 0,
                    "failed_phases": [],
                    "phases": [{"key": "phase_3_autonomous_execution", "passed": True}],
                },
                "product_development_goals": {
                    "schema_version": "reachops.product_development_goals.v1",
                    "ready": True,
                    "stage_count": 8,
                    "current_focus": {"title": "证据与交付闭环"},
                    "stages": [],
                },
                "mvp_acceptance": {"status": "mvp_accepted_external_pending", "mvp_local_ready": True},
                "final_delivery_evidence_plan": {
                    "schema_version": "reachops.final_delivery_evidence_plan.v1",
                    "ready": False,
                    "pending_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                    "items": [
                        {
                            "scope": "external_authorized_execution",
                            "status": "ready_for_external_validation",
                            "required_evidence": ["授权 TikTok 目标", "comment_visible_confirmed=true"],
                            "proof_fields": ["goal_status.pending_external_validation=[]"],
                            "commands": ["python tools\\reachops_goal_status_report.py --strict-external --json"],
                        },
                        {
                            "scope": "windows_final_artifacts",
                            "status": "failed",
                            "required_artifacts": [
                                r"dist\ReachOps\ReachOps.exe",
                                r"reports\reachops_acceptance\acceptance_summary.json",
                            ],
                            "proof_fields": ["delivery_package.final_delivery_ready=true"],
                            "commands": ["python tools\\reachops_delivery_package_check.py --json"],
                        },
                    ],
                },
                "two_phase_acceptance": {
                    "status": "local_mvp_accepted_final_pending",
                    "local_mvp_ready": True,
                    "final_delivery_ready": False,
                    "failed_items": ["windows_final_artifacts", "authorized_live_submit"],
                    "blocking_scopes": ["external_authorized_execution", "windows_final_artifacts"],
                    "path": str(reachops_web_ui.TWO_PHASE_MATRIX_JSON_PATH),
                    "markdown_path": str(reachops_web_ui.TWO_PHASE_MATRIX_MD_PATH),
                },
                "goal_delivery": {
                    "status": "local_mvp_accepted_final_pending",
                    "local_mvp_ready": True,
                    "windows_build_ready": True,
                    "final_delivery_ready": False,
                    "delivery_boundary": {
                        "summary": "本地 MVP 和客户端门禁已可验收；整项目最终交付仍未完成。",
                        "local_mvp_scope_ready": True,
                        "client_gate_scope_ready": True,
                        "windows_build_input_scope_ready": True,
                        "overall_final_delivery_scope_ready": False,
                        "client_gate_final_delivery_ready_is_not_overall_final_delivery": True,
                        "blocking_scopes": ["windows_final_artifacts", "external_authorized_execution"],
                    },
                    "final_delivery_blockers": [
                        {
                            "scope": "external_authorized_execution",
                            "status": "ready_for_external_validation",
                            "required_evidence": ["授权 TikTok 目标", "comment_visible_confirmed=true"],
                            "next_action": "完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。",
                        },
                        {
                            "scope": "windows_final_artifacts",
                            "status": "failed",
                            "required_artifacts": [
                                r"dist\ReachOps\ReachOps.exe",
                                r"reports\reachops_acceptance\acceptance_summary.json",
                            ],
                            "next_action": r"在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\reachops_delivery_package_check.py --json。",
                        },
                    ],
                    "blockers": [{"scope": "windows_final_artifacts", "status": "failed"}],
                    "windows_package_preflight": {
                        "status": "ready_for_windows_build",
                        "ready_for_windows_build": True,
                        "final_delivery_ready": False,
                        "missing_final_artifacts": ["exe", "installer", "manifest", "acceptance_summary"],
                        "default_build_requires_installer": True,
                        "skip_installer_is_non_final": True,
                    },
                    "summary_path": str(reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH),
                },
                "failed_checks": ["delivery_package:passed"],
                "blocking_plan": [
                    {
                        "stage": "授权输入",
                        "status": "blocked",
                        "blockers": ["已授权 TikTok 视频链接"],
                        "actions": ["填入已授权 TikTok 视频链接 CommentVideoUrl。"],
                    },
                    {
                        "stage": "Windows交付包",
                        "status": "blocked",
                        "blockers": ["Windows 交付包未达到 final_delivery_ready=true。"],
                        "actions": ["在 Windows 实机生成 exe、installer、manifest 和 acceptance_summary.json 后复跑 package check。"],
                    },
                ],
                "blocked_reasons": ["Windows 交付包未达到 final_delivery_ready=true。"],
            }
            reachops_web_ui.build_ixbrowser_status_payload = lambda: {
                "status": "blocked",
                "ready": False,
                "base_url": f"http://127.0.0.1:{reachops_web_ui.active_ixbrowser_api_port()}/api/v2/",
                "error": "ixBrowser Local API 未启动或端口不可连接",
                "error_detail": "connection refused",
                "no_browser_started": True,
                "no_submit": True,
                "next_actions": ["确认 ixBrowser 客户端已启动，并在 ixBrowser 设置中开启 Local API。"],
            }
            captured["group_refresh_calls"] = []

            def fake_load_groups(refresh=False, **kwargs):
                captured["group_refresh_calls"].append({"refresh": bool(refresh), **kwargs})
                return {
                    "groups": [
                        {
                            "name": "Canada",
                            "label": "Canada / 2账号",
                            "count": 2,
                            "count_known": True,
                            "count_label": "2账号",
                            "count_status": "known",
                            "count_source": "ixbrowser_profile_list",
                        },
                        {
                            "name": "United States",
                            "label": "United States / 3账号",
                            "count": 3,
                            "count_known": True,
                            "count_label": "3账号",
                            "count_status": "known",
                            "count_source": "ixbrowser_profile_list",
                        },
                    ],
                    "group_count": 2,
                    "known_group_count": 2,
                    "live_known_group_count": 2,
                    "all_group_counts_known": True,
                    "live_all_group_counts_known": True,
                    "error": "",
                }

            def fake_popen(cmd, **kwargs):
                runner_path = str((ROOT_DIR / "tools" / "run_reachops_headless_macos.py").resolve())
                launches_runner = len(cmd) > 1 and str(Path(str(cmd[1])).resolve()) == runner_path
                if not launches_runner:
                    return old_popen(cmd, **kwargs)
                captured["cmd"] = [str(item) for item in cmd]
                captured["cwd"] = str(kwargs.get("cwd") or "")
                captured["stdout_closed_before_return"] = bool(getattr(kwargs.get("stdout"), "closed", False))
                captured["stdout"] = kwargs.get("stdout")
                fake_process.alive = True
                fake_process.signal_sink = captured["signals"]
                return fake_process

            def fake_killpg(_pid, sig):
                captured["signals"].append(sig)
                fake_process.signals.append(sig)

            reachops_web_ui.subprocess.Popen = fake_popen
            reachops_web_ui.load_groups = fake_load_groups
            if old_killpg is not None:
                reachops_web_ui.os.killpg = fake_killpg

            try:
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
            except PermissionError as exc:
                return {
                    "status": "blocked_by_local_sandbox",
                    "passed": False,
                    "failed_checks": ["local_loopback_bind_permission"],
                    "checks": checks,
                    "error": f"{type(exc).__name__}: {exc}",
                    "blocked_reason": "本地沙箱拒绝绑定临时 loopback HTTP 端口，无法执行运行时 API 冒烟。",
                    "source_mtimes": source_mtimes(),
                    "captured_command": [],
                    "captured_signals": [],
                }
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            base = f"http://{host}:{port}"

            html = _html_request(base + "/")
            checks["html_contains_real_controls"] = all(
                token in html
                for token in [
                    'id="start"',
                    'id="start" disabled',
                    'id="pause"',
                    'id="resume"',
                    'id="stop"',
                    'id="liveConfirm"',
                    'id="activationState"',
                    'id="activationActions"',
                    'id="ixbrowserApiState"',
                    'id="ixbrowserApiPort"',
                    'id="applyIxBrowserPort"',
                    'id="ixbrowserStatusActions"',
                    'id="finalStatusState"',
                    "postJson('/api/start'",
                    "postJson('/api/start-preview'",
                    "postJson('/api/control'",
                    "postJson('/api/mvp-acceptance-refresh'",
                    "postJson('/api/goal-delivery-refresh'",
                    "fetch('/api/logs')",
                    "fetch('/api/snapshot')",
                    "fetch('/api/acceptance')",
                    "fetch('/api/product-capability')",
                    "mvp_local_ready",
                    "goal_delivery",
                    "delivery_boundary",
                    "交付边界",
                    "最终交付待验",
                    "windows_build_ready",
                    "fetch('/api/activation')",
                    "fetch('/api/ixbrowser-status')",
                    "fetch('/api/final-status')",
                    "async function refreshActivation()",
                    "async function refreshIxBrowserStatus()",
                    "async function refreshFinalStatus()",
                    "async function refreshProductCapability()",
                    "async function postJson(url, payload)",
                    "function showApiNotice",
                    "function apiNoticeActive()",
                    "apiNoticeUntil = Date.now() + Math.max",
                    "let groupListReady = false",
                    "$('start').disabled = !groupListReady",
                    "runtimePreview",
                    "controlPanel",
                    "taskForm",
                    "taskParams",
                    "taskActions",
                    "grid-template-columns:repeat(auto-fit,minmax(176px,1fr))",
                    "grid-template-columns:minmax(180px,1fr)",
                    "grid-template-columns:repeat(auto-fit,minmax(106px,1fr))",
                    "本地服务连接失败",
                    "$('runState').textContent = 'OFFLINE'",
                    "live_comment_confirmation_required",
                    "showApiNotice('启动被系统拦截'",
                    "showApiNotice(`控制未执行：${action}`",
                ]
            )
            status, version = _json_request(base + "/api/version")
            checks["version_endpoint_reports_current_ui_without_browser_action"] = (
                status == 200
                and version.get("status") == "ok"
                and version.get("version") == reachops_web_ui.WEB_UI_VERSION
                and version.get("display_version") == reachops_web_ui.CLIENT_DISPLAY_VERSION
                and version.get("client_surface") == "local_client_console"
                and version.get("display_name") == "ReachOps Local Client Console"
                and version.get("loopback_host") == "127.0.0.1"
                and version.get("no_browser_started") is True
                and version.get("no_submit") is True
            )
            app_entry = (ROOT_DIR / "ReachOpsApp.py").read_text(encoding="utf-8")
            launcher_source = (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8")
            local_client_command = (ROOT_DIR / "启动ReachOps本地客户端.command").read_text(encoding="utf-8")
            unified_web_command = (ROOT_DIR / "启动ReachOps统一WebUI.command").read_text(encoding="utf-8")
            native_mac_command = (ROOT_DIR / "启动ReachOps原生MacUI.command").read_text(encoding="utf-8")
            launcher_tests = (ROOT_DIR / "tests" / "test_launcher.py").read_text(encoding="utf-8")
            checks["client_launch_entrypoints_are_unified_local_console"] = (
                "from ReachOps.launcher import main" in app_entry
                and "return _launch_web_client()" in launcher_source
                and "legacy_requested = \"--legacy-tk\" in args or os.environ.get(\"REACHOPS_LEGACY_TK\") == \"1\""
                in launcher_source
                and "回退到原生 Tk 客户端" not in launcher_source
                and "exec ./启动ReachOps统一WebUI.command" in local_client_command
                and "tools/reachops_mac_self_check.py --start-web" in unified_web_command
                and "ReachOps 客户端入口已统一到本地客户端控制台" in native_mac_command
                and "ReachOpsApp.py --legacy-tk" in native_mac_command
                and "test_default_entry_starts_unified_web_client" in launcher_tests
                and "test_missing_web_launcher_does_not_silently_fallback_to_legacy_tk" in launcher_tests
            )

            status, empty_target = _json_request(base + "/api/start", {"target": "  "}, expect_error=400)
            checks["start_rejects_empty_target"] = status == 400 and empty_target.get("error") == "target_required"

            status, missing_replay_preview = _json_request(base + "/api/start-from-plan-preview")
            missing_replay_decision = missing_replay_preview.get("preflight_decision") or {}
            checks["start_from_plan_preview_reports_missing_plan_without_side_effects"] = (
                status == 200
                and missing_replay_preview.get("status") == "missing"
                and missing_replay_preview.get("execution_plan_replay") is True
                and "execution_plan_missing" in (missing_replay_decision.get("blockers") or [])
                and missing_replay_preview.get("no_browser_started") is True
                and missing_replay_preview.get("no_submit") is True
            )

            status, start_preview = _json_request(
                base + "/api/start-preview",
                {"mode": "live_comment", "volume": "stress", "profiles": 999, "liveConfirm": True},
            )
            checks["start_preview_uses_backend_normalization"] = (
                status == 200
                and start_preview.get("mode") == "live_comment"
                and start_preview.get("volume") == "stress"
                and int(start_preview.get("profile_limit") or 0) == reachops_web_ui.MAX_START_PROFILE_LIMIT
                and int(start_preview.get("max_videos") or 0) == 20
                and int(start_preview.get("max_comments") or 0) == 100
                and start_preview.get("submit_policy") == "真实评论提交"
                and start_preview.get("no_browser_started") is True
                and start_preview.get("no_submit") is True
            )
            preview_decision = start_preview.get("preflight_decision") or {}
            preview_forecast = start_preview.get("autonomous_preflight_forecast") or {}
            checks["start_preview_exposes_structured_preflight_decision"] = (
                status == 200
                and preview_decision.get("schema_version") == "reachops.start_preflight_decision.v1"
                and preview_decision.get("status") == "blocked"
                and preview_decision.get("start_allowed") is False
                and "target_required" in (preview_decision.get("blockers") or [])
                and "profile_group_list_not_ready" in (preview_decision.get("blockers") or [])
                and preview_decision.get("no_ai_token_used") is True
                and preview_decision.get("no_browser_started") is True
                and preview_decision.get("no_submit") is True
            )
            checks["start_preview_exposes_autonomous_preflight_forecast"] = (
                status == 200
                and preview_forecast.get("schema_version") == "reachops.autonomous_preflight_forecast.v1"
                and preview_forecast.get("status") == "blocked"
                and preview_forecast.get("start_allowed") is False
                and "target_required" in (preview_forecast.get("predicted_blockers") or [])
                and "profile_group_list_not_ready" in (preview_forecast.get("predicted_blockers") or [])
                and any((row or {}).get("gate") == "live_action_authorization" for row in (preview_forecast.get("risk_gates") or []))
                and any((row or {}).get("state") == "UNKNOWN_PAGE_STATE" for row in (preview_forecast.get("repair_routes") or []))
                and "run_session_state_history" in (preview_forecast.get("evidence_requirements") or [])
                and (preview_forecast.get("runtime_invariants") or {}).get("no_ai_token_during_execution") is True
                and preview_forecast.get("no_ai_token_used") is True
                and preview_forecast.get("no_browser_started") is True
                and preview_forecast.get("no_submit") is True
            )
            preview_plan = start_preview.get("execution_plan") or {}
            preview_authorization = preview_plan.get("authorization") or {}
            preview_repair_policy = preview_plan.get("repair_policy") or {}
            preview_risk_policy = preview_plan.get("risk_policy") or {}
            preview_runtime_contract = preview_plan.get("runtime_contract") or {}
            checks["start_preview_exposes_execution_plan"] = (
                preview_plan.get("schema_version") == "reachops.execution_plan.v1"
                and preview_plan.get("mode") == "live_comment"
                and preview_plan.get("volume") == "stress"
                and int((preview_plan.get("limits") or {}).get("profile_limit") or 0)
                == reachops_web_ui.MAX_START_PROFILE_LIMIT
                and preview_authorization.get("live_confirmed") is True
                and preview_authorization.get("live_submit_allowed") is True
                and preview_repair_policy.get("LOGIN_REQUIRED", {}).get("action") == "quarantine_profile"
                and preview_repair_policy.get("DOM_STALLED", {}).get("action") == "refresh_then_degrade"
                and preview_repair_policy.get("UNKNOWN_PAGE_STATE", {}).get("action") == "capture_error_bundle_then_block"
                and preview_risk_policy.get("no_ai_token_during_execution") is True
                and preview_risk_policy.get("require_human_authorization_for_live_actions") is True
                and preview_risk_policy.get("never_bypass_login_or_captcha") is True
                and preview_runtime_contract.get("schema_version") == "reachops.execution_runtime_contract.v1"
                and preview_runtime_contract.get("executor") == "local_program"
                and preview_runtime_contract.get("control_surface") == "local_client_console"
                and preview_runtime_contract.get("ai_console_is_execution_dependency") is False
                and preview_runtime_contract.get("no_ai_token_during_execution") is True
                and preview_runtime_contract.get("execution_phase_ai_calls_allowed") is False
                and preview_runtime_contract.get("requires_human_authorization_for_live_actions") is True
                and preview_runtime_contract.get("page_state_evidence_required") is True
                and preview_runtime_contract.get("evidence_bundle_required") is True
                and (start_preview.get("runtime_contract") or {}).get("schema_version") == "reachops.execution_runtime_contract.v1"
                and (((preview_plan.get("ui") or {}).get("parameter_mapping") or {}).get("schema_version"))
                == "reachops.execution_plan_parameter_mapping.v1"
                and (((((preview_plan.get("ui") or {}).get("parameter_mapping") or {}).get("fields") or {}).get("profile_limit") or {}).get("normalized"))
                == reachops_web_ui.MAX_START_PROFILE_LIMIT
            )
            status, ready_preview = _json_request(
                base + "/api/start-preview",
                {
                    "target": "anti aging serum",
                    "sourceType": "keyword",
                    "group": "Canada",
                    "mode": "preflight",
                    "volume": "quick",
                    "profiles": 3,
                    "groupListReady": True,
                },
            )
            ready_decision = ready_preview.get("preflight_decision") or {}
            ready_forecast = ready_preview.get("autonomous_preflight_forecast") or {}
            checks["start_preview_allows_ready_preflight_without_submit"] = (
                status == 200
                and ready_decision.get("status") == "ready"
                and ready_decision.get("start_allowed") is True
                and ready_preview.get("start_allowed") is True
                and ready_forecast.get("schema_version") == "reachops.autonomous_preflight_forecast.v1"
                and ready_forecast.get("status") == "ready"
                and ready_forecast.get("start_allowed") is True
                and "PROFILE_OPENING" in (ready_forecast.get("predicted_state_sequence") or [])
                and "REPAIRING" in (ready_forecast.get("predicted_state_sequence") or [])
                and ready_decision.get("submit_policy") == "预检，不提交"
                and ready_decision.get("no_browser_started") is True
                and ready_decision.get("no_submit") is True
            )
            status, ai_console = _json_request(
                base + "/api/ai-console",
                {
                    "message": "只采集不评论",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            ai_plan = ai_console.get("execution_plan") or {}
            ai_authorization = ai_plan.get("authorization") or {}
            ai_repair_policy = ai_plan.get("repair_policy") or {}
            ai_risk_policy = ai_plan.get("risk_policy") or {}
            ai_runtime_contract = ai_plan.get("runtime_contract") or {}
            checks["ai_console_maps_operator_text_to_execution_plan_without_tokens"] = (
                status == 200
                and ai_console.get("intent") == "plan_update"
                and ai_console.get("no_ai_token_used") is True
                and ai_console.get("no_browser_started") is True
                and ai_console.get("no_submit") is True
                and isinstance(ai_console.get("client_delivery"), dict)
                and isinstance(ai_console.get("client_delivery_summary"), dict)
                and (ai_console.get("client_delivery_summary") or {}).get("no_ai_token_used") is True
                and (ai_console.get("client_delivery_summary") or {}).get("no_browser_started") is True
                and (ai_console.get("client_delivery_summary") or {}).get("no_submit") is True
                and (ai_console.get("plan_patch") or {}).get("mode") == "collect"
                and ai_plan.get("schema_version") == "reachops.execution_plan.v1"
                and ai_plan.get("mode") == "collect"
                and ai_plan.get("profile_group") == "Canada"
                and ai_authorization.get("live_confirmed") is False
                and ai_authorization.get("live_submit_allowed") is False
                and ai_repair_policy.get("LOGIN_REQUIRED", {}).get("action") == "quarantine_profile"
                and ai_repair_policy.get("DOM_STALLED", {}).get("action") == "refresh_then_degrade"
                and ai_repair_policy.get("UNKNOWN_PAGE_STATE", {}).get("action") == "capture_error_bundle_then_block"
                and ai_risk_policy.get("no_ai_token_during_execution") is True
                and ai_risk_policy.get("require_human_authorization_for_live_actions") is False
                and ai_risk_policy.get("never_bypass_login_or_captcha") is True
                and ai_runtime_contract.get("schema_version") == "reachops.execution_runtime_contract.v1"
                and ai_runtime_contract.get("executor") == "local_program"
                and ai_runtime_contract.get("ai_console_is_execution_dependency") is False
                and ai_runtime_contract.get("no_ai_token_during_execution") is True
                and ai_runtime_contract.get("execution_phase_ai_calls_allowed") is False
                and ai_runtime_contract.get("requires_human_authorization_for_live_actions") is False
                and ai_runtime_contract.get("risk_gate_required") is True
            )

            status, untrusted = _json_request(
                base + "/api/start",
                {"target": "anti aging serum"},
                headers={"Origin": "https://evil.example"},
                expect_error=403,
            )
            checks["start_rejects_untrusted_origin"] = status == 403 and untrusted.get("error") == "untrusted_origin"

            status, get_untrusted = _json_request(
                base + "/api/acceptance",
                headers={"Origin": "https://evil.example"},
                expect_error=403,
            )
            checks["get_api_rejects_untrusted_origin"] = (
                status == 403 and get_untrusted.get("error") == "untrusted_origin"
            )

            status, unknown_api = _json_request(base + "/api/does-not-exist", expect_error=404)
            checks["unknown_get_api_returns_json_404"] = (
                status == 404 and unknown_api.get("error") == "unknown_api"
            )

            status, unknown_post_api = _json_request(
                base + "/api/does-not-exist",
                {"target": "anti aging serum"},
                expect_error=404,
            )
            checks["unknown_post_api_returns_json_404"] = (
                status == 404 and unknown_post_api.get("error") == "unknown_api"
            )

            status, groups = _json_request(base + "/api/groups?refresh=1")
            group_names = [row.get("name") for row in groups.get("groups") or []]
            checks["groups_endpoint_refreshes_ixbrowser_config_list"] = (
                status == 200
                and bool(captured["group_refresh_calls"])
                and bool(captured["group_refresh_calls"][0].get("refresh"))
                and group_names == ["Canada", "United States"]
            )
            checks["groups_endpoint_returns_operator_count_fields"] = (
                status == 200
                and {row.get("name"): row.get("count_label") for row in groups.get("groups") or []}
                == {"Canada": "2账号", "United States": "3账号"}
                and all(row.get("count_status") == "known" for row in groups.get("groups") or [])
                and all(row.get("count_source") for row in groups.get("groups") or [])
            )
            group_refresh_log = reachops_web_ui.LOG_PATH.read_text(encoding="utf-8", errors="replace")
            checks["groups_endpoint_writes_operator_visible_log"] = (
                "refresh_groups source=web_ui refresh=true" in group_refresh_log
                and "groups=2" in group_refresh_log
                and "Canada,United States" in group_refresh_log
            )

            status, unknown_group = _json_request(
                base + "/api/start",
                {"target": "anti aging serum", "group": "Ghost Group"},
                expect_error=400,
            )
            checks["start_rejects_group_outside_ixbrowser_config_list"] = (
                status == 400
                and unknown_group.get("error") == "profile_group_not_found"
                and (unknown_group.get("run_session") or {}).get("path")
                and (unknown_group.get("execution_plan") or {}).get("path")
                and not captured.get("cmd")
            )
            status, blocked_group_evidence = _json_request(base + "/api/evidence-bundle")
            blocked_group_auto = blocked_group_evidence.get("autonomous_execution_summary") or {}
            blocked_group_page = blocked_group_evidence.get("page_state_summary") or {}
            blocked_group_page_counts = blocked_group_page.get("state_counts") or {}
            checks["start_group_precheck_block_writes_auditable_run_session"] = (
                status == 200
                and blocked_group_evidence.get("schema_version") == "reachops.evidence_bundle.v1"
                and blocked_group_auto.get("precheck_blocked") is True
                and blocked_group_auto.get("autonomous_core_ready") is True
                and blocked_group_auto.get("required_core_states") == ["CREATED", "PRECHECK", "BLOCKED"]
                and blocked_group_auto.get("missing_core_states") == []
                and (blocked_group_evidence.get("summary") or {}).get("state") == "BLOCKED"
                and (blocked_group_evidence.get("summary") or {}).get("status") != "success"
                and (blocked_group_evidence.get("summary") or {}).get("state") != "COMPLETED"
            )
            checks["start_group_precheck_block_writes_page_state_sidecar"] = (
                status == 200
                and blocked_group_page.get("schema_version") == "reachops.page_state_summary.v1"
                and int(blocked_group_page.get("snapshot_count") or 0) > 0
                and int(blocked_group_page.get("blocking_count") or 0) > 0
                and int(blocked_group_page.get("unknown_count") or 0) > 0
                and int(blocked_group_page_counts.get("UNKNOWN_PAGE_STATE") or 0) > 0
                and int(blocked_group_page.get("screenshot_unavailable_count") or 0) > 0
                and blocked_group_page.get("no_ai_token_used") is True
                and (blocked_group_evidence.get("audit") or {}).get("page_state_sidecar_artifact_count", 0) > 0
                and any(
                    (row or {}).get("kind") == "page_state_sidecar" and (row or {}).get("exists") is True
                    for row in (blocked_group_evidence.get("artifacts") or [])
                )
            )
            blocked_group_repair = blocked_group_evidence.get("repair_summary") or {}
            blocked_group_repair_steps = [
                step
                for event in (blocked_group_repair.get("audit_events") or [])
                for step in ((event or {}).get("executable_steps") or [])
                if isinstance(step, dict)
            ]
            checks["start_group_precheck_block_writes_repair_decision"] = (
                status == 200
                and blocked_group_repair.get("schema_version") == "reachops.repair_summary.v1"
                and int(blocked_group_repair.get("decision_count") or 0) > 0
                and int(blocked_group_repair.get("audit_event_count") or 0) > 0
                and int(blocked_group_repair.get("block_count") or 0) > 0
                and int(blocked_group_repair.get("terminal_block_count") or 0) > 0
                and (blocked_group_repair.get("terminal_outcome_counts") or {}).get("blocked", 0) > 0
                and "refresh_profile_groups_and_reselect" in (blocked_group_repair.get("actions") or [])
                and "profile_group_not_found" in (blocked_group_repair.get("error_codes") or [])
                and any((step or {}).get("step") == "block_execution" for step in blocked_group_repair_steps)
                and any((step or {}).get("step") == "refresh_profile_groups" for step in blocked_group_repair_steps)
                and blocked_group_repair.get("no_ai_token_used") is True
            )
            blocked_group_risk = blocked_group_evidence.get("risk_summary") or {}
            blocked_group_policy = blocked_group_evidence.get("risk_policy_summary") or {}
            blocked_group_operator_risk = blocked_group_evidence.get("operator_risk_gate_summary") or {}
            checks["start_group_precheck_block_writes_risk_gate"] = (
                status == 200
                and blocked_group_risk.get("schema_version") == "reachops.risk_summary.v1"
                and int(blocked_group_risk.get("decision_count") or 0) > 0
                and int(blocked_group_risk.get("blocked_count") or 0) > 0
                and int(blocked_group_risk.get("block_execution_count") or 0) > 0
                and "profile_group_not_found" in (blocked_group_risk.get("reason_codes") or [])
                and int(blocked_group_policy.get("policy_block_count") or 0) > 0
                and blocked_group_operator_risk.get("schema_version") == "reachops.operator_risk_gate_summary.v1"
                and int(blocked_group_operator_risk.get("blocked_count") or 0) > 0
                and "profile_group_not_found" in str(blocked_group_operator_risk.get("primary_reason") or "")
            )

            original_fake_load_groups = reachops_web_ui.load_groups

            def fake_incomplete_group_counts(refresh=False, **kwargs):
                captured["group_refresh_calls"].append({"refresh": bool(refresh), **kwargs})
                return {
                    "groups": [
                        {
                            "name": "Canada",
                            "label": "Canada / 2账号",
                            "count": 2,
                            "count_known": True,
                            "count_label": "2账号",
                            "count_status": "known",
                        },
                        {
                            "name": "United States",
                            "label": "United States / 数量未返回",
                            "count": 0,
                            "count_known": False,
                            "count_label": "数量未返回",
                            "count_status": "unknown",
                        },
                    ],
                    "group_count": 2,
                    "known_group_count": 1,
                    "live_known_group_count": 1,
                    "all_group_counts_known": False,
                    "live_all_group_counts_known": False,
                    "error": "",
                }

            reachops_web_ui.load_groups = fake_incomplete_group_counts
            status, incomplete_group_counts = _json_request(
                base + "/api/start",
                {"target": "anti aging serum", "group": "Canada"},
                expect_error=400,
            )
            checks["start_rejects_incomplete_group_counts"] = (
                status == 400
                and incomplete_group_counts.get("error") == "profile_group_counts_incomplete"
                and (incomplete_group_counts.get("run_session") or {}).get("path")
                and (incomplete_group_counts.get("execution_plan") or {}).get("path")
                and not captured.get("cmd")
            )
            reachops_web_ui.load_groups = original_fake_load_groups

            status, unconfirmed_live = _json_request(
                base + "/api/start",
                {"target": "anti aging serum", "mode": "live_comment", "liveConfirm": False},
                expect_error=400,
            )
            checks["start_rejects_live_comment_without_confirmation"] = (
                status == 400 and unconfirmed_live.get("error") == "live_comment_confirmation_required" and not captured.get("cmd")
            )

            status, unauthorized_live = _json_request(
                base + "/api/start",
                {"target": "anti aging serum", "mode": "live_comment", "liveConfirm": True},
                expect_error=403,
            )
            checks["start_rejects_live_comment_without_activation"] = (
                status == 403 and unauthorized_live.get("error") == "LIVE_SUBMIT_NOT_AUTHORIZED" and not captured.get("cmd")
            )

            status, started = _json_request(
                base + "/api/start",
                {
                    "target": "anti aging serum",
                    "sourceType": "keyword",
                    "group": "Canada",
                    "mode": "invalid",
                    "volume": "huge",
                    "profiles": 9999,
                    "commentText": "Hi",
                },
            )
            captured["stdout_closed"] = bool(getattr(captured.get("stdout"), "closed", False))
            checks["start_launches_headless_runner"] = (
                status == 200
                and started.get("status") == "started"
                and "run_reachops_headless_macos.py" in " ".join(captured["cmd"]).replace("\\", "/")
            )
            cmd = captured["cmd"]
            checks["start_normalizes_runtime_inputs"] = all(
                [
                    cmd[cmd.index("--base-dir") + 1] == str(reachops_web_ui.DATA_DIR),
                    cmd[cmd.index("--profile-limit") + 1] == str(reachops_web_ui.MAX_START_PROFILE_LIMIT),
                    cmd[cmd.index("--mode") + 1] == "preflight",
                    cmd[cmd.index("--volume") + 1] == "quick",
                    cmd[cmd.index("--max-videos") + 1] == "3",
                    cmd[cmd.index("--max-comments") + 1] == "20",
                    int(cmd[cmd.index("--timeout") + 1]) >= 900,
                    cmd[cmd.index("--source-type") + 1] == "keyword",
                    cmd[cmd.index("--profile-group") + 1] == "Canada",
                    cmd[cmd.index("--comment-text") + 1] == "Hi",
                    int(started.get("timeout_seconds") or 0) == int(cmd[cmd.index("--timeout") + 1]),
                ]
            )
            checks["start_passes_web_runtime_dir_to_headless"] = cmd[cmd.index("--base-dir") + 1] == str(
                reachops_web_ui.DATA_DIR
            )
            plan_path = Path(cmd[cmd.index("--execution-plan") + 1]) if "--execution-plan" in cmd else Path("")
            stored_plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else {}
            checks["start_writes_and_passes_execution_plan"] = (
                "--execution-plan" in cmd
                and plan_path.is_file()
                and reachops_web_ui.LATEST_EXECUTION_PLAN_PATH.is_file()
                and stored_plan.get("schema_version") == "reachops.execution_plan.v1"
                and stored_plan.get("target") == "anti aging serum"
                and stored_plan.get("source_type") == "keyword"
                and stored_plan.get("profile_group") == "Canada"
                and (stored_plan.get("limits") or {}).get("profile_limit") == reachops_web_ui.MAX_START_PROFILE_LIMIT
                and started.get("execution_plan_id") == stored_plan.get("plan_id")
                and started.get("execution_plan_path") == str(plan_path)
            )
            status, execution_plan_payload = _json_request(base + "/api/execution-plan")
            checks["execution_plan_endpoint_returns_latest_auditable_plan"] = (
                status == 200
                and execution_plan_payload.get("status") == "ok"
                and execution_plan_payload.get("schema_version") == "reachops.execution_plan.v1"
                and execution_plan_payload.get("plan_id") == stored_plan.get("plan_id")
                and execution_plan_payload.get("path") == str(reachops_web_ui.LATEST_EXECUTION_PLAN_PATH)
                and (execution_plan_payload.get("execution_plan") or {}).get("profile_group") == "Canada"
                and execution_plan_payload.get("no_browser_started") is True
                and execution_plan_payload.get("no_submit") is True
            )
            status, contract_preview = _json_request(base + "/api/execution-plan-contract-preview")
            preview_contract = contract_preview.get("contract") or {}
            preview_after = preview_contract.get("after") or {}
            checks["execution_plan_contract_preview_uses_headless_mapper_without_side_effects"] = (
                status == 200
                and contract_preview.get("status") == "ok"
                and contract_preview.get("schema_version") == "reachops.execution_plan_contract_preview.v1"
                and contract_preview.get("execution_plan_id") == stored_plan.get("plan_id")
                and contract_preview.get("plan_fingerprint_sha256") == stored_plan.get("plan_fingerprint_sha256")
                and contract_preview.get("uses_headless_runtime_mapper") is True
                and contract_preview.get("all_plan_fields_mapped") is True
                and preview_contract.get("schema_version") == "reachops.execution_plan_runtime_contract.v1"
                and preview_contract.get("cli_args_ignored_for_plan_fields") is True
                and bool(preview_contract.get("runtime_after_fingerprint_sha256"))
                and preview_after.get("target") == stored_plan.get("target")
                and preview_after.get("source_type") == stored_plan.get("source_type")
                and preview_after.get("profile_group") == stored_plan.get("profile_group")
                and preview_after.get("mode") == stored_plan.get("mode")
                and preview_after.get("volume") == stored_plan.get("volume")
                and int(preview_after.get("profile_limit") or 0) == int((stored_plan.get("limits") or {}).get("profile_limit") or 0)
                and contract_preview.get("no_browser_started") is True
                and contract_preview.get("no_submit") is True
            )
            status, replay_preview = _json_request(base + "/api/start-from-plan-preview")
            replay_decision = replay_preview.get("preflight_decision") or {}
            checks["start_from_plan_preview_exposes_replay_contract"] = (
                status == 200
                and replay_preview.get("status") == "ok"
                and replay_preview.get("execution_plan_replay") is True
                and replay_preview.get("execution_plan_id") == stored_plan.get("plan_id")
                and replay_preview.get("plan_fingerprint_sha256") == stored_plan.get("plan_fingerprint_sha256")
                and replay_preview.get("execution_plan_path") == str(reachops_web_ui.LATEST_EXECUTION_PLAN_PATH)
                and (replay_preview.get("execution_plan") or {}).get("plan_id") == stored_plan.get("plan_id")
                and replay_decision.get("schema_version") == "reachops.start_preflight_decision.v1"
                and replay_decision.get("no_browser_started") is True
                and replay_decision.get("no_submit") is True
                and replay_preview.get("no_browser_started") is True
                and replay_preview.get("no_submit") is True
            )
            run_session_path = Path(cmd[cmd.index("--run-session") + 1]) if "--run-session" in cmd else Path("")
            stored_session = json.loads(run_session_path.read_text(encoding="utf-8")) if run_session_path.is_file() else {}
            checks["start_creates_and_passes_run_session"] = (
                "--run-session" in cmd
                and run_session_path.is_file()
                and reachops_web_ui.LATEST_RUN_SESSION_PATH.is_file()
                and stored_session.get("schema_version") == "reachops.run_session.v1"
                and stored_session.get("plan_id") == stored_plan.get("plan_id")
                and stored_session.get("state") == "PRECHECK"
                and (stored_session.get("checkpoint") or {}).get("state") == "PRECHECK"
                and any((row or {}).get("state") == "CREATED" for row in (stored_session.get("state_history") or []))
                and any((row or {}).get("state") == "PRECHECK" for row in (stored_session.get("state_history") or []))
                and all((row or {}).get("no_ai_token_used") is True for row in (stored_session.get("state_history") or []))
                and (stored_session.get("session_health") or {}).get("schema_version") == "reachops.run_session_health.v1"
                and (stored_session.get("session_health") or {}).get("state") == "PRECHECK"
                and (stored_session.get("session_health") or {}).get("status") in {"healthy", "terminal", "paused", "idle"}
                and stored_session.get("pid") == fake_process.pid
                and stored_session.get("no_ai_token_during_execution") is True
                and (stored_session.get("execution_runtime_contract") or {}).get("schema_version")
                == "reachops.execution_runtime_contract.v1"
                and (stored_session.get("execution_runtime_contract") or {}).get("executor") == "local_program"
                and (stored_session.get("execution_runtime_contract") or {}).get("ai_console_is_execution_dependency") is False
                and (stored_session.get("ai_usage_ledger") or {}).get("schema_version") == "reachops.ai_usage_ledger.v1"
                and ((stored_session.get("ai_usage_ledger") or {}).get("policy") or {}).get("executor") == "local_program"
                and ((stored_session.get("ai_usage_ledger") or {}).get("policy") or {}).get("execution_phase_ai_calls_allowed") is False
                and ((stored_session.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
                and ((stored_session.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("token_estimate") == 0
                and started.get("run_session_id") == stored_session.get("session_id")
                and started.get("run_session_path") == str(run_session_path)
            )
            execution_plan_contract_after = {
                "target": stored_plan.get("target"),
                "source_type": stored_plan.get("source_type"),
                "profile_group": stored_plan.get("profile_group"),
                "mode": stored_plan.get("mode"),
                "volume": stored_plan.get("volume"),
            }
            execution_plan_contract = {
                "schema_version": "reachops.execution_plan_runtime_contract.v1",
                "source": "execution_plan",
                "plan_id": stored_plan.get("plan_id"),
                "plan_fingerprint_sha256": stored_plan.get("plan_fingerprint_sha256"),
                "runtime_after_fingerprint_sha256": hashlib.sha256(
                    json.dumps(execution_plan_contract_after, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "cli_args_ignored_for_plan_fields": True,
                "before": {
                    "target": cmd[cmd.index("--target") + 1],
                    "source_type": cmd[cmd.index("--source-type") + 1],
                    "profile_group": cmd[cmd.index("--profile-group") + 1],
                    "mode": cmd[cmd.index("--mode") + 1],
                    "volume": cmd[cmd.index("--volume") + 1],
                },
                "after": execution_plan_contract_after,
                "no_ai_token_used": True,
            }
            runtime_result_risk_gate = RiskGate().evaluate(
                {"id": "aq_runtime_result_risk", "action_type": "comment_reply", "status": "approved", "execution_confirmed": 1},
                {"profile_id": "profile-result-risk", "group_name": "Canada"},
                live_submit=True,
                duplicate_text_status={"ok": False, "code": "DUPLICATE_ACTION_TEXT", "message": "same rendered text already used"},
            )
            reachops_web_ui.RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
            reachops_web_ui.RESULT_PATH.write_text(
                json.dumps(
                    {
                        "status": "started",
                        "generated_at": "2026-07-05T00:00:00Z",
                        "log_path": str(reachops_web_ui.LOG_PATH),
                        "target": stored_plan.get("target"),
                        "profile_group": stored_plan.get("profile_group"),
                        "execution_plan": {
                            "plan_id": stored_plan.get("plan_id"),
                            "schema_version": stored_plan.get("schema_version"),
                            "path": str(plan_path),
                        },
                        "execution_plan_contract": execution_plan_contract,
                        "run_session": {"path": str(run_session_path)},
                        "results": [
                            {
                                "action_id": "aq_runtime_result_risk",
                                "target_username": "target_result_risk",
                                "action_type": "comment_reply",
                                "status": "skipped",
                                "profile_id": "profile-result-risk",
                                "error_code": "DUPLICATE_ACTION_TEXT",
                                "error_message": "same rendered text already used",
                                "risk_gate": runtime_result_risk_gate,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            checks["start_closes_parent_stdout_handle"] = bool(captured["stdout_closed"])
            status, run_session_payload = _json_request(base + "/api/run-session")
            run_session_summary = run_session_payload.get("summary") or {}
            run_session_full = run_session_payload.get("run_session") or {}
            run_session_checkpoint = run_session_summary.get("checkpoint") or run_session_full.get("checkpoint") or {}
            run_session_health = run_session_full.get("session_health") or {}
            run_session_history = run_session_full.get("state_history") or []
            diagnostics["run_session_contract"] = {
                "stored": {
                    "state": stored_session.get("state"),
                    "checkpoint": stored_session.get("checkpoint") or {},
                    "state_history": stored_session.get("state_history") or [],
                    "session_health": stored_session.get("session_health") or {},
                    "pid": stored_session.get("pid"),
                },
                "api": {
                    "summary": run_session_summary,
                    "checkpoint": run_session_checkpoint,
                    "state_history": run_session_history,
                    "session_health": run_session_health,
                    "keys": sorted(run_session_payload.keys()),
                },
            }
            checks["run_session_endpoint_returns_latest_auditable_session"] = (
                status == 200
                and run_session_payload.get("status") == "ok"
                and run_session_payload.get("schema_version") == "reachops.run_session.v1"
                and run_session_payload.get("session_id") == stored_session.get("session_id")
                and run_session_payload.get("plan_id") == stored_plan.get("plan_id")
                and run_session_summary.get("state") == "PRECHECK"
                and run_session_summary.get("no_ai_token_during_execution") is True
                and run_session_checkpoint.get("state") == "PRECHECK"
                and any((row or {}).get("state") == "CREATED" for row in run_session_history)
                and any((row or {}).get("state") == "PRECHECK" for row in run_session_history)
                and all((row or {}).get("no_ai_token_used") is True for row in run_session_history)
                and run_session_health.get("schema_version") == "reachops.run_session_health.v1"
                and run_session_health.get("state") == "PRECHECK"
                and run_session_health.get("status") in {"healthy", "terminal", "paused", "idle"}
                and run_session_health.get("stale") is not True
                and (run_session_payload.get("execution_runtime_contract") or {}).get("schema_version")
                == "reachops.execution_runtime_contract.v1"
                and (run_session_payload.get("execution_runtime_contract") or {}).get("executor") == "local_program"
                and (run_session_payload.get("execution_runtime_contract") or {}).get("ai_console_is_execution_dependency") is False
                and (run_session_payload.get("ai_usage_ledger") or {}).get("schema_version") == "reachops.ai_usage_ledger.v1"
                and ((run_session_payload.get("ai_usage_ledger") or {}).get("policy") or {}).get("execution_phase_ai_calls_allowed") is False
                and ((run_session_payload.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
                and ((run_session_payload.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("token_estimate") == 0
                and run_session_payload.get("no_browser_started") is True
                and run_session_payload.get("no_submit") is True
            )

            seeded_risk_execution = seed_snapshot_risk_gate_execution(reachops_web_ui.DATA_DIR)
            status, snapshot = _json_request(base + "/api/snapshot")
            snapshot_artifacts = snapshot.get("report_artifacts") if isinstance(snapshot.get("report_artifacts"), list) else []
            snapshot_operations = snapshot.get("operations") if isinstance(snapshot.get("operations"), dict) else {}
            snapshot_outreach_view = (
                snapshot_operations.get("outreach_view")
                if isinstance(snapshot_operations.get("outreach_view"), list)
                else []
            )
            checks["snapshot_outreach_view_explains_risk_gate_to_operator"] = (
                status == 200
                and any(
                    (
                        (row or {}).get("execution_id") == seeded_risk_execution.get("execution_id")
                        or (row or {}).get("id") == seeded_risk_execution.get("execution_id")
                    )
                    and "风险门禁阻断" in str((row or {}).get("risk_gate_summary") or "")
                    and "DUPLICATE_ACTION_TEXT" in str((row or {}).get("risk_gate_summary") or "")
                    and "改写或轮换话术" in str((row or {}).get("next_step") or "")
                    for row in snapshot_outreach_view
                )
            )
            diagnostics["snapshot_risk_gate_rows"] = [
                {
                    "id": (row or {}).get("id"),
                    "execution_id": (row or {}).get("execution_id"),
                    "risk_gate_summary": (row or {}).get("risk_gate_summary"),
                    "next_step": (row or {}).get("next_step"),
                    "error_code": (row or {}).get("error_code"),
                }
                for row in snapshot_outreach_view[:5]
            ]
            diagnostics["snapshot_risk_gate_context"] = {
                "seeded": {
                    "batch_id": seeded_risk_execution.get("batch_id"),
                    "execution_id": seeded_risk_execution.get("execution_id"),
                },
                "latest_batch": snapshot.get("latest_batch"),
                "operation_counts": (snapshot_operations.get("counts") if isinstance(snapshot_operations, dict) else {}),
                "outreach_view_count": len(snapshot_outreach_view),
                "outreach_execution_count": len(snapshot_operations.get("outreach_executions") or [])
                if isinstance(snapshot_operations.get("outreach_executions"), list)
                else 0,
            }
            checks["snapshot_exposes_execution_plan_report_artifact"] = (
                status == 200
                and (snapshot.get("execution_plan") or {}).get("plan_id") == stored_plan.get("plan_id")
                and any(
                    (row or {}).get("kind") == "execution_plan"
                    and (row or {}).get("label") == "本轮执行计划 JSON"
                    and (row or {}).get("exists") is True
                    for row in snapshot_artifacts
                )
            )
            checks["snapshot_exposes_run_session_report_artifact"] = (
                status == 200
                and (snapshot.get("run_session") or {}).get("session_id") == stored_session.get("session_id")
                and any(
                    (row or {}).get("kind") == "run_session"
                    and (row or {}).get("label") == "本轮运行会话 JSON"
                    and (row or {}).get("exists") is True
                    for row in snapshot_artifacts
                )
            )
            checks["snapshot_exposes_operator_summary_homepage"] = (
                status == 200
                and ((snapshot.get("operator_summary") or {}).get("operator_summary") or {}).get("schema_version")
                == "reachops.operator_summary.v1"
                and (snapshot.get("operator_summary") or {}).get("no_browser_started") is True
                and (snapshot.get("operator_summary") or {}).get("no_submit") is True
            )
            snapshot_bundle = snapshot.get("evidence_bundle") if isinstance(snapshot.get("evidence_bundle"), dict) else {}
            checks["snapshot_exposes_evidence_bundle_contract"] = (
                status == 200
                and snapshot_bundle.get("schema_version") == "reachops.evidence_bundle.v1"
                and snapshot_bundle.get("plan_id") == stored_plan.get("plan_id")
                and snapshot_bundle.get("session_id") == stored_session.get("session_id")
                and (snapshot_bundle.get("summary") or {}).get("no_ai_token_during_execution") is True
                and (snapshot_bundle.get("account_health_summary") or {}).get("schema_version")
                == "reachops.account_health_summary.v1"
                and (snapshot_bundle.get("run_session_health") or {}).get("schema_version")
                == "reachops.run_session_health.v1"
                and (snapshot_bundle.get("run_recovery_summary") or {}).get("schema_version")
                == "reachops.run_recovery_summary.v1"
                and (snapshot_bundle.get("autonomous_execution_summary") or {}).get("schema_version")
                == "reachops.autonomous_execution_summary.v1"
                and (snapshot_bundle.get("autonomous_execution_summary") or {}).get("state_machine_contract_schema")
                == "reachops.run_session_state_machine_contract.v1"
                and (snapshot_bundle.get("autonomous_execution_summary") or {}).get("valid_state_transitions") is True
                and (snapshot_bundle.get("autonomous_execution_summary") or {}).get("state_transition_violation_count") == 0
                and (snapshot_bundle.get("autonomous_preflight_reconciliation") or {}).get("schema_version")
                == "reachops.autonomous_preflight_reconciliation.v1"
                and (snapshot_bundle.get("autonomy_readiness_summary") or {}).get("schema_version")
                == "reachops.autonomy_readiness_summary.v1"
                and (snapshot_bundle.get("product_capability_summary") or {}).get("schema_version")
                == "reachops.product_capability_summary.v1"
                and (snapshot_bundle.get("page_state_repair_coverage") or {}).get("schema_version")
                == "reachops.page_state_repair_coverage.v1"
                and (snapshot_bundle.get("page_state_repair_coverage") or {}).get("all_page_states_covered") is True
                and (snapshot_bundle.get("page_state_repair_coverage") or {}).get("uncovered_count") == 0
                and any(
                    (row or {}).get("key") == "phase_3_autonomous_execution"
                    for row in (snapshot_bundle.get("product_capability_summary") or {}).get("phases", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_health_current"
                    for row in (snapshot_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_transitions_valid"
                    for row in (snapshot_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "page_state_repair_policy_covered"
                    for row in (snapshot_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "autonomous_state_machine_core_covered"
                    for row in (snapshot_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and (snapshot_bundle.get("plan_runtime_contract") or {}).get("schema_version")
                == "reachops.plan_runtime_contract_summary.v1"
                and (snapshot_bundle.get("plan_runtime_contract") or {}).get("plan_id_matches") is True
                and (snapshot_bundle.get("plan_runtime_contract") or {}).get("plan_fingerprint_matches") is True
                and (snapshot_bundle.get("plan_runtime_contract") or {}).get("runtime_after_fingerprint_present") is True
                and (snapshot_bundle.get("plan_runtime_contract") or {}).get("cli_args_ignored_for_plan_fields") is True
                and (snapshot_bundle.get("execution_runtime_contract") or {}).get("schema_version")
                == "reachops.execution_runtime_contract_summary.v1"
                and (snapshot_bundle.get("execution_runtime_contract") or {}).get("local_program_executor") is True
                and (snapshot_bundle.get("execution_runtime_contract") or {}).get("ai_console_control_surface_only") is True
                and (snapshot_bundle.get("execution_runtime_contract") or {}).get("execution_phase_ai_calls_disallowed") is True
                and (snapshot_bundle.get("execution_runtime_contract") or {}).get("ai_usage_policy_matches_contract") is True
                and (snapshot_bundle.get("ai_usage_summary") or {}).get("execution_phase_ai_call_count") == 0
                and (snapshot_bundle.get("ai_usage_summary") or {}).get("execution_phase_token_estimate") == 0
                and any(
                    (row or {}).get("kind") == "evidence_bundle"
                    and (row or {}).get("label") == "本轮证据包 JSON"
                    and (row or {}).get("exists") is True
                    for row in snapshot_artifacts
                )
            )

            status, logs = _json_request(base + "/api/logs")
            checks["logs_report_running_state"] = status == 200 and logs.get("running") is True
            checks["logs_expose_run_session_state"] = (
                status == 200
                and (logs.get("run_session") or {}).get("schema_version") == "reachops.run_session.v1"
                and logs.get("run_session_state") in {"PRECHECK", "PROFILE_OPENING", "COLLECTING", "SCORING", "ACTION_PLANNING", "REPAIRING"}
            )
            logs_bundle = logs.get("evidence_bundle") or {}
            checks["logs_expose_evidence_bundle_contract"] = (
                status == 200
                and logs_bundle.get("schema_version") == "reachops.evidence_bundle.v1"
                and logs_bundle.get("plan_id") == stored_plan.get("plan_id")
                and logs_bundle.get("session_id") == stored_session.get("session_id")
                and (logs_bundle.get("summary") or {}).get("no_ai_token_during_execution") is True
                and (logs_bundle.get("page_state_summary") or {}).get("schema_version") == "reachops.page_state_summary.v1"
                and (logs_bundle.get("repair_summary") or {}).get("schema_version") == "reachops.repair_summary.v1"
                and (logs_bundle.get("risk_summary") or {}).get("schema_version") == "reachops.risk_summary.v1"
                and (logs_bundle.get("account_health_summary") or {}).get("schema_version")
                == "reachops.account_health_summary.v1"
                and (logs_bundle.get("run_session_health") or {}).get("schema_version")
                == "reachops.run_session_health.v1"
                and (logs_bundle.get("run_recovery_summary") or {}).get("schema_version")
                == "reachops.run_recovery_summary.v1"
                and (logs_bundle.get("autonomous_execution_summary") or {}).get("schema_version")
                == "reachops.autonomous_execution_summary.v1"
                and (logs_bundle.get("autonomous_execution_summary") or {}).get("state_machine_contract_schema")
                == "reachops.run_session_state_machine_contract.v1"
                and (logs_bundle.get("autonomous_execution_summary") or {}).get("valid_state_transitions") is True
                and (logs_bundle.get("autonomous_execution_summary") or {}).get("state_transition_violation_count") == 0
                and (logs_bundle.get("autonomous_preflight_reconciliation") or {}).get("schema_version")
                == "reachops.autonomous_preflight_reconciliation.v1"
                and (logs_bundle.get("autonomy_readiness_summary") or {}).get("schema_version")
                == "reachops.autonomy_readiness_summary.v1"
                and (logs_bundle.get("product_capability_summary") or {}).get("schema_version")
                == "reachops.product_capability_summary.v1"
                and (logs_bundle.get("page_state_repair_coverage") or {}).get("schema_version")
                == "reachops.page_state_repair_coverage.v1"
                and (logs_bundle.get("page_state_repair_coverage") or {}).get("all_page_states_covered") is True
                and (logs_bundle.get("page_state_repair_coverage") or {}).get("uncovered_count") == 0
                and any(
                    (row or {}).get("key") == "phase_3_autonomous_execution"
                    for row in (logs_bundle.get("product_capability_summary") or {}).get("phases", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_health_current"
                    for row in (logs_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_transitions_valid"
                    for row in (logs_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "page_state_repair_policy_covered"
                    for row in (logs_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "autonomous_state_machine_core_covered"
                    for row in (logs_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and (logs_bundle.get("plan_runtime_contract") or {}).get("schema_version")
                == "reachops.plan_runtime_contract_summary.v1"
                and (logs_bundle.get("plan_runtime_contract") or {}).get("plan_id_matches") is True
                and (logs_bundle.get("plan_runtime_contract") or {}).get("plan_fingerprint_matches") is True
                and (logs_bundle.get("plan_runtime_contract") or {}).get("runtime_after_fingerprint_present") is True
                and (logs_bundle.get("plan_runtime_contract") or {}).get("cli_args_ignored_for_plan_fields") is True
                and (logs_bundle.get("execution_runtime_contract") or {}).get("schema_version")
                == "reachops.execution_runtime_contract_summary.v1"
                and (logs_bundle.get("execution_runtime_contract") or {}).get("local_program_executor") is True
                and (logs_bundle.get("execution_runtime_contract") or {}).get("ai_console_control_surface_only") is True
                and (logs_bundle.get("execution_runtime_contract") or {}).get("execution_phase_ai_calls_disallowed") is True
                and (logs_bundle.get("execution_runtime_contract") or {}).get("ai_usage_policy_matches_contract") is True
                and isinstance(logs_bundle.get("artifacts"), list)
            )

            status, evidence_bundle = _json_request(base + "/api/evidence-bundle")
            operator_risk_summary = evidence_bundle.get("operator_risk_gate_summary") or {}
            checks["evidence_bundle_endpoint_returns_auditable_run_index"] = (
                status == 200
                and evidence_bundle.get("schema_version") == "reachops.evidence_bundle.v1"
                and evidence_bundle.get("plan_id") == stored_plan.get("plan_id")
                and evidence_bundle.get("session_id") == stored_session.get("session_id")
                and isinstance(evidence_bundle.get("timeline"), list)
                and isinstance(evidence_bundle.get("artifacts"), list)
                and (evidence_bundle.get("operator_summary") or {}).get("schema_version") == "reachops.operator_summary.v1"
                and (evidence_bundle.get("repair_summary") or {}).get("schema_version") == "reachops.repair_summary.v1"
                and (evidence_bundle.get("risk_summary") or {}).get("schema_version") == "reachops.risk_summary.v1"
                and (evidence_bundle.get("account_health_summary") or {}).get("schema_version")
                == "reachops.account_health_summary.v1"
                and (evidence_bundle.get("run_session_health") or {}).get("schema_version")
                == "reachops.run_session_health.v1"
                and (evidence_bundle.get("run_recovery_summary") or {}).get("schema_version")
                == "reachops.run_recovery_summary.v1"
                and (evidence_bundle.get("autonomous_execution_summary") or {}).get("schema_version")
                == "reachops.autonomous_execution_summary.v1"
                and (evidence_bundle.get("autonomous_execution_summary") or {}).get("state_machine_contract_schema")
                == "reachops.run_session_state_machine_contract.v1"
                and (evidence_bundle.get("autonomous_execution_summary") or {}).get("valid_state_transitions") is True
                and (evidence_bundle.get("autonomous_execution_summary") or {}).get("state_transition_violation_count") == 0
                and (evidence_bundle.get("autonomous_preflight_reconciliation") or {}).get("schema_version")
                == "reachops.autonomous_preflight_reconciliation.v1"
                and (evidence_bundle.get("autonomy_readiness_summary") or {}).get("schema_version")
                == "reachops.autonomy_readiness_summary.v1"
                and (evidence_bundle.get("product_capability_summary") or {}).get("schema_version")
                == "reachops.product_capability_summary.v1"
                and (evidence_bundle.get("page_state_repair_coverage") or {}).get("schema_version")
                == "reachops.page_state_repair_coverage.v1"
                and (evidence_bundle.get("page_state_repair_coverage") or {}).get("all_page_states_covered") is True
                and (evidence_bundle.get("page_state_repair_coverage") or {}).get("uncovered_count") == 0
                and any(
                    (row or {}).get("key") == "phase_3_autonomous_execution"
                    for row in (evidence_bundle.get("product_capability_summary") or {}).get("phases", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_health_current"
                    for row in (evidence_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "run_session_transitions_valid"
                    for row in (evidence_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "page_state_repair_policy_covered"
                    for row in (evidence_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and any(
                    (row or {}).get("name") == "autonomous_state_machine_core_covered"
                    for row in (evidence_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])
                )
                and (evidence_bundle.get("plan_runtime_contract") or {}).get("schema_version")
                == "reachops.plan_runtime_contract_summary.v1"
                and (evidence_bundle.get("plan_runtime_contract") or {}).get("plan_id_matches") is True
                and (evidence_bundle.get("plan_runtime_contract") or {}).get("plan_fingerprint_matches") is True
                and (evidence_bundle.get("plan_runtime_contract") or {}).get("runtime_after_fingerprint_present") is True
                and (evidence_bundle.get("plan_runtime_contract") or {}).get("cli_args_ignored_for_plan_fields") is True
                and (evidence_bundle.get("execution_runtime_contract") or {}).get("schema_version")
                == "reachops.execution_runtime_contract_summary.v1"
                and (evidence_bundle.get("execution_runtime_contract") or {}).get("local_program_executor") is True
                and (evidence_bundle.get("execution_runtime_contract") or {}).get("ai_console_control_surface_only") is True
                and (evidence_bundle.get("execution_runtime_contract") or {}).get("execution_phase_ai_calls_disallowed") is True
                and (evidence_bundle.get("execution_runtime_contract") or {}).get("ai_usage_policy_matches_contract") is True
                and Path((evidence_bundle.get("execution_plan") or {}).get("path") or "").is_file()
                and (evidence_bundle.get("page_state_summary") or {}).get("schema_version") == "reachops.page_state_summary.v1"
                and (evidence_bundle.get("control_summary") or {}).get("schema_version") == "reachops.control_summary.v1"
                and operator_risk_summary.get("schema_version") == "reachops.operator_risk_gate_summary.v1"
                and operator_risk_summary.get("no_ai_token_used") is True
                and int(operator_risk_summary.get("blocked_count") or 0) > 0
                and "DUPLICATE_ACTION_TEXT" in str(operator_risk_summary.get("primary_reason") or "")
                and "改写或轮换话术" in str(operator_risk_summary.get("primary_next_step") or "")
                and (evidence_bundle.get("ai_usage_summary") or {}).get("schema_version") == "reachops.ai_usage_summary.v1"
                and (evidence_bundle.get("ai_usage_summary") or {}).get("execution_phase_ai_call_count") == 0
                and (evidence_bundle.get("ai_usage_summary") or {}).get("execution_phase_token_estimate") == 0
                and (evidence_bundle.get("audit") or {}).get("no_ai_token_during_execution") is True
            )
            status, operator_summary = _json_request(base + "/api/operator-summary")
            checks["operator_summary_endpoint_returns_report_homepage"] = (
                status == 200
                and operator_summary.get("schema_version") == "reachops.operator_summary.v1"
                and (operator_summary.get("operator_summary") or {}).get("schema_version") == "reachops.operator_summary.v1"
                and operator_summary.get("no_ai_token_used") is True
                and operator_summary.get("no_browser_started") is True
                and operator_summary.get("no_submit") is True
                and bool(operator_summary.get("evidence_bundle_markdown_path"))
            )
            status, product_capability = _json_request(base + "/api/product-capability")
            product_summary = product_capability.get("product_capability_summary") or {}
            product_goals = product_capability.get("product_development_goals") or {}
            product_boundary = product_capability.get("delivery_boundary") or {}
            diagnostics["product_delivery_boundary"] = product_boundary
            checks["product_capability_endpoint_returns_phase_matrix"] = (
                status == 200
                and product_capability.get("schema_version") == "reachops.product_capability_summary.v1"
                and product_summary.get("schema_version") == "reachops.product_capability_summary.v1"
                and product_goals.get("schema_version") == "reachops.product_development_goals.v1"
                and product_goals.get("stage_count") == 8
                and isinstance(product_goals.get("current_focus"), dict)
                and isinstance(product_goals.get("stages"), list)
                and any(
                    (row or {}).get("key") == "phase_2_execution_plan_standardized"
                    and isinstance((row or {}).get("acceptance"), list)
                    and isinstance((row or {}).get("evidence"), list)
                    for row in product_goals.get("stages", [])
                )
                and any(
                    (row or {}).get("key") == "phase_3_autonomous_execution"
                    for row in product_summary.get("phases", [])
                )
                and (product_capability.get("autonomy_readiness_summary") or {}).get("schema_version")
                == "reachops.autonomy_readiness_summary.v1"
                and (product_capability.get("autonomous_execution_summary") or {}).get("schema_version")
                == "reachops.autonomous_execution_summary.v1"
                and (product_capability.get("operator_summary") or {}).get("schema_version")
                == "reachops.operator_summary.v1"
                and product_capability.get("no_ai_token_used") is True
                and product_capability.get("no_browser_started") is True
                and product_capability.get("no_submit") is True
                and bool(product_capability.get("evidence_bundle_download_url"))
                and bool(product_capability.get("evidence_bundle_markdown_download_url"))
            )
            checks["product_capability_exposes_delivery_boundary"] = (
                status == 200
                and product_boundary.get("schema_version") == "reachops.delivery_boundary.v1"
                and product_boundary.get("local_product_capability_ready")
                == bool(product_summary.get("ready") and product_goals.get("ready"))
                and product_boundary.get("final_delivery_ready") is False
                and product_boundary.get("external_validation_pending") is True
                and product_boundary.get("windows_final_artifacts_pending") is True
                and (product_boundary.get("final_delivery_evidence_plan") or {}).get("schema_version")
                == "reachops.final_delivery_evidence_plan.v1"
                and isinstance((product_boundary.get("final_delivery_evidence_plan") or {}).get("items"), list)
                and "external_authorized_execution"
                in ((product_boundary.get("final_delivery_evidence_plan") or {}).get("pending_scopes") or [])
                and {"external_authorized_execution", "windows_final_artifacts"}.issubset(
                    set(product_boundary.get("pending_scopes") or [])
                )
                and product_capability.get("delivery_boundary_status") == product_boundary.get("status")
                and product_capability.get("local_product_capability_ready")
                == product_boundary.get("local_product_capability_ready")
                and product_capability.get("product_capability_ready") == product_boundary.get("product_capability_ready")
                and product_capability.get("product_development_ready") == product_boundary.get("product_development_ready")
                and product_capability.get("final_delivery_ready") is False
                and product_capability.get("external_validation_pending") is True
                and product_capability.get("windows_final_artifacts_pending") is True
                and set(product_capability.get("pending_scopes") or []) == set(product_boundary.get("pending_scopes") or [])
                and product_boundary.get("no_browser_started") is True
                and product_boundary.get("no_submit") is True
            )
            status, ai_recap = _json_request(
                base + "/api/ai-console",
                {
                    "message": "复盘这次执行",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            recap_bundle = ai_recap.get("evidence_bundle") or {}
            recap_operator_risk = recap_bundle.get("operator_risk_gate_summary") or {}
            ai_recap_contract = {
                "status_200": status == 200,
                "intent_run_recap": ai_recap.get("intent") == "run_recap",
                "top_level_no_ai_token": ai_recap.get("no_ai_token_used") is True,
                "top_level_no_browser": ai_recap.get("no_browser_started") is True,
                "top_level_no_submit": ai_recap.get("no_submit") is True,
                "summary_no_ai": (recap_bundle.get("summary") or {}).get("no_ai_token_during_execution") is True,
                "repair_schema": (recap_bundle.get("repair_summary") or {}).get("schema_version") == "reachops.repair_summary.v1",
                "risk_schema": (recap_bundle.get("risk_summary") or {}).get("schema_version") == "reachops.risk_summary.v1",
                "account_schema": (recap_bundle.get("account_health_summary") or {}).get("schema_version") == "reachops.account_health_summary.v1",
                "health_schema": (recap_bundle.get("run_session_health") or {}).get("schema_version") == "reachops.run_session_health.v1",
                "run_recovery_schema": (recap_bundle.get("run_recovery_summary") or {}).get("schema_version")
                == "reachops.run_recovery_summary.v1",
                "autonomous_schema": (recap_bundle.get("autonomous_execution_summary") or {}).get("schema_version") == "reachops.autonomous_execution_summary.v1",
                "preflight_forecast_schema": (recap_bundle.get("autonomous_preflight_forecast") or {}).get("schema_version")
                == "reachops.autonomous_preflight_forecast_summary.v1",
                "preflight_forecast_exists": (recap_bundle.get("autonomous_preflight_forecast") or {}).get("exists") is True,
                "preflight_reconciliation_schema": (
                    recap_bundle.get("autonomous_preflight_reconciliation") or {}
                ).get("schema_version")
                == "reachops.autonomous_preflight_reconciliation.v1",
                "autonomy_schema": (recap_bundle.get("autonomy_readiness_summary") or {}).get("schema_version") == "reachops.autonomy_readiness_summary.v1",
                "product_schema": (recap_bundle.get("product_capability_summary") or {}).get("schema_version") == "reachops.product_capability_summary.v1",
                "phase_3_present": any((row or {}).get("key") == "phase_3_autonomous_execution" for row in (recap_bundle.get("product_capability_summary") or {}).get("phases", [])),
                "health_check_present": any((row or {}).get("name") == "run_session_health_current" for row in (recap_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])),
                "autonomous_core_check_present": any((row or {}).get("name") == "autonomous_state_machine_core_covered" for row in (recap_bundle.get("autonomy_readiness_summary") or {}).get("checks", [])),
                "plan_contract_schema": (recap_bundle.get("plan_runtime_contract") or {}).get("schema_version") == "reachops.plan_runtime_contract_summary.v1",
                "plan_id_matches": (recap_bundle.get("plan_runtime_contract") or {}).get("plan_id_matches") is True,
                "plan_fingerprint_matches": (recap_bundle.get("plan_runtime_contract") or {}).get("plan_fingerprint_matches") is True,
                "runtime_after_present": (recap_bundle.get("plan_runtime_contract") or {}).get("runtime_after_fingerprint_present") is True,
                "cli_ignored": (recap_bundle.get("plan_runtime_contract") or {}).get("cli_args_ignored_for_plan_fields") is True,
                "page_schema": (recap_bundle.get("page_state_summary") or {}).get("schema_version") == "reachops.page_state_summary.v1",
                "ai_usage_schema": (recap_bundle.get("ai_usage_summary") or {}).get("schema_version") == "reachops.ai_usage_summary.v1",
                "ai_usage_zero": (recap_bundle.get("ai_usage_summary") or {}).get("execution_phase_token_estimate") == 0,
                "operator_risk_schema": recap_operator_risk.get("schema_version") == "reachops.operator_risk_gate_summary.v1",
                "operator_risk_blocked": int(recap_operator_risk.get("blocked_count") or 0) > 0,
                "operator_risk_reason": "DUPLICATE_ACTION_TEXT" in str(recap_operator_risk.get("primary_reason") or ""),
                "operator_risk_next_step": "改写或轮换话术" in str(recap_operator_risk.get("primary_next_step") or ""),
                "reply_includes_operator_risk": "运营风险门禁" in str(ai_recap.get("reply") or ""),
                "bundle_id": bool(recap_bundle.get("bundle_id")),
                "operator_schema": (recap_bundle.get("operator_summary") or {}).get("schema_version") == "reachops.operator_summary.v1",
                "machine_actions_list": isinstance(ai_recap.get("machine_actions"), list),
                "machine_actions_include_operator_risk_next_step": any(
                    "证据包运营下一步" in str(row) for row in (ai_recap.get("machine_actions") or [])
                ),
                "machine_actions_include_preflight_forecast": any(
                    "启动前自治预判" in str(row) for row in (ai_recap.get("machine_actions") or [])
                ),
                "machine_actions_include_preflight_reconciliation": any(
                    "预判对账" in str(row) for row in (ai_recap.get("machine_actions") or [])
                ),
                "timeline_summary_list": isinstance(ai_recap.get("timeline_summary"), list),
                "timeline_summary_include_preflight_chain": any(
                    "预判状态链" in str(row) for row in (ai_recap.get("timeline_summary") or [])
                ),
                "bundle_timeline_summary_list": isinstance(recap_bundle.get("timeline_summary"), list),
            }
            diagnostics["ai_recap_contract"] = ai_recap_contract
            checks["ai_console_recaps_evidence_bundle_without_tokens"] = (
                all(ai_recap_contract.values())
            )
            status, ai_status = _json_request(
                base + "/api/ai-console",
                {
                    "message": "为什么停了",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            diagnostics["ai_status_contract_sample"] = {
                "status": status,
                "intent": ai_status.get("intent"),
                "reply": str(ai_status.get("reply") or "")[:800],
                "next_actions": list(ai_status.get("next_actions") or [])[:12],
            }
            checks["ai_console_explains_status_from_operator_summary"] = (
                status == 200
                and ai_status.get("intent") == "explain_status"
                and ai_status.get("no_ai_token_used") is True
                and ai_status.get("no_browser_started") is True
                and ai_status.get("no_submit") is True
                and "客户端门禁下一步" in str(ai_status.get("reply") or "")
                and isinstance(ai_status.get("client_delivery"), dict)
                and isinstance(ai_status.get("client_delivery_summary"), dict)
                and (ai_status.get("client_delivery_summary") or {}).get("no_ai_token_used") is True
                and (ai_status.get("client_delivery_summary") or {}).get("no_browser_started") is True
                and (ai_status.get("client_delivery_summary") or {}).get("no_submit") is True
                and int((ai_status.get("client_delivery_summary") or {}).get("next_action_count") or 0) > 0
                and any(
                    any(token in str(row) for token in ["ixBrowser", "账号", "修复", "重新预检", "内核"])
                    for row in (ai_status.get("next_actions") or [])
                )
                and (ai_status.get("operator_summary") or {}).get("schema_version") == "reachops.operator_summary.v1"
                and ((ai_status.get("evidence_bundle") or {}).get("operator_summary") or {}).get("schema_version")
                == "reachops.operator_summary.v1"
                and isinstance(ai_status.get("machine_actions"), list)
                and isinstance(ai_status.get("timeline_summary"), list)
                and isinstance(((ai_status.get("evidence_bundle") or {}).get("timeline_summary")), list)
            )
            checks["ai_console_explains_operator_risk_gate_from_operations"] = (
                status == 200
                and (ai_status.get("operations_risk_gate_summary") or {}).get("schema_version")
                == "reachops.operations_risk_gate_summary.v1"
                and int((ai_status.get("operations_risk_gate_summary") or {}).get("blocked_count") or 0) > 0
                and "DUPLICATE_ACTION_TEXT" in str((ai_status.get("operations_risk_gate_summary") or {}).get("primary_reason") or "")
                and any("运营触达下一步" in str(row) for row in (ai_status.get("machine_actions") or []))
                and "运营触达表显示" in str(ai_status.get("reply") or "")
            )
            status, ai_capability = _json_request(
                base + "/api/ai-console",
                {
                    "message": "产品能力矩阵现在做到哪了",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            checks["ai_console_explains_product_capability_matrix"] = (
                status == 200
                and ai_capability.get("intent") == "product_capability_status"
                and ai_capability.get("no_ai_token_used") is True
                and ai_capability.get("no_browser_started") is True
                and ai_capability.get("no_submit") is True
                and (ai_capability.get("product_capability_summary") or {}).get("schema_version")
                == "reachops.product_capability_summary.v1"
                and ((ai_capability.get("evidence_bundle") or {}).get("product_capability_summary") or {}).get("schema_version")
                == "reachops.product_capability_summary.v1"
                and (ai_capability.get("product_development_goals") or {}).get("schema_version")
                == "reachops.product_development_goals.v1"
                and ((ai_capability.get("evidence_bundle") or {}).get("product_development_goals") or {}).get("stage_count") == 8
                and (ai_capability.get("delivery_boundary") or {}).get("schema_version") == "reachops.delivery_boundary.v1"
                and (ai_capability.get("delivery_boundary") or {}).get("final_delivery_ready") is False
                and (ai_capability.get("final_delivery_evidence_plan") or {}).get("schema_version")
                == "reachops.final_delivery_evidence_plan.v1"
                and ((ai_capability.get("evidence_bundle") or {}).get("final_delivery_evidence_plan") or {}).get("schema_version")
                == "reachops.final_delivery_evidence_plan.v1"
                and ((ai_capability.get("evidence_bundle") or {}).get("delivery_boundary") or {}).get("external_validation_pending")
                is True
                and any(
                    (row or {}).get("key") == "phase_3_autonomous_execution"
                    for row in (ai_capability.get("product_capability_summary") or {}).get("phases", [])
                )
                and "产品能力矩阵" in str(ai_capability.get("reply") or "")
                and "当前开发目标" in str(ai_capability.get("reply") or "")
                and "交付边界" in str(ai_capability.get("reply") or "")
                and "待补证据" in str(ai_capability.get("reply") or "")
                and isinstance(ai_capability.get("machine_actions"), list)
                and isinstance(ai_capability.get("timeline_summary"), list)
            )
            status, ai_final_gap = _json_request(
                base + "/api/ai-console",
                {
                    "message": "最终交付还差什么证据",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            checks["ai_console_answers_final_delivery_evidence_gap_without_tokens"] = (
                status == 200
                and ai_final_gap.get("intent") == "product_capability_status"
                and ai_final_gap.get("no_ai_token_used") is True
                and ai_final_gap.get("no_browser_started") is True
                and ai_final_gap.get("no_submit") is True
                and (ai_final_gap.get("final_delivery_evidence_plan") or {}).get("schema_version")
                == "reachops.final_delivery_evidence_plan.v1"
                and "最终交付" in str(ai_final_gap.get("reply") or "")
                and "待补证据" in str(ai_final_gap.get("reply") or "")
                and isinstance(ai_final_gap.get("next_actions"), list)
            )
            status, offline_learning = _json_request(base + "/api/offline-learning")
            checks["offline_learning_endpoint_is_local_read_only"] = (
                status == 200
                and offline_learning.get("schema_version") == "reachops.offline_learning.v1"
                and offline_learning.get("no_ai_token_used") is True
                and offline_learning.get("no_browser_started") is True
                and offline_learning.get("no_submit") is True
                and isinstance(offline_learning.get("records"), list)
                and (offline_learning.get("policy_candidates") or {}).get("schema_version") == "reachops.offline_policy_candidates.v1"
                and (offline_learning.get("policy_candidates") or {}).get("candidate_count") >= 1
                and (offline_learning.get("policy_review_summary") or {}).get("schema_version") == "reachops.offline_policy_review.v1"
                and (offline_learning.get("policy_release_proposal") or {}).get("schema_version")
                == "reachops.offline_policy_release_proposal.v1"
                and (offline_learning.get("policy_release_proposal") or {}).get("runtime_auto_apply_count") == 0
            )
            status, offline_review = _json_request(
                base + "/api/offline-learning/review",
                {
                    "candidate_state": "LOGIN_REQUIRED",
                    "candidate_action": "cooldown_profile_and_switch",
                    "decision": "approved",
                    "reviewer": "runtime_smoke",
                    "note": "Repeated login wall evidence.",
                },
            )
            status, offline_learning_after_review = _json_request(base + "/api/offline-learning")
            status, evidence_bundle_after_review = _json_request(base + "/api/evidence-bundle")
            evidence_review_summary = (evidence_bundle_after_review.get("offline_learning") or {}).get("policy_review_summary") or {}
            checks["offline_learning_review_records_human_decision_without_runtime_apply"] = (
                status == 200
                and offline_review.get("status") == "review_recorded"
                and offline_review.get("no_ai_token_used") is True
                and offline_review.get("no_browser_started") is True
                and offline_review.get("no_submit") is True
                and (offline_review.get("review") or {}).get("decision") == "approved"
                and (offline_review.get("review") or {}).get("auto_apply") is False
                and (offline_review.get("review") or {}).get("runtime_effect") == "review_recorded_only"
                and (offline_review.get("policy_release_proposal") or {}).get("schema_version")
                == "reachops.offline_policy_release_proposal.v1"
                and ((offline_review.get("policy_release_proposal") or {}).get("ready_for_release_count") or 0) >= 1
                and ((offline_review.get("policy_release_proposal") or {}).get("runtime_auto_apply_count") or 0) == 0
                and ((offline_learning_after_review.get("policy_review_summary") or {}).get("approved_count") or 0) >= 1
                and ((offline_learning_after_review.get("policy_review_summary") or {}).get("runtime_auto_apply_count") or 0) == 0
                and ((offline_learning_after_review.get("policy_release_proposal") or {}).get("ready_for_release_count") or 0) >= 1
                and ((offline_learning_after_review.get("policy_release_proposal") or {}).get("runtime_auto_apply_count") or 0) == 0
                and (evidence_bundle_after_review.get("audit") or {}).get("offline_policy_review_count", 0) >= 1
                and (evidence_bundle_after_review.get("audit") or {}).get("offline_policy_approved_count", 0) >= 1
                and (evidence_bundle_after_review.get("audit") or {}).get("offline_policy_runtime_auto_apply_count") == 0
                and (evidence_bundle_after_review.get("audit") or {}).get("offline_policy_release_ready_count", 0) >= 1
                and (evidence_bundle_after_review.get("audit") or {}).get("offline_policy_release_runtime_auto_apply_count") == 0
                and (evidence_bundle_after_review.get("operator_summary") or {}).get("proof", {}).get("offline_policy_runtime_auto_apply_count") == 0
                and (evidence_bundle_after_review.get("operator_summary") or {}).get("proof", {}).get("offline_policy_release_runtime_auto_apply_count") == 0
                and evidence_review_summary.get("runtime_auto_apply_count") == 0
                and any(
                    (row or {}).get("review_status") == "approved" and (row or {}).get("auto_apply") is False
                    for row in ((offline_learning_after_review.get("policy_candidates") or {}).get("candidates") or [])
                )
            )
            status, ai_unknown = _json_request(
                base + "/api/ai-console",
                {
                    "message": "分析未知错误",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "Canada",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                },
            )
            checks["ai_console_analyzes_offline_learning_without_tokens"] = (
                status == 200
                and ai_unknown.get("intent") == "unknown_state_analysis"
                and ai_unknown.get("no_ai_token_used") is True
                and ai_unknown.get("no_browser_started") is True
                and ai_unknown.get("no_submit") is True
                and (ai_unknown.get("offline_learning") or {}).get("no_ai_token_used") is True
                and isinstance((ai_unknown.get("offline_learning") or {}).get("records"), list)
                and ((ai_unknown.get("offline_learning") or {}).get("policy_candidates") or {}).get("schema_version")
                == "reachops.offline_policy_candidates.v1"
                and ((ai_unknown.get("offline_learning") or {}).get("policy_review_summary") or {}).get("approved_count") >= 1
                and any("offline_learning" in str(row) for row in (ai_unknown.get("machine_actions") or []))
                and any("人工复核" in str(row) or "runtime_auto_apply=0" in str(row) for row in (ai_unknown.get("machine_actions") or []))
                and any("UNKNOWN_PAGE_STATE" in str(row) or "候选规则" in str(row) for row in (ai_unknown.get("timeline_summary") or []))
            )

            status, activation = _json_request(base + "/api/activation")
            checks["activation_endpoint_reports_no_browser_no_submit"] = (
                status == 200
                and activation.get("no_browser_started") is True
                and activation.get("no_submit") is True
                and isinstance(activation.get("next_actions"), list)
                and isinstance(activation.get("failed_checks"), list)
            )

            status, ix_status = _json_request(base + "/api/ixbrowser-status")
            checks["ixbrowser_status_endpoint_reports_no_browser_no_submit"] = (
                status == 200
                and ix_status.get("ready") is False
                and ix_status.get("no_browser_started") is True
                and ix_status.get("no_submit") is True
                and "53200" in str(ix_status.get("base_url") or "")
                and bool(ix_status.get("next_actions"))
            )

            status, ix_config = _json_request(base + "/api/ixbrowser-config", {"port": 53201})
            status_after_config, ix_status_after_config = _json_request(base + "/api/ixbrowser-status")
            checks["ixbrowser_port_config_updates_runtime_status"] = (
                status == 200
                and ix_config.get("status") == "saved"
                and ix_config.get("no_browser_started") is True
                and ix_config.get("no_submit") is True
                and status_after_config == 200
                and "53201" in str(ix_status_after_config.get("base_url") or "")
                and reachops_web_ui.WEB_SETTINGS_PATH.is_file()
                and '"ixbrowser_api_port": 53201' in reachops_web_ui.WEB_SETTINGS_PATH.read_text(encoding="utf-8")
            )
            reachops_web_ui.IXBROWSER_API_PORT_OVERRIDE = ""
            reachops_web_ui.os.environ.pop("REACHOPS_IXBROWSER_API_PORT", None)
            reachops_web_ui.initialize_ixbrowser_api_port_from_settings()
            checks["ixbrowser_port_config_persists_across_restart"] = (
                reachops_web_ui.IXBROWSER_API_PORT_OVERRIDE == "53201"
                and reachops_web_ui.os.environ.get("REACHOPS_IXBROWSER_API_PORT") == "53201"
            )

            status, final_status = _json_request(base + "/api/final-status")
            diagnostics["final_status"] = final_status
            checks["final_status_endpoint_reports_no_browser_no_submit"] = (
                status == 200
                and final_status.get("no_browser_started") is True
                and final_status.get("no_submit") is True
                and final_status.get("final_delivery_ready") is False
                and (final_status.get("final_delivery_evidence_plan") or {}).get("schema_version")
                == "reachops.final_delivery_evidence_plan.v1"
                and isinstance((final_status.get("final_delivery_evidence_plan") or {}).get("items"), list)
                and final_status.get("delivery_boundary_status")
                == (final_status.get("delivery_boundary") or {}).get("status")
                and final_status.get("local_product_capability_ready")
                == (final_status.get("delivery_boundary") or {}).get("local_product_capability_ready")
                and final_status.get("product_capability_ready")
                == bool((final_status.get("product_capability_summary") or {}).get("ready"))
                and final_status.get("product_development_ready")
                == bool((final_status.get("product_development_goals") or {}).get("ready"))
                and final_status.get("external_validation_pending") is True
                and final_status.get("windows_final_artifacts_pending") is True
                and set(final_status.get("pending_scopes") or [])
                >= {"external_authorized_execution", "windows_final_artifacts"}
                and (final_status.get("delivery_boundary") or {}).get("schema_version") == "reachops.delivery_boundary.v1"
                and (final_status.get("mvp_acceptance") or {}).get("mvp_local_ready") is True
                and (final_status.get("goal_delivery") or {}).get("windows_build_ready") is True
                and (final_status.get("goal_delivery") or {}).get("final_delivery_ready") is False
                and ((final_status.get("goal_delivery") or {}).get("delivery_boundary") or {}).get("overall_final_delivery_scope_ready") is False
                and (final_status.get("goal_delivery") or {}).get("summary_path") == str(reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH)
                and {row.get("scope") for row in ((final_status.get("goal_delivery") or {}).get("final_delivery_blockers") or [])}
                == {"external_authorized_execution", "windows_final_artifacts"}
                and (final_status.get("two_phase_acceptance") or {}).get("local_mvp_ready") is True
                and (final_status.get("two_phase_acceptance") or {}).get("final_delivery_ready") is False
                and any((row or {}).get("stage") == "授权输入" for row in final_status.get("blocking_plan") or [])
            )

            template_status, template_body, template_headers = _raw_request(base + "/api/acceptance-input-template")
            checks["acceptance_input_template_download_is_available"] = (
                template_status == 200
                and b"reachops_acceptance_inputs.local.ps1" in template_body
                and b"RunControlledLiveSubmit" in template_body
                and "reachops_acceptance_inputs.example.ps1" in template_headers.get("Content-Disposition", "")
            )

            status, mvp_refresh = _json_request(base + "/api/mvp-acceptance-refresh", {})
            checks["mvp_acceptance_refresh_endpoint_generates_summary"] = (
                status == 200
                and mvp_refresh.get("status") == "mvp_accepted_external_pending"
                and mvp_refresh.get("mvp_local_ready") is True
                and reachops_mvp_acceptance_summary.OUT_PATH.is_file()
            )

            status, goal_refresh = _json_request(base + "/api/goal-delivery-refresh", {})
            checks["goal_delivery_refresh_endpoint_generates_target_report"] = (
                status == 200
                and goal_refresh.get("status") == "local_mvp_accepted_final_pending"
                and goal_refresh.get("local_mvp_ready") is True
                and goal_refresh.get("windows_build_ready") is True
                and goal_refresh.get("final_delivery_ready") is False
                and ((goal_refresh.get("sections") or {}).get("windows_package_preflight") or {}).get("payload", {}).get("ready_for_windows_build") is True
                and reachops_goal_delivery_runner.OUT_PATH.is_file()
                and reachops_goal_delivery_runner.SUMMARY_PATH.is_file()
            )
            summary_status, summary_body, summary_headers = _raw_request(
                base + "/api/download?path=" + quote(str(reachops_goal_delivery_runner.SUMMARY_PATH), safe="")
            )
            checks["goal_delivery_summary_download_is_available"] = (
                summary_status == 200
                and b"ReachOps" in summary_body
                and b"final_delivery_ready" in summary_body
                and "text/markdown" in summary_headers.get("Content-Type", "")
            )

            status, duplicate = _json_request(base + "/api/start", {"target": "another target"})
            checks["duplicate_start_reports_existing_pid"] = status == 200 and duplicate.get("status") == "already_running"

            pause_signal = getattr(signal, "SIGSTOP", None)
            resume_signal = getattr(signal, "SIGCONT", None)
            if pause_signal is None:
                status, paused = _json_request(base + "/api/control", {"action": "pause"})
                checks["control_pause_reaches_process_signal"] = (
                    status == 200 and paused.get("status") == "paused" and paused.get("cooperative_control") is True
                )
                checks["control_pause_updates_run_session_without_tokens"] = (
                    status == 200
                    and ((paused.get("run_session") or {}).get("control") or {}).get("last_action") == "pause"
                    and ((paused.get("run_session") or {}).get("control") or {}).get("current_paused") is True
                    and ((paused.get("run_session") or {}).get("control") or {}).get("cooperative_control") is True
                    and (((paused.get("run_session") or {}).get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
                    and (((paused.get("run_session") or {}).get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("token_estimate") == 0
                )
            else:
                status, paused = _json_request(base + "/api/control", {"action": "pause"})
                checks["control_pause_reaches_process_signal"] = (
                    status == 200 and paused.get("status") == "paused" and pause_signal in captured["signals"]
                )
                paused_session = paused.get("run_session") if isinstance(paused.get("run_session"), dict) else {}
                paused_control = paused_session.get("control") if isinstance(paused_session.get("control"), dict) else {}
                paused_history = paused_session.get("control_history") if isinstance(paused_session.get("control_history"), list) else []
                paused_ai_usage = paused_session.get("ai_usage_ledger") if isinstance(paused_session.get("ai_usage_ledger"), dict) else {}
                checks["control_pause_updates_run_session_without_tokens"] = (
                    status == 200
                    and paused_session.get("schema_version") == "reachops.run_session.v1"
                    and paused_control.get("last_action") == "pause"
                    and paused_control.get("current_paused") is True
                    and any(
                        (row or {}).get("action") == "pause"
                        and (row or {}).get("reason") == "WEB_UI_PAUSE_REQUESTED"
                        and (row or {}).get("no_ai_token_used") is True
                        for row in paused_history
                    )
                    and paused_ai_usage.get("schema_version") == "reachops.ai_usage_ledger.v1"
                    and ((paused_ai_usage.get("execution_phase") or {}).get("ai_call_count") == 0)
                    and ((paused_ai_usage.get("execution_phase") or {}).get("token_estimate") == 0)
                )

            if resume_signal is None:
                status, resumed = _json_request(base + "/api/control", {"action": "resume"})
                checks["control_resume_reaches_process_signal"] = (
                    status == 200 and resumed.get("status") == "running" and resumed.get("cooperative_control") is True
                )
                checks["control_resume_updates_run_session_without_tokens"] = (
                    status == 200
                    and ((resumed.get("run_session") or {}).get("control") or {}).get("last_action") == "resume"
                    and ((resumed.get("run_session") or {}).get("control") or {}).get("current_paused") is False
                    and ((resumed.get("run_session") or {}).get("control") or {}).get("cooperative_control") is True
                    and (((resumed.get("run_session") or {}).get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
                    and (((resumed.get("run_session") or {}).get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("token_estimate") == 0
                )
            else:
                status, resumed = _json_request(base + "/api/control", {"action": "resume"})
                checks["control_resume_reaches_process_signal"] = (
                    status == 200 and resumed.get("status") == "running" and resume_signal in captured["signals"]
                )
                resumed_session = resumed.get("run_session") if isinstance(resumed.get("run_session"), dict) else {}
                resumed_control = resumed_session.get("control") if isinstance(resumed_session.get("control"), dict) else {}
                resumed_history = resumed_session.get("control_history") if isinstance(resumed_session.get("control_history"), list) else []
                resumed_ai_usage = resumed_session.get("ai_usage_ledger") if isinstance(resumed_session.get("ai_usage_ledger"), dict) else {}
                checks["control_resume_updates_run_session_without_tokens"] = (
                    status == 200
                    and resumed_session.get("schema_version") == "reachops.run_session.v1"
                    and resumed_control.get("last_action") == "resume"
                    and resumed_control.get("current_paused") is False
                    and any(
                        (row or {}).get("action") == "resume"
                        and (row or {}).get("reason") == "WEB_UI_RESUME_REQUESTED"
                        and (row or {}).get("no_ai_token_used") is True
                        for row in resumed_history
                    )
                    and any((row or {}).get("action") == "pause" for row in resumed_history)
                    and resumed_ai_usage.get("schema_version") == "reachops.ai_usage_ledger.v1"
                    and ((resumed_ai_usage.get("execution_phase") or {}).get("ai_call_count") == 0)
                    and ((resumed_ai_usage.get("execution_phase") or {}).get("token_estimate") == 0)
                )

            status, stopped = _json_request(base + "/api/control", {"action": "stop"})
            term_signal = getattr(signal, "SIGTERM", signal.SIGINT)
            checks["control_stop_finalizes_runtime_state"] = (
                status == 200
                and stopped.get("status") == "stopped"
                and term_signal in captured["signals"]
                and reachops_web_ui.RUN_PROCESS is None
            )
            checks["control_stop_updates_run_session"] = (
                status == 200
                and (stopped.get("run_session") or {}).get("state") == "BLOCKED"
                and ((stopped.get("run_session") or {}).get("control") or {}).get("last_action") == "stop"
                and any(
                    (row or {}).get("action") == "stop"
                    for row in ((stopped.get("run_session") or {}).get("control_history") or [])
                )
            )
            replay_original_plan_id = stored_plan.get("plan_id")
            replay_original_fingerprint = stored_plan.get("plan_fingerprint_sha256")
            status, replay_started = _json_request(base + "/api/start-from-plan", {})
            replay_cmd = list(captured.get("cmd") or [])
            replay_plan_path = Path(replay_cmd[replay_cmd.index("--execution-plan") + 1]) if "--execution-plan" in replay_cmd else Path("")
            replay_plan = json.loads(replay_plan_path.read_text(encoding="utf-8")) if replay_plan_path.is_file() else {}
            checks["start_from_plan_replays_latest_execution_plan"] = (
                status == 200
                and replay_started.get("status") == "started"
                and replay_started.get("execution_plan_replay") is True
                and replay_started.get("execution_plan_replay_source_path") == str(reachops_web_ui.LATEST_EXECUTION_PLAN_PATH)
                and replay_started.get("execution_plan_id") == replay_original_plan_id
                and replay_plan.get("plan_id") == replay_original_plan_id
                and replay_plan.get("plan_fingerprint_sha256") == replay_original_fingerprint
                and replay_plan.get("target") == stored_plan.get("target")
                and replay_plan.get("profile_group") == stored_plan.get("profile_group")
                and replay_cmd[replay_cmd.index("--execution-plan") + 1] == str(replay_plan_path)
                and replay_cmd[replay_cmd.index("--target") + 1] == stored_plan.get("target")
                and replay_cmd[replay_cmd.index("--profile-group") + 1] == stored_plan.get("profile_group")
            )
            status, replay_stopped = _json_request(base + "/api/control", {"action": "stop"})
            checks["start_from_plan_can_be_stopped_without_tokens"] = (
                status == 200
                and replay_stopped.get("status") == "stopped"
                and ((replay_stopped.get("run_session") or {}).get("ai_usage_ledger") or {}).get("schema_version")
                == "reachops.ai_usage_ledger.v1"
                and (((replay_stopped.get("run_session") or {}).get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
            )
            recovery_plan = reachops_web_ui.build_execution_plan(
                target="interrupted serum",
                source_type="keyword",
                mode="collect",
                profile_group="Canada",
                volume="quick",
                base_dir=str(reachops_web_ui.DATA_DIR),
                origin="runtime_smoke_recovery",
            )
            recovery_plan_path = reachops_web_ui.DATA_DIR / "plans" / f"{recovery_plan.get('plan_id')}.json"
            reachops_web_ui.write_execution_plan(recovery_plan, recovery_plan_path)
            reachops_web_ui.write_execution_plan(recovery_plan, reachops_web_ui.LATEST_EXECUTION_PLAN_PATH)
            interrupted_session = reachops_web_ui.create_run_session(
                recovery_plan,
                execution_plan_path=str(recovery_plan_path),
                result_path=str(reachops_web_ui.RESULT_PATH),
                log_path=str(reachops_web_ui.LOG_PATH),
                log_offset=0,
            )
            interrupted_session = reachops_web_ui.transition_run_session(
                interrupted_session,
                "COLLECTING",
                pid=98765,
                last_stage="COLLECT interrupted fixture",
            )
            recovery_session_path = reachops_web_ui.run_session_path_for(interrupted_session)
            reachops_web_ui.write_run_session(
                interrupted_session,
                recovery_session_path,
                reachops_web_ui.LATEST_RUN_SESSION_PATH,
            )
            reachops_web_ui.CURRENT_RUN_SESSION_PATH = str(recovery_session_path)
            reachops_web_ui.RUN_PROCESS = None
            reachops_web_ui.RESULT_PATH.unlink(missing_ok=True)
            status, recovered_logs = _json_request(base + "/api/logs")
            checks["logs_recover_interrupted_run_session_to_blocked"] = (
                status == 200
                and (recovered_logs.get("recovery") or {}).get("recovered") is True
                and recovered_logs.get("run_session_state") == "BLOCKED"
                and ((recovered_logs.get("run_session") or {}).get("result") or {}).get("error") == "process_interrupted"
                and (recovered_logs.get("run_result") or {}).get("error") == "process_interrupted"
                and ((recovered_logs.get("evidence_bundle") or {}).get("summary") or {}).get("status") == "blocked"
                and any(
                    (row or {}).get("action") == "recover_interrupted_run"
                    for row in ((recovered_logs.get("run_session") or {}).get("control_history") or [])
                )
                and ((recovered_logs.get("evidence_bundle") or {}).get("control_summary") or {}).get("recovery_count") == 1
                and ((recovered_logs.get("evidence_bundle") or {}).get("run_recovery_summary") or {}).get("schema_version")
                == "reachops.run_recovery_summary.v1"
                and ((recovered_logs.get("evidence_bundle") or {}).get("run_recovery_summary") or {}).get("recovered") is True
                and ((recovered_logs.get("evidence_bundle") or {}).get("run_recovery_summary") or {}).get("latest_reason")
                == "PROCESS_INTERRUPTED"
            )

            status, acceptance = _json_request(base + "/api/acceptance")
            diagnostics["acceptance_goal_delivery"] = acceptance.get("goal_delivery") or {}
            checks["acceptance_exposes_client_delivery_gate"] = (
                status == 200
                and "client_delivery" in acceptance
                and "final_delivery_ready" in acceptance.get("client_delivery", {})
                and "mvp_acceptance" in acceptance
                and "goal_delivery" in acceptance
            )
            checks["acceptance_exposes_goal_delivery_boundary"] = (
                status == 200
                and (acceptance.get("goal_delivery") or {}).get("status") == "local_mvp_accepted_final_pending"
                and (acceptance.get("goal_delivery") or {}).get("windows_build_ready") is True
                and (acceptance.get("goal_delivery") or {}).get("final_delivery_ready") is False
                and ((acceptance.get("goal_delivery") or {}).get("delivery_boundary") or {}).get("overall_final_delivery_scope_ready") is False
                and ((acceptance.get("goal_delivery") or {}).get("windows_package_preflight") or {}).get("skip_installer_is_non_final") is True
                and (acceptance.get("goal_delivery") or {}).get("summary_path") == str(reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH)
            )
            checks["acceptance_exposes_two_phase_matrix"] = (
                status == 200
                and "two_phase_acceptance" in acceptance
                and str((acceptance.get("two_phase_acceptance") or {}).get("path") or "").endswith("latest_two_phase_acceptance_matrix.json")
                and str((acceptance.get("two_phase_acceptance") or {}).get("markdown_path") or "").endswith("latest_two_phase_acceptance_matrix.md")
            )
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)
            reachops_web_ui.DATA_DIR = old_data_dir
            reachops_web_ui.LOG_PATH = old_log_path
            reachops_web_ui.RESULT_PATH = old_result_path
            reachops_web_ui.LATEST_EXECUTION_PLAN_PATH = old_latest_execution_plan_path
            reachops_web_ui.LATEST_RUN_SESSION_PATH = old_latest_run_session_path
            reachops_web_ui.LATEST_EVIDENCE_BUNDLE_PATH = old_latest_evidence_bundle_path
            reachops_web_ui.LATEST_EVIDENCE_BUNDLE_MD_PATH = old_latest_evidence_bundle_md_path
            reachops_web_ui.CURRENT_RUN_SESSION_PATH = old_current_run_session_path
            reachops_web_ui.RUN_PROCESS = old_process
            reachops_web_ui.RUN_PAUSED = old_paused
            reachops_web_ui.RUN_STARTED_AT = old_started_at
            reachops_web_ui.subprocess.Popen = old_popen
            reachops_web_ui.load_groups = old_load_groups
            reachops_web_ui.build_final_status_payload = old_final_status
            reachops_web_ui.build_ixbrowser_status_payload = old_ixbrowser_status
            reachops_web_ui.IXBROWSER_API_PORT_OVERRIDE = old_ixbrowser_override
            reachops_web_ui.WEB_SETTINGS_PATH = old_web_settings_path
            reachops_web_ui.MVP_ACCEPTANCE_SUMMARY_PATH = old_web_mvp_path
            reachops_web_ui.GOAL_DELIVERY_REPORT_PATH = old_web_goal_path
            reachops_web_ui.GOAL_DELIVERY_SUMMARY_PATH = old_web_goal_summary_path
            reachops_web_ui.TWO_PHASE_MATRIX_JSON_PATH = old_web_two_phase_json_path
            reachops_web_ui.TWO_PHASE_MATRIX_MD_PATH = old_web_two_phase_md_path
            if old_ixbrowser_env is None:
                reachops_web_ui.os.environ.pop("REACHOPS_IXBROWSER_API_PORT", None)
            else:
                reachops_web_ui.os.environ["REACHOPS_IXBROWSER_API_PORT"] = old_ixbrowser_env
            if old_require_activation_env is None:
                reachops_web_ui.os.environ.pop("REACHOPS_REQUIRE_ACTIVATION", None)
            else:
                reachops_web_ui.os.environ["REACHOPS_REQUIRE_ACTIVATION"] = old_require_activation_env
            reachops_mvp_acceptance_summary.build_summary = old_mvp_build_summary
            reachops_mvp_acceptance_summary.OUT_PATH = old_mvp_out_path
            reachops_goal_delivery_runner.build_report = old_goal_build_report
            reachops_goal_delivery_runner.OUT_PATH = old_goal_out_path
            reachops_goal_delivery_runner.SUMMARY_PATH = old_goal_summary_path
            if old_killpg is not None:
                reachops_web_ui.os.killpg = old_killpg

    failed = [name for name, ok in checks.items() if not ok]
    return {
        "status": "passed" if not failed else "failed",
        "passed": not failed,
        "failed_checks": failed,
        "checks": checks,
        "source_mtimes": source_mtimes(),
        "diagnostics": diagnostics,
        "captured_command": captured.get("cmd", []),
        "captured_signals": [int(sig) for sig in captured.get("signals", [])],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ReachOps Web panel runtime API smoke acceptance.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_runtime_smoke()
    write_latest_result(result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"status={result['status']} failed_checks={','.join(result['failed_checks']) or '-'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
