# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


REQUIRED_PACKAGE_REPORT_FILES = (
    "delivery_audit",
    "operator_pressure",
    "installer_smoke",
    "ui_startup",
    "activation_status",
    "live_acceptance_status",
    "live_validation",
    "repository_cleanliness",
    "windows_package_preflight",
    "client_delivery",
    "live_readiness",
    "live_preflight",
    "goal_status",
    "live_submit",
    "final_acceptance_gate",
    "issue_closure",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_acceptance_summary(reports_dir: Path) -> Path:
    if not reports_dir.exists():
        return Path()
    candidates = sorted(
        [item / "acceptance_summary.json" for item in reports_dir.iterdir() if item.is_dir() and (item / "acceptance_summary.json").exists()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else Path()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def pending_external_items(summary: dict[str, Any], verification: dict[str, Any]) -> list[str]:
    goal_status = _as_dict(summary.get("goal_status"))
    items: list[str] = []
    for value in (
        summary.get("pending_external_validation"),
        goal_status.get("pending_external_validation"),
        verification.get("pending"),
    ):
        for item in _as_list(value):
            text = str(item or "").strip()
            if text and text not in items:
                items.append(text)
    return items


def pending_external_actions(pending_items: list[str]) -> list[str]:
    mapping = {
        "授权允许时能真实执行": "Run readiness/preflight, then controlled live submit with confirmed authorized targets and active license.",
        "真实 TikTok 平台提交": "Complete platform_selenium live submit with real ixBrowser profiles and authorized TikTok targets.",
        "客户端交付验收门禁不会把环境阻断当通过": "Rerun client delivery acceptance until acceptance_ready=true and readiness=pass.",
        "external_platform_validation": "Complete external platform validation and regenerate acceptance_summary.json.",
        "live_preflight_environment_validation": "Fix ixBrowser profile/proxy/login environment and rerun no-submit live preflight.",
        "client_delivery_acceptance_gate": "Rerun client delivery acceptance until acceptance_ready=true and readiness=pass.",
        "real_tiktok_platform_submit": "Complete platform_selenium live submit with real ixBrowser profiles and authorized TikTok targets.",
        "live_authorization_execution_validation": "Run readiness/preflight, then controlled live submit with confirmed authorized targets and active license.",
    }
    actions: list[str] = []
    for item in pending_items:
        action = mapping.get(str(item), f"Resolve pending external validation item: {item}")
        if action not in actions:
            actions.append(action)
    return actions


def build_report(summary: dict[str, Any], summary_path: str = "", package_check: dict[str, Any] | None = None) -> dict[str, Any]:
    live_preflight = _as_dict(summary.get("live_preflight"))
    live_readiness = _as_dict(summary.get("live_readiness"))
    live_validation = _as_dict(summary.get("live_validation"))
    live_submit = _as_dict(summary.get("live_submit"))
    delivery_audit = _as_dict(summary.get("delivery_audit"))
    final_acceptance_gate = _as_dict(summary.get("final_acceptance_gate"))
    verification = _as_dict(summary.get("acceptance_verification"))
    package = package_check if isinstance(package_check, dict) else {}
    if not package and summary_path:
        package = load_json(Path(summary_path).parent / "delivery_package_check.json")
    environment = _as_dict(live_preflight.get("environment_diagnostics"))
    if not environment:
        environment = _as_dict(_as_dict(verification.get("live_preflight")).get("environment"))

    failed_profile_ids = [str(item) for item in _as_list(environment.get("failed_profile_ids"))]
    ready_profile_ids = [str(item) for item in _as_list(environment.get("ready_profile_ids"))]
    classification_counts = _as_dict(environment.get("classification_counts"))
    next_required_actions = [str(item) for item in _as_list(environment.get("next_required_actions"))]
    missing_validation_inputs = [str(item) for item in _as_list(live_validation.get("missing_inputs"))]
    if not missing_validation_inputs:
        missing_validation_inputs = [str(item) for item in _as_list(_as_dict(verification.get("live_validation")).get("missing_inputs"))]

    blockers: list[dict[str, Any]] = []
    blocking_stage = str(environment.get("blocking_stage") or "")
    if blocking_stage:
        blockers.append(
            {
                "code": blocking_stage,
                "scope": "ixbrowser_profile_environment",
                "profile_ids": failed_profile_ids,
                "classifications": classification_counts,
                "next_actions": next_required_actions,
            }
        )
    if str(live_readiness.get("status") or "") == "blocked" or not bool(live_readiness.get("ready")):
        blockers.append(
            {
                "code": "live_readiness_blocked",
                "scope": "authorization_or_inputs",
                "missing_inputs": missing_validation_inputs,
            }
        )
    if str(live_submit.get("status") or "") in {"", "skipped"}:
        blockers.append(
            {
                "code": "live_submit_not_run",
                "scope": "controlled_live_submit",
                "reason": "RunLiveSubmit remains disabled until readiness/preflight pass and targets are authorized.",
            }
        )
    final_gate_ready = str(final_acceptance_gate.get("status") or "") == "passed" and bool(final_acceptance_gate.get("final_delivery_ready"))
    package_artifacts = _as_dict(package.get("artifacts"))
    package_report_files = _as_dict(package.get("report_files"))
    package_acceptance_verification = _as_dict(package.get("acceptance_verification"))
    package_artifacts_ready = all(
        bool(_as_dict(package_artifacts.get(name)).get("exists"))
        and int(_as_dict(package_artifacts.get(name)).get("size") or 0) > 0
        for name in ("exe", "installer", "manifest", "acceptance_summary")
    )
    manifest = _as_dict(package_artifacts.get("manifest"))
    expected_sha = str(manifest.get("expected_sha256") or "")
    actual_sha = str(manifest.get("actual_sha256") or "")
    expected_size = int(manifest.get("expected_size") or 0)
    actual_size = int(manifest.get("actual_size") or 0)
    package_manifest_ready = (
        len(expected_sha) == 64
        and expected_sha == actual_sha
        and expected_size > 0
        and expected_size == actual_size
    )
    package_report_files_ready = all(
        bool(_as_dict(package_report_files.get(name)).get("exists"))
        and int(_as_dict(package_report_files.get(name)).get("size") or 0) > 0
        for name in REQUIRED_PACKAGE_REPORT_FILES
    )
    package_acceptance_verification_ready = (
        bool(package_acceptance_verification.get("passed"))
        and not package_acceptance_verification.get("failures")
        and not package_acceptance_verification.get("pending")
    )
    package_final_gate_report = _as_dict(package.get("final_gate_report"))
    package_final_gate_summary_ready = (
        str(package_final_gate_report.get("status") or "") == "passed"
        and bool(package_final_gate_report.get("final_delivery_ready"))
        and not package_final_gate_report.get("failed_checks")
        and not package_final_gate_report.get("missing_required_checks")
        and not package_final_gate_report.get("failed_required_checks")
        and bool(package_final_gate_report.get("checks_by_name"))
    )
    package_final_ready = (
        str(package.get("status") or "") == "passed"
        and bool(package.get("passed"))
        and bool(package.get("final_delivery_ready"))
        and not bool(package.get("bootstrap_only"))
        and package_final_gate_summary_ready
        and not package.get("failures")
        and not package.get("pending_external_validation")
        and package_artifacts_ready
        and package_manifest_ready
        and package_report_files_ready
        and package_acceptance_verification_ready
    )
    if package and not package_final_ready:
        blockers.append(
            {
                "code": "delivery_package_not_final_ready",
                "scope": "final_delivery_package",
                "status": str(package.get("status") or ""),
                "passed": bool(package.get("passed")),
                "final_delivery_ready": bool(package.get("final_delivery_ready")),
                "bootstrap_only": bool(package.get("bootstrap_only")),
                "failures": _as_list(package.get("failures")),
                "not_final_delivery_reasons": _as_list(package.get("not_final_delivery_reasons")),
                "pending_external_validation": _as_list(package.get("pending_external_validation")),
                "artifacts_ready": package_artifacts_ready,
                "manifest_ready": package_manifest_ready,
                "report_files_ready": package_report_files_ready,
                "acceptance_verification_ready": package_acceptance_verification_ready,
                "final_gate_report": package_final_gate_report,
                "final_gate_summary_ready": package_final_gate_summary_ready,
                "package_final_gate_summary_ready": package_final_gate_summary_ready,
            }
        )
    if not final_gate_ready:
        blockers.append(
            {
                "code": "final_acceptance_gate_not_ready",
                "scope": "final_delivery_gate",
                "status": str(final_acceptance_gate.get("status") or ""),
                "failed_checks": _as_list(final_acceptance_gate.get("failed_checks")),
            }
        )

    live_preflight_completed = str(live_preflight.get("status") or "") == "completed"
    missing_preflight_types = [str(item) for item in _as_list(live_preflight.get("missing_preflight_action_types"))]
    milestone3_ready = live_preflight_completed and bool(ready_profile_ids) and not missing_preflight_types
    effective_pending = int(delivery_audit.get("effective_pending_external_validation") or 0)
    pending_items = pending_external_items(summary, verification)
    pending_actions = pending_external_actions(pending_items)
    milestone4_ready = (
        str(summary.get("status") or "") == "passed"
        and effective_pending == 0
        and str(live_submit.get("status") or "") == "completed"
        and bool(live_submit.get("platform_validation"))
        and package_final_ready
        and final_gate_ready
    )

    return {
        "status": "passed" if milestone4_ready else "blocked",
        "summary_path": summary_path,
        "acceptance_status": str(summary.get("status") or verification.get("status") or ""),
        "milestone3_status": "ready" if milestone3_ready else "blocked",
        "milestone4_status": "passed" if milestone4_ready else "blocked",
        "no_submit": bool(live_preflight.get("no_submit", True)) and str(live_submit.get("status") or "") != "completed",
        "effective_pending_external_validation": effective_pending,
        "pending_external_validation": pending_items,
        "pending_external_actions": pending_actions,
        "final_acceptance_gate": {
            "status": str(final_acceptance_gate.get("status") or ""),
            "final_delivery_ready": bool(final_acceptance_gate.get("final_delivery_ready")),
            "failed_checks": _as_list(final_acceptance_gate.get("failed_checks")),
        },
        "delivery_package": {
            "status": str(package.get("status") or ""),
            "passed": bool(package.get("passed")),
            "final_delivery_ready": bool(package.get("final_delivery_ready")),
            "bootstrap_only": bool(package.get("bootstrap_only")),
            "failures": _as_list(package.get("failures")),
            "not_final_delivery_reasons": _as_list(package.get("not_final_delivery_reasons")),
            "pending_external_validation": _as_list(package.get("pending_external_validation")),
            "artifacts_ready": package_artifacts_ready,
            "manifest_ready": package_manifest_ready,
            "report_files_ready": package_report_files_ready,
            "acceptance_verification_ready": package_acceptance_verification_ready,
            "final_gate_summary_ready": package_final_gate_summary_ready,
            "package_final_gate_summary_ready": package_final_gate_summary_ready,
            "final_gate_report": package_final_gate_report,
        },
        "ready_profile_ids": ready_profile_ids,
        "failed_profile_ids": failed_profile_ids,
        "blocking_stage": blocking_stage,
        "classification_counts": classification_counts,
        "missing_preflight_action_types": missing_preflight_types,
        "missing_validation_inputs": missing_validation_inputs,
        "blockers": blockers,
        "safe_rerun_commands": {
            "background_acceptance_no_submit": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\start_reachops_acceptance_background_windows.ps1 -InputFile .\\tools\\reachops_acceptance_inputs.local.ps1",
            "background_status": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\get_reachops_acceptance_background_status_windows.ps1 -Json",
            "controlled_live_submit_after_authorization": "powershell -NoProfile -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets ...",
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize ReachOps live environment blockers from an acceptance summary.")
    parser.add_argument("--acceptance-summary", default="", help="Path to acceptance_summary.json. Defaults to latest reports/reachops_acceptance/*.")
    parser.add_argument("--reports-dir", default="", help="Acceptance reports directory used when --acceptance-summary is omitted.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary_path = Path(args.acceptance_summary) if args.acceptance_summary else latest_acceptance_summary(Path(args.reports_dir or ROOT_DIR / "reports" / "reachops_acceptance"))
    if not summary_path or not summary_path.exists():
        report = {"status": "missing", "error": "acceptance_summary.json not found"}
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    summary = load_json(summary_path)
    report = build_report(summary, str(summary_path))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") != "missing" else 2


if __name__ == "__main__":
    raise SystemExit(main())
