"""
core/reports.py — Statistical reports built from all available journal files.

Reports are computed by scanning every journal in the configured journal folder.
All report functions return a ReportResult containing a title, subtitle, and
a list of ReportSection objects for display.

Available reports
─────────────────
1. Career Overview       — lifetime kills, credits, time played
2. Bounty Breakdown      — kills and credits by ship type
3. Session History       — per-session summary table
4. Top Hunting Grounds   — most-visited systems and stations
5. NPC Rogues' Gallery   — unique attacker names + frequency
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ReportRow:
    cells: list[str]

@dataclass
class ReportSection:
    heading:  str
    columns:  list[str]          = field(default_factory=list)  # column headers; empty = prose
    rows:     list[ReportRow]    = field(default_factory=list)
    prose:    str                = ""                            # used when columns is empty
    note:     str                = ""                           # small footnote

@dataclass
class ReportResult:
    title:    str
    subtitle: str
    sections: list[ReportSection] = field(default_factory=list)
    error:    str                 = ""


# ── Journal scanner ───────────────────────────────────────────────────────────

def _iter_journal_events(journal_dir: Path):
    """Yield (event_dict, journal_path) for every parseable event in all journals."""
    paths = sorted(journal_dir.glob("Journal.*.log"))
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if isinstance(ev, dict) and "event" in ev:
                        yield ev, path
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass


def _fmt_credits(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


# ── Report 1: Career Overview ─────────────────────────────────────────────────

def report_career_overview(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Career Overview",
        subtitle="Lifetime statistics across all journal files"
    )

    kills         = 0
    bounty_total  = 0
    bond_total    = 0
    missions_done = 0
    mission_pay   = 0
    deaths        = 0
    rebuys        = 0
    jumps         = 0
    first_ts      = None
    last_ts       = None
    journals_read = 0
    prev_journal  = None

    for ev, jp in _iter_journal_events(journal_dir):
        if jp != prev_journal:
            journals_read += 1
            prev_journal   = jp

        ts = ev.get("timestamp", "")
        if ts:
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

        etype = ev.get("event", "")

        if etype == "Bounty":
            kills         += 1
            bounty_total  += ev.get("TotalReward", ev.get("Reward", 0))
        elif etype == "FactionKillBond":
            kills         += 1
            bond_total    += ev.get("Reward", 0)
        elif etype == "MissionCompleted":
            missions_done += 1
            mission_pay   += ev.get("Reward", 0)
        elif etype == "Died":
            deaths += 1
        elif etype == "Resurrect":
            rebuys += ev.get("Cost", 0)
        elif etype == "FSDJump":
            jumps += 1

    # Derive date range
    date_range = "Unknown"
    if first_ts and last_ts:
        d1 = first_ts[:10]
        d2 = last_ts[:10]
        date_range = d1 if d1 == d2 else f"{d1} → {d2}"

    overview_sec = ReportSection(
        heading="Lifetime Totals",
        columns=["Metric", "Value"],
        rows=[
            ReportRow(["Journals scanned",    str(journals_read)]),
            ReportRow(["Date range",          date_range]),
            ReportRow(["Kills",               f"{kills:,}"]),
            ReportRow(["Bounty rewards",      _fmt_credits(bounty_total)]),
            ReportRow(["Kill bond rewards",   _fmt_credits(bond_total)]),
            ReportRow(["Missions completed",  f"{missions_done:,}"]),
            ReportRow(["Mission pay",         _fmt_credits(mission_pay)]),
            ReportRow(["Total combat pay",    _fmt_credits(bounty_total + bond_total)]),
            ReportRow(["Deaths",              str(deaths)]),
            ReportRow(["Rebuy costs",         _fmt_credits(rebuys)]),
            ReportRow(["Hyperspace jumps",    f"{jumps:,}"]),
        ]
    )
    result.sections.append(overview_sec)
    return result


# ── Report 2: Bounty Breakdown by Ship Type ───────────────────────────────────

def report_bounty_breakdown(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Bounty Breakdown",
        subtitle="Kills and rewards by target ship type"
    )

    by_ship: dict[str, dict] = defaultdict(lambda: {"kills": 0, "credits": 0})

    for ev, _ in _iter_journal_events(journal_dir):
        if ev.get("event") == "Bounty":
            ship   = ev.get("Target_Localised", ev.get("Target", "Unknown"))
            reward = ev.get("TotalReward", ev.get("Reward", 0))
            by_ship[ship]["kills"]   += 1
            by_ship[ship]["credits"] += reward

    if not by_ship:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No Bounty events found in the journal directory."
        ))
        return result

    sorted_ships = sorted(by_ship.items(), key=lambda kv: kv[1]["credits"], reverse=True)

    sec = ReportSection(
        heading="By Ship Type  (sorted by total reward)",
        columns=["Ship", "Kills", "Total Reward", "Avg / Kill"],
    )
    for ship, data in sorted_ships[:40]:  # cap at 40 rows
        k = data["kills"]
        c = data["credits"]
        avg = c // k if k else 0
        sec.rows.append(ReportRow([ship, f"{k:,}", _fmt_credits(c), _fmt_credits(avg)]))

    result.sections.append(sec)
    return result


# ── Report 3: Session History ─────────────────────────────────────────────────

def report_session_history(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Session History",
        subtitle="Per-session summary across all journals"
    )

    # A session is delimited by LoadGame events (each journal start = new session)
    sessions = []
    cur: dict[str, Any] = {}

    def _flush():
        if cur and cur.get("kills", 0) + cur.get("missions", 0) > 0:
            sessions.append(dict(cur))

    for ev, jp in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "LoadGame":
            _flush()
            cur = {
                "date":    ev.get("timestamp", "")[:10],
                "cmdr":    ev.get("Commander", ""),
                "ship":    ev.get("Ship_Localised", ev.get("Ship", "")),
                "kills":   0,
                "bounty":  0,
                "missions":0,
                "mission_pay": 0,
                "deaths":  0,
            }
        elif etype == "Bounty":
            cur["kills"]  = cur.get("kills", 0) + 1
            cur["bounty"] = cur.get("bounty", 0) + ev.get("TotalReward", ev.get("Reward", 0))
        elif etype == "FactionKillBond":
            cur["kills"]  = cur.get("kills", 0) + 1
            cur["bounty"] = cur.get("bounty", 0) + ev.get("Reward", 0)
        elif etype == "MissionCompleted":
            cur["missions"]    = cur.get("missions", 0) + 1
            cur["mission_pay"] = cur.get("mission_pay", 0) + ev.get("Reward", 0)
        elif etype == "Died":
            cur["deaths"] = cur.get("deaths", 0) + 1

    _flush()

    if not sessions:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No sessions with activity found in the journal directory."
        ))
        return result

    # Most recent first
    sessions.reverse()

    sec = ReportSection(
        heading=f"{len(sessions)} sessions found",
        columns=["Date", "Commander", "Ship", "Kills", "Bounty", "Missions", "Mission Pay", "Deaths"],
    )
    for s in sessions[:60]:  # cap display at 60 rows
        sec.rows.append(ReportRow([
            s.get("date", ""),
            s.get("cmdr", ""),
            s.get("ship", ""),
            str(s.get("kills", 0)),
            _fmt_credits(s.get("bounty", 0)),
            str(s.get("missions", 0)),
            _fmt_credits(s.get("mission_pay", 0)),
            str(s.get("deaths", 0)),
        ]))
    if len(sessions) > 60:
        sec.note = f"Showing most recent 60 of {len(sessions)} sessions."
    result.sections.append(sec)
    return result


# ── Report 4: Top Hunting Grounds ─────────────────────────────────────────────

# ── Station type classification ───────────────────────────────────────────────
#
# StationType values seen in Docked / Location events.  These are the raw
# strings the game logs — names that only appear in FSSSignalDiscovered or
# CarrierLocation are NOT present here and handled separately.
#
# Fleet carrier (Drake-class personal AND Javelin-class squadron) both dock
# with StationType = "FleetCarrier".  Distinction requires cross-referencing
# CarrierLocation.CarrierType / CarrierStats.CarrierType (see report code).
#
# Stronghold Carrier: faction-controlled large vessel.  Appears in the FSS
# scanner as SignalType = "StationMegaShip" with SignalName = "Stronghold Carrier".
# If dockable it uses StationType = "StationMegaShip".  It is NOT a megaship
# in gameplay terms but is physically a large orbital vessel — categorised here
# as its own group so it never falls through to "Surface installation".

_MEGASHIP_TYPES = {
    "MegaShip",
    "MegaShipSrv",      # megaship with services bay
}

_STRONGHOLD_TYPES = {
    "StationMegaShip",  # Stronghold Carrier (faction-owned capital vessel)
}

_SURFACE_TYPES = {
    "SurfaceStation",
    "CraterOutpost",
    "CraterPort",
    "OnFootSettlement",
}

_ASTEROID_TYPES = {"AsteroidBase"}


def _station_kind(
    station_type: str,
    market_id:    int | None,
    own_fc_ids:   set[int],   # MarketIDs from CarrierStats(CarrierType=FleetCarrier)
    sqn_fc_ids:   set[int],   # MarketIDs from CarrierStats(CarrierType=SquadronCarrier)
    seen_sqn_ids: set[int],   # MarketIDs seen in CarrierLocation(CarrierType=SquadronCarrier)
) -> str:
    """Return a human-readable venue category string for the Type column.

    Carrier ID sets are built by the report during its journal scan pass:

      own_fc_ids   — CarrierStats where CarrierType = "FleetCarrier"
                     → your personal Drake-class carrier(s)

      sqn_fc_ids   — CarrierStats where CarrierType = "SquadronCarrier"
                     → squadron carriers you own or manage (DOCO etc.)
                     CarrierStats fires when YOU open the carrier management
                     panel, so this only covers carriers you have access to.

      seen_sqn_ids — CarrierLocation where CarrierType = "SquadronCarrier"
                     → any Javelin in the same system at login, regardless of
                     ownership.  Covers carriers you dock on but don't manage.
    """
    if station_type == "FleetCarrier":
        mid = market_id
        if mid and mid in own_fc_ids:
            return "Your fleet carrier"
        if mid and mid in sqn_fc_ids:
            return "Your squadron carrier"
        if mid and mid in seen_sqn_ids:
            return "Squadron carrier"
        return "Fleet carrier"
    if station_type in _STRONGHOLD_TYPES:
        return "Stronghold Carrier"
    if station_type in _MEGASHIP_TYPES:
        return "Megaship"
    if station_type in _SURFACE_TYPES:
        return "Surface installation"
    if station_type in _ASTEROID_TYPES:
        return "Asteroid base"
    return "Station / Outpost"


def report_hunting_grounds(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Top Hunting Grounds",
        subtitle="Most visited systems and stations by kill count"
    )

    # ── First pass: build carrier identity lookup tables ──────────────────────
    #
    # We need three ID sets to fully classify any FleetCarrier dock entry:
    #
    #   own_fc_ids   — personal Drake-class carriers you own
    #                  source: CarrierStats(CarrierType="FleetCarrier")
    #
    #   sqn_fc_ids   — Javelin-class squadron carriers you own/manage
    #                  source: CarrierStats(CarrierType="SquadronCarrier")
    #                  fires when you open carrier management on YOUR squadron carrier
    #
    #   seen_sqn_ids — any Javelin in your system at login (whether you own it or not)
    #                  source: CarrierLocation(CarrierType="SquadronCarrier")
    #                  fires once per session for each carrier tracked by the client
    #
    #   carrier_names — CarrierID → (callsign, display_name)
    #                   built from CarrierStats which carries both Callsign (permanent)
    #                   and Name (user-changeable).  Later events overwrite earlier ones
    #                   so the most-recently-seen name is always current.
    #                   Only populated for carriers whose management panel you open.
    #
    # MarketID in Docked/Location matches CarrierID in all carrier events.
    #
    own_fc_ids:    set[int] = set()
    sqn_fc_ids:    set[int] = set()
    seen_sqn_ids:  set[int] = set()
    carrier_names: dict[int, tuple[str, str]] = {}   # id → (callsign, name)

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")
        if etype == "CarrierStats":
            cid      = ev.get("CarrierID")
            ctype    = ev.get("CarrierType", "")
            callsign = ev.get("Callsign", "")
            name     = ev.get("Name", "").strip().title()   # game stores in ALL CAPS
            if cid:
                if ctype == "SquadronCarrier":
                    sqn_fc_ids.add(cid)
                else:
                    own_fc_ids.add(cid)
                if callsign:
                    carrier_names[cid] = (callsign, name)
        elif etype == "CarrierLocation":
            cid   = ev.get("CarrierID")
            ctype = ev.get("CarrierType", "")
            if cid and ctype == "SquadronCarrier":
                seen_sqn_ids.add(cid)

    # ── Second pass: tally kills by system and venue ──────────────────────────
    system_kills: dict[str, int] = defaultdict(int)
    # venue_kills: name → [kills, station_type, market_id]
    venue_kills:  dict[str, list] = {}

    current_system       = "Unknown"
    current_station:     str | None = None
    current_station_type = ""
    current_market_id:   int | None = None

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")
        if etype == "FSDJump":
            current_system       = ev.get("StarSystem", current_system)
            current_station      = None
            current_station_type = ""
            current_market_id    = None
        elif etype in ("Docked", "Location"):
            current_station      = ev.get("StationName")
            current_station_type = ev.get("StationType", "")
            current_market_id    = ev.get("MarketID")
        elif etype in ("Bounty", "FactionKillBond"):
            system_kills[current_system] += 1
            if current_station:
                if current_station not in venue_kills:
                    venue_kills[current_station] = [0, current_station_type, current_market_id]
                venue_kills[current_station][0] += 1

    top_systems = sorted(system_kills.items(), key=lambda x: x[1], reverse=True)[:20]

    # ── Systems section ───────────────────────────────────────────────────────
    if top_systems:
        sec = ReportSection(
            heading="Top Systems  (by kill count)",
            columns=["System", "Kills"]
        )
        for name, n in top_systems:
            sec.rows.append(ReportRow([name, f"{n:,}"]))
        result.sections.append(sec)

    # ── Venues section ────────────────────────────────────────────────────────
    if venue_kills:
        top_venues = sorted(venue_kills.items(), key=lambda x: x[1][0], reverse=True)[:20]
        sec2 = ReportSection(
            heading="Top Venues  (when docked or based nearby)",
            columns=["Venue", "Type", "Kills"],
        )
        for station_name, (kills, stype, mid) in top_venues:
            kind = _station_kind(stype, mid, own_fc_ids, sqn_fc_ids, seen_sqn_ids)
            # For fleet/squadron carriers we know the name from CarrierStats —
            # display as "CALLSIGN (Name)" so the permanent ID is always visible
            # alongside the current (potentially changed) display name.
            display_name = station_name
            if stype == "FleetCarrier" and mid and mid in carrier_names:
                callsign, cname = carrier_names[mid]
                if cname and cname.upper() != callsign.upper():
                    display_name = f"{callsign} ({cname})"
            sec2.rows.append(ReportRow([display_name, kind, f"{kills:,}"]))
        result.sections.append(sec2)

    if not top_systems and not venue_kills:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No kill events with system or location data found."
        ))
    return result


# ── Report 5: NPC Rogues' Gallery ────────────────────────────────────────────

def report_rogues_gallery(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="NPC Rogues' Gallery",
        subtitle="Every named pilot killed by or who has killed CMDR CALURSUS"
    )

    # ── Collect own commander names for self-filter ───────────────────────────
    own_names: set[str] = set()
    for ev, _ in _iter_journal_events(journal_dir):
        if ev.get("event") == "LoadGame":
            cmdr = ev.get("Commander", "")
            if cmdr:
                n = cmdr.strip().upper()
                own_names.add(n)
                own_names.add(f"CREW CMDR {n}")

    def _clean(raw: str):
        name = raw.strip()
        if not name or name.startswith("$") or len(name) < 2:
            return None
        if name.upper() in ("SYSTEM AUTHORITY VESSEL", "CLEAN", "WANTED"):
            return None
        nu = name.upper()
        if nu in own_names:
            return None
        for own in own_names:
            if nu == f"CREW CMDR {own}" or nu.endswith(own):
                return None
        return name

    # ── Journal scan ──────────────────────────────────────────────────────────
    #
    # Sources (from actual journal inspection):
    #
    #   Bounty.PilotName_Localised   — NPC you killed; on every Bounty event.
    #                                   Primary and most reliable name source.
    #   Bounty.PilotName "$ShipName_Police*" — authority vessel you destroyed.
    #
    #   Died.Killers[].Name          — pilots who killed you.
    #
    #   Interdicted (Submitted=false, IsPlayer=false)
    #                                — NPC interdiction you fought off.
    #
    #   PVPKill.Victim               — player you killed.
    #
    #   Scanned (ScanType=Cargo)     — cop scanned your cargo. No individual
    #                                   name available; counted as interactions.
    #
    # NOT used:
    #   ShipTargeted  — fires on every target lock; no engagement implied
    #   UnderAttack   — no pilot name field
    #   Interdicted (Submitted=true) — you fled; no fight
    #
    _POLICE_PREFIX = "$shipname_police"

    pirate_counts: dict[str, int] = defaultdict(int)
    killed_us:     dict[str, int] = defaultdict(int)
    pvp_counts:    dict[str, int] = defaultdict(int)
    cop_kills  = 0
    cop_deaths = 0
    cop_scans  = 0

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "Bounty":
            raw_key = ev.get("PilotName", "")
            if raw_key.lower().startswith(_POLICE_PREFIX):
                cop_kills += 1
            else:
                name = _clean(ev.get("PilotName_Localised", raw_key))
                if name:
                    pirate_counts[name] += 1

        elif etype == "Died":
            killers = ev.get("Killers", [])
            if not killers:
                killers = [{"Name": ev.get("KillerName", "")}]
            for k in killers:
                raw_key = k.get("Name", "")
                if raw_key.lower().startswith(_POLICE_PREFIX):
                    cop_deaths += 1
                elif raw_key.upper().startswith("CMDR "):
                    name = _clean(raw_key)
                    if name:
                        pvp_counts[name] = pvp_counts.get(name, 0) + 1
                else:
                    name = _clean(k.get("Name_Localised", raw_key))
                    if name:
                        killed_us[name] = killed_us.get(name, 0) + 1

        elif etype == "Interdicted" and not ev.get("Submitted", True) and not ev.get("IsPlayer", False):
            name = _clean(ev.get("Interdictor_Localised", ev.get("Interdictor", "")))
            if name:
                pirate_counts[name] += 1

        elif etype == "PVPKill":
            name = _clean(ev.get("Victim", ""))
            if name:
                pvp_counts[name] = pvp_counts.get(name, 0) + 1

        elif etype == "Scanned" and ev.get("ScanType") == "Cargo":
            cop_scans += 1

    # ── Build sections ────────────────────────────────────────────────────────

    if not pirate_counts and not killed_us and not pvp_counts and not cop_scans:
        result.sections.append(ReportSection(
            heading="No Records",
            prose=(
                "No combat engagements found. "
                "This report sources pilot names from Bounty events (kills you made), "
                "Died events (who killed you), and fought-off NPC interdictions. "
                "Data will appear after sessions with active combat."
            )
        ))
        return result

    # Kills made
    if pirate_counts:
        total_unique = len(pirate_counts)
        total_kills  = sum(pirate_counts.values())
        by_freq      = sorted(pirate_counts.items(), key=lambda x: (-x[1], x[0].lower()))
        by_alpha     = sorted(pirate_counts.items(), key=lambda x: x[0].lower())

        repeat_offenders = [(n, c) for n, c in by_freq if c > 1]
        if repeat_offenders:
            sec_repeat = ReportSection(
                heading=f"Repeat Offenders  ({len(repeat_offenders)} pilots encountered more than once)",
                columns=["Name", "Times killed"],
                note="Either very unlucky, or the same name reused by the RNG."
            )
            for name, count in repeat_offenders[:50]:
                sec_repeat.rows.append(ReportRow([name, str(count)]))
            result.sections.append(sec_repeat)

        sec_kills = ReportSection(
            heading=f"Pilots Destroyed — Alphabetical  ({total_unique} unique · {total_kills} total kills)",
            columns=["Name", "Times killed"],
        )
        for name, count in by_alpha:
            sec_kills.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_kills)

    # Pilots who killed us
    if killed_us:
        sec_killers = ReportSection(
            heading=f"Pilots Who Have Killed You  ({len(killed_us)} unique)",
            columns=["Name", "Times"],
        )
        for name, count in sorted(killed_us.items(), key=lambda x: (-x[1], x[0].lower())):
            sec_killers.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_killers)

    # Space cops
    if cop_scans or cop_deaths or cop_kills:
        sec_cops = ReportSection(
            heading="Law Enforcement Interactions",
            columns=["Metric", "Count"],
            rows=[
                ReportRow(["Times police scanned your cargo",    str(cop_scans)]),
                ReportRow(["Times killed by law enforcement",    str(cop_deaths)]),
                ReportRow(["Authority vessels destroyed by you", str(cop_kills)]),
            ],
            note="Police have no individual names in the journal — only 'System Authority Vessel'."
        )
        result.sections.append(sec_cops)

    # PvP
    if pvp_counts:
        sec_pvp = ReportSection(
            heading=f"Player vs Player  ({len(pvp_counts)} unique commanders)",
            columns=["Commander", "Engagements"],
        )
        for name, count in sorted(pvp_counts.items(), key=lambda x: (-x[1], x[0].lower())):
            sec_pvp.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_pvp)

    return result


# ── Registry ──────────────────────────────────────────────────────────────────

REPORT_REGISTRY = [
    ("career",    "Career Overview",       report_career_overview),
    ("bounty",    "Bounty Breakdown",      report_bounty_breakdown),
    ("sessions",  "Session History",       report_session_history),
    ("grounds",   "Hunting Grounds",       report_hunting_grounds),
    ("rogues",    "NPC Rogues' Gallery",   report_rogues_gallery),
]
