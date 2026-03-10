"""
gui/blocks/commander.py — Commander, ship, location, powerplay, and hull block.

Mirrors _build_cmdr_panel / _refresh_cmdr from the original edmd_gui.py exactly.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget
from gui.helpers    import hull_css, fmt_shield, pp_rank_progress


class CommanderBlock(BlockWidget):
    BLOCK_TITLE = "Commander"
    BLOCK_CSS   = "commander-block"

    def build(self, parent: Gtk.Box) -> None:
        # ── Two-line header ───────────────────────────────────────────────────
        hdr_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        # Line 1: CMDR name (left) + ship type (right)
        hdr_line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cmdr_header_lbl = Gtk.Label(label="Commander")
        self._cmdr_header_lbl.set_xalign(0.0)
        self._cmdr_header_lbl.set_hexpand(True)
        hdr_line1.append(self._cmdr_header_lbl)
        self._cmdr_ship_type_hdr = Gtk.Label(label="")
        self._cmdr_ship_type_hdr.set_xalign(1.0)
        hdr_line1.append(self._cmdr_ship_type_hdr)
        hdr_outer.append(hdr_line1)

        # Line 2: ship name | ident (right-aligned; hidden when neither set)
        self._cmdr_ship_ident_hdr = Gtk.Label(label="")
        self._cmdr_ship_ident_hdr.set_xalign(1.0)
        self._cmdr_ship_ident_hdr.set_visible(False)
        hdr_outer.append(self._cmdr_ship_ident_hdr)

        body = self._build_section(parent, title_widget=hdr_outer)

        # ── Data rows ─────────────────────────────────────────────────────────
        for lbl_text, attr in [
            ("Mode",        "_cmdr_mode"),
            ("Combat Rank", "_cmdr_rank"),
            ("System",      "_cmdr_system"),
            ("Body",        "_cmdr_location"),
            ("Fuel",        "_cmdr_fuel"),
            ("Power",       "_cmdr_pp"),
            ("PP Rank",     "_cmdr_pprank"),
        ]:
            row, val = self.make_row(lbl_text)
            setattr(self, attr, val)
            body.append(row)

        # PP progress bar (immediately below PP Rank row)
        self._pp_rank_bar = Gtk.ProgressBar()
        self._pp_rank_bar.set_fraction(0.0)
        self._pp_rank_bar.add_css_class("pp-rank-bar")
        self._pp_rank_bar.set_show_text(False)
        self._pp_rank_bar.set_size_request(40, 4)
        bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar_box.add_css_class("pp-rank-bar-row")
        bar_box.append(self._pp_rank_bar)
        self._pp_rank_bar.set_hexpand(True)
        body.append(bar_box)

        # Shields | Hull — always last; highest urgency during combat
        row_sh = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row_sh.add_css_class("data-row")
        key_sh = self.make_label("Shields | Hull", css_class="data-key")
        key_sh.set_hexpand(False)
        row_sh.append(key_sh)
        self._cmdr_health = self.make_label("— | —", css_class="data-value")
        self._cmdr_health.set_hexpand(True)
        self._cmdr_health.set_xalign(1.0)
        row_sh.append(self._cmdr_health)
        body.append(row_sh)

    def refresh(self) -> None:
        s = self.state

        # ── Header line 1: CMDR name / SLF indicator ─────────────────────────
        if s.pilot_name:
            if s.cmdr_in_slf:
                self._cmdr_header_lbl.set_label(f"CMDR {s.pilot_name}  [In Fighter]")
            else:
                self._cmdr_header_lbl.set_label(f"CMDR {s.pilot_name}")
        else:
            self._cmdr_header_lbl.set_label("Commander")
        self._cmdr_ship_type_hdr.set_label(s.pilot_ship or "")

        # ── Header line 2: ship name | ident ─────────────────────────────────
        parts = [p for p in [s.ship_name, s.ship_ident] if p]
        if parts:
            self._cmdr_ship_ident_hdr.set_label(" | ".join(parts))
            self._cmdr_ship_ident_hdr.set_visible(True)
        else:
            self._cmdr_ship_ident_hdr.set_visible(False)

        # ── Mode ──────────────────────────────────────────────────────────────
        self._cmdr_mode.set_label(s.pilot_mode or "—")

        # ── Combat Rank ───────────────────────────────────────────────────────
        rank = s.pilot_rank or "—"
        prog = f" +{s.pilot_rank_progress}%" if s.pilot_rank_progress is not None else ""
        self._cmdr_rank.set_label(f"{rank}{prog}")

        # ── System (hidden when absent) ───────────────────────────────────────
        if s.pilot_system:
            self._cmdr_system.set_label(s.pilot_system)
            self._cmdr_system.get_parent().set_visible(True)
        else:
            self._cmdr_system.set_label("—")
            self._cmdr_system.get_parent().set_visible(False)

        # ── Body (hidden when absent) ─────────────────────────────────────────
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._cmdr_location.set_label(body_str or "—")
            self._cmdr_location.get_parent().set_visible(True)
        else:
            self._cmdr_location.set_label("—")
            self._cmdr_location.get_parent().set_visible(False)

        # ── Fuel ──────────────────────────────────────────────────────────────
        fuel_current = s.fuel_current
        fuel_tank    = s.fuel_tank_size
        if fuel_current is not None and fuel_tank and fuel_tank > 0:
            fuel_pct = fuel_current / fuel_tank * 100
            fuel_str = f"{fuel_pct:.0f}%"
            # Append time-to-dry if burn rate is known
            burn = getattr(s, "fuel_burn_rate", None)
            if burn and burn > 0:
                secs_remain = (fuel_current / burn) * 3600
                fuel_str += f"  (~{self.fmt_duration(int(secs_remain))})"
            self._cmdr_fuel.set_label(fuel_str)
            self._cmdr_fuel.get_parent().set_visible(True)
            # Colour matches alert thresholds
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

        # ── Powerplay (all hidden when not pledged) ───────────────────────────
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

        # ── Shields | Hull ────────────────────────────────────────────────────
        shield_str = fmt_shield(s.ship_shields, s.ship_shields_recharging)
        hull_str   = f"{s.ship_hull}%" if s.ship_hull is not None else "—"
        self._cmdr_health.set_label(f"{shield_str}  |  {hull_str}")

        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_health.remove_css_class(cls)
        if not s.ship_shields:
            self._cmdr_health.add_css_class("health-crit")
        elif s.ship_shields_recharging:
            self._cmdr_health.add_css_class("health-warn")
        else:
            hc = hull_css(s.ship_hull) if s.ship_hull is not None else "health-good"
            self._cmdr_health.add_css_class(hc)

    def cleanup(self) -> None:
        """Zero the progress bar fraction before window teardown.
        Must be called from the window's close-request handler while the
        widget tree is still intact — prevents the GTK gizmo width warning."""
        if hasattr(self, "_pp_rank_bar"):
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)
