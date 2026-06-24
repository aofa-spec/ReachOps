# -*- coding: utf-8 -*-
from __future__ import annotations

import tkinter as tk

from ReachOps.workbench.standalone_app import GrowthIntelligenceStandaloneApp

from . import PRODUCT_NAME_CN


def main() -> int:
    """Start the standalone acquisition workbench.

    The implementation is still backed by the existing GrowthOps services while
    this directory becomes the product boundary for the independent client.
    """

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
