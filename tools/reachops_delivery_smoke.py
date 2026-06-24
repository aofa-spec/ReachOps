# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.workflow_service import GrowthWorkflowService


class SmokeDriver:
    def __init__(self):
        self.current_url = ""
        self.visited = []

    def get(self, url):
        self.current_url = url
        self.visited.append(url)

    def execute_script(self, _script):
        return ""

    def quit(self):
        pass


class SmokeProfileCollector:
    def collect(self, driver, task, context):
        username = driver.current_url.rstrip("/").split("/")[-1].lstrip("@") or "beauty_creator"
        return {
            "username": username,
            "profile_url": driver.current_url or f"https://www.tiktok.com/@{username}",
            "followers": 68000,
            "likes_total": 1240000,
        }


class SmokeVideoCollector:
    def collect(self, driver, task, context):
        username = task["creator"]["username"]
        max_videos = max(1, min(3, int(context.get("max_videos", 3) or 3)))
        return [
            {
                "video_id": f"{username}-smoke-{index}",
                "video_url": f"https://www.tiktok.com/@{username}/video/{1000 + index}",
                "caption": caption,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
            }
            for index, (caption, views, likes, comments, shares) in enumerate(
                [
                    ("where can I buy this serum link please", 180000, 9200, 880, 130),
                    ("free sample review app download name?", 96000, 4100, 420, 55),
                    ("watch my night routine episode with this product", 72000, 2100, 180, 28),
                ][:max_videos],
                start=1,
            )
        ]


class SmokeCommentCollector:
    def collect(self, driver, task, context):
        return [
            {
                "username": "buyer_where_link",
                "profile_url": "https://www.tiktok.com/@buyer_where_link",
                "comment_text": "where is the link I want to buy this",
                "comment_likes": 18,
                "reply_count": 3,
            },
            {
                "username": "buyer_app_name",
                "profile_url": "https://www.tiktok.com/@buyer_app_name",
                "comment_text": "what is the app name and is it free",
                "comment_likes": 6,
                "reply_count": 1,
            },
            {
                "username": "low_intent_viewer",
                "profile_url": "https://www.tiktok.com/@low_intent_viewer",
                "comment_text": "nice video",
                "comment_likes": 0,
                "reply_count": 0,
            },
        ][: max(1, int(context.get("max_comments", 3) or 3))]


class SmokeTopicContentCollector:
    def collect(self, driver, task, context):
        limit = max(1, min(3, int(context.get("limit", 3) or 3)))
        return [
            {
                "content": {
                    "creator_username": "beauty_topic_creator",
                    "video_id": f"topic-beauty-{index}",
                    "video_url": f"https://www.tiktok.com/@beauty_topic_creator/video/{2000 + index}",
                    "caption": caption,
                    "material_type": "topic_video",
                    "hook_text": caption,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                }
            }
            for index, (caption, views, likes, comments, shares) in enumerate(
                [
                    ("where can I buy anti aging serum link", 210000, 12200, 980, 160),
                    ("free sample app name for beauty product", 115000, 5400, 460, 70),
                    ("watch episode review of this serum", 84000, 2400, 210, 35),
                ][:limit],
                start=1,
            )
        ]


def build_service(base_dir: str) -> GrowthIntelligenceService:
    return GrowthIntelligenceService(
        base_dir=base_dir,
        browser_factory=lambda _profile_id: SmokeDriver(),
        collectors={
            "profile": SmokeProfileCollector(),
            "video": SmokeVideoCollector(),
            "comment": SmokeCommentCollector(),
            "topic_content": SmokeTopicContentCollector(),
            "search": object(),
        },
    )


def run_smoke(args) -> dict:
    base_dir = args.base_dir or tempfile.mkdtemp(prefix="reachops-delivery-smoke-")
    service = build_service(base_dir)
    workflow = GrowthWorkflowService(service)

    plan = service.create_campaign_plan(
        args.target,
        intent_keywords=args.intent_keywords,
        exclude_keywords=args.exclude_keywords,
        max_sources=args.max_sources,
    )
    campaign_id = str(plan["campaign"]["id"])
    sources = [
        {"type": row["source_type"], "value": row["source_value"]}
        for row in plan.get("sources", [])
    ][: args.max_sources]
    if not sources:
        raise RuntimeError("no acquisition sources planned")

    collection = service.run_collection(
        sources,
        [{"profile_id": "smoke-discovery-1", "group_name": "SMOKE"}],
        GrowthTaskConfig(
            campaign_id=campaign_id,
            max_videos_per_creator=args.max_videos,
            max_comments_per_video=args.max_comments,
            task_delay_min_seconds=30,
            task_delay_max_seconds=30,
            test_mode=True,
            intent_keywords=args.intent_keywords,
            exclude_keywords=args.exclude_keywords,
        ),
    )
    action_result = workflow.run_action_router(
        [{"profile_id": "smoke-action-1", "group_name": "SMOKE"}],
        config=ActionRouterConfig(
            max_workers=1,
            per_profile_action_limit=args.action_limit,
            action_types=["comment_reply", "follow_review", "dm_review"],
            dry_run=True,
        ),
        export_report=True,
    )
    artifacts = workflow.export_campaign_artifacts(campaign_id=campaign_id)
    funnel = workflow.build_campaign_funnel(campaign_id=campaign_id)
    collection_summary = (collection.report.summary if collection.report else {}) or {}
    summary = {
        "base_dir": os.path.abspath(base_dir),
        "campaign_id": campaign_id,
        "input_type": plan["campaign"].get("input_type"),
        "planned_sources": len(sources),
        "processed_sources": collection.processed_sources,
        "new_creators": int(collection_summary.get("new_creator_count", 0) or 0),
        "new_contents": int(collection_summary.get("new_content_count", 0) or 0),
        "new_candidates": int(collection_summary.get("candidate_user_count", 0) or 0),
        "collection_errors": collection.errors,
        "action_selected": action_result.get("selected_actions", 0),
        "action_success": action_result.get("success", 0),
        "action_failed": action_result.get("failed", 0),
        "funnel": funnel,
        "campaign_report": artifacts.get("json_path", ""),
        "actions_report": (action_result.get("report") or {}).get("json_path", ""),
    }

    failures = []
    if summary["processed_sources"] < 1:
        failures.append("processed_sources_empty")
    if summary["new_contents"] < 1:
        failures.append("new_contents_empty")
    if summary["new_candidates"] < 1:
        failures.append("new_candidates_empty")
    if summary["action_selected"] < 1:
        failures.append("action_queue_empty")
    if not summary["campaign_report"] or not Path(summary["campaign_report"]).exists():
        failures.append("campaign_report_missing")
    if failures:
        summary["status"] = "failed"
        summary["failures"] = failures
        raise RuntimeError(json.dumps(summary, ensure_ascii=False, indent=2))
    summary["status"] = "ok"
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps independent delivery smoke without live platform submission.")
    parser.add_argument("--target", default="anti aging serum", help="Product link, keyword, creator URL, video URL, or live room URL.")
    parser.add_argument("--base-dir", default="", help="Optional ReachOps runtime base dir. Defaults to a temp dir.")
    parser.add_argument("--max-sources", type=int, default=1)
    parser.add_argument("--max-videos", type=int, default=2)
    parser.add_argument("--max-comments", type=int, default=3)
    parser.add_argument("--action-limit", type=int, default=6)
    parser.add_argument("--intent-keywords", default="where,link,buy,app,free,name", help="Comma separated intent keywords.")
    parser.add_argument("--exclude-keywords", default="spam,bot", help="Comma separated exclusion keywords.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON only.")
    args = parser.parse_args()
    args.intent_keywords = [item.strip() for item in args.intent_keywords.split(",") if item.strip()]
    args.exclude_keywords = [item.strip() for item in args.exclude_keywords.split(",") if item.strip()]
    args.max_sources = max(1, int(args.max_sources or 1))
    args.max_videos = max(1, int(args.max_videos or 1))
    args.max_comments = max(1, int(args.max_comments or 1))
    args.action_limit = max(1, int(args.action_limit or 1))
    return args


def main() -> int:
    args = parse_args()
    summary = run_smoke(args)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
