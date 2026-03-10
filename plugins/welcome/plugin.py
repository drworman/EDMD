"""
plugins/welcome/plugin.py — Example EDMD plugin.

Demonstrates:
  • PLUGIN_DEFAULT_ENABLED = False  (ships disabled; user opts in)
  • A simple dashboard block
  • Reading live state (pilot name, ship model)
  • Using self.storage to persist a counter across sessions

This plugin is intentionally minimal.  It is not production-useful;
it exists to show the structure every third-party plugin should follow.
Read docs/PLUGIN_DEVELOPMENT.md before writing your own.
"""

from core.plugin_loader import BasePlugin

# GTK4 is optional — guard all GUI imports so the plugin still loads in
# terminal-only mode.
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    _GTK_AVAILABLE = True
except Exception:
    _GTK_AVAILABLE = False

if _GTK_AVAILABLE:
    from gui.block_base import BlockWidget


# ── Block widget ──────────────────────────────────────────────────────────────

if _GTK_AVAILABLE:
    class WelcomeBlock(BlockWidget):
        BLOCK_TITLE = "Welcome"

        DEFAULT_COL    = 8
        DEFAULT_ROW    = 28
        DEFAULT_WIDTH  = 8
        DEFAULT_HEIGHT = 5

        def build(self, parent: "Gtk.Box") -> None:
            body = self._build_section(parent)

            self._greeting = self.make_label(
                "Waiting for commander data…",
                css_class="data-value",
            )
            self._greeting.set_wrap(True)
            self._greeting.set_xalign(0.0)
            body.append(self._greeting)

        def refresh(self) -> None:
            state     = self.core.state
            name      = getattr(state, "pilot_name",  None) or "CMDR"
            ship_raw  = getattr(state, "pilot_ship",  None) or ""

            # pilot_ship holds the internal localised name from the journal.
            # Strip internal prefixes if present (e.g. "Type_10").
            ship = ship_raw.replace("_", " ").strip() if ship_raw else "your ship"

            self._greeting.set_label(
                f"Hello CMDR {name}, that's a {ship} you've got there.\n"
                f"You're the captain now."
            )


# ── Plugin ────────────────────────────────────────────────────────────────────

class WelcomePlugin(BasePlugin):
    PLUGIN_NAME         = "welcome"
    PLUGIN_DISPLAY      = "Welcome"
    PLUGIN_VERSION      = "1.0.0"
    PLUGIN_DESCRIPTION  = "Example plugin — greeting block. Ships disabled."
    SUBSCRIBED_EVENTS   = ["Commander", "Loadout"]

    # ── Ships disabled — user must enable in Installed Plugins ────────────────
    PLUGIN_DEFAULT_ENABLED = False

    BLOCK_WIDGET_CLASS = WelcomeBlock if _GTK_AVAILABLE else None

    def on_load(self, core) -> None:
        super().on_load(core)
        if _GTK_AVAILABLE:
            core.register_block(self, priority=99)

        # Example: read a persistent counter from storage
        data = self.storage.read_json("data.json")
        self._load_count = data.get("load_count", 0) + 1
        self.storage.write_json({"load_count": self._load_count}, "data.json")

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")
        if ev in ("Commander", "Loadout"):
            gq = self.core.gui_queue
            if gq:
                gq.put(("plugin_refresh", self.PLUGIN_NAME))
