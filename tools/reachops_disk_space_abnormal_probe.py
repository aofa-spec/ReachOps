# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.disk_space_abnormal_probe.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_disk_space_abnormal_probe.json",
    check_path: str | Path = "/tmp",
    required_free_bytes: int = 0,
) -> dict[str, Any]:
    started = time.monotonic()
    target_path = Path(check_path).expanduser()
    target_path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(target_path))
    required = int(required_free_bytes or 0)
    if required <= 0:
        required = int(usage.free) + 1
    abnormal = int(usage.free) < required
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": "blocked_by_environment" if abnormal else "passed",
        "terminal_state": "BLOCKED" if abnormal else "COMPLETED",
        "terminal_reason_code": "DISK_SPACE_ABNORMAL" if abnormal else "DISK_SPACE_OK",
        "error_code": "DISK_SPACE_ABNORMAL" if abnormal else "",
        "check_path": str(target_path),
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": True,
            "failure_code": "DISK_SPACE_ABNORMAL",
            "safe_no_submit": True,
            "real_disk_usage_checked": True,
            "required_free_bytes_injected": required_free_bytes <= 0,
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": False,
        },
        "disk_space": {
            "check_attempt_count": 1,
            "max_check_retries": 0,
            "bounded_retry_policy_enforced": True,
            "disk_usage_checked": True,
            "abnormal_observed": bool(abnormal),
            "prelaunch_block_enforced": bool(abnormal),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "required_free_bytes": required,
            "free_bytes_below_required": bool(abnormal),
            "bytes_short": max(0, required - int(usage.free)),
        },
        "summary": {
            "errors": {"DISK_SPACE_ABNORMAL": 1} if abnormal else {},
            "check_attempt_count": 1,
            "max_check_retries": 0,
            "free_bytes": int(usage.free),
            "required_free_bytes": required,
        },
        "outputs": {"json": str(Path(output).expanduser())},
        "next_action": "Keep disk-space checks prelaunch and block before browser/profile start when free space is below policy.",
        "wall_clock_seconds": round(max(0.0, time.monotonic() - started), 3),
        "bounded_exit": True,
    }
    write_report(output, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded no-submit disk space abnormal probe.")
    parser.add_argument("--output", default="/tmp/reachops_disk_space_abnormal_probe.json")
    parser.add_argument("--check-path", default="/tmp")
    parser.add_argument("--required-free-bytes", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(
        output=args.output,
        check_path=args.check_path,
        required_free_bytes=int(args.required_free_bytes or 0),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("error_code") == "DISK_SPACE_ABNORMAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
