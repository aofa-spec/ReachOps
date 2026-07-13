# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.version import PRODUCT_ID, VERSION
from tools.verify_reachops_acceptance_summary import load_summary, verify_summary

REQUIRED_FINAL_GATE_CHECKS = {
    "goal_status:passed",
    "client_delivery:final_ready",
    "delivery_package:passed",
    "delivery_audit:no_failed_checks",
    "operator_pressure:leads_and_actions",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _file_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists and path.is_file() else 0,
    }


def _windows_pe_status(path: Path) -> dict[str, Any]:
    detail = _file_status(path)
    dos_signature_valid = False
    pe_header_signature_valid = False
    pe_header_offset = 0
    if detail["exists"] and int(detail.get("size") or 0) >= 64:
        try:
            with path.open("rb") as fh:
                dos_signature_valid = fh.read(2) == b"MZ"
                fh.seek(0x3C)
                pe_header_offset = int.from_bytes(fh.read(4), "little")
                if 0 < pe_header_offset <= int(detail.get("size") or 0) - 4:
                    fh.seek(pe_header_offset)
                    pe_header_signature_valid = fh.read(4) == b"PE\x00\x00"
        except Exception:
            dos_signature_valid = False
            pe_header_signature_valid = False
            pe_header_offset = 0
    detail["pe_dos_signature_valid"] = dos_signature_valid
    detail["pe_header_offset"] = pe_header_offset
    detail["pe_header_signature_valid"] = pe_header_signature_valid
    detail["pe_signature_valid"] = bool(dos_signature_valid and pe_header_signature_valid)
    return detail


def _latest_acceptance_summary(root: Path) -> Path:
    reports_dir = root / "reports" / "reachops_acceptance"
    candidates = list(reports_dir.glob("*/acceptance_summary.json"))
    if not candidates:
        return reports_dir / "acceptance_summary.json"
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _default_manifest(root: Path) -> Path:
    candidates = [
        root / "reachops-update-manifest.json",
        root / "dist" / "installer" / "reachops-update-manifest.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _manifest_installer_path(root: Path, manifest_path: Path, manifest: dict[str, Any]) -> Path:
    installer = manifest.get("installer") if isinstance(manifest.get("installer"), dict) else {}
    raw_path = str(installer.get("path") or "")
    file_name = str(installer.get("file_name") or "")
    if raw_path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        resolved = root / path
        if resolved.exists():
            return resolved
        return manifest_path.parent / path
    if file_name:
        return manifest_path.parent / file_name
    return manifest_path.parent / f"ReachOps-Setup-{VERSION}.exe"


def _check_manifest(root: Path, manifest_path: Path, installer_path: Path) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    detail: dict[str, Any] = {"path": str(manifest_path), "exists": manifest_path.exists()}
    if not manifest_path.exists():
        failures.append("manifest_missing")
        return failures, detail
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append("manifest_invalid_json")
        detail["error"] = str(exc)
        return failures, detail

    installer = manifest.get("installer") if isinstance(manifest.get("installer"), dict) else {}
    manifest_installer = _manifest_installer_path(root, manifest_path, manifest)
    expected_sha = str(installer.get("sha256") or "")
    expected_size = int(installer.get("size_bytes") or 0)
    actual_installer = installer_path if installer_path.exists() else manifest_installer
    detail.update(
        {
            "product_id": manifest.get("product_id"),
            "version": manifest.get("version"),
            "platform": manifest.get("platform"),
            "installer_path": str(actual_installer),
            "expected_sha256": expected_sha,
            "expected_size": expected_size,
        }
    )

    if str(manifest.get("product_id") or "") != PRODUCT_ID:
        failures.append("manifest_product_mismatch")
    if str(manifest.get("version") or "") != VERSION:
        failures.append("manifest_version_mismatch")
    if str(manifest.get("platform") or "") != "windows":
        failures.append("manifest_platform_mismatch")
    if not actual_installer.exists():
        failures.append("manifest_installer_missing")
        return failures, detail
    actual_size = actual_installer.stat().st_size
    actual_sha = sha256_file(actual_installer)
    detail["actual_sha256"] = actual_sha
    detail["actual_size"] = actual_size
    if expected_size and expected_size != actual_size:
        failures.append("manifest_size_mismatch")
    if expected_sha and expected_sha != actual_sha:
        failures.append("manifest_sha256_mismatch")
    if not expected_sha:
        failures.append("manifest_sha256_missing")
    return failures, detail


def _report_sections(summary: dict[str, Any], final_required: bool, require_final_gate: bool) -> list[str]:
    sections = [
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
    ]
    if final_required:
        sections.append("live_submit")
    else:
        for optional in ["live_submit"]:
            section = summary.get(optional) if isinstance(summary.get(optional), dict) else {}
            if section.get("json_path"):
                sections.append(optional)
    final_gate = summary.get("final_acceptance_gate") if isinstance(summary.get("final_acceptance_gate"), dict) else {}
    if require_final_gate or final_gate.get("json_path"):
        sections.append("final_acceptance_gate")
    return sections


def _pending_actions(pending: list[Any]) -> list[str]:
    mapping = {
        "external_platform_validation": "Complete external platform validation and regenerate acceptance_summary.json.",
        "live_preflight_environment_validation": "Fix ixBrowser profile/proxy/login environment and rerun no-submit live preflight.",
        "live_authorization_execution_validation": "Run readiness/preflight, then controlled live submit with confirmed authorized targets and active license.",
        "real_tiktok_platform_submit": "Complete platform_selenium live submit with real ixBrowser profiles and authorized TikTok targets.",
        "client_delivery_acceptance_gate": "Rerun client delivery acceptance until acceptance_ready=true and readiness=pass.",
    }
    actions: list[str] = []
    for item in pending:
        code = str(item or "").strip()
        if not code:
            continue
        action = mapping.get(code, f"Resolve pending validation item: {code}")
        if action not in actions:
            actions.append(action)
    return actions


def _remediation_plan(
    *,
    root: Path,
    missing_artifacts: list[str],
    failures: list[str],
    acceptance_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    artifact_actions = {
        "exe": {
            "expected_path": str(root / "dist" / "ReachOps" / "ReachOps.exe"),
            "producer": "tools\\build_reachops_windows.ps1",
            "command": "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
        },
        "installer": {
            "expected_path": str(root / "dist" / "installer" / f"ReachOps-Setup-{VERSION}.exe"),
            "producer": "tools\\build_reachops_windows.ps1",
            "command": "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
        },
        "manifest": {
            "expected_path": str(manifest_path),
            "producer": "tools\\write_reachops_update_manifest.py",
            "command": "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
        },
        "acceptance_summary": {
            "expected_path": str(acceptance_path),
            "producer": "tools\\run_reachops_acceptance_windows.ps1",
            "command": "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
        },
    }
    return {
        "summary": (
            "Windows 最终交付包未闭环：需要在 Windows 实机生成缺失产物、完成授权验收，再复跑严格最终门禁。"
            if missing_artifacts or failures
            else "Windows 最终交付包已满足当前检查。"
        ),
        "missing_final_artifacts": list(missing_artifacts),
        "failure_codes": list(failures),
        "artifact_actions": {
            name: detail
            for name, detail in artifact_actions.items()
            if name in set(missing_artifacts) or f"{name}_missing" in set(failures)
        },
        "commands": [
            "powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1",
            "powershell -ExecutionPolicy Bypass -File tools\\init_reachops_acceptance_inputs_windows.ps1 -Json",
            "python tools\\reachops_live_acceptance_status.py --local-inputs-path tools\\reachops_acceptance_inputs.local.ps1 --write-report --json-report-path --json",
            "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_acceptance_windows.ps1 -InputFile tools\\reachops_acceptance_inputs.local.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets",
            "python tools\\reachops_authorization_handoff_bundle.py --verify --output-path reports\\reachops_acceptance\\<timestamp>\\latest_reachops_authorization_handoff.zip --json",
            "python tools\\reachops_delivery_package_check.py --json",
            "python tools\\reachops_final_acceptance_gate.py --json",
        ],
        "final_acceptance_required": {
            "package_check_status": "passed",
            "package_check_final_delivery_ready": True,
            "final_gate_status": "passed",
            "final_gate_final_delivery_ready": True,
        },
    }


def _final_gate_convergence_allowed(report_payload: dict[str, Any], checks_by_name: dict[str, Any]) -> bool:
    failed_checks = [str(item) for item in report_payload.get("failed_checks") or []]
    if failed_checks != ["delivery_package:passed"]:
        return False
    delivery_check = checks_by_name.get("delivery_package:passed")
    if not isinstance(delivery_check, dict) or bool(delivery_check.get("ok")):
        return False
    evidence = delivery_check.get("evidence") if isinstance(delivery_check.get("evidence"), dict) else {}
    return bool(evidence.get("bootstrap_only")) or "allow_missing_final_gate" in " ".join(
        str(item) for item in evidence.get("not_final_delivery_reasons") or []
    )


def _inspect_final_gate_report(
    summary: dict[str, Any], report_files: dict[str, dict[str, Any]], allow_final_gate_convergence: bool = False
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    final_gate_summary = summary.get("final_acceptance_gate") if isinstance(summary.get("final_acceptance_gate"), dict) else {}
    final_gate_report = report_files.get("final_acceptance_gate") if isinstance(report_files.get("final_acceptance_gate"), dict) else {}
    report_path = Path(str(final_gate_report.get("path") or ""))
    details: dict[str, Any] = {
        "path": str(report_path) if str(report_path) != "." else "",
        "exists": bool(final_gate_report.get("exists")),
        "size": int(final_gate_report.get("size") or 0),
        "required_checks": sorted(REQUIRED_FINAL_GATE_CHECKS),
        "present_required_checks": [],
        "missing_required_checks": sorted(REQUIRED_FINAL_GATE_CHECKS),
        "failed_required_checks": [],
        "checks_by_name": {},
        "convergence_only": False,
    }
    if not final_gate_report.get("exists") or int(final_gate_report.get("size") or 0) <= 0:
        return failures, details
    try:
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        details["error"] = str(exc)
        return ["final_acceptance_gate_json_invalid"], details
    if not isinstance(report_payload, dict):
        details["error"] = "final gate report root is not an object"
        return ["final_acceptance_gate_json_invalid"], details
    details.update(
        {
            "status": str(report_payload.get("status") or ""),
            "final_delivery_ready": bool(report_payload.get("final_delivery_ready")),
            "failed_checks": list(report_payload.get("failed_checks") or []),
        }
    )
    checks = report_payload.get("checks") if isinstance(report_payload.get("checks"), list) else []
    checks_by_name = {str(row.get("name") or ""): row for row in checks if isinstance(row, dict)}
    present_checks = sorted(REQUIRED_FINAL_GATE_CHECKS & set(checks_by_name))
    missing_checks = sorted(REQUIRED_FINAL_GATE_CHECKS - set(checks_by_name))
    failed_checks = sorted(
        name for name in present_checks if not bool((checks_by_name.get(name) or {}).get("ok"))
    )
    details.update(
        {
            "present_required_checks": present_checks,
            "missing_required_checks": missing_checks,
            "failed_required_checks": failed_checks,
            "checks_by_name": checks_by_name,
        }
    )
    convergence_only = (
        allow_final_gate_convergence
        and not missing_checks
        and failed_checks == ["delivery_package:passed"]
        and _final_gate_convergence_allowed(report_payload, checks_by_name)
    )
    details["convergence_only"] = convergence_only
    if str(report_payload.get("status") or "") != "passed" and not convergence_only:
        failures.append("final_acceptance_gate_json_not_passed")
    if not bool(report_payload.get("final_delivery_ready")) and not convergence_only:
        failures.append("final_acceptance_gate_json_not_ready")
    if report_payload.get("failed_checks") and not convergence_only:
        failures.append("final_acceptance_gate_json_failed_checks")
    if missing_checks:
        failures.append("final_acceptance_gate_json_checks_missing")
    elif failed_checks and not convergence_only:
        failures.append("final_acceptance_gate_json_checks_failed")
    if not convergence_only:
        for key in ("status", "final_delivery_ready", "failed_checks"):
            if final_gate_summary.get(key) != report_payload.get(key):
                failures.append("final_acceptance_gate_json_mismatch")
                break
    return failures, details


def check_delivery_package(
    root: str | Path = ROOT_DIR,
    acceptance_summary_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    allow_external_pending: bool = False,
    allow_missing_final_gate: bool = False,
    allow_final_gate_convergence: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    acceptance_path = _resolve(root, acceptance_summary_path) if acceptance_summary_path else _latest_acceptance_summary(root)
    manifest = _resolve(root, manifest_path) if manifest_path else _default_manifest(root)
    exe = root / "dist" / "ReachOps" / "ReachOps.exe"
    installer = root / "dist" / "installer" / f"ReachOps-Setup-{VERSION}.exe"
    failures: list[str] = []
    missing_artifacts: list[str] = []
    final_gate_report: dict[str, Any] = {}
    if not _is_relative_to(acceptance_path, root):
        failures.append("acceptance_summary_outside_root")
    if not _is_relative_to(manifest, root):
        failures.append("manifest_outside_root")

    artifact_status = {
        "exe": _windows_pe_status(exe),
        "installer": _windows_pe_status(installer),
        "manifest": _file_status(manifest),
        "acceptance_summary": _file_status(acceptance_path),
    }
    for key, detail in artifact_status.items():
        if not detail["exists"]:
            missing_artifacts.append(key)
            failures.append(f"{key}_missing")
        elif key in {"exe", "installer"}:
            if int(detail.get("size") or 0) <= 0:
                failures.append(f"{key}_empty")
            if not bool(detail.get("pe_signature_valid")):
                failures.append(f"{key}_not_windows_pe")

    summary: dict[str, Any] = {}
    acceptance_verification: dict[str, Any] = {
        "passed": False,
        "failures": ["acceptance_summary_missing"],
        "pending": [],
    }
    verification_failures: list[str] = ["acceptance_summary_missing"]
    if acceptance_path.exists():
        summary = load_summary(acceptance_path)
        acceptance_verification = verify_summary(
            summary,
            allow_external_pending=allow_external_pending,
            summary_path=acceptance_path,
        )
        verification_failures = list(acceptance_verification.get("failures") or [])
        if allow_missing_final_gate:
            verification_failures = [failure for failure in verification_failures if failure != "final_acceptance_gate_missing"]

    manifest_failures, manifest_detail = _check_manifest(root, manifest, installer)
    failures.extend(manifest_failures)
    failures = list(dict.fromkeys(failures))
    artifact_status["manifest"].update(manifest_detail)

    report_files: dict[str, dict[str, Any]] = {}
    if summary:
        require_final_gate = not allow_external_pending and not allow_missing_final_gate
        acceptance_report_dir = acceptance_path.parent
        for section_name in _report_sections(summary, final_required=not allow_external_pending, require_final_gate=require_final_gate):
            section = summary.get(section_name) if isinstance(summary.get(section_name), dict) else {}
            path_value = str(section.get("json_path") or "")
            if not path_value:
                failures.append(f"{section_name}_json_path_missing")
                report_files[section_name] = {"path": "", "exists": False, "size": 0}
                continue
            report_path = _resolve(root, path_value)
            detail = _file_status(report_path)
            report_files[section_name] = detail
            if not _is_relative_to(report_path, acceptance_report_dir):
                failures.append(f"{section_name}_json_outside_acceptance_dir")
            if not detail["exists"]:
                failures.append(f"{section_name}_json_missing")
            elif int(detail.get("size") or 0) <= 0:
                failures.append(f"{section_name}_json_empty")
        if require_final_gate:
            final_gate_failures, final_gate_report = _inspect_final_gate_report(
                summary,
                report_files,
                allow_final_gate_convergence=allow_final_gate_convergence,
            )
            failures.extend(final_gate_failures)

    if allow_final_gate_convergence and bool(final_gate_report.get("convergence_only")):
        verification_failures = [
            failure
            for failure in verification_failures
            if failure
            not in {
                "final_acceptance_gate_not_passed",
                "final_acceptance_gate_not_ready",
                "final_acceptance_gate_failed_checks",
            }
        ]
    if acceptance_path.exists():
        original_acceptance_passed = bool(acceptance_verification.get("passed"))
        filtered_acceptance_passed = original_acceptance_passed and not verification_failures
        if allow_final_gate_convergence and bool(final_gate_report.get("convergence_only")):
            filtered_acceptance_passed = bool(not verification_failures and not acceptance_verification.get("pending"))
        acceptance_verification = {
            **acceptance_verification,
            "failures": verification_failures,
            "passed": filtered_acceptance_passed,
        }
    if verification_failures or (not acceptance_verification.get("passed") and not allow_missing_final_gate):
        failures.append("acceptance_summary_not_passed")

    bootstrap_only = bool(allow_missing_final_gate)
    not_final_delivery_reasons: list[str] = []
    if bootstrap_only:
        not_final_delivery_reasons.append("allow_missing_final_gate is bootstrap-only; rerun without it after final_acceptance_gate.json is written.")
    if allow_final_gate_convergence and bool(final_gate_report.get("convergence_only")):
        not_final_delivery_reasons.append("allow_final_gate_convergence is an intermediate convergence pass; rerun strict package check after final_acceptance_gate.json is rewritten.")

    final_ready = not failures
    status = "passed" if final_ready else "failed"
    if allow_external_pending and not failures and acceptance_verification.get("pending"):
        status = "ready_for_external_validation"

    remediation_plan = _remediation_plan(
        root=root,
        missing_artifacts=missing_artifacts,
        failures=failures,
        acceptance_path=acceptance_path,
        manifest_path=manifest,
    )
    return {
        "status": status,
        "passed": final_ready,
        "final_delivery_ready": bool(final_ready and not bootstrap_only),
        "bootstrap_only": bootstrap_only,
        "not_final_delivery_reasons": not_final_delivery_reasons,
        "allow_external_pending": bool(allow_external_pending),
        "allow_missing_final_gate": bool(allow_missing_final_gate),
        "allow_final_gate_convergence": bool(allow_final_gate_convergence),
        "root": str(root),
        "failures": failures,
        "pending_external_validation": list(acceptance_verification.get("pending") or []),
        "pending_external_actions": _pending_actions(list(acceptance_verification.get("pending") or [])),
        "missing_artifacts": missing_artifacts,
        "remediation_plan": remediation_plan,
        "artifacts": artifact_status,
        "report_files": report_files,
        "final_gate_report": final_gate_report,
        "acceptance_verification": acceptance_verification,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps final delivery package artifacts.")
    parser.add_argument("--root", default=str(ROOT_DIR), help="ReachOps repository root.")
    parser.add_argument("--acceptance-summary", default="", help="Path to acceptance_summary.json. Defaults to latest report.")
    parser.add_argument("--manifest", default="", help="Path to reachops-update-manifest.json.")
    parser.add_argument("--allow-external-pending", action="store_true", help="Allow ready_for_external_validation interim package.")
    parser.add_argument("--allow-missing-final-gate", action="store_true", help="Bootstrap mode before final_acceptance_gate.json is generated.")
    parser.add_argument("--allow-final-gate-convergence", action="store_true", help="Intermediate Windows acceptance pass used to resolve the final gate/package self-reference.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = check_delivery_package(
            root=args.root,
            acceptance_summary_path=args.acceptance_summary or None,
            manifest_path=args.manifest or None,
            allow_external_pending=args.allow_external_pending,
            allow_missing_final_gate=args.allow_missing_final_gate,
            allow_final_gate_convergence=args.allow_final_gate_convergence,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "passed": False,
            "allow_external_pending": bool(args.allow_external_pending),
            "allow_missing_final_gate": bool(args.allow_missing_final_gate),
            "allow_final_gate_convergence": bool(args.allow_final_gate_convergence),
            "failures": [exc.__class__.__name__],
            "error": str(exc),
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps delivery package status: {result.get('status')}")
        if result.get("failures"):
            print(f"Failures: {', '.join(result['failures'])}")
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
