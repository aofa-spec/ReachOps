# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(backup_path)) as backup:
            source.backup(backup)
    except Exception as exc:
        return {"status": "failed", "passed": False, "failures": ["backup_failed"], "error": str(exc), "backup_path": str(backup_path), "restored_path": str(restored_path)}
    try:
        shutil.copy2(backup_path, restored_path)
        original = inspect_schema(db_path)
        restored = inspect_schema(restored_path)
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
    return {
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "failures": failures,
        "backup_path": str(backup_path),
        "backup_sha256": sha256_file(backup_path) if backup_path.exists() else "",
        "restored_path": str(restored_path),
        "source_schema_hash": original.get("schema_hash"),
        "restored_schema_hash": restored.get("schema_hash"),
        "source_integrity_check": original.get("integrity_check"),
        "restored_integrity_check": restored.get("integrity_check"),
    }


def build_support_bundle_policy(base_dir: Path) -> dict[str, Any]:
    return {
        "default_redacted": True,
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
    }


def build_report(
    *,
    root: str | Path = ROOT_DIR,
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    create_missing_db: bool = False,
    verify_backup: bool = False,
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
        "retention_classes": RETENTION_CLASSES,
        "data_catalog": DATA_CATALOG,
        "support_bundle": support_bundle,
        "privacy_operations": {
            "audit_table": DATA_PRIVACY_AUDIT_TABLE,
            "workspace_export_procedure": "export campaign/customer data, redact support-only fields, include audit manifest",
            "workspace_delete_procedure": "delete or redact raw_interaction/evidence/log data unless legal hold is active",
            "legal_hold_supported": "policy_defined_not_yet_runtime_enforced",
            "audit_record_required": True,
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
