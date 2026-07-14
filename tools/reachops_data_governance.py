# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.intelligence.migrations import DATA_PRIVACY_AUDIT_TABLE, MIGRATIONS, SCHEMA_MIGRATION_TABLE
from ReachOps.runtime_paths import RuntimePaths


SCHEMA_VERSION = "reachops.data_governance.v1"
SCHEMA_BASELINE_VERSION = "reachops.sqlite_schema_baseline.v1"
PRIVACY_OPERATION_SCHEMA_VERSION = "reachops.privacy_operations.v1"
RECOVERY_OBJECTIVE_SCHEMA_VERSION = "reachops.recovery_objectives.v1"
SUPPORT_BUNDLE_MANIFEST_SCHEMA_VERSION = "reachops.support_bundle_manifest.v1"

RECOVERY_OBJECTIVES: dict[str, Any] = {
    "schema_version": RECOVERY_OBJECTIVE_SCHEMA_VERSION,
    "rpo_minutes": 15,
    "rto_minutes": 30,
    "quarterly_exercise_required": True,
    "backup_before_migration_required": True,
    "restore_verification_required": True,
    "corruption_drill_required": True,
}

PRIVACY_OPERATION_PROCEDURES: dict[str, dict[str, Any]] = {
    "export": {
        "procedure": "export workspace/customer rows plus audit manifest; redact support-only fields by default",
        "requires_audit_record": True,
        "destructive": False,
    },
    "delete": {
        "procedure": "delete or redact raw_interaction/evidence/log data unless legal hold is active; retain direct-identifier-free aggregates",
        "requires_audit_record": True,
        "destructive": True,
    },
    "legal_hold": {
        "procedure": "record hold scope and suspend deletion for matching workspace/customer data until released by authorized actor",
        "requires_audit_record": True,
        "destructive": False,
    },
}

RETENTION_CLASSES: dict[str, dict[str, Any]] = {
    "raw_interaction": {
        "default_days": 90,
        "applies_to": ["candidate_users.comment_text", "discovered_contents.caption", "shop_contents.caption"],
        "deletion_method": "delete rows or redact field values for the workspace/customer export-delete procedure",
    },
    "evidence": {
        "default_days": 30,
        "applies_to": ["outreach_executions.evidence_path", "runtime evidence screenshots", "page-state sidecars"],
        "deletion_method": "remove files from runtime reports/evidence directories unless legal hold is active",
    },
    "operational_log": {
        "default_days": 30,
        "applies_to": ["growth_events.payload", "growth_errors.message", "runtime logs"],
        "deletion_method": "rotate and delete logs after support window",
    },
    "aggregate_metric": {
        "default_days": 730,
        "applies_to": ["collection_batches", "campaign-level counts", "non-PII funnel aggregates"],
        "deletion_method": "keep aggregate rows only when direct identifiers are absent",
    },
    "activation_secret": {
        "default_days": 0,
        "applies_to": ["config/reachops_activation_status.json", "license payloads", "device-bound entitlement tokens"],
        "deletion_method": "never include in support bundles; replace on revoke or customer delete",
    },
}

DATA_CATALOG: list[dict[str, Any]] = [
    {"table": "candidate_users", "field": "username", "classification": "pii", "purpose": "lead identity", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "candidate_users", "field": "profile_url", "classification": "pii", "purpose": "source traceability", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "candidate_users", "field": "comment_text", "classification": "customer_content", "purpose": "intent classification evidence", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "discovered_creators", "field": "username", "classification": "pii", "purpose": "creator/source identity", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "discovered_creators", "field": "profile_url", "classification": "pii", "purpose": "creator/source traceability", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "discovered_contents", "field": "video_url", "classification": "source_url", "purpose": "collection traceability", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "discovered_contents", "field": "caption", "classification": "customer_content", "purpose": "source context", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "operation_leads", "field": "reason", "classification": "derived_lead_evidence", "purpose": "qualification explanation", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "action_queue", "field": "target_username", "classification": "pii", "purpose": "authorized action target", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "action_queue", "field": "target_url", "classification": "pii", "purpose": "authorized action target", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "action_queue", "field": "suggested_text", "classification": "customer_content", "purpose": "operator-reviewed outreach copy", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "outreach_executions", "field": "target_username", "classification": "pii", "purpose": "execution audit", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "outreach_executions", "field": "evidence_path", "classification": "evidence_pointer", "purpose": "execution evidence", "retention_class": "evidence", "support_bundle": "exclude_file"},
    {"table": "outreach_executions", "field": "risk_gate_json", "classification": "audit_evidence", "purpose": "risk decision audit", "retention_class": "operational_log", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "owner", "classification": "customer_metadata", "purpose": "accepted opportunity ownership", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "dedupe_key", "classification": "derived_lead_evidence", "purpose": "WAQO uniqueness", "retention_class": "aggregate_metric", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "evidence_path", "classification": "evidence_pointer", "purpose": "accepted opportunity evidence", "retention_class": "evidence", "support_bundle": "exclude_file"},
    {"table": "lead_outcomes", "field": "revenue_amount", "classification": "commercial_outcome", "purpose": "lead-to-revenue attribution", "retention_class": "aggregate_metric", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "lost_reason", "classification": "commercial_outcome", "purpose": "outcome quality feedback", "retention_class": "raw_interaction", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "contact_policy", "classification": "customer_policy", "purpose": "consent and permitted follow-up boundary", "retention_class": "operational_log", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "outcome_ingest_source", "classification": "audit_evidence", "purpose": "CSV or webhook outcome provenance", "retention_class": "operational_log", "support_bundle": "redact"},
    {"table": "lead_outcomes", "field": "cost_amount", "classification": "commercial_outcome", "purpose": "cost per accepted opportunity reporting", "retention_class": "aggregate_metric", "support_bundle": "redact"},
    {"table": "growth_events", "field": "payload", "classification": "operational_log", "purpose": "support audit", "retention_class": "operational_log", "support_bundle": "redact"},
    {"table": "growth_errors", "field": "message", "classification": "operational_log", "purpose": "support diagnostics", "retention_class": "operational_log", "support_bundle": "redact"},
]

SUPPORT_BUNDLE_EXCLUDE_PATTERNS = [
    "config/reachops_activation_status.json",
    "config/*.json",
    "data/growth_intelligence/*.db",
    "data/growth_intelligence/*.db-*",
    "data/growth_intelligence/reports/**/action_submit_evidence/**",
    "data/growth_intelligence/reports/**/action_preflight_evidence/**",
    "data/growth_intelligence/reports/**/collection_profile_preflight_evidence/**",
    "reports/**/action_submit_evidence/**",
    "reports/**/*.png",
    "reports/**/*.jpg",
    "reports/**/*.jpeg",
    "reports/**/*.webp",
]

SUPPORT_BUNDLE_REQUIRED_DIAGNOSTICS = [
    "reports/support/diagnostics.json",
    "reports/support/delivery_package_check.json",
    "reports/support/final_acceptance_gate.json",
    "reports/support/issue_closure_payload.json",
    "reports/support/repository_cleanliness_payload.json",
    "reports/support/windows_package_preflight.json",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_support_path(base_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except Exception:
        return ""


def _support_exclude_match(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    for pattern in SUPPORT_BUNDLE_EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern):
            return pattern
    return ""


def build_support_bundle_manifest(base_dir: Path, candidate_paths: list[Path] | None = None) -> dict[str, Any]:
    base_dir = base_dir.resolve()
    if candidate_paths is None:
        candidate_paths = [
            base_dir / "config" / "reachops_activation_status.json",
            base_dir / "data" / "growth_intelligence" / "growth_intelligence.db",
            base_dir / "reports" / "acceptance" / "action_submit_evidence" / "submit.png",
            base_dir / "logs" / "reachops.log",
            *[base_dir / path for path in SUPPORT_BUNDLE_REQUIRED_DIAGNOSTICS],
        ]
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    outside_base: list[str] = []
    for raw_path in candidate_paths:
        path = Path(raw_path)
        relative_path = _relative_support_path(base_dir, path)
        if not relative_path:
            outside_base.append(str(path))
            excluded.append(
                {
                    "path": str(path),
                    "relative_path": "",
                    "reason": "outside_base_dir",
                    "matched_pattern": "",
                    "exists": path.exists(),
                }
            )
            continue
        matched_pattern = _support_exclude_match(relative_path)
        detail = {
            "path": str(path),
            "relative_path": relative_path,
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
            "sha256": sha256_file(path) if path.exists() and path.is_file() else "",
        }
        if matched_pattern:
            excluded.append({**detail, "reason": "excluded_by_policy", "matched_pattern": matched_pattern})
        else:
            included.append({**detail, "redaction_required": True})
    forbidden_included = [
        item["relative_path"]
        for item in included
        if _support_exclude_match(str(item.get("relative_path") or ""))
    ]
    return {
        "schema_version": SUPPORT_BUNDLE_MANIFEST_SCHEMA_VERSION,
        "base_dir": str(base_dir),
        "default_redacted": True,
        "redaction_required_for_included_files": True,
        "raw_database_included": any(
            str(item.get("relative_path") or "").endswith((".db", ".db-wal", ".db-shm")) for item in included
        ),
        "activation_status_included": any(
            str(item.get("relative_path") or "") == "config/reachops_activation_status.json" for item in included
        ),
        "evidence_image_included": any(
            str(item.get("relative_path") or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            for item in included
        ),
        "included_files": included,
        "excluded_files": excluded,
        "outside_base_candidates": outside_base,
        "forbidden_included": forbidden_included,
        "passed": not forbidden_included and not outside_base,
    }


def ensure_schema(db_path: Path) -> None:
    GrowthStorage(str(db_path))


def inspect_schema(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"exists": False, "tables": {}, "table_count": 0, "schema_hash": "", "integrity_check": "missing"}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            tables: dict[str, Any] = {}
            schema_parts: list[str] = []
            for row in table_rows:
                name = str(row["name"])
                columns = conn.execute(f"PRAGMA table_info({name})").fetchall()
                column_names = [str(col["name"]) for col in columns]
                tables[name] = {
                    "columns": column_names,
                    "column_count": len(column_names),
                    "row_count": int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]),
                }
                schema_parts.append(name + ":" + ",".join(column_names))
    except Exception as exc:
        return {"exists": True, "tables": {}, "table_count": 0, "schema_hash": "", "integrity_check": "error", "error": str(exc)}
    schema_hash = hashlib.sha256("\n".join(schema_parts).encode("utf-8")).hexdigest()
    return {
        "exists": True,
        "schema_version": SCHEMA_BASELINE_VERSION,
        "integrity_check": integrity,
        "tables": tables,
        "table_count": len(tables),
        "schema_hash": schema_hash,
    }


def inspect_migration_status(db_path: Path) -> dict[str, Any]:
    expected = {
        migration.version: {
            "description": migration.description,
            "checksum": migration.checksum,
            "rollback_policy": migration.rollback_policy,
        }
        for migration in MIGRATIONS
    }
    if not db_path.exists():
        return {
            "status": "failed",
            "ready": False,
            "expected_versions": list(expected),
            "applied_versions": [],
            "missing_versions": list(expected),
            "failures": ["database_missing"],
        }
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            }
            if SCHEMA_MIGRATION_TABLE not in tables:
                return {
                    "status": "failed",
                    "ready": False,
                    "expected_versions": list(expected),
                    "applied_versions": [],
                    "missing_versions": list(expected),
                    "failures": ["schema_migrations_table_missing"],
                }
            rows = conn.execute(f"SELECT * FROM {SCHEMA_MIGRATION_TABLE} ORDER BY version").fetchall()
    except Exception as exc:
        return {
            "status": "failed",
            "ready": False,
            "expected_versions": list(expected),
            "applied_versions": [],
            "missing_versions": list(expected),
            "failures": ["migration_status_error"],
            "error": str(exc),
        }
    applied = {str(row["version"]): dict(row) for row in rows}
    failures: list[str] = []
    for version, contract in expected.items():
        row = applied.get(version)
        if not row:
            failures.append(f"{version}:missing")
            continue
        if row.get("checksum") != contract["checksum"]:
            failures.append(f"{version}:checksum_mismatch")
        if not str(row.get("rollback_policy") or "").strip():
            failures.append(f"{version}:rollback_policy_missing")
    if DATA_PRIVACY_AUDIT_TABLE not in inspect_schema(db_path).get("tables", {}):
        failures.append("data_privacy_audit_table_missing")
    return {
        "status": "passed" if not failures else "failed",
        "ready": not failures,
        "expected_versions": list(expected),
        "applied_versions": list(applied),
        "missing_versions": [version for version in expected if version not in applied],
        "rollback_policies": {version: contract["rollback_policy"] for version, contract in expected.items()},
        "failures": failures,
    }


def backup_and_restore_verify(db_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / "growth_intelligence.backup.sqlite"
    restored_path = output_dir / "growth_intelligence.restored.sqlite"
    if backup_path.exists():
        backup_path.unlink()
    if restored_path.exists():
        restored_path.unlink()
    if not db_path.exists():
        return {"status": "failed", "passed": False, "failures": ["database_missing"], "backup_path": str(backup_path), "restored_path": str(restored_path)}
    try:
        backup_started = perf_counter()
        with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(backup_path)) as backup:
            source.backup(backup)
        backup_seconds = round(perf_counter() - backup_started, 6)
    except Exception as exc:
        return {"status": "failed", "passed": False, "failures": ["backup_failed"], "error": str(exc), "backup_path": str(backup_path), "restored_path": str(restored_path)}
    try:
        restore_started = perf_counter()
        shutil.copy2(backup_path, restored_path)
        original = inspect_schema(db_path)
        restored = inspect_schema(restored_path)
        restore_seconds = round(perf_counter() - restore_started, 6)
    except Exception as exc:
        return {"status": "failed", "passed": False, "failures": ["restore_failed"], "error": str(exc), "backup_path": str(backup_path), "restored_path": str(restored_path)}
    failures: list[str] = []
    if original.get("integrity_check") != "ok":
        failures.append("source_integrity_failed")
    if restored.get("integrity_check") != "ok":
        failures.append("restored_integrity_failed")
    if original.get("schema_hash") != restored.get("schema_hash"):
        failures.append("schema_hash_mismatch")
    if {
        name: table.get("row_count")
        for name, table in (original.get("tables") or {}).items()
    } != {
        name: table.get("row_count")
        for name, table in (restored.get("tables") or {}).items()
    }:
        failures.append("row_count_mismatch")
    corruption_drill = run_corruption_drill(backup_path, restored_path, output_dir)
    failures.extend(str(item) for item in corruption_drill.get("failures") or [])
    rpo_met = backup_seconds <= float(RECOVERY_OBJECTIVES["rpo_minutes"]) * 60
    rto_met = restore_seconds <= float(RECOVERY_OBJECTIVES["rto_minutes"]) * 60
    if not rpo_met:
        failures.append("rpo_not_met")
    if not rto_met:
        failures.append("rto_not_met")
    return {
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "failures": failures,
        "backup_path": str(backup_path),
        "backup_sha256": sha256_file(backup_path) if backup_path.exists() else "",
        "restored_path": str(restored_path),
        "backup_seconds": backup_seconds,
        "restore_seconds": restore_seconds,
        "rpo_met": rpo_met,
        "rto_met": rto_met,
        "recovery_objectives": RECOVERY_OBJECTIVES,
        "corruption_drill": corruption_drill,
        "source_schema_hash": original.get("schema_hash"),
        "restored_schema_hash": restored.get("schema_hash"),
        "source_integrity_check": original.get("integrity_check"),
        "restored_integrity_check": restored.get("integrity_check"),
    }


def run_corruption_drill(backup_path: Path, restored_path: Path, output_dir: Path) -> dict[str, Any]:
    corrupt_path = output_dir / "growth_intelligence.corrupt.sqlite"
    if corrupt_path.exists():
        corrupt_path.unlink()
    failures: list[str] = []
    try:
        shutil.copy2(backup_path, corrupt_path)
        with corrupt_path.open("r+b") as fh:
            fh.write(b"not sqlite")
        corrupt_schema = inspect_schema(corrupt_path)
        restored_schema = inspect_schema(restored_path)
    except Exception as exc:
        return {
            "status": "failed",
            "passed": False,
            "failures": ["corruption_drill_failed"],
            "error": str(exc),
            "corrupt_path": str(corrupt_path),
        }
    if corrupt_schema.get("integrity_check") not in {"error", "missing"}:
        failures.append("corruption_not_detected")
    if restored_schema.get("integrity_check") != "ok":
        failures.append("restored_database_not_usable_after_corruption_drill")
    return {
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "failures": failures,
        "corrupt_path": str(corrupt_path),
        "corrupt_integrity_check": corrupt_schema.get("integrity_check"),
        "restored_integrity_check": restored_schema.get("integrity_check"),
        "recovery_source": str(restored_path),
    }


def verify_privacy_operation_audit(db_path: Path, *, workspace_id: str = "workspace-audit") -> dict[str, Any]:
    failures: list[str] = []
    inserted: list[str] = []
    if not db_path.exists():
        return {
            "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
            "status": "failed",
            "passed": False,
            "failures": ["database_missing"],
            "procedures": PRIVACY_OPERATION_PROCEDURES,
        }
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            for operation, procedure in PRIVACY_OPERATION_PROCEDURES.items():
                audit_id = f"privacy-{operation}-{workspace_id}"
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {DATA_PRIVACY_AUDIT_TABLE}
                    (id, workspace_id, operation, subject_type, subject_id, status, request_id, actor, evidence_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        workspace_id,
                        operation,
                        "workspace",
                        workspace_id,
                        "dry_run_verified",
                        f"req-{operation}-{workspace_id}",
                        "data_governance_audit",
                        json.dumps(
                            {
                                "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
                                "procedure": procedure["procedure"],
                                "destructive_action_performed": False,
                                "support_bundle_redacted_by_default": True,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        utc_now_iso(),
                    ),
                )
                inserted.append(audit_id)
            rows = conn.execute(
                f"SELECT operation, status, evidence_json FROM {DATA_PRIVACY_AUDIT_TABLE} WHERE workspace_id=?",
                (workspace_id,),
            ).fetchall()
    except Exception as exc:
        return {
            "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
            "status": "failed",
            "passed": False,
            "failures": ["privacy_operation_audit_failed"],
            "error": str(exc),
            "procedures": PRIVACY_OPERATION_PROCEDURES,
        }
    observed = {str(row["operation"]): dict(row) for row in rows}
    for operation in PRIVACY_OPERATION_PROCEDURES:
        if operation not in observed:
            failures.append(f"{operation}_audit_missing")
            continue
        if observed[operation].get("status") != "dry_run_verified":
            failures.append(f"{operation}_status_invalid")
    return {
        "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "failures": failures,
        "workspace_id": workspace_id,
        "procedures": PRIVACY_OPERATION_PROCEDURES,
        "inserted_audit_ids": inserted,
        "observed_operations": sorted(observed),
        "audit_table": DATA_PRIVACY_AUDIT_TABLE,
    }


def build_support_bundle_policy(base_dir: Path) -> dict[str, Any]:
    dry_run_manifest = build_support_bundle_manifest(base_dir)
    included_paths = {str(item.get("relative_path") or "") for item in dry_run_manifest.get("included_files") or []}
    return {
        "default_redacted": True,
        "manifest_schema_version": SUPPORT_BUNDLE_MANIFEST_SCHEMA_VERSION,
        "manifest_required": True,
        "base_dir": str(base_dir),
        "exclude_patterns": list(SUPPORT_BUNDLE_EXCLUDE_PATTERNS),
        "redacted_fields": [
            f"{item['table']}.{item['field']}"
            for item in DATA_CATALOG
            if item.get("support_bundle") == "redact"
        ],
        "excluded_file_fields": [
            f"{item['table']}.{item['field']}"
            for item in DATA_CATALOG
            if item.get("support_bundle") == "exclude_file"
        ],
        "forbidden_by_default": [
            "activation status files",
            "SQLite database files",
            "screenshots and evidence images",
            "proxy credentials",
            "account credentials",
        ],
        "required_diagnostics": list(SUPPORT_BUNDLE_REQUIRED_DIAGNOSTICS),
        "diagnostic_manifest_complete": all(path in included_paths for path in SUPPORT_BUNDLE_REQUIRED_DIAGNOSTICS),
        "dry_run_manifest": dry_run_manifest,
        "dry_run_manifest_passed": bool(dry_run_manifest.get("passed")),
    }


def build_report(
    *,
    root: str | Path = ROOT_DIR,
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    create_missing_db: bool = False,
    verify_backup: bool = False,
    verify_privacy_ops: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    runtime_paths = RuntimePaths.build()
    db = Path(db_path).resolve() if db_path else Path(runtime_paths.db_path)
    if create_missing_db:
        ensure_schema(db)
    out = Path(output_dir).resolve() if output_dir else root / "reports" / "reachops_data_governance"
    schema = inspect_schema(db)
    failures: list[str] = []
    if not schema.get("exists"):
        failures.append("database_missing")
    elif schema.get("integrity_check") != "ok":
        failures.append("database_integrity_failed")
    if not DATA_CATALOG:
        failures.append("data_catalog_missing")
    if not RETENTION_CLASSES:
        failures.append("retention_policy_missing")
    migrations = inspect_migration_status(db)
    failures.extend(str(item) for item in migrations.get("failures") or [])
    support_bundle = build_support_bundle_policy(Path(runtime_paths.base_dir))
    backup = {"status": "not_run", "passed": False, "failures": ["backup_restore_not_run"]}
    if verify_backup:
        backup = backup_and_restore_verify(db, out)
        failures.extend(str(item) for item in backup.get("failures") or [])
    privacy_operation_audit = {
        "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
        "status": "not_run",
        "passed": False,
        "failures": ["privacy_operation_audit_not_run"],
        "procedures": PRIVACY_OPERATION_PROCEDURES,
    }
    if verify_privacy_ops:
        privacy_operation_audit = verify_privacy_operation_audit(db)
        failures.extend(str(item) for item in privacy_operation_audit.get("failures") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "root": str(root),
        "database": {
            "path": str(db),
            "schema": schema,
            "migration_policy": {
                "current_mode": "versioned_forward_migrations_with_documented_rollback",
                "target_mode": "versioned_forward_migrations_with_documented_rollback",
                "final_delivery_ready": bool(migrations.get("ready")),
                "schema_migration_table": SCHEMA_MIGRATION_TABLE,
                "expected_versions": migrations.get("expected_versions", []),
                "applied_versions": migrations.get("applied_versions", []),
                "rollback_policies": migrations.get("rollback_policies", {}),
            },
            "migrations": migrations,
        },
        "backup_restore": backup,
        "recovery_objectives": RECOVERY_OBJECTIVES,
        "retention_classes": RETENTION_CLASSES,
        "data_catalog": DATA_CATALOG,
        "support_bundle": support_bundle,
        "privacy_operations": {
            "schema_version": PRIVACY_OPERATION_SCHEMA_VERSION,
            "audit_table": DATA_PRIVACY_AUDIT_TABLE,
            "workspace_export_procedure": PRIVACY_OPERATION_PROCEDURES["export"]["procedure"],
            "workspace_delete_procedure": PRIVACY_OPERATION_PROCEDURES["delete"]["procedure"],
            "legal_hold_procedure": PRIVACY_OPERATION_PROCEDURES["legal_hold"]["procedure"],
            "legal_hold_supported": "audit_enforced_dry_run_before_runtime_deletion",
            "audit_record_required": True,
            "audit": privacy_operation_audit,
        },
        "failures": list(dict.fromkeys(failures)),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ReachOps data governance baseline.")
    parser.add_argument("--root", default=str(ROOT_DIR))
    parser.add_argument("--db-path", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--create-missing-db", action="store_true", help="Create the database if missing and apply idempotent schema migrations.")
    parser.add_argument("--verify-backup", action="store_true")
    parser.add_argument("--verify-privacy-ops", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = args.output_dir or tmp
        payload = build_report(
            root=args.root,
            db_path=args.db_path or None,
            output_dir=output_dir,
            create_missing_db=args.create_missing_db,
            verify_backup=args.verify_backup,
            verify_privacy_ops=args.verify_privacy_ops,
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps data governance baseline: {payload['status']}")
        if payload["failures"]:
            print("Failures: " + ", ".join(payload["failures"]))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
