#!/usr/bin/env python3
"""
verify_env.py — prove the mini's environment before implementation starts.

Runs ON the mini (invoked by transfer_to_mini.sh verify). Exits non-zero if
anything fails, so a broken environment is caught here rather than three
agents into Wave 1.

WHAT IT CHECKS
    1. Platform      — arch, OS, cores, and the resulting agent ceiling
    2. Python        — version is >= 3.10 (PySide6's floor)
    3. Imports       — numpy, scipy, soundfile, librosa, PySide6
    4. PySide6 live  — a QApplication actually constructs (offscreen, no display)
    5. ffmpeg        — present and runnable
    6. THE GATE      — byte-identical round-trip on every corpus bank

Check 6 is the one that matters. The others are prerequisites for it.

USAGE
    cd <project>/spike_a && python3 ../deploy/verify_env.py
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

# --- Adjustable: where the corpus banks live, relative to the project root ---
CORPUS_DIRNAME = "corpus"
# --- Adjustable: minimum Python for PySide6 -------------------------------
MIN_PYTHON = (3, 10)

OK, FAIL, WARN = "\033[32mOK\033[0m", "\033[31mFAIL\033[0m", "\033[33mWARN\033[0m"
failures: list[str] = []


def check(label: str, passed: bool, detail: str = "", fatal: bool = True) -> bool:
    print(
        f"  [{OK if passed else (FAIL if fatal else WARN)}] {label}"
        + (f" — {detail}" if detail else "")
    )
    if not passed and fatal:
        failures.append(label)
    return passed


def section(name: str) -> None:
    print(f"\n=== {name} ===")


# ---------------------------------------------------------------------------
section("1. Platform")
cores = os.cpu_count() or 1
ceiling = max(1, min(16, cores - 2))
print(f"  {platform.platform()}")
print(f"  machine={platform.machine()}  cores={cores}")
check(
    "arm64 (Apple Silicon)",
    platform.machine() == "arm64",
    platform.machine(),
    fatal=False,
)
check(
    "agent concurrency ceiling >= 6",
    ceiling >= 6,
    f"ceiling={ceiling} (widest planned wave is 6 agents)",
    fatal=False,
)

# ---------------------------------------------------------------------------
section("2. Python")
v = sys.version_info
check(
    f"python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
    v[:2] >= MIN_PYTHON,
    f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
)

# ---------------------------------------------------------------------------
section("3. Imports")
for mod in ("numpy", "scipy", "soundfile", "librosa", "PySide6"):
    try:
        m = __import__(mod)
        check(mod, True, getattr(m, "__version__", "?"))
    except Exception as e:  # noqa: BLE001
        check(mod, False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
section("4. PySide6 constructs a QApplication")
# Offscreen platform plugin: proves the binding loads without needing a display,
# which matters because this runs over SSH.
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import __version__ as pyside_version  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402

    app = QApplication([])
    check("QApplication (offscreen)", True, f"PySide6 {pyside_version}")
    app.quit()
except Exception as e:  # noqa: BLE001
    check("QApplication (offscreen)", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
section("5. ffmpeg")
try:
    r = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True, timeout=15
    )
    check(
        "ffmpeg runnable",
        r.returncode == 0,
        r.stdout.splitlines()[0] if r.stdout else "",
    )
except Exception as e:  # noqa: BLE001
    check("ffmpeg runnable", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
section("6. THE GATE — byte-identical round-trip on the corpus")
# Import from the spike_a directory this script is invoked from.
sys.path.insert(0, str(Path.cwd()))
try:
    import layout  # noqa: F401
    from esx_probe import EsxBank

    check("codec importable", True, "layout + esx_probe")
except Exception as e:  # noqa: BLE001
    check("codec importable", False, f"{type(e).__name__}: {e}")
    EsxBank = None  # type: ignore

corpus = Path.cwd().parent / CORPUS_DIRNAME
banks = sorted(corpus.glob("*.esx")) if corpus.is_dir() else []

if not banks:
    check("corpus present", False, f"no .esx files under {corpus}")
elif EsxBank is not None:
    check("corpus present", True, f"{len(banks)} bank(s) in {corpus}")
    for b in banks:
        data = b.read_bytes()
        try:
            bank = EsxBank(data)
            errs = bank.structural_errors()
            identical = bank.to_bytes() == data
            detail = f"{len(data):,} B"
            if errs:
                detail += f"; {len(errs)} structural problem(s)"
            check(f"round-trip {b.name}", identical and not errs, detail)
        except Exception as e:  # noqa: BLE001
            check(f"round-trip {b.name}", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
section("Result")
if failures:
    print(f"  {FAIL} {len(failures)} check(s) failed:")
    for f in failures:
        print(f"        - {f}")
    print("\n  Environment is NOT ready. Fix the above before starting Wave 0.")
    sys.exit(1)

print(f"  {OK} environment verified — the codec round-trips on this machine.")
print("  Ready for Wave 0 (contract freeze).")
sys.exit(0)
