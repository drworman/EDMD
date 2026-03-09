"""
core/config.py — Configuration loading, defaults, profile resolution,
                 and hot-reload.

Depends only on core.state (for EDMD_DATA_DIR).
Does not import from emit, journal, or gui.
"""

import sys
import tomllib
from pathlib import Path

from core.state import EDMD_DATA_DIR


# ── Minimal terminal colour for pre-emit warnings ────────────────────────────
# emit.py imports config, so we can't import Terminal from there.
# Only _WARNING is needed here; full Terminal lives in core.emit.

class _T:
    WARN = "\x1b[38;5;215m"
    END  = "\x1b[0m"

_WARNING = f"{_T.WARN}Warning:{_T.END}"


# ── Config defaults ───────────────────────────────────────────────────────────

CFG_DEFAULTS_SETTINGS = {
    "JournalFolder":  "",
    "UseUTC":         False,
    "WarnKillRate":   20,
    "WarnNoKills":    20,
    "PirateNames":    False,
    "BountyFaction":  False,
    "BountyValue":    False,
    "ExtendedStats":  False,
    "MinScanLevel":   1,
}

CFG_DEFAULTS_EXTRA = {
    "TruncateNames":      30,
    "WarnNoKillsInitial": 5,
    "WarnCooldown":       15,
    "FullStackSize":      20,
}

CFG_DEFAULTS_GUI = {
    "Enabled": False,
    "Theme":   "default",
}

CFG_DEFAULTS_DISCORD = {
    "WebhookURL":      "",
    "UserID":          0,
    "PrependCmdrName": False,
    "ForumChannel":    False,
    "ThreadCmdrNames": False,
    "Timestamp":       True,
    "Identity":        True,
}

CFG_DEFAULTS_EDDN = {
    "Enabled":    False,
    "UploaderID": "",
    "TestMode":   False,
}

CFG_DEFAULTS_EDSM = {
    "Enabled":       False,
    "CommanderName": "",
    "ApiKey":        "",
}

CFG_DEFAULTS_EDASTRO = {
    "Enabled":             False,
    "UploadCarrierEvents": False,
}


CFG_DEFAULTS_NOTIFY = {
    "InboundScan":      1,
    "RewardEvent":      2,
    "FighterDamage":    2,
    "FighterLost":      3,
    "ShieldEvent":      3,
    "HullEvent":        3,
    "Died":             3,
    "CargoLost":        3,
    "LowCargoValue":    2,
    "PoliceScan":       2,
    "PoliceAttack":     3,
    "FuelStatus":       1,
    "FuelWarning":      2,
    "FuelCritical":     3,
    "MissionUpdate":    2,
    "AllMissionsReady": 3,
    "MeritEvent":       0,
    "InactiveAlert":    3,
    "RateAlert":        3,
    "PeriodicKills":    2,
    "PeriodicFaction":  0,
    "PeriodicCredits":  2,
    "PeriodicMerits":   2,
}


# ── Config file resolution ────────────────────────────────────────────────────
# Priority:
#   1. User data dir  (~/.local/share/EDMD/config.toml)
#   2. Repo-adjacent  (same dir as edmd.py)   — dev / legacy fallback
#   3. PyInstaller bundle

def resolve_config_path(script_path: Path) -> Path | None:
    """Return the first existing config.toml candidate, or None."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates = [
            EDMD_DATA_DIR / "config.toml",
            script_path.parents[1] / "config.toml",
        ]
    else:
        candidates = [
            EDMD_DATA_DIR / "config.toml",
            script_path.parent / "config.toml",
        ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_config_file(config_path: Path) -> dict:
    """Read and parse a TOML config file.  Calls sys.exit on decode error."""
    with open(config_path, mode="rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(f"Config decode error: {e}")
            if sys.argv[0].count("\\") > 1:
                input("Press ENTER to exit")
            sys.exit(1)


# ── Setting resolution ────────────────────────────────────────────────────────

def _safe_section(d: dict, key: str) -> dict:
    """Return d[key] if it is a dict, else {}. Prevents crashes when a config
    key exists but holds a scalar value instead of a nested table."""
    v = d.get(key)
    return v if isinstance(v, dict) else {}


def load_setting(
    config: dict,
    config_profile: str | None,
    category: str,
    defaults: dict,
    warn_missing: bool = True,
) -> dict:
    """Resolve a settings block with profile → global → default fallback.

    Resolution order per key:
      1. config[config_profile][category][key]   (if profile active)
      2. config[category][key]
      3. defaults[key]
    """
    settings = {}

    # Pre-extract sections once so the loop is clean and type-safe.
    # _safe_section guards against any level being a non-dict value.
    profile_section: dict = _safe_section(config, config_profile) if config_profile else {}
    profile_cat:     dict = _safe_section(profile_section, category)
    global_cat:      dict = _safe_section(config, category)

    for key in defaults:
        value = None

        if profile_cat.get(key) is not None:
            value = profile_cat[key]
        elif global_cat.get(key) is not None:
            value = global_cat[key]
        else:
            value = defaults[key]
            if warn_missing:
                print(
                    f"{_WARNING} Config '{category}' -> '{key}' not found "
                    f"(using default: {defaults[key]})"
                )

        if type(value) != type(defaults[key]):
            print(
                f"{_WARNING} Config '{category}' -> '{key}' expected type "
                f"{type(defaults[key]).__name__} but got "
                f"{type(value).__name__} "
                f"(using default: {defaults[key]})"
            )
            value = defaults[key]

        settings[key] = value

    return settings


def pcfg(config: dict, config_profile: str | None, key: str, default=False):
    """Read a key from the active profile only, never from global config.

    These keys are profile-gated by design (e.g. _adv_session_mgmt).
    """
    if config_profile:
        v = _safe_section(config, config_profile).get(key)
        if v is not None:
            return v
    return default


# ── ConfigManager ─────────────────────────────────────────────────────────────

class ConfigManager:
    """Holds live config state and supports hot-reload.

    Instantiated once in edmd.py after initial load.  Passed into CoreAPI
    so all components access config through a single object.
    """

    def __init__(
        self,
        config: dict,
        config_path: Path,
        config_profile: str | None,
    ):
        self.config         = config
        self.config_path    = config_path
        self.config_profile = config_profile
        self._mtime         = config_path.stat().st_mtime

        # Resolved setting dicts — refreshed on hot-reload
        self.app_settings  = {}
        self.discord_cfg   = {}
        self.notify_levels = {}
        self.gui_cfg       = {}
        self._resolve_all(warn=True)

    def _resolve_all(self, warn: bool = False):
        self.app_settings  = self.load_setting("Settings",  CFG_DEFAULTS_SETTINGS, warn)
        self.app_settings.update(
            self.load_setting("Settings", CFG_DEFAULTS_EXTRA, False)
        )
        self.discord_cfg   = self.load_setting("Discord",   CFG_DEFAULTS_DISCORD,  warn)
        self.notify_levels = self.load_setting("LogLevels", CFG_DEFAULTS_NOTIFY,   warn)
        self.gui_cfg       = self.load_setting("GUI",       CFG_DEFAULTS_GUI,      False)
        self.eddn_cfg      = self.load_setting("EDDN",      CFG_DEFAULTS_EDDN,     False)
        self.edsm_cfg      = self.load_setting("EDSM",      CFG_DEFAULTS_EDSM,     False)
        self.edastro_cfg   = self.load_setting("EDAstro",   CFG_DEFAULTS_EDASTRO,  False)

    def load_setting(
        self,
        category: str,
        defaults: dict,
        warn_missing: bool = True,
    ) -> dict:
        """Convenience wrapper using stored config and profile."""
        return load_setting(
            self.config,
            self.config_profile,
            category,
            defaults,
            warn_missing,
        )

    def pcfg(self, key: str, default=False):
        """Profile-gated key lookup."""
        return pcfg(self.config, self.config_profile, key, default)

    def refresh(self, terminal_print: bool = True) -> bool:
        """Re-read config.toml if modified.  Returns True if reloaded."""
        try:
            new_mtime = self.config_path.stat().st_mtime
        except OSError:
            return False

        if new_mtime <= self._mtime:
            return False

        try:
            self.config = load_config_file(self.config_path)
        except SystemExit:
            return False

        self._mtime = new_mtime
        self._resolve_all(warn=False)

        if terminal_print:
            # Deferred import avoids circular dependency at module load time
            from core.emit import Terminal
            print(f"{Terminal.YELL}Config reloaded.{Terminal.END}")

        return True
