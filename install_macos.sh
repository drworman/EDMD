#!/usr/bin/env bash
# =============================================================================
# EDMD — install_macos.sh
# macOS installer for ED Monitor Daemon
# https://github.com/drworman/EDMD
#
# Developer notice: EDMD is developed on Linux. This installer is a
# best-effort community resource. For macOS-specific issues, see:
#   docs/guides/MACOS_SETUP.md
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MIN="3.11"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'
CYN='\033[0;36m'; WHT='\033[1;37m'; NC='\033[0m'

info()    { echo -e "${CYN}[EDMD]${NC} $*"; }
ok()      { echo -e "${GRN}[  OK  ]${NC} $*"; }
warn()    { echo -e "${YEL}[ WARN ]${NC} $*"; }
fail()    { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }
section() { echo -e "\n${WHT}── $* ──${NC}"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${CYN}"
echo "  ███████╗██████╗ ███╗   ███╗ ██████╗ ███╗   ██╗██████╗ "
echo "  ██╔════╝██╔══██╗████╗ ████║██╔═══██╗████╗  ██║██╔══██╗"
echo "  █████╗  ██║  ██║██╔████╔██║██║   ██║██╔██╗ ██║██║  ██║"
echo "  ██╔══╝  ██║  ██║██║╚██╔╝██║██║   ██║██║╚██╗██║██║  ██║"
echo "  ███████╗██████╔╝██║ ╚═╝ ██║╚██████╔╝██║ ╚████║██████╔╝"
echo "  ╚══════╝╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═════╝ "
echo -e "${NC}"
echo -e "${WHT}  ED Monitor Daemon — macOS Installer${NC}"
echo    "  https://github.com/drworman/EDMD"
echo
echo -e "${YEL}  Note: EDMD is developed on Linux. macOS support is best-effort.${NC}"
echo -e "${YEL}  See docs/guides/MACOS_SETUP.md for full details and troubleshooting.${NC}"
echo

# ── Platform check ────────────────────────────────────────────────────────────
section "Checking platform"

if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "This installer is for macOS only. Use install.sh on Linux."
fi
ok "macOS detected"

# ── Homebrew check ────────────────────────────────────────────────────────────
section "Checking Homebrew"

if ! command -v brew &>/dev/null; then
    fail "Homebrew not found. Install it first:\n  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\nThen re-run this script."
fi
ok "Homebrew found at $(command -v brew)"

# ── Python check ──────────────────────────────────────────────────────────────
section "Checking Python"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON="$cmd"
            ok "Found $cmd $VER"
            break
        else
            warn "Found $cmd $VER — too old (need ${PYTHON_MIN}+)"
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python ${PYTHON_MIN}+ not found on PATH."
    info "Install via Homebrew: brew install python3"
    info "Or download from: https://python.org/downloads"
    fail "Python ${PYTHON_MIN}+ is required."
fi

# ── GTK4 / PyGObject via Homebrew ─────────────────────────────────────────────
section "Installing GTK4 and PyGObject via Homebrew"

info "Running: brew install gtk4 pygobject3"
info "(This may take several minutes on first install)"

if brew install gtk4 pygobject3; then
    ok "GTK4 and PyGObject installed"
else
    warn "brew install exited with an error."
    warn "If packages were already installed, this may be harmless."
    warn "Check the output above for details."
fi

# ── Verify PyGObject is importable ────────────────────────────────────────────
section "Verifying PyGObject"

GUI_AVAILABLE=false
if $PYTHON -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
    ok "PyGObject (GTK4) is importable"
    GUI_AVAILABLE=true
else
    warn "PyGObject is NOT importable by $PYTHON."
    warn "This is a known macOS/Homebrew path issue."
    warn "Try: brew info pygobject3  — and follow the caveats/linking instructions."
    warn "GUI mode will NOT work until this is resolved."
    warn "Terminal mode will still work fine."
fi

# ── pip packages ──────────────────────────────────────────────────────────────
section "Installing pip packages"

for PKG in "psutil>=5.9.0" "discord-webhook>=1.3.0" "cryptography>=41.0.0"; do
    PKG_NAME=$(echo "$PKG" | cut -d'>' -f1)
    info "Installing ${PKG_NAME}..."
    if $PYTHON -m pip install "$PKG" --quiet 2>/dev/null; then
        ok "${PKG_NAME} installed"
    elif $PYTHON -m pip install "$PKG" --break-system-packages --quiet 2>/dev/null; then
        ok "${PKG_NAME} installed (--break-system-packages)"
    else
        warn "Could not install ${PKG_NAME} automatically."
        warn "Run manually: pip3 install ${PKG_NAME}"
    fi
done

# ── Config setup ──────────────────────────────────────────────────────────────
section "Configuration"

EDMD_DATA_DIR="$HOME/Library/Application Support/EDMD"
mkdir -p "$EDMD_DATA_DIR"

USER_CONFIG="$EDMD_DATA_DIR/config.toml"
EXAMPLE_CONFIG="$REPO_DIR/example.config.toml"

if [ -f "$USER_CONFIG" ]; then
    ok "config.toml already exists — leaving untouched"
elif [ -f "$EXAMPLE_CONFIG" ]; then
    cp "$EXAMPLE_CONFIG" "$USER_CONFIG"
    ok "Created config.toml at $USER_CONFIG"
    info "Edit it to set JournalFolder before running EDMD."
else
    warn "example.config.toml not found — config.toml was not created."
    warn "Copy example.config.toml to \"$EDMD_DATA_DIR/config.toml\" manually."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
section "Installation complete"

echo
echo -e "  ${GRN}EDMD is ready to run.${NC}"
echo
echo -e "  ${WHT}Terminal mode:${NC}"
echo -e "    python3 edmd.py"
echo

if [ "$GUI_AVAILABLE" = true ]; then
    echo -e "  ${WHT}GUI mode:${NC}"
    echo -e "    python3 edmd.py --gui"
    echo
else
    echo -e "  ${YEL}GUI mode requires PyGObject to be importable — see warnings above.${NC}"
    echo -e "  ${YEL}Terminal mode is fully functional without the GUI.${NC}"
    echo
fi

echo -e "  ${WHT}With a config profile:${NC}"
echo -e "    python3 edmd.py -p YourProfileName"
echo
echo -e "  ${CYN}Config: $EDMD_DATA_DIR/config.toml${NC}"
echo -e "  ${CYN}Set JournalFolder to your ED journal path before running.${NC}"
echo -e "  ${CYN}See docs/guides/MACOS_SETUP.md for full macOS documentation.${NC}"
echo
