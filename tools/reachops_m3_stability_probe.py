# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json(stdout: str, stderr: str = "") -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines() + (stderr or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def split_profile_ids(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def build_real_flow_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "tools/run_reachops_real_flow_macos.py",
        "--profile-group",
        str(args.profile_group or ""),
        "--profile-ids",
        str(args.profile_ids or ""),
        "--profile-limit",
        str(max(1, int(args.profile_limit or 1))),
        "--profile-scan-limit",
        str(max(1, int(args.profile_scan_limit or args.profile_limit or 1))),
        "--max-attempt-batches",
        "1",
        "--max-sources",
        str(max(1, int(args.max_sources or 1))),
        "--max-videos",
        str(max(1, int(args.max_videos or 1))),
        "--max-comments",
        str(max(1, int(args.max_comments or 1))),
        "--profile-page-timeout",
        str(max(1, int(args.profile_page_timeout or 20))),
        "--profile-preflight-timeout",
        str(max(1, int(args.profile_preflight_timeout or 25))),
        "--scenario-timeout",
        str(max(1, int(args.scenario_timeout or 150))),
        "--max-profile-launches-per-day",
        str(max(0, int(args.max_profile_launches_per_day or 0))),
        "--target",
        str(args.target or ""),
        "--json",
    ]


def summarize_iteration(
    index: int,
    proc: subprocess.CompletedProcess[str],
    duration_seconds: float,
) -> dict[str, Any]:
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    payload = extract_json(stdout, stderr)
    acceptance = payload.get("acceptance") if isinstance(payload.get("acceptance"), dict) else {}
    scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), list) else []
    scenario = scenarios[0] if scenarios and isinstance(scenarios[0], dict) else {}
    return {
        "iteration": index,
        "returncode": int(proc.returncode or 0),
        "duration_seconds": round(float(duration_seconds), 3),
        "run_id": str(payload.get("run_id") or ""),
        "report_path": str(payload.get("report_path") or ""),
        "acceptance_status": str(acceptance.get("status") or ""),
        "no_submit": bool(acceptance.get("no_submit", payload.get("no_submit", True))),
        "scenario_status": str(scenario.get("status") or ""),
        "diagnosis_status": str(scenario.get("diagnosis_status") or ""),
        "browser_started": int(scenario.get("browser_started") or 0),
        "profile_preflight": scenario.get("profile_preflight") if isinstance(scenario.get("profile_preflight"), dict) else {},
        "funnel": scenario.get("funnel") if isinstance(scenario.get("funnel"), dict) else {},
        "no_action_reason": scenario.get("no_action_reason") if isinstance(scenario.get("no_action_reason"), dict) else {},
        "selected_profile_ids": list(payload.get("selected_profile_ids") or []),
        "usable_profile_ids": list(payload.get("usable_profile_ids") or []),
        "blocked_profile_ids": list(payload.get("blocked_profile_ids") or []),
        "daily_counts": (
            (payload.get("profile_launch_budget") or {}).get("daily_counts")
            if isinstance(payload.get("profile_launch_budget"), dict)
            else {}
        )
        or {},
        "stdout_tail": stdout.splitlines()[-3:],
        "stderr_tail": stderr.splitlines()[-5:],
    }


def iteration_passed(row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("returncode") or 0) == 0
        and row.get("acceptance_status") == "passed"
        and row.get("no_submit") is True
    )


def build_summary(
    args: argparse.Namespace,
    *,
    started_at: str,
    rows: list[dict[str, Any]],
    terminal: bool = False,
) -> dict[str, Any]:
    passed_count = sum(1 for row in rows if iteration_passed(row))
    failed_count = len(rows) - passed_count
    completed = bool(len(rows) >= int(args.iterations or 0) and failed_count == 0)
    summary = {
        "schema_version": "reachops.m3_probe_summary.v1",
        "started_at": started_at,
        "updated_at": utc_stamp(),
        "target": str(args.target or ""),
        "profile_group": str(args.profile_group or ""),
        "profile_ids": split_profile_ids(str(args.profile_ids or "")),
        "iterations_requested": int(args.iterations or 0),
        "iterations_completed": len(rows),
        "cooldown_seconds": max(0, int(getattr(args, "cooldown_seconds", 0) or 0)),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "terminal_state": "COMPLETED" if completed else "BLOCKED" if terminal else "RUNNING",
        "terminal_reason": "twenty_consecutive_real_no_submit_passed" if completed else "m3_probe_stopped_before_completion" if terminal else "",
        "clear_terminal_ratio": passed_count / len(rows) if rows else 0,
        "unauthorized_submit_count": sum(1 for row in rows if row.get("no_submit") is False),
        "rows": rows,
    }
    if terminal:
        summary["finished_at"] = utc_stamp()
    return summary


def run_probe(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if not hasattr(args, "print_progress"):
        args.print_progress = not bool(getattr(args, "quiet", False))
    profile_ids = split_profile_ids(str(args.profile_ids or ""))
    if not str(args.target or "").strip():
        summary = {
            "schema_version": "reachops.m3_probe_summary.v1",
            "terminal_state": "FAILED",
            "terminal_reason": "target_required",
            "iterations_requested": int(args.iterations or 0),
            "iterations_completed": 0,
            "passed_count": 0,
            "failed_count": 0,
            "rows": [],
        }
        return 3, summary
    if len(profile_ids) < 3 and not bool(args.allow_fewer_profiles):
        summary = {
            "schema_version": "reachops.m3_probe_summary.v1",
            "terminal_state": "BLOCKED",
            "terminal_reason": "insufficient_profile_ids_for_m3",
            "profile_ids": profile_ids,
            "iterations_requested": int(args.iterations or 0),
            "iterations_completed": 0,
            "passed_count": 0,
            "failed_count": 0,
            "rows": [],
        }
        return 2, summary
    out_dir = Path(args.output_dir or ROOT_DIR / "reports" / "reachops" / "mac_real_flow" / f"m3_probe_{safe_stamp()}").resolve()
    summary_path = out_dir / "m3_probe_summary.json"
    started_at = utc_stamp()
    rows: list[dict[str, Any]] = []
    command = build_real_flow_command(args)
    for index in range(1, int(args.iterations or 1) + 1):
        started = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(ROOT_DIR),
                text=True,
                capture_output=True,
                timeout=max(1, int(args.iteration_timeout or 210)),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            proc = subprocess.CompletedProcess(
                command,
                returncode=2,
                stdout=stdout,
                stderr=(stderr + "\niteration_timeout").strip(),
            )
        row = summarize_iteration(index, proc, time.time() - started)
        rows.append(row)
        write_json(summary_path, build_summary(args, started_at=started_at, rows=rows))
        if bool(args.print_progress):
            print(
                "M3 iteration "
                f"{index}/{int(args.iterations or 1)} status={row.get('acceptance_status')} "
                f"rc={row.get('returncode')} browser={row.get('browser_started')} "
                f"diagnosis={row.get('diagnosis_status')} duration={row.get('duration_seconds')}s",
                flush=True,
            )
        passed = iteration_passed(row)
        if not passed and not bool(args.continue_on_failure):
            break
        if index < int(args.iterations or 1):
            cooldown_seconds = max(0, int(getattr(args, "cooldown_seconds", 0) or 0))
            if cooldown_seconds:
                if bool(args.print_progress):
                    print(f"M3 cooldown {cooldown_seconds}s before next iteration", flush=True)
                time.sleep(cooldown_seconds)
    summary = build_summary(args, started_at=started_at, rows=rows, terminal=True)
    summary["summary_path"] = str(summary_path)
    write_json(summary_path, summary)
    return (0 if summary["terminal_state"] == "COMPLETED" else 2), summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded ReachOps M3 real no-submit stability probe.")
    parser.add_argument("--target", required=True)
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-ids", required=True)
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--profile-scan-limit", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--max-sources", type=int, default=1)
    parser.add_argument("--max-videos", type=int, default=1)
    parser.add_argument("--max-comments", type=int, default=5)
    parser.add_argument("--profile-page-timeout", type=int, default=20)
    parser.add_argument("--profile-preflight-timeout", type=int, default=25)
    parser.add_argument("--scenario-timeout", type=int, default=150)
    parser.add_argument("--iteration-timeout", type=int, default=210)
    parser.add_argument("--cooldown-seconds", type=int, default=30)
    parser.add_argument("--max-profile-launches-per-day", type=int, default=80)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--allow-fewer-profiles", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.print_progress = not bool(args.quiet)
    code, summary = run_probe(args)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "ReachOps M3 probe: "
            f"{summary.get('terminal_state')} "
            f"passed={summary.get('passed_count')} failed={summary.get('failed_count')} "
            f"completed={summary.get('iterations_completed')}/{summary.get('iterations_requested')}"
        )
        if summary.get("summary_path"):
            print(f"summary={summary.get('summary_path')}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
