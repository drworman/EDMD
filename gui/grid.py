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
ROW_PX   = 40
GAP      = 8
MIN_W    = 4
MIN_H    = 2

# Default block layout — used when layout.json is absent or malformed.
DEFAULT_LAYOUT = {
    "commander":    {"col": 0,  "row": 0, "width": 8,  "height": 5},
    "session_stats":{"col": 8,  "row": 0, "width": 8,  "height": 5},
    "crew_slf":     {"col": 16, "row": 0, "width": 8,  "height": 5},
    "missions":     {"col": 0,  "row": 5, "width": 12, "height": 4},
    "alerts":       {"col": 0,  "row": 9, "width": 24, "height": 3},
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

    def __init__(self, canvas_width: int = 1280):
        self._canvas_width = canvas_width
        self._cells: dict[str, GridCell] = {}
        self._load()

    # ── Layout persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load layout from disk, falling back to defaults."""
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

    def pixel_rect(self, cell: GridCell) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) in pixels for a GridCell."""
        cw = self.col_width()
        x  = int(cell.col * cw + GAP)
        y  = int(cell.row * ROW_PX + GAP)
        w  = int(cell.width * cw - GAP)
        h  = int(cell.height * ROW_PX - GAP)
        return x, y, w, h

    def snap_to_col(self, px: float) -> int:
        """Snap a pixel x-coordinate to the nearest column index."""
        cw = self.col_width()
        col = round((px - GAP) / cw)
        return max(0, min(col, COLS - 1))

    def snap_to_row(self, py: float) -> int:
        """Snap a pixel y-coordinate to the nearest row index."""
        row = round((py - GAP) / ROW_PX)
        return max(0, row)

    def update_canvas_width(self, width: int) -> None:
        """Call when the window is resized so pixel geometry stays correct."""
        self._canvas_width = max(1, width)
