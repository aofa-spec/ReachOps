# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.workbench.device_identity import DeviceIdentity


def build_template(args) -> dict[str, Any]:
    current_device_id = DeviceIdentity.current_device_id()
    expires_at = str(getattr(args, "expires_at", "") or "").strip()
    if not expires_at:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=max(1, int(args.days)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "template_only": True,
        "active": bool(getattr(args, "active", False)),
        "device_id": current_device_id if bool(getattr(args, "bind_current_device", False)) else "",
        "expires_at": expires_at,
        "license_tier": str(getattr(args, "license_tier", "") or "enterprise"),
        "capabilities": {
            "live_submit": bool(getattr(args, "enable_live_submit", False)),
            "comment_reply": bool(getattr(args, "enable_comment_reply", False)),
            "follow_review": bool(getattr(args, "enable_follow_review", False)),
            "dm_review": bool(getattr(args, "enable_dm_review", False)),
        },
        "generated_by": "reachops_activation_status_template",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "current_device_id": current_device_id,
        "operator_notes": "Remove template_only only after the activation server/operator has approved this device and target scope.",
    }


def output_path(args) -> Path:
    explicit = str(getattr(args, "output", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path(RuntimePaths.build().config_dir) / "reachops_activation_status.template.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a ReachOps activation status JSON template without authorizing live submit.")
    parser.add_argument("--output", default="", help="Output path. Defaults to the ReachOps runtime config template path.")
    parser.add_argument("--write", action="store_true", help="Write the template to --output. Without this flag the template is printed only.")
    parser.add_argument("--active", action="store_true", help="Set active=true in the template.")
    parser.add_argument("--bind-current-device", action="store_true", help="Set device_id to the current ReachOps device id.")
    parser.add_argument("--enable-live-submit", action="store_true")
    parser.add_argument("--enable-comment-reply", action="store_true")
    parser.add_argument("--enable-follow-review", action="store_true")
    parser.add_argument("--enable-dm-review", action="store_true")
    parser.add_argument("--license-tier", default="enterprise")
    parser.add_argument("--expires-at", default="", help="Explicit ISO timestamp, for example 2999-01-01T00:00:00Z.")
    parser.add_argument("--days", type=int, default=7, help="Template expiry offset when --expires-at is omitted.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_template(args)
    path = output_path(args)
    result = {
        "status": "written" if args.write else "preview",
        "no_browser_started": True,
        "no_submit": True,
        "template_only": True,
        "output_path": str(path),
        "activation_status": payload,
    }
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
