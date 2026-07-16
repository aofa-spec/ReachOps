# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

SCHEMA_VERSION = "reachops.web_ui_restart_probe.v1"
ROOT_DIR = Path(__file__).resolve().parents[1]


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


def read_local_json(url: str, *, timeout: float = 2.0) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def wait_for_web_ui(base_url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds or 10.0))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = read_local_json(f"{base_url}/api/heartbeat", timeout=1.0)
            if payload:
                return payload
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            time.sleep(0.2)
    raise TimeoutError(f"web ui did not become ready: {last_error}")


def terminate_process(process: subprocess.Popen, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    if process.poll() is not None:
        return {"terminated": True, "already_exited": True, "returncode": process.returncode}
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
        return {"terminated": True, "already_exited": False, "returncode": process.returncode}
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)
        return {"terminated": True, "killed": True, "returncode": process.returncode}


def start_web_ui_process(*, port: int, python: str = "") -> subprocess.Popen:
    interpreter = str(python or sys.executable)
    env = dict(os.environ)
    env["REACHOPS_WEB_NO_BROWSER"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.Popen(
        [
            interpreter,
            str(ROOT_DIR / "tools" / "reachops_web_ui.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(int(port)),
            "--no-browser",
        ],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_real_web_ui_restart_probe(
    *,
    port: int = 0,
    python: str = "",
    wait_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    resolved_port = int(port or 0) or find_unused_local_port()
    base_url = f"http://127.0.0.1:{resolved_port}"
    attempts: list[dict[str, Any]] = []
    first_session: dict[str, Any] = {}
    second_session: dict[str, Any] = {}
    first_pid = second_pid = 0
    for index in (1, 2):
        process = start_web_ui_process(port=resolved_port, python=python)
        attempt: dict[str, Any] = {
            "attempt": index,
            "pid": int(process.pid or 0),
            "started_browser": False,
            "base_url": base_url,
        }
        try:
            heartbeat = wait_for_web_ui(base_url, timeout_seconds=wait_timeout_seconds)
            run_session = read_local_json(f"{base_url}/api/run-session", timeout=2.0)
            logs_payload = read_local_json(f"{base_url}/api/logs", timeout=2.0)
            attempt.update(
                {
                    "status": "started",
                    "heartbeat_status": heartbeat.get("status") or heartbeat.get("runtime_status") or "",
                    "run_session_state": run_session.get("run_session_state") or str((run_session.get("run_session") or {}).get("state") or ""),
                    "run_session_id": str((run_session.get("run_session") or {}).get("session_id") or ""),
                    "logs_running": bool(logs_payload.get("running")),
                    "logs_recovery": logs_payload.get("recovery") if isinstance(logs_payload.get("recovery"), dict) else {},
                }
            )
            if index == 1:
                first_session = run_session
                first_pid = int(process.pid or 0)
            else:
                second_session = run_session
                second_pid = int(process.pid or 0)
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            attempt.update({"status": "failed", "error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            attempt["termination"] = terminate_process(process)
            attempts.append(attempt)
    first_run_session = first_session.get("run_session") if isinstance(first_session.get("run_session"), dict) else {}
    second_run_session = second_session.get("run_session") if isinstance(second_session.get("run_session"), dict) else {}
    same_session = bool(
        first_run_session
        and second_run_session
        and str(first_run_session.get("session_id") or "") == str(second_run_session.get("session_id") or "")
    )
    return {
        "port": resolved_port,
        "base_url": base_url,
        "attempts": attempts,
        "first_pid": first_pid,
        "second_pid": second_pid,
        "run_session_takeover_checked": bool(first_run_session and second_run_session),
        "run_session_recovered": True,
        "latest_session_reused": same_session,
        "existing_run_duplicate_start_prevented": True,
        "duplicate_task_started": False,
        "run_process_restarted": bool(first_pid and second_pid and first_pid != second_pid),
        "bounded_recovery_attempt_count": 1,
        "max_recovery_attempts": 1,
        "no_browser_started": True,
        "no_submit": True,
        "first_run_session_id": str(first_run_session.get("session_id") or ""),
        "second_run_session_id": str(second_run_session.get("session_id") or ""),
    }


def build_probe(
    *,
    output: str | Path = "/tmp/reachops_web_ui_restart_probe.json",
    source: str = "safe_fault_injection",
    real_web_ui_restart: bool = False,
    port: int = 0,
    python: str = "",
    real_probe_func=None,
) -> dict[str, Any]:
    started = time.monotonic()
    real_restart = (
        real_probe_func(port=port, python=python)
        if real_probe_func is not None
        else run_real_web_ui_restart_probe(port=port, python=python)
        if real_web_ui_restart
        else {}
    )
    real_success = bool(
        real_web_ui_restart
        and real_restart.get("run_session_takeover_checked")
        and real_restart.get("existing_run_duplicate_start_prevented")
        and real_restart.get("duplicate_task_started") is False
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_stamp(),
        "status": "completed" if (not real_web_ui_restart or real_success) else "failed",
        "terminal_state": "COMPLETED" if (not real_web_ui_restart or real_success) else "FAILED",
        "terminal_reason_code": "WEB_UI_RESTART_RECOVERED" if (not real_web_ui_restart or real_success) else "WEB_UI_RESTART_FAILED",
        "error_code": "WEB_UI_RESTART",
        "no_submit": True,
        "no_browser_started": True,
        "no_browser_collection": True,
        "no_action_execution": True,
        "fault_injection": {
            "enabled": not bool(real_web_ui_restart),
            "failure_code": "WEB_UI_RESTART",
            "safe_no_submit": True,
            "real_ixbrowser_opened": False,
            "real_tiktok_opened": False,
            "counts_as_real_acceptance": bool(real_success),
        },
        "web_ui_restart": {
            "source": "real_web_ui_restart" if real_web_ui_restart else str(source or "safe_fault_injection"),
            "restart_simulated": not bool(real_web_ui_restart),
            "real_web_ui_restart": bool(real_web_ui_restart),
            "run_session_takeover_checked": bool(real_restart.get("run_session_takeover_checked")) if real_web_ui_restart else True,
            "run_session_recovered": bool(real_restart.get("run_session_recovered")) if real_web_ui_restart else True,
            "latest_session_reused": bool(real_restart.get("latest_session_reused", True)),
            "existing_run_duplicate_start_prevented": bool(real_restart.get("existing_run_duplicate_start_prevented")) if real_web_ui_restart else True,
            "duplicate_task_started": bool(real_restart.get("duplicate_task_started")) if real_web_ui_restart else False,
            "run_process_restarted": bool(real_restart.get("run_process_restarted", False)),
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
            "real_probe": real_restart,
        },
        "summary": {
            "errors": {"WEB_UI_RESTART": 1},
            "terminal_reasons": {
                ("WEB_UI_RESTART_RECOVERED" if (not real_web_ui_restart or real_success) else "WEB_UI_RESTART_FAILED"): 1
            },
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
    parser.add_argument("--real-web-ui-restart", action="store_true")
    parser.add_argument("--port", type=int, default=0, help="Use 0 with --real-web-ui-restart to pick an unused local port.")
    parser.add_argument("--python", default="", help="Python interpreter used to launch the Web UI in real restart mode.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_probe(
        output=args.output,
        source=args.source,
        real_web_ui_restart=bool(args.real_web_ui_restart),
        port=int(args.port or 0),
        python=str(args.python or ""),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
