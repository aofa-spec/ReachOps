# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import ctypes
import os
import tempfile
import tkinter as tk
from pathlib import Path

from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp

from . import PRODUCT_NAME_CN


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


def main() -> int:
    """Start the standalone acquisition workbench.

    The implementation is still backed by the existing GrowthOps services while
    this directory becomes the product boundary for the independent client.
    """

    if not _acquire_single_instance_lock():
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
