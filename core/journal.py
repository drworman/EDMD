"""
core/journal.py — Journal file monitoring, event dispatch, and bootstrap logic.

Depends on: core.state, core.config, core.emit
"""

import json
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from core.state import (
    EDMD_DATA_DIR,
    FIGHTER_LOADOUT_NAMES,
    FIGHTER_TYPE_NAMES,
    FUEL_CRIT_THRESHOLD,
    FUEL_WARN_THRESHOLD,
    GITHUB_REPO,
    LABEL_UNKNOWN,
    PIRATE_NOATTACK_MSGS,
    RANK_NAMES,
    RECENT_KILL_WINDOW,
    MonitorState,
    SessionData,
    load_session_state,
    save_session_state,
)
from core.emit import (
    Terminal,
    Emitter,
    emit_summary,
    fmt_credits,
    fmt_duration,
    rate_per_hour,
    clip_name,
)


# ── Process detection ─────────────────────────────────────────────────────────

_ED_PROCESS_NAMES = {"EliteDangerous64.exe", "EliteDangerous32.exe", "EliteDangerous.exe"}


def _ed_client_running() -> bool:
    try:
        for proc in psutil.process_iter(["name"]):
            if proc.info.get("name") in _ED_PROCESS_NAMES:
                return True
    except Exception:
        pass
    return False


def _max_notify_level(notify_levels: dict) -> int:
    return max((v for v in notify_levels.values() if isinstance(v, int)), default=2)


# ── Status.json polling ───────────────────────────────────────────────────────

_STATUS_JSON_POLL_INTERVAL = 0.5


def _poll_status_json(
    journal_dir: Path,
    state: MonitorState,
    gui_queue: queue.Queue | None,
) -> None:
    """Background thread: tail Status.json for shield/pilot-in-SLF flags."""
    status_path = journal_dir / "Status.json"
    last_flags  = None

    while True:
        try:
            if status_path.is_file():
                raw = status_path.read_text(encoding="utf-8").strip()
                if raw:
                    data  = json.loads(raw)
                    flags = data.get("Flags", 0)
                    if flags != last_flags:
                        last_flags = flags
                        changed    = False

                        shields_up = bool(flags & 0x08)
                        if state.ship_shields != shields_up:
                            state.ship_shields = shields_up
                            if shields_up:
                                state.ship_shields_recharging = False
                            changed = True

                        in_fighter = bool(flags & 0x2000000)
                        if state.cmdr_in_slf != in_fighter:
                            state.cmdr_in_slf = in_fighter
                            changed = True

                        if changed and gui_queue:
                            gui_queue.put(("vessel_update", None))
                            gui_queue.put(("slf_update",    None))
        except Exception:
            pass
        time.sleep(_STATUS_JSON_POLL_INTERVAL)


# ── Journal utilities ─────────────────────────────────────────────────────────

def find_latest_journal(journal_dir: Path) -> Path | None:
    journals = sorted(journal_dir.glob("Journal*.log"), reverse=True)
    return journals[0] if journals else None


def trace(message: str, trace_mode: bool = False) -> None:
    if trace_mode:
        print(
            f"{Terminal.WHITE}[Debug]{Terminal.END} {message} "
            f"[{datetime.strftime(datetime.now(), '%H:%M:%S')}]"
        )


# ── Bootstrap functions ───────────────────────────────────────────────────────

def bootstrap_slf(state: MonitorState, journal_dir: Path, trace_mode: bool = False) -> None:
    """Recover SLF type and deployed/docked state from journal history."""
    if not state.has_fighter_bay:
        return

    journals    = sorted(journal_dir.glob("Journal*.log"), reverse=True)
    STATE_EVENTS = {"LaunchFighter", "DockFighter", "FighterDestroyed"}
    slf_state_known = False
    slf_type_known  = state.slf_type is not None

    for jpath in journals:
        try:
            lines = jpath.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                try:
                    je = json.loads(line)
                except ValueError:
                    continue
                ev = je.get("event")

                if not slf_state_known and ev in STATE_EVENTS:
                    if ev == "LaunchFighter" and not je.get("PlayerControlled", True):
                        state.slf_deployed = True
                        state.slf_docked   = False
                        state.slf_loadout  = je.get("Loadout", state.slf_loadout)
                        trace(f"SLF bootstrap: deployed from {jpath.name}", trace_mode)
                    elif ev == "DockFighter":
                        state.slf_deployed = False
                        state.slf_docked   = True
                        trace(f"SLF bootstrap: docked from {jpath.name}", trace_mode)
                    elif ev == "FighterDestroyed":
                        state.slf_deployed = False
                        state.slf_docked   = False
                        state.slf_hull     = 0
                        trace(f"SLF bootstrap: destroyed from {jpath.name}", trace_mode)
                    slf_state_known = True

                if not slf_type_known and ev == "RestockVehicle":
                    ft   = je.get("Type", "")
                    lo   = je.get("Loadout", "")
                    key  = (ft, lo)
                    if key in FIGHTER_LOADOUT_NAMES:
                        state.slf_type = FIGHTER_LOADOUT_NAMES[key]
                    elif ft in FIGHTER_TYPE_NAMES:
                        state.slf_type = FIGHTER_TYPE_NAMES[ft]
                    elif ft:
                        state.slf_type = ft.replace("_", " ").title()
                    trace(f"SLF bootstrap: type={state.slf_type!r} from {jpath.name}", trace_mode)
                    slf_type_known = True

                if slf_state_known and slf_type_known:
                    break
        except OSError:
            continue
        if slf_state_known and slf_type_known:
            break


def bootstrap_crew(state: MonitorState, journal_dir: Path, trace_mode: bool = False) -> None:
    """Recover crew name, hire date, rank, and total paid from journal history."""
    if not state.has_fighter_bay:
        return

    journals = sorted(journal_dir.glob("Journal*.log"))  # oldest first

    if not state.crew_name:
        for jpath in reversed(journals):
            try:
                lines = jpath.read_text(encoding="utf-8").splitlines()
                for line in reversed(lines):
                    try:
                        je = json.loads(line)
                    except ValueError:
                        continue
                    ev = je.get("event")
                    if ev == "CrewAssign":
                        name = je.get("Name")
                        if name:
                            state.crew_name   = name
                            state.crew_active = True
                            trace(f"Crew bootstrap: name from history: {name!r}", trace_mode)
                            break
                    elif ev == "NpcCrewPaidWage":
                        name = je.get("NpcCrewName")
                        if name:
                            state.crew_name   = name
                            state.crew_active = True
                            trace(f"Crew bootstrap: name from NpcCrewPaidWage: {name!r}", trace_mode)
                            break
                    elif ev == "LoadGame":
                        break
                if state.crew_name:
                    break
            except OSError:
                continue

    if not state.crew_name:
        return

    earliest_time        = None
    found_rank           = None
    total_paid           = 0
    first_assign_journal = None

    for jpath in journals:
        try:
            with open(jpath, mode="r", encoding="utf-8") as f:
                for line in f:
                    try:
                        je = json.loads(line)
                    except ValueError:
                        continue
                    ev = je.get("event")
                    if ev == "CrewAssign" and je.get("Name") == state.crew_name:
                        t = datetime.fromisoformat(je["timestamp"]) if "timestamp" in je else None
                        if t and (earliest_time is None or t < earliest_time):
                            earliest_time        = t
                            first_assign_journal = jpath
                    elif ev == "NpcCrewRank" and je.get("NpcCrewName") == state.crew_name:
                        found_rank = je.get("RankCombat", found_rank)
                    elif ev == "NpcCrewPaidWage" and je.get("NpcCrewName") == state.crew_name:
                        total_paid += je.get("Amount", 0)
        except OSError:
            continue

    if earliest_time:
        state.crew_hire_time = earliest_time
        trace(f"Crew bootstrap: {state.crew_name} first seen at {earliest_time}", trace_mode)
    if found_rank is not None and state.crew_rank is None:
        state.crew_rank = found_rank
    if total_paid > 0:
        state.crew_total_paid = total_paid
    if first_assign_journal is not None and journals:
        state.crew_paid_complete = (first_assign_journal == journals[0])
    else:
        state.crew_paid_complete = False


def bootstrap_missions(
    state: MonitorState,
    journal_dir: Path,
    cfg_mgr,
    trace_mode: bool = False,
) -> None:
    """Reconstruct active massacre mission list and stack value from all journals."""
    journals  = sorted(journal_dir.glob("Journal*.log"))  # oldest first
    accepted  = {}
    redirected = set()

    for jpath in journals:
        try:
            with open(jpath, mode="r", encoding="utf-8") as f:
                for line in f:
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    ev  = j.get("event")
                    mid = j.get("MissionID")

                    if ev == "MissionAccepted" and "Mission_Massacre" in j.get("Name", ""):
                        accepted[mid] = {"reward": j.get("Reward", 0), "expires": j.get("Expiry", None)}
                    elif ev in ("MissionCompleted", "MissionAbandoned", "MissionFailed"):
                        accepted.pop(mid, None)
                        redirected.discard(mid)
                    elif ev == "MissionRedirected" and "Mission_Massacre" in j.get("Name", ""):
                        redirected.add(mid)
        except OSError:
            continue

    if not accepted:
        print(f"{Terminal.YELL}Mission bootstrap:{Terminal.END} No active massacre missions found")
        return

    now = datetime.now(timezone.utc)

    def _not_expired(data):
        exp = data.get("expires")
        if not exp:
            return True
        try:
            return datetime.fromisoformat(str(exp)) > now
        except (ValueError, TypeError):
            return True

    accepted           = {mid: d for mid, d in accepted.items() if _not_expired(d)}
    active_redirected  = redirected & accepted.keys()

    state.active_missions         = list(accepted.keys())
    state.mission_value_map       = {mid: d["reward"] for mid, d in accepted.items()}
    state.stack_value             = sum(d["reward"] for d in accepted.values())
    state.missions_complete       = len(active_redirected)
    state.missions                = True

    print(
        f"{Terminal.YELL}Mission bootstrap:{Terminal.END} "
        f"{len(state.active_missions)} active | "
        f"{state.missions_complete} complete | "
        f"Stack: {fmt_credits(state.stack_value)}"
    )


# ── Dispatch map builder ─────────────────────────────────────────────────────

def build_dispatch_map(plugins: list) -> dict:
    """Build an event_name -> [plugin, ...] lookup from a list of loaded plugins.

    Called once after PluginLoader.load_all() completes.  The resulting dict
    is passed into monitor_journal / run_monitor as plugin_dispatch.
    """
    dispatch: dict = {}
    for plugin in plugins:
        for event_name in plugin.SUBSCRIBED_EVENTS:
            dispatch.setdefault(event_name, []).append(plugin)
    return dispatch


# ── Event handler ─────────────────────────────────────────────────────────────

def handle_event(
    line: str,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
) -> None:
    try:
        j = json.loads(line)
    except ValueError:
        print(f"{Terminal.WHITE}Warning:{Terminal.END} Journal parsing error, skipping line")
        return

    # ── Plugin dispatch (Phase 2+) ────────────────────────────────────────────
    # When plugin_dispatch is provided, forward the event to all subscribed
    # plugins.  The legacy match block below is retained during this transition.
    if plugin_dispatch is not None:
        ev_name = j.get("event", "")
        logtime = datetime.fromisoformat(j["timestamp"]) if "timestamp" in j else None
        j["_logtime"] = logtime
        state.event_time = logtime
        for plugin in plugin_dispatch.get(ev_name, []):
            try:
                plugin.on_event(j, state)
            except Exception as e:
                print(
                    f"{Terminal.WARN}Warning:{Terminal.END} "
                    f"Plugin {plugin.PLUGIN_NAME!r} error on {ev_name!r}: {e}"
                )
        state.prev_event = ev_name
        return

    # Legacy path: no plugin_dispatch provided.
    # plugin_call is a no-op so KSW call sites degrade gracefully.
    def plugin_call(_name, _method, *_a, **_kw):  # noqa: E306
        return None

    notify = cfg_mgr.notify_levels
    settings = cfg_mgr.app_settings
    max_trunc = settings.get("TruncateNames", 30)

    try:
        logtime     = datetime.fromisoformat(j["timestamp"]) if "timestamp" in j else None
        state.event_time = logtime

        match j["event"]:

            # ── NPC TEXT ──────────────────────────────────────────────────
            case "ReceiveText" if j["Channel"] == "npc":
                if "$Pirate_OnStartScanCargo" in j["Message"]:
                    piratename = j.get("From_Localised", LABEL_UNKNOWN)
                    if piratename not in active_session.recent_inbound_scans:
                        active_session.inbound_scan_count += 1
                        lifetime.inbound_scan_count       += 1
                        count_str = (
                            f" (x{active_session.inbound_scan_count})"
                            if settings.get("ExtendedStats") else ""
                        )
                        pirate_str = f" [{piratename}]" if settings.get("PirateNames") else ""
                        if len(active_session.recent_inbound_scans) == 5:
                            active_session.recent_inbound_scans.pop(0)
                        active_session.recent_inbound_scans.append(piratename)
                        emitter.emit(
                            msg_term=f"Cargo scan{count_str}{pirate_str}",
                            msg_discord=f"**Cargo scan{count_str}**{pirate_str}",
                            emoji="📦", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )
                elif any(x in j["Message"] for x in PIRATE_NOATTACK_MSGS):
                    active_session.low_cargo_count += 1
                    count_str = (
                        f" (x{active_session.low_cargo_count})"
                        if settings.get("ExtendedStats") else ""
                    )
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.WARN}"
                            f'Pirate didn"t engage due to insufficient cargo value'
                            f"{count_str}{Terminal.END}"
                        ),
                        msg_discord=(
                            f'**Pirate didn"t engage due to insufficient cargo value**'
                            f"{count_str}"
                        ),
                        emoji="📦", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["LowCargoValue"],
                        event="LowCargoValue",
                    )
                elif "Police_Attack" in j["Message"]:
                    emitter.emit(
                        msg_term=f"{Terminal.BAD}Under attack by security services!{Terminal.END}",
                        msg_discord="**Under attack by security services!**",
                        emoji="🚨", sigil="!! ATCK",
                        timestamp=logtime, loglevel=notify["PoliceAttack"],
                    )

            # ── TARGET SCANNED ────────────────────────────────────────────
            case "ShipTargeted" if "Ship" in j:
                ship = j.get("Ship_Localised") or j["Ship"].title()
                rank = "" if "PilotRank" not in j else f" ({j['PilotRank']})"
                if (
                    ship != active_session.last_security_ship
                    and "PilotName" in j
                    and "$ShipName_Police" in j["PilotName"]
                ):
                    active_session.last_security_ship = ship
                    emitter.emit(
                        msg_term=f"{Terminal.WARN}Scanned security{Terminal.END} ({ship})",
                        msg_discord=f"**Scanned security** ({ship})",
                        emoji="🔍", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["PoliceScan"],
                    )
                else:
                    state.sessionstart(active_session)
                    piratename = j.get("PilotName_Localised", LABEL_UNKNOWN)
                    check      = piratename if settings.get("MinScanLevel") != 0 else ship
                    scanstage  = j.get("ScanStage", 0)
                    if (
                        scanstage >= settings.get("MinScanLevel", 1)
                        and check not in active_session.recent_outbound_scans
                    ):
                        if len(active_session.recent_outbound_scans) == 10:
                            active_session.recent_outbound_scans.pop(0)
                        active_session.recent_outbound_scans.append(check)
                        pirate_str = (
                            f" [{piratename}]"
                            if settings.get("PirateNames") and piratename != LABEL_UNKNOWN
                            else ""
                        )
                        emitter.emit(
                            msg_term=f"{Terminal.WHITE}Scan{Terminal.END}: {ship}{rank}{pirate_str}",
                            msg_discord=f"**{ship}**{rank}{pirate_str}",
                            emoji="🔍", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )

            # ── KILLS ─────────────────────────────────────────────────────
            case "Bounty" | "FactionKillBond":
                state.sessionstart(active_session)
                if settings.get("MinScanLevel") == 0:
                    active_session.recent_outbound_scans.clear()

                active_session.kills   += 1
                lifetime.kills         += 1
                thiskill                = logtime
                killtime_str            = ""
                state.last_rate_check   = time.monotonic()
                active_session.pending_merit_events += 1

                if active_session.last_kill_time:
                    secs = (thiskill - active_session.last_kill_time).total_seconds()
                    killtime_str = f" (+{fmt_duration(secs)})"
                    active_session.kill_interval_total += secs
                    if len(active_session.recent_kill_times) == RECENT_KILL_WINDOW:
                        active_session.recent_kill_times.pop(0)
                    active_session.recent_kill_times.append(secs)
                    lifetime.kill_interval_total += secs

                active_session.last_kill_time = logtime
                if not state.in_preload:
                    active_session.last_kill_mono = time.monotonic()

                if j["event"] == "Bounty":
                    bountyvalue = j["Rewards"][0]["Reward"]
                    ship        = j.get("Target_Localised") or j["Target"].title()
                else:
                    bountyvalue      = j["Reward"]
                    ship             = "Bond"
                    state.reward_type = "bonds"

                pirate_str = (
                    f" [{clip_name(j['PilotName_Localised'], max_trunc)}]"
                    if "PilotName_Localised" in j and settings.get("PirateNames")
                    else ""
                )
                active_session.credit_total += bountyvalue
                lifetime.credit_total       += bountyvalue

                kills_t = f" x{active_session.kills}" if settings.get("ExtendedStats") else ""
                kills_d = f"x{active_session.kills} " if settings.get("ExtendedStats") else ""
                bv_str  = (
                    f" [{fmt_credits(bountyvalue)} cr]"
                    if settings.get("BountyValue") else ""
                )
                victimfaction = j.get("VictimFaction_Localised") or j.get("VictimFaction", "")
                active_session.faction_tally[victimfaction] = (
                    active_session.faction_tally.get(victimfaction, 0) + 1
                )
                lifetime.faction_tally[victimfaction] = (
                    lifetime.faction_tally.get(victimfaction, 0) + 1
                )
                fc_count = (
                    f" x{active_session.faction_tally[victimfaction]}"
                    if settings.get("ExtendedStats") else ""
                )
                bf_str = (
                    f" [{clip_name(victimfaction, max_trunc)}{fc_count}]"
                    if settings.get("BountyFaction") else ""
                )
                emitter.emit(
                    msg_term=(
                        f"{Terminal.WHITE}Kill{Terminal.END}{kills_t}: "
                        f"{ship}{killtime_str}{pirate_str}{bv_str}{bf_str}"
                    ),
                    msg_discord=(
                        f"{kills_d}**{ship}{killtime_str}**"
                        f"{pirate_str}{bv_str}{bf_str}"
                    ),
                    emoji="💥", sigil="*  KILL",
                    timestamp=logtime, loglevel=notify["RewardEvent"],
                )

            # ── FUEL ──────────────────────────────────────────────────────
            case "ReservoirReplenished":
                fuel_pct = round((j["FuelMain"] / state.fuel_tank_size) * 100)
                fuel_time_remain = ""
                if (
                    active_session.fuel_check_time
                    and state.session_start_time
                    and logtime > active_session.fuel_check_time
                ):
                    fuel_time   = (logtime - active_session.fuel_check_time).total_seconds()
                    fuel_hour   = 3600 / fuel_time * (active_session.fuel_check_level - j["FuelMain"])
                    fuel_remain = fmt_duration(j["FuelMain"] / fuel_hour * 3600) if fuel_hour > 0 else None
                    if fuel_remain:
                        fuel_time_remain = f" (~{fuel_remain})"
                active_session.fuel_check_time  = logtime
                active_session.fuel_check_level = j["FuelMain"]
                col = ""; level = ":"; fuel_loglevel = 0
                if j["FuelMain"] < state.fuel_tank_size * FUEL_CRIT_THRESHOLD:
                    col = Terminal.BAD;  fuel_loglevel = notify["FuelCritical"]; level = " critical!"
                elif j["FuelMain"] < state.fuel_tank_size * FUEL_WARN_THRESHOLD:
                    col = Terminal.WARN; fuel_loglevel = notify["FuelWarning"];  level = " low:"
                elif state.session_start_time:
                    fuel_loglevel = notify["FuelStatus"]
                emitter.emit(
                    msg_term=f"{col}Fuel: {fuel_pct}% remaining{Terminal.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuel_pct}% remaining**{fuel_time_remain}",
                    emoji="⛽", sigil="+  FUEL",
                    timestamp=logtime, loglevel=fuel_loglevel,
                )
                if cfg_mgr.pcfg("QuitOnLowFuel"):
                    _fp = cfg_mgr.pcfg("QuitOnLowFuelPercent", 20)
                    _fm = cfg_mgr.pcfg("QuitOnLowFuelMinutes", 30)
                    _pt = fuel_pct <= _fp; _tt = False
                    if (
                        active_session.fuel_check_time and state.session_start_time
                        and 'fuel_hour' in dir() and fuel_hour > 0
                    ):
                        _tt = (j["FuelMain"] / fuel_hour) * 60 <= _fm
                    if _pt or _tt:
                        plugin_call("ksw", "flush_session")

            # ── FIGHTER EVENTS ────────────────────────────────────────────
            case "FighterDestroyed" if state.prev_event != "StartJump":
                state.slf_deployed       = False
                state.slf_docked         = False
                state.slf_hull           = 0
                state.slf_orders         = None
                state.slf_destroyed_count += 1
                if gui_queue: gui_queue.put(("slf_update", None))
                emitter.emit(
                    msg_term=f"{Terminal.BAD}Fighter destroyed!{Terminal.END}",
                    msg_discord="**Fighter destroyed!**",
                    emoji="💀", sigil="!! SLF ",
                    timestamp=logtime, loglevel=notify["FighterLost"],
                )
                if cfg_mgr.pcfg("QuitOnSLFDead"): plugin_call("ksw", "flush_session")

            case "LaunchFighter" if not j["PlayerControlled"]:
                state.slf_deployed = True
                state.slf_docked   = False
                state.slf_hull     = 100
                state.slf_orders   = "Defend"
                state.slf_loadout  = j.get("Loadout")
                if gui_queue: gui_queue.put(("slf_update", None))
                emitter.emit(
                    msg_term="Fighter launched",
                    emoji="🛩️", sigil="-  SLF ",
                    timestamp=logtime, loglevel=2,
                )

            case "RestockVehicle":
                ft   = j.get("Type", "")
                lo   = j.get("Loadout", "")
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
                if gui_queue: gui_queue.put(("slf_update", None))

            case "DockFighter":
                state.slf_deployed = False
                state.slf_docked   = True
                state.slf_hull     = 100
                state.slf_orders   = None
                if gui_queue: gui_queue.put(("slf_update", None))

            case "FighterRebuilt":
                state.slf_destroyed_count = max(0, state.slf_destroyed_count - 1)
                if gui_queue: gui_queue.put(("slf_update", None))

            case "FighterOrders":
                state.slf_orders = j.get("Orders")
                if gui_queue: gui_queue.put(("slf_update", None))

            # ── SHIELDS / HULL ────────────────────────────────────────────
            case "ShieldState":
                if j["ShieldsUp"]:
                    shields = "back up"; col = Terminal.GOOD
                    state.ship_shields            = True
                    state.ship_shields_recharging = False
                else:
                    shields = "down!"; col = Terminal.BAD
                    state.ship_shields            = False
                    state.ship_shields_recharging = True
                if gui_queue: gui_queue.put(("vessel_update", None))
                emitter.emit(
                    msg_term=f"{col}Ship shields {shields}{Terminal.END}",
                    msg_discord=f"**Ship shields {shields}**",
                    emoji="🛡️", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["ShieldEvent"],
                )

            case "HullDamage":
                hullhealth = round(j["Health"] * 100)
                if j["Fighter"] and not j["PlayerPilot"] and state.fighter_integrity != j["Health"]:
                    state.fighter_integrity = j["Health"]
                    state.slf_hull          = hullhealth
                    if gui_queue: gui_queue.put(("slf_update", None))
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.WARN}Fighter hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Fighter hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="🛩️", sigil="^  SLF ",
                        timestamp=logtime, loglevel=notify["FighterDamage"],
                    )
                elif j["PlayerPilot"] and not j["Fighter"]:
                    state.ship_hull = hullhealth
                    if gui_queue: gui_queue.put(("vessel_update", None))
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="⚠️", sigil="^  HULL",
                        timestamp=logtime, loglevel=notify["HullEvent"],
                    )
                    if (
                        cfg_mgr.pcfg("QuitOnLowHull")
                        and hullhealth <= cfg_mgr.pcfg("QuitOnLowHullThreshold", 10)
                    ):
                        plugin_call("ksw", "flush_session")

            case "Died":
                emitter.emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}",
                    msg_discord="**Ship destroyed!**",
                    emoji="💀", sigil="!! DEAD",
                    timestamp=logtime, loglevel=notify["Died"],
                )

            # ── SESSION TRANSITIONS ───────────────────────────────────────
            case "Music" if j["MusicTrack"] == "MainMenu":
                state.sessionend()
                state.in_game = False
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                emitter.emit(
                    msg_term="Exited to main menu",
                    emoji="🚪", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )

            case "LoadGame":
                state.reset_missions()
                state.crew_active = False
                state.in_game     = True
                state.offline_since_mono  = None
                state.last_offline_alert  = None
                state.pilot_ship = j.get("Ship_Localised") or j.get("Ship")
                if j.get("ShipName"):  state.ship_name  = j["ShipName"]
                if j.get("ShipIdent"): state.ship_ident = j["ShipIdent"]
                if "GameMode" in j:
                    state.pilot_mode = (
                        "Private Group" if j["GameMode"] == "Group" else j["GameMode"]
                    )
                if gui_queue: gui_queue.put(("vessel_update", None))
                cmdrinfo = (
                    f"{state.pilot_ship} / {state.pilot_mode} / "
                    f"{state.pilot_rank} +{state.pilot_rank_progress}%"
                )
                emitter.emit(
                    msg_term=f"CMDR {state.pilot_name} ({cmdrinfo})",
                    msg_discord=f"**CMDR {state.pilot_name}** ({cmdrinfo})",
                    emoji="👤", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )

            case "Loadout":
                state.fuel_tank_size = (
                    j["FuelCapacity"]["Main"] if j["FuelCapacity"]["Main"] >= 2 else 64
                )
                state.ship_name  = j.get("ShipName") or None
                state.ship_ident = j.get("ShipIdent") or None
                if gui_queue: gui_queue.put(("vessel_update", None))
                _FIGHTERBAY_CAPACITY = {"3": 1, "5": 4, "6": 6}
                slf_found = False; slf_cap = 0
                for mod in j.get("Modules", []):
                    item = mod.get("Item", "").lower()
                    if "fighterbay" in item:
                        slf_found = True
                        m = re.search(r"fighterbay_size(\d+)", item)
                        if m:
                            slf_cap = max(slf_cap, _FIGHTERBAY_CAPACITY.get(m.group(1), 1))
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
                if gui_queue:
                    gui_queue.put(("slf_update",  None))
                    gui_queue.put(("crew_update", None))

            # ── VEHICLE SWITCH ────────────────────────────────────────────
            case "VehicleSwitch":
                to = j.get("To", "")
                if to == "Fighter":   state.cmdr_in_slf = True
                elif to == "Mothership": state.cmdr_in_slf = False
                if gui_queue:
                    gui_queue.put(("vessel_update", None))
                    gui_queue.put(("slf_update",    None))

            # ── NPC CREW ──────────────────────────────────────────────────
            case "CrewAssign":
                name = j.get("Name")
                if name:
                    if state.crew_name != name:
                        state.crew_total_paid = 0
                    state.crew_name   = name
                    state.crew_active = True
                if gui_queue: gui_queue.put(("crew_update", None))

            case "NpcCrewPaidWage":
                wage_name = j.get("NpcCrewName")
                if not state.crew_name and wage_name:
                    state.crew_name = wage_name
                if wage_name and wage_name == state.crew_name:
                    state.crew_active = True
                    if state.crew_total_paid is None:
                        state.crew_total_paid = 0
                    state.crew_total_paid += j.get("Amount", 0)
                if gui_queue: gui_queue.put(("crew_update", None))

            case "NpcCrewRank":
                rank_name = j.get("NpcCrewName")
                if not state.crew_name and rank_name:
                    state.crew_name = rank_name
                if rank_name and rank_name == state.crew_name:
                    state.crew_rank = j.get("RankCombat", state.crew_rank)
                if gui_queue: gui_queue.put(("crew_update", None))

            # ── NAVIGATION ───────────────────────────────────────────────
            case "SupercruiseDestinationDrop" if any(
                x in j["Type"] for x in ["$MULTIPLAYER", "$Warzone"]
            ):
                state.sessionstart(active_session, True)
                type_local    = j.get("Type_Localised", LABEL_UNKNOWN)
                state.pilot_body = type_local
                if gui_queue: gui_queue.put(("cmdr_update", None))
                emoji = "🪐" if "Resource Extraction Site" in type_local else "⚔️"
                emitter.emit(
                    msg_term=f"Dropped at {type_local}",
                    emoji=emoji, sigil=">  DROP",
                    timestamp=logtime, loglevel=2,
                )

            case "EjectCargo" if not j["Abandoned"] and j["Count"] == 1:
                name = j.get("Type_Localised") or j["Type"].title()
                emitter.emit(
                    msg_term=f"{Terminal.BAD}Cargo stolen!{Terminal.END} ({name})",
                    msg_discord=f"**Cargo stolen!** ({name})",
                    emoji="📦", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["CargoLost"],
                    event="CargoLost",
                )

            case "Rank":
                state.pilot_rank = RANK_NAMES[j["Combat"]]

            case "Progress":
                state.pilot_rank_progress = j["Combat"]

            # ── POWERPLAY ─────────────────────────────────────────────────
            case "Powerplay":
                if j.get("Power"):     state.pp_power        = j["Power"]
                if j.get("Rank") is not None: state.pp_rank  = j["Rank"]
                if j.get("Merits") is not None: state.pp_merits_total = j["Merits"]
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayJoin":
                state.pp_power = j.get("Power"); state.pp_rank = 1
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayLeave":
                state.pp_power = state.pp_rank = state.pp_merits_total = None
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayDefect":
                state.pp_power = j.get("ToPower"); state.pp_rank = 1
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayRank":
                state.pp_rank = j.get("Rank")
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayMerits":
                if j.get("TotalMerits") is not None:
                    state.pp_merits_total = j["TotalMerits"]
                    if gui_queue: gui_queue.put(("cmdr_update", None))
                if j.get("Power") and not state.pp_power:
                    state.pp_power = j["Power"]
                if active_session.pending_merit_events > 0 and j["MeritsGained"] < 500:
                    active_session.merits += j["MeritsGained"]
                    lifetime.merits       += j["MeritsGained"]
                    emitter.emit(
                        msg_term=f"Merits: +{j['MeritsGained']:,} ({j['Power']})",
                        emoji="⭐", sigil="+  MERC",
                        timestamp=logtime, loglevel=notify["MeritEvent"],
                    )
                    active_session.pending_merit_events -= 1

            # ── LOCATION ──────────────────────────────────────────────────
            case "Location":
                if j.get("StarSystem"): state.pilot_system = j["StarSystem"]
                if j.get("Body"):
                    state.pilot_body = j["Body"] if j.get("Docked") is False else None
                if j.get("Docked") and j.get("StationName"):
                    state.pilot_body = j["StationName"]
                elif j.get("Docked") and not j.get("StationName"):
                    state.pilot_body = None
                if gui_queue: gui_queue.put(("cmdr_update", None))
                if j["BodyType"] == "PlanetaryRing":
                    state.sessionstart(active_session)

            case "Docked":
                if j.get("StationName"): state.pilot_body   = j["StationName"]
                if j.get("StarSystem"):  state.pilot_system = j["StarSystem"]
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "Undocked":
                state.pilot_body = None
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "ShipyardSwap":
                state.pilot_ship = j.get("ShipType_Localised") or j["ShipType"].title()
                emitter.emit(
                    msg_term=f"Swapped ship to {state.pilot_ship}",
                    emoji="🚢", sigil="-  SHIP",
                    timestamp=logtime, loglevel=2,
                )

            case "Shutdown":
                state.in_game = False
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                emitter.emit(
                    msg_term="Quit to desktop",
                    emoji="🛑", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )
                if __name__ == "__main__" and not state.in_preload:
                    sys.exit()

            case "SupercruiseEntry" | "FSDJump":
                if j["event"] == "SupercruiseEntry":
                    event_name = "Supercruise entry in"; emoji = "🚀"; sigil = ">  JUMP"
                    state.pilot_system = j.get("StarSystem", state.pilot_system)
                    state.pilot_body   = None
                else:
                    event_name = "FSD jump to"; emoji = "🌌"; sigil = ">  JUMP"
                    state.pilot_system = j.get("StarSystem", state.pilot_system)
                    state.pilot_body   = None
                if gui_queue: gui_queue.put(("cmdr_update", None))
                emitter.emit(
                    msg_term=f"{event_name} {j['StarSystem']}",
                    emoji=emoji, sigil=sigil,
                    timestamp=logtime, loglevel=2,
                )
                state.sessionend()

        state.prev_event = j["event"]

    except Exception as e:
        event_name  = j.get("event", LABEL_UNKNOWN) if isinstance(j, dict) else LABEL_UNKNOWN
        logtime_fmt = datetime.strftime(logtime, "%H:%M:%S") if logtime else LABEL_UNKNOWN
        print(
            f"{Terminal.WARN}Warning:{Terminal.END} "
            f"Process event error for [{event_name}]: "
            f"{e} (logtime: {logtime_fmt})"
        )


# ── Journal monitor ───────────────────────────────────────────────────────────

def monitor_journal(
    jfile: Path,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    journal_file_ref: list,   # [Path] — mutable single-element list for current file
    _edmd_start_mono: float,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
) -> Path | None:
    """Preload a journal then tail it live. Returns path of new journal if one appears."""

    print(f"{Terminal.YELL}Journal file:{Terminal.END} {jfile}")
    state.in_preload = True

    with open(jfile, mode="r", encoding="utf-8") as file:
        print("Preloading journal... (Press Ctrl+C to stop)")
        for line in file:
            handle_event(
                line, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir, trace_mode,
                plugin_dispatch=plugin_dispatch,
            )

        state.in_preload = False

        # Bootstrap missing data after preload
        if not state.missions or (state.active_missions and not state.stack_value):
            bootstrap_missions(state, journal_dir, cfg_mgr, trace_mode)

        load_session_state(jfile, active_session)
        bootstrap_slf(state, journal_dir, trace_mode)
        bootstrap_crew(state, journal_dir, trace_mode)

        # Restore session start time if persisted
        from core.state import _session_start_iso
        if not state.session_start_time and _session_start_iso:
            try:
                state.session_start_time = datetime.fromisoformat(_session_start_iso)
            except ValueError:
                pass

        print("Preload complete. Monitoring live...\n")

        # ── Terminal startup banner ───────────────────────────────────────
        term_bar = "=" * 42
        stack_line    = ""
        location_line = ""
        pp_line       = ""

        if state.stack_value > 0:
            _done = state.missions_complete
            _tot  = len(state.active_missions)
            _rem  = _tot - _done
            _status = (
                "all complete — turn in!"
                if _rem == 0
                else f"{_done}/{_tot} complete, {_rem} remaining"
            )
            stack_line = f"  Stack: {fmt_credits(state.stack_value)} ({_status})\n"

        if state.pilot_system:
            _loc = state.pilot_system
            if state.pilot_body:
                _loc += f"  |  {state.pilot_body}"
            location_line = f"  {_loc}\n"

        if state.pp_power:
            _pp_rank   = f"  Rank {state.pp_rank}" if state.pp_rank else ""
            _pp_merits = f"  ({state.pp_merits_total:,} merits)" if state.pp_merits_total else ""
            pp_line = f"  {state.pp_power}{_pp_rank}{_pp_merits}\n"

        term_msg = (
            f"\n{term_bar}\n"
            f"  ▶  MONITORING ACTIVE\n"
            f"  CMDR {state.pilot_name}\n"
            f"  {state.pilot_ship}  |  {state.pilot_mode}\n"
            f"  {state.pilot_rank} +{state.pilot_rank_progress}%\n"
            f"{pp_line}"
            f"{location_line}"
            f"{stack_line}"
            f"{term_bar}"
        )
        print(f"{Terminal.CYAN}{term_msg}{Terminal.END}\n")

        # ── Discord startup embed ─────────────────────────────────────────
        try:
            from discord_webhook import DiscordEmbed
            embed = DiscordEmbed(title="▶  Monitoring Active", color="00e5ff")
            embed.add_embed_field(name="Commander", value=f"CMDR {state.pilot_name}", inline=False)
            embed.add_embed_field(name="Ship",  value=state.pilot_ship  or "Unknown", inline=True)
            embed.add_embed_field(name="Mode",  value=state.pilot_mode  or "Unknown", inline=True)
            embed.add_embed_field(
                name="Combat Rank",
                value=f"{state.pilot_rank} +{state.pilot_rank_progress}%", inline=True,
            )
            if state.pp_power:
                _pp_val = state.pp_power
                if state.pp_rank:        _pp_val += f" — Rank {state.pp_rank}"
                if state.pp_merits_total: _pp_val += f" ({state.pp_merits_total:,} merits)"
                embed.add_embed_field(name="Powerplay", value=_pp_val, inline=False)
            if state.pilot_system:
                _loc_val = state.pilot_system
                if state.pilot_body: _loc_val += f" / {state.pilot_body}"
                embed.add_embed_field(name="Location", value=_loc_val, inline=False)
            if state.stack_value > 0:
                _done = state.missions_complete; _tot = len(state.active_missions)
                _rem  = _tot - _done
                _status = (
                    "All complete — turn in!" if _rem == 0
                    else f"{_done}/{_tot} complete, {_rem} remaining"
                )
                embed.add_embed_field(
                    name="Mission Stack",
                    value=f"{fmt_credits(state.stack_value)} — {_status}",
                    inline=False,
                )
            from core.state import VERSION
            embed.set_footer(text=f"Elite Dangerous Monitor Daemon v{VERSION}")
            embed.set_timestamp()
            emitter.post_embed(embed)
        except ImportError:
            pass

        # ── Live tail loop ────────────────────────────────────────────────
        while True:
            line = file.readline()

            if not line:
                time.sleep(1)
                cfg_mgr.refresh()

                # Check for a new journal file
                latest = find_latest_journal(journal_dir)
                if latest and latest != jfile:
                    print(f"{Terminal.YELL}New journal detected:{Terminal.END} {latest.name}")
                    return latest

                now_mono = time.monotonic()

                # ── Not-in-game detection ─────────────────────────────────
                OFFLINE_STARTUP_GRACE = 5  * 60
                OFFLINE_MENU_GRACE    = 15 * 60
                OFFLINE_RENOTIFY      = 60 * 60
                _startup_elapsed = now_mono - _edmd_start_mono
                _not_in_game     = not state.in_game and not state.in_preload

                if _not_in_game:
                    if state.offline_since_mono is None:
                        state.offline_since_mono = now_mono
                    offline_elapsed = now_mono - state.offline_since_mono
                    if _startup_elapsed < OFFLINE_STARTUP_GRACE:
                        _grace_ok = False
                    elif offline_elapsed < OFFLINE_MENU_GRACE:
                        _grace_ok = False
                    else:
                        _grace_ok = True

                    if _grace_ok:
                        _ed_up   = _ed_client_running()
                        _reason  = (
                            "Elite Dangerous client not detected"
                            if not _ed_up
                            else "Player at main menu — not in session"
                        )
                        cooldown_ok = (
                            state.last_offline_alert is None
                            or now_mono - state.last_offline_alert >= OFFLINE_RENOTIFY
                        )
                        if cooldown_ok:
                            _level = _max_notify_level(cfg_mgr.notify_levels)
                            emitter.emit(
                                msg_term=f"Not in game: {_reason}",
                                msg_discord=f"⛔ **Not in game** — {_reason}",
                                emoji="⛔", sigil="!  WARN",
                                timestamp=state.event_time, loglevel=_level,
                            )
                            state.last_offline_alert = now_mono
                        continue
                else:
                    state.offline_since_mono = None

                # ── Periodic summary ──────────────────────────────────────
                SUMMARY_INTERVAL = 15 * 60
                if (
                    state.session_start_time
                    and active_session.kills > 0
                    and state.last_periodic_summary is not None
                    and now_mono - state.last_periodic_summary >= SUMMARY_INTERVAL
                ):
                    state.last_periodic_summary = now_mono
                    emit_summary(emitter, state, active_session)

                # ── Inactivity alert ──────────────────────────────────────
                warn_no_kills = cfg_mgr.app_settings.get("WarnNoKills", 20)
                warn_initial  = cfg_mgr.app_settings.get("WarnNoKillsInitial", 5)
                warn_cooldown = cfg_mgr.app_settings.get("WarnCooldown", 15)
                if (
                    cfg_mgr.notify_levels.get("InactiveAlert", 3) > 0
                    and state.session_start_time
                    and warn_no_kills > 0
                ):
                    threshold_mins = warn_initial if active_session.kills == 0 else warn_no_kills
                    threshold_secs = threshold_mins * 60
                    last_kill = active_session.last_kill_mono or (
                        state.last_periodic_summary or now_mono
                    )
                    cooldown_ok = (
                        state.last_inactive_alert is None
                        or now_mono - state.last_inactive_alert >= warn_cooldown * 60
                    )
                    if cooldown_ok and now_mono - last_kill >= threshold_secs:
                        idle_dur = fmt_duration(now_mono - last_kill)
                        emitter.emit(
                            msg_term=f"No kills in {idle_dur} — session may be inactive",
                            msg_discord=f"⚠️ **No kills in {idle_dur}** — session may be inactive",
                            emoji="⚠️", sigil="!  WARN",
                            timestamp=state.event_time,
                            loglevel=cfg_mgr.notify_levels.get("InactiveAlert", 3),
                        )
                        state.last_inactive_alert = now_mono

                # ── Kill rate alert ───────────────────────────────────────
                warn_rate = cfg_mgr.app_settings.get("WarnKillRate", 20)
                if (
                    cfg_mgr.notify_levels.get("RateAlert", 3) > 0
                    and warn_rate > 0
                    and active_session.kills >= 3
                    and len(active_session.recent_kill_times) >= 3
                ):
                    recent_avg_secs = (
                        sum(active_session.recent_kill_times)
                        / len(active_session.recent_kill_times)
                    )
                    recent_rate = 3600 / recent_avg_secs if recent_avg_secs > 0 else 0
                    cooldown_ok = (
                        state.last_rate_alert is None
                        or now_mono - state.last_rate_alert >= warn_cooldown * 60
                    )
                    if cooldown_ok and recent_rate < warn_rate:
                        rate_fmt = f"{recent_rate:.1f}"
                        emitter.emit(
                            msg_term=f"Kill rate low: {rate_fmt}/hr (threshold: {warn_rate}/hr)",
                            msg_discord=f"📉 **Kill rate low: {rate_fmt}/hr** (threshold: {warn_rate}/hr)",
                            emoji="📉", sigil="!  WARN",
                            timestamp=state.event_time,
                            loglevel=cfg_mgr.notify_levels.get("RateAlert", 3),
                        )
                        state.last_rate_alert = now_mono

                continue

            handle_event(
                line, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir, trace_mode,
                plugin_dispatch=plugin_dispatch,
            )

    return None


def run_monitor(
    journal_file: Path,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    _edmd_start_mono: float,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
) -> None:
    """Outer loop: run monitor_journal, switching files when a new one appears."""
    try:
        current = journal_file
        journal_file_ref = [current]
        while True:
            next_journal = monitor_journal(
                current, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir,
                journal_file_ref, _edmd_start_mono, trace_mode,
                plugin_dispatch=plugin_dispatch,
            )
            if next_journal:
                current = next_journal
            else:
                break

    except KeyboardInterrupt:
        print("\nExiting...")
        state.sessionend()
        if state.session_start_time and journal_file:
            save_session_state(journal_file, active_session)

    except FileNotFoundError:
        print("Journal file not found")
        sys.exit(1)

    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
