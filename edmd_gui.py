"""
edmd_gui.py -- GTK4 graphical interface for Elite Dangerous Monitor Daemon

Layout:
  Left: Event Log (scrolling, live)
  Right panels (top to bottom):
    Commander | Crew | Mission Stack | Session Stats

Architecture:
  - Monitor runs on a background thread (see edmd.py)
  - GUI runs on GTK main thread
  - Communication via thread-safe queue: gui_queue
  - GLib.idle_add() polls the queue and updates widgets safely
"""

import signal
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib, Gdk, Pango
except ImportError:
    raise ImportError(
        "PyGObject not found. Install with: pacman -S python-gobject gtk4\n"
        "  or: pip install PyGObject"
    )


# ── Powerplay 2.0 rank helpers ───────────────────────────────────────────────

def pp_merits_for_rank(rank: int) -> int:
    """Return total cumulative merits required to reach the given rank.
    Formula verified against published Powerplay 2.0 tables:
      Ranks 1-5: fixed thresholds (0, 2000, 5000, 9000, 15000)
      Ranks 6-100: 15000 + (rank-5) * 8000
      Ranks 100+:  775000 + (rank-100) * 8000
    """
    if rank <= 1:  return 0
    if rank == 2:  return 2_000
    if rank == 3:  return 5_000
    if rank == 4:  return 9_000
    if rank == 5:  return 15_000
    if rank <= 100: return 15_000 + (rank - 5) * 8_000
    return 775_000 + (rank - 100) * 8_000


def pp_rank_progress(rank: int, total_merits: int) -> tuple:
    """Return (fraction 0.0-1.0, merits_in_rank, merits_needed, next_rank)
    for a given rank and total merit count."""
    floor = pp_merits_for_rank(rank)
    ceil  = pp_merits_for_rank(rank + 1)
    span  = ceil - floor
    earned = max(0, total_merits - floor)
    fraction = min(1.0, earned / span) if span > 0 else 1.0
    return fraction, earned, span, rank + 1


RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


# ── Theme loader ──────────────────────────────────────────────────────────────

THEMES_DIR = Path(__file__).parent / "themes"

def load_theme(theme_name: str) -> str:
    """Load base.css (structure) + palette CSS for the named theme.

    Theme files now contain only colour variable definitions (:root { }).
    base.css holds all structural rules and references those variables.
    Falls back to default.css palette if the named theme is not found.
    """
    base_file = THEMES_DIR / "base.css"
    palette_file = THEMES_DIR / f"{theme_name}.css"

    if not palette_file.is_file():
        palette_file = THEMES_DIR / "default.css"

    parts = []
    for path in (base_file, palette_file):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    return "\n".join(parts)


def apply_theme(theme_name: str) -> None:
    """Apply named CSS theme to the GTK display."""
    css = load_theme(theme_name)
    provider = Gtk.CssProvider()
    if css:
        provider.load_from_string(css)
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


# ── Helper widgets ────────────────────────────────────────────────────────────

def make_label(text="", css_class=None, xalign=0.0, wrap=False):
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(xalign)
    lbl.set_wrap(wrap)
    if css_class:
        for cls in (css_class if isinstance(css_class, list) else [css_class]):
            lbl.add_css_class(cls)
    return lbl


def make_section(title: str, title_widget=None) -> tuple:
    """Return (outer Box, inner Box) for a labelled panel section.
    If title_widget is given it replaces the plain text header."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    outer.add_css_class("panel-section")

    if title_widget is not None:
        header = title_widget
    else:
        header = Gtk.Label(label=title)
        header.set_xalign(0.0)
    header.add_css_class("section-header")
    outer.append(header)

    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    sep.add_css_class("section-sep")
    outer.append(sep)

    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    inner.add_css_class("section-body")
    outer.append(inner)

    return outer, inner


def make_row(label_text: str, value_text: str = "—") -> tuple:
    """Return (row Box, value Label) for a key/value display row."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.add_css_class("data-row")

    key = make_label(label_text, css_class="data-key")
    key.set_hexpand(False)
    row.append(key)

    val = make_label(value_text, css_class="data-value")
    val.set_hexpand(True)
    val.set_xalign(1.0)
    row.append(val)

    return row, val


def _hull_css(pct: int) -> str:
    """Return hull/shield CSS class name based on percentage."""
    if pct > 75:
        return "health-good"
    elif pct >= 25:
        return "health-warn"
    else:
        return "health-crit"


def _set_health_label(label: Gtk.Label, pct: int | None, suffix="%"):
    """Set a health label text and apply colour class."""
    for cls in ("health-good", "health-warn", "health-crit"):
        label.remove_css_class(cls)
    if pct is None:
        label.set_label("—")
    else:
        label.set_label(f"{pct}{suffix}")
        label.add_css_class(_hull_css(pct))


def _fmt_shield(shields_up, recharging: bool) -> str:
    """Return human-readable shield status string (no pct — not available from logs)."""
    if shields_up is None:
        return "—"
    if shields_up:
        return "Up"
    if recharging:
        return "Recharging"
    return "Down"


def _fmt_crew_active(delta) -> str:
    """Format a timedelta as human-readable crew active duration.
    Always shows the two most significant non-zero units, to the nearest
    complete day.  Examples: '3y 5mo', '11mo 23d', '45d', '<1d'"""
    total_days = int(delta.total_seconds() // 86400)
    if total_days < 1:
        return "<1d"
    years, rem_days = divmod(total_days, 365)
    months, days = divmod(rem_days, 30)
    parts = []
    if years:
        parts.append(f"{years}y")
    if months:
        parts.append(f"{months}mo")
    if days and len(parts) < 2:
        parts.append(f"{days}d")
    return " ".join(parts) if parts else f"{total_days}d"


# ── Main window ───────────────────────────────────────────────────────────────

class EdmdWindow(Gtk.ApplicationWindow):

    POLL_MS = 100   # queue poll interval in milliseconds

    def __init__(self, app, state, active_session, gui_queue, gui_cfg,
                 program, version, fmt_credits, fmt_duration, rate_per_hour):
        super().__init__(application=app, title=f"{program} v{version}")
        # Explicitly set WM title so i3 and other EWMH WMs see _NET_WM_NAME.
        # WM_CLASS is set at module level via GLib.set_prgname / set_application_name.
        self.set_title(f"{program} v{version}")

        self.state          = state
        self.session        = active_session
        self.gui_queue      = gui_queue
        self.gui_cfg        = gui_cfg
        self.fmt_credits    = fmt_credits
        self.fmt_duration   = fmt_duration
        self.rate_per_hour  = rate_per_hour
        self.program        = program
        self.version        = version
        self._session_start_mono = None   # for live duration display

        self.set_default_size(1280, 720)
        self.add_css_class("edmd-window")

        self._build_ui(program, version)
        self._refresh_all_panels()

        # Poll queue every POLL_MS ms via GLib main loop
        GLib.timeout_add(self.POLL_MS, self._poll_queue)
        # Refresh stat counters every second
        GLib.timeout_add(1000, self._tick_stats)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, program, version):
        # ── Header bar with window controls ──────────────────────────────────
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)   # close / min / max from WM
        header.add_css_class("edmd-header")

        # Program title on the left — full name for clarity
        title_lbl = Gtk.Label(label=f"{program}  v{version}")
        title_lbl.add_css_class("header-title")
        header.pack_start(title_lbl)

        # Suppress the HeaderBar's built-in centre title widget
        header.set_title_widget(Gtk.Box())

        # Fullscreen toggle button on the right
        self._fs_button = Gtk.Button()
        self._fs_button.set_icon_name("view-fullscreen-symbolic")
        self._fs_button.set_tooltip_text("Toggle fullscreen (F11)")
        self._fs_button.connect("clicked", self._toggle_fullscreen)
        self._fs_button.add_css_class("flat")
        header.pack_end(self._fs_button)

        self.set_titlebar(header)
        self._is_fullscreen = False

        # F11 keyboard shortcut for fullscreen
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.add_css_class("root-box")
        self.set_child(root)

        # ── Left: event log ──────────────────────────────────────────────────
        log_frame = Gtk.Frame()
        log_frame.add_css_class("log-frame")
        log_frame.set_hexpand(True)
        log_frame.set_vexpand(True)

        log_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        log_frame.set_child(log_outer)

        log_header = make_label("  Event Log", css_class="log-header")
        log_outer.append(log_header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("log-scroll")

        self._log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self._log_box.add_css_class("log-inner")
        self._log_box.set_valign(Gtk.Align.END)  # new entries appear at bottom

        scroll.set_child(self._log_box)
        log_outer.append(scroll)
        self._log_scroll = scroll

        root.append(log_frame)

        # ── Right: panels ────────────────────────────────────────────────────
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("right-panel")
        panel.set_vexpand(True)

        panel_scroll = Gtk.ScrolledWindow()
        panel_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel_scroll.set_vexpand(True)
        panel_scroll.set_size_request(340, -1)  # fixed width; height unconstrained
        panel_scroll.set_hexpand(False)
        panel_scroll.set_child(panel)
        panel_scroll.add_css_class("panel-scroll")

        root.append(panel_scroll)

        self._build_cmdr_panel(panel)
        self._build_crew_panel(panel)
        self._build_mission_panel(panel)
        self._build_stats_panel(panel)
        self._build_sponsor_panel(panel)

    def _build_cmdr_panel(self, parent):
        """Commander block — two-line header, reordered rows, shields at bottom."""
        # ── Two-line header ────────────────────────────────────────────────
        hdr_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        # Line 1: CMDR name left, ship type right
        hdr_line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cmdr_header_lbl = Gtk.Label(label="Commander")
        self._cmdr_header_lbl.set_xalign(0.0)
        self._cmdr_header_lbl.set_hexpand(True)
        hdr_line1.append(self._cmdr_header_lbl)
        self._cmdr_ship_type_hdr = Gtk.Label(label="")
        self._cmdr_ship_type_hdr.set_xalign(1.0)
        hdr_line1.append(self._cmdr_ship_type_hdr)
        hdr_outer.append(hdr_line1)

        # Line 2: ship name | ident, right-aligned (hidden when neither is set)
        self._cmdr_ship_ident_hdr = Gtk.Label(label="")
        self._cmdr_ship_ident_hdr.set_xalign(1.0)
        self._cmdr_ship_ident_hdr.set_visible(False)
        hdr_outer.append(self._cmdr_ship_ident_hdr)

        section, body = make_section("", title_widget=hdr_outer)
        self._cmdr_section = section
        parent.append(section)

        # ── Data rows: mode → rank → location → power → health ────────────
        for lbl_text, attr in [
            ("Mode",        "_cmdr_mode"),
            ("Combat Rank", "_cmdr_rank"),
            ("System",      "_cmdr_system"),
            ("Body",        "_cmdr_location"),
            ("Power",       "_cmdr_pp"),
            ("PP Rank",     "_cmdr_pprank"),
        ]:
            row, val = make_row(lbl_text)
            setattr(self, attr, val)
            body.append(row)

        # PP progress bar (immediately below PP Rank)
        self._pp_rank_bar = Gtk.ProgressBar()
        self._pp_rank_bar.set_fraction(0.0)
        self._pp_rank_bar.add_css_class("pp-rank-bar")
        self._pp_rank_bar.set_show_text(False)
        bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar_box.add_css_class("pp-rank-bar-row")
        bar_box.append(self._pp_rank_bar)
        self._pp_rank_bar.set_hexpand(True)
        body.append(bar_box)

        # Shields | Hull — always last; highest urgency during combat
        row_sh = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row_sh.add_css_class("data-row")
        key_sh = make_label("Shields | Hull", css_class="data-key")
        key_sh.set_hexpand(False)
        row_sh.append(key_sh)
        self._cmdr_health = make_label("— | —", css_class="data-value")
        self._cmdr_health.set_hexpand(True)
        self._cmdr_health.set_xalign(1.0)
        row_sh.append(self._cmdr_health)
        body.append(row_sh)
    def _build_crew_panel(self, parent):
        """CREW block — absorbs SLF status. Hidden when no active crew.

        Header:  CREW: <name>              <SLF type>  (right; hidden when no bay)
        ──────────────────────────────────────────────────────
        Rank       Competent
        Hired      14 Mar 2025
        Active     312 days
        Paid       ≥ 48.3M Cr
        SLF        SLF Docked / Hull 72% / Destroyed / All Spent

        When CMDR is in the SLF, crew flies the mothership:
          Header reads:  CREW: <name>  [Flying <ship type>]
          SLF row shows: CMDR Aboard | Hull <n>%
        """
        # Header: crew name left, SLF type right
        hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._crew_header_lbl = Gtk.Label(label="CREW")
        self._crew_header_lbl.set_xalign(0.0)
        self._crew_header_lbl.set_hexpand(True)
        hdr_box.append(self._crew_header_lbl)
        self._crew_slf_type_hdr = Gtk.Label(label="")
        self._crew_slf_type_hdr.set_xalign(1.0)
        hdr_box.append(self._crew_slf_type_hdr)

        section, body = make_section("", title_widget=hdr_box)
        self._crew_section = section
        parent.append(section)

        for lbl_text, attr in [
            ("Rank",   "_crew_rank_lbl"),
            ("Hired",  "_crew_hired_lbl"),
            ("Active", "_crew_active_lbl"),
            ("Paid",   "_crew_paid_lbl"),
            ("SLF",    "_crew_slf_status"),
        ]:
            row, val = make_row(lbl_text)
            setattr(self, attr, val)
            body.append(row)

        # Hidden by default until crew is active
        section.set_visible(False)
    def _build_mission_panel(self, parent):
        section, body = make_section("Mission Stack")
        parent.append(section)

        row, self._miss_value = make_row("Stack Value")
        body.append(row)

        row_p = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row_p.add_css_class("data-row")
        self._miss_progress_key = make_label("Completed", css_class="data-key")
        self._miss_progress_key.set_hexpand(False)
        row_p.append(self._miss_progress_key)
        self._miss_progress = make_label("—", css_class="data-value")
        self._miss_progress.set_hexpand(True)
        self._miss_progress.set_xalign(1.0)
        row_p.append(self._miss_progress)
        body.append(row_p)

        # Kill tracking header
        kill_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        kill_header.add_css_class("data-row")
        lbl_tf = make_label("Target Faction", css_class="data-key")
        lbl_tf.set_hexpand(True)
        lbl_tf.set_xalign(0.0)
        kill_header.append(lbl_tf)
        lbl_kn = make_label("Kills Needed", css_class="data-key")
        lbl_kn.set_hexpand(False)
        lbl_kn.set_xalign(1.0)
        kill_header.append(lbl_kn)
        body.append(kill_header)
        # Dynamic rows — one per target faction, rebuilt on each update
        self._kill_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.append(self._kill_rows_box)

    def _build_stats_panel(self, parent):
        section, body = make_section("Session Stats")
        parent.append(section)

        # Duration on its own row — right-aligned value
        row, self._stat_duration = make_row("Duration")
        body.append(row)

        # Stat rows: each is a single monospace label that spans the full width,
        # right-aligned.  _refresh_stats formats them with padded columns so the
        # pipe delimiters align across all three rows.
        for key_text, attr in [
            ("Kills",   "_stat_line_kills"),
            ("Bounties", "_stat_line_credits"),
            ("Merits",  "_stat_line_merits"),
        ]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.add_css_class("data-row")
            key = make_label(key_text, css_class="data-key")
            key.set_hexpand(False)
            row.append(key)
            lbl = Gtk.Label(label="—")
            lbl.add_css_class("stat-line")
            lbl.set_hexpand(True)
            lbl.set_xalign(1.0)
            row.append(lbl)
            setattr(self, attr, lbl)
            body.append(row)

    def _build_sponsor_panel(self, parent):

        # ── Avatar mark — themed, above sponsor block ──────────────────────
        theme = self.gui_cfg.get("Theme", "default")
        _theme_avatar_map = {
            "default-blue":   "edmd_avatar_blue_512.png",
            "default-green":  "edmd_avatar_green_512.png",
            "default-purple": "edmd_avatar_purple_512.png",
            "default-red":    "edmd_avatar_red_512.png",
            "default-yellow": "edmd_avatar_yellow_512.png",
            "default-light":  "edmd_avatar_light_512.png",
        }
        avatar_file = _theme_avatar_map.get(theme, "edmd_avatar_512.png")
        avatar_path = Path(__file__).parent / "images" / avatar_file

        if avatar_path.exists():
            avatar_pic = Gtk.Picture.new_for_filename(str(avatar_path))
            avatar_pic.set_can_shrink(True)
            avatar_pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            avatar_pic.set_size_request(72, 72)
            avatar_pic.set_opacity(0.55)
            avatar_pic.set_halign(Gtk.Align.CENTER)
            avatar_pic.set_margin_top(4)
            avatar_pic.set_margin_bottom(2)
            parent.append(avatar_pic)

        # Outer box: vexpand so it pushes to the bottom of the panel
        section, body = make_section("Sponsoring Development")
        section.set_vexpand(True)
        section.set_valign(Gtk.Align.END)
        parent.append(section)

        # Single-line links separated by " | "
        link_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        link_row.add_css_class("sponsor-link-row")

        links = [
            ("☕ Ko-Fi",  "https://ko-fi.com/drworman"),
            ("💳 PayPal", "https://paypal.me/DavidWorman"),
            ("🐙 GitHub", "https://github.com/drworman/EDMD"),
        ]

        for i, (label_text, url) in enumerate(links):
            if i > 0:
                sep = make_label(" | ", css_class="sponsor-sep")
                link_row.append(sep)
            btn = Gtk.LinkButton(uri=url, label=label_text)
            btn.set_halign(Gtk.Align.START)
            btn.add_css_class("sponsor-link")
            link_row.append(btn)
            if url.startswith("https://github.com"):
                self._github_btn = btn

        body.append(link_row)

    # ── Panel refresh ─────────────────────────────────────────────────────────

    def _refresh_cmdr(self):
        s = self.state

        # ── Header line 1: CMDR name (left) + ship type (right) ───────────
        if s.pilot_name:
            if s.cmdr_in_slf:
                self._cmdr_header_lbl.set_label(f"CMDR {s.pilot_name}  [In Fighter]")
            else:
                self._cmdr_header_lbl.set_label(f"CMDR {s.pilot_name}")
        else:
            self._cmdr_header_lbl.set_label("Commander")
        self._cmdr_ship_type_hdr.set_label(s.pilot_ship or "")

        # ── Header line 2: ship name | ident (right-aligned) ──────────────
        parts = [p for p in [s.ship_name, s.ship_ident] if p]
        if parts:
            self._cmdr_ship_ident_hdr.set_label(" | ".join(parts))
            self._cmdr_ship_ident_hdr.set_visible(True)
        else:
            self._cmdr_ship_ident_hdr.set_visible(False)

        # ── Mode ───────────────────────────────────────────────────────────
        self._cmdr_mode.set_label(s.pilot_mode or "—")

        # ── Combat Rank ────────────────────────────────────────────────────
        rank = s.pilot_rank or "—"
        prog = f" +{s.pilot_rank_progress}%" if s.pilot_rank_progress is not None else ""
        self._cmdr_rank.set_label(f"{rank}{prog}")

        # ── System (hidden in supercruise with no system) ──────────────────
        if s.pilot_system:
            self._cmdr_system.set_label(s.pilot_system)
            self._cmdr_system.get_parent().set_visible(True)
        else:
            self._cmdr_system.set_label("—")
            self._cmdr_system.get_parent().set_visible(False)

        # ── Body (hidden when not near a body) ─────────────────────────────
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._cmdr_location.set_label(body_str or "—")
            self._cmdr_location.get_parent().set_visible(True)
        else:
            self._cmdr_location.set_label("—")
            self._cmdr_location.get_parent().set_visible(False)

        # ── Power + PP Rank + bar (all hidden when not pledged) ───────────
        has_power = bool(s.pp_power)
        self._cmdr_pp.get_parent().set_visible(has_power)
        self._cmdr_pprank.get_parent().set_visible(has_power)
        self._cmdr_pp.set_label(s.pp_power or "—")
        if s.pp_rank:
            merits = s.pp_merits_total
            if merits is not None:
                fraction, earned, span, next_rank = pp_rank_progress(s.pp_rank, merits)
                pct = int(fraction * 100)
                pp_rank_label = f"Rank {s.pp_rank}  {pct}%"
                tooltip = (
                    f"{earned:,} / {span:,} merits to Rank {next_rank} "
                    f"({span - earned:,} remaining)"
                )
            else:
                pp_rank_label = f"Rank {s.pp_rank}"
                fraction = 0.0
                tooltip = "Earn merits to populate progress"
            self._cmdr_pprank.set_label(pp_rank_label)
            self._pp_rank_bar.set_fraction(fraction)
            self._pp_rank_bar.set_tooltip_text(tooltip)
            self._pp_rank_bar.set_visible(True)
        else:
            self._cmdr_pprank.set_label("—")
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)

        # ── Shields | Hull (always shown) ─────────────────────────────────
        shield_str = _fmt_shield(s.ship_shields, s.ship_shields_recharging)
        hull_str = f"{s.ship_hull}%" if s.ship_hull is not None else "—"
        self._cmdr_health.set_label(f"{shield_str}  |  {hull_str}")
        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_health.remove_css_class(cls)
        if not s.ship_shields:
            self._cmdr_health.add_css_class("health-crit")
        elif s.ship_shields_recharging:
            self._cmdr_health.add_css_class("health-warn")
        else:
            hull_css = _hull_css(s.ship_hull) if s.ship_hull is not None else "health-good"
            self._cmdr_health.add_css_class(hull_css)
    def _refresh_crew(self):
        s = self.state
        has_crew = bool(s.crew_name) and s.crew_active
        self._crew_section.set_visible(has_crew)
        if not has_crew:
            return

        # ── Header: crew name (left) + SLF type (right) ───────────────────
        # When CMDR is in the SLF, crew flies the mothership — note that.
        if s.cmdr_in_slf:
            self._crew_header_lbl.set_label(
                f"CREW: {s.crew_name or 'NPC'}  [Flying {s.pilot_ship or 'Ship'}]"
            )
        else:
            self._crew_header_lbl.set_label(f"CREW: {s.crew_name or 'NPC'}")
        self._crew_slf_type_hdr.set_label(s.slf_type or "")

        # ── Rank ───────────────────────────────────────────────────────────
        rank_str = (
            RANK_NAMES[s.crew_rank]
            if s.crew_rank is not None and 0 <= s.crew_rank < len(RANK_NAMES)
            else "—"
        )
        self._crew_rank_lbl.set_label(rank_str)

        # ── Hired ─────────────────────────────────────────────────────────
        self._crew_hired_lbl.set_label(
            s.crew_hire_time.strftime("%d %b %Y") if s.crew_hire_time else "Unknown"
        )

        # ── Active duration ────────────────────────────────────────────────
        if s.crew_hire_time:
            self._crew_active_lbl.set_label(
                _fmt_crew_active(datetime.now(timezone.utc) - s.crew_hire_time)
            )
        else:
            self._crew_active_lbl.set_label("—")

        # ── Total paid ────────────────────────────────────────────────────
        if s.crew_total_paid is not None and s.crew_total_paid > 0:
            prefix = "" if s.crew_paid_complete else "≥ "
            self._crew_paid_lbl.set_label(f"{prefix}{self.fmt_credits(s.crew_total_paid)}")
        else:
            self._crew_paid_lbl.set_label("—")

        # ── SLF status (hidden when no bay fitted) ─────────────────────────
        has_bay = s.has_fighter_bay
        self._crew_slf_status.get_parent().set_visible(has_bay)
        if not has_bay:
            return

        for cls in ("health-good", "health-warn", "health-crit"):
            self._crew_slf_status.remove_css_class(cls)

        all_spent = (
            s.slf_stock_total > 0
            and s.slf_destroyed_count >= s.slf_stock_total
            and not s.slf_docked
            and not s.slf_deployed
        )

        if s.cmdr_in_slf:
            # CMDR is in the SLF; show hull from CMDR's perspective
            hull_str = f"{s.slf_hull}%" if s.slf_hull is not None else "—"
            self._crew_slf_status.set_label(f"CMDR Aboard  |  Hull {hull_str}")
            self._crew_slf_status.add_css_class(
                _hull_css(s.slf_hull) if s.slf_hull is not None else "health-good"
            )
        elif s.slf_docked:
            self._crew_slf_status.set_label("SLF Docked")
            self._crew_slf_status.add_css_class("health-good")
        elif s.slf_deployed:
            hull_str = f"Hull {s.slf_hull}%" if s.slf_hull is not None else "Hull —"
            self._crew_slf_status.set_label(hull_str)
            self._crew_slf_status.add_css_class(
                _hull_css(s.slf_hull) if s.slf_hull is not None else "health-good"
            )
        elif all_spent:
            self._crew_slf_status.set_label("All Spent")
            self._crew_slf_status.add_css_class("health-crit")
        else:
            # Destroyed, rebuilding not yet complete
            self._crew_slf_status.set_label("Destroyed")
            self._crew_slf_status.add_css_class("health-crit")
    def _refresh_vessel(self):
        """Vessel and SLF state now live in CMDR and CREW blocks respectively."""
        self._refresh_cmdr()
        self._refresh_crew()

    def _refresh_slf(self):
        """SLF state now lives in CREW block."""
        self._refresh_crew()
    def _refresh_missions(self):
        s = self.state
        if s.stack_value > 0:
            total = len(s.active_missions)
            done  = s.missions_complete
            rem   = total - done

            self._miss_value.set_label(self.fmt_credits(s.stack_value))

            if rem == 0:
                self._miss_progress_key.set_label("Complete")
                self._miss_progress.set_label(f"{done}/{total}")
                self._miss_progress.remove_css_class("status-active")
                self._miss_progress.add_css_class("status-ready")
                self._miss_progress_key.remove_css_class("status-active")
                self._miss_progress_key.add_css_class("status-ready")
            else:
                self._miss_progress_key.set_label("Completed")
                self._miss_progress.set_label(f"{done}/{total}")
                self._miss_progress.remove_css_class("status-ready")
                self._miss_progress.add_css_class("status-active")
                self._miss_progress_key.remove_css_class("status-ready")
                self._miss_progress_key.add_css_class("status-active")

            # Kill tracking rows — one per target faction, alpha sorted
            while self._kill_rows_box.get_first_child():
                self._kill_rows_box.remove(self._kill_rows_box.get_first_child())
            if s.target_kill_totals:
                for target in sorted(s.target_kill_totals):
                    total    = s.target_kill_totals[target]
                    credited = s.target_kills_credited.get(target, 0)
                    remaining = max(0, total - credited)
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    row.add_css_class("data-row")
                    lbl_name = make_label(target, css_class="data-value")
                    lbl_name.set_hexpand(True)
                    lbl_name.set_xalign(0.0)
                    lbl_name.set_ellipsize(Pango.EllipsizeMode.END)
                    row.append(lbl_name)
                    lbl_val = make_label(f"{remaining:,} kills", css_class="data-value")
                    lbl_val.set_hexpand(False)
                    lbl_val.set_xalign(1.0)
                    row.append(lbl_val)
                    self._kill_rows_box.append(row)
        else:
            for w in [self._miss_value, self._miss_progress]:
                w.set_label("—")
            self._miss_progress_key.set_label("Completed")
            for w in [self._miss_progress, self._miss_progress_key]:
                w.remove_css_class("status-ready")
                w.remove_css_class("status-active")

    def _refresh_stats(self):
        s   = self.state
        ses = self.session

        duration = 0
        if s.session_start_time and s.event_time:
            duration = (s.event_time - s.session_start_time).total_seconds()

        self._stat_duration.set_label(self.fmt_duration(duration))

        # Compute raw totals and rates
        kills_total = str(ses.kills)
        if ses.kills > 0 and duration > 0:
            kph = self.rate_per_hour(duration / ses.kills, 1)
            kills_rate = f"{kph}"
        else:
            kills_rate = "—"

        cred_total = self.fmt_credits(ses.credit_total)
        if ses.credit_total > 0 and duration > 0:
            cph = self.rate_per_hour(duration / ses.credit_total, 2)
            cred_rate = f"{self.fmt_credits(cph)}"
        else:
            cred_rate = "—"

        merit_total = str(ses.merits)
        if ses.merits > 0 and duration > 0:
            mph = self.rate_per_hour(duration / ses.merits, 1)
            merit_rate = f"{mph}"
        else:
            merit_rate = "—"

        # Align columns: pad totals so pipe is at same position across all three rows,
        # then pad rates so /hr suffix aligns too.
        totals = [kills_total, cred_total, merit_total]
        rates  = [kills_rate,  cred_rate,  merit_rate]
        tw = max(len(t) for t in totals)   # widest total
        rw = max(len(r) for r in rates)    # widest rate

        def _fmt_stat_line(total, rate):
            return f"{total:>{tw}}  |  {rate:>{rw}} /hr"

        self._stat_line_kills.set_label(  _fmt_stat_line(kills_total, kills_rate))
        self._stat_line_credits.set_label(_fmt_stat_line(cred_total,  cred_rate))
        self._stat_line_merits.set_label( _fmt_stat_line(merit_total, merit_rate))

    def _refresh_all_panels(self):
        self._refresh_cmdr()
        self._refresh_crew()
        self._refresh_missions()
        self._refresh_stats()

    # ── Event log ─────────────────────────────────────────────────────────────

    def _append_log(self, text: str):
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        lbl.set_wrap(False)
        lbl.set_selectable(True)
        lbl.add_css_class("log-entry")
        self._log_box.append(lbl)

        # Auto-scroll to bottom via GLib idle (after widget is laid out)
        GLib.idle_add(self._scroll_to_bottom)

        # Trim log to 2000 entries
        children = []
        child = self._log_box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        if len(children) > 2000:
            self._log_box.remove(children[0])

    def _toggle_fullscreen(self, *_):
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

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_F11:
            self._toggle_fullscreen()
            return True
        return False

    def _scroll_to_bottom(self):
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False  # don't repeat

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        """Drain the gui_queue and dispatch updates. Called every POLL_MS ms."""
        try:
            while True:
                msg_type, payload = self.gui_queue.get_nowait()

                if msg_type == "log":
                    self._append_log(payload)

                elif msg_type == "cmdr_update":
                    self._refresh_cmdr()

                elif msg_type == "crew_update":
                    self._refresh_crew()

                elif msg_type == "vessel_update":
                    self._refresh_vessel()

                elif msg_type == "slf_update":
                    self._refresh_slf()

                elif msg_type == "mission_update":
                    self._refresh_missions()

                elif msg_type == "stats_update":
                    self._refresh_stats()

                elif msg_type == "all_update":
                    self._refresh_all_panels()

                elif msg_type == "update_notice":
                    self._show_update_notice(payload)

        except Exception:
            pass  # queue.Empty or shutdown race — normal

        return True  # keep timer running

    def _show_update_notice(self, version: str):
        """Replace the GitHub link row with an Upgrade button when a new version is available."""
        import sys, os
        try:
            # Append an Upgrade button after the existing link row
            upgrade_btn = Gtk.Button(label=f"⬆  Upgrade to v{version}")
            upgrade_btn.add_css_class("upgrade-btn")
            upgrade_btn.set_margin_top(4)
            upgrade_btn.set_tooltip_text(
                "Pull latest version from GitHub and restart EDMD automatically"
            )

            def _do_upgrade(_btn):
                # Save session state before replacing the process
                try:
                    from edmd import save_session_state, journal_file, state
                    if state.session_start_time and journal_file:
                        save_session_state(journal_file)
                except Exception:
                    pass
                # Replace this process with edmd.py --upgrade (strips any existing --upgrade)
                new_argv = [a for a in sys.argv if a != "--upgrade"] + ["--upgrade"]
                os.execv(sys.executable, [sys.executable] + new_argv)

            upgrade_btn.connect("clicked", _do_upgrade)

            # Insert below sponsor link row — find the link_row's parent
            link_row = self._github_btn.get_parent()
            if link_row and link_row.get_parent():
                link_row.get_parent().append(upgrade_btn)
                self._upgrade_btn = upgrade_btn

            # Also update the GitHub button label
            self._github_btn.set_label(f"🐙  GitHub  (v{version} available)")
            self._github_btn.add_css_class("update-available")
        except Exception:
            pass  # graceful degradation — update notice is informational

    def _tick_stats(self):
        """Refresh stats, crew active timer, and missions every second."""
        self._refresh_stats()
        self._refresh_missions()
        self._refresh_crew()
        return True  # keep timer running


# ── Application ───────────────────────────────────────────────────────────────

# Set WM_CLASS before the application starts so i3 and other WMs can match on it.
# WM_CLASS will be ("edmd", "EDMD") — use either in i3 assign rules:
#   assign [class="EDMD"] workspace 2
#   assign [instance="edmd"] workspace 2
GLib.set_prgname("edmd")
GLib.set_application_name("EDMD")


class EdmdApp(Gtk.Application):

    def __init__(self, state, active_session, gui_queue, gui_cfg,
                 program, version, fmt_credits, fmt_duration, rate_per_hour):
        super().__init__(application_id="com.drworman.edmd")

        self._kwargs = dict(
            state=state,
            active_session=active_session,
            gui_queue=gui_queue,
            gui_cfg=gui_cfg,
            program=program,
            version=version,
            fmt_credits=fmt_credits,
            fmt_duration=fmt_duration,
            rate_per_hour=rate_per_hour,
        )
        self._theme = gui_cfg.get("Theme", "default")

    def do_activate(self):
        apply_theme(self._theme)
        win = EdmdWindow(app=self, **self._kwargs)
        win.present()

        # Handle Ctrl+C cleanly - quit the GTK app without a traceback
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        # GLib needs a periodic wakeup to notice the signal
        GLib.timeout_add(200, lambda: True)

