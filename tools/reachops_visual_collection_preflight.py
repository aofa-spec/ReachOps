# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthIntelligenceService, GrowthTaskConfig
from ReachOps.workbench.profile_preflight import ProfilePreflightChecker, ProfilePreflightConfig
from ReachOps.workbench.workflow_service import GrowthWorkflowService
from tools.reachops_live_validation_manifest import load_profile_snapshot, select_numeric_profiles, split_csv


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def configure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class EvidenceDriver:
    def __init__(self, driver: Any, evidence_dir: Path, profile_id: str, evidence_rows: list[dict]):
        self._driver = driver
        self._evidence_dir = evidence_dir
        self._profile_id = str(profile_id or "")
        self._evidence_rows = evidence_rows
        self._navigation_index = 0

    def __getattr__(self, name: str):
        return getattr(self._driver, name)

    @property
    def current_url(self):
        return getattr(self._driver, "current_url", "")

    @property
    def title(self):
        return getattr(self._driver, "title", "")

    def get(self, url: str):
        result = self._driver.get(url)
        self.capture("navigation")
        return result

    def capture(self, label: str = "manual") -> str:
        if not hasattr(self._driver, "save_screenshot"):
            return ""
        self._navigation_index += 1
        safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(label or "page"))[:40]
        path = self._evidence_dir / f"{self._profile_id}_{self._navigation_index:03d}_{safe_label}.png"
        try:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            ok = bool(self._driver.save_screenshot(str(path)))
            if not ok:
                return ""
            data = path.read_bytes()
            meta = {
                "captured_at": utc_stamp(),
                "profile_id": self._profile_id,
                "label": safe_label,
                "current_url": str(getattr(self._driver, "current_url", "") or ""),
                "title": str(getattr(self._driver, "title", "") or "")[:160],
                "screenshot_path": str(path),
                "screenshot_size": len(data),
                "screenshot_sha256": hashlib.sha256(data).hexdigest() if data else "",
            }
            write_json(Path(f"{path}.json"), meta)
            self._evidence_rows.append(meta)
            return str(path)
        except Exception as exc:
            self._evidence_rows.append(
                {
                    "captured_at": utc_stamp(),
                    "profile_id": self._profile_id,
                    "label": safe_label,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return ""


class VisualEvidenceBrowserFactory:
    def __init__(self, evidence_dir: Path):
        self.evidence_dir = evidence_dir
        self.evidence_rows: list[dict] = []
        self.browser_started = 0
        self.errors: list[dict] = []

    def __call__(self, profile_id: str):
        from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

        manager = get_workbench_browser_adapter()
        session = manager.acquire(
            profile_id=str(profile_id or ""),
            account_id=f"visual-{profile_id}",
            trace_id=f"visual-{int(time.time())}",
            max_instances=3,
        )
        if not session or not getattr(session, "driver", None):
            error = ""
            try:
                error = manager.last_error()
            except Exception:
                error = "browser manager returned empty session"
            self.errors.append({"profile_id": str(profile_id or ""), "error_code": "PROFILE_START_FAILED", "error_message": error})
            return None
        self.browser_started += 1
        session.driver = EvidenceDriver(session.driver, self.evidence_dir, str(profile_id or ""), self.evidence_rows)
        try:
            session.driver.capture("profile_started")
        except Exception:
            pass
        return session


def select_profiles(args) -> tuple[list[dict], dict]:
    explicit_ids = split_csv(args.profile_ids)
    if explicit_ids:
        profiles = [{"profile_id": profile_id, "group_name": str(args.profile_group or "")} for profile_id in explicit_ids]
        return profiles[: max(1, int(args.profile_limit or 1))], {
            "available": False,
            "error": "profile scan skipped because --profile-ids was provided",
            "profiles": profiles,
            "groups": [],
        }
    snapshot = load_profile_snapshot(
        max_pages=int(args.max_pages or 50),
        timeout_seconds=int(args.profile_scan_timeout or 8),
        group_name=str(args.profile_group or ""),
        profile_limit=int(args.profile_limit or 1),
    )
    profiles = select_numeric_profiles(snapshot, str(args.profile_group or ""), int(args.profile_limit or 1))
    return profiles, snapshot


def source_from_plan(plan: dict, source_type: str, target: str) -> list[dict]:
    sources = plan.get("sources") or []
    if source_type and source_type != "auto":
        return [{"type": source_type, "value": target}]
    return [
        {"type": row.get("source_type"), "value": row.get("source_value")}
        for row in sources
        if row.get("source_type") and row.get("source_value")
    ][:1]


def build_profile_attempts(service: GrowthIntelligenceService, batch_id: str, evidence_rows: list[dict]) -> list[dict]:
    evidence_by_profile: dict[str, list[dict]] = {}
    for row in evidence_rows or []:
        evidence_by_profile.setdefault(str(row.get("profile_id") or ""), []).append(row)
    rows = []
    for task in service.storage.list_collection_tasks(limit=500):
        if str(task.get("batch_id") or "") != str(batch_id or ""):
            continue
        profile_id = str(task.get("profile_id") or "")
        rows.append(
            {
                "profile_id": profile_id,
                "source_type": str(task.get("source_type") or ""),
                "source_value": str(task.get("source_value") or ""),
                "status": str(task.get("status") or ""),
                "error_code": str(task.get("error_code") or ""),
                "error_message": str(task.get("error_message") or ""),
                "evidence_count": len(evidence_by_profile.get(profile_id, [])),
                "evidence_paths": [str(item.get("screenshot_path") or "") for item in evidence_by_profile.get(profile_id, []) if item.get("screenshot_path")],
                "started_browser": profile_id in evidence_by_profile,
            }
        )
    return list(reversed(rows))


def build_operator_diagnosis(report: dict) -> dict:
    funnel = report.get("funnel") or {}
    attempts = report.get("profile_attempts") or []
    errors = report.get("errors") or {}
    profile_preflight = report.get("profile_preflight") or {}
    if int(funnel.get("customer_leads") or 0) > 0:
        status = "leads_found"
        next_action = "进入客户池和触达执行预检"
    elif int(funnel.get("comment_users") or 0) > 0:
        status = "comment_users_found"
        next_action = "检查意图分数和动作队列"
    elif errors.get("COMMENT_ACCESS_GATED") or errors.get("LOGIN_REQUIRED"):
        status = "comment_access_gated"
        next_action = "当前账号能发现视频但不能读取评论；更换已登录且可看评论的 discovery/comment 分组后重试"
    elif int(funnel.get("content_found") or 0) > 0:
        status = "content_found_no_comments"
        next_action = "已发现素材但没有沉淀评论用户；优先检查账号评论权限，再考虑换具体视频链接或提高评论等待时间"
    elif errors.get("PROFILE_START_FAILED"):
        status = "profiles_not_starting"
        next_action = "更换可启动账号分组或检查 ixBrowser/Profile 配置"
    elif int(profile_preflight.get("requested") or 0) > 0 and int(profile_preflight.get("available") or 0) == 0:
        status = "no_logged_in_profile_available"
        next_action = "本轮账号均未通过登录态预检；先登录账号或更换 discovery/comment/action 分组"
    elif errors.get("EMPTY_RESULT_RETRY"):
        status = "opened_but_no_results"
        next_action = "当前页面没有可采内容；建议换热视频链接/达人主页，或更换网络/账号分组"
    elif not attempts:
        status = "not_started"
        next_action = "检查账号分组和目标输入"
    else:
        status = "no_leads"
        next_action = "查看账号矩阵和页面证据后重试"
    return {
        "status": status,
        "next_action": next_action,
        "attempt_count": len(attempts),
        "started_browser_count": len([row for row in attempts if row.get("started_browser")]),
        "profile_preflight": {
            "checked": int(profile_preflight.get("checked") or 0),
            "available": int(profile_preflight.get("available") or 0),
            "unavailable": int(profile_preflight.get("unavailable") or 0),
            "errors": profile_preflight.get("errors") or {},
        },
        "failed_profiles": [
            {"profile_id": row.get("profile_id"), "error_code": row.get("error_code")}
            for row in attempts
            if row.get("error_code")
        ],
    }


def run_visual_preflight(args) -> dict:
    base_dir = Path(args.base_dir).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = base_dir / "evidence" / run_id
    profiles, profile_snapshot = select_profiles(args)
    factory = VisualEvidenceBrowserFactory(evidence_dir)
    service = GrowthIntelligenceService(base_dir=str(base_dir), browser_factory=factory)
    workflow = GrowthWorkflowService(service)
    profile_preflight = {"skipped": True}
    executable_profiles = profiles
    if profiles and not bool(args.skip_profile_preflight):
        checker = ProfilePreflightChecker(
            service.storage,
            ProfilePreflightConfig(
                max_workers=max(1, min(int(args.profile_preflight_workers or 2), len(profiles))),
                page_load_timeout_seconds=max(1, int(args.profile_page_timeout or 20)),
                wait_after_open_seconds=max(0.0, float(args.profile_wait or 2.0)),
                total_timeout_seconds=max(5, int(args.profile_preflight_timeout or 0)),
                evidence_dir=str(evidence_dir / "profile_preflight"),
                close_browser_after_check=True,
            ),
        )
        executable_profiles, profile_preflight = checker.available_profiles(profiles)
        profile_preflight["skipped"] = False

    plan = service.create_campaign_plan(
        args.target,
        intent_keywords=split_csv(args.intent_keywords),
        exclude_keywords=split_csv(args.exclude_keywords),
        max_sources=1,
    )
    campaign_id = str((plan.get("campaign") or {}).get("id") or "")
    sources = source_from_plan(plan, str(args.source_type or "auto"), str(args.target or ""))
    result = None
    if executable_profiles and sources:
        result = service.run_collection(
            sources,
            executable_profiles,
            GrowthTaskConfig(
                campaign_id=campaign_id,
                profile_group=str(args.profile_group or ""),
                max_videos_per_creator=max(1, int(args.max_videos or 1)),
                max_comments_per_video=max(1, int(args.max_comments or 1)),
                min_views=max(0, int(args.min_views or 0)),
                min_comments=max(0, int(args.min_comments or 0)),
                task_delay_min_seconds=max(0, int(args.task_delay_seconds or 0)),
                task_delay_max_seconds=max(0, int(args.task_delay_seconds or 0)),
                test_mode=False,
                intent_keywords=split_csv(args.intent_keywords),
                exclude_keywords=split_csv(args.exclude_keywords),
            ),
        )
    batch = service.storage.latest_collection_batch_for_campaign(campaign_id) if campaign_id else {}
    funnel = workflow.build_campaign_funnel(campaign_id=campaign_id, batch_id=str(batch.get("id") or ""))
    errors = dict((funnel or {}).get("error_counts") or {})
    profile_attempts = build_profile_attempts(service, str(batch.get("id") or ""), factory.evidence_rows)
    report = {
        "status": "ok",
        "generated_at": utc_stamp(),
        "run_id": run_id,
        "mode": "visual_browser_read_only_preflight",
        "no_submit": True,
        "dry_run_actions": True,
        "target": str(args.target or ""),
        "source_type": str(args.source_type or "auto"),
        "profile_group": str(args.profile_group or ""),
        "selected_profiles": profiles,
        "executable_profiles": executable_profiles,
        "profile_preflight": profile_preflight,
        "profile_snapshot": {
            "available": bool(profile_snapshot.get("available")),
            "error": str(profile_snapshot.get("error") or ""),
            "profile_count": int(profile_snapshot.get("profile_count") or len(profile_snapshot.get("profiles") or [])),
            "group_count": int(profile_snapshot.get("group_count") or len(profile_snapshot.get("groups") or [])),
        },
        "campaign": plan.get("campaign") or {},
        "persona": plan.get("persona") or {},
        "sources": sources,
        "batch": batch,
        "funnel": funnel,
        "processed_sources": int(getattr(result, "processed_sources", 0) if result else 0),
        "report_json_path": str(getattr(result, "report_json_path", "") if result else ""),
        "report_csv_path": str(getattr(result, "report_csv_path", "") if result else ""),
        "browser_started": factory.browser_started,
        "browser_errors": factory.errors,
        "evidence": factory.evidence_rows,
        "profile_attempts": profile_attempts,
        "errors": errors,
    }
    report["operator_diagnosis"] = build_operator_diagnosis(report)
    failures = []
    if not profiles:
        failures.append("no_profile_selected")
    if profiles and not executable_profiles:
        failures.append("no_logged_in_profile_available")
    if not sources:
        failures.append("no_source_planned")
    if factory.browser_started < 1:
        failures.append("browser_not_started")
    if not factory.evidence_rows:
        failures.append("evidence_screenshot_missing")
    if not result or int(getattr(result, "processed_sources", 0) or 0) < 1:
        failures.append("collection_not_completed")
    if failures:
        report["status"] = "failed"
        report["failures"] = failures
    report_path = base_dir / "reachops_visual_collection_preflight_report.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    if failures and not args.allow_fail:
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps visual read-only browser collection preflight.")
    parser.add_argument("--base-dir", default="reports/reachops/visual_collection_preflight")
    parser.add_argument("--target", default="anti aging serum")
    parser.add_argument("--source-type", default="auto", choices=["auto", "keyword", "hashtag", "creator_url", "content_url", "live_room_url"])
    parser.add_argument("--profile-group", default="US")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-scan-timeout", type=int, default=8)
    parser.add_argument("--skip-profile-preflight", action="store_true")
    parser.add_argument("--profile-preflight-workers", type=int, default=2)
    parser.add_argument("--profile-page-timeout", type=int, default=20)
    parser.add_argument("--profile-wait", type=float, default=2.0)
    parser.add_argument("--profile-preflight-timeout", type=int, default=0)
    parser.add_argument("--max-videos", type=int, default=1)
    parser.add_argument("--max-comments", type=int, default=5)
    parser.add_argument("--min-views", type=int, default=0)
    parser.add_argument("--min-comments", type=int, default=0)
    parser.add_argument("--task-delay-seconds", type=int, default=0)
    parser.add_argument("--intent-keywords", default="where,link,buy,price,need,name,how,which,recommend")
    parser.add_argument("--exclude-keywords", default="spam,bot,haha,lol,giveaway")
    parser.add_argument("--allow-fail", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_stdio()
    try:
        report = run_visual_preflight(parse_args())
        code = 0 if report.get("status") == "ok" else 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
