"""
gui/blocks/materials.py — Engineering materials inventory block.

Three sections (Raw / Manufactured / Encoded) presented as tabs across the top.
Only the active tab's list is shown; each tab button carries the item count.

Implementation notes
--------------------
• Uses Gtk.Stack for the content pane — one child per tab, switched by name.
• Tab bar is a hand-rolled HBox of toggle-style Gtk.Button widgets rather than
  Gtk.Notebook.  This gives us full CSS control and clean theme adherence.
• Active tab: .mat-tab-btn.mat-tab-active — accent underline + brighter text.
• Inactive tab: .mat-tab-btn               — dimmed, no underline.
• Row management (add / remove / reorder) is identical to the previous single-
  scroll implementation; only the outer container shape has changed.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget

_TABS = [
    ("raw",          "Raw"),
    ("manufactured", "Manufactured"),
    ("encoded",      "Encoded"),
]


class MaterialsBlock(BlockWidget):
    BLOCK_TITLE = "MATERIALS"
    BLOCK_CSS   = "materials-block"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        # ── Tab bar ───────────────────────────────────────────────────────────
        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.add_css_class("mat-tab-bar")
        body.append(tab_bar)

        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Stack (one child per tab) ─────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_vexpand(True)
        self._stack.set_hexpand(True)
        body.append(self._stack)

        # ── Build each tab button + stack page ────────────────────────────────
        self._tab_btns:  dict[str, Gtk.Button] = {}
        self._sections:  dict[str, dict]       = {}
        self._active_tab: str = "raw"

        for cat, label in _TABS:
            # Tab button
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)   # keep keyboard nav clean
            tab_bar.append(btn)
            self._tab_btns[cat] = btn

            # Button inner: label + count badge
            btn_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            btn_inner.set_halign(Gtk.Align.CENTER)
            btn.set_child(btn_inner)

            tab_lbl = Gtk.Label(label=label)
            tab_lbl.add_css_class("mat-tab-label")
            btn_inner.append(tab_lbl)

            count_badge = Gtk.Label(label="0")
            count_badge.add_css_class("mat-tab-count")
            btn_inner.append(count_badge)

            # Stack page: scroll wrapping a vbox of item rows
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            scroll.add_css_class("mat-tab-scroll")

            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            list_box.set_vexpand(True)
            scroll.set_child(list_box)

            empty_lbl = Gtk.Label(label="— none —")
            empty_lbl.add_css_class("data-key")
            empty_lbl.set_xalign(0.5)
            empty_lbl.set_margin_top(6)
            empty_lbl.set_margin_bottom(4)
            list_box.append(empty_lbl)

            self._stack.add_named(scroll, cat)

            self._sections[cat] = {
                "count_badge": count_badge,
                "list_box":    list_box,
                "empty_lbl":   empty_lbl,
                "rows":        {},   # key → (row_box, name_lbl, count_lbl)
            }

            # Click handler — capture cat by value
            btn.connect("clicked", self._on_tab_click, cat)

        # Activate first tab
        self._set_active_tab("raw")

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _on_tab_click(self, _btn: Gtk.Button, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._stack.set_visible_child_name(cat)
        for key, btn in self._tab_btns.items():
            if key == cat:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        s = self.state
        buckets = {
            "raw":          getattr(s, "materials_raw",          {}),
            "manufactured": getattr(s, "materials_manufactured", {}),
            "encoded":      getattr(s, "materials_encoded",      {}),
        }

        for cat, items in buckets.items():
            sec          = self._sections[cat]
            count_badge  = sec["count_badge"]
            list_box     = sec["list_box"]
            empty_lbl    = sec["empty_lbl"]
            rows         = sec["rows"]

            total = sum(v["count"] for v in items.values())
            count_badge.set_label(str(total) if total else "0")

            if not items:
                empty_lbl.set_visible(True)
                for key in list(rows.keys()):
                    row_box, _, _ = rows.pop(key)
                    list_box.remove(row_box)
                continue

            empty_lbl.set_visible(False)

            sorted_items  = sorted(items.items(), key=lambda kv: kv[1]["name_local"].lower())
            current_keys  = [k for k, _ in sorted_items]

            # Remove stale rows
            for key in list(rows.keys()):
                if key not in items:
                    row_box, _, _ = rows.pop(key)
                    list_box.remove(row_box)

            # Add / update
            for key, data in sorted_items:
                name_str  = data["name_local"]
                count_str = f"  {data['count']}"

                if key in rows:
                    _, name_lbl_w, count_lbl_w = rows[key]
                    name_lbl_w.set_label(name_str)
                    count_lbl_w.set_label(count_str)
                else:
                    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                    row_box.add_css_class("data-row")

                    name_lbl_w = Gtk.Label(label=name_str)
                    name_lbl_w.set_xalign(0.0)
                    name_lbl_w.set_hexpand(True)
                    name_lbl_w.add_css_class("data-value")

                    count_lbl_w = Gtk.Label(label=count_str)
                    count_lbl_w.set_xalign(1.0)
                    count_lbl_w.add_css_class("data-key")

                    row_box.append(name_lbl_w)
                    row_box.append(count_lbl_w)
                    list_box.append(row_box)
                    rows[key] = (row_box, name_lbl_w, count_lbl_w)

            # Re-order if needed
            existing_order = [k for k in rows if k in items]
            if existing_order != current_keys:
                for key in current_keys:
                    if key in rows:
                        row_box, _, _ = rows[key]
                        list_box.remove(row_box)
                        list_box.append(row_box)
