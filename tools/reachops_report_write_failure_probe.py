# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "reachops.report_write_failure_probe.v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_failed_report_path(output: str | Path) -> Path:
    base = Path(output).expanduser().parent / "reachops_report_write_failure_readonly"
    base.mkdir(parents=True, exist_ok=True)
    return base / "blocked_report.json"


def _attempt_failed_write(path: Path) -> tuple[dict[str, Any], bool]:
    started = time.monotonic()
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = path.parent.stat().st_mode & 0o777
    chmod_applied = False
    try:
        try:
            os.chmod(path.parent, 0o500)
            chmod_applied = True
        except OSError:
            chmod_applied = False
        try:
            path.write_text('{"status":"should_not_write"}\n', encoding="utf-8")
            return (
                {
                    "attempt": 1,
                    "status": "unexpected_success",
                    "error_code": "",
                    "error": "",
                    "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                    "target_path": str(path),
                    "readonly_dir_chmod_applied": chmod_applied,
                },
                False,
            )
        except OSError as exc:
            return (
                {
                    "attempt": 1,
                    "status": "failed",
                    "error_code": "REPORT_WRITE_FAILURE",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                    "target_path": str(path),
                    "readonly_dir_chmod_applied": chmod_applied,
                },
                True,
            )
    finally:
        try:
            os.chmod(path.parent, original_mode)
        except OSError:
            pass


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_report_write_failure_probe.json",
    failed_report_path: str | Path = "",
) -> dict[str, Any]:
    started = time.monotonic()
    failed_target = Path(failed_report_path).expanduser() if failed_report_path else _default_failed_report_path(output)
    attempt, failure_observed = _attempt_failed_write(failed_target)
    status = "blocked_by_environment" if failure_observed else "failed"
    terminal_reason_code = "REPORT_WRITE_FAILURE" if failure_observed else "REPORT_WRITE_FAILURE_PROBE_FAILED"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": status,
        "terminal_state": "BLOCKED" if failure_observed else "FAILED",
        "terminal_reason_code": terminal_reason_code,
        "error_code": "REPORT_WRITE_FAILURE" if failure_observed else "REPORT_WRITE_FAILURE_PROBE_FAILED",
        "failed_report_path": str(failed_target),
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": True,
            "failure_code": "REPORT_WRITE_FAILURE",
            "safe_no_submit": True,
            "real_report_write_failure_observed": bool(failure_observed),
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": False,
        },
        "report_write_failure": {
            "write_attempt_count": 1,
            "max_write_retries": 0,
            "bounded_retry_policy_enforced": True,
            "write_failure_observed": bool(failure_observed),
            "report_preserved_after_failure": True,
            "final_evidence_output_path": str(Path(output).expanduser()),
            "attempts": [attempt],
        },
        "summary": {
            "errors": {"REPORT_WRITE_FAILURE": 1} if failure_observed else {"REPORT_WRITE_FAILURE_PROBE_FAILED": 1},
            "write_attempt_count": 1,
            "max_write_retries": 0,
        },
        "outputs": {"json": str(Path(output).expanduser())},
        "next_action": "Keep report writes bounded and preserve RunSession/final evidence when REPORT_WRITE_FAILURE occurs.",
        "wall_clock_seconds": round(max(0.0, time.monotonic() - started), 3),
        "bounded_exit": True,
    }
    write_report(output, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded no-submit report write failure probe.")
    parser.add_argument("--output", default="/tmp/reachops_report_write_failure_probe.json")
    parser.add_argument("--failed-report-path", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(output=args.output, failed_report_path=args.failed_report_path)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("error_code") == "REPORT_WRITE_FAILURE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
