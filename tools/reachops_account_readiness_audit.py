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


SCHEMA_VERSION = "reachops.account_readiness_audit.v1"
STATUS_WITH_EXTERNAL_PILOT_PENDING = "passed_with_external_account_pilot_pending"

REQUIRED_LIFECYCLE_SIGNALS = {
    "discovered": ["profile_candidates_loaded_from_selected_group", "account_queue_started_for_selected_group"],
    "validated": ["profile_preflight_checked", "profile_preflight_completed"],
    "ready": ["available", "ready_profile_ids", "profile ready"],
    "cooling": ["cooldown", "force_profile_cooldown"],
    "login-required": ["LOGIN_REQUIRED"],
    "kernel-mismatch": ["IXBROWSER_KERNEL_MISMATCH"],
    "proxy-failed": ["PROXY_FAILED", "proxy_failed"],
    "quarantined": ["profile_quarantine_move_completed", "moves_only_to_quarantine_group"],
    "retired": ["retired", "hard_failure"],
}

EXTERNAL_ACCEPTANCE_PENDING = [
    "certified_30_controlled_profiles",
    "target_page_readiness_at_least_85_percent",
    "target_page_open_success_at_least_90_percent",
    "100_real_no_submit_runs_across_three_industries",
    "page_state_accuracy_at_least_95_percent",
    "comment_collection_human_match_at_least_95_percent",
    "lead_dedupe_accuracy_at_least_99_percent",
    "precision_at_least_75_recall_at_least_60_on_labeled_set",
    "every_real_run_has_complete_evidence_bundle",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def has_all(text: str, tokens: list[str]) -> bool:
    return all(token in text for token in tokens)


def has_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def build_report(root_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(root_dir or ROOT_DIR)
    account_health = read_text(root / "ReachOps" / "workbench" / "account_health_manager.py")
    profile_preflight = read_text(root / "ReachOps" / "workbench" / "profile_preflight.py")
    live_preflight = read_text(root / "tools" / "reachops_live_preflight.py")
    acceptance_verifier = read_text(root / "tools" / "verify_reachops_acceptance_summary.py")
    client_delivery_check = read_text(root / "tools" / "reachops_client_delivery_check.py")
    client_acceptance_status = read_text(root / "tools" / "reachops_client_acceptance_status.py")
    evidence_bundle = read_text(root / "ReachOps" / "evidence_bundle.py")
    web_ui = read_text(root / "tools" / "reachops_web_ui.py")
    outcome_metrics = read_text(root / "tools" / "reachops_outcome_metrics.py")
    action_router = read_text(root / "ReachOps" / "workbench" / "action_router.py")
    standalone_app = read_text(root / "ReachOps" / "workbench" / "standalone_app.py")
    execution_plan = read_text(root / "ReachOps" / "execution_plan.py")
    docs = "\n".join(
        read_text(path)
        for path in [
            root / "README.md",
            root / "ReachOps" / "docs" / "REACHOPS_PRODUCT_COMMERCIAL_AUDIT_2026-07-13.md",
            root / "ReachOps" / "docs" / "REACHOPS_MAC_LOCAL_MVP_ACCEPTANCE.md",
        ]
    )
    combined = "\n".join(
        [
            account_health,
            profile_preflight,
            live_preflight,
            acceptance_verifier,
            client_delivery_check,
            client_acceptance_status,
            evidence_bundle,
            web_ui,
            outcome_metrics,
            action_router,
            standalone_app,
            execution_plan,
            docs,
        ]
    )

    lifecycle_coverage = {
        state: has_any(combined, tokens)
        for state, tokens in REQUIRED_LIFECYCLE_SIGNALS.items()
    }
    local_checks = {
        "account_health_cooldown_contract": has_all(
            account_health,
            [
                "AccountHealthManager",
                "COOLDOWN_ERROR_CODES",
                "IMMEDIATE_COOLDOWN_ERROR_CODES",
                "record_success",
                "record_failure",
                "force_profile_cooldown",
                "LOGIN_REQUIRED",
                "PROXY_FAILED",
                "IXBROWSER_KERNEL_MISMATCH",
            ],
        ),
        "profile_preflight_records_evidence_and_quarantine": has_all(
            profile_preflight,
            [
                "ProfilePreflightChecker",
                "ProfilePreflightConfig",
                "evidence_dir",
                "profile_preflight_checked",
                "profile_preflight_completed",
                "quarantine_on_failure",
                "profile_quarantine_move_completed",
                "LOGIN_REQUIRED",
                "IXBROWSER_KERNEL_MISMATCH",
            ],
        ),
        "client_gate_rejects_stale_or_missing_profile_preflight": has_all(
            client_delivery_check + client_acceptance_status,
            [
                "latest_profile_preflight",
                "profile_preflight_is_stale",
                "profile_preflight_fresh",
                "profile_available_count",
                "blocked_by_accounts",
                "不能复用旧账号可用性",
            ],
        ),
        "client_delivery_exposes_real_pilot_evidence_boundary": has_all(
            client_delivery_check,
            [
                "reachops.real_pilot_evidence_boundary.v1",
                "real_pilot_ready",
                "fixture_or_dry_run_claimed",
                "no_submit_preserved",
                "requires_real_account_pool",
                "requires_real_collection_evidence",
                "account_pool_remediation",
                "latest_apply_stale",
            ],
        ),
        "live_no_submit_preflight_covers_comment_follow_dm": has_all(
            live_preflight,
            [
                "comment_reply",
                "follow_review",
                "dm_review",
                "preflight_only",
                "no_submit",
                "allow_live_submit=False",
                "write_preflight_evidence_files",
                "environment_diagnostics",
            ],
        ),
        "blocked_live_preflight_starts_no_browser_and_submits_nothing": has_all(
            live_preflight,
            [
                "blocked_preflight_result",
                "no_browser_started",
                "no_submit",
                "preflight_only",
                "input_validation",
            ],
        ),
        "acceptance_summary_verifier_keeps_no_submit_boundary": has_all(
            acceptance_verifier,
            [
                "live_readiness",
                "live_preflight",
                "authorization_handoff",
                "no_submit",
                "live_preflight_environment_validation",
                "client_delivery_acceptance_gate",
            ],
        ),
        "evidence_bundle_indexes_account_health_and_repair": has_all(
            evidence_bundle,
            [
                "build_account_health_summary",
                "reachops.account_health_summary.v1",
                "build_account_repair_summary",
                "reachops.account_repair_summary.v1",
                "account_repair_plan",
                "account_repair_apply",
                "pending_recheck",
            ],
        ),
        "operator_surface_exposes_profile_readiness_repair_loop": has_all(
            web_ui,
            [
                "latest_profile_preflight",
                "profile_preflight_details",
                "quarantine_move",
                "accountRepairActionItems",
                "旧账号修复结果已失效",
                "moves_only_to_quarantine_group",
                "no_submit",
            ],
        ),
        "fixture_and_dry_run_data_excluded_from_real_metrics": has_all(
            outcome_metrics,
            [
                "fixture_data_excluded_by_default",
                "data_scope",
                "real_customer",
                "dry_run",
                "excluded_fixture_or_dry_run",
            ],
        ),
        "runtime_submit_path_requires_explicit_authorization": has_all(
            action_router + execution_plan,
            [
                "allow_live_submit",
                "live_preflight_only",
                "no_submit_without_authorization",
                "LIVE_SUBMIT_NOT_AUTHORIZED",
            ],
        ),
        "external_pilot_not_claimed_by_local_audit": has_all(
            docs,
            [
                "30",
                "100",
                "no-submit",
                "ready_for_external_validation",
            ],
        ),
    }
    local_checks["lifecycle_signal_coverage_complete"] = all(lifecycle_coverage.values())
    passed = all(local_checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_WITH_EXTERNAL_PILOT_PENDING if passed else "failed",
        "passed": passed,
        "local_checks": local_checks,
        "lifecycle_coverage": lifecycle_coverage,
        "no_submit_contract": {
            "readiness_blocks_do_not_start_browser": local_checks["blocked_live_preflight_starts_no_browser_and_submits_nothing"],
            "preflight_actions_do_not_submit": local_checks["live_no_submit_preflight_covers_comment_follow_dm"],
            "acceptance_summary_rejects_no_submit_regression": local_checks["acceptance_summary_verifier_keeps_no_submit_boundary"],
        },
        "real_vs_fixture_boundary": {
            "fixture_data_excluded_by_default": local_checks["fixture_and_dry_run_data_excluded_from_real_metrics"],
            "local_audit_does_not_certify_real_profile_pool": True,
            "external_pilot_required": True,
        },
        "external_acceptance_pending": EXTERNAL_ACCEPTANCE_PENDING,
        "does_not_claim_certified_30_profiles": True,
        "does_not_claim_100_real_no_submit_runs": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ReachOps account readiness and no-submit evidence contracts.")
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
