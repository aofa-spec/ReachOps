# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthIntelligenceService
from ReachOps.workbench.workflow_service import GrowthWorkflowService


def configure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def compact_rows(rows: list[dict], keys: list[str], limit: int) -> list[dict]:
    out = []
    for row in rows[: max(0, int(limit or 0))]:
        out.append({key: row.get(key, "") for key in keys})
    return out


def build_report(args) -> dict:
    service = GrowthIntelligenceService(base_dir=str(args.base_dir))
    workflow = GrowthWorkflowService(service)
    storage = service.storage
    campaign = storage.latest_campaign()
    campaign_id = str(args.campaign_id or campaign.get("id") or "")
    batch = storage.latest_collection_batch_for_campaign(campaign_id) if campaign_id else {}
    batch_id = str(args.batch_id or batch.get("id") or "")
    funnel = workflow.build_campaign_funnel(campaign_id=campaign_id, batch_id=batch_id)
    leads = storage.list_operation_leads(limit=500, batch_id=batch_id)
    actions = storage.list_action_queue(limit=1000, batch_id=batch_id)
    executions = storage.list_outreach_executions(limit=1000, batch_id=batch_id)
    tasks = [row for row in storage.list_collection_tasks(limit=500) if str(row.get("batch_id") or "") == batch_id]
    snapshot = workflow.build_snapshot(campaign_id=campaign_id, batch_id=batch_id)
    execution_status = Counter(str(row.get("status") or "") for row in executions)
    action_types = Counter(str(row.get("action_type") or "") for row in actions)
    task_errors = Counter(str(row.get("error_code") or "") for row in tasks if row.get("error_code"))
    high_value = [row for row in leads if int(row.get("score") or row.get("qualify_score") or 0) >= 70]
    acceptance = {
        "campaign_created": bool(campaign_id),
        "persona_created": bool(storage.get_audience_persona(campaign_id)) if campaign_id else False,
        "sources_planned": int(funnel.get("target_sources") or 0) > 0,
        "content_found": int(funnel.get("content_found") or 0) > 0,
        "comment_users_collected": int(funnel.get("comment_users") or 0) > 0,
        "customer_leads_created": int(funnel.get("customer_leads") or 0) > 0,
        "outreach_actions_created": int(funnel.get("outreach_actions") or 0) > 0,
        "preflight_attempted": bool(executions),
        "account_switch_verified": bool(execution_status.get("account_switched")),
        "reports_exported": any(row.get("exists") for row in snapshot.report_artifacts),
        "real_submit_executed": False,
    }
    status = "mvp_acquisition_verified" if all(
        acceptance[key]
        for key in [
            "campaign_created",
            "persona_created",
            "sources_planned",
            "content_found",
            "comment_users_collected",
            "customer_leads_created",
            "outreach_actions_created",
            "preflight_attempted",
            "account_switch_verified",
            "reports_exported",
        ]
    ) else "incomplete"
    if not acceptance["real_submit_executed"]:
        final_status = "pending_live_submit_validation"
    else:
        final_status = status
    return {
        "status": status,
        "final_status": final_status,
        "no_submit": True,
        "campaign": campaign,
        "batch": batch,
        "funnel": funnel,
        "acceptance": acceptance,
        "summary": {
            "collection_tasks": len(tasks),
            "task_errors": dict(task_errors),
            "lead_count": len(leads),
            "high_value_lead_count": len(high_value),
            "action_count": len(actions),
            "action_types": dict(action_types),
            "execution_count": len(executions),
            "execution_status": dict(execution_status),
        },
        "top_leads": compact_rows(
            leads,
            ["username", "lead_type", "priority", "score", "comment_text", "source_path", "action_count"],
            int(args.preview_limit),
        ),
        "actions": compact_rows(
            actions,
            ["action_type", "target_username", "status", "risk_level", "last_error_code", "suggested_text"],
            int(args.preview_limit),
        ),
        "executions": compact_rows(
            executions,
            ["action_type", "target_username", "status", "profile_id", "error_code", "evidence_path"],
            int(args.preview_limit),
        ),
        "report_artifacts": snapshot.report_artifacts,
        "remaining_gap": [
            "真实评论/关注/私信提交未执行；需要授权和可登录账号后验证。"
        ],
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Build a ReachOps real acquisition MVP evidence report.")
    parser.add_argument("--base-dir", default="reports/reachops/visual_collection_preflight")
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--preview-limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_stdio()
    payload = build_report(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "mvp_acquisition_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
