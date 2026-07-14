# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
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
OUTCOME_INGESTION_SCHEMA_VERSION = "reachops.outcome_ingestion.v1"
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
OUTCOME_IMPORT_COLUMNS = [
    "id",
    "lead_id",
    "workspace_id",
    "owner",
    "qualification_decision",
    "qualification_reason",
    "rejection_reason",
    "lifecycle_stage",
    "dedupe_key",
    "source_path",
    "evidence_path",
    "data_scope",
    "active_followup",
    "accepted_at",
    "reply_at",
    "meaningful_conversation_at",
    "meeting_at",
    "quote_at",
    "order_at",
    "revenue_amount",
    "revenue_currency",
    "lost_reason",
    "attribution_confidence",
    "contact_policy",
    "outcome_ingest_source",
    "outcome_ingested_at",
    "cost_amount",
    "cost_currency",
    "created_at",
    "updated_at",
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


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _elapsed_hours(start: str, end: str) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((end_dt - start_dt).total_seconds() / 3600, 6)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_float(value: Any) -> float:
    text = _clean_text(value)
    if not text:
        return 0.0
    return float(text)


def _clean_int(value: Any) -> int:
    text = _clean_text(value)
    if not text:
        return 0
    return 1 if text.lower() in {"1", "true", "yes", "y"} else int(float(text))


def normalize_outcome_row(row: dict[str, Any], *, ingest_source: str = "") -> dict[str, Any]:
    now = utc_now_iso()
    normalized = {column: _clean_text(row.get(column)) for column in OUTCOME_IMPORT_COLUMNS}
    normalized["id"] = normalized["id"] or f"outcome-{normalized['lead_id'] or normalized['dedupe_key']}"
    normalized["workspace_id"] = normalized["workspace_id"] or "default"
    normalized["qualification_decision"] = normalized["qualification_decision"] or "accepted"
    normalized["lifecycle_stage"] = normalized["lifecycle_stage"] or normalized["qualification_decision"]
    normalized["data_scope"] = normalized["data_scope"] or "real_customer"
    normalized["active_followup"] = _clean_int(row.get("active_followup"))
    normalized["revenue_amount"] = _clean_float(row.get("revenue_amount"))
    normalized["revenue_currency"] = normalized["revenue_currency"] or "USD"
    normalized["cost_amount"] = _clean_float(row.get("cost_amount"))
    normalized["cost_currency"] = normalized["cost_currency"] or normalized["revenue_currency"]
    normalized["outcome_ingest_source"] = normalized["outcome_ingest_source"] or ingest_source
    normalized["outcome_ingested_at"] = normalized["outcome_ingested_at"] or now
    normalized["created_at"] = normalized["created_at"] or normalized["accepted_at"] or now
    normalized["updated_at"] = now
    return normalized


def import_outcomes(
    *,
    db_path: str | Path | None,
    rows: list[dict[str, Any]],
    ingest_source: str,
    create_missing_db: bool = True,
) -> dict[str, Any]:
    runtime_paths = RuntimePaths.build()
    db = Path(db_path).resolve() if db_path else Path(runtime_paths.db_path)
    if create_missing_db:
        ensure_schema(db)
    failures: list[str] = []
    imported = 0
    skipped = 0
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        for index, raw_row in enumerate(rows, start=1):
            row = normalize_outcome_row(raw_row, ingest_source=ingest_source)
            missing = [
                name
                for name in ("id", "lead_id", "owner", "dedupe_key")
                if not str(row.get(name) or "").strip()
            ]
            if missing:
                failures.append(f"row_{index}_missing_" + "_".join(missing))
                skipped += 1
                continue
            if row["qualification_decision"] == "accepted":
                accepted_missing = [
                    name
                    for name in ("qualification_reason", "source_path", "evidence_path", "contact_policy", "accepted_at")
                    if not str(row.get(name) or "").strip()
                ]
                if accepted_missing:
                    failures.append(f"row_{index}_accepted_missing_" + "_".join(accepted_missing))
                    skipped += 1
                    continue
            if row["qualification_decision"] == "rejected" and not row["rejection_reason"]:
                failures.append(f"row_{index}_rejected_missing_rejection_reason")
                skipped += 1
                continue
            placeholders = ", ".join("?" for _ in OUTCOME_IMPORT_COLUMNS)
            updates = ", ".join(f"{column}=excluded.{column}" for column in OUTCOME_IMPORT_COLUMNS if column not in {"id", "dedupe_key", "data_scope"})
            conn.execute(
                f"""
                INSERT INTO {LEAD_OUTCOMES_TABLE}
                ({", ".join(OUTCOME_IMPORT_COLUMNS)})
                VALUES ({placeholders})
                ON CONFLICT(dedupe_key, data_scope) DO UPDATE SET {updates}
                """,
                tuple(row[column] for column in OUTCOME_IMPORT_COLUMNS),
            )
            imported += 1
    return {
        "schema_version": OUTCOME_INGESTION_SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "passed": not failures,
        "database_path": str(db),
        "ingest_source": ingest_source,
        "imported": imported,
        "skipped": skipped,
        "failures": failures,
    }


def import_outcomes_csv(
    *,
    db_path: str | Path,
    csv_path: str | Path,
    ingest_source: str = "csv",
    create_missing_db: bool = True,
) -> dict[str, Any]:
    path = Path(csv_path).resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = import_outcomes(
        db_path=db_path,
        rows=rows,
        ingest_source=ingest_source,
        create_missing_db=create_missing_db,
    )
    result["csv_path"] = str(path)
    result["rows_read"] = len(rows)
    return result


def import_outcomes_webhook_payload(
    *,
    db_path: str | Path,
    payload: dict[str, Any],
    ingest_source: str = "webhook",
    create_missing_db: bool = True,
) -> dict[str, Any]:
    raw_rows = payload.get("outcomes") if isinstance(payload.get("outcomes"), list) else [payload]
    return import_outcomes(
        db_path=db_path,
        rows=[dict(row) for row in raw_rows if isinstance(row, dict)],
        ingest_source=ingest_source,
        create_missing_db=create_missing_db,
    )


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
            "contact_policy is present",
            "data_scope=real_customer",
        ],
        "excluded": [
            "fixture",
            "dry_run",
            "qualification_decision!=accepted",
            "missing owner/source/evidence",
            "missing contact policy",
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
                  AND contact_policy!=''
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
            accepted_rows = conn.execute(
                f"""
                SELECT accepted_at, reply_at, meaningful_conversation_at, meeting_at, quote_at, order_at
                FROM {LEAD_OUTCOMES_TABLE}
                WHERE accepted_at>=?
                  AND accepted_at<=?
                  AND data_scope='real_customer'
                  AND qualification_decision='accepted'
                  AND active_followup=1
                  AND owner!=''
                  AND source_path!=''
                  AND evidence_path!=''
                  AND contact_policy!=''
                """,
                args,
            ).fetchall()
            candidate_signals = _count(conn, "SELECT COUNT(*) FROM operation_leads WHERE created_at>=? AND created_at<=?", args)
            duplicate_rows = 0
            accepted_missing_contact_policy = _count(
                conn,
                f"""
                SELECT COUNT(*)
                FROM {LEAD_OUTCOMES_TABLE}
                WHERE accepted_at>=?
                  AND accepted_at<=?
                  AND data_scope='real_customer'
                  AND qualification_decision='accepted'
                  AND active_followup=1
                  AND owner!=''
                  AND source_path!=''
                  AND evidence_path!=''
                  AND contact_policy=''
                """,
                args,
            )
            total_cost = _sum(conn, f"SELECT SUM(cost_amount) FROM {LEAD_OUTCOMES_TABLE} WHERE accepted_at>=? AND accepted_at<=? AND data_scope='real_customer'", args)
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
    if accepted_missing_contact_policy:
        failures.append("accepted_opportunities_missing_contact_policy")
    elapsed: dict[str, dict[str, float | int | None]] = {}
    for stage in ("reply", "meaningful_conversation", "meeting", "quote", "order"):
        values = [
            hours
            for item in accepted_rows
            for hours in [_elapsed_hours(str(item["accepted_at"] or ""), str(item[f"{stage}_at"] or ""))]
            if hours is not None
        ]
        elapsed[stage] = {
            "count": len(values),
            "average_hours_from_acceptance": round(sum(values) / len(values), 6) if values else None,
        }
    precision_denominator = waqo_count + rejected
    pilot_report = {
        "candidate_signals": candidate_signals,
        "accepted_opportunities": waqo_count,
        "rejected_leads": rejected,
        "acceptance_rate": _ratio(waqo_count, precision_denominator),
        "duplicate_rate": _ratio(duplicate_rows, max(1, real_scope)),
        "dedupe_enforced_by_unique_key": True,
        "reply_rate": _ratio(replies, waqo_count),
        "meaningful_conversation_rate": _ratio(conversations, waqo_count),
        "meeting_rate": _ratio(meetings, waqo_count),
        "quote_rate": _ratio(quotes, waqo_count),
        "order_attribution_rate": _ratio(orders, waqo_count),
        "cost_per_accepted_opportunity": round(total_cost / waqo_count, 6) if waqo_count else 0.0,
        "precision": _ratio(waqo_count, precision_denominator),
        "recall": 0.0,
        "recall_basis": "requires labeled real pilot denominator outside fixture metrics",
    }
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
        "elapsed_time": elapsed,
        "conversion_rates": {
            "reply_rate": pilot_report["reply_rate"],
            "meaningful_conversation_rate": pilot_report["meaningful_conversation_rate"],
            "meeting_rate": pilot_report["meeting_rate"],
            "quote_rate": pilot_report["quote_rate"],
            "order_attribution_rate": pilot_report["order_attribution_rate"],
        },
        "pilot_report": pilot_report,
        "quality": {
            "missing_rejection_reason": missing_rejection_reason,
            "accepted_missing_contact_policy": accepted_missing_contact_policy,
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
    parser.add_argument("--import-csv", default="")
    parser.add_argument("--import-webhook-json", default="")
    parser.add_argument("--ingest-source", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ingestion_result: dict[str, Any] | None = None
    if args.import_csv:
        ingestion_result = import_outcomes_csv(
            db_path=args.db_path or None,
            csv_path=args.import_csv,
            ingest_source=args.ingest_source or "csv",
            create_missing_db=args.create_missing_db,
        )
    if args.import_webhook_json:
        payload = json.loads(Path(args.import_webhook_json).read_text(encoding="utf-8"))
        ingestion_result = import_outcomes_webhook_payload(
            db_path=args.db_path or None,
            payload=payload,
            ingest_source=args.ingest_source or "webhook",
            create_missing_db=args.create_missing_db,
        )
    payload = build_report(
        db_path=args.db_path or None,
        start_at=args.start_at,
        end_at=args.end_at,
        create_missing_db=args.create_missing_db,
    )
    if ingestion_result is not None:
        payload["ingestion"] = ingestion_result
        if not ingestion_result.get("passed"):
            payload["passed"] = False
            payload["status"] = "failed"
            payload["failures"] = list(payload.get("failures") or []) + list(ingestion_result.get("failures") or [])
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
