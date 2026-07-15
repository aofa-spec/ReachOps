# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.group_refresh_failure_probe.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_group_refresh_failure_probe.json",
    profile_group: str = "United States",
    injected_error: str = "ixBrowser Local API 读取超时",
    injected_error_detail: str = "profile_group_list_timeout_after_10s",
) -> dict[str, Any]:
    started = time.monotonic()
    attempts = [
        {
            "attempt": 1,
            "status": "failed",
            "error_code": "GROUP_REFRESH_FAILURE",
            "error": injected_error,
            "error_detail": injected_error_detail,
            "started_browser": False,
        },
        {
            "attempt": 2,
            "status": "failed",
            "error_code": "GROUP_REFRESH_FAILURE",
            "error": injected_error,
            "error_detail": injected_error_detail,
            "started_browser": False,
        },
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": "blocked_by_environment",
        "terminal_state": "BLOCKED",
        "terminal_reason_code": "GROUP_REFRESH_FAILURE",
        "error_code": "GROUP_REFRESH_FAILURE",
        "profile_group": str(profile_group or ""),
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": True,
            "failure_code": "GROUP_REFRESH_FAILURE",
            "safe_no_submit": True,
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": False,
        },
        "group_refresh": {
            "attempted": True,
            "refresh_attempt_count": len(attempts),
            "max_refresh_retries": 1,
            "retry_count": 1,
            "bounded_retry_policy_enforced": True,
            "attempts": attempts,
        },
        "summary": {
            "errors": {"GROUP_REFRESH_FAILURE": 1},
            "refresh_attempt_count": len(attempts),
            "max_refresh_retries": 1,
        },
        "outputs": {"json": str(Path(output).expanduser())},
        "next_action": "Start ixBrowser Local API, refresh profile groups, then retry before launching collection.",
        "wall_clock_seconds": round(max(0.0, time.monotonic() - started), 3),
        "bounded_exit": True,
    }
    write_report(output, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded no-submit group refresh failure probe.")
    parser.add_argument("--output", default="/tmp/reachops_group_refresh_failure_probe.json")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--inject-error", default="ixBrowser Local API 读取超时")
    parser.add_argument("--inject-error-detail", default="profile_group_list_timeout_after_10s")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(
        output=args.output,
        profile_group=args.profile_group,
        injected_error=args.inject_error,
        injected_error_detail=args.inject_error_detail,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
