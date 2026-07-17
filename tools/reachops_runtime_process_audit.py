# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_run_session_takeover import DEFAULT_BASE_DIR, DEFAULT_LATEST_SESSION_PATH, build_takeover_report


RUNTIME_PROCESS_AUDIT_SCHEMA_VERSION = "reachops.runtime_process_audit.v1"
RUNTIME_PROCESS_CLEANUP_CONFIRMATION = "CLEANUP_RUNTIME_PROCESSES"


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
    try:
        completed = runner(
            ["ps", "-axo", "pid=,ppid=,stat=,etime=,command="],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in str(getattr(completed, "stdout", "") or "").splitlines():
        row = _parse_process_line(line)
        if row:
            rows.append(row)
    return rows


def _classify_process(row: dict[str, Any]) -> str:
    command = str(row.get("command") or "")
    lower = command.lower()
    if "--protected-userid=" in lower:
        return "ixbrowser_profile"
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


def _profile_id_from_command(command: str) -> str:
    match = re.search(r"--protected-userid=(\d+)", str(command or ""))
    return match.group(1) if match else ""


def _safe_process_row(row: dict[str, Any], classification: str) -> dict[str, Any]:
    return {
        "pid": int(row.get("pid") or 0),
        "ppid": int(row.get("ppid") or 0),
        "stat": str(row.get("stat") or ""),
        "etime": str(row.get("etime") or ""),
        "classification": classification,
        "profile_id": _profile_id_from_command(str(row.get("command") or "")),
        "command": str(row.get("command") or "")[:500],
    }


def _cleanup_item(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "pid": int(item.get("pid") or 0),
        "ppid": int(item.get("ppid") or 0),
        "classification": str(item.get("classification") or ""),
        "reason": reason,
        "signal": "SIGTERM",
        "command": str(item.get("command") or "")[:500],
    }


def _profile_cleanup_item(profile_id: str, rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    pids = sorted({int(row.get("pid") or 0) for row in rows if int(row.get("pid") or 0) > 0})
    return {
        "pid": 0,
        "ppid": 0,
        "profile_id": str(profile_id or ""),
        "profile_process_pids": pids[:20],
        "profile_process_count": len(pids),
        "classification": "ixbrowser_profile",
        "reason": reason,
        "signal": "IXBROWSER_CLOSE_PROFILE",
        "command": f"ixBrowser close_profile profile_id={profile_id}",
    }


def _profile_ids_from_value(value: Any, *, profile_context: bool = False) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").lower()
            if key_text in {"profile_id", "profileid"}:
                text = str(item or "")
                if text.isdigit():
                    ids.add(text)
            elif key_text in {"profile_ids", "profileids", "attempted_profiles"}:
                ids.update(_profile_ids_from_value(item, profile_context=True))
            else:
                ids.update(_profile_ids_from_value(item, profile_context=False))
        return ids
    if isinstance(value, list):
        for item in value:
            ids.update(_profile_ids_from_value(item, profile_context=profile_context))
        return ids
    text = str(value or "")
    if not text:
        return ids
    for match in re.finditer(r"--protected-userid=(\d+)", text):
        ids.add(match.group(1))
    for match in re.finditer(r"\bprofile_ids?=([0-9][0-9, ]*)", text):
        for token in re.split(r"[,\s]+", match.group(1)):
            if token.isdigit():
                ids.add(token)
    if profile_context and text.isdigit() and 4 <= len(text) <= 12:
        ids.add(text)
    return ids


def collect_runtime_profile_ids(*, latest_session_path: Path, base_dir: Path) -> list[str]:
    ids: set[str] = set()
    candidates = [
        Path(latest_session_path),
        Path(base_dir) / "reachops_web_ui_last_run.json",
        Path(base_dir) / "logs" / "growth_ops_runtime.log",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".json":
                try:
                    ids.update(_profile_ids_from_value(json.loads(text)))
                    continue
                except Exception:
                    pass
            ids.update(_profile_ids_from_value(text[-120000:]))
        except Exception:
            continue
    return sorted(ids, key=lambda item: (len(item), item))


def build_cleanup_plan(
    *,
    orphan_chromedrivers: list[dict[str, Any]],
    detached_reachops_clients: list[dict[str, Any]],
    stale_launchers: list[dict[str, Any]],
    ixbrowser_profile_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for item in ixbrowser_profile_candidates or []:
        profile_id = str(item.get("profile_id") or "").strip()
        if profile_id:
            plan.append(_profile_cleanup_item(profile_id, list(item.get("processes") or []), "runtime_ixbrowser_profile_candidate"))
    for item in orphan_chromedrivers:
        plan.append(_cleanup_item(item, "orphan_chromedriver_candidate"))
    for item in detached_reachops_clients:
        plan.append(_cleanup_item(item, "detached_reachops_client_process"))
    for item in stale_launchers:
        plan.append(_cleanup_item(item, "stale_native_client_launcher"))
    seen_pids: set[int] = set()
    seen_profiles: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in plan:
        if str(item.get("classification") or "") == "ixbrowser_profile":
            profile_id = str(item.get("profile_id") or "")
            if not profile_id or profile_id in seen_profiles:
                continue
            seen_profiles.add(profile_id)
            deduped.append(item)
            continue
        pid = int(item.get("pid") or 0)
        if pid <= 0 or pid in seen_pids:
            continue
        seen_pids.add(pid)
        deduped.append(item)
    return deduped


def apply_cleanup_plan(
    cleanup_plan: list[dict[str, Any]],
    *,
    apply: bool = False,
    confirm: str = "",
    process_terminator: Any = None,
    profile_closer: Any = None,
    sleep_seconds: float = 0.05,
) -> dict[str, Any]:
    if not apply:
        return {
            "schema_version": "reachops.runtime_process_cleanup.v1",
            "status": "dry_run",
            "applied": False,
            "confirmation_required": RUNTIME_PROCESS_CLEANUP_CONFIRMATION,
            "candidate_count": len(cleanup_plan),
            "attempted": [],
            "no_process_killed": True,
        }
    if str(confirm or "") != RUNTIME_PROCESS_CLEANUP_CONFIRMATION:
        return {
            "schema_version": "reachops.runtime_process_cleanup.v1",
            "status": "confirmation_required",
            "applied": False,
            "confirmation_required": RUNTIME_PROCESS_CLEANUP_CONFIRMATION,
            "candidate_count": len(cleanup_plan),
            "attempted": [],
            "no_process_killed": True,
        }
    terminator = process_terminator or os.kill
    attempted: list[dict[str, Any]] = []
    for item in cleanup_plan:
        if str(item.get("classification") or "") == "ixbrowser_profile":
            profile_id = str(item.get("profile_id") or "").strip()
            if not profile_id:
                continue
            row = dict(item)
            row["attempted"] = True
            try:
                closer = profile_closer
                if closer is None:
                    from ReachOps.adapters.browser_manager import get_workbench_browser_adapter

                    closer = get_workbench_browser_adapter().force_close_profile
                closer(profile_id, str(item.get("reason") or "runtime_cleanup"))
                row["ok"] = True
                row["error"] = ""
            except Exception as exc:
                row["ok"] = False
                row["error"] = str(exc)
            attempted.append(row)
            continue
        pid = int(item.get("pid") or 0)
        if pid <= 0:
            continue
        row = dict(item)
        row["attempted"] = True
        try:
            terminator(pid, signal.SIGTERM)
            if sleep_seconds > 0:
                time.sleep(float(sleep_seconds))
            row["ok"] = not _pid_running(pid) if process_terminator is None else True
            row["error"] = "" if row["ok"] else "process_still_running_after_sigterm"
        except ProcessLookupError:
            row["ok"] = True
            row["error"] = "process_already_exited"
        except PermissionError as exc:
            row["ok"] = False
            row["error"] = f"permission_denied:{exc}"
        except OSError as exc:
            row["ok"] = False
            row["error"] = str(exc)
        attempted.append(row)
    failed = [row for row in attempted if not row.get("ok")]
    return {
        "schema_version": "reachops.runtime_process_cleanup.v1",
        "status": "completed" if not failed else "partial_failed",
        "applied": True,
        "confirmation_required": RUNTIME_PROCESS_CLEANUP_CONFIRMATION,
        "candidate_count": len(cleanup_plan),
        "attempted_count": len(attempted),
        "failed_count": len(failed),
        "attempted": attempted,
        "no_process_killed": False,
    }


def build_runtime_process_audit(
    *,
    process_rows: list[dict[str, Any]] | None = None,
    latest_session_path: Path = DEFAULT_LATEST_SESSION_PATH,
    base_dir: Path = DEFAULT_BASE_DIR,
    command_runner: Any = None,
    apply_cleanup: bool = False,
    confirm_cleanup: str = "",
    process_terminator: Any = None,
    profile_closer: Any = None,
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
    runtime_profile_ids = collect_runtime_profile_ids(
        latest_session_path=Path(latest_session_path),
        base_dir=Path(base_dir),
    )
    runtime_profile_id_set = set(runtime_profile_ids)

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
    ixbrowser_profile_processes = [
        item
        for item in relevant
        if item["classification"] == "ixbrowser_profile"
        and str(item.get("profile_id") or "") in runtime_profile_id_set
    ]
    ixbrowser_profile_candidates: list[dict[str, Any]] = []
    for profile_id in runtime_profile_ids:
        processes = [item for item in ixbrowser_profile_processes if str(item.get("profile_id") or "") == profile_id]
        if not processes:
            continue
        ixbrowser_profile_candidates.append(
            {
                "profile_id": profile_id,
                "process_count": len(processes),
                "pids": sorted(int(item.get("pid") or 0) for item in processes if int(item.get("pid") or 0) > 0)[:20],
                "processes": processes,
            }
        )
    blockers: list[str] = []
    if ixbrowser_profile_candidates:
        blockers.append("runtime_ixbrowser_profile_candidates_present")
    if orphan_chromedrivers:
        blockers.append("orphan_chromedriver_candidates_present")
    if detached_reachops_clients:
        blockers.append("detached_reachops_client_processes_present")
    if len(stale_launchers) > 1:
        blockers.append("multiple_native_client_launchers_present")
    if session_pid and not session_pid_running and str(takeover.get("status") or "") == "needs_recovery":
        blockers.append("latest_run_session_needs_recovery")

    cleanup_plan = build_cleanup_plan(
        orphan_chromedrivers=orphan_chromedrivers,
        detached_reachops_clients=detached_reachops_clients,
        stale_launchers=stale_launchers,
        ixbrowser_profile_candidates=ixbrowser_profile_candidates,
    )
    cleanup_result = apply_cleanup_plan(
        cleanup_plan,
        apply=apply_cleanup,
        confirm=confirm_cleanup,
        process_terminator=process_terminator,
        profile_closer=profile_closer,
    )
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
        "runtime_profile_ids": runtime_profile_ids,
        "runtime_profile_id_count": len(runtime_profile_ids),
        "ixbrowser_profile_candidates": ixbrowser_profile_candidates,
        "ixbrowser_profile_candidate_count": len(ixbrowser_profile_candidates),
        "orphan_chromedriver_candidates": orphan_chromedrivers,
        "orphan_chromedriver_candidate_count": len(orphan_chromedrivers),
        "detached_reachops_client_processes": detached_reachops_clients,
        "detached_reachops_client_process_count": len(detached_reachops_clients),
        "stale_native_client_launchers": stale_launchers,
        "stale_native_client_launcher_count": len(stale_launchers),
        "blocker_codes": blockers,
        "cleanup_plan": cleanup_plan,
        "cleanup_candidate_count": len(cleanup_plan),
        "cleanup_confirmation_required": RUNTIME_PROCESS_CLEANUP_CONFIRMATION,
        "cleanup_result": cleanup_result,
        "read_only": not apply_cleanup,
        "no_process_killed": bool(cleanup_result.get("no_process_killed")),
        "no_browser_started": True,
        "no_submit": True,
        "no_ai_token_used": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ReachOps runtime processes without mutating local state.")
    parser.add_argument("--latest-session-path", default=str(DEFAULT_LATEST_SESSION_PATH))
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--apply", action="store_true", help="Apply cleanup to candidate stale/orphan local ReachOps processes.")
    parser.add_argument("--confirm", default="", help=f"Required confirmation token for --apply: {RUNTIME_PROCESS_CLEANUP_CONFIRMATION}")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_runtime_process_audit(
        latest_session_path=Path(args.latest_session_path),
        base_dir=Path(args.base_dir),
        apply_cleanup=bool(args.apply),
        confirm_cleanup=str(args.confirm or ""),
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
