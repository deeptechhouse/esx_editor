#!/usr/bin/env bash
#
# transfer_to_mini.sh — move ESX Bank Studio to the M4 mini and prove the
#                       environment works before any implementation starts.
#
# WHY THIS EXISTS
#   The dev machine (macOS 12 / Intel) cannot install PySide6 6.10+ — those
#   wheels are macosx_13_0 only — and its 4 cores cap Claude Code workflows at
#   2 concurrent agents. The M4 mini (macOS 26, arm64, 10 cores) has neither
#   limit. This script moves the project and then VERIFIES the move, so a
#   broken environment is caught here rather than three agents into Wave 1.
#
# USAGE
#   ./transfer_to_mini.sh check     # preflight only — changes nothing
#   ./transfer_to_mini.sh sync      # copy project + corpus banks
#   ./transfer_to_mini.sh setup     # install dependencies on the mini
#   ./transfer_to_mini.sh verify    # run the round-trip gate remotely
#   ./transfer_to_mini.sh all       # check -> sync -> setup -> verify
#
#   Add --dry-run to any phase to print commands without executing them.
#
# SAFETY
#   * rsync runs WITHOUT --delete, so nothing on the mini is ever removed.
#   * `setup` installs packages. Run `check` first and read what it reports.
#   * Re-running any phase is safe (idempotent).
#
set -euo pipefail

# ===========================================================================
# ADJUSTABLE PARAMETERS
# ===========================================================================

# SSH host alias for the mini (must already work: `ssh macmini` with keys).
REMOTE_HOST="${REMOTE_HOST:-macmini}"

# Where the project lands on the mini, RELATIVE TO THE REMOTE HOME.
#
# Do NOT write $HOME here. `ssh host "mkdir -p $HOME/x"` expands it, but rsync
# QUOTES the remote path, so `host:$HOME/x` creates a directory literally named
# '$HOME'. (Hit exactly that on 2026-08-09 — files landed in /Users/cooper/$HOME/.)
# Both ssh and rsync resolve a bare relative path against the remote home, so a
# home-relative path is the one form that is correct for both.
REMOTE_ROOT="${REMOTE_ROOT:-_andy_ai_projects_2026/esx_editor}"

# Local project directory (this script lives in deploy/ inside it).
LOCAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The three verified corpus banks. These are the round-trip gate's evidence.
# Add more here as you collect them (stereo bank, PSG save, twice-saved bank).
CORPUS_FILES=(
  "/Users/aaandy/Documents/TEST_SAMPLES/ajs_electribe_jan2026_/a3jan26.esx"
  "/Users/aaandy/Downloads/ESX-Factory-Data.esx"
  "/Users/aaandy/Downloads/Two-Lone-Swordsman_andy_mod.esx"
)

# Python version to use on the mini. PySide6 requires >=3.10; the mini's
# system Python is 3.9.6, so a Homebrew Python is needed.
PY_VERSION="${PY_VERSION:-3.12}"

# Virtualenv location on the mini (home-relative, same reasoning as above).
REMOTE_VENV="${REMOTE_VENV:-.venvs/esx}"

# Python packages. Kept minimal — add PySide6 extras only when the UI waves start.
PY_PACKAGES=(
  "numpy" "scipy" "soundfile" "librosa"       # audio analysis (Spike C verified)
  "PySide6"                                    # the GUI toolkit this box cannot run
  "pytest" "pytest-cov" "hypothesis"           # test stack per TDD section 11
  "black" "ruff"                               # formatting + lint per conventions
)

# Set to 1 to also copy the 194-file TEST_SAMPLES folder (hundreds of MB).
# Off by default — the corpus banks are what the gate needs.
COPY_TEST_SAMPLES="${COPY_TEST_SAMPLES:-0}"
TEST_SAMPLES_DIR="/Users/aaandy/Documents/TEST_SAMPLES"

# Where Homebrew lives on the mini. Apple Silicon uses /opt/homebrew;
# Intel Macs use /usr/local. Checked in that order.
BREW_CANDIDATES=("/opt/homebrew/bin/brew" "/usr/local/bin/brew")

# ---------------------------------------------------------------------------
# WHY THE NEXT BIT EXISTS — a real trap, not defensive boilerplate.
#
# `ssh host 'command'` runs a NON-INTERACTIVE, NON-LOGIN shell. macOS does not
# source ~/.zprofile for it, so the PATH is the bare system default:
#     /usr/bin:/bin:/usr/sbin:/sbin
# Homebrew's shellenv is normally added in ~/.zprofile, so `brew`, and anything
# brew installs (python3.12, ffmpeg), are INVISIBLE over ssh even though they
# are installed and work fine in an interactive terminal.
#
# Verified on this mini 2026-08-09: brew 6.0.15 exists at /opt/homebrew/bin/brew
# while `ssh macmini 'command -v brew'` returns nothing.
#
# Fix: evaluate brew's shellenv at the start of every remote command.
# ---------------------------------------------------------------------------
REMOTE_ENV=""      # populated by detect_brew()

detect_brew() {
  for c in "${BREW_CANDIDATES[@]}"; do
    if ssh -o ConnectTimeout=10 "$REMOTE_HOST" "test -x $c" 2>/dev/null; then
      BREW_BIN="$c"
      REMOTE_ENV="eval \"\$($c shellenv)\"; "
      return 0
    fi
  done
  BREW_BIN=""
  return 1
}

# ===========================================================================
# Plumbing
# ===========================================================================
DRY_RUN=0
for arg in "$@"; do [[ "$arg" == "--dry-run" ]] && DRY_RUN=1; done

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
ok()   { printf "  ${C_OK}OK${C_OFF}    %s\n" "$*"; }
warn() { printf "  ${C_WARN}WARN${C_OFF}  %s\n" "$*"; }
fail() { printf "  ${C_ERR}FAIL${C_OFF}  %s\n" "$*"; }
step() { printf "\n${C_DIM}==>${C_OFF} %s\n" "$*"; }

# Run a command locally, honouring --dry-run.
run() {
  if [[ $DRY_RUN -eq 1 ]]; then printf "  ${C_DIM}would run:${C_OFF} %s\n" "$*"; return 0; fi
  "$@"
}

# Run a command on the mini, honouring --dry-run.
# REMOTE_ENV puts Homebrew on PATH first — see detect_brew() above.
rrun() {
  if [[ $DRY_RUN -eq 1 ]]; then printf "  ${C_DIM}would run (remote):${C_OFF} %s\n" "$*"; return 0; fi
  ssh -o ConnectTimeout=10 "$REMOTE_HOST" "${REMOTE_ENV}$*"
}

# Run remotely and capture output even in dry-run (read-only probes).
rprobe() { ssh -o ConnectTimeout=10 "$REMOTE_HOST" "${REMOTE_ENV}$*" 2>/dev/null || true; }

# ===========================================================================
# Phase: check — preflight, changes nothing
# ===========================================================================
phase_check() {
  local problems=0

  step "Local source"
  if [[ -d "$LOCAL_ROOT/spike_a" ]]; then ok "project root: $LOCAL_ROOT"
  else fail "no spike_a/ under $LOCAL_ROOT — wrong location?"; problems=$((problems+1)); fi

  local total=0
  for f in "${CORPUS_FILES[@]}"; do
    if [[ -f "$f" ]]; then
      local sz; sz=$(stat -f%z "$f")
      total=$((total+sz))
      ok "corpus: $(basename "$f") ($(printf "%'d" $sz) B)"
    else
      fail "corpus MISSING: $f"; problems=$((problems+1))
    fi
  done
  [[ $total -gt 0 ]] && printf "        corpus total: %s B\n" "$(printf "%'d" $total)"

  step "Remote reachability"
  local probe; probe=$(rprobe 'echo READY; sysctl -n hw.ncpu; sw_vers -productVersion; uname -m')
  if [[ "$probe" == READY* ]]; then
    local cores os arch
    cores=$(echo "$probe" | sed -n 2p); os=$(echo "$probe" | sed -n 3p); arch=$(echo "$probe" | sed -n 4p)
    ok "$REMOTE_HOST reachable — macOS $os, $arch, $cores cores"
    # The workflow concurrency formula, restated so the payoff is visible here.
    local cap=$(( cores - 2 )); [[ $cap -gt 16 ]] && cap=16; [[ $cap -lt 1 ]] && cap=1
    ok "agent concurrency ceiling there: $cap  (this machine: 2)"
  else
    fail "cannot reach $REMOTE_HOST over ssh"; problems=$((problems+1))
  fi

  step "Remote toolchain"
  if detect_brew; then
    ok "brew: $BREW_BIN  $(rprobe 'brew --version | head -1')"
  else
    fail "brew not found at ${BREW_CANDIDATES[*]} — install from https://brew.sh"
    problems=$((problems+1))
  fi

  local ff; ff=$(rprobe 'command -v ffmpeg || true')
  [[ -n "$ff" ]] && ok "ffmpeg: $ff" || warn "ffmpeg missing — setup installs it"

  local py; py=$(rprobe "command -v python$PY_VERSION || true")
  if [[ -n "$py" ]]; then ok "python$PY_VERSION: $py"
  else warn "python$PY_VERSION missing — setup installs it (system python is 3.9.6, too old for PySide6)"; fi

  local venvpy; venvpy=$(rprobe "ls $REMOTE_VENV/bin/python 2>/dev/null || true")
  [[ -n "$venvpy" ]] && ok "venv already present: $REMOTE_VENV" || warn "venv not yet created"

  step "Summary"
  if [[ $problems -eq 0 ]]; then
    ok "preflight clean — safe to run: $0 sync"
  else
    fail "$problems blocking problem(s); fix before syncing"
    return 1
  fi
}

# ===========================================================================
# Phase: sync — copy files. Never deletes anything remote.
# ===========================================================================
phase_sync() {
  detect_brew || true          # not required for rsync, but keeps PATH consistent
  step "Creating remote directories"
  rrun "mkdir -p ~/$REMOTE_ROOT/corpus"

  step "Syncing project tree"
  # --delete is deliberately ABSENT: this never removes remote files.
  # Excludes keep caches, synthetic fixtures, and venvs out of the transfer.
  local rsync_opts=(-avz --human-readable --partial --progress
    --exclude '__pycache__/' --exclude '*.pyc' --exclude '.venv/'
    --exclude '*.esx'            # synthetic fixtures are regenerated, not copied
    --exclude '.DS_Store')
  [[ $DRY_RUN -eq 1 ]] && rsync_opts+=(--dry-run)
  rsync "${rsync_opts[@]}" "$LOCAL_ROOT/" "$REMOTE_HOST:$REMOTE_ROOT/"

  step "Syncing corpus banks"
  for f in "${CORPUS_FILES[@]}"; do
    [[ -f "$f" ]] || { warn "skipping missing $f"; continue; }
    local o=(-avz --human-readable --partial)
    [[ $DRY_RUN -eq 1 ]] && o+=(--dry-run)
    rsync "${o[@]}" "$f" "$REMOTE_HOST:$REMOTE_ROOT/corpus/"
  done

  if [[ "$COPY_TEST_SAMPLES" == "1" ]]; then
    step "Syncing TEST_SAMPLES (large — enabled via COPY_TEST_SAMPLES=1)"
    local o=(-avz --human-readable --partial --progress)
    [[ $DRY_RUN -eq 1 ]] && o+=(--dry-run)
    rsync "${o[@]}" "$TEST_SAMPLES_DIR/" "$REMOTE_HOST:\$HOME/TEST_SAMPLES/"
  else
    printf "  ${C_DIM}skipping TEST_SAMPLES (set COPY_TEST_SAMPLES=1 to include)${C_OFF}\n"
  fi

  ok "sync complete"
}

# ===========================================================================
# Phase: setup — install dependencies on the mini
# ===========================================================================
phase_setup() {
  # Must run first: populates REMOTE_ENV so brew and its packages are on PATH.
  detect_brew || { fail "brew not found on $REMOTE_HOST — install it first"; return 1; }

  step "Homebrew packages (ffmpeg, python$PY_VERSION)  [brew: $BREW_BIN]"
  # `brew install` is a no-op when already present, so this is idempotent.
  rrun "brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg"
  rrun "brew list python@$PY_VERSION >/dev/null 2>&1 || brew install python@$PY_VERSION"

  step "Virtualenv at $REMOTE_VENV"
  rrun "test -x ~/$REMOTE_VENV/bin/python || python$PY_VERSION -m venv ~/$REMOTE_VENV"
  rrun "~/$REMOTE_VENV/bin/python -m pip install --upgrade pip setuptools wheel"

  step "Python packages"
  rrun "~/$REMOTE_VENV/bin/python -m pip install ${PY_PACKAGES[*]}"

  step "Recording the environment"
  # A lockfile so the environment is reproducible per the version-pinning rule.
  rrun "~/$REMOTE_VENV/bin/python -m pip freeze > ~/$REMOTE_ROOT/deploy/requirements-mini.txt"
  ok "setup complete — wrote deploy/requirements-mini.txt on the mini"
}

# ===========================================================================
# Phase: verify — prove the environment before any agent starts work
# ===========================================================================
phase_verify() {
  detect_brew || true          # best-effort; the venv python is an absolute path
  step "Running remote verification"
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  ${C_DIM}would run: ~/%s/bin/python ~/%s/deploy/verify_env.py${C_OFF}\n" "$REMOTE_VENV" "$REMOTE_ROOT"
    return 0
  fi
  # verify_env.py exits nonzero if anything fails, so `set -e` surfaces it.
  # ${REMOTE_ENV} is required here too: verify_env.py shells out to ffmpeg, which
  # lives in Homebrew's prefix and is absent from the bare non-interactive PATH.
  ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
    "${REMOTE_ENV}cd ~/$REMOTE_ROOT/spike_a && ~/$REMOTE_VENV/bin/python ../deploy/verify_env.py"
}

# ===========================================================================
# Entry point
# ===========================================================================
PHASE="${1:-check}"
case "$PHASE" in
  check)  phase_check ;;
  sync)   phase_sync ;;
  setup)  phase_setup ;;
  verify) phase_verify ;;
  all)    phase_check && phase_sync && phase_setup && phase_verify ;;
  *)      sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
