# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import tempfile
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.version import VERSION
from tools.write_reachops_update_manifest import build_manifest


REQUIRED_FILES = {
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
        "tools\\reachops_windows_package_preflight.py",
        "windows_package_preflight.json",
        "PyInstaller --clean --noconfirm ReachOps\\packaging\\reachops.spec",
        "ReachOps\\packaging\\ReachOps.iss",
        "tools\\write_reachops_update_manifest.py",
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


def _build_manifest_contract() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    manifest: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / f"ReachOps-Setup-{VERSION}.exe"
            installer.write_bytes(b"reachops installer preflight")
            manifest = build_manifest(installer, version=VERSION, build="preflight", channel="mvp")
    except Exception as exc:
        return {"ok": False, "failures": ["manifest_fixture_failed"], "error": str(exc), "checks": checks}

    installer_meta = manifest.get("installer") if isinstance(manifest.get("installer"), dict) else {}
    runtime_policy = manifest.get("runtime_policy") if isinstance(manifest.get("runtime_policy"), dict) else {}
    installer_path = Path(str(installer_meta.get("path") or ""))
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True).lower()
    checks["product_version_current"] = str(manifest.get("version") or "") == VERSION
    checks["platform_windows"] = str(manifest.get("platform") or "") == "windows"
    checks["installer_sha256_present"] = len(str(installer_meta.get("sha256") or "")) == 64
    checks["installer_size_present"] = int(installer_meta.get("size_bytes") or 0) > 0
    checks["installer_path_portable"] = bool(installer_meta.get("path")) and not installer_path.is_absolute() and installer_path.name == str(installer_meta.get("file_name") or "")
    checks["preserve_config"] = bool(runtime_policy.get("preserve_config"))
    checks["preserve_data"] = bool(runtime_policy.get("preserve_data"))
    checks["preserve_activation_status"] = bool(runtime_policy.get("preserve_activation_status"))
    checks["no_customer_data_fields"] = not any(
        token in encoded
        for token in [
            "comment_text",
            "username",
            "tiktok_status",
            "cookie",
            "sqlite",
            "screenshot",
            "profile_id",
            "activation_secret",
        ]
    )
    failures = [f"manifest_contract_{name}_failed" for name, ok in checks.items() if not ok]
    return {
        "ok": not failures,
        "failures": failures,
        "checks": checks,
        "manifest": {
            "product_id": manifest.get("product_id"),
            "version": manifest.get("version"),
            "platform": manifest.get("platform"),
            "installer": {
                "file_name": installer_meta.get("file_name"),
                "path": installer_meta.get("path"),
                "size_bytes": installer_meta.get("size_bytes"),
                "sha256_present": bool(installer_meta.get("sha256")),
            },
            "runtime_policy": runtime_policy,
        },
    }


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

    manifest_contract = _build_manifest_contract()
    failures.extend(manifest_contract.get("failures") or [])

    artifacts = {name: _status(root / relative) for name, relative in FINAL_ARTIFACTS.items()}
    missing_artifacts = [name for name, detail in artifacts.items() if not detail["exists"]]

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
        "manifest_contract": manifest_contract,
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
