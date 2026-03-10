"""
core/plugin_loader.py — Discover, import, initialise, and lifecycle-manage
                        all builtins and plugins.

Search order:
  1. builtins/  — shipped with the main repo; always enabled by default
  2. plugins/   — optional; git submodules or user-dropped directories

Each builtin/plugin directory must contain a plugin.py with a class that
subclasses BasePlugin.  The loader:
  • reads metadata from every plugin.py regardless of enabled state
  • only instantiates and calls on_load() for enabled plugins
  • persists enabled/disabled state to EDMD_DATA_DIR/plugin_states.json
  • provides each plugin a PluginStorage instance pre-scoped to its own
    data directory and enforces write sandboxing at the open() call level

Sandboxing caveat
-----------------
Python has no true process-level sandbox.  The write guard below patches
open() inside each plugin module's namespace, which blocks accidental writes
outside the allowed directory and satisfies the intent for well-behaved
plugins.  A deliberately hostile plugin can still import builtins directly to
bypass this.  Users should only install plugins from sources they trust.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import sys
import tomllib
from functools import wraps
from pathlib import Path
from typing import Any

from core.emit import Terminal
from core.state import EDMD_DATA_DIR


# ── PluginStorage ─────────────────────────────────────────────────────────────

class PluginStorage:
    """Sandboxed, scoped data storage for a single plugin.

    Each plugin receives a PluginStorage instance pre-bound to:
        EDMD_DATA_DIR/plugins/<plugin_name>/

    Read operations are unrestricted.  Write operations are restricted to
    that directory — any attempt to write outside it raises PermissionError.

    Supported file types: JSON (.json) and TOML (.toml, read-only).
    TOML writing is not supported because the stdlib ships no TOML writer;
    use JSON for mutable state.

    API
    ---
    storage.read_json(filename)          → dict  (empty dict if file absent)
    storage.write_json(data, filename)   → None
    storage.read_toml(filename)          → dict  (empty dict if file absent)
    storage.path                         → Path  (the plugin's data directory)
    """

    # Allowed bare filenames — no path separators permitted.
    _ALLOWED_NAMES = frozenset({
        "data.json", "config.json", "state.json",
        "config.toml", "state.toml",
    })

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir

    @property
    def path(self) -> Path:
        return self._dir

    # ── internal ──────────────────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _validate_filename(self, filename: str) -> Path:
        """Reject any filename that contains path separators or is not on
        the allowed list, then return the resolved absolute path."""
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(
                f"Plugin storage filename must be a bare name (got {filename!r})"
            )
        if filename not in self._ALLOWED_NAMES:
            raise ValueError(
                f"Plugin storage filename {filename!r} is not permitted. "
                f"Allowed: {sorted(self._ALLOWED_NAMES)}"
            )
        return self._dir / filename

    # ── public API ────────────────────────────────────────────────────────────

    def read_json(self, filename: str = "data.json") -> dict:
        """Read a JSON file from the plugin data directory.
        Returns an empty dict if the file does not exist."""
        p = self._validate_filename(filename)
        if not p.exists():
            return {}
        with builtins.open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except (json.JSONDecodeError, ValueError):
                return {}

    def write_json(self, data: dict, filename: str = "data.json") -> None:
        """Write a JSON file to the plugin data directory (atomic via temp file)."""
        p = self._validate_filename(filename)
        self._ensure_dir()
        tmp = p.with_suffix(".tmp")
        with builtins.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        tmp.replace(p)

    def read_toml(self, filename: str = "config.toml") -> dict:
        """Read a TOML file from the plugin data directory.
        Returns an empty dict if the file does not exist."""
        if not filename.endswith(".toml"):
            raise ValueError("read_toml() requires a .toml filename")
        p = self._validate_filename(filename)
        if not p.exists():
            return {}
        with builtins.open(p, "rb") as f:
            try:
                return tomllib.load(f)
            except tomllib.TOMLDecodeError:
                return {}


# ── DisabledPluginMeta ────────────────────────────────────────────────────────

class DisabledPluginMeta:
    """Lightweight record for a plugin that was found but not loaded.
    Used by the Installed Plugins dialog to show disabled plugins."""

    __slots__ = (
        "PLUGIN_NAME", "PLUGIN_DISPLAY", "PLUGIN_VERSION",
        "PLUGIN_DESCRIPTION", "_is_builtin",
    )

    def __init__(
        self,
        name: str,
        display: str,
        version: str,
        description: str,
        is_builtin: bool,
    ) -> None:
        self.PLUGIN_NAME        = name
        self.PLUGIN_DISPLAY     = display
        self.PLUGIN_VERSION     = version
        self.PLUGIN_DESCRIPTION = description
        self._is_builtin        = is_builtin


# ── BasePlugin ────────────────────────────────────────────────────────────────

class BasePlugin:
    """Base class for all builtins and plugins.

    Subclass this and override the methods you need.
    PLUGIN_NAME, PLUGIN_DISPLAY, and SUBSCRIBED_EVENTS are required class
    attributes.  All other class attributes have sensible defaults.

    The loader guarantees that before on_load() is called:
      • self.storage  — PluginStorage scoped to this plugin's data directory
      • self._is_builtin — True for builtins/, False for plugins/

    Plugins must call super().on_load(core) or assign self.core manually.
    """

    # ── Required class attributes ─────────────────────────────────────────────
    PLUGIN_NAME:        str       = ""      # machine name, e.g. "missions"
    PLUGIN_DISPLAY:     str       = ""      # human name,   e.g. "Mission Stack"
    PLUGIN_VERSION:     str       = "0.0.1"
    PLUGIN_DESCRIPTION: str       = ""      # one-line description shown in dialog
    SUBSCRIBED_EVENTS:  list[str] = []

    # Set False to ship disabled by default (user can enable in Installed Plugins)
    PLUGIN_DEFAULT_ENABLED: bool  = True

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        """Called once at startup after storage is assigned.
        Always call super().on_load(core) first."""
        self.core = core

    def on_unload(self) -> None:
        """Called on clean shutdown."""

    # ── Event dispatch ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        """Called for every journal event whose name is in SUBSCRIBED_EVENTS."""

    # ── GUI integration ───────────────────────────────────────────────────────
    #
    # Set BLOCK_WIDGET_CLASS to a BlockWidget subclass to add a dashboard block.
    # See docs/PLUGIN_DEVELOPMENT.md for full instructions.
    #
    BLOCK_WIDGET_CLASS: type | None = None

    # ── Summary / alerts ─────────────────────────────────────────────────────

    def get_summary_line(self) -> str | None:
        """Return a line for the periodic terminal/Discord summary, or None."""
        return None

    def get_alert_events(self) -> list[str]:
        """Return a list of (emoji, text) alert tuples for the Alerts block."""
        return []


# ── Write sandbox ─────────────────────────────────────────────────────────────

def _make_sandboxed_open(allowed_dir: Path, plugin_name: str):
    """Return a replacement open() that raises PermissionError on any write
    attempt whose resolved path is outside allowed_dir."""

    resolved_allowed = allowed_dir.resolve()

    def _sandboxed_open(file, mode="r", *args, **kwargs):
        if any(c in str(mode) for c in ("w", "a", "x", "+")):
            try:
                target = Path(file).resolve()
            except Exception:
                target = Path(str(file)).resolve()
            if not str(target).startswith(str(resolved_allowed)):
                raise PermissionError(
                    f"[EDMD] Plugin '{plugin_name}' attempted to write to "
                    f"{target} — plugins may only write to "
                    f"{resolved_allowed}. "
                    f"Use self.storage.write_json() instead."
                )
        return builtins.open(file, mode, *args, **kwargs)

    return _sandboxed_open


# ── Plugin state persistence ──────────────────────────────────────────────────

_STATES_FILE = EDMD_DATA_DIR / "plugin_states.json"


def _load_plugin_states() -> dict[str, bool]:
    """Read persisted enabled/disabled overrides.  Missing = use class default."""
    if not _STATES_FILE.exists():
        return {}
    try:
        with builtins.open(_STATES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {k: bool(v) for k, v in raw.items() if isinstance(k, str)}
    except Exception:
        return {}


def _save_plugin_states(states: dict[str, bool]) -> None:
    EDMD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STATES_FILE.with_suffix(".tmp")
    with builtins.open(tmp, "w", encoding="utf-8") as f:
        json.dump(states, f, indent=2)
    tmp.replace(_STATES_FILE)


# ── Loader ────────────────────────────────────────────────────────────────────

class PluginLoader:
    """Discovers plugin directories and manages their lifecycle."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root    = repo_root
        self._plugins:     list[BasePlugin]        = []
        self._plugin_map:  dict[str, BasePlugin]   = {}
        self._disabled:    list[DisabledPluginMeta] = []
        self._states:      dict[str, bool]         = _load_plugin_states()
        self._dirty:       bool                    = False   # states changed, restart needed

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def plugins(self) -> list[BasePlugin]:
        return self._plugins

    @property
    def plugin_map(self) -> dict[str, BasePlugin]:
        return self._plugin_map

    @property
    def disabled_meta(self) -> list[DisabledPluginMeta]:
        """Metadata records for installed-but-disabled plugins."""
        return self._disabled

    @property
    def pending_restart(self) -> bool:
        """True if enable/disable changes have been made this session."""
        return self._dirty

    # ── Enable / disable ──────────────────────────────────────────────────────

    def is_enabled(self, plugin_name: str, default: bool = True) -> bool:
        return self._states.get(plugin_name, default)

    def set_enabled(self, plugin_name: str, enabled: bool) -> None:
        """Persist a new enabled/disabled state for a plugin.
        Changes take effect on next restart."""
        self._states[plugin_name] = enabled
        _save_plugin_states(self._states)
        self._dirty = True

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_all(self, core_api) -> None:
        """Scan builtins/ then plugins/; load enabled plugins; capture
        metadata for disabled ones so the dialog can show them."""
        builtins_dir = self._repo_root / "builtins"
        plugins_dir  = self._repo_root / "plugins"

        for search_dir, label, is_builtin in [
            (builtins_dir, "builtin", True),
            (plugins_dir,  "plugin",  False),
        ]:
            if not search_dir.is_dir():
                continue
            for plugin_dir in sorted(search_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_file = plugin_dir / "plugin.py"
                if not plugin_file.exists():
                    continue
                self._load_one(plugin_file, label, is_builtin, core_api)

        core_api._plugins = self._plugin_map
        core_api._loader  = self

    def _load_one(
        self,
        plugin_file: Path,
        label: str,
        is_builtin: bool,
        core_api,
    ) -> None:
        dir_name    = plugin_file.parent.name
        module_name = f"_edmd_plugin_{dir_name}"

        try:
            spec   = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)

            # ── Write sandbox ───────────────────────────────────────────────
            # Patch open() in this module's namespace before execution so that
            # any write attempt outside the plugin's data dir is blocked.
            storage_dir = EDMD_DATA_DIR / "plugins" / dir_name
            module.__builtins__ = vars(builtins).copy()
            module.__builtins__["open"] = _make_sandboxed_open(storage_dir, dir_name)

            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # ── Find the BasePlugin subclass ─────────────────────────────────
            plugin_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    plugin_cls = attr
                    break

            if plugin_cls is None:
                print(
                    f"{Terminal.WARN}Warning:{Terminal.END} "
                    f"{label} {dir_name!r}: no BasePlugin subclass found, skipping"
                )
                return

            # ── Read metadata before deciding whether to load ────────────────
            name        = getattr(plugin_cls, "PLUGIN_NAME",        dir_name)
            display     = getattr(plugin_cls, "PLUGIN_DISPLAY",     name)
            version     = getattr(plugin_cls, "PLUGIN_VERSION",     "0.0.1")
            description = getattr(plugin_cls, "PLUGIN_DESCRIPTION", "")
            cls_default = getattr(plugin_cls, "PLUGIN_DEFAULT_ENABLED", True)

            enabled = self.is_enabled(name, default=cls_default)

            if not enabled:
                self._disabled.append(
                    DisabledPluginMeta(name, display, version, description, is_builtin)
                )
                print(
                    f"  Skipped {label}: {display} v{version} [{name}] (disabled)"
                )
                return

            # ── Instantiate and wire up ──────────────────────────────────────
            instance             = plugin_cls()
            instance._is_builtin = is_builtin
            instance.storage     = PluginStorage(storage_dir)

            instance.on_load(core_api)

            self._plugins.append(instance)
            self._plugin_map[instance.PLUGIN_NAME] = instance

            print(
                f"  Loaded {label}: {instance.PLUGIN_DISPLAY} "
                f"v{instance.PLUGIN_VERSION} [{instance.PLUGIN_NAME}]"
            )

        except Exception as e:
            print(
                f"{Terminal.WARN}Warning:{Terminal.END} "
                f"Failed to load {label} from {plugin_file}: {e}"
            )
            import traceback
            traceback.print_exc()
