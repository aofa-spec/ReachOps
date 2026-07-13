# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from tools.reachops_live_acceptance_status import build_status
from tools.reachops_live_acceptance_status import render_markdown_report
from tools.reachops_live_acceptance_status import write_json_report
from tools.reachops_live_acceptance_status import write_markdown_report


DEFAULT_LOCAL_INPUTS = ROOT_DIR / "tools" / "reachops_acceptance_inputs.local.ps1"
SAFE_INPUT_TEMPLATE = ROOT_DIR / "tools" / "reachops_acceptance_inputs.example.ps1"
REQUIRED_BUNDLE_FILES = {
    "README_AUTHORIZATION_HANDOFF.md",
    "latest_live_acceptance_readiness.md",
    "latest_live_acceptance_readiness.json",
    "latest_phase2_handoff_check.md",
    "latest_phase2_handoff_check.json",
    "authorization_handoff_commands.txt",
    "authorization_handoff_manifest.json",
    "reachops_acceptance_inputs.example.ps1",
}
FORBIDDEN_BUNDLE_FILES = {
    "reachops_acceptance_inputs.local.ps1",
    "reachops_activation_status.json",
    "reachops_activation_status.template.json",
}


def default_output_dir() -> Path:
    return Path(RuntimePaths.build().reports_dir) / "acceptance_remediation"


def default_bundle_path() -> Path:
    return default_output_dir() / "latest_reachops_authorization_handoff.zip"


def status_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        profile_group=args.profile_group,
        profile_ids=args.profile_ids,
        profile_limit=args.profile_limit,
        max_pages=args.max_pages,
        profile_scan_timeout=args.profile_scan_timeout,
        target=args.target,
        comment_video_url=args.comment_video_url,
        target_profile_url=args.target_profile_url,
        dm_profile_url=args.dm_profile_url,
        target_username=args.target_username,
        activation_status_path=args.activation_status_path,
        activation_template_path=args.activation_template_path,
        local_inputs_path=args.local_inputs_path,
        acceptance_reports_dir=args.acceptance_reports_dir,
        limit=args.limit,
        allow_pressure_submit=args.allow_pressure_submit,
        confirm_authorized_targets=args.confirm_authorized_targets,
        require_final=False,
    )


def command_text(status: dict[str, Any]) -> str:
    lines = [
        "# ReachOps Authorization Handoff Commands",
        "",
        "Run these commands on the Windows acceptance machine after filling authorized targets.",
        "",
    ]
    for index, command in enumerate(status.get("operator_commands") or [], start=1):
        lines.append(f"{index}. {command}")
    lines.extend(["", "Final verification:"])
    for command in status.get("verification_commands") or []:
        lines.append(f"- {command}")
    lines.append("")
    return "\n".join(lines)


def build_handoff_bundle(args: argparse.Namespace, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    output_path = Path(args.output_path).expanduser() if str(args.output_path or "").strip() else default_bundle_path()
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    status = build_status(status_args(args), snapshot=snapshot)
    markdown_path = output_path.parent / "latest_live_acceptance_readiness.md"
    json_path = output_path.parent / "latest_live_acceptance_readiness.json"
    status["report_path"] = str(write_markdown_report(status, markdown_path))
    status["json_report_path"] = str(write_json_report(status, json_path))
    commands = command_text(status)
    phase2_json_path = output_path.parent / "latest_phase2_handoff_check.json"
    phase2_md_path = output_path.parent / "latest_phase2_handoff_check.md"
    phase2_json = phase2_json_path.read_text(encoding="utf-8") if phase2_json_path.is_file() else "{}"
    phase2_md = (
        phase2_md_path.read_text(encoding="utf-8")
        if phase2_md_path.is_file()
        else "# ReachOps Phase 2 Handoff Check\n\nRun `python tools/reachops_phase2_handoff_check.py --write --json` to generate this report.\n"
    )
    manifest = {
        "product": "ReachOps",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status.get("status"),
        "final_delivery_ready": bool(status.get("final_delivery_ready")),
        "no_browser_started": True,
        "no_submit": True,
        "bundle_path": str(output_path),
        "included_files": [
            "README_AUTHORIZATION_HANDOFF.md",
            "latest_live_acceptance_readiness.md",
            "latest_live_acceptance_readiness.json",
            "latest_phase2_handoff_check.md",
            "latest_phase2_handoff_check.json",
            "authorization_handoff_commands.txt",
            "reachops_acceptance_inputs.example.ps1",
        ],
        "excluded_sensitive_files": [
            "tools/reachops_acceptance_inputs.local.ps1",
            "activation status JSON containing real authorization",
            "TikTok target URLs after operator authorization",
        ],
        "failed_checks": status.get("failed_checks") or [],
        "next_required_actions": status.get("next_required_actions") or [],
        "operator_commands": status.get("operator_commands") or [],
        "verification_commands": status.get("verification_commands") or [],
    }

    readme = "\n".join(
        [
            "# ReachOps Authorization Handoff Bundle",
            "",
            "This package is safe to transfer for Windows acceptance preparation.",
            "It intentionally excludes local real authorization input values and activation files.",
            "",
            f"- status: {manifest['status']}",
            f"- final_delivery_ready: {str(manifest['final_delivery_ready']).lower()}",
            f"- markdown_report: latest_live_acceptance_readiness.md",
            f"- json_report: latest_live_acceptance_readiness.json",
            f"- phase2_handoff_report: latest_phase2_handoff_check.md",
            f"- phase2_handoff_json: latest_phase2_handoff_check.json",
            "",
            "## Required external inputs",
            "",
            *[f"- {item}" for item in (status.get("next_required_actions") or [])],
            "",
        ]
    )

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README_AUTHORIZATION_HANDOFF.md", readme)
        zf.writestr("latest_live_acceptance_readiness.md", render_markdown_report(status))
        zf.writestr("latest_live_acceptance_readiness.json", json.dumps(status, ensure_ascii=False, indent=2))
        zf.writestr("latest_phase2_handoff_check.md", phase2_md)
        zf.writestr("latest_phase2_handoff_check.json", phase2_json)
        zf.writestr("authorization_handoff_commands.txt", commands)
        zf.writestr("authorization_handoff_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if SAFE_INPUT_TEMPLATE.is_file():
            zf.write(SAFE_INPUT_TEMPLATE, "reachops_acceptance_inputs.example.ps1")

    return {
        "status": "created",
        "bundle_path": str(output_path),
        "exists": output_path.is_file(),
        "size": output_path.stat().st_size if output_path.is_file() else 0,
        "no_browser_started": True,
        "no_submit": True,
        "manifest": manifest,
        "readiness_status": status.get("status"),
        "final_delivery_ready": bool(status.get("final_delivery_ready")),
    }


def verify_handoff_bundle(path: str | Path = "") -> dict[str, Any]:
    bundle_path = Path(path).expanduser() if str(path or "").strip() else default_bundle_path()
    if not bundle_path.is_absolute():
        bundle_path = ROOT_DIR / bundle_path
    failures: list[str] = []
    names: set[str] = set()
    manifest: dict[str, Any] = {}
    if not bundle_path.is_file():
        failures.append("bundle_missing")
    else:
        try:
            with zipfile.ZipFile(bundle_path) as zf:
                names = set(zf.namelist())
                if zf.testzip():
                    failures.append("bundle_zip_integrity_failed")
                if "authorization_handoff_manifest.json" in names:
                    manifest_payload = json.loads(zf.read("authorization_handoff_manifest.json").decode("utf-8"))
                    manifest = manifest_payload if isinstance(manifest_payload, dict) else {}
                else:
                    failures.append("manifest_missing")
                commands_text = (
                    zf.read("authorization_handoff_commands.txt").decode("utf-8")
                    if "authorization_handoff_commands.txt" in names
                    else ""
                )
                readiness_payload = (
                    json.loads(zf.read("latest_live_acceptance_readiness.json").decode("utf-8"))
                    if "latest_live_acceptance_readiness.json" in names
                    else {}
                )
                if not isinstance(readiness_payload, dict):
                    failures.append("readiness_json_invalid")
                phase2_payload = (
                    json.loads(zf.read("latest_phase2_handoff_check.json").decode("utf-8"))
                    if "latest_phase2_handoff_check.json" in names
                    else {}
                )
                if not isinstance(phase2_payload, dict):
                    failures.append("phase2_handoff_json_invalid")
                live_readiness = phase2_payload.get("live_readiness") if isinstance(phase2_payload, dict) else {}
                local_inputs = live_readiness.get("local_inputs") if isinstance(live_readiness, dict) else {}
                if "latest_phase2_handoff_check.json" in names and not isinstance(local_inputs, dict):
                    failures.append("phase2_handoff_local_inputs_missing")
        except Exception as exc:
            failures.append(f"bundle_read_failed:{exc.__class__.__name__}")
            commands_text = ""
            readiness_payload = {}
    missing_files = sorted(REQUIRED_BUNDLE_FILES - names)
    forbidden_files = sorted(name for name in names if Path(name).name in FORBIDDEN_BUNDLE_FILES)
    if missing_files:
        failures.append("required_files_missing")
    if forbidden_files:
        failures.append("forbidden_sensitive_files_included")
    if manifest:
        excluded = set(str(item) for item in (manifest.get("excluded_sensitive_files") or []))
        if "tools/reachops_acceptance_inputs.local.ps1" not in excluded:
            failures.append("local_inputs_not_declared_excluded")
        if not bool(manifest.get("no_browser_started")):
            failures.append("no_browser_started_not_declared")
        if not bool(manifest.get("no_submit")):
            failures.append("no_submit_not_declared")
        if not manifest.get("operator_commands"):
            failures.append("operator_commands_missing")
    if "init_reachops_acceptance_inputs_windows.ps1 -Json" not in commands_text:
        failures.append("init_command_missing")
    if "reachops_final_acceptance_gate.py --json" not in commands_text:
        failures.append("final_gate_command_missing")
    return {
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "bundle_path": str(bundle_path),
        "exists": bundle_path.is_file(),
        "size": bundle_path.stat().st_size if bundle_path.is_file() else 0,
        "failures": failures,
        "missing_files": missing_files,
        "forbidden_files": forbidden_files,
        "included_files": sorted(names),
        "manifest": manifest,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a safe ReachOps authorization handoff bundle.")
    parser.add_argument("--output-path", default="")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-scan-timeout", type=int, default=8)
    parser.add_argument("--target", default="anti aging serum")
    parser.add_argument("--comment-video-url", default="")
    parser.add_argument("--target-profile-url", default="")
    parser.add_argument("--dm-profile-url", default="")
    parser.add_argument("--target-username", default="")
    parser.add_argument("--activation-status-path", default="")
    parser.add_argument("--activation-template-path", default="")
    parser.add_argument("--local-inputs-path", default=str(DEFAULT_LOCAL_INPUTS))
    parser.add_argument("--acceptance-reports-dir", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--confirm-authorized-targets", action="store_true")
    parser.add_argument("--verify", action="store_true", help="Verify an existing authorization handoff bundle instead of creating one.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = verify_handoff_bundle(args.output_path) if args.verify else build_handoff_bundle(args)
    if "--json" in (argv or sys.argv[1:]):
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed", result.get("exists"))) else 2


if __name__ == "__main__":
    raise SystemExit(main())
