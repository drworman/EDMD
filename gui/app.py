"""
gui/app.py — GTK4 dashboard window for Elite Dangerous Monitor Daemon.

Canvas sizing: connects to notify::width and notify::height on the canvas so
we always know the true available pixel dimensions after each layout pass.

Reflow: if the canvas shrinks below what the saved layout needs, blocks are
scaled down proportionally. When the canvas grows back to full size, blocks
return to their saved grid positions.
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
    CargoBlock,
    EngineeringBlock,
    AssetsBlock,
)

GLib.set_prgname("edmd")
GLib.set_application_name("EDMD")

# Built-in block registry — (name, BlockWidget subclass, display title)
_BUILTIN_REGISTRY = [
    ("commander",     CommanderBlock,    "Commander"),
    ("session_stats", SessionStatsBlock, "Session Stats"),
    ("crew_slf",      CrewSlfBlock,      "Crew / SLF"),
    ("missions",      MissionsBlock,     "Mission Stack"),
    ("alerts",        AlertsBlock,       "Alerts"),
    ("cargo",         CargoBlock,        "Cargo"),
    ("engineering",   EngineeringBlock,  "Engineering"),
    ("assets",        AssetsBlock,       "Assets"),
]


def _build_registry(core) -> list[tuple[str, type, str]]:
    """Build the full block registry: builtins + any plugin blocks.

    Plugin blocks are registered by setting BLOCK_WIDGET_CLASS on a BasePlugin
    subclass.  The plugin's BLOCK_WIDGET_CLASS must be a BlockWidget subclass;
    it receives the core reference via its __init__ just like builtins.
    Plugin names must not clash with builtin names — duplicates are skipped
    with a warning so a rogue plugin cannot hijack a builtin block.
    """
    registry = list(_BUILTIN_REGISTRY)
    builtin_names = {name for name, _, _ in _BUILTIN_REGISTRY}

    plugins = getattr(core, "_plugins", {})
    for plugin_name, plugin in plugins.items():
        cls = getattr(plugin, "BLOCK_WIDGET_CLASS", None)
        if cls is None:
            continue
        if plugin_name in builtin_names:
            from core.emit import Terminal
            print(
                f"{Terminal.WARN}Warning:{Terminal.END} Plugin {plugin_name!r} "
                f"tried to register a block with a builtin name — skipped."
            )
            continue
        display = getattr(plugin, "PLUGIN_DISPLAY", plugin_name)
        registry.append((plugin_name, cls, display))

    return registry


class EdmdWindow(Gtk.ApplicationWindow):

    POLL_MS   = 100
    TICK_MS   = 1000
    REFLOW_MS = 500    # how often to check for WM-driven window resize

    def __init__(self, app, core, program: str, version: str):
        super().__init__(application=app, title=f"{program} v{version}")
        self._core    = core
        self._program = program
        self._version = version

        self.set_default_size(1280, 760)
        self.add_css_class("edmd-window")

        # Build registry now — plugins are already loaded by this point
        self._registry      = _build_registry(core)
        self._grid          = BlockGrid(canvas_width=1280, canvas_height=760)
        self._blocks: dict  = {}
        self._is_fullscreen = False
        self._last_canvas_w = 0
        self._last_canvas_h = 0

        self._build_ui()
        self._build_and_place_blocks()
        self._refresh_all()

        GLib.timeout_add(self.POLL_MS,   self._poll_queue)
        GLib.timeout_add(self.TICK_MS,   self._tick)
        GLib.timeout_add(self.REFLOW_MS, self._reflow_tick)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("root-box")
        self.set_child(root)

        # ── Combined HeaderBar: menus left | title centre | controls right ────
        hb = Gtk.HeaderBar()
        # Hide Adwaita CSD buttons — we supply our own fully-styled controls.
        hb.set_show_title_buttons(False)
        hb.add_css_class("edmd-header")
        self.set_titlebar(hb)
        self._headerbar = hb

        # Centred title
        self._title_lbl = make_label(
            f"{self._program}  v{self._version}",
            css_class="header-title"
        )
        self._title_lbl.set_halign(Gtk.Align.CENTER)
        hb.set_title_widget(self._title_lbl)

        # ── Custom window controls (right side, left-to-right: fs | min | max | close)
        def _wctl(icon, tooltip, handler, css="wctl-btn"):
            b = Gtk.Button()
            b.set_icon_name(icon)
            b.set_tooltip_text(tooltip)
            b.connect("clicked", handler)
            b.add_css_class(css)
            return b

        self._fs_button = _wctl(
            "view-fullscreen-symbolic", "Toggle fullscreen (F11)",
            lambda *_: self.toggle_fullscreen()
        )
        self._min_button = _wctl(
            "window-minimize-symbolic", "Minimise",
            lambda *_: self.minimize()
        )
        self._max_button = _wctl(
            "window-maximize-symbolic", "Maximise",
            lambda *_: self._toggle_maximise()
        )
        self._close_button = _wctl(
            "window-close-symbolic", "Close  (Alt+F4)",
            lambda *_: self.close(),
            css="wctl-btn wctl-close"
        )

        # Pack right-to-left (pack_end reverses order)
        for btn in (self._close_button, self._max_button,
                    self._min_button, self._fs_button):
            hb.pack_end(btn)

        # Keep max button icon in sync with window state
        self.connect("notify::maximized", self._on_maximized_changed)

        # Menu buttons packed into left side of HeaderBar
        block_names = [name for name, _, _ in self._registry]
        self._menubar = EdmdMenuBar(self, block_names)
        for btn in self._menubar.buttons():
            hb.pack_start(btn)

        # ── Canvas ────────────────────────────────────────────────────────────
        self._canvas = Gtk.Fixed()
        self._canvas.add_css_class("dashboard-canvas")
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)

        self._canvas.connect("realize",        self._on_canvas_realize)
        self._canvas.connect("notify::width",  self._on_canvas_size_changed)
        self._canvas.connect("notify::height", self._on_canvas_size_changed)

        # Wrap in a ScrolledWindow so that when vertical space is very limited
        # (e.g. a narrow i3 horizontal split) the dashboard scrolls rather than
        # compressing blocks to an unreadable size.
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_hexpand(True)
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.add_css_class("dashboard-scroll")
        self._scroll.set_child(self._canvas)
        root.append(self._scroll)

        # Key handler for F11 fullscreen
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Pre-teardown cleanup — zero any progress bars before GTK destroys widgets
        self.connect("close-request", self._on_close_request)

    # ── Canvas resize → reflow ────────────────────────────────────────────────

    def _on_canvas_realize(self, canvas) -> None:
        # Trigger one poll after realize so we get real dims on first map.
        GLib.timeout_add(50, self._poll_canvas_size)

    def _on_canvas_size_changed(self, canvas, _param) -> None:
        """notify::width or notify::height — fires when the viewport changes."""
        self._apply_canvas_size(self._scroll.get_width(), self._scroll.get_height())

    def _reflow_tick(self) -> bool:
        """Fallback poll every REFLOW_MS — catches tiling WM resizes."""
        self._apply_canvas_size(self._scroll.get_width(), self._scroll.get_height())
        return True

    def _poll_canvas_size(self) -> bool:
        """One-shot after realize settle."""
        self._apply_canvas_size(self._scroll.get_width(), self._scroll.get_height())
        return False

    def _apply_canvas_size(self, w: int, h: int) -> None:
        """Apply both dimensions — only reflows if something actually changed."""
        if w < 100 or h < 50:
            return
        w_changed = (w != self._last_canvas_w)
        h_changed = (h != self._last_canvas_h)
        if not w_changed and not h_changed:
            return
        self._last_canvas_w = w
        self._last_canvas_h = h
        self._grid.update_canvas_width(w)
        self._grid.update_canvas_height(h)
        self._replace_all_blocks()

    # ── Block construction & placement ────────────────────────────────────────

    def _build_and_place_blocks(self) -> None:
        # Suppress Gtk.Fixed minimum-size propagation to the WM.
        # Without this, placing blocks with set_size_request causes Fixed to
        # report a minimum window size equal to the full layout extent —
        # which gets set as WM_NORMAL_HINTS min_height, preventing tiling WMs
        # from shrinking the window below the layout height (breaking vertical reflow).
        self._canvas.set_size_request(1, 1)

        for name, cls, _display in self._registry:
            # Honour DEFAULT_COL/ROW/WIDTH/HEIGHT declared on the block class.
            # Only applies when there is no saved layout entry for this block.
            if hasattr(cls, "DEFAULT_COL"):
                self._grid.register_plugin_default(
                    name,
                    getattr(cls, "DEFAULT_COL",    0),
                    getattr(cls, "DEFAULT_ROW",    0),
                    getattr(cls, "DEFAULT_WIDTH",  8),
                    getattr(cls, "DEFAULT_HEIGHT", 8),
                )
            block = cls(self._core)
            widget = block.build_widget(name, self._grid, self)
            self._blocks[name] = (block, widget)

            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            self._canvas.put(widget, x, y)
            widget.set_size_request(max(44, w), max(4, h))

    def _replace_all_blocks(self) -> None:
        """Reposition and resize all blocks after canvas resize or layout reset."""
        for name, (block, widget) in self._blocks.items():
            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            self._canvas.move(widget, x, y)
            # Enforce minimum 44px width so internal widgets (e.g. ProgressBar
            # with set_size_request(40,4)) never receive a negative allocation.
            pw, ph = max(44, w), max(4, h)
            widget.set_size_request(pw, ph)
            block.on_resize(pw, ph)

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

    def _toggle_maximise(self) -> None:
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _on_maximized_changed(self, *_) -> None:
        if self.is_maximized():
            self._max_button.set_icon_name("window-restore-symbolic")
            self._max_button.set_tooltip_text("Restore")
        else:
            self._max_button.set_icon_name("window-maximize-symbolic")
            self._max_button.set_tooltip_text("Maximise")

    def _on_close_request(self, *_) -> bool:
        """Zero progress bars before GTK tears down the widget tree."""
        entry = self._blocks.get("commander")
        if entry:
            block, _ = entry
            if hasattr(block, "cleanup"):
                block.cleanup()
        return False   # False = allow window to close

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
                elif msg_type == "plugin_refresh":
                    # payload = plugin name; allows plugins to trigger their
                    # own block refresh via core.gui_queue.put(("plugin_refresh", name))
                    self._refresh_block(payload)

        except Exception:
            pass

        return True

    def _tick(self) -> bool:
        # Refresh all blocks on the tick — builtins and plugin blocks alike.
        # _refresh_block is a no-op for unknown names, so this is always safe.
        for name, _, _ in self._registry:
            self._refresh_block(name)
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
        # Switch GTK theme to "Default" (minimal, no Adwaita CSD graphics)
        # before loading our CSS. This removes Adwaita's baked-in button
        # gradients so our window control colours actually take effect.
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-theme-name", "Default")
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
