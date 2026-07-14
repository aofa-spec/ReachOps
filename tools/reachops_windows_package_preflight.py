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

from ReachOps.version import VERSION


REQUIRED_FILES = {
    "dependency_lock": "requirements.lock",
    "dependency_baseline_verifier": "tools/verify_reachops_dependency_baseline.py",
    "dependency_license_inventory": "ReachOps/packaging/dependency-license-inventory.json",
    "data_governance": "tools/reachops_data_governance.py",
    "data_migrations": "ReachOps/intelligence/migrations.py",
    "security_signing": "ReachOps/security_signing.py",
    "windows_build_script": "tools/build_reachops_windows.ps1",
    "pyinstaller_spec": "ReachOps/packaging/reachops.spec",
    "inno_setup_script": "ReachOps/packaging/ReachOps.iss",
    "windows_requirements": "ReachOps/packaging/requirements-reachops.txt",
    "app_entry": "ReachOpsApp.py",
    "launcher": "ReachOps/launcher.py",
    "web_ui": "tools/reachops_web_ui.py",
    "acceptance_script": "tools/run_reachops_acceptance_windows.ps1",
    "installer_smoke": "tools/run_reachops_installer_smoke_windows.ps1",
    "ui_startup_smoke": "tools/run_reachops_ui_startup_smoke_windows.ps1",
    "live_validation_manifest": "tools/run_reachops_live_validation_manifest_windows.ps1",
    "acceptance_inputs_init": "tools/init_reachops_acceptance_inputs_windows.ps1",
    "acceptance_inputs_init_cross_platform": "tools/init_reachops_acceptance_inputs.py",
    "acceptance_inputs_template": "tools/reachops_acceptance_inputs.example.ps1",
    "live_acceptance_status": "tools/reachops_live_acceptance_status.py",
    "authorization_handoff_bundle": "tools/reachops_authorization_handoff_bundle.py",
    "manifest_writer": "tools/write_reachops_update_manifest.py",
    "release_evidence": "tools/reachops_release_evidence.py",
    "outcome_metrics": "tools/reachops_outcome_metrics.py",
    "package_check": "tools/reachops_delivery_package_check.py",
    "final_gate": "tools/reachops_final_acceptance_gate.py",
    "repository_cleanliness": "tools/reachops_repository_cleanliness_check.py",
    "acceptance_summary_verifier": "tools/verify_reachops_acceptance_summary.py",
}

FINAL_ARTIFACTS = {
    "exe": "dist/ReachOps/ReachOps.exe",
    "installer": f"dist/installer/ReachOps-Setup-{VERSION}.exe",
    "manifest": "dist/installer/reachops-update-manifest.json",
    "acceptance_summary": "reports/reachops_acceptance/acceptance_summary.json",
}

SCRIPT_EXPECTATIONS = {
    "tools/build_reachops_windows.ps1": [
        "requirements.lock",
        "tools\\verify_reachops_dependency_baseline.py",
        "--json",
        "Install ReachOps locked requirements",
        "tools\\reachops_windows_package_preflight.py",
        "windows_package_preflight.json",
        "PyInstaller --clean --noconfirm ReachOps\\packaging\\reachops.spec",
        "ReachOps\\packaging\\ReachOps.iss",
        "tools\\write_reachops_update_manifest.py",
        "tools\\reachops_release_evidence.py",
        "ReachOps release evidence",
        "tools\\reachops_final_acceptance_gate.py",
        "tools\\reachops_repository_cleanliness_check.py",
        "tools\\verify_reachops_acceptance_summary.py",
        "ISCC.exe not found",
        "pass -SkipInstaller for a non-final EXE-only build",
    ],
    "tools/run_reachops_acceptance_windows.ps1": [
        "windows_package_preflight.json",
        "windows_package_preflight",
        "tools\\reachops_windows_package_preflight.py",
        "repository_cleanliness_payload.json",
        "goal_status_report.json",
        "latest_live_acceptance_readiness.json",
        "latest_reachops_authorization_handoff.zip",
        "tools\\reachops_authorization_handoff_bundle.py",
        "final_acceptance_gate.json",
        "delivery_package_check.json",
        "Add-FinalGateToAcceptanceSummary",
        "tools\\reachops_final_acceptance_gate.py",
    ],
    "ReachOps/packaging/ReachOps.iss": [
        "OutputDir=..\\..\\dist\\installer",
        "OutputBaseFilename=ReachOps-Setup-{#MyAppVersion}",
        "Source: \"..\\..\\dist\\ReachOps\\*\"",
    ],
    "ReachOps/packaging/reachops.spec": [
        "ReachOpsApp.py",
        "name=\"ReachOps\"",
        "ixbrowser_local_api",
        "selenium.webdriver.chrome.webdriver",
    ],
    "ReachOps/packaging/requirements-reachops.txt": [
        "-r ../../requirements.lock",
    ],
    "requirements.txt": [
        "-r requirements.lock",
    ],
    "requirements.lock": [
        "requests==",
        "Pillow==",
        "selenium==",
        "ixbrowser-local-api==",
        "pyinstaller==",
    ],
    "ReachOps/packaging/dependency-license-inventory.json": [
        "reachops.dependency_license_inventory.v1",
        "requirements.lock",
        "commercial_review_required_for_unknown_license",
    ],
    "tools/verify_reachops_dependency_baseline.py": [
        "reachops.dependency_baseline.v1",
        "requirements_lock_line_",
        "dependency_license_inventory",
    ],
    "tools/reachops_data_governance.py": [
        "reachops.data_governance.v1",
        "backup_and_restore_verify",
        "SUPPORT_BUNDLE_EXCLUDE_PATTERNS",
        "RETENTION_CLASSES",
        "DATA_CATALOG",
        "inspect_migration_status",
        "versioned_forward_migrations_with_documented_rollback",
        "SCHEMA_MIGRATION_TABLE",
    ],
    "ReachOps/intelligence/migrations.py": [
        "SchemaMigration",
        "MIGRATIONS",
        "20260714_0001_data_privacy_audit",
        "20260714_0002_lead_outcomes",
        "lead_outcomes",
        "data_privacy_audit",
        "rollback_policy",
    ],
    "ReachOps/intelligence/storage.py": [
        "apply_schema_migrations",
    ],
    "ReachOps/security_signing.py": [
        "SIGNATURE_ALGORITHM",
        "canonical_payload",
        "sign_payload",
        "verify_signed_payload",
    ],
    "ReachOps/workbench/authorization_gate.py": [
        "entitlement_signature",
        "LIVE_SUBMIT_ENTITLEMENT_SIGNATURE_INVALID",
        "LIVE_SUBMIT_ENTITLEMENT_REVOKED",
        "LIVE_SUBMIT_OFFLINE_GRACE_EXPIRED",
        "LIVE_SUBMIT_DEVICE_LIMIT_EXCEEDED",
        "LIVE_SUBMIT_FEATURE_DISABLED",
        "packaged runtime requires a valid signed entitlement",
    ],
    "ReachOps/updater.py": [
        "require_signature = True",
        "manifest_signature",
        "manifest signature invalid",
        "manifest channel mismatch",
        "manifest installer.size_bytes is required",
        "rollback_policy",
        "rollback_available",
    ],
    "tools/write_reachops_update_manifest.py": [
        "sign_payload",
        "manifest_signature",
        "rollback_policy",
        "--signing-key-id",
        "--signing-key",
    ],
    "tools/reachops_outcome_metrics.py": [
        "reachops.outcome_metrics.v1",
        "reachops.waqo_definition.v1",
        "Weekly Accepted Qualified Opportunities",
        "fixture_data_excluded_by_default",
        "lead-to-revenue",
    ],
    "tools/reachops_release_evidence.py": [
        "reachops.release_evidence.v1",
        "reachops-release-evidence.json",
        "reachops-rollback-note.md",
        "check_delivery_package",
        "build_dependency_report",
    ],
    ".github/workflows/reachops-ci.yml": [
        "cache-dependency-path: requirements.lock",
        "tools/verify_reachops_dependency_baseline.py --json",
    ],
}


def _status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists and path.is_file() else 0,
    }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def build_preflight(root: str | Path = ROOT_DIR) -> dict[str, Any]:
    root = Path(root).resolve()
    failures: list[str] = []
    files: dict[str, Any] = {}
    for name, relative in REQUIRED_FILES.items():
        detail = _status(root / relative)
        files[name] = detail
        if not detail["exists"]:
            failures.append(f"{name}_missing")
        elif int(detail.get("size") or 0) <= 0:
            failures.append(f"{name}_empty")

    contract_checks: dict[str, Any] = {}
    for relative, needles in SCRIPT_EXPECTATIONS.items():
        path = root / relative
        text = _read(path)
        missing = [needle for needle in needles if needle not in text]
        contract_checks[relative] = {
            "path": str(path),
            "ok": not missing and path.exists(),
            "missing": missing,
        }
        failures.extend(f"{relative}:{needle}:missing" for needle in missing)

    artifacts = {name: _status(root / relative) for name, relative in FINAL_ARTIFACTS.items()}
    missing_artifacts = list(FINAL_ARTIFACTS)

    status = "ready_for_windows_build" if not failures else "failed"
    return {
        "product": "ReachOps",
        "status": status,
        "ready_for_windows_build": not failures,
        "final_delivery_ready": False,
        "root": str(root),
        "version": VERSION,
        "failures": failures,
        "files": files,
        "contract_checks": contract_checks,
        "final_artifacts": artifacts,
        "missing_final_artifacts": missing_artifacts,
        "build_contract": {
            "default_build_requires_installer": True,
            "skip_installer_is_non_final": True,
            "preflight_report_path": str(root / "reports/reachops_acceptance/windows_package_preflight.json"),
        },
        "next_actions": [
            "在 Windows 机器安装 Python 3.11、PyInstaller 依赖和 Inno Setup 6。",
            "运行 powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1。",
            "填入已授权验收输入后运行 tools\\run_reachops_acceptance_windows.ps1。",
            "最终运行 python tools\\reachops_final_acceptance_gate.py --json，确认 status=passed。",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps Windows packaging inputs before final build.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_preflight(args.root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps Windows package preflight: {payload['status']}")
        if payload["failures"]:
            print("Failures: " + ", ".join(payload["failures"]))
        if payload["missing_final_artifacts"]:
            print("Missing final artifacts: " + ", ".join(payload["missing_final_artifacts"]))
    return 0 if payload["ready_for_windows_build"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
