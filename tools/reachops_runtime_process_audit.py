# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_run_session_takeover import DEFAULT_BASE_DIR, DEFAULT_LATEST_SESSION_PATH, build_takeover_report


RUNTIME_PROCESS_AUDIT_SCHEMA_VERSION = "reachops.runtime_process_audit.v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_process_line(line: str) -> dict[str, Any]:
    parts = str(line or "").strip().split(None, 4)
    if len(parts) < 5:
        return {}
    try:
        pid = int(parts[0])
        ppid = int(parts[1])
    except ValueError:
        return {}
    return {
        "pid": pid,
        "ppid": ppid,
        "stat": parts[2],
        "etime": parts[3],
        "command": parts[4],
    }


def _read_process_rows(command_runner: Any = None) -> list[dict[str, Any]]:
    runner = command_runner or subprocess.run
    completed = runner(
        ["ps", "-axo", "pid=,ppid=,stat=,etime=,command="],
        text=True,
        capture_output=True,
        check=False,
    )
    rows: list[dict[str, Any]] = []
    for line in str(getattr(completed, "stdout", "") or "").splitlines():
        row = _parse_process_line(line)
        if row:
            rows.append(row)
    return rows


def _classify_process(row: dict[str, Any]) -> str:
    command = str(row.get("command") or "")
    lower = command.lower()
    if "chromedriver" in lower:
        return "chromedriver"
    if "ixbrowser.app" in lower or "/ixbrowser" in lower:
        return "ixbrowser"
    if "reachopsapp.py" in lower:
        return "reachops_native_client"
    if "run_reachops_headless_macos.py" in lower:
        return "reachops_headless_runner"
    if "启动reachops原生macui.command" in lower:
        return "reachops_native_client_launcher"
    if "selenium" in lower:
        return "selenium"
    if "reachops" in lower:
        return "reachops_other"
    return ""


def _safe_process_row(row: dict[str, Any], classification: str) -> dict[str, Any]:
    return {
        "pid": int(row.get("pid") or 0),
        "ppid": int(row.get("ppid") or 0),
        "stat": str(row.get("stat") or ""),
        "etime": str(row.get("etime") or ""),
        "classification": classification,
        "command": str(row.get("command") or "")[:500],
    }


def build_runtime_process_audit(
    *,
    process_rows: list[dict[str, Any]] | None = None,
    latest_session_path: Path = DEFAULT_LATEST_SESSION_PATH,
    base_dir: Path = DEFAULT_BASE_DIR,
    command_runner: Any = None,
) -> dict[str, Any]:
    rows = list(process_rows) if process_rows is not None else _read_process_rows(command_runner=command_runner)
    takeover, _rc = build_takeover_report(latest_session_path=Path(latest_session_path), recover=False)
    session_pid = int(takeover.get("pid") or 0)
    session_pid_running = bool(takeover.get("pid_running")) if session_pid else False
    by_pid = {int(row.get("pid") or 0): row for row in rows if int(row.get("pid") or 0)}
    relevant: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in rows:
        classification = _classify_process(row)
        if not classification:
            continue
        counts[classification] = int(counts.get(classification, 0) or 0) + 1
        relevant.append(_safe_process_row(row, classification))

    orphan_chromedrivers = [
        item
        for item in relevant
        if item["classification"] == "chromedriver"
        and int(item.get("ppid") or 0) == 1
        and int(item.get("pid") or 0) != session_pid
    ]
    detached_reachops_clients = [
        item
        for item in relevant
        if item["classification"] in {"reachops_native_client", "reachops_headless_runner"}
        and session_pid
        and int(item.get("pid") or 0) != session_pid
    ]
    stale_launchers = [
        item
        for item in relevant
        if item["classification"] == "reachops_native_client_launcher"
        and int(item.get("pid") or 0) != int((by_pid.get(session_pid) or {}).get("ppid") or 0)
    ]
    blockers: list[str] = []
    if orphan_chromedrivers:
        blockers.append("orphan_chromedriver_candidates_present")
    if detached_reachops_clients:
        blockers.append("detached_reachops_client_processes_present")
    if len(stale_launchers) > 1:
        blockers.append("multiple_native_client_launchers_present")
    if session_pid and not session_pid_running and str(takeover.get("status") or "") == "needs_recovery":
        blockers.append("latest_run_session_needs_recovery")

    status = "attention_required" if blockers else "ok"
    return {
        "schema_version": RUNTIME_PROCESS_AUDIT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "base_dir": str(base_dir),
        "latest_session_path": str(latest_session_path),
        "run_session_takeover": takeover,
        "session_pid": session_pid,
        "session_pid_running": session_pid_running,
        "process_count": len(rows),
        "relevant_process_count": len(relevant),
        "process_counts": counts,
        "relevant_processes": relevant,
        "orphan_chromedriver_candidates": orphan_chromedrivers,
        "orphan_chromedriver_candidate_count": len(orphan_chromedrivers),
        "detached_reachops_client_processes": detached_reachops_clients,
        "detached_reachops_client_process_count": len(detached_reachops_clients),
        "stale_native_client_launchers": stale_launchers,
        "stale_native_client_launcher_count": len(stale_launchers),
        "blocker_codes": blockers,
        "read_only": True,
        "no_process_killed": True,
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ReachOps runtime processes without mutating local state.")
    parser.add_argument("--latest-session-path", default=str(DEFAULT_LATEST_SESSION_PATH))
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_runtime_process_audit(
        latest_session_path=Path(args.latest_session_path),
        base_dir=Path(args.base_dir),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(
            f"{report['status']} relevant={report['relevant_process_count']} "
            f"orphan_chromedrivers={report['orphan_chromedriver_candidate_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
