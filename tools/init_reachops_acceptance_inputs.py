# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT_DIR / "tools" / "reachops_acceptance_inputs.example.ps1"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "tools" / "reachops_acceptance_inputs.local.ps1"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


CONTROL_CHAR_ESCAPES = {
    "\a": r"\a",
    "\b": r"\b",
    "\f": r"\f",
    "\n": r"\n",
    "\r": r"\r",
    "\t": r"\t",
    "\v": r"\v",
}


def normalize_cli_value(value: str) -> str:
    text = str(value)
    for char, replacement in CONTROL_CHAR_ESCAPES.items():
        text = text.replace(char, replacement)
    return text


def ps_quote(value: str) -> str:
    escaped = normalize_cli_value(value).replace("`", "``").replace('"', '`"')
    return f'"{escaped}"'


def set_input_value(content: str, name: str, value: str) -> str:
    if not str(value or "").strip():
        return content
    pattern = re.compile(rf"(?m)^\s*\${re.escape(name)}\s*=.*$")
    normalized = str(value).strip().lower()
    literal = normalized if normalized in {"$true", "$false"} else ps_quote(value)
    replacement = f"${name} = {literal}"
    return pattern.sub(lambda _match: replacement, content)


def build_content(args: argparse.Namespace, base_path: Path | None = None) -> str:
    if base_path and base_path.exists():
        content = base_path.read_text(encoding="utf-8")
    else:
        if not TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"Template missing: {TEMPLATE_PATH}")
        content = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "ProfileGroup": args.profile_group,
        "ProfileIds": args.profile_ids,
        "Target": args.target,
        "CommentVideoUrl": args.comment_video_url,
        "FollowProfileUrl": args.follow_profile_url,
        "DmProfileUrl": args.dm_profile_url,
        "TargetUsername": args.target_username,
        "ActivationStatusPath": args.activation_status_path,
        "ConfirmAuthorizedTargets": "$true" if bool(getattr(args, "confirm_authorized_targets", False)) else "",
    }
    for name, value in replacements.items():
        content = set_input_value(content, name, value)
    return content


def inspect_written_inputs(path: Path) -> dict:
    try:
        from tools.reachops_live_acceptance_status import inspect_local_inputs, local_input_field_status

        status = inspect_local_inputs(path)
        return {
            "path": str(path),
            "exists": bool(status.get("exists")),
            "usable": bool(status.get("usable")),
            "authorization_confirmed": bool(status.get("authorization_confirmed")),
            "missing_fields": list(status.get("missing_fields") or []),
            "placeholder_fields": list(status.get("placeholder_fields") or []),
            "field_status": local_input_field_status(status),
        }
    except Exception as exc:
        return {
            "path": str(path),
            "exists": path.exists(),
            "usable": False,
            "error": str(exc),
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the local ReachOps live-acceptance input file from the safe template."
    )
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--profile-group", default="")
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--target", default="")
    parser.add_argument("--comment-video-url", default="")
    parser.add_argument("--follow-profile-url", default="")
    parser.add_argument("--dm-profile-url", default="")
    parser.add_argument("--target-username", default="")
    parser.add_argument("--activation-status-path", default="")
    parser.add_argument(
        "--confirm-authorized-targets",
        action="store_true",
        help="Set ConfirmAuthorizedTargets=$true only after all TikTok targets are explicitly authorized.",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update an existing local input file in place, preserving values not supplied on this command.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing local input file.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = Path(args.output_path)
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    if output_path.exists() and not (args.force or args.update_existing):
        message = (
            f"{output_path} already exists. Review it directly, or rerun with --force only after "
            "backing up real authorized targets, or use --update-existing to set only supplied fields."
        )
        if args.json:
            import json

            print(json.dumps({"status": "exists", "created": False, "path": str(output_path), "error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_content(args, base_path=output_path if args.update_existing else None), encoding="utf-8")
    local_inputs = inspect_written_inputs(output_path)
    result = {
        "status": "updated" if args.update_existing and output_path.exists() else "created",
        "created": not args.update_existing,
        "updated": bool(args.update_existing),
        "path": str(output_path),
        "no_browser_started": True,
        "no_submit": True,
        "local_inputs": local_inputs,
        "verification_commands": [
            "python tools\\reachops_live_acceptance_status.py --write-report --json",
            "python tools\\reachops_client_delivery_check.py --json",
            "python tools\\reachops_delivery_package_check.py --json",
            "python tools\\reachops_final_acceptance_gate.py --json",
        ],
        "next_required_actions": [
            "打开 tools\\reachops_acceptance_inputs.local.ps1，替换所有占位值。",
            "填入已授权 TikTok 视频链接 CommentVideoUrl。",
            "填入已授权 TikTok 用户主页链接 FollowProfileUrl/DmProfileUrl。",
            "填入目标用户名 TargetUsername。",
            "生成或放置真实激活状态文件，并设置 ActivationStatusPath。",
            "确认目标已授权后使用 --confirm-authorized-targets。",
        ],
    }
    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"[ReachOpsInputs] Wrote {output_path}")
        print("[ReachOpsInputs] Fill only authorized TikTok targets and a real activation status path.")
        print("[ReachOpsInputs] Validate without opening a browser or submitting actions:")
        print("python tools\\reachops_live_acceptance_status.py --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
