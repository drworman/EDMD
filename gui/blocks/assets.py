"""
gui/blocks/assets.py — Commander assets block widget.

Three-tab view: Wallet | Ships | Modules.

Ships tab
---------
Lists current ship (★) followed by stored ships.  Clicking any row opens a
Gtk.Popover showing type, name, ident, system, estimated value, and hot status.

Modules tab
-----------
Lists stored modules with their system location.  Clicking a row shows a
popover with full detail: slot, system, mass, value, hot status.

Wallet tab
----------
Live credit balance with ship and module counts as quick summary stats.

Data comes from MonitorState fields set by builtins/assets/plugin.py.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


_TABS = [
    ("wallet",  "Wallet"),
    ("ships",   "Ships"),
    ("modules", "Modules"),
    ("carrier", "Carrier"),
]


def _fmt_credits(val) -> str:
    if val is None:
        return "—"
    try:
        v = int(val)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


class AssetsBlock(BlockWidget):
    BLOCK_TITLE = "ASSETS"
    BLOCK_CSS   = "assets-block"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        self._layout_stack = Gtk.Stack()
        self._layout_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._layout_stack.set_vexpand(True)
        self._layout_stack.set_hexpand(True)
        body.append(self._layout_stack)

        self._tab_btns:   dict[str, Gtk.Button] = {}
        self._active_tab: str = "wallet"
        self._sections:   dict[str, dict] = {}

        self._build_tabbed_layout()
        self._layout_stack.set_visible_child_name("tabbed")

    # ── Tab scaffold ──────────────────────────────────────────────────────────

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

            if cat == "wallet":
                tab_page = self._build_wallet_tab()
            elif cat == "carrier":
                tab_page = self._build_carrier_tab()
            else:
                scroll, list_box, empty_lbl = self._make_section_scroll()
                self._sections[cat] = {
                    "list_box":  list_box,
                    "empty_lbl": empty_lbl,
                    "rows":      {},   # key -> (container, n_lbl, s_lbl)
                }
                tab_page = scroll
            stack.add_named(tab_page, cat)

        self._set_active_tab("wallet")
        self._layout_stack.add_named(page, "tabbed")

    def _build_wallet_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        bal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bal_key = self.make_label("Credits", css_class="data-key")
        self._balance_lbl = self.make_label("—", css_class="data-value")
        self._balance_lbl.set_hexpand(True)
        self._balance_lbl.set_xalign(1.0)
        bal_row.append(bal_key)
        bal_row.append(self._balance_lbl)
        box.append(bal_row)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        sc_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sc_key = self.make_label("Ships owned", css_class="data-key")
        self._ship_count_lbl = self.make_label("—", css_class="data-value")
        self._ship_count_lbl.set_hexpand(True)
        self._ship_count_lbl.set_xalign(1.0)
        sc_row.append(sc_key)
        sc_row.append(self._ship_count_lbl)
        box.append(sc_row)

        sm_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sm_key = self.make_label("Stored modules", css_class="data-key")
        self._mod_count_lbl = self.make_label("—", css_class="data-value")
        self._mod_count_lbl.set_hexpand(True)
        self._mod_count_lbl.set_xalign(1.0)
        sm_row.append(sm_key)
        sm_row.append(self._mod_count_lbl)
        box.append(sm_row)
        return box

    def _build_carrier_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        self._carrier_none_lbl = Gtk.Label(label="No fleet carrier on record")
        self._carrier_none_lbl.add_css_class("data-key")
        self._carrier_none_lbl.set_xalign(0.5)
        self._carrier_none_lbl.set_margin_top(8)
        box.append(self._carrier_none_lbl)

        # Detail grid — hidden until carrier data is present
        self._carrier_detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self._carrier_detail_box.set_visible(False)
        box.append(self._carrier_detail_box)

        self._carrier_rows: dict[str, Gtk.Label] = {}
        for key, label in [
            ("name",      "Name"),
            ("callsign",  "Callsign"),
            ("system",    "System"),
            ("fuel",      "Fuel"),
            ("balance",   "Balance"),
            ("available", "Available"),
            ("free",      "Free Space"),
            ("docking",   "Docking"),
        ]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.add_css_class("data-row")
            k_lbl = self.make_label(label, css_class="data-key")
            v_lbl = self.make_label("—", css_class="data-value")
            v_lbl.set_hexpand(True)
            v_lbl.set_xalign(1.0)
            row.append(k_lbl)
            row.append(v_lbl)
            self._carrier_detail_box.append(row)
            self._carrier_rows[key] = v_lbl

        return box

    def _make_section_scroll(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_box.set_vexpand(True)
        list_box.set_margin_end(12)
        scroll.set_child(list_box)

        empty_lbl = Gtk.Label(label="— none —")
        empty_lbl.add_css_class("data-key")
        empty_lbl.set_xalign(0.5)
        empty_lbl.set_margin_top(6)
        empty_lbl.set_margin_bottom(4)
        list_box.append(empty_lbl)
        return scroll, list_box, empty_lbl

    # ── Tab switching ─────────────────────────────────────────────────────────

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

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        state = self.core.state

        bal            = getattr(state, "assets_balance",        None)
        current_ship   = getattr(state, "assets_current_ship",   None)
        stored_ships   = getattr(state, "assets_stored_ships",   [])
        stored_modules = getattr(state, "assets_stored_modules", [])

        self._balance_lbl.set_label(_fmt_credits(bal))

        # Filter stored ships: remove any entry whose ShipID matches the
        # current ship (it was stored at some earlier point; it's here now).
        current_id = (current_ship or {}).get("ship_id")
        if current_id is not None:
            stored_ships = [
                s for s in stored_ships
                if s.get("ship_id") != current_id
            ]

        all_ships = ([current_ship] if current_ship else []) + stored_ships
        self._ship_count_lbl.set_label(str(len(all_ships)) if all_ships else "—")
        self._mod_count_lbl.set_label(str(len(stored_modules)) if stored_modules else "—")

        self._refresh_ships(all_ships)
        # Hide the Modules tab entirely when we have no stored module data.
        # StoredModules only fires when the player opens outfitting; until then
        # the list is empty and showing an empty tab creates a false impression.
        self._tab_btns["modules"].set_visible(bool(stored_modules))
        if stored_modules:
            self._refresh_modules(stored_modules)
        self._refresh_carrier(getattr(state, "assets_carrier", None))

    # ── Carrier tab ─────────────────────────────────────────────────────────────────

    def _refresh_carrier(self, carrier: dict | None) -> None:
        has = carrier is not None
        self._carrier_none_lbl.set_visible(not has)
        self._carrier_detail_box.set_visible(has)
        if not has:
            return

        fuel_pct = int(carrier.get("fuel", 0) / 10)  # 0–1000 → 0–100%
        self._carrier_rows["name"].set_label(carrier.get("name", "—"))
        self._carrier_rows["callsign"].set_label(carrier.get("callsign", "—"))
        self._carrier_rows["system"].set_label(carrier.get("system", "—"))
        self._carrier_rows["fuel"].set_label(f"{carrier.get('fuel', 0)}/1000  ({fuel_pct}%)")
        self._carrier_rows["balance"].set_label(_fmt_credits(carrier.get("balance")))
        self._carrier_rows["available"].set_label(_fmt_credits(carrier.get("available")))
        capacity = carrier.get("capacity", 0)
        free     = carrier.get("free", 0)
        if capacity:
            used = capacity - free
            self._carrier_rows["free"].set_label(f"{free:,} / {capacity:,}  ({used*100//capacity}% used)")
        else:
            self._carrier_rows["free"].set_label("—")
        docking = carrier.get("docking", "—")
        self._carrier_rows["docking"].set_label(docking.replace("_", " ").title())

    # ── Ships tab ─────────────────────────────────────────────────────────────

    def _refresh_ships(self, ships: list) -> None:
        sec = self._sections.get("ships")
        if sec is None:
            return
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]

        seen = set()
        for ship in ships:
            key = ship.get("_key", "")
            seen.add(key)

            type_disp  = ship.get("type_display", "Unknown")
            name       = ship.get("name", "")
            is_current = ship.get("current", False)
            star       = "  \u2605" if is_current else ""

            line1 = f"{name}  ({type_disp}){star}" if name else f"{type_disp}{star}"
            line2 = ship.get("system", "\u2014")
            if ship.get("hot"):
                line2 = "\U0001f534 HOT  " + line2

            if key in rows:
                container, n_lbl, s_lbl = rows[key]
                n_lbl.set_label(line1)
                s_lbl.set_label(line2)
                self._update_ship_popover(container, ship)
            else:
                container = self._make_ship_row(key, ship, line1, line2, list_box)
                rows[key] = (container, container._n_lbl, container._s_lbl)

        for key in list(rows.keys()):
            if key not in seen:
                container, _, _ = rows.pop(key)
                if hasattr(container, "_popover"):
                    container._popover.unparent()
                list_box.remove(container)

        empty_lbl.set_visible(len(seen) == 0)

    def _make_ship_row(self, key, ship, line1, line2, list_box):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        btn = Gtk.Button()
        btn.add_css_class("assets-row-btn")
        btn.set_can_focus(False)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(2)
        inner.set_margin_bottom(2)
        inner.set_margin_start(4)

        n_lbl = self.make_label(line1, css_class="data-value")
        n_lbl.set_wrap(False)
        n_lbl.set_ellipsize(3)
        s_lbl = self.make_label(line2, css_class="data-key")
        s_lbl.set_wrap(False)
        s_lbl.set_ellipsize(3)
        inner.append(n_lbl)
        inner.append(s_lbl)
        btn.set_child(inner)
        container.append(btn)

        container._n_lbl = n_lbl
        container._s_lbl = s_lbl

        popover = self._build_ship_popover(ship)
        popover.set_parent(btn)
        container._popover = popover
        btn.connect("clicked", lambda b, p=popover: p.popup())

        list_box.append(container)
        return container

    def _build_ship_popover(self, ship):
        popover = Gtk.Popover()
        popover.add_css_class("assets-detail-popover")
        popover.set_autohide(True)

        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(3)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        rows_data = [
            ("Type",   ship.get("type_display", "\u2014")),
            ("Name",   ship.get("name", "\u2014") or "\u2014"),
            ("Ident",  ship.get("ident", "\u2014") or "\u2014"),
            ("System", ship.get("system", "\u2014")),
            ("Value",  _fmt_credits(ship.get("value"))),
            ("Status", "\U0001f534 HOT" if ship.get("hot") else "Clean"),
        ]
        for i, (k, v) in enumerate(rows_data):
            key_lbl = Gtk.Label(label=k)
            key_lbl.set_xalign(0.0)
            key_lbl.add_css_class("data-key")
            val_lbl = Gtk.Label(label=str(v))
            val_lbl.set_xalign(0.0)
            val_lbl.add_css_class("data-value")
            grid.attach(key_lbl, 0, i, 1, 1)
            grid.attach(val_lbl, 1, i, 1, 1)

        popover._val_labels = {k: grid.get_child_at(1, i)
                                for i, (k, _) in enumerate(rows_data)}
        popover.set_child(grid)
        return popover

    def _update_ship_popover(self, container, ship):
        try:
            vl = container._popover._val_labels
            vl["Type"].set_label(ship.get("type_display", "\u2014"))
            vl["Name"].set_label(ship.get("name", "\u2014") or "\u2014")
            vl["Ident"].set_label(ship.get("ident", "\u2014") or "\u2014")
            vl["System"].set_label(ship.get("system", "\u2014"))
            vl["Value"].set_label(_fmt_credits(ship.get("value")))
            vl["Status"].set_label("\U0001f534 HOT" if ship.get("hot") else "Clean")
        except Exception:
            pass

    # ── Modules tab ───────────────────────────────────────────────────────────

    def _refresh_modules(self, modules: list) -> None:
        sec = self._sections.get("modules")
        if sec is None:
            return
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]

        seen = set()
        for mod in modules:
            key = mod.get("_key", "")
            seen.add(key)

            line1 = mod.get("name_display", "Unknown")
            line2 = mod.get("system", "\u2014")
            if mod.get("hot"):
                line2 = "\U0001f534 HOT  " + line2

            if key in rows:
                container, n_lbl, s_lbl = rows[key]
                n_lbl.set_label(line1)
                s_lbl.set_label(line2)
                self._update_mod_popover(container, mod)
            else:
                container = self._make_mod_row(key, mod, line1, line2, list_box)
                rows[key] = (container, container._n_lbl, container._s_lbl)

        for key in list(rows.keys()):
            if key not in seen:
                container, _, _ = rows.pop(key)
                if hasattr(container, "_popover"):
                    container._popover.unparent()
                list_box.remove(container)

        empty_lbl.set_visible(len(seen) == 0)

    def _make_mod_row(self, key, mod, line1, line2, list_box):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        btn = Gtk.Button()
        btn.add_css_class("assets-row-btn")
        btn.set_can_focus(False)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(2)
        inner.set_margin_bottom(2)
        inner.set_margin_start(4)

        n_lbl = self.make_label(line1, css_class="data-value")
        n_lbl.set_ellipsize(3)
        s_lbl = self.make_label(line2, css_class="data-key")
        s_lbl.set_ellipsize(3)
        inner.append(n_lbl)
        inner.append(s_lbl)
        btn.set_child(inner)
        container.append(btn)

        container._n_lbl = n_lbl
        container._s_lbl = s_lbl

        popover = self._build_mod_popover(mod)
        popover.set_parent(btn)
        container._popover = popover
        btn.connect("clicked", lambda b, p=popover: p.popup())

        list_box.append(container)
        return container

    def _build_mod_popover(self, mod):
        popover = Gtk.Popover()
        popover.add_css_class("assets-detail-popover")
        popover.set_autohide(True)

        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(3)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        mass = mod.get("mass", 0.0)
        rows_data = [
            ("Module", mod.get("name_display", "\u2014")),
            ("Slot",   mod.get("slot", "") or "\u2014"),
            ("System", mod.get("system", "\u2014")),
            ("Mass",   f"{mass:.1f} t" if mass else "\u2014"),
            ("Value",  _fmt_credits(mod.get("value"))),
            ("Status", "\U0001f534 HOT" if mod.get("hot") else "Clean"),
        ]
        for i, (k, v) in enumerate(rows_data):
            key_lbl = Gtk.Label(label=k)
            key_lbl.set_xalign(0.0)
            key_lbl.add_css_class("data-key")
            val_lbl = Gtk.Label(label=str(v))
            val_lbl.set_xalign(0.0)
            val_lbl.add_css_class("data-value")
            grid.attach(key_lbl, 0, i, 1, 1)
            grid.attach(val_lbl, 1, i, 1, 1)

        popover._val_labels = {k: grid.get_child_at(1, i)
                                for i, (k, _) in enumerate(rows_data)}
        popover.set_child(grid)
        return popover

    def _update_mod_popover(self, container, mod):
        try:
            vl = container._popover._val_labels
            mass = mod.get("mass", 0.0)
            vl["Module"].set_label(mod.get("name_display", "\u2014"))
            vl["Slot"].set_label(mod.get("slot", "") or "\u2014")
            vl["System"].set_label(mod.get("system", "\u2014"))
            vl["Mass"].set_label(f"{mass:.1f} t" if mass else "\u2014")
            vl["Value"].set_label(_fmt_credits(mod.get("value")))
            vl["Status"].set_label("\U0001f534 HOT" if mod.get("hot") else "Clean")
        except Exception:
            pass
