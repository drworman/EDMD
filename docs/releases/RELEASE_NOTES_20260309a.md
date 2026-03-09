# EDMD Release Notes

---

## 20260309a

**Elite Dangerous Monitor Daemon — EDMD**

---

### New Feature — Statistical Reports

A **Reports** menu has been added to the menu bar, sitting between Settings and Help.
Five reports are available, each scanning your full journal history on demand:

**Career Overview** — lifetime kills, bounties, kill rate, and top session.

**Bounty Breakdown** — kills and earnings broken down by target ship class.

**Session History** — chronological per-session table with duration, kills,
bounties, and kill rate.

**Top Hunting Grounds** — most-visited systems and venues ranked by kill count,
with full venue classification (see below).

**NPC Rogues' Gallery** — every named pilot killed or who has killed you, law
enforcement interaction summary, and player vs player record.

Reports open in a dedicated scrollable viewer window. See
[docs/REPORTS.md](docs/REPORTS.md) for full coverage of each report's data
sources and columns.

---

### New Feature — Fleet Carrier and Venue Classification in Hunting Grounds

The Top Hunting Grounds report classifies every dockable location by type,
distinguishing between venue categories that previously appeared as a generic
"station" entry or were misclassified. The full classification hierarchy:

| Type | How it is identified |
|------|----------------------|
| Your fleet carrier | `CarrierStats` event with `CarrierType = "FleetCarrier"` |
| Your squadron carrier | `CarrierStats` event with `CarrierType = "SquadronCarrier"` |
| Squadron carrier | `CarrierLocation` event with `CarrierType = "SquadronCarrier"` — docked but not managed |
| Fleet carrier | `StationType = "FleetCarrier"` with no ownership data in journals |
| Stronghold Carrier | `StationType = "StationMegaShip"` |
| Megaship | `StationType = "MegaShip"` / `"MegaShipSrv"` |
| Surface installation | `SurfaceStation`, `CraterOutpost`, `CraterPort`, `OnFootSettlement` |
| Asteroid base | `AsteroidBase` |
| Station / Outpost | All standard orbital station classes |

Fleet and squadron carriers you have ownership data for are shown as
`CALLSIGN (Name)` — for example `BZZ-89N (Vectura)`. The display name
reflects the most recently seen `CarrierStats` event in your journals, so a
renamed carrier updates automatically in future reports.

---

### New Feature — Native Documentation Viewer

A full documentation browser is built into the GUI, accessible via the
**Help** menu. All documentation is rendered natively in a GTK4 window —
no browser, no file manager, nothing external.

---

### New Feature — Preferences: Automatic Restart on Apply

Settings that require a restart (Journal folder, Discord credentials, theme)
are now marked with a ⚠ indicator in the Preferences dialog. When any such
setting is changed, a banner appears at the bottom of the dialog warning that
Apply will trigger an automatic restart. On clicking Apply, EDMD relaunches
with the same command-line arguments — profile flags and all — so the new
settings take effect immediately without any manual intervention.

Hot-reloadable settings (those marked ✅) continue to apply instantly without
any restart.

---

### Bug Fix — Preferences: Restart Used Wrong argv

When relaunching after a theme or credential change, the previous code
stripped `edmd.py` from the argument list, passing the first user flag (e.g.
`-g`) directly to the Python interpreter, which rejected it with
`Unknown option: -g`. The restart now correctly passes the full original argv
including the script path.

---

### Bug Fix — config.toml Corruption After Theme Change

Profile sub-tables (e.g. `[EDP1.Settings]`, `[EDP1.Discord]`) were being
written as Python `repr()` strings rather than valid TOML when the config was
saved via Preferences. On the next load, `tomllib` would parse these as plain
strings and crash with `'str' object has no attribute 'get'`.

The TOML writer now correctly serialises nested profile sections as
`[Profile.Section]` headers with scalar key-value pairs beneath them.
Additionally, `load_setting()` and `pcfg()` now guard against any
non-dict value at any nesting level, so a malformed config from before this fix
will degrade gracefully rather than crash.

---

### Upgrading from 20260309

No config changes required. Run `edmd.py --upgrade` or use the Upgrade button
in the GUI sidebar.

---

### Known Limitations (unchanged)

- SLF shield state is not tracked — the game does not expose this via journal
  or `Status.json`
- GTK4 GUI is Linux-only; Windows users have terminal and Discord output
