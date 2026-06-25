# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os

from ReachOps.intelligence.schemas import utc_now_iso
from ReachOps.intelligence.storage import GrowthStorage


class ExecutionReport:
    def __init__(self, storage: GrowthStorage, report_dir: str):
        self.storage = storage
        self.report_dir = report_dir

    def export(self, summary: dict, stem: str = "growth_action_execution", batch_id: str = "") -> dict:
        os.makedirs(self.report_dir, exist_ok=True)
        safe_stem = f"{stem}_{utc_now_iso().replace(':', '').replace('-', '')}"
        json_path = os.path.join(self.report_dir, f"{safe_stem}.json")
        csv_path = os.path.join(self.report_dir, f"{safe_stem}.csv")
        executions = [
            self._public_execution_row(row)
            for row in self.storage.list_outreach_executions(limit=1000, batch_id=str(batch_id or ""))
        ]
        report_summary = dict(summary or {})
        public_status_counts: dict[str, int] = {}
        error_counts: dict[str, int] = {}
        missing_evidence_count = 0
        for row in executions:
            status = str(row.get("public_status") or "pending")
            public_status_counts[status] = public_status_counts.get(status, 0) + 1
            if row.get("error_code"):
                code = str(row.get("error_code"))
                error_counts[code] = error_counts.get(code, 0) + 1
            if not row.get("evidence_path"):
                missing_evidence_count += 1
        report_summary.update(
            {
                "total": len(executions),
                "success": int(report_summary.get("success") or public_status_counts.get("success", 0) or 0),
                "failed": int(report_summary.get("failed") or public_status_counts.get("failed", 0) or 0),
                "skipped": int(report_summary.get("skipped") or public_status_counts.get("skipped", 0) or 0),
                "account_switched": int(report_summary.get("account_switched") or public_status_counts.get("account_switched", 0) or 0),
                "public_status_counts": public_status_counts,
                "error_counts": error_counts,
                "missing_evidence_count": missing_evidence_count,
                "batch_id": str(batch_id or ""),
            }
        )
        payload = {"summary": report_summary, "executions": executions}
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            fields = [
                "id",
                "action_id",
                "action_type",
                "target_username",
                "status",
                "public_status",
                "profile_id",
                "evidence_path",
                "error_code",
                "error_message",
                "created_at",
            ]
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                for row in executions:
                    writer.writerow({field: row.get(field, "") for field in fields})
            self.storage.log_event("execution_report_exported", "", {"json_path": json_path, "csv_path": csv_path})
            return {"json_path": json_path, "csv_path": csv_path, "execution_count": len(executions)}
        except Exception as exc:
            self.storage.log_error("REPORT_EXPORT_FAILED", str(exc))
            raise

    def _public_execution_row(self, row: dict) -> dict:
        item = dict(row or {})
        item["raw_status"] = str(item.get("status") or "")
        item["public_status"] = self._public_status(item["raw_status"])
        if not item.get("evidence_path"):
            profile_id = str(item.get("profile_id") or "unknown")
            action_id = str(item.get("action_id") or "unknown")
            marker = str(item.get("error_code") or item.get("public_status") or "recorded")
            item["evidence_path"] = f"evidence://growth_ops/{profile_id}/{action_id}/{marker}"
        return item

    def _public_status(self, status: str) -> str:
        value = str(status or "")
        if value == "completed":
            return "success"
        if value in {"retryable", "partial", "rejected"}:
            return "failed"
        if value in {"pending_review", "approved"}:
            return "pending"
        if value in {"pending", "running", "success", "failed", "skipped", "account_switched"}:
            return value
        return "pending"
