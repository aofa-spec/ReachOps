# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.updater import ReachOpsUpdateManager
from ReachOps.version import VERSION
from ReachOps.intelligence import GrowthIntelligenceService
from ReachOps.intelligence.ai_strategy import HTTPAcquisitionIntelligenceProvider
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from ReachOps.workbench.action_router import ActionRouterConfig, FixtureActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService
from tools.reachops_delivery_smoke import build_service
from tools.reachops_live_submit_acceptance import run_acceptance as run_live_submit_acceptance
from tools.write_reachops_update_manifest import build_manifest as build_update_manifest
from ReachOps.intelligence import GrowthTaskConfig


LOCAL_PENDING = "pending_external_validation"


class ProfileSwitchFixtureExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, action: dict, profile: dict, rendered_text: str, dry_run: bool = True) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {
                "status": "failed",
                "error_code": "PAGE_OPEN_FAILED",
                "error_message": "fixture page open failed",
                "evidence_path": "evidence://audit/switch-failed",
            }
        return {
            "status": "success",
            "error_code": "",
            "error_message": "",
            "evidence_path": "evidence://audit/switch-success",
        }


def run_fixture_collection(base_dir: str, target: str):
    service = build_service(base_dir)
    workflow = GrowthWorkflowService(service)
    plan = service.create_campaign_plan(
        target,
        intent_keywords=["where", "link", "buy", "app", "free", "name"],
        exclude_keywords=["spam", "bot"],
        max_sources=1,
    )
    campaign_id = str(plan["campaign"]["id"])
    sources = [{"type": row["source_type"], "value": row["source_value"]} for row in plan.get("sources", [])][:1]
    service.run_collection(
        sources,
        [{"profile_id": "audit-discovery-1", "group_name": "AUDIT"}],
        GrowthTaskConfig(
            campaign_id=campaign_id,
            max_videos_per_creator=1,
            max_comments_per_video=3,
            task_delay_min_seconds=30,
            task_delay_max_seconds=30,
            test_mode=True,
            intent_keywords=["where", "link", "buy", "app", "free", "name"],
            exclude_keywords=["spam", "bot"],
        ),
    )
    return service, workflow, campaign_id, service.storage.latest_collection_batch_for_campaign(campaign_id) or {}


def run_live_authorized_fixture(target: str) -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-live-")
    service, workflow, campaign_id, batch = run_fixture_collection(base_dir, target)
    os.makedirs(os.path.dirname(service.paths.activation_status_path), exist_ok=True)
    with open(service.paths.activation_status_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "active": True,
                "expires_at": "2999-01-01T00:00:00Z",
                "license_tier": "enterprise",
                "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
            },
            fh,
        )
    result = workflow.run_action_router(
        [{"profile_id": "audit-live-1", "group_name": "AUDIT"}],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=10,
            action_types=["comment_reply"],
            dry_run=False,
            allow_live_submit=True,
            live_preflight_only=False,
            per_profile_video_hour_limit=99,
        ),
        fixture_outcomes=[{"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://audit/live-submit"}],
        export_report=False,
    )
    return {
        "campaign_id": campaign_id,
        "batch_id": str(batch.get("id") or ""),
        "result": result,
        "executions": service.storage.list_outreach_executions(limit=1000, batch_id=str(batch.get("id") or "")),
    }


def run_runtime_evidence_guard_fixture(target: str) -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-runtime-evidence-")
    service, workflow, campaign_id, batch = run_fixture_collection(base_dir, target)
    os.makedirs(os.path.dirname(service.paths.activation_status_path), exist_ok=True)
    with open(service.paths.activation_status_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "active": True,
                "expires_at": "2999-01-01T00:00:00Z",
                "license_tier": "enterprise",
                "capabilities": {"live_submit": True, "comment_reply": True},
            },
            fh,
        )
    missing_evidence_path = str(Path(base_dir) / "missing-evidence.png")
    result = workflow.run_action_router(
        [{"profile_id": "audit-live-1", "group_name": "AUDIT"}],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=10,
            action_types=["comment_reply"],
            dry_run=False,
            allow_live_submit=True,
            live_preflight_only=False,
            require_execution_evidence=True,
            per_profile_video_hour_limit=99,
        ),
        fixture_outcomes=[{"action_type": "comment_reply", "status": "success", "evidence_path": missing_evidence_path}],
        export_report=False,
    )
    return {
        "campaign_id": campaign_id,
        "batch_id": str(batch.get("id") or ""),
        "missing_evidence_path": missing_evidence_path,
        "result": result,
        "executions": service.storage.list_outreach_executions(limit=1000, batch_id=str(batch.get("id") or "")),
    }


def run_switch_profile_fixture(target: str) -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-switch-")
    service, workflow, campaign_id, batch = run_fixture_collection(base_dir, target)
    result = workflow.run_action_router(
        [
            {"profile_id": "audit-action-1", "group_name": "AUDIT"},
            {"profile_id": "audit-action-2", "group_name": "AUDIT"},
        ],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=10,
            max_switch_attempts=2,
            action_types=["comment_reply"],
            dry_run=True,
            per_profile_video_hour_limit=99,
        ),
        platform_executor=ProfileSwitchFixtureExecutor(),
        limit=20,
        export_report=False,
    )
    return {
        "campaign_id": campaign_id,
        "batch_id": str(batch.get("id") or ""),
        "result": result,
        "statuses": [row.get("status") for row in result.get("results", [])],
        "profiles": [row.get("profile_id") for row in result.get("results", [])],
    }


def run_fallback_comment_fixture(target: str) -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-fallback-")
    service, workflow, campaign_id, batch = run_fixture_collection(base_dir, target)
    result = workflow.run_action_router(
        [{"profile_id": "audit-action-1", "group_name": "AUDIT"}],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=10,
            action_types=["dm_review"],
            dry_run=True,
            per_profile_video_hour_limit=99,
        ),
        fixture_outcomes=[
            {"action_type": "dm_review", "status": "failed", "error_code": "DM_NOT_ALLOWED"},
            {"action_type": "comment_reply", "status": "success"},
        ],
        export_report=False,
    )
    return {
        "campaign_id": campaign_id,
        "batch_id": str(batch.get("id") or ""),
        "result": result,
        "action_types": [row.get("action_type") for row in result.get("results", [])],
        "statuses": [row.get("status") for row in result.get("results", [])],
    }


def run_ai_fallback_fixture(target: str) -> dict:
    def failing_requester(_endpoint, _payload, _headers, _timeout_seconds):
        raise TimeoutError("simulated ai timeout")

    base_dir = tempfile.mkdtemp(prefix="reachops-audit-ai-fallback-")
    service = GrowthIntelligenceService(
        base_dir=base_dir,
        intelligence_provider=HTTPAcquisitionIntelligenceProvider(
            endpoint="https://ai.local/analyze",
            requester=failing_requester,
            provider_name="audit_ai",
        ),
    )
    plan = service.create_campaign_plan(target, max_sources=1)
    return {
        "campaign": plan.get("campaign", {}),
        "strategy": plan.get("strategy", {}),
        "sources": plan.get("sources", []),
    }


def run_live_submit_acceptance_fixture() -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-live-submit-acceptance-")
    args = SimpleNamespace(
        base_dir=base_dir,
        profile_ids="10001",
        group_name="AUDIT",
        video_url="https://www.tiktok.com/@creator/video/123",
        follow_profile_url="https://www.tiktok.com/@buyer_one",
        dm_profile_url="https://www.tiktok.com/@buyer_one",
        target_username="buyer_one",
        comment_text="authorized audit comment",
        dm_text="authorized audit dm",
        workers=1,
        per_profile_limit=3,
        switch_attempts=2,
        limit=3,
        confirm_authorized_targets="YES",
        allow_pressure_submit="",
        per_profile_hour_limit=10,
        per_profile_video_hour_limit=5,
        page_timeout=1,
        element_timeout=1,
    )

    paths = RuntimePaths.build(base_dir).ensure_dirs()
    os.makedirs(os.path.dirname(paths.activation_status_path), exist_ok=True)
    with open(paths.activation_status_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "active": True,
                "expires_at": "2999-01-01T00:00:00Z",
                "license_tier": "enterprise",
                "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
            },
            fh,
        )
    return run_live_submit_acceptance(
        args,
        platform_executor=FixtureActionExecutor(
            [
                {"action_type": "comment_reply", "status": "success", "evidence_path": "evidence://audit-live-submit/comment"},
                {"action_type": "follow_review", "status": "success", "evidence_path": "evidence://audit-live-submit/follow"},
                {"action_type": "dm_review", "status": "success", "evidence_path": "evidence://audit-live-submit/dm"},
            ]
        ),
    )


def run_live_submit_acceptance_block_fixture() -> dict:
    args = SimpleNamespace(
        base_dir=tempfile.mkdtemp(prefix="reachops-audit-live-submit-block-"),
        profile_ids="10001",
        group_name="AUDIT",
        video_url="https://www.tiktok.com/@creator/video/123",
        follow_profile_url="https://www.tiktok.com/@buyer_one",
        dm_profile_url="https://www.tiktok.com/@buyer_one",
        target_username="buyer_one",
        comment_text="blocked audit comment",
        dm_text="blocked audit dm",
        workers=1,
        per_profile_limit=3,
        switch_attempts=2,
        limit=3,
        confirm_authorized_targets="",
        allow_pressure_submit="",
        per_profile_hour_limit=3,
        per_profile_video_hour_limit=1,
        page_timeout=1,
        element_timeout=1,
    )

    return run_live_submit_acceptance(
        args,
        platform_executor=FixtureActionExecutor([{"status": "success", "evidence_path": "evidence://should-not-run"}]),
    )


def run_packaging_update_fixture() -> dict:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-audit-packaging-"))
    installer = base_dir / "ReachOps-Setup.exe"
    install_dir = base_dir / "ReachOpsInstall"
    installer.write_bytes(b"reachops installer smoke")
    manifest = build_update_manifest(installer, version="9.9.9", build="audit", channel="mvp")
    manager = ReachOpsUpdateManager(current_version=VERSION, install_dir=str(install_dir))
    update = manager.check_manifest(manifest)
    return {
        "manifest_valid": True,
        "update_available": update.available,
        "latest_version": update.latest_version,
        "hash_ok": manager.verify_installer(installer, manifest),
        "silent_install_args": manager.silent_install_args(installer),
        "preserve_config": bool((manifest.get("runtime_policy") or {}).get("preserve_config")),
        "preserve_data": bool((manifest.get("runtime_policy") or {}).get("preserve_data")),
        "preserve_activation_status": bool((manifest.get("runtime_policy") or {}).get("preserve_activation_status")),
    }


class AuditDeviceIdentity:
    @classmethod
    def current_device_id(cls) -> str:
        return "audit-device"


def run_authorization_gate_matrix_fixture() -> dict:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-audit-authorization-"))
    status_path = base_dir / "reachops_activation_status.json"
    action = {"action_type": "comment_reply", "id": "audit-action"}
    follow_action = {"action_type": "follow_review", "id": "audit-follow"}
    profile = {"profile_id": "10001"}

    def decide(payload: dict, current_action: dict = action) -> dict:
        status_path.write_text(json.dumps(payload), encoding="utf-8")
        decision = LiveSubmitAuthorizationGate(str(status_path), device_identity=AuditDeviceIdentity).authorize_live_submit(current_action, profile)
        return {
            "allowed": decision.allowed,
            "error_code": decision.error_code,
            "error_message": decision.error_message,
        }

    active_payload = {
        "active": True,
        "device_id": "audit-device",
        "expires_at": "2999-01-01T00:00:00Z",
        "license_tier": "enterprise",
        "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": True, "dm_review": True},
    }
    allowed = decide(active_payload)
    device_mismatch = decide({**active_payload, "device_id": "another-device"})
    expired = decide({**active_payload, "expires_at": "2000-01-01T00:00:00Z"})
    disabled_action = decide(
        {
            **active_payload,
            "capabilities": {"live_submit": True, "comment_reply": True, "follow_review": False, "dm_review": True},
        },
        current_action=follow_action,
    )
    return {
        "allowed": allowed,
        "device_mismatch": device_mismatch,
        "expired": expired,
        "disabled_action": disabled_action,
    }


def run_profile_group_refresh_fixture() -> dict:
    from ReachOps.workbench.standalone_app import StandaloneProfileRegistry, group_display_name

    class FakeIXBrowserClient:
        calls = []

        def __init__(self):
            self.total = 0

        def get_profile_list(self, page=1, limit=100, **kwargs):
            self.calls.append({"page": page, "limit": limit, **kwargs})
            if "group_id" in kwargs:
                return []
            self.total = 5
            pages = {
                1: {
                    "data": {
                        "records": [
                            {"profileId": "ca-1", "profileName": "CA 1", "groupId": "281726", "groupName": "Canada"},
                            {"profileId": "ca-2", "profileName": "CA 2", "groupId": "281726", "groupName": "Canada"},
                            {"profileId": "us-1", "profileName": "US 1", "groupId": "257999", "groupName": "US"},
                            {"profileId": "br-1", "profileName": "BR 1", "groupId": "286343", "groupName": "BR"},
                            {"profileId": "br-2", "profileName": "BR 2", "groupId": "286343", "groupName": "BR"},
                        ],
                        "totalCount": 5,
                    }
                }
            }
            return pages.get(page, {"data": {"records": [], "totalCount": 5}})

        def get_group_list(self, page=1, limit=100):
            self.total = 1
            if page == 1:
                return {"data": {"list": [{"groupId": "stale", "groupName": "Stale Group", "profileCount": 999}], "total": 1}}
            return {"data": {"list": [], "total": 1}}

    previous_module = sys.modules.get("ixbrowser_local_api")
    sys.modules["ixbrowser_local_api"] = SimpleNamespace(IXBrowserClient=FakeIXBrowserClient)
    try:
        registry = StandaloneProfileRegistry()
        snapshot = registry.refresh(max_pages=3, include_profiles=False)
        canada_profiles = registry.select_profiles("Canada", limit=10)
        all_profiles = registry.select_profiles("全部配置", limit=10)
        groups = list(snapshot.get("groups") or [])
        labels = {str(row.get("group_name") or ""): group_display_name(row) for row in groups}
        counts = {str(row.get("group_name") or ""): int(row.get("count") or 0) for row in groups}
        return {
            "profile_count": snapshot.get("profile_count"),
            "group_count": snapshot.get("group_count"),
            "counts": counts,
            "labels": labels,
            "selected_canada_profile_ids": [row.get("profile_id") for row in canada_profiles],
            "all_profile_ids": [row.get("profile_id") for row in all_profiles],
            "stale_group_present": "Stale Group" in counts,
            "profiles_deferred": snapshot.get("profiles_deferred"),
            "profile_list_calls": list(FakeIXBrowserClient.calls),
            "all_profile_calls_omit_group_id": bool(FakeIXBrowserClient.calls)
            and all("group_id" not in row for row in FakeIXBrowserClient.calls),
        }
    finally:
        if previous_module is None:
            sys.modules.pop("ixbrowser_local_api", None)
        else:
            sys.modules["ixbrowser_local_api"] = previous_module


def run_profile_preflight_anomaly_fixture() -> dict:
    from ReachOps.intelligence import GrowthIntelligenceService
    from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig

    class AuditReleaseManager:
        def release(self, *_args, **_kwargs):
            return None

    class AuditProfileGroupManager:
        def __init__(self):
            self.moves = []

        def move_profile_to_quarantine(self, profile_id: str, reason: str = ""):
            self.moves.append((str(profile_id), str(reason)))
            return SimpleNamespace(ok=True, profile_id=str(profile_id), group_id="999", group_name="封禁账号", error_code="", error_message="")

    class AuditPreflightDriver:
        def __init__(self, page_text: str = "", fail_open: bool = False):
            self.page_text = page_text
            self.fail_open = fail_open
            self.current_url = "https://www.tiktok.com/messages"
            self.title = "TikTok"

        def set_page_load_timeout(self, _seconds):
            return None

        def get(self, url):
            self.current_url = url
            if self.fail_open:
                raise Exception("ERR_PROXY_CONNECTION_FAILED")

        def execute_script(self, script):
            if "pumbaaCtx" in str(script):
                text = self.page_text.lower()
                login_gate = "log in" in text or "sign up" in text
                logged_in = "messages" in text or "inbox" in text or "upload" in text
                return {
                    "url": self.current_url,
                    "title": self.title,
                    "loginGate": login_gate,
                    "loggedIn": logged_in,
                    "exactLoginButton": login_gate,
                    "dialogLoginGate": login_gate,
                    "forcedLoginText": login_gate,
                    "accountSetupGate": False,
                    "labels": ["log in"] if login_gate else ["messages"],
                    "dialogs": [],
                    "sample": self.page_text,
                }
            return self.page_text

    base_dir = tempfile.mkdtemp(prefix="reachops-audit-profile-preflight-")
    service = GrowthIntelligenceService(base_dir=base_dir)
    group_manager = AuditProfileGroupManager()
    profiles = [
        {"profile_id": "10001", "group_name": "US"},
        {"profile_id": "10002", "group_name": "US"},
        {"profile_id": "10003", "group_name": "US"},
        {"profile_id": "10004", "group_name": "US"},
        {"profile_id": "10005", "group_name": "US"},
    ]

    def factory(profile: dict):
        profile_id = str(profile.get("profile_id") or "")
        if profile_id == "10001":
            return AuditPreflightDriver("Messages Inbox Profile Upload"), (AuditReleaseManager(), profile_id), ""
        if profile_id == "10002":
            return AuditPreflightDriver("Log in to continue Sign up"), (AuditReleaseManager(), profile_id), ""
        if profile_id == "10003":
            return AuditPreflightDriver("captcha verify to continue security check"), (AuditReleaseManager(), profile_id), ""
        if profile_id == "10004":
            return AuditPreflightDriver("proxy failed", fail_open=True), (AuditReleaseManager(), profile_id), ""
        if profile_id == "10005":
            return None, None, "profile start failed"
        return None, None, "unknown profile"

    checker = ProfilePreflightChecker(
        service.storage,
        ProfilePreflightConfig(max_workers=3, page_load_timeout_seconds=1, wait_after_open_seconds=0, close_browser_after_check=True),
        driver_factory=factory,
        group_manager=group_manager,
    )
    available, summary = checker.available_profiles(profiles)
    health = {str(row.get("profile_id") or ""): row for row in service.storage.list_profile_health(limit=20)}
    return {
        "requested": summary.get("requested"),
        "checked": summary.get("checked"),
        "available": summary.get("available"),
        "unavailable": summary.get("unavailable"),
        "errors": summary.get("errors") or {},
        "available_profile_ids": [row.get("profile_id") for row in available],
        "health": {
            profile_id: {
                "status": row.get("status"),
                "last_error_code": row.get("last_error_code"),
                "consecutive_failures": row.get("consecutive_failures"),
            }
            for profile_id, row in health.items()
        },
        "quarantine_moves": group_manager.moves,
    }


def _method_body(source: str, method_name: str) -> str:
    marker = f"    def {method_name}("
    if marker not in source:
        return ""
    body = source.split(marker, 1)[1]
    next_marker = body.find("\n    def ")
    if next_marker >= 0:
        body = body[:next_marker]
    return body


def run_operator_console_contract_fixture() -> dict:
    console_source = (ROOT_DIR / "ReachOps/workbench/console.py").read_text(encoding="utf-8")
    app_source = (ROOT_DIR / "ReachOps/workbench/standalone_app.py").read_text(encoding="utf-8")

    start_page_body = _method_body(console_source, "_build_start_collection_page")
    start_collection_body = _method_body(app_source, "start_collection_from_console")
    collection_finished_body = _method_body(app_source, "_collection_finished")
    action_preflight_body = _method_body(app_source, "_start_action_queue_processing")
    export_report_body = _method_body(app_source, "export_report")
    refresh_body = _method_body(app_source, "_refresh_profile_groups_sync")
    apply_refresh_body = _method_body(app_source, "_apply_profile_group_snapshot")

    real_setting_tokens = [
        "scan_max_videos_var",
        "scan_max_comments_var",
        "scan_profile_limit_var",
        "scan_interval_var",
        "scan_intent_keywords_var",
        "scan_exclude_keywords_var",
        "action_execution_workers_var",
    ]
    wired_button_tokens = [
        "command=self._start_collection",
        "command=self._export_report",
        "command=self._refresh_profile_groups",
    ]
    log_tokens = [
        "PLAN   campaign",
        "CHECK  profile_preflight",
        "START  campaign",
        "DONE   collection",
        "WARN   collection recoverable_errors",
        "_schedule_runtime_refresh",
    ]
    popup_tokens = ["messagebox.show", "showerror(", "showwarning(", "showinfo("]
    automation_bodies = {
        "start_collection_from_console": start_collection_body,
        "_collection_finished": collection_finished_body,
        "_start_action_queue_processing": action_preflight_body,
        "export_report": export_report_body,
    }
    popup_hits = {
        name: [token for token in popup_tokens if token in body]
        for name, body in automation_bodies.items()
    }
    operator_control_map = {
        "推广目标": {
            "ui": ["scan_source_value_var", "推广目标"],
            "execution": ["source_value", "create_campaign_plan"],
            "evidence": ["PLAN   campaign", "target={source_value}"],
        },
        "账号分组": {
            "ui": ["scan_profile_group_display_var", "刷新"],
            "execution": ["profile_registry.select_profiles", "_selected_group_name"],
            "evidence": ["CONFIG selected_profiles", "group="],
        },
        "每个目标最多视频": {
            "ui": ["scan_max_videos_var", "每个目标最多视频"],
            "execution": ["max_videos_per_creator=max_videos", "max_sources=max(1, min(max_videos, 5))"],
            "evidence": ["max_videos={max_videos}", "range=每来源最多"],
        },
        "每条视频最多评论": {
            "ui": ["scan_max_comments_var", "每条视频最多评论"],
            "execution": ["max_comments_per_video=max_comments"],
            "evidence": ["max_comments={max_comments}", "每视频最多"],
        },
        "参与账号数": {
            "ui": ["scan_profile_limit_var", "参与账号数"],
            "execution": ["profile_limit = max", "_selected_profiles"],
            "evidence": ["profiles={len(executable_profiles)}", "selected="],
        },
        "任务间隔秒": {
            "ui": ["scan_interval_var", "任务间隔秒"],
            "execution": ["task_delay_min_seconds=task_interval", "task_delay_max_seconds=task_interval"],
            "evidence": ["interval_seconds={task_interval}", "任务间隔"],
        },
        "意向词": {
            "ui": ["scan_intent_keywords_var", "意向词"],
            "execution": ["intent_keywords=intent_keywords"],
            "evidence": ["intent_keywords=", "意向判断："],
        },
        "排除词": {
            "ui": ["scan_exclude_keywords_var", "排除词"],
            "execution": ["exclude_keywords=exclude_keywords"],
            "evidence": ["exclude_keywords", "排除规则"],
        },
        "触达并发": {
            "ui": ["action_execution_workers_var"],
            "execution": ["max_workers=max(1, min(int(self.console.action_execution_workers_var.get()"],
            "evidence": ["profile_preflight", "action_router"],
        },
    }

    def token_present(token: str) -> bool:
        return token in console_source or token in app_source

    operator_control_evidence = {}
    for label, contract in operator_control_map.items():
        ui_ok = all(token_present(token) for token in contract["ui"])
        execution_ok = all(token_present(token) for token in contract["execution"])
        evidence_ok = all(token_present(token) for token in contract["evidence"])
        operator_control_evidence[label] = {
            "ui": ui_ok,
            "execution": execution_ok,
            "evidence": evidence_ok,
            "passed": ui_ok and execution_ok and evidence_ok,
        }

    chinese_source_labels = all(
        token in console_source
        for token in [
            '"auto": "自动识别"',
            '"creator_url": "达人主页"',
            '"content_url": "视频链接"',
            '"live_room_url": "直播间活跃用户"',
            '"product_url": "商品页"',
        ]
    )
    technical_start_page_terms = [
        "creator_url",
        "content_url",
        "live_room_url",
        "profile_preflight",
        "action_router",
    ]
    start_page_technical_hits = [token for token in technical_start_page_terms if token in start_page_body]

    return {
        "buttons_wired": all(token in start_page_body for token in wired_button_tokens),
        "wired_button_tokens": wired_button_tokens,
        "settings_consumed_by_execution": all(token in start_collection_body or token in action_preflight_body for token in real_setting_tokens),
        "real_setting_tokens": real_setting_tokens,
        "runtime_log_tokens_present": all(token in (start_collection_body + collection_finished_body) for token in log_tokens),
        "runtime_log_tokens": log_tokens,
        "operator_log_terminal": "append_runtime_log" in console_source and "self.runtime_log_text" in console_source,
        "non_blocking_automation": all(not hits for hits in popup_hits.values()) and "no_popup=true" in collection_finished_body,
        "popup_hits": popup_hits,
        "chinese_source_labels": chinese_source_labels,
        "display_source_type_used": "display_source_type" in console_source and "format_campaign_plan_summary" in console_source,
        "start_page_technical_hits": start_page_technical_hits,
        "profile_refresh_uses_profile_list": "profile_registry.refresh" in refresh_body and "set_profile_group_options" in apply_refresh_body,
        "operator_control_evidence": operator_control_evidence,
        "operator_controls_all_real": all(row["passed"] for row in operator_control_evidence.values()),
        "operator_result_visibility": {
            "execution_success": "执行成功" in console_source and "execution_success" in console_source,
            "failed": "失败异常" in console_source and "error_diagnostics" in console_source,
            "account_switches": "换号次数" in console_source and "account_switches" in console_source,
            "error_code": "首要错误" in console_source and "display_error_code" in console_source,
            "action_router_summary": all(token in console_source for token in ["成功:", "失败:", "换号:", "错误统计:"]),
        },
    }


def run_campaign_funnel_isolation_fixture(target: str) -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-funnel-isolation-")
    service = build_service(base_dir)
    workflow = GrowthWorkflowService(service)

    old_plan = service.create_campaign_plan(f"{target} old audience", max_sources=1)
    service.run_collection(
        [{"type": "keyword", "value": f"{target} old audience"}],
        [{"profile_id": "audit-old-discovery", "group_name": "US"}],
        GrowthTaskConfig(
            campaign_id=old_plan["campaign"]["id"],
            max_videos_per_creator=1,
            max_comments_per_video=3,
            task_delay_min_seconds=30,
            task_delay_max_seconds=30,
            test_mode=True,
        ),
    )
    old_batch = service.storage.latest_collection_batch_for_campaign(old_plan["campaign"]["id"]) or {}
    workflow.run_action_router(
        [{"profile_id": "audit-old-action", "group_name": "US"}],
        config=ActionRouterConfig(max_workers=1, per_profile_action_limit=10, action_types=["comment_reply"], dry_run=True),
        campaign_id=old_plan["campaign"]["id"],
        export_report=False,
    )

    new_plan = service.create_campaign_plan(f"{target} new audience", max_sources=1)
    service.run_collection(
        [{"type": "keyword", "value": f"{target} new audience"}],
        [{"profile_id": "audit-new-discovery", "group_name": "CA"}],
        GrowthTaskConfig(
            campaign_id=new_plan["campaign"]["id"],
            max_videos_per_creator=1,
            max_comments_per_video=3,
            task_delay_min_seconds=30,
            task_delay_max_seconds=30,
            test_mode=True,
        ),
    )
    new_batch = service.storage.latest_collection_batch_for_campaign(new_plan["campaign"]["id"]) or {}

    old_funnel = workflow.build_campaign_funnel(campaign_id=old_plan["campaign"]["id"], batch_id=str(old_batch.get("id") or ""))
    new_funnel = workflow.build_campaign_funnel(campaign_id=new_plan["campaign"]["id"], batch_id=str(new_batch.get("id") or ""))
    old_snapshot = workflow.build_snapshot(campaign_id=old_plan["campaign"]["id"], batch_id=str(old_batch.get("id") or ""))
    new_snapshot = workflow.build_snapshot(campaign_id=new_plan["campaign"]["id"], batch_id=str(new_batch.get("id") or ""))

    return {
        "old_campaign_id": old_plan["campaign"]["id"],
        "new_campaign_id": new_plan["campaign"]["id"],
        "old_batch_id": str(old_batch.get("id") or ""),
        "new_batch_id": str(new_batch.get("id") or ""),
        "old_funnel": old_funnel,
        "new_funnel": new_funnel,
        "old_candidate_batch_ids": sorted({str(row.get("batch_id") or "") for row in old_snapshot.candidate_users}),
        "new_candidate_batch_ids": sorted({str(row.get("batch_id") or "") for row in new_snapshot.candidate_users}),
        "old_action_batch_ids": sorted({str(row.get("batch_id") or "") for row in old_snapshot.action_queue}),
        "new_action_batch_ids": sorted({str(row.get("batch_id") or "") for row in new_snapshot.action_queue}),
        "old_execution_success": old_funnel.get("execution_success"),
        "new_execution_success": new_funnel.get("execution_success"),
    }


def run_collection_error_state_fixture() -> dict:
    from ReachOps.intelligence import GrowthIntelligenceService

    class PageOpenFailDriver:
        current_url = ""
        title = ""

        def get(self, url):
            self.current_url = url
            raise Exception("audit page open failed")

    class EmptyCommentDriver:
        current_url = ""
        title = "TikTok"

        def get(self, url):
            self.current_url = url

        def execute_script(self, _script):
            return ""

    class StaticProfileCollector:
        def collect(self, _driver, _task, _context):
            return {"username": "audit_creator", "profile_url": "https://www.tiktok.com/@audit_creator"}

    class StaticVideoCollector:
        def collect(self, _driver, _task, _context):
            return [
                {
                    "video_id": "audit-video-1",
                    "video_url": "https://www.tiktok.com/@audit_creator/video/1",
                    "caption": "audit video",
                    "views": 1000,
                    "comments": 10,
                }
            ]

    class EmptyCommentCollector:
        level = "selenium_dom"
        last_diagnostics = {
            "page_state": "empty_comments",
            "error_code": "COMMENT_SCAN_EMPTY",
            "comment_panel_seen": False,
            "comment_open_attempts": 3,
        }

        def collect(self, _driver, _task, _context):
            return []

    page_fail_base = tempfile.mkdtemp(prefix="reachops-audit-page-fail-")
    page_fail_service = GrowthIntelligenceService(
        base_dir=page_fail_base,
        browser_factory=lambda _profile_id: PageOpenFailDriver(),
        collectors={
            "profile": StaticProfileCollector(),
            "video": StaticVideoCollector(),
            "comment": EmptyCommentCollector(),
            "search": object(),
        },
    )
    page_fail_result = page_fail_service.run_collection(
        [{"type": "creator_url", "value": "https://www.tiktok.com/@audit_creator"}],
        [{"profile_id": "audit-page-fail", "group_name": "US"}],
        GrowthTaskConfig(test_mode=True, task_delay_min_seconds=30, task_delay_max_seconds=30),
    )
    page_fail_tasks = page_fail_service.storage.list_collection_tasks(limit=20)

    empty_comment_base = tempfile.mkdtemp(prefix="reachops-audit-empty-comments-")
    empty_comment_service = GrowthIntelligenceService(
        base_dir=empty_comment_base,
        browser_factory=lambda _profile_id: EmptyCommentDriver(),
        collectors={
            "profile": StaticProfileCollector(),
            "video": StaticVideoCollector(),
            "comment": EmptyCommentCollector(),
            "search": object(),
        },
    )
    empty_comment_service.router._wait_for_page = lambda *_args, **_kwargs: True
    empty_comment_result = empty_comment_service.run_collection(
        [{"type": "creator_url", "value": "https://www.tiktok.com/@audit_creator"}],
        [{"profile_id": "audit-empty-comments", "group_name": "US"}],
        GrowthTaskConfig(test_mode=True, task_delay_min_seconds=30, task_delay_max_seconds=30),
    )
    empty_comment_tasks = empty_comment_service.storage.list_collection_tasks(limit=20)

    return {
        "page_open_failed": {
            "processed_sources": page_fail_result.processed_sources,
            "errors": page_fail_result.errors,
            "tasks": [{"status": row.get("status"), "error_code": row.get("error_code")} for row in page_fail_tasks],
        },
        "empty_comments": {
            "processed_sources": empty_comment_result.processed_sources,
            "errors": empty_comment_result.errors,
            "tasks": [{"status": row.get("status"), "error_code": row.get("error_code")} for row in empty_comment_tasks],
            "candidate_count": empty_comment_service.storage.count_table("candidate_users"),
        },
    }


def run_product_link_campaign_fixture() -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-product-link-")
    service = build_service(base_dir)
    target = "https://www.amazon.com/Retinol-Anti-Aging-Face-Serum/dp/B0ABC12345?tag=audit"
    plan = service.create_campaign_plan(target, max_sources=6)
    campaign = plan.get("campaign") or {}
    persona = plan.get("persona") or {}
    sources = list(plan.get("sources") or [])
    strategy = plan.get("strategy") or {}
    executable_source_types = {"keyword", "hashtag", "creator_url", "content_url", "live_room_url"}
    source_types = sorted({str(row.get("source_type") or "") for row in sources})
    return {
        "target": target,
        "campaign": campaign,
        "persona": {
            "interests": persona.get("interests") or [],
            "intent_keywords": persona.get("intent_keywords") or [],
            "search_keywords": persona.get("search_keywords") or [],
            "hashtags": persona.get("hashtags") or [],
        },
        "sources": sources,
        "source_pairs": [(row.get("source_type"), row.get("source_value")) for row in sources],
        "source_types": source_types,
        "all_sources_executable": all(str(row.get("source_type") or "") in executable_source_types for row in sources),
        "direct_product_url_source_count": sum(1 for row in sources if str(row.get("source_type") or "") == "product_url"),
        "direct_shop_url_source_count": sum(1 for row in sources if str(row.get("source_type") or "") == "shop_url"),
        "non_executable_source_types": sorted(set(source_types) - executable_source_types),
        "product_analysis": strategy.get("product_analysis") or {},
        "source_expansion": strategy.get("source_expansion") or [],
    }


def run_creator_and_topic_input_fixture() -> dict:
    base_dir = tempfile.mkdtemp(prefix="reachops-audit-creator-topic-")
    service = build_service(base_dir)
    creator_plan = service.create_campaign_plan("https://www.tiktok.com/@beauty_creator", max_sources=3)
    topic_plan = service.create_campaign_plan("#skincare", max_sources=3)

    def compact(plan: dict) -> dict:
        campaign = plan.get("campaign") or {}
        sources = list(plan.get("sources") or [])
        return {
            "campaign": campaign,
            "sources": sources,
            "source_pairs": [(row.get("source_type"), row.get("source_value")) for row in sources],
            "source_types": sorted({str(row.get("source_type") or "") for row in sources}),
        }

    return {
        "creator": compact(creator_plan),
        "topic": compact(topic_plan),
    }


def inspect_exported_campaign_artifacts(
    campaign_report: str,
    customers_csv: str,
    actions_csv: str,
    executions_csv: str,
    action_report: str,
) -> dict:
    payload = {}
    customer_header = []
    action_header = []
    execution_header = []
    customer_rows = 0
    action_rows = 0
    execution_rows = 0
    action_report_payload = {}
    if campaign_report and Path(campaign_report).exists():
        with open(campaign_report, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    if customers_csv and Path(customers_csv).exists():
        with open(customers_csv, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            customer_header = list(reader.fieldnames or [])
            customer_rows = sum(1 for _row in reader)
    if actions_csv and Path(actions_csv).exists():
        with open(actions_csv, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            action_header = list(reader.fieldnames or [])
            action_rows = sum(1 for _row in reader)
    if executions_csv and Path(executions_csv).exists():
        with open(executions_csv, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            execution_header = list(reader.fieldnames or [])
            execution_rows = sum(1 for _row in reader)
    if action_report and Path(action_report).exists():
        with open(action_report, "r", encoding="utf-8") as fh:
            action_report_payload = json.load(fh)
    required_customer_columns = {"username", "profile_url", "qualify_score", "intent_tags", "comment_text", "video_url", "batch_id"}
    required_action_columns = {"target_username", "action_type", "status", "risk_level", "suggested_text", "target_url", "batch_id"}
    required_execution_columns = {"action_id", "action_type", "target_username", "status", "profile_id", "evidence_path", "error_code", "created_at"}
    funnel = payload.get("funnel") or {}
    execution_summary = payload.get("execution_summary") if isinstance(payload.get("execution_summary"), dict) else {}
    outreach_executions = payload.get("outreach_executions") if isinstance(payload.get("outreach_executions"), list) else []
    return {
        "campaign_report_exists": bool(payload),
        "has_campaign": bool(payload.get("campaign")),
        "has_persona": bool(payload.get("persona")),
        "has_strategy": bool(payload.get("strategy")),
        "has_sources": bool(payload.get("sources")),
        "has_funnel": bool(funnel),
        "has_error_counts": isinstance(funnel.get("error_counts"), dict),
        "candidate_users": len(payload.get("candidate_users") or []),
        "operation_leads": len(payload.get("operation_leads") or []),
        "action_queue": len(payload.get("action_queue") or []),
        "outreach_executions_present": isinstance(payload.get("outreach_executions"), list),
        "execution_summary_present": bool(execution_summary),
        "execution_summary_total_matches": int(execution_summary.get("total") or 0) == len(outreach_executions),
        "execution_summary_has_errors": isinstance(execution_summary.get("error_counts"), dict),
        "execution_summary_has_switches": "account_switched" in execution_summary,
        "customer_csv_rows": customer_rows,
        "action_csv_rows": action_rows,
        "execution_csv_rows": execution_rows,
        "customer_header": customer_header,
        "action_header": action_header,
        "execution_header": execution_header,
        "customer_columns_ok": required_customer_columns.issubset(set(customer_header)),
        "action_columns_ok": required_action_columns.issubset(set(action_header)),
        "execution_columns_ok": required_execution_columns.issubset(set(execution_header)),
        "action_report_exists": bool(action_report_payload),
        "action_report_has_summary": bool((action_report_payload.get("summary") or {}).get("total") is not None),
        "action_report_has_errors": isinstance((action_report_payload.get("summary") or {}).get("error_counts"), dict),
    }


def check(name: str, passed: bool, evidence=None, status: str | None = None) -> dict:
    if status:
        result = status
    else:
        result = "passed" if passed else "failed"
    return {"name": name, "status": result, "evidence": evidence or {}}


def run_audit(args) -> dict:
    base_dir = args.base_dir or tempfile.mkdtemp(prefix="reachops-delivery-audit-")
    service = build_service(base_dir)
    workflow = GrowthWorkflowService(service)
    paths = RuntimePaths.build(base_dir).ensure_dirs()

    plan = service.create_campaign_plan(
        args.target,
        intent_keywords=["where", "link", "buy", "app", "free", "name"],
        exclude_keywords=["spam", "bot"],
        max_sources=2,
    )
    campaign_id = str(plan["campaign"]["id"])
    strategy = plan.get("strategy") or {}
    service.save_campaign_strategy_overrides(
        campaign_id,
        {
            "product_analysis": {
                "primary_offer": "operator verified acquisition angle",
            },
            "outreach_recommendations": [
                {
                    "action_type": "comment_reply",
                    "priority": 1,
                    "template_angle": "operator verified comment angle",
                    "risk_level": "medium",
                }
            ],
        },
        updated_by="delivery_audit",
    )
    operator_strategy = service.build_campaign_strategy(campaign_id)
    sources = [{"type": row["source_type"], "value": row["source_value"]} for row in plan.get("sources", [])][:2]
    collection = service.run_collection(
        sources,
        [{"profile_id": "audit-discovery-1", "group_name": "AUDIT"}],
        GrowthTaskConfig(
            campaign_id=campaign_id,
            max_videos_per_creator=2,
            max_comments_per_video=3,
            task_delay_min_seconds=30,
            task_delay_max_seconds=30,
            test_mode=True,
            intent_keywords=["where", "link", "buy", "app", "free", "name"],
            exclude_keywords=["spam", "bot"],
        ),
    )
    batch = service.storage.latest_collection_batch_for_campaign(campaign_id) or {}
    batch_id = str(batch.get("id") or "")
    action_result = workflow.run_action_router(
        [{"profile_id": "audit-action-1", "group_name": "AUDIT"}],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=20,
            action_types=["comment_reply", "follow_review", "dm_review"],
            dry_run=True,
        ),
        export_report=True,
    )
    artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
    funnel = workflow.build_campaign_funnel(campaign_id=campaign_id, batch_id=batch_id)
    candidates = service.storage.list_candidates_with_content(batch_id=batch_id)
    actions = service.storage.list_action_queue(limit=1000, batch_id=batch_id)
    executions = service.storage.list_outreach_executions(limit=1000, batch_id=batch_id)
    events = service.storage.list_recent_events(limit=1000)
    errors = service.storage.error_counts()

    campaign_report = artifacts.get("json_path", "")
    customers_csv = artifacts.get("customers_csv_path", "")
    actions_csv = artifacts.get("actions_csv_path", "")
    executions_csv = artifacts.get("executions_csv_path", "")
    action_report = (action_result.get("report") or {}).get("json_path", "")
    exported_campaign_payload = {}
    if campaign_report and Path(campaign_report).exists():
        with open(campaign_report, "r", encoding="utf-8") as fh:
            exported_campaign_payload = json.load(fh)
    export_artifact_inspection = inspect_exported_campaign_artifacts(campaign_report, customers_csv, actions_csv, executions_csv, action_report)
    live_fixture = run_live_authorized_fixture(args.target)
    runtime_evidence_guard = run_runtime_evidence_guard_fixture(args.target)
    switch_fixture = run_switch_profile_fixture(args.target)
    fallback_fixture = run_fallback_comment_fixture(args.target)
    ai_fallback_fixture = run_ai_fallback_fixture(args.target)
    live_submit_acceptance_fixture = run_live_submit_acceptance_fixture()
    live_submit_block_fixture = run_live_submit_acceptance_block_fixture()
    packaging_update_fixture = run_packaging_update_fixture()
    authorization_gate_matrix = run_authorization_gate_matrix_fixture()
    profile_group_refresh = run_profile_group_refresh_fixture()
    profile_preflight_anomalies = run_profile_preflight_anomaly_fixture()
    operator_console_contract = run_operator_console_contract_fixture()
    campaign_funnel_isolation = run_campaign_funnel_isolation_fixture(args.target)
    collection_error_states = run_collection_error_state_fixture()
    product_link_campaign = run_product_link_campaign_fixture()
    creator_topic_inputs = run_creator_and_topic_input_fixture()

    checks = [
        check("输入产品/关键词即可创建获客任务", bool(plan.get("campaign", {}).get("id")), {"campaign_id": campaign_id, "input_type": plan.get("campaign", {}).get("input_type")}),
        check(
            "产品链接能自动生成获客任务和可执行来源",
            bool(
                (product_link_campaign.get("campaign") or {}).get("id")
                and (product_link_campaign.get("campaign") or {}).get("input_type") == "product_url"
                and (product_link_campaign.get("campaign") or {}).get("product_name")
                and product_link_campaign.get("all_sources_executable")
                and not product_link_campaign.get("non_executable_source_types")
                and int(product_link_campaign.get("direct_product_url_source_count") or 0) == 0
                and int(product_link_campaign.get("direct_shop_url_source_count") or 0) == 0
                and any(row.get("source_type") == "keyword" for row in product_link_campaign.get("sources") or [])
                and any(row.get("source_type") == "hashtag" for row in product_link_campaign.get("sources") or [])
                and bool(product_link_campaign.get("persona", {}).get("intent_keywords"))
                and (product_link_campaign.get("product_analysis") or {}).get("input_type") == "product_url"
            ),
            product_link_campaign,
        ),
        check(
            "达人链接和话题能自动生成获客任务",
            bool(
                (creator_topic_inputs.get("creator", {}).get("campaign") or {}).get("input_type") == "creator_url"
                and ("creator_url", "https://www.tiktok.com/@beauty_creator") in creator_topic_inputs.get("creator", {}).get("source_pairs", [])
                and (creator_topic_inputs.get("topic", {}).get("campaign") or {}).get("input_type") == "hashtag"
                and ("hashtag", "skincare") in creator_topic_inputs.get("topic", {}).get("source_pairs", [])
            ),
            creator_topic_inputs,
        ),
        check(
            "AI/规则能生成产品分析",
            bool((strategy.get("product_analysis") or {}).get("category") and (strategy.get("product_analysis") or {}).get("customer_problem")),
            {"product_analysis": strategy.get("product_analysis", {})},
        ),
        check(
            "外部 AI 故障可自动降级规则策略",
            str((ai_fallback_fixture.get("strategy") or {}).get("generator") or "").endswith("_fallback_rules")
            and bool(ai_fallback_fixture.get("sources")),
            {
                "generator": (ai_fallback_fixture.get("strategy") or {}).get("generator"),
                "category": ((ai_fallback_fixture.get("strategy") or {}).get("product_analysis") or {}).get("category"),
                "source_count": len(ai_fallback_fixture.get("sources") or []),
            },
        ),
        check("系统能自动生成受众画像", bool(plan.get("persona", {}).get("interests")), {"interests": plan.get("persona", {}).get("interests", [])[:5]}),
        check(
            "AI/规则能生成意图分类和话术建议",
            bool(strategy.get("intent_taxonomy")) and bool(strategy.get("outreach_recommendations")),
            {
                "intent_types": [row.get("intent_type") for row in strategy.get("intent_taxonomy", [])],
                "actions": [row.get("action_type") for row in strategy.get("outreach_recommendations", [])],
            },
        ),
        check("系统能自动规划来源", bool(sources), {"sources": sources}),
        check(
            "刷新分组能完整读取 ixBrowser 配置列表",
            bool(
                profile_group_refresh.get("profile_count") == 5
                and profile_group_refresh.get("profiles_deferred") is False
                and profile_group_refresh.get("counts", {}).get("全部配置") == 5
                and profile_group_refresh.get("counts", {}).get("Canada") == 2
                and profile_group_refresh.get("counts", {}).get("BR") == 2
                and not profile_group_refresh.get("stale_group_present")
                and profile_group_refresh.get("all_profile_calls_omit_group_id")
            ),
            profile_group_refresh,
        ),
        check(
            "选择哪个分组就实际用哪个分组执行",
            profile_group_refresh.get("selected_canada_profile_ids") == ["ca-1", "ca-2"]
            and len(profile_group_refresh.get("all_profile_ids") or []) == 5,
            {
                "selected_canada_profile_ids": profile_group_refresh.get("selected_canada_profile_ids"),
                "all_profile_ids": profile_group_refresh.get("all_profile_ids"),
                "counts": profile_group_refresh.get("counts"),
            },
        ),
        check(
            "能识别并排除异常账号",
            bool(
                profile_preflight_anomalies.get("available_profile_ids") == ["10001"]
                and profile_preflight_anomalies.get("available") == 1
                and profile_preflight_anomalies.get("unavailable") == 4
                and profile_preflight_anomalies.get("errors", {}).get("LOGIN_REQUIRED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("CAPTCHA_DETECTED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("PROXY_FAILED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("PROFILE_START_FAILED") == 1
                and all(
                    (profile_preflight_anomalies.get("health", {}).get(profile_id) or {}).get("status") == "cooldown"
                    for profile_id in ["10002", "10003", "10004", "10005"]
                )
            ),
            profile_preflight_anomalies,
        ),
        check(
            "客户端按钮和设置接入真实执行链路",
            bool(
                operator_console_contract.get("buttons_wired")
                and operator_console_contract.get("settings_consumed_by_execution")
                and operator_console_contract.get("profile_refresh_uses_profile_list")
            ),
            operator_console_contract,
        ),
        check(
            "客户可见设置都有执行证据映射",
            bool(operator_console_contract.get("operator_controls_all_real")),
            {
                "operator_controls_all_real": operator_console_contract.get("operator_controls_all_real"),
                "operator_control_evidence": operator_console_contract.get("operator_control_evidence"),
            },
        ),
        check(
            "客户能看到成功失败换号和错误码",
            bool(
                operator_console_contract.get("operator_result_visibility")
                and all((operator_console_contract.get("operator_result_visibility") or {}).values())
                and "execution_success" in funnel
                and "failed" in funnel
                and "account_switches" in funnel
                and isinstance(funnel.get("error_counts"), dict)
            ),
            {
                "operator_result_visibility": operator_console_contract.get("operator_result_visibility"),
                "funnel_fields": {
                    "execution_success": funnel.get("execution_success"),
                    "failed": funnel.get("failed"),
                    "account_switches": funnel.get("account_switches"),
                    "error_counts": funnel.get("error_counts"),
                },
                "action_result": {
                    "success": action_result.get("success"),
                    "failed": action_result.get("failed"),
                    "account_switched": action_result.get("account_switched"),
                    "errors": action_result.get("errors"),
                },
            },
        ),
        check(
            "开始任务后日志能实时显示执行进度",
            bool(operator_console_contract.get("runtime_log_tokens_present") and operator_console_contract.get("operator_log_terminal")),
            {
                "runtime_log_tokens_present": operator_console_contract.get("runtime_log_tokens_present"),
                "runtime_log_tokens": operator_console_contract.get("runtime_log_tokens"),
                "operator_log_terminal": operator_console_contract.get("operator_log_terminal"),
            },
        ),
        check(
            "异常不弹窗卡死",
            bool(operator_console_contract.get("non_blocking_automation")),
            {
                "non_blocking_automation": operator_console_contract.get("non_blocking_automation"),
                "popup_hits": operator_console_contract.get("popup_hits"),
            },
        ),
        check(
            "漏斗只显示本轮 Campaign",
            bool(
                campaign_funnel_isolation.get("old_funnel", {}).get("campaign_id") == campaign_funnel_isolation.get("old_campaign_id")
                and campaign_funnel_isolation.get("new_funnel", {}).get("campaign_id") == campaign_funnel_isolation.get("new_campaign_id")
                and campaign_funnel_isolation.get("old_funnel", {}).get("batch_id") == campaign_funnel_isolation.get("old_batch_id")
                and campaign_funnel_isolation.get("new_funnel", {}).get("batch_id") == campaign_funnel_isolation.get("new_batch_id")
                and campaign_funnel_isolation.get("old_candidate_batch_ids") == [campaign_funnel_isolation.get("old_batch_id")]
                and campaign_funnel_isolation.get("new_candidate_batch_ids") == [campaign_funnel_isolation.get("new_batch_id")]
                and campaign_funnel_isolation.get("old_action_batch_ids") == [campaign_funnel_isolation.get("old_batch_id")]
                and campaign_funnel_isolation.get("new_action_batch_ids") == [campaign_funnel_isolation.get("new_batch_id")]
                and int(campaign_funnel_isolation.get("old_execution_success") or 0) > 0
                and int(campaign_funnel_isolation.get("new_execution_success") or 0) == 0
            ),
            campaign_funnel_isolation,
        ),
        check(
            "能识别页面打不开和无评论",
            bool(
                (collection_error_states.get("page_open_failed", {}).get("errors") or {}).get("CREATOR_PAGE_OPEN_FAILED", 0) >= 1
                and any(
                    str(row.get("error_code") or "") == "CREATOR_PAGE_OPEN_FAILED"
                    for row in collection_error_states.get("page_open_failed", {}).get("tasks", [])
                )
                and (collection_error_states.get("empty_comments", {}).get("errors") or {}).get("COMMENT_SCAN_EMPTY", 0) >= 1
                and int(collection_error_states.get("empty_comments", {}).get("candidate_count") or 0) == 0
            ),
            collection_error_states,
        ),
        check(
            "客户端文案面向运营用户",
            bool(
                operator_console_contract.get("chinese_source_labels")
                and operator_console_contract.get("display_source_type_used")
                and not operator_console_contract.get("start_page_technical_hits")
            ),
            {
                "chinese_source_labels": operator_console_contract.get("chinese_source_labels"),
                "display_source_type_used": operator_console_contract.get("display_source_type_used"),
                "start_page_technical_hits": operator_console_contract.get("start_page_technical_hits"),
            },
        ),
        check(
            "AI/规则能扩展获客来源",
            bool(strategy.get("source_expansion")),
            {"source_expansion": strategy.get("source_expansion", [])[:3]},
        ),
        check(
            "人工可编辑策略可保存并进入报告",
            bool(operator_strategy.get("overrides_applied"))
            and ((exported_campaign_payload.get("strategy") or {}).get("product_analysis") or {}).get("primary_offer") == "operator verified acquisition angle",
            {
                "overrides_applied": operator_strategy.get("overrides_applied"),
                "updated_by": operator_strategy.get("overrides_updated_by"),
                "exported_primary_offer": ((exported_campaign_payload.get("strategy") or {}).get("product_analysis") or {}).get("primary_offer"),
            },
        ),
        check("系统能发现内容", int(funnel.get("content_found") or 0) > 0, {"content_found": funnel.get("content_found")}),
        check("系统能采集互动用户", int(funnel.get("comment_users") or 0) > 0, {"comment_users": funnel.get("comment_users")}),
        check("系统能识别购买/咨询意向", any(int(row.get("qualify_score") or 0) >= 40 for row in candidates), {"candidate_count": len(candidates)}),
        check("系统能生成客户线索", int(funnel.get("customer_leads") or 0) > 0, {"customer_leads": funnel.get("customer_leads")}),
        check("系统能生成触达动作", int(funnel.get("outreach_actions") or 0) > 0 and bool(actions), {"action_count": len(actions)}),
        check("系统能执行预检", bool(executions) and int(action_result.get("success", 0) or 0) > 0, {"executions": len(executions), "success": action_result.get("success")}),
        check(
            "授权允许时能真实执行",
            False,
            {
                "mode": "local_fixture_gate_and_evidence",
                "local_gate_validated": int((live_fixture.get("result") or {}).get("success", 0) or 0) > 0 and bool(live_fixture.get("executions")),
                "result": live_fixture.get("result"),
                "reason": "真实 TikTok 平台提交必须由 platform_selenium live submit 验收证明，fixture 只能证明授权门和证据链路。",
            },
            LOCAL_PENDING,
        ),
        check(
            "真实提交验收入口默认阻止误提交",
            live_submit_block_fixture.get("error_code") == "AUTHORIZATION_INVALID" and live_submit_block_fixture.get("live_submit") is False,
            {"error_code": live_submit_block_fixture.get("error_code"), "errors": live_submit_block_fixture.get("errors", [])},
        ),
        check(
            "真实提交验收入口支持授权证据校验",
            bool(live_submit_acceptance_fixture.get("passed"))
            and int((live_submit_acceptance_fixture.get("summary") or {}).get("success") or 0) == 3
            and int(live_submit_acceptance_fixture.get("missing_evidence_count") or 0) == 0,
            {
                "passed": live_submit_acceptance_fixture.get("passed"),
                "success": (live_submit_acceptance_fixture.get("summary") or {}).get("success"),
                "missing_evidence_count": live_submit_acceptance_fixture.get("missing_evidence_count"),
            },
        ),
        check(
            "真实执行成功必须有有效证据",
            int((runtime_evidence_guard.get("result") or {}).get("failed") or 0) >= 1
            and ((runtime_evidence_guard.get("result") or {}).get("errors") or {}).get("LIVE_SUBMIT_EVIDENCE_MISSING") >= 1,
            {
                "mode": "runtime_action_router_guard",
                "missing_evidence_path": runtime_evidence_guard.get("missing_evidence_path"),
                "result": runtime_evidence_guard.get("result"),
            },
        ),
        check(
            "授权门覆盖设备绑定、过期和能力限制",
            bool(
                (authorization_gate_matrix.get("allowed") or {}).get("allowed")
                and not (authorization_gate_matrix.get("device_mismatch") or {}).get("allowed")
                and (authorization_gate_matrix.get("device_mismatch") or {}).get("error_code") == "LIVE_SUBMIT_DEVICE_MISMATCH"
                and not (authorization_gate_matrix.get("expired") or {}).get("allowed")
                and (authorization_gate_matrix.get("expired") or {}).get("error_code") == "LIVE_SUBMIT_LICENSE_EXPIRED"
                and not (authorization_gate_matrix.get("disabled_action") or {}).get("allowed")
                and (authorization_gate_matrix.get("disabled_action") or {}).get("error_code") == "LIVE_SUBMIT_NOT_AUTHORIZED"
            ),
            authorization_gate_matrix,
        ),
        check(
            "真实 TikTok 平台提交",
            False,
            {"reason": "requires Windows VM, real ixBrowser profile, platform account, and live-submit authorization"},
            LOCAL_PENDING,
        ),
        check(
            "账号失败能自动换号",
            "account_switched" in switch_fixture.get("statuses", []) and "success" in switch_fixture.get("statuses", []),
            {"mode": "local_fixture", "statuses": switch_fixture.get("statuses"), "profiles": switch_fixture.get("profiles")},
        ),
        check(
            "私信/关注失败能降级评论",
            "dm_review" in fallback_fixture.get("action_types", []) and "comment_reply" in fallback_fixture.get("action_types", []) and "success" in fallback_fixture.get("statuses", []),
            {"mode": "local_fixture", "action_types": fallback_fixture.get("action_types"), "statuses": fallback_fixture.get("statuses")},
        ),
        check("全程有实时漏斗", bool(funnel.get("campaign_id") == campaign_id and funnel.get("batch_id") == batch_id), {"funnel": funnel}),
        check("全程有错误码和证据", bool(events), {"event_count": len(events), "error_counts": errors}),
        check(
            "可导出客户名单和执行报告",
            all(Path(path).exists() for path in [campaign_report, customers_csv, actions_csv, executions_csv, action_report] if path),
            {
                "campaign_report": campaign_report,
                "customers_csv": customers_csv,
                "actions_csv": actions_csv,
                "executions_csv": executions_csv,
                "action_report": action_report,
            },
        ),
        check(
            "导出内容包含客户池动作漏斗和错误统计",
            bool(
                export_artifact_inspection.get("has_campaign")
                and export_artifact_inspection.get("has_persona")
                and export_artifact_inspection.get("has_strategy")
                and export_artifact_inspection.get("has_sources")
                and export_artifact_inspection.get("has_funnel")
                and export_artifact_inspection.get("has_error_counts")
                and int(export_artifact_inspection.get("candidate_users") or 0) > 0
                and int(export_artifact_inspection.get("operation_leads") or 0) > 0
                and int(export_artifact_inspection.get("action_queue") or 0) > 0
                and export_artifact_inspection.get("outreach_executions_present")
                and export_artifact_inspection.get("execution_summary_present")
                and export_artifact_inspection.get("execution_summary_total_matches")
                and export_artifact_inspection.get("execution_summary_has_errors")
                and export_artifact_inspection.get("execution_summary_has_switches")
                and int(export_artifact_inspection.get("customer_csv_rows") or 0) > 0
                and int(export_artifact_inspection.get("action_csv_rows") or 0) > 0
                and export_artifact_inspection.get("execution_columns_ok")
                and export_artifact_inspection.get("customer_columns_ok")
                and export_artifact_inspection.get("action_columns_ok")
                and export_artifact_inspection.get("action_report_exists")
                and export_artifact_inspection.get("action_report_has_summary")
                and export_artifact_inspection.get("action_report_has_errors")
            ),
            export_artifact_inspection,
        ),
        check("独立配置/数据/授权目录存在", all(Path(path).exists() for path in [paths.data_dir, paths.config_dir, paths.logs_dir]), {"data_dir": paths.data_dir, "config_dir": paths.config_dir, "activation_status_path": paths.activation_status_path}),
        check("Windows 打包入口存在", all((ROOT_DIR / path).exists() for path in ["ReachOps/packaging/reachops.spec", "ReachOps/packaging/ReachOps.iss", "tools/build_reachops_windows.ps1"]), {"version": VERSION}),
        check(
            "升级清单和安装校验机制可用",
            bool(
                packaging_update_fixture.get("manifest_valid")
                and packaging_update_fixture.get("update_available")
                and packaging_update_fixture.get("hash_ok")
                and packaging_update_fixture.get("preserve_config")
                and packaging_update_fixture.get("preserve_data")
                and packaging_update_fixture.get("preserve_activation_status")
                and "/VERYSILENT" in packaging_update_fixture.get("silent_install_args", [])
                and "/SUPPRESSMSGBOXES" in packaging_update_fixture.get("silent_install_args", [])
            ),
            packaging_update_fixture,
        ),
    ]
    failed = [row for row in checks if row["status"] == "failed"]
    pending = [row for row in checks if row["status"] == LOCAL_PENDING]
    result = {
        "status": "failed" if failed else "ok",
        "base_dir": os.path.abspath(base_dir),
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "summary": {
            "passed": len([row for row in checks if row["status"] == "passed"]),
            "pending_external_validation": len(pending),
            "failed": len(failed),
            "processed_sources": collection.processed_sources,
            "action_selected": action_result.get("selected_actions", 0),
        },
        "checks": checks,
    }
    if failed:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps delivery audit against product acceptance requirements.")
    parser.add_argument("--target", default="anti aging serum")
    parser.add_argument("--base-dir", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    result = run_audit(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
