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
DEFAULT_PROFILE_PREFLIGHT_TIMEOUT_SECONDS = 60
DEFAULT_PROFILE_PREFLIGHT_WORKERS = 2
DEFAULT_REPEATED_TARGET_REAL_ITERATIONS = 3
RESOURCE_CONSERVATION_CODES = {"duplicate_suppressed", "no_candidates"}
RESOURCE_CONSERVATION_DIAGNOSES = {"duplicate_suppressed", "content_found_no_comments"}


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


def effective_profile_preflight_timeout(args: argparse.Namespace) -> int:
    per_wave_timeout = max(
        5,
        int(getattr(args, "profile_preflight_timeout", 0) or DEFAULT_PROFILE_PREFLIGHT_TIMEOUT_SECONDS),
    )
    explicit_profile_count = len(split_profile_ids(str(getattr(args, "profile_ids", "") or "")))
    profile_count = explicit_profile_count or max(1, int(getattr(args, "profile_limit", 1) or 1))
    workers = max(1, min(DEFAULT_PROFILE_PREFLIGHT_WORKERS, profile_count))
    waves = max(1, (profile_count + workers - 1) // workers)
    return per_wave_timeout * waves


def build_real_flow_command(args: argparse.Namespace) -> list[str]:
    profile_limit = max(1, int(args.profile_limit or 1))
    profile_scan_limit = max(1, int(args.profile_scan_limit or args.profile_limit or 1))
    max_attempt_batches = max(1, min(4, (profile_scan_limit + profile_limit - 1) // profile_limit))
    command = [
        sys.executable,
        "tools/run_reachops_real_flow_macos.py",
        "--profile-group",
        str(args.profile_group or ""),
        "--profile-limit",
        str(profile_limit),
        "--profile-scan-limit",
        str(profile_scan_limit),
        "--max-attempt-batches",
        str(max_attempt_batches),
        "--max-sources",
        str(max(1, int(args.max_sources or 1))),
        "--max-videos",
        str(max(1, int(args.max_videos or 1))),
        "--max-comments",
        str(max(1, int(args.max_comments or 1))),
        "--profile-page-timeout",
        str(max(1, int(args.profile_page_timeout or 20))),
        "--profile-preflight-timeout",
        str(effective_profile_preflight_timeout(args)),
        "--scenario-timeout",
        str(max(1, int(args.scenario_timeout or 240))),
        "--max-profile-launches-per-day",
        str(max(0, int(args.max_profile_launches_per_day or 0))),
        "--target",
        str(args.target or ""),
        "--json",
    ]
    if str(args.profile_ids or "").strip():
        command[4:4] = ["--profile-ids", str(args.profile_ids or "")]
    return command


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


def iteration_passed(row: dict[str, Any], minimum_profile_count: int = 1) -> bool:
    profile_preflight = row.get("profile_preflight") if isinstance(row.get("profile_preflight"), dict) else {}
    available_profiles = max(
        int(profile_preflight.get("available") or 0),
        len([item for item in row.get("usable_profile_ids") or [] if str(item or "").strip()]),
    )
    return bool(
        int(row.get("returncode") or 0) == 0
        and row.get("acceptance_status") == "passed"
        and row.get("no_submit") is True
        and available_profiles >= max(1, int(minimum_profile_count or 1))
    )


def resource_conservation_terminal(row: dict[str, Any]) -> bool:
    no_action = row.get("no_action_reason") if isinstance(row.get("no_action_reason"), dict) else {}
    code = str(no_action.get("code") or "").strip()
    diagnosis = str(row.get("diagnosis_status") or "").strip()
    funnel = row.get("funnel") if isinstance(row.get("funnel"), dict) else {}
    no_new_leads = int(funnel.get("customer_leads") or 0) <= 0 and int(funnel.get("outreach_actions") or 0) <= 0
    return bool(
        row.get("no_submit") is True
        and row.get("acceptance_status") == "passed"
        and no_new_leads
        and (code in RESOURCE_CONSERVATION_CODES or diagnosis in RESOURCE_CONSERVATION_DIAGNOSES)
    )


def should_stop_for_account_conservation(args: argparse.Namespace, rows: list[dict[str, Any]]) -> bool:
    if bool(getattr(args, "allow_repeated_target_pressure", False)):
        return False
    if split_profile_ids(str(getattr(args, "profile_ids", "") or "")):
        return False
    if int(getattr(args, "iterations", 0) or 0) <= DEFAULT_REPEATED_TARGET_REAL_ITERATIONS:
        return False
    floor = max(1, int(getattr(args, "resource_conservation_after", 0) or DEFAULT_REPEATED_TARGET_REAL_ITERATIONS))
    if len(rows) < floor:
        return False
    recent = rows[-floor:]
    return all(resource_conservation_terminal(row) for row in recent)


def build_summary(
    args: argparse.Namespace,
    *,
    started_at: str,
    rows: list[dict[str, Any]],
    terminal: bool = False,
) -> dict[str, Any]:
    minimum_profile_count = max(1, int(getattr(args, "minimum_profile_count", 3) or 3))
    passed_count = sum(1 for row in rows if iteration_passed(row, minimum_profile_count))
    failed_count = len(rows) - passed_count
    completed = bool(len(rows) >= int(args.iterations or 0) and failed_count == 0)
    completed_reason = (
        "twenty_consecutive_real_no_submit_passed"
        if int(args.iterations or 0) >= 20
        else "requested_real_no_submit_iterations_passed"
    )
    summary = {
        "schema_version": "reachops.m3_probe_summary.v1",
        "started_at": started_at,
        "updated_at": utc_stamp(),
        "target": str(args.target or ""),
        "profile_group": str(args.profile_group or ""),
        "profile_ids": split_profile_ids(str(args.profile_ids or "")),
        "adaptive_profile_pool": bool(getattr(args, "adaptive_profile_pool", False)),
        "minimum_profile_count": minimum_profile_count,
        "account_resource_policy": {
            "allow_repeated_target_pressure": bool(getattr(args, "allow_repeated_target_pressure", False)),
            "resource_conservation_after": max(
                1,
                int(getattr(args, "resource_conservation_after", 0) or DEFAULT_REPEATED_TARGET_REAL_ITERATIONS),
            ),
            "conserves_group_pool_by_default": True,
        },
        "profile_preflight_timeout_seconds": max(
            5,
            int(getattr(args, "profile_preflight_timeout", 0) or DEFAULT_PROFILE_PREFLIGHT_TIMEOUT_SECONDS),
        ),
        "effective_profile_preflight_timeout_seconds": effective_profile_preflight_timeout(args),
        "active_profile_ids": list(getattr(args, "active_profile_ids", []) or []),
        "excluded_profile_ids": list(getattr(args, "excluded_profile_ids", []) or []),
        "iterations_requested": int(args.iterations or 0),
        "iterations_completed": len(rows),
        "cooldown_seconds": max(0, int(getattr(args, "cooldown_seconds", 0) or 0)),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "terminal_state": "COMPLETED" if completed else "BLOCKED" if terminal else "RUNNING",
        "terminal_reason": (
            str(getattr(args, "terminal_reason_override", "") or "")
            or (completed_reason if completed else "m3_probe_stopped_before_completion" if terminal else "")
        ),
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
    args.adaptive_profile_pool = not bool(getattr(args, "disable_adaptive_profile_pool", False))
    args.minimum_profile_count = max(1, int(getattr(args, "minimum_profile_count", 3) or 3))
    args.terminal_reason_override = ""
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
    if profile_ids and len(profile_ids) < args.minimum_profile_count and not bool(args.allow_fewer_profiles):
        summary = {
            "schema_version": "reachops.m3_probe_summary.v1",
            "terminal_state": "BLOCKED",
            "terminal_reason": "insufficient_profile_ids_for_m3",
            "profile_ids": profile_ids,
            "minimum_profile_count": args.minimum_profile_count,
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
    active_profile_ids = list(profile_ids)
    excluded_profile_ids: list[str] = []
    args.active_profile_ids = list(active_profile_ids)
    args.excluded_profile_ids = list(excluded_profile_ids)
    for index in range(1, int(args.iterations or 1) + 1):
        command_args = argparse.Namespace(**vars(args))
        if active_profile_ids:
            command_args.profile_ids = ",".join(active_profile_ids)
            command_args.profile_limit = min(max(1, int(args.profile_limit or 1)), len(active_profile_ids))
            command_args.profile_scan_limit = min(max(1, int(args.profile_scan_limit or args.profile_limit or 1)), len(active_profile_ids))
        command = build_real_flow_command(command_args)
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
        if profile_ids and bool(args.adaptive_profile_pool):
            blocked_now = {str(item) for item in row.get("blocked_profile_ids") or [] if str(item)}
            for profile_id in active_profile_ids:
                if profile_id in blocked_now and profile_id not in excluded_profile_ids:
                    excluded_profile_ids.append(profile_id)
            active_profile_ids = [profile_id for profile_id in active_profile_ids if profile_id not in blocked_now]
            args.active_profile_ids = list(active_profile_ids)
            args.excluded_profile_ids = list(excluded_profile_ids)
        write_json(summary_path, build_summary(args, started_at=started_at, rows=rows))
        if bool(args.print_progress):
            print(
                "M3 iteration "
                f"{index}/{int(args.iterations or 1)} status={row.get('acceptance_status')} "
                f"rc={row.get('returncode')} browser={row.get('browser_started')} "
                f"diagnosis={row.get('diagnosis_status')} duration={row.get('duration_seconds')}s",
                flush=True,
            )
        if (
            profile_ids
            and bool(args.adaptive_profile_pool)
            and not bool(args.allow_fewer_profiles)
            and len(active_profile_ids) < args.minimum_profile_count
        ):
            args.terminal_reason_override = "insufficient_active_profiles_for_m3"
            break
        passed = iteration_passed(row, args.minimum_profile_count)
        if not passed and not bool(args.continue_on_failure):
            break
        if should_stop_for_account_conservation(args, rows):
            args.terminal_reason_override = "account_resource_conservation_stop_duplicate_target"
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
    parser.add_argument("--profile-ids", default="")
    parser.add_argument("--profile-limit", type=int, default=3)
    parser.add_argument("--profile-scan-limit", type=int, default=3)
    parser.add_argument("--minimum-profile-count", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--max-sources", type=int, default=1)
    parser.add_argument("--max-videos", type=int, default=1)
    parser.add_argument("--max-comments", type=int, default=5)
    parser.add_argument("--profile-page-timeout", type=int, default=20)
    parser.add_argument("--profile-preflight-timeout", type=int, default=DEFAULT_PROFILE_PREFLIGHT_TIMEOUT_SECONDS)
    parser.add_argument("--scenario-timeout", type=int, default=240)
    parser.add_argument("--iteration-timeout", type=int, default=360)
    parser.add_argument("--cooldown-seconds", type=int, default=30)
    parser.add_argument("--max-profile-launches-per-day", type=int, default=80)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--allow-fewer-profiles", action="store_true")
    parser.add_argument(
        "--allow-repeated-target-pressure",
        action="store_true",
        help="Support-only: allow repeated real browser runs against the same terminal target despite account resource cost.",
    )
    parser.add_argument("--resource-conservation-after", type=int, default=DEFAULT_REPEATED_TARGET_REAL_ITERATIONS)
    parser.add_argument("--disable-adaptive-profile-pool", action="store_true")
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
