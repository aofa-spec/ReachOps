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

from ReachOps.runtime_paths import RuntimePaths
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_validation_manifest import build_manifest


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_acceptance_report(reports_dir: str | Path = "") -> dict[str, Any]:
    root = Path(reports_dir or (ROOT_DIR / "reports" / "reachops_acceptance"))
    if not root.exists():
        return {"exists": False, "dir": "", "summary_path": "", "package_check_path": ""}
    dirs = [item for item in root.iterdir() if item.is_dir()]
    if not dirs:
        return {"exists": False, "dir": "", "summary_path": "", "package_check_path": ""}
    latest = max(dirs, key=lambda item: item.stat().st_mtime)
    summary_path = latest / "acceptance_summary.json"
    package_path = latest / "delivery_package_check.json"
    summary = load_json(summary_path)
    package = load_json(package_path)
    verification = summary.get("acceptance_verification") if isinstance(summary.get("acceptance_verification"), dict) else {}
    delivery_audit = summary.get("delivery_audit") if isinstance(summary.get("delivery_audit"), dict) else {}
    if not delivery_audit:
        delivery_audit = verification.get("delivery_audit") if isinstance(verification.get("delivery_audit"), dict) else {}
    goal_status = summary.get("goal_status") if isinstance(summary.get("goal_status"), dict) else {}
    return {
        "exists": True,
        "dir": str(latest),
        "summary_path": str(summary_path),
        "package_check_path": str(package_path),
        "summary_status": str(summary.get("status") or verification.get("status") or ""),
        "package_status": str(package.get("status") or ""),
        "package_passed": bool(package.get("passed")),
        "effective_pending_external_validation": int(delivery_audit.get("effective_pending_external_validation") or 0),
        "pending_external_validation": list(
            summary.get("pending_external_validation")
            or goal_status.get("pending_external_validation")
            or verification.get("pending")
            or []
        ),
    }


def build_status(args: argparse.Namespace, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_paths = RuntimePaths.build()
    activation_path = str(args.activation_status_path or runtime_paths.activation_status_path)
    local_inputs_path = Path(args.local_inputs_path or (ROOT_DIR / "tools" / "reachops_acceptance_inputs.local.ps1"))
    template_path = Path(args.activation_template_path or (Path(runtime_paths.config_dir) / "reachops_activation_status.template.json"))
    activation = check_activation_status(activation_path)
    manifest_args = SimpleNamespace(
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
        activation_status_path=activation_path,
        limit=args.limit,
        allow_pressure_submit=args.allow_pressure_submit,
        confirm_authorized_targets="YES" if args.confirm_authorized_targets else "",
        include_live_submit_command=False,
    )
    manifest = build_manifest(manifest_args, snapshot=snapshot)
    acceptance = latest_acceptance_report(args.acceptance_reports_dir)
    missing_inputs = list(manifest.get("missing_inputs") or [])
    if not local_inputs_path.exists():
        missing_inputs.insert(0, "本地验收输入文件 tools/reachops_acceptance_inputs.local.ps1")
    seen = set()
    deduped_missing = []
    for item in missing_inputs:
        key = str(item)
        if key not in seen:
            seen.add(key)
            deduped_missing.append(key)
    profile_ids = [str(item) for item in (manifest.get("selected_profile_ids") or [])]
    stage3_ready_for_preflight = (
        bool(profile_ids)
        and bool((manifest.get("blocking_summary") or {}).get("target_ready"))
        and bool((manifest.get("blocking_summary") or {}).get("activation_ready"))
        and bool((manifest.get("blocking_summary") or {}).get("authorization_confirmed"))
    )
    final_delivery_ready = (
        acceptance.get("summary_status") == "passed"
        and bool(acceptance.get("package_passed"))
        and int(acceptance.get("effective_pending_external_validation") or 0) == 0
    )
    return {
        "status": "passed" if final_delivery_ready else "blocked",
        "ready_for_live_preflight": stage3_ready_for_preflight,
        "ready_for_live_submit": stage3_ready_for_preflight,
        "final_delivery_ready": final_delivery_ready,
        "no_browser_started": True,
        "no_submit": True,
        "local_inputs": {
            "path": str(local_inputs_path),
            "exists": local_inputs_path.exists(),
        },
        "activation": {
            "path": activation_path,
            "template_path": str(template_path),
            "template_exists": template_path.exists(),
            "exists": bool(activation.get("activation_status_exists")),
            "ready": bool(activation.get("ready")),
            "status": str(activation.get("status") or ""),
        },
        "live_validation": {
            "status": str(manifest.get("status") or ""),
            "selected_profile_ids": profile_ids,
            "selected_profile_count": int(manifest.get("selected_profile_count") or 0),
            "missing_inputs": deduped_missing,
            "blocking_summary": manifest.get("blocking_summary") or {},
        },
        "latest_acceptance": acceptance,
        "next_required_actions": deduped_missing
        or (["运行受控真实提交并生成 live submit evidence"] if not final_delivery_ready else []),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize ReachOps live acceptance readiness without opening a browser or submitting actions.")
    parser.add_argument("--profile-group", default="BR")
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
    parser.add_argument("--local-inputs-path", default="")
    parser.add_argument("--acceptance-reports-dir", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--confirm-authorized-targets", action="store_true")
    parser.add_argument("--require-final", action="store_true", help="Return non-zero unless final_delivery_ready is true.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_status(args)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if (status.get("final_delivery_ready") or not args.require_final) else 2


if __name__ == "__main__":
    raise SystemExit(main())
