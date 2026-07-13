# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_log_lines(path: Path, limit: int = 120) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def has_terminal_collection_line(lines: list[str]) -> bool:
    return any("DONE   collection" in line or "BLOCK  campaign failed" in line for line in lines)


def has_terminal_action_line(lines: list[str]) -> bool:
    return any("DONE   action_preflight" in line or "DONE   action_submit" in line or "BLOCK  action_" in line for line in lines)


def lines_after_marker(lines: list[str], marker: str) -> list[str]:
    start = -1
    for index, line in enumerate(lines):
        if marker in line:
            start = index
    return lines[start:] if start >= 0 else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real ReachOps Tk GUI controller path for acceptance evidence on macOS.")
    parser.add_argument("--base-dir", default="reports/reachops/mac_gui/runtime")
    parser.add_argument("--target", default="https://www.tiktok.com/@aofacore/video/7656416339531205901")
    parser.add_argument("--source-type", default="视频链接")
    parser.add_argument("--profile-group", default="United States")
    parser.add_argument("--profile-limit", type=int, default=2)
    parser.add_argument("--max-videos", type=int, default=1)
    parser.add_argument("--max-comments", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).expanduser()
    if not base_dir.is_absolute():
        base_dir = (ROOT_DIR / base_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    os.environ["REACHOPS_DATA_DIR"] = str(base_dir)
    existing_no_proxy = [item.strip() for item in str(os.environ.get("NO_PROXY") or "").split(",") if item.strip()]
    for item in ["127.0.0.1", "localhost", "::1"]:
        if item not in existing_no_proxy:
            existing_no_proxy.append(item)
    os.environ["NO_PROXY"] = ",".join(existing_no_proxy)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    import tkinter as tk

    from ReachOps.workbench.console import display_source_type
    from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp

    root = tk.Tk()
    app = GrowthIntelligenceStandaloneApp(root, base_dir=str(base_dir), auto_refresh_profiles=True)
    try:
        root.update_idletasks()
        root.update()
    except Exception:
        pass

    started_at = time.monotonic()
    log_path = Path(app.runtime_log_path)
    result: dict = {
        "status": "running",
        "generated_at": utc_now(),
        "base_dir": str(base_dir),
        "log_path": str(log_path),
        "target": args.target,
        "source_type": args.source_type,
        "profile_group": args.profile_group,
        "profile_limit": args.profile_limit,
    }

    def configure_and_start():
        app.console.scan_source_value_var.set(str(args.target))
        app.console.scan_source_type_var.set(display_source_type(str(args.source_type)))
        app.console.scan_profile_group_var.set(str(args.profile_group))
        app.console.scan_profile_group_display_var.set(str(args.profile_group))
        app.group_var.set(str(args.profile_group))
        app.console.scan_profile_limit_var.set(max(1, int(args.profile_limit)))
        app.console.scan_max_videos_var.set(max(1, int(args.max_videos)))
        app.console.scan_max_comments_var.set(max(1, int(args.max_comments)))
        app.console.scan_interval_var.set(30)
        app.console.action_execution_mode_var.set("预检，不提交")
        app.console.action_execution_live_confirm_var.set(False)
        app._log(result["start_marker"])
        app.start_collection_from_console()

    result["start_marker"] = (
        "TEST   gui_acceptance_start "
        f"target={args.target} source_type={args.source_type} group={args.profile_group}"
    )
    root.after(1200, configure_and_start)

    deadline = time.monotonic() + max(30, int(args.timeout))
    terminal_seen_at = 0.0
    try:
        while time.monotonic() < deadline:
            root.update()
            lines = lines_after_marker(latest_log_lines(log_path, limit=400), result["start_marker"])
            if has_terminal_collection_line(lines) and (has_terminal_action_line(lines) or any("TOUCH  skipped" in line for line in lines)):
                terminal_seen_at = time.monotonic()
                break
            time.sleep(0.2)
        if terminal_seen_at:
            settle_deadline = time.monotonic() + 3
            while time.monotonic() < settle_deadline:
                root.update()
                time.sleep(0.2)
        lines = lines_after_marker(latest_log_lines(log_path, limit=400), result["start_marker"])
        tokens = ["READY", "PLAN", "CHECK  profile_preflight", "START", "RUN", "VIDEO", "TOUCH", "DONE"]
        result.update(
            {
                "status": "completed" if has_terminal_collection_line(lines) else "timeout",
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "contains": {token: any(token in line for line in lines) for token in tokens},
                "tail": lines[-80:],
                "active_campaign_id": str(getattr(app, "active_campaign_id", "") or ""),
                "active_batch_id": str(getattr(app, "active_batch_id", "") or ""),
            }
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
