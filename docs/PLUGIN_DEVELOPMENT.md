# EDMD Plugin Development

EDMD supports user-written plugins. Drop a plugin into `plugins/<name>/plugin.py` and it will be loaded automatically on startup alongside the five built-in modules.

> **Note:** The plugin interface is new and may evolve. No stability guarantees until v2.

---

## Plugin Location

```
plugins/
└── myplugin/
    └── plugin.py
```

The `plugins/` directory is gitignored — your plugins will not be overwritten by `--upgrade`.

---

## Minimal Plugin

```python
from core.plugin_loader import BasePlugin

class MyPlugin(BasePlugin):
    PLUGIN_NAME       = "myplugin"
    DISPLAY           = "My Plugin"
    VERSION           = "1.0"
    SUBSCRIBED_EVENTS = ["Bounty", "FactionKillBond"]

    def on_load(self, core_api) -> None:
        self.core = core_api

    def on_event(self, j: dict, state) -> None:
        if j.get("event") == "Bounty":
            # j contains the parsed journal line
            # state is the live MonitorState
            pass
```

---

## CoreAPI Reference

Your plugin receives a `CoreAPI` instance in `on_load`. It exposes:

| Attribute / Method | Description |
|--------------------|-------------|
| `core.state` | Live `MonitorState` |
| `core.active_session` | `SessionData` for the current session |
| `core.cfg` | `ConfigManager` — use `.pcfg(key)` for profile-aware config lookup |
| `core.emit(msg_term, msg_discord, ...)` | Post an event to terminal, GUI, and Discord |
| `core.gui_queue` | Thread-safe queue — put `(msg_type, payload)` tuples to update the GUI |
| `core.plugin_call(name, method, *args)` | Call a method on another loaded plugin; returns `None` if not loaded |
| `core.fmt_credits(n)` | Format a credit value (e.g. `1.50M`) |
| `core.fmt_duration(s)` | Format a duration in seconds (e.g. `1:30:00`) |
