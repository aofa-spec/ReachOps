import io
import http.client
import json
import os
from email.message import Message
from io import BytesIO
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.reachops_client_acceptance_status import (
    build_acceptance_manifest,
    build_account_repair_plan,
    derive_acceptance,
    extract_profile_preflight_details,
    dedupe_profile_remediation_details,
    recommended_profile_action,
    write_remediation_report,
)
from tools.reachops_mac_self_check import (
    REQUIRED_WEB_UI_MARKERS,
    apply_version_payload,
    classify_tk_failure,
    check_client_delivery,
    evaluate_web_ui_body,
    find_available_port,
    format_human,
    start_web,
)
from tools import reachops_mvp_acceptance_summary
from tools import reachops_web_ui
from tools import reachops_mac_loop_acceptance
from tools.reachops_client_delivery_check import (
    account_repair_summary_lines,
    build_account_blocker_resolution,
    build_delivery_check,
    build_real_pilot_evidence_boundary,
    latest_account_repair_apply_status,
    main as run_delivery_check,
    profile_remediation_csv_quality,
)
from tools.reachops_apply_account_repair_plan import apply_account_repair_plan
from tools.reachops_web_panel_dom_smoke import run_dom_smoke
from tools.reachops_web_panel_runtime_smoke import run_runtime_smoke
from tools.run_reachops_headless_macos import DummyRoot
from tools.reachops_web_ui import (
    DEFAULT_TARGET,
    MAX_JSON_PAYLOAD_BYTES,
    MAX_START_PROFILE_LIMIT,
    WEB_UI_VERSION,
    format_url_host,
    html_page,
    is_local_api_host,
    normalize_local_bind_host,
    normalize_profile_limit,
    safe_report_download_path,
)


class ReachOpsClientAcceptanceStatusTest(unittest.TestCase):
    def test_headless_dummy_root_executes_delayed_callbacks(self):
        calls = []

        DummyRoot().after(10, lambda: calls.append("refresh"))

        self.assertEqual(calls, ["refresh"])

    def test_native_mac_ui_uses_full_operator_tabs_not_blank_fallback(self):
        root = Path(__file__).resolve().parents[1]
        standalone = (root / "ReachOps" / "workbench" / "standalone_app.py").read_text(encoding="utf-8")
        console = (root / "ReachOps" / "workbench" / "console.py").read_text(encoding="utf-8")

        self.assertIn("self.console = GrowthOpsConsole(", standalone)
        self.assertNotIn("console_cls = MacQuickConsole", standalone)
        self.assertIn('OPERATOR_VIEW_NAMES = ["获客任务", "线索分析", "触达执行", "账号诊断", "报告中心"]', console)
        for view_name in ["获客任务", "线索分析", "触达执行", "账号诊断", "报告中心"]:
            self.assertIn(view_name, console)
        self.assertIn("page_header = tk.Frame(", console)
        self.assertIn("textvariable=self.page_title_var", console)
        self.assertIn("textvariable=self.page_subtitle_var", console)
        self.assertIn("textvariable=self.operator_status_var", console)
        self.assertIn("self.stack = tk.Frame(content", console)
        self.assertIn("self.stack.grid(row=1", console)
        self.assertIn("frame = tk.Frame(self.stack", console)
        self.assertIn("view.tkraise()", console)
        self.assertIn("view.lift()", console)
        self.assertIn("暂无数据；开始获客或刷新工作台后会在这里显示结果。", console)
        self.assertIn("self._build_start_collection_page(self.views[\"获客任务\"])", console)
        self.assertIn("self._build_report_view(self.views[\"报告中心\"])", console)
        for required_token in [
            '"bg": "#1f2327"',
            '"surface": "#2b3036"',
            '"surface_alt": "#343a40"',
            '"border": "#59616a"',
            '"text": "#ffffff"',
            '"muted": "#d1d5db"',
            '"nav": "#2b3036"',
            '"nav_text": "#ffffff"',
            '"accent": "#ffffff"',
            '"accent_soft": "#4b5563"',
            '"terminal_bg": "#0c0d0e"',
            '"terminal_text": "#d1d5db"',
            '"terminal_info": "#60a5fa"',
            '"terminal_success": "#22c55e"',
            '"terminal_warning": "#fbbf24"',
            '"terminal_error": "#f87171"',
        ]:
            self.assertIn(required_token, console)
        for required_runtime_token in [
            "widget.tag_configure(\"terminal_error\"",
            "widget.tag_configure(\"terminal_warning\"",
            "widget.tag_configure(\"terminal_success\"",
            "def _runtime_line_tag(self, line: str)",
        ]:
            self.assertIn(required_runtime_token, console)
        for forbidden_color in [
            "#0A84FF",
            "#45D96B",
            "#FF6B6B",
            "#A8FF60",
            "#3A4044",
            "#4A5258",
            "#202528",
            "#111416",
            "#5B6B8C",
            "#f3f4f6",
            "#111827",
            "#1d4ed8",
            "#dbeafe",
        ]:
            self.assertNotIn(forbidden_color, console)
            self.assertNotIn(forbidden_color, standalone)
        self.assertIn("def _runtime_line_color(self, line: str)", standalone)
        self.assertNotIn("fill=green", standalone)
        self.assertIn('"text": "#ffffff"', standalone)
        self.assertIn('bg=APP_COLORS["surface"]', standalone)
        self.assertIn('fg=APP_COLORS["text"]', standalone)

    def test_mvp_acceptance_summary_uses_current_client_gate_over_historical_pass(self):
        def fake_run_json(command, timeout=120):
            joined = " ".join(command)
            if "reachops_delivery_audit.py" in joined:
                return {"status": "ok", "summary": {"failed": 0}}, 0, ""
            if "reachops_goal_status_report.py" in joined:
                return {
                    "status": "ready_for_external_validation",
                    "summary": {"stages_failed": 0, "final_failed": 0},
                    "pending_external_validation": ["授权允许时能真实执行"],
                }, 0, ""
            if "reachops_client_delivery_check.py" in joined:
                return {
                    "status": "blocked_by_accounts",
                    "readiness": "blocked_by_accounts",
                    "contract_ok": True,
                    "acceptance_ready": False,
                    "final_delivery_ready": False,
                    "failed_checks": ["acceptance:ready"],
                    "blockers": ["United States 可用账号为 0"],
                    "next_actions": ["修复账号登录和内核版本后复测。"],
                }, 1, ""
            if "reachops_mac_loop_acceptance.py" in joined:
                return {
                    "status": "passed",
                    "mac_loop_ready": True,
                    "checks": {"start_contract_evidence_complete": True},
                }, 0, ""
            if "reachops_repository_cleanliness_check.py" in joined:
                return {"status": "passed", "passed": True}, 0, ""
            return {}, 0, ""

        with patch("tools.reachops_mvp_acceptance_summary.run_json", side_effect=fake_run_json), patch(
            "tools.reachops_mvp_acceptance_summary.read_json",
            return_value={"status": "passed", "passed": True},
        ):
            summary = reachops_mvp_acceptance_summary.build_summary()

        self.assertEqual(summary["status"], "blocked_by_accounts")
        self.assertFalse(summary["mvp_local_ready"])
        self.assertFalse(summary["current_client_gate_ready"])
        self.assertIn("client_delivery:acceptance:ready", summary["failed_checks"])
        self.assertEqual(summary["blockers"], ["United States 可用账号为 0"])

    def test_blocked_by_accounts_uses_real_profile_group(self):
        batch = {
            "id": "gb_1",
            "campaign_id": "acq_1",
            "status": "failed",
            "profile_group": "Canada",
            "config_json": (
                '{"planned_sources":[{"source_type":"keyword","source_value":"skin care"}],'
                '"max_videos_per_creator":3,"max_comments_per_video":20,'
                '"quick_send":{"detected_type":"product_url","mode_label":"采集 + 触达预检","volume":"快速"}}'
            ),
        }
        preflight = {"checked": 9, "available": 0, "errors": {"PROFILE_START_FAILED": 9}}
        logs = [
            "PLAN   campaign id=acq_1 input_type=product_url product=skin care",
            "START  campaign id=acq_1 batch=gb_1 status=pending stage=profile_preflight",
            "CHECK  profile_preflight checked=9 available=0 unavailable=9 errors=PROFILE_START_FAILED=9",
            "CHECK  profile_preflight_detail stage=collection profile=45 status=不可用 error=PROFILE_START_FAILED evidence=- message=ixBrowser open_profile failed",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "blocked_by_accounts")
        self.assertTrue(result["checks"]["product_auto_detected"])
        self.assertEqual(result["execution_context"]["detected_type"], "product_url")
        self.assertEqual(result["execution_context"]["planned_source_count"], 1)
        self.assertEqual(result["profile_error_summary"]["PROFILE_START_FAILED"]["profile_ids"], ["45"])
        self.assertTrue(any("Canada" in item for item in result["next_actions"]))
        self.assertTrue(any("45" in item for item in result["next_actions"]))

    def test_pass_requires_collection_and_action_in_scoped_batch(self):
        batch = {"id": "gb_2", "campaign_id": "acq_2", "status": "completed", "profile_group": "US", "config_json": "{}"}
        preflight = {"checked": 1, "available": 1, "errors": {}}
        logs = [
            "DONE   collection old batch=gb_old",
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=product_url product=demo",
            "CONFIG quick_preflight_candidates group=US requested=1 candidates=3 checked_limit=3 auto_limit=60",
            "QUEUE  account_queue_start batch=gb_2 group=US concurrency=1 queue_target=1 max_sources_per_profile=1",
            "DONE   collection batch=gb_2",
            "START  action_preflight batch=gb_2 actions=1",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "pass")
        self.assertTrue(result["checks"]["profile_candidates_loaded_from_selected_group"])
        self.assertTrue(result["checks"]["account_queue_started_for_selected_group"])
        self.assertTrue(result["checks"]["profile_list_execution_evidence"])
        self.assertTrue(result["checks"]["collection_done"])
        self.assertTrue(result["checks"]["action_started"])

    def test_pass_accepts_no_submit_action_preflight_skipped_terminal(self):
        batch = {"id": "gb_2", "campaign_id": "acq_2", "status": "completed", "profile_group": "US", "config_json": "{}"}
        preflight = {"checked": 2, "available": 2, "errors": {}}
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=product_url product=demo",
            "CONFIG quick_preflight_candidates group=US requested=2 candidates=3 checked_limit=3 auto_limit=60",
            "QUEUE  account_queue_start batch=gb_2 group=US concurrency=2 queue_target=2 max_sources_per_profile=1",
            "DONE   collection batch=gb_2 processed_sources=0 errors=TOPIC_CONTENT_SCAN_FAILED=1",
            "TOUCH  skipped batch=gb_2 reason=本轮没有待预检/已批准动作 no_submit=true",
            "DONE   action_preflight skipped batch=gb_2 reason=本轮没有待预检/已批准动作",
            "FAST   acceptance status=executed mode=preflight actions=0 success=0 failed=0 skipped=0 no_submit=true",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "pass")
        self.assertTrue(result["checks"]["collection_done"])
        self.assertTrue(result["checks"]["action_started"])
        self.assertEqual(result["blockers"], [])

    def test_failed_batch_with_terminal_logs_does_not_pass(self):
        batch = {"id": "gb_2", "campaign_id": "acq_2", "status": "failed", "profile_group": "US", "config_json": "{}"}
        preflight = {"checked": 0, "available": 1, "errors": {}}
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=content_url product=demo",
            "CONFIG quick_preflight_candidates group=US requested=1 checked_limit=1 auto_limit=8",
            "QUEUE  account_queue_start batch=gb_2 group=US requested_concurrency=1 queue_target=2",
            "DONE   collection batch=gb_2 processed_sources=0 errors=COMMENT_SCAN_EMPTY=1",
            "DONE   action_preflight skipped batch=gb_2 reason=本轮没有待预检/已批准动作",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "partial")
        self.assertIn("最新批次状态为 failed", result["blockers"][0])

    def test_source_failure_summary_drives_specific_next_action(self):
        batch = {
            "id": "gb_2",
            "campaign_id": "acq_2",
            "status": "failed",
            "profile_group": "United States",
            "processed_sources": 0,
            "config_json": "{}",
        }
        preflight = {"checked": 0, "available": 1, "errors": {}}
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight group=United States",
            "PLAN   campaign id=acq_2 input_type=content_url product=demo",
            "CONFIG quick_preflight_candidates group=United States requested=1 checked_limit=1 auto_limit=8",
            "QUEUE  account_queue_start batch=gb_2 group=United States requested_concurrency=1 queue_target=2",
            "DONE   collection batch=gb_2 processed_sources=0 errors=URL_MISMATCH_DISCARDED=1",
            "SOURCE failed batch=gb_2 type=content_url value=https://www.tiktok.com/@a/video/1 error=URL_MISMATCH_DISCARDED message=normal",
            "DONE   action_preflight skipped batch=gb_2 reason=本轮没有待预检/已批准动作",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["top_source_error"], "URL_MISMATCH_DISCARDED")
        self.assertEqual(result["source_failure_summary"]["URL_MISMATCH_DISCARDED"]["count"], 1)
        self.assertTrue(any("跳转到其他 TikTok 视频" in item for item in result["blockers"]))
        self.assertTrue(any("当前链接会跳到其他视频" in item for item in result["next_actions"]))

    def test_source_failure_summary_ignores_previous_batch_failures(self):
        batch = {
            "id": "gb_new",
            "campaign_id": "acq_new",
            "status": "partial_failed",
            "profile_group": "United States",
            "processed_sources": 2,
            "config_json": "{}",
        }
        preflight = {"checked": 0, "available": 1, "errors": {}}
        logs = [
            "SOURCE failed batch=gb_old type=content_url value=https://www.tiktok.com/@a/video/1 error=URL_MISMATCH_DISCARDED message=normal",
            "START  campaign id=acq_new batch=gb_new status=pending stage=profile_preflight group=United States",
            "PLAN   campaign id=acq_new input_type=product_url product=demo",
            "CONFIG quick_preflight_candidates group=United States requested=1 checked_limit=1 auto_limit=8",
            "QUEUE  account_queue_start batch=gb_new group=United States requested_concurrency=1 queue_target=2",
            "DONE   collection batch=gb_new processed_sources=2 errors=LOGIN_REQUIRED=1",
            "SOURCE failed batch=gb_new type=keyword value=demo error=LOGIN_REQUIRED message=page state detected: LOGIN_REQUIRED",
            "DONE   action_preflight skipped batch=gb_new reason=本轮没有待预检/已批准动作",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["top_source_error"], "LOGIN_REQUIRED")
        self.assertNotIn("URL_MISMATCH_DISCARDED", result["source_failure_summary"])
        self.assertTrue(any("评论区" in item for item in result["next_actions"]))

    def test_restart_after_latest_batch_requires_new_run(self):
        batch = {"id": "gb_2", "campaign_id": "acq_2", "status": "completed", "profile_group": "US", "config_json": "{}"}
        preflight = {"checked": 1, "available": 1, "errors": {}}
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=product_url product=demo",
            "CONFIG quick_preflight_candidates group=US requested=1 candidates=3 checked_limit=3 auto_limit=60",
            "QUEUE  account_queue_start batch=gb_2 group=US concurrency=1 queue_target=1 max_sources_per_profile=1",
            "DONE   collection batch=gb_2 processed_sources=1 errors=无",
            "DONE   action_preflight skipped batch=gb_2 reason=本轮没有待预检/已批准动作",
            "READY  app_started data_dir=/tmp/reachops log=/tmp/reachops/logs/growth_ops_runtime.log",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "pending_new_run")
        self.assertTrue(result["checks"]["runtime_restarted_after_latest_batch"])
        self.assertTrue(any("重启" in item for item in result["blockers"]))
        self.assertTrue(any("重新点击开始获客" in item for item in result["next_actions"]))

    def test_pass_rejects_collection_without_selected_group_profile_list_evidence(self):
        batch = {"id": "gb_2", "campaign_id": "acq_2", "status": "completed", "profile_group": "US", "config_json": "{}"}
        preflight = {"checked": 1, "available": 1, "errors": {}}
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=product_url product=demo",
            "DONE   collection batch=gb_2",
            "START  action_preflight batch=gb_2 actions=1",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertNotEqual(result["readiness"], "pass")
        self.assertFalse(result["checks"]["profile_candidates_loaded_from_selected_group"])
        self.assertFalse(result["checks"]["account_queue_started_for_selected_group"])
        self.assertFalse(result["checks"]["profile_list_execution_evidence"])
        self.assertTrue(any("配置列表" in item for item in result["blockers"]))

    def test_empty_ixbrowser_group_refresh_reports_environment_blocker(self):
        batch = {"id": "gb_3", "campaign_id": "acq_3", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        preflight = {"checked": 0, "available": 0, "errors": {}}
        logs = [
            "CONFIG refresh_profiles groups_loaded groups=0 profiles=0",
            "PLAN   campaign id=acq_3 input_type=product_url product=demo",
            "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight group=United States",
            "CONFIG selected_profiles group=United States requested=1 candidates=0 selected=0 excluded=0",
            "BLOCK  campaign failed reason=没有可用账号 error=NO_PROFILE_SELECTED",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "blocked_by_environment")
        self.assertTrue(result["checks"]["ixbrowser_group_refresh_seen"])
        self.assertTrue(result["checks"]["ixbrowser_group_list_empty"])
        self.assertEqual(result["checks"]["selected_profiles_candidate_count"], 0)
        self.assertTrue(any("groups=0/profiles=0" in item for item in result["blockers"]))
        self.assertTrue(any("本地服务" in item for item in result["next_actions"]))

    def test_pass_rejects_stale_profile_preflight_from_previous_batch(self):
        batch = {
            "id": "gb_2",
            "campaign_id": "acq_2",
            "status": "completed",
            "created_at": "2026-06-30T10:00:00Z",
            "config_json": "{}",
        }
        preflight = {
            "checked": 3,
            "available": 3,
            "errors": {},
            "created_at": "2026-06-30T09:59:00Z",
        }
        logs = [
            "START  campaign id=acq_2 batch=gb_2 status=pending stage=profile_preflight",
            "PLAN   campaign id=acq_2 input_type=product_url product=demo",
            "DONE   collection batch=gb_2",
            "START  action_preflight batch=gb_2 actions=1",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "blocked_by_environment")
        self.assertFalse(result["checks"]["profile_preflight_fresh"])
        self.assertEqual(result["checks"]["profile_available_count"], 0)
        self.assertTrue(any("不能复用旧账号可用性" in item for item in result["blockers"]))

    def test_headless_timeout_is_reported_as_environment_blocker(self):
        batch = {"id": "gb_3", "campaign_id": "acq_3", "status": "failed", "config_json": "{}"}
        preflight = {"checked": 0, "available": 0, "errors": {}}
        logs = [
            "PLAN   campaign id=acq_3 input_type=product_url product=demo",
            "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight",
            "BLOCK  campaign failed batch=gb_3 reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
        ]

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "blocked_by_environment")
        self.assertTrue(any("ixBrowser 本地服务" in item for item in result["blockers"]))
        self.assertTrue(any("真实执行复测" in item for item in result["next_actions"]))

    def test_extract_profile_preflight_details(self):
        details = extract_profile_preflight_details(
            [
                "CHECK  profile_preflight_detail stage=collection profile=385 status=不可用 error=IXBROWSER_KERNEL_MISMATCH evidence=- message=ixBrowser open_profile failed: code=2014",
                "CHECK  profile_preflight_detail stage=collection profile=4 status=不可用 error=IXBROWSER_NETWORK_ERROR evidence=/tmp/e.png close_action=closed_and_skipped operator_hint=配置预检异常，已关闭并继续下一个账号 message=ECONNRESET",
            ]
        )

        self.assertEqual(details[0]["profile_id"], "385")
        self.assertEqual(details[0]["error"], "IXBROWSER_KERNEL_MISMATCH")
        self.assertEqual(details[0]["evidence"], "")
        self.assertEqual(details[1]["evidence"], "/tmp/e.png")
        self.assertEqual(details[1]["close_action"], "closed_and_skipped")
        self.assertIn("已关闭", details[1]["operator_hint"])

    def test_derive_acceptance_keeps_full_profile_remediation_list(self):
        batch = {
            "id": "gb_many",
            "campaign_id": "acq_many",
            "status": "pending",
            "profile_group": "United States",
            "created_at": "2026-07-04T00:00:00Z",
            "config_json": json.dumps({"quick_send": {"detected_type": "product_url"}}),
        }
        preflight = {
            "checked": 35,
            "available": 0,
            "errors": {"IXBROWSER_KERNEL_MISMATCH": 35},
            "created_at": "2026-07-04T00:01:00Z",
        }
        logs = [
            "2026-07-04 00:00:00  PLAN   campaign id=acq_many input_type=product_url product=demo",
            "2026-07-04 00:00:01  START  campaign id=acq_many batch=gb_many status=pending stage=profile_preflight group=United States",
            "2026-07-04 00:00:02  CONFIG quick_preflight_candidates group=United States requested=3 candidates=35 checked_limit=35 auto_limit=60",
            "2026-07-04 00:00:03  QUEUE  account_queue_start batch=gb_many group=United States concurrency=3 queue_target=60",
            "2026-07-04 00:00:04  CHECK  profile_preflight checked=35 available=0 unavailable=35 errors=IXBROWSER_KERNEL_MISMATCH=35",
        ]
        logs.extend(
            f"2026-07-04 00:00:05  CHECK  profile_preflight_detail stage=collection profile={1000 + idx} status=不可用 error=IXBROWSER_KERNEL_MISMATCH evidence=- message=kernel"
            for idx in range(35)
        )

        result = derive_acceptance(batch, preflight, logs)

        self.assertEqual(result["readiness"], "blocked_by_accounts")
        self.assertEqual(len(result["profile_preflight_details"]), 35)
        self.assertEqual(result["profile_preflight_details"][-1]["profile_id"], "1034")

    def test_write_remediation_report_exports_actionable_files(self):
        with TemporaryDirectory() as tmpdir:
            report = write_remediation_report(
                Path(tmpdir),
                {"id": "gb_1", "profile_group": "United States"},
                [
                    {
                        "profile_id": "45",
                        "status": "不可用",
                        "error": "PROFILE_START_FAILED",
                        "evidence": "",
                        "message": "start failed",
                    },
                    {
                        "profile_id": "46",
                        "status": "不可用",
                        "error": "LOGIN_REQUIRED",
                        "evidence": "/tmp/login.png",
                        "message": "LOGIN_REQUIRED",
                    }
                ],
            )

            csv_text = Path(report["csv_path"]).read_text(encoding="utf-8")
            json_text = Path(report["json_path"]).read_text(encoding="utf-8")
            md_text = Path(report["markdown_path"]).read_text(encoding="utf-8")
            guide_text = Path(report["guide_path"]).read_text(encoding="utf-8")
            index_text = Path(report["index_path"]).read_text(encoding="utf-8")
            manifest = json_load(Path(report["manifest_path"]))
            latest_csv_text = Path(report["latest_csv_path"]).read_text(encoding="utf-8")
            latest_json_text = Path(report["latest_json_path"]).read_text(encoding="utf-8")
            latest_markdown_text = Path(report["latest_markdown_path"]).read_text(encoding="utf-8")
            latest_guide_text = Path(report["latest_guide_path"]).read_text(encoding="utf-8")
            latest_index_text = Path(report["latest_index_path"]).read_text(encoding="utf-8")
            latest_manifest = json_load(Path(report["latest_manifest_path"]))
            account_plan = json_load(Path(report["account_plan_json_path"]))
            account_plan_text = Path(report["account_plan_markdown_path"]).read_text(encoding="utf-8")
            latest_account_plan = json_load(Path(report["latest_account_plan_json_path"]))
            latest_account_plan_text = Path(report["latest_account_plan_markdown_path"]).read_text(encoding="utf-8")

        self.assertIn("45", csv_text)
        self.assertIn("46", csv_text)
        self.assertIn("PROFILE_START_FAILED", csv_text)
        self.assertIn("手动打开该配置", csv_text)
        self.assertIn("United States", json_text)
        self.assertIn("ReachOps Mac 真实执行验收报告", md_text)
        self.assertIn("复测通过标准", md_text)
        self.assertIn("45", latest_csv_text)
        self.assertIn("United States", latest_json_text)
        self.assertIn("ReachOps Mac 真实执行验收报告", latest_markdown_text)
        self.assertIn("ReachOps Mac 客户验收操作指南", guide_text)
        self.assertIn("ReachOps Mac 客户验收操作指南", latest_guide_text)
        self.assertIn("ReachOps Mac 真实执行验收包", index_text)
        self.assertIn("ReachOps Mac 真实执行验收包", latest_index_text)
        self.assertIn("本地客户端控制台", guide_text)
        self.assertIn("启动ReachOps本地客户端.command", guide_text)
        self.assertIn("本地客户端控制台", index_text)
        self.assertIn("启动ReachOps本地客户端.command", index_text)
        self.assertIn("执行ReachOps账号修复.command", guide_text)
        self.assertIn("执行ReachOps账号修复.command", index_text)
        self.assertIn("复测ReachOps真实执行.command", guide_text)
        self.assertIn("固定最新账号修复计划", guide_text)
        self.assertIn("账号修复计划", index_text)
        self.assertIn("account_repair", manifest["client_entrypoints"])
        self.assertIn("real_retest", manifest["client_entrypoints"])
        self.assertIn("local_client_console", manifest["client_entrypoints"])
        self.assertIn("account_repair", latest_manifest["client_entrypoints"])
        self.assertIn("real_retest", latest_manifest["client_entrypoints"])
        self.assertIn("local_client_console", latest_manifest["client_entrypoints"])
        self.assertEqual(manifest["web_operator_api"]["final_status"], "/api/final-status")
        self.assertTrue(manifest["web_operator_api"]["final_status_no_browser_started"])
        self.assertTrue(manifest["web_operator_api"]["final_status_no_submit"])
        self.assertEqual(manifest["acceptance_gates"]["requires_profile_available"], "available>=1")
        self.assertIn("client_acceptance_guide", manifest["reports"])
        self.assertIn("acceptance_index_html", manifest["reports"])
        self.assertIn("account_repair_plan_markdown", manifest["reports"])
        self.assertEqual(manifest["account_repair_summary"]["total_unique_profiles_by_error"], 2)
        self.assertEqual(manifest["account_repair_summary"]["total_error_events_by_error"], 2)
        self.assertEqual(manifest["account_repair_summary"]["summary_only_error_count"], 0)
        self.assertEqual(
            {row["error"]: row["profile_ids_total"] for row in manifest["account_repair_summary"]["error_groups"]},
            {"PROFILE_START_FAILED": 1, "LOGIN_REQUIRED": 1},
        )
        self.assertEqual(latest_manifest["account_repair_summary"], manifest["account_repair_summary"])
        errors = {row["error"]: row for row in account_plan["groups"]}
        self.assertIn("PROFILE_START_FAILED", errors)
        self.assertIn("LOGIN_REQUIRED", errors)
        self.assertEqual(errors["LOGIN_REQUIRED"]["profile_ids"], ["46"])
        self.assertEqual(latest_account_plan["groups"], account_plan["groups"])
        self.assertIn("ReachOps 账号修复计划", account_plan_text)
        self.assertIn("LOGIN_REQUIRED", latest_account_plan_text)

    def test_profile_remediation_details_are_deduped_by_profile_with_actionable_error(self):
        rows = dedupe_profile_remediation_details(
            [
                {"profile_id": "21632", "error": "PROFILE_PREFLIGHT_TIMEOUT", "message": "timeout"},
                {"profile_id": "21632", "error": "IXBROWSER_KERNEL_MISMATCH", "message": "kernel"},
                {"profile_id": "21638", "error": "LOGIN_REQUIRED", "message": "login"},
            ]
        )

        self.assertEqual([row["profile_id"] for row in rows], ["21632", "21638"])
        self.assertEqual(rows[0]["error"], "IXBROWSER_KERNEL_MISMATCH")
        self.assertEqual(rows[0]["message"], "kernel")

    def test_account_repair_plan_keeps_summary_errors_without_profile_ids(self):
        plan = build_account_repair_plan(
            {"id": "gb_1", "status": "failed", "profile_group": "United States"},
            [{"profile_id": "21632", "error": "IXBROWSER_KERNEL_MISMATCH", "message": "kernel"}],
            preflight_errors={"IXBROWSER_KERNEL_MISMATCH": 1, "LOGIN_REQUIRED": 13, "PAGE_OPEN_FAILED": 6},
        )

        errors = {row["error"]: row for row in plan["groups"]}
        self.assertEqual(errors["IXBROWSER_KERNEL_MISMATCH"]["profile_ids"], ["21632"])
        self.assertEqual(errors["IXBROWSER_KERNEL_MISMATCH"]["profile_ids_total"], 1)
        self.assertEqual(errors["IXBROWSER_KERNEL_MISMATCH"]["summary_only_count"], 0)
        self.assertEqual(errors["LOGIN_REQUIRED"]["count"], 13)
        self.assertEqual(errors["LOGIN_REQUIRED"]["profile_ids"], [])
        self.assertEqual(errors["LOGIN_REQUIRED"]["profile_ids_total"], 0)
        self.assertEqual(errors["LOGIN_REQUIRED"]["summary_only_count"], 13)
        self.assertEqual(errors["PAGE_OPEN_FAILED"]["count_source"], "profile_preflight_summary")
        self.assertEqual(plan["total_unique_profiles_by_error"], 1)
        self.assertEqual(plan["total_error_events_by_error"], 20)
        self.assertEqual(plan["summary_only_error_count"], 19)

    def test_profile_remediation_csv_quality_rejects_duplicate_profile_ids(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "remediation.csv"
            path.write_text(
                "profile_id,error\n21632,LOGIN_REQUIRED\n21632,IXBROWSER_KERNEL_MISMATCH\n",
                encoding="utf-8",
            )

            quality = profile_remediation_csv_quality(path, expected_count=2)

        self.assertFalse(quality["ok"])
        self.assertEqual(quality["duplicate_profile_ids"], ["21632"])
        self.assertEqual(quality["row_count"], 2)

    def test_acceptance_manifest_lists_entrypoints_and_blocked_profiles(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = build_acceptance_manifest(
                {"id": "gb_1", "status": "failed", "profile_group": "United States"},
                [{"profile_id": "45", "error": "PROFILE_START_FAILED", "recommended_action": "fix"}],
                root / "fix.csv",
                root / "fix.json",
                root / "fix.md",
                root / "guide.md",
                root / "index.html",
                account_plan=build_account_repair_plan(
                    {"id": "gb_1", "status": "failed", "profile_group": "United States"},
                    [{"profile_id": "45", "error": "PROFILE_START_FAILED", "message": "start failed"}],
                    preflight_errors={"PROFILE_START_FAILED": 1, "PAGE_OPEN_FAILED": 3},
                ),
            )

        self.assertIn("web_ui", manifest["client_entrypoints"])
        self.assertIn("local_client_console", manifest["client_entrypoints"])
        self.assertIn("real_retest", manifest["client_entrypoints"])
        self.assertEqual(manifest["web_operator_api"]["acceptance"], "/api/acceptance")
        self.assertEqual(manifest["web_operator_api"]["final_status"], "/api/final-status")
        self.assertEqual(manifest["blocked_profiles"][0]["profile_id"], "45")
        self.assertEqual(manifest["readiness"], "blocked_by_accounts")
        self.assertEqual(manifest["account_repair_summary"]["total_unique_profiles_by_error"], 1)
        self.assertEqual(manifest["account_repair_summary"]["total_error_events_by_error"], 4)
        self.assertEqual(manifest["account_repair_summary"]["summary_only_error_count"], 3)
        errors = {row["error"]: row for row in manifest["account_repair_summary"]["error_groups"]}
        self.assertEqual(errors["PROFILE_START_FAILED"]["profile_ids_total"], 1)
        self.assertEqual(errors["PROFILE_START_FAILED"]["summary_only_count"], 0)
        self.assertEqual(errors["PAGE_OPEN_FAILED"]["profile_ids_total"], 0)
        self.assertEqual(errors["PAGE_OPEN_FAILED"]["summary_only_count"], 3)
        self.assertEqual(errors["PAGE_OPEN_FAILED"]["count_source"], "profile_preflight_summary")

    def test_recommended_profile_action_mentions_kernel_for_mismatch(self):
        self.assertIn("内核", recommended_profile_action("IXBROWSER_KERNEL_MISMATCH"))


class ReachOpsWebUiContractTest(unittest.TestCase):
    def setUp(self):
        self._old_group_cache = dict(reachops_web_ui.GROUP_CACHE)
        reachops_web_ui.GROUP_CACHE = {
            "loaded_at": time.time(),
            "groups": [
                {"name": "Canada", "label": "[ 2] Canada", "count": 2, "count_known": True},
                {"name": "United States", "label": "[ 3] United States", "count": 3, "count_known": True},
            ],
            "error": "",
        }

    def tearDown(self):
        reachops_web_ui.GROUP_CACHE = self._old_group_cache

    @contextmanager
    def start_gates_pass(self, group: str = "United States"):
        group_payload = {"group": {"name": group, "count": 3, "count_known": True}}
        account_payload = {"status": "ok", "force_account_recheck": False}
        with patch("tools.reachops_web_ui.validate_profile_group_for_start", return_value=(True, group_payload)):
            with patch("tools.reachops_web_ui.validate_account_repair_for_start", return_value=(True, account_payload)):
                yield

    def test_run_session_payload_recovers_dead_running_session(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_latest_run_session_path = reachops_web_ui.LATEST_RUN_SESSION_PATH
            old_current_run_session_path = reachops_web_ui.CURRENT_RUN_SESSION_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_started_at = reachops_web_ui.RUN_STARTED_AT
            try:
                base = Path(tmpdir)
                reachops_web_ui.DATA_DIR = base
                reachops_web_ui.LATEST_RUN_SESSION_PATH = base / "runs" / "latest_run_session.json"
                reachops_web_ui.CURRENT_RUN_SESSION_PATH = ""
                reachops_web_ui.RESULT_PATH = base / "reachops_web_ui_last_run.json"
                reachops_web_ui.LOG_PATH = base / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.RUN_STARTED_AT = 0.0

                plan = reachops_web_ui.build_execution_plan(
                    target="anti aging serum",
                    source_type="keyword",
                    mode="collect",
                    profile_group="United States",
                    base_dir=str(base),
                    origin="test_dead_run_session_recovery",
                )
                session = reachops_web_ui.create_run_session(
                    plan,
                    execution_plan_path=str(base / "plans" / "plan.json"),
                    result_path=str(reachops_web_ui.RESULT_PATH),
                    log_path=str(reachops_web_ui.LOG_PATH),
                )
                session = reachops_web_ui.transition_run_session(
                    session,
                    "PRECHECK",
                    pid=987654,
                    last_stage="PRECHECK running fixture",
                )
                session["created_at"] = "2026-01-01T00:00:00Z"
                session["started_at"] = "2026-01-01T00:00:00Z"
                session["updated_at"] = "2026-01-01T00:00:00Z"
                session_path = reachops_web_ui.run_session_path_for(session)
                reachops_web_ui.write_run_session(session, session_path, reachops_web_ui.LATEST_RUN_SESSION_PATH)
                reachops_web_ui.RESULT_PATH.write_text(
                    json.dumps({"status": "completed", "plan_id": "old-plan"}),
                    encoding="utf-8",
                )

                payload = reachops_web_ui.build_current_run_session_payload()
                persisted = json.loads(reachops_web_ui.LATEST_RUN_SESSION_PATH.read_text(encoding="utf-8"))
                result = json.loads(reachops_web_ui.RESULT_PATH.read_text(encoding="utf-8"))
            finally:
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LATEST_RUN_SESSION_PATH = old_latest_run_session_path
                reachops_web_ui.CURRENT_RUN_SESSION_PATH = old_current_run_session_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.RUN_STARTED_AT = old_started_at

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["recovery"]["recovered"])
        self.assertEqual(payload["summary"]["state"], "BLOCKED")
        self.assertEqual(payload["run_session"]["result"]["error"], "process_interrupted")
        self.assertEqual(persisted["state"], "BLOCKED")
        self.assertEqual(result["error"], "process_interrupted")

    def test_run_session_recovery_respects_matching_terminal_result(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_latest_run_session_path = reachops_web_ui.LATEST_RUN_SESSION_PATH
            old_current_run_session_path = reachops_web_ui.CURRENT_RUN_SESSION_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            try:
                base = Path(tmpdir)
                reachops_web_ui.DATA_DIR = base
                reachops_web_ui.LATEST_RUN_SESSION_PATH = base / "runs" / "latest_run_session.json"
                reachops_web_ui.CURRENT_RUN_SESSION_PATH = ""
                reachops_web_ui.RESULT_PATH = base / "reachops_web_ui_last_run.json"
                reachops_web_ui.LOG_PATH = base / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = None

                plan = reachops_web_ui.build_execution_plan(target="anti aging serum", mode="collect", base_dir=str(base))
                session = reachops_web_ui.create_run_session(plan)
                session = reachops_web_ui.transition_run_session(session, "PRECHECK", pid=12345)
                session["created_at"] = "2026-01-01T00:00:00Z"
                session["started_at"] = "2026-01-01T00:00:00Z"
                reachops_web_ui.write_run_session(
                    session,
                    reachops_web_ui.run_session_path_for(session),
                    reachops_web_ui.LATEST_RUN_SESSION_PATH,
                )
                reachops_web_ui.RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
                reachops_web_ui.RESULT_PATH.write_text(
                    json.dumps({"status": "completed", "plan_id": session["plan_id"]}),
                    encoding="utf-8",
                )

                payload = reachops_web_ui.build_current_run_session_payload()
            finally:
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LATEST_RUN_SESSION_PATH = old_latest_run_session_path
                reachops_web_ui.CURRENT_RUN_SESSION_PATH = old_current_run_session_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertFalse(payload["recovery"]["recovered"])
        self.assertEqual(payload["summary"]["state"], "PRECHECK")

    def test_web_ui_has_real_volume_control_and_no_tiktok_default(self):
        html = html_page().decode("utf-8")

        self.assertEqual(DEFAULT_TARGET, "")
        self.assertIn('id="volume"', html)
        self.assertIn(WEB_UI_VERSION, html)
        self.assertIn('value="stress"', html)
        self.assertIn("volume:$('volume').value", html)
        self.assertIn('placeholder="输入产品链接、关键词、达人主页、视频链接、话题或直播间"', html)
        self.assertIn("function remediationRows", html)
        self.assertIn("修复清单 CSV", html)
        self.assertIn("验收报告 Markdown", html)
        self.assertIn("客户验收指南", html)
        self.assertIn("验收包首页 HTML", html)
        self.assertIn("验收包 Manifest", html)
        self.assertIn("最新验收指南", html)
        self.assertIn("最新验收包首页", html)
        self.assertIn("最新 Manifest", html)
        self.assertIn("/api/download?path=", html)
        self.assertIn("本地验收输入模板", html)
        self.assertIn("/api/acceptance-input-template", html)
        self.assertIn("profile_error_summary", html)
        self.assertIn("客户端门禁", html)
        self.assertIn("final_delivery_ready", html)
        self.assertIn("failed_checks", html)
        self.assertIn("blocked_by_environment", html)
        self.assertIn("授权准备报告", html)
        self.assertIn("data.report_path", html)
        self.assertNotIn("7656416339531205901", html)

    def test_web_ui_normalizes_profile_limit_to_safe_bounds(self):
        self.assertEqual(normalize_profile_limit(None), 3)
        self.assertEqual(normalize_profile_limit("-9"), 1)
        self.assertEqual(normalize_profile_limit("7"), 7)
        self.assertEqual(normalize_profile_limit("9999"), MAX_START_PROFILE_LIMIT)

    def test_web_ui_only_trusts_local_api_hosts(self):
        self.assertTrue(is_local_api_host("127.0.0.1:8766"))
        self.assertTrue(is_local_api_host("localhost"))
        self.assertTrue(is_local_api_host("::1"))
        self.assertTrue(is_local_api_host("[::1]:8766"))
        self.assertTrue(is_local_api_host("http://127.0.0.1:8766"))
        self.assertFalse(is_local_api_host("0.0.0.0"))
        self.assertFalse(is_local_api_host("192.168.1.50"))
        self.assertFalse(is_local_api_host("example.com"))
        self.assertFalse(is_local_api_host("http://evil.example"))

    def test_web_ui_bind_host_is_restricted_to_loopback(self):
        self.assertEqual(normalize_local_bind_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(normalize_local_bind_host("localhost"), "localhost")
        self.assertEqual(normalize_local_bind_host("[::1]"), "::1")
        self.assertEqual(format_url_host("::1"), "[::1]")
        with self.assertRaises(ValueError):
            normalize_local_bind_host("0.0.0.0")
        with self.assertRaises(ValueError):
            normalize_local_bind_host("192.168.1.50")

    def test_web_ui_controls_are_bound_to_real_local_api_endpoints(self):
        html = html_page().decode("utf-8")

        for control_id in ['id="start"', 'id="pause"', 'id="resume"', 'id="stop"', 'id="refresh"', 'id="refreshGroups"']:
            self.assertIn(control_id, html)
        self.assertIn('id="start" disabled', html)
        self.assertIn('id="initAcceptanceInputs"', html)
        self.assertIn('id="liveConfirm"', html)
        self.assertIn('id="activationState"', html)
        self.assertIn('id="finalStatusState"', html)
        self.assertIn('id="finalStatusActions"', html)
        self.assertIn('id="finalStatusCommands"', html)
        self.assertIn("最终交付下一步", html)
        self.assertIn("最终复核命令", html)
        self.assertIn("async function refreshActivation()", html)
        self.assertIn("async function refreshFinalStatus()", html)
        self.assertIn("fetch('/api/activation')", html)
        self.assertIn("fetch('/api/final-status')", html)
        self.assertIn("next_required_actions", html)
        self.assertIn("verification_commands", html)
        self.assertIn("report_path", html)
        self.assertIn("safeDownload(data.report_path)", html)
        self.assertIn("live_comment_confirmation_required", html)
        self.assertIn("liveConfirm:$('liveConfirm').checked", html)
        self.assertIn("async function start()", html)
        self.assertIn("async function postJson(url, payload)", html)
        self.assertIn("function showApiNotice", html)
        self.assertIn("let apiNoticeUntil = 0", html)
        self.assertIn("function apiNoticeActive()", html)
        self.assertIn("apiNoticeUntil = Date.now() + Math.max(0, Number(ttlMs || 0))", html)
        self.assertIn("postJson('/api/start'", html)
        self.assertIn("target:$('target').value", html)
        self.assertIn("sourceType:$('sourceType').value", html)
        self.assertIn("group:$('group').value", html)
        self.assertIn("profiles:$('profiles').value", html)
        self.assertIn("mode:$('mode').value", html)
        self.assertIn("volume:$('volume').value", html)
        self.assertIn("commentText:$('commentText').value", html)
        self.assertIn("不会真实提交评论", html)
        self.assertIn("apiNoticeUntil = 0", html)
        self.assertIn("refreshAcceptance();", html)
        self.assertIn("}, 4200)", html)
        self.assertIn("postJson('/api/control'", html)
        self.assertIn("postJson('/api/acceptance-input-init'", html)
        self.assertIn("async function initAcceptanceInputs()", html)
        self.assertIn("showApiNotice('启动被系统拦截'", html)
        self.assertIn("showApiNotice('已有执行在运行'", html)
        self.assertIn("showApiNotice(`控制未执行：${action}`", html)
        self.assertIn("$('start').onclick = start", html)
        self.assertIn("$('pause').onclick = () => control('pause')", html)
        self.assertIn("$('resume').onclick = () => control('resume')", html)
        self.assertIn("$('stop').onclick = () => control('stop')", html)
        self.assertIn("$('initAcceptanceInputs').onclick = initAcceptanceInputs", html)
        self.assertIn("$('refresh').onclick", html)
        self.assertIn("fetch('/api/logs')", html)
        self.assertIn("fetch('/api/snapshot')", html)
        self.assertIn("fetch('/api/acceptance')", html)
        self.assertIn("fetch('/api/final-status')", html)
        self.assertIn("fetch(force ? '/api/groups?refresh=1' : '/api/groups')", html)
        self.assertNotIn("fetch(force ? '/api/groups?refresh=1&background=1' : '/api/groups')", html)
        self.assertIn("refreshLogs();", html)
        self.assertIn("append_group_refresh_log", Path(reachops_web_ui.__file__).read_text(encoding="utf-8"))
        self.assertIn("refresh_groups source=web_ui", Path(reachops_web_ui.__file__).read_text(encoding="utf-8"))
        self.assertIn("正在刷新账号分组", html)
        self.assertIn("await refreshGroups();", html)
        self.assertIn("启动前已自动刷新 ixBrowser 配置分组", html)
        self.assertIn("同步确认中", html)
        self.assertIn('id="refreshGroupsInline"', html)
        self.assertIn('class="groupField"', html)
        self.assertIn("class=\"groupControl\"", html)
        self.assertIn("id=\"selectedGroupBar\"", html)
        self.assertIn("id=\"selectedGroupCount\"", html)
        self.assertIn("可读取账号数", html)
        self.assertIn("selectedGroupId", html)
        self.assertIn("class=\"taskForm\"", html)
        self.assertIn("class=\"taskParams\"", html)
        self.assertIn("class=\"taskActions\"", html)
        self.assertIn("grid-template-columns:repeat(auto-fit,minmax(176px,1fr))", html)
        self.assertNotIn("待读取账号数", html)
        self.assertIn("$('refreshGroupsInline').onclick = () => { refreshIxBrowserStatus(); refreshGroups(); }", html)
        self.assertIn("let groupListReady = false", html)
        self.assertIn("$('start').disabled = !groupListReady", html)
        self.assertIn("未读取到 ixBrowser 配置分组；不可启动", html)
        self.assertIn("启动前已自动刷新 ixBrowser 配置分组", html)
        self.assertIn("本地服务连接失败", html)
        self.assertIn("$('runState').textContent = 'OFFLINE'", html)
        self.assertIn("$('acceptanceState').textContent = '验收状态：本地服务连接失败'", html)
        self.assertNotIn("保留 United States 默认执行", html)
        self.assertIn("profile_group_not_found", Path(reachops_web_ui.__file__).read_text(encoding="utf-8"))
        self.assertIn("profile_group_list_unavailable", Path(reachops_web_ui.__file__).read_text(encoding="utf-8"))

    def test_acceptance_annotation_records_low_intent_no_action_reason(self):
        acceptance = {"next_actions": ["重新点击开始获客，观察是否出现 DONE collection 和 START action_*。"]}
        operations = {"counts": {"candidates": 2, "qualified_leads": 0, "actions": 0}}
        batch = {"status": "completed"}

        reachops_web_ui.annotate_acceptance_with_operations(acceptance, operations, batch)

        reason = acceptance["no_action_reason"]
        self.assertEqual(reason["code"], "low_intent_candidates")
        self.assertEqual(reason["candidate_count"], 2)
        self.assertEqual(reason["qualified_lead_count"], 0)
        self.assertEqual(reason["action_count"], 0)
        self.assertTrue(reason["no_submit"])
        self.assertTrue(any("评分未达到触达线" in item for item in acceptance["next_actions"]))
        self.assertNotIn("重新点击开始获客，观察是否出现 DONE collection 和 START action_*。", acceptance["next_actions"])

    def test_acceptance_annotation_records_no_candidate_no_action_reason(self):
        acceptance = {"next_actions": []}
        operations = {"counts": {"candidates": 0, "qualified_leads": 0, "actions": 0}}
        batch = {"status": "partial_failed"}

        reachops_web_ui.annotate_acceptance_with_operations(acceptance, operations, batch)

        reason = acceptance["no_action_reason"]
        self.assertEqual(reason["code"], "no_candidates")
        self.assertEqual(reason["candidate_count"], 0)
        self.assertEqual(reason["qualified_lead_count"], 0)
        self.assertEqual(reason["action_count"], 0)
        self.assertTrue(any("没有采集到候选用户" in item for item in acceptance["next_actions"]))

    def test_web_panel_runtime_smoke_proves_real_api_execution_chain(self):
        result = run_runtime_smoke()

        self.assertTrue(result["passed"], result.get("failed_checks"))
        self.assertTrue(result["checks"]["start_launches_headless_runner"])
        self.assertTrue(result["checks"]["control_pause_reaches_process_signal"])
        self.assertTrue(result["checks"]["control_resume_reaches_process_signal"])
        self.assertTrue(result["checks"]["control_stop_finalizes_runtime_state"])
        self.assertTrue(result["checks"]["final_status_endpoint_reports_no_browser_no_submit"])
        self.assertTrue(result["checks"]["goal_delivery_refresh_endpoint_generates_target_report"])
        self.assertTrue(result["checks"]["acceptance_exposes_goal_delivery_boundary"])
        self.assertIn("tools/run_reachops_headless_macos.py", " ".join(result["captured_command"]))
        self.assertIn("--profile-limit", result["captured_command"])
        self.assertIn(str(MAX_START_PROFILE_LIMIT), result["captured_command"])

    def test_web_panel_dom_smoke_clicks_buttons_and_shows_api_feedback(self):
        result = run_dom_smoke()

        self.assertTrue(result["passed"], result.get("failed_checks"))
        self.assertTrue(result["checks"]["click_start_posts_api_start"])
        self.assertTrue(result["checks"]["click_start_posts_operator_payload"])
        self.assertTrue(result["checks"]["click_controls_post_api_control"])
        self.assertTrue(result["checks"]["unconfirmed_live_comment_click_does_not_post_start"])
        self.assertTrue(result["checks"]["activation_status_is_visible_to_operator"])
        self.assertTrue(result["checks"]["final_status_is_visible_to_operator"])
        self.assertTrue(result["checks"]["operator_notice_updates_after_api_response"])
        self.assertTrue(result["checks"]["click_init_acceptance_inputs_posts_api"])
        self.assertTrue(result["checks"]["init_acceptance_inputs_feedback_visible_to_operator"])
        self.assertTrue(result["checks"]["final_status_commands_visible_to_operator"])
        self.assertTrue(result["checks"]["start_button_reenabled_after_click"])
        self.assertEqual(result["control_title"], "控制已执行：stop")
        self.assertIn("stopped", result["control_body"])
        self.assertEqual(result["init_notice_title"], "已生成本地验收输入")
        self.assertIn("reachops_final_acceptance_gate.py", result["final_status_commands"])
        self.assertIn("无激活文件", result["activation_state"])
        self.assertIn("不可最终交付", result["final_status_state"])

    def test_acceptance_api_includes_client_delivery_gate(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.LOG_PATH.parent.mkdir(parents=True)
                reachops_web_ui.LOG_PATH.write_text(
                    "\n".join(
                        [
                            "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                            "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight",
                            "BLOCK  campaign failed batch=gb_3 reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
                        ]
                    ),
                    encoding="utf-8",
                )
                existing_delivery_check = (
                    reachops_web_ui.DATA_DIR
                    / "reports"
                    / "acceptance_remediation"
                    / "latest_delivery_check.json"
                )
                existing_delivery_check.parent.mkdir(parents=True)
                existing_delivery_check.write_text(
                    json.dumps(
                        {
                            "ixbrowser_metadata": {
                                "status": "ok",
                                "safe_read_only": True,
                                "open_profile_called": False,
                                "profile_count": 0,
                                "group_count": 0,
                                "selected_profile_count": 0,
                            }
                        }
                    ),
                    encoding="utf-8",
                )

                payload = reachops_web_ui.build_acceptance_payload()
                delivery_check_path = Path(payload["client_delivery"]["delivery_check_path"])
                delivery_check_exists = delivery_check_path.is_file()
                delivery_check_saved = json.loads(delivery_check_path.read_text(encoding="utf-8"))
            finally:
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(payload["acceptance"]["readiness"], "blocked_by_environment")
        self.assertEqual(payload["client_delivery"]["status"], "blocked_by_environment")
        self.assertFalse(payload["client_delivery"]["final_delivery_ready"])
        self.assertEqual(payload["client_delivery"]["failed_checks"], ["acceptance:ready"])
        self.assertEqual(payload["client_delivery"]["ixbrowser_metadata"]["status"], "ok")
        self.assertFalse(payload["client_delivery"]["ixbrowser_metadata"]["open_profile_called"])
        self.assertEqual(delivery_check_saved["ixbrowser_metadata"]["profile_count"], 0)
        self.assertTrue(delivery_check_exists)
        self.assertEqual(delivery_check_path.name, "latest_delivery_check.json")

    def test_ai_console_payload_attaches_client_delivery_summary_for_plan_updates(self):
        acceptance_payload = {
            "client_delivery": {
                "status": "blocked_by_accounts",
                "readiness": "blocked_by_accounts",
                "acceptance_ready": False,
                "final_delivery_ready": False,
                "failed_checks": ["acceptance:ready"],
                "blockers": ["账号预检没有可用账号"],
                "next_actions": ["先修复 United States 分组账号。"],
                "no_browser_started": True,
                "no_submit": True,
            },
            "acceptance": {"blockers": []},
        }
        with patch("tools.reachops_web_ui.read_current_run_session", return_value={}), patch(
            "tools.reachops_web_ui.read_run_result_payload", return_value={}
        ), patch("tools.reachops_web_ui.build_current_evidence_bundle", return_value={}), patch(
            "tools.reachops_web_ui.build_offline_learning_payload", return_value={"record_count": 0}
        ), patch(
            "tools.reachops_web_ui.build_acceptance_payload", return_value=acceptance_payload
        ):
            result = reachops_web_ui.build_ai_console_payload(
                {
                    "message": "只采集不评论",
                    "form": {
                        "target": "anti aging serum",
                        "sourceType": "keyword",
                        "group": "United States",
                        "mode": "preflight",
                        "volume": "quick",
                        "profiles": "3",
                    },
                }
            )

        self.assertEqual(result["intent"], "plan_update")
        self.assertEqual(result["execution_plan"]["mode"], "collect")
        self.assertEqual(result["client_delivery"]["status"], "blocked_by_accounts")
        self.assertEqual(result["client_delivery_summary"]["status"], "blocked_by_accounts")
        self.assertEqual(result["client_delivery_summary"]["blocker_count"], 1)
        self.assertEqual(result["client_delivery_summary"]["next_action_count"], 1)
        self.assertTrue(result["client_delivery_summary"]["no_ai_token_used"])
        self.assertTrue(result["client_delivery_summary"]["no_browser_started"])
        self.assertTrue(result["client_delivery_summary"]["no_submit"])

    def test_acceptance_http_endpoint_exposes_client_gate_to_web_operator(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.LOG_PATH.parent.mkdir(parents=True)
                reachops_web_ui.LOG_PATH.write_text(
                    "\n".join(
                        [
                            "PLAN   campaign id=acq_http input_type=product_url product=demo",
                            "START  campaign id=acq_http batch=gb_http status=pending stage=profile_preflight",
                            "BLOCK  campaign failed batch=gb_http reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
                        ]
                    ),
                    encoding="utf-8",
                )
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{host}:{port}/api/acceptance", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                delivery_check_exists = Path(payload["client_delivery"]["delivery_check_path"]).is_file()
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(payload["acceptance"]["readiness"], "blocked_by_environment")
        self.assertEqual(payload["client_delivery"]["status"], "blocked_by_environment")
        self.assertTrue(payload["client_delivery"]["contract_ok"])
        self.assertFalse(payload["client_delivery"]["final_delivery_ready"])
        self.assertEqual(payload["client_delivery"]["failed_checks"], ["acceptance:ready"])
        self.assertTrue(delivery_check_exists)

    def test_logs_http_endpoint_exposes_structured_headless_failure_result(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_started_at = reachops_web_ui.RUN_STARTED_AT
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.RUN_STARTED_AT = 0.0
                reachops_web_ui.LOG_PATH.parent.mkdir(parents=True)
                reachops_web_ui.LOG_PATH.write_text(
                    "\n".join(
                        [
                            "RUN    web_headless_start target=anti aging serum",
                            "START  campaign id=acq_timeout batch=gb_timeout status=pending stage=profile_preflight",
                            "BLOCK  campaign failed batch=gb_timeout reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
                        ]
                    ),
                    encoding="utf-8",
                )
                reachops_web_ui.RESULT_PATH.write_text(
                    json.dumps(
                        {
                            "status": "timeout_finalized",
                            "timeout_finalization": {
                                "finalized": True,
                                "batch_id": "gb_timeout",
                                "reason": "HEADLESS_TIMEOUT",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{host}:{port}/api/logs", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.RUN_STARTED_AT = old_started_at

        self.assertFalse(payload["running"])
        self.assertTrue(payload["run_failed"])
        self.assertEqual(payload["run_result_status"], "timeout_finalized")
        self.assertEqual(payload["run_result"]["timeout_finalization"]["reason"], "HEADLESS_TIMEOUT")
        self.assertIn("HEADLESS_TIMEOUT", payload["last_stage"])

    def test_logs_http_endpoint_extracts_json_result_from_mixed_headless_output(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_started_at = reachops_web_ui.RUN_STARTED_AT
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.RUN_STARTED_AT = 0.0
                reachops_web_ui.LOG_PATH.parent.mkdir(parents=True)
                reachops_web_ui.LOG_PATH.write_text(
                    "\n".join(
                        [
                            "RUN    web_headless_start target=anti aging serum",
                            "BLOCK  campaign failed batch=gb_mixed reason=HEADLESS_TIMEOUT",
                        ]
                    ),
                    encoding="utf-8",
                )
                reachops_web_ui.RESULT_PATH.write_text(
                    "\n".join(
                        [
                            "READY  headless_app_started data_dir=/tmp/reachops",
                            json.dumps(
                                {
                                    "status": "timeout_finalized",
                                    "timeout_finalization": {
                                        "finalized": True,
                                        "batch_id": "gb_mixed",
                                        "reason": "HEADLESS_TIMEOUT",
                                    },
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            "WARN   trailing stdout after result",
                        ]
                    ),
                    encoding="utf-8",
                )
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{host}:{port}/api/logs", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.RUN_STARTED_AT = old_started_at

        self.assertFalse(payload["running"])
        self.assertTrue(payload["run_failed"])
        self.assertEqual(payload["run_result_status"], "timeout_finalized")
        self.assertEqual(payload["run_result"]["timeout_finalization"]["batch_id"], "gb_mixed")

    def test_get_api_endpoint_rejects_untrusted_origin(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/acceptance",
                    headers={"Origin": "https://evil.example"},
                    method="GET",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "untrusted_origin")

    def test_unknown_get_api_endpoint_returns_json_404(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(f"http://{host}:{port}/api/does-not-exist", timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "unknown_api")

    def test_unknown_post_api_endpoint_returns_json_404(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/does-not-exist",
                    data=json.dumps({"target": "anti aging serum"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "unknown_api")

    def test_activation_http_endpoint_reports_no_browser_no_submit_state(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{host}:{port}/api/activation", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["ready"])
        self.assertTrue(payload["no_browser_started"])
        self.assertTrue(payload["no_submit"])
        self.assertIn("activation_status_path", payload)

    def test_final_status_http_endpoint_reports_no_browser_no_submit_state(self):
        server = None
        thread = None
        try:
            server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            host, port = server.server_address
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with patch(
                "tools.reachops_web_ui.build_final_status_payload",
                return_value={
                    "status": "blocked",
                    "final_delivery_ready": False,
                    "no_browser_started": True,
                    "no_submit": True,
                    "failed_checks": ["delivery_package:passed"],
                    "blocked_reasons": ["Windows 交付包未达到 final_delivery_ready=true。"],
                    "verification_commands": ["python tools\\reachops_final_acceptance_gate.py --json"],
                },
            ):
                with opener.open(f"http://{host}:{port}/api/final-status", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertTrue(payload["no_browser_started"])
        self.assertTrue(payload["no_submit"])
        self.assertEqual(payload["failed_checks"], ["delivery_package:passed"])
        self.assertEqual(payload["verification_commands"], ["python tools\\reachops_final_acceptance_gate.py --json"])

    def test_final_status_payload_writes_downloadable_live_readiness_report(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                with patch(
                    "tools.reachops_web_ui.summarize_mvp_acceptance",
                    return_value={"status": "mvp_accepted_external_pending", "mvp_local_ready": True},
                ), patch(
                    "tools.reachops_web_ui.summarize_goal_delivery",
                    return_value={"status": "local_mvp_accepted_final_pending", "final_delivery_ready": False},
                ):
                    payload = reachops_web_ui.build_final_status_payload()
                    report_path = Path(payload["report_path"])
                    safe_download_path = safe_report_download_path(str(report_path))
            finally:
                reachops_web_ui.DATA_DIR = old_data_dir

            self.assertEqual(payload["status"], "blocked")
            self.assertTrue(report_path.exists())
            self.assertIn("latest_live_acceptance_readiness.md", str(report_path))
            self.assertIn("ReachOps Live Acceptance Readiness", report_path.read_text(encoding="utf-8"))
            self.assertEqual(safe_download_path, report_path.resolve())

    def test_start_http_endpoint_rejects_empty_target_before_launch(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "  "}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "target_required")
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_untrusted_origin_without_launching(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "untrusted_origin")
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_live_comment_without_confirmation(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "mode": "live_comment"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "live_comment_confirmation_required")
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_live_comment_without_activation(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "mode": "live_comment", "liveConfirm": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "LIVE_SUBMIT_NOT_AUTHORIZED")
        self.assertIn("activation_status_path", payload)
        self.assertTrue(payload["no_browser_started"])
        self.assertTrue(payload["no_submit"])
        self.assertIn("activation_status_file_exists", payload["failed_checks"])
        self.assertTrue(any("激活状态文件" in item for item in payload["next_actions"]))
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_handler_rejects_account_gate_without_launching_process(self):
        body = json.dumps(
            {
                "target": "anti aging serum",
                "mode": "preflight",
                "group": "United States",
                "profiles": 3,
            }
        ).encode("utf-8")
        headers = Message()
        headers["Host"] = "127.0.0.1:8769"
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        handler = object.__new__(reachops_web_ui.Handler)
        handler.path = "/api/start"
        handler.headers = headers
        handler.rfile = BytesIO(body)
        captured = {}

        def capture_json(payload, status=200):
            captured["payload"] = payload
            captured["status"] = status

        handler._send_json = capture_json
        old_process = reachops_web_ui.RUN_PROCESS
        try:
            reachops_web_ui.RUN_PROCESS = None
            with patch("tools.reachops_web_ui.validate_profile_group_for_start", return_value=(True, {"group": {"name": "United States"}})):
                with patch(
                    "tools.reachops_web_ui.validate_account_repair_for_start",
                    return_value=(
                        False,
                        {
                            "status": "rejected",
                            "error": "account_repair_required",
                            "message": "账号未修复",
                            "no_browser_started": True,
                            "no_submit": True,
                        },
                    ),
                ) as account_gate:
                    with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                        reachops_web_ui.Handler.do_POST(handler)
        finally:
            reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(captured["status"], 409)
        self.assertEqual(captured["payload"]["status"], "rejected")
        self.assertEqual(captured["payload"]["error"], "account_repair_required")
        self.assertTrue(captured["payload"]["no_browser_started"])
        self.assertTrue(captured["payload"]["no_submit"])
        account_gate.assert_called_once_with("United States", False)
        popen.assert_not_called()

    def test_account_repair_gate_blocks_only_matching_group(self):
        delivery = {
            "status": "blocked_by_accounts",
            "profile_available": 0,
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "ixbrowser_metadata": {"group_name_filter": "United States"},
            "checks": [
                {"name": "report:account_plan_markdown_path", "path": "/tmp/us_account_plan.md"},
                {"name": "report:account_plan_json_path", "path": "/tmp/us_account_plan.json"},
                {"name": "report:latest_account_plan_markdown_path", "path": "/tmp/latest_account_plan.md"},
                {"name": "report:latest_account_plan_json_path", "path": "/tmp/latest_account_plan.json"},
            ],
        }

        with patch("tools.reachops_client_delivery_check.build_delivery_check", return_value=delivery), patch(
            "tools.reachops_client_delivery_check.write_delivery_check"
        ) as write_check:
            same_ok, same_payload = reachops_web_ui.validate_account_repair_for_start("United States", False)
            other_ok, other_payload = reachops_web_ui.validate_account_repair_for_start("Canada", False)

        self.assertFalse(same_ok)
        self.assertEqual(same_payload["error"], "account_repair_required")
        self.assertEqual(same_payload["profile_group"], "United States")
        self.assertEqual(same_payload["account_plan_markdown_path"], "/tmp/us_account_plan.md")
        self.assertEqual(same_payload["latest_account_plan_json_path"], "/tmp/latest_account_plan.json")
        self.assertEqual(len(same_payload["account_repair_plan_paths"]), 4)
        self.assertTrue(other_ok)
        self.assertEqual(other_payload["status"], "blocked_by_accounts")
        self.assertEqual(other_payload["profile_available"], 0)
        self.assertFalse(other_payload["same_group"])
        self.assertEqual(write_check.call_count, 2)

    def test_account_repair_gate_embeds_operator_summary(self):
        with TemporaryDirectory() as td:
            latest_plan = Path(td) / "latest_account_plan.json"
            latest_plan.write_text(
                json.dumps(
                    {
                        "batch_id": "gb_accounts",
                        "batch_status": "failed",
                        "profile_group": "United States",
                        "total_unique_profiles_by_error": 52,
                        "operator_steps": ["先处理内核不匹配账号。"],
                        "groups": [
                            {
                                "error": "IXBROWSER_KERNEL_MISMATCH",
                                "count": 39,
                                "profile_ids": ["21644", "21647", "21655"],
                                "recommended_action": "修改内核版本或移出执行分组。",
                            },
                            {
                                "error": "LOGIN_REQUIRED",
                                "count": 13,
                                "profile_ids": [],
                                "recommended_action": "完成 TikTok 登录。",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            delivery = {
                "status": "blocked_by_accounts",
                "profile_available": 0,
                "ixbrowser_metadata": {"group_name_filter": "United States"},
                "checks": [{"name": "report:latest_account_plan_json_path", "path": str(latest_plan)}],
            }

            with patch("tools.reachops_client_delivery_check.build_delivery_check", return_value=delivery), patch(
                "tools.reachops_client_delivery_check.write_delivery_check"
            ):
                ok, payload = reachops_web_ui.validate_account_repair_for_start("United States", False)

        self.assertFalse(ok)
        summary = payload["account_repair_summary"]
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["profile_group"], "United States")
        self.assertEqual(summary["total_unique_profiles_by_error"], 52)
        self.assertEqual(summary["safety_contract"]["schema_version"], "reachops.account_repair_safety_contract.v1")
        self.assertTrue(summary["safety_contract"]["manual_apply_required"])
        self.assertFalse(summary["safety_contract"]["operator_confirmed_apply"])
        self.assertTrue(summary["safety_contract"]["hard_blocker_only"])
        self.assertTrue(summary["safety_contract"]["moves_only_to_quarantine_group"])
        self.assertTrue(summary["safety_contract"]["no_browser_started"])
        self.assertTrue(summary["safety_contract"]["no_submit"])
        self.assertTrue(summary["safety_contract"]["no_ai_token_used"])
        self.assertEqual(summary["operator_steps"], ["先处理内核不匹配账号。"])
        self.assertEqual(summary["error_groups"][0]["error"], "IXBROWSER_KERNEL_MISMATCH")
        self.assertEqual(summary["error_groups"][0]["count"], 39)
        self.assertEqual(summary["error_groups"][0]["profile_ids_sample"], ["21644", "21647", "21655"])
        self.assertEqual(summary["error_groups"][1]["recommended_action"], "完成 TikTok 登录。")

    def test_account_repair_gate_exposes_stale_apply_state(self):
        delivery = {
            "status": "blocked_by_accounts",
            "profile_available": 0,
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["批量筛出 IXBROWSER_KERNEL_MISMATCH 账号。"],
            "ixbrowser_metadata": {"group_name_filter": "United States"},
            "account_repair_apply": {
                "stale": True,
                "stale_reason": "newer_account_repair_plan_for_current_batch",
                "pending_recheck": False,
                "profile_group": "United States",
            },
        }

        with patch("tools.reachops_client_delivery_check.build_delivery_check", return_value=delivery), patch(
            "tools.reachops_client_delivery_check.write_delivery_check"
        ):
            ok, payload = reachops_web_ui.validate_account_repair_for_start("United States", False)

        self.assertFalse(ok)
        self.assertEqual(payload["error"], "account_repair_required")
        self.assertIn("旧账号修复结果已失效", payload["message"])
        self.assertTrue(payload["account_repair_apply"]["stale"])
        self.assertEqual(payload["account_repair_apply"]["stale_reason"], "newer_account_repair_plan_for_current_batch")

    def test_start_handler_does_not_force_account_recheck_for_non_matching_group_confirmation(self):
        body = json.dumps(
            {
                "target": "anti aging serum",
                "mode": "preflight",
                "group": "Canada",
                "profiles": 3,
                "accountRepairConfirmed": True,
            }
        ).encode("utf-8")
        headers = Message()
        headers["Host"] = "127.0.0.1:8769"
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        handler = object.__new__(reachops_web_ui.Handler)
        handler.path = "/api/start"
        handler.headers = headers
        handler.rfile = BytesIO(body)
        captured = {}

        def capture_json(payload, status=200):
            captured["payload"] = payload
            captured["status"] = status

        class FakeProcess:
            pid = 43210

            def poll(self):
                return None

        popen_kwargs = {}

        def fake_popen(_cmd, **kwargs):
            popen_kwargs.update(kwargs)
            return FakeProcess()

        handler._send_json = capture_json
        old_data_dir = reachops_web_ui.DATA_DIR
        old_log_path = reachops_web_ui.LOG_PATH
        old_result_path = reachops_web_ui.RESULT_PATH
        old_process = reachops_web_ui.RUN_PROCESS
        try:
            with TemporaryDirectory() as tmpdir:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                with patch("tools.reachops_web_ui.validate_profile_group_for_start", return_value=(True, {"group": {"name": "Canada"}})):
                    with patch(
                        "tools.reachops_web_ui.validate_account_repair_for_start",
                        return_value=(
                            True,
                            {"status": "blocked_by_accounts", "profile_available": 0, "same_group": False},
                        ),
                    ) as account_gate:
                        with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                            reachops_web_ui.Handler.do_POST(handler)
        finally:
            reachops_web_ui.DATA_DIR = old_data_dir
            reachops_web_ui.LOG_PATH = old_log_path
            reachops_web_ui.RESULT_PATH = old_result_path
            reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["status"], "started")
        account_gate.assert_called_once_with("Canada", True)
        self.assertNotIn("REACHOPS_FORCE_ACCOUNT_RECHECK", popen_kwargs["env"])

    def test_start_http_endpoint_rejects_invalid_json_without_crashing(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=b"{not-json",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "invalid_json")

    def test_start_http_endpoint_requires_json_object_payload(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=b'["not", "an", "object"]',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "json_object_required")
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_invalid_content_length_without_crashing(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            conn = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.putrequest("POST", "/api/start")
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", "not-a-number")
                conn.endheaders()
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                if conn is not None:
                    conn.close()
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(response.status, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "invalid_content_length")

    def test_start_http_endpoint_rejects_oversized_payload_without_launching(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=b"{" + (b" " * (MAX_JSON_PAYLOAD_BYTES + 1)) + b"}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "payload_too_large")
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_group_not_in_ixbrowser_config_list(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "group": "Ghost Group"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                group_payload = {
                    "groups": [
                        {"name": "Canada", "label": "Canada / 2账号", "count": 2, "count_known": True},
                        {"name": "United States", "label": "United States / 3账号", "count": 3, "count_known": True},
                    ],
                    "error": "",
                    "stale_cache": False,
                }
                with patch("tools.reachops_web_ui.load_groups", return_value=group_payload):
                    with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "profile_group_not_found")
        self.assertIn("Canada", payload["available_groups"])
        self.assertIn("United States", payload["available_groups"])
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_when_ixbrowser_group_list_unavailable(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.GROUP_CACHE = {"loaded_at": time.time(), "groups": [], "error": "ix api down"}
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "group": "United States"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.load_groups", return_value=reachops_web_ui.GROUP_CACHE):
                    with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "profile_group_live_refresh_required")
        self.assertEqual(payload["group_error"], "ix api down")
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_start_http_endpoint_rejects_stale_cached_group_list(self):
        stale_groups_payload = {
            "loaded_at": time.time() - 600,
            "groups": [
                {
                    "name": "United States",
                    "label": "United States / 700账号",
                    "group_id": "257999",
                    "count": 700,
                    "count_known": True,
                    "count_label": "700账号",
                }
            ],
            "profile_count": 700,
            "error": "",
            "stale_cache": True,
        }
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "group": "United States"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.load_groups", return_value=stale_groups_payload):
                    with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "profile_group_live_refresh_required")
        self.assertTrue(payload["stale_cache"])
        popen.assert_not_called()
        self.assertFalse(Path(tmpdir, "reachops_web_ui_last_run.json").exists())

    def test_groups_http_endpoint_times_out_when_ixbrowser_group_refresh_hangs(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_group_cache = reachops_web_ui.GROUP_CACHE
            old_latest_groups_path = reachops_web_ui.LATEST_GROUPS_PATH
            old_timeout = reachops_web_ui.GROUP_REFRESH_TIMEOUT_SECONDS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmpdir) / "config" / "missing_latest_ixbrowser_groups.json"
                reachops_web_ui.GROUP_REFRESH_TIMEOUT_SECONDS = 0.01
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def slow_refresh(self, *args, **kwargs):
                    time.sleep(0.25)
                    return {"groups": [{"group_name": "Late"}], "profile_count": 1, "group_count": 1}

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                started_at = time.time()
                with patch("ReachOps.workbench.standalone_app.StandaloneProfileRegistry.refresh", slow_refresh):
                    with opener.open(f"http://{host}:{port}/api/groups?refresh=1", timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                elapsed = time.time() - started_at
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.GROUP_CACHE = old_group_cache
                reachops_web_ui.LATEST_GROUPS_PATH = old_latest_groups_path
                reachops_web_ui.GROUP_REFRESH_TIMEOUT_SECONDS = old_timeout

        self.assertLess(elapsed, 0.2)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["groups"], [])
        self.assertIn("ixBrowser Local API 读取超时", payload["error"])

    def test_web_group_refresh_reads_group_list_and_resolves_counts_without_full_profile_scan(self):
        old_group_cache = reachops_web_ui.GROUP_CACHE
        old_latest_groups_path = reachops_web_ui.LATEST_GROUPS_PATH
        calls = []
        count_calls = []

        def fake_refresh(self, *args, **kwargs):
            calls.append(dict(kwargs))
            return {
                "groups": [
                    {
                        "group_id": "281726",
                        "group_name": "Canada",
                        "count": 0,
                        "count_known": False,
                    }
                ],
                "profile_count": 0,
                "group_count": 1,
                "profiles_deferred": True,
                "counts_resolved": False,
            }

        def fake_resolve_counts(groups, *args, **kwargs):
            count_calls.append({"groups": list(groups), "kwargs": dict(kwargs)})
            resolved = [dict(row) for row in groups]
            resolved[0]["count"] = 2
            resolved[0]["count_known"] = True
            return resolved

        try:
            reachops_web_ui.GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
            with TemporaryDirectory() as tmpdir:
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmpdir) / "missing_latest_ixbrowser_groups.json"
                with patch("ReachOps.workbench.standalone_app.StandaloneProfileRegistry.refresh", fake_refresh):
                    with patch("ReachOps.workbench.standalone_app.resolve_ixbrowser_group_counts", fake_resolve_counts):
                        payload = reachops_web_ui.load_groups(refresh=True, allow_async=False)
        finally:
            reachops_web_ui.GROUP_CACHE = old_group_cache
            reachops_web_ui.LATEST_GROUPS_PATH = old_latest_groups_path

        self.assertTrue(calls)
        self.assertFalse(calls[-1]["include_profiles"])
        self.assertTrue(count_calls)
        self.assertEqual(payload["profile_count"], 2)
        self.assertTrue(payload["profiles_deferred"])
        self.assertTrue(payload["counts_resolved"])
        self.assertEqual(payload["groups"][0]["label"], "Canada / 2账号")
        self.assertNotIn("?", payload["groups"][0]["label"])

    def test_web_group_cache_prefers_persisted_known_counts_over_memory_without_counts(self):
        old_group_cache = reachops_web_ui.GROUP_CACHE
        old_latest_groups_path = reachops_web_ui.LATEST_GROUPS_PATH
        try:
            with TemporaryDirectory() as tmpdir:
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmpdir) / "latest_ixbrowser_groups.json"
                reachops_web_ui.LATEST_GROUPS_PATH.write_text(
                    json.dumps(
                        {
                            "loaded_at": 1000,
                            "groups": [
                                {
                                    "name": "United States",
                                    "label": "United States / 702账号",
                                    "count": 702,
                                    "count_known": True,
                                    "count_label": "702账号",
                                }
                            ],
                            "profile_count": 2910,
                        }
                    ),
                    encoding="utf-8",
                )
                reachops_web_ui.GROUP_CACHE = {
                    "loaded_at": time.time(),
                    "groups": [
                        {
                            "name": "United States",
                            "label": "United States / 数量未返回",
                            "count": 0,
                            "count_known": False,
                            "count_label": "数量未返回",
                        }
                    ],
                    "profile_count": 0,
                    "error": "ixBrowser Local API 读取超时（10s）",
                    "error_detail": "profile_group_list_timeout_after_10s",
                }

                payload = reachops_web_ui.read_cached_groups_payload()
                non_refresh_payload = reachops_web_ui.load_groups(refresh=False)

            self.assertEqual(payload["groups"][0]["count_label"], "702账号")
            self.assertTrue(payload["groups"][0]["count_known"])
            self.assertEqual(payload["profile_count"], 2910)
            self.assertEqual(non_refresh_payload["groups"][0]["count_label"], "702账号")
            self.assertTrue(non_refresh_payload["groups"][0]["count_known"])
            self.assertEqual(non_refresh_payload["profile_count"], 2910)
            self.assertEqual(non_refresh_payload.get("error"), "")
            self.assertEqual(non_refresh_payload.get("error_detail"), "")
        finally:
            reachops_web_ui.GROUP_CACHE = old_group_cache
            reachops_web_ui.LATEST_GROUPS_PATH = old_latest_groups_path

    def test_web_group_refresh_uses_cached_counts_after_live_group_list_success(self):
        old_group_cache = reachops_web_ui.GROUP_CACHE
        old_latest_groups_path = reachops_web_ui.LATEST_GROUPS_PATH
        calls = []
        count_calls = []

        def fake_refresh(self, *args, **kwargs):
            calls.append(dict(kwargs))
            return {
                "groups": [
                    {
                        "group_id": "257999",
                        "group_name": "United States",
                        "count": 0,
                        "count_known": False,
                    }
                ],
                "profile_count": 0,
                "group_count": 1,
                "profiles_deferred": True,
                "counts_resolved": False,
            }

        def fake_resolve_counts(groups, *args, **kwargs):
            count_calls.append({"groups": list(groups), "kwargs": dict(kwargs)})
            return groups

        try:
            reachops_web_ui.GROUP_CACHE = {"loaded_at": 0.0, "groups": [], "error": ""}
            with TemporaryDirectory() as tmpdir:
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmpdir) / "latest_ixbrowser_groups.json"
                reachops_web_ui.LATEST_GROUPS_PATH.write_text(
                    json.dumps(
                        {
                            "loaded_at": 1000,
                            "groups": [
                                {
                                    "name": "United States",
                                    "group_id": "257999",
                                    "label": "United States / 717账号",
                                    "count": 717,
                                    "count_known": True,
                                    "count_label": "717账号",
                                }
                            ],
                            "profile_count": 2910,
                        }
                    ),
                    encoding="utf-8",
                )
                with patch("ReachOps.workbench.standalone_app.StandaloneProfileRegistry.refresh", fake_refresh):
                    with patch("ReachOps.workbench.standalone_app.resolve_ixbrowser_group_counts", fake_resolve_counts):
                        payload = reachops_web_ui.load_groups(refresh=True, allow_async=False)
        finally:
            reachops_web_ui.GROUP_CACHE = old_group_cache
            reachops_web_ui.LATEST_GROUPS_PATH = old_latest_groups_path

        self.assertTrue(calls)
        self.assertFalse(count_calls)
        self.assertFalse(payload["stale_cache"])
        self.assertTrue(payload["live_all_group_counts_known"])
        self.assertEqual(payload["groups"][0]["name"], "United States")
        self.assertEqual(payload["groups"][0]["count"], 717)
        self.assertEqual(payload["groups"][0]["count_source"], "cached_known_count_after_live_group_list")

    def test_web_group_cache_clears_stale_flag_after_known_counts_are_available(self):
        old_group_cache = reachops_web_ui.GROUP_CACHE
        old_latest_groups_path = reachops_web_ui.LATEST_GROUPS_PATH
        try:
            with TemporaryDirectory() as tmpdir:
                reachops_web_ui.LATEST_GROUPS_PATH = Path(tmpdir) / "latest_ixbrowser_groups.json"
                reachops_web_ui.GROUP_CACHE = {
                    "loaded_at": time.time(),
                    "groups": [
                        {
                            "name": "United States",
                            "label": "United States / 700账号",
                            "count": 700,
                            "count_known": True,
                            "count_label": "700账号",
                        }
                    ],
                    "profile_count": 700,
                    "known_group_count": 1,
                    "error": "",
                    "error_detail": "",
                    "stale_cache": True,
                    "background_refresh": False,
                }

                with patch("tools.reachops_web_ui.group_refresh_background_active", return_value=False):
                    payload = reachops_web_ui.load_groups(refresh=False)

            self.assertEqual(payload["groups"][0]["count_label"], "700账号")
            self.assertTrue(payload["groups"][0]["count_known"])
            self.assertFalse(payload.get("stale_cache"))
            self.assertFalse(payload.get("background_refresh"))
            self.assertFalse(payload.get("refresh_started"))
        finally:
            reachops_web_ui.GROUP_CACHE = old_group_cache
            reachops_web_ui.LATEST_GROUPS_PATH = old_latest_groups_path

    def test_start_http_endpoint_reports_launch_failure_as_json(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.append_web_log") as append_log:
                    with self.start_gates_pass():
                        with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=OSError("python missing")):
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                opener.open(request, timeout=5)
                log_calls = [str(call.args[0]) for call in append_log.call_args_list]
                payload = json.loads(raised.exception.read().decode("utf-8"))
                persisted = json.loads(reachops_web_ui.RESULT_PATH.read_text(encoding="utf-8"))
                with opener.open(f"http://{host}:{port}/api/logs", timeout=5) as response:
                    logs_payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "launch_failed")
        self.assertIn("python missing", payload["message"])
        self.assertEqual(persisted["status"], "launch_failed")
        self.assertIn("python missing", persisted["message"])
        self.assertTrue(logs_payload["run_failed"])
        self.assertEqual(logs_payload["run_result_status"], "launch_failed")
        self.assertTrue(any("web_ui_launch_failed" in item for item in log_calls))

    def test_start_http_endpoint_reports_immediate_headless_exit_as_json(self):
        class ExitedProcess:
            pid = 43211

            def poll(self):
                return 7

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_started_at = reachops_web_ui.RUN_STARTED_AT
            old_healthcheck = reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.RUN_STARTED_AT = 123.0
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = 0
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(_cmd, **kwargs):
                    kwargs["stdout"].write("headless import failed\n")
                    kwargs["stdout"].flush()
                    return ExitedProcess()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.append_web_log") as append_log:
                    with self.start_gates_pass():
                        with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                log_calls = [str(call.args[0]) for call in append_log.call_args_list]
                current_process = reachops_web_ui.RUN_PROCESS
                current_started_at = reachops_web_ui.RUN_STARTED_AT
                persisted = json.loads(reachops_web_ui.RESULT_PATH.read_text(encoding="utf-8"))
                with opener.open(f"http://{host}:{port}/api/logs", timeout=5) as response:
                    logs_payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.RUN_STARTED_AT = old_started_at
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = old_healthcheck

        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "headless_exited_immediately")
        self.assertEqual(payload["exit_code"], 7)
        self.assertIn("headless import failed", payload["output_tail"])
        self.assertEqual(persisted["status"], "headless_exited_immediately")
        self.assertEqual(persisted["exit_code"], 7)
        self.assertIn("headless import failed", persisted["output_tail"])
        self.assertTrue(logs_payload["run_failed"])
        self.assertEqual(logs_payload["run_result_status"], "headless_exited_immediately")
        self.assertIsNone(current_process)
        self.assertEqual(current_started_at, 0.0)
        self.assertTrue(any("web_ui_headless_exited_immediately" in item for item in log_calls))

    def test_start_http_endpoint_reports_result_file_open_failure_as_json(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            blocked_result_path = Path(tmpdir) / "reachops_web_ui_last_run.json"
            blocked_result_path.mkdir()
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = blocked_result_path
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen") as popen:
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "result_file_open_failed")
        popen.assert_not_called()

    def test_start_http_endpoint_closes_parent_stdout_and_reports_existing_run(self):
        class FakeProcess:
            pid = 43210

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            captured = {}
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(_cmd, **kwargs):
                    captured["stdout"] = kwargs["stdout"]
                    return FakeProcess()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "profiles": 2}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        with opener.open(request, timeout=5) as response:
                            started = json.loads(response.read().decode("utf-8"))

                    duplicate_request = urllib.request.Request(
                        f"http://{host}:{port}/api/start",
                        data=json.dumps({"target": "another target"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with opener.open(duplicate_request, timeout=5) as response:
                        duplicate = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(started["status"], "started")
        self.assertEqual(started["pid"], 43210)
        self.assertTrue(captured["stdout"].closed)
        self.assertEqual(duplicate["status"], "already_running")
        self.assertEqual(duplicate["pid"], 43210)

    def test_start_http_endpoint_serializes_concurrent_starts(self):
        class FakeProcess:
            pid = 43218

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_healthcheck = reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS
            popen_entered = threading.Event()
            release_popen = threading.Event()
            popen_calls = []
            responses = []
            errors = []
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = 0
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(_cmd, **_kwargs):
                    popen_calls.append(1)
                    popen_entered.set()
                    release_popen.wait(timeout=3)
                    return FakeProcess()

                host, port = server.server_address

                def post_start(target):
                    try:
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        request = urllib.request.Request(
                            f"http://{host}:{port}/api/start",
                            data=json.dumps({"target": target}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with opener.open(request, timeout=5) as response:
                            responses.append(json.loads(response.read().decode("utf-8")))
                    except Exception as exc:
                        errors.append(exc)

                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        first = threading.Thread(target=post_start, args=("anti aging serum",))
                        second = threading.Thread(target=post_start, args=("retinol serum",))
                        first.start()
                        self.assertTrue(popen_entered.wait(timeout=3))
                        second.start()
                        time.sleep(0.05)
                        release_popen.set()
                        first.join(timeout=5)
                        second.join(timeout=5)
            finally:
                release_popen.set()
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = old_healthcheck

        self.assertFalse(errors)
        self.assertEqual(len(popen_calls), 1)
        self.assertEqual(sorted(row["status"] for row in responses), ["already_running", "started"])
        started = [row for row in responses if row["status"] == "started"][0]
        duplicate = [row for row in responses if row["status"] == "already_running"][0]
        self.assertEqual(started["pid"], 43218)
        self.assertEqual(duplicate["pid"], 43218)

    def test_control_stop_waits_for_inflight_start_before_stopping_process(self):
        class FakeProcess:
            pid = 43219

            def __init__(self):
                self.exited = False

            def poll(self):
                return 0 if self.exited else None

            def wait(self, timeout=None):
                self.exited = True
                return 0

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            old_healthcheck = reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS
            fake_process = FakeProcess()
            popen_entered = threading.Event()
            release_popen = threading.Event()
            responses = {}
            errors = []
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = 0
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(_cmd, **_kwargs):
                    popen_entered.set()
                    release_popen.wait(timeout=3)
                    return fake_process

                host, port = server.server_address

                def post_json(name, url, payload):
                    try:
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        request = urllib.request.Request(
                            f"http://{host}:{port}{url}",
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with opener.open(request, timeout=5) as response:
                            responses[name] = json.loads(response.read().decode("utf-8"))
                    except Exception as exc:
                        errors.append(exc)

                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        with patch("tools.reachops_web_ui.os.killpg", return_value=None):
                            start_thread = threading.Thread(
                                target=post_json,
                                args=("start", "/api/start", {"target": "anti aging serum"}),
                            )
                            stop_thread = threading.Thread(
                                target=post_json,
                                args=("stop", "/api/control", {"action": "stop"}),
                            )
                            start_thread.start()
                            self.assertTrue(popen_entered.wait(timeout=3))
                            stop_thread.start()
                            time.sleep(0.05)
                            release_popen.set()
                            start_thread.join(timeout=5)
                            stop_thread.join(timeout=5)
                    process_after_stop = reachops_web_ui.RUN_PROCESS
            finally:
                release_popen.set()
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.STARTUP_HEALTHCHECK_SECONDS = old_healthcheck

        self.assertFalse(errors)
        self.assertEqual(responses["start"]["status"], "started")
        self.assertEqual(responses["stop"]["status"], "stopped")
        self.assertEqual(responses["stop"]["pid"], 43219)
        self.assertTrue(fake_process.exited)
        self.assertIsNone(process_after_stop)

    def test_start_http_endpoint_normalizes_invalid_mode_and_volume_before_launch(self):
        class FakeProcess:
            pid = 43215

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            captured = {}
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(cmd, **kwargs):
                    captured["cmd"] = list(cmd)
                    captured["stdout"] = kwargs["stdout"]
                    return FakeProcess()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "mode": "bogus", "volume": "huge"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        with opener.open(request, timeout=5) as response:
                            payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        mode_index = captured["cmd"].index("--mode") + 1
        volume_index = captured["cmd"].index("--volume") + 1
        base_dir_index = captured["cmd"].index("--base-dir") + 1
        max_videos_index = captured["cmd"].index("--max-videos") + 1
        max_comments_index = captured["cmd"].index("--max-comments") + 1
        timeout_index = captured["cmd"].index("--timeout") + 1
        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["mode"], "采集 + 触达预检")
        self.assertEqual(captured["cmd"][base_dir_index], tmpdir)
        self.assertEqual(captured["cmd"][mode_index], "preflight")
        self.assertEqual(captured["cmd"][volume_index], "quick")
        self.assertEqual(captured["cmd"][max_videos_index], "3")
        self.assertEqual(captured["cmd"][max_comments_index], "20")
        self.assertGreaterEqual(int(captured["cmd"][timeout_index]), 900)
        self.assertEqual(payload["timeout_seconds"], int(captured["cmd"][timeout_index]))
        self.assertTrue(captured["stdout"].closed)

    def test_start_http_endpoint_uses_longer_timeout_for_stress_runs(self):
        class FakeProcess:
            pid = 43220

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            captured = {}
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(cmd, **kwargs):
                    captured["cmd"] = list(cmd)
                    captured["stdout"] = kwargs["stdout"]
                    return FakeProcess()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps(
                        {
                            "target": "anti aging serum",
                            "mode": "preflight",
                            "volume": "stress",
                            "profiles": 3,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        with opener.open(request, timeout=5) as response:
                            payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        timeout_seconds = int(captured["cmd"][captured["cmd"].index("--timeout") + 1])
        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["volume"], "stress")
        self.assertEqual(captured["cmd"][captured["cmd"].index("--max-videos") + 1], "20")
        self.assertEqual(captured["cmd"][captured["cmd"].index("--max-comments") + 1], "100")
        self.assertGreaterEqual(timeout_seconds, 3600)
        self.assertEqual(payload["timeout_seconds"], timeout_seconds)
        self.assertTrue(captured["stdout"].closed)

    def test_start_http_endpoint_clamps_profile_limit_before_launch(self):
        class FakeProcess:
            pid = 43216

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_result_path = reachops_web_ui.RESULT_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            captured = {}
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RESULT_PATH = Path(tmpdir) / "reachops_web_ui_last_run.json"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def fake_popen(cmd, **kwargs):
                    captured["cmd"] = list(cmd)
                    captured["stdout"] = kwargs["stdout"]
                    return FakeProcess()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/start",
                    data=json.dumps({"target": "anti aging serum", "profiles": 9999}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.start_gates_pass():
                    with patch("tools.reachops_web_ui.subprocess.Popen", side_effect=fake_popen):
                        with opener.open(request, timeout=5) as response:
                            payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RESULT_PATH = old_result_path
                reachops_web_ui.RUN_PROCESS = old_process

        profile_limit_index = captured["cmd"].index("--profile-limit") + 1
        base_dir_index = captured["cmd"].index("--base-dir") + 1
        self.assertEqual(payload["status"], "started")
        self.assertEqual(captured["cmd"][base_dir_index], tmpdir)
        self.assertEqual(captured["cmd"][profile_limit_index], str(MAX_START_PROFILE_LIMIT))
        self.assertTrue(captured["stdout"].closed)

    def test_control_http_endpoint_rejects_invalid_json_without_crashing(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=b"[",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "invalid_json")

    def test_control_http_endpoint_rejects_unknown_action_consistently(self):
        class FakeProcess:
            pid = 43211

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = FakeProcess()
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=json.dumps({"action": "bogus"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["error"], "unknown_action")

    def test_control_http_endpoint_reports_signal_failure_as_json(self):
        class FakeProcess:
            pid = 43212

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = FakeProcess()
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=json.dumps({"action": "pause"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.os.killpg", side_effect=PermissionError("denied")):
                    with opener.open(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["pid"], 43212)

    def test_control_pause_uses_cooperative_file_when_signal_unsupported(self):
        class FakeProcess:
            pid = 43214

            def poll(self):
                return None

        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_control_dir = reachops_web_ui.CONTROL_DIR
            old_process = reachops_web_ui.RUN_PROCESS
            old_pause_signal = reachops_web_ui.PAUSE_SIGNAL
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.CONTROL_DIR = Path(tmpdir) / "control"
                reachops_web_ui.RUN_PROCESS = FakeProcess()
                reachops_web_ui.PAUSE_SIGNAL = None
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=json.dumps({"action": "pause"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with opener.open(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                pause_file_exists = (Path(tmpdir) / "control" / "pause.request").exists()
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.CONTROL_DIR = old_control_dir
                reachops_web_ui.RUN_PROCESS = old_process
                reachops_web_ui.PAUSE_SIGNAL = old_pause_signal

        self.assertEqual(payload["status"], "paused")
        self.assertTrue(payload["cooperative_control"])
        self.assertEqual(payload["pid"], 43214)
        self.assertTrue(pause_file_exists)

    def test_control_stop_signal_failure_keeps_running_process_state(self):
        class FakeProcess:
            pid = 43213

            def poll(self):
                return None

        fake_process = FakeProcess()
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = fake_process
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=json.dumps({"action": "stop"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.os.killpg", side_effect=PermissionError("denied")):
                    with opener.open(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    process_after_stop = reachops_web_ui.RUN_PROCESS
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["pid"], 43213)
        self.assertTrue(payload["running"])
        self.assertIs(process_after_stop, fake_process)

    def test_control_stop_keeps_state_when_process_survives_sigkill(self):
        class FakeProcess:
            pid = 43214

            def poll(self):
                return None

            def wait(self, timeout=None):
                raise TimeoutError("still running")

        fake_process = FakeProcess()
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            old_process = reachops_web_ui.RUN_PROCESS
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                reachops_web_ui.RUN_PROCESS = fake_process
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/control",
                    data=json.dumps({"action": "stop"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch("tools.reachops_web_ui.os.killpg", return_value=None):
                    with opener.open(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    process_after_stop = reachops_web_ui.RUN_PROCESS
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path
                reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["pid"], 43214)
        self.assertTrue(payload["running"])
        self.assertIs(process_after_stop, fake_process)

    def test_safe_report_download_path_only_allows_runtime_reports(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                allowed = Path(tmpdir) / "reports" / "acceptance_remediation" / "fix.csv"
                allowed.parent.mkdir(parents=True)
                allowed.write_text("ok", encoding="utf-8")
                denied = Path(tmpdir) / "outside.csv"
                denied.write_text("no", encoding="utf-8")

                self.assertEqual(safe_report_download_path(str(allowed)), allowed.resolve())
                self.assertIsNone(safe_report_download_path(str(denied)))
            finally:
                reachops_web_ui.DATA_DIR = old_data_dir

    def test_download_http_endpoint_reports_file_send_failure_as_json(self):
        with TemporaryDirectory() as tmpdir:
            old_data_dir = reachops_web_ui.DATA_DIR
            old_log_path = reachops_web_ui.LOG_PATH
            server = None
            thread = None
            try:
                reachops_web_ui.DATA_DIR = Path(tmpdir)
                reachops_web_ui.LOG_PATH = Path(tmpdir) / "logs" / "growth_ops_runtime.log"
                allowed = Path(tmpdir) / "reports" / "acceptance_remediation" / "fix.csv"
                allowed.parent.mkdir(parents=True)
                allowed.write_text("ok", encoding="utf-8")
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                url = f"http://{host}:{port}/api/download?path={urllib.parse.quote(str(allowed))}"
                with patch("tools.reachops_web_ui.append_web_log") as append_log:
                    with patch.object(reachops_web_ui.Handler, "_send_file", side_effect=OSError("disk read failed")):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            opener.open(url, timeout=5)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                log_calls = [str(call.args[0]) for call in append_log.call_args_list]
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.DATA_DIR = old_data_dir
                reachops_web_ui.LOG_PATH = old_log_path

        self.assertEqual(raised.exception.code, 500)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "download_failed")
        self.assertIn("disk read failed", payload["message"])
        self.assertTrue(any("web_ui_download_failed" in item for item in log_calls))

    def test_acceptance_input_template_endpoint_downloads_safe_template(self):
        server = None
        thread = None
        try:
            server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            host, port = server.server_address
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://{host}:{port}/api/acceptance-input-template", timeout=5) as response:
                body = response.read().decode("utf-8")
                headers = response.headers
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)

        self.assertIn("reachops_acceptance_inputs.local.ps1", body)
        self.assertIn("$RunControlledLiveSubmit = $false", body)
        self.assertIn("placeholder value", body)
        self.assertIn("reachops_acceptance_inputs.example.ps1", headers.get("Content-Disposition", ""))

    def test_acceptance_input_init_endpoint_creates_local_template_without_overwrite(self):
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            template_path = tmp_path / "reachops_acceptance_inputs.example.ps1"
            local_path = tmp_path / "reachops_acceptance_inputs.local.ps1"
            template_path.write_text("# template\n$RunControlledLiveSubmit = $false\n", encoding="utf-8")
            server = None
            thread = None
            old_template = reachops_web_ui.ACCEPTANCE_INPUT_TEMPLATE_PATH
            old_local = reachops_web_ui.ACCEPTANCE_INPUT_LOCAL_PATH
            try:
                reachops_web_ui.ACCEPTANCE_INPUT_TEMPLATE_PATH = template_path
                reachops_web_ui.ACCEPTANCE_INPUT_LOCAL_PATH = local_path
                server = reachops_web_ui.ThreadingHTTPServer(("127.0.0.1", 0), reachops_web_ui.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                host, port = server.server_address
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/acceptance-input-init",
                    data=json.dumps({}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with opener.open(request, timeout=5) as response:
                    created_payload = json.loads(response.read().decode("utf-8"))
                local_path.write_text("real local values", encoding="utf-8")
                with opener.open(request, timeout=5) as response:
                    existing_payload = json.loads(response.read().decode("utf-8"))
                final_local_text = local_path.read_text(encoding="utf-8")
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                reachops_web_ui.ACCEPTANCE_INPUT_TEMPLATE_PATH = old_template
                reachops_web_ui.ACCEPTANCE_INPUT_LOCAL_PATH = old_local

        self.assertEqual(created_payload["status"], "created")
        self.assertTrue(created_payload["no_browser_started"])
        self.assertTrue(created_payload["no_submit"])
        self.assertIn("report_path", created_payload)
        self.assertTrue(Path(created_payload["report_path"]).exists())
        self.assertEqual(existing_payload["status"], "already_exists")
        self.assertIn("readiness", existing_payload)
        self.assertIn("report_path", existing_payload)
        self.assertTrue(Path(existing_payload["report_path"]).exists())
        self.assertEqual(final_local_text, "real local values")

    def test_mac_retest_command_uses_product_auto_flow_and_acceptance_report(self):
        script = Path("复测ReachOps真实执行.command").read_text(encoding="utf-8")

        self.assertIn("APRILSKIN-Pore-Care-Long-lasting-Duo", script)
        self.assertIn("--source-type auto", script)
        self.assertIn("--profile-group \"$PROFILE_GROUP\"", script)
        self.assertIn("tools/reachops_client_acceptance_status.py", script)
        self.assertIn("LIVE", script)


class ReachOpsMacSelfCheckTest(unittest.TestCase):
    def test_required_web_ui_markers_detect_current_contract(self):
        html = html_page().decode("utf-8")
        missing = [marker for marker in REQUIRED_WEB_UI_MARKERS if marker not in html]

        self.assertIn(f'data-reachops-ui-version="{reachops_web_ui.WEB_UI_VERSION}"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn("ReachOps 本地客户端控制台", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("客户端外壳", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("ReachOpsApp.py", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("127.0.0.1 控制台", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("客户端 v20", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("执行期 0 token", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("未授权不提交", REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="accountRepairConfirmed"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="applyAccountRepair"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="accountGateState"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn("账号门禁已启用", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("隔离坏账号", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("/api/account-repair-apply", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("applyAccountRepairPlan", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("客户端门禁", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("client_delivery_summary", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("最终交付门禁", REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="finalStatusState"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="finalStatusActions"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn('id="finalStatusCommands"', REQUIRED_WEB_UI_MARKERS)
        self.assertIn("fetch('/api/final-status')", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("next_required_actions", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("verification_commands", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("final_delivery_ready", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("failed_checks", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("accountRepairActionItems", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("账号修复安全边界", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("no_browser_started", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("no_submit", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("no_ai_token_used", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("account_repair_summary", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("error_groups", REQUIRED_WEB_UI_MARKERS)
        self.assertIn("profile_ids_sample", REQUIRED_WEB_UI_MARKERS)
        self.assertEqual(missing, [])

    def test_check_port_rejects_old_web_ui_version(self):
        old_html = (
            '<html><body data-reachops-ui-version="reachops-unified-ui-2026-06-29-v17">'
            "ReachOps 统一控制台"
            ' <button id="volume">快速</button>'
            "客户端门禁 最终交付门禁"
            ' <span id="finalStatusState"></span>'
            ' <span id="finalStatusActions"></span>'
            ' <span id="finalStatusCommands"></span>'
            "fetch('/api/final-status') next_required_actions verification_commands final_delivery_ready failed_checks"
            "</body></html>"
        )
        status = evaluate_web_ui_body(old_html)

        self.assertFalse(status["ui_current"])
        self.assertFalse(status["ok"])
        self.assertIn(f'data-reachops-ui-version="{reachops_web_ui.WEB_UI_VERSION}"', status["missing_markers"])
        self.assertIn('id="accountRepairConfirmed"', status["missing_markers"])

    def test_version_payload_requires_local_client_identity(self):
        result = {}
        apply_version_payload(
            result,
            {
                "version": reachops_web_ui.WEB_UI_VERSION,
                "display_version": reachops_web_ui.CLIENT_DISPLAY_VERSION,
                "client_surface": "local_client_console",
                "display_name": "ReachOps Local Client Console",
                "loopback_host": "127.0.0.1",
            },
        )

        self.assertTrue(result["version_current"])
        self.assertTrue(result["client_surface_current"])
        self.assertTrue(result["display_version_current"])
        self.assertTrue(result["loopback_host_current"])

        stale = {}
        apply_version_payload(stale, {"version": reachops_web_ui.WEB_UI_VERSION})

        self.assertTrue(stale["version_current"])
        self.assertFalse(stale["client_surface_current"])
        self.assertFalse(stale["display_version_current"])
        self.assertFalse(stale["loopback_host_current"])

    def test_find_available_port_skips_listening_port(self):
        statuses = {
            8766: {"listening": True, "ok": False},
            8767: {"listening": False, "ok": True},
        }

        with patch("tools.reachops_mac_self_check.check_port", side_effect=lambda port: statuses[port]):
            self.assertEqual(find_available_port(8766, 8767), 8767)

    def test_start_web_launcher_binds_loopback_and_closes_parent_log_handle(self):
        class FakeProcess:
            pid = 43127

        captured = {}

        def fake_popen(command, **kwargs):
            captured["command"] = list(command)
            captured["env"] = dict(kwargs["env"])
            captured["stdout"] = kwargs["stdout"]
            captured["close_fds"] = kwargs["close_fds"]
            captured["start_new_session"] = kwargs["start_new_session"]
            return FakeProcess()

        with patch("tools.reachops_mac_self_check.subprocess.Popen", side_effect=fake_popen):
            result = start_web(8766)

        self.assertEqual(result["url"], "http://127.0.0.1:8766/")
        self.assertTrue(captured["command"][1].endswith("tools/reachops_web_ui.py"))
        self.assertNotIn("ReachOpsApp.py", captured["command"][1])
        self.assertIn("--web", captured["command"])
        self.assertIn("--no-browser", captured["command"])
        self.assertIn("--host", captured["command"])
        self.assertEqual(captured["command"][captured["command"].index("--host") + 1], "127.0.0.1")
        self.assertEqual(captured["env"]["REACHOPS_WEB_HOST"], "127.0.0.1")
        self.assertEqual(captured["env"]["REACHOPS_WEB_PORT"], "8766")
        self.assertEqual(captured["env"]["REACHOPS_WEB_NO_BROWSER"], "1")
        self.assertTrue(captured["close_fds"])
        self.assertTrue(captured["start_new_session"])
        self.assertTrue(captured["stdout"].closed)

    def test_start_web_launcher_reports_popen_failure_without_crashing(self):
        with patch("tools.reachops_mac_self_check.subprocess.Popen", side_effect=PermissionError("blocked")):
            result = start_web(8768)

        self.assertFalse(result["ok"])
        self.assertEqual(result["pid"], 0)
        self.assertEqual(result["port"], 8768)
        self.assertIn("PermissionError: blocked", result["error"])
        self.assertTrue(Path(result["log"]).exists())

    def test_tk_failure_is_classified_as_environment_not_entrypoint_regression(self):
        payload = classify_tk_failure("TclError: Can't find a usable tk.tcl; cannot use non-numeric floating-point value \"NaN\"")

        self.assertEqual(payload["failure_code"], "PYTHON_TK_UNUSABLE")
        self.assertIn("Python/Tk", payload["message"])
        self.assertTrue(any("启动ReachOps原生MacUI.command" in item for item in payload["operator_actions"]))
        self.assertTrue(any("不是 ReachOpsApp.py 入口分流问题" in item for item in payload["operator_actions"]))

    def test_self_check_human_output_includes_customer_blocker_summary(self):
        text = format_human(
            {
                "python": {"ok": True, "version": "3.9.6", "executable": "/usr/bin/python3"},
                "tk": {
                    "ok": False,
                    "error": "TclError: Can't find a usable tk.tcl",
                    **classify_tk_failure("TclError: Can't find a usable tk.tcl"),
                },
                "port": {"port": 8766, "listening": False, "http_ok": False, "title": ""},
                "acceptance": {
                    "readiness": "blocked_by_accounts",
                    "batch": {"id": "gb_1", "status": "failed", "group": "United States"},
                    "profile_preflight": {
                        "checked": 9,
                        "available": 0,
                        "errors": {"PROFILE_START_FAILED": 9},
                    },
                    "profile_error_summary": {
                        "PROFILE_START_FAILED": {"count": 9, "profile_ids": ["45", "46"]}
                    },
                    "remediation_report": {
                        "csv_path": "/tmp/fix.csv",
                        "json_path": "/tmp/fix.json",
                        "markdown_path": "/tmp/fix.md",
                        "guide_path": "/tmp/guide.md",
                        "index_path": "/tmp/index.html",
                        "manifest_path": "/tmp/manifest.json",
                        "latest_guide_path": "/tmp/latest_guide.md",
                        "latest_index_path": "/tmp/latest_index.html",
                        "latest_manifest_path": "/tmp/latest_manifest.json",
                    },
                    "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
                    "next_actions": ["先在 ixBrowser 手动打开 United States 中至少 1 个账号。"],
                },
                "client_delivery": {
                    "status": "blocked_by_accounts",
                    "contract_ok": True,
                    "acceptance_ready": False,
                    "final_delivery_ready": False,
                    "failed_checks": ["acceptance:ready"],
                },
                "web_start_error": "PermissionError: [Errno 1] Operation not permitted",
                "started_web": {"ok": False, "error": "PermissionError: [Errno 1] Operation not permitted", "log": "/tmp/web.log"},
            }
        )

        self.assertIn("ReachOps Mac 自检", text)
        self.assertIn("Tk 原生 UI: FAIL", text)
        self.assertIn("当前 Python/Tk 运行环境不可用", text)
        self.assertNotIn("Traceback", text)
        self.assertIn("Tk 失败类型: PYTHON_TK_UNUSABLE", text)
        self.assertIn("Tk 恢复: 优先双击“启动ReachOps原生MacUI.command”", text)
        self.assertIn("验收状态: blocked_by_accounts", text)
        self.assertIn("PROFILE_START_FAILED", text)
        self.assertIn("profiles=45,46", text)
        self.assertIn("/tmp/fix.csv", text)
        self.assertIn("/tmp/fix.md", text)
        self.assertIn("/tmp/guide.md", text)
        self.assertIn("/tmp/index.html", text)
        self.assertIn("/tmp/manifest.json", text)
        self.assertIn("/tmp/latest_guide.md", text)
        self.assertIn("/tmp/latest_index.html", text)
        self.assertIn("/tmp/latest_manifest.json", text)
        self.assertIn("本地客户端控制台启动异常", text)
        self.assertIn("本地客户端控制台启动失败", text)
        self.assertIn("客户端门禁: status=blocked_by_accounts", text)
        self.assertIn("final_delivery_ready=False", text)
        self.assertIn("客户端门禁失败: acceptance:ready", text)

    def test_self_check_human_output_identifies_stale_primary_web_port(self):
        text = format_human(
            {
                "python": {"ok": True, "version": "3.9.6", "executable": "/usr/bin/python3"},
                "tk": {"ok": True, "version": "8.6"},
                "port": {
                    "port": 8770,
                    "listening": True,
                    "http_ok": True,
                    "title": "ReachOps 统一控制台",
                    "ui_current": True,
                    "version": reachops_web_ui.WEB_UI_VERSION,
                    "missing_markers": [],
                },
                "stale_web_port": {
                    "port": 8769,
                    "listening": True,
                    "http_ok": True,
                    "title": "ReachOps 统一控制台",
                    "ui_current": False,
                    "version": "reachops-unified-ui-2026-06-29-v17",
                },
                "started_web": {"ok": True, "url": "http://127.0.0.1:8770/", "pid": 123, "log": "/tmp/web.log"},
                "web_url": "http://127.0.0.1:8770/",
                "acceptance": {
                    "readiness": "blocked_by_accounts",
                    "batch": {"id": "gb_1", "status": "failed", "group": "United States"},
                    "profile_preflight": {"checked": 3, "available": 0, "errors": {"IXBROWSER_KERNEL_MISMATCH": 3}},
                    "profile_error_summary": {},
                    "remediation_report": {},
                    "blockers": [],
                    "next_actions": [],
                },
                "client_delivery": {
                    "status": "blocked_by_accounts",
                    "contract_ok": True,
                    "acceptance_ready": False,
                    "final_delivery_ready": False,
                    "failed_checks": ["acceptance:ready"],
                },
            }
        )

        self.assertIn("旧本地客户端控制台端口: 8769", text)
        self.assertIn("已改用新的实际地址", text)
        self.assertIn("本地客户端控制台地址: http://127.0.0.1:8770/", text)

    def test_self_check_client_delivery_reports_structured_gate_status(self):
        with TemporaryDirectory() as tmpdir:
            payload = check_client_delivery(Path(tmpdir))

        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["final_delivery_ready"])
        self.assertIn("runtime:evidence", payload["failed_checks"])
        self.assertIn("acceptance:ready", payload["failed_checks"])

    def test_open_acceptance_package_command_refreshes_and_opens_latest(self):
        script = Path("打开ReachOps验收包.command").read_text(encoding="utf-8")

        self.assertIn("tools/reachops_client_acceptance_status.py", script)
        self.assertIn("latest_acceptance_index.html", script)
        self.assertIn("latest_client_acceptance_guide.md", script)
        self.assertIn("latest_acceptance_manifest.json", script)
        self.assertIn("open \"$REPORT_DIR\"", script)

    def test_account_repair_command_previews_requires_apply_and_refreshes_gate(self):
        script = Path("执行ReachOps账号修复.command").read_text(encoding="utf-8")

        self.assertIn("tools/reachops_apply_account_repair_plan.py --json", script)
        self.assertIn("tools/reachops_apply_account_repair_plan.py --apply --json", script)
        self.assertIn("PREVIEW_JSON", script)
        self.assertIn("APPLY_JSON", script)
        self.assertIn("no_applicable_profiles", script)
        self.assertIn("最新账号修复计划没有默认可自动隔离的账号", script)
        self.assertIn("已记录本次账号修复结果: no_applicable_profiles", script)
        self.assertIn("exit 2", script)
        self.assertIn("CONFIRM", script)
        self.assertIn("APPLY", script)
        self.assertIn("tools/reachops_client_delivery_check.py", script)
        self.assertIn("NO_PROXY", script)

    def test_real_retest_command_detects_pending_account_repair_recheck(self):
        script = Path("复测ReachOps真实执行.command").read_text(encoding="utf-8")

        self.assertIn("tools/reachops_client_delivery_check.py --json > \"$PRECHECK_JSON\"", script)
        self.assertIn("account_repair_apply", script)
        self.assertIn("pending_recheck", script)
        self.assertIn("STALE_REPAIR", script)
        self.assertIn("旧账号修复结果已失效", script)
        self.assertIn("执行ReachOps账号修复.command", script)
        self.assertIn("exit 2", script)
        self.assertIn("REACHOPS_FORCE_ACCOUNT_RECHECK", script)
        self.assertIn("重新预检模式", script)
        self.assertIn("tools/run_reachops_headless_macos.py", script)

    def test_mac_operator_docs_define_account_repair_acceptance_loop(self):
        mac_acceptance = Path("ReachOps/docs/REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md").read_text(encoding="utf-8")
        pm_baseline = Path("ReachOps/docs/REACHOPS_PM_DELIVERY_BASELINE.md").read_text(encoding="utf-8")
        operator_matrix = Path("ReachOps/docs/REACHOPS_OPERATOR_ACCEPTANCE_MATRIX.md").read_text(encoding="utf-8")
        combined = "\n".join([mac_acceptance, pm_baseline, operator_matrix])

        for token in [
            "隔离坏账号",
            "执行ReachOps账号修复.command",
            "tools/reachops_apply_account_repair_plan.py --json",
            "封禁账号",
            "blocked_by_accounts",
            "tools/reachops_client_delivery_check.py --json",
        ]:
            self.assertIn(token, combined)
        self.assertIn("profile_available>=1", pm_baseline)
        self.assertIn("status=passed", pm_baseline)
        self.assertIn("acceptance_ready=true", pm_baseline)
        self.assertIn("只生成账号修复计划不算验收通过", operator_matrix)

    def test_delivery_check_contract_contains_entrypoints_and_report_checks(self):
        payload = build_delivery_check()
        names = {item["name"] for item in payload["checks"]}

        self.assertIn("entrypoint:启动ReachOps本地客户端.command", names)
        self.assertIn("entrypoint:启动ReachOps统一WebUI.command", names)
        self.assertIn("entrypoint:执行ReachOps账号修复.command", names)
        self.assertIn("entrypoint:复测ReachOps真实执行.command", names)
        self.assertIn("entrypoint:打开ReachOps验收包.command", names)
        self.assertIn("report:latest_index_path", names)
        self.assertIn("web_ui_contract", names)
        self.assertIn("web_ui_version_api_local_client_identity", names)
        self.assertIn("autonomous_product_core_contract", names)
        self.assertIn("manifest:entrypoints", names)
        self.assertIn("manifest:web_operator_final_status_api", names)
        self.assertIn("manifest:account_repair_summary", names)
        self.assertIn("acceptance:ready", names)
        self.assertIn(payload["readiness"], {"pass", "partial", "blocked_by_accounts", "blocked_by_environment", "not_started", "pending_new_run"})
        manifest_check = next(item for item in payload["checks"] if item["name"] == "manifest:entrypoints")
        self.assertTrue(manifest_check["ok"])
        repair_manifest_check = next(item for item in payload["checks"] if item["name"] == "manifest:account_repair_summary")
        self.assertTrue(repair_manifest_check["ok"])
        version_check = next(item for item in payload["checks"] if item["name"] == "web_ui_version_api_local_client_identity")
        self.assertTrue(version_check["ok"])
        self.assertEqual(version_check["version_payload"]["version"], reachops_web_ui.WEB_UI_VERSION)
        self.assertEqual(version_check["version_payload"]["display_version"], reachops_web_ui.CLIENT_DISPLAY_VERSION)
        self.assertEqual(version_check["version_payload"]["client_surface"], "local_client_console")
        self.assertEqual(version_check["version_payload"]["loopback_host"], "127.0.0.1")
        core_check = next(item for item in payload["checks"] if item["name"] == "autonomous_product_core_contract")
        self.assertTrue(core_check["ok"])
        self.assertTrue(core_check["checks"]["execution_plan_valid"])
        self.assertTrue(core_check["checks"]["run_session_state_machine"])
        self.assertTrue(core_check["checks"]["page_state_required_classes"])
        self.assertTrue(core_check["checks"]["repair_login_blocks_and_captures"])
        self.assertTrue(core_check["checks"]["risk_gate_blocks_unauthorized_live_submit"])
        self.assertTrue(core_check["checks"]["ai_usage_policy_zero_token"])

    def test_delivery_check_embeds_account_repair_summary(self):
        batch = {"id": "gb_accounts", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "blocked_by_accounts",
            "checks": {"profile_available_count": 0},
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "profile_preflight_details": [
                {
                    "profile_id": "21644",
                    "status": "不可用",
                    "error": "IXBROWSER_KERNEL_MISMATCH",
                    "message": "当前版本仅支持 138 内核打开",
                },
                {
                    "profile_id": "23946",
                    "status": "不可用",
                    "error": "LOGIN_REQUIRED",
                    "message": "TikTok 未登录",
                },
            ],
        }
        with TemporaryDirectory() as tmpdir:
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 2, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=["WARN profile preflight failed"]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(Path(tmpdir))
                                repair_plan_exists = Path(payload["remediation_report"]["latest_account_plan_json_path"]).is_file()

        summary = payload["account_repair_summary"]
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["profile_group"], "United States")
        errors = {row["error"]: row for row in summary["error_groups"]}
        self.assertEqual(errors["IXBROWSER_KERNEL_MISMATCH"]["count"], 1)
        self.assertEqual(errors["IXBROWSER_KERNEL_MISMATCH"]["profile_ids_sample"], ["21644"])
        self.assertEqual(errors["LOGIN_REQUIRED"]["profile_ids_sample"], ["23946"])
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertTrue(checks["manifest:account_repair_summary"]["ok"])
        self.assertEqual(checks["manifest:account_repair_summary"]["total_unique_profiles_by_error"], 2)
        self.assertEqual(checks["manifest:account_repair_summary"]["total_error_events_by_error"], 2)
        self.assertEqual(checks["manifest:account_repair_summary"]["summary_only_error_count"], 0)
        self.assertEqual(checks["manifest:account_repair_summary"]["error_group_count"], 2)
        resolution = payload["account_blocker_resolution"]
        self.assertEqual(resolution["schema_version"], "reachops.account_blocker_resolution.v1")
        self.assertEqual(resolution["status"], "repair_plan_ready")
        self.assertEqual(resolution["priority_action"], "apply_latest_account_repair_plan")
        self.assertTrue(resolution["requires_latest_repair_apply"])
        self.assertFalse(resolution["ready_for_retest"])
        self.assertTrue(resolution["does_not_claim_real_account_pool_ready"])
        self.assertEqual(resolution["repair_plan_profile_count"], 2)
        self.assertTrue(repair_plan_exists)

    def test_delivery_check_missing_account_repair_plan_is_not_file_error(self):
        batch = {"id": "gb_partial", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "partial",
            "checks": {"profile_available_count": 1},
            "blockers": ["目标链接跳转。"],
            "next_actions": ["更换目标。"],
            "profile_preflight_details": [],
        }
        with TemporaryDirectory() as tmpdir:
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 0, "available": 1}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=["DONE collection"]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(Path(tmpdir))

        summary = payload["account_repair_summary"]
        self.assertEqual(summary["status"], "not_available")
        self.assertNotIn("error", summary)

    def test_delivery_check_marks_applied_account_repair_as_pending_recheck(self):
        batch = {"id": "gb_accounts", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "blocked_by_accounts",
            "checks": {"profile_available_count": 0},
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "profile_preflight_details": [
                {
                    "profile_id": "24909",
                    "status": "不可用",
                    "error": "IXBROWSER_KERNEL_MISMATCH",
                    "message": "当前版本仅支持 138 内核打开",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            log_lines = [
                "CONFIG account_repair_apply status=applied group=United States selected=1 moved=1 failed=0"
            ]
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 1, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=log_lines):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(Path(tmpdir))

        self.assertEqual(payload["status"], "blocked_by_accounts")
        self.assertFalse(payload["acceptance_ready"])
        self.assertTrue(payload["account_repair_apply"]["pending_recheck"])
        self.assertEqual(payload["account_repair_apply"]["effective_status"], "pending_recheck")
        self.assertEqual(payload["account_repair_apply"]["source"], "growth_ops_runtime.log")
        self.assertIn("等待重新预检", payload["blockers"][0])
        self.assertIn("点击开始获客复测 United States 分组", payload["next_actions"][0])
        resolution = payload["account_blocker_resolution"]
        self.assertEqual(resolution["status"], "pending_recheck")
        self.assertEqual(resolution["priority_action"], "rerun_client_preflight")
        self.assertTrue(resolution["ready_for_retest"])
        self.assertFalse(resolution["requires_latest_repair_apply"])
        self.assertTrue(resolution["does_not_claim_real_account_pool_ready"])

    def test_account_blocker_resolution_prioritizes_manual_account_work_when_no_apply_candidates(self):
        resolution = build_account_blocker_resolution(
            {
                "readiness": "blocked_by_accounts",
                "checks": {"profile_available_count": 0},
            },
            batch={"id": "gb_manual", "profile_group": "United States"},
            account_repair_summary={
                "status": "ok",
                "path": "/tmp/latest_account_repair_plan.json",
                "profile_group": "United States",
                "total_unique_profiles_by_error": 0,
            },
            account_repair_apply={"status": "no_applicable_profiles"},
        )

        self.assertEqual(resolution["status"], "manual_account_work_required")
        self.assertEqual(resolution["priority_action"], "manually_repair_or_replace_accounts")
        self.assertTrue(resolution["requires_manual_account_work"])
        self.assertFalse(resolution["ready_for_retest"])
        self.assertIn("account_repair_no_applicable_profiles", resolution["blocker_codes"])

    def test_account_repair_apply_status_normalizes_counts_from_results(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            result_path = base_dir / "reports" / "acceptance_remediation" / "latest_account_repair_apply.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "profile_group": "United States",
                        "selected_count": 2,
                        "moved_count": 2,
                        "failed_count": 0,
                        "results": [
                            {
                                "profile_id": "24909",
                                "attempted": True,
                                "ok": True,
                                "group_name": "封禁账号",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = latest_account_repair_apply_status(
                base_dir,
                [],
                profile_group="United States",
                batch_id="gb_accounts",
            )

        self.assertTrue(payload["count_normalized_from_results"])
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["moved_count"], 1)
        self.assertEqual(payload["failed_count"], 0)
        self.assertTrue(payload["pending_recheck"])

    def test_account_repair_apply_status_ignores_stale_apply_before_new_plan(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            apply_path = report_dir / "latest_account_repair_apply.json"
            plan_path = report_dir / "latest_account_repair_plan.json"
            apply_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "profile_group": "United States",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "24909", "attempted": True, "ok": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_path.write_text(
                json.dumps(
                    {
                        "batch_id": "gb_new_failed",
                        "profile_group": "United States",
                        "groups": [{"error": "IXBROWSER_KERNEL_MISMATCH", "profile_ids": ["24919"]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_time = time.time() - 60
            new_time = time.time()
            os.utime(apply_path, (old_time, old_time))
            os.utime(plan_path, (new_time, new_time))

            payload = latest_account_repair_apply_status(
                base_dir,
                [],
                profile_group="United States",
                batch_id="gb_new_failed",
            )

        self.assertTrue(payload["stale"])
        self.assertEqual(payload["stale_reason"], "newer_account_repair_plan_for_current_batch")
        self.assertFalse(payload["same_batch"])
        self.assertFalse(payload["pending_recheck"])
        self.assertEqual(payload["effective_status"], "stale")
        self.assertIn("旧账号修复结果已失效", payload["effective_message"])

    def test_account_repair_apply_status_rejects_previous_batch_apply(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            apply_path = report_dir / "latest_account_repair_apply.json"
            apply_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "batch_id": "gb_previous_failed",
                        "profile_group": "United States",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "24909", "attempted": True, "ok": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = latest_account_repair_apply_status(
                base_dir,
                [],
                profile_group="United States",
                batch_id="gb_current_failed",
            )

        self.assertFalse(payload["same_batch"])
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["stale_reason"], "account_repair_apply_batch_mismatch")
        self.assertFalse(payload["pending_recheck"])
        self.assertEqual(payload["effective_status"], "stale")
        self.assertIn("旧账号修复结果已失效", payload["effective_message"])

    def test_account_repair_apply_status_rejects_other_group_apply(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            apply_path = report_dir / "latest_account_repair_apply.json"
            apply_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "batch_id": "gb_current_failed",
                        "profile_group": "Canada",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "24909", "attempted": True, "ok": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = latest_account_repair_apply_status(
                base_dir,
                [],
                profile_group="United States",
                batch_id="gb_current_failed",
            )

        self.assertFalse(payload["same_group"])
        self.assertTrue(payload["same_batch"])
        self.assertFalse(payload.get("stale", False))
        self.assertFalse(payload["pending_recheck"])
        self.assertEqual(payload["effective_status"], "group_mismatch")
        self.assertIn("属于其他分组", payload["effective_message"])

    def test_delivery_check_blocks_stale_account_repair_apply_before_retest(self):
        batch = {"id": "gb_new_failed", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "blocked_by_accounts",
            "checks": {"profile_available_count": 0},
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "profile_preflight_details": [
                {
                    "profile_id": "24919",
                    "status": "不可用",
                    "error": "IXBROWSER_KERNEL_MISMATCH",
                    "message": "当前版本仅支持 138 内核打开",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            apply_path = report_dir / "latest_account_repair_apply.json"
            apply_path.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "profile_group": "United States",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "24909", "attempted": True, "ok": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_time = time.time() - 60
            os.utime(apply_path, (old_time, old_time))
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 1, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=[]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(base_dir)

        self.assertTrue(payload["account_repair_apply"]["stale"])
        self.assertFalse(payload["account_repair_apply"]["pending_recheck"])
        self.assertEqual(payload["account_repair_apply"]["status"], "applied")
        self.assertEqual(payload["account_repair_apply"]["effective_status"], "stale")
        self.assertIn("旧账号修复结果已失效", payload["blockers"][0])
        self.assertIn("先执行最新账号修复计划", payload["next_actions"][0])
        self.assertIn("latest_apply_stale", payload["real_pilot_evidence"]["account_pool_remediation"])
        self.assertTrue(payload["real_pilot_evidence"]["account_pool_remediation"]["latest_apply_stale"])
        self.assertEqual(
            payload["real_pilot_evidence"]["account_pool_remediation"]["latest_apply_effective_status"],
            "stale",
        )

    def test_delivery_check_blocks_other_group_account_repair_apply(self):
        batch = {"id": "gb_current_failed", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "blocked_by_accounts",
            "checks": {"profile_available_count": 0},
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "profile_preflight_details": [],
        }
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            (report_dir / "latest_account_repair_apply.json").write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "batch_id": "gb_current_failed",
                        "profile_group": "Canada",
                        "selected_count": 1,
                        "moved_count": 1,
                        "failed_count": 0,
                        "results": [{"profile_id": "24909", "attempted": True, "ok": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 1, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=[]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(base_dir)

        self.assertEqual(payload["account_repair_apply"]["effective_status"], "group_mismatch")
        self.assertIn("不能用于当前 United States 分组验收", payload["blockers"][0])
        self.assertIn("执行 United States 分组的最新账号修复计划", payload["next_actions"][0])
        self.assertEqual(
            payload["real_pilot_evidence"]["account_pool_remediation"]["latest_apply_effective_status"],
            "group_mismatch",
        )

    def test_delivery_check_explains_no_applicable_account_repair_apply(self):
        batch = {"id": "gb_no_auto", "status": "failed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "blocked_by_accounts",
            "checks": {"profile_available_count": 0},
            "blockers": ["账号预检没有可用账号，无法进入真实采集/触达。"],
            "next_actions": ["先修复 United States 分组账号。"],
            "profile_preflight_details": [
                {
                    "profile_id": "slow-1",
                    "status": "不可用",
                    "error": "PROFILE_PREFLIGHT_TIMEOUT",
                    "message": "profile preflight exceeded 21.0s",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report_dir = base_dir / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            (report_dir / "latest_account_repair_apply.json").write_text(
                json.dumps(
                    {
                        "status": "no_applicable_profiles",
                        "batch_id": "gb_no_auto",
                        "profile_group": "United States",
                        "selected_count": 0,
                        "moved_count": 0,
                        "failed_count": 0,
                        "no_applicable_profiles": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 1, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=[]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                payload = build_delivery_check(base_dir)

        self.assertEqual(payload["account_repair_apply"]["status"], "no_applicable_profiles")
        self.assertFalse(payload["account_repair_apply"]["pending_recheck"])
        self.assertFalse(payload["account_repair_apply"].get("stale", False))
        self.assertIn("没有默认可自动隔离的账号", payload["blockers"][0])
        self.assertIn("手动打开受影响账号", payload["next_actions"][0])

    def test_delivery_check_human_output_formats_account_repair_summary(self):
        payload = {
            "account_repair_summary": {
                "status": "ok",
                "profile_group": "United States",
                "total_unique_profiles_by_error": 52,
                "total_error_events_by_error": 58,
                "summary_only_error_count": 6,
                "error_groups": [
                    {
                        "error": "IXBROWSER_KERNEL_MISMATCH",
                        "count": 39,
                        "profile_ids_sample": ["21644", "21647"],
                        "profile_ids_total": 39,
                        "summary_only_count": 0,
                        "recommended_action": "修改内核版本或移出执行分组。",
                    },
                    {
                        "error": "LOGIN_REQUIRED",
                        "count": 13,
                        "profile_ids_sample": ["23946"],
                        "profile_ids_total": 7,
                        "summary_only_count": 6,
                        "recommended_action": "完成 TikTok 登录。",
                    },
                ],
                "acceptance_after_repair": [
                    "reachops_client_delivery_check.py --json 返回 status=passed。",
                    "profile_available>=1。",
                ],
            },
            "account_repair_apply": {
                "safety_contract": {
                    "schema_version": "reachops.account_repair_safety_contract.v1",
                    "manual_apply_required": True,
                    "operator_confirmed_apply": True,
                    "hard_blocker_only": True,
                    "no_browser_started": True,
                    "no_submit": True,
                    "no_ai_token_used": True,
                }
            },
        }

        text = "\n".join(account_repair_summary_lines(payload))

        self.assertIn("group=United States", text)
        self.assertIn("profiles=52 events=58 summary_only=6", text)
        self.assertIn(
            "IXBROWSER_KERNEL_MISMATCH count=39 profile_ids=39 summary_only=0 sample=21644,21647 action=修改内核版本或移出执行分组。",
            text,
        )
        self.assertIn("LOGIN_REQUIRED count=13 profile_ids=7 summary_only=6 sample=23946 action=完成 TikTok 登录。", text)
        self.assertIn("after_repair_acceptance=reachops_client_delivery_check.py --json 返回 status=passed。 | profile_available>=1。", text)
        self.assertIn(
            "account_repair_safety=manual_apply_required=true operator_confirmed_apply=true hard_blocker_only=true no_browser_started=true no_submit=true no_ai_token_used=true",
            text,
        )
        self.assertIn("after_repair_commands=python tools/reachops_client_delivery_check.py --json | python tools/reachops_mac_self_check.py --json", text)

    def test_apply_account_repair_plan_dry_run_and_apply_hard_blockers(self):
        class Manager:
            def __init__(self):
                self.moves = []

            def move_profile_to_quarantine(self, profile_id, reason=""):
                self.moves.append((str(profile_id), str(reason)))
                return type(
                    "Move",
                    (),
                    {
                        "ok": True,
                        "group_id": "999",
                        "group_name": "封禁账号",
                        "error_code": "",
                        "error_message": "",
                    },
                )()

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latest_account_repair_plan.json"
            path.write_text(
                json.dumps(
                    {
                        "batch_id": "gb_1",
                        "profile_group": "United States",
                        "groups": [
                            {"error": "IXBROWSER_KERNEL_MISMATCH", "profile_ids": ["24909", "24910"]},
                            {"error": "PROFILE_PREFLIGHT_TIMEOUT", "profile_ids": ["slow-1"]},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = Manager()

            dry = apply_account_repair_plan(path, apply=False, manager_factory=lambda: manager)
            applied = apply_account_repair_plan(path, apply=True, manager_factory=lambda: manager)

        self.assertEqual(dry["status"], "dry_run")
        self.assertEqual(dry["selected_count"], 2)
        self.assertTrue(all(row["attempted"] is False for row in dry["results"]))
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["moved_count"], 2)
        self.assertEqual(applied["safety_contract"]["schema_version"], "reachops.account_repair_safety_contract.v1")
        self.assertTrue(applied["safety_contract"]["manual_apply_required"])
        self.assertTrue(applied["safety_contract"]["operator_confirmed_apply"])
        self.assertTrue(applied["safety_contract"]["hard_blocker_only"])
        self.assertTrue(applied["safety_contract"]["no_browser_started"])
        self.assertTrue(applied["safety_contract"]["no_submit"])
        self.assertTrue(applied["safety_contract"]["no_ai_token_used"])
        self.assertEqual(manager.moves, [("24909", "IXBROWSER_KERNEL_MISMATCH"), ("24910", "IXBROWSER_KERNEL_MISMATCH")])

    def test_apply_account_repair_plan_rejects_apply_when_no_auto_profiles_selected(self):
        class Manager:
            def move_profile_to_quarantine(self, profile_id, reason=""):
                raise AssertionError("no profile should be moved")

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latest_account_repair_plan.json"
            path.write_text(
                json.dumps(
                    {
                        "batch_id": "gb_1",
                        "profile_group": "United States",
                        "groups": [
                            {"error": "PROFILE_PREFLIGHT_TIMEOUT", "profile_ids": ["slow-1"]},
                            {"error": "PAGE_OPEN_FAILED", "profile_ids": []},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            dry = apply_account_repair_plan(path, apply=False, manager_factory=Manager)
            applied = apply_account_repair_plan(path, apply=True, manager_factory=Manager)

        self.assertEqual(dry["status"], "dry_run")
        self.assertTrue(dry["no_applicable_profiles"])
        self.assertEqual(dry["selected_count"], 0)
        self.assertEqual(applied["status"], "no_applicable_profiles")
        self.assertFalse(applied["ok"])
        self.assertEqual(applied["selected_count"], 0)
        self.assertEqual(applied["moved_count"], 0)
        self.assertIn("PROFILE_PREFLIGHT_TIMEOUT", applied["non_auto_error_codes"])
        self.assertTrue(applied["next_actions"])
        self.assertTrue(applied["no_browser_started"])
        self.assertTrue(applied["no_submit"])

    def test_web_account_repair_apply_uses_latest_plan_and_blocks_running_task(self):
        old_process = reachops_web_ui.RUN_PROCESS

        class RunningProcess:
            def poll(self):
                return None

        try:
            reachops_web_ui.RUN_PROCESS = RunningProcess()
            running = reachops_web_ui.apply_latest_account_repair_plan_from_web("United States")
            self.assertEqual(running["status"], "rejected")
            self.assertEqual(running["error"], "run_in_progress")

            reachops_web_ui.RUN_PROCESS = None
            captured = {}

            def fake_apply(path, apply=False):
                captured["path"] = str(path)
                captured["apply"] = apply
                return {
                    "status": "applied",
                    "ok": True,
                    "profile_group": "United States",
                    "selected_count": 2,
                    "moved_count": 2,
                    "failed_count": 0,
                    "results": [{"profile_id": "24909", "ok": True, "group_name": "封禁账号"}],
                    "safety_contract": {
                        "schema_version": "reachops.account_repair_safety_contract.v1",
                        "manual_apply_required": True,
                        "operator_confirmed_apply": True,
                        "hard_blocker_only": True,
                        "moves_only_to_quarantine_group": True,
                        "no_browser_started": True,
                        "no_submit": True,
                        "no_ai_token_used": True,
                    },
                }

            with patch(
                "tools.reachops_apply_account_repair_plan.load_plan",
                return_value={"profile_group": "United States", "groups": []},
            ), patch("tools.reachops_apply_account_repair_plan.apply_account_repair_plan", side_effect=fake_apply):
                applied = reachops_web_ui.apply_latest_account_repair_plan_from_web("United States")

            with patch(
                "tools.reachops_apply_account_repair_plan.load_plan",
                return_value={"profile_group": "United States", "groups": []},
            ):
                mismatch = reachops_web_ui.apply_latest_account_repair_plan_from_web("Canada")
        finally:
            reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(applied["status"], "applied")
        self.assertTrue(captured["apply"])
        self.assertTrue(captured["path"].endswith("latest_account_repair_plan.json"))
        self.assertIn("刷新分组", " ".join(applied["next_actions"]))
        self.assertEqual(mismatch["status"], "rejected")
        self.assertEqual(mismatch["error"], "account_repair_group_mismatch")
        self.assertEqual(mismatch["profile_group"], "United States")

    def test_web_account_repair_apply_explains_no_applicable_profiles(self):
        old_process = reachops_web_ui.RUN_PROCESS
        captured_write = {}

        def fake_apply(path, apply=False):
            return {
                "status": "no_applicable_profiles",
                "ok": False,
                "profile_group": "United States",
                "selected_count": 0,
                "moved_count": 0,
                "failed_count": 0,
                "non_auto_error_codes": ["PROFILE_PREFLIGHT_TIMEOUT"],
                "next_actions": ["最新账号修复计划没有默认可自动隔离的账号，未移动任何 ixBrowser 配置。"],
                "no_browser_started": True,
                "no_submit": True,
            }

        def fake_write(result):
            captured_write["status"] = result.get("status")
            captured_write["selected_count"] = result.get("selected_count")
            return Path("/tmp/latest_account_repair_apply.json")

        try:
            reachops_web_ui.RUN_PROCESS = None
            with patch(
                "tools.reachops_apply_account_repair_plan.load_plan",
                return_value={"profile_group": "United States", "groups": []},
            ), patch(
                "tools.reachops_apply_account_repair_plan.apply_account_repair_plan",
                side_effect=fake_apply,
            ), patch("tools.reachops_apply_account_repair_plan.write_account_repair_apply_result", side_effect=fake_write):
                result = reachops_web_ui.apply_latest_account_repair_plan_from_web("United States")
        finally:
            reachops_web_ui.RUN_PROCESS = old_process

        self.assertEqual(result["status"], "no_applicable_profiles")
        self.assertFalse(result["ok"])
        self.assertEqual(result["apply_result_path"], "/tmp/latest_account_repair_apply.json")
        self.assertEqual(captured_write, {"status": "no_applicable_profiles", "selected_count": 0})
        self.assertTrue(result["no_browser_started"])
        self.assertTrue(result["no_submit"])
        next_actions = " ".join(result["next_actions"])
        self.assertIn("手动打开受影响账号", next_actions)
        self.assertNotIn("Local API", next_actions)
        self.assertNotIn("ixBrowser 客户端已启动", next_actions)

    def test_delivery_check_exposes_no_action_reason_when_actions_are_zero(self):
        batch = {"id": "gb_no_action", "status": "completed", "profile_group": "United States", "config_json": "{}"}
        acceptance = {
            "readiness": "pass",
            "checks": {"profile_available_count": 2},
            "blockers": [],
            "next_actions": ["重新点击开始获客，观察是否出现 DONE collection 和 START action_*。"],
            "profile_preflight_details": [],
        }
        operations = {"counts": {"candidates": 2, "qualified_leads": 0, "actions": 0}}
        with TemporaryDirectory() as tmpdir:
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 2, "available": 2}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=["DONE   collection batch=gb_no_action"]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value=operations):
                                payload = build_delivery_check(Path(tmpdir))

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["no_action_reason"]["code"], "low_intent_candidates")
        self.assertEqual(payload["no_action_reason"]["candidate_count"], 2)
        self.assertEqual(payload["operation_counts"]["actions"], 0)
        self.assertTrue(any("评分未达到触达线" in item for item in payload["next_actions"]))

    def test_real_pilot_evidence_boundary_blocks_zero_account_claims(self):
        boundary = build_real_pilot_evidence_boundary(
            {
                "readiness": "blocked_by_accounts",
                "checks": {"profile_available_count": 0},
            },
            {"counts": {"candidates": 0, "actions": 0, "touched": 0}},
            status="blocked_by_accounts",
            contract_ok=True,
            acceptance_ready=False,
        )

        self.assertEqual(boundary["schema_version"], "reachops.real_pilot_evidence_boundary.v1")
        self.assertFalse(boundary["real_pilot_ready"])
        self.assertEqual(boundary["status"], "external_validation_pending")
        self.assertFalse(boundary["fixture_or_dry_run_claimed"])
        self.assertTrue(boundary["no_submit_preserved"])
        self.assertTrue(boundary["requires_real_account_pool"])
        self.assertTrue(boundary["requires_real_collection_evidence"])
        self.assertIn("profile_available_zero", boundary["external_acceptance_pending"])
        self.assertIn("candidate_count_zero", boundary["external_acceptance_pending"])
        self.assertIn("client_delivery_status_blocked_by_accounts", boundary["external_acceptance_pending"])

    def test_real_pilot_evidence_boundary_includes_account_repair_remediation(self):
        boundary = build_real_pilot_evidence_boundary(
            {
                "readiness": "blocked_by_accounts",
                "checks": {"profile_available_count": 0},
            },
            {"counts": {"candidates": 0, "actions": 0, "touched": 0}},
            status="blocked_by_accounts",
            contract_ok=True,
            acceptance_ready=False,
            account_repair_summary={
                "status": "ok",
                "path": "/tmp/latest_account_repair_plan.json",
                "batch_id": "gb_current",
                "profile_group": "United States",
                "total_unique_profiles_by_error": 25,
                "total_error_events_by_error": 30,
                "summary_only_error_count": 5,
                "operator_steps": ["修复内核不匹配账号。", "补充已登录账号。"],
            },
            account_repair_apply={
                "status": "applied",
                "stale": True,
                "stale_reason": "newer_account_repair_plan_for_current_batch",
                "pending_recheck": False,
            },
        )

        remediation = boundary["account_pool_remediation"]
        self.assertTrue(remediation["repair_plan_available"])
        self.assertEqual(remediation["repair_plan_path"], "/tmp/latest_account_repair_plan.json")
        self.assertEqual(remediation["repair_plan_batch_id"], "gb_current")
        self.assertEqual(remediation["repair_plan_profile_group"], "United States")
        self.assertEqual(remediation["total_unique_profiles_by_error"], 25)
        self.assertEqual(remediation["total_error_events_by_error"], 30)
        self.assertEqual(remediation["summary_only_error_count"], 5)
        self.assertEqual(remediation["operator_steps"], ["修复内核不匹配账号。", "补充已登录账号。"])
        self.assertEqual(remediation["latest_apply_status"], "applied")
        self.assertEqual(remediation["latest_apply_effective_status"], "stale")
        self.assertIn("旧账号修复结果已失效", remediation["latest_apply_effective_message"])
        self.assertTrue(remediation["latest_apply_stale"])
        self.assertEqual(remediation["latest_apply_stale_reason"], "newer_account_repair_plan_for_current_batch")
        self.assertFalse(remediation["latest_apply_pending_recheck"])

    def test_real_pilot_evidence_boundary_allows_real_ready_only_with_accounts_and_candidates(self):
        boundary = build_real_pilot_evidence_boundary(
            {
                "readiness": "pass",
                "checks": {"profile_available_count": 2},
            },
            {"counts": {"candidates": 5, "actions": 0, "touched": 0}},
            status="passed",
            contract_ok=True,
            acceptance_ready=True,
        )

        self.assertTrue(boundary["real_pilot_ready"])
        self.assertEqual(boundary["status"], "ready")
        self.assertFalse(boundary["fixture_or_dry_run_claimed"])
        self.assertTrue(boundary["no_submit_preserved"])
        self.assertFalse(boundary["requires_real_account_pool"])
        self.assertFalse(boundary["requires_real_collection_evidence"])
        self.assertEqual(boundary["external_acceptance_pending"], [])

    def test_mac_loop_acceptance_requires_start_contract_evidence(self):
        def fake_read_json_url(url, timeout=20):
            if url.endswith("/api/logs"):
                return {
                    "running": False,
                    "run_failed": False,
                    "run_result_status": "completed",
                    "run_result": {"status": "completed"},
                    "lines": [],
                }, ""
            if url.endswith("/api/acceptance"):
                return {
                    "latest_batch": {"id": "gb_contract", "status": "completed", "profile_group": "United States"},
                    "acceptance": {
                        "readiness": "pass",
                        "checks": {
                            "target_planned": True,
                            "campaign_started": True,
                            "profile_preflight_fresh": True,
                            "profile_available_count": 1,
                            "collection_done": True,
                            "action_started": False,
                        },
                        "scoped_log_lines": 12,
                        "no_action_reason": {},
                    },
                    "operations": {"counts": {"candidates": 1, "qualified_leads": 0, "actions": 0}},
                }, ""
            if url.endswith("/api/groups?refresh=1"):
                return {
                    "groups": [{"name": "United States", "count": 700, "count_known": True}],
                    "known_group_count": 1,
                    "profile_count": 700,
                    "stale_cache": False,
                    "background_refresh": False,
                    "error": "",
                }, ""
            if url.endswith("/api/ixbrowser-status"):
                return {"ready": True}, ""
            return {}, "unexpected"

        client_delivery = {"status": "passed", "failed_checks": [], "blockers": []}
        live_status = {"final_delivery_ready": False}
        with patch("tools.reachops_mac_loop_acceptance.read_json_url", side_effect=fake_read_json_url):
            with patch("tools.reachops_mac_loop_acceptance.build_delivery_check", return_value=client_delivery):
                with patch("tools.reachops_mac_loop_acceptance.build_live_acceptance_status", return_value=live_status):
                    payload = reachops_mac_loop_acceptance.build_report("http://127.0.0.1:8769")

        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["checks"]["start_contract_evidence_complete"])
        self.assertIn("start_contract_evidence_complete", payload["local_required_checks"])
        self.assertFalse(payload["start_contract_evidence"]["action_terminal_or_no_submit_reason"])

    def test_mac_loop_acceptance_retries_busy_ixbrowser_status(self):
        calls = []

        def fake_read_json_url(url, timeout=20):
            calls.append(url)
            if len(calls) == 1:
                return {"ready": False, "error": "ixBrowser Local API 繁忙，请稍后重试"}, ""
            return {"ready": True}, ""

        with patch("tools.reachops_mac_loop_acceptance.read_json_url", side_effect=fake_read_json_url):
            with patch("tools.reachops_mac_loop_acceptance.time.sleep", return_value=None):
                payload, error = reachops_mac_loop_acceptance.read_json_url_retry(
                    "http://127.0.0.1:8769/api/ixbrowser-status",
                    attempts=2,
                    delay=0,
                )

        self.assertEqual(error, "")
        self.assertTrue(payload["ready"])
        self.assertEqual(len(calls), 2)

    def test_delivery_check_cli_writes_latest_file_contract(self):
        payload = build_delivery_check()
        out_path = Path(payload["base_dir"]) / "reports" / "acceptance_remediation" / "latest_delivery_check.json"

        self.assertTrue(str(out_path).endswith("latest_delivery_check.json"))
        self.assertEqual(payload["delivery_check_path"], str(out_path))

    def test_delivery_check_cli_accepts_base_dir_output_and_json(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            out_path = base / "custom_delivery_check.json"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = run_delivery_check(["--base-dir", str(base), "--output", str(out_path), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["base_dir"], str(base))
            self.assertEqual(payload["delivery_check_path"], str(out_path))
            self.assertEqual(payload["failed_checks"], ["runtime:evidence", "acceptance:ready"])
            self.assertFalse(payload["final_delivery_ready"])
            self.assertTrue(out_path.is_file())

    def test_delivery_check_reports_missing_runtime_evidence_without_report_noise(self):
        with TemporaryDirectory() as tmpdir:
            payload = build_delivery_check(Path(tmpdir))

        checks = {item["name"]: item for item in payload["checks"]}

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["contract_ok"])
        self.assertFalse(payload["acceptance_ready"])
        self.assertFalse(payload["final_delivery_ready"])
        self.assertIn("runtime:evidence", payload["failed_checks"])
        self.assertIn("acceptance:ready", payload["failed_checks"])
        self.assertFalse(checks["runtime:evidence"]["ok"])
        self.assertEqual(checks["runtime:evidence"]["message"], "no runtime batch/log evidence available")
        self.assertTrue(checks["report:latest_index_path"]["ok"])
        self.assertFalse(checks["report:latest_index_path"]["required"])
        self.assertTrue(checks["manifest:entrypoints"]["ok"])
        self.assertFalse(checks["manifest:entrypoints"]["required"])
        self.assertTrue(checks["manifest:account_repair_summary"]["ok"])
        self.assertFalse(checks["manifest:account_repair_summary"]["required"])

    def test_delivery_check_requires_local_client_console_manifest_entrypoint(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report_dir = base / "reports" / "acceptance_remediation"
            report_dir.mkdir(parents=True)
            manifest_path = report_dir / "legacy_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "client_entrypoints": {
                            "web_ui": "启动ReachOps统一WebUI.command",
                            "native_mac_ui": "启动ReachOps原生MacUI.command",
                            "real_retest": "复测ReachOps真实执行.command",
                        },
                        "web_operator_api": {
                            "acceptance": "/api/acceptance",
                            "final_status": "/api/final-status",
                            "final_status_no_browser_started": True,
                            "final_status_no_submit": True,
                        },
                        "account_repair_summary": {
                            "total_unique_profiles_by_error": "not-a-number",
                            "total_error_events_by_error": "not-a-number",
                            "summary_only_error_count": "not-a-number",
                            "error_groups": [{"error": "LOGIN_REQUIRED"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            batch = {"id": "gb_manifest", "status": "failed", "profile_group": "United States", "config_json": "{}"}
            acceptance = {
                "readiness": "blocked_by_accounts",
                "checks": {"profile_available_count": 0},
                "profile_preflight_details": [{"profile_id": "10001", "error": "LOGIN_REQUIRED"}],
                "profile_preflight_summary": {"errors": {"LOGIN_REQUIRED": 1}},
                "blockers": ["账号不可用"],
                "next_actions": ["修复账号"],
            }
            remediation = {
                "manifest_path": str(manifest_path),
                "latest_manifest_path": str(manifest_path),
                "count": 1,
            }
            with patch("tools.reachops_client_delivery_check.latest_batch", return_value=batch):
                with patch("tools.reachops_client_delivery_check.latest_profile_preflight", return_value={"checked": 1, "available": 0}):
                    with patch("tools.reachops_client_delivery_check.read_lines", return_value=["PLAN campaign"]):
                        with patch("tools.reachops_client_delivery_check.derive_acceptance", return_value=acceptance):
                            with patch("tools.reachops_client_delivery_check.build_operations_payload", return_value={"counts": {}}):
                                with patch("tools.reachops_client_delivery_check.write_remediation_report", return_value=remediation):
                                    payload = build_delivery_check(base)

        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(checks["manifest:entrypoints"]["ok"])
        self.assertFalse(checks["manifest:account_repair_summary"]["ok"])
        self.assertTrue(checks["manifest:entrypoints"]["required"])
        self.assertTrue(checks["manifest:account_repair_summary"]["required"])
        self.assertEqual(checks["manifest:account_repair_summary"]["total_error_events_by_error"], 0)
        self.assertIn("manifest:entrypoints", payload["failed_checks"])
        self.assertIn("manifest:account_repair_summary", payload["failed_checks"])

    def test_delivery_check_does_not_mark_environment_blocker_as_accepted(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            log_path = base / "logs" / "growth_ops_runtime.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                        "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight",
                        "BLOCK  campaign failed batch=gb_3 reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_delivery_check(base)

        checks = {item["name"]: item for item in payload["checks"]}

        self.assertEqual(payload["readiness"], "blocked_by_environment")
        self.assertEqual(payload["status"], "blocked_by_environment")
        self.assertTrue(payload["contract_ok"])
        self.assertFalse(payload["acceptance_ready"])
        self.assertFalse(payload["final_delivery_ready"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_checks"], ["acceptance:ready"])
        self.assertFalse(checks["acceptance:ready"]["ok"])

    def test_delivery_check_embeds_readonly_ixbrowser_metadata_for_environment_blocker(self):
        metadata = {
            "status": "ok",
            "safe_read_only": True,
            "open_profile_called": False,
            "profile_count": 0,
            "group_count": 0,
            "selected_profile_count": 0,
        }
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            log_path = base / "logs" / "growth_ops_runtime.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        "CONFIG refresh_profiles groups_loaded groups=0 profiles=0",
                        "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                        "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight group=United States",
                        "CONFIG selected_profiles group=United States requested=1 candidates=0 selected=0 excluded=0",
                        "BLOCK  campaign failed batch=gb_3 reason=没有可用账号 error=NO_PROFILE_SELECTED",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_delivery_check(base, ixbrowser_metadata=metadata, collect_metadata=True)

        checks = {item["name"]: item for item in payload["checks"]}

        self.assertEqual(payload["readiness"], "blocked_by_environment")
        self.assertEqual(payload["ixbrowser_metadata"]["profile_count"], 0)
        self.assertTrue(checks["ixbrowser:list_api_metadata"]["ok"])
        self.assertTrue(checks["ixbrowser:list_api_metadata"]["safe_read_only"])
        self.assertFalse(checks["ixbrowser:list_api_metadata"]["open_profile_called"])
        self.assertTrue(payload["contract_ok"])

    def test_delivery_check_requires_selected_group_count_to_match_group_list(self):
        metadata = {
            "status": "ok",
            "safe_read_only": True,
            "open_profile_called": False,
            "profile_count": 20,
            "group_count": 2,
            "selected_group_id": "257999",
            "group_name_filter": "United States",
            "selected_profile_count": 702,
            "groups": [
                {
                    "group_id": "257999",
                    "group_name": "United States",
                    "profile_count": 702,
                    "count_known": True,
                    "count_source": "selected_group_profile_list",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            log_path = base / "logs" / "growth_ops_runtime.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        "CONFIG refresh_profiles groups_loaded groups=1 profiles=deferred",
                        "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                        "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight group=United States",
                        "CONFIG selected_profiles group=United States requested=1 candidates=0 selected=0 excluded=0",
                        "BLOCK  campaign failed batch=gb_3 reason=没有可用账号 error=NO_PROFILE_SELECTED",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_delivery_check(base, ixbrowser_metadata=metadata, collect_metadata=True)

        checks = {item["name"]: item for item in payload["checks"]}

        self.assertTrue(checks["ixbrowser:selected_group_count_consistent"]["ok"])
        self.assertEqual(checks["ixbrowser:selected_group_count_consistent"]["matched_group_count"], 702)
        self.assertEqual(checks["ixbrowser:selected_group_count_consistent"]["matched_group_count_source"], "selected_group_profile_list")

    def test_delivery_check_fails_when_selected_group_count_is_not_reflected_in_group_list(self):
        metadata = {
            "status": "ok",
            "safe_read_only": True,
            "open_profile_called": False,
            "profile_count": 20,
            "group_count": 2,
            "selected_group_id": "257999",
            "group_name_filter": "United States",
            "selected_profile_count": 702,
            "groups": [
                {
                    "group_id": "257999",
                    "group_name": "United States",
                    "profile_count": 0,
                    "count_known": False,
                    "count_source": "",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            log_path = base / "logs" / "growth_ops_runtime.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        "CONFIG refresh_profiles groups_loaded groups=1 profiles=deferred",
                        "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                        "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight group=United States",
                        "CONFIG selected_profiles group=United States requested=1 candidates=0 selected=0 excluded=0",
                        "BLOCK  campaign failed batch=gb_3 reason=没有可用账号 error=NO_PROFILE_SELECTED",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_delivery_check(base, ixbrowser_metadata=metadata, collect_metadata=True)

        checks = {item["name"]: item for item in payload["checks"]}

        self.assertFalse(checks["ixbrowser:selected_group_count_consistent"]["ok"])
        self.assertFalse(payload["contract_ok"])
        self.assertIn("ixbrowser:selected_group_count_consistent", payload["failed_checks"])

    def test_delivery_check_default_does_not_probe_ixbrowser_metadata(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            log_path = base / "logs" / "growth_ops_runtime.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text(
                "\n".join(
                    [
                        "CONFIG refresh_profiles groups_loaded groups=0 profiles=0",
                        "PLAN   campaign id=acq_3 input_type=product_url product=demo",
                        "START  campaign id=acq_3 batch=gb_3 status=pending stage=profile_preflight group=United States",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("tools.reachops_client_delivery_check.collect_ixbrowser_metadata") as probe:
                payload = build_delivery_check(base)

        names = {item["name"] for item in payload["checks"]}
        probe.assert_not_called()
        self.assertNotIn("ixbrowser:list_api_metadata", names)

    def test_start_validation_rejects_incomplete_group_counts(self):
        payload = {
            "groups": [
                {"name": "Canada", "group_id": "281726", "count": 2, "count_known": True},
                {"name": "United States", "group_id": "257999", "count": 0, "count_known": False},
            ],
            "group_count": 2,
            "known_group_count": 1,
            "live_known_group_count": 1,
            "all_group_counts_known": False,
            "live_all_group_counts_known": False,
            "error": "",
            "stale_cache": False,
        }
        with patch("tools.reachops_web_ui.load_groups", return_value=payload):
            ok, result = reachops_web_ui.validate_profile_group_for_start("Canada")

        self.assertFalse(ok)
        self.assertEqual(result["error"], "profile_group_counts_incomplete")
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["known_group_count"], 1)

    def test_delivery_check_write_preserves_existing_ixbrowser_metadata(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report_path = base / "reports" / "acceptance_remediation" / "latest_delivery_check.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                json.dumps(
                    {
                        "ixbrowser_metadata": {
                            "status": "ok",
                            "safe_read_only": True,
                            "open_profile_called": False,
                            "profile_count": 0,
                            "group_count": 0,
                            "selected_profile_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = build_delivery_check(base)

            from tools.reachops_client_delivery_check import write_delivery_check

            write_delivery_check(payload)
            saved = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(saved["ixbrowser_metadata"]["status"], "ok")
        self.assertFalse(saved["ixbrowser_metadata"]["open_profile_called"])


def json_load(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
