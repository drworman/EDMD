"""
gui/app.py — GTK4 dashboard window for Elite Dangerous Monitor Daemon.

Architecture:
  - Monitor runs on a background thread (run_monitor in core/journal.py)
  - GUI runs on the GTK main thread
  - Communication via thread-safe queue: gui_queue
  - GLib.timeout_add polls the queue and dispatches targeted block refreshes

Layout:
  - Menu bar (top)
  - 24-column snap grid canvas (fills remaining space)
  - Blocks placed absolutely on the canvas via Gtk.Fixed
  - No event log area; no right-panel sidebar
  - Sponsoring links live in Help -> About

Replaces the old log+sidebar layout from edmd_gui.py.
"""

import signal
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib, Gdk
except ImportError:
    raise ImportError(
        "PyGObject not found.\n"
        "  Arch/Manjaro:  pacman -S python-gobject gtk4\n"
        "  pip:           pip install PyGObject"
    )

from gui.helpers  import apply_theme, make_label
from gui.grid     import BlockGrid
from gui.menu     import EdmdMenuBar
from gui.blocks   import (
    CommanderBlock,
    CrewSlfBlock,
    MissionsBlock,
    SessionStatsBlock,
    AlertsBlock,
)

GLib.set_prgname("edmd")
GLib.set_application_name("EDMD")

# Block registry: (plugin_name, BlockWidget class, display label)
BLOCK_REGISTRY = [
    ("commander",     CommanderBlock,    "Commander"),
    ("session_stats", SessionStatsBlock, "Session Stats"),
    ("crew_slf",      CrewSlfBlock,      "Crew / SLF"),
    ("missions",      MissionsBlock,     "Mission Stack"),
    ("alerts",        AlertsBlock,       "Alerts"),
]


class EdmdWindow(Gtk.ApplicationWindow):

    POLL_MS = 100    # gui_queue poll interval (ms)
    TICK_MS = 1000   # per-second block refresh (ms)

    def __init__(self, app, core, program: str, version: str):
        super().__init__(application=app, title=f"{program} v{version}")
        self._core    = core
        self._program = program
        self._version = version

        self.set_default_size(1280, 760)
        self.add_css_class("edmd-window")

        self._grid          = BlockGrid(canvas_width=1280)
        self._blocks: dict  = {}
        self._is_fullscreen = False

        self._build_ui()
        self._build_and_place_blocks()
        self._refresh_all()

        GLib.timeout_add(self.POLL_MS, self._poll_queue)
        GLib.timeout_add(self.TICK_MS, self._tick)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("root-box")
        self.set_child(root)

        # ── Thin title bar ────────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.add_css_class("edmd-titlebar")

        self._title_lbl = make_label(
            f"{self._program}  v{self._version}",
            css_class="header-title"
        )
        self._title_lbl.set_hexpand(True)
        self._title_lbl.set_margin_start(8)
        header.append(self._title_lbl)

        self._fs_button = Gtk.Button()
        self._fs_button.set_icon_name("view-fullscreen-symbolic")
        self._fs_button.set_tooltip_text("Toggle fullscreen (F11)")
        self._fs_button.connect("clicked", lambda *_: self.toggle_fullscreen())
        self._fs_button.add_css_class("flat")
        header.append(self._fs_button)

        # Window controls (close/min/max) via HeaderBar trick: we use a real
        # HeaderBar but hide its title and pack our header row into it.
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(True)
        hb.add_css_class("edmd-header")
        hb.set_title_widget(header)
        self.set_titlebar(hb)

        # ── Menu bar ──────────────────────────────────────────────────────────
        block_names = [name for name, _, _ in BLOCK_REGISTRY]
        self._menubar = EdmdMenuBar(self, block_names)
        root.append(self._menubar.widget())

        # ── Canvas ────────────────────────────────────────────────────────────
        self._canvas = Gtk.Fixed()
        self._canvas.add_css_class("dashboard-canvas")
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)

        canvas_scroll = Gtk.ScrolledWindow()
        canvas_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        canvas_scroll.set_vexpand(True)
        canvas_scroll.set_hexpand(True)
        canvas_scroll.add_css_class("canvas-scroll")
        canvas_scroll.set_child(self._canvas)
        root.append(canvas_scroll)

        # Key handler
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Resize handler
        self.connect("notify::default-width", self._on_resize)

    def _on_resize(self, *_) -> None:
        w = self.get_width()
        if w > 100:
            self._grid.update_canvas_width(w)
            self._replace_all_blocks()

    # ── Block construction & placement ────────────────────────────────────────

    def _build_and_place_blocks(self) -> None:
        """Build all block widgets and place them on the canvas."""
        for name, cls, _display in BLOCK_REGISTRY:
            block = cls(self._core)
            widget = block.build_widget()
            self._blocks[name] = (block, widget)

            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            widget.set_size_request(w, h)
            self._canvas.put(widget, x, y)

    def _replace_all_blocks(self) -> None:
        """Reposition all blocks after a resize or layout reset."""
        for name, (block, widget) in self._blocks.items():
            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            self._canvas.move(widget, x, y)
            widget.set_size_request(w, h)

    # ── Block visibility ──────────────────────────────────────────────────────

    def set_block_visible(self, name: str, visible: bool) -> None:
        entry = self._blocks.get(name)
        if entry:
            _, widget = entry
            widget.set_visible(visible)

    # ── Layout reset ──────────────────────────────────────────────────────────

    def reset_layout(self) -> None:
        self._grid.reset()
        self._replace_all_blocks()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        for block, _ in self._blocks.values():
            block.refresh()

    def _refresh_block(self, name: str) -> None:
        entry = self._blocks.get(name)
        if entry:
            block, _ = entry
            block.refresh()

    # ── Fullscreen ────────────────────────────────────────────────────────────

    def toggle_fullscreen(self) -> None:
        if self._is_fullscreen:
            self.unfullscreen()
            self._fs_button.set_icon_name("view-fullscreen-symbolic")
            self._fs_button.set_tooltip_text("Toggle fullscreen (F11)")
            self._is_fullscreen = False
        else:
            self.fullscreen()
            self._fs_button.set_icon_name("view-restore-symbolic")
            self._fs_button.set_tooltip_text("Exit fullscreen (F11)")
            self._is_fullscreen = True

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        return False

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self) -> bool:
        try:
            while True:
                msg_type, payload = self._core.gui_queue.get_nowait()

                if msg_type in ("cmdr_update", "vessel_update"):
                    self._refresh_block("commander")
                elif msg_type in ("crew_update", "slf_update"):
                    self._refresh_block("crew_slf")
                elif msg_type == "mission_update":
                    self._refresh_block("missions")
                elif msg_type == "stats_update":
                    self._refresh_block("session_stats")
                elif msg_type == "alerts_update":
                    self._refresh_block("alerts")
                elif msg_type == "all_update":
                    self._refresh_all()
                elif msg_type == "update_notice":
                    self._on_update_notice(payload)
                # "log" messages discarded — terminal receives them via emit()

        except Exception:
            pass

        return True

    def _tick(self) -> bool:
        self._refresh_block("session_stats")
        self._refresh_block("missions")
        self._refresh_block("crew_slf")
        self._refresh_block("alerts")
        return True

    # ── Update notice ─────────────────────────────────────────────────────────

    def _on_update_notice(self, version: str) -> None:
        self._title_lbl.set_label(
            f"{self._program}  v{self._version}"
            f"  ·  \u2b06 v{version} available  (File \u2192 Upgrade)"
        )
        self._title_lbl.add_css_class("update-available")


# ── Application ───────────────────────────────────────────────────────────────

class EdmdApp(Gtk.Application):

    def __init__(self, core, program: str, version: str):
        super().__init__(application_id="com.drworman.edmd")
        self._core    = core
        self._program = program
        self._version = version
        self._theme   = core.cfg.gui_cfg.get("Theme", "default")

    def do_activate(self) -> None:
        apply_theme(self._theme)
        win = EdmdWindow(
            app=self,
            core=self._core,
            program=self._program,
            version=self._version,
        )
        win.present()

        signal.signal(signal.SIGINT, lambda *_: self.quit())
        GLib.timeout_add(200, lambda: True)
