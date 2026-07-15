# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.database_busy_probe.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_locked_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE IF NOT EXISTS busy_probe (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("BEGIN EXCLUSIVE")
    conn.execute("INSERT INTO busy_probe(value) VALUES ('lock-holder')")
    return conn


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_database_busy_probe.json",
    db_path: str | Path = "/tmp/reachops_database_busy_probe.sqlite3",
    busy_timeout_ms: int = 100,
) -> dict[str, Any]:
    started = time.monotonic()
    busy_timeout_ms = max(1, int(busy_timeout_ms or 100))
    db_target = Path(db_path).expanduser()
    lock_conn: sqlite3.Connection | None = None
    observed_error = ""
    observed_error_type = ""
    write_elapsed_seconds = 0.0
    busy_observed = False
    attempt = {
        "attempt": 1,
        "status": "not_run",
        "error_code": "",
        "error": "",
        "elapsed_seconds": 0.0,
    }
    try:
        lock_conn = _prepare_locked_database(db_target)
        write_started = time.monotonic()
        try:
            contender = sqlite3.connect(
                str(db_target),
                timeout=busy_timeout_ms / 1000.0,
                isolation_level=None,
            )
            try:
                contender.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
                contender.execute("INSERT INTO busy_probe(value) VALUES ('contender')")
                attempt["status"] = "unexpected_success"
            finally:
                contender.close()
        except sqlite3.OperationalError as exc:
            observed_error = str(exc)
            observed_error_type = exc.__class__.__name__
            busy_observed = "locked" in observed_error.lower() or "busy" in observed_error.lower()
            attempt.update(
                {
                    "status": "failed",
                    "error_code": "DATABASE_BUSY" if busy_observed else "SQLITE_OPERATIONAL_ERROR",
                    "error": observed_error,
                }
            )
        write_elapsed_seconds = round(max(0.0, time.monotonic() - write_started), 3)
        attempt["elapsed_seconds"] = write_elapsed_seconds
    finally:
        if lock_conn is not None:
            try:
                lock_conn.rollback()
            finally:
                lock_conn.close()

    status = "blocked_by_environment" if busy_observed else "failed"
    terminal_reason_code = "DATABASE_BUSY" if busy_observed else "DATABASE_BUSY_PROBE_FAILED"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": status,
        "terminal_state": "BLOCKED" if busy_observed else "FAILED",
        "terminal_reason_code": terminal_reason_code,
        "error_code": "DATABASE_BUSY" if busy_observed else "DATABASE_BUSY_PROBE_FAILED",
        "database_path": str(db_target),
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": True,
            "failure_code": "DATABASE_BUSY",
            "safe_no_submit": True,
            "real_sqlite_lock_observed": bool(busy_observed),
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": False,
        },
        "database_busy": {
            "lock_strategy": "sqlite_begin_exclusive",
            "write_attempt_count": 1,
            "max_write_retries": 0,
            "busy_timeout_ms": busy_timeout_ms,
            "busy_timeout_enforced": bool(busy_observed),
            "bounded_retry_policy_enforced": True,
            "real_sqlite_lock_observed": bool(busy_observed),
            "observed_error_type": observed_error_type,
            "observed_error": observed_error,
            "write_elapsed_seconds": write_elapsed_seconds,
            "attempts": [attempt],
        },
        "summary": {
            "errors": {"DATABASE_BUSY": 1} if busy_observed else {"DATABASE_BUSY_PROBE_FAILED": 1},
            "write_attempt_count": 1,
            "max_write_retries": 0,
            "busy_timeout_ms": busy_timeout_ms,
        },
        "outputs": {"json": str(Path(output).expanduser())},
        "next_action": "Keep storage writes bounded and surface DATABASE_BUSY as a structured blocked terminal state.",
        "wall_clock_seconds": round(max(0.0, time.monotonic() - started), 3),
        "bounded_exit": True,
    }
    write_report(output, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded no-submit SQLite database busy probe.")
    parser.add_argument("--output", default="/tmp/reachops_database_busy_probe.json")
    parser.add_argument("--db-path", default="/tmp/reachops_database_busy_probe.sqlite3")
    parser.add_argument("--busy-timeout-ms", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(output=args.output, db_path=args.db_path, busy_timeout_ms=args.busy_timeout_ms)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("error_code") == "DATABASE_BUSY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
