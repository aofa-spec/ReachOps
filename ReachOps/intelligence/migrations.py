# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


SCHEMA_MIGRATION_TABLE = "schema_migrations"
DATA_PRIVACY_AUDIT_TABLE = "data_privacy_audit"
LEAD_OUTCOMES_TABLE = "lead_outcomes"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SchemaMigration:
    version: str
    description: str
    rollback_policy: str
    apply: Callable

    @property
    def checksum(self) -> str:
        payload = f"{self.version}\n{self.description}\n{self.rollback_policy}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _ensure_migration_table(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATION_TABLE} (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            checksum TEXT NOT NULL,
            rollback_policy TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _apply_data_privacy_audit(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DATA_PRIVACY_AUDIT_TABLE} (
            id TEXT PRIMARY KEY,
            workspace_id TEXT DEFAULT '',
            operation TEXT NOT NULL,
            subject_type TEXT DEFAULT '',
            subject_id TEXT DEFAULT '',
            status TEXT DEFAULT 'recorded',
            request_id TEXT DEFAULT '',
            actor TEXT DEFAULT '',
            evidence_json TEXT DEFAULT '{{}}',
            created_at TEXT NOT NULL
        )
        """
    )


def _apply_lead_outcomes(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LEAD_OUTCOMES_TABLE} (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            workspace_id TEXT DEFAULT '',
            owner TEXT NOT NULL,
            qualification_decision TEXT NOT NULL,
            qualification_reason TEXT DEFAULT '',
            rejection_reason TEXT DEFAULT '',
            lifecycle_stage TEXT DEFAULT 'accepted',
            dedupe_key TEXT NOT NULL,
            source_path TEXT DEFAULT '',
            evidence_path TEXT DEFAULT '',
            data_scope TEXT DEFAULT 'real_customer',
            active_followup INTEGER DEFAULT 0,
            accepted_at TEXT DEFAULT '',
            reply_at TEXT DEFAULT '',
            meaningful_conversation_at TEXT DEFAULT '',
            meeting_at TEXT DEFAULT '',
            quote_at TEXT DEFAULT '',
            order_at TEXT DEFAULT '',
            revenue_amount REAL DEFAULT 0,
            revenue_currency TEXT DEFAULT 'USD',
            lost_reason TEXT DEFAULT '',
            attribution_confidence TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(dedupe_key, data_scope)
        )
        """
    )


MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(
        version="20260714_0001_data_privacy_audit",
        description="Create customer-scoped privacy operation audit records for export, deletion, legal hold, backup, and restore evidence.",
        rollback_policy="forward_only; rollback by restoring the verified pre-migration SQLite backup captured before applying this migration",
        apply=_apply_data_privacy_audit,
    ),
    SchemaMigration(
        version="20260714_0002_lead_outcomes",
        description="Create WAQO and lead-to-revenue outcome records separated from fixture and dry-run execution evidence.",
        rollback_policy="forward_only; rollback by restoring the verified pre-migration SQLite backup captured before applying this migration",
        apply=_apply_lead_outcomes,
    ),
)


def apply_schema_migrations(conn) -> list[dict]:
    _ensure_migration_table(conn)
    applied: list[dict] = []
    for migration in MIGRATIONS:
        row = conn.execute(
            f"SELECT version, checksum FROM {SCHEMA_MIGRATION_TABLE} WHERE version=?",
            (migration.version,),
        ).fetchone()
        if row:
            checksum = row["checksum"] if hasattr(row, "keys") else row[1]
            if checksum != migration.checksum:
                raise RuntimeError(f"schema migration checksum mismatch: {migration.version}")
            continue
        migration.apply(conn)
        conn.execute(
            f"""
            INSERT INTO {SCHEMA_MIGRATION_TABLE}
            (version, description, checksum, rollback_policy, applied_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (migration.version, migration.description, migration.checksum, migration.rollback_policy, _utc_now_iso()),
        )
        applied.append(
            {
                "version": migration.version,
                "description": migration.description,
                "checksum": migration.checksum,
                "rollback_policy": migration.rollback_policy,
            }
        )
    return applied
