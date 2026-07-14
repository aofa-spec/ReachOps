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
REQUIRED_STATUS_CHECKS = [
    "Linux full unit suite (Python 3.11)",
    "Windows core contracts (Python 3.11)",
    "Deterministic delivery audits",
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


def _status_check_names(required_status_checks: dict[str, Any]) -> set[str]:
    names = set(str(item) for item in required_status_checks.get("contexts") or [] if str(item).strip())
    for check in required_status_checks.get("checks") or []:
        if isinstance(check, dict) and str(check.get("context") or "").strip():
            names.add(str(check["context"]))
    return names


def evaluate_github_governance(github_governance: dict[str, Any] | None) -> dict[str, Any]:
    if not github_governance:
        return {
            "checked": False,
            "status": "not_checked",
            "branch_protection": {"available": None, "message": "github_governance_not_provided"},
            "required_status_checks": {
                "required": REQUIRED_STATUS_CHECKS,
                "configured": [],
                "missing": REQUIRED_STATUS_CHECKS,
                "passed": False,
            },
            "pull_request_reviews": {"passed": False, "required_approving_review_count": 0},
            "consecutive_green_runs": {"required": 10, "observed": 0, "passed": False},
            "external_governance_pending": list(EXTERNAL_GOVERNANCE_GATES),
            "external_governance_blockers": [],
            "does_not_claim_branch_protection": True,
            "does_not_claim_ten_green_ci_runs": True,
        }

    branch_protection = github_governance.get("branch_protection") or {}
    branch_available = bool(branch_protection.get("available"))
    unavailable_reason = str(branch_protection.get("message") or branch_protection.get("error") or "").strip()
    protection_payload = branch_protection.get("payload") if isinstance(branch_protection.get("payload"), dict) else branch_protection
    required_status_checks = protection_payload.get("required_status_checks") or {}
    configured_checks = sorted(_status_check_names(required_status_checks))
    missing_checks = [name for name in REQUIRED_STATUS_CHECKS if name not in configured_checks]
    checks_passed = branch_available and not missing_checks

    review_payload = protection_payload.get("required_pull_request_reviews") or {}
    approving_count = int(review_payload.get("required_approving_review_count") or 0) if isinstance(review_payload, dict) else 0
    reviews_passed = branch_available and approving_count >= 1

    runs = github_governance.get("workflow_runs") or []
    green_runs = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    ten_green_passed = len(green_runs) >= 10

    pending: list[str] = []
    blockers: list[dict[str, Any]] = []
    if not reviews_passed:
        pending.append("main_branch_protection_requires_pr_review")
    if not checks_passed:
        pending.append("main_branch_protection_requires_successful_checks")
    if not ten_green_passed:
        pending.append("ten_consecutive_ci_runs_without_code_failure")
    if not branch_available:
        blockers.append(
            {
                "name": "branch_protection_unavailable",
                "status": str(branch_protection.get("status") or ""),
                "message": unavailable_reason or "branch_protection_not_available",
            }
        )

    return {
        "checked": True,
        "status": "passed" if not pending else "external_pending",
        "branch_protection": {
            "available": branch_available,
            "message": unavailable_reason,
            "status": str(branch_protection.get("status") or ""),
        },
        "required_status_checks": {
            "required": REQUIRED_STATUS_CHECKS,
            "configured": configured_checks,
            "missing": missing_checks,
            "passed": checks_passed,
        },
        "pull_request_reviews": {
            "passed": reviews_passed,
            "required_approving_review_count": approving_count,
        },
        "consecutive_green_runs": {
            "required": 10,
            "observed": len(green_runs),
            "passed": ten_green_passed,
        },
        "external_governance_pending": pending,
        "external_governance_blockers": blockers,
        "does_not_claim_branch_protection": not (reviews_passed and checks_passed),
        "does_not_claim_ten_green_ci_runs": not ten_green_passed,
    }


def build_report(
    root: str | Path = ROOT_DIR,
    *,
    run_pip: bool = True,
    github_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    github_governance_report = evaluate_github_governance(github_governance)
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
        "github_governance": github_governance_report,
        "external_governance_gates": [
            {
                "name": name,
                "status": "pending_external_validation"
                if name in github_governance_report["external_governance_pending"]
                else "passed",
            }
            for name in EXTERNAL_GOVERNANCE_GATES
        ],
        "external_governance_pending": list(github_governance_report["external_governance_pending"]),
        "external_governance_blockers": list(github_governance_report["external_governance_blockers"]),
        "does_not_claim_branch_protection": bool(github_governance_report["does_not_claim_branch_protection"]),
        "does_not_claim_ten_green_ci_runs": bool(github_governance_report["does_not_claim_ten_green_ci_runs"]),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ReachOps CI and release baseline contracts.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--skip-pip-check", action="store_true")
    parser.add_argument("--github-governance-json", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    github_governance = None
    if str(args.github_governance_json or "").strip():
        github_governance = json.loads(Path(args.github_governance_json).read_text(encoding="utf-8"))
    payload = build_report(args.root, run_pip=not args.skip_pip_check, github_governance=github_governance)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps CI/release baseline audit: {payload['status']}")
        if payload["external_governance_pending"]:
            print("External governance pending: " + ", ".join(payload["external_governance_pending"]))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
