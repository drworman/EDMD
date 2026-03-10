"""
gui/grid.py — 24-column snap grid layout engine for the EDMD dashboard.

Manages block positions in grid units, handles persistence to layout.json,
and provides the GTK Fixed container that blocks are placed into.

Grid model:
  - 24 columns, each = 1/24 of the available canvas width
  - Row height units = ROW_PX pixels each (default 40)
  - 8px gap between all blocks
  - Minimum block: 4 wide × 2 tall
  - Layout persisted to ~/.local/share/EDMD/layout.json
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from core.state import EDMD_DATA_DIR

LAYOUT_FILE = Path(EDMD_DATA_DIR) / "layout.json"

COLS     = 24
ROW_PX   = 20
GAP      = 4
MIN_W    = 4
MIN_H    = 1

# Default block layout — used when layout.json is absent or malformed.
# Heights doubled from original values to compensate for halved ROW_PX.
DEFAULT_LAYOUT = {
    # Row 0 — identity/status strip (3 equal blocks, full 24 cols)
    "commander":    {"col": 0,  "row": 0,  "width": 8,  "height": 10},
    "session_stats":{"col": 8,  "row": 0,  "width": 8,  "height": 10},
    "crew_slf":     {"col": 16, "row": 0,  "width": 8,  "height": 10},
    # Row 10 — mission/cargo/materials (10+6+8 = 24 cols, no gap, no overlap)
    # materials at width=8 (~424px at 1280) exceeds the wide-layout threshold.
    "missions":     {"col": 0,  "row": 10, "width": 10, "height": 10},
    "cargo":        {"col": 10, "row": 10, "width": 6,  "height": 10},
    "materials":    {"col": 16, "row": 10, "width": 8,  "height": 10},
    # Row 20 — alerts full width
    "alerts":       {"col": 0,  "row": 20, "width": 24, "height": 8},
}


@dataclass
class GridCell:
    col:    int
    row:    int
    width:  int
    height: int


class BlockGrid:
    """
    Manages the dashboard grid layout.

    Usage:
        grid = BlockGrid(canvas_width=1280)
        cell = grid.cell_for("commander")         # GridCell
        x, y, w, h = grid.pixel_rect(cell)        # pixel coords for placement
        grid.move_block("commander", col=4, row=0) # update position
        grid.save()                                # persist to disk
    """

    def __init__(self, canvas_width: int = 1280, canvas_height: int = 760):
        self._canvas_width  = canvas_width
        self._canvas_height = canvas_height
        self._cells: dict[str, GridCell] = {}
        self._load()

    # ── Layout persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load layout from disk, falling back to defaults.

        After loading, any block present in DEFAULT_LAYOUT but absent from the
        saved file (e.g. a newly introduced block) is inserted at its default
        position and the file is re-saved so the entry persists for next time.
        """
        try:
            data = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
            blocks = data.get("blocks", {})
            for name, d in blocks.items():
                self._cells[name] = GridCell(
                    col=int(d["col"]),
                    row=int(d["row"]),
                    width=max(MIN_W, int(d["width"])),
                    height=max(MIN_H, int(d["height"])),
                )
            # Backfill any blocks that exist in DEFAULT_LAYOUT but are missing
            # from the saved file — happens when a new block is introduced.
            added = False
            for name, d in DEFAULT_LAYOUT.items():
                if name not in self._cells:
                    self._cells[name] = GridCell(**d)
                    added = True
            if added:
                self.save()
        except Exception:
            self._apply_defaults()

    def _apply_defaults(self) -> None:
        for name, d in DEFAULT_LAYOUT.items():
            self._cells[name] = GridCell(**d)

    def save(self) -> None:
        """Persist current layout to disk."""
        try:
            LAYOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"blocks": {n: asdict(c) for n, c in self._cells.items()}}
            LAYOUT_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass   # non-fatal

    def reset(self) -> None:
        """Reset all blocks to default positions and save."""
        self._cells.clear()
        self._apply_defaults()
        self.save()

    # ── Cell access ───────────────────────────────────────────────────────────

    def register_plugin_default(
        self,
        name: str,
        col: int,
        row: int,
        width: int,
        height: int,
    ) -> None:
        """Register a default position for a plugin block.

        Called by the window during block construction when the block class
        declares DEFAULT_COL / DEFAULT_ROW / DEFAULT_WIDTH / DEFAULT_HEIGHT.
        Only takes effect when there is no saved layout entry for this block.
        Has no effect after a layout entry already exists.
        """
        if name not in self._cells:
            self._cells[name] = GridCell(
                col=max(0, col),
                row=max(0, row),
                width=max(MIN_W, width),
                height=max(MIN_H, height),
            )

    def cell_for(self, name: str) -> GridCell:
        """Return the GridCell for a block, using defaults if unknown."""
        if name not in self._cells:
            d = DEFAULT_LAYOUT.get(name)
            if d:
                self._cells[name] = GridCell(**d)
            else:
                self._cells[name] = GridCell(col=0, row=0, width=MIN_W, height=MIN_H)
        return self._cells[name]

    def move_block(self, name: str, col: int, row: int) -> None:
        c = self.cell_for(name)
        c.col = max(0, min(col, COLS - c.width))
        c.row = max(0, row)

    def resize_block(self, name: str, width: int, height: int) -> None:
        c = self.cell_for(name)
        c.width  = max(MIN_W, min(width, COLS - c.col))
        c.height = max(MIN_H, height)

    # ── Pixel geometry ────────────────────────────────────────────────────────

    def col_width(self) -> float:
        """Width of one column unit in pixels."""
        return (self._canvas_width - GAP) / COLS

    def row_height(self) -> float:
        """Height of one row unit in pixels.
        Equals ROW_PX normally; scales down proportionally if the canvas is
        shorter than the natural layout extent so blocks always fit."""
        natural_rows = self._natural_row_extent()
        natural_h    = natural_rows * ROW_PX
        if natural_h <= 0 or self._canvas_height >= natural_h:
            return float(ROW_PX)
        return max(ROW_PX / 2, self._canvas_height / natural_rows)

    def _natural_row_extent(self) -> int:
        """Total rows spanned by the current layout (max row + height)."""
        if not self._cells:
            return 24   # fallback
        return max(c.row + c.height for c in self._cells.values())

    def pixel_rect(self, cell: GridCell) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) in pixels for a GridCell."""
        cw = self.col_width()
        rh = self.row_height()
        x  = int(cell.col * cw + GAP)
        y  = int(cell.row * rh + GAP)
        w  = int(cell.width  * cw - GAP)
        h  = int(cell.height * rh - GAP)
        return x, y, w, h

    def snap_to_col(self, px: float) -> int:
        """Snap a pixel x-coordinate to the nearest column index."""
        cw = self.col_width()
        col = round((px - GAP) / cw)
        return max(0, min(col, COLS - 1))

    def snap_to_row(self, py: float) -> int:
        """Snap a pixel y-coordinate to the nearest row index."""
        rh = self.row_height()
        row = round((py - GAP) / rh)
        return max(0, row)

    def update_canvas_width(self, width: int) -> None:
        """Call when the window width changes."""
        self._canvas_width = max(1, width)

    def update_canvas_height(self, height: int) -> None:
        """Call when the window height changes."""
        self._canvas_height = max(1, height)
