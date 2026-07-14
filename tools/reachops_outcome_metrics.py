# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence.migrations import LEAD_OUTCOMES_TABLE
from ReachOps.intelligence.storage import GrowthStorage
from ReachOps.runtime_paths import RuntimePaths


SCHEMA_VERSION = "reachops.outcome_metrics.v1"
WAQO_DEFINITION_VERSION = "reachops.waqo_definition.v1"
COMMERCIAL_OUTCOME_STAGES = [
    "accepted_opportunity",
    "reply",
    "meaningful_conversation",
    "meeting",
    "quote",
    "order",
    "revenue",
    "lost",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_start_at(days: int = 7) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, int(days or 7)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_schema(db_path: Path) -> None:
    GrowthStorage(str(db_path))


def _count(conn, sql: str, args: tuple[Any, ...]) -> int:
    row = conn.execute(sql, args).fetchone()
    return int((row or [0])[0] or 0)


def _sum(conn, sql: str, args: tuple[Any, ...]) -> float:
    row = conn.execute(sql, args).fetchone()
    return float((row or [0])[0] or 0)


def build_definition() -> dict[str, Any]:
    return {
        "schema_version": WAQO_DEFINITION_VERSION,
        "name": "Weekly Accepted Qualified Opportunities",
        "abbreviation": "WAQO",
        "owner": "customer_success",
        "window": "accepted_at in [start_at, end_at]",
        "unit": "unique dedupe_key",
        "included": [
            "qualification_decision=accepted",
            "active_followup=1",
            "owner is present",
            "source_path is present",
            "evidence_path is present",
            "data_scope=real_customer",
        ],
        "excluded": [
            "fixture",
            "dry_run",
            "qualification_decision!=accepted",
            "missing owner/source/evidence",
            "inactive follow-up",
        ],
        "outcome_stages": list(COMMERCIAL_OUTCOME_STAGES),
    }


def build_report(
    *,
    db_path: str | Path | None = None,
    start_at: str = "",
    end_at: str = "",
    create_missing_db: bool = False,
) -> dict[str, Any]:
    runtime_paths = RuntimePaths.build()
    db = Path(db_path).resolve() if db_path else Path(runtime_paths.db_path)
    if create_missing_db:
        ensure_schema(db)
    start = str(start_at or "").strip() or default_start_at()
    end = str(end_at or "").strip() or utc_now_iso()
    failures: list[str] = []
    if not db.exists():
        failures.append("database_missing")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "passed": False,
            "database_path": str(db),
            "definition": build_definition(),
            "window": {"start_at": start, "end_at": end},
            "waqo": {"count": 0, "query_ready": False},
            "funnel": {},
            "failures": failures,
        }
    try:
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            }
            if LEAD_OUTCOMES_TABLE not in tables:
                failures.append("lead_outcomes_table_missing")
                return {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "passed": False,
                    "database_path": str(db),
                    "definition": build_definition(),
                    "window": {"start_at": start, "end_at": end},
                    "waqo": {"count": 0, "query_ready": False},
                    "funnel": {},
                    "failures": failures,
                }
            args = (start, end)
            total_outcomes = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE created_at>=? AND created_at<=?", args)
            real_scope = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE created_at>=? AND created_at<=? AND data_scope='real_customer'", args)
            fixture_scope = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE created_at>=? AND created_at<=? AND data_scope IN ('fixture','dry_run')", args)
            waqo_count = _count(
                conn,
                f"""
                SELECT COUNT(DISTINCT dedupe_key)
                FROM {LEAD_OUTCOMES_TABLE}
                WHERE accepted_at>=?
                  AND accepted_at<=?
                  AND data_scope='real_customer'
                  AND qualification_decision='accepted'
                  AND active_followup=1
                  AND owner!=''
                  AND source_path!=''
                  AND evidence_path!=''
                """,
                args,
            )
            rejected = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE created_at>=? AND created_at<=? AND qualification_decision='rejected'", args)
            replies = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE reply_at>=? AND reply_at<=? AND data_scope='real_customer'", args)
            conversations = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE meaningful_conversation_at>=? AND meaningful_conversation_at<=? AND data_scope='real_customer'", args)
            meetings = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE meeting_at>=? AND meeting_at<=? AND data_scope='real_customer'", args)
            quotes = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE quote_at>=? AND quote_at<=? AND data_scope='real_customer'", args)
            orders = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE order_at>=? AND order_at<=? AND data_scope='real_customer'", args)
            revenue = _sum(conn, f"SELECT SUM(revenue_amount) FROM {LEAD_OUTCOMES_TABLE} WHERE order_at>=? AND order_at<=? AND data_scope='real_customer'", args)
            lost = _count(conn, f"SELECT COUNT(*) FROM {LEAD_OUTCOMES_TABLE} WHERE created_at>=? AND created_at<=? AND data_scope='real_customer' AND lost_reason!=''", args)
            missing_rejection_reason = _count(
                conn,
                f"""
                SELECT COUNT(*)
                FROM {LEAD_OUTCOMES_TABLE}
                WHERE created_at>=?
                  AND created_at<=?
                  AND qualification_decision='rejected'
                  AND rejection_reason=''
                """,
                args,
            )
    except Exception as exc:
        failures.append("outcome_metrics_query_failed")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "passed": False,
            "database_path": str(db),
            "definition": build_definition(),
            "window": {"start_at": start, "end_at": end},
            "waqo": {"count": 0, "query_ready": False},
            "funnel": {},
            "error": str(exc),
            "failures": failures,
        }
    if missing_rejection_reason:
        failures.append("rejected_leads_missing_reason")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "database_path": str(db),
        "definition": build_definition(),
        "window": {"start_at": start, "end_at": end},
        "waqo": {
            "count": waqo_count,
            "query_ready": True,
            "owner": "customer_success",
            "excluded_fixture_or_dry_run": fixture_scope,
        },
        "funnel": {
            "total_outcomes": total_outcomes,
            "real_customer_outcomes": real_scope,
            "fixture_or_dry_run_excluded": fixture_scope,
            "accepted_opportunities": waqo_count,
            "rejected_leads": rejected,
            "replies": replies,
            "meaningful_conversations": conversations,
            "meetings": meetings,
            "quotes": quotes,
            "orders": orders,
            "revenue_amount": revenue,
            "lost": lost,
        },
        "quality": {
            "missing_rejection_reason": missing_rejection_reason,
            "fixture_data_excluded_by_default": True,
        },
        "failures": failures,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ReachOps WAQO and lead-to-revenue outcome metrics.")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--start-at", default="")
    parser.add_argument("--end-at", default="")
    parser.add_argument("--create-missing-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_report(
        db_path=args.db_path or None,
        start_at=args.start_at,
        end_at=args.end_at,
        create_missing_db=args.create_missing_db,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ReachOps outcome metrics: {payload['status']}")
        print(f"WAQO={payload.get('waqo', {}).get('count', 0)}")
        if payload.get("failures"):
            print("Failures: " + ", ".join(payload["failures"]))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
