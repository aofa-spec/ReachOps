# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import socket
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


def find_unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def refresh_groups_via_local_api(*, api_target: str, api_port: int) -> int:
    old_target = os.environ.get("REACHOPS_IXBROWSER_API_TARGET")
    old_port = os.environ.get("REACHOPS_IXBROWSER_API_PORT")
    os.environ["REACHOPS_IXBROWSER_API_TARGET"] = str(api_target or "127.0.0.1")
    os.environ["REACHOPS_IXBROWSER_API_PORT"] = str(int(api_port))
    try:
        from ReachOps.workbench.standalone_app import create_ixbrowser_client, extract_ixbrowser_rows, require_ixbrowser_response

        client = create_ixbrowser_client()
        response = require_ixbrowser_response(client, client.get_group_list(page=1, limit=100), "ixbrowser_get_group_list")
        rows, _total = extract_ixbrowser_rows(response)
        return len(rows)
    finally:
        if old_target is None:
            os.environ.pop("REACHOPS_IXBROWSER_API_TARGET", None)
        else:
            os.environ["REACHOPS_IXBROWSER_API_TARGET"] = old_target
        if old_port is None:
            os.environ.pop("REACHOPS_IXBROWSER_API_PORT", None)
        else:
            os.environ["REACHOPS_IXBROWSER_API_PORT"] = old_port


def build_real_local_api_disconnect_attempts(
    *,
    api_target: str,
    api_port: int,
    group_refresh_func=None,
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    refresher = group_refresh_func or refresh_groups_via_local_api
    for attempt in range(1, 3):
        started = time.monotonic()
        try:
            group_count = int(refresher(api_target=api_target, api_port=api_port) or 0)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "unexpected_success",
                    "error_code": "",
                    "error": "",
                    "error_detail": f"group_count={group_count}",
                    "started_browser": False,
                    "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                }
            )
            break
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "error_code": "GROUP_REFRESH_FAILURE",
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "error_detail": f"ixbrowser_local_api_unavailable target={api_target}:{api_port}",
                    "started_browser": False,
                    "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                }
            )
    return attempts


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_group_refresh_failure_probe.json",
    profile_group: str = "United States",
    injected_error: str = "ixBrowser Local API 读取超时",
    injected_error_detail: str = "profile_group_list_timeout_after_10s",
    real_local_api_disconnect: bool = False,
    api_target: str = "127.0.0.1",
    api_port: int = 0,
    group_refresh_func=None,
) -> dict[str, Any]:
    started = time.monotonic()
    resolved_api_port = int(api_port or 0)
    if real_local_api_disconnect:
        if resolved_api_port <= 0:
            resolved_api_port = find_unused_local_port()
        attempts = build_real_local_api_disconnect_attempts(
            api_target=api_target,
            api_port=resolved_api_port,
            group_refresh_func=group_refresh_func,
        )
    else:
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
    failed_attempts = [row for row in attempts if row.get("error_code") == "GROUP_REFRESH_FAILURE"]
    terminal_reason_code = "GROUP_REFRESH_FAILURE" if failed_attempts else "GROUP_REFRESH_UNEXPECTED_SUCCESS"
    status = "blocked_by_environment" if failed_attempts else "failed"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": status,
        "terminal_state": "BLOCKED" if failed_attempts else "FAILED",
        "terminal_reason_code": terminal_reason_code,
        "error_code": terminal_reason_code,
        "profile_group": str(profile_group or ""),
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": not bool(real_local_api_disconnect),
            "failure_code": "GROUP_REFRESH_FAILURE",
            "safe_no_submit": True,
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": bool(real_local_api_disconnect and failed_attempts),
        },
        "group_refresh": {
            "attempted": True,
            "refresh_attempt_count": len(attempts),
            "max_refresh_retries": 1,
            "retry_count": 1,
            "bounded_retry_policy_enforced": True,
            "attempts": attempts,
            "real_local_api_disconnect": bool(real_local_api_disconnect),
            "api_target": str(api_target or "127.0.0.1"),
            "api_port": resolved_api_port if real_local_api_disconnect else 0,
        },
        "summary": {
            "errors": {"GROUP_REFRESH_FAILURE": 1} if failed_attempts else {"GROUP_REFRESH_UNEXPECTED_SUCCESS": 1},
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
    parser.add_argument("--real-local-api-disconnect", action="store_true")
    parser.add_argument("--api-target", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=0, help="Use 0 with --real-local-api-disconnect to pick an unused local port.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(
        output=args.output,
        profile_group=args.profile_group,
        injected_error=args.inject_error,
        injected_error_detail=args.inject_error_detail,
        real_local_api_disconnect=bool(args.real_local_api_disconnect),
        api_target=args.api_target,
        api_port=args.api_port,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
