"""
gui/blocks/cargo.py — Cargo hold inventory block.

Shows:
  Header: "CARGO  N / MAX t"
  Body:   sorted list of cargo items with counts
          stolen items marked with ⚠
  Empty hold shows a single "— empty —" line.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


class CargoBlock(BlockWidget):
    BLOCK_TITLE = "CARGO"
    BLOCK_CSS   = "cargo-block"

    def build(self, parent: Gtk.Box) -> None:
        # Header: "CARGO" left + "N / MAX t" right
        hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cargo_title = Gtk.Label(label="CARGO")
        self._cargo_title.set_xalign(0.0)
        self._cargo_title.set_hexpand(True)
        hdr_box.append(self._cargo_title)
        self._cargo_usage = Gtk.Label(label="")
        self._cargo_usage.set_xalign(1.0)
        self._cargo_usage.add_css_class("data-key")
        hdr_box.append(self._cargo_usage)

        body = self._build_section(parent, title_widget=hdr_box)

        # Scrollable inner box for item rows
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        body.append(self._scroll)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._list_box.set_vexpand(True)
        self._scroll.set_child(self._list_box)

        # Placeholder shown when hold is empty
        self._empty_lbl = Gtk.Label(label="— empty —")
        self._empty_lbl.add_css_class("data-key")
        self._empty_lbl.set_xalign(0.5)
        self._empty_lbl.set_hexpand(True)
        self._list_box.append(self._empty_lbl)

        # Cache of item row widgets keyed by cargo key to avoid full rebuilds
        self._item_rows: dict = {}   # key → (row_box, name_lbl, count_lbl)

    def refresh(self) -> None:
        s     = self.state
        items = getattr(s, "cargo_items", {})
        cap   = getattr(s, "cargo_capacity", 0)
        used  = sum(v["count"] for v in items.values())

        # Update capacity line in header
        if cap > 0:
            self._cargo_usage.set_label(f"{used} / {cap} t")
        elif used > 0:
            self._cargo_usage.set_label(f"{used} t")
        else:
            self._cargo_usage.set_label("")

        # Fill indicator class on usage label
        for cls in ("cargo-full", "cargo-warn", "cargo-ok"):
            self._cargo_usage.remove_css_class(cls)
        if cap > 0:
            pct = used / cap
            if pct >= 1.0:
                self._cargo_usage.add_css_class("cargo-full")
            elif pct >= 0.75:
                self._cargo_usage.add_css_class("cargo-warn")
            else:
                self._cargo_usage.add_css_class("cargo-ok")

        if not items:
            self._empty_lbl.set_visible(True)
            for key in list(self._item_rows.keys()):
                row_box, _, _ = self._item_rows.pop(key)
                self._list_box.remove(row_box)
            return

        self._empty_lbl.set_visible(False)

        # Sorted alphabetically by localised name
        sorted_items = sorted(items.items(), key=lambda kv: kv[1]["name_local"].lower())
        current_keys = [k for k, _ in sorted_items]

        # Remove rows that no longer exist
        for key in list(self._item_rows.keys()):
            if key not in items:
                row_box, _, _ = self._item_rows.pop(key)
                self._list_box.remove(row_box)

        # Add or update rows
        for key, data in sorted_items:
            name_str  = data["name_local"]
            count_str = f"  {data['count']} t"
            stolen    = data.get("stolen", False)

            if key in self._item_rows:
                row_box, name_lbl, count_lbl = self._item_rows[key]
                display = f"⚠ {name_str}" if stolen else name_str
                name_lbl.set_label(display)
                count_lbl.set_label(count_str)
                if stolen:
                    name_lbl.add_css_class("cargo-stolen")
                else:
                    name_lbl.remove_css_class("cargo-stolen")
            else:
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                row_box.add_css_class("data-row")

                display  = f"⚠ {name_str}" if stolen else name_str
                name_lbl = Gtk.Label(label=display)
                name_lbl.set_xalign(0.0)
                name_lbl.set_hexpand(True)
                name_lbl.add_css_class("data-value")
                if stolen:
                    name_lbl.add_css_class("cargo-stolen")

                count_lbl = Gtk.Label(label=count_str)
                count_lbl.set_xalign(1.0)
                count_lbl.add_css_class("data-key")

                row_box.append(name_lbl)
                row_box.append(count_lbl)
                self._list_box.append(row_box)
                self._item_rows[key] = (row_box, name_lbl, count_lbl)

        # Re-order rows to match sorted order if order has changed
        existing_order = [k for k in self._item_rows if k in items]
        if existing_order != current_keys:
            for key in current_keys:
                if key in self._item_rows:
                    row_box, _, _ = self._item_rows[key]
                    self._list_box.remove(row_box)
                    self._list_box.append(row_box)
