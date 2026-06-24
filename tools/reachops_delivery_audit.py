# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
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
    action_report = (action_result.get("report") or {}).get("json_path", "")
    exported_campaign_payload = {}
    if campaign_report and Path(campaign_report).exists():
        with open(campaign_report, "r", encoding="utf-8") as fh:
            exported_campaign_payload = json.load(fh)
    live_fixture = run_live_authorized_fixture(args.target)
    runtime_evidence_guard = run_runtime_evidence_guard_fixture(args.target)
    switch_fixture = run_switch_profile_fixture(args.target)
    fallback_fixture = run_fallback_comment_fixture(args.target)
    ai_fallback_fixture = run_ai_fallback_fixture(args.target)
    live_submit_acceptance_fixture = run_live_submit_acceptance_fixture()
    live_submit_block_fixture = run_live_submit_acceptance_block_fixture()
    packaging_update_fixture = run_packaging_update_fixture()
    authorization_gate_matrix = run_authorization_gate_matrix_fixture()

    checks = [
        check("输入产品/关键词即可创建获客任务", bool(plan.get("campaign", {}).get("id")), {"campaign_id": campaign_id, "input_type": plan.get("campaign", {}).get("input_type")}),
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
        check("可导出客户名单和执行报告", all(Path(path).exists() for path in [campaign_report, customers_csv, actions_csv, action_report] if path), {"campaign_report": campaign_report, "customers_csv": customers_csv, "actions_csv": actions_csv, "action_report": action_report}),
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
