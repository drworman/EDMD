"""
gui/blocks/materials.py — Engineering materials inventory block.

Responsive layout:
  • Narrow (< WIDE_THRESHOLD px): tabbed — Raw / Manufactured / Encoded tabs
    across the top; only the active tab's list is shown.
  • Wide  (≥ WIDE_THRESHOLD px): three columns side by side, all sections
    visible simultaneously.

Implementation notes
--------------------
• An outer Gtk.Stack with pages "tabbed" and "wide" holds both layouts.
  The visible page is switched via the on_resize() hook, called by the
  window's _replace_all_blocks() after every set_size_request.
• Each layout has its own complete widget subtree and its own section dicts
  (list_box + rows).  refresh() updates both simultaneously so the display
  is always current regardless of which page is active.
• Row management is factored into _refresh_section() called for every
  section in both layouts on each refresh().
• Tab bar uses hand-rolled Gtk.Button widgets (not Gtk.Notebook) for full
  CSS control.  See themes/base.css for .mat-tab-* classes.
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

# Minimum block pixel width to show three columns simultaneously.
# Below this threshold the tabbed layout is used instead.
WIDE_THRESHOLD = 380


class MaterialsBlock(BlockWidget):
    BLOCK_TITLE = "MATERIALS"
    BLOCK_CSS   = "materials-block"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        # ── Top-level layout switcher ─────────────────────────────────────────
        self._layout_stack = Gtk.Stack()
        self._layout_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._layout_stack.set_vexpand(True)
        self._layout_stack.set_hexpand(True)
        body.append(self._layout_stack)

        # ── Build both layouts ────────────────────────────────────────────────
        self._tab_btns:  dict[str, Gtk.Button] = {}
        self._active_tab: str = "raw"

        # Each layout gets its own sections dict:
        #   { cat: {"count_lbl": ..., "list_box": ..., "empty_lbl": ..., "rows": {}} }
        self._sections_tabbed: dict[str, dict] = {}
        self._sections_wide:   dict[str, dict] = {}

        self._build_tabbed_layout()
        self._build_wide_layout()

        # Start in tabbed mode; on_resize() switches layout once the window
        # measures and places this block via _replace_all_blocks.
        self._layout_stack.set_visible_child_name("tabbed")
        self._current_layout = "tabbed"

    # ── Tabbed layout ─────────────────────────────────────────────────────────

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
            # Tab button
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            tab_bar.append(btn)
            self._tab_btns[cat] = btn

            btn_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            btn_inner.set_halign(Gtk.Align.CENTER)
            btn.set_child(btn_inner)

            tab_lbl = Gtk.Label(label=label)
            tab_lbl.add_css_class("mat-tab-label")
            btn_inner.append(tab_lbl)

            count_badge = Gtk.Label(label="0")
            count_badge.add_css_class("mat-tab-count")
            btn_inner.append(count_badge)

            scroll, list_box, empty_lbl = self._make_section_scroll()
            stack.add_named(scroll, cat)

            self._sections_tabbed[cat] = {
                "count_lbl":  count_badge,
                "list_box":   list_box,
                "empty_lbl":  empty_lbl,
                "rows":       {},
            }

            btn.connect("clicked", self._on_tab_click, cat)

        self._set_active_tab("raw")
        self._layout_stack.add_named(page, "tabbed")

    # ── Wide (three-column) layout ────────────────────────────────────────────

    def _build_wide_layout(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        page.set_vexpand(True)
        page.set_hexpand(True)

        for i, (cat, label) in enumerate(_TABS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            col.set_hexpand(True)
            col.set_vexpand(True)

            # Column header: label left, count right
            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            hdr.add_css_class("mat-col-hdr")
            hdr.set_margin_start(4)
            hdr.set_margin_end(4)
            hdr.set_margin_top(4)
            hdr.set_margin_bottom(2)

            hdr_lbl = Gtk.Label(label=label.upper())
            hdr_lbl.add_css_class("mat-col-title")
            hdr_lbl.set_xalign(0.0)
            hdr_lbl.set_hexpand(True)
            hdr.append(hdr_lbl)

            count_lbl = Gtk.Label(label="0")
            count_lbl.add_css_class("data-key")
            hdr.append(count_lbl)

            col.append(hdr)
            col.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            scroll, list_box, empty_lbl = self._make_section_scroll()
            col.append(scroll)

            self._sections_wide[cat] = {
                "count_lbl":  count_lbl,
                "list_box":   list_box,
                "empty_lbl":  empty_lbl,
                "rows":       {},
            }

            page.append(col)

            # Vertical divider between columns (not after the last one)
            if i < len(_TABS) - 1:
                page.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self._layout_stack.add_named(page, "wide")

    # ── Shared scroll+list factory ────────────────────────────────────────────

    def _make_section_scroll(self):
        """Return (ScrolledWindow, list_box, empty_label) ready to populate."""
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

        return scroll, list_box, empty_lbl

    # ── Layout switching ──────────────────────────────────────────────────────

    def on_resize(self, w: int, h: int) -> None:
        """Called by the window after every set_size_request — switch layout mode."""
        if w < 10:
            return
        target = "wide" if w >= WIDE_THRESHOLD else "tabbed"
        if target != self._current_layout:
            self._layout_stack.set_visible_child_name(target)
            self._current_layout = target

    # ── Tab switching (tabbed layout only) ────────────────────────────────────

    def _on_tab_click(self, _btn: Gtk.Button, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._tab_stack.set_visible_child_name(cat)
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
            # Update both layouts every tick — cost is negligible and ensures
            # the display is correct immediately when switching modes.
            self._refresh_section(items, self._sections_tabbed[cat])
            self._refresh_section(items, self._sections_wide[cat])

    def _refresh_section(self, items: dict, sec: dict) -> None:
        count_lbl = sec["count_lbl"]
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]

        total = sum(v["count"] for v in items.values())
        count_lbl.set_label(str(total) if total else "0")

        if not items:
            empty_lbl.set_visible(True)
            for key in list(rows.keys()):
                row_box, _, _ = rows.pop(key)
                list_box.remove(row_box)
            return

        empty_lbl.set_visible(False)

        sorted_items = sorted(items.items(), key=lambda kv: kv[1]["name_local"].lower())
        current_keys = [k for k, _ in sorted_items]

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
