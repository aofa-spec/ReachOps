# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from tools.reachops_activation_status_check import check_activation_status
from tools.reachops_live_readiness import is_tiktok_url, normalize_username, username_from_profile_url


def configure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def configure_localhost_proxy_bypass():
    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    entries = [item.strip() for item in existing.split(",") if item.strip()]
    for item in ["127.0.0.1", "localhost", "::1"]:
        if item not in entries:
            entries.append(item)
    value = ",".join(entries)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def normalize_ixbrowser_profile(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": str(row.get("profile_id") or row.get("id") or ""),
        "name": str(row.get("name") or row.get("profile_name") or row.get("title") or ""),
        "group_id": str(row.get("group_id") or ""),
        "group_name": str(row.get("group_name") or row.get("group_title") or ""),
    }


def load_profile_snapshot_direct(max_pages: int = 50, group_name: str = "", profile_limit: int = 20) -> dict[str, Any]:
    try:
        configure_localhost_proxy_bypass()
        from ixbrowser_local_api import IXBrowserClient

        client = IXBrowserClient()
        wanted = str(group_name or "").strip().lower()
        groups = []
        selected_group = None
        for page in range(1, max(1, int(max_pages or 50)) + 1):
            batch = client.get_group_list(page=page, limit=100) or []
            groups.extend(batch)
            for group in batch:
                title = str(group.get("title") or group.get("group_name") or group.get("name") or "").strip()
                if wanted and title.lower() == wanted:
                    selected_group = group
                    break
            if selected_group or len(batch) < 100:
                break
        group_id = selected_group.get("id") if selected_group else None
        profile_kwargs = {"page": 1, "limit": max(1, min(100, int(profile_limit or 20)))}
        if group_id is not None:
            profile_kwargs["group_id"] = group_id
        profiles = [normalize_ixbrowser_profile(row) for row in (client.get_profile_list(**profile_kwargs) or [])]
        group_rows = [
            {
                "group_id": str(group.get("id") or ""),
                "group_name": str(group.get("title") or group.get("group_name") or group.get("name") or ""),
                "count": int(group.get("count") or group.get("profile_count") or 0),
            }
            for group in groups
        ]
        return {
            "available": True,
            "error": "",
            "profiles": profiles,
            "groups": group_rows[:50],
            "profile_count": len(profiles),
            "group_count": len(group_rows),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": f"{exc.__class__.__name__}: {exc}",
            "profiles": [],
            "groups": [],
            "profile_count": 0,
            "group_count": 0,
        }


def load_profile_snapshot(max_pages: int = 50, timeout_seconds: int = 8, group_name: str = "", profile_limit: int = 20) -> dict[str, Any]:
    try:
        env = dict(os.environ)
        existing = env.get("NO_PROXY") or env.get("no_proxy") or ""
        entries = [item.strip() for item in existing.split(",") if item.strip()]
        for item in ["127.0.0.1", "localhost", "::1"]:
            if item not in entries:
                entries.append(item)
        env["NO_PROXY"] = ",".join(entries)
        env["no_proxy"] = env["NO_PROXY"]
        output = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--profile-snapshot-worker",
                "--max-pages",
                str(max_pages),
                "--profile-group",
                str(group_name or ""),
                "--profile-limit",
                str(profile_limit or 20),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds or 8)),
            env=env,
        )
        stdout = output.stdout or ""
        stderr = output.stderr or ""
        if output.returncode == 0 and stdout.strip():
            payload = json.loads(stdout.strip().splitlines()[-1])
            if isinstance(payload, dict):
                return payload
        return {
            "available": False,
            "error": (stderr or stdout or f"profile snapshot worker failed: {output.returncode}").strip()[:500],
            "profiles": [],
            "groups": [],
            "profile_count": 0,
            "group_count": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "error": f"ixBrowser profile snapshot timed out after {max(1, int(timeout_seconds or 8))} seconds",
            "profiles": [],
            "groups": [],
            "profile_count": 0,
            "group_count": 0,
        }


def profile_matches_group(profile: dict[str, Any], group_name: str) -> bool:
    wanted = str(group_name or "").strip().lower()
    if not wanted:
        return True
    fields = [
        str(profile.get("profile_id") or ""),
        str(profile.get("id") or ""),
        str(profile.get("name") or ""),
        str(profile.get("profile_name") or ""),
        str(profile.get("title") or ""),
        str(profile.get("group_id") or ""),
        str(profile.get("group_name") or ""),
    ]
    return any(wanted in item.lower() for item in fields if item)


def select_numeric_profiles(snapshot: dict[str, Any], group_name: str, limit: int) -> list[dict[str, Any]]:
    rows = []
    for profile in snapshot.get("profiles") or []:
        profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
        if not profile_id.isdigit():
            continue
        if not profile_matches_group(profile, group_name):
            continue
        rows.append(
            {
                "profile_id": profile_id,
                "name": str(profile.get("name") or profile.get("profile_name") or profile.get("title") or ""),
                "group_id": str(profile.get("group_id") or ""),
                "group_name": str(profile.get("group_name") or ""),
            }
        )
        if len(rows) >= max(1, int(limit or 3)):
            break
    return rows


def build_powershell_command(script: str, params: dict[str, str | bool]) -> str:
    parts = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script,
    ]
    for key, value in params.items():
        if value is False or value is None:
            continue
        parts.append(f"-{key}")
        if value is True:
            continue
        escaped = str(value).replace("'", "''")
        parts.append(f"'{escaped}'")
    return " ".join(parts)


def build_manifest(args, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    explicit_profile_ids = split_csv(args.profile_ids)
    limit = max(1, int(getattr(args, "limit", 3) or 3))
    allow_pressure_submit = str(getattr(args, "allow_pressure_submit", "") or "").strip()
    if snapshot is None and explicit_profile_ids:
        snapshot = {
            "available": False,
            "error": "profile scan skipped because explicit ProfileIds were provided",
            "profiles": [],
            "groups": [],
            "profile_count": 0,
            "group_count": 0,
        }
    snapshot = snapshot if snapshot is not None else load_profile_snapshot(
        max_pages=int(args.max_pages or 50),
        timeout_seconds=int(args.profile_scan_timeout or 8),
        group_name=str(args.profile_group or ""),
        profile_limit=int(args.profile_limit or 3),
    )
    selected_profiles = select_numeric_profiles(snapshot, args.profile_group, int(args.profile_limit or 3))
    selected_profile_ids = explicit_profile_ids or [row["profile_id"] for row in selected_profiles]
    selected_profile_ids_csv = ",".join(selected_profile_ids)
    target_profile_url = str(args.target_profile_url or "").strip()
    dm_profile_url = str(args.dm_profile_url or target_profile_url).strip()
    target_username = normalize_username(args.target_username) or normalize_username(username_from_profile_url(target_profile_url))
    activation_status_path = str(args.activation_status_path or RuntimePaths.build().activation_status_path)
    activation_status = check_activation_status(activation_status_path, require_status_file=True)
    activation_ready = bool(activation_status.get("ready"))

    missing_inputs = []
    if not selected_profile_ids:
        missing_inputs.append("ixBrowser 数字 Profile ID")
    if not is_tiktok_url(args.comment_video_url, video=True):
        missing_inputs.append("已授权 TikTok 视频链接")
    if not is_tiktok_url(target_profile_url, profile=True):
        missing_inputs.append("已授权 TikTok 用户主页链接")
    if not target_username:
        missing_inputs.append("目标用户名")
    if not Path(activation_status_path).exists():
        missing_inputs.append("激活状态文件")
    elif not activation_ready:
        missing_inputs.append("有效激活状态文件")
    if str(args.confirm_authorized_targets or "").upper() != "YES":
        missing_inputs.append("授权确认 ConfirmAuthorizedTargets=YES")

    profile_group = str(args.profile_group or "")
    snapshot_groups = list(snapshot.get("groups") or [])
    selected_profile_count = len(selected_profile_ids)
    if profile_group and selected_profiles:
        wanted = profile_group.strip().lower()
        group_found = False
        patched_groups = []
        for group in snapshot_groups:
            item = dict(group)
            name = str(item.get("group_name") or "").strip().lower()
            if name == wanted:
                group_found = True
                item["selected_profile_count"] = len(selected_profiles)
                if int(item.get("count") or 0) == 0:
                    item["count"] = len(selected_profiles)
            patched_groups.append(item)
        if not group_found:
            patched_groups.append(
                {
                    "group_id": str(selected_profiles[0].get("group_id") or ""),
                    "group_name": profile_group,
                    "count": len(selected_profiles),
                    "selected_profile_count": len(selected_profiles),
                }
            )
        snapshot_groups = patched_groups
    blocking_summary = {
        "profile_ready": selected_profile_count > 0,
        "target_ready": bool(is_tiktok_url(args.comment_video_url, video=True) and is_tiktok_url(target_profile_url, profile=True) and target_username),
        "activation_ready": activation_ready,
        "authorization_confirmed": str(args.confirm_authorized_targets or "").upper() == "YES",
        "next_blocking_item": missing_inputs[0] if missing_inputs else "",
    }

    base_params = {
        "ProfileGroup": str(args.profile_group or ""),
        "ProfileIds": selected_profile_ids_csv,
        "CommentVideoUrl": str(args.comment_video_url or ""),
        "TargetProfileUrl": target_profile_url,
        "TargetUsername": target_username,
        "ActivationStatusPath": activation_status_path,
        "Limit": limit,
        "AllowPressureSubmit": allow_pressure_submit,
        "ConfirmAuthorizedTargets": str(args.confirm_authorized_targets or "").upper() == "YES",
    }
    readiness_command = build_powershell_command("tools\\run_reachops_live_readiness_windows.ps1", base_params)
    acceptance_params = {
        "ProfileGroup": str(args.profile_group or ""),
        "ProfileIds": selected_profile_ids_csv,
        "Target": str(args.target or "anti aging serum"),
        "CommentVideoUrl": str(args.comment_video_url or ""),
        "FollowProfileUrl": target_profile_url,
        "DmProfileUrl": dm_profile_url,
        "TargetUsername": target_username,
        "ActivationStatusPath": activation_status_path,
        "Limit": limit,
        "AllowPressureSubmit": allow_pressure_submit,
        "ConfirmAuthorizedTargets": str(args.confirm_authorized_targets or "").upper() == "YES",
        "RunLiveSubmit": bool(args.include_live_submit_command),
    }
    acceptance_command = build_powershell_command("tools\\run_reachops_acceptance_windows.ps1", acceptance_params)

    return {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "status": "ready_for_readiness_check" if not missing_inputs else "blocked",
        "no_browser_started": True,
        "no_submit": True,
        "profile_group": profile_group,
        "profile_snapshot": {
            "available": bool(snapshot.get("available")),
            "error": str(snapshot.get("error") or ""),
            "profile_count": int(snapshot.get("profile_count") or len(snapshot.get("profiles") or [])),
            "group_count": int(snapshot.get("group_count") or len(snapshot.get("groups") or [])),
            "groups": snapshot_groups[:20],
        },
        "selected_profiles": selected_profiles,
        "selected_profile_ids": selected_profile_ids,
        "selected_profile_count": selected_profile_count,
        "missing_inputs": missing_inputs,
        "blocking_summary": blocking_summary,
        "activation_status_path": activation_status_path,
        "activation_status": {
            "status": str(activation_status.get("status") or ""),
            "ready": activation_ready,
            "exists": bool(activation_status.get("activation_status_exists")),
            "checks": [
                {
                    "name": str(item.get("name") or ""),
                    "passed": bool(item.get("passed")),
                    "error_code": (
                        (((item.get("evidence") or {}).get("decisions") or [{}])[0] or {}).get("error_code", "")
                        if isinstance(item.get("evidence"), dict)
                        else ""
                    ),
                }
                for item in (activation_status.get("checks") or [])
                if isinstance(item, dict)
            ],
        },
        "commands": {
            "readiness_no_browser_no_submit": readiness_command,
            "acceptance_preflight": acceptance_command,
            "controlled_live_submit": acceptance_command if args.include_live_submit_command else "",
        },
        "operator_sequence": [
            "先运行 readiness_no_browser_no_submit，确认不启动浏览器、不提交动作。",
            "readiness ready 后运行 acceptance_preflight，验证页面预检和执行链路。",
            "确认授权目标无误后，才追加 -RunLiveSubmit 执行真实评论/关注/私信。",
        ],
        "safety_gates": [
            "Profile ID 必须是 ixBrowser 数字 ID。",
            "未传 ConfirmAuthorizedTargets=YES 时禁止真实提交。",
            "真实提交必须加载激活状态文件。",
            "真实提交必须生成截图证据和 sidecar。",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a ReachOps real-platform validation manifest without opening browser or submitting actions.")
    parser.add_argument("--profile-group", default="BR")
    parser.add_argument("--profile-ids", default="", help="Optional explicit ixBrowser numeric profile ids.")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--profile-scan-timeout", type=int, default=8)
    parser.add_argument("--target", default="anti aging serum")
    parser.add_argument("--comment-video-url", default="")
    parser.add_argument("--target-profile-url", default="")
    parser.add_argument("--dm-profile-url", default="")
    parser.add_argument("--target-username", default="")
    parser.add_argument("--activation-status-path", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--allow-pressure-submit", default="")
    parser.add_argument("--confirm-authorized-targets", default="")
    parser.add_argument("--include-live-submit-command", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    configure_localhost_proxy_bypass()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if "--profile-snapshot-worker" in raw_argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--profile-snapshot-worker", action="store_true")
        parser.add_argument("--max-pages", type=int, default=50)
        parser.add_argument("--profile-group", default="")
        parser.add_argument("--profile-limit", type=int, default=20)
        worker_args = parser.parse_args(raw_argv)
        print(json.dumps(load_profile_snapshot_direct(max_pages=worker_args.max_pages, group_name=worker_args.profile_group, profile_limit=worker_args.profile_limit), ensure_ascii=False, separators=(",", ":")))
        return 0
    manifest = build_manifest(parse_args(argv))
    if "--json" in sys.argv:
        print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not manifest.get("missing_inputs") else 2


if __name__ == "__main__":
    raise SystemExit(main())
