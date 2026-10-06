# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — builds `ESX Bank Studio.app`, a self-contained macOS bundle.

PURPOSE
    One double-clickable app with its own Python, Qt, audio backends, MIDI
    backend, data files, and (when present at build time) ffmpeg/ffprobe.
    Nothing needs to be installed on the machine that runs it.
    Run it through `build_app.sh`, not directly — that script also draws the
    icon and installs the result into /Applications.

FLOW
    Analysis(ui/app.py) follows every import → EXE (the launcher) →
    COLLECT (onedir: fast startup, no unpack-to-/tmp on every launch) →
    BUNDLE (wraps it as .app with Info.plist + icon).

WHERE THE DATA FILES LAND, AND WHY NO CODE CHANGES WERE NEEDED
    PyInstaller keeps the package layout under `sys._MEIPASS`, and each
    module's `__file__` points there. So:
      spike_a/default.esx  → codec/default.esx  (BankTemplate's FIRST candidate)
      research/*.tsv       → research/          (ui/motion/editor.RESEARCH)
    If either lookup moves in the source, move its destination here too.

TRAPS
    - mido loads its backend by NAME at runtime (importlib), so the import
      graph never sees `mido.backends.rtmidi` — without the hidden import,
      MIDI Learn would report "no backend" only inside the .app.
    - The .esx template is gitignored (see .gitignore); `build_app.sh` refuses
      to build without it rather than ship an app whose "New bank" fails.
"""

import os
import shutil

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # SPECPATH is injected by PyInstaller

# ADJUSTABLE: bump with pyproject.toml's `version` — Finder's Get Info shows this.
APP_VERSION = "0.7.0"
APP_NAME = "ESX Bank Studio"
BUNDLE_ID = "com.deeptechhouse.esxbankstudio"

datas = [
    (os.path.join(ROOT, "spike_a", "default.esx"), "codec"),
    (os.path.join(ROOT, "research", "motion_operation_table_313.tsv"), "research"),
    (os.path.join(ROOT, "research", "motion_target_domains.tsv"), "research"),
]

# Bundle ffmpeg + ffprobe into `bin/`, where audio.ffmpeg_adapter looks first.
# PyInstaller collects their Homebrew dylibs and rewrites the load paths, so
# the bundled copies do not need Homebrew on the target machine. Absent at
# build time → the app still works, using a system ffmpeg or WAV-only import.
binaries = []
# O(t) time, O(1) space — t = 2 tools
for tool in ("ffmpeg", "ffprobe"):
    found = shutil.which(tool, path=os.pathsep.join(
        [os.environ.get("PATH", ""), "/usr/local/bin", "/opt/homebrew/bin"]))
    if found:
        binaries.append((os.path.realpath(found), "bin"))
    else:
        print(f"WARNING: {tool} not found — app will rely on a system install")

hiddenimports = collect_submodules("mido.backends") + ["rtmidi"]

a = Analysis(
    [os.path.join(ROOT, "ui", "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Dev/test tooling the app never imports; keeping it out trims the bundle.
    excludes=["pytest", "hypothesis", "IPython", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,  # GUI app: no Terminal window
    argv_emulation=False,
    upx=False,  # UPX breaks Qt/macOS code signatures
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=os.path.join(SPECPATH, "build", "ESXBankStudio.icns"),
    bundle_identifier=BUNDLE_ID,
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",  # built on macOS 12; see pyproject pins
        "NSRequiresAquaSystemAppearance": False,
    },
)
