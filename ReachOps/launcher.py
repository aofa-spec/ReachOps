# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import ctypes
import os
import tempfile
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import PRODUCT_NAME_CN

_LOCK_HANDLE = None
_USAGE = """ReachOps unified client launcher.

Usage:
  python ReachOpsApp.py              Start the unified Web console.
  python ReachOpsApp.py --legacy-tk  Start the legacy Tk diagnostic client.
  python ReachOpsApp.py --help       Show this help without starting clients.
"""

_LEGACY_TK_DIAGNOSTIC_NOTE = "旧 Tk 仅作为诊断入口保留；默认客户入口是 ReachOps 本地客户端控制台。"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_single_instance_lock() -> bool:
    lock_path = Path(tempfile.gettempdir()) / "reachops_ui_single_instance.lock"
    global _LOCK_HANDLE

    if os.name != "nt":
        try:
            import fcntl

            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            _LOCK_HANDLE = handle
            return True
        except Exception:
            pass

    try:
        if lock_path.exists():
            raw_pid = lock_path.read_text(encoding="utf-8").strip()
            existing_pid = int(raw_pid or "0")
            if _pid_is_running(existing_pid):
                return False
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        return True

    def cleanup():
        try:
            if lock_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(cleanup)
    return True


def _bring_existing_native_client_to_front():
    if sys.platform != "darwin":
        return
    script = """
    tell application "System Events"
      repeat with procName in {"python", "Python"}
        if exists process procName then
          set frontmost of process procName to true
          exit repeat
        end if
      end repeat
    end tell
    """
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=3)
    except Exception:
        pass


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _launch_web_client() -> int:
    root = _project_root()
    self_check = root / "tools" / "reachops_mac_self_check.py"
    if not self_check.exists():
        print("ReachOps Web 控制台启动器不存在。", file=sys.stderr)
        print("ReachOps 客户端入口已统一到本地客户端控制台；缺少 Web 控制台启动器时不会静默回退。", file=sys.stderr)
        return 2
    command = [sys.executable, str(self_check), "--start-web"]
    completed = subprocess.run(
        command,
        cwd=str(root),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
    url_path = root / "reports" / "reachops" / "mac_gui" / "runtime" / "reachops_web_ui_url.txt"
    url = ""
    try:
        url = url_path.read_text(encoding="utf-8").strip()
    except Exception:
        url = ""
    if url:
        print(f"ReachOps 本地客户端控制台: {url}")
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"浏览器打开失败，请手动复制地址：{url} ({exc})")
    else:
        print("ReachOps 本地客户端控制台未生成可用地址，请查看上方自检输出。")
    return completed.returncode


def _launch_legacy_tk_client() -> int:
    import tkinter as tk

    from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp

    print(_LEGACY_TK_DIAGNOSTIC_NOTE)
    if not _acquire_single_instance_lock():
        _bring_existing_native_client_to_front()
        print("ReachOps 客户端已在运行，已尝试切回现有窗口。")
        return 0

    root = tk.Tk()
    root.title(PRODUCT_NAME_CN)
    GrowthIntelligenceStandaloneApp(root)
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.after(1200, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Start the ReachOps operator client."""

    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg in {"-h", "--help"} for arg in args):
        print(_USAGE.strip())
        return 0
    allowed = {"--legacy-tk", "--web"}
    unknown = [arg for arg in args if arg not in allowed]
    if unknown:
        print(f"未知启动参数: {', '.join(unknown)}", file=sys.stderr)
        print(_USAGE.strip(), file=sys.stderr)
        return 2
    legacy_requested = "--legacy-tk" in args or os.environ.get("REACHOPS_LEGACY_TK") == "1"
    if legacy_requested:
        return _launch_legacy_tk_client()
    return _launch_web_client()
