# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ReachOps.run_recovery import recover_interrupted_run_session, should_recover_interrupted_run
from ReachOps.run_session import build_session_health, read_run_session, write_run_session


DEFAULT_BASE_DIR = ROOT_DIR / "reports" / "reachops" / "mac_gui" / "runtime"
DEFAULT_LATEST_SESSION_PATH = DEFAULT_BASE_DIR / "runs" / "latest_run_session.json"
DEFAULT_RESULT_PATH = DEFAULT_BASE_DIR / "reachops_web_ui_last_run.json"


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _result_path_for(session: dict[str, Any], default_path: Path) -> Path:
    checkpoint = session.get("checkpoint") if isinstance(session.get("checkpoint"), dict) else {}
    evidence = session.get("evidence") if isinstance(session.get("evidence"), dict) else {}
    value = checkpoint.get("result_path") or evidence.get("result_path") or str(default_path)
    return Path(str(value))


def _session_archive_path(session: dict[str, Any], latest_path: Path) -> Path:
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        return latest_path
    return latest_path.parent / f"{session_id}.json"


def build_takeover_report(
    *,
    latest_session_path: Path = DEFAULT_LATEST_SESSION_PATH,
    default_result_path: Path = DEFAULT_RESULT_PATH,
    recover: bool = False,
) -> tuple[dict[str, Any], int]:
    latest_session_path = Path(latest_session_path)
    default_result_path = Path(default_result_path)
    session = read_run_session(latest_session_path)
    if not session:
        return (
            {
                "schema_version": "reachops.run_session_takeover.v1",
                "status": "missing",
                "latest_session_path": str(latest_session_path),
                "exists": latest_session_path.exists(),
                "recovered": False,
                "no_browser_started": True,
                "no_submit": True,
            },
            0,
        )

    pid = int(session.get("pid") or 0)
    running = _pid_running(pid)
    result_path = _result_path_for(session, default_result_path)
    run_result = _read_json(result_path)
    needs_recovery = should_recover_interrupted_run(session, running=running, run_result=run_result)
    health = build_session_health(session, running=running)
    recovery: dict[str, Any] = {"recovered": False}

    if needs_recovery and recover:
        updated, recovery = recover_interrupted_run_session(
            session,
            running=running,
            run_result=run_result,
            last_stage="RUN_SESSION_TAKEOVER_RECOVERY",
            pid=pid,
        )
        archive_path = _session_archive_path(updated, latest_session_path)
        write_run_session(updated, archive_path, latest_session_path)
        result = recovery.get("result") if isinstance(recovery.get("result"), dict) else {}
        if result:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        session = updated
        health = build_session_health(session, running=False)

    status = "recovered_interrupted" if recovery.get("recovered") else "needs_recovery" if needs_recovery else health["status"]
    report = {
        "schema_version": "reachops.run_session_takeover.v1",
        "status": status,
        "latest_session_path": str(latest_session_path),
        "result_path": str(result_path),
        "session_id": str(session.get("session_id") or ""),
        "plan_id": str(session.get("plan_id") or ""),
        "state": str(session.get("state") or ""),
        "pid": pid,
        "pid_running": running,
        "health": health,
        "needs_recovery": needs_recovery,
        "recovered": bool(recovery.get("recovered")),
        "recovery": recovery,
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
    }
    return report, 2 if needs_recovery else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and optionally recover the latest ReachOps RunSession.")
    parser.add_argument("--latest-session-path", default=str(DEFAULT_LATEST_SESSION_PATH))
    parser.add_argument("--result-path", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report, rc = build_takeover_report(
        latest_session_path=Path(args.latest_session_path),
        default_result_path=Path(args.result_path),
        recover=bool(args.recover),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"{report['status']} state={report.get('state') or '-'} pid={report.get('pid') or 0}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
