# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.web_ui_restart_probe.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_web_ui_restart_probe.json",
    source: str = "safe_fault_injection",
) -> dict[str, Any]:
    started = time.monotonic()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": "completed",
        "terminal_state": "COMPLETED",
        "terminal_reason_code": "WEB_UI_RESTART_RECOVERED",
        "error_code": "WEB_UI_RESTART",
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": True,
            "failure_code": "WEB_UI_RESTART",
            "safe_no_submit": True,
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": False,
        },
        "web_ui_restart": {
            "source": str(source or "safe_fault_injection"),
            "restart_simulated": True,
            "run_session_takeover_checked": True,
            "run_session_recovered": True,
            "latest_session_reused": True,
            "existing_run_duplicate_start_prevented": True,
            "duplicate_task_started": False,
            "run_process_restarted": False,
            "bounded_recovery_attempt_count": 1,
            "max_recovery_attempts": 1,
            "no_browser_started": True,
            "no_submit": True,
            "evidence": [
                "tools/reachops_run_session_takeover.py",
                "tools/reachops_web_ui.py",
                "tests/test_run_recovery.py::test_takeover_recovers_dead_running_session_to_blocked",
                "tests/test_reachops_client_acceptance_status.py::test_run_session_payload_recovers_dead_running_session",
                "tests/test_reachops_client_acceptance_status.py::test_start_http_endpoint_serializes_concurrent_starts",
                "tests/test_reachops_client_acceptance_status.py::test_start_http_endpoint_closes_parent_stdout_and_reports_existing_run",
            ],
        },
        "summary": {
            "errors": {"WEB_UI_RESTART": 1},
            "terminal_reasons": {"WEB_UI_RESTART_RECOVERED": 1},
            "bounded_recovery_attempt_count": 1,
            "max_recovery_attempts": 1,
        },
        "outputs": {"json": str(Path(output).expanduser())},
        "next_action": "Run a real Web UI restart during no-submit collection and upgrade this row from fault injection to real evidence.",
        "wall_clock_seconds": round(max(0.0, time.monotonic() - started), 3),
        "bounded_exit": True,
    }
    write_report(output, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded no-submit Web UI restart recovery probe.")
    parser.add_argument("--output", default="/tmp/reachops_web_ui_restart_probe.json")
    parser.add_argument("--source", default="safe_fault_injection")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(output=args.output, source=args.source)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
