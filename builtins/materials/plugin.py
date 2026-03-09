"""
builtins/materials/plugin.py — Engineering materials inventory tracking.

Tracks the three material categories that do NOT consume cargo hold space:
  Raw          — geological elements (e.g. Carbon, Vanadium, Polonium)
  Manufactured — salvaged tech components (e.g. Heat Conductors, Polymer Capacitors)
  Encoded      — scanned data (e.g. Modified Consumer Firmware, Unexpected Emission Data)

These are accumulated separately from cargo and are used at engineers.

State stored on MonitorState:
    materials_raw          dict   — {name_lower: {"count": int, "name_local": str}}
    materials_manufactured dict
    materials_encoded      dict

GUI block: materials
"""

from core.plugin_loader import BasePlugin


class MaterialsPlugin(BasePlugin):
    PLUGIN_NAME    = "materials"
    PLUGIN_DISPLAY = "Materials"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Materials",            # Full snapshot — always authoritative
        "MaterialCollected",    # Picked up one item
        "MaterialDiscarded",    # Discarded one or more
        "MaterialTrade",        # Traded at a material trader
        "EngineerCraft",        # Consumed materials for a blueprint
        "TechnologyBroker",     # Consumed materials for a tech unlock
        "Synthesis",            # Consumed materials for synthesis (ammo, repair, etc.)
        "LoadGame",             # Session start — Materials snapshot follows
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=50)
        s = core.state
        if not hasattr(s, "materials_raw"):          s.materials_raw          = {}
        if not hasattr(s, "materials_manufactured"): s.materials_manufactured = {}
        if not hasattr(s, "materials_encoded"):      s.materials_encoded      = {}

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "Materials":
                # Full authoritative snapshot across all three categories
                state.materials_raw          = _parse_list(event.get("Raw", []))
                state.materials_manufactured = _parse_list(event.get("Manufactured", []))
                state.materials_encoded      = _parse_list(event.get("Encoded", []))
                if gq: gq.put(("plugin_refresh", "materials"))

            case "MaterialCollected":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _bucket(state, cat)
                if bucket is not None and key:
                    entry = bucket.setdefault(key, {
                        "count":      0,
                        "name_local": event.get("Name_Localised") or _fmt_name(key),
                    })
                    entry["count"] += count
                if gq: gq.put(("plugin_refresh", "materials"))

            case "MaterialDiscarded":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _bucket(state, cat)
                if bucket is not None and key and key in bucket:
                    bucket[key]["count"] -= count
                    if bucket[key]["count"] <= 0:
                        del bucket[key]
                if gq: gq.put(("plugin_refresh", "materials"))

            case "MaterialTrade":
                paid = event.get("Paid", {})
                recv = event.get("Received", {})
                for side, delta in [(paid, -1), (recv, 1)]:
                    cat    = side.get("Category", "").lower()
                    key    = side.get("Name", "").lower()
                    count  = int(side.get("Count", 1)) * delta
                    bucket = _bucket(state, cat)
                    if bucket is not None and key:
                        if count < 0:
                            if key in bucket:
                                bucket[key]["count"] += count
                                if bucket[key]["count"] <= 0:
                                    del bucket[key]
                        else:
                            entry = bucket.setdefault(key, {
                                "count":      0,
                                "name_local": side.get("Name_Localised") or _fmt_name(key),
                            })
                            entry["count"] += count
                if gq: gq.put(("plugin_refresh", "materials"))

            case "EngineerCraft" | "TechnologyBroker" | "Synthesis":
                key_ingr = "Ingredients" if ev != "Synthesis" else "Materials"
                for item in event.get(key_ingr, []):
                    cat    = item.get("Category", "").lower()
                    key    = item.get("Name", "").lower()
                    count  = int(item.get("Count", 1))
                    bucket = _bucket(state, cat)
                    # Fallback: if no Category in ingredient, search all buckets
                    if bucket is None:
                        for b in (state.materials_raw,
                                  state.materials_manufactured,
                                  state.materials_encoded):
                            if key in b:
                                bucket = b
                                break
                    if bucket is not None and key and key in bucket:
                        bucket[key]["count"] -= count
                        if bucket[key]["count"] <= 0:
                            del bucket[key]
                if gq: gq.put(("plugin_refresh", "materials"))

            case "LoadGame":
                state.materials_raw          = {}
                state.materials_manufactured = {}
                state.materials_encoded      = {}
                if gq: gq.put(("plugin_refresh", "materials"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_list(items: list) -> dict:
    result = {}
    for item in items:
        key = item.get("Name", "").lower()
        if not key:
            continue
        result[key] = {
            "count":      int(item.get("Count", 0)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return result


def _bucket(state, category: str):
    """Return the correct materials dict for a category string."""
    if "raw" in category:          return state.materials_raw
    if "manufactured" in category: return state.materials_manufactured
    if "encoded" in category:      return state.materials_encoded
    return None


def _fmt_name(key: str) -> str:
    return key.replace("_", " ").title()
