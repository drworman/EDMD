# EDMD Release Notes

---

## 20260310

**Elite Dangerous Monitor Daemon — EDMD**

Feature release. Adds Windows and macOS GUI support documentation and
installers, automatic layout migration for new blocks, and the Cargo and
Materials dashboard blocks introduced in 20260309b/c.

---

### Feature — Windows and macOS GUI Support (best-effort)

The GTK4 GUI is no longer documented as Linux-only. Two paths for Windows
and one path for macOS are now provided, each with a dedicated guide and
installer.

**macOS** — GTK4 and PyGObject are available via Homebrew. Installation
is straightforward and the GUI is expected to work on macOS 13 Ventura or
newer with no code changes required.

```bash
bash install_macos.sh
```

Full guide: `docs/guides/MACOS_SETUP.md`

**Windows — Option A (MSYS2, recommended)** — GTK4 and PyGObject are
available via MSYS2's `pacman`. EDMD runs inside the MSYS2 UCRT64 terminal.
This is the officially recommended PyGObject on Windows path.

```bash
# Inside the MSYS2 UCRT64 terminal
bash install_msys2.sh
```

**Windows — Option B (gvsbuild, advanced)** — Builds GTK4 natively using
Visual Studio Build Tools. EDMD runs from a standard CMD or PowerShell
window with no MSYS2 dependency.

```bat
install_gvsbuild.bat
```

Full guide: `docs/guides/WINDOWS_GUI.md`

**Developer notice:** EDMD is developed and tested exclusively on Linux.
Windows and macOS GUI support is a best-effort community resource. The
developer does not have access to these platforms and cannot provide direct
troubleshooting for platform-specific installation issues. Terminal mode
continues to work on all platforms with no additional setup, and remains
the recommended path on Windows and macOS if GTK4 installation proves
difficult.

**Terminal mode is unaffected on all platforms.** Linux support is
unchanged.

---

### Feature — Automatic Layout Migration for New Blocks

When a new block is introduced in a future release, `layout.json` no
longer needs to be manually deleted. On startup, the grid engine now
compares the saved layout against `DEFAULT_LAYOUT` and backfills any
missing entries at their default positions, then re-saves the file. Users
who have customised their layout retain all existing positions.

---

### Feature — Cargo Dashboard Block

A live cargo hold display in the dashboard. Shows current / maximum
tonnage in the block header with colour-coded fill states (ok / warn /
full), a scrollable sorted item list, and stolen-goods flagging. Reads
directly from `Cargo.json` rather than journal event payloads, ensuring
SRV and fighter cargo events never overwrite ship hold data.

---

### Feature — Materials Dashboard Block

Engineering materials inventory across the three categories (Raw,
Manufactured, Encoded) in a single unified scrollable block. Item counts
update live as materials are collected, traded, or consumed at engineers.

---

### Feature — Data Contribution Plugins (EDDN, EDSM, EDAstro)

Opt-in journal uploading to the three major community data networks:

- **EDDN** — market, outfitting, shipyard, and exploration data to the
  Elite Dangerous Data Network
- **EDSM** — flight log and discovery data to edsm.net
- **EDAstro** — exploration, organic scan, and carrier data to edastro.com

All three are disabled by default and configured under
`Preferences → Data & Integrations`. Each plugin maintains a disk-backed
retry queue so events are not lost on network failure.

The `PrimaryInstance` setting (`[Settings] PrimaryInstance = false`)
suppresses uploads on secondary or remote instances sharing a journal
folder, preventing duplicate submissions.

---

### Feature — Alerts Clear Button

A Clear button in the Alerts block drains the alert queue immediately.

---

### Feature — Ghost Drag and Resize

Block drag and resize operations now use a ghost overlay rather than
moving the real block during the gesture. Eliminates visual stutter on
slow redraws and makes large moves feel snappier.

---

### Upgrading

No config changes required when upgrading from 20260309c.

If upgrading from 20260309b or earlier and EDSM or EDAstro were enabled
during that session, no events were successfully delivered (a serialisation
bug prevented all sends). There is nothing to replay — both services will
resume normal uploads immediately on restart with this release.

layout.json does not need to be deleted. The grid engine will backfill any
missing block entries automatically.

---

### Known Limitations

- SLF shield state is not tracked — the game does not expose this via the
  journal or `Status.json`
- GTK4 GUI is Linux-native; Windows and macOS are best-effort
- Inara integration is pending whitelist approval from CMDR Artie
- CAPI integration is deferred (OAuth complexity, marginal benefit)
- GTK progress bar cosmetic warning on window close is known and set aside
