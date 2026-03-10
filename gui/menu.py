"""
gui/menu.py — Menu bar construction for EDMD dashboard.

Menu structure:
  File      — Upgrade, Exit
  View      — Show/Hide per-block checkboxes, Reset Layout, Always on Top, Full Screen
  Settings  — Preferences, Plugins
  Help      — Documentation, GitHub, About EDMD

About dialog: version, author, Ko-Fi, PayPal, GitHub links.
"""

import subprocess
import sys
import os
import webbrowser

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib, Gio
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from core.state import VERSION, AUTHOR, GITHUB_REPO

KOFI_URL   = "https://ko-fi.com/drworman"
PAYPAL_URL = "https://paypal.me/DavidWorman"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
DOCS_URL   = f"https://github.com/{GITHUB_REPO}#readme"


class EdmdMenuBar:
    """
    Builds and owns the EDMD GTK4 menu bar.

    Parameters
    ----------
    window      : EdmdWindow  — parent window (for callbacks)
    block_names : list[str]   — plugin names with GUI blocks (for View menu)
    """

    def __init__(self, window, block_names: list[str]):
        self._win         = window
        self._block_names = block_names
        self._check_items: dict[str, Gtk.CheckButton] = {}
        self._buttons: list[Gtk.MenuButton] = []
        self._build()

    def widget(self) -> Gtk.Widget:
        """Assemble buttons into a standalone bar box (for non-HeaderBar use)."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.add_css_class("edmd-menubar")
        for btn in self._buttons:
            bar.append(btn)
        return bar

    def buttons(self) -> list:
        """Return the individual MenuButton widgets for packing into a HeaderBar."""
        return self._buttons

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Build MenuButton objects and store them. No parenting yet."""
        for label, builder in [
            ("File",     self._build_file_menu),
            ("View",     self._build_view_menu),
            ("Settings", self._build_settings_menu),
            ("Reports",  self._build_reports_menu),
            ("Help",     self._build_help_menu),
        ]:
            btn = Gtk.MenuButton(label=label)
            btn.add_css_class("menubar-btn")
            btn.set_popover(builder())
            self._buttons.append(btn)

    def _popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        pop.add_css_class("edmd-menu-popover")
        pop.set_has_arrow(False)
        return pop

    def _vbox(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class("menu-box")
        return box

    def _menu_btn(self, label: str, callback) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.add_css_class("menu-item")
        btn.set_has_frame(False)
        btn.connect("clicked", callback)
        return btn

    def _separator(self) -> Gtk.Separator:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("menu-sep")
        return sep

    # ── File menu ─────────────────────────────────────────────────────────────

    def _build_file_menu(self) -> Gtk.Popover:
        pop = self._popover()
        box = self._vbox()

        box.append(self._menu_btn("⬆  Upgrade", self._on_upgrade))
        box.append(self._separator())
        box.append(self._menu_btn("✕  Exit", self._on_exit))

        pop.set_child(box)
        return pop

    # ── View menu ─────────────────────────────────────────────────────────────

    def _build_view_menu(self) -> Gtk.Popover:
        pop = self._popover()
        box = self._vbox()

        # Show/Hide per-block checkboxes
        lbl = Gtk.Label(label="Blocks")
        lbl.add_css_class("menu-section-label")
        lbl.set_xalign(0.0)
        box.append(lbl)

        for name in self._block_names:
            display = name.replace("_", " ").title()
            chk = Gtk.CheckButton(label=display)
            chk.set_active(True)
            chk.add_css_class("menu-check")
            chk.connect("toggled", self._on_block_toggle, name)
            self._check_items[name] = chk
            box.append(chk)

        box.append(self._separator())
        box.append(self._menu_btn("↺  Reset Layout", self._on_reset_layout))
        box.append(self._separator())

        # Always on top toggle
        self._aot_check = Gtk.CheckButton(label="Always on Top")
        self._aot_check.add_css_class("menu-check")
        self._aot_check.connect("toggled", self._on_always_on_top)
        box.append(self._aot_check)

        box.append(self._menu_btn("⛶  Full Screen  (F11)", self._on_fullscreen))

        pop.set_child(box)
        return pop

    # ── Settings menu ─────────────────────────────────────────────────────────

    def _build_settings_menu(self) -> Gtk.Popover:
        pop = self._popover()
        box = self._vbox()

        box.append(self._menu_btn("⚙  Preferences", self._on_preferences))
        box.append(self._separator())
        box.append(self._menu_btn("🔌  Plugins", self._on_plugins))

        pop.set_child(box)
        return pop

    # ── Reports menu ──────────────────────────────────────────────────────────

    def _build_reports_menu(self) -> Gtk.Popover:
        pop = self._popover()
        box = self._vbox()

        from core.reports import REPORT_REGISTRY
        for key, display, _ in REPORT_REGISTRY:
            box.append(self._menu_btn(f"  {display}", lambda *_, k=key: self._on_report(k)))

        pop.set_child(box)
        return pop

    # ── Help menu ─────────────────────────────────────────────────────────────

    def _build_help_menu(self) -> Gtk.Popover:
        pop = self._popover()
        box = self._vbox()

        box.append(self._menu_btn("📄  Documentation", self._on_docs))
        box.append(self._menu_btn("🐙  GitHub", self._on_github))
        box.append(self._separator())
        box.append(self._menu_btn("ℹ  About EDMD", self._on_about))

        pop.set_child(box)
        return pop

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_upgrade(self, *_) -> None:
        try:
            from core.state import save_session_state
            from pathlib import Path
            save_session_state(Path("."), self._win._core.active_session)
        except Exception:
            pass
        new_argv = [a for a in sys.argv if a != "--upgrade"] + ["--upgrade"]
        os.execv(sys.executable, [sys.executable] + new_argv)

    def _on_exit(self, *_) -> None:
        self._win.get_application().quit()

    def _on_block_toggle(self, chk: Gtk.CheckButton, name: str) -> None:
        self._win.set_block_visible(name, chk.get_active())

    def _on_reset_layout(self, *_) -> None:
        self._win.reset_layout()

    def _on_always_on_top(self, chk: Gtk.CheckButton) -> None:
        # GTK4 ApplicationWindow does not expose a direct always-on-top API;
        # use the underlying GDK surface hint where available.
        try:
            surface = self._win.get_surface()
            if hasattr(surface, "set_keep_above"):
                surface.set_keep_above(chk.get_active())
        except Exception:
            pass

    def _on_fullscreen(self, *_) -> None:
        self._win.toggle_fullscreen()

    def _on_preferences(self, *_) -> None:
        from gui.preferences import PreferencesWindow
        pref = PreferencesWindow(self._win, self._win._core)
        pref.present()

    def _on_plugins(self, *_) -> None:
        self._show_plugins_dialog()

    def _on_docs(self, *_) -> None:
        from gui.docs_viewer import DocsViewer
        viewer = DocsViewer(self._win)
        viewer.present()

    def _on_report(self, key: str) -> None:
        journal_dir = self._win._core.journal_dir
        if not journal_dir:
            self._show_no_journal_dialog()
            return
        from pathlib import Path
        from gui.reports_viewer import ReportsViewer
        viewer = ReportsViewer(self._win, Path(journal_dir), initial_key=key)
        viewer.present()

    def _show_no_journal_dialog(self) -> None:
        dlg = Gtk.Window(title="No Journal Folder")
        dlg.set_transient_for(self._win)
        dlg.set_modal(True)
        dlg.set_default_size(340, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20); box.set_margin_bottom(20)
        box.set_margin_start(20); box.set_margin_end(20)
        dlg.set_child(box)
        lbl = Gtk.Label(label="Journal folder is not configured.\nSet JournalFolder in config.toml.")
        lbl.set_wrap(True); lbl.add_css_class("doc-para")
        box.append(lbl)
        btn = Gtk.Button(label="OK")
        btn.add_css_class("about-close")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_: dlg.close())
        box.append(btn)
        dlg.present()

    def _on_github(self, *_) -> None:
        webbrowser.open(GITHUB_URL)

    def _on_about(self, *_) -> None:
        self._show_about_dialog()

    # ── About dialog ──────────────────────────────────────────────────────────

    def _show_about_dialog(self) -> None:
        from gui.helpers import avatar_path_for_theme
        theme = self._win._core.cfg.gui_cfg.get("Theme", "default")

        dlg = Gtk.Window(title="About EDMD")
        dlg.set_transient_for(self._win)
        dlg.set_modal(True)
        dlg.set_resizable(False)
        dlg.set_default_size(360, -1)
        dlg.add_css_class("about-dialog")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(20)
        outer.set_margin_bottom(20)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        dlg.set_child(outer)

        # Avatar
        avatar_path = avatar_path_for_theme(theme)
        if avatar_path:
            pic = Gtk.Picture.new_for_filename(str(avatar_path))
            pic.set_can_shrink(True)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_size_request(80, 80)
            pic.set_halign(Gtk.Align.CENTER)
            outer.append(pic)

        # Title
        title = Gtk.Label(label="Elite Dangerous Monitor Daemon")
        title.add_css_class("about-title")
        title.set_wrap(True)
        title.set_halign(Gtk.Align.CENTER)
        outer.append(title)

        version_lbl = Gtk.Label(label=f"v{VERSION}")
        version_lbl.add_css_class("about-version")
        version_lbl.set_halign(Gtk.Align.CENTER)
        outer.append(version_lbl)

        author_lbl = Gtk.Label(label=f"by {AUTHOR}")
        author_lbl.add_css_class("about-author")
        author_lbl.set_halign(Gtk.Align.CENTER)
        outer.append(author_lbl)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.append(sep)

        # Links
        link_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        link_box.set_halign(Gtk.Align.CENTER)

        for label, url in [
            ("☕ Ko-Fi",   KOFI_URL),
            ("💳 PayPal",  PAYPAL_URL),
            ("🐙 GitHub",  GITHUB_URL),
        ]:
            btn = Gtk.LinkButton(uri=url, label=label)
            btn.add_css_class("about-link")
            link_box.append(btn)

        outer.append(link_box)

        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("about-close")
        close_btn.set_halign(Gtk.Align.CENTER)
        close_btn.connect("clicked", lambda *_: dlg.close())
        outer.append(close_btn)

        dlg.present()

    # ── Installed Plugins dialog ──────────────────────────────────────────────

    def _show_plugins_dialog(self) -> None:
        """Installed Plugins dialog — lists all plugins (enabled and disabled)
        with per-plugin enable/disable toggles.  Changes persist to
        plugin_states.json and take effect after restart."""

        core   = self._win._core
        loader = getattr(core, "_loader", None)

        dlg = Gtk.Window(title="Installed Plugins")
        dlg.set_transient_for(self._win)
        dlg.set_modal(True)
        dlg.set_resizable(True)
        dlg.set_default_size(460, -1)
        dlg.add_css_class("plugins-dialog")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        dlg.set_child(outer)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = Gtk.Label(label="Installed Plugins")
        hdr.add_css_class("section-header")
        hdr.set_xalign(0.0)
        outer.append(hdr)

        outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Restart notice (hidden until a toggle changes) ────────────────────
        restart_bar = Gtk.Label(
            label="⟳  Restart EDMD to apply changes"
        )
        restart_bar.add_css_class("plugin-restart-notice")
        restart_bar.set_xalign(0.5)
        restart_bar.set_visible(False)
        # will be shown when any toggle fires

        # ── Collect all plugins: enabled + disabled ───────────────────────────
        active_plugins   = list(getattr(core, "_plugins", {}).values())
        disabled_plugins = getattr(loader, "disabled_meta", []) if loader else []

        all_plugins = (
            [(p, True)  for p in active_plugins]
            + [(p, False) for p in disabled_plugins]
        )
        # Sort: builtins first (alphabetical), then third-party (alphabetical)
        all_plugins.sort(key=lambda x: (
            not getattr(x[0], "_is_builtin", True),
            getattr(x[0], "PLUGIN_DISPLAY", "").lower(),
        ))

        if not all_plugins:
            lbl = Gtk.Label(label="No plugins found.")
            lbl.add_css_class("about-author")
            lbl.set_xalign(0.0)
            lbl.set_margin_top(8)
            outer.append(lbl)
        else:
            # ── Section: Builtins ─────────────────────────────────────────────
            builtins_list  = [(p, e) for p, e in all_plugins if getattr(p, "_is_builtin", True)]
            thirdparty_list = [(p, e) for p, e in all_plugins if not getattr(p, "_is_builtin", True)]

            for section_items, section_title in [
                (builtins_list,   "Built-in"),
                (thirdparty_list, "Third-party"),
            ]:
                if not section_items:
                    continue

                sec_lbl = Gtk.Label(label=section_title)
                sec_lbl.add_css_class("plugin-section-label")
                sec_lbl.set_xalign(0.0)
                sec_lbl.set_margin_top(10)
                sec_lbl.set_margin_bottom(2)
                outer.append(sec_lbl)

                for plugin, is_active in section_items:
                    pname    = getattr(plugin, "PLUGIN_NAME",    "unknown")
                    pdisplay = getattr(plugin, "PLUGIN_DISPLAY",  pname)
                    pver     = getattr(plugin, "PLUGIN_VERSION",  "?")
                    pdesc    = getattr(plugin, "PLUGIN_DESCRIPTION", "")
                    is_blt   = getattr(plugin, "_is_builtin",    False)

                    # Container row
                    row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    row.set_margin_top(4)
                    row.set_margin_bottom(4)
                    outer.append(row)

                    # Top line: name + version badge + toggle
                    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                    row.append(top)

                    name_lbl = Gtk.Label(label=pdisplay)
                    name_lbl.set_xalign(0.0)
                    name_lbl.set_hexpand(True)
                    name_lbl.add_css_class("data-value")
                    top.append(name_lbl)

                    ver_lbl = Gtk.Label(label=f"v{pver}")
                    ver_lbl.add_css_class("data-key")
                    top.append(ver_lbl)

                    toggle = Gtk.Switch()
                    toggle.set_active(is_active)
                    toggle.set_valign(Gtk.Align.CENTER)
                    # Builtins can be toggled too; user is in charge.
                    top.append(toggle)

                    # Description line (if present)
                    if pdesc:
                        desc_lbl = Gtk.Label(label=pdesc)
                        desc_lbl.add_css_class("plugin-desc")
                        desc_lbl.set_xalign(0.0)
                        desc_lbl.set_wrap(True)
                        row.append(desc_lbl)

                    outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

                    # Toggle handler — capture pname by value
                    def _on_toggle(sw, _param, name=pname):
                        if loader:
                            loader.set_enabled(name, sw.get_active())
                        restart_bar.set_visible(True)

                    toggle.connect("notify::active", _on_toggle)

        # ── Restart notice + close ────────────────────────────────────────────
        outer.append(restart_bar)

        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("about-close")
        close_btn.set_halign(Gtk.Align.CENTER)
        close_btn.set_margin_top(10)
        close_btn.connect("clicked", lambda *_: dlg.close())
        outer.append(close_btn)

        dlg.present()

    # ── Public update helpers ─────────────────────────────────────────────────

    def set_update_available(self, version: str) -> None:
        """Called by EdmdWindow when a new version is detected."""
        # Mark the upgrade menu item — no-op if already marked
        pass   # visual hint handled by EdmdWindow's header bar label
