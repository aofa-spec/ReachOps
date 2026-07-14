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


def build_real_pilot_evidence_boundary(
    acceptance: dict,
    operations: dict,
    *,
    status: str,
    contract_ok: bool,
    acceptance_ready: bool,
) -> dict:
    counts = operations.get("counts") if isinstance(operations, dict) else {}
    counts = counts if isinstance(counts, dict) else {}
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
        "external_acceptance_pending": blockers,
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
    stale_reason = ""
    if batch_id and not payload_batch_id and payload.get("source") == "latest_account_repair_apply.json":
        plan_path = base_dir / "reports" / "acceptance_remediation" / "latest_account_repair_plan.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_batch_id = str(plan.get("batch_id") or "").strip()
            plan_mtime = plan_path.stat().st_mtime
        except Exception:
            plan_batch_id = ""
            plan_mtime = 0
        if plan_batch_id == str(batch_id or "") and plan_mtime > float(payload.get("mtime") or 0):
            stale_reason = "newer_account_repair_plan_for_current_batch"
    payload["same_batch"] = bool(
        not batch_id
        or (not payload_batch_id and not stale_reason)
        or payload_batch_id == str(batch_id or "")
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
    account_repair_apply = latest_account_repair_apply_status(
        base_dir,
        log_lines,
        str(batch.get("profile_group") or ""),
        str(batch.get("id") or ""),
    )
    if account_repair_apply.get("pending_recheck") and acceptance.get("readiness") == "blocked_by_accounts":
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
    )

    return {
        "root_dir": str(ROOT_DIR),
        "base_dir": str(base_dir),
        "delivery_check_path": str(base_dir / "reports" / "acceptance_remediation" / "latest_delivery_check.json"),
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
        "remediation_report": remediation,
        "account_repair_summary": account_repair_summary,
        "account_repair_apply": account_repair_apply,
        "ixbrowser_metadata": ixbrowser_metadata,
        "checks": checks,
        "failed_checks": failed_checks,
        "ok": ok,
    }


def write_delivery_check(payload: dict, output_path: str | Path | None = None) -> Path:
    out_path = Path(output_path or payload.get("delivery_check_path") or "")
    if not str(out_path):
        out_path = Path(payload["base_dir"]) / "reports" / "acceptance_remediation" / "latest_delivery_check.json"
    payload["delivery_check_path"] = str(out_path)
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
        f"total={summary.get('total_unique_profiles_by_error') or 0}"
    ]
    for row in groups[: max(1, int(limit or 1))]:
        samples = [str(item) for item in (row.get("profile_ids_sample") or []) if str(item).strip()]
        sample_text = f" sample={','.join(samples[:8])}" if samples else ""
        action = str(row.get("recommended_action") or "").strip()
        action_text = f" action={action}" if action else ""
        lines.append(f"  {row.get('error') or '-'} count={row.get('count') or 0}{sample_text}{action_text}")
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
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_delivery_check(Path(args.base_dir), collect_metadata=True)
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
