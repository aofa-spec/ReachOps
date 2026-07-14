# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.verify_reachops_dependency_baseline import build_report as build_dependency_report


SCHEMA_VERSION = "reachops.ci_release_baseline_audit.v1"
SUPPORTED_PYTHON = "3.11"
SUPPORTED_WINDOWS_RUNNER = "windows-latest"
SUPPORTED_LINUX_RUNNER = "ubuntu-latest"
EXTERNAL_GOVERNANCE_GATES = [
    "main_branch_protection_requires_pr_review",
    "main_branch_protection_requires_successful_checks",
    "ten_consecutive_ci_runs_without_code_failure",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _contains_all(text: str, needles: list[str]) -> bool:
    return all(needle in text for needle in needles)


def run_pip_check() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=str(ROOT_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": f"{Path(sys.executable).name} -m pip check",
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "output": result.stdout.strip(),
    }


def build_report(root: str | Path = ROOT_DIR, *, run_pip: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    workflow = _read(root / ".github" / "workflows" / "reachops-ci.yml")
    release_evidence = _read(root / "tools" / "reachops_release_evidence.py")
    build_script = _read(root / "tools" / "build_reachops_windows.ps1")
    dependency_baseline = build_dependency_report(root)
    pip_check = run_pip_check() if run_pip else {
        "command": f"{Path(sys.executable).name} -m pip check",
        "returncode": None,
        "passed": None,
        "output": "skipped",
    }

    ci_contract = {
        "workflow_exists": bool(workflow),
        "pull_request_trigger": "pull_request:" in workflow,
        "main_push_trigger": "branches:\n      - main" in workflow,
        "linux_full_unit_job": _contains_all(
            workflow,
            [
                "Linux full unit suite (Python 3.11)",
                "runs-on: ubuntu-latest",
                'python-version: "3.11"',
                "python tools/run_reachops_ci_unittest.py",
            ],
        ),
        "windows_core_contract_job": _contains_all(
            workflow,
            [
                "Windows core contracts (Python 3.11)",
                "runs-on: windows-latest",
                'python-version: "3.11"',
                "test_commercial_security_contract.py",
                "test_execution_plan.py",
                "test_headless_execution_plan_contract.py",
                "test_run_recovery.py",
            ],
        ),
        "deterministic_delivery_audit_job": _contains_all(
            workflow,
            [
                "Deterministic delivery audits",
                "linux-full-unit",
                "windows-core-contract",
                "tools/reachops_delivery_audit.py --json",
                "tools/reachops_web_panel_dom_smoke.py --json",
                "tools/reachops_web_panel_runtime_smoke.py --json",
                "tools/reachops_repository_cleanliness_check.py --json",
            ],
        ),
        "external_acceptance_boundary_declared": _contains_all(
            workflow,
            [
                "Declare external acceptance boundary",
                "GitHub CI intentionally does not claim:",
                "full Windows packaged-client acceptance",
                "authorized TikTok comment/follow/DM submission",
            ],
        ),
        "dependency_cache_uses_lock": "cache-dependency-path: requirements.lock" in workflow,
        "pip_check_in_all_install_steps": workflow.count("python -m pip check") >= 3,
        "dependency_baseline_in_all_install_steps": workflow.count("python tools/verify_reachops_dependency_baseline.py --json") >= 3,
    }

    release_contract = {
        "release_evidence_schema": "reachops.release_evidence.v1" in release_evidence,
        "records_version_commit_channel": _contains_all(
            release_evidence,
            ['"version": version', '"commit": _git_value(root, "rev-parse", "HEAD")', '"channel": channel'],
        ),
        "records_dirty_tracked_files": _contains_all(
            release_evidence,
            ['"dirty_tracked_files": source_status', '"tracked_source_clean": not source_status'],
        ),
        "hashes_installer_manifest_acceptance_and_lock": _contains_all(
            release_evidence,
            [
                '"installer": _artifact(installer)',
                '"manifest": _artifact(manifest_path)',
                '"acceptance_summary": _artifact(acceptance_path)',
                '"requirements_lock": _artifact(root / "requirements.lock")',
                '"dependency_license_inventory": _artifact(root / "ReachOps" / "packaging" / "dependency-license-inventory.json")',
            ],
        ),
        "includes_dependency_baseline": "build_dependency_report(root)" in release_evidence,
        "includes_delivery_package_check": "check_delivery_package(" in release_evidence,
        "indexes_final_package_report_set": _contains_all(
            release_evidence,
            [
                "ACCEPTANCE_SUMMARY_SECTIONS",
                '"repository_cleanliness"',
                '"windows_package_preflight"',
                '"authorization_handoff"',
                '"authorization_handoff_readiness_report"',
                '"authorization_handoff_readiness_json"',
                '"client_delivery"',
                '"final_acceptance_gate"',
                '"package_report_files"',
                '"missing_package_report_files"',
            ],
        ),
        "rollback_note_exposes_report_recovery_evidence": _contains_all(
            release_evidence,
            [
                "Missing package reports",
                "Authorization handoff evidence",
                "Authorization handoff readiness report",
                "Authorization handoff readiness JSON",
                "Client delivery evidence",
            ],
        ),
        "writes_evidence_and_rollback_note": _contains_all(
            release_evidence,
            ["reachops-release-evidence.json", "reachops-rollback-note.md", "_rollback_note(payload)"],
        ),
        "windows_build_invokes_release_evidence": _contains_all(
            build_script,
            ["tools\\reachops_release_evidence.py", "ReachOps release evidence"],
        ),
    }

    supported_platforms = {
        "python": SUPPORTED_PYTHON,
        "linux_runner": SUPPORTED_LINUX_RUNNER,
        "windows_runner": SUPPORTED_WINDOWS_RUNNER,
        "workflow_supports_declared_versions": _contains_all(
            workflow,
            [
                f'python-version: "{SUPPORTED_PYTHON}"',
                f"runs-on: {SUPPORTED_WINDOWS_RUNNER}",
                f"runs-on: {SUPPORTED_LINUX_RUNNER}",
            ],
        ),
    }

    local_checks = {
        "ci_contract_complete": all(ci_contract.values()),
        "dependency_baseline_passed": bool(dependency_baseline.get("passed")),
        "pip_check_passed": bool(pip_check.get("passed")) if run_pip else True,
        "release_contract_complete": all(release_contract.values()),
        "supported_platforms_declared": bool(supported_platforms["workflow_supports_declared_versions"]),
    }
    local_passed = all(local_checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed_with_external_governance_pending" if local_passed else "failed",
        "passed": local_passed,
        "root": str(root),
        "supported_platforms": supported_platforms,
        "ci_contract": ci_contract,
        "dependency_baseline": dependency_baseline,
        "pip_check": pip_check,
        "release_contract": release_contract,
        "local_checks": local_checks,
        "external_governance_gates": [
            {"name": name, "status": "pending_external_validation"} for name in EXTERNAL_GOVERNANCE_GATES
        ],
        "external_governance_pending": list(EXTERNAL_GOVERNANCE_GATES),
        "does_not_claim_branch_protection": True,
        "does_not_claim_ten_green_ci_runs": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ReachOps CI and release baseline contracts.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--skip-pip-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report(args.root, run_pip=not args.skip_pip_check)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps CI/release baseline audit: {payload['status']}")
        if payload["external_governance_pending"]:
            print("External governance pending: " + ", ".join(payload["external_governance_pending"]))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
