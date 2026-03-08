# EDMD Installation Guide

EDMD is a Python daemon for real-time Elite Dangerous AFK session monitoring.

---

## Dependencies

EDMD has two types of dependencies:

**System packages** (install via your package manager — do NOT use pip for these):
- `python-psutil` — process and system utilities
- `python-gobject` + `gtk4` — GTK4 GUI support (Linux only; optional)

**pip packages:**
- `discord-webhook` — Discord notification support
- `cryptography` — config integrity verification and secure transport features

---

## Linux — Arch

Arch ships current versions of everything EDMD needs.

```bash
sudo pacman -S python-psutil python-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
```

**Running EDMD:**

```bash
git clone https://github.com/drworman/EDMD.git
cd EDMD
bash install.sh         # creates ~/.local/share/EDMD/config.toml from example
nano ~/.local/share/EDMD/config.toml   # set JournalFolder at minimum
./edmd.py
./edmd.py --gui         # GTK4 interface
```

---

## Linux — Debian / Ubuntu

```bash
sudo apt install python3-psutil python3-gi gir1.2-gtk-4.0
pip install discord-webhook cryptography --break-system-packages
```

**Running EDMD:**

```bash
git clone https://github.com/drworman/EDMD.git
cd EDMD
bash install.sh
nano ~/.local/share/EDMD/config.toml
./edmd.py --gui
```

---

## Linux — Fedora

```bash
sudo dnf install python3-psutil python3-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
```

---

## Windows

```bat
pip install psutil discord-webhook cryptography
```

Or run the provided installer:

```bat
install.bat
```

EDMD runs in terminal mode on Windows. GTK4 GUI is Linux-only.

---

## Config file location

`install.sh` creates `config.toml` in the EDMD user data directory automatically.
If you need to locate or create it manually:

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/EDMD/config.toml` |
| Windows | `%APPDATA%\EDMD\config.toml` |
| macOS | `~/Library/Application Support/EDMD/config.toml` |

On Linux, `~/.config/EDMD` is a symlink to `~/.local/share/EDMD/` — you can use
either path. A repo-adjacent `config.toml` is also accepted as a fallback for
development or portable installs.

---

## Verifying your install

```bash
python3 -c "import psutil, discord_webhook, cryptography; print('All dependencies OK')"
```

---

## GTK4 GUI (Linux only)

The GUI requires PyGObject with GTK4 bindings, including Pango (bundled with GTK4 — no separate install needed). If these are not available you can still run EDMD in terminal mode:

```bash
./edmd.py    # terminal mode only
```

GTK4 availability is checked at runtime — if `--gui` is passed but PyGObject cannot be loaded, EDMD will print a clear error and fall back to terminal mode.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'psutil'`**
Install via your package manager, not pip: `sudo pacman -S python-psutil` (Arch) or `sudo apt install python3-psutil` (Debian/Ubuntu).

**`ModuleNotFoundError: No module named 'gi'`**
PyGObject is not installed. Install `python-gobject` (Arch), `python3-gi` (Debian), or `python3-gobject` (Fedora). GTK4 itself must also be installed.

**`ModuleNotFoundError: No module named 'discord_webhook'`**
Run `pip install discord-webhook --break-system-packages`.

**`ModuleNotFoundError: No module named 'cryptography'`**
Run `pip install cryptography --break-system-packages`.

**`sshfs` for remote access**
If you plan to use EDMD's remote GUI mode (secondary machine as thin client), install `sshfs` on the secondary machine:
`sudo pacman -S sshfs` (Arch) · `sudo apt install sshfs` (Debian/Ubuntu) · `sudo dnf install fuse-sshfs` (Fedora).
See [docs/guides/REMOTE_ACCESS.md](docs/guides/REMOTE_ACCESS.md) for full setup.

**`GLib.GError` or blank GUI window**
Your GTK4 theme or icon set may be incomplete. Ensure `adwaita-icon-theme` (or equivalent) is installed for your distro.

**auto-quit doesn't trigger / antivirus warning**
EDMD uses `psutil` to exit `EliteDangerous64.exe` under certain conditions. Some antivirus tools flag process-termination behaviour. If EDMD is blocked, add an exclusion for the EDMD folder in your antivirus settings.
