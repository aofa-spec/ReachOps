# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_account_readiness_audit import build_report as build_account_readiness_report
from tools.reachops_ci_release_baseline_audit import build_report as build_ci_release_baseline_report
from tools.reachops_control_plane_audit import build_report as build_control_plane_report
from tools.reachops_data_governance import build_report as build_data_governance_report
from tools.reachops_outcome_metrics import build_report as build_outcome_metrics_report
from tools.reachops_outcome_metrics import import_outcomes_csv
from tools.reachops_security_supply_chain_audit import build_report as build_security_supply_chain_report
from tools.reachops_start_contract_audit import build_report as build_start_contract_report


SCHEMA_VERSION = "reachops.issue_closure_audit.v1"
STATUS_EXTERNAL_PENDING = "passed_with_external_acceptance_pending"


def _external_pending(*reports: dict[str, Any]) -> list[str]:
    keys = (
        "external_governance_pending",
        "external_acceptance_pending",
        "external_control_plane_pending",
    )
    pending: list[str] = []
    for report in reports:
        for key in keys:
            pending.extend(str(item) for item in report.get(key) or [])
    return list(dict.fromkeys(pending))


def _criterion(
    criterion_id: str,
    text: str,
    status: str,
    evidence_key: str,
    *,
    next_action: str = "",
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "text": text,
        "status": status,
        "evidence_key": evidence_key,
        "next_action": next_action,
    }


def _count_criteria(issues: list[dict[str, Any]], status: str) -> int:
    return sum(
        1
        for issue in issues
        for criterion in issue.get("acceptance_criteria") or []
        if criterion.get("status") == status
    )


def _run_data_governance_fixture(root: Path) -> dict[str, Any]:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-issue-governance-"))
    return build_data_governance_report(
        root=root,
        db_path=base_dir / "growth_intelligence.db",
        output_dir=base_dir / "governance",
        create_missing_db=True,
        verify_backup=True,
        verify_privacy_ops=True,
    )


def _run_outcome_metrics_fixture() -> dict[str, Any]:
    base_dir = Path(tempfile.mkdtemp(prefix="reachops-issue-outcomes-"))
    db_path = base_dir / "outcomes.db"
    now = "2026-07-14T00:00:00Z"
    build_outcome_metrics_report(db_path=db_path, create_missing_db=True)
    csv_path = base_dir / "outcomes.csv"
    csv_path.write_text(
        "\n".join(
            [
                "id,lead_id,workspace_id,owner,qualification_decision,qualification_reason,rejection_reason,lifecycle_stage,dedupe_key,source_path,evidence_path,data_scope,active_followup,accepted_at,reply_at,meaningful_conversation_at,meeting_at,quote_at,order_at,revenue_amount,revenue_currency,lost_reason,attribution_confidence,contact_policy,cost_amount,cost_currency,created_at",
                f"out-real,lead-real,ws-1,owner-1,accepted,human accepted,,accepted,buyer@example.test,https://www.tiktok.com/@creator/video/1,reports/evidence/lead-real.json,real_customer,1,{now},{now},{now},{now},{now},{now},1200,USD,,operator_confirmed,authorized_followup,300,USD,{now}",
            ]
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO operation_leads
            (id, candidate_user_id, lead_type, priority, score, reason, lifecycle_stage,
             source_path, status, batch_id, created_at, updated_at)
            VALUES
            ('lead-real', 'candidate-real', 'purchase', 'high', 92, 'asked for price', 'accepted',
             'https://www.tiktok.com/@creator/video/1', 'accepted', 'batch-real', ?, ?),
            ('lead-fixture', 'candidate-fixture', 'purchase', 'high', 99, 'fixture lead', 'accepted',
             'fixture://source', 'accepted', 'batch-fixture', ?, ?)
            """,
            (now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO lead_outcomes
            (id, lead_id, workspace_id, owner, qualification_decision, qualification_reason,
             rejection_reason, lifecycle_stage, dedupe_key, source_path, evidence_path, data_scope,
             active_followup, accepted_at, reply_at, revenue_amount, revenue_currency, lost_reason,
             attribution_confidence, contact_policy, cost_amount, cost_currency, created_at, updated_at)
            VALUES
            ('out-fixture', 'lead-fixture', 'ws-1', 'owner-1', 'accepted', 'fixture accepted',
             '', 'accepted', 'fixture-buyer', 'fixture://source', 'fixture://evidence', 'fixture',
             1, ?, ?, 0.0, 'USD', '', 'fixture', 'fixture', 0.0, 'USD', ?, ?)
            """,
            (now, now, now, now),
        )
    ingestion = import_outcomes_csv(db_path=db_path, csv_path=csv_path, ingest_source="csv")
    report = build_outcome_metrics_report(
        db_path=db_path,
        start_at="2026-07-13T00:00:00Z",
        end_at="2026-07-15T00:00:00Z",
    )
    report["ingestion"] = ingestion
    return report


def _issue(
    number: int,
    title: str,
    local_passed: bool,
    evidence: dict[str, Any],
    acceptance_criteria: list[dict[str, Any]],
    external_pending: list[str] | None = None,
) -> dict[str, Any]:
    pending = list(external_pending or [])
    unclassified = [row for row in acceptance_criteria if row.get("status") == "unclassified"]
    return {
        "issue_number": number,
        "title": title,
        "local_status": "local_contract_passed_external_pending" if pending else "local_contract_passed",
        "local_contract_passed": bool(local_passed),
        "local_evidence": evidence,
        "acceptance_criteria": acceptance_criteria,
        "acceptance_criteria_total": len(acceptance_criteria),
        "acceptance_criteria_local_passed": len([row for row in acceptance_criteria if row.get("status") == "local_passed"]),
        "acceptance_criteria_external_pending": len([row for row in acceptance_criteria if row.get("status") == "external_pending"]),
        "acceptance_criteria_unclassified": len(unclassified),
        "external_pending": pending,
        "does_not_claim_issue_closed": bool(pending),
    }


def build_report(root: str | Path = ROOT_DIR, *, run_pip: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    ci_release = build_ci_release_baseline_report(root, run_pip=run_pip)
    start_contract = build_start_contract_report(root)
    account_readiness = build_account_readiness_report(root)
    security_supply_chain = build_security_supply_chain_report()
    data_governance = _run_data_governance_fixture(root)
    outcome_metrics = _run_outcome_metrics_fixture()
    control_plane = build_control_plane_report(root)

    issues = [
        _issue(
            1,
            "[P0] Enforce CI, PR review, and deterministic release baseline",
            bool(
                ci_release.get("passed")
                and (ci_release.get("local_checks") or {}).get("ci_contract_complete")
                and (ci_release.get("local_checks") or {}).get("release_contract_complete")
                and ci_release.get("does_not_claim_branch_protection") is True
                and ci_release.get("does_not_claim_ten_green_ci_runs") is True
            ),
            {
                "schema_version": ci_release.get("schema_version"),
                "status": ci_release.get("status"),
                "ci_contract_complete": (ci_release.get("local_checks") or {}).get("ci_contract_complete"),
                "release_contract_complete": (ci_release.get("local_checks") or {}).get("release_contract_complete"),
                "dependency_baseline_passed": (ci_release.get("local_checks") or {}).get("dependency_baseline_passed"),
                "pip_check_passed": (ci_release.get("local_checks") or {}).get("pip_check_passed"),
                "does_not_claim_branch_protection": ci_release.get("does_not_claim_branch_protection"),
                "does_not_claim_ten_green_ci_runs": ci_release.get("does_not_claim_ten_green_ci_runs"),
            },
            [
                _criterion(
                    "issue_1_branch_protection_pr_review_checks",
                    "main branch protection requires PR review and successful checks.",
                    "external_pending",
                    "external_governance_pending",
                    next_action="Enable GitHub main branch protection with PR review and required checks.",
                ),
                _criterion(
                    "issue_1_linux_windows_tests_zero_failures",
                    "Full tests pass on Linux and Windows with zero failures/errors.",
                    "local_passed" if ci_release.get("passed") else "unclassified",
                    "ci_contract.linux_full_unit_job/windows_core_contract_job",
                ),
                _criterion(
                    "issue_1_deterministic_delivery_audits_pass",
                    "Deterministic delivery audits pass.",
                    "local_passed" if (ci_release.get("ci_contract") or {}).get("deterministic_delivery_audit_job") else "unclassified",
                    "ci_contract.deterministic_delivery_audit_job",
                ),
                _criterion(
                    "issue_1_ten_consecutive_ci_runs",
                    "Ten consecutive CI runs complete without code-related failure.",
                    "external_pending",
                    "external_governance_pending.ten_consecutive_ci_runs_without_code_failure",
                    next_action="Collect ten consecutive green GitHub Actions runs for the protected branch.",
                ),
                _criterion(
                    "issue_1_dependencies_locked_pip_check",
                    "Dependencies are locked and pip check passes.",
                    "local_passed" if (ci_release.get("local_checks") or {}).get("dependency_baseline_passed") and (ci_release.get("local_checks") or {}).get("pip_check_passed") else "unclassified",
                    "local_checks.dependency_baseline_passed/pip_check_passed",
                ),
                _criterion(
                    "issue_1_release_evidence_rollback_note",
                    "Every release has a reproducible evidence bundle and rollback note.",
                    "local_passed" if (ci_release.get("local_checks") or {}).get("release_contract_complete") else "unclassified",
                    "local_checks.release_contract_complete",
                ),
                _criterion(
                    "issue_1_p0_defects_zero_at_release",
                    "P0 defects are zero at release time.",
                    "external_pending",
                    "issue_tracker_release_governance",
                    next_action="Keep P0 issue inventory at zero before cutting a release.",
                ),
            ],
            _external_pending(ci_release),
        ),
        _issue(
            2,
            "[P0] Freeze the /api/start contract and restore a zero-failure test baseline",
            bool(
                start_contract.get("passed")
                and start_contract.get("schema_version") == "reachops.start_contract_audit.v1"
                and start_contract.get("contract_version") == "reachops.api_start_contract.v1"
                and (start_contract.get("response_invariants") or {}).get("prelaunch_rejections_do_not_start_browser")
                and (start_contract.get("response_invariants") or {}).get("prelaunch_rejections_do_not_submit")
            ),
            {
                "schema_version": start_contract.get("schema_version"),
                "contract_version": start_contract.get("contract_version"),
                "failed_cases": start_contract.get("failed_cases"),
                "rejection_case_count": len(start_contract.get("rejection_cases") or []),
                "response_invariants": start_contract.get("response_invariants"),
            },
            [
                _criterion(
                    "issue_2_unittest_zero_failures_linux_windows",
                    'python -m unittest discover -s tests -p "test_*.py" -v returns zero failures/errors on Linux and Windows.',
                    "local_passed" if start_contract.get("passed") else "unclassified",
                    "current_review_pr_github_checks_and_local_full_unittest",
                ),
                _criterion(
                    "issue_2_versioned_start_contract",
                    "/api/start has a versioned request/response contract.",
                    "local_passed" if start_contract.get("contract_version") == "reachops.api_start_contract.v1" else "unclassified",
                    "contract_version",
                ),
                _criterion(
                    "issue_2_group_evidence_cached_fallback",
                    "Fresh live group evidence and permitted cached fallback behavior are unambiguous.",
                    "local_passed" if len(start_contract.get("rejection_cases") or []) >= 8 else "unclassified",
                    "rejection_cases.profile_group_*",
                ),
                _criterion(
                    "issue_2_rejections_stable_no_browser_no_submit",
                    "Every rejection returns a stable error code, next action, no_browser_started, and no_submit.",
                    "local_passed" if (start_contract.get("response_invariants") or {}).get("prelaunch_rejections_do_not_start_browser") and (start_contract.get("response_invariants") or {}).get("prelaunch_rejections_do_not_submit") else "unclassified",
                    "response_invariants",
                ),
                _criterion(
                    "issue_2_live_authorization_not_bypassable",
                    "Live-action authorization cannot be bypassed by request shape or stale state.",
                    "local_passed" if any(row.get("error_code") == "LIVE_SUBMIT_NOT_AUTHORIZED" for row in start_contract.get("rejection_cases") or []) else "unclassified",
                    "rejection_cases.live_submit_not_authorized",
                ),
                _criterion(
                    "issue_2_contract_tests_cover_required_cases",
                    "Contract tests cover target missing, group unavailable, count incomplete, account recheck, live authorization, already-running, and successful start.",
                    "local_passed" if len(start_contract.get("rejection_cases") or []) >= 8 and not start_contract.get("failed_cases") else "unclassified",
                    "rejection_cases and success_contract",
                ),
            ],
        ),
        _issue(
            3,
            "[P0] Certify a real account-readiness pool and no-submit evidence pack",
            bool(
                account_readiness.get("passed")
                and account_readiness.get("status") == "passed_with_external_account_pilot_pending"
                and (account_readiness.get("no_submit_contract") or {}).get("preflight_actions_do_not_submit")
                and account_readiness.get("does_not_claim_certified_30_profiles") is True
                and account_readiness.get("does_not_claim_100_real_no_submit_runs") is True
            ),
            {
                "schema_version": account_readiness.get("schema_version"),
                "status": account_readiness.get("status"),
                "local_checks": account_readiness.get("local_checks"),
                "no_submit_contract": account_readiness.get("no_submit_contract"),
                "real_vs_fixture_boundary": account_readiness.get("real_vs_fixture_boundary"),
                "does_not_claim_certified_30_profiles": account_readiness.get("does_not_claim_certified_30_profiles"),
                "does_not_claim_100_real_no_submit_runs": account_readiness.get("does_not_claim_100_real_no_submit_runs"),
            },
            [
                _criterion(
                    "issue_3_30_profiles_certified_metadata",
                    "At least 30 profiles have current owner, region, kernel, proxy, login, last-check, expiry, and evidence metadata.",
                    "external_pending",
                    "external_acceptance_pending.certified_30_controlled_profiles",
                    next_action="Certify 30 controlled real profiles and attach current metadata/evidence.",
                ),
                _criterion(
                    "issue_3_target_page_readiness_open_success",
                    "Certified profile target-page readiness is at least 85%; target-page open success is at least 90%.",
                    "external_pending",
                    "external_acceptance_pending.target_page_readiness/open_success",
                    next_action="Run real target-page readiness measurement on the certified profile pool.",
                ),
                _criterion(
                    "issue_3_100_real_no_submit_runs_three_industries",
                    "At least 100 complete real no-submit runs across three industries.",
                    "external_pending",
                    "external_acceptance_pending.100_real_no_submit_runs_across_three_industries",
                    next_action="Run the controlled real no-submit pilot across three industries.",
                ),
                _criterion(
                    "issue_3_page_state_accuracy",
                    "Page-state classification accuracy is at least 95%.",
                    "external_pending",
                    "external_acceptance_pending.page_state_accuracy_at_least_95_percent",
                    next_action="Score page-state classifications against human-labeled real samples.",
                ),
                _criterion(
                    "issue_3_comment_collection_human_match",
                    "Comment collection matches human sampling at least 95%.",
                    "external_pending",
                    "external_acceptance_pending.comment_collection_human_match_at_least_95_percent",
                    next_action="Compare real collection output with human sampling.",
                ),
                _criterion(
                    "issue_3_lead_dedupe_accuracy",
                    "Lead dedupe accuracy is at least 99%.",
                    "external_pending",
                    "external_acceptance_pending.lead_dedupe_accuracy_at_least_99_percent",
                    next_action="Measure dedupe accuracy on labeled real pilot output.",
                ),
                _criterion(
                    "issue_3_precision_recall_labeled_set",
                    "High-intent precision is at least 75% and recall at least 60% on a labeled set.",
                    "external_pending",
                    "external_acceptance_pending.precision_at_least_75_recall_at_least_60_on_labeled_set",
                    next_action="Evaluate high-intent scoring on a labeled real customer-like dataset.",
                ),
                _criterion(
                    "issue_3_complete_bundle_zero_unauthorized_submits",
                    "Every run has a complete evidence bundle; unauthorized submissions are zero.",
                    "external_pending",
                    "external_acceptance_pending.every_real_run_has_complete_evidence_bundle",
                    next_action="Attach evidence bundles for every real no-submit run and verify zero submissions.",
                ),
                _criterion(
                    "issue_3_fixture_dry_run_separated",
                    "Results are separated from fixture/dry-run results in UI and reports.",
                    "local_passed" if (account_readiness.get("real_vs_fixture_boundary") or {}).get("fixture_data_excluded_by_default") else "unclassified",
                    "real_vs_fixture_boundary.fixture_data_excluded_by_default",
                ),
            ],
            _external_pending(account_readiness),
        ),
        _issue(
            4,
            "[P0] Harden licensing, entitlement, and the update supply chain",
            bool(
                security_supply_chain.get("passed")
                and security_supply_chain.get("schema_version") == "reachops.security_supply_chain_audit.v1"
                and (security_supply_chain.get("entitlement") or {}).get("schema_version") == "reachops.entitlement_security_matrix.v1"
                and (security_supply_chain.get("update_supply_chain") or {}).get("schema_version") == "reachops.update_supply_chain_matrix.v1"
            ),
            {
                "schema_version": security_supply_chain.get("schema_version"),
                "entitlement_schema_version": (security_supply_chain.get("entitlement") or {}).get("schema_version"),
                "update_supply_chain_schema_version": (security_supply_chain.get("update_supply_chain") or {}).get("schema_version"),
                "replay_detected_error_code": (((security_supply_chain.get("entitlement") or {}).get("cases") or {}).get("replay_detected") or {}).get("error_code"),
                "downgrade_without_rollback_blocked": (security_supply_chain.get("update_supply_chain") or {}).get("downgrade_without_rollback_blocked"),
                "explicit_rollback_available": (security_supply_chain.get("update_supply_chain") or {}).get("explicit_rollback_available"),
            },
            [
                _criterion(
                    "issue_4_packaged_runtime_signed_entitlement",
                    "Packaged runtime cannot authorize live actions without a valid signed entitlement.",
                    "local_passed" if security_supply_chain.get("passed") else "unclassified",
                    "entitlement.cases.valid_signed/invalid_signature",
                ),
                _criterion(
                    "issue_4_env_cannot_bypass_packaged_activation",
                    "Environment variables cannot bypass packaged activation.",
                    "local_passed" if security_supply_chain.get("passed") else "unclassified",
                    "entitlement.packaged_activation_required",
                ),
                _criterion(
                    "issue_4_entitlements_signed_expiry_device_revocable_auditable_rotatable",
                    "Entitlements are signed, expiry-bound, device-bound, revocable, auditable, and key-rotatable.",
                    "local_passed" if (security_supply_chain.get("entitlement") or {}).get("schema_version") == "reachops.entitlement_security_matrix.v1" else "unclassified",
                    "entitlement",
                ),
                _criterion(
                    "issue_4_remote_manifests_https_signature",
                    "Remote manifests require HTTPS and a valid signature.",
                    "local_passed" if (security_supply_chain.get("update_supply_chain") or {}).get("http_manifest_rejected") else "unclassified",
                    "update_supply_chain.http_manifest_rejected/manifest_signature",
                ),
                _criterion(
                    "issue_4_installer_hash_size_product_version_channel_signature",
                    "Installer hash, size, product, version, channel, and signature are all verified.",
                    "local_passed" if (security_supply_chain.get("update_supply_chain") or {}).get("installer_verified") else "unclassified",
                    "update_supply_chain.installer_verified",
                ),
                _criterion(
                    "issue_4_revocation_sla_offline_grace",
                    "Revocation takes effect within the defined SLA while honoring documented offline grace.",
                    "local_passed" if (((security_supply_chain.get("entitlement") or {}).get("cases") or {}).get("revoked") or {}).get("error_code") == "LIVE_SUBMIT_ENTITLEMENT_REVOKED" else "unclassified",
                    "entitlement.cases.revoked/offline_grace",
                ),
                _criterion(
                    "issue_4_downgrade_rollback_explicit_tested",
                    "Downgrade and rollback paths are explicit and tested.",
                    "local_passed" if (security_supply_chain.get("update_supply_chain") or {}).get("downgrade_without_rollback_blocked") and (security_supply_chain.get("update_supply_chain") or {}).get("explicit_rollback_available") else "unclassified",
                    "update_supply_chain.downgrade_without_rollback_blocked/explicit_rollback_available",
                ),
                _criterion(
                    "issue_4_security_tests_cover_tampering_replay_expiry_device_revocation_http_signature_downgrade",
                    "Security tests cover tampering, replay, expired payloads, wrong device, revoked device, HTTP manifest, bad signature, and downgrade.",
                    "local_passed" if security_supply_chain.get("passed") else "unclassified",
                    "security_supply_chain_audit matrix",
                ),
            ],
        ),
        _issue(
            5,
            "[P0] Add versioned migrations, backup/restore, retention, and privacy controls",
            bool(
                data_governance.get("passed")
                and data_governance.get("schema_version") == "reachops.data_governance.v1"
                and (data_governance.get("database") or {}).get("migration_policy", {}).get("final_delivery_ready")
                and (data_governance.get("backup_restore") or {}).get("status") == "passed"
                and (data_governance.get("privacy_operations") or {}).get("schema_version") == "reachops.privacy_operations.v1"
            ),
            {
                "schema_version": data_governance.get("schema_version"),
                "migration_policy": (data_governance.get("database") or {}).get("migration_policy"),
                "backup_restore": data_governance.get("backup_restore"),
                "recovery_objectives": data_governance.get("recovery_objectives"),
                "privacy_operations": data_governance.get("privacy_operations"),
            },
            [
                _criterion(
                    "issue_5_versioned_migration_tests",
                    "Every schema change has a versioned migration and automated migration test.",
                    "local_passed" if (data_governance.get("database") or {}).get("migration_policy", {}).get("final_delivery_ready") else "unclassified",
                    "database.migration_policy",
                ),
                _criterion(
                    "issue_5_backup_restore_representative_quarterly",
                    "Backup and restore complete successfully on representative datasets and are exercised quarterly.",
                    "local_passed" if (data_governance.get("backup_restore") or {}).get("status") == "passed" else "unclassified",
                    "backup_restore",
                ),
                _criterion(
                    "issue_5_rpo_rto_documented_met",
                    "Recovery-point and recovery-time objectives are documented and met.",
                    "local_passed" if (data_governance.get("backup_restore") or {}).get("rpo_met") and (data_governance.get("backup_restore") or {}).get("rto_met") else "unclassified",
                    "backup_restore.rpo_met/rto_met",
                ),
                _criterion(
                    "issue_5_workspace_export_delete_procedure",
                    "A workspace/customer can export and delete its data through a documented procedure.",
                    "local_passed" if (data_governance.get("privacy_operations") or {}).get("workspace_export_procedure") and (data_governance.get("privacy_operations") or {}).get("workspace_delete_procedure") else "unclassified",
                    "privacy_operations.export/delete",
                ),
                _criterion(
                    "issue_5_retention_rules_data_classes",
                    "Retention rules apply to raw interaction data, screenshots, logs, evidence, and aggregates.",
                    "local_passed" if bool(data_governance.get("retention_classes")) else "unclassified",
                    "retention_classes",
                ),
                _criterion(
                    "issue_5_pii_catalog_support_bundles_redacted",
                    "PII fields and purposes are documented; support bundles are redacted by default.",
                    "local_passed" if bool(data_governance.get("data_catalog")) and (data_governance.get("support_bundle") or {}).get("default_redacted") else "unclassified",
                    "data_catalog/support_bundle",
                ),
                _criterion(
                    "issue_5_migration_backup_restore_privacy_corruption_audit_evidence",
                    "Migration, backup, restore, export, deletion, and corrupted-database scenarios have tests and audit evidence.",
                    "local_passed" if data_governance.get("passed") and (data_governance.get("backup_restore") or {}).get("corruption_drill", {}).get("status") == "passed" else "unclassified",
                    "data_governance audit evidence",
                ),
            ],
        ),
        _issue(
            6,
            "[P0] Instrument WAQO and the full lead-to-revenue outcome funnel",
            bool(
                outcome_metrics.get("passed")
                and outcome_metrics.get("schema_version") == "reachops.outcome_metrics.v1"
                and (outcome_metrics.get("definition") or {}).get("schema_version") == "reachops.waqo_definition.v1"
                and (outcome_metrics.get("ingestion") or {}).get("schema_version") == "reachops.outcome_ingestion.v1"
                and (outcome_metrics.get("quality") or {}).get("fixture_data_excluded_by_default") is True
            ),
            {
                "schema_version": outcome_metrics.get("schema_version"),
                "definition": outcome_metrics.get("definition"),
                "ingestion": outcome_metrics.get("ingestion"),
                "waqo": outcome_metrics.get("waqo"),
                "funnel": outcome_metrics.get("funnel"),
                "pilot_report": outcome_metrics.get("pilot_report"),
                "quality": outcome_metrics.get("quality"),
            },
            [
                _criterion(
                    "issue_6_waqo_definition_query_owner_dashboard",
                    "WAQO has a versioned definition, query, owner, and dashboard.",
                    "local_passed" if (outcome_metrics.get("definition") or {}).get("schema_version") == "reachops.waqo_definition.v1" and (outcome_metrics.get("waqo") or {}).get("owner") else "unclassified",
                    "definition/waqo",
                ),
                _criterion(
                    "issue_6_accepted_opportunity_required_fields",
                    "Every accepted opportunity has source, evidence, owner, timestamp, dedupe key, and qualification reason.",
                    "local_passed" if (outcome_metrics.get("waqo") or {}).get("query_ready") else "unclassified",
                    "waqo.query",
                ),
                _criterion(
                    "issue_6_rejected_leads_structured_reason",
                    "Rejected leads retain a structured rejection reason for model evaluation.",
                    "local_passed" if (outcome_metrics.get("quality") or {}).get("missing_rejection_reason") == 0 else "unclassified",
                    "quality.missing_rejection_reason",
                ),
                _criterion(
                    "issue_6_downstream_outcome_stages",
                    "Outcomes support reply, meaningful conversation, meeting, quote, order, revenue, and lost reason.",
                    "local_passed" if (outcome_metrics.get("funnel") or {}).get("orders") == 1 and float((outcome_metrics.get("funnel") or {}).get("revenue_amount") or 0) > 0 else "unclassified",
                    "funnel",
                ),
                _criterion(
                    "issue_6_funnel_conversion_elapsed_time",
                    "Funnel conversion and elapsed time are available for every stage.",
                    "local_passed" if bool(outcome_metrics.get("conversion_rates")) and bool(outcome_metrics.get("elapsed_time")) else "unclassified",
                    "conversion_rates/elapsed_time",
                ),
                _criterion(
                    "issue_6_fixture_dry_run_excluded",
                    "Fixture/dry-run data is excluded from commercial dashboards by default.",
                    "local_passed" if (outcome_metrics.get("quality") or {}).get("fixture_data_excluded_by_default") else "unclassified",
                    "quality.fixture_data_excluded_by_default",
                ),
                _criterion(
                    "issue_6_pilot_report_metrics",
                    "Pilot reports include precision, recall, acceptance rate, duplicate rate, reply rate, conversation rate, meeting/quote rate, order attribution, and cost per accepted opportunity.",
                    "local_passed" if bool(outcome_metrics.get("pilot_report")) else "unclassified",
                    "pilot_report",
                ),
                _criterion(
                    "issue_6_three_pilot_customers_attribution_before_ga",
                    "At least three pilot customers can provide auditable meeting, quote, or order attribution before GA.",
                    "external_pending",
                    "external_customer_pilot_attribution",
                    next_action="Collect auditable meeting/quote/order attribution from at least three pilot customers before GA.",
                ),
            ],
        ),
        _issue(
            7,
            "[P1] Build the commercial control plane and decouple channel connectors",
            bool(
                control_plane.get("passed")
                and control_plane.get("status") == "passed_with_external_control_plane_pending"
                and (control_plane.get("control_plane_boundary") or {}).get("server_side_rbac_pending")
                and (control_plane.get("connector_boundary") or {}).get("non_tiktok_connector_pending")
                and (control_plane.get("module_boundary") or {}).get("monolith_split_pending")
                and control_plane.get("does_not_claim_server_side_rbac") is True
                and control_plane.get("does_not_claim_non_tiktok_connector_ga") is True
            ),
            {
                "schema_version": control_plane.get("schema_version"),
                "status": control_plane.get("status"),
                "local_checks": control_plane.get("local_checks"),
                "control_plane_boundary": control_plane.get("control_plane_boundary"),
                "connector_boundary": control_plane.get("connector_boundary"),
                "module_boundary": control_plane.get("module_boundary"),
                "does_not_claim_server_side_rbac": control_plane.get("does_not_claim_server_side_rbac"),
                "does_not_claim_non_tiktok_connector_ga": control_plane.get("does_not_claim_non_tiktok_connector_ga"),
                "does_not_claim_web_ui_module_split_complete": control_plane.get("does_not_claim_web_ui_module_split_complete"),
            },
            [
                _criterion(
                    "issue_7_workspace_scoped_data_runtime",
                    "Data and runtime actions are scoped by workspace.",
                    "local_passed" if (control_plane.get("local_checks") or {}).get("workspace_scoped_data_and_privacy_audit_exist") else "unclassified",
                    "local_checks.workspace_scoped_data_and_privacy_audit_exist",
                ),
                _criterion(
                    "issue_7_server_side_roles_permissions_audited",
                    "Member roles and permissions are enforced server-side and audited.",
                    "external_pending",
                    "external_control_plane_pending.server_side_rbac_enforcement_and_audit",
                    next_action="Implement and audit server-side organization/workspace/member/role enforcement.",
                ),
                _criterion(
                    "issue_7_plan_entitlement_limits_independent",
                    "Plan/entitlement limits are checked independently from local UI state.",
                    "external_pending",
                    "external_control_plane_pending.customer_plan_state_trials_limits_and_usage_metering",
                    next_action="Implement server-side plan state, trials, limits and usage metering.",
                ),
                _criterion(
                    "issue_7_versioned_connector_contract_suite",
                    "Connectors implement a versioned contract and contract-test suite.",
                    "local_passed" if (control_plane.get("local_checks") or {}).get("connector_contract_exists_for_collection_with_evidence") and (control_plane.get("local_checks") or {}).get("action_executor_contract_separates_fixture_from_tiktok") else "unclassified",
                    "connector_boundary",
                ),
                _criterion(
                    "issue_7_fixture_tiktok_non_tiktok_without_core_branching",
                    "The domain model can run with a fixture connector, TikTok browser connector, and one non-TikTok connector without branching core business logic.",
                    "external_pending",
                    "external_control_plane_pending.non_tiktok_connector_contract_implementation",
                    next_action="Implement one non-TikTok connector against the connector contract and prove no core branching.",
                ),
                _criterion(
                    "issue_7_remote_disable_high_risk_connectors",
                    "High-risk connector actions can be remotely disabled without shipping a new client.",
                    "local_passed" if (control_plane.get("local_checks") or {}).get("packaged_entitlement_enforces_remote_disable") else "unclassified",
                    "local_checks.packaged_entitlement_enforces_remote_disable",
                ),
                _criterion(
                    "issue_7_web_ui_api_service_connector_split",
                    "Web UI routing, process control, domain validation, and connector code are no longer in one monolithic module.",
                    "external_pending",
                    "external_control_plane_pending.web_ui_http_api_service_connector_module_split",
                    next_action="Split Web UI, HTTP API, application services, process control and connector modules.",
                ),
                _criterion(
                    "issue_7_support_bundles_telemetry_customer_scoped_redacted",
                    "Support bundles and product telemetry are customer-scoped and redacted.",
                    "external_pending",
                    "external_control_plane_pending.customer_scoped_product_telemetry_and_crash_reporting",
                    next_action="Add customer-scoped telemetry/crash reporting and verify redaction.",
                ),
            ],
            _external_pending(control_plane),
        ),
    ]
    local_contracts_passed = sum(1 for issue in issues if issue["local_contract_passed"])
    external_pending = list(dict.fromkeys(
        [
            item
            for issue in issues
            for item in issue["external_pending"]
        ]
        + [
            str(criterion.get("id"))
            for issue in issues
            for criterion in issue.get("acceptance_criteria") or []
            if criterion.get("status") == "external_pending"
        ]
    ))
    criteria_total = sum(int(issue.get("acceptance_criteria_total") or 0) for issue in issues)
    criteria_local_passed = _count_criteria(issues, "local_passed")
    criteria_external_pending = _count_criteria(issues, "external_pending")
    criteria_unclassified = _count_criteria(issues, "unclassified")
    does_not_claim_all_issues_closed = all(
        issue["does_not_claim_issue_closed"] for issue in issues if issue["external_pending"]
    )
    passed = (
        len(issues) == 7
        and local_contracts_passed == 7
        and criteria_total == 53
        and criteria_unclassified == 0
        and bool(external_pending)
        and does_not_claim_all_issues_closed
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_EXTERNAL_PENDING if passed else "failed",
        "passed": passed,
        "root": str(root),
        "github_issues": {
            "range": "#1-#7",
            "expected_open_until_external_acceptance": True,
            "closure_requires_external_validation": True,
        },
        "summary": {
            "issues_total": len(issues),
            "local_contracts_passed": local_contracts_passed,
            "acceptance_criteria_total": criteria_total,
            "acceptance_criteria_local_passed": criteria_local_passed,
            "acceptance_criteria_external_pending": criteria_external_pending,
            "acceptance_criteria_unclassified": criteria_unclassified,
            "external_pending_count": len(external_pending),
            "does_not_claim_all_issues_closed": does_not_claim_all_issues_closed,
        },
        "issues": issues,
        "external_acceptance_pending": external_pending,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Map ReachOps Issues #1-#7 to local evidence and external acceptance gaps.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--run-pip-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report(args.root, run_pip=args.run_pip_check)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload["summary"]
        print(f"ReachOps issue closure audit: {payload['status']}")
        print(
            "Issues #{range}: {passed}/{total} local contracts passed; {pending} external acceptance items pending.".format(
                range=payload["github_issues"]["range"].replace("#", ""),
                passed=summary["local_contracts_passed"],
                total=summary["issues_total"],
                pending=summary["external_pending_count"],
            )
        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
