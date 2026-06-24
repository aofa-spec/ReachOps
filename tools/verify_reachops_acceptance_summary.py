# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STATUS_PASSED = "passed"
STATUS_READY_FOR_EXTERNAL_VALIDATION = "ready_for_external_validation"
STATUS_FAILED = "failed"


def load_summary(path: str | Path) -> dict[str, Any]:
    summary_path = Path(path)
    if not summary_path.exists():
        raise FileNotFoundError(str(summary_path))
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance summary must be a JSON object")
    return payload


def verify_summary(summary: dict[str, Any], allow_external_pending: bool = False) -> dict[str, Any]:
    status = str(summary.get("status") or "").strip()
    delivery_audit = summary.get("delivery_audit") or {}
    operator_pressure = summary.get("operator_pressure") or {}
    installer_smoke = summary.get("installer_smoke") or {}
    ui_startup = summary.get("ui_startup") or {}
    live_validation = summary.get("live_validation") or {}
    live_readiness = summary.get("live_readiness") or {}
    live_preflight = summary.get("live_preflight") or {}
    live_submit = summary.get("live_submit") or {}
    goal_status = summary.get("goal_status") or {}

    failures: list[str] = []
    pending: list[str] = []

    if status not in {STATUS_PASSED, STATUS_READY_FOR_EXTERNAL_VALIDATION, STATUS_FAILED}:
        failures.append(f"unknown_status:{status or 'empty'}")
    if status == STATUS_FAILED:
        failures.append("summary_status_failed")

    if int(delivery_audit.get("failed") or 0) > 0:
        failures.append("delivery_audit_failed")
    if str(delivery_audit.get("status") or "") != "ok":
        failures.append("delivery_audit_not_ok")

    operator_pressure_ok = (
        str(operator_pressure.get("status") or "") == "ok"
        and int(operator_pressure.get("campaign_count") or 0) >= 3
        and int(operator_pressure.get("content_found") or 0) > 0
        and int(operator_pressure.get("comment_users") or 0) > 0
        and int(operator_pressure.get("customer_leads") or 0) > 0
        and int(operator_pressure.get("outreach_actions") or 0) > 0
        and int(operator_pressure.get("execution_success") or 0) > 0
        and int(operator_pressure.get("account_switched") or 0) > 0
    )
    if not operator_pressure_ok:
        failures.append("operator_pressure_failed")

    pending_external = int(delivery_audit.get("pending_external_validation") or 0)
    resolved_external = int(delivery_audit.get("resolved_external_validation") or 0)
    if "effective_pending_external_validation" in delivery_audit:
        effective_pending_external = int(delivery_audit.get("effective_pending_external_validation") or 0)
    else:
        effective_pending_external = max(0, pending_external - resolved_external)
    if effective_pending_external > 0:
        pending.append("external_platform_validation")

    installer_status = str(installer_smoke.get("status") or "")
    installer_optional = bool(installer_smoke.get("optional"))
    installer_ok = (
        (
            installer_status == "ok"
            and bool(installer_smoke.get("exe_exists"))
            and not bool(installer_smoke.get("data_in_install_dir"))
            and bool(installer_smoke.get("hash_ok"))
        )
        or (installer_status == "skipped_optional" and installer_optional)
    )
    if not installer_ok:
        failures.append("installer_smoke_failed")

    ui_startup_ok = (
        str(ui_startup.get("status") or "") == "ok"
        and bool(ui_startup.get("process_running"))
        and bool(ui_startup.get("interactive_task"))
    )
    if not ui_startup_ok:
        failures.append("ui_startup_failed")

    if live_validation:
        if not bool(live_validation.get("no_browser_started", True)):
            failures.append("live_validation_started_browser")
        if not bool(live_validation.get("no_submit", True)):
            failures.append("live_validation_submitted_action")

    if str(live_preflight.get("status") or "") == "completed":
        missing_preflight = (
            live_preflight.get("missing_preflight_action_types")
            if isinstance(live_preflight.get("missing_preflight_action_types"), list)
            else []
        )
        preflight_statuses = (
            live_preflight.get("preflight_action_statuses")
            if isinstance(live_preflight.get("preflight_action_statuses"), dict)
            else {}
        )
        required_action_types = {"comment_reply", "follow_review", "dm_review"}
        present_success = {
            action_type
            for action_type, rows in preflight_statuses.items()
            if isinstance(rows, list) and any(str(row.get("status") or "") == "success" for row in rows if isinstance(row, dict))
        }
        if missing_preflight or sorted(required_action_types - present_success):
            failures.append("live_preflight_action_missing")

    if str(live_submit.get("status") or "") == "failed":
        failures.append("live_submit_failed")
    if str(live_submit.get("status") or "") == "completed" and not bool(live_submit.get("platform_validation")):
        failures.append("live_submit_not_platform_validation")
    if (
        str(live_submit.get("status") or "") == "completed"
        and bool(live_submit.get("platform_validation"))
        and not bool(live_submit.get("activation_status_loaded"))
    ):
        failures.append("live_submit_activation_status_missing")
    evidence_by_action_type = live_submit.get("evidence_by_action_type") if isinstance(live_submit.get("evidence_by_action_type"), dict) else {}
    evidence_file_details = live_submit.get("evidence_file_details") if isinstance(live_submit.get("evidence_file_details"), dict) else {}
    missing_evidence_action_types = live_submit.get("missing_evidence_action_types") if isinstance(live_submit.get("missing_evidence_action_types"), list) else []
    missing_local_evidence_file_action_types = (
        live_submit.get("missing_local_evidence_file_action_types")
        if isinstance(live_submit.get("missing_local_evidence_file_action_types"), list)
        else []
    )
    if str(live_submit.get("status") or "") == "completed" and bool(live_submit.get("platform_validation")):
        required_action_types = {"comment_reply", "follow_review", "dm_review"}
        present_action_types = {key for key, value in evidence_by_action_type.items() if value}
        missing_required = sorted(required_action_types - present_action_types)
        if missing_evidence_action_types or missing_required:
            failures.append("live_submit_action_evidence_missing")
        if missing_local_evidence_file_action_types:
            failures.append("live_submit_local_evidence_file_missing")
        detail_action_types = {key for key, value in evidence_file_details.items() if value}
        if sorted(required_action_types - detail_action_types):
            failures.append("live_submit_evidence_file_details_missing")
        else:
            for action_type in required_action_types:
                valid_detail = False
                for detail in evidence_file_details.get(action_type, []):
                    if not isinstance(detail, dict):
                        continue
                    sha = str(detail.get("sha256") or "")
                    sidecar = detail.get("sidecar") if isinstance(detail.get("sidecar"), dict) else {}
                    sidecar_sha = str(sidecar.get("screenshot_sha256") or "")
                    if (
                        int(detail.get("size") or 0) > 0
                        and len(sha) == 64
                        and str(detail.get("sidecar_path") or "")
                        and sidecar_sha == sha
                        and str(sidecar.get("action_type") or "") == action_type
                        and str(sidecar.get("profile_id") or "")
                        and str(sidecar.get("action_id") or "")
                        and str(sidecar.get("current_url") or "")
                    ):
                        valid_detail = True
                        break
                if not valid_detail:
                    failures.append("live_submit_evidence_file_details_invalid")
                    break

    passed = not failures and (allow_external_pending or not pending)
    if status == STATUS_PASSED and pending:
        failures.append("passed_status_with_external_pending")
        passed = False
    if status == STATUS_READY_FOR_EXTERNAL_VALIDATION and not pending:
        failures.append("ready_status_without_external_pending")
        passed = False

    goal_status_value = str(goal_status.get("status") or "")
    goal_pending = (
        goal_status.get("pending_external_validation")
        if isinstance(goal_status.get("pending_external_validation"), list)
        else []
    )
    goal_summary = goal_status.get("summary") if isinstance(goal_status.get("summary"), dict) else {}
    if goal_status:
        if goal_status_value not in {STATUS_PASSED, STATUS_READY_FOR_EXTERNAL_VALIDATION, STATUS_FAILED}:
            failures.append("goal_status_unknown")
            passed = False
        if goal_status_value == STATUS_FAILED:
            failures.append("goal_status_failed")
            passed = False
        if status == STATUS_PASSED and goal_status_value != STATUS_PASSED:
            failures.append("goal_status_not_passed")
            passed = False
        if status == STATUS_READY_FOR_EXTERNAL_VALIDATION and goal_status_value != STATUS_READY_FOR_EXTERNAL_VALIDATION:
            failures.append("goal_status_not_ready")
            passed = False
        if effective_pending_external > 0 and "真实 TikTok 平台提交" not in goal_pending:
            failures.append("goal_status_missing_platform_pending")
            passed = False
        if effective_pending_external == 0 and goal_pending:
            failures.append("goal_status_has_stale_pending")
            passed = False

    return {
        "passed": passed,
        "status": status,
        "allow_external_pending": bool(allow_external_pending),
        "failures": failures,
        "pending": pending,
        "delivery_audit": {
            "passed": int(delivery_audit.get("passed") or 0),
            "pending_external_validation": pending_external,
            "resolved_external_validation": resolved_external,
            "effective_pending_external_validation": effective_pending_external,
            "failed": int(delivery_audit.get("failed") or 0),
        },
        "operator_pressure": {
            "status": str(operator_pressure.get("status") or ""),
            "campaign_count": int(operator_pressure.get("campaign_count") or 0),
            "content_found": int(operator_pressure.get("content_found") or 0),
            "comment_users": int(operator_pressure.get("comment_users") or 0),
            "customer_leads": int(operator_pressure.get("customer_leads") or 0),
            "outreach_actions": int(operator_pressure.get("outreach_actions") or 0),
            "execution_success": int(operator_pressure.get("execution_success") or 0),
            "account_switched": int(operator_pressure.get("account_switched") or 0),
        },
        "installer_smoke": {
            "status": installer_status,
            "optional": installer_optional,
            "exe_exists": bool(installer_smoke.get("exe_exists")),
            "data_in_install_dir": bool(installer_smoke.get("data_in_install_dir")),
            "hash_ok": bool(installer_smoke.get("hash_ok")),
        },
        "ui_startup": {
            "status": str(ui_startup.get("status") or ""),
            "process_running": bool(ui_startup.get("process_running")),
            "interactive_task": bool(ui_startup.get("interactive_task")),
        },
        "live_preflight": {
            "status": str(live_preflight.get("status") or ""),
            "missing_preflight_action_types": list(live_preflight.get("missing_preflight_action_types") or []),
        },
        "live_validation": {
            "status": str(live_validation.get("status") or ""),
            "no_browser_started": bool(live_validation.get("no_browser_started", True)),
            "no_submit": bool(live_validation.get("no_submit", True)),
            "missing_inputs": list(live_validation.get("missing_inputs") or []),
            "selected_profile_ids": list(live_validation.get("selected_profile_ids") or []),
        },
        "live_readiness": {
            "status": str(live_readiness.get("status") or ""),
            "ready": bool(live_readiness.get("ready")),
            "no_browser_started": bool(live_readiness.get("no_browser_started", True)),
            "no_submit": bool(live_readiness.get("no_submit", True)),
        },
        "live_submit": {
            "status": str(live_submit.get("status") or ""),
            "executor_mode": str(live_submit.get("executor_mode") or ""),
            "platform_validation": bool(live_submit.get("platform_validation")),
            "activation_status_loaded": bool(live_submit.get("activation_status_loaded")),
            "activation_status_source": str(live_submit.get("activation_status_source") or ""),
            "missing_evidence_action_types": list(missing_evidence_action_types),
            "missing_local_evidence_file_action_types": list(missing_local_evidence_file_action_types),
            "evidence_file_detail_action_types": sorted(evidence_file_details.keys()),
        },
        "goal_status": {
            "status": goal_status_value,
            "stages_passed": int(goal_summary.get("stages_passed") or 0),
            "stages_pending_external_validation": int(goal_summary.get("stages_pending_external_validation") or 0),
            "stages_failed": int(goal_summary.get("stages_failed") or 0),
            "pending_external_validation": list(goal_pending),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ReachOps acceptance_summary.json.")
    parser.add_argument("summary", help="Path to acceptance_summary.json")
    parser.add_argument("--allow-external-pending", action="store_true", help="Return success for ready_for_external_validation.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable verification result.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = verify_summary(load_summary(args.summary), allow_external_pending=args.allow_external_pending)
    except Exception as exc:
        result = {
            "passed": False,
            "status": "failed",
            "allow_external_pending": bool(args.allow_external_pending),
            "failures": [exc.__class__.__name__],
            "error": str(exc),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps acceptance status: {result.get('status')}")
        if result.get("pending"):
            print(f"Pending: {', '.join(result['pending'])}")
        if result.get("failures"):
            print(f"Failures: {', '.join(result['failures'])}")

    if result.get("passed"):
        return 0
    if result.get("pending") and not result.get("failures"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
