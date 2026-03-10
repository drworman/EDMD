#!/usr/bin/env bash
# scripts/sync_wiki.sh
#
# Copies EDMD docs from the main repo into the wiki repo.
# Rewrites internal cross-document links so they work in the wiki's flat
# namespace.
#
# Usage (local):
#   WIKI_DIR=/path/to/EDMD.wiki bash scripts/sync_wiki.sh
#
# Usage (CI — called by .github/workflows/sync-wiki.yml):
#   Env vars WIKI_DIR and REPO_DIR are set by the workflow.
#
# Wiki page name mapping
# ─────────────────────
#   README.md                       → Home.md          (wiki home page)
#   INSTALL.md                      → Installation.md
#   docs/CONFIGURATION.md           → Configuration.md
#   docs/MISSION_BOOTSTRAP.md       → Mission-Bootstrap.md
#   docs/PLUGIN_DEVELOPMENT.md      → Plugin-Development.md
#   docs/REPORTS.md                 → Reports.md
#   docs/TERMINAL_OUTPUT.md         → Terminal-Output.md
#   docs/THEMING.md                 → Theming.md
#   docs/guides/DUAL_PILOT.md       → Dual-Pilot.md
#   docs/guides/LINUX_SETUP.md      → Linux-Setup.md
#   docs/guides/MACOS_SETUP.md      → macOS-Setup.md
#   docs/guides/REMOTE_ACCESS.md    → Remote-Access.md
#   docs/guides/WINDOWS_GUI.md      → Windows-GUI.md
#   docs/releases/RELEASE_NOTES_*  → Release-Notes.md (combined, newest first)
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)}"
WIKI_DIR="${WIKI_DIR:-}"

if [[ -z "$WIKI_DIR" ]]; then
    echo "ERROR: WIKI_DIR is not set." >&2
    exit 1
fi

# ── Source → wiki name mapping ────────────────────────────────────────────────
declare -A MAP
MAP["README.md"]="Home.md"
MAP["INSTALL.md"]="Installation.md"
MAP["docs/CONFIGURATION.md"]="Configuration.md"
MAP["docs/MISSION_BOOTSTRAP.md"]="Mission-Bootstrap.md"
MAP["docs/PLUGIN_DEVELOPMENT.md"]="Plugin-Development.md"
MAP["docs/REPORTS.md"]="Reports.md"
MAP["docs/TERMINAL_OUTPUT.md"]="Terminal-Output.md"
MAP["docs/THEMING.md"]="Theming.md"
MAP["docs/guides/DUAL_PILOT.md"]="Dual-Pilot.md"
MAP["docs/guides/LINUX_SETUP.md"]="Linux-Setup.md"
MAP["docs/guides/MACOS_SETUP.md"]="macOS-Setup.md"
MAP["docs/guides/REMOTE_ACCESS.md"]="Remote-Access.md"
MAP["docs/guides/WINDOWS_GUI.md"]="Windows-GUI.md"

# ── Link rewrite table (applied via sed to every copied file) ─────────────────
# Format: "old_link|new_wiki_link_target"
# Wiki links use bare page names (no .md extension).
REWRITES=(
    "INSTALL.md|Installation"
    "docs/CONFIGURATION.md|Configuration"
    "docs/MISSION_BOOTSTRAP.md|Mission-Bootstrap"
    "docs/PLUGIN_DEVELOPMENT.md|Plugin-Development"
    "docs/REPORTS.md|Reports"
    "docs/TERMINAL_OUTPUT.md|Terminal-Output"
    "docs/THEMING.md|Theming"
    "docs/guides/DUAL_PILOT.md|Dual-Pilot"
    "docs/guides/LINUX_SETUP.md|Linux-Setup"
    "docs/guides/MACOS_SETUP.md|macOS-Setup"
    "docs/guides/REMOTE_ACCESS.md|Remote-Access"
    "docs/guides/WINDOWS_GUI.md|Windows-GUI"
)

rewrite_links() {
    local file="$1"
    for entry in "${REWRITES[@]}"; do
        local old="${entry%%|*}"
        local new="${entry##*|}"
        # Replace ](old_path) with ](new_wiki_name) — handles both plain links
        # and links with anchor fragments e.g. LINUX_SETUP.md#option-a
        sed -i -E "s|\]\(${old}(#[^)]*)?\)|\](${new}\1)|g" "$file"
    done
}

# ── Copy individual docs ──────────────────────────────────────────────────────
echo "Syncing docs to wiki at: $WIKI_DIR"

for src_rel in "${!MAP[@]}"; do
    src="$REPO_DIR/$src_rel"
    dst="$WIKI_DIR/${MAP[$src_rel]}"
    if [[ -f "$src" ]]; then
        cp "$src" "$dst"
        rewrite_links "$dst"
        echo "  copied: $src_rel → ${MAP[$src_rel]}"
    else
        echo "  WARNING: source not found — $src_rel" >&2
    fi
done

# ── Combine release notes → Release-Notes.md ─────────────────────────────────
RELEASES_DIR="$REPO_DIR/docs/releases"
RELEASE_OUT="$WIKI_DIR/Release-Notes.md"

echo "# Release Notes" > "$RELEASE_OUT"
echo "" >> "$RELEASE_OUT"

# Newest first: reverse-sort by filename (RELEASE_NOTES_YYYYMMDD[x].md)
for f in $(ls "$RELEASES_DIR"/RELEASE_NOTES_*.md 2>/dev/null | sort -r); do
    echo "---" >> "$RELEASE_OUT"
    echo "" >> "$RELEASE_OUT"
    cat "$f" >> "$RELEASE_OUT"
    echo "" >> "$RELEASE_OUT"
done

echo "  combined: docs/releases/ → Release-Notes.md"

# ── Sidebar (_Sidebar.md) ─────────────────────────────────────────────────────
cat > "$WIKI_DIR/_Sidebar.md" << 'SIDEBAR'
## EDMD Wiki

**Getting Started**
- [[Home]]
- [[Installation]]

**Guides**
- [[Linux-Setup|Linux Setup]]
- [[macOS-Setup|macOS Setup]]
- [[Windows-GUI|Windows GUI]]
- [[Dual-Pilot|Dual Pilot Setup]]
- [[Remote-Access|Remote Access]]

**Reference**
- [[Configuration]]
- [[Terminal-Output|Terminal Output]]
- [[Reports]]
- [[Theming]]
- [[Mission-Bootstrap|Mission Bootstrap]]
- [[Plugin-Development|Plugin Development]]

**Releases**
- [[Release-Notes|Release Notes]]
SIDEBAR

echo "  wrote: _Sidebar.md"
echo ""
echo "Sync complete."
