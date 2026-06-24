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


def _file_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists and path.is_file() else 0,
    }


def _latest_acceptance_summary(root: Path) -> Path:
    candidates = list((root / "reports" / "reachops_acceptance").glob("*/acceptance_summary.json"))
    if not candidates:
        raise FileNotFoundError("no acceptance_summary.json found under reports/reachops_acceptance")
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


def _report_sections(summary: dict[str, Any], final_required: bool) -> list[str]:
    sections = [
        "delivery_audit",
        "operator_pressure",
        "installer_smoke",
        "ui_startup",
        "live_validation",
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
    return sections


def check_delivery_package(
    root: str | Path = ROOT_DIR,
    acceptance_summary_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    allow_external_pending: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    acceptance_path = _resolve(root, acceptance_summary_path) if acceptance_summary_path else _latest_acceptance_summary(root)
    manifest = _resolve(root, manifest_path) if manifest_path else _default_manifest(root)
    exe = root / "dist" / "ReachOps" / "ReachOps.exe"
    installer = root / "dist" / "installer" / f"ReachOps-Setup-{VERSION}.exe"
    failures: list[str] = []
    missing_artifacts: list[str] = []

    artifact_status = {
        "exe": _file_status(exe),
        "installer": _file_status(installer),
        "manifest": _file_status(manifest),
        "acceptance_summary": _file_status(acceptance_path),
    }
    for key, detail in artifact_status.items():
        if not detail["exists"]:
            missing_artifacts.append(key)
            failures.append(f"{key}_missing")
        elif key in {"exe", "installer"} and int(detail.get("size") or 0) <= 0:
            failures.append(f"{key}_empty")

    summary: dict[str, Any] = {}
    acceptance_verification: dict[str, Any] = {
        "passed": False,
        "failures": ["acceptance_summary_missing"],
        "pending": [],
    }
    if acceptance_path.exists():
        summary = load_summary(acceptance_path)
        acceptance_verification = verify_summary(summary, allow_external_pending=allow_external_pending)
        if not acceptance_verification.get("passed"):
            failures.append("acceptance_summary_not_passed")

    manifest_failures, manifest_detail = _check_manifest(root, manifest, installer)
    failures.extend(manifest_failures)
    artifact_status["manifest"].update(manifest_detail)

    report_files: dict[str, dict[str, Any]] = {}
    if summary:
        for section_name in _report_sections(summary, final_required=not allow_external_pending):
            section = summary.get(section_name) if isinstance(summary.get(section_name), dict) else {}
            path_value = str(section.get("json_path") or "")
            if not path_value:
                failures.append(f"{section_name}_json_path_missing")
                report_files[section_name] = {"path": "", "exists": False, "size": 0}
                continue
            report_path = _resolve(root, path_value)
            detail = _file_status(report_path)
            report_files[section_name] = detail
            if not detail["exists"]:
                failures.append(f"{section_name}_json_missing")
            elif int(detail.get("size") or 0) <= 0:
                failures.append(f"{section_name}_json_empty")

    final_ready = not failures
    status = "passed" if final_ready else "failed"
    if allow_external_pending and not failures and acceptance_verification.get("pending"):
        status = "ready_for_external_validation"

    return {
        "status": status,
        "passed": final_ready,
        "allow_external_pending": bool(allow_external_pending),
        "root": str(root),
        "failures": failures,
        "missing_artifacts": missing_artifacts,
        "artifacts": artifact_status,
        "report_files": report_files,
        "acceptance_verification": acceptance_verification,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps final delivery package artifacts.")
    parser.add_argument("--root", default=str(ROOT_DIR), help="ReachOps repository root.")
    parser.add_argument("--acceptance-summary", default="", help="Path to acceptance_summary.json. Defaults to latest report.")
    parser.add_argument("--manifest", default="", help="Path to reachops-update-manifest.json.")
    parser.add_argument("--allow-external-pending", action="store_true", help="Allow ready_for_external_validation interim package.")
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
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "passed": False,
            "allow_external_pending": bool(args.allow_external_pending),
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
