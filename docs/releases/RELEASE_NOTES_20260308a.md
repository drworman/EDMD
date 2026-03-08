# EDMD Release Notes

---

## 20260308a

**Elite Dangerous Monitor Daemon — EDMD**

---

### Bug Fix — Kill Counter Bottleneck Included Completed Missions

**Symptom:** The kill counter displayed an inflated total and consequently a wrong remaining count. For a stack with 20 active missions where 15 had already met quota (pending turn-in), the display showed 255 kills required rather than the correct 129, and reported 147 remaining when the actual figure was closer to 120.

**Root cause:** `recalc_target_kill_totals()` summed the kill requirements of **all** active missions per issuing faction, including missions that had already received a `MissionRedirected` event (kill quota met, awaiting turn-in at the station). Those missions contributed to the bottleneck sum despite requiring no further kills, inflating the displayed total.

**Fix:** A new `mission_redirected_set` is tracked in state. `MissionRedirected` events add to this set and trigger a recalculation. `recalc_target_kill_totals()` now skips any mission whose ID is in `mission_redirected_set` when computing issuer sums, so the bottleneck reflects only missions with kills still outstanding. The set is populated from journal history during the bootstrap phase (via `bootstrap_missions()`) and cleaned up on `MissionCompleted` / `MissionAbandoned` / `MissionFailed`.

---

### Kill Display — Simplified to Remaining Count Only

All kill counter display sites have been unified to show only the number of kills remaining, dropping the `credited / total` format.

| Context | Before | After |
|---------|--------|-------|
| GUI sidebar row | `108 / 255` | `147 kills` |
| Stack-full announcement | `255 kills vs Faction` | `147 kills needed vs Faction` |
| Periodic summary | `Progress: 108/255 kills vs Faction` | `Kills: 147 remaining vs Faction` |
| Startup status block | `Kills: 108/255 vs Faction` | `Kills: 147 remaining vs Faction` |

The `credited / total` form was confusing in practice because it required knowing what "credited" meant and mentally computing the gap. The remaining count is the only number that drives decisions.

---

### Not-In-Game Detection and Output Suppression

EDMD now detects when the player is not in an active game session and alerts accordingly.

**Triggers:**
- `Music: MainMenu` journal event — fires when the player exits to the main menu (logout, character select). This is the primary signal; it arrives within seconds and is reliable across all exit paths including force-close-and-relaunch.
- `Shutdown` journal event — fires on a clean quit to desktop.
- Process check against `EliteDangerous64.exe` — performed at alert time to distinguish "client not running" from "client running but player at menu."

**Grace periods:**
- **5 minutes from EDMD startup** — allows the player time to get the game client running and log in before any check fires.
- **15 minutes from menu / quit** — covers brief interruptions (coffee, phone call, bio break) without generating noise.

**After grace expires:**
- Emits an alert at the highest loglevel configured across all `[LogLevels]` settings. If any category is configured at level 3, Discord pings the configured user.
- Re-alerts hourly while the player remains offline.
- Suppresses all other periodic output (inactivity alerts, kill rate alerts, periodic summaries) while not in game — there is nothing to report.

**Return to game:** `LoadGame` clears all offline state immediately. The next session proceeds normally.

---

### Known Limitations (unchanged)

- SLF shield state is not tracked — the game does not expose this via journal or `Status.json`
- GTK4 GUI is Linux-only; Windows users have terminal and Discord output
- Theme changes require a restart (no hot-reload for CSS)
