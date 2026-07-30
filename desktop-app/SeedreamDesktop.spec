# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
for path in (SPECPATH, project_root):
    if path not in sys.path:
        sys.path.insert(0, path)

replicate_datas, replicate_binaries, replicate_hiddenimports = collect_all("replicate")
server_hiddenimports = collect_submodules("server")
desktop_hiddenimports = collect_submodules("seedream_desktop")

datas = [
    ("icon-placeholder.png", "."),
    ("shortcuts.py", "."),
    ("secrets.example.json", "."),
] + replicate_datas

icon_path = os.path.join(SPECPATH, "icon.ico")
exe_icon = icon_path if os.path.isfile(icon_path) else None


a = Analysis(
    ["app.py"],
    pathex=[SPECPATH, project_root],
    binaries=replicate_binaries,
    datas=datas,
    hiddenimports=replicate_hiddenimports
    + server_hiddenimports
    + desktop_hiddenimports
    + ["PIL._tkinter_finder", "fastapi", "pydantic", "httpx", "requests"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SeedreamDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)
