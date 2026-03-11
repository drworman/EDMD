"""
builtins/commander/plugin.py — Commander, ship, location, and powerplay state.

Owns: pilot_*, pp_*, ship_*, in_game, pilot_mode, location tracking.
GUI block: col=0, row=0, width=8, height=5 (default).
"""

from core.plugin_loader import BasePlugin
from core.state import RANK_NAMES
from core.emit import Terminal


class CommanderPlugin(BasePlugin):
    PLUGIN_NAME    = "commander"
    PLUGIN_DISPLAY = "Commander"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Commander", "LoadGame", "Rank", "Progress", "Reputation",
        "Location", "Docked", "Undocked",
        "FSDJump", "SupercruiseEntry",
        "ShipyardSwap", "Loadout",
        "Powerplay", "PowerplayJoin", "PowerplayLeave",
        "PowerplayDefect", "PowerplayRank", "PowerplayMerits",
        "VehicleSwitch", "Shutdown", "Music",
        "ReservoirReplenished",   # fuel level updates
    ]

    # GUI grid defaults
    DEFAULT_COL    = 0
    DEFAULT_ROW    = 0
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 6

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=10)
        # Read current fuel level from Status.json so the block shows a value
        # immediately on startup rather than waiting for the first refuel event.
        self._read_status_json(core)

    def _read_status_json(self, core) -> None:
        """Read FuelMain from Status.json for immediate display on startup."""
        import json
        from pathlib import Path
        try:
            path = Path(core.journal_dir) / "Status.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                fuel = data.get("Fuel", {})
                main = fuel.get("FuelMain")
                if main is not None:
                    core.state.fuel_current = float(main)
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:
            case "Commander":
                if not state.pilot_name:
                    state.pilot_name = event.get("Name")

            case "Rank":
                state.pilot_rank = RANK_NAMES[event["Combat"]]

            case "Progress":
                state.pilot_rank_progress = event["Combat"]

            case "Reputation":
                # Major faction standing 0-100 floats from Journal.
                # Stored as-is; display layer formats as percentages.
                rep = {}
                for faction in ("Federation", "Empire", "Alliance", "Independent"):
                    val = event.get(faction)
                    if val is not None:
                        rep[faction] = float(val)
                if rep:
                    if not hasattr(state, "pilot_reputation"):
                        state.pilot_reputation = {}
                    state.pilot_reputation.update(rep)
                    if gq: gq.put(("cmdr_update", None))

            case "LoadGame":
                state.crew_active = False
                state.in_game     = True
                state.offline_since_mono = None
                state.last_offline_alert = None
                state.pilot_ship = event.get("Ship_Localised") or event.get("Ship")
                if event.get("ShipName"):  state.ship_name  = event["ShipName"]
                if event.get("ShipIdent"): state.ship_ident = event["ShipIdent"]
                if "GameMode" in event:
                    state.pilot_mode = (
                        "Private Group" if event["GameMode"] == "Group"
                        else event["GameMode"]
                    )
                if gq: gq.put(("vessel_update", None))
                cmdrinfo = (
                    f"{state.pilot_ship} / {state.pilot_mode} / "
                    f"{state.pilot_rank} +{state.pilot_rank_progress}%"
                )
                core.emitter.emit(
                    msg_term=f"CMDR {state.pilot_name} ({cmdrinfo})",
                    msg_discord=f"**CMDR {state.pilot_name}** ({cmdrinfo})",
                    emoji="👤", sigil="-  INFO",
                    timestamp=event.get("_logtime"),
                    loglevel=2,
                )

            case "ReservoirReplenished":
                # Alerts plugin owns the burn-rate calculation and sets
                # state.fuel_current and state.fuel_burn_rate there too.
                # We only update here to ensure the commander block stays live
                # even if the alerts plugin is disabled.
                state.fuel_current = event.get("FuelMain")
                if gq: gq.put(("cmdr_update", None))

            case "Loadout":
                state.fuel_tank_size = (
                    event["FuelCapacity"]["Main"]
                    if event["FuelCapacity"]["Main"] >= 2 else 64
                )
                state.ship_name  = event.get("ShipName") or None
                state.ship_ident = event.get("ShipIdent") or None
                if gq: gq.put(("vessel_update", None))

            case "VehicleSwitch":
                to = event.get("To", "")
                if to == "Fighter":      state.cmdr_in_slf = True
                elif to == "Mothership": state.cmdr_in_slf = False
                if gq:
                    gq.put(("vessel_update", None))
                    gq.put(("slf_update",    None))

            case "Music" if event.get("MusicTrack") == "MainMenu":
                state.in_game = False
                import time
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                core.emitter.emit(
                    msg_term="Exited to main menu",
                    emoji="🚪", sigil="-  INFO",
                    timestamp=event.get("_logtime"), loglevel=2,
                )

            case "Shutdown":
                state.in_game = False
                import time
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                core.emitter.emit(
                    msg_term="Quit to desktop",
                    emoji="🛑", sigil="-  INFO",
                    timestamp=event.get("_logtime"), loglevel=2,
                )

            case "ShipyardSwap":
                state.pilot_ship = (
                    event.get("ShipType_Localised") or event["ShipType"].title()
                )
                core.emitter.emit(
                    msg_term=f"Swapped ship to {state.pilot_ship}",
                    emoji="🚢", sigil="-  SHIP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )

            case "Powerplay":
                if event.get("Power"):             state.pp_power        = event["Power"]
                if event.get("Rank") is not None:  state.pp_rank         = event["Rank"]
                if event.get("Merits") is not None: state.pp_merits_total = event["Merits"]
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayJoin":
                state.pp_power = event.get("Power"); state.pp_rank = 1
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayLeave":
                state.pp_power = state.pp_rank = state.pp_merits_total = None
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayDefect":
                state.pp_power = event.get("ToPower"); state.pp_rank = 1
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayRank":
                state.pp_rank = event.get("Rank")
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayMerits":
                if event.get("TotalMerits") is not None:
                    state.pp_merits_total = event["TotalMerits"]
                    if gq: gq.put(("cmdr_update", None))
                if event.get("Power") and not state.pp_power:
                    state.pp_power = event["Power"]

            case "Location":
                if event.get("StarSystem"): state.pilot_system = event["StarSystem"]
                if event.get("Body"):
                    state.pilot_body = event["Body"] if event.get("Docked") is False else None
                if event.get("Docked") and event.get("StationName"):
                    state.pilot_body = event["StationName"]
                elif event.get("Docked") and not event.get("StationName"):
                    state.pilot_body = None
                # Harvest local faction standings
                factions = event.get("Factions", [])
                if factions:
                    minor_rep = {}
                    for f in factions:
                        name = f.get("Name") or f.get("FactionName")
                        val  = f.get("MyReputation")
                        if name and val is not None:
                            minor_rep[name] = float(val)
                    if minor_rep:
                        state.pilot_minor_reputation = minor_rep
                if gq: gq.put(("cmdr_update", None))

            case "Docked":
                if event.get("StationName"): state.pilot_body   = event["StationName"]
                if event.get("StarSystem"):  state.pilot_system = event["StarSystem"]
                if gq: gq.put(("cmdr_update", None))

            case "Undocked":
                state.pilot_body = None
                if gq: gq.put(("cmdr_update", None))

            case "FSDJump":
                state.pilot_system = event.get("StarSystem", state.pilot_system)
                state.pilot_body   = None
                # Harvest local faction standings for the Rep tab
                factions = event.get("Factions", [])
                if factions:
                    minor_rep = {}
                    for f in factions:
                        name = f.get("Name") or f.get("FactionName")
                        val  = f.get("MyReputation")
                        if name and val is not None:
                            minor_rep[name] = float(val)
                    if minor_rep:
                        state.pilot_minor_reputation = minor_rep
                if gq: gq.put(("cmdr_update", None))
                core.emitter.emit(
                    msg_term=f"FSD jump to {event['StarSystem']}",
                    emoji="🌌", sigil=">  JUMP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )
                state.sessionend()

            case "SupercruiseEntry":
                state.pilot_system = event.get("StarSystem", state.pilot_system)
                state.pilot_body   = None
                if gq: gq.put(("cmdr_update", None))
                core.emitter.emit(
                    msg_term=f"Supercruise entry in {event['StarSystem']}",
                    emoji="🚀", sigil=">  JUMP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )
                state.sessionend()
