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

        # Net Worth (Statistics.Bank_Account.Current_Wealth — liquid + ships + modules + carrier)
        nw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        nw_key = self.make_label("Net Worth", css_class="data-key")
        self._net_worth_lbl = self.make_label("—", css_class="data-value")
        self._net_worth_lbl.set_hexpand(True)
        self._net_worth_lbl.set_xalign(1.0)
        nw_row.append(nw_key)
        nw_row.append(self._net_worth_lbl)
        self._net_worth_row = nw_row
        nw_row.set_visible(False)   # hidden until Statistics event fires
        box.append(nw_row)

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

    # ── Carrier tab helpers ────────────────────────────────────────────────────

    def _carrier_section(self, body: "Gtk.Box", title: str) -> None:
        """Append a thin section header label to body."""
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("data-key")
        lbl.set_xalign(0.0)
        lbl.set_margin_top(6)
        lbl.set_margin_bottom(2)
        body.append(lbl)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(sep)

    def _carrier_row(self, body: "Gtk.Box", key: str, label: str) -> None:
        """Append a key/value row and register the value label under key."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.add_css_class("data-row")
        k_lbl = self.make_label(label, css_class="data-key")
        v_lbl = self.make_label("—", css_class="data-value")
        v_lbl.set_hexpand(True)
        v_lbl.set_xalign(1.0)
        row.append(k_lbl)
        row.append(v_lbl)
        body.append(row)
        self._carrier_rows[key] = v_lbl

    def _build_carrier_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._carrier_none_lbl = Gtk.Label(label="No fleet carrier on record")
        self._carrier_none_lbl.add_css_class("data-key")
        self._carrier_none_lbl.set_xalign(0.5)
        self._carrier_none_lbl.set_margin_top(8)
        outer.append(self._carrier_none_lbl)

        # Scrollable detail area — hidden until carrier data is present
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")
        self._carrier_detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._carrier_detail_box.set_vexpand(True)
        self._carrier_detail_box.set_margin_start(6)
        self._carrier_detail_box.set_margin_end(12)
        self._carrier_detail_box.set_margin_top(4)
        self._carrier_detail_box.set_margin_bottom(4)
        scroll.set_child(self._carrier_detail_box)
        scroll.set_visible(False)
        outer.append(scroll)
        self._carrier_scroll = scroll

        self._carrier_rows: dict[str, Gtk.Label] = {}
        body = self._carrier_detail_box

        # ── Identity ─────────────────────────────────────────────────────────
        self._carrier_row(body, "name",          "Name")
        self._carrier_row(body, "callsign",       "Callsign")
        self._carrier_row(body, "system",         "System")
        self._carrier_row(body, "fuel",           "Fuel")
        self._carrier_row(body, "carrier_state",  "State")
        self._carrier_row(body, "theme",          "Theme")

        # ── Access ────────────────────────────────────────────────────────────
        self._carrier_section(body, "ACCESS")
        self._carrier_row(body, "docking",        "Docking")
        self._carrier_row(body, "notorious",      "Notorious")

        # ── Finance ───────────────────────────────────────────────────────────
        self._carrier_section(body, "FINANCE")
        self._carrier_row(body, "balance",        "Balance")
        self._carrier_row(body, "reserve",        "Reserve")
        self._carrier_row(body, "available",      "Available")
        self._carrier_row(body, "tax_refuel",     "Tax: Refuel")
        self._carrier_row(body, "tax_repair",     "Tax: Repair")
        self._carrier_row(body, "tax_rearm",      "Tax: Rearm")
        self._carrier_row(body, "tax_pioneer",    "Tax: Supplies")
        self._carrier_row(body, "maintenance",     "Upkeep/wk")
        self._carrier_row(body, "maintenance_wtd", "Upkeep so far")

        # ── Cargo ─────────────────────────────────────────────────────────────
        self._carrier_section(body, "CARGO")
        self._carrier_row(body, "cargo_cap_row",   "Total space")
        self._carrier_row(body, "cargo_crew_row",  "Crew/services")
        self._carrier_row(body, "cargo_used_row",  "Cargo stored")
        self._carrier_row(body, "cargo_free_row",  "Cargo free")

        # ── Storage ───────────────────────────────────────────────────────────
        self._carrier_section(body, "STORAGE")
        self._carrier_row(body, "ship_packs",     "Ship Packs")
        self._carrier_row(body, "module_packs",   "Module Packs")
        self._carrier_row(body, "micro_row",      "Micro-resources")

        # ── Services ──────────────────────────────────────────────────────────
        self._carrier_section(body, "SERVICES")
        self._carrier_services_lbl = Gtk.Label(label="—")
        self._carrier_services_lbl.add_css_class("data-key")
        self._carrier_services_lbl.set_xalign(0.0)
        self._carrier_services_lbl.set_wrap(True)
        self._carrier_services_lbl.set_margin_top(2)
        self._carrier_services_lbl.set_margin_bottom(4)
        body.append(self._carrier_services_lbl)

        return outer

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
        total_wealth   = getattr(state, "assets_total_wealth",   None)
        current_ship   = getattr(state, "assets_current_ship",   None)
        stored_ships   = getattr(state, "assets_stored_ships",   [])
        stored_modules = getattr(state, "assets_stored_modules", [])

        self._balance_lbl.set_label(_fmt_credits(bal))

        if total_wealth is not None:
            self._net_worth_lbl.set_label(_fmt_credits(total_wealth))
            self._net_worth_row.set_visible(True)
        else:
            self._net_worth_row.set_visible(False)

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

    # Service name → display label
    _SVC_LABELS = {
        "blackmarket":         "Black Market",
        "commodities":         "Commodities",
        "workshop":            "Workshop",
        "refuel":              "Refuel",
        "repair":              "Repair",
        "rearm":               "Rearm",
        "shipyard":            "Shipyard",
        "exploration":         "Cartographics",
        "voucherredemption":   "Redemption",
        "pioneersupplies":     "Pioneer Supplies",
        "bartender":           "Bartender",
        "vistagenomics":       "Vista Genomics",
        "socialspace":         "Social Space",
    }
    # Statuses that count as the service being active
    _SVC_ACTIVE = {"ok", "faction"}
    # Internal/infrastructure services to suppress from the display list
    _SVC_HIDDEN = {
        "carriermanagement", "stationmenu", "dock", "crewlounge",
        "contacts", "carrierfuel", "engineer", "livery",
        "registeringcolonisation",
    }

    def _refresh_carrier(self, carrier: dict | None) -> None:
        has = carrier is not None
        self._carrier_none_lbl.set_visible(not has)
        self._carrier_scroll.set_visible(has)
        if not has:
            return

        def _s(key, default="\u2014"):
            v = carrier.get(key, default)
            return str(v) if v is not None else default

        def _cr(key):
            return _fmt_credits(carrier.get(key))

        def _pct_val(key):
            v = carrier.get(key, 0)
            try:
                f = float(v)
                return f"{f:.1f}%" if f != int(f) else f"{int(f)}%"
            except (TypeError, ValueError):
                return "\u2014"

        # ── Identity ─────────────────────────────────────────────────────────
        self._carrier_rows["name"].set_label(_s("name"))
        self._carrier_rows["callsign"].set_label(_s("callsign"))
        self._carrier_rows["system"].set_label(_s("system"))
        fuel = int(carrier.get("fuel", 0) or 0)
        self._carrier_rows["fuel"].set_label(f"{fuel}/1000  ({fuel // 10}%)")
        raw_state = (carrier.get("carrier_state") or "\u2014").replace("_", " ")
        self._carrier_rows["carrier_state"].set_label(raw_state.title())
        theme = (carrier.get("theme") or "\u2014").replace("_", " ").title()
        self._carrier_rows["theme"].set_label(theme)

        # ── Access ────────────────────────────────────────────────────────────
        docking = carrier.get("docking", "\u2014") or "\u2014"
        self._carrier_rows["docking"].set_label(
            docking.replace("squadronfriends", "Squadron + Friends")
                   .replace("_", " ").title()
        )
        notorious = carrier.get("notorious", False)
        self._carrier_rows["notorious"].set_label(
            "Allowed" if notorious else "Not Allowed"
        )

        # ── Finance ───────────────────────────────────────────────────────────
        self._carrier_rows["balance"].set_label(_cr("balance"))
        bal     = int(carrier.get("balance",  0) or 0)
        reserve = int(carrier.get("reserve",  0) or 0)
        res_pct = (reserve * 100 // bal) if bal else 0
        self._carrier_rows["reserve"].set_label(
            f"{_fmt_credits(reserve)}  ({res_pct}%)" if reserve else "\u2014"
        )
        self._carrier_rows["available"].set_label(_cr("available"))
        self._carrier_rows["tax_refuel"].set_label(_pct_val("tax_refuel"))
        self._carrier_rows["tax_repair"].set_label(_pct_val("tax_repair"))
        self._carrier_rows["tax_rearm"].set_label(_pct_val("tax_rearm"))
        self._carrier_rows["tax_pioneer"].set_label(_pct_val("tax_pioneer"))
        maint = int(carrier.get("maintenance",     0) or 0)
        mwtd  = int(carrier.get("maintenance_wtd", 0) or 0)
        self._carrier_rows["maintenance"].set_label(
            _fmt_credits(maint) if maint else "\u2014"
        )
        self._carrier_rows["maintenance_wtd"].set_label(
            _fmt_credits(mwtd) if mwtd else "\u2014"
        )

        # ── Cargo ─────────────────────────────────────────────────────────────
        ctotal = int(carrier.get("cargo_total", 0) or 0)
        ccrew  = int(carrier.get("cargo_crew",  0) or 0)
        cused  = int(carrier.get("cargo_used",  0) or 0)
        cfree  = int(carrier.get("cargo_free",  0) or 0)
        self._carrier_rows["cargo_cap_row"].set_label(
            f"{ctotal:,} t" if ctotal else "\u2014"
        )
        self._carrier_rows["cargo_crew_row"].set_label(
            f"{ccrew:,} t" if ccrew else "\u2014"
        )
        if cused or cfree:
            self._carrier_rows["cargo_used_row"].set_label(f"{cused:,} t")
            self._carrier_rows["cargo_free_row"].set_label(f"{cfree:,} t")
        else:
            self._carrier_rows["cargo_used_row"].set_label("0 t")
            self._carrier_rows["cargo_free_row"].set_label(f"{cfree:,} t")

        # ── Storage ───────────────────────────────────────────────────────────
        sp = int(carrier.get("ship_packs",   0) or 0)
        mp = int(carrier.get("module_packs", 0) or 0)
        self._carrier_rows["ship_packs"].set_label(str(sp) if sp else "\u2014")
        self._carrier_rows["module_packs"].set_label(str(mp) if mp else "\u2014")
        mt = int(carrier.get("micro_total", 0) or 0)
        mu = int(carrier.get("micro_used",  0) or 0)
        mf = int(carrier.get("micro_free",  0) or 0)
        self._carrier_rows["micro_row"].set_label(
            f"{mu}/{mt}  ({mf} free)" if mt else "\u2014"
        )

        # ── Services ──────────────────────────────────────────────────────────
        svcs = carrier.get("services") or {}
        active = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v in self._SVC_ACTIVE and k not in self._SVC_HIDDEN
        )
        unavailable = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v == "unavailable" and k not in self._SVC_HIDDEN
        )
        unmanned = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v == "unmanned" and k not in self._SVC_HIDDEN
        )
        parts = []
        if active:
            parts.append("\u2705 " + ",  ".join(active))
        if unmanned:
            parts.append("\U0001f6ab Unmanned: " + ",  ".join(unmanned))
        if unavailable:
            parts.append("\u274c N/A: " + ",  ".join(unavailable))
        self._carrier_services_lbl.set_label(
            "\n".join(parts) if parts else "\u2014"
        )


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
