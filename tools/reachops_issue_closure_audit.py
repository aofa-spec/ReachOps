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
    external_pending: list[str] | None = None,
) -> dict[str, Any]:
    pending = list(external_pending or [])
    return {
        "issue_number": number,
        "title": title,
        "local_status": "local_contract_passed_external_pending" if pending else "local_contract_passed",
        "local_contract_passed": bool(local_passed),
        "local_evidence": evidence,
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
            _external_pending(control_plane),
        ),
    ]
    local_contracts_passed = sum(1 for issue in issues if issue["local_contract_passed"])
    external_pending = list(dict.fromkeys(item for issue in issues for item in issue["external_pending"]))
    does_not_claim_all_issues_closed = all(
        issue["does_not_claim_issue_closed"] for issue in issues if issue["external_pending"]
    )
    passed = (
        len(issues) == 7
        and local_contracts_passed == 7
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
