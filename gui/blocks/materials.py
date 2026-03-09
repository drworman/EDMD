"""
gui/blocks/materials.py — Engineering materials inventory block.

Shows three sections: Raw / Manufactured / Encoded.
Each section header shows the total item count.
Items are sorted alphabetically within each section.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


class MaterialsBlock(BlockWidget):
    BLOCK_TITLE = "MATERIALS"
    BLOCK_CSS   = "materials-block"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)

        self._sections: dict = {}   # cat → {"count_lbl", "list_box", "empty_lbl", "rows"}

        for cat, label in [
            ("raw",          "Raw"),
            ("manufactured", "Manufactured"),
            ("encoded",      "Encoded"),
        ]:
            # Section header: label left, count right
            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            hdr.add_css_class("materials-section-hdr")

            lbl = Gtk.Label(label=label.upper())
            lbl.set_xalign(0.0)
            lbl.set_hexpand(True)
            lbl.add_css_class("section-header")
            hdr.append(lbl)

            count_lbl = Gtk.Label(label="0")
            count_lbl.add_css_class("data-key")
            hdr.append(count_lbl)

            body.append(hdr)

            # Scrollable item list
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            body.append(scroll)

            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            list_box.set_vexpand(True)
            scroll.set_child(list_box)

            empty_lbl = Gtk.Label(label="— none —")
            empty_lbl.add_css_class("data-key")
            empty_lbl.set_xalign(0.5)
            list_box.append(empty_lbl)

            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("menu-sep")
            body.append(sep)

            self._sections[cat] = {
                "count_lbl": count_lbl,
                "list_box":  list_box,
                "empty_lbl": empty_lbl,
                "rows":      {},      # key → (row_box, name_lbl, count_lbl)
            }

    def refresh(self) -> None:
        s = self.state
        buckets = {
            "raw":          getattr(s, "materials_raw",          {}),
            "manufactured": getattr(s, "materials_manufactured", {}),
            "encoded":      getattr(s, "materials_encoded",      {}),
        }

        for cat, items in buckets.items():
            sec       = self._sections[cat]
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
                continue

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
