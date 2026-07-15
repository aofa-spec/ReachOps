# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
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
from tools.reachops_ci_release_baseline_audit import build_report as build_ci_release_baseline_report
from tools.reachops_account_readiness_audit import build_report as build_account_readiness_report
from tools.reachops_control_plane_audit import build_report as build_control_plane_report
from tools.reachops_issue_closure_audit import build_report as build_issue_closure_report
from tools.reachops_delivery_smoke import build_service
from tools.reachops_client_delivery_check import build_delivery_check
from tools.reachops_data_governance import build_report as build_data_governance_report
from tools.reachops_security_supply_chain_audit import build_report as build_security_supply_chain_report
from tools.reachops_start_contract_audit import build_report as build_start_contract_report
from tools.reachops_outcome_metrics import build_report as build_outcome_metrics_report
from tools.reachops_outcome_metrics import import_outcomes_csv as import_outcomes_csv_fixture
from tools.reachops_live_submit_acceptance import run_acceptance as run_live_submit_acceptance
from tools.reachops_repository_cleanliness_check import clean_generated_redundant_paths, scan_repository_cleanliness
from tools.reachops_web_panel_dom_smoke import run_dom_smoke as run_web_panel_dom_smoke
from tools.reachops_web_panel_runtime_smoke import (
    LATEST_RESULT_PATH as WEB_PANEL_RUNTIME_SMOKE_LATEST_PATH,
    run_runtime_smoke as run_web_panel_runtime_smoke,
    source_mtimes as web_panel_runtime_source_mtimes,
)
from tools.write_reachops_update_manifest import build_manifest as build_update_manifest
from ReachOps.intelligence import GrowthTaskConfig


LOCAL_PENDING = "pending_external_validation"


def write_local_action_evidence(base_dir: str, action_type: str, profile_id: str, action_id: str, expected_text: str = "") -> str:
    evidence_dir = Path(base_dir) / "audit_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{profile_id}_{action_id}_{action_type}.png"
    data = b"png"
    path.write_bytes(data)
    sidecar = {
        "screenshot_sha256": hashlib.sha256(data).hexdigest(),
        "screenshot_size": len(data),
        "action_type": action_type,
        "profile_id": profile_id,
        "action_id": action_id,
        "current_url": "https://www.tiktok.com/@buyer_one/video/123",
    }
    if action_type == "comment_reply":
        sidecar["submitted_text"] = expected_text
        sidecar["comment_visible_confirmed"] = True
    Path(f"{path}.json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


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
    comment_action = next(
        (row for row in service.storage.list_action_queue(limit=1000, batch_id=str(batch.get("id") or "")) if str(row.get("action_type") or "") == "comment_reply"),
        {},
    )
    comment_evidence = write_local_action_evidence(
        base_dir,
        "comment_reply",
        "audit-live-1",
        str(comment_action.get("id") or "comment-1"),
        str(comment_action.get("suggested_text") or ""),
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
        fixture_outcomes=[{"action_type": "comment_reply", "status": "success", "evidence_path": comment_evidence}],
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
    evidence_paths = {
        "comment_reply": write_local_action_evidence(base_dir, "comment_reply", "10001", "comment-1", args.comment_text),
        "follow_review": write_local_action_evidence(base_dir, "follow_review", "10001", "follow-1"),
        "dm_review": write_local_action_evidence(base_dir, "dm_review", "10001", "dm-1"),
    }
    return run_live_submit_acceptance(
        args,
        platform_executor=FixtureActionExecutor(
            [
                {"action_type": "comment_reply", "status": "success", "evidence_path": evidence_paths["comment_reply"]},
                {"action_type": "follow_review", "status": "success", "evidence_path": evidence_paths["follow_review"]},
                {"action_type": "dm_review", "status": "success", "evidence_path": evidence_paths["dm_review"]},
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


def run_outcome_metrics_fixture() -> dict:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-audit-outcomes-"))
    db_path = base_dir / "outcomes.db"
    now = "2026-07-14T00:00:00Z"
    build_outcome_metrics_report(db_path=db_path, create_missing_db=True)
    csv_path = base_dir / "outcomes.csv"
    csv_path.write_text(
        "\n".join(
            [
                "id,lead_id,workspace_id,owner,qualification_decision,qualification_reason,rejection_reason,lifecycle_stage,dedupe_key,source_path,evidence_path,data_scope,active_followup,accepted_at,reply_at,meaningful_conversation_at,meeting_at,quote_at,order_at,revenue_amount,revenue_currency,lost_reason,attribution_confidence,contact_policy,cost_amount,cost_currency,created_at",
                f"out-real,lead-real,ws-1,owner-1,accepted,human accepted,,accepted,buyer@example.test,https://www.tiktok.com/@creator/video/1,reports/evidence/lead-real.json,real_customer,1,{now},{now},{now},{now},{now},{now},1200,USD,,operator_confirmed,authorized_followup,300,USD,{now}",
            ]
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO operation_leads
            (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage,
             source_path, status, batch_id, created_at, updated_at)
            VALUES
            ('lead-real', 'candidate-real', 'purchase', 'high', 92, 'asked for price', 'accepted',
             'https://www.tiktok.com/@creator/video/1', 'accepted', 'batch-real', ?, ?),
            ('lead-fixture', 'candidate-fixture', 'purchase', 'high', 99, 'fixture lead', 'accepted',
             'fixture://source', 'accepted', 'batch-fixture', ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO lead_outcomes
            (id, lead_id, workspace_id, owner, qualification_decision, qualification_reason,
             rejection_reason, lifecycle_stage, dedupe_key, source_path, evidence_path, data_scope,
             active_followup, accepted_at, reply_at, revenue_amount, revenue_currency, lost_reason,
             attribution_confidence, contact_policy, cost_amount, cost_currency, created_at, updated_at)
            VALUES
            ('out-fixture', 'lead-fixture', 'ws-1', 'owner-1', 'accepted', 'fixture accepted',
             '', 'accepted', 'fixture-buyer', 'fixture://source', 'fixture://evidence', 'fixture',
             1, ?, ?, 0.0, 'USD', '', 'fixture', 'fixture', 0.0, 'USD', ?, ?)
            """
            ,
            (now, now, now, now),
        )
    ingestion = import_outcomes_csv_fixture(db_path=db_path, csv_path=csv_path, ingest_source="csv")
    report = build_outcome_metrics_report(
        db_path=db_path,
        start_at="2026-07-13T00:00:00Z",
        end_at="2026-07-15T00:00:00Z",
    )
    report["ingestion"] = ingestion
    return report


def run_data_governance_fixture() -> dict:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-audit-governance-"))
    db_path = base_dir / "growth_intelligence.db"
    output_dir = base_dir / "governance"
    return build_data_governance_report(
        root=ROOT_DIR,
        db_path=db_path,
        output_dir=output_dir,
        create_missing_db=True,
        verify_backup=True,
        verify_privacy_ops=True,
    )


def run_web_panel_runtime_smoke_with_retry(attempts: int = 3) -> dict:
    result = {}
    for index in range(max(1, int(attempts or 1))):
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py"), "--json"],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if completed.stdout.strip():
                result = json.loads(completed.stdout)
            else:
                result = {
                    "status": "failed",
                    "passed": False,
                    "failed_checks": ["runtime_smoke_subprocess_no_stdout"],
                    "error": (completed.stderr or "").strip(),
                    "returncode": completed.returncode,
                }
        except Exception as exc:
            result = {
                "status": "failed",
                "passed": False,
                "failed_checks": ["runtime_smoke_subprocess_error"],
                "error": f"{type(exc).__name__}: {exc}",
            }
        if result.get("status") == "failed" and "runtime_smoke_subprocess" in ",".join(result.get("failed_checks") or []):
            try:
                result = run_web_panel_runtime_smoke()
            except Exception as exc:
                result = {
                    "status": "failed",
                    "passed": False,
                    "failed_checks": ["runtime_smoke_inprocess_error"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
        if result.get("status") != "blocked_by_local_sandbox":
            if index:
                result = dict(result)
                result["retry_count"] = index
            return result
        time.sleep(0.4)
    if result.get("status") == "blocked_by_local_sandbox" and WEB_PANEL_RUNTIME_SMOKE_LATEST_PATH.exists():
        try:
            cached = json.loads(WEB_PANEL_RUNTIME_SMOKE_LATEST_PATH.read_text(encoding="utf-8"))
            current_mtimes = web_panel_runtime_source_mtimes()
            cached_mtimes = cached.get("source_mtimes") if isinstance(cached.get("source_mtimes"), dict) else {}
            cache_is_current = all(
                abs(float(cached_mtimes.get(key) or 0) - float(value or 0)) < 0.001
                for key, value in current_mtimes.items()
            )
            if cached.get("passed") and cache_is_current:
                cached = dict(cached)
                cached["status"] = "passed"
                cached["used_cached_current_result"] = True
                cached["blocked_live_attempt"] = result
                return cached
        except Exception:
            pass
    result = dict(result)
    result["retry_count"] = max(0, int(attempts or 1) - 1)
    return result


def run_client_delivery_gate_fixture() -> dict:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-audit-client-delivery-"))
    log_path = base_dir / "logs" / "growth_ops_runtime.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                "PLAN   campaign id=acq_audit input_type=product_url product=audit demo",
                "START  campaign id=acq_audit batch=gb_audit status=pending stage=profile_preflight",
                "BLOCK  campaign failed batch=gb_audit reason=HEADLESS_TIMEOUT next=检查 ixBrowser 本地服务、账号分组和网络后重新复测",
            ]
        ),
        encoding="utf-8",
    )
    payload = build_delivery_check(base_dir)
    acceptance_checks = payload.get("checks") or []
    autonomous_core = next(
        (row for row in acceptance_checks if isinstance(row, dict) and row.get("name") == "autonomous_product_core_contract"),
        {},
    )
    return {
        "base_dir": str(base_dir),
        "status": payload.get("status"),
        "ok": payload.get("ok"),
        "contract_ok": payload.get("contract_ok"),
        "acceptance_ready": payload.get("acceptance_ready"),
        "final_delivery_ready": payload.get("final_delivery_ready"),
        "readiness": payload.get("readiness"),
        "blockers": payload.get("blockers") or [],
        "next_actions": payload.get("next_actions") or [],
        "failed_checks": payload.get("failed_checks") or [],
        "acceptance_checks": acceptance_checks,
        "autonomous_product_core_contract": autonomous_core,
    }


def run_web_local_api_architecture_fixture() -> dict:
    web_ui = (ROOT_DIR / "tools" / "reachops_web_ui.py").read_text(encoding="utf-8")
    mac_self_check = (ROOT_DIR / "tools" / "reachops_mac_self_check.py").read_text(encoding="utf-8")
    live_acceptance_status = (ROOT_DIR / "tools" / "reachops_live_acceptance_status.py").read_text(encoding="utf-8")
    headless = (ROOT_DIR / "tools" / "run_reachops_headless_macos.py").read_text(encoding="utf-8")
    standalone = (ROOT_DIR / "ReachOps" / "workbench" / "standalone_app.py").read_text(encoding="utf-8")
    action_router = (ROOT_DIR / "ReachOps" / "workbench" / "action_router.py").read_text(encoding="utf-8")
    router = (ROOT_DIR / "ReachOps" / "intelligence" / "growth_task_router.py").read_text(encoding="utf-8")
    action_executor = (ROOT_DIR / "ReachOps" / "workbench" / "tiktok_action_executor.py").read_text(encoding="utf-8")
    browser_manager = (ROOT_DIR / "ReachOps" / "adapters" / "browser_manager.py").read_text(encoding="utf-8")
    live_readiness = (ROOT_DIR / "tools" / "reachops_live_readiness.py").read_text(encoding="utf-8")
    live_submit_acceptance = (ROOT_DIR / "tools" / "reachops_live_submit_acceptance.py").read_text(encoding="utf-8")
    client_acceptance = (ROOT_DIR / "tools" / "reachops_client_acceptance_status.py").read_text(encoding="utf-8")
    client_delivery_check = (ROOT_DIR / "tools" / "reachops_client_delivery_check.py").read_text(encoding="utf-8")
    delivery_package_check = (ROOT_DIR / "tools" / "reachops_delivery_package_check.py").read_text(encoding="utf-8")
    goal_delivery_runner = (ROOT_DIR / "tools" / "reachops_goal_delivery_runner.py").read_text(encoding="utf-8")
    final_acceptance_gate = (ROOT_DIR / "tools" / "reachops_final_acceptance_gate.py").read_text(encoding="utf-8")
    schemas = (ROOT_DIR / "ReachOps" / "intelligence" / "schemas.py").read_text(encoding="utf-8")
    error_diagnostics = (ROOT_DIR / "ReachOps" / "workbench" / "error_diagnostics.py").read_text(encoding="utf-8")
    app_entry = (ROOT_DIR / "ReachOpsApp.py").read_text(encoding="utf-8")
    launcher = (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8")
    local_client_command = (ROOT_DIR / "启动ReachOps本地客户端.command").read_text(encoding="utf-8")
    unified_web_command = (ROOT_DIR / "启动ReachOps统一WebUI.command").read_text(encoding="utf-8")
    native_mac_command = (ROOT_DIR / "启动ReachOps原生MacUI.command").read_text(encoding="utf-8")
    execution_plan = (ROOT_DIR / "ReachOps" / "execution_plan.py").read_text(encoding="utf-8")
    run_session = (ROOT_DIR / "ReachOps" / "run_session.py").read_text(encoding="utf-8")
    run_recovery = (ROOT_DIR / "ReachOps" / "run_recovery.py").read_text(encoding="utf-8")
    page_state_detector = (ROOT_DIR / "ReachOps" / "workbench" / "page_state_detector.py").read_text(encoding="utf-8")
    repair_policy_engine = (ROOT_DIR / "ReachOps" / "workbench" / "repair_policy_engine.py").read_text(encoding="utf-8")
    risk_gate = (ROOT_DIR / "ReachOps" / "workbench" / "risk_gate.py").read_text(encoding="utf-8")
    ai_console = (ROOT_DIR / "ReachOps" / "ai_console.py").read_text(encoding="utf-8")
    evidence_bundle = (ROOT_DIR / "ReachOps" / "evidence_bundle.py").read_text(encoding="utf-8")
    workflow_service = (ROOT_DIR / "ReachOps" / "workbench" / "workflow_service.py").read_text(encoding="utf-8")
    offline_learning = (ROOT_DIR / "ReachOps" / "workbench" / "offline_learning_ledger.py").read_text(encoding="utf-8")
    checks = {
        "web_api_start_endpoint": "\"/api/start\"" in web_ui and "postJson('/api/start'" in web_ui,
        "web_api_version_endpoint_identifies_current_ui": 'parsed.path == "/api/version"' in web_ui and "build_version_payload" in web_ui and "WEB_UI_VERSION" in web_ui and "CLIENT_DISPLAY_VERSION" in web_ui and "\"display_version\": CLIENT_DISPLAY_VERSION" in web_ui and "\"client_surface\": \"local_client_console\"" in web_ui and "\"display_name\": \"ReachOps Local Client Console\"" in web_ui and "\"loopback_host\": \"127.0.0.1\"" in web_ui and "ReachOps 本地客户端控制台" in web_ui and "127.0.0.1 控制台" in web_ui and "no_browser_started" in web_ui and "no_submit" in web_ui,
        "client_entrypoints_default_to_unified_web_console": "from ReachOps.launcher import main" in app_entry and "return _launch_legacy_tk_client()" in launcher and "return _launch_web_client()" in launcher and "web_requested = \"--web\" in args or os.environ.get(\"REACHOPS_WEB_CLIENT\") == \"1\"" in launcher and "Start the native Tk client" in launcher and "Start the unified Web console" in launcher and "ReachOps 本地客户端启动中" in local_client_command and "ReachOpsApp.py" in local_client_command and "tools/reachops_mac_self_check.py --start-web" in unified_web_command and "ReachOps 原生客户端 UI" in native_mac_command and "test_default_entry_starts_native_tk_client" in (ROOT_DIR / "tests" / "test_launcher.py").read_text(encoding="utf-8") and "test_web_client_requires_explicit_flag" in (ROOT_DIR / "tests" / "test_launcher.py").read_text(encoding="utf-8") and "test_missing_web_launcher_does_not_silently_fallback_to_legacy_tk" in (ROOT_DIR / "tests" / "test_launcher.py").read_text(encoding="utf-8"),
        "web_api_start_rejects_empty_target": "target_required" in web_ui and "status\": \"rejected\"" in web_ui,
        "web_api_rejects_invalid_json": "_read_json_payload" in web_ui and "invalid_json" in web_ui,
        "web_api_requires_json_object_payload": "json_object_required" in web_ui and "isinstance(payload, dict)" in web_ui,
        "web_api_rejects_invalid_content_length": "invalid_content_length" in web_ui and "length < 0" in web_ui,
        "web_api_rejects_oversized_payloads": "MAX_JSON_PAYLOAD_BYTES" in web_ui and "payload_too_large" in web_ui,
        "web_api_rejects_untrusted_hosts": "LOCAL_API_HOSTS" in web_ui and "untrusted_origin" in web_ui and "_reject_untrusted_api_request" in web_ui,
        "web_get_api_rejects_untrusted_hosts": "def do_GET" in web_ui and "parsed.path.startswith(\"/api/\") and self._reject_untrusted_api_request()" in web_ui,
        "web_get_api_unknown_returns_json_404": "unknown_api" in web_ui and "parsed.path.startswith(\"/api/\")" in web_ui,
        "web_post_api_unknown_returns_json_404": "parsed.path not in {\"/api/start\", \"/api/start-from-plan\"}" in web_ui and "unknown_api" in web_ui,
        "web_server_binds_loopback_only": "normalize_local_bind_host" in web_ui and "only supports local loopback hosts" in web_ui and "format_url_host" in web_ui,
        "web_api_reports_launch_failure": "launch_failed" in web_ui and "web_ui_launch_failed" in web_ui and "write_run_result_payload" in web_ui,
        "web_api_reports_immediate_headless_exit": "STARTUP_HEALTHCHECK_SECONDS" in web_ui and "headless_exited_immediately" in web_ui and "web_ui_headless_exited_immediately" in web_ui and "output_tail" in web_ui and "write_run_result_payload" in web_ui,
        "web_api_reports_result_file_open_failure": "result_file_open_failed" in web_ui and "web_ui_result_file_open_failed" in web_ui,
        "web_api_reports_download_failure": "download_failed" in web_ui and "web_ui_download_failed" in web_ui,
        "web_api_normalizes_mode_and_volume": "normalize_mode" in web_ui and "normalize_volume" in web_ui and "ALLOWED_MODES" in web_ui and "ALLOWED_VOLUMES" in web_ui,
        "web_api_clamps_profile_limit": "MAX_START_PROFILE_LIMIT" in web_ui and "normalize_profile_limit" in web_ui,
        "web_logs_extract_mixed_headless_json_result": "extract_last_json_object" in web_ui and "decoder.raw_decode" in web_ui and "return extract_last_json_object(text)" in web_ui,
        "web_logs_expose_structured_run_result": "read_run_result_payload" in web_ui and "run_result_status" in web_ui and "run_failed" in web_ui and "timeout_finalized" in web_ui and "FAILED" in web_ui,
        "web_api_serializes_concurrent_starts": "RUN_STATE_LOCK" in web_ui and "with RUN_STATE_LOCK:" in web_ui,
        "web_api_serializes_start_and_control": "RUN_STATE_LOCK" in web_ui and web_ui.count("with RUN_STATE_LOCK:") >= 2 and "parsed.path == \"/api/control\"" in web_ui,
        "web_api_requires_live_comment_confirmation": "live_comment_confirmation_required" in web_ui and "liveConfirm" in web_ui and "mode == \"live_comment\"" in web_ui,
        "web_start_preview_exposes_structured_preflight_decision": "reachops.start_preflight_decision.v1" in web_ui and "preflight_decision" in web_ui and "start_allowed" in web_ui and "profile_group_list_not_ready" in web_ui,
        "web_start_preview_exposes_autonomous_preflight_forecast": "attach_autonomous_preflight_forecast" in web_ui and "build_autonomous_preflight_forecast" in web_ui and "autonomous_preflight_forecast" in web_ui and "reachops.autonomous_preflight_forecast.v1" in execution_plan and "predicted_state_sequence" in execution_plan and "repair_routes" in execution_plan and "risk_gates" in execution_plan and "runtime_invariants" in execution_plan,
        "web_ui_renders_autonomous_preflight_forecast": "previewAutonomy" in web_ui and "previewAutonomyList" in web_ui and "状态链：" in web_ui and "自修复：" in web_ui and "证据要求：" in web_ui and "运行约束：0 token" in web_ui,
        "web_api_requires_live_comment_activation": "live_comment_activation_status" in web_ui and "LiveSubmitAuthorizationGate" in web_ui and "LIVE_SUBMIT_NOT_AUTHORIZED" in web_ui,
        "web_api_reports_already_running_pid": "already_running" in web_ui and "\"pid\": RUN_PROCESS.pid" in web_ui,
        "web_api_closes_parent_stdout_handle": "finally:" in web_ui and "out.close()" in web_ui and "RUN_PROCESS = process" in web_ui,
        "web_api_passes_runtime_dir_to_headless": "\"--base-dir\"" in web_ui and "str(DATA_DIR)" in web_ui,
        "execution_plan_schema_exists": "PLAN_SCHEMA_VERSION" in execution_plan and "EXECUTION_PLAN_JSON_SCHEMA" in execution_plan and "validate_execution_plan" in execution_plan and "limits_{key}_required" in execution_plan and "max_comments" in execution_plan and "authorization_live_confirmed_required" in execution_plan and "risk_policy_no_ai_token_required" in execution_plan and "UNKNOWN_PAGE_STATE" in execution_plan and "reachops.execution_plan_parameter_mapping.v1" in execution_plan and "runtime_contract" in execution_plan and "reachops.execution_runtime_contract.v1" in execution_plan and "\"executor\": \"local_program\"" in execution_plan and "\"control_surface\": \"local_client_console\"" in execution_plan and "\"ai_console_is_execution_dependency\": False" in execution_plan and "\"execution_phase_ai_calls_allowed\": False" in execution_plan and "runtime_contract_no_ai_token_required" in execution_plan and "runtime_contract_execution_ai_calls_disallowed_required" in execution_plan and "plan_fingerprint_sha256" in execution_plan and "plan_id_mismatch" in execution_plan and "build_execution_plan_runtime_contract" in execution_plan and "adversarial_cli_args_for_contract_preview" in execution_plan and "build_autonomous_preflight_forecast" in execution_plan and "attach_autonomous_preflight_forecast" in execution_plan,
        "web_api_builds_and_persists_execution_plan": "build_execution_plan" in web_ui and "write_execution_plan(execution_plan, plan_path)" in web_ui and "LATEST_EXECUTION_PLAN_PATH" in web_ui and "\"--execution-plan\"" in web_ui and "execution_plan_write_failed" in web_ui and "parsed.path == \"/api/start-from-plan\"" in web_ui and "parsed.path == \"/api/start-from-plan-preview\"" in web_ui and "parsed.path == \"/api/execution-plan-contract-preview\"" in web_ui and "build_start_from_plan_preview" in web_ui and "build_execution_plan_contract_preview" in web_ui and "execution_plan_replay" in web_ui,
        "web_api_exposes_latest_execution_plan_for_audit": "build_current_execution_plan_payload" in web_ui and "parsed.path == \"/api/execution-plan\"" in web_ui and "read_execution_plan" in web_ui and "\"本轮执行计划 JSON\"" in web_ui and "download_url" in web_ui and "下载执行计划" in web_ui and "reachops.execution_plan_contract_preview.v1" in web_ui and "uses_headless_runtime_mapper" in web_ui,
        "runtime_smoke_verifies_execution_plan_audit_endpoint": "execution_plan_endpoint_returns_latest_auditable_plan" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "execution_plan_contract_preview_uses_headless_mapper_without_side_effects" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "snapshot_exposes_execution_plan_report_artifact" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_from_plan_replays_latest_execution_plan" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_from_plan_preview_exposes_replay_contract" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_preview_exposes_autonomous_preflight_forecast" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "preview_authorization" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "preview_repair_policy" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "preview_risk_policy" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "preview_runtime_contract" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_authorization" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_repair_policy" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_risk_policy" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_runtime_contract" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "capture_error_bundle_then_block" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "require_human_authorization_for_live_actions" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.execution_runtime_contract.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "runtime_smoke_verifies_snapshot_evidence_bundle_contract": "snapshot_exposes_evidence_bundle_contract" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "product_capability_endpoint_returns_phase_matrix" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_console_explains_product_capability_matrix" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_group_precheck_block_writes_auditable_run_session" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_group_precheck_block_writes_page_state_sidecar" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_group_precheck_block_writes_repair_decision" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_group_precheck_block_writes_risk_gate" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "blocked_group_page_counts" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "blocking_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "UNKNOWN_PAGE_STATE" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "status\") != \"success\"" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "state\") != \"COMPLETED\"" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "本轮证据包 JSON" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.evidence_bundle.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.account_health_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.run_session_health.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.run_recovery_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.autonomous_execution_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "precheck_blocked" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "required_core_states" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "screenshot_unavailable_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "page_state_sidecar_artifact_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "refresh_profile_groups_and_reselect" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "profile_group_not_found" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "run_session_health_current" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "autonomous_state_machine_core_covered" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.autonomy_readiness_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.product_capability_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "phase_3_autonomous_execution" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.plan_runtime_contract_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.execution_runtime_contract_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_console_control_surface_only" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "execution_phase_ai_calls_disallowed" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "ai_usage_policy_matches_contract" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "cli_args_ignored_for_plan_fields" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "plan_fingerprint_matches" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "runtime_after_fingerprint_present" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "headless_reads_execution_plan_as_runtime_contract": "parser.add_argument(\"--execution-plan\"" in headless and "read_execution_plan(plan_path)" in headless and "apply_execution_plan_to_args(args, execution_plan, source=\"execution_plan\")" in headless and "cli_synthesized_execution_plan" in headless and "build_execution_plan(" in headless and "write_execution_plan(execution_plan, plan_path)" in headless and "write_execution_plan(execution_plan, plans_dir / \"latest_execution_plan.json\")" in headless and "build_execution_plan_runtime_contract" in headless and "reachops.execution_plan_runtime_contract.v1" in execution_plan and "cli_args_ignored_for_plan_fields" in execution_plan and "plan_fingerprint_sha256" in execution_plan and "runtime_after_fingerprint_sha256" in execution_plan and "\"execution_plan_contract\"" in headless and "Invalid ExecutionPlan" in execution_plan,
        "run_session_state_machine_exists": "RUN_SESSION_STATES" in run_session and "RUN_SESSION_STATE_ORDER" in run_session and "\"PRECHECK\"" in run_session and "\"PROFILE_OPENING\"" in run_session and "\"COLLECTING\"" in run_session and "\"SCORING\"" in run_session and "\"ACTION_PLANNING\"" in run_session and "\"EXECUTING\"" in run_session and "\"REPAIRING\"" in run_session and "\"DEGRADED\"" in run_session and "\"BLOCKED\"" in run_session and "state_history" in run_session and "no_ai_token_during_execution" in run_session and "execution_runtime_contract_from_plan" in run_session and "execution_runtime_contract" in run_session and "reachops.execution_runtime_contract.v1" in run_session and "create_run_session(" in headless and "write_run_session(session, run_session_path, run_session_latest_path)" in headless and "runs_dir / \"latest_run_session.json\"" in headless,
        "run_session_state_machine_transition_contract_exists": "RUN_SESSION_ALLOWED_TRANSITIONS" in run_session and "is_allowed_state_transition" in run_session and "normalize_state_machine_contract" in run_session and "reachops.run_session_state_machine_contract.v1" in run_session and "state_transition_violations" in run_session and "valid_transition" in run_session and "invalid_state_transition" in run_session,
        "run_session_records_control_history_without_tokens": "control_history" in run_session and "last_action" in run_session and "build_session_health" in run_session and "reachops.run_session_health.v1" in run_session and "no_ai_token_used" in run_session,
        "run_session_records_ai_usage_ledger": "AI_USAGE_LEDGER_SCHEMA_VERSION" in run_session and "build_ai_usage_ledger" in run_session and "normalize_ai_usage_ledger" in run_session and "\"execution_phase\"" in run_session and "\"token_estimate\"" in run_session and "execution_runtime_contract_schema" in run_session and "ai_console_is_execution_dependency" in run_session and "execution_phase_ai_calls_allowed" in run_session,
        "run_recovery_blocks_interrupted_sessions_without_tokens": "RUN_RECOVERY_SCHEMA_VERSION" in run_recovery and "recover_interrupted_run_session" in run_recovery and "process_interrupted" in run_recovery and "PROCESS_INTERRUPTED" in run_recovery and "no_ai_token_used" in run_recovery,
        "web_api_creates_and_exposes_run_session": "create_run_session" in web_ui and "LATEST_RUN_SESSION_PATH" in web_ui and "\"--run-session\"" in web_ui and "\"run_session\"" in web_ui and "infer_run_state" in web_ui and "persist_precheck_blocked_start" in web_ui and "web_ui_start_precheck_blocked" in web_ui,
        "web_api_exposes_latest_run_session_for_audit": "build_current_run_session_payload" in web_ui and "parsed.path == \"/api/run-session\"" in web_ui and "read_run_session" in web_ui and "\"本轮运行会话 JSON\"" in web_ui,
        "runtime_smoke_verifies_run_session_audit_endpoint": "run_session_endpoint_returns_latest_auditable_session" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "snapshot_exposes_run_session_report_artifact" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "run_session_checkpoint" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "run_session_health" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "run_session_history" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "control_pause_updates_run_session_without_tokens" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "control_resume_updates_run_session_without_tokens" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "WEB_UI_PAUSE_REQUESTED" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "WEB_UI_RESUME_REQUESTED" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "no_ai_token_used" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "runtime_smoke_verifies_state_machine_transition_contract": "reachops.run_session_state_machine_contract.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "valid_state_transitions" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "run_session_transitions_valid" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "state_transition_violation_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "web_logs_recover_interrupted_run_session": "recover_interrupted_run_session" in web_ui and "recover_current_run_session_if_interrupted" in web_ui and "run_session_recovered_interrupted" in web_ui and "\"recovery\"" in web_ui,
        "headless_updates_run_session_checkpoints": "parser.add_argument(\"--run-session\"" in headless and "update_run_session(\"PRECHECK\"" in headless and "update_run_session(\"PROFILE_PREFLIGHT\"" in headless and "update_runtime_checkpoint" in headless and "runtime_state_inferred" in headless and "log_line_count" in headless and "\"COMPLETED\" if result[\"status\"] == \"completed\" else \"BLOCKED\"" in headless and "execution_plan_contract" in run_session and "merged_evidence[\"execution_plan_contract\"]" in run_session,
        "page_state_detector_standardizes_browser_state": "PAGE_STATES" in page_state_detector and "\"READY\"" in page_state_detector and "\"LOGIN_REQUIRED\"" in page_state_detector and "\"CAPTCHA_DETECTED\"" in page_state_detector and "\"RATE_LIMITED\"" in page_state_detector and "\"PAGE_TIMEOUT\"" in page_state_detector and "\"DOM_STALLED\"" in page_state_detector and "\"MODAL_BLOCKED\"" in page_state_detector and "\"COMMENT_BOX_MISSING\"" in page_state_detector and "\"SUBMIT_BUTTON_MISSING\"" in page_state_detector and "\"UNKNOWN_PAGE_STATE\"" in page_state_detector and "dismissible_modal_visible" in page_state_detector and "close_candidates" in page_state_detector and "no_ai_token_used" in page_state_detector,
        "tiktok_executor_uses_page_state_detector": "PageStateDetector" in action_executor and "self.page_state_detector.detect" in action_executor and "\"page_state\"" in action_executor and "include_action_requirements" in action_executor,
        "tiktok_executor_detects_dom_stalled_from_previous_snapshot": "_page_state_history" in action_executor and "previous_snapshot=previous_snapshot" in action_executor and "state_key=state_key" in action_executor and "\"DOM_STALLED\"" in action_executor,
        "page_state_errors_enter_diagnostics": "DOM_STALLED" in schemas and "MODAL_BLOCKED" in schemas and "SUBMIT_BUTTON_MISSING" in schemas and "UNKNOWN_PAGE_STATE" in schemas and "DOM_STALLED" in error_diagnostics and "UNKNOWN_PAGE_STATE" in error_diagnostics,
        "repair_policy_engine_maps_known_failures": "RepairPolicyEngine" in repair_policy_engine and "cooldown_profile_and_switch" in repair_policy_engine and "retry_same_profile_with_backoff" in repair_policy_engine and "dismiss_modal" in repair_policy_engine and "degrade_to_collect" in repair_policy_engine and "capture_unknown_state_bundle" in repair_policy_engine and "refresh_profile_groups_and_reselect" in repair_policy_engine and "profile_group_not_found" in repair_policy_engine and "retry_after_seconds" in repair_policy_engine and "executable_steps" in repair_policy_engine and "repair_decision_id" in repair_policy_engine and "terminal_outcome" in repair_policy_engine and "no_ai_token_used" in repair_policy_engine and "blocked_group_repair_steps" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "terminal_block_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "block_execution" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "refresh_profile_groups" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "repair_policy_covers_all_page_states": "PAGE_STATE_REPAIR_COVERAGE_SCHEMA_VERSION" in repair_policy_engine and "build_page_state_repair_coverage" in repair_policy_engine and "all_page_states_covered" in repair_policy_engine and "continue_execution" in repair_policy_engine and "COMMENT_BOX_MISSING" in repair_policy_engine and "UNKNOWN_PAGE_STATE" in repair_policy_engine,
        "action_router_uses_repair_policy_engine": "RepairPolicyEngine" in action_router and "action_router_repair_decision" in action_router and "retry_same_profile" in action_router and "repair_decision" in action_router and "executable_steps" in action_router and "_execute_repair_steps" in action_router and "repair_step_results" in action_router and "requires_browser_executor" in action_router and "requires_human_review" in action_router,
        "risk_gate_unifies_account_authorization_and_quota": "RiskGate" in risk_gate and "block_precheck" in risk_gate and "PUBLISH_PROFILE_BLOCKED" in risk_gate and "HIGH_RISK_REVIEW_NOTE_REQUIRED" in risk_gate and "DAILY_QUOTA_EXCEEDED" in risk_gate and "DUPLICATE_ACTION_TEXT" in risk_gate and "profile_group_" in risk_gate and "rewrite_or_rotate_message" in risk_gate and "risk_actions" in risk_gate and "risk_decision_id" in risk_gate and "risk_category" in risk_gate and "terminal_outcome" in risk_gate and "block_execution" in risk_gate and "no_ai_token_used" in risk_gate,
        "action_router_uses_risk_gate_before_execution": "RiskGate" in action_router and "self.risk_gate.evaluate" in action_router and "\"risk_gate\"" in action_router and "live_submit_authorization_blocked" in action_router and "_duplicate_text_status" in action_router and "risk_gate_duplicate_text_blocked" in action_router,
        "web_operator_outreach_rows_explain_risk_gate": "risk_gate_json" in web_ui and "extract_risk_gate" in web_ui and "human_risk_gate_summary" in web_ui and "风险/失败原因" in web_ui and "风险门禁阻断" in web_ui and "风险门禁通过" in web_ui and "改写或轮换话术后重试" in web_ui and "等待人工授权后再执行" in web_ui,
        "runtime_smoke_verifies_operator_risk_gate_snapshot": "snapshot_outreach_view_explains_risk_gate_to_operator" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "seed_snapshot_risk_gate_execution" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "DUPLICATE_ACTION_TEXT" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "风险门禁阻断" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "local_ai_console_maps_text_to_execution_plan_without_tokens": "LocalAIConsole" in ai_console and "AI_CONSOLE_SCHEMA_VERSION" in ai_console and "build_execution_plan" in ai_console and "no_ai_token_used" in ai_console and "只采集" in ai_console and "为什么" in ai_console,
        "local_ai_console_explains_status_from_evidence_bundle": "def explain_status" in ai_console and "operator_summary" in ai_console and "page_state_summary" in ai_console and "risk_summary" in ai_console and "run_session_health" in ai_console and "run_recovery_summary" in ai_console and "会话健康" in ai_console and "运行控制记录" in ai_console and "中断恢复" in ai_console and "machine_actions" in ai_console and "timeline_summary" in ai_console and "时间线显示" in ai_console and "autonomous_preflight_reconciliation" in ai_console and "预判对账" in ai_console,
        "web_api_exposes_local_ai_console_without_browser_or_submit": "build_ai_console_payload" in web_ui and "parsed.path == \"/api/ai-console\"" in web_ui and "LocalAIConsole" in web_ui and "no_browser_started" in web_ui and "no_submit" in web_ui and "local_ai_console" in web_ui,
        "local_ai_console_recaps_evidence_bundle_without_tokens": "run_recap" in ai_console and "recap_run" in ai_console and "evidence_bundle" in ai_console and "复盘" in ai_console and "关键时间线" in ai_console and "timeline_summary" in ai_console and "no_ai_token_used" in ai_console and "run_recovery_summary" in ai_console and "中断恢复" in ai_console and "autonomous_preflight_reconciliation" in ai_console and "预判对账" in ai_console,
        "web_api_passes_evidence_bundle_to_ai_console": "runtime[\"evidence_bundle\"] = build_current_evidence_bundle()" in web_ui and "parsed.path == \"/api/ai-console\"" in web_ui and "\"reachops.evidence_bundle.v1\"" in web_ui,
        "runtime_smoke_verifies_ai_console_evidence_recap": "ai_console_recaps_evidence_bundle_without_tokens" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "复盘这次执行" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "preflight_reconciliation_schema" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "runtime_smoke_verifies_ai_console_operator_risk_gate_explanation": "ai_console_explains_operator_risk_gate_from_operations" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "operations_risk_gate_summary" in ai_console and "reachops.operations_risk_gate_summary.v1" in ai_console and "运营触达表显示" in ai_console and "runtime[\"operations\"] = runtime[\"acceptance\"].get(\"operations\")" in web_ui,
        "runtime_smoke_verifies_account_health_evidence_contract": "account_health_summary" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.account_health_summary.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "local_ai_console_analyzes_unknown_states_from_offline_learning": "unknown_state_analysis" in ai_console and "analyze_unknown_states" in ai_console and "offline_learning" in ai_console and "不会自动绕过 RiskGate" in ai_console,
        "web_api_passes_offline_learning_to_ai_console": "runtime[\"offline_learning\"] = build_offline_learning_payload()" in web_ui and "parsed.path == \"/api/ai-console\"" in web_ui and "\"reachops.offline_learning.v1\"" in web_ui,
        "runtime_smoke_verifies_ai_console_unknown_state_analysis": "ai_console_analyzes_offline_learning_without_tokens" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "分析未知错误" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "offline_learning" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "候选规则" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "web_ui_social_console_updates_plan_preview": "aiConsolePanel" in web_ui and "aiConsoleInput" in web_ui and "sendAiConsoleMessage" in web_ui and "applyAiPlanPatch" in web_ui and "renderAiConsoleResult" in web_ui and "postJson('/api/ai-console'" in web_ui and "本地规则 / 0 token" in web_ui and "aiConsoleMachineList" in web_ui and "machine_actions" in web_ui and "aiConsoleTimelineList" in web_ui and "timeline_summary" in web_ui and "关键时间线" in web_ui and "aiConsoleAnalyzeUnknown" in web_ui and "分析未知错误" in web_ui and "未知状态分析" in web_ui and "aiConsoleProductCapability" in web_ui and "产品能力矩阵现在做到哪了" in web_ui and "产品能力矩阵" in web_ui and "offlinePolicyReview" in web_ui and "approveOfflinePolicyCandidate" in web_ui and "rejectOfflinePolicyCandidate" in web_ui and "reviewOfflinePolicyCandidate" in web_ui and "postJson('/api/offline-learning/review'" in web_ui,
        "web_ui_hourglass_uses_runtime_evidence_not_decoration": "infoHourglass" in web_ui and "renderInfoHourglass" in web_ui and "page_state_summary" in web_ui and "repair_summary" in web_ui and "risk_summary" in web_ui and "account_health_summary" in web_ui and "run_recovery_summary" in web_ui and "中断恢复" in web_ui and "autonomous_preflight_reconciliation" in web_ui and "预判对账" in web_ui and "autonomy_readiness_summary" in web_ui and "product_capability_summary" in web_ui and "run_session_state" in web_ui and "页面状态阻断" in web_ui and "风险门禁阻断" in web_ui and "账号健康" in web_ui and "自治链路" in web_ui and "产品闭环" in web_ui and "产品能力闭环未完成" in web_ui and "自治链路未就绪" in web_ui and "hourglass_particles_are_bound_to_runtime_evidence" in (ROOT_DIR / "tools" / "reachops_web_panel_dom_smoke.py").read_text(encoding="utf-8") and "title=\\\"页面状态：2\\\"" in (ROOT_DIR / "tools" / "reachops_web_panel_dom_smoke.py").read_text(encoding="utf-8") and "title=\\\"风险动作：2\\\"" in (ROOT_DIR / "tools" / "reachops_web_panel_dom_smoke.py").read_text(encoding="utf-8") and "title=\\\"交付边界：3\\\"" in (ROOT_DIR / "tools" / "reachops_web_panel_dom_smoke.py").read_text(encoding="utf-8"),
        "evidence_bundle_indexes_plan_session_result_log_and_timeline": "EVIDENCE_BUNDLE_SCHEMA_VERSION" in evidence_bundle and "build_evidence_bundle" in evidence_bundle and "collect_evidence_artifacts" in evidence_bundle and "collect_page_state_artifacts" in evidence_bundle and "page_state_screenshot" in evidence_bundle and "page_state_sidecar" in evidence_bundle and "build_timeline" in evidence_bundle and "run_session.checkpoint" in evidence_bundle and "run_session.state_history" in evidence_bundle and "run_session_health" in evidence_bundle and "Run Session Health" in evidence_bundle and "build_run_recovery_summary" in evidence_bundle and "reachops.run_recovery_summary.v1" in evidence_bundle and "Run Recovery Summary" in evidence_bundle and "build_autonomous_execution_summary" in evidence_bundle and "reachops.autonomous_execution_summary.v1" in evidence_bundle and "Autonomous Execution Summary" in evidence_bundle and "autonomous_state_machine_core_covered" in evidence_bundle and "precheck_blocked" in evidence_bundle and "required_core_states" in evidence_bundle and "PROFILE_GROUP_PRECHECK_BLOCKED" in evidence_bundle and "\"RISK_GATE\"" in evidence_bundle and "\"PAGE_STATE\"" in evidence_bundle and "runtime_state_inferred" in evidence_bundle and "render_evidence_markdown" in evidence_bundle and "no_ai_token_during_execution" in evidence_bundle and "build_plan_runtime_contract_summary" in evidence_bundle and "reachops.plan_runtime_contract_summary.v1" in evidence_bundle and "plan_fingerprint_matches" in evidence_bundle and "runtime_after_fingerprint_present" in evidence_bundle and "execution_plan_audit_preview" in evidence_bundle and "audit_preview" in evidence_bundle and "ExecutionPlan Runtime Contract" in evidence_bundle and "build_execution_runtime_contract_summary" in evidence_bundle and "reachops.execution_runtime_contract_summary.v1" in evidence_bundle and "execution_runtime_contract_ai_usage_policy_matches" in evidence_bundle and "Execution Runtime Contract" in evidence_bundle and "build_autonomous_preflight_forecast_summary" in evidence_bundle and "reachops.autonomous_preflight_forecast_summary.v1" in evidence_bundle and "Autonomous Preflight Forecast" in evidence_bundle and "build_autonomous_preflight_reconciliation" in evidence_bundle and "reachops.autonomous_preflight_reconciliation.v1" in evidence_bundle and "Autonomous Preflight Reconciliation" in evidence_bundle,
        "evidence_bundle_indexes_page_state_repair_coverage": "build_page_state_repair_coverage" in evidence_bundle and "page_state_repair_coverage" in evidence_bundle and "reachops.page_state_repair_coverage.v1" in evidence_bundle and "page_state_repair_policy_covered" in evidence_bundle and "page_state_repair_all_covered" in evidence_bundle and "Page State Repair Coverage" in evidence_bundle,
        "evidence_bundle_summarizes_state_machine_transition_contract": "reachops.run_session_state_machine_contract.v1" in evidence_bundle and "valid_state_transitions" in evidence_bundle and "state_transition_violation_count" in evidence_bundle and "run_session_transitions_valid" in evidence_bundle and "autonomous_valid_state_transitions" in evidence_bundle and "Valid state transitions" in evidence_bundle,
        "evidence_bundle_builds_operator_report_homepage": "build_operator_summary" in evidence_bundle and "build_autonomy_readiness_summary" in evidence_bundle and "build_product_capability_summary" in evidence_bundle and "build_product_development_goals" in evidence_bundle and "reachops.operator_summary.v1" in evidence_bundle and "reachops.autonomy_readiness_summary.v1" in evidence_bundle and "reachops.product_capability_summary.v1" in evidence_bundle and "reachops.product_development_goals.v1" in evidence_bundle and "run_session_health_current" in evidence_bundle and "phase_3_autonomous_execution" in evidence_bundle and "Operator Summary" in evidence_bundle and "Autonomy Readiness Summary" in evidence_bundle and "Product Capability Summary" in evidence_bundle and "Product Development Goals" in evidence_bundle and "primary_blocker" in evidence_bundle,
        "web_api_exposes_operator_summary_report_homepage": "build_operator_summary_payload" in web_ui and "build_product_capability_payload" in web_ui and "parsed.path == \"/api/operator-summary\"" in web_ui and "parsed.path == \"/api/product-capability\"" in web_ui and "\"operator_summary\"" in web_ui and "\"product_capability_summary\"" in web_ui and "\"product_development_goals\"" in web_ui and "\"autonomous_execution_summary\"" in web_ui and "evidence_bundle_markdown_download_url" in web_ui,
        "web_ai_console_wraps_all_intents_with_client_delivery_summary": "def build_ai_console_payload" in web_ui and "result.setdefault(\"client_delivery\", client_delivery)" in web_ui and "result.setdefault(\n            \"client_delivery_summary\"" in web_ui and "\"no_browser_started\": bool(client_delivery.get(\"no_browser_started\", True))" in web_ui and "\"no_submit\": bool(client_delivery.get(\"no_submit\", True))" in web_ui,
        "web_snapshot_exposes_unified_operations_payload": "def build_snapshot_payload" in web_ui and "acceptance_payload = build_acceptance_payload()" in web_ui and "payload[\"operations\"] = acceptance_payload.get(\"operations\")" in web_ui and "payload[\"latest_batch\"] = acceptance_payload.get(\"latest_batch\")" in web_ui,
        "web_api_product_capability_exposes_top_level_delivery_boundary": "\"delivery_boundary_status\"" in web_ui and "\"local_product_capability_ready\"" in web_ui and "\"product_capability_ready\"" in web_ui and "\"product_development_ready\"" in web_ui and "\"windows_final_artifacts_pending\"" in web_ui and "\"pending_scopes\"" in web_ui and "product_capability.get(\"delivery_boundary_status\") == product_boundary.get(\"status\")" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "product_capability.get(\"local_product_capability_ready\")" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "product_capability.get(\"windows_final_artifacts_pending\") is True" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "local_ai_console_uses_operator_summary_in_recap": "operator_summary" in ai_console and "autonomy_readiness_summary" in ai_console and "product_capability_summary" in ai_console and "product_development_goals" in ai_console and "product_capability_status" in ai_console and "explain_product_capability" in ai_console and "自治链路" in ai_console and "产品能力矩阵" in ai_console and "当前开发目标" in ai_console and "运营摘要" in ai_console and "primary_blocker" in ai_console and "client_delivery_next_actions" in ai_console and "客户端门禁下一步" in ai_console and "\"client_delivery\"" in ai_console and "\"client_delivery_summary\"" in ai_console,
        "evidence_bundle_summarizes_repair_attempts": "build_repair_summary" in evidence_bundle and "reachops.repair_summary.v1" in evidence_bundle and "repair_decision_count" in evidence_bundle and "Repair Summary" in evidence_bundle and "Repair Machine Actions" in evidence_bundle and "executable_steps" in evidence_bundle and "repair_step_result_count" in evidence_bundle and "terminal_outcome_counts" in evidence_bundle and "terminal_retry_count" in evidence_bundle and "Repair steps executed locally" in evidence_bundle,
        "local_ai_console_explains_repair_summary_in_recap": "repair_summary" in ai_console and "自修复记录" in ai_console and "run_recap" in ai_console and "executable_steps" in ai_console and "自修复最终处置" in ai_console,
        "evidence_bundle_summarizes_risk_gate_decisions": "build_risk_summary" in evidence_bundle and "build_risk_policy_summary" in evidence_bundle and "reachops.risk_summary.v1" in evidence_bundle and "reachops.risk_policy_summary.v1" in evidence_bundle and "risk_gate_decision_count" in evidence_bundle and "risk_action_count" in evidence_bundle and "risk_category_counts" in evidence_bundle and "terminal_outcome_counts" in evidence_bundle and "duplicate_text_block_count" in evidence_bundle and "Risk Summary" in evidence_bundle and "Risk Policy Summary" in evidence_bundle and "Risk Gate Machine Actions" in evidence_bundle and "risk_actions" in evidence_bundle,
        "evidence_bundle_renders_operator_risk_gate_summary": "build_operator_risk_gate_summary" in evidence_bundle and "reachops.operator_risk_gate_summary.v1" in evidence_bundle and "operator_risk_gate_blocked_count" in evidence_bundle and "Operator Risk Gate Summary" in evidence_bundle and "Primary next step" in evidence_bundle and "改写或轮换话术后重试" in evidence_bundle and "operator_risk_gate_summary" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "start_group_precheck_block_writes_risk_gate" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "campaign_export_includes_operator_risk_gate_fields": "_enrich_exported_execution" in workflow_service and "risk_gate_reason_code" in workflow_service and "risk_gate_summary" in workflow_service and "risk_gate_next_step" in workflow_service and "改写或轮换话术后重试" in workflow_service,
        "local_ai_console_explains_risk_summary_in_recap": "risk_summary" in ai_console and "risk_policy_summary" in ai_console and "operator_risk_gate_summary" in ai_console and "证据包运营风险门禁" in ai_console and "运营风险门禁" in ai_console and "风险门禁" in ai_console and "风险策略" in ai_console and "风险分类" in ai_console and "风险最终处置" in ai_console and "重复话术" in ai_console and "authorization_block_count" in ai_console and "risk_actions" in ai_console and "risk_action_count" in ai_console,
        "evidence_bundle_summarizes_account_health_cooldowns": "build_account_health_summary" in evidence_bundle and "reachops.account_health_summary.v1" in evidence_bundle and "\"ACCOUNT_HEALTH\"" in evidence_bundle and "profile_forced_cooldown" in evidence_bundle and "Account Health Summary" in evidence_bundle,
        "evidence_bundle_indexes_account_repair_plan": "build_account_repair_summary" in evidence_bundle and "reachops.account_repair_summary.v1" in evidence_bundle and "account_repair_plan" in evidence_bundle and "account_repair_apply" in evidence_bundle and "Account Repair Summary" in evidence_bundle and "pending_recheck" in evidence_bundle and "account_repair_safety_contract" in (ROOT_DIR / "tools" / "reachops_apply_account_repair_plan.py").read_text(encoding="utf-8") and "reachops.account_repair_post_apply_verification.v1" in (ROOT_DIR / "tools" / "reachops_apply_account_repair_plan.py").read_text(encoding="utf-8") and "apply_alone_is_not_acceptance" in (ROOT_DIR / "tools" / "reachops_apply_account_repair_plan.py").read_text(encoding="utf-8") and "manual_apply_required" in evidence_bundle and "hard_blocker_only" in evidence_bundle and "account_repair_no_submit" in evidence_bundle,
        "evidence_bundle_indexes_account_support_handoff": "build_account_support_handoff_summary" in evidence_bundle and "reachops.account_support_handoff_summary.v1" in evidence_bundle and "account_support_handoff_summary" in evidence_bundle and "Account Support Handoff" in evidence_bundle and "does_not_claim_real_account_pool_ready" in evidence_bundle and "blocker_codes" in evidence_bundle and "retest_checklist" in evidence_bundle and "Retest command" in evidence_bundle,
        "local_ai_console_explains_account_health_timeline": "\"ACCOUNT_HEALTH\"" in ai_console and "账号已进入冷却" in ai_console and "profile_id" in ai_console,
        "local_ai_console_explains_account_repair_recheck": "account_repair_summary" in ai_console and "账号修复" in ai_console and "重新预检" in ai_console and "hard_blocker_profile_count" in ai_console and "账号修复安全边界" in ai_console and "manual_apply_required" in ai_console and "hard_blocker_only" in ai_console and "no_browser_started" in ai_console and "no_submit" in ai_console,
        "action_router_attaches_account_health_to_results": "\"account_health\"" in action_router and "record_failure(profile" in action_router and "record_success(profile)" in action_router,
        "evidence_bundle_summarizes_page_states": "build_page_state_summary" in evidence_bundle and "reachops.page_state_summary.v1" in evidence_bundle and "page_state_snapshot_count" in evidence_bundle and "page_state_artifact_count" in evidence_bundle and "page_state_evidence_audited" in evidence_bundle and "screenshot_unavailable_count" in evidence_bundle and "Page State Summary" in evidence_bundle and "Page State Counts" in evidence_bundle,
        "local_ai_console_explains_page_state_summary_in_recap": "page_state_summary" in ai_console and "页面状态" in ai_console and "unknown_count" in ai_console,
        "evidence_bundle_summarizes_run_controls": "build_control_summary" in evidence_bundle and "reachops.control_summary.v1" in evidence_bundle and "control_event_count" in evidence_bundle and "current_paused" in evidence_bundle and "Control Summary" in evidence_bundle,
        "local_ai_console_explains_control_summary_in_recap": "control_summary" in ai_console and "运行控制" in ai_console and "stop_count" in ai_console,
        "evidence_bundle_summarizes_ai_usage_ledger": "build_ai_usage_summary" in evidence_bundle and "reachops.ai_usage_summary.v1" in evidence_bundle and "execution_phase_ai_call_count" in evidence_bundle and "AI Usage Summary" in evidence_bundle,
        "local_ai_console_explains_ai_usage_summary_in_recap": "ai_usage_summary" in ai_console and "执行期 AI 调用" in ai_console and "execution_phase_token_estimate" in ai_console,
        "web_api_exposes_ai_usage_audit": "ai_usage_ledger" in web_ui and "ai_usage_summary" in web_ui and "no_ai_token_used" in web_ui and "build_current_run_session_payload" in web_ui,
        "headless_writes_evidence_bundle_on_terminal_result": "attach_evidence_bundle" in headless and "finalize_with_evidence_bundle" in headless and "build_evidence_bundle" in headless and "write_evidence_bundle" in headless and "write_evidence_markdown" in headless and "\"evidence_bundle\"" in headless and "\"run_results\"" in headless and "result_path=str(result_artifact_path)" in headless,
        "web_api_exposes_evidence_bundle_and_report_artifacts": "build_current_evidence_bundle" in web_ui and "parsed.path == \"/api/evidence-bundle\"" in web_ui and "\"evidence_bundle\"" in web_ui and "本轮证据包 JSON" in web_ui and "latest_evidence_bundle.md" in web_ui,
        "offline_learning_records_unknown_states_without_tokens": "OFFLINE_LEARNING_SCHEMA_VERSION" in offline_learning and "OfflineLearningLedger" in offline_learning and "record_unknown_state" in offline_learning and "state_signature" in offline_learning and "suggested_policy" in offline_learning and "no_ai_token_used" in offline_learning,
        "offline_learning_promotes_repeated_unknowns_to_review_candidates": "OFFLINE_POLICY_CANDIDATES_SCHEMA_VERSION" in offline_learning and "build_policy_candidates_from_records" in offline_learning and "requires_human_review" in offline_learning and "auto_apply" in offline_learning,
        "offline_learning_records_human_policy_reviews_without_auto_apply": "OFFLINE_POLICY_REVIEW_SCHEMA_VERSION" in offline_learning and "review_policy_candidate" in offline_learning and "policy_review_summary" in offline_learning and "runtime_effect" in offline_learning and "review_recorded_only" in offline_learning and "\"runtime_auto_apply_count\": 0" in offline_learning,
        "offline_learning_builds_release_proposal_without_runtime_apply": "OFFLINE_POLICY_RELEASE_PROPOSAL_SCHEMA_VERSION" in offline_learning and "build_policy_release_proposal" in offline_learning and "release_target_components" in offline_learning and "code_or_policy_release_required" in offline_learning and "release_proposal_only" in offline_learning and "\"runtime_auto_apply\": False" in offline_learning,
        "executor_and_router_attach_offline_learning_to_unknown_failures": "OfflineLearningLedger" in action_executor and "RepairPolicyEngine" in action_executor and "\"offline_learning\"" in action_executor and "\"repair_decision\"" in action_executor and "record_unknown_state" in action_executor and "repair_policy_engine.decide" in action_executor and "OfflineLearningLedger" in action_router and "\"offline_learning\"" in action_router and "record_unknown_state" in action_router,
        "web_api_exposes_offline_learning_read_only": "build_offline_learning_payload" in web_ui and "parsed.path == \"/api/offline-learning\"" in web_ui and "summarize_offline_learning" in web_ui and "policy_candidates" in web_ui and "policy_review_summary" in web_ui and "policy_release_proposal" in web_ui and "no_browser_started" in web_ui and "no_submit" in web_ui,
        "web_api_records_offline_policy_reviews_locally": "review_offline_policy_candidate" in web_ui and "parsed.path == \"/api/offline-learning/review\"" in web_ui and "review_policy_candidate" in web_ui and "invalid_policy_review" in web_ui and "no_browser_started" in web_ui and "no_submit" in web_ui,
        "runtime_smoke_verifies_offline_policy_review_api": "offline_learning_review_records_human_decision_without_runtime_apply" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "/api/offline-learning/review" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "review_recorded_only" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "offline_policy_runtime_auto_apply_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "offline_policy_release_ready_count" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "reachops.offline_policy_release_proposal.v1" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8") and "runtime_auto_apply_count\") == 0" in (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8"),
        "evidence_bundle_indexes_offline_policy_candidates": "offline_policy_candidate_count" in evidence_bundle and "offline_policy_review_count" in evidence_bundle and "offline_policy_approved_count" in evidence_bundle and "offline_policy_runtime_auto_apply_count" in evidence_bundle and "offline_policy_release_ready_count" in evidence_bundle and "offline_policy_release_runtime_auto_apply_count" in evidence_bundle and "offline_learning_artifact_count" in evidence_bundle and "offline_learning_evidence" in evidence_bundle and "Offline Policy Candidates" in evidence_bundle and "policy_release_proposal" in evidence_bundle and "Release runtime auto apply" in evidence_bundle,
        "local_ai_console_explains_offline_policy_candidates": "policy_candidates" in ai_console and "policy_review_summary" in ai_console and "policy_release_proposal" in ai_console and "runtime_auto_apply=0" in ai_console and "策略发布建议" in ai_console and "evidence_path_count" in ai_console and "可核对证据文件" in ai_console and "候选规则" in ai_console and "不会自动绕过 RiskGate" in ai_console,
        "web_groups_endpoint_refreshes_profile_registry": "parsed.path == \"/api/groups\"" in web_ui and "load_groups(refresh=refresh, allow_async=\"background=1\" in parsed.query)" in web_ui and "append_group_refresh_log(payload, refresh=refresh)" in web_ui and "refresh_groups source=web_ui" in web_ui and "include_profiles=False" in web_ui and "StandaloneProfileRegistry().refresh" in web_ui and "resolve_ixbrowser_group_counts" in web_ui,
        "web_groups_endpoint_has_ixbrowser_timeout": "GROUP_REFRESH_TIMEOUT_SECONDS" in web_ui and "GROUP_COUNT_RESOLVE_TIMEOUT_SECONDS" in web_ui and "future.result(timeout=GROUP_REFRESH_TIMEOUT_SECONDS)" in web_ui and "profile_group_list_timeout_after_" in web_ui and "executor.shutdown(wait=False, cancel_futures=True)" in web_ui,
        "web_ixbrowser_status_visible_to_operator": "parsed.path == \"/api/ixbrowser-status\"" in web_ui and "build_ixbrowser_status_payload" in web_ui and "ixbrowserApiState" in web_ui and "ixbrowserStatusActions" in web_ui and "refreshIxBrowserStatus" in web_ui and "no_browser_started" in web_ui and "no_submit" in web_ui and "ixbrowser_status_next_actions" in web_ui and "开启 Local API" in web_ui,
        "web_ixbrowser_port_configurable_by_operator": "parsed.path == \"/api/ixbrowser-config\"" in web_ui and "apply_ixbrowser_api_port" in web_ui and "applyIxBrowserPort" in web_ui and "ixbrowserApiPort" in web_ui and "REACHOPS_IXBROWSER_API_PORT" in web_ui and "GROUP_CACHE" in web_ui and "reachops_web_settings.json" in web_ui and "initialize_ixbrowser_api_port_from_settings" in web_ui,
        "web_group_refresh_controls_populate_config_list": "async function refreshGroups(force = true)" in web_ui and "fetch(force ? '/api/groups?refresh=1' : '/api/groups')" in web_ui and "groups.map(g => `<option value=\"" in web_ui and "$('refreshGroups').onclick = refreshGroups" in web_ui and "selectedGroupBar" in web_ui and "selectedGroupCount" in web_ui,
        "web_selected_group_drives_start_payload": "group:$('group').value" in web_ui and "\"--profile-group\"" in web_ui and "profile_group = str(payload.get(\"group\") or \"United States\")" in web_ui,
        "web_start_requires_group_from_ixbrowser_config_list": "validate_profile_group_for_start(profile_group)" in web_ui and "profile_group_not_found" in web_ui and "profile_group_list_unavailable" in web_ui and "web_ui_start_rejected_profile_group" in web_ui,
        "web_ui_disables_start_until_ixbrowser_group_list_ready": 'id="start" disabled' in web_ui and "let groupListReady = false" in web_ui and "$('start').disabled = !groupListReady" in web_ui and "未读取到 ixBrowser 配置分组；不可启动" in web_ui and "保留 United States 默认执行" not in web_ui,
        "web_ui_toolbar_and_metrics_are_responsive": "controlPanel" in web_ui and "taskForm" in web_ui and "taskParams" in web_ui and "taskActions" in web_ui and "grid-template-columns:repeat(auto-fit,minmax(176px,1fr))" in web_ui and "grid-template-columns:minmax(180px,1fr)" in web_ui and "grid-template-columns:repeat(auto-fit,minmax(106px,1fr))" in web_ui and "grid-template-columns:repeat(auto-fit,minmax(92px,1fr))" in web_ui and "grid-template-columns:repeat(auto-fit,minmax(112px,1fr))" in web_ui,
        "web_ui_refresh_failures_are_operator_visible": "本地服务连接失败" in web_ui and "$('runState').textContent = 'OFFLINE'" in web_ui and "$('acceptanceState').textContent = '验收状态：本地服务连接失败'" in web_ui and "读取失败：本地服务连接失败" in web_ui,
        "web_api_passes_live_comment_mode_to_headless": "\"--mode\"" in web_ui and "mode" in web_ui and "\"live_comment\"" in web_ui and "liveConfirm" in web_ui,
        "web_api_control_rejects_unknown_actions": "unknown_action" in web_ui and '"status": "rejected"' in web_ui,
        "web_api_control_handles_signal_os_errors": "except OSError" in web_ui and '"status": "paused" if ok else "failed"' in web_ui,
        "web_api_control_handles_cross_platform_pause_resume": "cooperative_control" in web_ui and "pause.request" in web_ui and "resume.request" in web_ui and "PAUSE_SIGNAL" in web_ui and "RESUME_SIGNAL" in web_ui and "WEB_UI_COOPERATIVE_PAUSE_REQUESTED" in web_ui and "WEB_UI_COOPERATIVE_RESUME_REQUESTED" in web_ui and "parser.add_argument(\"--control-dir\"" in headless and "wait_if_cooperatively_paused" in headless and "cooperative_pause_waiting" in headless,
        "web_api_stop_keeps_state_on_signal_failure": "web_ui_stop_signal_failed" in web_ui and '"running": True' in web_ui,
        "web_api_stop_keeps_state_when_process_survives": "web_ui_stop_process_still_running" in web_ui and "RUN_PROCESS.poll() is None" in web_ui,
        "web_api_controls_runtime": "parsed.path == \"/api/control\"" in web_ui and "SIGSTOP" in web_ui and "SIGCONT" in web_ui,
        "web_ui_controls_are_real_api_bound": all(
            token in web_ui
            for token in [
                "postJson('/api/start'",
                "getJson('/api/start-from-plan-preview')",
                "postJson('/api/start-from-plan'",
                "postJson('/api/control'",
                "fetch('/api/logs')",
                "fetch('/api/snapshot')",
                "fetch('/api/acceptance')",
                "fetch('/api/final-status')",
                "fetch(force ? '/api/groups?refresh=1' : '/api/groups')",
                "async function postJson(url, payload)",
                "async function refreshFinalStatus()",
                "function showApiNotice",
                "function apiNoticeActive()",
                "apiNoticeUntil = Date.now() + Math.max",
                "liveConfirm:$('liveConfirm').checked",
                "live_comment_confirmation_required",
                "showApiNotice('启动被系统拦截'",
                "showApiNotice(`控制未执行：${{action}}`",
                "$('start').onclick = start",
                "$('previewPlanReplay').onclick = previewPlanReplay",
                "$('startFromPlan').onclick = startFromPlan",
                "$('downloadExecutionPlan').onclick = downloadExecutionPlan",
                "getJson('/api/execution-plan')",
                "执行计划已准备下载",
                "$('pause').onclick = () => control('pause')",
                "$('resume').onclick = () => control('resume')",
                "$('stop').onclick = () => control('stop')",
            ]
        ),
        "web_acceptance_exposes_client_gate": "\"client_delivery\"" in web_ui and "final_delivery_ready" in web_ui and "failed_checks" in web_ui,
        "web_goal_delivery_visible_to_operator": "\"goal_delivery\"" in web_ui and "refreshGoalDelivery" in web_ui and "parsed.path == \"/api/goal-delivery-refresh\"" in web_ui and "reachops_goal_delivery_runner.py --json" in web_ui and "目标模式总报告" in web_ui,
        "web_acceptance_persists_client_gate": "write_delivery_check(client_delivery)" in web_ui and "latest_delivery_check.json" in (ROOT_DIR / "tools" / "reachops_client_delivery_check.py").read_text(encoding="utf-8"),
        "client_gate_rejects_stale_profile_preflight": "profile_preflight_is_stale" in client_acceptance and "profile_preflight_fresh" in client_acceptance and "不能复用旧账号可用性" in client_acceptance,
        "client_gate_requires_selected_group_profile_list_evidence": "profile_candidates_loaded_from_selected_group" in client_acceptance and "account_queue_started_for_selected_group" in client_acceptance and "profile_list_execution_evidence" in client_acceptance and "不能证明配置列表参与本次采集" in client_acceptance,
        "client_gate_embeds_readonly_ixbrowser_metadata": "collect_ixbrowser_metadata" in client_delivery_check
        and "reachops_ixbrowser_profile_metadata_report.py" in client_delivery_check
        and '"ixbrowser_metadata"' in client_delivery_check
        and "open_profile_called" in client_delivery_check
        and "--collect-live-metadata" in client_delivery_check
        and "collect_metadata=bool(args.collect_live_metadata)" in client_delivery_check,
        "client_gate_exposes_account_support_handoff": "build_account_support_handoff" in client_delivery_check
        and "reachops.account_support_handoff.v1" in client_delivery_check
        and "write_account_support_handoff_diagnostic" in client_delivery_check
        and "reachops.account_support_handoff_diagnostic.v1" in client_delivery_check
        and "reports\" / \"support\" / \"account_support_handoff.json" in client_delivery_check
        and '"account_support_handoff"' in client_delivery_check
        and "retest_commands" in client_delivery_check
        and "retest_checklist" in client_delivery_check
        and "apply_alone_is_not_acceptance" in client_delivery_check
        and "blocker_codes" in client_delivery_check
        and "does_not_claim_real_account_pool_ready" in client_delivery_check,
        "goal_delivery_surfaces_account_support_handoff_blocker": "build_local_mvp_blocker" in goal_delivery_runner
        and "reachops.local_mvp_account_pool_blocker.v1" in goal_delivery_runner
        and "account_pool_external_validation" in goal_delivery_runner
        and "account_support_handoff" in goal_delivery_runner
        and "account_support_handoff_path" in goal_delivery_runner
        and '"local_mvp_acceptance"' in goal_delivery_runner
        and "本地 MVP 账号支持交接" in goal_delivery_runner
        and "下一步复验命令" in goal_delivery_runner
        and "本地MVP账号交接" in web_ui
        and "本地MVP账号复验命令" in web_ui
        and "does_not_claim_local_mvp_ready" in goal_delivery_runner
        and "does_not_claim_real_account_pool_ready" in goal_delivery_runner,
        "delivery_package_writes_windows_acceptance_handoff": "build_windows_acceptance_handoff" in delivery_package_check
        and "reachops.windows_acceptance_handoff.v1" in delivery_package_check
        and "windows_acceptance_handoff_path" in delivery_package_check
        and "reports\" / \"support\" / \"windows_acceptance_handoff.json" in delivery_package_check
        and "does_not_create_acceptance_summary" in delivery_package_check
        and "requires_windows_real_acceptance" in delivery_package_check,
        "final_gate_indexes_windows_acceptance_handoff": "_windows_acceptance_handoff_summary" in final_acceptance_gate
        and '"windows_acceptance_handoff"' in final_acceptance_gate
        and '"windows_acceptance_handoff_path"' in final_acceptance_gate
        and "does_not_claim_final_delivery_ready" in final_acceptance_gate
        and "requires_windows_real_acceptance" in final_acceptance_gate,
        "goal_delivery_indexes_windows_acceptance_handoff": "windows_acceptance_handoff_summary" in goal_delivery_runner
        and "with_windows_acceptance_handoff" in goal_delivery_runner
        and '"windows_acceptance_handoff"' in goal_delivery_runner
        and '"windows_acceptance_handoff_path"' in goal_delivery_runner
        and "does_not_claim_final_delivery_ready" in goal_delivery_runner,
        "client_gate_human_output_has_repair_loop": "account_repair_summary_lines" in client_delivery_check and "action=" in client_delivery_check and "after_repair_acceptance=" in client_delivery_check and "account_repair_safety=" in client_delivery_check and "no_submit" in client_delivery_check and "after_repair_commands=" in client_delivery_check and "account_repair_summary" in client_delivery_check,
        "web_activation_status_visible_to_operator": "parsed.path == \"/api/activation\"" in web_ui and "build_activation_payload" in web_ui and "activationState" in web_ui and "refreshActivation" in web_ui,
        "web_final_status_visible_to_operator": "parsed.path == \"/api/final-status\"" in web_ui and "build_final_status_payload" in web_ui and "finalStatusState" in web_ui and "finalStatusActions" in web_ui and "finalStatusCommands" in web_ui and "next_required_actions" in web_ui and "verification_commands" in web_ui and "refreshFinalStatus" in web_ui,
        "web_final_status_uses_operator_default_group": "profile_group=\"United States\"" in web_ui and "profile_group=\"BR\"" not in web_ui,
        "web_operator_copy_has_no_test_comment_prompt": "测试可填 Hi" not in web_ui and "测试评论动作" not in web_ui and "已审核话术" in web_ui,
        "web_acceptance_input_template_available": "parsed.path == \"/api/acceptance-input-template\"" in web_ui and "reachops_acceptance_inputs.example.ps1" in web_ui and "本地验收输入模板" in web_ui,
        "web_acceptance_input_init_available": "parsed.path == \"/api/acceptance-input-init\"" in web_ui and "init_acceptance_input_file" in web_ui and "initAcceptanceInputs" in web_ui,
        "live_acceptance_status_exposes_verification_commands": "verification_commands" in live_acceptance_status and "reachops_final_acceptance_gate.py --json" in live_acceptance_status,
        "mac_self_check_exposes_client_gate": "\"client_delivery\"" in mac_self_check and "check_client_delivery" in mac_self_check and "final_delivery_ready" in mac_self_check,
        "native_app_entry_unifies_to_web_with_explicit_legacy_tk_diagnostics": "from ReachOps.launcher import main" in app_entry and "_launch_legacy_tk_client" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "_launch_web_client" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "--web" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "REACHOPS_WEB_CLIENT" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "--help" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "Show this help without starting clients" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "未知启动参数" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "return 2" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "回退到原生 Tk 客户端" not in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8"),
        "mac_self_check_starts_web_on_loopback": "tools\" / \"reachops_web_ui.py" in mac_self_check and "\"--web\"" in mac_self_check and "\"--host\"" in mac_self_check and "\"127.0.0.1\"" in mac_self_check and "REACHOPS_WEB_HOST" in mac_self_check,
        "mac_self_check_classifies_tk_environment_failures": "classify_tk_failure" in mac_self_check and "PYTHON_TK_UNUSABLE" in mac_self_check and "Tk 恢复:" in mac_self_check,
        "mac_self_check_reports_web_start_failure": "start_web_failed" in mac_self_check and "\"ok\": False" in mac_self_check and "web_start_error" in mac_self_check and "本地客户端控制台后端启动失败" in mac_self_check,
        "mac_self_check_requires_version_api_local_client_identity": "apply_version_payload" in mac_self_check and "client_surface_current" in mac_self_check and "display_version_current" in mac_self_check and "loopback_host_current" in mac_self_check and "local_client_console" in mac_self_check and "客户端 v20" in mac_self_check,
        "client_entry_copy_identifies_local_client_console": "启动ReachOps本地客户端.command" in (ROOT_DIR / "README.md").read_text(encoding="utf-8") and "启动ReachOps本地客户端.command" in (ROOT_DIR / "ReachOps" / "README.md").read_text(encoding="utf-8") and (ROOT_DIR / "启动ReachOps本地客户端.command").exists() and "ReachOps 本地客户端启动中" in (ROOT_DIR / "启动ReachOps本地客户端.command").read_text(encoding="utf-8") and "ReachOpsApp.py" in (ROOT_DIR / "启动ReachOps本地客户端.command").read_text(encoding="utf-8") and "启动ReachOps本地客户端.command" in (ROOT_DIR / "tools" / "sync_reachops_to_windows_vm.sh").read_text(encoding="utf-8") and "ReachOps 原生客户端 UI" in (ROOT_DIR / "启动ReachOps原生MacUI.command").read_text(encoding="utf-8") and "ReachOps 本地客户端控制台实际地址" in (ROOT_DIR / "启动ReachOps统一WebUI.command").read_text(encoding="utf-8") and "Start the native Tk client" in (ROOT_DIR / "ReachOps" / "launcher.py").read_text(encoding="utf-8") and "Web 运营面板" not in mac_self_check,
        "web_ui_version_markers_include_client_gate": "REQUIRED_WEB_UI_MARKERS" in mac_self_check and "ReachOps 本地客户端控制台" in mac_self_check and "127.0.0.1 控制台" in mac_self_check and "客户端 v20" in mac_self_check and "客户端门禁" in mac_self_check and "最终交付门禁" in mac_self_check and "finalStatusState" in mac_self_check and "finalStatusActions" in mac_self_check and "finalStatusCommands" in mac_self_check and "fetch('/api/final-status')" in mac_self_check and "next_required_actions" in mac_self_check and "verification_commands" in mac_self_check and "final_delivery_ready" in mac_self_check and "failed_checks" in mac_self_check,
        "web_account_repair_summary_visible_to_operator": "accountRepairActionItems" in web_ui and "account_repair_summary" in web_ui and "error_groups" in web_ui and "profile_ids_sample" in web_ui and "accountRepairActionItems" in mac_self_check and "account_repair_summary" in mac_self_check,
        "web_account_repair_stale_state_visible_to_operator": "accountRepairApplyItems" in web_ui and "旧账号修复结果已失效" in web_ui and "不要继续勾选旧的重新预检" in web_ui and "旧账号修复结果已失效" in mac_self_check,
        "server_launches_headless_runner": "tools/run_reachops_headless_macos.py" in web_ui and "subprocess.Popen" in web_ui,
        "headless_refreshes_profile_groups_before_start": "refresh_profile_groups(show_message=False)" in headless and "headless_refresh_profiles_failed" in headless and "start_collection_from_console()" in headless,
        "headless_uses_service_layer": "GrowthIntelligenceService" in headless and "GrowthWorkflowService" in headless,
        "headless_reuses_collection_entrypoint": "start_collection_from_console()" in headless,
        "headless_recheck_keeps_hard_failure_exclusion": "REACHOPS_FORCE_ACCOUNT_RECHECK" in web_ui and "live_recheck_keep_hard_failure_exclusion" in standalone and "_exclude_recent_hard_failed_profiles(candidate_profiles)" in standalone and "selected = list(candidate_profiles or [])[:limit]" not in standalone,
        "headless_live_comment_sets_real_submit_mode": "live_comment = str(args.mode) == \"live_comment\"" in headless and "DummyVar(\"真实提交\" if live_comment else \"预检，不提交\")" in headless and "action_execution_live_confirm_var = DummyVar(live_comment)" in headless,
        "headless_collect_mode_does_not_wait_for_action_submit": "if str(mode) == \"collect\":" in headless and "return collection_terminal_seen(lines)" in headless,
        "standalone_routes_actions_through_workflow": "self.workflow.run_action_router" in standalone and "TikTokSeleniumActionExecutor" in standalone,
        "standalone_collect_only_skips_action_processing": "if quick_mode == \"collect_only\":" in standalone and "reason=目标快发只采集模式 no_submit=true" in standalone,
        "standalone_live_comment_enables_platform_submit": "live_submit = live_mode and live_confirmed" in standalone and "live_preflight_only=not live_submit" in standalone and "allow_live_submit=live_submit" in standalone and "preflight_only=not live_submit" in standalone,
        "standalone_live_submit_requires_authorization_gate": "require_authorization=True" in standalone and "require_authorization=not live_submit" not in standalone,
        "action_router_live_submit_requires_local_evidence_file": "require_local_evidence_file: bool = True" in action_router and "allow_uri=not config.require_local_evidence_file" in action_router and "LIVE_SUBMIT_EVIDENCE_MISSING" in action_router,
        "live_readiness_rejects_fixture_uri_as_real_evidence": '"accept_fixture_uri": False' in live_readiness and "sidecar_profile_id_present" in live_readiness and "sidecar_current_url_present" in live_readiness,
        "live_submit_platform_acceptance_requires_local_evidence_details": "require_local_evidence_file=platform_executor is None" in live_submit_acceptance and "sidecar.get(\"profile_id\")" in live_submit_acceptance and "sidecar.get(\"current_url\")" in live_submit_acceptance,
        "collection_uses_workbench_browser_adapter": "get_workbench_browser_adapter" in router and "manager.acquire" in router,
        "actions_use_workbench_browser_adapter": "get_workbench_browser_adapter" in action_executor and "manager.acquire" in action_executor,
        "ixbrowser_local_api_adapter": "from ixbrowser_local_api import IXBrowserClient" in browser_manager and "client.open_profile" in browser_manager,
        "selenium_attaches_to_ixbrowser_debug_port": "options.debugger_address" in browser_manager and "webdriver.Chrome" in browser_manager,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "architecture": "web_ui_http_api -> local server subprocess -> headless service layer -> workflow/router -> ixBrowser local API -> Selenium",
        "operator_entrypoint": "/api/start",
        "browser_adapter": "IxBrowserLocalAdapter",
        "runtime_control": ["/api/logs", "/api/snapshot", "/api/acceptance", "/api/final-status", "/api/control"],
    }


def run_final_delivery_contract_docs_fixture() -> dict:
    docs = {
        "root_readme": ROOT_DIR / "README.md",
        "reachops_readme": ROOT_DIR / "ReachOps" / "README.md",
        "delivery_plan": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_DELIVERY_EXECUTION_PLAN.md",
        "goal_mode_execution": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_GOAL_MODE_EXECUTION.md",
        "windows_runbook": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_WINDOWS_LIVE_ACCEPTANCE_RUNBOOK.md",
        "operator_matrix": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_OPERATOR_ACCEPTANCE_MATRIX.md",
        "pm_delivery_baseline": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_PM_DELIVERY_BASELINE.md",
        "handoff": ROOT_DIR / "HANDOFF.md",
        "pressure_audit_report": ROOT_DIR / "ReachOps" / "docs" / "REACHOPS_REAL_PRESSURE_AUDIT_ACCEPTANCE_REPORT.md",
    }
    required_tokens = [
        "reachops_final_acceptance_gate.py",
        "final_delivery_ready=true",
        "failed_checks=[]",
    ]
    gate_tokens = {
        "client_gate": "reachops_client_delivery_check.py",
        "package_gate": "reachops_delivery_package_check.py",
        "final_gate_report": "final_acceptance_gate.json",
        "windows_package_preflight": "windows_package_preflight",
    }
    per_doc: dict[str, dict] = {}
    for name, path in docs.items():
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if name in {"root_readme", "windows_runbook", "operator_matrix"}:
            missing.extend(token for token in gate_tokens.values() if token not in text)
        if name in {"windows_runbook", "handoff", "pressure_audit_report"}:
            missing.extend(token for token in ["final_delivery_ready", "final_delivery_blockers"] if token not in text)
        if name in {"root_readme", "windows_runbook", "handoff", "pressure_audit_report"}:
            missing.extend(token for token in ["--allow-missing-final-gate", "bootstrap_only=true"] if token not in text)
        if name in {"handoff", "pressure_audit_report"}:
            missing.extend(token for token in ["SYNC_FINAL_ACCEPTANCE_GATE_STATUS", "SYNC_FINAL_DELIVERY_READY"] if token not in text)
            missing.extend(token for token in ["final_delivery_package"] if token not in text)
            missing.extend(token for token in ["delivery_package_check_not_final_ready"] if token not in text)
            missing.extend(token for token in ["windows_package_preflight"] if token not in text)
        if name in {"root_readme", "operator_matrix", "pm_delivery_baseline", "handoff", "pressure_audit_report", "goal_mode_execution"}:
            missing.extend(
                token
                for token in [
                    "deliverable_index",
                    "delivery_boundary",
                    "windows_final_package.ready=false",
                    "authorized_live_submit.ready=false",
                    "final_acceptance_gate.ready=false",
                ]
                if token not in text
            )
        if name in {"operator_matrix", "pm_delivery_baseline"}:
            missing.extend(
                token
                for token in [
                    "执行ReachOps账号修复.command",
                    "tools/reachops_apply_account_repair_plan.py --json",
                    "隔离坏账号",
                    "封禁账号",
                    "blocked_by_accounts",
                ]
                if token not in text
            )
        if name == "pm_delivery_baseline":
            missing.extend(
                token
                for token in [
                    "复测ReachOps真实执行.command",
                    "profile_available>=1",
                    "status=passed",
                    "acceptance_ready=true",
                ]
                if token not in text
            )
        if name == "goal_mode_execution":
            missing.extend(
                token
                for token in ["latest_goal_delivery_summary.md", "reachops_mac_loop_acceptance.py", "mac_loop_ready=true"]
                if token not in text
            )
        if name == "pressure_audit_report":
            missing.extend(
                token
                for token in [
                    "package_evidence_ready",
                    "package_final_gate_summary_ready",
                    "artifacts_ready=false",
                    "manifest_ready=false",
                    "report_files_ready=false",
                    "acceptance_verification_ready=false",
                    "evidence_ready=true",
                    "readiness=pass",
                    "size>0",
                    "expected_sha256/actual_sha256",
                    "expected_size/actual_size",
                    "final report set",
                    "live_submit",
                    "final_acceptance_gate_json_mismatch",
                    "final_acceptance_gate_json_checks_missing",
                    "final_acceptance_gate_json_checks_failed",
                    "final_gate_report",
                    "missing_required_checks",
                    "failed_required_checks",
                    "outside_acceptance_dir",
                ]
                if token not in text
            )
        per_doc[name] = {
            "path": str(path.relative_to(ROOT_DIR)),
            "ok": not missing,
            "missing": missing,
        }
    return {
        "passed": all(row["ok"] for row in per_doc.values()),
        "documents": per_doc,
        "required_contract": "summary passed + client gate ready + package check passed + final acceptance gate passed + deliverable_index boundary",
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
            records = [
                {"profileId": "ca-1", "profileName": "CA 1", "groupId": "281726", "groupName": "Canada"},
                {"profileId": "ca-2", "profileName": "CA 2", "groupId": "281726", "groupName": "Canada"},
                {"profileId": "us-1", "profileName": "US 1", "groupId": "257999", "groupName": "US"},
                {"profileId": "br-1", "profileName": "BR 1", "groupId": "286343", "groupName": "BR"},
                {"profileId": "br-2", "profileName": "BR 2", "groupId": "286343", "groupName": "BR"},
            ]
            if "group_id" in kwargs:
                group_id = str(kwargs.get("group_id") or "")
                filtered = [row for row in records if str(row.get("groupId") or "") == group_id]
                self.total = len(filtered)
                return {"data": {"records": filtered, "totalCount": len(filtered)}}
            self.total = 5
            pages = {
                1: {
                    "data": {
                        "records": records,
                        "totalCount": 5,
                    }
                }
            }
            return pages.get(page, {"data": {"records": [], "totalCount": 5}})

        def get_group_list(self, page=1, limit=100):
            self.total = 3
            if page == 1:
                return {
                    "data": {
                        "list": [
                            {"groupId": "281726", "groupName": "Canada", "profileCount": 2},
                            {"groupId": "257999", "groupName": "US", "profileCount": 1},
                            {"groupId": "286343", "groupName": "BR", "profileCount": 2},
                        ],
                        "total": 3,
                    }
                }
            return {"data": {"list": [], "total": 3}}

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
            "group_list_is_runtime_config_source": snapshot.get("profiles_deferred") is True
            and counts.get("Canada") == 2
            and counts.get("BR") == 2,
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
        {"profile_id": "10006", "group_name": "US"},
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
        if profile_id == "10006":
            return None, None, "ixBrowser open_profile failed: code=2014 message=当前版本仅支持 138 内核打开"
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
            "execution": ["max_videos = max(1, int(self.console.scan_max_videos_var.get() or 5))", "max_videos_per_creator=max_videos"],
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
    hidden_rule_controls = {"每个目标最多视频", "每条视频最多评论", "参与账号数", "任务间隔秒", "排除词"}
    for label, contract in operator_control_map.items():
        ui_ok = True if label in hidden_rule_controls else all(token_present(token) for token in contract["ui"])
        execution_ok = all(token_present(token) for token in contract["execution"])
        evidence_ok = all(token_present(token) for token in contract["evidence"])
        operator_control_evidence[label] = {
            "ui": ui_ok,
            "execution": execution_ok,
            "evidence": evidence_ok,
            "ui_policy": "hidden_rule_control" if label in hidden_rule_controls else "visible_operator_control",
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
    execution_csv_rows_data = []
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
            execution_csv_rows_data = list(reader)
            execution_rows = len(execution_csv_rows_data)
    if action_report and Path(action_report).exists():
        with open(action_report, "r", encoding="utf-8") as fh:
            action_report_payload = json.load(fh)
    required_customer_columns = {"username", "profile_url", "qualify_score", "intent_tags", "comment_text", "video_url", "batch_id"}
    required_action_columns = {"target_username", "action_type", "status", "risk_level", "suggested_text", "target_url", "batch_id"}
    required_execution_columns = {
        "action_id",
        "action_type",
        "target_username",
        "status",
        "profile_id",
        "evidence_path",
        "error_code",
        "risk_gate_reason_code",
        "risk_gate_summary",
        "risk_gate_next_step",
        "created_at",
    }
    funnel = payload.get("funnel") or {}
    execution_summary = payload.get("execution_summary") if isinstance(payload.get("execution_summary"), dict) else {}
    outreach_executions = payload.get("outreach_executions") if isinstance(payload.get("outreach_executions"), list) else []
    json_execution_risk_fields_present = bool(outreach_executions) and all(
        "risk_gate_reason_code" in row and "risk_gate_summary" in row and "risk_gate_next_step" in row
        for row in outreach_executions
        if isinstance(row, dict)
    )
    json_execution_risk_values_present = any(
        str((row or {}).get("risk_gate_summary") or "").strip()
        or str((row or {}).get("risk_gate_next_step") or "").strip()
        for row in outreach_executions
        if isinstance(row, dict)
    )
    csv_execution_risk_values_present = any(
        str((row or {}).get("risk_gate_summary") or "").strip()
        or str((row or {}).get("risk_gate_next_step") or "").strip()
        for row in execution_csv_rows_data
    )
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
        "execution_export_has_risk_gate_fields": {
            "risk_gate_reason_code",
            "risk_gate_summary",
            "risk_gate_next_step",
        }.issubset(set(execution_header)),
        "json_execution_risk_fields_present": json_execution_risk_fields_present,
        "json_execution_risk_values_present": json_execution_risk_values_present,
        "csv_execution_risk_values_present": csv_execution_risk_values_present,
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
    outcome_metrics_fixture = run_outcome_metrics_fixture()
    data_governance_fixture = run_data_governance_fixture()
    security_supply_chain_fixture = build_security_supply_chain_report()
    start_contract_fixture = build_start_contract_report(ROOT_DIR)
    client_delivery_gate = run_client_delivery_gate_fixture()
    web_local_api_architecture = run_web_local_api_architecture_fixture()
    web_panel_dom_smoke = run_web_panel_dom_smoke()
    web_panel_runtime_smoke = run_web_panel_runtime_smoke_with_retry()
    final_delivery_contract_docs = run_final_delivery_contract_docs_fixture()
    authorization_gate_matrix = run_authorization_gate_matrix_fixture()
    profile_group_refresh = run_profile_group_refresh_fixture()
    profile_preflight_anomalies = run_profile_preflight_anomaly_fixture()
    operator_console_contract = run_operator_console_contract_fixture()
    campaign_funnel_isolation = run_campaign_funnel_isolation_fixture(args.target)
    collection_error_states = run_collection_error_state_fixture()
    product_link_campaign = run_product_link_campaign_fixture()
    creator_topic_inputs = run_creator_and_topic_input_fixture()
    ci_release_baseline_fixture = build_ci_release_baseline_report(ROOT_DIR)
    account_readiness_fixture = build_account_readiness_report(ROOT_DIR)
    control_plane_fixture = build_control_plane_report(ROOT_DIR)
    issue_closure_fixture = build_issue_closure_report(ROOT_DIR, run_pip=False)

    repository_cleanup = clean_generated_redundant_paths(ROOT_DIR)
    repository_cleanliness = scan_repository_cleanliness(ROOT_DIR, require_clean_git=False)
    repository_cleanliness["cleanup"] = repository_cleanup
    action_executor_source = (ROOT_DIR / "ReachOps" / "workbench" / "tiktok_action_executor.py").read_text(encoding="utf-8")
    action_router_source = (ROOT_DIR / "ReachOps" / "workbench" / "action_router.py").read_text(encoding="utf-8")
    account_health_source = (ROOT_DIR / "ReachOps" / "workbench" / "account_health_manager.py").read_text(encoding="utf-8")
    evidence_bundle_source = (ROOT_DIR / "ReachOps" / "evidence_bundle.py").read_text(encoding="utf-8")
    ai_console_source = (ROOT_DIR / "ReachOps" / "ai_console.py").read_text(encoding="utf-8")
    runtime_smoke_source = (ROOT_DIR / "tools" / "reachops_web_panel_runtime_smoke.py").read_text(encoding="utf-8")

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
            "/api/start 启动契约可审计且阻断路径不启动浏览器",
            bool(
                start_contract_fixture.get("passed")
                and not start_contract_fixture.get("failed_cases")
                and (start_contract_fixture.get("response_invariants") or {}).get("prelaunch_rejections_do_not_start_browser")
                and (start_contract_fixture.get("response_invariants") or {}).get("prelaunch_rejections_do_not_submit")
                and (start_contract_fixture.get("response_invariants") or {}).get("blocked_start_is_recoverable_and_supportable")
                and len(start_contract_fixture.get("rejection_cases") or []) >= 8
            ),
            start_contract_fixture,
        ),
        check(
            "CI 和 release baseline 本地门禁可重复审计",
            bool(
                ci_release_baseline_fixture.get("passed")
                and (ci_release_baseline_fixture.get("local_checks") or {}).get("ci_contract_complete")
                and (ci_release_baseline_fixture.get("local_checks") or {}).get("dependency_baseline_passed")
                and (ci_release_baseline_fixture.get("local_checks") or {}).get("pip_check_passed")
                and (ci_release_baseline_fixture.get("local_checks") or {}).get("release_contract_complete")
                and ci_release_baseline_fixture.get("does_not_claim_branch_protection") is True
                and ci_release_baseline_fixture.get("does_not_claim_ten_green_ci_runs") is True
            ),
            ci_release_baseline_fixture,
        ),
        check(
            "账号 readiness 和 no-submit 证据包本地合同可审计",
            bool(
                account_readiness_fixture.get("passed")
                and account_readiness_fixture.get("schema_version") == "reachops.account_readiness_audit.v1"
                and account_readiness_fixture.get("status") == "passed_with_external_account_pilot_pending"
                and (account_readiness_fixture.get("local_checks") or {}).get("lifecycle_signal_coverage_complete")
                and (account_readiness_fixture.get("local_checks") or {}).get("profile_preflight_records_evidence_and_quarantine")
                and (account_readiness_fixture.get("local_checks") or {}).get("live_no_submit_preflight_covers_comment_follow_dm")
                and (account_readiness_fixture.get("no_submit_contract") or {}).get("preflight_actions_do_not_submit")
                and (account_readiness_fixture.get("real_vs_fixture_boundary") or {}).get("external_pilot_required")
                and account_readiness_fixture.get("does_not_claim_certified_30_profiles") is True
                and account_readiness_fixture.get("does_not_claim_100_real_no_submit_runs") is True
                and "certified_30_controlled_profiles" in (account_readiness_fixture.get("external_acceptance_pending") or [])
                and "100_real_no_submit_runs_across_three_industries" in (account_readiness_fixture.get("external_acceptance_pending") or [])
            ),
            account_readiness_fixture,
        ),
        check(
            "商业控制面和 connector 解耦边界可审计",
            bool(
                control_plane_fixture.get("passed")
                and control_plane_fixture.get("schema_version") == "reachops.control_plane_audit.v1"
                and control_plane_fixture.get("status") == "passed_with_external_control_plane_pending"
                and (control_plane_fixture.get("local_checks") or {}).get("local_control_surface_is_plan_and_session_bound")
                and (control_plane_fixture.get("local_checks") or {}).get("connector_contract_exists_for_collection_with_evidence")
                and (control_plane_fixture.get("local_checks") or {}).get("action_executor_contract_separates_fixture_from_tiktok")
                and (control_plane_fixture.get("local_checks") or {}).get("packaged_entitlement_enforces_remote_disable")
                and (control_plane_fixture.get("control_plane_boundary") or {}).get("server_side_rbac_pending")
                and (control_plane_fixture.get("connector_boundary") or {}).get("non_tiktok_connector_pending")
                and (control_plane_fixture.get("module_boundary") or {}).get("monolith_split_pending")
                and control_plane_fixture.get("does_not_claim_server_side_rbac") is True
                and control_plane_fixture.get("does_not_claim_non_tiktok_connector_ga") is True
                and "web_ui_http_api_service_connector_module_split" in (control_plane_fixture.get("external_control_plane_pending") or [])
            ),
            control_plane_fixture,
        ),
        check(
            "Issues #1-#7 商业交付闭环证据索引可审计",
            bool(
                issue_closure_fixture.get("passed")
                and issue_closure_fixture.get("schema_version") == "reachops.issue_closure_audit.v1"
                and issue_closure_fixture.get("status") == "passed_with_external_acceptance_pending"
                and (issue_closure_fixture.get("summary") or {}).get("issues_total") == 7
                and (issue_closure_fixture.get("summary") or {}).get("local_contracts_passed") == 7
                and (issue_closure_fixture.get("summary") or {}).get("acceptance_criteria_total") == 53
                and (issue_closure_fixture.get("summary") or {}).get("acceptance_criteria_unclassified") == 0
                and (issue_closure_fixture.get("summary") or {}).get("external_pending_count", 0) >= 1
                and (issue_closure_fixture.get("summary") or {}).get("does_not_claim_all_issues_closed") is True
                and (issue_closure_fixture.get("github_issues") or {}).get("closure_requires_external_validation") is True
            ),
            issue_closure_fixture,
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
            "刷新分组能读取 ixBrowser 配置分组列表",
            bool(
                profile_group_refresh.get("profile_count") == 0
                and profile_group_refresh.get("profiles_deferred") is True
                and profile_group_refresh.get("counts", {}).get("Canada") == 2
                and profile_group_refresh.get("counts", {}).get("BR") == 2
                and not profile_group_refresh.get("stale_group_present")
                and profile_group_refresh.get("group_list_is_runtime_config_source")
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
                and profile_preflight_anomalies.get("unavailable") == 5
                and profile_preflight_anomalies.get("errors", {}).get("LOGIN_REQUIRED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("CAPTCHA_DETECTED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("PROXY_FAILED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("PROFILE_START_FAILED") == 1
                and profile_preflight_anomalies.get("errors", {}).get("IXBROWSER_KERNEL_MISMATCH") == 1
                and all(
                    (profile_preflight_anomalies.get("health", {}).get(profile_id) or {}).get("status") == "cooldown"
                    for profile_id in ["10002", "10003", "10004", "10005", "10006"]
                )
                and ("10006", "IXBROWSER_KERNEL_MISMATCH") in profile_preflight_anomalies.get("quarantine_moves", [])
            ),
            profile_preflight_anomalies,
        ),
        check(
            "连续失败账号会自动冷却隔离",
            bool(
                "cooldown_after_failures" in account_health_source
                and "should_force_cooldown" in account_health_source
                and ">= self.cooldown_after_failures" in account_health_source
                and "_force_cooldown" in account_health_source
                and "dict(row.__dict__)" in account_health_source
            ),
            {
                "configured_threshold_present": "cooldown_after_failures" in account_health_source,
                "record_failure_forces_cooldown": "should_force_cooldown" in account_health_source and "_force_cooldown" in account_health_source,
                "returns_snapshot": "dict(row.__dict__)" in account_health_source,
            },
        ),
        check(
            "账号冷却原因进入证据包和AI解释",
            bool(
                "build_account_health_summary" in evidence_bundle_source
                and "reachops.account_health_summary.v1" in evidence_bundle_source
                and "\"ACCOUNT_HEALTH\"" in evidence_bundle_source
                and "profile_forced_cooldown" in evidence_bundle_source
                and "\"ACCOUNT_HEALTH\"" in ai_console_source
                and "账号已进入冷却" in ai_console_source
                and "\"account_health\"" in action_router_source
                and "account_health_summary" in runtime_smoke_source
                and "reachops.account_health_summary.v1" in runtime_smoke_source
            ),
            {
                "action_router_account_health": "\"account_health\"" in action_router_source,
                "evidence_bundle_account_health": "build_account_health_summary" in evidence_bundle_source and "reachops.account_health_summary.v1" in evidence_bundle_source,
                "ai_console_account_health": "\"ACCOUNT_HEALTH\"" in ai_console_source and "账号已进入冷却" in ai_console_source,
                "runtime_smoke_account_health_contract": "account_health_summary" in runtime_smoke_source and "reachops.account_health_summary.v1" in runtime_smoke_source,
            },
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
            "页面卡住能基于上一帧快照识别",
            bool(
                "_page_state_history" in action_executor_source
                and "previous_snapshot=previous_snapshot" in action_executor_source
                and "state_key=state_key" in action_executor_source
                and "\"DOM_STALLED\"" in action_executor_source
            ),
            {
                "executor_uses_page_state_history": "_page_state_history" in action_executor_source,
                "detector_receives_previous_snapshot": "previous_snapshot=previous_snapshot" in action_executor_source,
                "state_key_scopes_history": "state_key=state_key" in action_executor_source,
            },
        ),
        check(
            "评论动作缺失控件使用标准页面状态",
            bool(
                "include_action_requirements=True" in action_executor_source
                and "\"COMMENT_BOX_MISSING\"" in action_executor_source
                and "\"SUBMIT_BUTTON_MISSING\"" in action_executor_source
                and "\"COMMENT_BOX_NOT_FOUND\", \"comment box not found\"" not in action_executor_source
            ),
            {
                "action_requirement_detection_enabled": "include_action_requirements=True" in action_executor_source,
                "comment_box_missing_standardized": "\"COMMENT_BOX_MISSING\"" in action_executor_source,
                "submit_button_missing_standardized": "\"SUBMIT_BUTTON_MISSING\"" in action_executor_source,
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
                and export_artifact_inspection.get("execution_export_has_risk_gate_fields")
                and export_artifact_inspection.get("json_execution_risk_fields_present")
                and export_artifact_inspection.get("json_execution_risk_values_present")
                and export_artifact_inspection.get("csv_execution_risk_values_present")
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
        check(
            "WAQO 和结果漏斗排除 fixture/dry-run 数据",
            bool(
                outcome_metrics_fixture.get("passed")
                and outcome_metrics_fixture.get("definition", {}).get("schema_version") == "reachops.waqo_definition.v1"
                and int(outcome_metrics_fixture.get("waqo", {}).get("count") or 0) == 1
                and int(outcome_metrics_fixture.get("waqo", {}).get("excluded_fixture_or_dry_run") or 0) == 1
                and int(outcome_metrics_fixture.get("funnel", {}).get("orders") or 0) == 1
                and float(outcome_metrics_fixture.get("funnel", {}).get("revenue_amount") or 0) == 1200.0
                and outcome_metrics_fixture.get("ingestion", {}).get("schema_version") == "reachops.outcome_ingestion.v1"
                and int(outcome_metrics_fixture.get("ingestion", {}).get("imported") or 0) == 1
                and float(outcome_metrics_fixture.get("pilot_report", {}).get("cost_per_accepted_opportunity") or 0) == 300.0
                and outcome_metrics_fixture.get("quality", {}).get("fixture_data_excluded_by_default") is True
            ),
            outcome_metrics_fixture,
        ),
        check(
            "数据治理执行备份恢复、腐坏库恢复和隐私操作审计",
            bool(
                data_governance_fixture.get("passed")
                and data_governance_fixture.get("backup_restore", {}).get("status") == "passed"
                and data_governance_fixture.get("backup_restore", {}).get("rpo_met") is True
                and data_governance_fixture.get("backup_restore", {}).get("rto_met") is True
                and data_governance_fixture.get("backup_restore", {}).get("corruption_drill", {}).get("status") == "passed"
                and data_governance_fixture.get("privacy_operations", {}).get("schema_version") == "reachops.privacy_operations.v1"
                and data_governance_fixture.get("privacy_operations", {}).get("audit", {}).get("observed_operations") == ["delete", "export", "legal_hold"]
                and data_governance_fixture.get("recovery_objectives", {}).get("schema_version") == "reachops.recovery_objectives.v1"
                and data_governance_fixture.get("support_bundle", {}).get("manifest_schema_version") == "reachops.support_bundle_manifest.v1"
                and data_governance_fixture.get("support_bundle", {}).get("diagnostic_manifest_complete") is True
                and isinstance(data_governance_fixture.get("support_bundle", {}).get("required_diagnostic_files"), list)
                and isinstance(data_governance_fixture.get("support_bundle", {}).get("missing_required_diagnostics"), list)
                and "required_diagnostics_present" in data_governance_fixture.get("support_bundle", {})
                and "does_not_claim_required_diagnostics_present" in data_governance_fixture.get("support_bundle", {})
                and data_governance_fixture.get("support_diagnostics_materialization", {}).get("schema_version") == "reachops.support_diagnostics_materialization.v1"
                and "sync-support-diagnostics" in (ROOT_DIR / "tools" / "reachops_data_governance.py").read_text(encoding="utf-8")
                and "materialize_support_diagnostics" in (ROOT_DIR / "tools" / "reachops_data_governance.py").read_text(encoding="utf-8")
                and "reports/support/account_support_handoff.json" in (data_governance_fixture.get("support_bundle", {}).get("required_diagnostics") or [])
                and "reports/support/account_support_handoff.json" in {
                    str(item.get("relative_path") or "")
                    for item in data_governance_fixture.get("support_bundle", {}).get("required_diagnostic_files") or []
                }
                and data_governance_fixture.get("support_bundle", {}).get("dry_run_manifest_passed") is True
                and data_governance_fixture.get("support_bundle", {}).get("dry_run_manifest", {}).get("activation_status_included") is False
                and data_governance_fixture.get("support_bundle", {}).get("dry_run_manifest", {}).get("raw_database_included") is False
                and data_governance_fixture.get("support_bundle", {}).get("dry_run_manifest", {}).get("evidence_image_included") is False
            ),
            data_governance_fixture,
        ),
        check(
            "打包授权和更新供应链安全矩阵通过",
            bool(
                security_supply_chain_fixture.get("passed")
                and security_supply_chain_fixture.get("schema_version") == "reachops.security_supply_chain_audit.v1"
                and security_supply_chain_fixture.get("entitlement", {}).get("cases", {}).get("replay_detected", {}).get("error_code") == "LIVE_SUBMIT_ENTITLEMENT_REPLAYED"
                and security_supply_chain_fixture.get("entitlement", {}).get("key_rotation", {}).get("retired_key_rejected") is True
                and security_supply_chain_fixture.get("update_supply_chain", {}).get("installer_verified") is True
                and security_supply_chain_fixture.get("update_supply_chain", {}).get("http_manifest_rejected") is True
                and security_supply_chain_fixture.get("update_supply_chain", {}).get("downgrade_without_rollback_blocked") is True
                and security_supply_chain_fixture.get("update_supply_chain", {}).get("explicit_rollback_available") is True
            ),
            security_supply_chain_fixture,
        ),
        check("独立配置/数据/授权目录存在", all(Path(path).exists() for path in [paths.data_dir, paths.config_dir, paths.logs_dir]), {"data_dir": paths.data_dir, "config_dir": paths.config_dir, "activation_status_path": paths.activation_status_path}),
        check("Windows 打包入口存在", all((ROOT_DIR / path).exists() for path in ["ReachOps/packaging/reachops.spec", "ReachOps/packaging/ReachOps.iss", "tools/build_reachops_windows.ps1"]), {"version": VERSION}),
        check(
            "Windows 启动入口标记为本地客户端控制台",
            bool(
                "ReachOpsApp.py" in (ROOT_DIR / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
                and 'client_surface = "local_client_console"' in (ROOT_DIR / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
                and 'display_name = "ReachOps Local Client Console"' in (ROOT_DIR / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
                and 'loopback_host = "127.0.0.1"' in (ROOT_DIR / "tools" / "start_reachops_ui_windows.ps1").read_text(encoding="utf-8")
                and "client_surface_not_local_console" in (ROOT_DIR / "tools" / "run_reachops_ui_startup_smoke_windows.ps1").read_text(encoding="utf-8")
                and "loopback_host_not_local" in (ROOT_DIR / "tools" / "run_reachops_ui_startup_smoke_windows.ps1").read_text(encoding="utf-8")
            ),
            {
                "launcher": "tools/start_reachops_ui_windows.ps1",
                "startup_smoke": "tools/run_reachops_ui_startup_smoke_windows.ps1",
                "client_surface": "local_client_console",
            },
        ),
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
        check(
            "客户端交付验收门禁不会把环境阻断当通过",
            False,
            {
                "contract_ok": client_delivery_gate.get("contract_ok"),
                "acceptance_ready": client_delivery_gate.get("acceptance_ready"),
                "final_delivery_ready": client_delivery_gate.get("final_delivery_ready"),
                "status": client_delivery_gate.get("status"),
                "readiness": client_delivery_gate.get("readiness"),
                "ok": client_delivery_gate.get("ok"),
                "blockers": client_delivery_gate.get("blockers"),
                "next_actions": client_delivery_gate.get("next_actions"),
                "failed_checks": client_delivery_gate.get("failed_checks"),
            },
            LOCAL_PENDING
            if client_delivery_gate.get("contract_ok")
            and not client_delivery_gate.get("acceptance_ready")
            and client_delivery_gate.get("readiness") in {"blocked_by_environment", "blocked_by_accounts", "partial", "not_started"}
            else None,
        ),
        check(
            "自治客户端核心合同已纳入交付门禁",
            bool((client_delivery_gate.get("autonomous_product_core_contract") or {}).get("ok")),
            client_delivery_gate.get("autonomous_product_core_contract") or {},
        ),
        check(
            "网页端通过服务端本地 API 调用指纹浏览器执行获客",
            bool(web_local_api_architecture.get("passed")),
            web_local_api_architecture,
        ),
        check(
            "运营 Web 面板运行时 API 冒烟可真实启动和控制执行链",
            bool(web_panel_runtime_smoke.get("passed")),
            web_panel_runtime_smoke,
            LOCAL_PENDING if web_panel_runtime_smoke.get("status") == "blocked_by_local_sandbox" else None,
        ),
        check(
            "运营 Web 面板按钮点击会执行真实 JS 并反馈 API 结果",
            bool(web_panel_dom_smoke.get("passed")),
            web_panel_dom_smoke,
        ),
        check(
            "最终交付文档合同统一要求客户端门禁、交付包和 final gate",
            bool(final_delivery_contract_docs.get("passed")),
            final_delivery_contract_docs,
        ),
        check(
            "项目结构无缓存临时备份冗余文件",
            bool(repository_cleanliness.get("passed")),
            repository_cleanliness,
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
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
