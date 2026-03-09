"""
builtins/cargo/plugin.py — Ship cargo inventory tracking.

Tracks the current cargo hold: capacity, used slots, and per-item breakdown.
Only cargo items (those that consume hold space) are tracked here.
Engineering materials, raw/manufactured/data commodities go in the
materials builtin.

Cargo.json strategy
-------------------
The game writes Cargo.json to the journal directory whenever the hold
changes.  It is always the ship's cargo (never SRV or Fighter), so we
read it on every "Cargo" journal event rather than parsing the event's
Inventory array directly — which suffers from multiple per-vessel events
firing in sequence with the SRV/Fighter snapshots overwriting the ship's.

On on_load we also attempt an immediate bootstrap read of Cargo.json so
the block shows data before a journal Cargo event fires.

State stored on MonitorState:
    cargo_capacity   int    — maximum hold tonnage (from Loadout)
    cargo_items      dict   — {name: {"count": int, "stolen": bool, "name_local": str}}

GUI block: cargo
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin


class CargoPlugin(BasePlugin):
    PLUGIN_NAME    = "cargo"
    PLUGIN_DISPLAY = "Cargo"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Cargo",            # Trigger to re-read Cargo.json
        "CollectCargo",     # Scooped/picked up
        "EjectCargo",       # Dropped
        "MarketBuy",        # Bought commodity
        "MarketSell",       # Sold commodity
        "MiningRefined",    # Refined ore into hold
        "CargoDepot",       # Wing mission cargo delivery/collection
        "Loadout",          # Gives us hold capacity via CargoCapacity field
        "LoadGame",         # Session start — Cargo.json / journal Cargo event follows
        "Died",             # Ship destroyed — cargo lost
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=45)
        s = core.state
        if not hasattr(s, "cargo_capacity"):
            s.cargo_capacity = 0
        if not hasattr(s, "cargo_items"):
            s.cargo_items = {}
        # Bootstrap from Cargo.json immediately so the block isn't blank
        # before the first journal Cargo event fires.
        items = _read_cargo_json(core.journal_dir)
        if items is not None:
            s.cargo_items = items

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "Loadout":
                cap = event.get("CargoCapacity", 0)
                if cap:
                    state.cargo_capacity = int(cap)
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Cargo":
                # Journal fires one Cargo event per vessel (Ship, SRV, Fighter).
                # Cargo.json always contains the ship hold — read that instead.
                items = _read_cargo_json(core.journal_dir)
                if items is not None:
                    state.cargo_items = items
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "CollectCargo":
                key = event.get("Type", "").lower()
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count":      0,
                        "stolen":     bool(event.get("Stolen", False)),
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += 1
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "EjectCargo":
                key   = event.get("Type", "").lower()
                count = int(event.get("Count", 1))
                if key and key in state.cargo_items:
                    state.cargo_items[key]["count"] -= count
                    if state.cargo_items[key]["count"] <= 0:
                        del state.cargo_items[key]
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MarketBuy":
                key   = event.get("Type", "").lower()
                count = int(event.get("Count", 1))
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count":      0,
                        "stolen":     False,
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += count
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MarketSell":
                key   = event.get("Type", "").lower()
                count = int(event.get("Count", 1))
                if key and key in state.cargo_items:
                    state.cargo_items[key]["count"] -= count
                    if state.cargo_items[key]["count"] <= 0:
                        del state.cargo_items[key]
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MiningRefined":
                key = event.get("Type", "").lower()
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count":      0,
                        "stolen":     False,
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += 1
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "CargoDepot":
                # Wing mission — re-read Cargo.json for authoritative state
                items = _read_cargo_json(core.journal_dir)
                if items is not None:
                    state.cargo_items = items
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Died":
                state.cargo_items = {}
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "LoadGame":
                # Clear on new session; Cargo.json / journal Cargo event follows shortly
                state.cargo_items = {}
                if gq: gq.put(("plugin_refresh", "cargo"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_cargo_json(journal_dir) -> dict | None:
    """
    Read Cargo.json from the journal directory and return a cargo_items dict.

    Returns None on any error (file missing, parse failure, etc.).
    Cargo.json items lack Name_Localised, so _fmt_name() is the display fallback.
    """
    if journal_dir is None:
        return None
    path = Path(journal_dir) / "Cargo.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    result = {}
    for item in data.get("Inventory", []):
        key = item.get("Name", "").lower()
        if not key:
            continue
        result[key] = {
            "count":      int(item.get("Count", 1)),
            "stolen":     bool(item.get("Stolen", False)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return result


def _fmt_name(key: str) -> str:
    """Fallback localised name from internal key: 'food_cartridges' → 'Food Cartridges'."""
    return key.replace("_", " ").title()
