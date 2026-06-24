# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthIntelligenceService
from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import new_id
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def seed_preflight_actions(service: GrowthIntelligenceService, video_url: str, profile_url: str, target_username: str) -> list[str]:
    specs = [
        ("comment_reply", video_url, "Preflight only comment text for @{username}"),
        ("follow_review", profile_url, "Preflight only follow review for @{username}"),
        ("dm_review", profile_url, "Preflight only DM text for @{username}"),
    ]
    action_ids = []
    for action_type, target_url, suggested_text in specs:
        action_id, _created = service.storage.upsert_action_queue_item(
            ActionQueueItem(
                id=new_id("aq"),
                lead_id=new_id("lead"),
                action_type=action_type,
                target_username=target_username,
                target_url=target_url,
                suggested_text=suggested_text,
                status="pending_review",
                risk_level="medium" if action_type != "dm_review" else "high",
                reason="reachops_live_preflight_no_submit",
            )
        )
        service.storage.update_action_status(action_id, "approved", "reachops live preflight seeded action")
        service.storage.confirm_action_execution(action_id, confirmed_by="reachops_preflight", note="preflight only; no submit")
        action_ids.append(action_id)
    return action_ids


def build_platform_executor(args):
    return TikTokSeleniumActionExecutor(
        TikTokActionExecutorConfig(
            preflight_only=True,
            page_load_timeout_seconds=max(1, int(args.page_timeout)),
            element_timeout_seconds=max(1, int(args.element_timeout)),
            evidence_dir=str(Path(args.base_dir) / "evidence"),
            close_browser_after_action=True,
        )
    )


def run_preflight(args, platform_executor=None) -> dict:
    base_dir = Path(args.base_dir)
    service = GrowthIntelligenceService(base_dir=str(base_dir))
    workflow = GrowthWorkflowService(service)
    username = str(args.target_username or "").strip() or str(args.profile_url).rstrip("/").rsplit("/", 1)[-1].lstrip("@")
    action_ids = seed_preflight_actions(service, args.video_url, args.profile_url, username)
    profiles = [{"profile_id": profile_id, "group_name": str(args.group_name or "")} for profile_id in split_csv(args.profile_ids)]
    executor = platform_executor or build_platform_executor(args)
    summary = workflow.run_action_router(
        profiles,
        config=ActionRouterConfig(
            max_workers=max(1, int(args.workers)),
            per_profile_action_limit=max(1, int(args.per_profile_limit)),
            max_switch_attempts=max(1, int(args.switch_attempts)),
            action_types=["comment_reply", "follow_review", "dm_review"],
            auto_approve=True,
            auto_confirm=True,
            dry_run=False,
            live_preflight_only=True,
            allow_live_submit=False,
            per_profile_hour_limit=max(1, int(args.per_profile_hour_limit)),
            per_profile_video_hour_limit=max(1, int(args.per_profile_video_hour_limit)),
        ),
        platform_executor=executor,
        limit=10,
        export_report=True,
    )
    results = list(summary.get("results") or [])
    required_types = {"comment_reply", "follow_review", "dm_review"}
    preflight_action_statuses = {}
    for action_type in sorted(required_types):
        rows = [row for row in results if str(row.get("action_type") or "") == action_type]
        preflight_action_statuses[action_type] = [
            {
                "status": str(row.get("status") or ""),
                "profile_id": str(row.get("profile_id") or ""),
                "error_code": str(row.get("error_code") or ""),
                "evidence_path": str(row.get("evidence_path") or ""),
            }
            for row in rows
        ]
    success_types = {
        str(row.get("action_type") or "")
        for row in results
        if str(row.get("status") or "") == "success"
    }
    missing_preflight_action_types = sorted(required_types - success_types)
    return {
        "base_dir": str(base_dir),
        "seeded_action_ids": action_ids,
        "profiles": profiles,
        "summary": summary,
        "preflight_action_statuses": preflight_action_statuses,
        "missing_preflight_action_types": missing_preflight_action_types,
        "no_submit": True,
        "preflight_only": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps live account preflight without submitting comment/follow/dm actions.")
    parser.add_argument("--base-dir", default="reports/reachops/live_preflight")
    parser.add_argument("--profile-ids", required=True, help="Comma/semicolon separated ixBrowser profile ids.")
    parser.add_argument("--group-name", default="")
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--profile-url", required=True)
    parser.add_argument("--target-username", default="")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--per-profile-limit", type=int, default=3)
    parser.add_argument("--switch-attempts", type=int, default=2)
    parser.add_argument("--per-profile-hour-limit", type=int, default=20)
    parser.add_argument("--per-profile-video-hour-limit", type=int, default=5)
    parser.add_argument("--page-timeout", type=int, default=35)
    parser.add_argument("--element-timeout", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    result = run_preflight(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
