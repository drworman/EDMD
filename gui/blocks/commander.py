"""
gui/blocks/commander.py — Commander, ship, location, powerplay block.

Three-tab layout (matching Assets block pattern):
  Info  — ship identity, vitals (shields/hull/fuel), location, mode, powerplay
  Ranks — CAPI combat/trade/explore/CQC/mercenary/exobio ranks with progress
  Rep   — CAPI superpower reputation (Federation, Empire, Alliance, Independent)

Powerplay stays on the Info tab. Combat rank moves to Ranks tab.
Ranks and Rep tabs are CAPI-sourced; they stay hidden until first poll.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget
from gui.helpers    import hull_css, fmt_shield, pp_rank_progress

_TABS = [
    ("info",   "Info"),
    ("ranks",  "Ranks"),
    ("rep",    "Rep"),
]


class CommanderBlock(BlockWidget):
    BLOCK_TITLE = "Commander"
    BLOCK_CSS   = "commander-block"

    # ── Build ──────────────────────────────────────────────────────────────────

    def build(self, parent: Gtk.Box) -> None:
        # ── Two-line header ───────────────────────────────────────────────────
        hdr_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        hdr_line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cmdr_header_lbl = Gtk.Label(label="Commander")
        self._cmdr_header_lbl.set_xalign(0.0)
        self._cmdr_header_lbl.set_hexpand(True)
        hdr_line1.append(self._cmdr_header_lbl)
        self._cmdr_ship_type_hdr = Gtk.Label(label="")
        self._cmdr_ship_type_hdr.set_xalign(1.0)
        hdr_line1.append(self._cmdr_ship_type_hdr)
        hdr_outer.append(hdr_line1)

        self._cmdr_ship_ident_hdr = Gtk.Label(label="")
        self._cmdr_ship_ident_hdr.set_xalign(1.0)
        self._cmdr_ship_ident_hdr.set_visible(False)
        hdr_outer.append(self._cmdr_ship_ident_hdr)

        body = self._build_section(parent, title_widget=hdr_outer)

        # ── Tab scaffold ──────────────────────────────────────────────────────
        self._layout_stack = Gtk.Stack()
        self._layout_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._layout_stack.set_vexpand(True)
        self._layout_stack.set_hexpand(True)
        body.append(self._layout_stack)

        self._tab_btns:   dict[str, Gtk.Button] = {}
        self._active_tab: str = "info"

        self._build_tabbed_layout()
        self._layout_stack.set_visible_child_name("tabbed")

    # ── Tab scaffold ───────────────────────────────────────────────────────────

    def _build_tabbed_layout(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_vexpand(True)

        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.add_css_class("mat-tab-bar")
        page.append(tab_bar)
        page.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        stack.set_vexpand(True)
        stack.set_hexpand(True)
        page.append(stack)
        self._tab_stack = stack

        for cat, label in _TABS:
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            tab_bar.append(btn)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("mat-tab-label")
            btn.set_child(lbl)
            btn.connect("clicked", self._on_tab_click, cat)
            self._tab_btns[cat] = btn

            if cat == "info":
                tab_page = self._build_info_tab()
            elif cat == "ranks":
                tab_page = self._build_ranks_tab()
            else:
                tab_page = self._build_rep_tab()
            stack.add_named(tab_page, cat)

        self._set_active_tab("info")
        self._layout_stack.add_named(page, "tabbed")

    # ── Info tab ───────────────────────────────────────────────────────────────

    def _build_info_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(4)

        def _row(key_text):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            r.add_css_class("data-row")
            k = self.make_label(key_text, css_class="data-key")
            k.set_hexpand(False)
            r.append(k)
            v = self.make_label("—", css_class="data-value")
            v.set_hexpand(True)
            v.set_xalign(1.0)
            r.append(v)
            box.append(r)
            return r, v

        # Shields
        row_sh = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row_sh.add_css_class("data-row")
        row_sh.append(self.make_label("Shields", css_class="data-key"))
        self._cmdr_shields = self.make_label("—", css_class="data-value")
        self._cmdr_shields.set_hexpand(True)
        self._cmdr_shields.set_xalign(1.0)
        row_sh.append(self._cmdr_shields)
        box.append(row_sh)

        # Hull
        row_hull = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row_hull.add_css_class("data-row")
        row_hull.append(self.make_label("Hull", css_class="data-key"))
        self._cmdr_hull = self.make_label("—", css_class="data-value")
        self._cmdr_hull.set_hexpand(True)
        self._cmdr_hull.set_xalign(1.0)
        row_hull.append(self._cmdr_hull)
        box.append(row_hull)

        _, self._cmdr_fuel = _row("Fuel")

        vitals_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vitals_sep.add_css_class("vitals-sep")
        box.append(vitals_sep)

        _, self._cmdr_mode     = _row("Mode")
        _, self._cmdr_system   = _row("System")
        _, self._cmdr_location = _row("Body")
        _, self._cmdr_pp       = _row("Power")
        _, self._cmdr_pprank   = _row("PP Rank")

        # PP progress bar
        self._pp_rank_bar = Gtk.ProgressBar()
        self._pp_rank_bar.set_fraction(0.0)
        self._pp_rank_bar.add_css_class("pp-rank-bar")
        self._pp_rank_bar.set_show_text(False)
        self._pp_rank_bar.set_size_request(40, 4)
        bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar_box.add_css_class("pp-rank-bar-row")
        bar_box.append(self._pp_rank_bar)
        self._pp_rank_bar.set_hexpand(True)
        box.append(bar_box)

        return box

    # ── Ranks tab ──────────────────────────────────────────────────────────────

    def _build_ranks_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.set_margin_top(4)
        box.set_margin_end(12)   # clear GTK4 overlay scrollbar track
        scroll.set_child(box)

        self._no_ranks_lbl = Gtk.Label(label="Awaiting CAPI data…")
        self._no_ranks_lbl.add_css_class("data-key")
        self._no_ranks_lbl.set_xalign(0.5)
        self._no_ranks_lbl.set_margin_top(8)
        box.append(self._no_ranks_lbl)

        # dict: capi_key -> (row_box, value_label, progress_bar, bar_wrapper)
        self._rank_rows: dict = {}

        from core.state import CAPI_RANK_SKILLS
        for capi_key, display_label, _table in CAPI_RANK_SKILLS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.add_css_class("data-row")
            k = self.make_label(display_label, css_class="data-key")
            k.set_hexpand(False)
            row.append(k)
            v = self.make_label("—", css_class="data-value")
            v.set_hexpand(True)
            v.set_xalign(1.0)
            row.append(v)
            row.set_visible(False)
            box.append(row)

            bar = Gtk.ProgressBar()
            bar.set_fraction(0.0)
            bar.add_css_class("pp-rank-bar")
            bar.set_show_text(False)
            bar.set_size_request(40, 3)
            bar.set_hexpand(True)
            bar_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            bar_wrap.add_css_class("pp-rank-bar-row")
            bar_wrap.append(bar)
            bar_wrap.set_visible(False)
            box.append(bar_wrap)

            self._rank_rows[capi_key] = (row, v, bar, bar_wrap)

        return scroll

    # ── Rep tab ────────────────────────────────────────────────────────────────

    def _build_rep_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.set_margin_top(4)
        box.set_margin_end(12)   # clear GTK4 overlay scrollbar track
        scroll.set_child(box)

        self._no_rep_lbl = Gtk.Label(label="Awaiting login data…")
        self._no_rep_lbl.add_css_class("data-key")
        self._no_rep_lbl.set_xalign(0.5)
        self._no_rep_lbl.set_margin_top(8)
        box.append(self._no_rep_lbl)

        # ── Major factions ────────────────────────────────────────────────────
        major_hdr = Gtk.Label(label="MAJOR FACTIONS")
        major_hdr.add_css_class("section-sub-header")
        major_hdr.set_xalign(0.0)
        major_hdr.set_margin_top(4)
        major_hdr.set_margin_bottom(2)
        box.append(major_hdr)
        self._major_hdr = major_hdr

        self._rep_rows: dict[str, Gtk.Label] = {}
        for faction in ("Federation", "Empire", "Alliance", "Independent"):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.add_css_class("data-row")
            k = self.make_label(faction, css_class="data-key")
            k.set_hexpand(False)
            row.append(k)
            v = self.make_label("—", css_class="data-value")
            v.set_hexpand(True)
            v.set_xalign(1.0)
            row.append(v)
            row.set_visible(False)
            box.append(row)
            self._rep_rows[faction] = v

        # ── Minor factions (current system, populated from FSDJump/Location) ──
        minor_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        minor_sep.add_css_class("vitals-sep")
        minor_sep.set_margin_top(4)
        box.append(minor_sep)
        self._minor_sep = minor_sep

        minor_hdr = Gtk.Label(label="LOCAL FACTIONS")
        minor_hdr.add_css_class("section-sub-header")
        minor_hdr.set_xalign(0.0)
        minor_hdr.set_margin_top(2)
        minor_hdr.set_margin_bottom(2)
        box.append(minor_hdr)
        self._minor_hdr = minor_hdr

        self._minor_none_lbl = Gtk.Label(label="Jump to a system to see local standings")
        self._minor_none_lbl.add_css_class("data-key")
        self._minor_none_lbl.set_xalign(0.5)
        self._minor_none_lbl.set_wrap(True)
        self._minor_none_lbl.set_margin_top(4)
        box.append(self._minor_none_lbl)

        # Minor faction rows are built dynamically in refresh()
        self._minor_rep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._minor_rep_box.set_visible(False)
        box.append(self._minor_rep_box)
        self._minor_rep_rows: dict[str, Gtk.Label] = {}

        return scroll

    # ── Tab switching ──────────────────────────────────────────────────────────

    def _on_tab_click(self, _btn, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._tab_stack.set_visible_child_name(cat)
        for key, btn in self._tab_btns.items():
            if key == cat:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    def on_resize(self, w: int, h: int) -> None:
        super().on_resize(w, h)

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        s = self.state

        # ── Header ────────────────────────────────────────────────────────────
        if s.pilot_name:
            lbl = (f"CMDR {s.pilot_name}  [In Fighter]"
                   if s.cmdr_in_slf else f"CMDR {s.pilot_name}")
            self._cmdr_header_lbl.set_label(lbl)
        else:
            self._cmdr_header_lbl.set_label("Commander")
        self._cmdr_ship_type_hdr.set_label(s.pilot_ship or "")

        parts = [p for p in [s.ship_name, s.ship_ident] if p]
        if parts:
            self._cmdr_ship_ident_hdr.set_label(" | ".join(parts))
            self._cmdr_ship_ident_hdr.set_visible(True)
        else:
            self._cmdr_ship_ident_hdr.set_visible(False)

        # ── Info tab: Mode ────────────────────────────────────────────────────
        self._cmdr_mode.set_label(s.pilot_mode or "—")

        # ── Info tab: System ──────────────────────────────────────────────────
        if s.pilot_system:
            self._cmdr_system.set_label(s.pilot_system)
            self._cmdr_system.get_parent().set_visible(True)
        else:
            self._cmdr_system.set_label("—")
            self._cmdr_system.get_parent().set_visible(False)

        # ── Info tab: Body ────────────────────────────────────────────────────
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._cmdr_location.set_label(body_str or "—")
            self._cmdr_location.get_parent().set_visible(True)
        else:
            self._cmdr_location.set_label("—")
            self._cmdr_location.get_parent().set_visible(False)

        # ── Info tab: Fuel ────────────────────────────────────────────────────
        fuel_current = s.fuel_current
        fuel_tank    = s.fuel_tank_size
        if fuel_current is not None and fuel_tank and fuel_tank > 0:
            fuel_pct = fuel_current / fuel_tank * 100
            fuel_str = f"{fuel_pct:.0f}%"
            burn = getattr(s, "fuel_burn_rate", None)
            if burn and burn > 0:
                secs_remain = (fuel_current / burn) * 3600
                fuel_str += f"  (~{self.fmt_duration(int(secs_remain))})"
            self._cmdr_fuel.set_label(fuel_str)
            self._cmdr_fuel.get_parent().set_visible(True)
            from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD
            for cls in ("health-good", "health-warn", "health-crit"):
                self._cmdr_fuel.remove_css_class(cls)
            if fuel_current < fuel_tank * FUEL_CRIT_THRESHOLD:
                self._cmdr_fuel.add_css_class("health-crit")
            elif fuel_current < fuel_tank * FUEL_WARN_THRESHOLD:
                self._cmdr_fuel.add_css_class("health-warn")
            else:
                self._cmdr_fuel.add_css_class("health-good")
        else:
            self._cmdr_fuel.get_parent().set_visible(False)

        # ── Info tab: Powerplay ───────────────────────────────────────────────
        has_power = bool(s.pp_power)
        self._cmdr_pp.get_parent().set_visible(has_power)
        self._cmdr_pprank.get_parent().set_visible(has_power)
        self._cmdr_pp.set_label(s.pp_power or "—")

        if s.pp_rank:
            merits = s.pp_merits_total
            if merits is not None:
                fraction, earned, span, next_rank = pp_rank_progress(s.pp_rank, merits)
                pct     = int(fraction * 100)
                pp_lbl  = f"Rank {s.pp_rank}  {pct}%"
                tooltip = (
                    f"{earned:,} / {span:,} merits to Rank {next_rank} "
                    f"({span - earned:,} remaining)"
                )
            else:
                pp_lbl   = f"Rank {s.pp_rank}"
                fraction = 0.0
                tooltip  = "Earn merits to populate progress"
            self._cmdr_pprank.set_label(pp_lbl)
            self._pp_rank_bar.set_fraction(fraction)
            self._pp_rank_bar.set_tooltip_text(tooltip)
            self._pp_rank_bar.set_visible(True)
        else:
            self._cmdr_pprank.set_label("—")
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)

        # ── Info tab: Shields ─────────────────────────────────────────────────
        shield_str = fmt_shield(s.ship_shields, s.ship_shields_recharging)
        self._cmdr_shields.set_label(shield_str)
        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_shields.remove_css_class(cls)
        if s.ship_shields is None:
            pass  # leave unstyled
        elif not s.ship_shields:
            self._cmdr_shields.add_css_class(
                "health-warn" if s.ship_shields_recharging else "health-crit"
            )
        else:
            self._cmdr_shields.add_css_class("health-good")

        # ── Info tab: Hull ────────────────────────────────────────────────────
        hull_pct = s.ship_hull
        self._cmdr_hull.set_label(f"{hull_pct}%" if hull_pct is not None else "—")
        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_hull.remove_css_class(cls)
        if hull_pct is not None:
            self._cmdr_hull.add_css_class(hull_css(hull_pct))

        # ── Ranks tab ─────────────────────────────────────────────────────────
        capi_ranks    = getattr(s, "capi_ranks",    None)
        capi_progress = getattr(s, "capi_progress", None)
        has_ranks = bool(capi_ranks)
        self._no_ranks_lbl.set_visible(not has_ranks)

        if has_ranks:
            from core.state import CAPI_RANK_SKILLS
            for capi_key, _display, table in CAPI_RANK_SKILLS:
                row, v_lbl, bar, bar_wrap = self._rank_rows[capi_key]
                idx = capi_ranks.get(capi_key)
                if idx is None:
                    row.set_visible(False)
                    bar_wrap.set_visible(False)
                    continue
                rank_name = table[idx] if 0 <= idx < len(table) else str(idx)
                prog      = (capi_progress or {}).get(capi_key)
                pct_str   = f" +{prog}%" if prog is not None else ""
                v_lbl.set_label(f"{rank_name}{pct_str}")
                row.set_visible(True)
                if prog is not None:
                    bar.set_fraction(min(prog / 100.0, 1.0))
                    bar_wrap.set_visible(True)
                else:
                    bar_wrap.set_visible(False)

        # ── Rep tab ───────────────────────────────────────────────────────────
        # Major faction standing: Journal Reputation event (fired at login)
        pilot_rep = getattr(s, "pilot_reputation", None)
        has_rep   = bool(pilot_rep)
        self._no_rep_lbl.set_visible(not has_rep)
        self._major_hdr.set_visible(has_rep)
        self._minor_sep.set_visible(has_rep)
        self._minor_hdr.set_visible(has_rep)

        for faction, v_lbl in self._rep_rows.items():
            val = (pilot_rep or {}).get(faction)
            if val is not None:
                v_lbl.set_label(f"{val:.1f}%")
                v_lbl.get_parent().set_visible(True)
            else:
                v_lbl.get_parent().set_visible(False)

        # Minor/local faction standing: FSDJump/Location Factions[].MyReputation
        minor_rep = getattr(s, "pilot_minor_reputation", None)
        if minor_rep:
            self._minor_none_lbl.set_visible(False)
            self._minor_rep_box.set_visible(True)
            seen = set()
            for name, val in sorted(minor_rep.items(), key=lambda kv: -kv[1]):
                seen.add(name)
                if name not in self._minor_rep_rows:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                    row.add_css_class("data-row")
                    k = self.make_label(name, css_class="data-key")
                    k.set_hexpand(False)
                    row.append(k)
                    v = self.make_label("—", css_class="data-value")
                    v.set_hexpand(True)
                    v.set_xalign(1.0)
                    row.append(v)
                    self._minor_rep_box.append(row)
                    self._minor_rep_rows[name] = v
                self._minor_rep_rows[name].set_label(f"{val:.1f}%")
            # Hide rows for factions no longer in current system
            for name, v_lbl in self._minor_rep_rows.items():
                v_lbl.get_parent().set_visible(name in seen)
        else:
            self._minor_none_lbl.set_visible(has_rep)
            self._minor_rep_box.set_visible(False)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Zero all progress bars before window teardown — prevents GTK gizmo warning."""
        if hasattr(self, "_pp_rank_bar"):
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)
        if hasattr(self, "_rank_rows"):
            for _row, _lbl, bar, bar_wrap in self._rank_rows.values():
                bar.set_fraction(0.0)
                bar_wrap.set_visible(False)
