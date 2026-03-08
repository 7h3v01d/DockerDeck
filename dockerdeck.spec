# -*- mode: python ; coding: utf-8 -*-
"""
DockerDeck – dockerdeck.spec
PyInstaller one-file build spec.

Build instructions:
    pip install pyinstaller
    pyinstaller dockerdeck.spec

Output:
    dist/DockerDeck          (Linux/macOS executable)
    dist/DockerDeck.exe      (Windows executable)

Notes:
  • The spec targets Python 3.8+ with tkinter available.
  • On Linux, tkinter must be installed (e.g. sudo apt install python3-tk).
  • On macOS, use the official python.org installer which bundles tkinter.
  • On Windows, tkinter ships with the standard Python installer.
  • The resulting binary bundles ALL modules — users do NOT need Python installed.
"""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

# Collect all application modules
app_sources = [
    str(ROOT / "main.py"),
]

hidden_imports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.scrolledtext",
    "tkinter.messagebox",
    "tkinter.filedialog",
    # stdlib used at runtime
    "subprocess",
    "threading",
    "json",
    "pathlib",
    "re",
    "ctypes",
    "traceback",
    "collections",
    "datetime",
    "webbrowser",
    "urllib.request",
    "urllib.error",
    "gc",
]

a = Analysis(
    app_sources,
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Include subpackage
        (str(ROOT / "actions"), "actions"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "setuptools", "pip"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DockerDeck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=True,    # macOS: handle Apple Events
    target_arch=None,       # None = current arch; set 'x86_64' or 'arm64' to cross-compile
    codesign_identity=None,
    entitlements_file=None,
    # Windows icon (uncomment and provide .ico file):
    # icon="assets/icon.ico",
)

# macOS .app bundle (optional — uncomment to produce DockerDeck.app)
# app = BUNDLE(
#     exe,
#     name="DockerDeck.app",
#     icon="assets/icon.icns",
#     bundle_identifier="com.dockerdeck.app",
#     info_plist={
#         "NSHighResolutionCapable": True,
#         "CFBundleShortVersionString": "3.0.0",
#     },
# )
