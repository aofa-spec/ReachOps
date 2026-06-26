# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
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


def username_from_profile_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if "/@" not in value:
        return ""
    return value.rsplit("/@", 1)[-1].split("/", 1)[0].lstrip("@")


def dm_profile_url(args) -> str:
    explicit = str(getattr(args, "dm_profile_url", "") or "").strip()
    return explicit or str(getattr(args, "profile_url", "") or "").strip()


def validate_preflight_inputs(args) -> list[str]:
    errors: list[str] = []
    profile_ids = split_csv(getattr(args, "profile_ids", ""))
    if not profile_ids:
        errors.append("--profile-ids must include at least one profile id")
    non_numeric_profile_ids = [profile_id for profile_id in profile_ids if not str(profile_id).isdigit()]
    if non_numeric_profile_ids:
        errors.append(f"--profile-ids must be ixBrowser numeric profile ids: {', '.join(non_numeric_profile_ids)}")
    if not str(getattr(args, "video_url", "") or "").strip():
        errors.append("--video-url is required")
    if not str(getattr(args, "profile_url", "") or "").strip():
        errors.append("--profile-url is required")
    if not dm_profile_url(args):
        errors.append("--dm-profile-url is required")
    target_username = str(getattr(args, "target_username", "") or "").strip().lstrip("@").lower()
    profile_username = username_from_profile_url(getattr(args, "profile_url", "")).lower()
    dm_username = username_from_profile_url(dm_profile_url(args)).lower()
    if not target_username and not profile_username:
        errors.append("--target-username is required when --profile-url does not contain /@username")
    if target_username and profile_username and target_username != profile_username:
        errors.append(f"target username mismatch: profile={profile_username}, username={target_username}")
    if target_username and dm_username and target_username != dm_username:
        errors.append(f"target username mismatch: dm_profile={dm_username}, username={target_username}")
    return errors


def blocked_preflight_result(args, errors: list[str]) -> dict:
    profile_ids = split_csv(getattr(args, "profile_ids", ""))
    return {
        "status": "blocked",
        "ready": False,
        "base_dir": str(getattr(args, "base_dir", "")),
        "profiles": [{"profile_id": profile_id, "group_name": str(getattr(args, "group_name", "") or "")} for profile_id in profile_ids],
        "errors": errors,
        "missing_preflight_action_types": ["comment_reply", "dm_review", "follow_review"],
        "preflight_action_statuses": {"comment_reply": [], "dm_review": [], "follow_review": []},
        "no_browser_started": True,
        "no_submit": True,
        "preflight_only": True,
    }


def seed_preflight_actions(service: GrowthIntelligenceService, video_url: str, profile_url: str, dm_url: str, target_username: str) -> list[str]:
    specs = [
        ("comment_reply", video_url, "Preflight only comment text for @{username}"),
        ("follow_review", profile_url, "Preflight only follow review for @{username}"),
        ("dm_review", dm_url, "Preflight only DM text for @{username}"),
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


def safe_name(value: str) -> str:
    text = str(value or "").strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return cleaned[:80] or "unknown"


def write_preflight_evidence_files(base_dir: Path, results: list[dict], target_urls: dict[str, str]) -> dict[str, list[dict]]:
    evidence_dir = base_dir / "evidence" / "preflight"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_by_action: dict[str, list[dict]] = {"comment_reply": [], "follow_review": [], "dm_review": []}
    for index, row in enumerate(results, start=1):
        action_type = str(row.get("action_type") or "")
        action_id = str(row.get("action_id") or "")
        execution_id = str(row.get("execution_id") or "")
        profile_id = str(row.get("profile_id") or "")
        status = str(row.get("status") or "")
        error_code = str(row.get("error_code") or "")
        file_name = "_".join(
            [
                f"{index:03d}",
                safe_name(action_type),
                safe_name(profile_id),
                safe_name(execution_id or action_id),
            ]
        )
        path = evidence_dir / f"{file_name}.json"
        payload = {
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "kind": "reachops_live_preflight_evidence",
            "preflight_only": True,
            "no_submit": True,
            "action_type": action_type,
            "action_id": action_id,
            "execution_id": execution_id,
            "profile_id": profile_id,
            "status": status,
            "error_code": error_code,
            "error_message": str(row.get("error_message") or ""),
            "target_url": str(target_urls.get(action_type) or ""),
            "evidence_path": str(row.get("evidence_path") or ""),
            "screenshot_available": False,
            "screenshot_unavailable_reason": "browser_driver_not_available" if error_code == "PROFILE_START_FAILED" else "preflight_sidecar_only",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["payload_sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        detail = {
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "action_type": action_type,
            "profile_id": profile_id,
            "status": status,
            "error_code": error_code,
            "screenshot_available": False,
        }
        row["evidence_file_path"] = str(path)
        evidence_by_action.setdefault(action_type, []).append(detail)
    return evidence_by_action


def classify_environment_issue(error_code: str, error_message: str) -> list[str]:
    code = str(error_code or "").upper()
    message = str(error_message or "").lower()
    classifications: list[str] = []
    if code == "PROFILE_START_FAILED":
        classifications.append("profile_start_failed")
    if "proxy detection failed" in message:
        classifications.append("proxy_detection_failed")
    if "socks5 authentication failed" in message or "socks authentication failed" in message:
        classifications.append("socks5_auth_failed")
    if "no module named 'modules'" in message or 'no module named "modules"' in message:
        classifications.append("legacy_adapter_missing")
    if code == "PROXY_FAILED" or "err_proxy" in message or "tunnel connection failed" in message:
        classifications.append("proxy_failed")
    if code == "LOGIN_REQUIRED":
        classifications.append("login_required")
    if code == "CAPTCHA_DETECTED":
        classifications.append("captcha_detected")
    return classifications


def build_environment_diagnostics(results: list[dict], profiles: list[dict], no_browser_started: bool = False) -> dict:
    attempted_profile_ids = sorted(
        {
            str(row.get("profile_id") or "")
            for row in results
            if str(row.get("profile_id") or "")
        }
    )
    configured_profile_ids = [
        str(profile.get("profile_id") or profile.get("id") or "")
        for profile in profiles
        if str(profile.get("profile_id") or profile.get("id") or "")
    ]
    ready_profile_ids = sorted(
        {
            str(row.get("profile_id") or "")
            for row in results
            if str(row.get("status") or "") == "success" and str(row.get("profile_id") or "")
        }
    )
    profile_failures: dict[str, dict] = {}
    error_counts: dict[str, int] = {}
    classification_counts: dict[str, int] = {}
    account_switches: list[dict] = []
    for row in results:
        profile_id = str(row.get("profile_id") or "")
        status = str(row.get("status") or "")
        error_code = str(row.get("error_code") or "")
        error_message = str(row.get("error_message") or "")
        if status == "account_switched":
            account_switches.append(
                {
                    "profile_id": profile_id,
                    "next_profile_id": str(row.get("next_profile_id") or ""),
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )
            continue
        if status == "success" or not profile_id:
            continue
        if error_code:
            error_counts[error_code] = error_counts.get(error_code, 0) + 1
        classes = classify_environment_issue(error_code, error_message)
        for item in classes:
            classification_counts[item] = classification_counts.get(item, 0) + 1
        entry = profile_failures.setdefault(
            profile_id,
            {
                "profile_id": profile_id,
                "attempts": 0,
                "error_codes": [],
                "classifications": [],
                "last_error_code": "",
                "last_error_message": "",
            },
        )
        entry["attempts"] += 1
        if error_code and error_code not in entry["error_codes"]:
            entry["error_codes"].append(error_code)
        for item in classes:
            if item not in entry["classifications"]:
                entry["classifications"].append(item)
        if error_code:
            entry["last_error_code"] = error_code
        if error_message:
            entry["last_error_message"] = error_message

    failed_profile_ids = sorted(profile_failures.keys())
    blocking_stage = ""
    if classification_counts.get("profile_start_failed"):
        blocking_stage = "ixbrowser_open_profile"
    elif classification_counts.get("proxy_failed") or classification_counts.get("proxy_detection_failed"):
        blocking_stage = "network_proxy"
    elif classification_counts.get("login_required"):
        blocking_stage = "tiktok_login"
    elif classification_counts.get("captcha_detected"):
        blocking_stage = "tiktok_captcha"
    elif no_browser_started:
        blocking_stage = "input_validation"

    next_required_actions: list[str] = []
    if classification_counts.get("socks5_auth_failed") or classification_counts.get("proxy_detection_failed"):
        next_required_actions.append("Fix ixBrowser profile proxy credentials and pass ixBrowser proxy detection.")
    if classification_counts.get("legacy_adapter_missing"):
        next_required_actions.append("Install or repair the legacy ixBrowser adapter module used by fallback startup.")
    if classification_counts.get("profile_start_failed"):
        next_required_actions.append("Open each selected numeric profile in ixBrowser before rerunning live preflight.")
    if classification_counts.get("login_required"):
        next_required_actions.append("Log in to TikTok for the selected profiles.")
    if classification_counts.get("captcha_detected"):
        next_required_actions.append("Resolve TikTok captcha for the selected profiles.")
    if no_browser_started:
        next_required_actions.append("Provide complete live preflight inputs before starting browser validation.")

    return {
        "status": "ready" if ready_profile_ids else ("blocked" if failed_profile_ids or no_browser_started else "unknown"),
        "blocking_stage": blocking_stage,
        "configured_profile_ids": configured_profile_ids,
        "attempted_profile_ids": attempted_profile_ids,
        "ready_profile_ids": ready_profile_ids,
        "failed_profile_ids": failed_profile_ids,
        "error_counts": dict(sorted(error_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "profile_failures": [profile_failures[key] for key in failed_profile_ids],
        "account_switches": account_switches,
        "next_required_actions": next_required_actions,
        "no_browser_started": bool(no_browser_started),
        "no_submit": True,
    }


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
    input_errors = validate_preflight_inputs(args)
    if input_errors:
        result = blocked_preflight_result(args, input_errors)
        result["environment_diagnostics"] = build_environment_diagnostics(
            [],
            result.get("profiles") or [],
            no_browser_started=True,
        )
        return result

    base_dir = Path(args.base_dir)
    service = GrowthIntelligenceService(base_dir=str(base_dir))
    workflow = GrowthWorkflowService(service)
    username = str(args.target_username or "").strip() or username_from_profile_url(args.profile_url)
    action_ids = seed_preflight_actions(service, args.video_url, args.profile_url, dm_profile_url(args), username)
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
    target_urls = {
        "comment_reply": str(args.video_url or ""),
        "follow_review": str(args.profile_url or ""),
        "dm_review": dm_profile_url(args),
    }
    evidence_file_details = write_preflight_evidence_files(base_dir, results, target_urls)
    environment_diagnostics = build_environment_diagnostics(results, profiles)
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
                "evidence_file_path": str(row.get("evidence_file_path") or ""),
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
        "status": "completed",
        "ready": True,
        "base_dir": str(base_dir),
        "seeded_action_ids": action_ids,
        "profiles": profiles,
        "summary": summary,
        "preflight_action_statuses": preflight_action_statuses,
        "missing_preflight_action_types": missing_preflight_action_types,
        "target_urls": target_urls,
        "evidence_file_details": evidence_file_details,
        "environment_diagnostics": environment_diagnostics,
        "no_submit": True,
        "preflight_only": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="ReachOps live account preflight without submitting comment/follow/dm actions.")
    parser.add_argument("--base-dir", default="reports/reachops/live_preflight")
    parser.add_argument("--profile-ids", default="", help="Comma/semicolon separated ixBrowser profile ids.")
    parser.add_argument("--group-name", default="")
    parser.add_argument("--video-url", default="")
    parser.add_argument("--profile-url", default="")
    parser.add_argument("--dm-profile-url", default="", help="Optional DM profile URL. Defaults to --profile-url when omitted.")
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
    return 0 if str(result.get("status") or "") != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
