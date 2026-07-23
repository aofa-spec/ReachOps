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
REQUIRED_CURRENT_GOAL_PENDING = {
    "授权允许时能真实执行",
    "真实 TikTok 平台提交",
    "客户端交付验收门禁不会把环境阻断当通过",
}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def load_summary(path: str | Path) -> dict[str, Any]:
    summary_path = Path(path)
    if not summary_path.exists():
        raise FileNotFoundError(str(summary_path))
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance summary must be a JSON object")
    return payload


def report_path_status(summary_path: str | Path | None, raw_path: str) -> dict[str, Any]:
    path_text = str(raw_path or "").strip()
    detail: dict[str, Any] = {"path": path_text, "exists": False, "size": 0, "inside_summary_dir": False}
    if not path_text:
        return detail
    summary_parent = Path(summary_path).resolve().parent if summary_path else None
    candidates = [Path(path_text)]
    if summary_parent:
        candidates.append(summary_parent / path_text)
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            inside_summary_dir = False
            if summary_parent:
                try:
                    resolved.relative_to(summary_parent)
                    inside_summary_dir = True
                except Exception:
                    inside_summary_dir = False
            detail.update(
                {
                    "path": str(resolved),
                    "exists": True,
                    "size": candidate.stat().st_size,
                    "inside_summary_dir": inside_summary_dir,
                }
            )
            return detail
    return detail


def load_report_payload(detail: dict[str, Any]) -> dict[str, Any]:
    if not bool(detail.get("exists")):
        return {"loaded": False, "error": "missing", "payload": {}}
    try:
        payload = json.loads(Path(str(detail.get("path") or "")).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"loaded": False, "error": exc.__class__.__name__, "payload": {}}
    if not isinstance(payload, dict):
        return {"loaded": False, "error": "not_object", "payload": {}}
    return {"loaded": True, "error": "", "payload": payload}


def verify_summary(
    summary: dict[str, Any],
    allow_external_pending: bool = False,
    summary_path: str | Path | None = None,
) -> dict[str, Any]:
    status = str(summary.get("status") or "").strip()
    delivery_audit = summary.get("delivery_audit") or {}
    operator_pressure = summary.get("operator_pressure") or {}
    installer_smoke = summary.get("installer_smoke") or {}
    ui_startup = summary.get("ui_startup") or {}
    live_validation = summary.get("live_validation") or {}
    repository_cleanliness = summary.get("repository_cleanliness") or {}
    windows_package_preflight = summary.get("windows_package_preflight") or {}
    windows_credential_manager_validation = summary.get("windows_credential_manager_validation") or {}
    client_delivery = summary.get("client_delivery") or {}
    live_readiness = summary.get("live_readiness") or {}
    live_acceptance_status = summary.get("live_acceptance_status") or {}
    authorization_handoff = summary.get("authorization_handoff") or {}
    live_preflight = summary.get("live_preflight") or {}
    live_submit = summary.get("live_submit") or {}
    goal_status = summary.get("goal_status") or {}
    final_acceptance_gate = summary.get("final_acceptance_gate") or {}
    preflight_environment = (
        live_preflight.get("environment_diagnostics")
        if isinstance(live_preflight.get("environment_diagnostics"), dict)
        else {}
    )

    failures: list[str] = []
    pending: list[str] = []

    def add_pending(code: str):
        if code and code not in pending:
            pending.append(code)

    goal_status_value = str(goal_status.get("status") or "")
    goal_pending = (
        goal_status.get("pending_external_validation")
        if isinstance(goal_status.get("pending_external_validation"), list)
        else []
    )
    goal_summary = goal_status.get("summary") if isinstance(goal_status.get("summary"), dict) else {}

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
    final_external_resolved = status == STATUS_PASSED or effective_pending_external == 0
    if effective_pending_external > 0:
        add_pending("external_platform_validation")
        goal_pending_codes = {
            "授权允许时能真实执行": "live_authorization_execution_validation",
            "真实 TikTok 平台提交": "real_tiktok_platform_submit",
            "客户端交付验收门禁不会把环境阻断当通过": "client_delivery_acceptance_gate",
        }
        for item in goal_pending:
            add_pending(goal_pending_codes.get(str(item), ""))

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

    ui_startup_json = report_path_status(
        summary_path,
        str(ui_startup.get("json_path") or ""),
    )
    ui_startup_ok = (
        str(ui_startup.get("status") or "") == "ok"
        and bool(ui_startup.get("process_running"))
        and bool(ui_startup.get("interactive_task"))
        and str(ui_startup.get("client_surface") or "") == "local_client_console"
        and str(ui_startup.get("loopback_host") or "") in {"127.0.0.1", "localhost"}
        and bool(ui_startup.get("no_browser_started", False))
        and bool(ui_startup.get("no_submit", False))
    )
    if not ui_startup_ok:
        failures.append("ui_startup_failed")
    if str(ui_startup.get("client_surface") or "") != "local_client_console":
        failures.append("ui_startup_client_surface_not_local_console")
    if str(ui_startup.get("loopback_host") or "") not in {"127.0.0.1", "localhost"}:
        failures.append("ui_startup_loopback_not_local")
    if not bool(ui_startup.get("no_browser_started", False)):
        failures.append("ui_startup_started_browser")
    if not bool(ui_startup.get("no_submit", False)):
        failures.append("ui_startup_submitted_action")
    if status == STATUS_PASSED and not str(ui_startup.get("json_path") or "").strip():
        failures.append("ui_startup_json_path_missing")
    if status == STATUS_PASSED and summary_path and str(ui_startup.get("json_path") or "").strip():
        if not ui_startup_json["exists"]:
            failures.append("ui_startup_json_missing")
        elif int(ui_startup_json.get("size") or 0) <= 0:
            failures.append("ui_startup_json_empty")
        elif not bool(ui_startup_json.get("inside_summary_dir")):
            failures.append("ui_startup_json_outside_summary_dir")
    ui_startup_payload_detail = {"loaded": False, "error": "", "payload": {}}
    if (
        status == STATUS_PASSED
        and summary_path
        and bool(ui_startup_json.get("exists"))
        and int(ui_startup_json.get("size") or 0) > 0
        and bool(ui_startup_json.get("inside_summary_dir"))
    ):
        ui_startup_payload_detail = load_report_payload(ui_startup_json)
        ui_startup_payload = ui_startup_payload_detail.get("payload") or {}
        if not bool(ui_startup_payload_detail.get("loaded")):
            failures.append("ui_startup_json_invalid")
        else:
            expected_ui_fields = {
                "status": str(ui_startup.get("status") or ""),
                "process_running": bool(ui_startup.get("process_running")),
                "interactive_task": bool(ui_startup.get("interactive_task")),
                "client_surface": str(ui_startup.get("client_surface") or ""),
                "loopback_host": str(ui_startup.get("loopback_host") or ""),
                "no_browser_started": bool(ui_startup.get("no_browser_started", False)),
                "no_submit": bool(ui_startup.get("no_submit", False)),
            }
            for key, expected in expected_ui_fields.items():
                actual = ui_startup_payload.get(key)
                if isinstance(expected, bool):
                    matches = bool(actual) == expected
                else:
                    matches = str(actual or "") == expected
                if not matches:
                    failures.append(f"ui_startup_json_mismatch:{key}")

    if live_validation:
        if not bool(live_validation.get("no_browser_started", True)):
            failures.append("live_validation_started_browser")
        if not bool(live_validation.get("no_submit", True)):
            failures.append("live_validation_submitted_action")

    repository_cleanliness_status = str(repository_cleanliness.get("status") or "")
    repository_cleanliness_passed = bool(repository_cleanliness.get("passed"))
    repository_cleanliness_forbidden_count = int(repository_cleanliness.get("forbidden_count") or 0)
    repository_cleanliness_json = report_path_status(
        summary_path,
        str(repository_cleanliness.get("json_path") or ""),
    )
    if status == STATUS_PASSED and not repository_cleanliness:
        failures.append("repository_cleanliness_missing")
    if repository_cleanliness:
        if repository_cleanliness_status != STATUS_PASSED:
            failures.append("repository_cleanliness_not_passed")
        if not repository_cleanliness_passed:
            failures.append("repository_cleanliness_failed")
        if repository_cleanliness_forbidden_count != 0:
            failures.append("repository_cleanliness_forbidden_items")
        if status == STATUS_PASSED and not str(repository_cleanliness.get("json_path") or "").strip():
            failures.append("repository_cleanliness_json_path_missing")
        if status == STATUS_PASSED and summary_path and str(repository_cleanliness.get("json_path") or "").strip():
            if not repository_cleanliness_json["exists"]:
                failures.append("repository_cleanliness_json_missing")
            elif int(repository_cleanliness_json.get("size") or 0) <= 0:
                failures.append("repository_cleanliness_json_empty")
            elif not bool(repository_cleanliness_json.get("inside_summary_dir")):
                failures.append("repository_cleanliness_json_outside_summary_dir")

    windows_preflight_status = str(windows_package_preflight.get("status") or "")
    windows_preflight_ready = bool(windows_package_preflight.get("ready_for_windows_build"))
    windows_preflight_contract = (
        windows_package_preflight.get("build_contract")
        if isinstance(windows_package_preflight.get("build_contract"), dict)
        else {}
    )
    windows_preflight_json = report_path_status(
        summary_path,
        str(windows_package_preflight.get("json_path") or ""),
    )
    if status == STATUS_PASSED and not windows_package_preflight:
        failures.append("windows_package_preflight_missing")
    if windows_package_preflight:
        if windows_preflight_status != "ready_for_windows_build":
            failures.append("windows_package_preflight_not_ready")
        if not windows_preflight_ready:
            failures.append("windows_package_preflight_failed")
        if not bool(windows_preflight_contract.get("default_build_requires_installer")):
            failures.append("windows_package_preflight_installer_contract_missing")
        if not bool(windows_preflight_contract.get("skip_installer_is_non_final")):
            failures.append("windows_package_preflight_skip_installer_contract_missing")
        if status == STATUS_PASSED and not str(windows_package_preflight.get("json_path") or "").strip():
            failures.append("windows_package_preflight_json_path_missing")
        if status == STATUS_PASSED and summary_path and str(windows_package_preflight.get("json_path") or "").strip():
            if not windows_preflight_json["exists"]:
                failures.append("windows_package_preflight_json_missing")
            elif int(windows_preflight_json.get("size") or 0) <= 0:
                failures.append("windows_package_preflight_json_empty")
            elif not bool(windows_preflight_json.get("inside_summary_dir")):
                failures.append("windows_package_preflight_json_outside_summary_dir")

    credential_validation_status = str(windows_credential_manager_validation.get("status") or "")
    credential_validation_checks = (
        windows_credential_manager_validation.get("checks")
        if isinstance(windows_credential_manager_validation.get("checks"), dict)
        else {}
    )
    credential_validation_json = report_path_status(
        summary_path,
        str(windows_credential_manager_validation.get("json_path") or ""),
    )
    if status == STATUS_PASSED and not windows_credential_manager_validation:
        failures.append("windows_credential_manager_validation_missing")
    if windows_credential_manager_validation:
        if credential_validation_status != STATUS_PASSED:
            failures.append("windows_credential_manager_validation_not_passed")
        if not bool(windows_credential_manager_validation.get("passed")):
            failures.append("windows_credential_manager_validation_failed")
        if str(windows_credential_manager_validation.get("backend") or "") != "windows_credential_manager":
            failures.append("windows_credential_manager_validation_backend_invalid")
        if not bool(credential_validation_checks.get("windows_credential_manager_available")):
            failures.append("windows_credential_manager_validation_unavailable")
        if not bool(credential_validation_checks.get("secret_write_succeeded")):
            failures.append("windows_credential_manager_validation_write_failed")
        if not bool(credential_validation_checks.get("secret_readback_matched")):
            failures.append("windows_credential_manager_validation_readback_failed")
        if not bool(credential_validation_checks.get("secret_delete_succeeded")):
            failures.append("windows_credential_manager_validation_delete_failed")
        if not bool(credential_validation_checks.get("output_excludes_secret_value")):
            failures.append("windows_credential_manager_validation_output_leaked_secret")
        if not bool(windows_credential_manager_validation.get("no_browser_started", True)):
            failures.append("windows_credential_manager_validation_opened_browser")
        if not bool(windows_credential_manager_validation.get("no_submit", True)):
            failures.append("windows_credential_manager_validation_submitted_action")
        if bool(windows_credential_manager_validation.get("customer_data_uploaded")):
            failures.append("windows_credential_manager_validation_uploaded_customer_data")
        if bool(windows_credential_manager_validation.get("secret_value_included")):
            failures.append("windows_credential_manager_validation_included_secret_value")
        if status == STATUS_PASSED and not str(windows_credential_manager_validation.get("json_path") or "").strip():
            failures.append("windows_credential_manager_validation_json_path_missing")
        if status == STATUS_PASSED and summary_path and str(windows_credential_manager_validation.get("json_path") or "").strip():
            if not credential_validation_json["exists"]:
                failures.append("windows_credential_manager_validation_json_missing")
            elif int(credential_validation_json.get("size") or 0) <= 0:
                failures.append("windows_credential_manager_validation_json_empty")
            elif not bool(credential_validation_json.get("inside_summary_dir")):
                failures.append("windows_credential_manager_validation_json_outside_summary_dir")
        credential_payload_detail = {"loaded": False, "error": "", "payload": {}}
        if (
            status == STATUS_PASSED
            and summary_path
            and bool(credential_validation_json.get("exists"))
            and int(credential_validation_json.get("size") or 0) > 0
            and bool(credential_validation_json.get("inside_summary_dir"))
        ):
            credential_payload_detail = load_report_payload(credential_validation_json)
            credential_payload = credential_payload_detail.get("payload") or {}
            if not bool(credential_payload_detail.get("loaded")):
                failures.append("windows_credential_manager_validation_json_invalid")
            else:
                expected_credential_fields = {
                    "status": credential_validation_status,
                    "passed": bool(windows_credential_manager_validation.get("passed")),
                    "backend": str(windows_credential_manager_validation.get("backend") or ""),
                    "no_browser_started": bool(windows_credential_manager_validation.get("no_browser_started", True)),
                    "no_submit": bool(windows_credential_manager_validation.get("no_submit", True)),
                    "customer_data_uploaded": bool(windows_credential_manager_validation.get("customer_data_uploaded")),
                    "secret_value_included": bool(windows_credential_manager_validation.get("secret_value_included")),
                }
                for key, expected in expected_credential_fields.items():
                    actual = credential_payload.get(key)
                    if isinstance(expected, bool):
                        matches = bool(actual) == expected
                    else:
                        matches = str(actual or "") == expected
                    if not matches:
                        failures.append(f"windows_credential_manager_validation_json_mismatch:{key}")
                payload_checks = credential_payload.get("checks") if isinstance(credential_payload.get("checks"), dict) else {}
                for key, expected in credential_validation_checks.items():
                    if bool(payload_checks.get(key)) != bool(expected):
                        failures.append(f"windows_credential_manager_validation_json_mismatch:checks.{key}")
    else:
        credential_payload_detail = {"loaded": False, "error": "", "payload": {}}

    client_delivery_status = str(client_delivery.get("status") or "")
    client_delivery_readiness = str(client_delivery.get("readiness") or "")
    client_delivery_json = report_path_status(
        summary_path,
        str(client_delivery.get("json_path") or ""),
    )
    client_delivery_failed_checks = as_list(client_delivery.get("failed_checks"))
    if status == STATUS_PASSED and not client_delivery:
        failures.append("client_delivery_missing")
    if client_delivery:
        if client_delivery_status != STATUS_PASSED:
            failures.append("client_delivery_not_passed")
        if client_delivery_readiness != "pass":
            failures.append("client_delivery_readiness_not_pass")
        if not bool(client_delivery.get("contract_ok")):
            failures.append("client_delivery_contract_not_ok")
        if not bool(client_delivery.get("acceptance_ready")):
            failures.append("client_delivery_acceptance_not_ready")
        if not bool(client_delivery.get("final_delivery_ready")):
            failures.append("client_delivery_final_not_ready")
        if client_delivery_failed_checks:
            failures.append("client_delivery_failed_checks")
        if status == STATUS_PASSED and not str(client_delivery.get("json_path") or "").strip():
            failures.append("client_delivery_json_path_missing")
        if status == STATUS_PASSED and summary_path and str(client_delivery.get("json_path") or "").strip():
            if not client_delivery_json["exists"]:
                failures.append("client_delivery_json_missing")
            elif int(client_delivery_json.get("size") or 0) <= 0:
                failures.append("client_delivery_json_empty")
            elif not bool(client_delivery_json.get("inside_summary_dir")):
                failures.append("client_delivery_json_outside_summary_dir")
        client_delivery_payload_detail = {"loaded": False, "error": "", "payload": {}}
        if (
            status == STATUS_PASSED
            and summary_path
            and bool(client_delivery_json.get("exists"))
            and int(client_delivery_json.get("size") or 0) > 0
            and bool(client_delivery_json.get("inside_summary_dir"))
        ):
            client_delivery_payload_detail = load_report_payload(client_delivery_json)
            client_delivery_payload = client_delivery_payload_detail.get("payload") or {}
            if not bool(client_delivery_payload_detail.get("loaded")):
                failures.append("client_delivery_json_invalid")
            else:
                expected_client_delivery_fields = {
                    "status": client_delivery_status,
                    "readiness": client_delivery_readiness,
                    "contract_ok": bool(client_delivery.get("contract_ok")),
                    "acceptance_ready": bool(client_delivery.get("acceptance_ready")),
                    "final_delivery_ready": bool(client_delivery.get("final_delivery_ready")),
                }
                for key, expected in expected_client_delivery_fields.items():
                    actual = client_delivery_payload.get(key)
                    if isinstance(expected, bool):
                        matches = bool(actual) == expected
                    else:
                        matches = str(actual or "") == expected
                    if not matches:
                        failures.append(f"client_delivery_json_mismatch:{key}")
                payload_failed_checks = as_list(client_delivery_payload.get("failed_checks"))
                if [str(item) for item in payload_failed_checks] != [str(item) for item in client_delivery_failed_checks]:
                    failures.append("client_delivery_json_mismatch:failed_checks")
    else:
        client_delivery_payload_detail = {"loaded": False, "error": "", "payload": {}}

    if final_external_resolved:
        readiness_status = str(live_readiness.get("status") or "")
        if readiness_status not in {"ready", "completed"} or not bool(live_readiness.get("ready")):
            failures.append("live_readiness_not_ready")
        if not bool(live_readiness.get("no_browser_started", True)):
            failures.append("live_readiness_started_browser")
        if not bool(live_readiness.get("no_submit", True)):
            failures.append("live_readiness_submitted_action")
        if str(live_preflight.get("status") or "") != "completed":
            failures.append("live_preflight_not_completed")

    if status == STATUS_PASSED and not live_acceptance_status:
        failures.append("live_acceptance_status_missing")
    if live_acceptance_status:
        live_acceptance_status_value = str(live_acceptance_status.get("status") or "")
        live_acceptance_local_inputs = (
            live_acceptance_status.get("local_inputs")
            if isinstance(live_acceptance_status.get("local_inputs"), dict)
            else {}
        )
        live_acceptance_activation = (
            live_acceptance_status.get("activation")
            if isinstance(live_acceptance_status.get("activation"), dict)
            else {}
        )
        live_acceptance_validation = (
            live_acceptance_status.get("live_validation")
            if isinstance(live_acceptance_status.get("live_validation"), dict)
            else {}
        )
        live_acceptance_missing_inputs = as_list(live_acceptance_validation.get("missing_inputs"))
        live_acceptance_selected_profiles = as_list(live_acceptance_validation.get("selected_profile_ids"))
        live_acceptance_failed_checks = as_list(live_acceptance_status.get("failed_checks"))
        if status == STATUS_PASSED and live_acceptance_status_value != STATUS_PASSED:
            failures.append("live_acceptance_status_not_passed")
        if status == STATUS_PASSED and not bool(live_acceptance_status.get("final_delivery_ready")):
            failures.append("live_acceptance_status_final_not_ready")
        if status == STATUS_PASSED and not bool(live_acceptance_status.get("ready_for_live_submit")):
            failures.append("live_acceptance_status_not_ready_for_live_submit")
        if status == STATUS_PASSED and not bool(live_acceptance_local_inputs.get("usable")):
            failures.append("live_acceptance_status_local_inputs_unusable")
        if status == STATUS_PASSED and not bool(live_acceptance_activation.get("ready")):
            failures.append("live_acceptance_status_activation_not_ready")
        if status == STATUS_PASSED and not live_acceptance_selected_profiles:
            failures.append("live_acceptance_status_profile_ids_missing")
        if status == STATUS_PASSED and live_acceptance_missing_inputs:
            failures.append("live_acceptance_status_missing_inputs")
        if status == STATUS_PASSED and live_acceptance_failed_checks:
            failures.append("live_acceptance_status_failed_checks")
    else:
        live_acceptance_status_value = ""
        live_acceptance_local_inputs = {}
        live_acceptance_activation = {}
        live_acceptance_validation = {}
        live_acceptance_missing_inputs = []
        live_acceptance_selected_profiles = []
        live_acceptance_failed_checks = []

    authorization_handoff_json = report_path_status(
        summary_path,
        authorization_handoff.get("json_path") if isinstance(authorization_handoff, dict) else "",
    )
    if status == STATUS_PASSED and not authorization_handoff:
        failures.append("authorization_handoff_missing")
    if authorization_handoff:
        authorization_handoff_status = str(authorization_handoff.get("status") or "")
        if status == STATUS_PASSED and authorization_handoff_status not in {"created", "passed"}:
            failures.append("authorization_handoff_not_created")
        if status == STATUS_PASSED and not bool(authorization_handoff.get("exists")):
            failures.append("authorization_handoff_bundle_missing")
        if status == STATUS_PASSED and not bool(authorization_handoff.get("no_browser_started", True)):
            failures.append("authorization_handoff_opened_browser")
        if status == STATUS_PASSED and not bool(authorization_handoff.get("no_submit", True)):
            failures.append("authorization_handoff_submitted_action")
        if status == STATUS_PASSED and not str(authorization_handoff.get("bundle_path") or "").strip():
            failures.append("authorization_handoff_bundle_path_missing")
        if status == STATUS_PASSED and not str(authorization_handoff.get("json_path") or "").strip():
            failures.append("authorization_handoff_json_path_missing")
        if status == STATUS_PASSED and summary_path and str(authorization_handoff.get("json_path") or "").strip():
            if not authorization_handoff_json["exists"]:
                failures.append("authorization_handoff_json_missing")
            elif int(authorization_handoff_json.get("size") or 0) <= 0:
                failures.append("authorization_handoff_json_empty")
            elif not bool(authorization_handoff_json.get("inside_summary_dir")):
                failures.append("authorization_handoff_json_outside_summary_dir")
    else:
        authorization_handoff_status = ""

    if str(live_preflight.get("status") or "") == "completed":
        missing_preflight = (
            live_preflight.get("missing_preflight_action_types")
            if isinstance(live_preflight.get("missing_preflight_action_types"), list)
            else []
        )
        preflight_evidence_details = (
            live_preflight.get("evidence_file_details")
            if isinstance(live_preflight.get("evidence_file_details"), dict)
            else {}
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
            preflight_has_failure_evidence = any(
                isinstance(rows, list)
                and any(
                    isinstance(row, dict)
                    and int(row.get("size") or 0) > 0
                    and len(str(row.get("sha256") or "")) == 64
                    and str(row.get("path") or "")
                    for row in rows
                )
                for rows in preflight_evidence_details.values()
            )
            if allow_external_pending and bool(live_preflight.get("no_submit", True)) and preflight_has_failure_evidence:
                add_pending("live_preflight_environment_validation")
            else:
                failures.append("live_preflight_action_missing")

    if str(live_submit.get("status") or "") == "failed":
        failures.append("live_submit_failed")
    if str(live_submit.get("status") or "") == "completed" and not bool(live_submit.get("platform_validation")):
        failures.append("live_submit_not_platform_validation")
    if (
        str(live_submit.get("status") or "") == "completed"
        and bool(live_submit.get("platform_validation"))
        and str(live_submit.get("executor_mode") or "") != "platform_selenium"
    ):
        failures.append("live_submit_executor_not_platform_selenium")
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
        live_submit_summary = live_submit.get("summary") if isinstance(live_submit.get("summary"), dict) else {}
        live_submit_required_types = {"comment_reply", "follow_review", "dm_review"}
        live_submit_result_types = {
            str(row.get("action_type") or "")
            for row in (live_submit_summary.get("results") or [])
            if isinstance(row, dict) and str(row.get("status") or "") == "success"
        }
        if (
            not bool(live_submit.get("passed"))
            or not bool(live_submit.get("live_submit"))
            or int(live_submit_summary.get("selected_actions") or 0) < len(live_submit_required_types)
            or int(live_submit_summary.get("success") or 0) < len(live_submit_required_types)
            or int(live_submit_summary.get("failed") or 0) > 0
            or int(live_submit_summary.get("skipped") or 0) > 0
            or sorted(live_submit_required_types - live_submit_result_types)
        ):
            failures.append("live_submit_execution_summary_invalid")
        required_action_types = {"comment_reply", "follow_review", "dm_review"}
        successful_result_keys = {
            (
                str(row.get("action_type") or ""),
                str(row.get("action_id") or ""),
                str(row.get("profile_id") or ""),
            )
            for row in (live_submit_summary.get("results") or [])
            if isinstance(row, dict)
            and str(row.get("status") or "") == "success"
            and str(row.get("action_id") or "")
            and str(row.get("profile_id") or "")
        }
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
                    sidecar_action_id = str(sidecar.get("action_id") or "")
                    sidecar_profile_id = str(sidecar.get("profile_id") or "")
                    action_evidence_ok = True
                    if action_type == "comment_reply":
                        action_evidence_ok = (
                            bool(str(sidecar.get("submitted_text") or "").strip())
                            and sidecar.get("comment_visible_confirmed") is True
                        )
                    elif action_type == "follow_review":
                        action_evidence_ok = sidecar.get("follow_state_confirmed") is True
                    elif action_type == "dm_review":
                        action_evidence_ok = (
                            sidecar.get("dm_entry_confirmed") is True
                            and bool(str(sidecar.get("dm_submitted_text") or "").strip())
                        )
                    if (
                        int(detail.get("size") or 0) > 0
                        and len(sha) == 64
                        and str(detail.get("sidecar_path") or "")
                        and sidecar_sha == sha
                        and str(sidecar.get("action_type") or "") == action_type
                        and sidecar_profile_id
                        and sidecar_action_id
                        and str(sidecar.get("current_url") or "")
                        and action_evidence_ok
                        and (action_type, sidecar_action_id, sidecar_profile_id) in successful_result_keys
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
        if effective_pending_external >= len(REQUIRED_CURRENT_GOAL_PENDING):
            missing_goal_pending = sorted(REQUIRED_CURRENT_GOAL_PENDING - set(str(item) for item in goal_pending))
            if missing_goal_pending:
                failures.append("goal_status_missing_current_pending")
                passed = False
        if effective_pending_external == 0 and goal_pending:
            failures.append("goal_status_has_stale_pending")
            passed = False

    if status == STATUS_PASSED and not final_acceptance_gate:
        failures.append("final_acceptance_gate_missing")
        passed = False

    if final_acceptance_gate:
        final_gate_status = str(final_acceptance_gate.get("status") or "")
        final_gate_failed_checks = as_list(final_acceptance_gate.get("failed_checks"))
        final_gate_json = report_path_status(
            summary_path,
            str(final_acceptance_gate.get("json_path") or ""),
        )
        if final_gate_status not in {STATUS_PASSED, "not_ready", STATUS_FAILED}:
            failures.append("final_acceptance_gate_unknown")
            passed = False
        if status == STATUS_PASSED and final_gate_status != STATUS_PASSED:
            failures.append("final_acceptance_gate_not_passed")
            passed = False
        if status == STATUS_PASSED and not bool(final_acceptance_gate.get("final_delivery_ready")):
            failures.append("final_acceptance_gate_not_ready")
            passed = False
        if status == STATUS_PASSED and final_gate_failed_checks:
            failures.append("final_acceptance_gate_failed_checks")
            passed = False
        if status == STATUS_PASSED and not str(final_acceptance_gate.get("json_path") or "").strip():
            failures.append("final_acceptance_gate_json_path_missing")
            passed = False
        if status == STATUS_PASSED and summary_path and str(final_acceptance_gate.get("json_path") or "").strip():
            if not final_gate_json["exists"]:
                failures.append("final_acceptance_gate_json_missing")
                passed = False
            elif int(final_gate_json.get("size") or 0) <= 0:
                failures.append("final_acceptance_gate_json_empty")
                passed = False
            elif not bool(final_gate_json.get("inside_summary_dir")):
                failures.append("final_acceptance_gate_json_outside_summary_dir")
                passed = False
    else:
        final_gate_json = report_path_status(summary_path, "")

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
            "client_surface": str(ui_startup.get("client_surface") or ""),
            "loopback_host": str(ui_startup.get("loopback_host") or ""),
            "no_browser_started": bool(ui_startup.get("no_browser_started", False)),
            "no_submit": bool(ui_startup.get("no_submit", False)),
            "json_path": str(ui_startup.get("json_path") or ""),
            "json_exists": bool(ui_startup_json.get("exists")),
            "json_inside_summary_dir": bool(ui_startup_json.get("inside_summary_dir")),
            "json_loaded": bool(ui_startup_payload_detail.get("loaded")),
            "json_error": str(ui_startup_payload_detail.get("error") or ""),
        },
        "live_preflight": {
            "status": str(live_preflight.get("status") or ""),
            "missing_preflight_action_types": list(live_preflight.get("missing_preflight_action_types") or []),
            "no_submit": bool(live_preflight.get("no_submit", True)),
            "evidence_file_detail_action_types": sorted(
                key
                for key, value in (
                    live_preflight.get("evidence_file_details")
                    if isinstance(live_preflight.get("evidence_file_details"), dict)
                    else {}
                ).items()
                if value
            ),
            "environment": {
                "status": str(preflight_environment.get("status") or ""),
                "blocking_stage": str(preflight_environment.get("blocking_stage") or ""),
                "configured_profile_ids": as_list(preflight_environment.get("configured_profile_ids")),
                "attempted_profile_ids": as_list(preflight_environment.get("attempted_profile_ids")),
                "ready_profile_ids": as_list(preflight_environment.get("ready_profile_ids")),
                "failed_profile_ids": as_list(preflight_environment.get("failed_profile_ids")),
                "classification_counts": (
                    preflight_environment.get("classification_counts")
                    if isinstance(preflight_environment.get("classification_counts"), dict)
                    else {}
                ),
                "next_required_actions": as_list(preflight_environment.get("next_required_actions")),
            },
        },
        "live_validation": {
            "status": str(live_validation.get("status") or ""),
            "no_browser_started": bool(live_validation.get("no_browser_started", True)),
            "no_submit": bool(live_validation.get("no_submit", True)),
            "missing_inputs": as_list(live_validation.get("missing_inputs")),
            "selected_profile_ids": as_list(live_validation.get("selected_profile_ids")),
        },
        "repository_cleanliness": {
            "status": repository_cleanliness_status,
            "passed": repository_cleanliness_passed,
            "forbidden_count": repository_cleanliness_forbidden_count,
            "json_path": str(repository_cleanliness.get("json_path") or ""),
            "json_exists": bool(repository_cleanliness_json.get("exists")),
            "json_size": int(repository_cleanliness_json.get("size") or 0),
            "json_inside_summary_dir": bool(repository_cleanliness_json.get("inside_summary_dir")),
        },
        "windows_package_preflight": {
            "status": windows_preflight_status,
            "ready_for_windows_build": windows_preflight_ready,
            "default_build_requires_installer": bool(windows_preflight_contract.get("default_build_requires_installer")),
            "skip_installer_is_non_final": bool(windows_preflight_contract.get("skip_installer_is_non_final")),
            "json_path": str(windows_package_preflight.get("json_path") or ""),
            "json_exists": bool(windows_preflight_json.get("exists")),
            "json_size": int(windows_preflight_json.get("size") or 0),
            "json_inside_summary_dir": bool(windows_preflight_json.get("inside_summary_dir")),
        },
        "windows_credential_manager_validation": {
            "status": credential_validation_status,
            "passed": bool(windows_credential_manager_validation.get("passed")),
            "backend": str(windows_credential_manager_validation.get("backend") or ""),
            "no_browser_started": bool(windows_credential_manager_validation.get("no_browser_started", True)),
            "no_submit": bool(windows_credential_manager_validation.get("no_submit", True)),
            "customer_data_uploaded": bool(windows_credential_manager_validation.get("customer_data_uploaded")),
            "secret_value_included": bool(windows_credential_manager_validation.get("secret_value_included")),
            "checks": credential_validation_checks,
            "json_path": str(windows_credential_manager_validation.get("json_path") or ""),
            "json_exists": bool(credential_validation_json.get("exists")),
            "json_size": int(credential_validation_json.get("size") or 0),
            "json_inside_summary_dir": bool(credential_validation_json.get("inside_summary_dir")),
            "json_loaded": bool(credential_payload_detail.get("loaded")),
            "json_error": str(credential_payload_detail.get("error") or ""),
        },
        "client_delivery": {
            "status": client_delivery_status,
            "readiness": client_delivery_readiness,
            "contract_ok": bool(client_delivery.get("contract_ok")),
            "acceptance_ready": bool(client_delivery.get("acceptance_ready")),
            "final_delivery_ready": bool(client_delivery.get("final_delivery_ready")),
            "failed_checks": client_delivery_failed_checks,
            "json_path": str(client_delivery.get("json_path") or ""),
            "json_exists": bool(client_delivery_json.get("exists")),
            "json_size": int(client_delivery_json.get("size") or 0),
            "json_inside_summary_dir": bool(client_delivery_json.get("inside_summary_dir")),
            "json_loaded": bool(client_delivery_payload_detail.get("loaded")),
            "json_error": str(client_delivery_payload_detail.get("error") or ""),
        },
        "live_readiness": {
            "status": str(live_readiness.get("status") or ""),
            "ready": bool(live_readiness.get("ready")),
            "no_browser_started": bool(live_readiness.get("no_browser_started", True)),
            "no_submit": bool(live_readiness.get("no_submit", True)),
        },
        "live_acceptance_status": {
            "status": live_acceptance_status_value,
            "final_delivery_ready": bool(live_acceptance_status.get("final_delivery_ready")),
            "ready_for_live_submit": bool(live_acceptance_status.get("ready_for_live_submit")),
            "failed_checks": live_acceptance_failed_checks,
            "local_inputs_usable": bool(live_acceptance_local_inputs.get("usable")),
            "activation_ready": bool(live_acceptance_activation.get("ready")),
            "selected_profile_ids": live_acceptance_selected_profiles,
            "missing_inputs": live_acceptance_missing_inputs,
        },
        "authorization_handoff": {
            "status": authorization_handoff_status,
            "exists": bool(authorization_handoff.get("exists")),
            "no_browser_started": bool(authorization_handoff.get("no_browser_started", True)),
            "no_submit": bool(authorization_handoff.get("no_submit", True)),
            "bundle_path": str(authorization_handoff.get("bundle_path") or ""),
            "readiness_status": str(authorization_handoff.get("readiness_status") or ""),
            "json_path": str(authorization_handoff.get("json_path") or ""),
            "json_exists": bool(authorization_handoff_json.get("exists")),
            "json_size": int(authorization_handoff_json.get("size") or 0),
            "json_inside_summary_dir": bool(authorization_handoff_json.get("inside_summary_dir")),
        },
        "live_submit": {
            "status": str(live_submit.get("status") or ""),
            "executor_mode": str(live_submit.get("executor_mode") or ""),
            "platform_validation": bool(live_submit.get("platform_validation")),
            "activation_status_loaded": bool(live_submit.get("activation_status_loaded")),
            "activation_status_source": str(live_submit.get("activation_status_source") or ""),
            "passed": bool(live_submit.get("passed")),
            "selected_actions": int(((live_submit.get("summary") or {}) if isinstance(live_submit.get("summary"), dict) else {}).get("selected_actions") or 0),
            "success": int(((live_submit.get("summary") or {}) if isinstance(live_submit.get("summary"), dict) else {}).get("success") or 0),
            "failed": int(((live_submit.get("summary") or {}) if isinstance(live_submit.get("summary"), dict) else {}).get("failed") or 0),
            "skipped": int(((live_submit.get("summary") or {}) if isinstance(live_submit.get("summary"), dict) else {}).get("skipped") or 0),
            "missing_evidence_action_types": as_list(missing_evidence_action_types),
            "missing_local_evidence_file_action_types": as_list(missing_local_evidence_file_action_types),
            "evidence_file_detail_action_types": sorted(evidence_file_details.keys()),
        },
        "goal_status": {
            "status": goal_status_value,
            "stages_passed": int(goal_summary.get("stages_passed") or 0),
            "stages_pending_external_validation": int(goal_summary.get("stages_pending_external_validation") or 0),
            "stages_failed": int(goal_summary.get("stages_failed") or 0),
            "pending_external_validation": as_list(goal_pending),
        },
        "final_acceptance_gate": {
            "status": str(final_acceptance_gate.get("status") or ""),
            "final_delivery_ready": bool(final_acceptance_gate.get("final_delivery_ready")),
            "failed_checks": as_list(final_acceptance_gate.get("failed_checks")),
            "json_path": str(final_acceptance_gate.get("json_path") or ""),
            "json_exists": bool(final_gate_json.get("exists")),
            "json_size": int(final_gate_json.get("size") or 0),
            "json_inside_summary_dir": bool(final_gate_json.get("inside_summary_dir")),
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
        result = verify_summary(
            load_summary(args.summary),
            allow_external_pending=args.allow_external_pending,
            summary_path=args.summary,
        )
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
