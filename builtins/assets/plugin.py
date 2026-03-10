"""
builtins/assets/plugin.py — Commander assets inventory.

Tracks four asset categories sourced entirely from the journal and companion
JSON files in the journal directory:

  Wallet    — credit balance (Status.json, updated on every Status event)
  Ships     — current ship + stored ships (StoredShips journal event)
  Modules   — modules stored away from any ship (StoredModules journal event)
Data availability notes
-----------------------
• Balance        : live — Status.json is written by the game every ~few seconds.
• Current ship   : live — Loadout fires on every login and ship change.
• Stored ships   : stale — StoredShips only fires when the player opens a
                   shipyard.  The list is accurate at that moment but does not
                   update until the player visits a shipyard again.
• Stored modules : stale — StoredModules only fires when the player opens
                   outfitting.  Same caveat as stored ships.

Note: Odyssey ShipLocker inventory has moved to builtins/engineering/plugin.py.

State stored on MonitorState (all added via hasattr guard in on_load):
    assets_balance         float   — current credit balance
    assets_current_ship    dict    — {type, name, ident, system, hull, value}
    assets_stored_ships    list    — [{type_display, name, system, value, hot}]
    assets_stored_modules  list    — [{name_display, system, mass, value, hot}]

CAPI note: when FDev CAPI is integrated, stored ships and modules will be
sourced from /fleetcarrier and /profile endpoints rather than relying on
stale journal snapshots.  The state schema is intentionally forward-compatible.
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import normalise_ship_name

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    _GTK = True
except Exception:
    _GTK = False

if _GTK:
    from gui.block_base import BlockWidget


# ── Module name normalisation ─────────────────────────────────────────────────

_CLASS_MAP = {"1": "E", "2": "D", "3": "C", "4": "B", "5": "A"}

_MODULE_TYPES: dict[str, str] = {
    # Thrusters / drives
    "engine":                      "Thrusters",
    "hyperdrive":                   "Frame Shift Drive",
    "hyperdrive_overcharge":        "Overcharged FSD",
    # Power
    "powerplant":                   "Power Plant",
    "powerdistributor":             "Power Distributor",
    # Shields / armour
    "shieldgenerator":              "Shield Generator",
    "shieldbankfast":               "Shield Cell Bank",
    "shieldbank":                   "Shield Cell Bank",
    "hullreinforcement":            "Hull Reinforcement",
    "modulereinforcement":          "Module Reinforcement",
    "guardianshieldreinforcement":  "Guardian Shield Reinf.",
    "guardianhullreinforcement":    "Guardian Hull Reinf.",
    # Hardpoints — weapons
    "beamlaser":                    "Beam Laser",
    "pulselaser":                   "Pulse Laser",
    "multican":                     "Multi-cannon",
    "cannon":                       "Cannon",
    "railgun":                      "Rail Gun",
    "plasmaaccelerator":            "Plasma Accelerator",
    "mininglaser":                  "Mining Laser",
    "slugshot":                     "Fragment Cannon",
    "dumbfiremissilerack":          "Dumbfire Missiles",
    "drunkmissilerack":             "Pack-Hound Missiles",
    "causticmissile":               "Enzyme Missiles",
    "advancedtorpedopylon":         "Torpedo Pylon",
    "torpedopylon":                 "Torpedo Pylon",
    "shieldbooster":                "Shield Booster",
    "plasmapointdefence":           "Point Defence",
    "chafflauncher":                "Chaff Launcher",
    "electroniccountermeasure":     "ECM",
    "heatsinklauncher":             "Heat Sink",
    # Utilities / internals
    "sensors":                      "Sensors",
    "lifesupport":                  "Life Support",
    "fuelscoop":                    "Fuel Scoop",
    "fueltank":                     "Fuel Tank",
    "cargorack":                    "Cargo Rack",
    "corrosionproofcargorack":      "Corrosion Cargo Rack",
    "dockingcomputer":              "Docking Computer",
    "dockingcomputer_advanced":     "Advanced Docking Comp.",
    "supercruiseassist":            "Supercruise Assist",
    "detailedsurfacescanner":       "Detailed Surface Scanner",
    "fighterbay":                   "Fighter Hangar",
    "passengercabin":               "Passenger Cabin",
    "buggybay":                     "Planetary Vehicle Hangar",
    "repairer":                     "Auto Field-Maint. Unit",
    "collectorlimpetcontroller":    "Collector Limpet Ctrl",
    "prospectorlimpetcontroller":   "Prospector Limpet Ctrl",
    "miningequipment":              "Abrasion Blaster",
    "seismiccharge":                "Seismic Charge",
    "subsurfacedisplacementmissile":"Disp. Missile",
    "meta_alloy_hull_reinforcement":"Meta-Alloy Hull Reinf.",
    "planetapproachsuite":          "Planetary Approach Suite",
    "codexscanner":                 "Codex Scanner",
    "colonisation":                 "Colonisation Suite",
    "stellarbodydiscoveryscanner":  "Discovery Scanner",
    "shipdatalinkscanner":          "Data Link Scanner",
}

_MOUNT_MAP = {
    "fixed":    "Fixed",
    "gimbal":   "Gimballed",
    "turret":   "Turret",
}

_SIZE_MAP = {
    "tiny":   "0",
    "small":  "1",
    "medium": "2",
    "large":  "3",
    "huge":   "4",
}


def normalise_module_name(internal: str) -> str:
    """Convert an internal module name to a human-readable display string.

    Examples
    --------
    int_engine_size7_class5           → 7A Thrusters
    int_shieldgenerator_size8_class5  → 8A Shield Generator
    hpt_pulselaser_turret_large       → Large Pulse Laser (Turret)
    int_dockingcomputer_advanced      → Advanced Docking Comp.
    """
    if not internal:
        return "—"
    raw = internal.lower().strip()

    # Strip prefix (int_ / hpt_ / etc.)
    for prefix in ("int_", "hpt_", "ext_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    parts = raw.split("_")

    # ── Hardpoint weapons: hpt_{type}_{mount}_{size} ─────────────────────────
    # e.g. pulselaser_turret_large
    # Identify mount keyword
    mount = ""
    for i, p in enumerate(parts):
        if p in _MOUNT_MAP:
            mount = _MOUNT_MAP[p]
            parts = parts[:i] + parts[i + 1:]
            break

    # Identify size keyword (tiny/small/medium/large/huge or sizeN)
    size_str = ""
    new_parts = []
    for p in parts:
        if p in _SIZE_MAP:
            size_str = _SIZE_MAP[p].upper()
        elif p.startswith("size") and p[4:].isdigit():
            size_str = p[4:]
        else:
            new_parts.append(p)
    parts = new_parts

    # Class keyword
    class_str = ""
    new_parts = []
    for p in parts:
        if p.startswith("class") and p[5:].isdigit():
            class_str = _CLASS_MAP.get(p[5:], p[5:])
        else:
            new_parts.append(p)
    parts = new_parts

    # Look up type name from remaining parts joined
    type_key = "_".join(parts)
    type_name = _MODULE_TYPES.get(type_key)

    # Try progressively shorter prefixes if no exact match
    if type_name is None:
        for n in range(len(parts) - 1, 0, -1):
            k = "_".join(parts[:n])
            if k in _MODULE_TYPES:
                type_name = _MODULE_TYPES[k]
                break

    if type_name is None:
        # Fallback: title-case the remaining parts
        type_name = " ".join(p.title() for p in parts)

    # Assemble
    prefix_part = f"{size_str}{class_str}" if (size_str or class_str) else ""
    suffix_part = f" ({mount})" if mount else ""
    if prefix_part:
        return f"{prefix_part} {type_name}{suffix_part}"
    return f"{type_name}{suffix_part}"


# ── Block widget ──────────────────────────────────────────────────────────────

_TABS = [
    ("wallet",  "Wallet"),
    ("ships",   "Ships"),
    ("modules", "Modules"),
]

WIDE_THRESHOLD = 380


if _GTK:
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

            # Each section: {list_box, empty_lbl, rows: dict}
            # rows keyed differently per tab:
            #   wallet  — not used (static labels)
            #   ships   — keyed by ship id string
            #   modules — keyed by (system, name)
            self._sections: dict[str, dict] = {}

            self._build_tabbed_layout()

            self._layout_stack.set_visible_child_name("tabbed")
            self._current_layout = "tabbed"

        # ── Tabbed layout ─────────────────────────────────────────────────────

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
                else:
                    scroll, list_box, empty_lbl = self._make_section_scroll()
                    self._sections[cat] = {
                        "list_box":  list_box,
                        "empty_lbl": empty_lbl,
                        "rows":      {},
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

            # Primary credit balance — large display
            bal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            bal_key = self.make_label("Credits", css_class="data-key")
            self._balance_lbl = self.make_label("—", css_class="data-value")
            self._balance_lbl.set_hexpand(True)
            self._balance_lbl.set_xalign(1.0)
            bal_row.append(bal_key)
            bal_row.append(self._balance_lbl)
            box.append(bal_row)

            box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            # Ship count summary
            sc_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            sc_key = self.make_label("Ships owned", css_class="data-key")
            self._ship_count_lbl = self.make_label("—", css_class="data-value")
            self._ship_count_lbl.set_hexpand(True)
            self._ship_count_lbl.set_xalign(1.0)
            sc_row.append(sc_key)
            sc_row.append(self._ship_count_lbl)
            box.append(sc_row)

            # Stored modules count
            sm_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            sm_key = self.make_label("Stored modules", css_class="data-key")
            self._mod_count_lbl = self.make_label("—", css_class="data-value")
            self._mod_count_lbl.set_hexpand(True)
            self._mod_count_lbl.set_xalign(1.0)
            sm_row.append(sm_key)
            sm_row.append(self._mod_count_lbl)
            box.append(sm_row)

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

        # ── Tab switching ─────────────────────────────────────────────────────

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

        # ── on_resize ─────────────────────────────────────────────────────────

        def on_resize(self, w: int, h: int) -> None:
            super().on_resize(w, h)

        # ── Refresh ───────────────────────────────────────────────────────────

        def refresh(self) -> None:
            state = self.core.state

            # Wallet tab
            bal = getattr(state, "assets_balance", None)
            self._balance_lbl.set_label(
                self.fmt_credits(bal) if bal is not None else "—"
            )

            stored_ships   = getattr(state, "assets_stored_ships",   [])
            current_ship   = getattr(state, "assets_current_ship",   None)
            stored_modules = getattr(state, "assets_stored_modules", [])
            all_ships = ([current_ship] if current_ship else []) + stored_ships
            self._ship_count_lbl.set_label(str(len(all_ships)) if all_ships else "—")

            self._mod_count_lbl.set_label(
                str(len(stored_modules)) if stored_modules else "—"
            )

            # Ships tab
            self._refresh_ships(all_ships)

            # Modules tab
            self._refresh_modules(stored_modules)

        def _refresh_ships(self, ships: list) -> None:
            sec = self._sections.get("ships")
            if sec is None:
                return
            list_box  = sec["list_box"]
            empty_lbl = sec["empty_lbl"]
            rows      = sec["rows"]

            seen = set()
            for ship in ships:
                key = ship.get("_key", ship.get("name", "") + ship.get("system", ""))
                seen.add(key)
                name_display = ship.get("type_display", "Unknown")
                if ship.get("name"):
                    name_display = f"{ship['name']} ({ship.get('type_display', '')})"
                system = ship.get("system", "—")
                is_current = ship.get("current", False)
                tag = "  ★" if is_current else ""
                line1 = name_display + tag
                line2 = system

                if key in rows:
                    n_lbl, s_lbl = rows[key]
                    n_lbl.set_label(line1)
                    s_lbl.set_label(line2)
                else:
                    row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    row_box.set_margin_top(2)
                    row_box.set_margin_bottom(2)
                    row_box.set_margin_start(4)
                    n_lbl = self.make_label(line1, css_class="data-value")
                    n_lbl.set_wrap(False)
                    n_lbl.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
                    s_lbl = self.make_label(line2, css_class="data-key")
                    s_lbl.set_wrap(False)
                    s_lbl.set_ellipsize(3)
                    row_box.append(n_lbl)
                    row_box.append(s_lbl)
                    list_box.append(row_box)
                    rows[key] = (n_lbl, s_lbl)

            # Remove stale rows
            for key in list(rows.keys()):
                if key not in seen:
                    n_lbl, _ = rows.pop(key)
                    parent = n_lbl.get_parent()
                    if parent:
                        list_box.remove(parent)

            empty_lbl.set_visible(len(seen) == 0)

        def _refresh_modules(self, modules: list) -> None:
            sec = self._sections.get("modules")
            if sec is None:
                return
            list_box  = sec["list_box"]
            empty_lbl = sec["empty_lbl"]
            rows      = sec["rows"]

            seen = set()
            for mod in modules:
                key = mod.get("_key", mod.get("name_display", "") + mod.get("system", ""))
                seen.add(key)
                name_display = mod.get("name_display", "Unknown")
                system       = mod.get("system", "—")

                if key in rows:
                    n_lbl, s_lbl = rows[key]
                    n_lbl.set_label(name_display)
                    s_lbl.set_label(system)
                else:
                    row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    row_box.set_margin_top(2)
                    row_box.set_margin_bottom(2)
                    row_box.set_margin_start(4)
                    n_lbl = self.make_label(name_display, css_class="data-value")
                    n_lbl.set_ellipsize(3)
                    s_lbl = self.make_label(system, css_class="data-key")
                    s_lbl.set_ellipsize(3)
                    row_box.append(n_lbl)
                    row_box.append(s_lbl)
                    list_box.append(row_box)
                    rows[key] = (n_lbl, s_lbl)

            for key in list(rows.keys()):
                if key not in seen:
                    n_lbl, _ = rows.pop(key)
                    parent = n_lbl.get_parent()
                    if parent:
                        list_box.remove(parent)

            empty_lbl.set_visible(len(seen) == 0)



# ── Plugin ────────────────────────────────────────────────────────────────────

class AssetsPlugin(BasePlugin):
    PLUGIN_NAME        = "assets"
    PLUGIN_DISPLAY     = "Assets"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Commander assets — wallet, ships, and stored modules."

    SUBSCRIBED_EVENTS = [
        # Balance
        "Statistics",
        "Commander",
        # Ships
        "Loadout",
        "StoredShips",
        # Modules
        "StoredModules",
        # Session boundaries
        "LoadGame",
    ]

    BLOCK_WIDGET_CLASS = AssetsBlock if _GTK else None

    def on_load(self, core) -> None:
        super().on_load(core)
        if _GTK:
            core.register_block(self, priority=55)

        s = core.state
        if not hasattr(s, "assets_balance"):        s.assets_balance        = None
        if not hasattr(s, "assets_current_ship"):   s.assets_current_ship   = None
        if not hasattr(s, "assets_stored_ships"):   s.assets_stored_ships   = []
        if not hasattr(s, "assets_stored_modules"): s.assets_stored_modules = []

        # Read Status.json for initial balance
        self._read_status_json()

        import threading
        threading.Timer(3.0, self._startup_refresh).start()

    def _startup_refresh(self) -> None:
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "assets"))

    def _read_status_json(self) -> None:
        """Read Balance from Status.json on startup."""
        try:
            path = Path(self.core.journal_dir) / "Status.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                bal = data.get("Balance")
                if bal is not None:
                    self.core.state.assets_balance = float(bal)
        except Exception:
            pass


    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "LoadGame":
                # LoadGame contains Balance
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Commander":
                # Some versions carry balance here too
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Statistics":
                # Statistics has a "Bank_Account" sub-object with Current_Wealth
                bank = event.get("Bank_Account", {})
                bal  = bank.get("Current_Wealth")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Loadout":
                ship_type   = event.get("Ship", "")
                ship_type_l = event.get("Ship_Localised") or normalise_ship_name(ship_type) or ship_type
                state.assets_current_ship = {
                    "_key":         "current",
                    "current":      True,
                    "type":         ship_type,
                    "type_display": ship_type_l,
                    "name":         event.get("ShipName", ""),
                    "ident":        event.get("ShipIdent", ""),
                    "system":       getattr(state, "pilot_system", None) or "—",
                    "value":        event.get("HullValue", 0),
                    "hull":         100,
                }
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredShips":
                ships = []
                for section in ("ShipsHere", "ShipsRemote"):
                    for s in event.get(section, []):
                        ship_type = s.get("ShipType", "")
                        disp = (s.get("ShipType_Localised")
                                or normalise_ship_name(ship_type)
                                or ship_type.replace("_", " ").title())
                        name = s.get("Name", "")
                        key  = f"{s.get('ShipID', '')}_{ship_type}"
                        ships.append({
                            "_key":         key,
                            "current":      False,
                            "type":         ship_type,
                            "type_display": disp,
                            "name":         name,
                            "system":       s.get("StarSystem", "—"),
                            "value":        s.get("Value", 0),
                            "hot":          s.get("Hot", False),
                        })
                state.assets_stored_ships = ships
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredModules":
                mods = []
                for i, m in enumerate(event.get("Items", [])):
                    internal = m.get("Name", "")
                    disp = (m.get("Name_Localised")
                            or normalise_module_name(internal))
                    system = m.get("StarSystem", "—")
                    key    = f"{i}_{internal}_{system}"
                    mods.append({
                        "_key":         key,
                        "name_internal":internal,
                        "name_display": disp,
                        "system":       system,
                        "mass":         m.get("Mass", 0.0),
                        "value":        m.get("Value", 0),
                        "hot":          m.get("Hot", False),
                    })
                state.assets_stored_modules = mods
                if gq: gq.put(("plugin_refresh", "assets"))


# ── Helpers ───────────────────────────────────────────────────────────────────
