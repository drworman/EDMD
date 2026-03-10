"""
builtins/crew_slf/plugin.py — NPC Crew and SLF (Support Landing Fighter) state.

Owns: crew_*, slf_*, has_fighter_bay, cmdr_in_slf, fighter_integrity.
GUI block: col=16, row=0, width=8, height=5 (default).
"""

import re
from core.plugin_loader import BasePlugin
from core.emit import Terminal
from core.state import FIGHTER_LOADOUT_NAMES, FIGHTER_TYPE_NAMES


class CrewSlfPlugin(BasePlugin):
    PLUGIN_NAME    = "crew_slf"
    PLUGIN_DISPLAY = "NPC Crew & SLF"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "CrewAssign", "NpcCrewPaidWage", "NpcCrewRank",
        "LaunchFighter", "DockFighter", "FighterDestroyed",
        "FighterRebuilt", "FighterOrders", "RestockVehicle",
        "HullDamage", "Loadout",
    ]

    DEFAULT_COL    = 16
    DEFAULT_ROW    = 0
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 5

    _FIGHTERBAY_CAPACITY = {"3": 1, "5": 4, "6": 6}

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=15)

    def on_event(self, event: dict, state) -> None:
        core    = self.core
        gq      = core.gui_queue
        notify  = core.notify_levels
        cfg     = core.cfg
        ev      = event.get("event")
        logtime = event.get("_logtime")

        match ev:

            case "Loadout":
                # Fighter bay detection — drives crew and SLF visibility
                slf_found = False
                slf_cap   = 0
                for mod in event.get("Modules", []):
                    item = mod.get("Item", "").lower()
                    if "fighterbay" in item:
                        slf_found = True
                        m = re.search(r"fighterbay_size(\d+)", item)
                        if m:
                            slf_cap = max(slf_cap, self._FIGHTERBAY_CAPACITY.get(m.group(1), 1))
                state.has_fighter_bay = slf_found
                if slf_found:
                    state.slf_stock_total     = slf_cap or 1
                    state.slf_destroyed_count = 0
                if not slf_found:
                    state.slf_type     = None
                    state.slf_deployed = False
                    state.slf_docked   = False
                    state.slf_hull     = 100
                    state.slf_loadout  = None
                    state.crew_active  = False
                    state.crew_name    = None
                if slf_found and state.crew_name and not state.crew_active:
                    state.crew_active = True
                if gq:
                    gq.put(("slf_update",  None))
                    gq.put(("crew_update", None))

            case "FighterDestroyed" if state.prev_event != "StartJump":
                state.slf_deployed        = False
                state.slf_docked          = False
                state.slf_hull            = 0
                state.slf_orders          = None
                state.slf_destroyed_count += 1
                if gq: gq.put(("slf_update", None))
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Fighter destroyed!{Terminal.END}",
                    msg_discord="**Fighter destroyed!**",
                    emoji="💀", sigil="!! SLF ",
                    timestamp=logtime, loglevel=notify["FighterLost"],
                )

            case "LaunchFighter" if not event.get("PlayerControlled"):
                state.slf_deployed = True
                state.slf_docked   = False
                state.slf_hull     = 100
                state.slf_orders   = "Defend"
                state.slf_loadout  = event.get("Loadout")
                if gq: gq.put(("slf_update", None))
                core.emitter.emit(
                    msg_term="Fighter launched",
                    emoji="🛩️", sigil="-  SLF ",
                    timestamp=logtime, loglevel=2,
                )

            case "RestockVehicle":
                ft   = event.get("Type", "")
                lo   = event.get("Loadout", "")
                lkey = (ft, lo)
                if lkey in FIGHTER_LOADOUT_NAMES:
                    state.slf_type = FIGHTER_LOADOUT_NAMES[lkey]
                elif ft in FIGHTER_TYPE_NAMES:
                    state.slf_type = FIGHTER_TYPE_NAMES[ft]
                elif ft:
                    state.slf_type = ft.replace("_", " ").title()
                state.slf_destroyed_count = 0
                state.slf_docked          = True
                state.slf_deployed        = False
                if gq: gq.put(("slf_update", None))

            case "DockFighter":
                state.slf_deployed = False
                state.slf_docked   = True
                state.slf_hull     = 100
                state.slf_orders   = None
                if gq: gq.put(("slf_update", None))

            case "FighterRebuilt":
                state.slf_destroyed_count = max(0, state.slf_destroyed_count - 1)
                if gq: gq.put(("slf_update", None))

            case "FighterOrders":
                state.slf_orders = event.get("Orders")
                if gq: gq.put(("slf_update", None))

            case "HullDamage":
                hullhealth = round(event["Health"] * 100)
                if event.get("Fighter") and not event.get("PlayerPilot"):
                    if state.fighter_integrity != event["Health"]:
                        state.fighter_integrity = event["Health"]
                        state.slf_hull          = hullhealth
                        if gq: gq.put(("slf_update", None))
                        core.emitter.emit(
                            msg_term=(
                                f"{Terminal.WARN}Fighter hull damaged!{Terminal.END} "
                                f"(Integrity: {hullhealth}%)"
                            ),
                            msg_discord=f"**Fighter hull damaged!** (Integrity: {hullhealth}%)",
                            emoji="🛩️", sigil="^  SLF ",
                            timestamp=logtime, loglevel=notify["FighterDamage"],
                        )
                elif event.get("PlayerPilot") and not event.get("Fighter"):
                    state.ship_hull = hullhealth
                    if gq: gq.put(("vessel_update", None))
                    core.emitter.emit(
                        msg_term=(
                            f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="⚠️", sigil="^  HULL",
                        timestamp=logtime, loglevel=notify["HullEvent"],
                    )

            case "CrewAssign":
                name = event.get("Name")
                if name:
                    if state.crew_name != name:
                        state.crew_total_paid = 0
                    state.crew_name   = name
                    state.crew_active = True
                if gq: gq.put(("crew_update", None))

            case "NpcCrewPaidWage":
                wage_name = event.get("NpcCrewName")
                if not state.crew_name and wage_name:
                    state.crew_name = wage_name
                if wage_name and wage_name == state.crew_name:
                    state.crew_active = True
                    if state.crew_total_paid is None:
                        state.crew_total_paid = 0
                    state.crew_total_paid += event.get("Amount", 0)
                if gq: gq.put(("crew_update", None))

            case "NpcCrewRank":
                rank_name = event.get("NpcCrewName")
                if not state.crew_name and rank_name:
                    state.crew_name = rank_name
                if rank_name and rank_name == state.crew_name:
                    state.crew_rank = event.get("RankCombat", state.crew_rank)
                if gq: gq.put(("crew_update", None))
