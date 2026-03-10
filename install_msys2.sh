#!/usr/bin/env bash
# =============================================================================
# EDMD — install_msys2.sh
# Windows GUI installer for ED Monitor Daemon — MSYS2 / UCRT64 path
# https://github.com/drworman/EDMD
#
# Run this from inside the MSYS2 UCRT64 terminal, NOT from CMD or PowerShell.
#
# Developer notice: EDMD is developed on Linux. Windows GUI support is
# best-effort. See docs/guides/WINDOWS_GUI.md for full details.
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
echo -e "${WHT}  ED Monitor Daemon — Windows MSYS2 Installer${NC}"
echo    "  https://github.com/drworman/EDMD"
echo
echo -e "${YEL}  Note: EDMD is developed on Linux. Windows support is best-effort.${NC}"
echo -e "${YEL}  See docs/guides/WINDOWS_GUI.md for full details and troubleshooting.${NC}"
echo

# ── Environment check ─────────────────────────────────────────────────────────
section "Checking environment"

# Confirm we are inside MSYS2 UCRT64 — not a plain bash on Windows
if [[ -z "${MSYSTEM:-}" ]]; then
    fail "MSYSTEM is not set. This script must be run inside the MSYS2 UCRT64 terminal.\nOpen the 'MSYS2 UCRT64' shortcut from your Start menu and re-run:\n  bash install_msys2.sh"
fi

if [[ "${MSYSTEM}" != "UCRT64" ]]; then
    warn "MSYSTEM is '${MSYSTEM}', expected 'UCRT64'."
    warn "EDMD is tested with the UCRT64 environment only."
    warn "If you proceed and encounter issues, switch to the MSYS2 UCRT64 terminal."
    echo
    read -rp "  Continue anyway? [y/N] " CONTINUE
    [[ "${CONTINUE,,}" == "y" ]] || fail "Aborted."
fi

ok "MSYS2 ${MSYSTEM} environment"

# ── Check pacman ──────────────────────────────────────────────────────────────
section "Checking pacman"

if ! command -v pacman &>/dev/null; then
    fail "pacman not found. This script requires MSYS2."
fi
ok "pacman found"

# ── Update package database ───────────────────────────────────────────────────
section "Updating package database"

info "Running pacman -Sy ..."
pacman -Sy --noconfirm
ok "Package database updated"

# ── Install GTK4 and PyGObject ────────────────────────────────────────────────
section "Installing GTK4 and PyGObject"

PKGS=(
    "mingw-w64-ucrt-x86_64-gtk4"
    "mingw-w64-ucrt-x86_64-python-gobject"
    "mingw-w64-ucrt-x86_64-python-psutil"
    "mingw-w64-ucrt-x86_64-adwaita-icon-theme"
)

info "Installing: ${PKGS[*]}"
info "(This may take several minutes on first install)"

if pacman -S --needed --noconfirm "${PKGS[@]}"; then
    ok "GTK4, PyGObject, psutil installed via pacman"
else
    fail "pacman install failed. Check output above for details."
fi

# ── Verify PyGObject ──────────────────────────────────────────────────────────
section "Verifying PyGObject"

PYTHON=""
for cmd in python python3; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON="$cmd"
            ok "Found $cmd $VER"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python ${PYTHON_MIN}+ not found inside MSYS2.\nInstall via: pacman -S mingw-w64-ucrt-x86_64-python"
fi

GUI_AVAILABLE=false
if $PYTHON -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
    ok "PyGObject (GTK4) is importable"
    GUI_AVAILABLE=true
else
    warn "PyGObject is NOT importable. GUI mode will not work."
    warn "See docs/guides/WINDOWS_GUI.md — MSYS2 troubleshooting section."
fi

# ── pip packages ──────────────────────────────────────────────────────────────
section "Installing pip packages"

for PKG in "discord-webhook>=1.3.0" "cryptography>=41.0.0"; do
    PKG_NAME=$(echo "$PKG" | cut -d'>' -f1)
    info "Installing ${PKG_NAME}..."
    if $PYTHON -m pip install "$PKG" --quiet 2>/dev/null; then
        ok "${PKG_NAME} installed"
    else
        warn "Could not install ${PKG_NAME} automatically."
        warn "Run manually: pip install ${PKG_NAME}"
    fi
done

# ── Config setup ──────────────────────────────────────────────────────────────
section "Configuration"

# APPDATA is a Windows env var, available inside MSYS2
APPDATA_WIN="${APPDATA:-}"
if [ -z "$APPDATA_WIN" ]; then
    warn "APPDATA not set — config will be placed next to edmd.py"
    EDMD_DATA_DIR="$REPO_DIR"
else
    # Convert Windows path to MSYS2 path (C:\Users\... → /c/Users/...)
    APPDATA_MSYS=$(echo "$APPDATA_WIN" | sed 's|\\|/|g' | sed 's|^\([A-Za-z]\):|/\L\1|')
    EDMD_DATA_DIR="${APPDATA_MSYS}/EDMD"
fi

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
echo -e "  ${WHT}Important:${NC} always launch from the MSYS2 UCRT64 terminal."
echo
echo -e "  ${WHT}Terminal mode:${NC}"
echo -e "    $PYTHON edmd.py"
echo

if [ "$GUI_AVAILABLE" = true ]; then
    echo -e "  ${WHT}GUI mode:${NC}"
    echo -e "    $PYTHON edmd.py --gui"
    echo
else
    echo -e "  ${YEL}GUI mode requires PyGObject — see warnings above.${NC}"
    echo -e "  ${YEL}Terminal mode is fully functional without the GUI.${NC}"
    echo
fi

echo -e "  ${WHT}With a config profile:${NC}"
echo -e "    $PYTHON edmd.py -p YourProfileName"
echo
if [ -n "$APPDATA_WIN" ]; then
    echo -e "  ${CYN}Config: %APPDATA%\\EDMD\\config.toml${NC}"
fi
echo -e "  ${CYN}Set JournalFolder to your ED journal path before running.${NC}"
echo -e "  ${CYN}See docs/guides/WINDOWS_GUI.md for full Windows documentation.${NC}"
echo
