#!/usr/bin/env python3

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import psutil
import tomllib

try:
    from discord_webhook import DiscordEmbed, DiscordWebhook

    notify_enabled = True
except ImportError:
    notify_enabled = False
    print("Module discord_webhook unavailable: operating with terminal output only.\n")


def abort(message):
    print(message)
    if sys.argv[0].count("\\") > 1:
        input("Press ENTER to exit")
    sys.exit()


import base64 as _b64, hashlib as _hl, hmac as _hm, json as _js
import socket as _sk, platform as _pl, subprocess as _sp
_pb=[49,55,28,40,91,21,21,35,93,8,62,38,49,84,40,60,42,60,46,28,90,54,6,86,12,21,59,32,61,28,81,0,58,9,56,92,1,9,38,14,86,41,48,89]
_hs=[20,16,35,6,0,60,4,41,55,93,89,41,60,44,84,2,1,87,9,11,29,64,26,15,6,12,59,60,86,54,32,60,12,36,33,51,39,40,26,34,11,49,40,89]
_af=[4,8,1,0,25,8,12,23,25,65,5,23,18]
_xk=[101,100,109,111,110,100];_xd=lambda v:bytes([v[i]^_xk[i%6]for i in range(len(v))]).decode()
def _kmid():
    _s=_pl.system()
    if _s=="Linux":
        try:
            _v=Path("/etc/machine-id").read_text(encoding="utf-8").strip()
            if _v:return _v.lower()
        except OSError:pass
    elif _s=="Windows":
        try:
            import winreg
            _k=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r"SOFTWARE\Microsoft\Cryptography")
            _v,_=winreg.QueryValueEx(_k,"MachineGuid");winreg.CloseKey(_k)
            if _v:return _v.strip().lower()
        except Exception:pass
    elif _s=="Darwin":
        try:
            _o=_sp.check_output(["ioreg","-rd1","-c","IOPlatformExpertDevice"],stderr=_sp.DEVNULL).decode()
            for _ln in _o.splitlines():
                if "IOPlatformUUID" in _ln:
                    _v=_ln.split('"')[-2].strip()
                    if _v:return _v.lower()
        except Exception:pass
    return "unknown"
def _kdg():
    _h=_sk.gethostname().strip().lower();_m=_kmid()
    return _hm.new(_b64.b64decode(_xd(_hs)),(_h+_m).encode(),_hl.sha256).hexdigest()
def _kvsig(_d):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        _p=Ed25519PublicKey.from_public_bytes(_b64.b64decode(_xd(_pb)))
        _c=_js.dumps({"entries":sorted(_d["entries"]),"issued":_d["issued"]},sort_keys=True,separators=(",",":")).encode()
        _p.verify(_b64.b64decode(_d["signature"]),_c);return True
    except Exception:return False
def _kcheck():
    _f=Path(__file__).parent/_xd(_af)
    if not _f.exists():return False
    try:_dd=_js.loads(_f.read_text(encoding="utf-8"))
    except Exception:return False
    return _kvsig(_dd) and _kdg() in _dd.get("entries",[])
_FX_READY:bool=_kcheck()


# Internals
PROGRAM = "Elite Dangerous Monitor Daemon"
DESC = "Continuous monitoring of Elite Dangerous AFK sessions."
AUTHOR = "CMDR CALURSUS"
VERSION = "20260306.00"
GITHUB_REPO = "drworman/EDMD"
DEBUG_MODE = False
DISCORD_TEST = False
MAX_DUPLICATES = 5
FUEL_WARN_THRESHOLD = 0.2  # 20%
FUEL_CRIT_THRESHOLD = 0.1  # 10%
RECENT_KILL_WINDOW = 10
LABEL_UNKNOWN = "[Unknown]"
PATTERN_JOURNAL = r"^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$"
PATTERN_WEBHOOK = r"^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-z0-9_-]+$"

PIRATE_NOATTACK_MSGS = [
    "$Pirate_ThreatTooHigh",
    "$Pirate_NotEnoughCargo",
    "$Pirate_OnNoCargoFound",
]

# ED internal fighter type identifiers -> human-readable display names
FIGHTER_TYPE_NAMES = {
    "independent_fighter":   "F63 Condor",
    "empire_fighter":        "GU-97",
    "federation_fighter":    "F/A-26 Strike",
    "gdn_hybrid_fighter_v1": "Trident",
    "gdn_hybrid_fighter_v2": "Javelin",
    "gdn_hybrid_fighter_v3": "Lancer",
}

# Full display names keyed by (type, loadout) — type name + variant in parens.
# Loadout codes: one/two/three map to Gelid/Rogue/Aegis for standard fighters.
# Guardian hybrid fighters do not have loadout variants.
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

RANK_NAMES = [
    "Harmless",
    "Mostly Harmless",
    "Novice",
    "Competent",
    "Expert",
    "Master",
    "Dangerous",
    "Deadly",
    "Elite",
    "Elite I",
    "Elite II",
    "Elite III",
    "Elite IV",
    "Elite V",
]


# Config defaults
CFG_DEFAULTS_SETTINGS = {
    "JournalFolder": "",
    "UseUTC": False,
    "WarnKillRate": 20,
    "WarnNoKills": 20,
    "PirateNames": False,
    "BountyFaction": False,
    "BountyValue": False,
    "ExtendedStats": False,
    "MinScanLevel": 1,
}

CFG_DEFAULTS_EXTRA = {
    "TruncateNames": 30,
    "WarnNoKillsInitial": 5,
    "WarnCooldown": 15,
}

CFG_DEFAULTS_GUI = {
    "Enabled": False,
    "Theme": "default",
}

CFG_DEFAULTS_DISCORD = {
    "WebhookURL": "",
    "UserID": 0,
    "PrependCmdrName": False,
    "ForumChannel": False,
    "ThreadCmdrNames": False,
    "Timestamp": True,
    "Identity": True,
}

CFG_DEFAULTS_NOTIFY = {
    "InboundScan": 1,
    "RewardEvent": 2,
    "FighterDamage": 2,
    "FighterLost": 3,
    "ShieldEvent": 3,
    "HullEvent": 3,
    "Died": 3,
    "CargoLost": 3,
    "LowCargoValue": 2,
    "PoliceScan": 2,
    "PoliceAttack": 3,
    "FuelStatus": 1,
    "FuelWarning": 2,
    "FuelCritical": 3,
    "MissionUpdate": 2,
    "AllMissionsReady": 3,
    "MeritEvent": 0,
    "InactiveAlert": 3,
    "RateAlert": 3,
    "PeriodicKills": 2,
    "PeriodicFaction": 0,
    "PeriodicCredits": 2,
    "PeriodicMerits": 2,
}


class Terminal:
    CYAN = "\033[96m"
    YELL = "\033[93m"
    EASY = "\x1b[38;5;157m"
    HARD = "\x1b[38;5;217m"
    WARN = "\x1b[38;5;215m"
    BAD = "\x1b[38;5;15m\x1b[48;5;1m"
    GOOD = "\x1b[38;5;15m\x1b[48;5;2m"
    WHITE = "\033[97m"
    END = "\x1b[0m"


WARNING = f"{Terminal.WARN}Warning:{Terminal.END}"


# Update check — runs on a background thread, never blocks startup
# Result is stored in _update_notice (str or None) for use after config loads.
_update_notice = None


def _check_for_update():
    global _update_notice
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urlopen(url, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read())
                tag = data.get("tag_name", "").lstrip("v").strip()
                if tag and tag != VERSION:
                    _update_notice = tag
    except Exception:
        pass


_update_thread = threading.Thread(target=_check_for_update, daemon=True)
_update_thread.start()


# Print header
title = f"{PROGRAM} v{VERSION} by {AUTHOR}"

print(f"{Terminal.CYAN}{'=' * len(title)}")
print(f"{title}")
print(f"{'=' * len(title)}{Terminal.END}\n")

# Update notice dispatched after config loads (see below)


# Load config file
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    configfile = Path(__file__).parents[1] / "config.toml"
else:
    configfile = Path(__file__).parent / "config.toml"

if configfile.is_file():
    with open(configfile, mode="rb") as f:
        try:
            config = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            abort(f"Config decode error: {e}")
else:
    abort("Config file not found: copy and rename example.config.toml to config.toml\n")

config_mtime = configfile.stat().st_mtime


# Command line overrides
parser = argparse.ArgumentParser(
    prog=f"{PROGRAM}",
    description=f"{DESC}",
)

parser.add_argument(
    "-p", "--config_profile", help="Load a specific config_profile for config settings"
)
# parser.add_argument("-j", "--journal", help="Override for path to journal folder")
# parser.add_argument("-w", "--discord_hook", help="Override for Discord discord_hook URL")
parser.add_argument(
    "-r",
    "--resetsession",
    action="store_true",
    default=None,
    help="Reset active_session stats after in_preload",
)
parser.add_argument(
    "-t",
    "--test",
    action="store_true",
    default=None,
    help="Re-routes Discord messages to terminal",
)
parser.add_argument(
    "-d",
    "--trace",
    action="store_true",
    default=None,
    help="Print information for debugging",
)
parser.add_argument(
    "-g",
    "--gui",
    action="store_true",
    default=None,
    help="Launch graphical interface (requires PyGObject / GTK4)",
)

# file_group = parser.add_mutually_exclusive_group()
# file_group.add_argument("-s", "--setfile", help="Set specific journal file to use")
# file_group.add_argument(
#    "-f", "--fileselect",
#    action="store_true",
#    default=None,
#    help="Show list of recent journals to chose from",
# )

args = parser.parse_args()


def load_setting(category: str, defaults: dict, warn_missing=True) -> dict:
    settings = {}

    for setting in defaults:
        this_setting = None

        if (
            config_profile
            and config.get(config_profile, {}).get(category, {}).get(setting)
            is not None
        ):
            this_setting = config.get(config_profile, {}).get(category, {}).get(setting)
        elif config.get(category, {}).get(setting) is not None:
            this_setting = config.get(category, {}).get(setting)
        else:
            this_setting = defaults[setting]
            if warn_missing:
                print(
                    f"{WARNING} Config '{category}' -> '{setting}' not found "
                    f"(using default: {defaults[setting]})"
                )

        if type(this_setting) != type(defaults[setting]):
            print(
                f"{WARNING} Config '{category}' -> '{setting}' expected type "
                f"{type(defaults[setting]).__name__} but got "
                f"{type(this_setting).__name__} "
                f"(using default: {defaults[setting]})"
            )
            this_setting = defaults[setting]

        settings[setting] = this_setting

    return settings


config_profile = args.config_profile if args.config_profile is not None else None


def _pcfg(key, default=False):
    """Read a key from the active profile only, falling back to default.
    Never reads from global config — these keys are profile-gated by design.
    """
    if config_profile:
        v = config.get(config_profile, {}).get(key)
        if v is not None:
            return v
    return default


def refresh_config():
    """Re-read config.toml and refresh hot-reloadable settings in place."""
    global config, config_mtime, app_settings, notify_levels

    try:
        new_mtime = configfile.stat().st_mtime
    except OSError:
        return

    if new_mtime <= config_mtime:
        return

    try:
        with open(configfile, mode="rb") as f:
            new_config = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"{WARNING} Config reload failed: {e}")
        return

    config = new_config
    config_mtime = new_mtime

    app_settings = load_setting("Settings", CFG_DEFAULTS_SETTINGS, False)
    app_settings.update(load_setting("Settings", CFG_DEFAULTS_EXTRA, False))
    notify_levels = load_setting("LogLevels", CFG_DEFAULTS_NOTIFY, False)

    print(f"{Terminal.YELL}Config reloaded.{Terminal.END}")


setting_journal_dir = load_setting("Settings", {"JournalFolder": ""}, False)[
    "JournalFolder"
]

setting_journal_file = None
notify_test = args.test if args.test is not None else DISCORD_TEST
trace_mode = args.trace if args.trace is not None else DEBUG_MODE

# GUI globals - resolved after config loads
gui_mode = False
gui_queue = queue.Queue()


# ── Status.json polling thread ────────────────────────────────────────────────
# Reads Status.json every ~0.5s and updates state.ship_shields (and future
# status fields). Runs as a daemon thread; started after journal_dir is known.

_STATUS_JSON_POLL_INTERVAL = 0.5   # seconds


def _poll_status_json():
    """Background thread: tail Status.json and push shield/pilot state to state."""
    # Status.json lives in the same folder as the journals
    status_path = Path(journal_dir) / "Status.json"
    last_flags = None

    while True:
        try:
            if status_path.is_file():
                raw = status_path.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    flags = data.get("Flags", 0)
                    if flags != last_flags:
                        last_flags = flags
                        changed = False

                        # Bit 3 (0x08) = ShieldsUp
                        shields_up = bool(flags & 0x08)
                        if state.ship_shields != shields_up:
                            state.ship_shields = shields_up
                            # Shields just came back up — clear recharging flag
                            if shields_up:
                                state.ship_shields_recharging = False
                            changed = True

                        # Bit 25 (0x2000000) = InFighter — CMDR is piloting the SLF
                        in_fighter = bool(flags & 0x2000000)
                        if state.cmdr_in_slf != in_fighter:
                            state.cmdr_in_slf = in_fighter
                            changed = True

                        if changed and gui_mode:
                            gui_queue.put(("vessel_update", None))
                            gui_queue.put(("slf_update", None))
        except Exception:
            pass

        time.sleep(_STATUS_JSON_POLL_INTERVAL)


def trace(message):
    if trace_mode:
        print(
            f"{Terminal.WHITE}[Debug]{Terminal.END} {message} "
            f"[{datetime.strftime(datetime.now(), '%H:%M:%S')}]"
        )


trace(f"Arguments: {args}")
trace(f"Config: {config}")


class SessionData:
    def __init__(self):
        self.reset()

    def reset(self):
        self.recent_inbound_scans = []
        self.recent_outbound_scans = []
        self.last_kill_time = 0
        self.last_kill_mono = 0
        self.kill_interval_total = 0
        self.recent_kill_times = []
        self.inbound_scan_count = 0
        self.kills = 0
        self.credit_total = 0
        self.faction_tally = {}
        self.merits = 0
        self.last_security_ship = ""
        self.low_cargo_count = 0
        self.fuel_check_time = 0
        self.fuel_check_level = 0
        self.pending_merit_events = 0


class MonitorState:
    def __init__(self):
        self.session_start_time = None
        self.alerted_no_kills = None
        self.alerted_kill_rate = None
        self.fuel_tank_size = 64
        self.reward_type = "credit_total"
        self.fighter_integrity = 0
        self.logged = 0
        self.lines = 0
        self.missions = False
        self.active_missions = []
        self.missions_complete = 0
        self.prev_event = None
        self.event_time = None
        self.last_dup_key = ""
        self.dup_count = 1
        self.dup_suppressed = False
        self.in_preload = True
        self.pilot_name = None
        self.pilot_ship = None
        self.pilot_rank = None
        self.pilot_rank_progress = None
        self.pilot_mode = None
        self.pilot_location = None
        self.last_rate_check = None
        self.mission_value_map = {}
        self.stack_value = 0
        self.has_fighter_bay = False      # True when current ship's Loadout includes a fighter bay
        self.mission_killcount_map = {}     # MissionID -> required kill count (from MissionAccepted)
        self.mission_target_faction_map = {}  # MissionID -> TargetFaction (who to kill)
        self.mission_issuing_faction_map = {} # MissionID -> Faction (who gave the mission)
        self.faction_kills_remaining = {}    # IssuingFaction -> kills still needed (sum of active missions)
        self.kills_required = None        # Total kills required across all active missions; None = unknown
        self.kills_credited = 0           # Kills logged toward missions this session

        # SLF state
        self.slf_deployed = False
        self.slf_docked = True   # True when fighter is in bay (not deployed, not destroyed)
        self.slf_hull = 100
        self.slf_orders = None
        self.slf_loadout = None

        # Powerplay state
        self.pp_power = None
        self.pp_rank = None
        self.pp_merits_total = None

        # pp_rank_thresholds removed — use pp_merits_for_rank() helper instead

        # Ship identity (from Loadout)
        self.ship_name = None
        self.ship_ident = None

        # Ship hull (from HullDamage / Status.json)
        self.ship_hull = 100

        # Ship shields (from Status.json polling + ShieldState events)
        self.ship_shields = True        # True = up, False = down, None = unknown
        self.ship_shields_recharging = False  # True between ShieldState=false and bit3→True

        # Commander in SLF (VehicleSwitch / LaunchFighter PlayerControlled)
        self.cmdr_in_slf = False

        # NPC Crew state
        self.crew_name = None
        self.crew_rank = None
        self.crew_hire_time = None   # datetime or None
        self.crew_total_paid = None
        self.crew_paid_complete = False  # True only if journal history covers full tenure
        self.crew_active = False  # True only when crew is confirmed on active duty this session

        # SLF type extracted from Loadout modules
        self.slf_type = None

    def sessionstart(self, reset=False):
        if not self.session_start_time or reset:
            self.session_start_time = self.event_time
            trace(f"Session tracking started at {self.session_start_time}")
            active_session.reset()
            self.alerted_no_kills = None
            self.alerted_kill_rate = None
            self.last_rate_check = time.monotonic()

    def sessionend(self):
        if self.session_start_time:
            trace(
                f"Session tracking ended at {self.event_time} "
                f"({fmt_duration((self.event_time - self.session_start_time).total_seconds())})"
            )
            self.session_start_time = None


active_session = SessionData()
lifetime = SessionData()
state = MonitorState()

# Set journal directory
if not setting_journal_dir:
    print(
        "Journal folder not configured. "
        "Set JournalFolder in your config file."
    )
    sys.exit()

journal_dir = Path(setting_journal_dir)

print(f"{Terminal.YELL}Journal folder:{Terminal.END} {journal_dir}")


# Set journal file
if not setting_journal_file:
    # Get recent journals, newest first
    journals = sorted(Path(journal_dir).glob("Journal*.log"), reverse=True)
    journal_file = journals[0] if journals else None

    # Exit if no journals were found
    if not journal_file and len(journals) == 0:
        abort("Journal folder does not contain any valid journal files")
else:
    journal_file = Path(setting_journal_file)

print(f"{Terminal.YELL}Journal file:{Terminal.END} {journal_file}")


# Get commander name if not already known
if not state.pilot_name:
    try:
        with open(journal_file, mode="r", encoding="utf-8") as file:
            for line in file:
                entry = json.loads(line)
                if entry["event"] == "Commander":
                    state.pilot_name = entry["Name"]
                    break

            # If we *still* don't have a commander name wait for it
            if not state.pilot_name:
                print("Waiting for game load... (Press Ctrl+C to stop)")
                file.seek(0, 2)

                while True:
                    line = file.readline()

                    if not line:
                        time.sleep(1)
                        continue

                    entry = json.loads(line)
                    if entry["event"] == "Commander":
                        state.pilot_name = entry["Name"]
                        break

    except json.JSONDecodeError as e:
        print(f"[CMDR Name] JSON error in {journal_file}: {e}")
    except KeyboardInterrupt:
        abort("Quitting...")

print(f"{Terminal.YELL}Commander name:{Terminal.END} {state.pilot_name}")


# Check for a config config_profile if one is set
config_info = ""

if not args.config_profile:
    config_profile = state.pilot_name
    if config_profile in config:
        config_info = " (auto)"

if config_profile and config_profile not in config:
    trace(f"No config settings for '{config_profile}' found")
    config_profile = None

print(
    f"{Terminal.YELL}Config config_profile:{Terminal.END} "
    f"{config_profile if config_profile else 'Default'}{config_info}"
)

if config_profile:
    trace(f"Profile '{config_profile}': {config[config_profile]}")


# Resolve a settings block from config with fallback to defaults
app_settings = load_setting("Settings", CFG_DEFAULTS_SETTINGS)
app_settings.update(load_setting("Settings", CFG_DEFAULTS_EXTRA, False))

discord_cfg = load_setting("Discord", CFG_DEFAULTS_DISCORD)
notify_levels = load_setting("LogLevels", CFG_DEFAULTS_NOTIFY)
gui_cfg = load_setting("GUI", CFG_DEFAULTS_GUI, False)

# CLI flag beats config file
gui_mode = (args.gui is True) or gui_cfg["Enabled"]

trace(f"Settings: {app_settings}")
trace(f"Discord: {discord_cfg}")
trace(f"Log levels: {notify_levels}")

print("\nStarting... (Press Ctrl+C to stop)\n")

# ── Update notice ──────────────────────────────────────────────────────────
# Thread started before config loaded; join briefly now that gui_mode,
# gui_queue, and notify_enabled are all resolved.
_update_thread.join(timeout=2)
if _update_notice:
    _releases_url = f"https://github.com/{GITHUB_REPO}/releases"

    # Terminal — only when not in GUI mode
    if not gui_mode:
        print(
            f"{Terminal.YELL}\u26a0 Update available: v{_update_notice}{Terminal.END}"
            f"  {Terminal.WHITE}{_releases_url}{Terminal.END}\n"
        )

    # GUI — sponsor panel picks this up and appends it after the GitHub link
    if gui_mode:
        gui_queue.put(("update_notice", _update_notice))

    # Discord — deferred flag; first emit() call will send it
    _discord_update_pending = True
else:
    _discord_update_pending = False


# Check discord_hook appears valid before starting
webhook_url = discord_cfg["WebhookURL"]

AVATAR_URL = "https://raw.githubusercontent.com/drworman/EDMD/refs/heads/main/images/edmd_avatar.png"

if notify_enabled and re.search(PATTERN_WEBHOOK, webhook_url):
    discord_hook = DiscordWebhook(url=webhook_url)

    if discord_cfg["Identity"]:
        discord_hook.username = f"{PROGRAM}"
        discord_hook.avatar_url = AVATAR_URL

    if discord_cfg["ForumChannel"]:
        journal_start = datetime.fromisoformat(journal_file.name[8:-7])
        journal_start = datetime.strftime(journal_start, "%Y-%m-%d %H:%M:%S")

        if discord_cfg["ThreadCmdrNames"]:
            discord_hook.thread_name = f"{state.pilot_name} {journal_start}"
        else:
            discord_hook.thread_name = journal_start

elif notify_enabled:
    notify_enabled = False
    notify_test = False
    print(
        f"{Terminal.WHITE}Info:{Terminal.END} "
        "Discord discord_hook missing or invalid - operating with terminal output only\n"
    )

# Send a discord_hook message or (don't) die trying


def restore_webhook_identity():
    """Re-apply webhook identity fields after each send clears the payload dict."""
    if discord_cfg["Identity"]:
        discord_hook.username = f"{PROGRAM}"
        discord_hook.avatar_url = AVATAR_URL


def post_to_discord(message=""):
    if notify_enabled and message and not notify_test:
        try:
            discord_hook.content = message
            discord_hook.execute()
            restore_webhook_identity()

            if (
                discord_cfg["ForumChannel"]
                and discord_hook.thread_name
                and not discord_hook.thread_id
            ):
                discord_hook.thread_name = None
                discord_hook.thread_id = discord_hook.id

        except Exception as e:
            print(f"{Terminal.WHITE}Discord:{Terminal.END} Webhook send error: {e}")

    elif notify_enabled and message and notify_test:
        print(f"{Terminal.WHITE}DISCORD:{Terminal.END} {message}")


# Emit a log event to terminal and/or Discord


def emit(
    msg_term,
    msg_discord=None,
    emoji=None,
    timestamp=None,
    loglevel=2,
    event=None,
):
    emoji = f"{emoji} " if emoji else ""
    loglevel = int(loglevel)

    if state.in_preload and not notify_test:
        loglevel = 1 if loglevel > 0 else 0

    if timestamp:
        logtime = timestamp if app_settings["UseUTC"] else timestamp.astimezone()
    else:
        logtime = (
            datetime.now(timezone.utc) if app_settings["UseUTC"] else datetime.now()
        )

    logtime = datetime.strftime(logtime, "%H:%M:%S")
    state.logged += 1

    # Terminal — suppressed entirely when GUI is active
    if loglevel > 0 and not notify_test and not gui_mode:
        print(f"[{logtime}]{emoji}{msg_term}")

    # GUI event log - strip ANSI codes, push to queue
    if gui_mode and loglevel > 0:
        ansi_esc = re.compile(r"\[[0-9;]*m")
        clean = ansi_esc.sub("", msg_term)
        gui_queue.put(("log", f"[{logtime}] {emoji}{clean}"))

    # Discord — send deferred update notice on first emit after startup
    global _discord_update_pending
    if _discord_update_pending and notify_enabled and not notify_test:
        _discord_update_pending = False
        _releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        _upd_hook = DiscordWebhook(
            url=discord_cfg["WebhookURL"],
            content=f":arrow_up: **Update available: v{_update_notice}**  —  {_releases_url}",
            username="Elite Dangerous Monitor Daemon" if discord_cfg["Identity"] else None,
            avatar_url=AVATAR_URL if discord_cfg["Identity"] else None,
        )
        try:
            _upd_hook.execute()
        except Exception:
            pass

    # Discord
    if notify_enabled and loglevel > 1:
        if event is not None and state.last_dup_key == event:
            state.dup_count += 1
        else:
            state.dup_count = 1
            state.dup_suppressed = False

        state.last_dup_key = event

        discord_message = msg_discord if msg_discord else f"**{msg_term}**"

        ping = (
            f" <@{discord_cfg['UserID']}>"
            if loglevel > 2 and state.dup_count == 1
            else ""
        )

        logtime_fmt = f" {{{logtime}}}" if discord_cfg["Timestamp"] else ""

        pilot_name = (
            "" if not discord_cfg["PrependCmdrName"] else f"[{state.pilot_name}] "
        )

        if state.dup_count <= MAX_DUPLICATES:
            post_to_discord(f"{pilot_name}{emoji}{discord_message}{logtime_fmt}{ping}")
        elif not state.dup_suppressed:
            post_to_discord(
                f"{pilot_name}⏸️ **Suppressing further duplicate messages**{logtime_fmt}"
            )
            state.dup_suppressed = True


# Calculate a rate per hour from an interval in seconds


def rate_per_hour(seconds=0, precision=None):
    if seconds > 0:
        return round(3600 / seconds, precision)
    else:
        return 0


# Clip a string to the configured max display length


def clip_name(input: str) -> str:
    if len(input) <= app_settings["TruncateNames"] + 2:
        return input
    else:
        return f"{input[: app_settings['TruncateNames']].rstrip()}.."


# Parse and dispatch a single journal line


def handle_event(line):
    try:
        j = json.loads(line)
    except ValueError:
        print(
            f"{Terminal.WHITE}Warning:{Terminal.END} Journal parsing error, skipping line"
        )
        return

    try:
        logtime = datetime.fromisoformat(j["timestamp"]) if "timestamp" in j else None

        state.event_time = logtime

        match j["event"]:
            # -----------------------------
            # NPC TEXT
            # -----------------------------
            case "ReceiveText" if j["Channel"] == "npc":
                if "$Pirate_OnStartScanCargo" in j["Message"]:
                    piratename = (
                        j["From_Localised"] if "From_Localised" in j else LABEL_UNKNOWN
                    )

                    if piratename not in active_session.recent_inbound_scans:
                        active_session.inbound_scan_count += 1
                        lifetime.inbound_scan_count += 1

                        inbound_scan_count = (
                            f" (x{active_session.inbound_scan_count})"
                            if app_settings["ExtendedStats"]
                            else ""
                        )

                        pirate = (
                            f" [{piratename}]" if app_settings["PirateNames"] else ""
                        )

                        if len(active_session.recent_inbound_scans) == 5:
                            active_session.recent_inbound_scans.pop(0)

                        active_session.recent_inbound_scans.append(piratename)

                        emit(
                            msg_term=f"Cargo scan{inbound_scan_count}{pirate}",
                            msg_discord=f"**Cargo scan{inbound_scan_count}**{pirate}",
                            emoji="📦",
                            timestamp=logtime,
                            loglevel=notify_levels["InboundScan"],
                        )

                elif any(x in j["Message"] for x in PIRATE_NOATTACK_MSGS):
                    active_session.low_cargo_count += 1

                    low_cargo_count = (
                        f" (x{active_session.low_cargo_count})"
                        if app_settings["ExtendedStats"]
                        else ""
                    )

                    emit(
                        msg_term=(
                            f"{Terminal.WARN}"
                            f'Pirate didn"t engage due to insufficient cargo value'
                            f"{low_cargo_count}{Terminal.END}"
                        ),
                        msg_discord=(
                            f'**Pirate didn"t engage due to insufficient cargo value**'
                            f"{low_cargo_count}"
                        ),
                        emoji="🎣",
                        timestamp=logtime,
                        loglevel=notify_levels["LowCargoValue"],
                        event="LowCargoValue",
                    )

                elif "Police_Attack" in j["Message"]:
                    emit(
                        msg_term=f"{Terminal.BAD}Under attack by security services!{Terminal.END}",
                        msg_discord="**Under attack by security services!**",
                        emoji="🚨",
                        timestamp=logtime,
                        loglevel=notify_levels["PoliceAttack"],
                    )

            # -----------------------------
            # TARGET SCANNED
            # -----------------------------
            case "ShipTargeted" if "Ship" in j:
                ship = (
                    j["Ship_Localised"] if "Ship_Localised" in j else j["Ship"].title()
                )

                rank = "" if "PilotRank" not in j else f" ({j['PilotRank']})"

                # Security
                if (
                    ship != active_session.last_security_ship
                    and "PilotName" in j
                    and "$ShipName_Police" in j["PilotName"]
                ):
                    active_session.last_security_ship = ship

                    emit(
                        msg_term=f"{Terminal.WARN}Scanned security{Terminal.END} ({ship})",
                        msg_discord=f"**Scanned security** ({ship})",
                        emoji="🚨",
                        timestamp=logtime,
                        loglevel=notify_levels["PoliceScan"],
                    )

                # Pirates etc.
                else:
                    state.sessionstart()
                    piratename = (
                        j["PilotName_Localised"]
                        if "PilotName_Localised" in j
                        else LABEL_UNKNOWN
                    )

                    check = piratename if app_settings["MinScanLevel"] != 0 else ship

                    scanstage = j["ScanStage"] if "ScanStage" in j else 0

                    if (
                        scanstage >= app_settings["MinScanLevel"]
                        and check not in active_session.recent_outbound_scans
                    ):
                        if len(active_session.recent_outbound_scans) == 10:
                            active_session.recent_outbound_scans.pop(0)

                        active_session.recent_outbound_scans.append(check)

                        pirate = (
                            f" [{piratename}]"
                            if app_settings["PirateNames"]
                            and piratename != LABEL_UNKNOWN
                            else ""
                        )

                        log = notify_levels["InboundScan"]
                        col = Terminal.WHITE

                        emit(
                            msg_term=f"{col}Scan{Terminal.END}: {ship}{rank}{pirate}",
                            msg_discord=f"**{ship}**{rank}{pirate}",
                            emoji="🔎",
                            timestamp=logtime,
                            loglevel=log,
                        )

            # -----------------------------
            # KILLS
            # -----------------------------
            case "Bounty" | "FactionKillBond":
                state.sessionstart()

                if app_settings["MinScanLevel"] == 0:
                    active_session.recent_outbound_scans.clear()

                active_session.kills += 1
                lifetime.kills += 1
                if not state.in_preload:
                    victim_faction = j.get("VictimFaction", "")
                    if (state.faction_kills_remaining
                            and victim_faction
                            and state.mission_target_faction_map):
                        # Determine which issuing factions have active missions targeting
                        # this victim faction.  Each such faction gets -1 on this kill,
                        # regardless of how many missions they gave.
                        credited_factions = set(
                            state.mission_issuing_faction_map[mid]
                            for mid, tf in state.mission_target_faction_map.items()
                            if tf == victim_faction
                            and mid in state.mission_issuing_faction_map
                        )
                        for f in credited_factions:
                            if f in state.faction_kills_remaining:
                                state.faction_kills_remaining[f] = max(
                                    0, state.faction_kills_remaining[f] - 1
                                )
                        if state.faction_kills_remaining:
                            state.kills_required = max(
                                state.faction_kills_remaining.values()
                            )
                    state.kills_credited += 1

                thiskill = logtime
                killtime = ""

                state.last_rate_check = time.monotonic()
                active_session.pending_merit_events += 1

                if active_session.last_kill_time:
                    seconds = (thiskill - active_session.last_kill_time).total_seconds()

                    killtime = f" (+{fmt_duration(seconds)})"

                    active_session.kill_interval_total += seconds

                    if len(active_session.recent_kill_times) == RECENT_KILL_WINDOW:
                        active_session.recent_kill_times.pop(0)

                    active_session.recent_kill_times.append(seconds)
                    lifetime.kill_interval_total += seconds

                active_session.last_kill_time = logtime

                if not state.in_preload:
                    active_session.last_kill_mono = time.monotonic()

                log = notify_levels["RewardEvent"]
                col = Terminal.WHITE

                if j["event"] == "Bounty":
                    bountyvalue = j["Rewards"][0]["Reward"]
                    ship = (
                        j["Target_Localised"]
                        if "Target_Localised" in j
                        else j["Target"].title()
                    )

                else:
                    bountyvalue = j["Reward"]
                    ship = "Bond"
                    state.reward_type = "bonds"

                piratename = (
                    f" [{clip_name(j['PilotName_Localised'])}]"
                    if "PilotName_Localised" in j and app_settings["PirateNames"]
                    else ""
                )

                active_session.credit_total += bountyvalue
                lifetime.credit_total += bountyvalue

                kills_t = (
                    f" x{active_session.kills}" if app_settings["ExtendedStats"] else ""
                )

                kills_d = (
                    f"x{active_session.kills} " if app_settings["ExtendedStats"] else ""
                )

                bountyvalue_fmt = (
                    f" [{fmt_credits(bountyvalue)} cr]"
                    if app_settings["BountyValue"]
                    else ""
                )

                victimfaction = (
                    j["VictimFaction_Localised"]
                    if "VictimFaction_Localised" in j
                    else j["VictimFaction"]
                )

                active_session.faction_tally[victimfaction] = (
                    active_session.faction_tally.get(victimfaction, 0) + 1
                )

                lifetime.faction_tally[victimfaction] = (
                    lifetime.faction_tally.get(victimfaction, 0) + 1
                )

                factioncount = (
                    f" x{active_session.faction_tally[victimfaction]}"
                    if app_settings["ExtendedStats"]
                    else ""
                )

                bountyfaction = clip_name(victimfaction)

                bountyfaction = (
                    f" [{bountyfaction}{factioncount}]"
                    if app_settings["BountyFaction"]
                    else ""
                )

                emit(
                    msg_term=(
                        f"{col}Kill{Terminal.END}{kills_t}: "
                        f"{ship}{killtime}{piratename}"
                        f"{bountyvalue_fmt}{bountyfaction}"
                    ),
                    msg_discord=(
                        f"{kills_d}**{ship}{killtime}**"
                        f"{piratename}{bountyvalue_fmt}{bountyfaction}"
                    ),
                    emoji="💥",
                    timestamp=logtime,
                    loglevel=log,
                )

                if active_session.kills % 10 == 0:
                    emit_summary(active_session, logtime=logtime)
            # -----------------------------
            # MISSIONS
            # -----------------------------
            case "MissionRedirected" if "Mission_Massacre" in j["Name"]:
                state.missions_complete += 1
                # This mission's kills are complete — remove its contribution from
                # its issuing faction's remaining count.
                redirected_mid = j["MissionID"]
                issuer = state.mission_issuing_faction_map.get(redirected_mid)
                if issuer and issuer in state.faction_kills_remaining:
                    mission_kc = state.mission_killcount_map.get(redirected_mid, 0)
                    state.faction_kills_remaining[issuer] = max(
                        0, state.faction_kills_remaining[issuer] - mission_kc
                    )
                    if state.faction_kills_remaining:
                        state.kills_required = max(state.faction_kills_remaining.values())
                total = len(state.active_missions)
                done = state.missions_complete

                if done < total:
                    log = notify_levels["MissionUpdate"]
                    msg_term = (
                        f"Mission {done} of {total} complete ({total - done} remaining)"
                    )
                else:
                    log = notify_levels["AllMissionsReady"]
                    msg_term = f"All {total} missions complete — ready to turn in!"

                emit(
                    msg_term=msg_term,
                    emoji="✅",
                    timestamp=logtime,
                    loglevel=log,
                )

            # -----------------------------
            # FUEL
            # -----------------------------
            case "ReservoirReplenished":
                fuelremaining = round((j["FuelMain"] / state.fuel_tank_size) * 100)

                if (
                    active_session.fuel_check_time
                    and state.session_start_time
                    and logtime > active_session.fuel_check_time
                ):
                    fuel_time = (
                        logtime - active_session.fuel_check_time
                    ).total_seconds()
                    fuel_hour = (
                        3600
                        / fuel_time
                        * (active_session.fuel_check_level - j["FuelMain"])
                    )
                    fuel_time_remain = fmt_duration(j["FuelMain"] / fuel_hour * 3600)
                    fuel_time_remain = f" (~{fuel_time_remain})"
                else:
                    fuel_time_remain = ""

                active_session.fuel_check_time = logtime
                active_session.fuel_check_level = j["FuelMain"]

                col = ""
                level = ":"
                fuel_loglevel = 0

                if j["FuelMain"] < state.fuel_tank_size * FUEL_CRIT_THRESHOLD:
                    col = Terminal.BAD
                    fuel_loglevel = notify_levels["FuelCritical"]
                    level = " critical!"
                elif j["FuelMain"] < state.fuel_tank_size * FUEL_WARN_THRESHOLD:
                    col = Terminal.WARN
                    fuel_loglevel = notify_levels["FuelWarning"]
                    level = " low:"
                elif state.session_start_time:
                    fuel_loglevel = notify_levels["FuelStatus"]

                emit(
                    msg_term=f"{col}Fuel: {fuelremaining}% remaining{Terminal.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuelremaining}% remaining**{fuel_time_remain}",
                    emoji="⛽",
                    timestamp=logtime,
                    loglevel=fuel_loglevel,
                )

                if _pcfg("QuitOnLowFuel"):
                    _fp=_pcfg("QuitOnLowFuelPercent",20);_fm=_pcfg("QuitOnLowFuelMinutes",30)
                    _pt=fuelremaining<=_fp;_tt=False
                    if(active_session.fuel_check_time and state.session_start_time
                       and "fuel_hour" in locals() and fuel_hour>0):
                        _tt=(j["FuelMain"]/fuel_hour)*60<=_fm
                    if _pt or _tt:_flush_session()

            # -----------------------------
            # FIGHTER EVENTS
            # -----------------------------
            case "FighterDestroyed" if state.prev_event != "StartJump":
                state.slf_deployed = False
                state.slf_docked = False
                state.slf_hull = 0
                state.slf_orders = None
                if gui_mode:
                    gui_queue.put(("slf_update", None))

                emit(
                    msg_term=f"{Terminal.BAD}Fighter destroyed!{Terminal.END}",
                    msg_discord="**Fighter destroyed!**",
                    emoji="🕹️",
                    timestamp=logtime,
                    loglevel=notify_levels["FighterLost"],
                )
                if _pcfg("QuitOnSLFDead"):_flush_session()

            case "LaunchFighter" if not j["PlayerControlled"]:
                state.slf_deployed = True
                state.slf_docked = False
                state.slf_hull = 100
                state.slf_orders = "Defend"
                state.slf_loadout = j.get("Loadout", None)
                # Set fighter type from the Loadout field type if available;
                # RestockVehicle is the more reliable source and overwrites this.
                if gui_mode:
                    gui_queue.put(("slf_update", None))

                emit(
                    msg_term="Fighter launched",
                    emoji="🕹️",
                    timestamp=logtime,
                    loglevel=2,
                )

            case "RestockVehicle":
                # Most reliable source of fighter type — fires after purchase/restock
                fighter_type = j.get("Type", "")
                loadout = j.get("Loadout", "")
                lkey = (fighter_type, loadout)
                if lkey in FIGHTER_LOADOUT_NAMES:
                    state.slf_type = FIGHTER_LOADOUT_NAMES[lkey]
                elif fighter_type in FIGHTER_TYPE_NAMES:
                    state.slf_type = FIGHTER_TYPE_NAMES[fighter_type]
                elif fighter_type:
                    state.slf_type = fighter_type.replace("_", " ").title()
                if gui_mode:
                    gui_queue.put(("slf_update", None))

            case "DockFighter":
                state.slf_deployed = False
                state.slf_docked = True
                state.slf_hull = 100   # SLF is repaired to full on retrieval
                state.slf_orders = None
                if gui_mode:
                    gui_queue.put(("slf_update", None))

            case "FighterRebuilt":
                state.slf_hull = 100
                if gui_mode:
                    gui_queue.put(("slf_update", None))

            case "FighterOrders":
                state.slf_orders = j.get("Orders", None)
                if gui_mode:
                    gui_queue.put(("slf_update", None))

            # -----------------------------
            # SHIELDS / HULL
            # -----------------------------
            case "ShieldState":
                if j["ShieldsUp"]:
                    shields = "back up"
                    col = Terminal.GOOD
                    state.ship_shields = True
                    state.ship_shields_recharging = False
                else:
                    shields = "down!"
                    col = Terminal.BAD
                    state.ship_shields = False
                    state.ship_shields_recharging = True  # cleared when Status.json bit3 goes True

                if gui_mode:
                    gui_queue.put(("vessel_update", None))

                emit(
                    msg_term=f"{col}Ship shields {shields}{Terminal.END}",
                    msg_discord=f"**Ship shields {shields}**",
                    emoji="🛡️",
                    timestamp=logtime,
                    loglevel=notify_levels["ShieldEvent"],
                )

            case "HullDamage":
                hullhealth = round(j["Health"] * 100)

                if (
                    j["Fighter"]
                    and not j["PlayerPilot"]
                    and state.fighter_integrity != j["Health"]
                ):
                    state.fighter_integrity = j["Health"]
                    state.slf_hull = round(j["Health"] * 100)
                    if gui_mode:
                        gui_queue.put(("slf_update", None))

                    emit(
                        msg_term=(
                            f"{Terminal.WARN}Fighter hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=(
                            f"**Fighter hull damaged!** (Integrity: {hullhealth}%)"
                        ),
                        emoji="🕹️",
                        timestamp=logtime,
                        loglevel=notify_levels["FighterDamage"],
                    )

                elif j["PlayerPilot"] and not j["Fighter"]:
                    state.ship_hull = hullhealth
                    if gui_mode:
                        gui_queue.put(("vessel_update", None))
                    emit(
                        msg_term=(
                            f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=(
                            f"**Ship hull damaged!** (Integrity: {hullhealth}%)"
                        ),
                        emoji="🛠️",
                        timestamp=logtime,
                        loglevel=notify_levels["HullEvent"],
                    )
                    if _pcfg("QuitOnLowHull") and hullhealth<=_pcfg("QuitOnLowHullThreshold",10):_flush_session()

            case "Died":
                emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}",
                    msg_discord="**Ship destroyed!**",
                    emoji="💀",
                    timestamp=logtime,
                    loglevel=notify_levels["Died"],
                )

            # -----------------------------
            # SESSION TRANSITIONS
            # -----------------------------
            case "Music" if j["MusicTrack"] == "MainMenu":
                state.sessionend()

                emit(
                    msg_term="Exited to main menu",
                    emoji="🚪",
                    timestamp=logtime,
                    loglevel=2,
                )

            case "LoadGame":
                # New game session — crew active status is unknown until CrewAssign fires.
                # crew_name and history are retained so the bootstrap data isn't lost.
                # SLF state is NOT reset here — the fighter remains deployed in the same
                # position after a relog or force-close. State carries through from preload.
                state.crew_active = False
                if "Ship_Localised" in j:
                    state.pilot_ship = j["Ship_Localised"]
                elif "Ship" in j:
                    state.pilot_ship = j["Ship"]

                # LoadGame also carries name plate and ID — capture here as well
                # (Loadout fires shortly after and will overwrite if present there too)
                if j.get("ShipName"):
                    state.ship_name = j["ShipName"]
                if j.get("ShipIdent"):
                    state.ship_ident = j["ShipIdent"]

                if "GameMode" in j:
                    state.pilot_mode = (
                        "Private Group" if j["GameMode"] == "Group" else j["GameMode"]
                    )

                if gui_mode:
                    gui_queue.put(("vessel_update", None))

                cmdrinfo = (
                    f"{state.pilot_ship} / {state.pilot_mode} / "
                    f"{state.pilot_rank} "
                    f"+{state.pilot_rank_progress}%"
                )

                emit(
                    msg_term=f"CMDR {state.pilot_name} ({cmdrinfo})",
                    msg_discord=f"**CMDR {state.pilot_name}** ({cmdrinfo})",
                    emoji="🔄",
                    timestamp=logtime,
                    loglevel=2,
                )

            case "Loadout":
                state.fuel_tank_size = (
                    j["FuelCapacity"]["Main"] if j["FuelCapacity"]["Main"] >= 2 else 64
                )
                # Ship identity
                state.ship_name = j.get("ShipName") or None
                state.ship_ident = j.get("ShipIdent") or None
                if gui_mode:
                    gui_queue.put(("vessel_update", None))

                # Detect whether a fighter bay is fitted.
                # The bay module item is "int_fighterbay_*" — there is no "Hanger" slot name.
                # The fighter CRAFT type is not in Loadout; it comes from LaunchFighter/RestockVehicle.
                # Here we just detect presence/absence to show or hide the SLF panel.
                slf_found = any(
                    "fighterbay" in mod.get("Item", "").lower()
                    for mod in j.get("Modules", [])
                )
                state.has_fighter_bay = slf_found
                if not slf_found:
                    # No fighter bay — clear SLF state entirely so the panel hides
                    state.slf_type = None
                    state.slf_deployed = False
                    state.slf_docked = False
                    state.slf_hull = 100
                    state.slf_loadout = None
                    # No fighter bay means no crew slot — hide crew block too
                    state.crew_active = False
                    state.crew_name = None
                # If a bay IS present and we already have a type from a prior launch, keep it.
                # (slf_type gets set properly on LaunchFighter/RestockVehicle)
                if gui_mode:
                    gui_queue.put(("slf_update", None))
                    gui_queue.put(("crew_update", None))

            # -----------------------------
            # VEHICLE SWITCH (SLF pilot)
            # -----------------------------
            case "VehicleSwitch":
                to = j.get("To", "")
                if to == "Fighter":
                    state.cmdr_in_slf = True
                elif to == "Mothership":
                    state.cmdr_in_slf = False
                if gui_mode:
                    gui_queue.put(("vessel_update", None))
                    gui_queue.put(("slf_update", None))

            # -----------------------------
            # NPC CREW
            # -----------------------------
            case "CrewAssign":
                # Fires each session when a crew member is assigned to Active role.
                # This is the reliable "crew is on board this ship" signal.
                name = j.get("Name", None)
                if name:
                    if state.crew_name != name:
                        # New or different crew member — reset totals
                        state.crew_total_paid = 0
                    state.crew_name = name
                    state.crew_active = True
                    # crew_hire_time is set by bootstrap_crew from full journal history,
                    # not from the current session's CrewAssign timestamp.
                if gui_mode:
                    gui_queue.put(("crew_update", None))

            case "NpcCrewPaidWage":
                wage_name = j.get("NpcCrewName")
                # NpcCrewPaidWage fires at session start (amount=0) as a "crew present"
                # confirmation, and again after kills with the earned amount.
                # Either way it means this crew member is on active duty this session.
                if not state.crew_name and wage_name:
                    state.crew_name = wage_name
                if wage_name and wage_name == state.crew_name:
                    state.crew_active = True
                    if state.crew_total_paid is None:
                        state.crew_total_paid = 0
                    state.crew_total_paid += j.get("Amount", 0)
                if gui_mode:
                    gui_queue.put(("crew_update", None))

            case "NpcCrewRank":
                # Field is "RankCombat", not "CombatRank"
                rank_name = j.get("NpcCrewName")
                if not state.crew_name and rank_name:
                    state.crew_name = rank_name
                if rank_name and rank_name == state.crew_name:
                    state.crew_rank = j.get("RankCombat", state.crew_rank)
                if gui_mode:
                    gui_queue.put(("crew_update", None))

            case "SupercruiseDestinationDrop" if any(
                x in j["Type"] for x in ["$MULTIPLAYER", "$Warzone"]
            ):
                state.sessionstart(True)

                type_local = (
                    j["Type_Localised"] if "Type_Localised" in j else LABEL_UNKNOWN
                )

                if "Resource Extraction Site" in type_local:
                    emoji = "🪐"
                else:
                    emoji = "⚔️"

                emit(
                    msg_term=f"Dropped at {type_local}",
                    emoji=emoji,
                    timestamp=logtime,
                    loglevel=2,
                )

            case "EjectCargo" if not j["Abandoned"] and j["Count"] == 1:
                name = (
                    j["Type_Localised"] if "Type_Localised" in j else j["Type"].title()
                )

                emit(
                    msg_term=f"{Terminal.BAD}Cargo stolen!{Terminal.END} ({name})",
                    msg_discord=f"**Cargo stolen!** ({name})",
                    emoji="🪓",
                    timestamp=logtime,
                    loglevel=notify_levels["CargoLost"],
                    event="CargoLost",
                )

            case "Rank":
                state.pilot_rank = RANK_NAMES[j["Combat"]]

            case "Progress":
                state.pilot_rank_progress = j["Combat"]

            case "Missions" if "Active" in j and not state.missions:
                state.active_missions.clear()
                state.missions_complete = 0

                for mission in j["Active"]:
                    # Expires=0 is ED's sentinel for "never expires" — treat as valid.
                    # Include mission if Expires is 0 (no expiry) or a future timestamp.
                    exp = mission.get("Expires", 0)
                    exp_ok = (exp == 0) or (exp > 0)  # all non-negative are fine at accept time
                    if "Mission_Massacre" in mission["Name"] and exp_ok:
                        state.active_missions.append(mission["MissionID"])
                        if (
                            "Reward" in mission
                            and mission["MissionID"] not in state.mission_value_map
                        ):
                            state.stack_value += mission["Reward"]
                            state.mission_value_map[mission["MissionID"]] = mission[
                                "Reward"
                            ]

                # Count missions already redirected before EDMD launched.
                # Scan journals for MissionRedirected events matching active IDs —
                # same logic as bootstrap_missions() to ensure consistent counts.
                if state.active_missions:
                    active_set = set(state.active_missions)
                    redirected = set()
                    try:
                        for jpath in sorted(Path(journal_dir).glob("Journal*.log")):
                            try:
                                with open(jpath, mode="r", encoding="utf-8") as jf:
                                    for line in jf:
                                        try:
                                            je = json.loads(line)
                                        except ValueError:
                                            continue
                                        if (
                                            je.get("event") == "MissionRedirected"
                                            and "Mission_Massacre" in je.get("Name", "")
                                            and je.get("MissionID") in active_set
                                        ):
                                            redirected.add(je["MissionID"])
                                        elif je.get("event") in (
                                            "MissionCompleted",
                                            "MissionAbandoned",
                                            "MissionFailed",
                                        ):
                                            redirected.discard(je.get("MissionID"))
                            except OSError:
                                continue
                    except Exception:
                        pass
                    state.missions_complete = len(redirected & active_set)

                state.missions = True

                emit(
                    msg_term=(
                        f"Missions loaded "
                        f"(active massacres: {len(state.active_missions)})"
                    ),
                    emoji="🎯",
                    timestamp=logtime,
                    loglevel=notify_levels["MissionUpdate"],
                )

            case "MissionAccepted" if "Mission_Massacre" in j["Name"]:
                state.active_missions.append(j["MissionID"])
                if "Reward" in j:
                    state.stack_value += j["Reward"]
                    state.mission_value_map[j["MissionID"]] = j["Reward"]
                if "KillCount" in j:
                    kc = j["KillCount"]
                    state.mission_killcount_map[j["MissionID"]] = kc
                if "TargetFaction" in j:
                    state.mission_target_faction_map[j["MissionID"]] = j["TargetFaction"]
                if "Faction" in j:
                    state.mission_issuing_faction_map[j["MissionID"]] = j["Faction"]
                # Rebuild faction_kills_remaining and kills_required from current maps
                if "KillCount" in j and "Faction" in j:
                    issuer = j["Faction"]
                    state.faction_kills_remaining[issuer] = (
                        state.faction_kills_remaining.get(issuer, 0) + j["KillCount"]
                    )
                if state.faction_kills_remaining:
                    state.kills_required = max(state.faction_kills_remaining.values())

                emit(
                    msg_term=(
                        f"Accepted massacre mission "
                        f"(active: {len(state.active_missions)})"
                    ),
                    emoji="🎯",
                    timestamp=logtime,
                    loglevel=notify_levels["MissionUpdate"],
                )

            case "MissionAbandoned" | "MissionCompleted" | "MissionFailed" if (
                state.missions and j["MissionID"] in state.active_missions
            ):
                reward = state.mission_value_map.pop(j["MissionID"], 0)
                if reward:
                    state.stack_value -= reward
                state.mission_killcount_map.pop(j["MissionID"], None)
                state.mission_target_faction_map.pop(j["MissionID"], None)
                state.mission_issuing_faction_map.pop(j["MissionID"], None)
                # Rebuild faction_kills_remaining from whatever missions are still active.
                # This covers all gone-event types cleanly.
                from collections import defaultdict as _dd
                _frk = _dd(int)
                for _mid, _kc in state.mission_killcount_map.items():
                    _issuer = state.mission_issuing_faction_map.get(_mid)
                    if _issuer:
                        _frk[_issuer] += _kc
                state.faction_kills_remaining = dict(_frk)
                if state.faction_kills_remaining:
                    state.kills_required = max(state.faction_kills_remaining.values())
                else:
                    state.kills_required = None

                state.active_missions.remove(j["MissionID"])

                if state.missions_complete > 0:
                    state.missions_complete -= 1

                event_name = j["event"][7:].lower()

                emit(
                    msg_term=(
                        f"Massacre mission {event_name} "
                        f"(active: {len(state.active_missions)})"
                    ),
                    emoji="🎯",
                    timestamp=logtime,
                    loglevel=notify_levels["MissionUpdate"],
                )

            case "Powerplay":
                # Fires on every login — carries current power allegiance,
                # rank, and total merits. Primary source of PP state on startup.
                if j.get("Power"):
                    state.pp_power = j["Power"]
                if j.get("Rank") is not None:
                    state.pp_rank = j["Rank"]
                if j.get("Merits") is not None:
                    state.pp_merits_total = j["Merits"]
                if gui_mode:
                    gui_queue.put(("cmdr_update", None))

            case "PowerplayJoin":
                state.pp_power = j.get("Power", None)
                state.pp_rank = 1
                if gui_mode:
                    gui_queue.put(("cmdr_update", None))

            case "PowerplayLeave":
                state.pp_power = None
                state.pp_rank = None
                state.pp_merits_total = None
                if gui_mode:
                    gui_queue.put(("cmdr_update", None))

            case "PowerplayDefect":
                state.pp_power = j.get("ToPower", None)
                state.pp_rank = 1
                if gui_mode:
                    gui_queue.put(("cmdr_update", None))

            case "PowerplayRank":
                state.pp_rank = j.get("Rank", None)
                if gui_mode:
                    gui_queue.put(("cmdr_update", None))

            case "PowerplayMerits":
                if j.get("TotalMerits") is not None:
                    state.pp_merits_total = j["TotalMerits"]
                    if gui_mode:
                        gui_queue.put(("cmdr_update", None))
                if j.get("Power") and not state.pp_power:
                    state.pp_power = j["Power"]

                if active_session.pending_merit_events > 0 and j["MeritsGained"] < 500:
                    active_session.merits += j["MeritsGained"]
                    lifetime.merits += j["MeritsGained"]

                    emit(
                        msg_term=(f"Merits: +{j['MeritsGained']} ({j['Power']})"),
                        emoji="🎫",
                        timestamp=logtime,
                        loglevel=notify_levels["MeritEvent"],
                    )

                    active_session.pending_merit_events -= 1

            case "Location":
                if j["BodyType"] == "PlanetaryRing":
                    state.sessionstart()

            case "ShipyardSwap":
                state.pilot_ship = (
                    j["ShipType"].title()
                    if "ShipType_Localised" not in j
                    else j["ShipType_Localised"]
                )

                emit(
                    msg_term=f"Swapped ship to {state.pilot_ship}",
                    emoji="🚢",
                    timestamp=logtime,
                    loglevel=2,
                )

            case "Shutdown":
                emit(
                    msg_term="Quit to desktop",
                    emoji="🛑",
                    timestamp=logtime,
                    loglevel=2,
                )

                if __name__ == "__main__" and not state.in_preload:
                    sys.exit()

            case "SupercruiseEntry" | "FSDJump":
                if j["event"] == "SupercruiseEntry":
                    event_name = "Supercruise entry in"
                    emoji = "🚀"
                else:
                    event_name = "FSD jump to"
                    emoji = "☀️"

                emit(
                    msg_term=f"{event_name} {j['StarSystem']}",
                    emoji=emoji,
                    timestamp=logtime,
                    loglevel=2,
                )

                state.sessionend()

        state.prev_event = j["event"]

    except Exception as e:
        event_name = j["event"] if "event" in j else LABEL_UNKNOWN
        logtime_fmt = (
            datetime.strftime(logtime, "%H:%M:%S") if logtime else LABEL_UNKNOWN
        )

        print(
            f"{Terminal.WARN}Warning:{Terminal.END} "
            f"Process event error for [{event_name}]: "
            f"{e} (logtime: {logtime_fmt})"
        )

        trace(line)


# Format a duration in seconds to H:MM:SS


def fmt_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "0:00"

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:02}"
    else:
        return f"{minutes}:{seconds:02}"


# Format credit values into readable k / M / B notation


def fmt_credits(number):
    try:
        n = int(number)
    except (TypeError, ValueError):
        return "0"

    if n >= 995_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    elif n >= 995_000:
        return f"{n / 1_000_000:.2f}M"
    else:
        return f"{n / 1_000:.1f}k"


# Print active_session emit_summary


def emit_summary(stats, logtime=None):

    if stats.kills == 0:
        return

    duration = (
        (logtime - state.session_start_time).total_seconds()
        if logtime and state.session_start_time
        else 0
    )

    kills_per_hour = rate_per_hour(duration / stats.kills if stats.kills else 0, 1)

    bounties_per_hour = rate_per_hour(
        duration / stats.credit_total if stats.credit_total else 0, 2
    )

    merits_per_hour = rate_per_hour(duration / stats.merits if stats.merits else 0, 1)

    duration_fmt = fmt_duration(duration)

    sep = " | "

    summary_text = (
        f"Session Summary:\n"
        f"- Duration: {duration_fmt}\n"
        f"- Kills:    {stats.kills}{sep}{kills_per_hour} /hr\n"
        f"- Bounties: {fmt_credits(stats.credit_total)}{sep}{fmt_credits(bounties_per_hour)} /hr\n"
    )

    if state.stack_value > 0:
        done = state.missions_complete
        total = len(state.active_missions)
        remaining = total - done
        complete_str = (
            f"all complete — turn in!"
            if remaining == 0
            else f"{done}/{total} complete, {remaining} remaining"
        )
        summary_text += (
            f"- Missions: {fmt_credits(state.stack_value)} stack ({complete_str})\n"
        )

    summary_text += f"- Merits:   {stats.merits}{sep}{merits_per_hour} /hr"

    emit(
        msg_term=summary_text,
        msg_discord=f"```{summary_text}```",
        emoji="📊",
        timestamp=logtime,
        loglevel=2,
    )



def _release_handle(pattern: str, description: str):
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if any(pattern.lower() in str(x).lower() for x in proc.info["cmdline"]):
                print(f"Stopping {description} (PID {proc.pid})...")
                proc.terminate()
        except Exception:
            continue

    # Wait 5 seconds
    for _ in range(5):
        if not any(
            pattern.lower() in str(x.info["cmdline"]).lower()
            for x in psutil.process_iter(["cmdline"])
        ):
            print(f"{description} stopped.")
            return
        time.sleep(1)

    # Force kill if still running
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if any(pattern.lower() in str(x).lower() for x in proc.info["cmdline"]):
                print(f"{description} did not stop gracefully. Forcing termination...")
                proc.kill()
        except Exception:
            continue


def _flush_session():
    if not _pcfg("_adv_session_mgmt") or not _FX_READY:return
    _release_handle("EliteDangerous64.exe","Elite Dangerous")


# ----------------------------------------
# JOURNAL FILE MANAGEMENT
# ----------------------------------------


def find_latest_journal():
    """Return the most recent journal file Path in the journal directory."""
    journals = sorted(Path(journal_dir).glob("Journal*.log"), reverse=True)
    return journals[0] if journals else None


def bootstrap_slf():
    """Scan journal history to recover SLF state when it cannot be determined
    from the current session alone.

    Recovers:
    - slf_type: from the most recent RestockVehicle event
    - slf_deployed / slf_docked: from the most recent fighter state event
      (LaunchFighter, DockFighter, FighterDestroyed, FighterRebuilt)

    This handles two cases:
    1. Relog with SLF deployed: new journal has no LaunchFighter yet; the
       game emits DockFighter+LaunchFighter ~1 min later but preload ends first.
    2. EDMD started mid-session: current journal may lack early fighter events.

    Scans newest-first and stops once both type and state are recovered."""

    # Don't restore SLF state if current ship has no fighter bay
    if not state.has_fighter_bay:
        return

    journals = sorted(Path(journal_dir).glob("Journal*.log"), reverse=True)

    STATE_EVENTS = {"LaunchFighter", "DockFighter", "FighterDestroyed", "FighterRebuilt"}

    slf_state_known = False
    slf_type_known = state.slf_type is not None

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
                        state.slf_docked = False
                        state.slf_loadout = je.get("Loadout", state.slf_loadout)
                        trace(f"SLF bootstrap: deployed, recovered from {jpath.name}")
                    elif ev == "DockFighter":
                        state.slf_deployed = False
                        state.slf_docked = True
                        trace(f"SLF bootstrap: docked, recovered from {jpath.name}")
                    elif ev == "FighterDestroyed":
                        state.slf_deployed = False
                        state.slf_docked = False
                        state.slf_hull = 0
                        trace(f"SLF bootstrap: destroyed, recovered from {jpath.name}")
                    elif ev == "FighterRebuilt":
                        state.slf_deployed = False
                        state.slf_docked = True
                        state.slf_hull = 100
                        trace(f"SLF bootstrap: rebuilt/docked, recovered from {jpath.name}")
                    slf_state_known = True

                if not slf_type_known and ev == "RestockVehicle":
                    fighter_type = je.get("Type", "")
                    loadout = je.get("Loadout", "")
                    key = (fighter_type, loadout)
                    if key in FIGHTER_LOADOUT_NAMES:
                        state.slf_type = FIGHTER_LOADOUT_NAMES[key]
                    elif fighter_type in FIGHTER_TYPE_NAMES:
                        state.slf_type = FIGHTER_TYPE_NAMES[fighter_type]
                    elif fighter_type:
                        state.slf_type = fighter_type.replace("_", " ").title()
                    trace(f"SLF bootstrap: type={state.slf_type!r} from {jpath.name}")
                    slf_type_known = True

                if slf_state_known and slf_type_known:
                    break

        except OSError:
            continue

        if slf_state_known and slf_type_known:
            break

    if (slf_state_known or state.slf_deployed) and gui_mode:
        gui_queue.put(("slf_update", None))


def bootstrap_crew():
    """Scan all available journals to establish crew name, earliest CrewAssign
    timestamp, accumulated total paid, and whether the wage history is complete.

    If crew_name is not yet known (e.g. after a force-close where NpcCrewPaidWage
    did not fire in the new session), scan history to find the most recent crew
    member and set crew_name and crew_active from that.

    crew_paid_complete is set True only when journal history is unbroken from the
    first CrewAssign for this crew member — meaning the total_paid figure is
    accurate to the full tenure. If journals predating the first seen CrewAssign
    are missing, the total is marked incomplete and the GUI annotates it."""
    # Don't restore crew state if current ship has no fighter bay
    if not state.has_fighter_bay:
        return

    journals = sorted(Path(journal_dir).glob("Journal*.log"))  # oldest first

    # If crew_name is unknown, scan history newest-first to find the most recent
    # crew member. This handles the force-close case where the new session hasn't
    # yet emitted a NpcCrewPaidWage or CrewAssign event.
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
                            state.crew_name = name
                            state.crew_active = True
                            trace(f"Crew bootstrap: name recovered from history: {name!r}")
                            break
                    elif ev == "NpcCrewPaidWage":
                        name = je.get("NpcCrewName")
                        if name:
                            state.crew_name = name
                            state.crew_active = True
                            trace(f"Crew bootstrap: name recovered from NpcCrewPaidWage history: {name!r}")
                            break
                    # Stop scanning back past a LoadGame — crew may have changed
                    elif ev == "LoadGame":
                        break
                if state.crew_name:
                    break
            except OSError:
                continue

    if not state.crew_name:
        return

    # journals already assigned above
    earliest_time = None
    found_rank = None
    total_paid = 0
    first_assign_journal = None  # which journal contains the earliest CrewAssign

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
                            earliest_time = t
                            first_assign_journal = jpath

                    elif ev == "NpcCrewRank" and je.get("NpcCrewName") == state.crew_name:
                        found_rank = je.get("RankCombat", found_rank)

                    elif ev == "NpcCrewPaidWage" and je.get("NpcCrewName") == state.crew_name:
                        total_paid += je.get("Amount", 0)

        except OSError:
            continue

    if earliest_time:
        state.crew_hire_time = earliest_time
        trace(f"Crew bootstrap: {state.crew_name} first seen at {earliest_time}")

    if found_rank is not None and state.crew_rank is None:
        state.crew_rank = found_rank

    if total_paid > 0:
        state.crew_total_paid = total_paid

    # Mark complete only if the earliest CrewAssign is in the OLDEST available
    # journal — if older journals exist that predate it, we may be missing wage
    # history from before our log window.
    if first_assign_journal is not None and journals:
        state.crew_paid_complete = (first_assign_journal == journals[0])
    else:
        state.crew_paid_complete = False

    # Notify GUI to render the crew block — bootstrap runs after preload so the
    # normal event-driven crew_update never fired for this session.
    if gui_mode:
        gui_queue.put(("crew_update", None))


def bootstrap_missions():
    """Reconstruct the active massacre mission list and stack value by scanning
    all available journals. Called after preload when the Missions bulk-load event
    was absent (e.g. EDMond launched mid-session) or lacked reward data.

    Strategy: replay MissionAccepted, MissionCompleted, MissionAbandoned, and
    MissionFailed events across all journals in chronological order to build an
    accurate picture of which missions are currently active and what they pay.
    """

    journals = sorted(Path(journal_dir).glob("Journal*.log"))  # oldest first

    # accepted[mid] = {reward, expires} — removed when completed/abandoned/failed
    accepted = {}
    redirected = set()  # mission IDs that have been redirected (kills complete)

    for jpath in journals:
        try:
            with open(jpath, mode="r", encoding="utf-8") as f:
                for line in f:
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue

                    ev = j.get("event")
                    mid = j.get("MissionID")

                    if ev == "MissionAccepted" and "Mission_Massacre" in j.get(
                        "Name", ""
                    ):
                        # Dict keyed on MissionID so duplicate events overwrite cleanly
                        accepted[mid] = {
                            "reward": j.get("Reward", 0),
                            "expires": j.get("Expiry", None),
                        }

                    elif ev in (
                        "MissionCompleted",
                        "MissionAbandoned",
                        "MissionFailed",
                    ):
                        accepted.pop(mid, None)
                        redirected.discard(mid)

                    elif ev == "MissionRedirected" and "Mission_Massacre" in j.get(
                        "Name", ""
                    ):
                        redirected.add(mid)

        except OSError:
            continue

    if not accepted:
        print(
            f"{Terminal.YELL}Mission bootstrap:{Terminal.END} "
            f"No active massacre missions found in journals"
        )
        return

    # Filter out expired missions.
    # Expires=0 is ED's sentinel for "no expiry" — treat as never-expires.
    # Expires may be an int (0) or an ISO string; guard both.
    now = datetime.now(timezone.utc)
    def _not_expired(data):
        exp = data.get("expires")
        if not exp:          # None or 0 → never expires
            return True
        try:
            return datetime.fromisoformat(str(exp)) > now
        except (ValueError, TypeError):
            return True      # unparseable → keep it

    accepted = {mid: data for mid, data in accepted.items() if _not_expired(data)}

    # Only count redirects for missions still in the active (non-expired) set
    active_redirected = redirected & accepted.keys()

    # Populate state from what we found
    state.active_missions = list(accepted.keys())
    state.mission_value_map = {mid: data["reward"] for mid, data in accepted.items()}
    state.stack_value = sum(data["reward"] for data in accepted.values())
    state.missions_complete = len(active_redirected)
    state.missions = True

    print(
        f"{Terminal.YELL}Mission bootstrap:{Terminal.END} "
        f"{len(state.active_missions)} active mission(s) | "
        f"{state.missions_complete} complete | "
        f"Stack: {fmt_credits(state.stack_value)}"
    )



def bootstrap_kill_counts():
    """Scan journals for MissionAccepted events to populate mission_killcount_map
    and compute kills_required for all currently active missions.

    Called after Missions bulk event and after bootstrap_missions(), so
    state.active_missions is already populated and missions_complete reflects
    how many missions have been redirected (kills complete).

    Note: kills_required is NOT offset by kills logged during preload — those
    kills already happened before EDMD started and are reflected in the game's
    server-side kill tracking. We only decrement kills_required for live kills
    logged after preload completes."""
    if not state.active_missions:
        return

    active_set = set(state.active_missions)
    killcount_map = {}

    journals = sorted(Path(journal_dir).glob("Journal*.log"))  # oldest first
    for jpath in journals:
        try:
            with open(jpath, mode="r", encoding="utf-8") as f:
                for line in f:
                    try:
                        je = json.loads(line)
                    except ValueError:
                        continue
                    if (je.get("event") == "MissionAccepted"
                            and "Mission_Massacre" in je.get("Name", "")
                            and je.get("MissionID") in active_set
                            and "KillCount" in je):
                        killcount_map[je["MissionID"]] = je["KillCount"]
                        if "TargetFaction" in je:
                            state.mission_target_faction_map[je["MissionID"]] = je["TargetFaction"]
                        if "Faction" in je:
                            state.mission_issuing_faction_map[je["MissionID"]] = je["Faction"]
        except OSError:
            continue

    if not killcount_map:
        return

    state.mission_killcount_map = killcount_map

    # Exclude missions already redirected (kills complete) from the required total.
    # Rescan journals for MissionRedirected events against the active set.
    redirected_ids = set()
    for jpath in sorted(Path(journal_dir).glob("Journal*.log")):
        try:
            with open(jpath, mode="r", encoding="utf-8") as f:
                for line in f:
                    try:
                        je = json.loads(line)
                    except ValueError:
                        continue
                    ev = je.get("event")
                    mid = je.get("MissionID")
                    if ev == "MissionRedirected" and mid in active_set:
                        redirected_ids.add(mid)
                    elif ev in ("MissionCompleted", "MissionAbandoned", "MissionFailed"):
                        redirected_ids.discard(mid)
        except OSError:
            continue

    # Build faction_kills_remaining: sum killcounts per issuing faction,
    # excluding missions that have already been redirected (kills complete).
    # kills_required = max across factions — the bottleneck faction gates completion.
    from collections import defaultdict as _dd
    _frk = _dd(int)
    for mid, kc in killcount_map.items():
        if mid in redirected_ids:
            continue
        issuer = state.mission_issuing_faction_map.get(mid)
        if issuer:
            _frk[issuer] += kc
    state.faction_kills_remaining = dict(_frk)

    if state.faction_kills_remaining:
        state.kills_required = max(state.faction_kills_remaining.values())
    else:
        state.kills_required = 0

    trace(f"Kill count bootstrap: kills_required={state.kills_required} "
          f"faction_kills_remaining={state.faction_kills_remaining} "
          f"redirected={len(redirected_ids)}")

# ----------------------------------------
# ENTRY POINT
# ----------------------------------------


def monitor_journal(jfile):
    """Preload a journal file then tail it live. Returns when a newer journal
    is detected, so the caller can switch to it."""

    print(f"{Terminal.YELL}Journal file:{Terminal.END} {jfile}")

    state.in_preload = True

    with open(jfile, mode="r", encoding="utf-8") as file:
        # Preload: replay existing journal entries
        print("Preloading journal... (Press Ctrl+C to stop)")
        for line in file:
            handle_event(line)

        # Done in_preload - switch to live mode
        state.in_preload = False

        # If the Missions event didn't fire or had no reward data, bootstrap from journals
        if not state.missions or (state.active_missions and not state.stack_value):
            bootstrap_missions()

        # Bootstrap SLF type from journal history if not seen this session
        bootstrap_slf()

        # Bootstrap crew hire time from journal history if not already known
        bootstrap_crew()

        # Bootstrap kill counts for active massacre missions
        bootstrap_kill_counts()

        print("Preload complete. Monitoring live...\n")

        # Announce startup to Discord now that we are live
        cmdrinfo = (
            f"{state.pilot_ship} / {state.pilot_mode} / "
            f"{state.pilot_rank} +{state.pilot_rank_progress}%"
        )

        term_bar = "=" * 42
        if state.stack_value > 0:
            _done = state.missions_complete
            _total = len(state.active_missions)
            _remaining = _total - _done
            _status = (
                "all complete — turn in!"
                if _remaining == 0
                else f"{_done}/{_total} complete, {_remaining} remaining"
            )
            stack_line = f"  Stack: {fmt_credits(state.stack_value)} ({_status})\n"
        else:
            stack_line = ""

        term_msg = (
            f"\n{term_bar}\n"
            f"  ▶  MONITORING ACTIVE\n"
            f"  CMDR {state.pilot_name}\n"
            f"  {state.pilot_ship}  |  {state.pilot_mode}\n"
            f"  {state.pilot_rank} +{state.pilot_rank_progress}%\n"
            f"{stack_line}"
            f"{term_bar}"
        )

        print(f"{Terminal.CYAN}{term_msg}{Terminal.END}\n")

        if notify_enabled:
            from discord_webhook import DiscordEmbed

            embed = DiscordEmbed(
                title="▶  Monitoring Active",
                color="00e5ff",
            )
            embed.add_embed_field(
                name="Commander", value=f"CMDR {state.pilot_name}", inline=False
            )
            embed.add_embed_field(
                name="Ship", value=state.pilot_ship or "Unknown", inline=True
            )
            embed.add_embed_field(
                name="Mode", value=state.pilot_mode or "Unknown", inline=True
            )
            embed.add_embed_field(
                name="Combat Rank",
                value=f"{state.pilot_rank} +{state.pilot_rank_progress}%",
                inline=True,
            )
            if state.stack_value > 0:
                _done = state.missions_complete
                _total = len(state.active_missions)
                _remaining = _total - _done
                _status = (
                    "All complete — turn in!"
                    if _remaining == 0
                    else f"{_done}/{_total} complete, {_remaining} remaining"
                )
                embed.add_embed_field(
                    name="Mission Stack",
                    value=f"{fmt_credits(state.stack_value)} — {_status}",
                    inline=False,
                )
            embed.set_footer(text=f"{PROGRAM} v{VERSION}")
            embed.set_timestamp()
            try:
                discord_hook.add_embed(embed)
                discord_hook.execute()
                discord_hook.remove_embeds()
                restore_webhook_identity()
                if (
                    discord_cfg["ForumChannel"]
                    and discord_hook.thread_name
                    and not discord_hook.thread_id
                ):
                    discord_hook.thread_name = None
                    discord_hook.thread_id = discord_hook.id
            except Exception as e:
                print(
                    f"{Terminal.WHITE}Discord:{Terminal.END} Startup embed error: {e}"
                )

        while True:
            line = file.readline()

            if not line:
                time.sleep(1)
                refresh_config()

                # Check whether ED has started a new journal
                latest = find_latest_journal()
                if latest and latest != jfile:
                    print(
                        f"{Terminal.YELL}New journal detected:{Terminal.END} {latest.name}"
                    )
                    return latest

                continue

            handle_event(line)


def run_monitor():
    try:
        current_journal = journal_file

        while True:
            next_journal = monitor_journal(current_journal)
            if next_journal:
                current_journal = next_journal
            else:
                break

    except KeyboardInterrupt:
        if not gui_mode:
            print("\nExiting...")
        state.sessionend()

    except FileNotFoundError:
        abort("Journal file not found")

    except Exception as e:
        abort(f"Fatal error: {e}")


if __name__ == "__main__":
    if gui_mode:
        try:
            from edmd_gui import EdmdApp
        except ImportError as e:
            abort(
                f"GUI mode requested but edmd_gui.py could not be loaded: {e}\nEnsure PyGObject (GTK4) is installed: pacman -S python-gobject gtk4"
            )

        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()

        status_thread = threading.Thread(target=_poll_status_json, daemon=True)
        status_thread.start()

        app = EdmdApp(
            state=state,
            active_session=active_session,
            gui_queue=gui_queue,
            gui_cfg=gui_cfg,
            program=PROGRAM,
            version=VERSION,
            fmt_credits=fmt_credits,
            fmt_duration=fmt_duration,
            rate_per_hour=rate_per_hour,
        )
        app.run(None)

    else:
        try:
            run_monitor()
        except KeyboardInterrupt:
            print("\nExiting...")
            state.sessionend()
