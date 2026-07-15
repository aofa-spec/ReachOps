# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_client_acceptance_status import (
    DEFAULT_BASE_DIR,
    account_operator_steps,
    derive_acceptance,
    latest_batch,
    latest_profile_preflight,
    read_lines,
    write_remediation_report,
)
from tools.reachops_mac_self_check import REQUIRED_WEB_UI_MARKERS
from tools.reachops_web_ui import (
    CLIENT_DISPLAY_VERSION,
    WEB_UI_VERSION,
    annotate_acceptance_with_operations,
    build_operations_payload,
    build_version_payload,
    html_page,
    summarize_account_repair_plan,
)
from ReachOps.evidence_bundle import EVIDENCE_BUNDLE_SCHEMA_VERSION
from ReachOps.execution_plan import (
    PLAN_SCHEMA_VERSION,
    build_execution_plan,
    validate_execution_plan,
)
from ReachOps.run_session import (
    RUN_SESSION_SCHEMA_VERSION,
    RUN_SESSION_STATES,
    build_ai_usage_ledger,
    create_run_session,
    transition_run_session,
)
from ReachOps.workbench.page_state_detector import PAGE_STATES, PAGE_STATE_SCHEMA_VERSION
from ReachOps.workbench.repair_policy_engine import REPAIR_POLICY_SCHEMA_VERSION, RepairPolicyEngine
from ReachOps.workbench.risk_gate import RISK_GATE_SCHEMA_VERSION, RiskGate


ENTRYPOINTS = [
    "启动ReachOps本地客户端.command",
    "启动ReachOps统一WebUI.command",
    "启动ReachOps原生MacUI.command",
    "执行ReachOps账号修复.command",
    "复测ReachOps真实执行.command",
    "打开ReachOps验收包.command",
]
WINDOWS_ENTRYPOINTS = [
    "tools/start_reachops_ui_windows.ps1",
    "tools/start_growth_ui_windows.bat",
    "tools/run_reachops_acceptance_windows.ps1",
    "tools/build_reachops_windows.ps1",
]
ACCOUNT_REPAIR_APPLY_RE = re.compile(
    r"account_repair_apply\s+status=(?P<status>\S+)\s+group=(?P<group>.*?)\s+selected=(?P<selected>\d+)\s+moved=(?P<moved>\d+)\s+failed=(?P<failed>\d+)"
)
REQUIRED_AUTONOMOUS_RUN_STATES = {
    "CREATED",
    "PRECHECK",
    "PROFILE_OPENING",
    "COLLECTING",
    "SCORING",
    "ACTION_PLANNING",
    "EXECUTING",
    "REPAIRING",
    "DEGRADED",
    "BLOCKED",
    "COMPLETED",
}
REQUIRED_PAGE_STATES = {
    "READY",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "RATE_LIMITED",
    "PAGE_TIMEOUT",
    "DOM_STALLED",
    "MODAL_BLOCKED",
    "COMMENT_BOX_MISSING",
    "SUBMIT_BUTTON_MISSING",
    "UNKNOWN_PAGE_STATE",
}
ACCOUNT_REPAIR_AUTO_APPLY_ERRORS = {
    "IXBROWSER_KERNEL_MISMATCH",
    "LOGIN_REQUIRED",
    "CAPTCHA_DETECTED",
    "PROXY_FAILED",
    "COMMENT_ACCESS_GATED",
    "ACCOUNT_RESTRICTED",
}


def is_executable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & stat.S_IXUSR)
    except Exception:
        return False


def delivery_status(contract_ok: bool, acceptance_ready: bool, readiness: str) -> str:
    if contract_ok and acceptance_ready:
        return "passed"
    if not contract_ok:
        return "failed"
    if readiness in {"partial", "blocked_by_accounts", "blocked_by_environment", "not_started"}:
        return readiness
    return "failed"


def account_repair_apply_effective_status(repair_apply: dict) -> str:
    raw_status = str((repair_apply if isinstance(repair_apply, dict) else {}).get("status") or "")
    if not raw_status:
        return ""
    if repair_apply.get("stale"):
        return "stale"
    if repair_apply.get("same_group") is False:
        return "group_mismatch"
    if raw_status == "applied" and repair_apply.get("pending_recheck"):
        return "pending_recheck"
    return raw_status


def account_repair_apply_effective_message(repair_apply: dict) -> str:
    effective_status = account_repair_apply_effective_status(repair_apply)
    if effective_status == "stale":
        return "旧账号修复结果已失效；必须执行最新账号修复计划后再复测。"
    if effective_status == "group_mismatch":
        return "账号修复结果属于其他分组，不能用于当前执行分组；请执行当前分组的最新账号修复计划。"
    if effective_status == "pending_recheck":
        return "账号修复已执行；需要重新预检当前分组后才能验收。"
    if effective_status == "no_applicable_profiles":
        return "最新账号修复计划没有默认可自动隔离的账号；需要人工处理账号池。"
    return ""


def build_real_pilot_evidence_boundary(
    acceptance: dict,
    operations: dict,
    *,
    status: str,
    contract_ok: bool,
    acceptance_ready: bool,
    account_repair_summary: dict | None = None,
    account_repair_apply: dict | None = None,
) -> dict:
    counts = operations.get("counts") if isinstance(operations, dict) else {}
    counts = counts if isinstance(counts, dict) else {}
    repair_summary = account_repair_summary if isinstance(account_repair_summary, dict) else {}
    repair_apply = account_repair_apply if isinstance(account_repair_apply, dict) else {}
    repair_apply_effective_status = account_repair_apply_effective_status(repair_apply)
    profile_available = int((acceptance.get("checks") or {}).get("profile_available_count") or 0)
    candidates = int(counts.get("candidates") or 0)
    actions = int(counts.get("actions") or 0)
    touched = int(counts.get("touched") or 0)
    real_pilot_ready = bool(
        status == "passed"
        and contract_ok
        and acceptance_ready
        and profile_available > 0
        and candidates > 0
    )
    blockers: list[str] = []
    if profile_available <= 0:
        blockers.append("profile_available_zero")
    if candidates <= 0:
        blockers.append("candidate_count_zero")
    if not acceptance_ready:
        blockers.append("acceptance_not_ready")
    if status != "passed":
        blockers.append(f"client_delivery_status_{status}")
    return {
        "schema_version": "reachops.real_pilot_evidence_boundary.v1",
        "real_pilot_ready": real_pilot_ready,
        "status": "ready" if real_pilot_ready else "external_validation_pending",
        "fixture_or_dry_run_claimed": False,
        "no_submit_preserved": True,
        "requires_real_account_pool": profile_available <= 0,
        "requires_real_collection_evidence": candidates <= 0,
        "requires_human_labeled_quality_evidence": True,
        "profile_available": profile_available,
        "operation_counts": {
            "candidates": candidates,
            "actions": actions,
            "touched": touched,
        },
        "account_pool_remediation": {
            "repair_plan_available": repair_summary.get("status") == "ok",
            "repair_plan_path": str(repair_summary.get("path") or ""),
            "repair_plan_batch_id": str(repair_summary.get("batch_id") or ""),
            "repair_plan_profile_group": str(repair_summary.get("profile_group") or ""),
            "total_unique_profiles_by_error": int(repair_summary.get("total_unique_profiles_by_error") or 0),
            "total_error_events_by_error": int(repair_summary.get("total_error_events_by_error") or 0),
            "summary_only_error_count": int(repair_summary.get("summary_only_error_count") or 0),
            "operator_steps": list(repair_summary.get("operator_steps") or [])[:5],
            "latest_apply_status": str(repair_apply.get("status") or ""),
            "latest_apply_effective_status": repair_apply_effective_status,
            "latest_apply_effective_message": account_repair_apply_effective_message(repair_apply),
            "latest_apply_stale": bool(repair_apply.get("stale")),
            "latest_apply_stale_reason": str(repair_apply.get("stale_reason") or ""),
            "latest_apply_pending_recheck": bool(repair_apply.get("pending_recheck")),
        },
        "external_acceptance_pending": blockers,
    }


def build_account_blocker_resolution(
    acceptance: dict,
    *,
    batch: dict | None = None,
    account_repair_summary: dict | None = None,
    account_repair_apply: dict | None = None,
) -> dict:
    batch = batch if isinstance(batch, dict) else {}
    repair_summary = account_repair_summary if isinstance(account_repair_summary, dict) else {}
    repair_apply = account_repair_apply if isinstance(account_repair_apply, dict) else {}
    readiness = str((acceptance if isinstance(acceptance, dict) else {}).get("readiness") or "")
    checks = (acceptance.get("checks") if isinstance(acceptance, dict) else {}) or {}
    profile_available = int(checks.get("profile_available_count") or 0)
    effective_status = account_repair_apply_effective_status(repair_apply)
    repair_plan_available = repair_summary.get("status") == "ok"
    repair_plan_profiles = int(repair_summary.get("total_unique_profiles_by_error") or 0)
    error_groups = [row for row in (repair_summary.get("error_groups") or []) if isinstance(row, dict)]
    auto_apply_profile_count = sum(
        int(row.get("profile_ids_total") or 0)
        for row in error_groups
        if str(row.get("error") or "").strip() in ACCOUNT_REPAIR_AUTO_APPLY_ERRORS
    )
    non_auto_error_codes = sorted(
        {
            str(row.get("error") or "").strip()
            for row in error_groups
            if str(row.get("error") or "").strip()
            and int(row.get("profile_ids_total") or 0) > 0
            and str(row.get("error") or "").strip() not in ACCOUNT_REPAIR_AUTO_APPLY_ERRORS
        }
    )
    blocker_codes: list[str] = []
    status = "not_blocked"
    priority_action = ""
    ready_for_retest = False
    requires_latest_repair_apply = False
    requires_manual_account_work = False
    if readiness == "blocked_by_accounts":
        if effective_status == "pending_recheck":
            status = "pending_recheck"
            priority_action = "rerun_client_preflight"
            ready_for_retest = True
            blocker_codes.append("account_repair_applied_pending_recheck")
        elif effective_status == "stale":
            status = "stale_repair_apply"
            if auto_apply_profile_count > 0:
                priority_action = "apply_latest_account_repair_plan"
                requires_latest_repair_apply = True
            elif repair_plan_available and repair_plan_profiles > 0:
                priority_action = "manually_repair_or_replace_accounts"
                requires_manual_account_work = True
            else:
                priority_action = "apply_latest_account_repair_plan"
                requires_latest_repair_apply = True
            blocker_codes.append("account_repair_apply_stale")
            if repair_plan_available and repair_plan_profiles > 0 and auto_apply_profile_count <= 0:
                blocker_codes.append("account_repair_plan_has_no_auto_applicable_profiles")
        elif effective_status == "group_mismatch":
            status = "repair_apply_group_mismatch"
            if auto_apply_profile_count > 0:
                priority_action = "apply_current_group_account_repair_plan"
                requires_latest_repair_apply = True
            else:
                priority_action = "manually_repair_or_replace_accounts"
                requires_manual_account_work = True
            blocker_codes.append("account_repair_apply_group_mismatch")
            if repair_plan_available and repair_plan_profiles > 0 and auto_apply_profile_count <= 0:
                blocker_codes.append("account_repair_plan_has_no_auto_applicable_profiles")
        elif effective_status == "no_applicable_profiles":
            status = "manual_account_work_required"
            priority_action = "manually_repair_or_replace_accounts"
            requires_manual_account_work = True
            blocker_codes.append("account_repair_no_applicable_profiles")
        elif repair_plan_available and auto_apply_profile_count > 0:
            status = "repair_plan_ready"
            priority_action = "apply_latest_account_repair_plan"
            requires_latest_repair_apply = True
            blocker_codes.append("account_repair_plan_ready")
        elif repair_plan_available and repair_plan_profiles > 0:
            status = "manual_account_work_required"
            priority_action = "manually_repair_or_replace_accounts"
            requires_manual_account_work = True
            blocker_codes.append("account_repair_plan_has_no_auto_applicable_profiles")
        else:
            status = "account_pool_empty"
            priority_action = "create_or_repair_real_account_pool"
            requires_manual_account_work = True
            blocker_codes.append("profile_available_zero")
    return {
        "schema_version": "reachops.account_blocker_resolution.v1",
        "status": status,
        "readiness": readiness,
        "profile_group": str(batch.get("profile_group") or repair_summary.get("profile_group") or ""),
        "batch_id": str(batch.get("id") or repair_summary.get("batch_id") or ""),
        "profile_available": profile_available,
        "repair_plan_available": repair_plan_available,
        "repair_plan_path": str(repair_summary.get("path") or ""),
        "repair_plan_profile_count": repair_plan_profiles,
        "repair_plan_auto_apply_profile_count": auto_apply_profile_count,
        "non_auto_error_codes": non_auto_error_codes,
        "latest_apply_effective_status": effective_status,
        "latest_apply_effective_message": account_repair_apply_effective_message(repair_apply),
        "ready_for_retest": ready_for_retest,
        "requires_latest_repair_apply": requires_latest_repair_apply,
        "requires_manual_account_work": requires_manual_account_work,
        "priority_action": priority_action,
        "blocker_codes": blocker_codes,
        "does_not_claim_real_account_pool_ready": bool(readiness == "blocked_by_accounts" and profile_available <= 0),
    }


def build_account_retest_checklist(resolution: dict, repair_summary: dict | None = None) -> list[dict]:
    resolution = resolution if isinstance(resolution, dict) else {}
    repair_summary = repair_summary if isinstance(repair_summary, dict) else {}
    if str(resolution.get("readiness") or "") != "blocked_by_accounts":
        return []
    group = str(resolution.get("profile_group") or repair_summary.get("profile_group") or "当前分组")
    checklist: list[dict] = []
    if bool(resolution.get("requires_manual_account_work")):
        checklist.append(
            {
                "id": "manual_repair_or_replace_accounts",
                "kind": "manual_account_work",
                "required": True,
                "title": "人工修复或替换执行分组账号",
                "profile_group": group,
                "command": "",
                "expected": "至少保留 1 个已登录、内核匹配、代理可用、可手动打开 TikTok 的账号在执行分组内。",
                "blocks_retest_until_done": True,
                "no_browser_started_by_reachops": True,
                "no_submit": True,
            }
        )
    if bool(resolution.get("requires_latest_repair_apply")):
        checklist.append(
            {
                "id": "apply_latest_account_repair_plan",
                "kind": "local_repair_apply",
                "required": True,
                "title": "应用最新账号修复计划",
                "profile_group": group,
                "command": "python tools/reachops_apply_account_repair_plan.py --apply --json",
                "expected": "latest_account_repair_apply.status=applied 且 pending_recheck=true；apply 本身不等于验收通过。",
                "blocks_retest_until_done": True,
                "no_browser_started_by_reachops": True,
                "no_submit": True,
            }
        )
    checklist.extend(
        [
            {
                "id": "client_delivery_retest",
                "kind": "local_gate",
                "required": True,
                "title": "复跑客户端账号门禁",
                "profile_group": group,
                "command": "python tools/reachops_client_delivery_check.py --json",
                "expected": "status=passed, readiness=pass, profile_available>=1, failed_checks=[]。",
                "blocks_retest_until_done": False,
                "no_browser_started_by_reachops": True,
                "no_submit": True,
            },
            {
                "id": "mac_loop_mvp_retest",
                "kind": "local_mvp_gate",
                "required": True,
                "title": "复跑本地 MVP 循环验收",
                "profile_group": group,
                "command": "python tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json",
                "expected": "status=passed 且 mac_loop_ready=true；如仍阻断，继续使用新的账号支持交接包。",
                "blocks_retest_until_done": False,
                "no_browser_started_by_reachops": False,
                "no_submit": True,
            },
            {
                "id": "goal_delivery_retest",
                "kind": "goal_gate",
                "required": True,
                "title": "复跑目标总门禁",
                "profile_group": group,
                "command": "python tools/reachops_goal_delivery_runner.py --json",
                "expected": "local_mvp_ready=true；final_delivery_ready 仍需 Windows 实机验收和授权真实执行证据。",
                "blocks_retest_until_done": False,
                "no_browser_started_by_reachops": True,
                "no_submit": True,
            },
        ]
    )
    return checklist


def build_account_support_handoff(
    acceptance: dict,
    *,
    batch: dict | None = None,
    remediation: dict | None = None,
    account_repair_summary: dict | None = None,
    profile_readiness_handoff: dict | None = None,
    account_repair_apply: dict | None = None,
    account_blocker_resolution: dict | None = None,
) -> dict:
    batch = batch if isinstance(batch, dict) else {}
    remediation = remediation if isinstance(remediation, dict) else {}
    repair_summary = account_repair_summary if isinstance(account_repair_summary, dict) else {}
    profile_readiness = profile_readiness_handoff if isinstance(profile_readiness_handoff, dict) else {}
    repair_apply = account_repair_apply if isinstance(account_repair_apply, dict) else {}
    resolution = account_blocker_resolution if isinstance(account_blocker_resolution, dict) else {}
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    readiness = str(acceptance.get("readiness") or "")
    support_required = readiness == "blocked_by_accounts"
    error_groups = []
    for row in repair_summary.get("error_groups") or []:
        if not isinstance(row, dict):
            continue
        error_groups.append(
            {
                "error": str(row.get("error") or ""),
                "count": int(row.get("count") or 0),
                "profile_ids_sample": [str(item) for item in (row.get("profile_ids_sample") or []) if str(item).strip()][:8],
                "profile_ids_total": int(row.get("profile_ids_total") or 0),
                "summary_only_count": int(row.get("summary_only_count") or 0),
                "recommended_action": str(row.get("recommended_action") or ""),
                "sample_message": str(row.get("sample_message") or ""),
            }
        )
    support_status = str(resolution.get("status") or ("blocked_by_accounts" if support_required else "not_required"))
    priority_action = str(resolution.get("priority_action") or "")
    blocker_codes = [str(item) for item in (resolution.get("blocker_codes") or []) if str(item).strip()]
    if support_required and profile_readiness.get("source_exists"):
        blocker_code = "profile_readiness_probe_manual_repair_required"
        if blocker_code not in blocker_codes and int(profile_readiness.get("available") or 0) <= 0:
            blocker_codes.append(blocker_code)
    if support_required and not priority_action:
        priority_action = "create_or_repair_real_account_pool"
    retest_checklist = build_account_retest_checklist(resolution, repair_summary)
    profile_retest_command = str(profile_readiness.get("retest_command") or "").strip()
    if support_required and profile_retest_command:
        retest_checklist.insert(
            0,
            {
                "id": "profile_readiness_probe_retest",
                "kind": "profile_readiness_probe",
                "required": True,
                "title": "复跑 P0-5 Profile readiness probe",
                "profile_group": str(profile_readiness.get("profile_group") or ""),
                "command": profile_retest_command,
                "expected": "至少 1 个 READY profile；如仍 blocked_by_accounts，继续使用 profile_repair_checklist 修复或替换账号。",
                "blocks_retest_until_done": True,
                "no_browser_started_by_reachops": False,
                "no_submit": True,
            },
        )
    operator_steps = account_operator_steps(error_groups) if support_required and error_groups else [
        str(item) for item in (repair_summary.get("operator_steps") or [])
    ][:8]
    if support_required and profile_readiness.get("source_exists") and profile_readiness.get("next_action"):
        operator_steps = [str(profile_readiness.get("next_action"))] + operator_steps
    profile_error_groups = []
    for row in profile_readiness.get("error_groups") or []:
        if isinstance(row, dict):
            profile_error_groups.append(
                {
                    "error_code": str(row.get("error_code") or ""),
                    "count": int(row.get("count") or 0),
                    "profile_ids_sample": [str(item) for item in (row.get("profile_ids_sample") or [])[:8]],
                    "profile_ids_total": int(row.get("profile_ids_total") or 0),
                    "recommended_action": str(row.get("recommended_action") or ""),
                    "evidence_paths_sample": [str(item) for item in (row.get("evidence_paths_sample") or [])[:4]],
                }
            )
    retest_commands = [
        "python tools/reachops_client_delivery_check.py --json",
        "python tools/reachops_mac_loop_acceptance.py --base-url http://127.0.0.1:8769 --json",
        "python tools/reachops_goal_delivery_runner.py --json",
    ]
    if profile_retest_command:
        retest_commands.insert(0, profile_retest_command)
    return {
        "schema_version": "reachops.account_support_handoff.v1",
        "status": support_status,
        "support_required": support_required,
        "support_case": "account_pool_blocked" if support_required else "not_required",
        "profile_group": str(batch.get("profile_group") or repair_summary.get("profile_group") or resolution.get("profile_group") or ""),
        "batch_id": str(batch.get("id") or repair_summary.get("batch_id") or resolution.get("batch_id") or ""),
        "readiness": readiness,
        "priority_action": priority_action,
        "ready_for_retest": bool(resolution.get("ready_for_retest")),
        "requires_latest_repair_apply": bool(resolution.get("requires_latest_repair_apply")),
        "requires_manual_account_work": bool(resolution.get("requires_manual_account_work")),
        "blocker_codes": blocker_codes,
        "does_not_claim_real_account_pool_ready": bool(resolution.get("does_not_claim_real_account_pool_ready") or support_required),
        "repair_plan": {
            "available": repair_summary.get("status") == "ok",
            "json_path": str(
                remediation.get("latest_account_plan_json_path")
                or remediation.get("account_plan_json_path")
                or repair_summary.get("path")
                or ""
            ),
            "markdown_path": str(
                remediation.get("latest_account_plan_markdown_path")
                or remediation.get("account_plan_markdown_path")
                or ""
            ),
            "profile_count": int(repair_summary.get("total_unique_profiles_by_error") or 0),
            "event_count": int(repair_summary.get("total_error_events_by_error") or 0),
            "summary_only_error_count": int(repair_summary.get("summary_only_error_count") or 0),
            "auto_apply_profile_count": int(resolution.get("repair_plan_auto_apply_profile_count") or 0),
            "non_auto_error_codes": list(resolution.get("non_auto_error_codes") or []),
        },
        "profile_readiness_probe": {
            "available": bool(profile_readiness.get("source_exists")),
            "schema_version": str(profile_readiness.get("schema_version") or ""),
            "status": str(profile_readiness.get("status") or ""),
            "terminal_state": str(profile_readiness.get("terminal_state") or ""),
            "path": str(profile_readiness.get("path") or ""),
            "repair_json_path": str(profile_readiness.get("repair_json_path") or ""),
            "repair_markdown_path": str(profile_readiness.get("repair_markdown_path") or ""),
            "profile_group": str(profile_readiness.get("profile_group") or ""),
            "run_id": str(profile_readiness.get("run_id") or ""),
            "checked": int(profile_readiness.get("checked") or 0),
            "ready_profile_count": int(profile_readiness.get("ready_profile_count") or 0),
            "failed_profile_count": int(profile_readiness.get("failed_profile_count") or 0),
            "error_groups": profile_error_groups,
            "retest_command": profile_retest_command,
            "no_submit": bool(profile_readiness.get("no_submit", True)),
            "no_browser_collection": bool(profile_readiness.get("no_browser_collection", True)),
            "no_action_execution": bool(profile_readiness.get("no_action_execution", True)),
            "does_not_modify_ixbrowser_groups": bool(profile_readiness.get("does_not_modify_ixbrowser_groups", True)),
            "does_not_claim_real_account_pool_ready": bool(
                profile_readiness.get("does_not_claim_real_account_pool_ready", True)
            ),
        },
        "latest_apply": {
            "status": str(repair_apply.get("status") or ""),
            "effective_status": str(resolution.get("latest_apply_effective_status") or account_repair_apply_effective_status(repair_apply)),
            "effective_message": str(
                resolution.get("latest_apply_effective_message") or account_repair_apply_effective_message(repair_apply)
            ),
            "stale": bool(repair_apply.get("stale")),
            "stale_reason": str(repair_apply.get("stale_reason") or ""),
            "pending_recheck": bool(repair_apply.get("pending_recheck")),
            "moved_count": int(repair_apply.get("moved_count") or 0),
            "failed_count": int(repair_apply.get("failed_count") or 0),
        },
        "impacted_accounts": {
            "error_group_count": len(error_groups),
            "error_groups": error_groups,
        },
        "operator_steps": operator_steps[:8],
        "retest_commands": retest_commands,
        "retest_checklist": retest_checklist,
        "acceptance_required": [
            "client_delivery.status=passed",
            "client_delivery.readiness=pass",
            "client_delivery.profile_available>=1",
            "client_delivery.failed_checks=[]",
            "goal_delivery.local_mvp_ready=true",
        ],
        "safety_contract": {
            "manual_apply_required": True,
            "no_browser_started": True,
            "no_submit": True,
            "no_ai_token_used": True,
            "apply_alone_is_not_acceptance": True,
        },
    }


def build_autonomous_product_contract_check() -> dict:
    plan = build_execution_plan(
        target="anti aging serum",
        source_type="keyword",
        mode="collect",
        profile_group="United States",
        profile_limit=3,
        max_videos=3,
        max_comments=20,
        origin="client_delivery_check",
    )
    plan_errors = validate_execution_plan(plan)
    ai_ledger = build_ai_usage_ledger(plan)
    run_session = create_run_session(plan, execution_plan_path="plans/sample_execution_plan.json")
    run_session = transition_run_session(
        run_session,
        "PRECHECK",
        last_stage="delivery contract precheck",
        checkpoint_update={"runtime_state_inferred": "PRECHECK", "log_line_count": 1},
    )
    repair_login = RepairPolicyEngine().decide("LOGIN_REQUIRED", page_state={"state": "LOGIN_REQUIRED"}, max_retries=1)
    repair_dom_stalled = RepairPolicyEngine().decide("DOM_STALLED", page_state={"state": "DOM_STALLED"}, max_retries=1)
    risk_unauthorized = RiskGate().evaluate(
        {"action_type": "comment_reply", "risk_level": "medium", "status": "approved", "execution_confirmed": 1},
        {"profile_id": "delivery-contract-profile"},
        live_submit=True,
        require_authorization=True,
        authorization_decision=None,
    )
    checks = {
        "execution_plan_schema": plan.get("schema_version") == PLAN_SCHEMA_VERSION,
        "execution_plan_valid": not plan_errors,
        "execution_plan_required_sections": all(key in plan for key in ["target", "source_type", "mode", "profile_group", "limits", "authorization", "repair_policy", "risk_policy"]),
        "execution_plan_no_ai_policy": (plan.get("risk_policy") or {}).get("no_ai_token_during_execution") is True,
        "run_session_schema": run_session.get("schema_version") == RUN_SESSION_SCHEMA_VERSION,
        "run_session_state_machine": REQUIRED_AUTONOMOUS_RUN_STATES.issubset(RUN_SESSION_STATES),
        "run_session_checkpointed": (run_session.get("checkpoint") or {}).get("state") == "PRECHECK",
        "run_session_ai_zero": (run_session.get("ai_usage_ledger") or {}).get("no_ai_token_used") is True
        and ((run_session.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("ai_call_count") == 0
        and ((run_session.get("ai_usage_ledger") or {}).get("execution_phase") or {}).get("token_estimate") == 0,
        "page_state_schema": PAGE_STATE_SCHEMA_VERSION == "reachops.page_state.v1",
        "page_state_required_classes": REQUIRED_PAGE_STATES.issubset(PAGE_STATES),
        "repair_policy_schema": repair_login.get("schema_version") == REPAIR_POLICY_SCHEMA_VERSION,
        "repair_login_blocks_and_captures": repair_login.get("cooldown_profile") is True
        and repair_login.get("block_execution") is True
        and any((step or {}).get("step") == "capture_page_state_bundle" for step in repair_login.get("executable_steps") or []),
        "repair_dom_stalled_retries_or_switches": repair_dom_stalled.get("retry_same_profile") is True
        or repair_dom_stalled.get("switch_profile") is True,
        "risk_gate_schema": risk_unauthorized.get("schema_version") == RISK_GATE_SCHEMA_VERSION,
        "risk_gate_blocks_unauthorized_live_submit": risk_unauthorized.get("allowed") is False
        and risk_unauthorized.get("block_execution") is True
        and risk_unauthorized.get("requires_authorization") is True,
        "evidence_bundle_schema": EVIDENCE_BUNDLE_SCHEMA_VERSION == "reachops.evidence_bundle.v1",
        "ai_usage_policy_zero_token": ai_ledger.get("no_ai_token_used") is True
        and (ai_ledger.get("execution_phase") or {}).get("ai_call_count") == 0
        and (ai_ledger.get("execution_phase") or {}).get("token_estimate") == 0,
    }
    return {
        "name": "autonomous_product_core_contract",
        "ok": all(checks.values()),
        "checks": checks,
        "plan_id": plan.get("plan_id", ""),
        "plan_errors": plan_errors,
        "run_state": run_session.get("state", ""),
        "blocked_live_reason": risk_unauthorized.get("reason_code", ""),
    }


def collect_ixbrowser_metadata(group_name: str = "", timeout_seconds: int = 90) -> dict:
    command = [
        sys.executable,
        str(ROOT_DIR / "tools" / "reachops_ixbrowser_profile_metadata_report.py"),
        "--group-name",
        str(group_name or ""),
        "--profile-limit",
        "20",
        "--max-pages",
        "3",
        "--json",
    ]
    try:
        output = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds or 8)),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "safe_read_only": True,
            "open_profile_called": False,
            "error_code": "IXBROWSER_METADATA_TIMEOUT",
            "error_message": f"ixBrowser metadata read timed out after {max(1, int(timeout_seconds or 8))} seconds",
            "profile_count": 0,
            "group_count": 0,
            "selected_profile_count": 0,
        }
    stdout = (output.stdout or "").strip()
    stderr = (output.stderr or "").strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("safe_read_only", True)
    payload.setdefault("open_profile_called", False)
    payload.setdefault("profile_count", 0)
    payload.setdefault("group_count", 0)
    payload.setdefault("selected_profile_count", 0)
    if output.returncode != 0 and not payload.get("error_message"):
        payload["status"] = payload.get("status") or "error"
        payload["error_code"] = payload.get("error_code") or "IXBROWSER_METADATA_READ_FAILED"
        payload["error_message"] = (stderr or stdout or f"metadata command failed: {output.returncode}")[:500]
    if str(payload.get("status") or "") != "ok" or int(payload.get("selected_profile_count") or 0) <= 0:
        fallback = collect_web_ui_group_metadata(group_name)
        if fallback.get("status") == "ok":
            fallback["metadata_fallback_reason"] = payload.get("error_message") or payload.get("error_code") or ""
            return fallback
    return payload


def collect_web_ui_group_metadata(group_name: str = "") -> dict:
    try:
        with urlopen("http://127.0.0.1:8769/api/groups", timeout=130) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        snapshot_path = DEFAULT_BASE_DIR / "config/latest_ixbrowser_groups.json"
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "status": "error",
                "safe_read_only": True,
                "open_profile_called": False,
                "error_code": "WEB_UI_GROUP_METADATA_READ_FAILED",
                "error_message": f"{type(exc).__name__}: {exc}",
                "profile_count": 0,
                "group_count": 0,
                "selected_profile_count": 0,
            }
    groups = [row for row in (payload.get("groups") or []) if isinstance(row, dict)]
    wanted = str(group_name or "").strip().lower()
    selected = next((row for row in groups if str(row.get("name") or "").strip().lower() == wanted), {})
    known_total = sum(int(row.get("count") or 0) for row in groups if row.get("count_known"))
    return {
        "status": "ok",
        "source": "web_ui_groups_api",
        "safe_read_only": True,
        "open_profile_called": False,
        "profile_count": known_total,
        "group_count": len(groups),
        "selected_profile_count": int(selected.get("count") or 0) if selected else 0,
        "selected_group_id": str(selected.get("group_id") or ""),
        "selected_profile_sample_count": 0,
        "group_name_filter": group_name,
        "groups": [
            {
                "group_id": str(row.get("group_id") or ""),
                "group_name": str(row.get("name") or ""),
                "profile_count": int(row.get("count") or 0),
                "count_known": bool(row.get("count_known")),
            }
            for row in groups
        ],
        "selected_profiles": [],
        "notes": ["Read from local Web UI /api/groups. This is read-only and does not open profiles or submit actions."],
    }


def selected_group_count_consistency(ixbrowser_metadata: dict) -> dict:
    selected_count = int(ixbrowser_metadata.get("selected_profile_count") or 0)
    selected_group_id = str(ixbrowser_metadata.get("selected_group_id") or "").strip()
    selected_group_name = str(ixbrowser_metadata.get("group_name_filter") or "").strip().lower()
    groups = [row for row in (ixbrowser_metadata.get("groups") or []) if isinstance(row, dict)]
    if selected_count <= 0 or not groups:
        return {
            "ok": True,
            "required": False,
            "selected_profile_count": selected_count,
            "selected_group_id": selected_group_id,
            "group_name_filter": ixbrowser_metadata.get("group_name_filter", ""),
            "matched_group_count": 0,
            "matched_group_count_known": False,
            "matched_group_count_source": "",
        }
    matched = {}
    for row in groups:
        group_id = str(row.get("group_id") or "").strip()
        group_name = str(row.get("group_name") or row.get("name") or "").strip().lower()
        if selected_group_id and group_id == selected_group_id:
            matched = row
            break
        if selected_group_name and group_name == selected_group_name:
            matched = row
            break
    matched_count = int(matched.get("profile_count") or matched.get("count") or 0) if matched else 0
    matched_known = bool(matched.get("count_known")) if matched else False
    return {
        "ok": bool(matched and matched_known and matched_count > 0),
        "required": True,
        "selected_profile_count": selected_count,
        "selected_group_id": selected_group_id,
        "group_name_filter": ixbrowser_metadata.get("group_name_filter", ""),
        "matched_group_count": matched_count,
        "matched_group_count_known": matched_known,
        "matched_group_count_source": str(matched.get("count_source") or "") if matched else "",
    }


def latest_account_repair_apply_status(base_dir: Path, log_lines: list[str], profile_group: str = "", batch_id: str = "") -> dict:
    result_path = base_dir / "reports" / "acceptance_remediation" / "latest_account_repair_apply.json"
    payload: dict = {}
    if result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            payload = {"status": "read_failed", "error": f"{type(exc).__name__}: {exc}"}
        payload["source"] = "latest_account_repair_apply.json"
        payload["path"] = str(result_path)
        try:
            payload["mtime"] = result_path.stat().st_mtime
        except OSError:
            payload["mtime"] = 0
    if not payload or payload.get("status") == "read_failed":
        for line in reversed(log_lines or []):
            match = ACCOUNT_REPAIR_APPLY_RE.search(line)
            if not match:
                continue
            payload = {
                "status": match.group("status"),
                "profile_group": match.group("group").strip(),
                "selected_count": int(match.group("selected") or 0),
                "moved_count": int(match.group("moved") or 0),
                "failed_count": int(match.group("failed") or 0),
                "source": "growth_ops_runtime.log",
            }
            break
    if not payload:
        return {}
    results = payload.get("results")
    if isinstance(results, list):
        normalized_selected = len([row for row in results if isinstance(row, dict)])
        normalized_moved = len([row for row in results if isinstance(row, dict) and row.get("ok")])
        normalized_failed = len(
            [
                row
                for row in results
                if isinstance(row, dict) and row.get("attempted") and not row.get("ok")
            ]
        )
        if (
            int(payload.get("selected_count") or 0) != normalized_selected
            or int(payload.get("moved_count") or 0) != normalized_moved
            or int(payload.get("failed_count") or 0) != normalized_failed
        ):
            payload["count_normalized_from_results"] = True
        payload["selected_count"] = normalized_selected
        payload["moved_count"] = normalized_moved
        payload["failed_count"] = normalized_failed
    wanted_group = str(profile_group or "").strip().lower()
    payload_group = str(payload.get("profile_group") or "").strip().lower()
    payload["same_group"] = bool(not wanted_group or not payload_group or wanted_group == payload_group)
    payload_batch_id = str(payload.get("batch_id") or "").strip()
    current_batch_id = str(batch_id or "").strip()
    stale_reason = ""
    if current_batch_id and payload_batch_id and payload_batch_id != current_batch_id:
        stale_reason = "account_repair_apply_batch_mismatch"
    elif current_batch_id and not payload_batch_id and payload.get("source") == "latest_account_repair_apply.json":
        plan_path = base_dir / "reports" / "acceptance_remediation" / "latest_account_repair_plan.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_batch_id = str(plan.get("batch_id") or "").strip()
            plan_mtime = plan_path.stat().st_mtime
        except Exception:
            plan_batch_id = ""
            plan_mtime = 0
        if plan_batch_id == current_batch_id and plan_mtime > float(payload.get("mtime") or 0):
            stale_reason = "newer_account_repair_plan_for_current_batch"
    payload["same_batch"] = bool(
        not current_batch_id
        or (not payload_batch_id and not stale_reason)
        or payload_batch_id == current_batch_id
    )
    if stale_reason:
        payload["stale"] = True
        payload["stale_reason"] = stale_reason
    payload["pending_recheck"] = bool(
        payload.get("same_group")
        and not payload.get("stale")
        and str(payload.get("status") or "") == "applied"
        and int(payload.get("moved_count") or 0) > 0
        and int(payload.get("failed_count") or 0) == 0
    )
    payload["effective_status"] = account_repair_apply_effective_status(payload)
    effective_message = account_repair_apply_effective_message(payload)
    if effective_message:
        payload["effective_message"] = effective_message
    return payload


def profile_remediation_csv_quality(path: Path | str, expected_count: int = 0) -> dict:
    csv_path = Path(str(path or ""))
    if not csv_path.is_file():
        return {
            "ok": False,
            "path": str(csv_path) if str(csv_path) else "",
            "row_count": 0,
            "unique_profile_count": 0,
            "duplicate_profile_ids": [],
            "missing_profile_id_count": 0,
            "expected_count": int(expected_count or 0),
            "error": "missing_csv",
        }
    try:
        with csv_path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception as exc:
        return {
            "ok": False,
            "path": str(csv_path),
            "row_count": 0,
            "unique_profile_count": 0,
            "duplicate_profile_ids": [],
            "missing_profile_id_count": 0,
            "expected_count": int(expected_count or 0),
            "error": f"{type(exc).__name__}: {exc}",
        }
    profile_ids = [str(row.get("profile_id") or "").strip() for row in rows]
    non_empty = [profile_id for profile_id in profile_ids if profile_id]
    duplicates = sorted({profile_id for profile_id in non_empty if non_empty.count(profile_id) > 1})
    missing_count = len([profile_id for profile_id in profile_ids if not profile_id])
    expected = int(expected_count or 0)
    count_ok = expected <= 0 or len(rows) == expected
    return {
        "ok": bool(rows) and not duplicates and missing_count == 0 and count_ok,
        "path": str(csv_path),
        "row_count": len(rows),
        "unique_profile_count": len(set(non_empty)),
        "duplicate_profile_ids": duplicates,
        "missing_profile_id_count": missing_count,
        "expected_count": expected,
        "error": "",
    }


def summarize_optional_account_repair_plan(path_value: str | Path) -> dict:
    raw = str(path_value or "").strip()
    if not raw:
        return {"status": "not_available", "path": "", "reason": "account_repair_plan_not_generated"}
    path = Path(raw)
    if not path.is_file():
        return {"status": "not_available", "path": str(path), "reason": "account_repair_plan_not_found"}
    return summarize_account_repair_plan(path)


def latest_profile_readiness_probe_handoff(root: Path = ROOT_DIR) -> dict:
    probe_root = root / "reports" / "reachops" / "profile_readiness_probe"
    candidates = sorted(
        probe_root.glob("*/reports/profile_readiness_probe.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    if not candidates:
        return {
            "schema_version": "reachops.profile_readiness_handoff.v1",
            "source_exists": False,
            "status": "not_available",
            "reason": "profile_readiness_probe_not_generated",
            "does_not_claim_real_account_pool_ready": True,
        }
    report_path = candidates[0]
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema_version": "reachops.profile_readiness_handoff.v1",
            "source_exists": False,
            "status": "read_failed",
            "path": str(report_path),
            "reason": f"{type(exc).__name__}: {exc}",
            "does_not_claim_real_account_pool_ready": True,
        }
    if not isinstance(payload, dict):
        payload = {}
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    repair_path = Path(str(outputs.get("repair_json") or report_path.with_name("profile_repair_checklist.json")))
    repair = payload.get("repair_checklist") if isinstance(payload.get("repair_checklist"), dict) else {}
    if repair_path.is_file():
        try:
            loaded_repair = json.loads(repair_path.read_text(encoding="utf-8"))
            if isinstance(loaded_repair, dict):
                repair = loaded_repair
        except Exception:
            pass
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    error_groups = []
    for row in repair.get("error_groups") or []:
        if not isinstance(row, dict):
            continue
        profile_ids = [str(item) for item in (row.get("profile_ids") or []) if str(item).strip()]
        evidence_paths = [str(item) for item in (row.get("evidence_paths") or []) if str(item).strip()]
        error_groups.append(
            {
                "error_code": str(row.get("error_code") or ""),
                "count": int(row.get("count") or 0),
                "profile_ids_sample": profile_ids[:8],
                "profile_ids_total": len(profile_ids),
                "recommended_action": str(row.get("recommended_action") or ""),
                "evidence_paths_sample": evidence_paths[:4],
            }
        )
    ready_ids = [str(item) for item in (repair.get("ready_profile_ids") or []) if str(item).strip()]
    failed_ids = [str(item) for item in (repair.get("failed_profile_ids") or []) if str(item).strip()]
    return {
        "schema_version": "reachops.profile_readiness_handoff.v1",
        "source_exists": True,
        "status": str(payload.get("status") or repair.get("status") or ""),
        "terminal_state": str(payload.get("terminal_state") or ""),
        "path": str(report_path),
        "repair_json_path": str(repair_path),
        "repair_markdown_path": str(outputs.get("repair_markdown") or report_path.with_name("profile_repair_checklist.md")),
        "profile_group": str(payload.get("profile_group") or repair.get("profile_group") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "checked": int(summary.get("checked") or 0),
        "available": int(summary.get("available") or 0),
        "unavailable": int(summary.get("unavailable") or 0),
        "ready_profile_count": len(ready_ids),
        "failed_profile_count": len(failed_ids),
        "error_groups": error_groups,
        "retest_command": str(repair.get("retest_command") or ""),
        "next_action": str(repair.get("next_action") or payload.get("next_action") or ""),
        "no_submit": bool(payload.get("no_submit", True) and repair.get("no_submit", True)),
        "no_browser_collection": bool(payload.get("no_browser_collection", True)),
        "no_action_execution": bool(payload.get("no_action_execution", True)),
        "does_not_modify_ixbrowser_groups": bool(repair.get("does_not_modify_ixbrowser_groups", True)),
        "does_not_claim_real_account_pool_ready": int(summary.get("available") or 0) <= 0,
    }


def build_delivery_check(
    base_dir: Path = DEFAULT_BASE_DIR,
    ixbrowser_metadata: dict | None = None,
    collect_metadata: bool = False,
) -> dict:
    db_path = base_dir / "data/growth_intelligence/growth_intelligence.db"
    log_path = base_dir / "logs/growth_ops_runtime.log"
    batch = latest_batch(db_path)
    preflight = latest_profile_preflight(db_path)
    log_lines = read_lines(log_path)
    acceptance = derive_acceptance(batch, preflight, log_lines)
    operations = {}
    try:
        operations = build_operations_payload(db_path, batch, acceptance, log_lines)
        annotate_acceptance_with_operations(acceptance, operations, batch)
    except Exception:
        operations = {}
    ix_refresh = acceptance.get("ixbrowser_refresh_summary") or {}
    should_collect_ixbrowser_metadata = bool(
        collect_metadata
        and (ix_refresh.get("seen") or acceptance.get("readiness") in {"blocked_by_environment", "blocked_by_accounts"})
    )
    if ixbrowser_metadata is None and should_collect_ixbrowser_metadata:
        ixbrowser_metadata = collect_ixbrowser_metadata(str(batch.get("profile_group") or ""))
    ixbrowser_metadata = ixbrowser_metadata or {}
    selected_profile_count = int(ixbrowser_metadata.get("selected_profile_count") or 0)
    if selected_profile_count > 0 and acceptance.get("readiness") != "pass":
        selected_summary = acceptance.get("selected_profile_summary") or {}
        if selected_summary.get("seen") and int(selected_summary.get("candidates") or 0) <= 0:
            profile_group = str(batch.get("profile_group") or "").strip() or "当前选择分组"
            stale_blocker = f"最近一次运行日志显示 {profile_group} 候选账号为 0，但当前 ixBrowser 只读元数据已确认该分组有 {selected_profile_count} 个配置；需要用最新分组读取逻辑重新开始获客复测。"
            blockers = [item for item in (acceptance.get("blockers") or []) if "候选账号为 0" not in str(item)]
            blockers.insert(0, stale_blocker)
            acceptance["blockers"] = blockers
            actions = [item for item in (acceptance.get("next_actions") or []) if "手动打开" not in str(item)]
            actions.insert(0, "当前配置列表已可读取账号数量，请重新点击开始获客生成新的账号预检和采集证据。")
            acceptance["next_actions"] = actions
    profile_details = acceptance.get("profile_preflight_details") or []
    has_runtime_evidence = bool(batch or preflight or log_lines)
    remediation = write_remediation_report(
        base_dir,
        batch,
        profile_details,
        preflight_errors=(acceptance.get("profile_preflight_summary") or {}).get("errors") or {},
    )
    account_repair_summary = summarize_optional_account_repair_plan(
        remediation.get("latest_account_plan_json_path") or remediation.get("account_plan_json_path") or ""
    )
    profile_readiness_handoff = latest_profile_readiness_probe_handoff(ROOT_DIR)
    account_repair_apply = latest_account_repair_apply_status(
        base_dir,
        log_lines,
        str(batch.get("profile_group") or ""),
        str(batch.get("id") or ""),
    )
    if (
        str(account_repair_apply.get("status") or "") == "no_applicable_profiles"
        and acceptance.get("readiness") == "blocked_by_accounts"
    ):
        acceptance["blockers"] = [
            "最新账号修复计划没有默认可自动隔离的账号，不能把账号修复视为完成。"
        ] + list(acceptance.get("blockers") or [])
        acceptance["next_actions"] = [
            "手动打开受影响账号，确认登录状态、内核版本、代理和 TikTok 页面加载；不可用账号再移入封禁账号分组。",
            "至少保留 1 个已登录、内核匹配、可手动打开 TikTok 的账号在执行分组内，再复跑真实执行复测。",
        ] + list(acceptance.get("next_actions") or [])
    elif account_repair_apply.get("stale") and acceptance.get("readiness") == "blocked_by_accounts":
        group = str(batch.get("profile_group") or account_repair_apply.get("profile_group") or "当前分组")
        acceptance["blockers"] = [
            f"旧账号修复结果已失效：{group} 分组已经产生新的账号阻断批次，不能继续用旧修复结果复测。"
        ] + list(acceptance.get("blockers") or [])
        acceptance["next_actions"] = [
            "先执行最新账号修复计划，确认至少 1 个已登录、内核匹配、可手动打开 TikTok 的账号保留在执行分组内。",
            f"修复后再复测 {group} 分组；系统会重新读取分组、重新选择剩余账号并重新预检。",
        ] + list(acceptance.get("next_actions") or [])
    elif account_repair_apply_effective_status(account_repair_apply) == "group_mismatch" and acceptance.get("readiness") == "blocked_by_accounts":
        current_group = str(batch.get("profile_group") or "当前分组")
        apply_group = str(account_repair_apply.get("profile_group") or "其他分组")
        acceptance["blockers"] = [
            f"账号修复结果属于 {apply_group} 分组，不能用于当前 {current_group} 分组验收。"
        ] + list(acceptance.get("blockers") or [])
        acceptance["next_actions"] = [
            f"执行 {current_group} 分组的最新账号修复计划，再重新预检当前分组。",
        ] + list(acceptance.get("next_actions") or [])
    elif account_repair_apply.get("pending_recheck") and acceptance.get("readiness") == "blocked_by_accounts":
        group = str(batch.get("profile_group") or account_repair_apply.get("profile_group") or "当前分组")
        moved = int(account_repair_apply.get("moved_count") or 0)
        acceptance["blockers"] = [
            f"账号修复已执行：已隔离 {moved} 个硬失败账号，当前状态为等待重新预检，不应继续读取旧失败批次作为最终结论。"
        ] + list(acceptance.get("blockers") or [])
        acceptance["next_actions"] = [
            f"点击开始获客复测 {group} 分组；系统会重新读取分组、重新选择剩余账号并重新预检。",
            "如果复测仍为 0 个可用账号，按新的账号修复计划继续隔离或补充已登录且内核匹配的账号。",
        ] + list(acceptance.get("next_actions") or [])

    checks = []
    checks.append(
        {
            "name": "runtime:evidence",
            "ok": has_runtime_evidence,
            "db_path": str(db_path),
            "log_path": str(log_path),
            "message": "found latest runtime batch/log evidence" if has_runtime_evidence else "no runtime batch/log evidence available",
        }
    )
    entrypoints = WINDOWS_ENTRYPOINTS if sys.platform.startswith("win") else ENTRYPOINTS
    for name in entrypoints:
        path = ROOT_DIR / name
        ok = path.exists() if sys.platform.startswith("win") else path.exists() and is_executable(path)
        checks.append(
            {
                "name": f"entrypoint:{name}",
                "ok": ok,
                "path": str(path),
            }
        )

    for key in [
        "csv_path",
        "json_path",
        "markdown_path",
        "guide_path",
        "index_path",
        "manifest_path",
        "latest_csv_path",
        "latest_json_path",
        "latest_markdown_path",
        "latest_guide_path",
        "latest_index_path",
        "latest_manifest_path",
        "account_plan_json_path",
        "account_plan_markdown_path",
        "latest_account_plan_json_path",
        "latest_account_plan_markdown_path",
    ]:
        raw_path = str(remediation.get(key) or "")
        path = Path(raw_path) if raw_path else None
        required = bool(profile_details)
        checks.append(
            {
                "name": f"report:{key}",
                "ok": (not required) or bool(path and path.is_file()),
                "required": required,
                "path": str(path) if path else "",
            }
        )

    if profile_details:
        checks.append(
            {
                "name": "report:profile_remediation_unique",
                "required": True,
                **profile_remediation_csv_quality(
                    remediation.get("latest_csv_path") or remediation.get("csv_path") or "",
                    int(remediation.get("count") or 0),
                ),
            }
        )

    html = html_page().decode("utf-8")
    missing_markers = [marker for marker in REQUIRED_WEB_UI_MARKERS if marker not in html]
    checks.append(
        {
            "name": "web_ui_contract",
            "ok": not missing_markers and "验收包首页 HTML" in html and "/api/download?path=" in html,
            "missing_markers": missing_markers,
        }
    )
    version_payload = build_version_payload()
    checks.append(
        {
            "name": "web_ui_version_api_local_client_identity",
            "ok": version_payload.get("status") == "ok"
            and version_payload.get("version") == WEB_UI_VERSION
            and version_payload.get("display_version") == CLIENT_DISPLAY_VERSION
            and version_payload.get("client_surface") == "local_client_console"
            and version_payload.get("display_name") == "ReachOps Local Client Console"
            and version_payload.get("loopback_host") == "127.0.0.1"
            and version_payload.get("no_browser_started") is True
            and version_payload.get("no_submit") is True,
            "version_payload": {
                "version": version_payload.get("version"),
                "display_version": version_payload.get("display_version"),
                "client_surface": version_payload.get("client_surface"),
                "display_name": version_payload.get("display_name"),
                "loopback_host": version_payload.get("loopback_host"),
                "no_browser_started": version_payload.get("no_browser_started"),
                "no_submit": version_payload.get("no_submit"),
            },
        }
    )
    checks.append(build_autonomous_product_contract_check())

    manifest_path = Path(str(remediation.get("manifest_path") or ""))
    manifest = {}
    if str(manifest_path) != "." and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    checks.append(
        {
            "name": "manifest:entrypoints",
            "ok": (not profile_details)
            or all(
                key in (manifest.get("client_entrypoints") or {})
                for key in ["local_client_console", "web_ui", "unified_mac_client", "native_mac_ui", "real_retest"]
            ),
            "required": bool(profile_details),
            "path": str(manifest_path),
        }
    )
    web_operator_api = manifest.get("web_operator_api") if isinstance(manifest.get("web_operator_api"), dict) else {}
    checks.append(
        {
            "name": "manifest:web_operator_final_status_api",
            "ok": (not profile_details)
            or (
                web_operator_api.get("final_status") == "/api/final-status"
                and web_operator_api.get("acceptance") == "/api/acceptance"
                and web_operator_api.get("final_status_no_browser_started") is True
                and web_operator_api.get("final_status_no_submit") is True
            ),
            "required": bool(profile_details),
            "path": str(manifest_path),
        }
    )
    manifest_repair_summary = (
        manifest.get("account_repair_summary") if isinstance(manifest.get("account_repair_summary"), dict) else {}
    )
    manifest_error_groups = manifest_repair_summary.get("error_groups") or []
    def manifest_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    manifest_unique_profiles = manifest_int(manifest_repair_summary.get("total_unique_profiles_by_error"))
    manifest_error_events = manifest_int(manifest_repair_summary.get("total_error_events_by_error"))
    manifest_summary_only = manifest_int(manifest_repair_summary.get("summary_only_error_count"))
    checks.append(
        {
            "name": "manifest:account_repair_summary",
            "ok": (not profile_details)
            or (
                isinstance(manifest_error_groups, list)
                and len(manifest_error_groups) > 0
                and manifest_unique_profiles >= 0
                and manifest_error_events >= len(profile_details)
                and manifest_summary_only >= 0
            ),
            "required": bool(profile_details),
            "path": str(manifest_path),
            "total_unique_profiles_by_error": manifest_unique_profiles,
            "total_error_events_by_error": manifest_error_events,
            "summary_only_error_count": manifest_summary_only,
            "error_group_count": len(manifest_error_groups) if isinstance(manifest_error_groups, list) else 0,
        }
    )
    checks.append(
        {
            "name": "acceptance:current_state_known",
            "ok": acceptance.get("readiness") in {"pass", "partial", "blocked_by_accounts", "blocked_by_environment", "not_started"},
            "readiness": acceptance.get("readiness"),
        }
    )
    if ixbrowser_metadata:
        count_consistency = selected_group_count_consistency(ixbrowser_metadata)
        checks.append(
            {
                "name": "ixbrowser:list_api_metadata",
                "ok": bool(ixbrowser_metadata.get("safe_read_only")) and not bool(ixbrowser_metadata.get("open_profile_called")),
                "status": ixbrowser_metadata.get("status", ""),
                "profile_count": int(ixbrowser_metadata.get("profile_count") or 0),
                "group_count": int(ixbrowser_metadata.get("group_count") or 0),
                "selected_profile_count": int(ixbrowser_metadata.get("selected_profile_count") or 0),
                "safe_read_only": bool(ixbrowser_metadata.get("safe_read_only")),
                "open_profile_called": bool(ixbrowser_metadata.get("open_profile_called")),
            }
        )
        checks.append({"name": "ixbrowser:selected_group_count_consistent", **count_consistency})
    checks.append(
        {
            "name": "acceptance:ready",
            "ok": acceptance.get("readiness") == "pass",
            "readiness": acceptance.get("readiness"),
            "message": "client acceptance evidence is complete"
            if acceptance.get("readiness") == "pass"
            else "client acceptance is not complete; inspect blockers and next_actions",
        }
    )

    contract_checks = [item for item in checks if item.get("name") != "acceptance:ready"]
    contract_ok = all(item.get("ok") for item in contract_checks)
    acceptance_ready = acceptance.get("readiness") == "pass"
    failed_checks = [str(item.get("name") or "") for item in checks if not item.get("ok")]
    ok = contract_ok and acceptance_ready
    status = delivery_status(contract_ok, acceptance_ready, str(acceptance.get("readiness") or ""))
    real_pilot_evidence = build_real_pilot_evidence_boundary(
        acceptance,
        operations,
        status=status,
        contract_ok=contract_ok,
        acceptance_ready=acceptance_ready,
        account_repair_summary=account_repair_summary,
        account_repair_apply=account_repair_apply,
    )
    account_blocker_resolution = build_account_blocker_resolution(
        acceptance,
        batch=batch,
        account_repair_summary=account_repair_summary,
        account_repair_apply=account_repair_apply,
    )
    account_support_handoff = build_account_support_handoff(
        acceptance,
        batch=batch,
        remediation=remediation,
        account_repair_summary=account_repair_summary,
        profile_readiness_handoff=profile_readiness_handoff,
        account_repair_apply=account_repair_apply,
        account_blocker_resolution=account_blocker_resolution,
    )

    return {
        "root_dir": str(ROOT_DIR),
        "base_dir": str(base_dir),
        "delivery_check_path": str(base_dir / "reports" / "acceptance_remediation" / "latest_delivery_check.json"),
        "support_account_handoff_path": str(base_dir / "reports" / "support" / "account_support_handoff.json"),
        "status": status,
        "readiness": acceptance.get("readiness"),
        "batch_id": batch.get("id", ""),
        "profile_available": (acceptance.get("checks") or {}).get("profile_available_count", 0),
        "contract_ok": contract_ok,
        "acceptance_ready": acceptance_ready,
        "final_delivery_ready": ok,
        "blockers": acceptance.get("blockers") or [],
        "next_actions": acceptance.get("next_actions") or [],
        "no_action_reason": acceptance.get("no_action_reason") or {},
        "operation_counts": (operations.get("counts") if isinstance(operations, dict) else {}) or {},
        "real_pilot_evidence": real_pilot_evidence,
        "account_blocker_resolution": account_blocker_resolution,
        "account_support_handoff": account_support_handoff,
        "profile_readiness_handoff": profile_readiness_handoff,
        "remediation_report": remediation,
        "account_repair_summary": account_repair_summary,
        "account_repair_apply": account_repair_apply,
        "ixbrowser_metadata": ixbrowser_metadata,
        "checks": checks,
        "failed_checks": failed_checks,
        "ok": ok,
    }


def build_account_support_handoff_diagnostic(payload: dict) -> dict:
    handoff = payload.get("account_support_handoff") if isinstance(payload.get("account_support_handoff"), dict) else {}
    blocker_resolution = (
        payload.get("account_blocker_resolution")
        if isinstance(payload.get("account_blocker_resolution"), dict)
        else {}
    )
    safety_contract = handoff.get("safety_contract") if isinstance(handoff.get("safety_contract"), dict) else {}
    profile_readiness = (
        handoff.get("profile_readiness_probe")
        if isinstance(handoff.get("profile_readiness_probe"), dict)
        else payload.get("profile_readiness_handoff")
        if isinstance(payload.get("profile_readiness_handoff"), dict)
        else {}
    )
    return {
        "schema_version": "reachops.account_support_handoff_diagnostic.v1",
        "generated_from": "reachops_client_delivery_check",
        "delivery_check_path": str(payload.get("delivery_check_path") or ""),
        "status": str(payload.get("status") or ""),
        "readiness": str(payload.get("readiness") or ""),
        "final_delivery_ready": bool(payload.get("final_delivery_ready")),
        "failed_checks": [str(item) for item in (payload.get("failed_checks") or [])],
        "support_required": bool(handoff.get("support_required")),
        "support_case": str(handoff.get("support_case") or "not_required"),
        "profile_group": str(handoff.get("profile_group") or ""),
        "batch_id": str(handoff.get("batch_id") or payload.get("batch_id") or ""),
        "priority_action": str(handoff.get("priority_action") or ""),
        "ready_for_retest": bool(handoff.get("ready_for_retest")),
        "requires_latest_repair_apply": bool(handoff.get("requires_latest_repair_apply")),
        "requires_manual_account_work": bool(handoff.get("requires_manual_account_work")),
        "blocker_codes": [str(item) for item in (handoff.get("blocker_codes") or blocker_resolution.get("blocker_codes") or []) if str(item).strip()],
        "does_not_claim_real_account_pool_ready": bool(handoff.get("does_not_claim_real_account_pool_ready", True)),
        "account_blocker_resolution": blocker_resolution,
        "account_support_handoff": handoff,
        "profile_readiness_probe": profile_readiness,
        "retest_commands": [str(item) for item in (handoff.get("retest_commands") or [])],
        "retest_checklist": [
            item for item in (handoff.get("retest_checklist") or []) if isinstance(item, dict)
        ],
        "acceptance_required": [str(item) for item in (handoff.get("acceptance_required") or [])],
        "safety_contract": safety_contract,
        "no_browser_started": bool(safety_contract.get("no_browser_started", True)),
        "no_submit": bool(safety_contract.get("no_submit", True)),
        "support_bundle_redacted_by_default": True,
    }


def default_support_account_handoff_path(payload: dict, delivery_check_path: Path | None = None) -> Path:
    base_dir = str(payload.get("base_dir") or "").strip()
    if base_dir:
        return Path(base_dir) / "reports" / "support" / "account_support_handoff.json"
    if delivery_check_path and delivery_check_path.parent.name == "acceptance_remediation":
        reports_dir = delivery_check_path.parent.parent
        if reports_dir.name == "reports":
            return reports_dir / "support" / "account_support_handoff.json"
    if delivery_check_path:
        return delivery_check_path.with_name("account_support_handoff.json")
    return Path("reports") / "support" / "account_support_handoff.json"


def write_account_support_handoff_diagnostic(payload: dict, output_path: str | Path | None = None) -> Path:
    out_path = Path(output_path or payload.get("support_account_handoff_path") or "")
    if not str(out_path):
        delivery_check_path = Path(str(payload.get("delivery_check_path") or "")) if payload.get("delivery_check_path") else None
        out_path = default_support_account_handoff_path(payload, delivery_check_path)
    payload["support_account_handoff_path"] = str(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic = build_account_support_handoff_diagnostic(payload)
    out_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_delivery_check(payload: dict, output_path: str | Path | None = None) -> Path:
    out_path = Path(output_path or payload.get("delivery_check_path") or "")
    if not str(out_path):
        out_path = Path(payload["base_dir"]) / "reports" / "acceptance_remediation" / "latest_delivery_check.json"
    payload["delivery_check_path"] = str(out_path)
    payload["support_account_handoff_path"] = str(
        payload.get("support_account_handoff_path") or default_support_account_handoff_path(payload, out_path)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not payload.get("ixbrowser_metadata") and out_path.is_file():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
        previous_metadata = previous.get("ixbrowser_metadata") if isinstance(previous, dict) else {}
        if isinstance(previous_metadata, dict) and previous_metadata:
            payload["ixbrowser_metadata"] = previous_metadata
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_account_support_handoff_diagnostic(payload)
    return out_path


def account_repair_summary_lines(payload: dict, limit: int = 4) -> list[str]:
    summary = payload.get("account_repair_summary") if isinstance(payload, dict) else {}
    if not isinstance(summary, dict) or summary.get("status") != "ok":
        return []
    groups = [row for row in (summary.get("error_groups") or []) if isinstance(row, dict)]
    if not groups:
        return []
    lines = [
        "account_repair_summary="
        f"group={summary.get('profile_group') or '-'} "
        f"profiles={summary.get('total_unique_profiles_by_error') or 0} "
        f"events={summary.get('total_error_events_by_error') or summary.get('total_unique_profiles_by_error') or 0} "
        f"summary_only={summary.get('summary_only_error_count') or 0}"
    ]
    for row in groups[: max(1, int(limit or 1))]:
        samples = [str(item) for item in (row.get("profile_ids_sample") or []) if str(item).strip()]
        sample_text = f" sample={','.join(samples[:8])}" if samples else ""
        profile_total = int(row.get("profile_ids_total") or len(samples))
        summary_only_count = int(row.get("summary_only_count") or 0)
        coverage_text = f" profile_ids={profile_total} summary_only={summary_only_count}"
        action = str(row.get("recommended_action") or "").strip()
        action_text = f" action={action}" if action else ""
        lines.append(
            f"  {row.get('error') or '-'} count={row.get('count') or 0}"
            f"{coverage_text}{sample_text}{action_text}"
        )
    after_repair = [str(item).strip() for item in (summary.get("acceptance_after_repair") or []) if str(item).strip()]
    if after_repair:
        lines.append("after_repair_acceptance=" + " | ".join(after_repair[:4]))
    apply_status = payload.get("account_repair_apply") if isinstance(payload.get("account_repair_apply"), dict) else {}
    safety = apply_status.get("safety_contract") if isinstance(apply_status.get("safety_contract"), dict) else {}
    if safety:
        lines.append(
            "account_repair_safety="
            f"manual_apply_required={str(bool(safety.get('manual_apply_required', True))).lower()} "
            f"operator_confirmed_apply={str(bool(safety.get('operator_confirmed_apply'))).lower()} "
            f"hard_blocker_only={str(bool(safety.get('hard_blocker_only', True))).lower()} "
            f"no_browser_started={str(bool(safety.get('no_browser_started', True))).lower()} "
            f"no_submit={str(bool(safety.get('no_submit', True))).lower()} "
            f"no_ai_token_used={str(bool(safety.get('no_ai_token_used', True))).lower()}"
        )
    lines.append(
        "after_repair_commands="
        "python tools/reachops_client_delivery_check.py --json | "
        "python tools/reachops_mac_self_check.py --json"
    )
    return lines


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps Mac client delivery acceptance evidence.")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR), help="Runtime directory that contains data/ and logs/.")
    parser.add_argument("--output", default="", help="Path for latest_delivery_check.json. Defaults under base-dir reports.")
    parser.add_argument(
        "--collect-live-metadata",
        action="store_true",
        help="Also run the read-only ixBrowser/Web UI group metadata probe. Omitted by PM gates to stay deterministic.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_delivery_check(Path(args.base_dir), collect_metadata=bool(args.collect_live_metadata))
    out_path = write_delivery_check(payload, args.output or None)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps client delivery check: {str(payload.get('status') or '').upper()}")
        print(f"readiness={payload.get('readiness')} contract_ok={payload.get('contract_ok')} acceptance_ready={payload.get('acceptance_ready')}")
        if payload.get("failed_checks"):
            print(f"failed_checks={','.join(payload['failed_checks'])}")
        for line in account_repair_summary_lines(payload):
            print(line)
        print(f"report={out_path}")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
