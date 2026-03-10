# EDMD Plugin Development Guide

> **API stability:** The plugin interface is stable as of v20260310.
> Breaking changes will be versioned and announced in release notes.

---

## Overview

EDMD plugins are Python modules dropped into the `plugins/` directory.
They subscribe to Elite Dangerous journal events, can render dashboard blocks,
and can store persistent data — all without modifying EDMD's core.

Builtins (in `builtins/`) ship with EDMD and follow the same API.
Third-party plugins (in `plugins/`) work identically.

---

## Quick start

```
plugins/
└── myplugin/
    └── plugin.py      ← your code lives here
```

`plugins/` is git-ignored — your plugins survive `--upgrade`.

---

## Minimal plugin

```python
from core.plugin_loader import BasePlugin

class MyPlugin(BasePlugin):
    PLUGIN_NAME        = "myplugin"          # unique machine name
    PLUGIN_DISPLAY     = "My Plugin"         # shown in Installed Plugins dialog
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "One-line description shown in the plugin dialog."
    SUBSCRIBED_EVENTS  = ["Bounty", "FactionKillBond"]

    # Remove this line (or set True) to ship enabled by default.
    PLUGIN_DEFAULT_ENABLED = False

    def on_load(self, core) -> None:
        super().on_load(core)        # sets self.core; always call this first
        # self.storage is also available here — see Storage section below

    def on_event(self, event: dict, state) -> None:
        ev     = event.get("event")
        reward = event.get("TotalReward", 0)
        # event — the parsed journal line dict (includes "_logtime": datetime)
        # state — live MonitorState instance
```

---

## Class attributes reference

| Attribute | Type | Required | Default | Notes |
|---|---|---|---|---|
| `PLUGIN_NAME` | `str` | ✅ | — | Machine name; must be unique across all plugins |
| `PLUGIN_DISPLAY` | `str` | ✅ | — | Human name shown in dialog |
| `PLUGIN_VERSION` | `str` | — | `"0.0.1"` | Semver recommended |
| `PLUGIN_DESCRIPTION` | `str` | — | `""` | One-liner shown below the name in dialog |
| `SUBSCRIBED_EVENTS` | `list[str]` | — | `[]` | Journal event names to receive |
| `PLUGIN_DEFAULT_ENABLED` | `bool` | — | `True` | Set `False` to ship disabled |
| `BLOCK_WIDGET_CLASS` | `type\|None` | — | `None` | Set to a `BlockWidget` subclass to add a dashboard block |

---

## Lifecycle

```
plugin.py found
    │
    ▼
Module imported (sandbox applied)
    │
    ▼
Class found, metadata read
    │
    ├─[disabled]─▶  recorded in dialog, on_load NOT called
    │
    └─[enabled]──▶  instance created
                        │
                        ├─ self.storage set
                        ├─ self._is_builtin set
                        │
                        ▼
                   on_load(core) called
                        │
                        ▼
                   on_event(event, state) called per subscribed event
                        │
                        ▼
                   on_unload() called on clean shutdown
```

---

## Enable / disable

Users toggle plugins in **🔌 Plugins → Installed Plugins**.
The state is persisted to `EDMD_DATA_DIR/plugin_states.json`.
Changes take effect after restart.

`PLUGIN_DEFAULT_ENABLED = False` ships a plugin in the disabled state.
The user enables it explicitly.  This is the right default for any plugin
that makes network requests, writes data, or changes behaviour that the user
needs to understand first.

---

## Persistent storage

Each plugin has a sandboxed storage directory:

```
~/.local/share/EDMD/plugins/<plugin_name>/
```

Use the `self.storage` API — do **not** use `open()` directly for writes.
Writing outside this directory will raise `PermissionError` at runtime.

```python
def on_load(self, core) -> None:
    super().on_load(core)

    # Read existing data (returns {} if file absent)
    data = self.storage.read_json("data.json")
    self._session_count = data.get("sessions", 0) + 1

    # Write updated data
    self.storage.write_json({"sessions": self._session_count}, "data.json")
```

### Storage API

| Method | Description |
|---|---|
| `storage.read_json(filename)` | Read JSON → dict.  Default filename: `"data.json"` |
| `storage.write_json(data, filename)` | Write dict → JSON (atomic). Default: `"data.json"` |
| `storage.read_toml(filename)` | Read TOML → dict (read-only).  Default: `"config.toml"` |
| `storage.path` | `Path` to the plugin's data directory |

### Allowed filenames

Only these filenames are permitted:

```
data.json    config.json    state.json
config.toml  state.toml
```

Path separators and `..` are rejected.

### TOML config convention

If your plugin has user-editable settings, use `config.toml` for those and
`data.json` for mutable runtime state.  Write documentation for your config
keys — EDMD has no auto-generated config UI for third-party plugins.

---

## CoreAPI reference

Every plugin receives a `CoreAPI` instance via `on_load(core)`.

### State and session data

| Attribute | Type | Description |
|---|---|---|
| `core.state` | `MonitorState` | Live game state |
| `core.active_session` | `SessionData` | Current session counters |
| `core.lifetime` | `SessionData` | Lifetime totals |
| `core.journal_dir` | `Path` | Active journal directory |
| `core.trace_mode` | `bool` | True if `--trace` was passed |

### Configuration

| Method | Description |
|---|---|
| `core.cfg.load_setting(category, defaults, warn)` | Resolve a settings block from config.toml with profile fallback |
| `core.cfg.pcfg(key, default)` | Read a profile-only key |
| `core.app_settings` | Resolved `[Settings]` block |
| `core.notify_levels` | Resolved `[LogLevels]` block |

### Emitting output

```python
core.emitter.emit(
    msg_term   = "Terminal message",
    msg_discord= "Discord message",
    emoji      = "💥",
    sigil      = "!! KILL",
    timestamp  = event.get("_logtime"),
    loglevel   = core.notify_levels.get("RewardEvent", 2),
)
```

| Parameter | Description |
|---|---|
| `msg_term` | Text written to terminal |
| `msg_discord` | Text sent to Discord webhook (omit to suppress) |
| `emoji` | Emoji prefix for Discord |
| `sigil` | 7-char label in terminal log lines |
| `timestamp` | `datetime` (pass `event["_logtime"]`) |
| `loglevel` | 0 = suppress, 1–3 = verbosity threshold |

### GUI queue

Signal the GUI to refresh a block:

```python
if core.gui_queue:
    core.gui_queue.put(("plugin_refresh", self.PLUGIN_NAME))
```

Standard message types:

| Message | Payload | Effect |
|---|---|---|
| `plugin_refresh` | plugin name | Refresh that plugin's block |
| `all_update` | `None` | Refresh all blocks |
| `alerts_update` | `None` | Refresh Alerts block |

### Plugin-to-plugin calls

```python
result = core.plugin_call("missions", "get_stack_value")
```

Returns `None` if the named plugin is not loaded or the method doesn't exist.
Do not import other plugin modules directly.

### Formatting helpers

```python
core.fmt_credits(1_500_000)   # → "1.50M"
core.fmt_duration(3661)       # → "1h 1m"
core.rate_per_hour(120, 3661) # → "117.8/hr"
core.clip_name("Long Name", 20)
```

---

## Adding a dashboard block

The dashboard block framework provides all chrome — frame, section header,
drag-to-move, resize handle, footer gutter.  Your plugin fills only the
content area.  Layout is consistent regardless of who wrote the plugin.

### Step 1 — Guard GTK4 imports

```python
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    _GTK_AVAILABLE = True
except Exception:
    _GTK_AVAILABLE = False

if _GTK_AVAILABLE:
    from gui.block_base import BlockWidget
```

This ensures your plugin loads in terminal-only mode (no GTK4 present).

### Step 2 — Write a BlockWidget subclass

```python
if _GTK_AVAILABLE:
    class MyBlock(BlockWidget):
        BLOCK_TITLE    = "My Plugin"   # section header text

        DEFAULT_COL    = 16            # default grid position
        DEFAULT_ROW    = 30
        DEFAULT_WIDTH  = 8
        DEFAULT_HEIGHT = 6

        def build(self, parent: Gtk.Box) -> None:
            """Populate the content area.  Called once at startup."""
            body = self._build_section(parent)    # returns inner content box

            self._value = self.make_label("—", css_class="data-value")
            body.append(self.make_row("Stat label"))
            body.append(self._value)

        def refresh(self) -> None:
            """Called every tick and on plugin_refresh queue messages."""
            val = getattr(self.core.state, "my_stat", 0)
            self._value.set_label(str(val))
```

### Step 3 — Register the block in your plugin

```python
class MyPlugin(BasePlugin):
    PLUGIN_NAME        = "myplugin"
    BLOCK_WIDGET_CLASS = MyBlock if _GTK_AVAILABLE else None

    def on_load(self, core) -> None:
        super().on_load(core)
        if _GTK_AVAILABLE:
            core.register_block(self, priority=60)
```

`priority` controls sort order in the View → Blocks menu (lower = earlier).
Default grid position is used only when the user has no saved layout entry.

### BlockWidget API

| Method | Returns | Description |
|---|---|---|
| `self._build_section(parent, title)` | `Gtk.Box` | Sets up frame + header; returns inner content box |
| `self.make_label(text, css_class, xalign)` | `Gtk.Label` | Styled label |
| `self.make_row(key, value)` | `Gtk.Box` | Key / value row |
| `self.footer()` | `Gtk.Box` | Footer gutter — prepend status items here |
| `self.state` | `MonitorState` | Live game state |
| `self.session` | `SessionData` | Current session |
| `self.core` | `CoreAPI` | Full core API |
| `self.fmt_credits(n)` | `str` | Format credits |
| `self.fmt_duration(s)` | `str` | Format duration |

---

## MonitorState quick reference

Fields guaranteed to exist at `on_event` time:

| Field | Type | Description |
|---|---|---|
| `state.pilot_name` | `str` | Commander name |
| `state.pilot_ship` | `str` | Ship model (internal name) |
| `state.pilot_system` | `str` | Current star system |
| `state.pilot_rank` | `str` | Combat rank name |
| `state.in_preload` | `bool` | True during journal replay at startup |
| `state.in_game` | `bool` | True when in-game |
| `state.fuel_tank_size` | `float` | Fuel tank capacity |

Always check `state.in_preload` before acting on events you don't want to
replay from history (e.g. quit triggers, Discord notifications).

---

## Security requirements

EDMD will be used on systems where Elite Dangerous is running.  Plugins run
in the same process with the same privileges as EDMD.  This is unavoidable
in Python without subprocess isolation.

**As a plugin author you must:**

- Use `self.storage.write_json()` for all file writes
- Not write to any path outside your storage directory
- Not make network requests without clear user documentation and config opt-in
- Not import `subprocess`, `os.system`, or `ctypes` unless you have an
  explicit and documented reason
- Not read from `core.cfg` keys you did not define — other plugins' config
  sections are not part of your API
- Not call `plugin_call()` in a way that could affect another plugin's state
  unless that plugin explicitly documents the method as callable

**EDMD enforces:**

- Write sandbox: `open()` is patched in your module's namespace; writes outside
  your data directory raise `PermissionError` at runtime
- Storage filename allowlist: only `data.json`, `config.json`, `state.json`,
  `config.toml`, `state.toml` are accepted

**EDMD cannot enforce** (Python limitation):

- Preventing import of `builtins` to bypass the write sandbox
- Network access restrictions
- CPU or memory usage limits

Plugins are installed by the user.  **Distribute only from sources you trust.
Do not install plugins you have not read.**

---

## Example plugin

A complete example lives at `plugins/welcome/plugin.py`.  It ships disabled
by default and demonstrates storage, block rendering, and GTK guards.

Enable it in **🔌 Plugins → Installed Plugins** and restart.

---

## Checklist before distributing

- [ ] `PLUGIN_NAME` is unique and lowercase with no spaces
- [ ] `PLUGIN_DISPLAY` and `PLUGIN_DESCRIPTION` are set
- [ ] `PLUGIN_DEFAULT_ENABLED = False` if the plugin needs user opt-in
- [ ] All file writes go through `self.storage`
- [ ] GTK imports are guarded with try/except
- [ ] `on_load` calls `super().on_load(core)` first
- [ ] `on_event` checks `state.in_preload` before acting on trigger events
- [ ] Network requests (if any) are documented and gated on a config key
- [ ] README / docs explain what the plugin does and how to configure it
