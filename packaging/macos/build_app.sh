#!/usr/bin/env bash
# build_app.sh — build "ESX Bank Studio.app" and install it into /Applications.
#
# PURPOSE
#   One command from a dev checkout to a double-clickable, self-contained app.
#   The result carries its own Python, Qt, librosa/numpy, mido/rtmidi, data
#   files and ffmpeg — it does not need this repo, the venv, or Homebrew.
#
# FLOW
#   preflight (python, PyInstaller, template) → make_icon.py → pyinstaller
#   → smoke test (the bundled binary imports + finds its data) → copy to
#   /Applications → ad-hoc re-sign → register with Launch Services.
#
# USAGE
#   packaging/macos/build_app.sh            # build + install to /Applications
#   packaging/macos/build_app.sh --no-install   # build only (dist/ in this folder)
#
# RE-RUN AFTER EVERY CODE CHANGE — the .app is a snapshot, not a link to the source.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP_NAME="ESX Bank Studio"
# ADJUSTABLE: install location. ~/Applications works without admin rights.
INSTALL_DIR="${INSTALL_DIR:-/Applications}"
PY="${PYTHON:-python3}"  # ADJUSTABLE: point at another interpreter via PYTHON=...

echo "==> Preflight"
"$PY" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version' \
  || { echo "Need Python 3.13 (see .python-version)"; exit 1; }
"$PY" -c 'import PySide6' || { echo "PySide6 missing: pip3 install -r requirements.txt"; exit 1; }
"$PY" -m PyInstaller --version >/dev/null 2>&1 || { echo "PyInstaller missing: pip3 install pyinstaller"; exit 1; }
[[ -f "$ROOT/spike_a/default.esx" ]] || {
  echo "spike_a/default.esx missing — 'New bank' would fail. Regenerate it with spike_a/make_template.py"; exit 1; }
# Optional extras are bundled only if installed here; say which, so a thin build is never a surprise.
"$PY" -c 'import librosa, soundfile, numpy' 2>/dev/null && echo "    audio extras: bundled" \
  || echo "    audio extras: NOT installed — key/pitch detection will be off in the app"
"$PY" -c 'import mido, rtmidi' 2>/dev/null && echo "    MIDI extras:  bundled" \
  || echo "    MIDI extras:  NOT installed — MIDI Learn will be off in the app"

echo "==> Icon"
mkdir -p "$HERE/build"
"$PY" "$HERE/make_icon.py" "$HERE/build/ESXBankStudio.icns"

echo "==> PyInstaller (a few minutes the first time)"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$HERE/dist" --workpath "$HERE/build/pyinstaller" \
  "$HERE/esx_bank_studio.spec"

APP="$HERE/dist/$APP_NAME.app"
BIN="$APP/Contents/MacOS/$APP_NAME"

echo "==> Smoke test (offscreen: builds the main window, then quits)"
# ESX_SMOKE_TEST makes ui/app.py quit right after the window is built, so a
# missing module or data file fails HERE, not on first double-click.
QT_QPA_PLATFORM=offscreen ESX_SMOKE_TEST=1 PATH=/usr/bin:/bin "$BIN"
echo "    ok"

if [[ "${1:-}" == "--no-install" ]]; then
  echo "Built: $APP"; exit 0
fi

echo "==> Install to $INSTALL_DIR"
DEST="$INSTALL_DIR/$APP_NAME.app"
rm -rf "$DEST"          # replace the previous build of THIS app only
ditto "$APP" "$DEST"    # ditto preserves bundle metadata + signatures; cp -R can break them
codesign --force --deep --sign - "$DEST"   # ad-hoc sign: required to launch on Apple Silicon
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST"

echo
echo "Installed: $DEST"
echo "Open it from Launchpad / Finder → Applications, or:  open \"$DEST\""
