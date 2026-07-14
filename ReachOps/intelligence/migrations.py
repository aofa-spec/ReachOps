# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


SCHEMA_MIGRATION_TABLE = "schema_migrations"
DATA_PRIVACY_AUDIT_TABLE = "data_privacy_audit"


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


MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(
        version="20260714_0001_data_privacy_audit",
        description="Create customer-scoped privacy operation audit records for export, deletion, legal hold, backup, and restore evidence.",
        rollback_policy="forward_only; rollback by restoring the verified pre-migration SQLite backup captured before applying this migration",
        apply=_apply_data_privacy_audit,
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
