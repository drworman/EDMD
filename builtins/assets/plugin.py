"""
builtins/assets/plugin.py — Commander assets inventory.

Tracks four asset categories sourced from the journal:

  Wallet    — credit balance (Status.json, live)
  Ships     — current ship (Loadout event) + stored ships (StoredShips event)
  Modules   — modules stored away from any ship (StoredModules event)

Startup strategy
----------------
On load the plugin:
  1. Restores the last-known ship/module lists from plugin storage (data.json).
  2. Scans the last SCAN_JOURNALS journal files (newest first) for the most
     recent StoredShips and StoredModules events, overwriting storage if found.
  3. Falls back to empty lists if neither source has data.

This means the fleet list is always populated from the most recent journal data
found on disk, not just events seen in the current session.

Note: Odyssey ShipLocker inventory is in builtins/engineering/plugin.py.

State stored on MonitorState (added via hasattr guard in on_load):
    assets_balance         float   — current credit balance
    assets_current_ship    dict    — {_key, type, type_display, name, ident,
                                      system, value, hull}
    assets_stored_ships    list    — [{_key, type, type_display, name, ident,
                                        system, value, hot}]
    assets_stored_modules  list    — [{_key, name_internal, name_display,
                                        slot, system, mass, value, hot}]

CAPI note: when FDev CAPI is integrated, stored ships and modules will come
from /profile.  The state schema is forward-compatible.
"""


import json
import threading
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import normalise_ship_name

# How many journal files to scan backwards for StoredShips/StoredModules
SCAN_JOURNALS = 10


# ── Module name normalisation ─────────────────────────────────────────────────

_CLASS_MAP = {"1": "E", "2": "D", "3": "C", "4": "B", "5": "A"}

_MODULE_TYPES: dict[str, str] = {
    # Thrusters / drives
    "engine":                      "Thrusters",
    "hyperdrive":                   "Frame Shift Drive",
    "hyperdrive_overcharge":        "Overcharged FSD",
    # Power
    "powerplant":                   "Power Plant",
    "powerdistributor":             "Power Distributor",
    # Shields / armour
    "shieldgenerator":              "Shield Generator",
    "shieldbankfast":               "Shield Cell Bank",
    "shieldbank":                   "Shield Cell Bank",
    "hullreinforcement":            "Hull Reinforcement",
    "modulereinforcement":          "Module Reinforcement",
    "guardianshieldreinforcement":  "Guardian Shield Reinf.",
    "guardianhullreinforcement":    "Guardian Hull Reinf.",
    # Hardpoints — weapons
    "beamlaser":                    "Beam Laser",
    "pulselaser":                   "Pulse Laser",
    "multican":                     "Multi-cannon",
    "cannon":                       "Cannon",
    "railgun":                      "Rail Gun",
    "plasmaaccelerator":            "Plasma Accelerator",
    "mininglaser":                  "Mining Laser",
    "slugshot":                     "Fragment Cannon",
    "dumbfiremissilerack":          "Dumbfire Missiles",
    "drunkmissilerack":             "Pack-Hound Missiles",
    "causticmissile":               "Enzyme Missiles",
    "advancedtorpedopylon":         "Torpedo Pylon",
    "torpedopylon":                 "Torpedo Pylon",
    "shieldbooster":                "Shield Booster",
    "plasmapointdefence":           "Point Defence",
    "chafflauncher":                "Chaff Launcher",
    "electroniccountermeasure":     "ECM",
    "heatsinklauncher":             "Heat Sink",
    # Utilities / internals
    "sensors":                      "Sensors",
    "lifesupport":                  "Life Support",
    "fuelscoop":                    "Fuel Scoop",
    "fueltank":                     "Fuel Tank",
    "cargorack":                    "Cargo Rack",
    "corrosionproofcargorack":      "Corrosion Cargo Rack",
    "dockingcomputer":              "Docking Computer",
    "dockingcomputer_advanced":     "Advanced Docking Comp.",
    "supercruiseassist":            "Supercruise Assist",
    "detailedsurfacescanner":       "Detailed Surface Scanner",
    "fighterbay":                   "Fighter Hangar",
    "passengercabin":               "Passenger Cabin",
    "buggybay":                     "Planetary Vehicle Hangar",
    "repairer":                     "Auto Field-Maint. Unit",
    "collectorlimpetcontroller":    "Collector Limpet Ctrl",
    "prospectorlimpetcontroller":   "Prospector Limpet Ctrl",
    "miningequipment":              "Abrasion Blaster",
    "seismiccharge":                "Seismic Charge",
    "subsurfacedisplacementmissile":"Disp. Missile",
    "meta_alloy_hull_reinforcement":"Meta-Alloy Hull Reinf.",
    "planetapproachsuite":          "Planetary Approach Suite",
    "codexscanner":                 "Codex Scanner",
    "colonisation":                 "Colonisation Suite",
    "stellarbodydiscoveryscanner":  "Discovery Scanner",
    "shipdatalinkscanner":          "Data Link Scanner",
}

_MOUNT_MAP = {
    "fixed":    "Fixed",
    "gimbal":   "Gimballed",
    "turret":   "Turret",
}

_SIZE_MAP = {
    "tiny":   "0",
    "small":  "1",
    "medium": "2",
    "large":  "3",
    "huge":   "4",
}


def normalise_module_name(internal: str) -> str:
    """Convert an internal module name to a human-readable display string.

    Examples
    --------
    int_engine_size7_class5           → 7A Thrusters
    int_shieldgenerator_size8_class5  → 8A Shield Generator
    hpt_pulselaser_turret_large       → Large Pulse Laser (Turret)
    int_dockingcomputer_advanced      → Advanced Docking Comp.
    """
    if not internal:
        return "—"
    raw = internal.lower().strip()

    # Strip prefix (int_ / hpt_ / etc.)
    for prefix in ("int_", "hpt_", "ext_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    parts = raw.split("_")

    # ── Hardpoint weapons: hpt_{type}_{mount}_{size} ─────────────────────────
    # e.g. pulselaser_turret_large
    # Identify mount keyword
    mount = ""
    for i, p in enumerate(parts):
        if p in _MOUNT_MAP:
            mount = _MOUNT_MAP[p]
            parts = parts[:i] + parts[i + 1:]
            break

    # Identify size keyword (tiny/small/medium/large/huge or sizeN)
    size_str = ""
    new_parts = []
    for p in parts:
        if p in _SIZE_MAP:
            size_str = _SIZE_MAP[p].upper()
        elif p.startswith("size") and p[4:].isdigit():
            size_str = p[4:]
        else:
            new_parts.append(p)
    parts = new_parts

    # Class keyword
    class_str = ""
    new_parts = []
    for p in parts:
        if p.startswith("class") and p[5:].isdigit():
            class_str = _CLASS_MAP.get(p[5:], p[5:])
        else:
            new_parts.append(p)
    parts = new_parts

    # Look up type name from remaining parts joined
    type_key = "_".join(parts)
    type_name = _MODULE_TYPES.get(type_key)

    # Try progressively shorter prefixes if no exact match
    if type_name is None:
        for n in range(len(parts) - 1, 0, -1):
            k = "_".join(parts[:n])
            if k in _MODULE_TYPES:
                type_name = _MODULE_TYPES[k]
                break

    if type_name is None:
        # Fallback: title-case the remaining parts
        type_name = " ".join(p.title() for p in parts)

    # Assemble
    prefix_part = f"{size_str}{class_str}" if (size_str or class_str) else ""
    suffix_part = f" ({mount})" if mount else ""
    if prefix_part:
        return f"{prefix_part} {type_name}{suffix_part}"
    return f"{type_name}{suffix_part}"


# ── Plugin ────────────────────────────────────────────────────────────────────

class AssetsPlugin(BasePlugin):
    PLUGIN_NAME        = "assets"
    PLUGIN_DISPLAY     = "Assets"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Commander assets — wallet, ships, and stored modules."

    SUBSCRIBED_EVENTS = [
        # Balance
        "Statistics",
        "Commander",
        # Ships
        "Loadout",
        "StoredShips",
        # Modules
        "StoredModules",
        # Fleet carrier
        "CarrierStats",
        "CarrierJump",
        "CarrierFinance",
        # Session boundaries
        "LoadGame",
    ]


    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        if not hasattr(s, "assets_balance"):        s.assets_balance        = None
        if not hasattr(s, "assets_current_ship"):   s.assets_current_ship   = None
        if not hasattr(s, "assets_stored_ships"):   s.assets_stored_ships   = []
        if not hasattr(s, "assets_stored_modules"): s.assets_stored_modules = []
        if not hasattr(s, "assets_carrier"):        s.assets_carrier        = None
        self._shiptype_cache: dict[str, str] = {}

        # ── Step 1: build ShipType→localised name cache from Shipyard.json ────
        # Must happen before any parsing in the background scan thread.
        self._read_shipyard_json()

        # ── Step 2: restore last-known fleet from plugin storage ──────────────
        self._restore_from_storage()

        # ── Step 3: scan recent journals for StoredShips/StoredModules ────────
        # Also scans Shipyard journal events to extend the name cache with
        # ships from any station the player has ever visited.
        threading.Thread(target=self._scan_and_refresh, daemon=True,
                         name="assets-scan").start()

        # ── Step 4: read Status.json for initial balance ──────────────────────
        self._read_status_json()

    def _read_shipyard_json(self) -> None:
        """Prime the ShipType→localised name cache from Shipyard.json.

        Shipyard.json is written by the game whenever the player accesses a
        shipyard.  It contains ``ShipType`` and ``ShipType_Localised`` for
        every ship in the price list, giving us authoritative display names
        for newer ships (e.g. ``smallcombat01_nx`` → ``Kestrel Mk II``) that
        may not yet be in our static map.  We cache them in
        ``self._shiptype_cache`` so ``_parse_stored_ships`` and the Loadout
        handler can look them up.
        """
        try:
            path = Path(self.core.journal_dir) / "Shipyard.json"
            if not path.exists():
                return
            data = path.read_text(encoding="utf-8").strip()
            # Shipyard.json is a single multi-line JSON object.
            # Try whole-file parse first; fall back to line-by-line for
            # any journal-format variants (one JSON object per line).
            import json as _json
            def _index_entries(obj):
                for entry in obj.get("PriceList", []):
                    st  = entry.get("ShipType", "").lower()
                    loc = entry.get("ShipType_Localised", "")
                    if st and loc:
                        self._shiptype_cache[st] = loc
            try:
                _index_entries(_json.loads(data))
            except ValueError:
                for raw_line in data.splitlines():
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        _index_entries(_json.loads(raw_line))
                    except ValueError:
                        pass
        except Exception:
            pass

    def _localised_ship_name(self, ship_type: str) -> str:
        """Return the best display name for a ShipType internal string."""
        # 1. Shipyard.json cache (authoritative, covers newest ships)
        key = ship_type.lower()
        if key in self._shiptype_cache:
            return self._shiptype_cache[key]
        # 2. Static map
        from core.state import normalise_ship_name
        name = normalise_ship_name(ship_type)
        if name:
            return name
        # 3. Fallback: clean up underscores + title-case
        return ship_type.replace("_", " ").strip().title()

    def _restore_from_storage(self) -> None:
        """Load last-persisted ship and module lists from plugin storage."""
        try:
            saved = self.storage.read_json("data.json") or {}
            s = self.core.state
            ships   = saved.get("stored_ships")
            modules = saved.get("stored_modules")
            if isinstance(ships, list):
                s.assets_stored_ships   = ships
            if isinstance(modules, list):
                s.assets_stored_modules = modules
        except Exception:
            pass

    def _scan_and_refresh(self) -> None:
        """Scan recent journals for StoredShips/StoredModules; update state and GUI.

        StoredShips events only list ships NOT currently active, so a single
        event will be missing whichever ship the player was flying at the time.
        We therefore union across all StoredShips events in the scan window,
        keyed by ShipID, and strip the current ship out after the scan.
        """
        try:
            journal_dir = Path(self.core.journal_dir)
            journals = sorted(journal_dir.glob("Journal*.log"), reverse=True)

            # ships_by_id: accumulated union of all stored-ship records seen
            ships_by_id: dict[int, dict] = {}
            found_modules = False
            found_carrier = False
            found_loadout = False

            for jpath in journals[:SCAN_JOURNALS]:
                if found_modules and found_carrier and found_loadout:
                    break
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    if found_modules and found_carrier and found_loadout:
                        break
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    name = ev.get("event")
                    if name == "Shipyard":
                        # Extend the ShipType→localised cache from any
                        # shipyard the player has visited.
                        for entry in ev.get("PriceList", []):
                            st  = entry.get("ShipType", "").lower()
                            loc = entry.get("ShipType_Localised", "")
                            if st and loc:
                                self._shiptype_cache[st] = loc
                    elif name == "StoredShips":
                        # Accumulate — don't stop on first hit.
                        # A ship absent from one event was likely the active
                        # ship at that moment; earlier events will list it.
                        for ship_dict in self._parse_stored_ships(ev):
                            sid = ship_dict.get("ship_id")
                            if sid is not None and sid not in ships_by_id:
                                ships_by_id[sid] = ship_dict
                    elif not found_modules and name == "StoredModules":
                        mods = self._parse_stored_modules(ev)
                        self.core.state.assets_stored_modules = mods
                        found_modules = True
                    elif not found_carrier and name == "CarrierStats":
                        self.core.state.assets_carrier = self._parse_carrier_stats(ev)
                        found_carrier = True
                    elif not found_loadout and name == "Loadout":
                        ship_type   = ev.get("Ship", "")
                        ship_type_l = (ev.get("Ship_Localised")
                                       or self._localised_ship_name(ship_type))
                        if ship_type_l and ship_type:
                            self._shiptype_cache[ship_type.lower()] = ship_type_l
                        self.core.state.assets_current_ship = {
                            "_key":         "current",
                            "current":      True,
                            "ship_id":      ev.get("ShipID"),
                            "type":         ship_type,
                            "type_display": ship_type_l,
                            "name":         ev.get("ShipName", ""),
                            "ident":        ev.get("ShipIdent", ""),
                            "system":       self.core.state.pilot_system or "—",
                            "value":        ev.get("HullValue", 0),
                            "hull":         100,
                        }
                        found_loadout = True

            # Strip the current ship from stored list (it appears as current,
            # not stored).  Do this after the full scan so we have both pieces.
            current_id = (self.core.state.assets_current_ship or {}).get("ship_id")
            if current_id is not None:
                ships_by_id.pop(current_id, None)
            self.core.state.assets_stored_ships = list(ships_by_id.values())

            self._save_to_storage()
        except Exception:
            pass

        # Trigger GUI refresh on main thread
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "assets"))

    def _parse_stored_ships(self, event: dict) -> list:
        ships = []
        for section in ("ShipsHere", "ShipsRemote"):
            for s in event.get(section, []):
                ship_type = s.get("ShipType", "")
                disp = (s.get("ShipType_Localised")
                        or self._localised_ship_name(ship_type))
                name   = s.get("Name", "")
                ident  = s.get("Ident", "")
                key    = f"{s.get('ShipID', '')}_{ship_type}"
                ships.append({
                    "_key":         key,
                    "ship_id":      s.get("ShipID"),    # used to dedupe vs current ship
                    "current":      False,
                    "type":         ship_type,
                    "type_display": disp,
                    "name":         name,
                    "ident":        ident,
                    "system":       s.get("StarSystem", "—"),
                    "value":        s.get("Value", 0),
                    "hot":          s.get("Hot", False),
                })
        return ships

    def _parse_stored_modules(self, event: dict) -> list:
        mods = []
        for i, m in enumerate(event.get("Items", [])):
            internal = m.get("Name", "")
            disp = (m.get("Name_Localised") or normalise_module_name(internal))
            system = m.get("StarSystem", "—")
            key    = f"{i}_{internal}_{system}"
            mods.append({
                "_key":         key,
                "name_internal":internal,
                "name_display": disp,
                "slot":         m.get("Slot", ""),
                "system":       system,
                "mass":         m.get("Mass", 0.0),
                "value":        m.get("Value", 0),
                "hot":          m.get("Hot", False),
            })
        return mods

    def _parse_carrier_stats(self, event: dict) -> dict:
        """Extract display-relevant fields from a CarrierStats journal event."""
        fin   = event.get("Finance", {})
        space = event.get("SpaceUsage", {})
        return {
            "callsign":  event.get("Callsign", "—"),
            "name":      event.get("Name", "—"),
            "system":    event.get("CurrentStarSystem", "—"),
            "fuel":      event.get("FuelLevel", 0),       # 0–1000 tritium
            "balance":   fin.get("CarrierBalance",    0),
            "available": fin.get("AvailableBalance",  0),
            "capacity":  space.get("TotalCapacity",   0),
            "free":      space.get("FreeSpace",       0),
            "docking":   event.get("DockingAccess",   "—"),
        }

    def _save_to_storage(self) -> None:
        """Persist current ship and module lists to plugin storage."""
        try:
            s = self.core.state
            self.storage.write_json({
                "stored_ships":   getattr(s, "assets_stored_ships",   []),
                "stored_modules": getattr(s, "assets_stored_modules", []),
            }, "data.json")
        except Exception:
            pass

    def _read_status_json(self) -> None:
        """Read Balance from Status.json on startup."""
        try:
            path = Path(self.core.journal_dir) / "Status.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                bal = data.get("Balance")
                if bal is not None:
                    self.core.state.assets_balance = float(bal)
        except Exception:
            pass


    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "LoadGame":
                # LoadGame contains Balance
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Commander":
                # Some versions carry balance here too
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Statistics":
                # Statistics has a "Bank_Account" sub-object with Current_Wealth
                bank = event.get("Bank_Account", {})
                bal  = bank.get("Current_Wealth")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Loadout":
                ship_type   = event.get("Ship", "")
                ship_type_l = event.get("Ship_Localised") or self._localised_ship_name(ship_type)
                # Also prime the name cache from this event's localised name
                if ship_type_l and ship_type:
                    self._shiptype_cache[ship_type.lower()] = ship_type_l
                state.assets_current_ship = {
                    "_key":         "current",
                    "current":      True,
                    "ship_id":      event.get("ShipID"),     # used to dedupe StoredShips
                    "type":         ship_type,
                    "type_display": ship_type_l,
                    "name":         event.get("ShipName", ""),
                    "ident":        event.get("ShipIdent", ""),
                    "system":       getattr(state, "pilot_system", None) or "—",
                    "value":        event.get("HullValue", 0),
                    "hull":         100,
                }
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredShips":
                state.assets_stored_ships = self._parse_stored_ships(event)
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredModules":
                state.assets_stored_modules = self._parse_stored_modules(event)
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierStats":
                state.assets_carrier = self._parse_carrier_stats(event)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierJump":
                if state.assets_carrier is not None:
                    state.assets_carrier["system"] = event.get("SystemName", "—")
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierFinance":
                if state.assets_carrier is not None:
                    fin = event.get("Finance", {})
                    state.assets_carrier["balance"]   = fin.get("CarrierBalance",   state.assets_carrier.get("balance"))
                    state.assets_carrier["available"] = fin.get("AvailableBalance", state.assets_carrier.get("available"))
                if gq: gq.put(("plugin_refresh", "assets"))


# ── Helpers ───────────────────────────────────────────────────────────────────
