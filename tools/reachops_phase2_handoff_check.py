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

from tools.reachops_authorization_handoff_bundle import verify_handoff_bundle
from tools.reachops_delivery_package_check import check_delivery_package
from tools.reachops_live_acceptance_status import build_status as build_live_status
from tools.reachops_windows_package_preflight import build_preflight

OUT_DIR = ROOT_DIR / "reports/reachops/mac_gui/runtime/reports/acceptance_remediation"
OUT_PATH = OUT_DIR / "latest_phase2_handoff_check.json"
MD_PATH = OUT_DIR / "latest_phase2_handoff_check.md"
HANDOFF_PATH = OUT_DIR / "latest_reachops_authorization_handoff.zip"
LOCAL_INPUTS_PATH = ROOT_DIR / "tools/reachops_acceptance_inputs.local.ps1"


def skipped_profile_snapshot() -> dict[str, Any]:
    return {
        "available": False,
        "error": "profile snapshot skipped: phase2_handoff_check",
        "profiles": [],
        "groups": [],
        "profile_count": 0,
        "group_count": 0,
    }


def live_status_args(local_inputs_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        profile_group="United States",
        profile_ids="",
        profile_limit=3,
        max_pages=1,
        profile_scan_timeout=1,
        target="",
        comment_video_url="",
        target_profile_url="",
        dm_profile_url="",
        target_username="",
        activation_status_path="",
        activation_template_path="",
        local_inputs_path=str(local_inputs_path),
        acceptance_reports_dir="",
        limit=3,
        allow_pressure_submit="",
        confirm_authorized_targets=False,
        require_final=False,
    )


def build_check(local_inputs_path: Path = LOCAL_INPUTS_PATH, handoff_path: Path = HANDOFF_PATH) -> dict[str, Any]:
    windows_preflight = build_preflight(ROOT_DIR)
    handoff = verify_handoff_bundle(handoff_path)
    live = build_live_status(live_status_args(local_inputs_path), snapshot=skipped_profile_snapshot())
    package = check_delivery_package(ROOT_DIR, allow_external_pending=False)

    missing_artifacts = list(package.get("missing_artifacts") or [])
    live_failed = list(live.get("failed_checks") or [])
    live_blocked = list(live.get("blocked_reasons") or [])
    local_inputs = live.get("local_inputs") if isinstance(live.get("local_inputs"), dict) else {}
    activation = live.get("activation") if isinstance(live.get("activation"), dict) else {}
    live_validation = live.get("live_validation") if isinstance(live.get("live_validation"), dict) else {}
    blocking_plan = live.get("blocking_plan") if isinstance(live.get("blocking_plan"), list) else []
    operator_commands = live.get("operator_commands") if isinstance(live.get("operator_commands"), list) else []
    ready_for_windows_execution = bool(windows_preflight.get("ready_for_windows_build")) and bool(handoff.get("passed"))
    ready_for_authorized_live_submit = bool(
        live.get("ready_for_live_submit")
        and not live_failed
        and bool(live.get("final_delivery_ready"))
    )
    final_delivery_ready = bool(
        package.get("final_delivery_ready")
        and ready_for_authorized_live_submit
        and not missing_artifacts
    )
    blockers: list[dict[str, Any]] = []
    if not windows_preflight.get("ready_for_windows_build"):
        blockers.append(
            {
                "scope": "windows_build_inputs",
                "status": windows_preflight.get("status"),
                "failures": windows_preflight.get("failures") or [],
                "next_action": "修复 Windows 构建脚本、spec、installer 或 acceptance 脚本合同。",
            }
        )
    if not handoff.get("passed"):
        blockers.append(
            {
                "scope": "authorization_handoff_bundle",
                "status": handoff.get("status"),
                "failures": handoff.get("failures") or [],
                "next_action": "重新生成并验证 latest_reachops_authorization_handoff.zip。",
            }
        )
    if live_failed or live_blocked:
        blockers.append(
            {
                "scope": "authorized_live_inputs",
                "status": live.get("status"),
                "failed_checks": live_failed,
                "blocked_reasons": live_blocked,
                "next_actions": live.get("next_required_actions") or [],
            }
        )
    if missing_artifacts or package.get("failures"):
        blockers.append(
            {
                "scope": "windows_final_artifacts",
                "status": package.get("status"),
                "missing_artifacts": missing_artifacts,
                "failures": package.get("failures") or [],
                "next_action": "在 Windows 实机生成 exe、installer、manifest 和通过的 acceptance_summary.json。",
            }
        )

    return {
        "product": "ReachOps",
        "status": "final_delivery_ready" if final_delivery_ready else "ready_for_windows_execution" if ready_for_windows_execution else "blocked",
        "ready_for_windows_execution": ready_for_windows_execution,
        "ready_for_authorized_live_submit": ready_for_authorized_live_submit,
        "final_delivery_ready": final_delivery_ready,
        "local_inputs_path": str(local_inputs_path),
        "handoff_bundle_path": str(handoff_path),
        "windows_preflight": {
            "status": windows_preflight.get("status"),
            "ready_for_windows_build": bool(windows_preflight.get("ready_for_windows_build")),
            "failures": windows_preflight.get("failures") or [],
            "missing_final_artifacts": windows_preflight.get("missing_final_artifacts") or [],
        },
        "authorization_handoff": {
            "status": handoff.get("status"),
            "passed": bool(handoff.get("passed")),
            "failures": handoff.get("failures") or [],
            "missing_files": handoff.get("missing_files") or [],
            "forbidden_files": handoff.get("forbidden_files") or [],
            "size": handoff.get("size", 0),
        },
        "live_readiness": {
            "status": live.get("status"),
            "ready_for_live_preflight": bool(live.get("ready_for_live_preflight")),
            "ready_for_live_submit": bool(live.get("ready_for_live_submit")),
            "final_delivery_ready": bool(live.get("final_delivery_ready")),
            "failed_checks": live_failed,
            "blocked_reasons": live_blocked,
            "next_required_actions": live.get("next_required_actions") or [],
            "report_path": live.get("report_path") or "",
            "json_report_path": live.get("json_report_path") or "",
            "operator_commands": operator_commands,
            "blocking_plan": blocking_plan,
            "local_inputs": {
                "path": local_inputs.get("path") or str(local_inputs_path),
                "exists": bool(local_inputs.get("exists")),
                "usable": bool(local_inputs.get("usable")),
                "authorization_confirmed": bool(local_inputs.get("authorization_confirmed")),
                "missing_fields": local_inputs.get("missing_fields") or [],
                "placeholder_fields": local_inputs.get("placeholder_fields") or [],
                "field_status": local_inputs.get("field_status") if isinstance(local_inputs.get("field_status"), dict) else {},
            },
            "activation": {
                "path": activation.get("path") or "",
                "exists": bool(activation.get("exists")),
                "ready": bool(activation.get("ready")),
                "status": activation.get("status") or "",
                "failed_checks": activation.get("failed_checks") or [],
                "next_required_actions": activation.get("next_required_actions") or [],
            },
            "live_validation": {
                "status": live_validation.get("status") or "",
                "selected_profile_count": int(live_validation.get("selected_profile_count") or 0),
                "missing_inputs": live_validation.get("missing_inputs") or [],
                "blocking_summary": live_validation.get("blocking_summary") if isinstance(live_validation.get("blocking_summary"), dict) else {},
            },
        },
        "delivery_package": {
            "status": package.get("status"),
            "passed": bool(package.get("passed")),
            "final_delivery_ready": bool(package.get("final_delivery_ready")),
            "missing_artifacts": missing_artifacts,
            "failures": package.get("failures") or [],
        },
        "blockers": blockers,
        "next_actions": [
            "在 Windows 实机运行 powershell -ExecutionPolicy Bypass -File tools\\build_reachops_windows.ps1。",
            "填写 tools\\reachops_acceptance_inputs.local.ps1 中的授权目标、ProfileIds、ActivationStatusPath，并确认授权。",
            "授权 ready 后运行 tools\\run_reachops_acceptance_windows.ps1 -RunLiveSubmit -ConfirmAuthorizedTargets。",
            "最后运行 tools\\reachops_delivery_package_check.py --json 和 tools\\reachops_final_acceptance_gate.py --json。",
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    live = payload.get("live_readiness") if isinstance(payload.get("live_readiness"), dict) else {}
    local_inputs = live.get("local_inputs") if isinstance(live.get("local_inputs"), dict) else {}
    activation = live.get("activation") if isinstance(live.get("activation"), dict) else {}
    live_validation = live.get("live_validation") if isinstance(live.get("live_validation"), dict) else {}
    lines = [
        "# ReachOps Phase 2 Handoff Check",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_windows_execution: `{str(payload.get('ready_for_windows_execution')).lower()}`",
        f"- ready_for_authorized_live_submit: `{str(payload.get('ready_for_authorized_live_submit')).lower()}`",
        f"- final_delivery_ready: `{str(payload.get('final_delivery_ready')).lower()}`",
        f"- handoff_bundle: `{payload.get('handoff_bundle_path')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    if not blockers:
        lines.append("- none")
    for blocker in blockers:
        lines.append(f"- `{blocker.get('scope')}`: {blocker.get('status')}")
    lines.extend(["", "## Authorized Input Status", ""])
    lines.append(f"- input_file: `{local_inputs.get('path') or payload.get('local_inputs_path')}`")
    lines.append(f"- exists: `{str(bool(local_inputs.get('exists'))).lower()}`")
    lines.append(f"- usable: `{str(bool(local_inputs.get('usable'))).lower()}`")
    lines.append(f"- authorization_confirmed: `{str(bool(local_inputs.get('authorization_confirmed'))).lower()}`")
    placeholders = local_inputs.get("placeholder_fields") or []
    missing = local_inputs.get("missing_fields") or []
    lines.append(f"- placeholder_fields: `{', '.join(placeholders) or '-'}`")
    lines.append(f"- missing_fields: `{', '.join(missing) or '-'}`")
    field_status = local_inputs.get("field_status") if isinstance(local_inputs.get("field_status"), dict) else {}
    if field_status:
        lines.extend(["", "| Field | Ready | State | Required Action |", "| --- | --- | --- | --- |"])
        for name, detail in field_status.items():
            detail = detail if isinstance(detail, dict) else {}
            action = str(detail.get("required_action") or "").replace("|", "\\|")
            lines.append(
                f"| `{name}` | `{str(bool(detail.get('ready'))).lower()}` | `{detail.get('state') or ''}` | {action or '-'} |"
            )
    lines.extend(["", "## Activation", ""])
    lines.append(f"- path: `{activation.get('path') or '-'}`")
    lines.append(f"- ready: `{str(bool(activation.get('ready'))).lower()}`")
    lines.append(f"- status: `{activation.get('status') or '-'}`")
    failed_activation = activation.get("failed_checks") or []
    lines.append(f"- failed_checks: `{', '.join(failed_activation) or '-'}`")
    lines.extend(["", "## Live Validation", ""])
    lines.append(f"- status: `{live_validation.get('status') or '-'}`")
    lines.append(f"- selected_profile_count: `{live_validation.get('selected_profile_count') or 0}`")
    missing_inputs = live_validation.get("missing_inputs") or []
    lines.append(f"- missing_inputs: `{', '.join(missing_inputs) or '-'}`")
    operator_commands = live.get("operator_commands") or []
    if operator_commands:
        lines.extend(["", "## Operator Commands", ""])
        for command in operator_commands:
            lines.append(f"- `{command}`")
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ReachOps Phase 2 Windows/auth handoff readiness.")
    parser.add_argument("--local-inputs-path", default=str(LOCAL_INPUTS_PATH))
    parser.add_argument("--handoff-path", default=str(HANDOFF_PATH))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_check(Path(args.local_inputs_path), Path(args.handoff_path))
    if args.write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        MD_PATH.write_text(render_markdown(payload), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps phase2 handoff: {payload['status']}")
        print(f"ready_for_windows_execution={payload['ready_for_windows_execution']}")
        print(f"final_delivery_ready={payload['final_delivery_ready']}")
    return 0 if payload.get("ready_for_windows_execution") else 1


if __name__ == "__main__":
    raise SystemExit(main())
