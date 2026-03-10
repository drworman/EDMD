# EDMD Roadmap

Last updated: 20260310

---

## Active / In Progress

### Inara Integration
- Waiting on whitelist approval from CMDR Artie — https://inara.cz/elite/cmdr/1/
- Architecture in place (same pattern as EDDN / EDSM / EDAstro)
- Will post flight logs, kills, and pull CMDR profile data to supplement local state

### FDev CAPI Integration
- Begin after Inara is shipped
- OAuth2 companion app auth flow
- Primary benefit: `/profile` endpoint gives full fleet regardless of visited shipyard
  — eliminates StoredShips / StoredModules staleness in the Assets block
- Also: live market data, shipyard, outfitting, fleet carrier inventory

---

## Near-term

### Context-aware Commander block
The Commander block currently shows fixed rows: Mode, Combat Rank, System, Body,
Fuel, Shields/Hull.  These rows should become context-aware and reuse screen
real-estate intelligently depending on what the player is doing.

**Ship mode (current behaviour)**
- Fuel: `XX%  (~Xh Xm)`
- Shields | Hull: `XX%  |  XX%`

**On foot (Odyssey)**  
When `VehicleSwitch` To="OnFoot" or equivalent Odyssey boarding events fire:
- Fuel → Battery: `XX%  (~Xm)`  (suit battery from Status.json `Oxygen` / suit charge)
- Shields | Hull → Suit Shield | Health: `XX%  |  XX%`

**SRV mode**
When `VehicleSwitch` To="SRV":
- Fuel → SRV Fuel: `XX%`  (Status.json `Fuel.FuelMain` reflects SRV tank when in SRV)
- Shields | Hull → SRV Hull: `XX%`  (HullDamage events while in SRV)

**Fighter (SLF)**
Already partially handled — header shows `[In Fighter]`.
Row labels do not need to change; SLF has no fuel display.

Implementation notes:
- `pilot_mode` on MonitorState can disambiguate (track "OnFoot" alongside
  "Open", "Solo", "Private Group")
- Status.json `Flags` bits 26-27 give on-foot / SRV state if needed
- Suit health and shield data comes from Status.json and Odyssey journal events
- All changes are purely in `commander_block.refresh()` — no plugin changes needed
  beyond subscribing to the relevant boarding/disembarking events

---

## Deferred / Parked

### Profile Switcher GUI
- Selector in menu bar or title bar
- Create-new-profile dialog writing a fully-defaulted `[PROFILENAME]` section to config.toml
- Restart with `-p PROFILENAME`

### Inara Builtin (implementation)
- Blocked on whitelist approval
- Architecture: same pattern as EDDN/EDSM/EDAstro builtins

### CAPI OAuth Flow
- Non-trivial auth flow — defer until after Inara is complete
- Will inform what additional fields Assets block can show

---

## Known Limitations / Technical Debt

- `StoredShips` and `StoredModules` data is stale between shipyard / outfitting visits
  — will be resolved by CAPI `/profile` integration
- GTK progressbar warning on close (`GtkGizmo min width -2`) — set aside intentionally
- Block collapse state is not persisted across restarts — intentional for now
