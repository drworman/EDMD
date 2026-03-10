"""
gui/block_base.py — BlockWidget base class for all dashboard blocks.

Widget tree per block:
  Gtk.Frame  (.dashboard-block)          ← placed on canvas
    Gtk.Box  (vertical)
      [content from build() / _build_section()]
      Gtk.Box  (.block-footer)            ← gutter row, always at bottom
        [future status items …]
        Gtk.Label  ⤡  (.resize-handle)   ← pinned right

Drag:   grab the section-header label — leaf widget, no children, no CAPTURE needed.
Resize: grab the ⤡ handle in the footer — also a leaf widget.
Neither gesture interferes with the other.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
except ImportError:
    raise ImportError(
        "PyGObject not found.\n"
        "  Arch/Manjaro:  pacman -S python-gobject gtk4\n"
        "  pip:           pip install PyGObject"
    )

from gui.helpers import make_label, make_section, make_row


class BlockWidget:
    BLOCK_TITLE: str = ""
    BLOCK_CSS:   str = "block"

    def __init__(self, core):
        self.core    = core
        self.state   = core.state
        self.session = core.active_session

        self._frame:  Gtk.Frame  | None = None
        self._root:   Gtk.Box    | None = None
        self._header: Gtk.Widget | None = None   # drag target
        self._footer: Gtk.Box    | None = None   # gutter row
        self._grid    = None
        self._window  = None
        self._name:   str = ""

        # Drag state
        self._drag_origin_x = 0.0
        self._drag_origin_y = 0.0
        self._dragging      = False
        self._drag_ghost: "Gtk.Frame | None" = None   # lightweight ghost overlay

        # Resize state
        self._resize_origin_w = 0.0
        self._resize_origin_h = 0.0
        self._resize_origin_x = 0.0
        self._resize_origin_y = 0.0
        self._resize_ghost: "Gtk.Frame | None" = None

    # ── Build ─────────────────────────────────────────────────────────────────

    def build_widget(self, name: str, grid, window) -> Gtk.Widget:
        self._name   = name
        self._grid   = grid
        self._window = window

        self._frame = Gtk.Frame()
        self._frame.add_css_class("dashboard-block")
        self._frame.set_hexpand(False)
        self._frame.set_vexpand(False)

        # Outer vertical box: content on top, footer gutter at bottom
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer_box.set_hexpand(True)
        outer_box.set_vexpand(True)
        self._frame.set_child(outer_box)

        # Content area — expands to fill available space above the footer
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_box.set_hexpand(True)
        content_box.set_vexpand(True)
        outer_box.append(content_box)

        # Let subclass populate content_box; this also sets self._header
        self.build(content_box)

        # Footer gutter — fixed height, never overlaps content
        self._footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._footer.add_css_class("block-footer")
        self._footer.set_hexpand(True)
        self._footer.set_vexpand(False)
        outer_box.append(self._footer)

        # Spacer pushes handle to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._footer.append(spacer)

        # Resize handle in footer — leaf widget, plain BUBBLE gesture
        handle = Gtk.Label(label="⤡")
        handle.add_css_class("resize-handle")
        handle.set_halign(Gtk.Align.END)
        handle.set_valign(Gtk.Align.CENTER)
        handle.set_cursor(Gdk.Cursor.new_from_name("se-resize"))
        self._footer.append(handle)

        # Wire gestures
        self._wire_resize(handle)
        drag_target = self._header if self._header is not None else self._frame
        self._wire_drag(drag_target)

        if self._header is not None:
            self._header.set_cursor(Gdk.Cursor.new_from_name("grab"))

        return self._frame

    def root_widget(self) -> Gtk.Widget | None:
        return self._frame

    # ── Footer access (for subclasses that want to add footer items) ──────────

    def footer(self) -> Gtk.Box | None:
        """Return the footer gutter box. Prepend items before the spacer."""
        return self._footer

    # ── Drag to move (header label only) ─────────────────────────────────────

    def _wire_drag(self, widget: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin",  self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end",    self._on_drag_end)
        widget.add_controller(drag)
        self._drag_gesture = drag

    def _on_drag_begin(self, gesture, start_x, start_y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._dragging = True
        cell = self._grid.cell_for(self._name)
        x, y, w, h = self._grid.pixel_rect(cell)
        self._drag_origin_x = float(x)
        self._drag_origin_y = float(y)
        if self._header:
            self._header.set_cursor(Gdk.Cursor.new_from_name("grabbing"))

        # Create ghost: an empty frame the same size as the block, placed on
        # the canvas.  Only this lightweight widget moves during the drag;
        # the real block stays put until drop.  This eliminates the stutter
        # caused by re-rendering the block's full widget tree on every
        # mouse-move event.
        ghost = Gtk.Frame()
        ghost.add_css_class("block-drag-ghost")
        ghost.set_size_request(w, h)
        self._window._canvas.put(ghost, x, y)
        ghost.set_visible(True)
        self._drag_ghost = ghost

        # Dim the real block to indicate it is being moved
        if self._frame:
            self._frame.add_css_class("block-dragging")

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if not self._dragging or self._drag_ghost is None:
            return
        # Move only the ghost — the real block does not move here
        nx = max(0.0, self._drag_origin_x + offset_x)
        ny = max(0.0, self._drag_origin_y + offset_y)
        self._window._canvas.move(self._drag_ghost, int(nx), int(ny))

    def _on_drag_end(self, gesture, offset_x, offset_y):
        self._dragging = False
        if self._header:
            self._header.set_cursor(Gdk.Cursor.new_from_name("grab"))
        if self._frame:
            self._frame.remove_css_class("block-dragging")

        # Destroy ghost
        if self._drag_ghost is not None:
            self._window._canvas.remove(self._drag_ghost)
            self._drag_ghost = None

        # Snap and commit the real block to its new position
        final_x = self._drag_origin_x + offset_x
        final_y = self._drag_origin_y + offset_y
        col = self._grid.snap_to_col(final_x)
        row = self._grid.snap_to_row(final_y)
        self._grid.move_block(self._name, col, row)
        cell = self._grid.cell_for(self._name)
        x, y, w, h = self._grid.pixel_rect(cell)
        if self._frame:
            self._window._canvas.move(self._frame, x, y)
            self._frame.set_size_request(w, h)
        self._grid.save()

    # ── Resize (⤡ handle in footer) ───────────────────────────────────────────

    def _wire_resize(self, handle: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin",  self._on_resize_begin)
        drag.connect("drag-update", self._on_resize_update)
        drag.connect("drag-end",    self._on_resize_end)
        handle.add_controller(drag)

    def _on_resize_begin(self, gesture, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        cell = self._grid.cell_for(self._name)
        bx, by, w, h = self._grid.pixel_rect(cell)
        self._resize_origin_w = float(w)
        self._resize_origin_h = float(h)
        self._resize_origin_x = float(bx)
        self._resize_origin_y = float(by)
        if self._frame:
            self._frame.add_css_class("block-resizing")
        # Ghost overlay anchored at block origin — only the ghost resizes during drag
        ghost = Gtk.Frame()
        ghost.add_css_class("block-drag-ghost")
        ghost.set_size_request(w, h)
        self._window._canvas.put(ghost, bx, by)
        ghost.set_visible(True)
        self._resize_ghost = ghost

    def _on_resize_update(self, gesture, offset_x, offset_y):
        if self._resize_ghost is None:
            return
        nw = max(80.0, self._resize_origin_w + offset_x)
        nh = max(40.0, self._resize_origin_h + offset_y)
        self._resize_ghost.set_size_request(int(nw), int(nh))

    def _on_resize_end(self, gesture, offset_x, offset_y):
        if self._frame:
            self._frame.remove_css_class("block-resizing")
        if self._resize_ghost is not None:
            self._window._canvas.remove(self._resize_ghost)
            self._resize_ghost = None
        from gui.grid import ROW_PX
        cw   = self._grid.col_width()
        nw   = max(80.0,  self._resize_origin_w + offset_x)
        nh   = max(40.0,  self._resize_origin_h + offset_y)
        cols = max(4, round(nw / cw))
        rows = max(2, round(nh / ROW_PX))
        self._grid.resize_block(self._name, cols, rows)
        cell = self._grid.cell_for(self._name)
        _, _, w, h = self._grid.pixel_rect(cell)
        if self._frame:
            self._frame.set_size_request(w, h)
        self._grid.save()

    # ── Section scaffolding ───────────────────────────────────────────────────

    def _build_section(
        self,
        parent: Gtk.Box,
        title: str | None = None,
        title_widget: Gtk.Widget | None = None,
    ) -> Gtk.Box:
        t = title if title is not None else self.BLOCK_TITLE
        outer, inner = make_section(t, title_widget=title_widget)
        outer.add_css_class(self.BLOCK_CSS)
        outer.set_hexpand(True)
        outer.set_vexpand(True)
        parent.append(outer)
        self._root = outer
        # First child of outer is the header label — use it as drag target
        self._header = outer.get_first_child()
        return inner

    # ── Visibility ────────────────────────────────────────────────────────────

    def set_visible(self, visible: bool) -> None:
        if self._root is not None:
            self._root.set_visible(visible)

    def is_visible(self) -> bool:
        return self._root.get_visible() if self._root is not None else False

    # ── Convenience re-exports ────────────────────────────────────────────────

    @staticmethod
    def make_label(text="", css_class=None, xalign=0.0):
        return make_label(text, css_class=css_class, xalign=xalign)

    @staticmethod
    def make_row(label_text, value_text="—"):
        return make_row(label_text, value_text)

    @staticmethod
    def make_section(title, title_widget=None):
        return make_section(title, title_widget=title_widget)

    def fmt_credits(self, n):
        return self.core.fmt_credits(n)

    def fmt_duration(self, s):
        return self.core.fmt_duration(s)

    def rate_per_hour(self, s, precision=None):
        return self.core.rate_per_hour(s, precision)

    # ── Subclass interface ────────────────────────────────────────────────────

    def build(self, parent: Gtk.Box) -> None:
        self._build_section(parent)

    def refresh(self) -> None:
        pass

    def on_resize(self, w: int, h: int) -> None:
        """Called by the window after every set_size_request on this block.
        Override in subclasses that need to respond to their own pixel width,
        e.g. to switch between layout modes.  Default is a no-op."""
        pass
