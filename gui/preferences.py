"""
gui/preferences.py — Preferences window for EDMD.

Tabbed GTK4 dialog covering:
  General      — journal folder, UTC toggle, name truncation, inactivity config
  Notifications — per-event log level grid (0–3)
  Discord      — webhook URL, user ID, display options
  Appearance   — theme selector

Hot-reloadable settings take effect immediately on save.
Settings marked ❌ require a restart — shown with a ⚠ indicator.

Writes changes to config.toml using tomllib (read) + manual string assembly (write).
Requires Python 3.11+ (tomllib stdlib).
"""

import tomllib
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")


# ── Notification level labels ─────────────────────────────────────────────────

LEVEL_LABELS = ["Off", "Terminal only", "Terminal + Discord", "Terminal + Discord + Ping"]

NOTIFY_EVENTS = [
    ("RewardEvent",      "Kill (bounty / combat bond)"),
    ("FighterDamage",    "Fighter hull damage (~20% steps)"),
    ("FighterLost",      "Fighter destroyed"),
    ("ShieldEvent",      "Ship shields dropped / raised"),
    ("HullEvent",        "Ship hull damaged"),
    ("Died",             "Ship destroyed"),
    ("CargoLost",        "Cargo stolen"),
    ("LowCargoValue",    "Pirate declined to attack"),
    ("PoliceScan",       "Security vessel scan"),
    ("PoliceAttack",     "Security vessel attack"),
    ("FuelStatus",       "Fuel level (routine)"),
    ("FuelWarning",      "Fuel warning"),
    ("FuelCritical",     "Fuel critical"),
    ("MissionUpdate",    "Mission accepted / completed / redirected"),
    ("AllMissionsReady", "All massacre missions ready to turn in"),
    ("MeritEvent",       "Individual merit gain"),
    ("InactiveAlert",    "Inactivity alert"),
    ("RateAlert",        "Kill rate alert"),
    ("InboundScan",      "Incoming cargo scan"),
]

THEMES = [
    "default", "default-blue", "default-green", "default-purple",
    "default-red", "default-yellow", "default-light",
]


class PreferencesWindow(Gtk.Window):
    """Tabbed preferences window."""

    def __init__(self, parent, core):
        super().__init__(title="EDMD Preferences")
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(540, 560)
        self.set_resizable(True)
        self.add_css_class("prefs-window")

        self._core    = core
        self._cfg     = core.cfg
        self._changed = {}   # key → new value, flushed on Apply

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        notebook.add_css_class("prefs-notebook")
        outer.append(notebook)

        self._build_general_tab(notebook)
        self._build_notifications_tab(notebook)
        self._build_discord_tab(notebook)
        self._build_appearance_tab(notebook)

        # Button row
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        btn_row.set_margin_bottom(12)
        btn_row.set_margin_end(12)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        cancel_btn.add_css_class("prefs-btn")
        btn_row.append(cancel_btn)

        apply_btn = Gtk.Button(label="Apply & Save")
        apply_btn.add_css_class("prefs-btn-apply")
        apply_btn.connect("clicked", self._on_apply)
        btn_row.append(apply_btn)

        outer.append(btn_row)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _tab(self, notebook: Gtk.Notebook, label: str) -> Gtk.Box:
        """Add a tab and return its scrollable content box."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scroll.set_child(box)
        notebook.append_page(scroll, Gtk.Label(label=label))
        return box

    def _section_label(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        lbl.add_css_class("section-header")
        return lbl

    def _row(self, key_text: str, widget: Gtk.Widget,
             restart_required: bool = False) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_bottom(2)
        lbl = Gtk.Label(label=key_text)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        lbl.add_css_class("prefs-key")
        row.append(lbl)
        if restart_required:
            warn = Gtk.Label(label="⚠")
            warn.set_tooltip_text("Requires restart to take effect")
            warn.add_css_class("prefs-restart-warn")
            row.append(warn)
        row.append(widget)
        return row

    # ── General tab ───────────────────────────────────────────────────────────

    def _build_general_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "General")
        s   = self._cfg.app_settings

        box.append(self._section_label("Session"))

        # Journal folder
        jf_entry = Gtk.Entry()
        jf_entry.set_text(s.get("JournalFolder", ""))
        jf_entry.set_hexpand(True)
        jf_entry.set_width_chars(28)
        jf_entry.connect("changed", lambda w: self._track("JournalFolder", w.get_text()))
        box.append(self._row("Journal Folder", jf_entry, restart_required=True))

        # UTC toggle
        utc_sw = Gtk.Switch()
        utc_sw.set_active(bool(s.get("UseUTC", False)))
        utc_sw.set_valign(Gtk.Align.CENTER)
        utc_sw.connect("state-set", lambda w, v: self._track("UseUTC", v))
        box.append(self._row("Use UTC Timestamps", utc_sw))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Display"))

        # Truncate names
        trunc_spin = Gtk.SpinButton.new_with_range(10, 100, 1)
        trunc_spin.set_value(int(s.get("TruncateNames", 30)))
        trunc_spin.set_valign(Gtk.Align.CENTER)
        trunc_spin.connect("value-changed", lambda w: self._track("TruncateNames", int(w.get_value())))
        box.append(self._row("Truncate Names (chars)", trunc_spin))

        # Pirate names
        pn_sw = Gtk.Switch()
        pn_sw.set_active(bool(s.get("PirateNames", False)))
        pn_sw.set_valign(Gtk.Align.CENTER)
        pn_sw.connect("state-set", lambda w, v: self._track("PirateNames", v))
        box.append(self._row("Show Pirate Names", pn_sw))

        # Bounty value
        bv_sw = Gtk.Switch()
        bv_sw.set_active(bool(s.get("BountyValue", False)))
        bv_sw.set_valign(Gtk.Align.CENTER)
        bv_sw.connect("state-set", lambda w, v: self._track("BountyValue", v))
        box.append(self._row("Show Credit Value per Kill", bv_sw))

        # Bounty faction
        bf_sw = Gtk.Switch()
        bf_sw.set_active(bool(s.get("BountyFaction", False)))
        bf_sw.set_valign(Gtk.Align.CENTER)
        bf_sw.connect("state-set", lambda w, v: self._track("BountyFaction", v))
        box.append(self._row("Show Victim Faction per Kill", bf_sw))

        # Extended stats
        es_sw = Gtk.Switch()
        es_sw.set_active(bool(s.get("ExtendedStats", False)))
        es_sw.set_valign(Gtk.Align.CENTER)
        es_sw.connect("state-set", lambda w, v: self._track("ExtendedStats", v))
        box.append(self._row("Extended Kill Stats", es_sw))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Inactivity Alerts"))

        # WarnNoKills
        wnk_spin = Gtk.SpinButton.new_with_range(1, 120, 1)
        wnk_spin.set_value(int(s.get("WarnNoKills", 20)))
        wnk_spin.set_valign(Gtk.Align.CENTER)
        wnk_spin.connect("value-changed", lambda w: self._track("WarnNoKills", int(w.get_value())))
        box.append(self._row("Alert After N Minutes Without Kill", wnk_spin))

        # WarnKillRate
        wkr_spin = Gtk.SpinButton.new_with_range(1, 200, 1)
        wkr_spin.set_value(int(s.get("WarnKillRate", 20)))
        wkr_spin.set_valign(Gtk.Align.CENTER)
        wkr_spin.connect("value-changed", lambda w: self._track("WarnKillRate", int(w.get_value())))
        box.append(self._row("Alert When Kill Rate Below (kills/hr)", wkr_spin))

        # WarnCooldown
        wcd_spin = Gtk.SpinButton.new_with_range(1, 120, 1)
        wcd_spin.set_value(int(s.get("WarnCooldown", 15)))
        wcd_spin.set_valign(Gtk.Align.CENTER)
        wcd_spin.connect("value-changed", lambda w: self._track("WarnCooldown", int(w.get_value())))
        box.append(self._row("Alert Cooldown (minutes)", wcd_spin))

    # ── Notifications tab ─────────────────────────────────────────────────────

    def _build_notifications_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Notifications")
        levels = self._cfg.notify_levels

        box.append(self._section_label("Notification Levels"))

        note = Gtk.Label(label="0 = Off   1 = Terminal   2 = + Discord   3 = + Ping")
        note.set_xalign(0.0)
        note.add_css_class("prefs-note")
        box.append(note)

        for key, description in NOTIFY_EVENTS:
            spin = Gtk.SpinButton.new_with_range(0, 3, 1)
            spin.set_value(int(levels.get(key, 2)))
            spin.set_width_chars(2)
            spin.set_valign(Gtk.Align.CENTER)
            spin.connect("value-changed",
                         lambda w, k=key: self._track_notify(k, int(w.get_value())))
            box.append(self._row(description, spin))

    # ── Discord tab ───────────────────────────────────────────────────────────

    def _build_discord_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Discord")
        d   = self._cfg.discord_cfg

        box.append(self._section_label("Connection"))

        wh_entry = Gtk.Entry()
        wh_entry.set_text(d.get("WebhookURL", ""))
        wh_entry.set_hexpand(True)
        wh_entry.set_width_chars(32)
        wh_entry.set_visibility(False)   # treat as sensitive
        wh_entry.connect("changed", lambda w: self._track_discord("WebhookURL", w.get_text()))
        box.append(self._row("Webhook URL", wh_entry, restart_required=True))

        uid_entry = Gtk.Entry()
        uid_entry.set_text(str(d.get("UserID", 0)))
        uid_entry.set_width_chars(20)
        uid_entry.connect("changed", lambda w: self._track_discord("UserID", w.get_text()))
        box.append(self._row("User ID (for @mention)", uid_entry, restart_required=True))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Options"))

        for key, label, hot in [
            ("Identity",        "Use EDMD name and avatar",    False),
            ("PrependCmdrName", "Prefix messages with CMDR name", True),
            ("Timestamp",       "Append timestamp to messages", False),
            ("ForumChannel",    "Forum channel thread mode",    False),
            ("ThreadCmdrNames", "Use CMDR name as thread title", False),
        ]:
            sw = Gtk.Switch()
            sw.set_active(bool(d.get(key, False)))
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("state-set", lambda w, v, k=key: self._track_discord(k, v))
            box.append(self._row(label, sw, restart_required=not hot))

    # ── Appearance tab ────────────────────────────────────────────────────────

    def _build_appearance_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Appearance")
        current_theme = self._cfg.gui_cfg.get("Theme", "default")

        box.append(self._section_label("Theme"))

        note = Gtk.Label(label="Theme changes take effect on next launch.")
        note.set_xalign(0.0)
        note.add_css_class("prefs-note")
        box.append(note)

        combo = Gtk.ComboBoxText()
        for t in THEMES:
            combo.append_text(t)
        # Add any custom themes found on disk
        from gui.helpers import THEMES_DIR
        custom_dir = THEMES_DIR / "custom"
        if custom_dir.is_dir():
            for f in sorted(custom_dir.glob("*.css")):
                combo.append_text(f"custom/{f.stem}")

        # Select current
        all_themes = THEMES + [
            f"custom/{f.stem}"
            for f in sorted((THEMES_DIR / "custom").glob("*.css"))
            if (THEMES_DIR / "custom").is_dir()
        ]
        try:
            combo.set_active(all_themes.index(current_theme))
        except ValueError:
            combo.set_active(0)

        combo.connect("changed",
                      lambda w: self._track_gui("Theme", w.get_active_text() or "default"))
        box.append(self._row("Active Theme", combo, restart_required=True))

    # ── Change tracking ───────────────────────────────────────────────────────

    def _track(self, key: str, value) -> None:
        self._changed.setdefault("Settings", {})[key] = value

    def _track_notify(self, key: str, value: int) -> None:
        self._changed.setdefault("LogLevels", {})[key] = value

    def _track_discord(self, key: str, value) -> None:
        self._changed.setdefault("Discord", {})[key] = value

    def _track_gui(self, key: str, value) -> None:
        self._changed.setdefault("GUI", {})[key] = value

    # ── Apply & Save ──────────────────────────────────────────────────────────

    def _on_apply(self, *_) -> None:
        """Write changes to config.toml, then force a hot-reload."""
        if not self._changed:
            self.close()
            return

        config_path = self._cfg.config_path
        try:
            raw = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(raw)
        except Exception as e:
            self._show_error(f"Could not read config.toml:\n{e}")
            return

        # Merge changes into the parsed config dict
        for section, kvs in self._changed.items():
            if section not in config:
                config[section] = {}
            for k, v in kvs.items():
                # UserID: store as int if possible
                if k == "UserID":
                    try: v = int(v)
                    except (ValueError, TypeError): v = 0
                config[section][k] = v

        # Write back — use a minimal TOML serializer
        try:
            new_toml = _dict_to_toml(config)
            config_path.write_text(new_toml, encoding="utf-8")
        except Exception as e:
            self._show_error(f"Could not write config.toml:\n{e}")
            return

        # Force hot-reload
        try:
            self._cfg.refresh(terminal_print=False)
        except Exception:
            pass

        self._changed.clear()
        self.close()

    def _show_error(self, msg: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        dlg.connect("response", lambda d, *_: d.close())
        dlg.present()


# ── Minimal TOML writer ───────────────────────────────────────────────────────

def _dict_to_toml(d: dict) -> str:
    """
    Write a flat-section TOML dict back to a string.
    Handles: str, int, float, bool, nested one-level dicts (sections).
    Sufficient for EDMD's config.toml structure.
    """
    lines = []

    def _val(v) -> str:
        if isinstance(v, bool):  return "true" if v else "false"
        if isinstance(v, int):   return str(v)
        if isinstance(v, float): return str(v)
        # string — escape backslashes and quotes
        escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    # Top-level scalar keys first
    for k, v in d.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_val(v)}")

    # Sections
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"\n[{k}]")
            for sk, sv in v.items():
                lines.append(f"{sk} = {_val(sv)}")

    return "\n".join(lines) + "\n"
