# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthTaskConfig
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.workflow_service import GrowthWorkflowService
from tools.reachops_delivery_smoke import build_service


DEFAULT_TARGETS = [
    "anti aging serum",
    "https://www.tiktok.com/@beauty_creator",
    "#makeupfinds",
]


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _campaign_sources(plan: dict, limit: int) -> list[dict]:
    return [
        {"type": row["source_type"], "value": row["source_value"]}
        for row in plan.get("sources", [])
        if row.get("source_type") and row.get("source_value")
    ][:limit]


def _write_json(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def run_pressure(args) -> dict:
    base_dir = args.base_dir or tempfile.mkdtemp(prefix="reachops-operator-pressure-")
    service = build_service(base_dir)
    workflow = GrowthWorkflowService(service)
    targets = list(args.targets or DEFAULT_TARGETS)
    profiles_collect = [
        {"profile_id": f"collect-{index}", "group_name": args.profile_group}
        for index in range(1, max(2, args.collect_profile_count) + 1)
    ]
    profiles_execute = [
        {"profile_id": f"exec-{index}", "group_name": args.profile_group}
        for index in range(1, max(2, args.execute_profile_count) + 1)
    ]
    campaigns = []
    artifacts = []
    collection_failures = []

    for target in targets[: args.max_campaigns]:
        plan = service.create_campaign_plan(
            target,
            intent_keywords=args.intent_keywords,
            exclude_keywords=args.exclude_keywords,
            max_sources=args.max_sources_per_campaign,
        )
        campaign_id = str(plan["campaign"]["id"])
        sources = _campaign_sources(plan, args.max_sources_per_campaign)
        if not sources:
            collection_failures.append({"target": target, "error_code": "NO_SOURCE_PLANNED"})
            continue
        collection = service.run_collection(
            sources,
            profiles_collect,
            GrowthTaskConfig(
                campaign_id=campaign_id,
                profile_group=args.profile_group,
                max_videos_per_creator=args.max_videos,
                max_comments_per_video=args.max_comments,
                min_views=args.min_views,
                min_comments=args.min_comments,
                task_delay_min_seconds=args.task_delay_seconds,
                task_delay_max_seconds=args.task_delay_seconds,
                test_mode=True,
                intent_keywords=args.intent_keywords,
                exclude_keywords=args.exclude_keywords,
            ),
        )
        batch = service.storage.latest_collection_batch_for_campaign(campaign_id) or {}
        funnel = workflow.build_campaign_funnel(campaign_id=campaign_id, batch_id=str(batch.get("id") or ""))
        campaign_artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
        campaigns.append(
            {
                "campaign_id": campaign_id,
                "target": target,
                "input_type": plan["campaign"].get("input_type", ""),
                "batch_id": str(batch.get("id") or ""),
                "planned_sources": len(sources),
                "processed_sources": collection.processed_sources,
                "errors": collection.errors,
                "funnel": funnel,
                "persona": plan.get("persona", {}),
                "strategy": plan.get("strategy", {}),
            }
        )
        artifacts.append(campaign_artifacts)

    latest_campaign = campaigns[-1] if campaigns else {}
    latest_batch_id = str(latest_campaign.get("batch_id") or "")
    fallback_action_result = workflow.run_action_router(
        [
            {"profile_id": "fallback-1", "group_name": args.profile_group},
            {"profile_id": "fallback-2", "group_name": args.profile_group},
        ],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=args.per_profile_limit,
            max_switch_attempts=args.switch_attempts,
            action_types=["dm_review"],
            dry_run=True,
            profile_group=args.profile_group,
            per_profile_hour_limit=args.per_profile_hour_limit,
            per_profile_video_hour_limit=args.per_profile_video_hour_limit,
            batch_id=latest_batch_id,
        ),
        fixture_outcomes=[
            {"action_type": "dm_review", "status": "failed", "error_code": "DM_NOT_ALLOWED"},
            {"action_type": "comment_reply", "status": "success"},
        ],
        limit=max(1, min(3, args.action_limit)),
        export_report=False,
        batch_id=latest_batch_id,
    )
    action_result = workflow.run_action_router(
        profiles_execute,
        config=ActionRouterConfig(
            max_workers=args.workers,
            per_profile_action_limit=args.per_profile_limit,
            max_switch_attempts=args.switch_attempts,
            action_types=["comment_reply", "follow_review"],
            dry_run=True,
            profile_group=args.profile_group,
            per_profile_hour_limit=args.per_profile_hour_limit,
            per_profile_video_hour_limit=args.per_profile_video_hour_limit,
            batch_id=latest_batch_id,
        ),
        fixture_outcomes=[
            {
                "action_type": "comment_reply",
                "profile_id": "exec-1",
                "status": "failed",
                "error_code": "PAGE_OPEN_FAILED",
                "error_message": "fixture first account page open failed",
            },
            {"action_type": "comment_reply", "profile_id": "exec-2", "status": "success"},
            {"action_type": "follow_review", "status": "failed", "error_code": "FOLLOW_RATE_LIMITED"},
            {"action_type": "dm_review", "status": "failed", "error_code": "DM_NOT_ALLOWED"},
        ],
        limit=args.action_limit,
        export_report=True,
        batch_id=latest_batch_id,
    )
    snapshot = workflow.build_snapshot(
        campaign_id=str(latest_campaign.get("campaign_id") or ""),
        batch_id=latest_batch_id,
    )
    final_funnel = snapshot.campaign_funnel
    results = (fallback_action_result.get("results") or []) + (action_result.get("results") or [])
    result_action_types = [row.get("action_type") for row in results]
    result_statuses = [row.get("status") for row in results]
    report = {
        "status": "ok",
        "base_dir": os.path.abspath(base_dir),
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile_group": args.profile_group,
        "targets": targets[: args.max_campaigns],
        "campaign_count": len(campaigns),
        "campaigns": campaigns,
        "collection_failures": collection_failures,
        "fallback_action_result": fallback_action_result,
        "action_result": action_result,
        "final_funnel": final_funnel,
        "summary": {
            "target_sources": sum(int(row.get("funnel", {}).get("target_sources") or 0) for row in campaigns),
            "content_found": sum(int(row.get("funnel", {}).get("content_found") or 0) for row in campaigns),
            "comment_users": sum(int(row.get("funnel", {}).get("comment_users") or 0) for row in campaigns),
            "customer_leads": sum(int(row.get("funnel", {}).get("customer_leads") or 0) for row in campaigns),
            "outreach_actions": sum(int(row.get("funnel", {}).get("outreach_actions") or 0) for row in campaigns),
            "selected_actions": int(fallback_action_result.get("selected_actions") or 0) + int(action_result.get("selected_actions") or 0),
            "execution_success": int(fallback_action_result.get("success") or 0) + int(action_result.get("success") or 0),
            "execution_failed": int(fallback_action_result.get("failed") or 0) + int(action_result.get("failed") or 0),
            "account_switched": int(fallback_action_result.get("account_switched") or 0) + int(action_result.get("account_switched") or 0),
            "workers": int(action_result.get("worker_count") or 0),
            "available_profiles": int(action_result.get("available_profile_count") or 0),
        },
        "artifacts": artifacts,
    }
    failures = []
    if len(campaigns) < min(args.max_campaigns, len(targets)):
        failures.append("campaign_creation_incomplete")
    if report["summary"]["content_found"] < len(campaigns):
        failures.append("content_found_too_low")
    if report["summary"]["comment_users"] < len(campaigns):
        failures.append("comment_users_too_low")
    if report["summary"]["customer_leads"] < len(campaigns):
        failures.append("customer_leads_too_low")
    if report["summary"]["outreach_actions"] < len(campaigns):
        failures.append("outreach_actions_too_low")
    if report["summary"]["selected_actions"] < 1:
        failures.append("action_selection_empty")
    if report["summary"]["workers"] < max(1, args.workers):
        failures.append("worker_count_too_low")
    if report["summary"]["execution_success"] < 1:
        failures.append("execution_success_empty")
    if report["summary"]["account_switched"] < 1:
        failures.append("account_switch_not_verified")
    if "dm_review" not in result_action_types or "comment_reply" not in result_action_types:
        failures.append("fallback_chain_not_exercised")
    if "account_switched" not in result_statuses:
        failures.append("account_switch_status_missing")
    if not final_funnel.get("campaign_id"):
        failures.append("final_funnel_missing_campaign")
    if int(final_funnel.get("execution_success") or 0) != 0:
        failures.append("final_funnel_live_success_must_remain_zero")
    if failures:
        report["status"] = "failed"
        report["failures"] = failures
    report_path = os.path.join(base_dir, "reports", "growth_ops_smoke", "reachops_operator_pressure_report.json")
    _write_json(report_path, report)
    report["report_path"] = report_path
    if failures and not args.allow_fail:
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps operator pressure test without live platform submission.")
    parser.add_argument("--base-dir", default="")
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="Comma separated product/keyword/creator/hashtag targets.")
    parser.add_argument("--profile-group", default="US")
    parser.add_argument("--max-campaigns", type=int, default=3)
    parser.add_argument("--max-sources-per-campaign", type=int, default=1)
    parser.add_argument("--max-videos", type=int, default=5)
    parser.add_argument("--max-comments", type=int, default=10)
    parser.add_argument("--min-views", type=int, default=0)
    parser.add_argument("--min-comments", type=int, default=0)
    parser.add_argument("--collect-profile-count", type=int, default=3)
    parser.add_argument("--execute-profile-count", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--per-profile-limit", type=int, default=10)
    parser.add_argument("--switch-attempts", type=int, default=2)
    parser.add_argument("--action-limit", type=int, default=18)
    parser.add_argument("--per-profile-hour-limit", type=int, default=20)
    parser.add_argument("--per-profile-video-hour-limit", type=int, default=99)
    parser.add_argument("--task-delay-seconds", type=int, default=30)
    parser.add_argument("--intent-keywords", default="where,link,buy,price,download,app,coupon")
    parser.add_argument("--exclude-keywords", default="spam,bot,haha,lol")
    parser.add_argument("--allow-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    args.targets = _csv_list(args.targets)
    args.intent_keywords = _csv_list(args.intent_keywords)
    args.exclude_keywords = _csv_list(args.exclude_keywords)
    args.max_campaigns = max(1, int(args.max_campaigns or 1))
    args.max_sources_per_campaign = max(1, int(args.max_sources_per_campaign or 1))
    args.max_videos = max(1, int(args.max_videos or 1))
    args.max_comments = max(1, int(args.max_comments or 1))
    args.collect_profile_count = max(1, int(args.collect_profile_count or 1))
    args.execute_profile_count = max(1, int(args.execute_profile_count or 1))
    args.workers = max(1, int(args.workers or 1))
    args.per_profile_limit = max(1, int(args.per_profile_limit or 1))
    args.switch_attempts = max(1, int(args.switch_attempts or 1))
    args.action_limit = max(1, int(args.action_limit or 1))
    return args


def main() -> int:
    args = parse_args()
    report = run_pressure(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
