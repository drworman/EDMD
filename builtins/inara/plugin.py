"""
builtins/inara/plugin.py — Inara API uploader for EDMD.

Posts commander activity to the Inara API (https://inara.cz/inapi/v1/).

What is posted
--------------
Travel       — FSD jumps, dockings
Status       — credits, ranks (pilot, engineer, power), reputation
Missions     — accepted, completed, failed, abandoned
Ship         — current ship identity and full loadout
Materials    — Horizons materials snapshot (from Materials journal event)

What is NOT posted (yet — pending CAPI integration)
----------------------------------------------------
Fleet (stored ships)       — StoredShips is stale; CAPI /profile is authoritative
Combat log (kills, bonds)  — high-frequency; Inara does not require real-time
Market transactions        — covered by EDDN for the galaxy-wide dataset

Config [Inara] in config.toml
------------------------------
    Enabled        = false          # opt-in
    ApiKey         = ""             # personal API key from inara.cz settings
    CommanderName  = ""             # in-game name only — do not include "CMDR"

Rate limits
-----------
Inara enforces 2 requests per minute per API key across all apps.  We batch
all events between session transitions and flush on FSDJump / Docked / LoadGame.
The sender thread enforces a minimum 30-second gap between requests.

Whitelisting
------------
App name registered with Inara: EDMD
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import EDMD_DATA_DIR, VERSION

# ── Constants ─────────────────────────────────────────────────────────────────

PLUGIN_VERSION  = "1.0.0"
INARA_API_URL   = "https://inara.cz/inapi/v1/"
APP_NAME        = "EDMD"
APP_VERSION     = VERSION
HTTP_TIMEOUT_S  = 20
SEND_INTERVAL_S = 30        # 2 requests/minute hard limit from Inara
STARTUP_DELAY_S = 8         # wait before first send so preload finishes
BATCH_MAX       = 100       # events per request (Inara has no documented per-batch limit)
QUEUE_FILE: Path = EDMD_DATA_DIR / "inara_queue.jsonl"

# Journal Rank keys → Inara rankName strings
_RANK_KEYS = {
    "Combat":       "combat",
    "Trade":        "trade",
    "Explore":      "explore",
    "Soldier":      "soldier",
    "Exobiologist": "exobiologist",
    "CQC":          "cqc",
    "Federation":   "federation",
    "Empire":       "empire",
}

CFG_DEFAULTS = {
    "Enabled":       False,
    "ApiKey":        "",
    "CommanderName": "",
}


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):
    """
    Background thread — batches Inara API events and POSTs them.

    Call push(event_dict) to enqueue an individual Inara event.
    Call flush() to force an immediate send of the accumulated batch.
    Call stop() for clean shutdown.
    """

    def __init__(self, cmdr_name: str, api_key: str):
        super().__init__(daemon=True, name="inara-sender")
        self._cmdr      = cmdr_name
        self._key       = api_key
        self._q         = queue.Queue()
        self._stop_evt  = threading.Event()
        self._last_send = 0.0

    def push(self, inara_event: dict) -> None:
        self._q.put(inara_event)

    def flush(self) -> None:
        self._q.put(_FLUSH_SENTINEL)

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)

    def run(self) -> None:
        time.sleep(STARTUP_DELAY_S)
        self._drain_disk()

        batch: list[dict] = []

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if batch and (time.monotonic() - self._last_send >= SEND_INTERVAL_S):
                    self._send_batch(batch)
                    batch = []
                continue

            if item is None:
                if batch:
                    self._send_batch(batch)
                return

            if item is _FLUSH_SENTINEL:
                if batch:
                    self._send_batch(batch)
                    batch = []
                continue

            batch.append(item)
            if len(batch) >= BATCH_MAX:
                self._send_batch(batch)
                batch = []

        if batch:
            self._send_batch(batch)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _send_batch(self, events: list[dict]) -> None:
        """POST a batch of Inara events.  Persist to disk on failure."""
        gap = SEND_INTERVAL_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)

        payload = {
            "header": {
                "appName":        APP_NAME,
                "appVersion":     APP_VERSION,
                "isDeveloped":    False,
                "APIkey":         self._key,
                "commanderName":  self._cmdr,
            },
            "events": events,
        }

        try:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            req = urllib.request.Request(
                INARA_API_URL,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent":   f"{APP_NAME}/{APP_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body.strip() else {}
                header_status = result.get("header", {}).get("eventStatus", 200)
                if header_status not in (200, 204):
                    msg = result.get("header", {}).get("eventStatusText", "")
                    print(f"  [Inara] API header error {header_status}: {msg}")
                    # 400 = bad request — no point retrying
                    if header_status != 400:
                        self._persist(events)

        except urllib.error.HTTPError as e:
            print(f"  [Inara] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            if e.code != 400:
                self._persist(events)
        except Exception as exc:
            print(f"  [Inara] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
            self._persist(events)

    # ── Disk queue ────────────────────────────────────────────────────────────

    def _persist(self, events: list[dict]) -> None:
        try:
            QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps({"queued_at": time.time(), "msg": ev}) + "\n")
        except Exception as e:
            print(f"  [Inara] Failed to persist events to disk: {e}")

    def _drain_disk(self) -> None:
        if not QUEUE_FILE.exists():
            return
        try:
            lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        if not lines:
            return

        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line)["msg"])
            except Exception:
                pass

        if events:
            print(f"  [Inara] Replaying {len(events)} queued event(s) from disk...")
            for i in range(0, len(events), BATCH_MAX):
                self._send_batch(events[i:i + BATCH_MAX])
                if i + BATCH_MAX < len(events):
                    time.sleep(SEND_INTERVAL_S)

        try:
            QUEUE_FILE.unlink(missing_ok=True)
        except Exception:
            pass


_FLUSH_SENTINEL = object()


# ── Plugin ────────────────────────────────────────────────────────────────────

class InaraPlugin(BasePlugin):

    PLUGIN_NAME        = "inara"
    PLUGIN_DISPLAY     = "Inara Uploader"
    PLUGIN_VERSION     = PLUGIN_VERSION
    PLUGIN_DESCRIPTION = "Posts commander activity to inara.cz."
    PLUGIN_DEFAULT_ENABLED = False

    SUBSCRIBED_EVENTS = [
        # Session
        "LoadGame", "Commander",
        # Location / travel
        "Location", "FSDJump", "CarrierJump", "Docked",
        # Ranks and reputation
        "Rank", "Progress", "Reputation", "EngineerProgress",
        # Powerplay
        "Powerplay", "PowerplayJoin", "PowerplayLeave",
        "PowerplayDefect", "PowerplayRank", "PowerplayMerits",
        # Credits
        "Statistics",
        # Missions
        "MissionAccepted", "MissionCompleted",
        "MissionFailed", "MissionAbandoned",
        # Ship
        "Loadout", "ShipyardSwap",
        # Materials
        "Materials",
    ]

    def on_load(self, core) -> None:
        self.core          = core
        self._enabled      = False
        self._sender: _Sender | None = None

        # Internal tracking — maintained independently from MonitorState
        # so we never accidentally send stale data.
        self._cmdr_name:    str = ""
        self._ship_type:    str = ""
        self._ship_id:      int | None = None
        self._system_name:  str | None = None
        self._star_pos:     list | None = None
        # Rank snapshot — accumulated from Rank + Progress events
        # so we can send a combined array to Inara on LoadGame
        self._rank_values:    dict[str, int]   = {}   # key → rankValue
        self._rank_progress:  dict[str, float] = {}   # key → fraction 0-1

        cfg = core.load_setting("Inara", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            print("  [Inara] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return
        if not cfg["ApiKey"] or not cfg["CommanderName"]:
            print(
                "  [Inara] Disabled — ApiKey and CommanderName must both be "
                "set in config.toml under [Inara]"
            )
            return

        self._enabled     = True
        # Strip "CMDR " prefix if the user included it — a common mistake
        raw_name          = cfg["CommanderName"].strip()
        self._cmdr_name   = raw_name[5:].strip() if raw_name.upper().startswith("CMDR ") else raw_name
        self._sender      = _Sender(self._cmdr_name, cfg["ApiKey"])
        self._sender.start()

        print(f"  [Inara] Enabled — uploading as CMDR {self._cmdr_name}")

    def on_unload(self) -> None:
        if self._sender:
            self._sender.stop()
            self._sender.join(timeout=5)

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event", "")
        ts = event.get("timestamp", "")

        # Always maintain internal tracking regardless of enabled state
        self._track(ev, event)

        if not self._enabled or self._sender is None:
            return

        # ── Beta guard — never send beta data to Inara ────────────────────────
        game_version = getattr(state, "_game_version", "") or ""
        if "beta" in game_version.lower() or game_version.startswith("3."):
            return

        match ev:

            case "LoadGame":
                credits = event.get("Credits")
                if credits is not None and credits >= 0:
                    self._push(ts, "setCommanderCredits", {
                        "commanderCredits": int(credits),
                    })
                # Flush current rank snapshot
                if self._rank_values:
                    self._push_ranks(ts)
                self._sender.flush()

            case "Rank":
                for journal_key, inara_key in _RANK_KEYS.items():
                    if journal_key in event:
                        self._rank_values[inara_key] = int(event[journal_key])

            case "Progress":
                for journal_key, inara_key in _RANK_KEYS.items():
                    if journal_key in event:
                        self._rank_progress[inara_key] = event[journal_key] / 100.0

            case "Statistics":
                bank = event.get("Bank_Account", {})
                credits = bank.get("Current_Wealth")
                assets  = bank.get("Assets_Total") or bank.get("Current_Wealth")
                if credits is not None and credits >= 0:
                    data: dict = {"commanderCredits": int(credits)}
                    if assets is not None and assets >= 0:
                        data["commanderAssets"] = int(assets)
                    self._push(ts, "setCommanderCredits", data)

            case "Reputation":
                # Post major faction reputations
                reps = []
                for faction_key, inara_name in [
                    ("Federation", "Federation"),
                    ("Empire",     "Empire"),
                    ("Alliance",   "Alliance"),
                    ("Independent","Independent"),
                ]:
                    val = event.get(faction_key)
                    if val is not None:
                        reps.append({
                            "factionName":       inara_name,
                            "reputationValue":   val / 100.0,
                        })
                if reps:
                    self._push(ts, "setCommanderReputationMajorFaction", reps)

            case "EngineerProgress":
                engineers = event.get("Engineers", [])
                if engineers:
                    eng_data = []
                    for eng in engineers:
                        name   = eng.get("Engineer")
                        stage  = eng.get("Progress")       # "Known"/"Invited"/"Unlocked"/etc.
                        rank_v = eng.get("Rank")
                        if name and stage:
                            entry: dict = {
                                "engineerName": name,
                                "rankStage":    stage,
                            }
                            if rank_v is not None:
                                entry["rankValue"] = int(rank_v)
                            eng_data.append(entry)
                    if eng_data:
                        self._push(ts, "setCommanderRankEngineer", eng_data)

            case "Powerplay" | "PowerplayJoin":
                power  = event.get("Power")
                rank_v = event.get("Rank", 1)
                merits = event.get("Merits") or event.get("TotalMerits")
                if power:
                    data: dict = {
                        "powerName": power,
                        "rankValue": int(rank_v),
                    }
                    if merits is not None:
                        data["meritsValue"] = int(merits)
                    self._push(ts, "setCommanderRankPower", data)

            case "PowerplayLeave":
                # Signal end of pledge — send rank 0
                power = getattr(state, "pp_power", None)
                if power:
                    self._push(ts, "setCommanderRankPower", {
                        "powerName": power,
                        "rankValue": 0,
                    })

            case "PowerplayRank":
                rank_v = event.get("Rank")
                power  = getattr(state, "pp_power", None)
                merits = getattr(state, "pp_merits_total", None)
                if power and rank_v is not None:
                    data = {"powerName": power, "rankValue": int(rank_v)}
                    if merits is not None:
                        data["meritsValue"] = int(merits)
                    self._push(ts, "setCommanderRankPower", data)

            case "PowerplayMerits":
                power  = event.get("Power") or getattr(state, "pp_power", None)
                rank_v = getattr(state, "pp_rank", None)
                merits = event.get("TotalMerits")
                if power and merits is not None:
                    data = {"powerName": power, "meritsValue": int(merits)}
                    if rank_v is not None:
                        data["rankValue"] = int(rank_v)
                    self._push(ts, "setCommanderRankPower", data)

            case "FSDJump" | "CarrierJump":
                data: dict = {
                    "starsystemName": event.get("StarSystem", ""),
                }
                if self._star_pos:
                    data["starsystemCoords"] = self._star_pos
                jump_dist = event.get("JumpDist")
                if jump_dist is not None:
                    data["jumpDistance"] = round(float(jump_dist), 2)
                if self._ship_type:
                    data["shipType"] = self._ship_type
                if self._ship_id is not None:
                    data["shipGameID"] = self._ship_id
                self._push(ts, "addCommanderTravelFSDJump", data)
                self._push_ranks(ts)
                self._sender.flush()

            case "Docked":
                data = {
                    "starsystemName": event.get("StarSystem", ""),
                    "stationName":    event.get("StationName", ""),
                }
                market_id = event.get("MarketID")
                if market_id is not None:
                    data["marketID"] = int(market_id)
                if self._ship_type:
                    data["shipType"] = self._ship_type
                if self._ship_id is not None:
                    data["shipGameID"] = self._ship_id
                self._push(ts, "addCommanderTravelDock", data)
                self._sender.flush()

            case "MissionAccepted":
                mission_id = event.get("MissionID")
                name       = event.get("Name", "")
                faction    = event.get("Faction", "")
                expires    = event.get("Expiry", "")
                if mission_id is not None:
                    data = {
                        "missionGameID": int(mission_id),
                        "missionName":   name,
                    }
                    if faction:
                        data["minorfactionName"] = faction
                    if expires:
                        data["missionExpiry"] = expires
                    self._push(ts, "addCommanderMission", data)

            case "MissionCompleted":
                mission_id = event.get("MissionID")
                reward     = event.get("Reward", 0)
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionCompleted", {
                        "missionGameID": int(mission_id),
                        "rewardCredits": int(reward),
                    })

            case "MissionFailed":
                mission_id = event.get("MissionID")
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionFailed", {
                        "missionGameID": int(mission_id),
                    })

            case "MissionAbandoned":
                mission_id = event.get("MissionID")
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionAbandoned", {
                        "missionGameID": int(mission_id),
                    })

            case "Loadout":
                # Current ship identity
                ship_type = event.get("Ship", "")
                ship_id   = event.get("ShipID")
                if ship_type:
                    ship_data: dict = {
                        "shipType":      ship_type,
                        "isCurrentShip": True,
                    }
                    if ship_id is not None:
                        ship_data["shipGameID"] = int(ship_id)
                    name  = event.get("ShipName")
                    ident = event.get("ShipIdent")
                    if name:  ship_data["shipName"]  = name
                    if ident: ship_data["shipIdent"] = ident
                    self._push(ts, "setCommanderShip", ship_data)

                # Full loadout
                modules = event.get("Modules", [])
                if modules and ship_type:
                    loadout_modules = []
                    for mod in modules:
                        slot = mod.get("Slot", "")
                        item = mod.get("Item", "")
                        if not slot or not item:
                            continue
                        entry: dict = {"Slot": slot, "Item": item}
                        # Engineering blueprint if present
                        eng = mod.get("Engineering")
                        if eng:
                            bp: dict = {}
                            if eng.get("BlueprintName"): bp["BlueprintName"]     = eng["BlueprintName"]
                            if eng.get("Level"):         bp["Level"]             = int(eng["Level"])
                            if eng.get("Quality"):       bp["Quality"]           = float(eng["Quality"])
                            if eng.get("ExperimentalEffect"): bp["ExperimentalEffect"] = eng["ExperimentalEffect"]
                            if bp:
                                entry["Engineering"] = bp
                        loadout_modules.append(entry)

                    loadout_data: dict = {
                        "shipType":    ship_type,
                        "shipLoadout": loadout_modules,
                    }
                    if ship_id is not None:
                        loadout_data["shipGameID"] = int(ship_id)
                    self._push(ts, "setCommanderShipLoadout", loadout_data)

            case "Materials":
                # Full materials snapshot — post as setCommanderInventoryMaterials
                all_materials = []
                for category, journal_key in [
                    ("raw",          "Raw"),
                    ("manufactured", "Manufactured"),
                    ("encoded",      "Encoded"),
                ]:
                    for item in event.get(journal_key, []):
                        all_materials.append({
                            "itemName":     item.get("Name", ""),
                            "itemCount":    int(item.get("Count", 0)),
                            "itemCategory": category,
                        })
                if all_materials:
                    self._push(ts, "setCommanderInventoryMaterials", all_materials)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _track(self, ev: str, event: dict) -> None:
        """Maintain internal ship/location state from raw journal events."""
        if ev == "Commander":
            name = event.get("Name")
            if name:
                self._cmdr_name = name

        elif ev in ("FSDJump", "CarrierJump", "Location"):
            self._system_name = event.get("StarSystem") or self._system_name
            pos = event.get("StarPos")
            if pos:
                self._star_pos = pos

        elif ev == "Loadout":
            ship_type = event.get("Ship")
            ship_id   = event.get("ShipID")
            if ship_type:
                self._ship_type = ship_type
            if ship_id is not None:
                self._ship_id = int(ship_id)

        elif ev == "ShipyardSwap":
            ship_type = event.get("ShipType")
            ship_id   = event.get("ShipID")
            if ship_type:
                self._ship_type = ship_type
            if ship_id is not None:
                self._ship_id = int(ship_id)

    def _push(self, timestamp: str, event_name: str, event_data) -> None:
        """Enqueue a single Inara API event."""
        if self._sender:
            self._sender.push({
                "eventName":      event_name,
                "eventTimestamp": timestamp,
                "eventData":      event_data,
            })

    def _push_ranks(self, timestamp: str) -> None:
        """Send the accumulated rank snapshot as a combined setCommanderRankPilot."""
        if not self._rank_values:
            return
        ranks = []
        for key, value in self._rank_values.items():
            entry: dict = {"rankName": key, "rankValue": value}
            progress = self._rank_progress.get(key)
            if progress is not None:
                entry["rankProgress"] = round(progress, 4)
            ranks.append(entry)
        self._push(timestamp, "setCommanderRankPilot", ranks)
