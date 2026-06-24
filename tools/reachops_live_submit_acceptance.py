# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.intelligence import GrowthIntelligenceService
from ReachOps.intelligence.schemas import ActionQueueItem
from ReachOps.intelligence.storage import new_id
from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.action_router import ActionRouterConfig
from ReachOps.workbench.tiktok_action_executor import TikTokActionExecutorConfig, TikTokSeleniumActionExecutor
from ReachOps.workbench.workflow_service import GrowthWorkflowService


def utc_stamp() -> str:
    return datetime.utcnow().replace(microsecond=0).strftime("%Y%m%d_%H%M%S")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def username_from_profile_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if "/@" not in value:
        return ""
    return value.rsplit("/@", 1)[-1].split("/", 1)[0].lstrip("@")


def normalize_username(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def validate_authorization(args) -> list[str]:
    errors: list[str] = []
    if str(args.confirm_authorized_targets or "") != "YES":
        errors.append("--confirm-authorized-targets YES is required for live submit")
    if not str(args.video_url or "").strip():
        errors.append("--video-url is required")
    if not str(args.follow_profile_url or "").strip():
        errors.append("--follow-profile-url is required")
    if not str(args.dm_profile_url or "").strip():
        errors.append("--dm-profile-url is required")
    if not str(args.target_username or "").strip():
        errors.append("--target-username is required")
    target = normalize_username(args.target_username)
    follow_user = normalize_username(username_from_profile_url(args.follow_profile_url))
    dm_user = normalize_username(username_from_profile_url(args.dm_profile_url))
    if follow_user != target:
        errors.append(f"follow target mismatch: profile={follow_user or '<empty>'}, username={target or '<empty>'}")
    if dm_user != target:
        errors.append(f"dm target mismatch: profile={dm_user or '<empty>'}, username={target or '<empty>'}")
    if not split_csv(args.profile_ids):
        errors.append("--profile-ids must include at least one profile id")
    non_numeric_profile_ids = [profile_id for profile_id in split_csv(args.profile_ids) if not str(profile_id).isdigit()]
    if non_numeric_profile_ids:
        errors.append(f"--profile-ids must be ixBrowser numeric profile ids: {', '.join(non_numeric_profile_ids)}")
    if int(args.limit or 0) > 3 and str(args.allow_pressure_submit or "") != "YES":
        errors.append("--allow-pressure-submit YES is required when --limit > 3")
    return errors


def seed_live_submit_actions(service: GrowthIntelligenceService, args) -> list[str]:
    username = normalize_username(args.target_username)
    specs = [
        ("comment_reply", args.video_url, args.comment_text, "medium"),
        ("follow_review", args.follow_profile_url, f"Authorized follow acceptance for @{username}", "medium"),
        ("dm_review", args.dm_profile_url, args.dm_text, "high"),
    ]
    action_ids = []
    for action_type, target_url, suggested_text, risk_level in specs:
        action_id, _created = service.storage.upsert_action_queue_item(
            ActionQueueItem(
                id=new_id("aq"),
                lead_id=new_id("lead"),
                action_type=action_type,
                target_username=username,
                target_url=target_url,
                suggested_text=suggested_text,
                status="pending_review",
                risk_level=risk_level,
                reason="reachops_authorized_live_submit_acceptance",
            )
        )
        service.storage.update_action_status(action_id, "approved", "authorized live-submit acceptance")
        service.storage.confirm_action_execution(action_id, confirmed_by="reachops_acceptance", note="explicit authorized live submit acceptance")
        action_ids.append(action_id)
    return action_ids


def build_platform_executor(args):
    return TikTokSeleniumActionExecutor(
        TikTokActionExecutorConfig(
            preflight_only=False,
            page_load_timeout_seconds=max(1, int(args.page_timeout)),
            element_timeout_seconds=max(1, int(args.element_timeout)),
            evidence_dir=str(Path(args.base_dir) / "evidence"),
            close_browser_after_action=True,
        )
    )


def resolve_activation_status_path(args, target_status_path: str) -> tuple[str, bool]:
    explicit = str(getattr(args, "activation_status_path", "") or "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path(RuntimePaths.build().activation_status_path))
    target = Path(target_status_path)
    try:
        if target.exists():
            return str(target), True
    except Exception:
        pass
    for candidate in candidates:
        try:
            source = candidate.resolve()
        except Exception:
            source = candidate
        if not source.exists() or not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            shutil.copyfile(str(source), str(target))
        return str(source), True
    return explicit or str(candidates[-1]), False


def is_local_evidence_file(path: str) -> bool:
    value = str(path or "").strip()
    if not value or "://" in value:
        return False
    return Path(value).exists()


def local_evidence_file_detail(path: str, expected_action_type: str = "") -> dict[str, Any]:
    value = str(path or "").strip()
    if not value or "://" in value:
        return {}
    file_path = Path(value)
    if not file_path.exists() or not file_path.is_file():
        return {}
    data = file_path.read_bytes()
    if not data:
        return {}
    sidecar_path = Path(f"{file_path}.json")
    if not sidecar_path.exists() or not sidecar_path.is_file():
        return {}
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    digest = hashlib.sha256(data).hexdigest()
    if str(sidecar.get("screenshot_sha256") or "") and str(sidecar.get("screenshot_sha256")) != digest:
        return {}
    if expected_action_type and str(sidecar.get("action_type") or "") != str(expected_action_type):
        return {}
    return {
        "path": str(file_path),
        "size": len(data),
        "sha256": digest,
        "sidecar_path": str(sidecar_path),
        "sidecar": sidecar if isinstance(sidecar, dict) else {},
    }


def run_acceptance(args, platform_executor=None) -> dict[str, Any]:
    validation_errors = validate_authorization(args)
    if validation_errors:
        return {
            "passed": False,
            "error_code": "AUTHORIZATION_INVALID",
            "errors": validation_errors,
            "live_submit": False,
        }
    base_dir = Path(args.base_dir or f"reports/reachops/live_submit_acceptance_{utc_stamp()}")
    args.base_dir = str(base_dir)
    service = GrowthIntelligenceService(base_dir=str(base_dir))
    workflow = GrowthWorkflowService(service)
    activation_status_source, activation_status_loaded = resolve_activation_status_path(args, service.paths.activation_status_path)
    action_ids = seed_live_submit_actions(service, args)
    profiles = [{"profile_id": profile_id, "group_name": str(args.group_name or "")} for profile_id in split_csv(args.profile_ids)]
    executor = platform_executor or build_platform_executor(args)
    executor_mode = "fixture" if platform_executor is not None else "platform_selenium"
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
            live_preflight_only=False,
            allow_live_submit=True,
            per_profile_hour_limit=max(1, int(args.per_profile_hour_limit)),
            per_profile_video_hour_limit=max(1, int(args.per_profile_video_hour_limit)),
            require_authorization=True,
            require_execution_evidence=True,
        ),
        platform_executor=executor,
        limit=max(1, int(args.limit)),
        export_report=True,
    )
    results = list(summary.get("results") or [])
    success_types = {str(row.get("action_type") or "") for row in results if row.get("status") == "success"}
    missing_evidence = [row for row in results if row.get("status") == "success" and not str(row.get("evidence_path") or "")]
    required_types = {"comment_reply", "follow_review", "dm_review"}
    evidence_by_type = {}
    for action_type in sorted(required_types):
        evidence_by_type[action_type] = [
            str(row.get("evidence_path") or "")
            for row in results
            if row.get("status") == "success"
            and str(row.get("action_type") or "") == action_type
            and str(row.get("evidence_path") or "")
        ]
    missing_evidence_types = sorted([action_type for action_type in required_types if not evidence_by_type.get(action_type)])
    platform_validation = executor_mode == "platform_selenium"
    missing_local_evidence_file_types = []
    evidence_file_details = {action_type: [] for action_type in sorted(required_types)}
    if platform_validation:
        for action_type in sorted(required_types):
            evidence_file_details[action_type] = [
                detail
                for detail in [local_evidence_file_detail(path, expected_action_type=action_type) for path in evidence_by_type.get(action_type, [])]
                if detail
            ]
        missing_local_evidence_file_types = sorted(
            [
                action_type
                for action_type in required_types
                if not evidence_file_details.get(action_type)
            ]
        )
    passed = (
        int(summary.get("selected_actions") or 0) >= min(3, int(args.limit))
        and int(summary.get("failed") or 0) == 0
        and int(summary.get("skipped") or 0) == 0
        and not missing_evidence
        and not missing_evidence_types
        and not missing_local_evidence_file_types
        and required_types.issubset(success_types)
    )
    return {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "base_dir": str(base_dir),
        "executor_mode": executor_mode,
        "platform_validation": platform_validation,
        "activation_status_source": activation_status_source,
        "activation_status_path": service.paths.activation_status_path,
        "activation_status_loaded": activation_status_loaded,
        "seeded_action_ids": action_ids,
        "profiles": profiles,
        "target": {
            "video_url": args.video_url,
            "follow_profile_url": args.follow_profile_url,
            "dm_profile_url": args.dm_profile_url,
            "target_username": args.target_username,
        },
        "summary": summary,
        "missing_evidence_count": len(missing_evidence),
        "evidence_by_action_type": evidence_by_type,
        "evidence_file_details": evidence_file_details,
        "missing_evidence_action_types": missing_evidence_types,
        "missing_local_evidence_file_action_types": missing_local_evidence_file_types,
        "passed": passed,
        "live_submit": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Run controlled ReachOps live-submit acceptance for comment/follow/DM.")
    parser.add_argument("--base-dir", default="")
    parser.add_argument("--profile-ids", required=True, help="Comma/semicolon separated ixBrowser profile ids.")
    parser.add_argument("--group-name", default="")
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--follow-profile-url", required=True)
    parser.add_argument("--dm-profile-url", required=True)
    parser.add_argument("--target-username", required=True)
    parser.add_argument("--comment-text", default="ReachOps authorized validation comment.")
    parser.add_argument("--dm-text", default="ReachOps authorized validation message.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--per-profile-limit", type=int, default=3)
    parser.add_argument("--switch-attempts", type=int, default=2)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--confirm-authorized-targets", default="")
    parser.add_argument("--activation-status-path", default="", help="Optional server-synced ReachOps activation status JSON.")
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--per-profile-hour-limit", type=int, default=3)
    parser.add_argument("--per-profile-video-hour-limit", type=int, default=1)
    parser.add_argument("--page-timeout", type=int, default=45)
    parser.add_argument("--element-timeout", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    result = run_acceptance(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2 if result.get("error_code") == "AUTHORIZATION_INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
