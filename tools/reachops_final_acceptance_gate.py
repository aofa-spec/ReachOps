# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_client_delivery_check import build_delivery_check, write_delivery_check
from tools.reachops_delivery_package_check import check_delivery_package
from tools.reachops_goal_status_report import build_goal_status_report, run_default_audit
from tools.reachops_issue_closure_audit import build_report as build_issue_closure_report
from tools.reachops_operator_pressure import DEFAULT_TARGETS, run_pressure


PASSED = "passed"
FAILED = "failed"
READY_FOR_EXTERNAL_VALIDATION = "ready_for_external_validation"
NOT_READY = "not_ready"
REQUIRED_PACKAGE_REPORT_FILES = (
    "delivery_audit",
    "operator_pressure",
    "installer_smoke",
    "ui_startup",
    "activation_status",
    "live_acceptance_status",
    "authorization_handoff",
    "live_validation",
    "repository_cleanliness",
    "windows_package_preflight",
    "client_delivery",
    "live_readiness",
    "live_preflight",
    "goal_status",
    "live_submit",
    "issue_closure",
    "final_acceptance_gate",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _input_path_failures(root: Path, args: argparse.Namespace) -> list[str]:
    checks = {
        "audit_json_outside_root": args.audit_json,
        "pressure_json_outside_root": args.pressure_json,
        "goal_status_json_outside_root": args.goal_status_json,
        "client_delivery_json_outside_root": args.client_delivery_json,
        "package_check_json_outside_root": args.package_check_json,
        "issue_closure_json_outside_root": args.issue_closure_json,
        "acceptance_summary_outside_root": args.acceptance_summary,
        "manifest_outside_root": args.manifest,
    }
    failures: list[str] = []
    for failure, raw_path in checks.items():
        if raw_path and not _is_relative_to(_resolve(root, raw_path), root):
            failures.append(failure)
    return failures


def _package_check_root_matches(package_check: dict[str, Any], root: Path) -> bool:
    package_root = str(package_check.get("root") or "").strip()
    if not package_root:
        return False
    try:
        return Path(package_root).resolve() == root.resolve()
    except Exception:
        return False


def _client_delivery_root_validation(client_delivery: dict[str, Any], root: Path) -> tuple[bool, dict[str, Any]]:
    if str(client_delivery.get("source") or "") == "acceptance_summary.live_acceptance_status":
        return True, {"source": "acceptance_summary.live_acceptance_status"}
    delivery_check_path = str(client_delivery.get("delivery_check_path") or "").strip()
    client_root = str(client_delivery.get("root_dir") or "").strip()
    evidence: dict[str, Any] = {
        "root": str(root),
        "client_root_dir": client_root,
        "delivery_check_path": delivery_check_path,
        "delivery_check_inside_root": False,
        "delivery_check_exists": False,
        "delivery_check_root_dir": "",
    }
    if not delivery_check_path or not client_root:
        return False, evidence
    try:
        if Path(client_root).resolve() != root.resolve():
            return False, evidence
        resolved_delivery_check = _resolve(root, delivery_check_path).resolve()
        evidence["delivery_check_path"] = str(resolved_delivery_check)
        evidence["delivery_check_inside_root"] = _is_relative_to(resolved_delivery_check, root)
        evidence["delivery_check_exists"] = resolved_delivery_check.is_file()
        if not evidence["delivery_check_inside_root"] or not evidence["delivery_check_exists"]:
            return False, evidence
        payload = _load_json(resolved_delivery_check)
        evidence["delivery_check_root_dir"] = str(payload.get("root_dir") or "")
        return (
            bool(str(payload.get("delivery_check_path") or "").strip())
            and Path(str(payload.get("delivery_check_path") or "")).resolve() == resolved_delivery_check
            and bool(str(payload.get("root_dir") or "").strip())
            and Path(str(payload.get("root_dir") or "")).resolve() == root.resolve()
        ), evidence
    except Exception as exc:
        evidence["error"] = str(exc)
        return False, evidence


def _check(name: str, ok: bool, status: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "status": status,
        "evidence": evidence or {},
    }


def _startup_failure_payload(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "product": "ReachOps",
        "status": FAILED,
        "final_delivery_ready": False,
        "checks": [
            _check(
                name,
                False,
                FAILED,
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:4000],
                },
            )
        ],
        "failed_checks": [name],
        "final_delivery_blockers": [
            {
                "scope": name.split(":", 1)[0],
                "status": FAILED,
                "next_action": f"修复 {name} 默认验收命令失败项，确保 final gate 能输出结构化结果。",
            }
        ],
        "next_actions": [f"修复 {name} 默认验收命令失败项，复跑 tools\\reachops_final_acceptance_gate.py --json。"],
    }


def _goal_ready(goal_status: dict[str, Any]) -> bool:
    return str(goal_status.get("status") or "") == PASSED and not goal_status.get("pending_external_validation")


def _current_stage_gate_status(goal_status: dict[str, Any]) -> dict[str, Any]:
    gate = goal_status.get("current_stage_gate") if isinstance(goal_status.get("current_stage_gate"), dict) else {}
    local_checks = gate.get("local_checks") if isinstance(gate.get("local_checks"), dict) else {}
    return {
        "schema_version": str(gate.get("schema_version") or ""),
        "status": str(gate.get("status") or ""),
        "local_passed": bool(gate.get("local_passed")),
        "local_checks": local_checks,
        "external_validation_pending": gate.get("external_validation_pending") or [],
        "does_not_claim_real_pilot_when_blocked": bool(gate.get("does_not_claim_real_pilot_when_blocked")),
        "real_pilot_evidence": gate.get("real_pilot_evidence") if isinstance(gate.get("real_pilot_evidence"), dict) else {},
    }


def _current_stage_gate_ready_or_external_pending(goal_status: dict[str, Any]) -> bool:
    gate = _current_stage_gate_status(goal_status)
    required_local_checks = (
        "delivery_audit_has_no_local_failures",
        "client_delivery_reports_real_pilot_boundary",
        "client_delivery_does_not_claim_blocked_real_pilot",
    )
    return (
        gate["schema_version"] == "reachops.current_stage_gate.v1"
        and gate["local_passed"]
        and gate["status"] in {PASSED, READY_FOR_EXTERNAL_VALIDATION}
        and all(bool(gate["local_checks"].get(name)) for name in required_local_checks)
        and gate["does_not_claim_real_pilot_when_blocked"]
    )


def _issue_closure_ready(issue_closure: dict[str, Any] | None) -> bool:
    if not isinstance(issue_closure, dict) or not issue_closure:
        return True
    summary = issue_closure.get("summary") if isinstance(issue_closure.get("summary"), dict) else {}
    return (
        bool(issue_closure.get("passed"))
        and int(summary.get("issues_total") or 0) == 7
        and int(summary.get("local_contracts_passed") or 0) == 7
        and int(summary.get("acceptance_criteria_total") or 0) == 53
        and int(summary.get("acceptance_criteria_unclassified") or 0) == 0
        and int(summary.get("acceptance_criteria_external_pending") or 0) == 0
        and int(summary.get("external_pending_count") or 0) == 0
        and not issue_closure.get("external_acceptance_pending")
        and (issue_closure.get("github_issues") or {}).get("closure_requires_external_validation") is False
    )


def _external_pending_summary(issue_closure: dict[str, Any] | None, limit: int = 20) -> dict[str, Any]:
    pending = [
        str(item)
        for item in ((issue_closure or {}).get("external_acceptance_pending") or [])
        if str(item or "").strip()
    ]
    shown = pending[:limit]
    return {
        "external_acceptance_pending": shown,
        "external_acceptance_pending_total": len(pending),
        "external_acceptance_pending_displayed": len(shown),
        "external_acceptance_pending_remaining": max(0, len(pending) - len(shown)),
    }


def _client_evidence_ready(client_delivery: dict[str, Any]) -> bool:
    if str(client_delivery.get("source") or "") == "acceptance_summary.client_delivery":
        return (
            str(client_delivery.get("status") or "") == PASSED
            and bool(client_delivery.get("final_delivery_ready"))
            and bool(client_delivery.get("acceptance_ready"))
            and str(client_delivery.get("readiness") or "") == "pass"
            and not client_delivery.get("failed_checks")
        )
    if str(client_delivery.get("source") or "") == "acceptance_summary.live_acceptance_status":
        live_status = client_delivery.get("live_acceptance_status") if isinstance(client_delivery.get("live_acceptance_status"), dict) else {}
        return str(live_status.get("status") or "") == PASSED and bool(live_status.get("final_delivery_ready"))
    path = str(client_delivery.get("delivery_check_path") or "").strip()
    if not path:
        return False
    report_path = Path(path)
    if not report_path.is_file():
        return False
    try:
        evidence = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(evidence, dict):
        return False
    return (
        str(evidence.get("status") or "") == PASSED
        and bool(evidence.get("final_delivery_ready"))
        and bool(evidence.get("acceptance_ready"))
        and str(evidence.get("readiness") or "") == "pass"
        and not evidence.get("failed_checks")
        and str(evidence.get("delivery_check_path") or "") == path
    )


def _client_ready(client_delivery: dict[str, Any]) -> bool:
    return (
        str(client_delivery.get("status") or "") == PASSED
        and bool(client_delivery.get("final_delivery_ready"))
        and bool(client_delivery.get("acceptance_ready"))
        and str(client_delivery.get("readiness") or "") == "pass"
        and not client_delivery.get("failed_checks")
        and _client_evidence_ready(client_delivery)
    )


def _evidence_item(
    *,
    scope: str,
    title: str,
    ready: bool,
    status: str,
    required_evidence: list[str] | None = None,
    required_artifacts: list[str] | None = None,
    commands: list[str] | None = None,
    proof_fields: list[str] | None = None,
    blocker_codes: list[str] | None = None,
    blocker_summary: dict[str, Any] | None = None,
    next_action: str = "",
) -> dict[str, Any]:
    return {
        "scope": scope,
        "title": title,
        "ready": bool(ready),
        "status": status,
        "required_evidence": required_evidence or [],
        "required_artifacts": required_artifacts or [],
        "commands": commands or [],
        "proof_fields": proof_fields or [],
        "blocker_codes": blocker_codes or [],
        "blocker_summary": blocker_summary or {},
        "next_action": next_action,
    }


def build_final_delivery_evidence_plan(
    *,
    goal_status: dict[str, Any],
    client_delivery: dict[str, Any],
    package_check: dict[str, Any],
    issue_closure: dict[str, Any] | None = None,
    delivery_audit: dict[str, Any] | None = None,
    operator_pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Machine-readable evidence checklist for the final delivery boundary."""
    audit_summary = (delivery_audit or {}).get("summary") if isinstance((delivery_audit or {}).get("summary"), dict) else {}
    pressure_summary = (
        (operator_pressure or {}).get("summary") if isinstance((operator_pressure or {}).get("summary"), dict) else {}
    )
    acceptance_verification = (
        package_check.get("acceptance_verification")
        if isinstance(package_check.get("acceptance_verification"), dict)
        else {}
    )
    issue_pending_summary = _external_pending_summary(issue_closure)
    items = [
        _evidence_item(
            scope="current_stage_gate",
            title="当前恢复阶段本地门禁证据",
            ready=_current_stage_gate_ready_or_external_pending(goal_status),
            status=_current_stage_gate_status(goal_status)["status"] or FAILED,
            required_evidence=[
                "current_stage_gate.schema_version=reachops.current_stage_gate.v1",
                "current_stage_gate.local_passed=true",
                "本地 delivery audit 无代码级失败",
                "client delivery 明确暴露真实 pilot 边界",
                "账号或平台阻断时不声称真实 pilot 通过",
            ],
            commands=["python tools\\reachops_goal_status_report.py --json"],
            proof_fields=[
                "current_stage_gate.status in [passed, ready_for_external_validation]",
                "current_stage_gate.local_passed=true",
                "current_stage_gate.local_checks.delivery_audit_has_no_local_failures=true",
                "current_stage_gate.local_checks.client_delivery_reports_real_pilot_boundary=true",
                "current_stage_gate.local_checks.client_delivery_does_not_claim_blocked_real_pilot=true",
            ],
            blocker_codes=[str(item) for item in _current_stage_gate_status(goal_status)["external_validation_pending"]],
            next_action="修复 current_stage_gate 本地失败项；外部阻断只能保留为 external_validation_pending，不能声明最终通过。",
        ),
        _evidence_item(
            scope="external_authorized_execution",
            title="授权真实平台执行证据",
            ready=_goal_ready(goal_status),
            status=str(goal_status.get("status") or FAILED),
            required_evidence=[
                "授权 TikTok 目标",
                "激活状态 ready",
                "真实提交截图和 sidecar",
                "submitted_text",
                "comment_visible_confirmed=true",
            ],
            commands=[
                "python tools\\reachops_live_acceptance_status.py --local-inputs-path tools\\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json",
                "python tools\\reachops_goal_status_report.py --strict-external --json",
            ],
            proof_fields=[
                "goal_status.status=passed",
                "goal_status.pending_external_validation=[]",
                "live_submit.status=completed",
                "live_submit.platform_validation=true",
            ],
            blocker_codes=[str(item) for item in (goal_status.get("pending_external_validation") or [])],
            next_action="完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。",
        ),
        _evidence_item(
            scope="client_delivery_gate",
            title="客户端交付门禁证据",
            ready=_client_ready(client_delivery),
            status=str(client_delivery.get("status") or FAILED),
            required_evidence=[
                "status=passed",
                "readiness=pass",
                "acceptance_ready=true",
                "final_delivery_ready=true",
                "failed_checks=[]",
                "delivery_check_path 指向当前仓库内最新 JSON",
            ],
            commands=["python tools\\reachops_client_delivery_check.py --json"],
            proof_fields=[
                "client_delivery.status=passed",
                "client_delivery.readiness=pass",
                "client_delivery.acceptance_ready=true",
                "client_delivery.final_delivery_ready=true",
                "client_delivery.failed_checks=[]",
            ],
            blocker_codes=[str(item) for item in (client_delivery.get("failed_checks") or [])],
            next_action="复跑 tools\\reachops_client_delivery_check.py --json，直到 status=passed、final_delivery_ready=true、failed_checks=[]。",
        ),
        _evidence_item(
            scope="windows_final_artifacts",
            title="Windows 最终客户端包证据",
            ready=_package_ready(package_check),
            status=str(package_check.get("status") or FAILED),
            required_artifacts=[
                "dist\\ReachOps\\ReachOps.exe",
                "dist\\installer\\ReachOps-Setup-0.4.0.exe",
                "dist\\installer\\reachops-update-manifest.json",
                "reports\\reachops_acceptance\\acceptance_summary.json",
            ],
            commands=[
                "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
                "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
                "python tools\\reachops_delivery_package_check.py --json",
            ],
            proof_fields=[
                "delivery_package.status=passed",
                "delivery_package.final_delivery_ready=true",
                "delivery_package.missing_artifacts=[]",
                "delivery_package.acceptance_verification.passed=true",
                "delivery_package.acceptance_verification.failures=[]",
                "delivery_package.acceptance_verification.pending=[]",
            ],
            blocker_codes=[
                *[str(item) for item in (package_check.get("failures") or [])],
                *[str(item) for item in (acceptance_verification.get("failures") or [])],
            ],
            next_action="在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\\reachops_delivery_package_check.py --json。",
        ),
        _evidence_item(
            scope="commercial_issue_closure",
            title="Issues #1-#7 商业验收闭环证据",
            ready=_issue_closure_ready(issue_closure),
            status=str((issue_closure or {}).get("status") or FAILED),
            required_evidence=[
                "Issues #1-#7 全部有 acceptance criteria 级证据矩阵",
                "acceptance_criteria_total=53",
                "acceptance_criteria_unclassified=0",
                "acceptance_criteria_external_pending=0",
                "external_pending_count=0",
                "GitHub Issues #1-#7 已按证据关闭或明确转入后续非阻断范围",
            ],
            commands=["python tools\\reachops_issue_closure_audit.py --json"],
            proof_fields=[
                "issue_closure.summary.issues_total=7",
                "issue_closure.summary.acceptance_criteria_total=53",
                "issue_closure.summary.acceptance_criteria_unclassified=0",
                "issue_closure.summary.acceptance_criteria_external_pending=0",
                "issue_closure.summary.external_pending_count=0",
                "issue_closure.github_issues.closure_requires_external_validation=false",
            ],
            blocker_codes=[
                *issue_pending_summary["external_acceptance_pending"],
                *(
                    ["acceptance_criteria_external_pending"]
                    if int(((issue_closure or {}).get("summary") or {}).get("acceptance_criteria_external_pending") or 0)
                    else []
                ),
            ],
            blocker_summary=issue_pending_summary,
            next_action="完成 Issues #1-#7 中仍标记 external_pending 的验收标准，并复跑 tools\\reachops_issue_closure_audit.py --json。",
        ),
        _evidence_item(
            scope="delivery_audit",
            title="本地能力审计证据",
            ready=bool(str((delivery_audit or {}).get("status") or "") == "ok" and int(audit_summary.get("failed") or 0) == 0),
            status=str((delivery_audit or {}).get("status") or FAILED),
            commands=["python tools\\reachops_delivery_audit.py --json"],
            proof_fields=["delivery_audit.status=ok", "delivery_audit.summary.failed=0"],
            blocker_codes=[] if int(audit_summary.get("failed") or 0) == 0 else ["delivery_audit_failed"],
            next_action="修复 reachops_delivery_audit 失败项，并复跑 tools\\reachops_delivery_audit.py --json。",
        ),
        _evidence_item(
            scope="operator_pressure",
            title="运营压测证据",
            ready=bool(str((operator_pressure or {}).get("status") or "") == "ok" and int(pressure_summary.get("customer_leads") or 0) > 0),
            status=str((operator_pressure or {}).get("status") or FAILED),
            commands=["python tools\\reachops_operator_pressure.py --json"],
            proof_fields=["operator_pressure.status=ok", "operator_pressure.summary.customer_leads>0"],
            blocker_codes=[] if int(pressure_summary.get("customer_leads") or 0) > 0 else ["operator_pressure_no_leads"],
            next_action="修复运营压测失败项，直到 tools\\reachops_operator_pressure.py --json 返回 status=ok 且 customer_leads>0。",
        ),
    ]
    pending = [item for item in items if not item.get("ready")]
    return {
        "schema_version": "reachops.final_delivery_evidence_plan.v1",
        "ready": not pending,
        "item_count": len(items),
        "ready_count": len(items) - len(pending),
        "pending_count": len(pending),
        "pending_scopes": [item["scope"] for item in pending],
        "items": items,
        "next_actions": [item["next_action"] for item in pending if item.get("next_action")],
    }


def client_delivery_from_acceptance_summary(summary: dict[str, Any]) -> dict[str, Any]:
    embedded = summary.get("client_delivery") if isinstance(summary.get("client_delivery"), dict) else {}
    if embedded:
        failed_checks = [str(item) for item in embedded.get("failed_checks") or [] if str(item or "").strip()]
        return {
            "status": str(embedded.get("status") or "blocked_by_environment"),
            "readiness": str(embedded.get("readiness") or ""),
            "contract_ok": bool(embedded.get("contract_ok")),
            "acceptance_ready": bool(embedded.get("acceptance_ready")),
            "final_delivery_ready": bool(embedded.get("final_delivery_ready")),
            "failed_checks": failed_checks,
            "blockers": [str(item) for item in embedded.get("blockers") or [] if str(item or "").strip()],
            "delivery_check_path": str(embedded.get("delivery_check_path") or embedded.get("json_path") or ""),
            "source": "acceptance_summary.client_delivery",
            "checks": embedded.get("checks") if isinstance(embedded.get("checks"), list) else [],
        }
    live_status = summary.get("live_acceptance_status") if isinstance(summary.get("live_acceptance_status"), dict) else {}
    next_required = [str(item) for item in live_status.get("next_required_actions") or [] if str(item or "").strip()]
    final_ready = False
    readiness = "pass" if final_ready else "blocked_by_environment"
    return {
        "status": PASSED if final_ready else "blocked_by_environment",
        "readiness": readiness,
        "contract_ok": True,
        "acceptance_ready": final_ready,
        "final_delivery_ready": final_ready,
        "failed_checks": [] if final_ready else ["client_delivery:missing"],
        "blockers": [] if final_ready else next_required or ["Windows acceptance summary is missing client_delivery evidence."],
        "source": "acceptance_summary.live_acceptance_status",
        "live_acceptance_status": {
            "status": live_status.get("status"),
            "final_delivery_ready": live_status.get("final_delivery_ready"),
            "next_required_actions": next_required,
        },
    }


def _package_ready(package_check: dict[str, Any]) -> bool:
    acceptance_verification = (
        package_check.get("acceptance_verification")
        if isinstance(package_check.get("acceptance_verification"), dict)
        else {}
    )
    artifacts = package_check.get("artifacts") if isinstance(package_check.get("artifacts"), dict) else {}
    report_files = package_check.get("report_files") if isinstance(package_check.get("report_files"), dict) else {}
    final_gate_report = (
        package_check.get("final_gate_report")
        if isinstance(package_check.get("final_gate_report"), dict)
        else {}
    )
    required_artifacts = ("exe", "installer", "manifest", "acceptance_summary")
    artifacts_ready = all(
        bool((artifacts.get(name) or {}).get("exists")) and int((artifacts.get(name) or {}).get("size") or 0) > 0
        for name in required_artifacts
    )
    pe_artifacts_ready = all(
        bool((artifacts.get(name) or {}).get("pe_signature_valid"))
        for name in ("exe", "installer")
    )
    manifest = artifacts.get("manifest") if isinstance(artifacts.get("manifest"), dict) else {}
    expected_sha = str(manifest.get("expected_sha256") or "")
    actual_sha = str(manifest.get("actual_sha256") or "")
    expected_size = int(manifest.get("expected_size") or 0)
    actual_size = int(manifest.get("actual_size") or 0)
    manifest_hash_ready = len(expected_sha) == 64 and expected_sha == actual_sha
    manifest_size_ready = expected_size > 0 and expected_size == actual_size
    report_files_ready = all(
        bool((report_files.get(name) or {}).get("exists")) and int((report_files.get(name) or {}).get("size") or 0) > 0
        for name in REQUIRED_PACKAGE_REPORT_FILES
    )
    final_gate_report_ready = (
        str(final_gate_report.get("status") or "") == PASSED
        and bool(final_gate_report.get("final_delivery_ready"))
        and not final_gate_report.get("failed_checks")
        and not final_gate_report.get("missing_required_checks")
        and not final_gate_report.get("failed_required_checks")
        and bool(final_gate_report.get("checks_by_name"))
    )
    final_gate_convergence_ready = (
        bool(package_check.get("allow_final_gate_convergence"))
        and bool(final_gate_report.get("convergence_only"))
        and not final_gate_report.get("missing_required_checks")
        and final_gate_report.get("failed_required_checks") == ["delivery_package:passed"]
        and bool(final_gate_report.get("checks_by_name"))
    )
    return (
        str(package_check.get("status") or "") == PASSED
        and bool(package_check.get("passed"))
        and bool(package_check.get("final_delivery_ready"))
        and not bool(package_check.get("bootstrap_only"))
        and not package_check.get("failures")
        and not package_check.get("pending_external_validation")
        and bool(acceptance_verification.get("passed"))
        and not acceptance_verification.get("failures")
        and not acceptance_verification.get("pending")
        and artifacts_ready
        and pe_artifacts_ready
        and manifest_hash_ready
        and manifest_size_ready
        and report_files_ready
        and (final_gate_report_ready or final_gate_convergence_ready)
    )


def run_default_pressure() -> dict[str, Any]:
    return run_pressure(
        SimpleNamespace(
            base_dir="",
            targets=list(DEFAULT_TARGETS),
            profile_group="US",
            max_campaigns=5,
            max_sources_per_campaign=5,
            max_videos=5,
            max_comments=4,
            min_views=0,
            min_comments=0,
            collect_profile_count=4,
            execute_profile_count=4,
            workers=2,
            per_profile_limit=10,
            switch_attempts=2,
            action_limit=250,
            per_profile_hour_limit=20,
            per_profile_video_hour_limit=99,
            task_delay_seconds=30,
            intent_keywords=["where", "link", "buy", "price", "download", "app", "coupon"],
            exclude_keywords=["spam", "bot", "haha", "lol"],
            allow_fail=False,
        )
    )


def build_final_acceptance_gate(
    *,
    goal_status: dict[str, Any],
    client_delivery: dict[str, Any],
    package_check: dict[str, Any],
    issue_closure: dict[str, Any] | None = None,
    delivery_audit: dict[str, Any] | None = None,
    operator_pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_summary = (issue_closure or {}).get("summary") if isinstance((issue_closure or {}).get("summary"), dict) else {}
    current_stage_gate = _current_stage_gate_status(goal_status)
    checks = [
        _check(
            "current_stage_gate:local_ready_or_external_pending",
            _current_stage_gate_ready_or_external_pending(goal_status),
            current_stage_gate["status"] or FAILED,
            current_stage_gate,
        ),
        _check(
            "goal_status:passed",
            _goal_ready(goal_status),
            str(goal_status.get("status") or FAILED),
            {
                "pending_external_validation": goal_status.get("pending_external_validation") or [],
                "summary": goal_status.get("summary") or {},
            },
        ),
        _check(
            "client_delivery:final_ready",
            _client_ready(client_delivery),
            str(client_delivery.get("status") or FAILED),
            {
                "readiness": client_delivery.get("readiness"),
                "contract_ok": client_delivery.get("contract_ok"),
                "acceptance_ready": client_delivery.get("acceptance_ready"),
                "final_delivery_ready": client_delivery.get("final_delivery_ready"),
                "failed_checks": client_delivery.get("failed_checks") or [],
                "blockers": client_delivery.get("blockers") or [],
                "delivery_check_path": client_delivery.get("delivery_check_path") or "",
                "source": client_delivery.get("source") or "",
                "evidence_ready": _client_evidence_ready(client_delivery),
            },
        ),
        _check(
            "delivery_package:passed",
            _package_ready(package_check),
            str(package_check.get("status") or FAILED),
            {
                "missing_artifacts": package_check.get("missing_artifacts") or [],
                "failures": package_check.get("failures") or [],
                "final_delivery_ready": package_check.get("final_delivery_ready"),
                "bootstrap_only": package_check.get("bootstrap_only"),
                "not_final_delivery_reasons": package_check.get("not_final_delivery_reasons") or [],
                "pending_external_validation": package_check.get("pending_external_validation") or [],
                "root": package_check.get("root") or "",
                "artifacts": package_check.get("artifacts") or {},
                "report_files": package_check.get("report_files") or {},
                "final_gate_report": package_check.get("final_gate_report") or {},
                "acceptance_verification": package_check.get("acceptance_verification") or {},
            },
        ),
    ]
    if issue_closure is not None:
        checks.append(
            _check(
                "commercial_issue_closure:closed",
                _issue_closure_ready(issue_closure),
                str(issue_closure.get("status") or FAILED),
                {
                    "github_issues": issue_closure.get("github_issues") or {},
                    "summary": issue_summary,
                    "external_acceptance_pending": issue_closure.get("external_acceptance_pending") or [],
                },
            )
        )
    audit_ok = True
    if delivery_audit is not None:
        audit_summary = delivery_audit.get("summary") or {}
        audit_ok = str(delivery_audit.get("status") or "") == "ok" and int(audit_summary.get("failed") or 0) == 0
        checks.append(
            _check(
                "delivery_audit:no_failed_checks",
                audit_ok,
                str(delivery_audit.get("status") or FAILED),
                {"summary": audit_summary},
            )
        )
    pressure_ok = True
    if operator_pressure is not None:
        pressure_summary = operator_pressure.get("summary") or {}
        pressure_ok = str(operator_pressure.get("status") or "") == "ok" and int(pressure_summary.get("customer_leads") or 0) > 0
        checks.append(
            _check(
                "operator_pressure:leads_and_actions",
                pressure_ok,
                str(operator_pressure.get("status") or FAILED),
                {"summary": pressure_summary},
            )
        )

    failed_checks = [row for row in checks if not row.get("ok")]
    status = PASSED if not failed_checks else FAILED
    if failed_checks and any(row["status"] == READY_FOR_EXTERNAL_VALIDATION for row in failed_checks):
        status = NOT_READY
    if failed_checks and all(row["status"] in {READY_FOR_EXTERNAL_VALIDATION, "blocked_by_environment", "blocked_by_accounts"} for row in failed_checks):
        status = NOT_READY

    final_delivery_blockers = []
    next_actions = []
    if not _current_stage_gate_ready_or_external_pending(goal_status):
        final_delivery_blockers.append(
            {
                "scope": "current_stage_gate",
                "status": current_stage_gate["status"] or FAILED,
                "local_passed": current_stage_gate["local_passed"],
                "local_checks": current_stage_gate["local_checks"],
                "external_validation_pending": current_stage_gate["external_validation_pending"],
                "next_action": "修复 current_stage_gate 本地失败项，确保本阶段恢复基线明确通过或只剩外部真实环境验收。",
            }
        )
        next_actions.append("修复 current_stage_gate 本地失败项，确保本阶段恢复基线明确通过或只剩外部真实环境验收。")
    if not _goal_ready(goal_status):
        pending = [str(item) for item in (goal_status.get("pending_external_validation") or []) if str(item or "").strip()]
        final_delivery_blockers.append(
            {
                "scope": "external_authorized_execution",
                "status": str(goal_status.get("status") or FAILED),
                "pending_external_validation": pending,
                "required_evidence": [
                    "授权 TikTok 目标",
                    "激活状态 ready",
                    "真实提交截图和 sidecar",
                    "submitted_text",
                    "comment_visible_confirmed=true",
                ],
                "next_action": "完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。",
            }
        )
        next_actions.append("完成授权真实触达验收，确保 goal_status.status=passed 且 pending_external_validation=[]。")
    if not _client_ready(client_delivery):
        final_delivery_blockers.append(
            {
                "scope": "client_delivery_gate",
                "status": str(client_delivery.get("status") or FAILED),
                "failed_checks": client_delivery.get("failed_checks") or [],
                "blockers": client_delivery.get("blockers") or [],
                "next_action": "复跑 tools\\reachops_client_delivery_check.py --json，直到 status=passed、final_delivery_ready=true、failed_checks=[]。",
            }
        )
        next_actions.append("复跑 tools\\reachops_client_delivery_check.py --json，直到 status=passed、final_delivery_ready=true、failed_checks=[]。")
    if not _package_ready(package_check):
        missing = [str(item) for item in (package_check.get("missing_artifacts") or []) if str(item or "").strip()]
        failures = [str(item) for item in (package_check.get("failures") or []) if str(item or "").strip()]
        final_delivery_blockers.append(
            {
                "scope": "windows_final_artifacts",
                "status": str(package_check.get("status") or FAILED),
                "missing_artifacts": missing,
                "failures": failures,
                "required_artifacts": [
                    "dist\\ReachOps\\ReachOps.exe",
                    "dist\\installer\\ReachOps-Setup-0.4.0.exe",
                    "dist\\installer\\reachops-update-manifest.json",
                    "reports\\reachops_acceptance\\acceptance_summary.json",
                ],
                "next_action": "在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\\reachops_delivery_package_check.py --json。",
            }
        )
        next_actions.append("在 Windows 实机生成 exe、installer、update manifest 和通过的 acceptance_summary.json，然后复跑 tools\\reachops_delivery_package_check.py --json。")
    if issue_closure is not None and not _issue_closure_ready(issue_closure):
        issue_pending_summary = _external_pending_summary(issue_closure)
        final_delivery_blockers.append(
            {
                "scope": "commercial_issue_closure",
                "status": str(issue_closure.get("status") or FAILED),
                "summary": issue_summary,
                **issue_pending_summary,
                "required_evidence": [
                    "acceptance_criteria_total=53",
                    "acceptance_criteria_unclassified=0",
                    "acceptance_criteria_external_pending=0",
                    "external_pending_count=0",
                    "Issues #1-#7 已有关闭证据或非阻断移交证据",
                ],
                "next_action": "完成 Issues #1-#7 中仍标记 external_pending 的验收标准，并复跑 tools\\reachops_issue_closure_audit.py --json。",
            }
        )
        next_actions.append("完成 Issues #1-#7 中仍标记 external_pending 的验收标准，并复跑 tools\\reachops_issue_closure_audit.py --json。")
    if not audit_ok:
        final_delivery_blockers.append(
            {
                "scope": "delivery_audit",
                "status": str((delivery_audit or {}).get("status") or FAILED),
                "next_action": "修复 reachops_delivery_audit 失败项，并复跑 tools\\reachops_delivery_audit.py --json。",
            }
        )
        next_actions.append("修复 reachops_delivery_audit 失败项，并复跑 tools\\reachops_delivery_audit.py --json。")
    if not pressure_ok:
        final_delivery_blockers.append(
            {
                "scope": "operator_pressure",
                "status": str((operator_pressure or {}).get("status") or FAILED),
                "next_action": "修复运营压测失败项，直到 tools\\reachops_operator_pressure.py --json 返回 status=ok 且 customer_leads>0。",
            }
        )
        next_actions.append("修复运营压测失败项，直到 tools\\reachops_operator_pressure.py --json 返回 status=ok 且 customer_leads>0。")

    final_delivery_evidence_plan = build_final_delivery_evidence_plan(
        goal_status=goal_status,
        client_delivery=client_delivery,
        package_check=package_check,
        issue_closure=issue_closure,
        delivery_audit=delivery_audit,
        operator_pressure=operator_pressure,
    )
    return {
        "product": "ReachOps",
        "status": status,
        "final_delivery_ready": status == PASSED,
        "checks": checks,
        "failed_checks": [row["name"] for row in failed_checks],
        "final_delivery_blockers": final_delivery_blockers,
        "final_delivery_evidence_plan": final_delivery_evidence_plan,
        "next_actions": next_actions,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the strict ReachOps final delivery acceptance gate.")
    parser.add_argument("--root", default=str(ROOT_DIR), help="ReachOps repository root.")
    parser.add_argument("--base-dir", default="", help="Runtime base dir for client delivery check.")
    parser.add_argument("--audit-json", default="", help="Existing reachops_delivery_audit JSON.")
    parser.add_argument("--pressure-json", default="", help="Existing reachops_operator_pressure JSON.")
    parser.add_argument("--goal-status-json", default="", help="Existing reachops_goal_status_report JSON.")
    parser.add_argument("--client-delivery-json", default="", help="Existing reachops_client_delivery_check JSON.")
    parser.add_argument("--package-check-json", default="", help="Existing reachops_delivery_package_check JSON.")
    parser.add_argument("--issue-closure-json", default="", help="Existing reachops_issue_closure_audit JSON.")
    parser.add_argument("--acceptance-summary", default="", help="Acceptance summary used when package check JSON is not supplied.")
    parser.add_argument("--manifest", default="", help="Update manifest used when package check JSON is not supplied.")
    parser.add_argument("--target", default="anti aging serum", help="Audit target used only when goal status JSON is not supplied.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    input_failures = _input_path_failures(root, args)
    if input_failures:
        payload = {
            "product": "ReachOps",
            "status": FAILED,
            "final_delivery_ready": False,
            "checks": [
                _check(
                    "input_paths:inside_root",
                    False,
                    FAILED,
                    {"root": str(root), "failures": input_failures},
                )
            ],
            "failed_checks": ["input_paths:inside_root"],
            "next_actions": ["Keep final gate input JSON files under the current ReachOps repository root."],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
            print(f"failed_checks={','.join(payload['failed_checks'])}")
            for action in payload.get("next_actions") or []:
                print(f"next={action}")
        return 1
    try:
        delivery_audit = _load_json(args.audit_json) if args.audit_json else run_default_audit(args.target)
    except Exception as exc:
        payload = _startup_failure_payload("delivery_audit:no_failed_checks", exc)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
            print(f"failed_checks={','.join(payload['failed_checks'])}")
            for action in payload.get("next_actions") or []:
                print(f"next={action}")
        return 1
    try:
        operator_pressure = _load_json(args.pressure_json) if args.pressure_json else run_default_pressure()
    except Exception as exc:
        payload = _startup_failure_payload("operator_pressure:leads_and_actions", exc)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
            print(f"failed_checks={','.join(payload['failed_checks'])}")
            for action in payload.get("next_actions") or []:
                print(f"next={action}")
        return 1

    if args.client_delivery_json:
        client_delivery = _load_json(args.client_delivery_json)
        client_root_ok, client_root_evidence = _client_delivery_root_validation(client_delivery, root)
        if not client_root_ok:
            payload = {
                "product": "ReachOps",
                "status": FAILED,
                "final_delivery_ready": False,
                "checks": [
                    _check(
                        "client_delivery:root_matches",
                        False,
                        FAILED,
                        client_root_evidence,
                    )
                ],
                "failed_checks": ["client_delivery:root_matches"],
                "next_actions": [
                    "Regenerate reachops_client_delivery_check JSON from the current repository root before final delivery."
                ],
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
                print(f"failed_checks={','.join(payload['failed_checks'])}")
                for action in payload.get("next_actions") or []:
                    print(f"next={action}")
            return 1
    else:
        if args.acceptance_summary:
            client_delivery = client_delivery_from_acceptance_summary(_load_json(args.acceptance_summary))
        else:
            client_delivery = build_delivery_check(Path(args.base_dir) if args.base_dir else root / "reports/reachops/mac_gui/runtime")
            write_delivery_check(client_delivery)

    if args.goal_status_json:
        goal_status = _load_json(args.goal_status_json)
    else:
        goal_status = build_goal_status_report(delivery_audit, client_delivery=client_delivery)

    if args.package_check_json:
        package_check = _load_json(args.package_check_json)
        if not _package_check_root_matches(package_check, root):
            payload = {
                "product": "ReachOps",
                "status": FAILED,
                "final_delivery_ready": False,
                "checks": [
                    _check(
                        "package_check:root_matches",
                        False,
                        FAILED,
                        {
                            "root": str(root),
                            "package_check_root": package_check.get("root") or "",
                            "package_check_json": str(_resolve(root, args.package_check_json).resolve()),
                        },
                    )
                ],
                "failed_checks": ["package_check:root_matches"],
                "next_actions": [
                    "Regenerate reachops_delivery_package_check JSON from the current repository root before final delivery."
                ],
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
                print(f"failed_checks={','.join(payload['failed_checks'])}")
                for action in payload.get("next_actions") or []:
                    print(f"next={action}")
            return 1
    else:
        package_check = check_delivery_package(
            root=root,
            acceptance_summary_path=args.acceptance_summary or None,
            manifest_path=args.manifest or None,
            allow_external_pending=False,
        )

    if args.issue_closure_json:
        issue_closure = _load_json(args.issue_closure_json)
    else:
        issue_closure = build_issue_closure_report(root, run_pip=False)

    payload = build_final_acceptance_gate(
        goal_status=goal_status,
        client_delivery=client_delivery,
        package_check=package_check,
        issue_closure=issue_closure,
        delivery_audit=delivery_audit,
        operator_pressure=operator_pressure,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps final acceptance gate: {payload['status'].upper()}")
        if payload.get("failed_checks"):
            print(f"failed_checks={','.join(payload['failed_checks'])}")
        for action in payload.get("next_actions") or []:
            print(f"next={action}")
    return 0 if payload["final_delivery_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
