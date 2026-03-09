"""
core/plugin_loader.py — Discover, import, and initialise all builtins and plugins.

Search order:
  1. builtins/  — shipped with the main repo; always loaded
  2. plugins/   — optional; git submodules or user-dropped directories

Each builtin/plugin directory must contain a plugin.py with a class that
subclasses BasePlugin.  The loader calls on_load(core_api) on each.
"""

import importlib.util
import sys
from pathlib import Path

from core.emit import Terminal


# ── BasePlugin ────────────────────────────────────────────────────────────────

class BasePlugin:
    """Base class for all builtins and plugins.

    Subclass this and override the methods you need.
    PLUGIN_NAME, PLUGIN_DISPLAY, and SUBSCRIBED_EVENTS are required.
    """

    # ── Required class attributes ─────────────────────────────────────────────
    PLUGIN_NAME:     str  = ""          # machine name, e.g. "missions"
    PLUGIN_DISPLAY:  str  = ""          # human name,   e.g. "Mission Stack"
    PLUGIN_VERSION:  str  = "0.0.1"
    SUBSCRIBED_EVENTS: list[str] = []   # journal event names this plugin handles

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        """Called once at startup. Store the core reference here."""
        self.core = core

    def on_unload(self) -> None:
        """Called on clean shutdown."""

    # ── Event dispatch ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        """Called for every journal event whose name is in SUBSCRIBED_EVENTS."""

    # ── GUI integration ───────────────────────────────────────────────────────
    #
    # To add a dashboard block, set BLOCK_WIDGET_CLASS to a BlockWidget subclass.
    # The GUI framework will instantiate it, place it on the dashboard, and call
    # refresh() on every tick — exactly like the built-in blocks.
    #
    # The block will use PLUGIN_NAME as its grid key and PLUGIN_DISPLAY as its
    # default title.  All chrome (frame, drag, resize handle, footer) is provided
    # by BlockWidget.  The plugin only fills the content area via build().
    #
    # Example:
    #   from gui.block_base import BlockWidget
    #
    #   class MyBlock(BlockWidget):
    #       BLOCK_TITLE = "My Plugin"
    #       def build(self, parent): ...
    #       def refresh(self): ...
    #
    #   class MyPlugin(BasePlugin):
    #       PLUGIN_NAME        = "myplugin"
    #       BLOCK_WIDGET_CLASS = MyBlock
    #       ...
    #
    BLOCK_WIDGET_CLASS: type | None = None

    # ── Summary / alerts ─────────────────────────────────────────────────────

    def get_summary_line(self) -> str | None:
        """Return a line for the periodic terminal/Discord summary, or None."""
        return None

    def get_alert_events(self) -> list[str]:
        """Return a list of (emoji, text) alert tuples for the Alerts block."""
        return []


# ── Loader ────────────────────────────────────────────────────────────────────

class PluginLoader:
    """Discovers plugin directories and instantiates their plugin classes."""

    def __init__(self, repo_root: Path):
        self._repo_root   = repo_root
        self._plugins:    list[BasePlugin] = []
        self._plugin_map: dict[str, BasePlugin] = {}

    @property
    def plugins(self) -> list[BasePlugin]:
        return self._plugins

    @property
    def plugin_map(self) -> dict[str, BasePlugin]:
        return self._plugin_map

    def load_all(self, core_api) -> None:
        """Load builtins then plugins, calling on_load(core_api) on each."""
        builtins_dir = self._repo_root / "builtins"
        plugins_dir  = self._repo_root / "plugins"

        for search_dir, label in [(builtins_dir, "builtin"), (plugins_dir, "plugin")]:
            if not search_dir.is_dir():
                continue
            for plugin_dir in sorted(search_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_file = plugin_dir / "plugin.py"
                if not plugin_file.exists():
                    continue
                self._load_one(plugin_file, label, core_api)

        # Expose the full plugin map back to CoreAPI
        core_api._plugins = self._plugin_map

    def _load_one(self, plugin_file: Path, label: str, core_api) -> None:
        module_name = f"_edmd_plugin_{plugin_file.parent.name}"
        try:
            spec   = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find the BasePlugin subclass in the module
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
                    f"{label} {plugin_file.parent.name!r}: no BasePlugin subclass found"
                )
                return

            instance = plugin_cls()
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
