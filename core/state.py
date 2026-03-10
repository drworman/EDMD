"""
core/state.py — Runtime state containers, constants, and session persistence.

No imports from other EDMD core modules — this is the bottom of the
dependency stack.  Everything else imports from here.
"""

import json
import os
import platform as _pl
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Program identity ──────────────────────────────────────────────────────────

PROGRAM = "Elite Dangerous Monitor Daemon"
DESC    = "Continuous monitoring of Elite Dangerous AFK sessions."
AUTHOR  = "CMDR CALURSUS"
VERSION = "20260310"
GITHUB_REPO = "drworman/EDMD"
DEBUG_MODE  = False


# ── User data directory ───────────────────────────────────────────────────────
# Linux:   ~/.local/share/EDMD/
# Windows: %APPDATA%\EDMD\
# macOS:   ~/Library/Application Support/EDMD/
# A symlink ~/.config/EDMD → ~/.local/share/EDMD is created on Linux.

def _user_data_dir() -> Path:
    system = _pl.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "EDMD"
    d.mkdir(parents=True, exist_ok=True)
    if system not in ("Windows", "Darwin"):
        config_link = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "EDMD"
        if not config_link.exists() and not config_link.is_symlink():
            try:
                config_link.symlink_to(d)
            except OSError:
                pass
    return d


EDMD_DATA_DIR: Path = _user_data_dir()
STATE_FILE: Path    = EDMD_DATA_DIR / "session_state.json"


# ── Numeric / display constants ───────────────────────────────────────────────

MAX_DUPLICATES       = 5
FUEL_WARN_THRESHOLD  = 0.2   # 20 %
FUEL_CRIT_THRESHOLD  = 0.1   # 10 %
RECENT_KILL_WINDOW   = 10
LABEL_UNKNOWN        = "[Unknown]"
PATTERN_JOURNAL      = r"^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$"
PATTERN_WEBHOOK      = r"^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-z0-9_-]+$"

PIRATE_NOATTACK_MSGS = [
    "$Pirate_ThreatTooHigh",
    "$Pirate_NotEnoughCargo",
    "$Pirate_OnNoCargoFound",
]

FIGHTER_TYPE_NAMES = {
    "independent_fighter":   "F63 Condor",
    "empire_fighter":        "GU-97",
    "federation_fighter":    "F/A-26 Strike",
    "gdn_hybrid_fighter_v1": "Trident",
    "gdn_hybrid_fighter_v2": "Javelin",
    "gdn_hybrid_fighter_v3": "Lancer",
}

FIGHTER_LOADOUT_NAMES = {
    ("empire_fighter",      "one"):   "GU-97 (Gelid F)",
    ("empire_fighter",      "two"):   "GU-97 (Rogue F)",
    ("empire_fighter",      "three"): "GU-97 (Aegis F)",
    ("independent_fighter", "at"):    "F63 Condor (Aegis)",
    ("independent_fighter", "df"):    "F63 Condor (Rogue)",
    ("independent_fighter", "four"):  "F63 Condor (Gelid)",
    ("federation_fighter",  "one"):   "F/A-26 Strike (Gelid F)",
    ("federation_fighter",  "two"):   "F/A-26 Strike (Rogue F)",
    ("federation_fighter",  "three"): "F/A-26 Strike (Aegis F)",
}

# ── Ship name normalisation ───────────────────────────────────────────────────
#
# The game's journal is inconsistent: some ships arrive with correct casing via
# the _Localised field, others arrive lowercase (e.g. "adder", "eagle") or as
# raw internal identifiers (e.g. "CobraMkIII", "Type_9_Military").
#
# normalise_ship_name() is the single point of truth for ship display names.
# Every place in EDMD that resolves a ship name must call this function.
# Keys are lowercase; the function lowercases its input before lookup.

_SHIP_NAMES: dict[str, str] = {
    # ── Faulcon DeLacy ────────────────────────────────────────────────────────
    "sidewinder":               "Sidewinder",
    "sidewindermkii":           "Sidewinder Mk. II",
    "eagle":                    "Eagle",
    "eaglemkii":                "Eagle Mk. II",
    "cobramkiii":               "Cobra Mk. III",
    "cobramkiv":                "Cobra Mk. IV",
    "cobra mk. iii":            "Cobra Mk. III",
    "cobra mk. iv":             "Cobra Mk. IV",
    "cobra mkiii":              "Cobra Mk. III",
    "cobra mkiv":               "Cobra Mk. IV",
    "python":                   "Python",
    "pythonmkii":               "Python Mk. II",
    "anaconda":                 "Anaconda",
    "mamba":                    "Mamba",
    # ── Lakon Spaceways ───────────────────────────────────────────────────────
    "adder":                    "Adder",
    "asp":                      "Asp Explorer",
    "asp explorer":             "Asp Explorer",
    "aspscout":                 "Asp Scout",
    "asp scout":                "Asp Scout",
    "hauler":                   "Hauler",
    "diamondbackscout":         "Diamondback Scout",
    "diamondback scout":        "Diamondback Scout",
    "diamondbackxl":            "Diamondback Explorer",
    "diamondback explorer":     "Diamondback Explorer",
    "type6":                    "Type-6 Transporter",
    "type-6 transporter":       "Type-6 Transporter",
    "type6transporter":         "Type-6 Transporter",
    "type7":                    "Type-7 Transporter",
    "type-7 transporter":       "Type-7 Transporter",
    "type7transporter":         "Type-7 Transporter",
    "type9":                    "Type-9 Heavy",
    "type-9 heavy":             "Type-9 Heavy",
    "type9heavy":               "Type-9 Heavy",
    "type10":                   "Type-10 Defender",
    "type-10 defender":         "Type-10 Defender",
    "type10defender":           "Type-10 Defender",
    "type_9_military":          "Type-10 Defender",
    "krait_mkii":               "Krait Mk. II",
    "krait mkii":               "Krait Mk. II",
    "krait mk. ii":             "Krait Mk. II",
    "kraitmkii":                "Krait Mk. II",
    "krait_light":              "Krait Phantom",
    "krait light":              "Krait Phantom",
    "krait phantom":            "Krait Phantom",
    "manowarinterdictor":       "Mandalay",
    "mandalay":                 "Mandalay",
    # ── Saud Kruger ───────────────────────────────────────────────────────────
    "belugaliner":              "Beluga Liner",
    "beluga liner":             "Beluga Liner",
    "beluga":                   "Beluga Liner",
    "dolphin":                  "Dolphin",
    "orca":                     "Orca",
    # ── Core Dynamics ─────────────────────────────────────────────────────────
    "viper":                    "Viper Mk. III",
    "vipermkiii":               "Viper Mk. III",
    "viper mk. iii":            "Viper Mk. III",
    "vipermkiv":                "Viper Mk. IV",
    "viper mk. iv":             "Viper Mk. IV",
    "vulture":                  "Vulture",
    "federation_dropship":      "Federal Dropship",
    "federaldropship":          "Federal Dropship",
    "federal dropship":         "Federal Dropship",
    "federation_dropship_mkii": "Federal Assault Ship",
    "federalassaultship":       "Federal Assault Ship",
    "federal assault ship":     "Federal Assault Ship",
    "federation_gunship":       "Federal Gunship",
    "federalgunship":           "Federal Gunship",
    "federal gunship":          "Federal Gunship",
    "federation_corvette":      "Federal Corvette",
    "federalcorvette":          "Federal Corvette",
    "federal corvette":         "Federal Corvette",
    # ── Gutamaya ─────────────────────────────────────────────────────────────
    "empire_eagle":             "Imperial Eagle",
    "imperialeagle":            "Imperial Eagle",
    "imperial eagle":           "Imperial Eagle",
    "empire_courier":           "Imperial Courier",
    "imperialcourier":          "Imperial Courier",
    "imperial courier":         "Imperial Courier",
    "empire_trader":            "Imperial Clipper",
    "imperialclipper":          "Imperial Clipper",
    "imperial clipper":         "Imperial Clipper",
    "empire_fighter":           "Imperial Fighter",
    "imperial fighter":         "Imperial Fighter",
    "cutter":                   "Imperial Cutter",
    "imperialcutter":           "Imperial Cutter",
    "imperial cutter":          "Imperial Cutter",
    # ── Alliance / Crusader ───────────────────────────────────────────────────
    "typex":                    "Alliance Chieftain",
    "alliance chieftain":       "Alliance Chieftain",
    "alliancechieftain":        "Alliance Chieftain",
    "typex_2":                  "Alliance Crusader",
    "alliance crusader":        "Alliance Crusader",
    "alliancecrusader":         "Alliance Crusader",
    "typex_3":                  "Alliance Challenger",
    "alliance challenger":      "Alliance Challenger",
    "alliancechallenger":       "Alliance Challenger",
    # ── Zorgon Peterson ───────────────────────────────────────────────────────
    "ferdelance":               "Fer-de-Lance",
    "fer-de-lance":             "Fer-de-Lance",
    "fer de lance":             "Fer-de-Lance",
    "asp_sa":                   "Asp Scout",
    "keelback":                 "Keelback",
    # ── Misc / Rare ───────────────────────────────────────────────────────────
    "independant_trader":       "Keelback",
    "imperial_fighter":         "Imperial Fighter",
    "independent_fighter":      "F63 Condor",
    "federation_fighter":       "F/A-26 Strike",
    "gdn_hybrid_fighter_v1":    "Trident",
    "gdn_hybrid_fighter_v2":    "Javelin",
    "gdn_hybrid_fighter_v3":    "Lancer",
    "testbuggy":                "SRV",
    "scarab":                   "SRV",
    "combat_multirole":         "Mamba",
}


def normalise_ship_name(raw: str | None) -> str | None:
    """Return the correctly-capitalised display name for a ship.

    Accepts both internal journal identifiers (e.g. ``"adder"``,
    ``"CobraMkIII"``) and pre-localised strings that the game sometimes
    sends in lowercase (e.g. ``"eagle"``).

    Falls back to ``str.title()`` for names not in the correction map so
    future or unknown ships still get reasonable capitalisation.

    Returns ``None`` if ``raw`` is ``None`` or empty.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _SHIP_NAMES:
        return _SHIP_NAMES[key]
    # Not in map — clean up internal underscores/dots and title-case
    return raw.replace("_", " ").strip().title()


RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


# ── Session data (per-session counters, reset on sessionstart) ────────────────

class SessionData:
    def __init__(self):
        self.reset()

    def reset(self):
        self.recent_inbound_scans  = []
        self.recent_outbound_scans = []
        self.last_kill_time        = 0
        self.last_kill_mono        = 0
        self.kill_interval_total   = 0
        self.recent_kill_times     = []
        self.inbound_scan_count    = 0
        self.kills                 = 0
        self.credit_total          = 0
        self.faction_tally         = {}
        self.merits                = 0
        self.last_security_ship    = ""
        self.low_cargo_count       = 0
        self.fuel_check_time       = 0
        self.fuel_check_level      = 0
        self.pending_merit_events  = 0


# ── Monitor state (persistent across the session, reflects game state) ────────

class MonitorState:
    def __init__(self):
        self.session_start_time      = None
        self.alerted_no_kills        = None
        self.alerted_kill_rate       = None
        self.fuel_tank_size          = 64
        self.reward_type             = "credit_total"
        self.fighter_integrity       = 0
        self.logged                  = 0
        self.lines                   = 0
        self.missions                = False
        self.active_missions         = []
        self.missions_complete       = 0
        self.prev_event              = None
        self.event_time              = None
        self.last_dup_key            = ""
        self.dup_count               = 1
        self.dup_suppressed          = False
        self.in_preload              = True
        self.pilot_name              = None
        self.pilot_ship              = None
        self.pilot_rank              = None
        self.pilot_rank_progress     = None
        self.pilot_mode              = None
        self.pilot_location          = None   # compat alias; prefer pilot_system/pilot_body
        self.pilot_system            = None
        self.pilot_body              = None
        self.last_rate_check         = None
        self.last_periodic_summary   = None
        self.last_inactive_alert     = None
        self.last_rate_alert         = None
        self.last_offline_alert      = None
        self.offline_since_mono      = None
        self.in_game                 = False
        self.mission_value_map       = {}
        self.stack_value             = 0
        self.has_fighter_bay         = False
        self.mission_target_faction_map = {}

        # SLF state
        self.slf_deployed  = False
        self.slf_docked    = True
        self.slf_hull      = 100
        self.slf_orders    = None
        self.slf_loadout   = None

        # Powerplay state
        self.pp_power        = None
        self.pp_rank         = None
        self.pp_merits_total = None

        # Ship identity (from Loadout)
        self.ship_name  = None
        self.ship_ident = None

        # Ship hull and shields
        self.ship_hull              = 100
        self.ship_shields           = True
        self.ship_shields_recharging = False

        # Commander in SLF
        self.cmdr_in_slf = False

        # NPC Crew state
        self.crew_name         = None
        self.crew_rank         = None
        self.crew_hire_time    = None
        self.crew_total_paid   = None
        self.crew_paid_complete = False
        self.crew_active       = False

        # SLF type and stock
        self.slf_type            = None
        self.slf_stock_total     = 0
        self.slf_destroyed_count = 0

    def sessionstart(self, active_session: SessionData, reset: bool = False):
        if not self.session_start_time or reset:
            self.session_start_time = self.event_time
            active_session.reset()
            self.alerted_no_kills      = None
            self.alerted_kill_rate     = None
            self.last_rate_check       = time.monotonic()
            self.last_periodic_summary = time.monotonic()
            self.last_inactive_alert   = None
            self.last_rate_alert       = None
            global _session_start_iso
            _session_start_iso = (
                self.session_start_time.isoformat()
                if self.session_start_time else None
            )

    def sessionend(self):
        if self.session_start_time:
            self.session_start_time = None

    def reset_missions(self):
        """Clear mission state so a new game session bootstraps cleanly.

        Called on LoadGame.  Without this, missions flag and maps carried over
        from a prior session prevent the Missions bulk event and
        bootstrap_missions() from running.
        """
        self.missions                   = False
        self.active_missions            = []
        self.missions_complete          = 0
        self.stack_value                = 0
        self.mission_value_map          = {}
        self.mission_target_faction_map = {}


# ── Session state persistence ─────────────────────────────────────────────────
# Thin JSON snapshot written before upgrade-restart and on clean exit.
# Consumed at startup only when it references the same journal file.

# Wall-clock ISO of session start — set after sessionstart() fires.
_session_start_iso: str | None = None


def save_session_state(journal_path: Path, active_session: SessionData) -> None:
    """Write active session counters to STATE_FILE for upgrade-restart recovery."""
    try:
        payload = {
            "journal":             str(journal_path),
            "session_start_time":  _session_start_iso,
            "kills":               active_session.kills,
            "credit_total":        active_session.credit_total,
            "merits":              active_session.merits,
            "faction_tally":       active_session.faction_tally,
            "kill_interval_total": active_session.kill_interval_total,
            "recent_kill_times":   [t.isoformat() for t in active_session.recent_kill_times],
            "inbound_scan_count":  active_session.inbound_scan_count,
            "low_cargo_count":     active_session.low_cargo_count,
        }
        STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_session_state(
    journal_path: Path,
    active_session: SessionData,
) -> None:
    """Restore session counters from STATE_FILE if it matches journal_path.

    Called once during preload.  Consumed immediately — STATE_FILE is deleted
    after a successful load so state is never restored twice.
    """
    global _session_start_iso
    try:
        if not STATE_FILE.exists():
            return
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if payload.get("journal") != str(journal_path):
            return
        active_session.kills               = int(payload.get("kills", 0))
        active_session.credit_total        = int(payload.get("credit_total", 0))
        active_session.merits              = int(payload.get("merits", 0))
        active_session.faction_tally       = dict(payload.get("faction_tally", {}))
        active_session.kill_interval_total = float(payload.get("kill_interval_total", 0))
        active_session.inbound_scan_count  = int(payload.get("inbound_scan_count", 0))
        active_session.low_cargo_count     = int(payload.get("low_cargo_count", 0))
        active_session.recent_kill_times   = [
            datetime.fromisoformat(t)
            for t in payload.get("recent_kill_times", []) if t
        ]
        _session_start_iso = payload.get("session_start_time")
        STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
