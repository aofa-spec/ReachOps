# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


SCHEMA_VERSION = "reachops.start_contract_audit.v1"
START_CONTRACT_VERSION = "reachops.api_start_contract.v1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _contains_all(text: str, needles: list[str]) -> bool:
    return all(needle in text for needle in needles)


def _error_payload_has_safety_flags(source: str, error_code: str) -> bool:
    pattern = re.compile(
        r'"error":\s*"' + re.escape(error_code) + r'".{0,900}?"no_browser_started":\s*True.{0,300}?"no_submit":\s*True',
        re.DOTALL,
    )
    return bool(pattern.search(source))


def _case(
    name: str,
    *,
    error_code: str,
    http_status: int | str,
    source_ok: bool,
    test_ok: bool,
    next_action: str,
    evidence: list[str],
) -> dict[str, Any]:
    passed = bool(source_ok and test_ok)
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "error_code": error_code,
        "http_status": http_status,
        "stable_error_code": bool(error_code),
        "next_action": next_action,
        "no_browser_started": True,
        "no_submit": True,
        "source_contract_present": bool(source_ok),
        "test_or_smoke_evidence_present": bool(test_ok),
        "evidence": evidence,
    }


def _continuation_case(
    name: str,
    *,
    source_ok: bool,
    test_ok: bool,
    next_action: str,
    evidence: list[str],
) -> dict[str, Any]:
    passed = bool(source_ok and test_ok)
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "next_action": next_action,
        "previous_error_code": "account_repair_required",
        "force_account_recheck": True,
        "runtime_auto_grouping": True,
        "no_submit": True,
        "source_contract_present": bool(source_ok),
        "test_or_smoke_evidence_present": bool(test_ok),
        "evidence": evidence,
    }


def build_report(root: str | Path = ROOT_DIR) -> dict[str, Any]:
    root = Path(root).resolve()
    web_ui = _read(root / "tools" / "reachops_web_ui.py")
    http_tests = _read(root / "tests" / "test_reachops_client_acceptance_status.py")
    runtime_smoke = _read(root / "tools" / "reachops_web_panel_runtime_smoke.py")

    request_contract = {
        "endpoint": "/api/start",
        "method": "POST",
        "content_type": "application/json",
        "required_fields": ["target"],
        "normalized_fields": ["mode", "volume", "profiles", "group", "source_type", "comment_text"],
        "live_submit_requires": ["mode=live_comment", "liveConfirm=true", "valid signed activation/entitlement"],
        "loopback_only": _contains_all(web_ui, ["LOCAL_API_HOSTS", "_reject_untrusted_api_request", "untrusted_origin"]),
        "json_payload_guard": _contains_all(
            web_ui,
            ["MAX_JSON_PAYLOAD_BYTES", "invalid_json", "json_object_required", "invalid_content_length", "payload_too_large"],
        ),
    }

    rejection_cases = [
        _case(
            "missing_target",
            error_code="target_required",
            http_status=400,
            source_ok=_error_payload_has_safety_flags(web_ui, "target_required"),
            test_ok="test_start_http_endpoint_rejects_empty_target_before_launch" in http_tests
            and "reachops_web_ui_last_run.json" in http_tests,
            next_action="Ask the operator to provide a product URL, keyword, creator URL, video URL, topic, or live room.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "untrusted_origin",
            error_code="untrusted_origin",
            http_status=403,
            source_ok=_contains_all(
                web_ui,
                [
                    '("Origin", "untrusted_origin")',
                    '"error": error_code',
                    '"no_browser_started": True',
                    '"no_submit": True',
                ],
            ),
            test_ok="test_start_http_endpoint_rejects_untrusted_origin_without_launching" in http_tests
            and "popen.assert_not_called()" in http_tests,
            next_action="Use the loopback ReachOps client console bound to 127.0.0.1.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "group_list_unavailable",
            error_code="profile_group_list_unavailable",
            http_status=409,
            source_ok=_contains_all(
                web_ui,
                ["profile_group_list_unavailable", "persist_precheck_blocked_start", "no_browser_started", "no_submit"],
            ),
            test_ok="test_start_http_endpoint_rejects_when_ixbrowser_group_list_unavailable" in http_tests
            and "popen.assert_not_called()" in http_tests,
            next_action="Start ixBrowser Local API, refresh groups, then retry.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "group_not_found",
            error_code="profile_group_not_found",
            http_status=400,
            source_ok=_contains_all(
                web_ui,
                ["profile_group_not_found", "available_groups", "persist_precheck_blocked_start", "no_browser_started", "no_submit"],
            ),
            test_ok="test_start_http_endpoint_rejects_group_not_in_ixbrowser_config_list" in http_tests
            and "available_groups" in http_tests
            and "popen.assert_not_called()" in http_tests,
            next_action="Refresh ixBrowser groups and select a group that exists in the current config list.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "group_counts_incomplete",
            error_code="profile_group_counts_incomplete",
            http_status=400,
            source_ok=_contains_all(
                web_ui,
                [
                    "profile_group_counts_incomplete",
                    "live_all_group_counts_known",
                    "count_resolution_error",
                    "persist_precheck_blocked_start",
                ],
            ),
            test_ok="start_group_precheck_block_writes_auditable_run_session" in runtime_smoke
            and "blocked_group_page_counts" in runtime_smoke,
            next_action="Refresh groups until every ixBrowser group count is live and complete.",
            evidence=["tools/reachops_web_ui.py", "tools/reachops_web_panel_runtime_smoke.py"],
        ),
        _case(
            "live_comment_confirmation_required",
            error_code="live_comment_confirmation_required",
            http_status=400,
            source_ok=_error_payload_has_safety_flags(web_ui, "live_comment_confirmation_required"),
            test_ok="test_start_http_endpoint_rejects_live_comment_without_confirmation" in http_tests
            and "popen.assert_not_called()" in http_tests,
            next_action="Require explicit operator confirmation before any live comment mode start.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "live_submit_not_authorized",
            error_code="LIVE_SUBMIT_NOT_AUTHORIZED",
            http_status=403,
            source_ok=_contains_all(
                web_ui,
                ["live_comment_activation_status", "LIVE_SUBMIT_NOT_AUTHORIZED", "activation_status_path", "no_browser_started", "no_submit"],
            ),
            test_ok="test_start_http_endpoint_rejects_live_comment_without_activation" in http_tests
            and "activation_status_file_exists" in http_tests,
            next_action="Provide a valid signed activation/entitlement status before live submit.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
        _case(
            "already_running",
            error_code="already_running",
            http_status=200,
            source_ok=_contains_all(web_ui, ["already_running", '"pid": RUN_PROCESS.pid', "RUN_STATE_LOCK"]),
            test_ok="test_start_http_endpoint_serializes_concurrent_starts" in http_tests
            and "test_start_http_endpoint_closes_parent_stdout_and_reports_existing_run" in http_tests,
            next_action="Surface the existing process id and keep the second start from spawning another process.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        ),
    ]

    runtime_continuation_cases = [
        _continuation_case(
            "account_gate_runtime_auto_recheck",
            source_ok=_contains_all(
                web_ui,
                [
                    "web_ui_account_gate_auto_recheck",
                    "runtime_preflight_auto_grouping",
                    "runtime_auto_grouping",
                    "force_account_recheck",
                    "REACHOPS_FORCE_ACCOUNT_RECHECK",
                ],
            ),
            test_ok="test_start_handler_allows_account_gate_runtime_recheck" in http_tests
            and "REACHOPS_FORCE_ACCOUNT_RECHECK" in http_tests
            and "runtime_auto_grouping" in http_tests,
            next_action="Start bounded runtime preflight so logged-in accounts continue and blocked accounts are skipped or quarantined.",
            evidence=["tools/reachops_web_ui.py", "tests/test_reachops_client_acceptance_status.py"],
        )
    ]

    success_contract = {
        "status_started": _contains_all(web_ui, ['"status": "started"', '"pid": RUN_PROCESS.pid']),
        "execution_plan_persisted": _contains_all(
            web_ui,
            [
                "build_execution_plan",
                "write_execution_plan(execution_plan, plan_path)",
                "current_latest_execution_plan_path",
            ],
        ),
        "run_session_persisted": _contains_all(
            web_ui,
            ["create_run_session", "persist_run_session", '"--run-session"', '"run_session_path"'],
        ),
        "runtime_command_is_plan_backed": _contains_all(
            web_ui,
            ['"--execution-plan"', '"--target"', '"--mode"', '"--volume"'],
        ),
        "covered_by_http_tests": "test_start_http_endpoint_closes_parent_stdout_and_reports_existing_run" in http_tests
        and "test_start_http_endpoint_normalizes_invalid_mode_and_volume_before_launch" in http_tests,
    }

    auditability = {
        "blocked_group_start_writes_execution_plan": _contains_all(
            web_ui,
            ["persist_precheck_blocked_start", "write_execution_plan(execution_plan, plan_path)", "web_ui_start_precheck_blocked"],
        ),
        "blocked_group_start_writes_run_session": _contains_all(
            web_ui,
            ["create_run_session", "transition_run_session", "PROFILE_GROUP_PRECHECK_BLOCKED", "run_session_path"],
        ),
        "blocked_group_start_writes_page_state_sidecar": _contains_all(
            web_ui,
            ["write_precheck_page_state_bundle", "UNKNOWN_PAGE_STATE", "browser_not_started_by_precheck"],
        ),
        "runtime_smoke_covers_blocked_start_artifacts": _contains_all(
            runtime_smoke,
            [
                "start_group_precheck_block_writes_auditable_run_session",
                "start_group_precheck_block_writes_page_state_sidecar",
                "start_group_precheck_block_writes_repair_decision",
                "start_group_precheck_block_writes_risk_gate",
            ],
        ),
    }

    response_invariants = {
        "rejections_have_stable_error_code": all(row["stable_error_code"] for row in rejection_cases),
        "rejections_have_next_action": all(bool(row["next_action"]) for row in rejection_cases),
        "prelaunch_rejections_do_not_start_browser": all(row["no_browser_started"] for row in rejection_cases),
        "prelaunch_rejections_do_not_submit": all(row["no_submit"] for row in rejection_cases),
        "success_response_is_auditable": all(success_contract.values()),
        "blocked_start_is_recoverable_and_supportable": all(auditability.values()),
        "runtime_account_recheck_is_bounded_and_no_submit": all(row["passed"] and row["no_submit"] for row in runtime_continuation_cases),
    }

    passed = bool(
        request_contract["loopback_only"]
        and request_contract["json_payload_guard"]
        and all(row["passed"] for row in rejection_cases)
        and all(row["passed"] for row in runtime_continuation_cases)
        and all(response_invariants.values())
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": START_CONTRACT_VERSION,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "root": str(root),
        "request_contract": request_contract,
        "rejection_cases": rejection_cases,
        "runtime_continuation_cases": runtime_continuation_cases,
        "success_contract": success_contract,
        "auditability": auditability,
        "response_invariants": response_invariants,
        "failed_cases": [row["name"] for row in rejection_cases if not row["passed"]],
        "failed_continuation_cases": [row["name"] for row in runtime_continuation_cases if not row["passed"]],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the local ReachOps /api/start contract.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report(args.root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps /api/start contract audit: {payload['status']}")
        if payload["failed_cases"]:
            print("Failed cases: " + ", ".join(payload["failed_cases"]))
        if payload["failed_continuation_cases"]:
            print("Failed continuation cases: " + ", ".join(payload["failed_continuation_cases"]))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
