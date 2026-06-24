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
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def configure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def run_preflight(args) -> dict:
    service = GrowthIntelligenceService(base_dir=str(args.base_dir))
    workflow = GrowthWorkflowService(service)
    campaign = service.storage.latest_campaign()
    campaign_id = str(args.campaign_id or campaign.get("id") or "")
    batch = service.storage.latest_collection_batch_for_campaign(campaign_id) if campaign_id else {}
    batch_id = str(args.batch_id or batch.get("id") or "")
    profiles = [
        {"profile_id": profile_id, "group_name": str(args.profile_group or "")}
        for profile_id in split_csv(args.profile_ids)
    ]
    executor = TikTokSeleniumActionExecutor(
        TikTokActionExecutorConfig(
            preflight_only=True,
            close_browser_after_action=True,
            evidence_dir=str(Path(args.base_dir) / "action_preflight_evidence"),
            page_load_timeout_seconds=max(1, int(args.page_timeout or 35)),
            element_timeout_seconds=max(1, int(args.element_timeout or 25)),
        )
    )
    if not batch_id:
        return {"status": "blocked", "error_code": "BATCH_NOT_FOUND", "campaign": campaign, "batch": batch}
    if not profiles:
        return {"status": "blocked", "error_code": "PROFILE_IDS_REQUIRED", "campaign": campaign, "batch": batch}
    profile_preflight = {"skipped": True}
    executable_profiles = profiles
    if not bool(args.skip_profile_preflight):
        checker = ProfilePreflightChecker(
            service.storage,
            ProfilePreflightConfig(
                max_workers=max(1, int(args.preflight_workers or args.workers or 1)),
                page_load_timeout_seconds=max(1, int(args.profile_page_timeout or 20)),
                wait_after_open_seconds=max(0.0, float(args.profile_wait or 2.0)),
                evidence_dir=str(Path(args.base_dir) / "profile_preflight_evidence"),
                close_browser_after_check=True,
            ),
        )
        executable_profiles, profile_preflight = checker.available_profiles(profiles)
        profile_preflight["skipped"] = False
        if not executable_profiles:
            return {
                "status": "blocked",
                "error_code": "NO_LOGGED_IN_PROFILE_AVAILABLE",
                "no_submit": True,
                "campaign": campaign,
                "batch": batch,
                "profiles": profiles,
                "executable_profiles": executable_profiles,
                "profile_preflight": profile_preflight,
            }
    result = workflow.run_action_router(
        executable_profiles,
        config=ActionRouterConfig(
            batch_id=batch_id,
            max_workers=max(1, int(args.workers or 1)),
            per_profile_action_limit=max(1, int(args.per_profile_limit or 3)),
            max_switch_attempts=max(1, int(args.switch_attempts or 2)),
            action_types=split_csv(args.action_types) or ["comment_reply", "follow_review", "dm_review"],
            dry_run=False,
            live_preflight_only=True,
            allow_live_submit=False,
            auto_approve=True,
            auto_confirm=True,
            profile_group=str(args.profile_group or ""),
            per_profile_hour_limit=max(1, int(args.per_profile_hour_limit or 10)),
            per_profile_video_hour_limit=max(1, int(args.per_profile_video_hour_limit or 2)),
        ),
        platform_executor=executor,
        limit=max(1, int(args.limit or 6)),
        export_report=True,
        batch_id=batch_id,
    )
    return {
        "status": "ok",
        "no_submit": True,
        "campaign": campaign,
        "batch": batch,
        "profiles": profiles,
        "executable_profiles": executable_profiles,
        "profile_preflight": profile_preflight,
        "result": result,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Run ReachOps no-submit action preflight for the latest or selected collection batch.")
    parser.add_argument("--base-dir", default="reports/reachops/visual_collection_preflight")
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--profile-group", default="")
    parser.add_argument("--profile-ids", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--per-profile-limit", type=int, default=3)
    parser.add_argument("--switch-attempts", type=int, default=2)
    parser.add_argument("--action-types", default="comment_reply,follow_review,dm_review")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--per-profile-hour-limit", type=int, default=10)
    parser.add_argument("--per-profile-video-hour-limit", type=int, default=2)
    parser.add_argument("--page-timeout", type=int, default=35)
    parser.add_argument("--element-timeout", type=int, default=25)
    parser.add_argument("--skip-profile-preflight", action="store_true")
    parser.add_argument("--preflight-workers", type=int, default=3)
    parser.add_argument("--profile-page-timeout", type=int, default=20)
    parser.add_argument("--profile-wait", type=float, default=2.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_stdio()
    payload = run_preflight(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
