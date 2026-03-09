"""
gui/block_base.py — BlockWidget base class for all dashboard blocks.

New contract for the grid-based dashboard:
  - build_widget() -> Gtk.Widget   build and return the root widget (Gtk.Frame)
  - root_widget()  -> Gtk.Widget   return the already-built root widget (or None)
  - refresh()                      update widget labels from state

The old build(parent) contract is preserved for compatibility but no longer
used by EdmdWindow. Blocks now return their root widget and EdmdWindow places
them on the canvas directly via Gtk.Fixed.

Each block is wrapped in a Gtk.Frame (dashboard-block class) so it has a
visible border and can receive a title. The inner content Gtk.Box is returned
by _build_section() for subclasses to append their data rows into.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError(
        "PyGObject not found.\n"
        "  Arch/Manjaro:  pacman -S python-gobject gtk4\n"
        "  pip:           pip install PyGObject"
    )

from gui.helpers import make_label, make_section, make_row


class BlockWidget:
    """Base class for all EDMD dashboard blocks."""

    BLOCK_TITLE: str = ""
    BLOCK_CSS:   str = "block"

    def __init__(self, core):
        self.core    = core
        self.state   = core.state
        self.session = core.active_session
        self._frame: Gtk.Frame | None  = None   # outermost widget placed on canvas
        self._root:  Gtk.Box  | None   = None   # panel-section box (inner)

    # ── Grid dashboard interface ──────────────────────────────────────────────

    def build_widget(self) -> Gtk.Widget:
        """
        Build the block and return the root Gtk.Frame for placement on the
        canvas.  Called once by EdmdWindow during startup.

        Wraps the existing build() method in a Gtk.Frame so each block has
        a consistent border and CSS handle (.dashboard-block).
        """
        self._frame = Gtk.Frame()
        self._frame.add_css_class("dashboard-block")
        self._frame.set_hexpand(True)
        self._frame.set_vexpand(True)

        inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        inner_box.set_hexpand(True)
        inner_box.set_vexpand(True)
        self._frame.set_child(inner_box)

        self.build(inner_box)
        return self._frame

    def root_widget(self) -> Gtk.Widget | None:
        """Return the already-built root widget, or None if not yet built."""
        return self._frame

    # ── Legacy interface (still used internally by build_widget) ─────────────

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
        return inner

    # ── Visibility ────────────────────────────────────────────────────────────

    def set_visible(self, visible: bool) -> None:
        if self._root is not None:
            self._root.set_visible(visible)

    def is_visible(self) -> bool:
        return self._root.get_visible() if self._root is not None else False

    # ── Convenience re-exports ────────────────────────────────────────────────

    @staticmethod
    def make_label(text: str = "", css_class=None, xalign: float = 0.0) -> Gtk.Label:
        return make_label(text, css_class=css_class, xalign=xalign)

    @staticmethod
    def make_row(label_text: str, value_text: str = "—") -> tuple:
        return make_row(label_text, value_text)

    @staticmethod
    def make_section(title: str, title_widget=None) -> tuple:
        return make_section(title, title_widget=title_widget)

    # ── Formatting helpers ────────────────────────────────────────────────────

    def fmt_credits(self, n) -> str:
        return self.core.fmt_credits(n)

    def fmt_duration(self, s) -> str:
        return self.core.fmt_duration(s)

    def rate_per_hour(self, s, precision=None) -> float:
        return self.core.rate_per_hour(s, precision)

    # ── Subclass interface ────────────────────────────────────────────────────

    def build(self, parent: Gtk.Box) -> None:
        """Build all widgets and append root section to parent."""
        self._build_section(parent)

    def refresh(self) -> None:
        """Update widget labels from state. Safe to call at any time."""
