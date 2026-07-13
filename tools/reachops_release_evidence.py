# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.version import BUILD_CHANNEL, PRODUCT_ID, PRODUCT_NAME, VERSION
from tools.reachops_delivery_package_check import check_delivery_package
from tools.verify_reachops_dependency_baseline import build_report as build_dependency_report


SCHEMA_VERSION = "reachops.release_evidence.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _git_status(root: Path) -> list[str]:
    value = _git_value(root, "status", "--short", "--untracked-files=no")
    return [line for line in value.splitlines() if line.strip()]


def _artifact(path: Path) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
        "sha256": "",
    }
    if detail["exists"] and path.is_file():
        detail["sha256"] = sha256_file(path)
    return detail


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_acceptance_summary(root: Path) -> Path:
    reports_dir = root / "reports" / "reachops_acceptance"
    candidates = list(reports_dir.glob("*/acceptance_summary.json"))
    if candidates:
        return max(candidates, key=lambda item: item.stat().st_mtime)
    return reports_dir / "acceptance_summary.json"


def _default_manifest(root: Path) -> Path:
    primary = root / "dist" / "installer" / "reachops-update-manifest.json"
    if primary.exists():
        return primary
    return root / "reachops-update-manifest.json"


def _default_output_dir(root: Path, version: str, build: str) -> Path:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")
    safe_build = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "-" for ch in str(build or "0"))
    return root / "reports" / "reachops_release" / f"{version}-{safe_build}-{timestamp}"


def _rollback_note(payload: dict[str, Any]) -> str:
    rollback = payload["rollback"]
    return "\n".join(
        [
            f"# ReachOps Rollback Note {payload['version']}",
            "",
            f"- Product: {payload['product_name']} ({payload['product_id']})",
            f"- Version: {payload['version']}",
            f"- Build: {payload['build']}",
            f"- Commit: {payload['source']['commit'] or 'unknown'}",
            f"- Channel: {payload['channel']}",
            f"- Final delivery ready: {str(bool(payload['final_delivery_ready'])).lower()}",
            "",
            "## Rollback Policy",
            "",
            f"- Preserve customer config: {str(bool(rollback['preserve_config'])).lower()}",
            f"- Preserve local data: {str(bool(rollback['preserve_data'])).lower()}",
            f"- Preserve activation status: {str(bool(rollback['preserve_activation_status'])).lower()}",
            "- Roll back only to a manifest whose product, channel, version, installer hash, and acceptance evidence are verified.",
            "- Do not use SkipInstaller or EXE-only builds as final customer rollback targets.",
            "",
            "## Required Operator Steps",
            "",
            "1. Stop the ReachOps local client and confirm no run session is active.",
            "2. Archive the current release evidence directory and acceptance reports.",
            "3. Install the previous verified ReachOps installer from its signed/hashed manifest.",
            "4. Run installer smoke, activation status check, client delivery check, package check, and final acceptance gate.",
            "5. Keep this rollback note with the release evidence bundle.",
            "",
            "## Current Evidence Status",
            "",
            f"- Package check status: {payload['package_check'].get('status', 'unknown')}",
            f"- Package check failures: {', '.join(payload['package_check'].get('failures') or []) or 'none'}",
            f"- Missing artifacts: {', '.join(payload['package_check'].get('missing_artifacts') or []) or 'none'}",
            "",
        ]
    )


def build_release_evidence(
    *,
    root: str | Path = ROOT_DIR,
    version: str = VERSION,
    build: str = "0",
    channel: str = BUILD_CHANNEL,
    acceptance_summary: str | Path | None = None,
    manifest: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    acceptance_path = Path(acceptance_summary).resolve() if acceptance_summary else _default_acceptance_summary(root)
    manifest_path = Path(manifest).resolve() if manifest else _default_manifest(root)
    output = Path(output_dir).resolve() if output_dir else _default_output_dir(root, version, build)
    exe = root / "dist" / "ReachOps" / "ReachOps.exe"
    installer = root / "dist" / "installer" / f"ReachOps-Setup-{version}.exe"
    package_check = check_delivery_package(root=root, acceptance_summary_path=acceptance_path, manifest_path=manifest_path)
    dependency_baseline = build_dependency_report(root)
    manifest_payload = _load_json(manifest_path)
    runtime_policy = manifest_payload.get("runtime_policy") if isinstance(manifest_payload.get("runtime_policy"), dict) else {}
    source_status = _git_status(root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product_id": PRODUCT_ID,
        "product_name": PRODUCT_NAME,
        "version": version,
        "build": str(build),
        "channel": channel,
        "platform": "windows",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "root": str(root),
        "source": {
            "commit": _git_value(root, "rev-parse", "HEAD"),
            "branch": _git_value(root, "branch", "--show-current"),
            "dirty_tracked_files": source_status,
            "tracked_source_clean": not source_status,
        },
        "dependency_baseline": dependency_baseline,
        "artifacts": {
            "exe": _artifact(exe),
            "installer": _artifact(installer),
            "manifest": _artifact(manifest_path),
            "acceptance_summary": _artifact(acceptance_path),
            "requirements_lock": _artifact(root / "requirements.lock"),
            "dependency_license_inventory": _artifact(root / "ReachOps" / "packaging" / "dependency-license-inventory.json"),
        },
        "manifest": {
            "path": str(manifest_path),
            "product_id": manifest_payload.get("product_id"),
            "version": manifest_payload.get("version"),
            "build": manifest_payload.get("build"),
            "channel": manifest_payload.get("channel"),
            "installer": manifest_payload.get("installer") if isinstance(manifest_payload.get("installer"), dict) else {},
            "runtime_policy": runtime_policy,
        },
        "acceptance": {
            "path": str(acceptance_path),
            "summary": {
                "status": _load_json(acceptance_path).get("status"),
                "final_acceptance_gate": _load_json(acceptance_path).get("final_acceptance_gate"),
            },
        },
        "package_check": package_check,
        "rollback": {
            "preserve_config": bool(runtime_policy.get("preserve_config", True)),
            "preserve_data": bool(runtime_policy.get("preserve_data", True)),
            "preserve_activation_status": bool(runtime_policy.get("preserve_activation_status", True)),
            "requires_previous_verified_manifest": True,
            "forbid_exe_only_final_rollback": True,
            "verification_commands": [
                "powershell -ExecutionPolicy Bypass -File tools\\run_reachops_installer_smoke_windows.ps1",
                "python tools\\reachops_activation_status_check.py --json",
                "python tools\\reachops_client_delivery_check.py --json",
                "python tools\\reachops_delivery_package_check.py --json",
                "python tools\\reachops_final_acceptance_gate.py --json",
            ],
        },
        "final_delivery_ready": bool(package_check.get("final_delivery_ready")),
        "not_final_delivery_reasons": [] if package_check.get("final_delivery_ready") else [
            "release_evidence_created_without_strict_final_delivery_package_pass"
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    evidence_path = output / "reachops-release-evidence.json"
    rollback_path = output / "reachops-rollback-note.md"
    payload["evidence_path"] = str(evidence_path)
    payload["rollback_note_path"] = str(rollback_path)
    rollback_path.write_text(_rollback_note(payload), encoding="utf-8")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create ReachOps release evidence and rollback note.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--build", default="0")
    parser.add_argument("--channel", default=BUILD_CHANNEL)
    parser.add_argument("--acceptance-summary", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_release_evidence(
        root=args.root,
        version=args.version,
        build=args.build,
        channel=args.channel,
        acceptance_summary=args.acceptance_summary or None,
        manifest=args.manifest or None,
        output_dir=args.output_dir or None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps release evidence: {payload['evidence_path']}")
        print(f"ReachOps rollback note: {payload['rollback_note_path']}")
    return 0 if payload.get("dependency_baseline", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
