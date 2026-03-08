# EDMD Release Notes

---

## 20260308.00

**Elite Dangerous Monitor Daemon — EDMD**

---

### In-Place Upgrade — `--upgrade`

EDMD can now update itself from GitHub and restart without user intervention.

```bash
edmd.py --upgrade
```

**Behaviour:**
- Verifies `git` is available and the installation is a git clone
- Warns if uncommitted local changes are detected (other than `config.toml`) and asks for confirmation before proceeding
- Runs `git pull --ff-only` to fetch the latest release
- Re-runs `install.sh` (Linux/macOS) or `install.bat` (Windows) to pick up any new or updated dependencies
- Replaces the running process via `os.execv` — same terminal session, same arguments, no subprocess overhead
- If already up to date, exits cleanly with no action

`--upgrade` is mutually exclusive with all other flags. Passing any other argument alongside it is an error.

**GUI — Upgrade button:** When a new version is detected at startup, an **Upgrade** button appears in the sidebar below the sponsor links. Clicking it saves session state and relaunches into `--upgrade` automatically — no terminal required.

**Terminal — updated notice:** The update available notice now includes the `--upgrade` invocation for quick reference.

---

### User Data Directory and Config Migration

EDMD now creates and uses a platform-appropriate user data directory for all runtime files, including `config.toml`.

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/EDMD/` |
| Windows | `%APPDATA%\EDMD\` |
| macOS | `~/Library/Application Support/EDMD/` |

On Linux, a symlink is created at `~/.config/EDMD` → `~/.local/share/EDMD/` for XDG hygiene. Either path works.

**Config resolution order:**
1. User data directory (`~/.local/share/EDMD/config.toml`) — primary
2. Repo-adjacent (`<install dir>/config.toml`) — fallback for portable or development installs

`install.sh` now creates `config.toml` in the user data directory automatically. The "config not found" error message shows both expected paths explicitly.

**Existing installs:** move `config.toml` from the repo directory to `~/.local/share/EDMD/config.toml` and EDMD will find it there on next launch. The repo-adjacent path continues to work as a fallback indefinitely.

---

### Session State Persistence

EDMD now preserves active session counters across upgrade restarts and clean exits.

A lightweight JSON snapshot is written to the user data directory before `os.execv` fires and on `Ctrl+C` exit. On next startup, if the snapshot references the same journal file that is currently active, session counters are restored before monitoring begins.

**Persisted fields:**
- Kill count, credit total, merit total
- Faction kill tally
- Kill interval data (for rate calculations)
- Inbound scan and low cargo counts
- Session start time (for accurate duration display)

**Not persisted** (re-derived from journal bootstrap as before):
- Mission kill totals and target faction maps
- Pilot, ship, crew, and SLF state
- Alert timers (reset on restart — brief gap is acceptable)
- Periodic summary timer (reset to prevent an immediate summary on relaunch)

The snapshot is keyed to the active journal filename. If the journal has rolled over between exit and restart, the snapshot is discarded — stale state from a prior session is never restored.

State file: `<user data dir>/session_state.json`

---

### Bug Fix — NPC Crew Panel Missing After Relog

**Symptom:** The NPC crew block disappeared from the GUI after logging out to the main menu and back in, even when crew was still hired.

**Root cause:** `LoadGame` correctly sets `crew_active = False` pending re-confirmation. `CrewAssign` re-fires on relog only when the player explicitly interacts with crew during that session — it does not always fire automatically. `bootstrap_crew()` runs only once at initial preload and was not called again on relog.

**Fix:** In the `Loadout` handler, after `has_fighter_bay` is resolved: if a fighter bay is present, `crew_name` is known, and `crew_active` is still `False`, `crew_active` is set to `True` immediately. The existing `crew_update` queue push then redraws the panel. No bootstrap re-run required.

---

### Avatar — Theme Variants

Seven theme-matched avatar variants have been added to `images/`:

| Theme | File |
|-------|------|
| `default` / `default-dark` | `edmd_avatar_512.png` / `edmd_avatar_4096.png` |
| `default-blue` | `edmd_avatar_blue_512.png` / `edmd_avatar_blue_4096.png` |
| `default-green` | `edmd_avatar_green_512.png` / `edmd_avatar_green_4096.png` |
| `default-purple` | `edmd_avatar_purple_512.png` / `edmd_avatar_purple_4096.png` |
| `default-red` | `edmd_avatar_red_512.png` / `edmd_avatar_red_4096.png` |
| `default-yellow` | `edmd_avatar_yellow_512.png` / `edmd_avatar_yellow_4096.png` |
| `default-light` | `edmd_avatar_light_512.png` / `edmd_avatar_light_4096.png` |

All variants share the same Concept D geometry (concentric rings, hexagon, central lens/iris, cardinal ticks with 45° sub-ticks, crosshair lines). Accent colour matches the active theme.

**GUI:** The sidebar avatar resolves the correct variant at startup from the active theme name. Falls back to the default orange variant for unknown or custom theme names.

**Discord webhook:** `AVATAR_URL` updated to point to `edmd_avatar_512.png` in the repo.

---

### GUI — Avatar in Sidebar

A 72×72px avatar mark is now displayed at the top of the sponsor/links panel in the sidebar. Rendered at 55% opacity, centred, using the theme-matched variant. Fails silently if the image file is not found.

---

### GUI — Upgrade Button CSS

New `.upgrade-btn` class added to `themes/base.css`. Uses `--accent` background with black text and a `color-mix` hover state. Applies to all themes automatically via the base stylesheet.

---

### Command Line Arguments — Audit and Cleanup

**Removed:** `--resetsession` / `-r` — this flag was defined but never read after `args = parser.parse_args()`. It had no effect. Removed from code and documentation.

**Added:** `--upgrade` — documented above.

**Documented (previously undocumented):**
- `--test` / `-t` — re-routes Discord output to terminal instead of sending to webhook. Useful for verifying notification formatting without sending live messages.
- `--trace` / `-d` — prints verbose debug and trace output to terminal.

README Command Line Arguments section updated accordingly.

---

### Documentation — Guides

Three new guides added to `docs/guides/`:

**`LINUX_SETUP.md`** — Getting Elite Dangerous running on Linux with Steam, Proton, Minimal ED Launcher, EDMC, and EDMD. Includes an `edquit` session cleanup script targeting only the known ED process stack.

**`DUAL_PILOT.md`** — Running two accounts simultaneously on a single machine with independent Proton prefixes, journal directories, EDMC profiles, and EDMD profiles.

**`REMOTE_ACCESS.md`** — Running the EDMD GUI on a secondary machine (e.g. laptop) as a thin-client front-end against the game machine's live session. Covers SSH key setup, optional DuckDNS WAN access, the `[REMOTE]` config profile, and the `edmd_launch.sh` context-aware launcher script.

`docs/` restructured:
```
docs/
├── guides/
│   ├── LINUX_SETUP.md
│   ├── DUAL_PILOT.md
│   └── REMOTE_ACCESS.md
└── releases/
    ├── RELEASE_NOTES_20260306.md
    ├── RELEASE_NOTES_20260307.md
    └── RELEASE_NOTES_20260308.md
```

README updated with a `## Guides` section linking all three.

---

### Documentation — `example.config.toml`

- Dead `PeriodicKills`, `PeriodicCredits`, `PeriodicMerits`, and `PeriodicFaction` log level keys removed — these keys are defined in defaults but never consulted by any emit call and have no effect
- `WarnCooldown` and `FullStackSize` settings added (were missing from the example)
- `[REMOTE]` profile and `[REMOTE.LogLevels]` block added as a ready-to-use template for the remote access setup
- Default `BountyValue` corrected to `false` (example previously showed `true`)
- Log level comments updated: level 1 now reads "Terminal / GUI only" to reflect GUI support
- `GUI.Enabled` default corrected to `false` (example previously showed `true`)

---

### Known Limitations (unchanged)

- SLF shield state is not tracked — the game does not expose this via journal or `Status.json`
- GTK4 GUI is Linux-only; Windows users have terminal and Discord output
- Theme changes require a restart (no hot-reload for CSS)
