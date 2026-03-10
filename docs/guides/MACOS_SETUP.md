# EDMD on macOS

> **Developer notice:** EDMD is developed and tested exclusively on Linux.
> The developer does not own or use macOS hardware and cannot provide direct
> troubleshooting support for macOS-specific installation issues. This guide
> represents a best-effort attempt at community documentation. If you run into
> problems that this guide does not cover, the following external resources are
> your best avenue:
>
> - [PyGObject documentation](https://pygobject.gnome.org)
> - [Homebrew discussion forums](https://github.com/Homebrew/homebrew-core/discussions)
> - [GTK4 macOS notes (gtk.org)](https://gtk.org/docs/installations/macos/)
> - The EDMD GitHub issue tracker (for code bugs, not installation help)

---

## Before you begin — an important note about Elite Dangerous

**Elite Dangerous does not run natively on macOS.** Frontier Developments dropped
macOS support in 2019. This means your game journal files do not exist on your Mac
unless you are doing one of the following:

- **Running ED on a Windows machine** and sharing or syncing the journal folder to
  your Mac (e.g. via Syncthing, a network share, or SSHFS). EDMD can monitor a
  remote journal folder over any of these methods — see
  [REMOTE_ACCESS.md](REMOTE_ACCESS.md) for setup details.
- **Running ED under CrossOver or a similar Wine layer** on macOS. In this case your
  journal files will be inside your Wine prefix, typically at a path like:
  `~/Library/Application Support/CrossOver/Bottles/<bottle-name>/drive_c/users/<user>/Saved Games/Frontier Developments/Elite Dangerous/`

In both cases, set `JournalFolder` in your EDMD config to wherever the `.log` files
actually are.

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS 13 Ventura or newer | Older versions may work but are untested |
| [Homebrew](https://brew.sh) | Required to install GTK4 and PyGObject |
| Python 3.11+ | Can be installed via Homebrew or python.org |
| ~500 MB disk space | For GTK4 and its dependencies |

---

## Installation

### 1. Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the on-screen instructions. After installation, ensure `brew` is on your PATH
(the installer prints the exact commands needed — usually adding a line to
`~/.zprofile`).

---

### 2. Install GTK4 and PyGObject

```bash
brew install gtk4 pygobject3
```

This installs GTK4 and the Python GObject introspection bindings. Homebrew handles
all transitive dependencies (GLib, Cairo, Pango, etc.). This may take several
minutes on the first run.

---

### 3. Install pip dependencies

```bash
pip3 install discord-webhook cryptography psutil
```

If pip3 is not found, use `python3 -m pip install ...`. If you get an
`externally managed environment` error, try:

```bash
pip3 install discord-webhook cryptography psutil --break-system-packages
```

---

### 4. Run the EDMD macOS installer

From the EDMD directory:

```bash
bash install_macos.sh
```

This verifies your Python version, checks that PyGObject is importable, creates your
config directory, and copies `example.config.toml` as a starting point.

---

### 5. Configure EDMD

Open your config file:

```bash
open -a TextEdit "~/Library/Application Support/EDMD/config.toml"
```

At minimum, set `JournalFolder` to wherever your journal files are:

```toml
[Settings]
JournalFolder = "/path/to/your/Saved Games/Frontier Developments/Elite Dangerous"
```

---

### 6. Run EDMD

**Terminal mode** (always works, no GUI dependencies):

```bash
python3 edmd.py
```

**GTK4 GUI mode**:

```bash
python3 edmd.py --gui
```

If the GUI fails to launch, EDMD will fall back to terminal mode automatically and
print the error. Terminal mode is fully functional — all monitoring, alerts, and
Discord notifications work without the GUI.

---

## Known macOS quirks

**GTK rendering differences:** GTK4 on macOS uses the Quartz backend, which renders
slightly differently from the Linux (Wayland/X11) backends. Fonts may look different
and some spacing may be slightly off. This is cosmetic.

**Window controls:** macOS GTK apps draw their own window controls (close/minimise/
maximise) rather than using the native macOS traffic light buttons. EDMD supplies its
own header bar buttons — they will look like the EDMD buttons on Linux, not standard
macOS buttons. This is intentional.

**`gtk-theme-name` warning:** You may see a GTK warning about the theme name
`Default` not being found. This is harmless — EDMD handles it gracefully and loads
its own CSS regardless.

**App menu / dock icon:** GTK4 apps on macOS appear in the dock but may not have a
standard macOS-style application menu. This is a GTK/macOS integration limitation
unrelated to EDMD.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'gi'`**
PyGObject is not installed or not on the Python path that `python3` resolves to.
Run `brew info pygobject3` and check the caveats section — Homebrew often prints
the exact command needed to make the bindings importable.

**`gi.require_version("Gtk", "4.0")` fails**
GTK4 introspection data is not installed. Try:
```bash
brew reinstall gtk4 pygobject3
```

**Display not found / `Gdk-WARNING: cannot open display`**
GTK4 needs a running display server. If you are SSHing into your Mac without
forwarding a display, GUI mode will not work. Run EDMD directly on the Mac desktop,
or use terminal mode over SSH.

**Slow startup**
GTK4's first launch on macOS can be slow while it initialises the Quartz backend and
font cache. Subsequent launches are faster.

**`brew` not found after installation**
Follow the PATH instructions printed at the end of the Homebrew install script. For
Apple Silicon Macs, Homebrew installs to `/opt/homebrew/bin/`, which may need to be
added to your `~/.zprofile` explicitly.
