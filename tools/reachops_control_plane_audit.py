# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


SCHEMA_VERSION = "reachops.control_plane_audit.v1"
STATUS_WITH_EXTERNAL_CONTROL_PLANE_PENDING = "passed_with_external_control_plane_pending"

EXTERNAL_CONTROL_PLANE_PENDING = [
    "organization_workspace_member_role_seat_service",
    "server_side_rbac_enforcement_and_audit",
    "customer_plan_state_trials_limits_and_usage_metering",
    "multi_workspace_cloud_control_plane",
    "non_tiktok_connector_contract_implementation",
    "web_ui_http_api_service_connector_module_split",
    "customer_scoped_product_telemetry_and_crash_reporting",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def has_all(text: str, tokens: list[str]) -> bool:
    return all(token in text for token in tokens)


def has_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def build_report(root_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(root_dir or ROOT_DIR)
    execution_plan = read_text(root / "ReachOps" / "execution_plan.py")
    run_session = read_text(root / "ReachOps" / "run_session.py")
    collector_base = read_text(root / "ReachOps" / "collectors" / "base.py")
    collector_runtime = read_text(root / "ReachOps" / "collectors" / "collector_runtime.py")
    action_router = read_text(root / "ReachOps" / "workbench" / "action_router.py")
    tiktok_executor = read_text(root / "ReachOps" / "workbench" / "tiktok_action_executor.py")
    live_preflight = read_text(root / "tools" / "reachops_live_preflight.py")
    outcome_metrics = read_text(root / "tools" / "reachops_outcome_metrics.py")
    data_governance = read_text(root / "tools" / "reachops_data_governance.py")
    migrations = read_text(root / "ReachOps" / "intelligence" / "migrations.py")
    authorization_gate = read_text(root / "ReachOps" / "workbench" / "authorization_gate.py")
    security_audit = read_text(root / "tools" / "reachops_security_supply_chain_audit.py")
    web_ui = read_text(root / "tools" / "reachops_web_ui.py")
    runtime_smoke = read_text(root / "tools" / "reachops_web_panel_runtime_smoke.py")
    docs = "\n".join(
        read_text(path)
        for path in [
            root / "README.md",
            root / "ReachOps" / "README.md",
            root / "ReachOps" / "docs" / "REACHOPS_PRODUCT_COMMERCIAL_AUDIT_2026-07-13.md",
            root / "ReachOps" / "docs" / "REACHOPS_COMMERCIAL_AUDIT_ACTION_INDEX_2026-07-13.md",
        ]
    )
    combined = "\n".join(
        [
            execution_plan,
            run_session,
            collector_base,
            collector_runtime,
            action_router,
            tiktok_executor,
            live_preflight,
            outcome_metrics,
            data_governance,
            migrations,
            authorization_gate,
            security_audit,
            web_ui,
            runtime_smoke,
            docs,
        ]
    )

    local_checks = {
        "local_control_surface_is_plan_and_session_bound": has_all(
            execution_plan + run_session + runtime_smoke,
            [
                "reachops.execution_plan.v1",
                "reachops.execution_plan_runtime_contract.v1",
                "reachops.execution_runtime_contract.v1",
                "run_session_required",
                "checkpoint_required",
                "no_ai_token_during_execution",
                "start_writes_and_passes_execution_plan",
                "start_creates_and_passes_run_session",
            ],
        ),
        "connector_contract_exists_for_collection_with_evidence": has_all(
            collector_base + collector_runtime,
            [
                "CollectorAdapter",
                "CollectorEvidence",
                "CollectorRuntime",
                "collect_with_fallback",
                "fallback_on_empty",
                "adapter_name",
                "screenshot_path",
            ],
        ),
        "action_executor_contract_separates_fixture_from_tiktok": has_all(
            action_router + tiktok_executor + live_preflight,
            [
                "PlatformActionExecutor",
                "FixtureActionExecutor",
                "TikTokSeleniumActionExecutor",
                "allow_live_submit",
                "live_preflight_only",
                "preflight_only",
                "no_submit",
            ],
        ),
        "outcome_ingestion_has_csv_and_webhook_boundaries": has_all(
            outcome_metrics,
            [
                "import_outcomes_csv",
                "import_outcomes_webhook_payload",
                "workspace_id",
                "owner",
                "data_scope",
                "real_customer",
                "fixture_data_excluded_by_default",
            ],
        ),
        "workspace_scoped_data_and_privacy_audit_exist": has_all(
            data_governance + migrations,
            [
                "workspace_id",
                "DATA_PRIVACY_AUDIT_TABLE",
                "workspace_export_procedure",
                "workspace_delete_procedure",
                "legal_hold",
                "privacy_operations",
            ],
        ),
        "packaged_entitlement_enforces_remote_disable": has_all(
            authorization_gate + security_audit,
            [
                "entitlement_signature",
                "LIVE_SUBMIT_FEATURE_DISABLED",
                "emergency_disabled_features",
                "device_registration",
                "max_concurrent_devices",
                "revocation_sla_hours",
            ],
        ),
        "support_bundle_policy_is_redacted_by_default": has_all(
            data_governance,
            [
                "SUPPORT_BUNDLE_EXCLUDE_PATTERNS",
                "build_support_bundle_policy",
                "default_redacted",
                "redacted_fields",
                "excluded_file_fields",
            ],
        ),
        "monolith_refactor_boundary_declared": has_all(
            docs,
            [
                "Workspace/RBAC/seat/entitlement",
                "连接器契约",
                "拆分 Web 单体",
            ],
        )
        or has_all(
            docs,
            [
                "organization / workspace / user / role / seat",
                "Product telemetry / Crash reporting / Support bundle",
                "Add connector contracts and contract tests",
            ],
        ),
    }
    local_checks["current_code_does_not_claim_cloud_control_plane"] = not has_any(
        combined,
        [
            "reachops.cloud_control_plane.v1",
            "server_side_rbac_enforced=true",
            "non_tiktok_connector_ga=true",
        ],
    )
    passed = all(local_checks.values())
    web_ui_lines = len(web_ui.splitlines())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_WITH_EXTERNAL_CONTROL_PLANE_PENDING if passed else "failed",
        "passed": passed,
        "local_checks": local_checks,
        "connector_boundary": {
            "collection_contract": "CollectorAdapter",
            "action_contract": "PlatformActionExecutor",
            "fixture_executor_available": local_checks["action_executor_contract_separates_fixture_from_tiktok"],
            "tiktok_browser_connector_is_replaceable_boundary": local_checks["connector_contract_exists_for_collection_with_evidence"],
            "non_tiktok_connector_pending": True,
        },
        "control_plane_boundary": {
            "workspace_data_fields_present": local_checks["workspace_scoped_data_and_privacy_audit_exist"],
            "packaged_entitlement_present": local_checks["packaged_entitlement_enforces_remote_disable"],
            "server_side_rbac_pending": True,
            "seat_plan_metering_pending": True,
            "multi_workspace_cloud_pending": True,
        },
        "module_boundary": {
            "web_ui_lines": web_ui_lines,
            "monolith_split_pending": web_ui_lines > 3000,
            "process_control_is_smoke_tested": local_checks["local_control_surface_is_plan_and_session_bound"],
        },
        "external_control_plane_pending": EXTERNAL_CONTROL_PLANE_PENDING,
        "does_not_claim_server_side_rbac": True,
        "does_not_claim_non_tiktok_connector_ga": True,
        "does_not_claim_web_ui_module_split_complete": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ReachOps commercial control-plane and connector boundaries.")
    parser.add_argument("--root-dir", default=str(ROOT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.root_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
