# EDMD Plugin Development

EDMD supports user-written plugins. Drop a plugin into `plugins/<name>/plugin.py`
and it will be loaded automatically on startup alongside the five built-in modules.

> **Stability note:** Event handling and GUI block interfaces are stable as of v20260309.

---

## Plugin Location

```
plugins/
└── myplugin/
    └── plugin.py
```

The `plugins/` directory is gitignored — your work survives `--upgrade`.

---

## Minimal Plugin (event handler only)

```python
from core.plugin_loader import BasePlugin

class MyPlugin(BasePlugin):
    PLUGIN_NAME        = "myplugin"
    PLUGIN_DISPLAY     = "My Plugin"
    PLUGIN_VERSION     = "1.0.0"
    SUBSCRIBED_EVENTS  = ["Bounty", "FactionKillBond"]

    def on_load(self, core) -> None:
        self.core = core

    def on_event(self, event: dict, state) -> None:
        reward = event.get("TotalReward", 0)
        # event is the parsed journal line
        # state is the live MonitorState
```

---

## Adding a Dashboard Block

Plugins can register a native dashboard block. The framework provides all chrome —
the frame, section header, drag-to-move, resize handle, and footer gutter. Your
plugin only fills the content area.

**Consistency is structurally guaranteed.** A plugin cannot alter the chrome because
it is owned entirely by `BlockWidget`. There is no override path. The dashboard
will always look consistent regardless of who wrote the plugin.

### Step 1 — Write a BlockWidget subclass

```python
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    pass

from gui.block_base import BlockWidget


class MyBlock(BlockWidget):
    BLOCK_TITLE = "My Plugin"       # section header text

    def build(self, parent: Gtk.Box) -> None:
        """Populate the content area. Called once at startup."""
        body = self._build_section(parent)  # sets up header, returns inner box

        self._value_lbl = self.make_label("—", css_class="data-value")
        body.append(self.make_row("Kills today"))
        body.append(self._value_lbl)

    def refresh(self) -> None:
        """Called every tick and on plugin_refresh queue messages."""
        count = getattr(self.core.state, "my_kill_count", 0)
        self._value_lbl.set_label(str(count))
```

### Step 2 — Register it on your plugin

```python
class MyPlugin(BasePlugin):
    PLUGIN_NAME        = "myplugin"
    PLUGIN_DISPLAY     = "My Plugin"
    PLUGIN_VERSION     = "1.0.0"
    SUBSCRIBED_EVENTS  = ["Bounty"]
    BLOCK_WIDGET_CLASS = MyBlock            # ← this is all that's needed

    def on_load(self, core) -> None:
        self.core = core

    def on_event(self, event, state) -> None:
        if event.get("event") == "Bounty":
            # Signal the GUI to refresh our block immediately
            self.core.gui_queue.put(("plugin_refresh", self.PLUGIN_NAME))
```

The GUI will automatically place your block on the canvas, add it to the
View → Blocks show/hide list, and call `refresh()` on every tick.

### Triggering an immediate block refresh

Put `("plugin_refresh", PLUGIN_NAME)` on `core.gui_queue` from your `on_event`
handler. The GUI calls `refresh()` on your block widget within 100ms.

### Default block position

If the user has no saved layout entry for your block it will appear at
`col=0, row=0` with a default size of 8 columns × 8 rows. Users can drag and
resize it like any built-in block. Their layout is saved automatically.

---

## CoreAPI Reference

Your plugin receives a `CoreAPI` instance via `on_load`. Available attributes:

| Attribute / Method | Description |
|--------------------|-------------|
| `core.state` | Live `MonitorState` |
| `core.active_session` | `SessionData` for the current session |
| `core.cfg` | `ConfigManager` — use `.pcfg(key)` for profile-aware lookup |
| `core.journal_dir` | `Path` to the active journal directory |
| `core.emit(msg_term, msg_discord, ...)` | Post to terminal, GUI log, and Discord |
| `core.gui_queue` | Thread-safe queue for GUI update messages |
| `core.plugin_call(name, method, *args)` | Call a method on another loaded plugin |
| `core.fmt_credits(n)` | Format a credit value — e.g. `1.50M` |
| `core.fmt_duration(s)` | Format seconds — e.g. `1h 30m` |

---

## GUI Queue Message Types

| Message type | Payload | Effect |
|---|---|---|
| `plugin_refresh` | plugin name `str` | Calls `refresh()` on that plugin's block |
| `all_update` | `None` | Refreshes all blocks |
| `cmdr_update` | `None` | Refreshes Commander block |
| `stats_update` | `None` | Refreshes Session Stats block |
| `mission_update` | `None` | Refreshes Mission Stack block |
| `crew_update` / `slf_update` | `None` | Refreshes Crew / SLF block |
| `alerts_update` | `None` | Refreshes Alerts block |
| `update_notice` | version string | Shows update banner in title bar |

---

## BlockWidget API Quick Reference

Methods available inside your `BlockWidget` subclass:

| Method | Returns | Description |
|--------|---------|-------------|
| `self._build_section(parent, title)` | `Gtk.Box` | Sets up section frame and header; returns inner content box |
| `self.make_label(text, css_class, xalign)` | `Gtk.Label` | Create a styled label |
| `self.make_row(key_text, value_text)` | `Gtk.Box` | Create a key / value row |
| `self.footer()` | `Gtk.Box` | Footer gutter — prepend status items here |
| `self.fmt_credits(n)` | `str` | Format credits |
| `self.fmt_duration(s)` | `str` | Format duration |
| `self.state` | `MonitorState` | Live game state |
| `self.session` | `SessionData` | Current session data |
| `self.core` | `CoreAPI` | Full core API |
