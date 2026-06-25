# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

SPEC_FILE = Path(__file__).resolve() if "__file__" in globals() else Path(SPECPATH).resolve() / "reachops.spec"
PROJECT_ROOT = SPEC_FILE.parents[2]

block_cipher = None


a = Analysis(
    [str(PROJECT_ROOT / "ReachOpsApp.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "ReachOps" / "README.md"), "ReachOps"),
        (str(PROJECT_ROOT / "ReachOps" / "PRODUCT_ARCHITECTURE.md"), "ReachOps"),
    ],
    hiddenimports=[
        "ReachOps",
        "ReachOps.launcher",
        "ReachOps.updater",
        "ReachOps.workbench.standalone_app",
        "ReachOps.intelligence.ai_strategy",
        "ReachOps.intelligence.comment_intent",
        "ReachOps.intelligence.outreach_copy",
        "ReachOps.adapters.browser_manager",
        "ixbrowser_local_api",
        "selenium",
        "selenium.webdriver.chrome.webdriver",
        "selenium.webdriver.chrome.options",
        "selenium.webdriver.chrome.service",
        "selenium.webdriver.chromium.webdriver",
        "selenium.webdriver.remote.webdriver",
        "tkinter",
        "sqlite3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "modules.publish",
        "modules.video",
        "modules.smart_publish",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReachOps",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "ico" / "startup_icon.ico") if (PROJECT_ROOT / "ico" / "startup_icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ReachOps",
)
