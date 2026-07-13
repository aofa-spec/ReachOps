# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.authorization_gate import LiveSubmitAuthorizationGate
from tools.reachops_live_submit_acceptance import normalize_username, split_csv, username_from_profile_url, validate_authorization


def is_tiktok_url(value: str, *, video: bool = False, profile: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text.startswith(("https://www.tiktok.com/", "https://tiktok.com/")):
        return False
    if video and "/video/" not in text:
        return False
    if profile and "/@" not in text:
        return False
    return True


def build_action(action_type: str, target_url: str, target_username: str) -> dict[str, Any]:
    return {
        "id": f"readiness_{action_type}",
        "action_type": action_type,
        "target_url": target_url,
        "source_path": target_url if action_type == "comment_reply" else "",
        "target_username": target_username,
    }


def activation_status_path(args) -> str:
    explicit = str(getattr(args, "activation_status_path", "") or "").strip()
    if explicit:
        return str(Path(explicit).expanduser())
    return RuntimePaths.build().activation_status_path


def check_authorization(args, status_path: str) -> list[dict[str, Any]]:
    gate = LiveSubmitAuthorizationGate(status_path)
    profile_id = split_csv(args.profile_ids)[0] if split_csv(args.profile_ids) else ""
    profile = {"profile_id": profile_id, "group_name": str(args.group_name or "")}
    target_username = normalize_username(args.target_username)
    actions = [
        build_action("comment_reply", args.video_url, target_username),
        build_action("follow_review", args.follow_profile_url, target_username),
        build_action("dm_review", args.dm_profile_url, target_username),
    ]
    decisions = []
    for action in actions:
        decision = gate.authorize_live_submit(action, profile, feature="live_submit")
        decisions.append(
            {
                "action_type": action["action_type"],
                "allowed": bool(decision.allowed),
                "error_code": decision.error_code,
                "error_message": decision.error_message,
                "evidence": decision.evidence,
            }
        )
    return decisions


def execution_evidence_policy() -> dict[str, Any]:
    return {
        "require_execution_evidence": True,
        "accept_fixture_uri": False,
        "local_file_requirements": [
            "screenshot_file_exists",
            "screenshot_file_non_empty",
            "sidecar_json_exists",
            "sidecar_screenshot_sha256_matches_file",
            "sidecar_action_type_matches_action",
            "sidecar_profile_id_present",
            "sidecar_action_id_present",
            "sidecar_current_url_present",
        ],
        "failure_error_code": "LIVE_SUBMIT_EVIDENCE_MISSING",
    }


def run_readiness(args) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, **evidence):
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    authorization_errors = validate_authorization(args)
    add("live_submit_parameters", not authorization_errors, errors=authorization_errors)

    profile_ids = split_csv(args.profile_ids)
    add("profile_ids_present", bool(profile_ids), profile_ids=profile_ids)
    non_numeric_profile_ids = [profile_id for profile_id in profile_ids if not str(profile_id).isdigit()]
    add("profile_ids_are_ixbrowser_numeric_ids", bool(profile_ids) and not non_numeric_profile_ids, profile_ids=profile_ids, non_numeric_profile_ids=non_numeric_profile_ids)
    add("comment_video_url_valid", is_tiktok_url(args.video_url, video=True), video_url=args.video_url)
    add("follow_profile_url_valid", is_tiktok_url(args.follow_profile_url, profile=True), follow_profile_url=args.follow_profile_url)
    add("dm_profile_url_valid", is_tiktok_url(args.dm_profile_url, profile=True), dm_profile_url=args.dm_profile_url)

    target = normalize_username(args.target_username)
    follow_user = normalize_username(username_from_profile_url(args.follow_profile_url))
    dm_user = normalize_username(username_from_profile_url(args.dm_profile_url))
    add("target_username_matches_profiles", bool(target and follow_user == target and dm_user == target), target_username=target, follow_user=follow_user, dm_user=dm_user)

    status_path = activation_status_path(args)
    status_file = Path(status_path)
    activation_required = LiveSubmitAuthorizationGate.activation_required()
    add(
        "activation_status_file_exists_or_not_required",
        (status_file.exists() and status_file.is_file()) or not activation_required,
        activation_status_path=str(status_file),
        activation_required=activation_required,
        runtime_mode=LiveSubmitAuthorizationGate.runtime_mode(),
    )

    authorization_decisions = check_authorization(args, str(status_file)) if status_file.exists() or not activation_required else []
    if authorization_decisions:
        add("activation_allows_live_submit_actions", all(item["allowed"] for item in authorization_decisions), decisions=authorization_decisions)
    else:
        add("activation_allows_live_submit_actions", False, decisions=authorization_decisions)
    evidence_policy = execution_evidence_policy()
    add(
        "execution_evidence_policy_required",
        bool(evidence_policy.get("require_execution_evidence") and evidence_policy.get("failure_error_code") == "LIVE_SUBMIT_EVIDENCE_MISSING"),
        policy=evidence_policy,
    )

    ready = all(item["passed"] for item in checks)
    return {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "no_browser_started": True,
        "no_submit": True,
        "profile_ids": profile_ids,
        "activation_status_path": str(status_file),
        "runtime_mode": LiveSubmitAuthorizationGate.runtime_mode(),
        "activation_required": activation_required,
        "development_bypass": not activation_required,
        "execution_evidence_policy": evidence_policy,
        "checks": checks,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Check ReachOps live-submit readiness without opening browser or submitting actions.")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--group-name", default="")
    parser.add_argument("--video-url", default="")
    parser.add_argument("--follow-profile-url", default="")
    parser.add_argument("--dm-profile-url", default="")
    parser.add_argument("--target-username", default="")
    parser.add_argument("--confirm-authorized-targets", default="")
    parser.add_argument("--activation-status-path", default="")
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    result = run_readiness(parse_args())
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
