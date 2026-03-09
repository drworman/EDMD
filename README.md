<div align="center">

<img src="images/edmd_avatar_512.png" width="140" alt="EDMD"/>

# Elite Dangerous Monitor Daemon
### EDMD

**Real-time AFK session monitoring for Elite Dangerous**

*Kill tracking · Discord alerts · Session awareness · Mission stack tracking · Reports · GTK4 GUI*

---

by **CMDR CALURSUS**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-informational?style=flat-square)]()
[![GTK4](https://img.shields.io/badge/GUI-GTK4-4A86CF?style=flat-square&logo=gnome&logoColor=white)]()
[![Discord](https://img.shields.io/badge/Discord-Webhook%20Support-5865F2?style=flat-square&logo=discord&logoColor=white)]()
[![License](https://img.shields.io/badge/License-MIT-brightgreen?style=flat-square)]()

</div>

---

## Overview

EDMD is a Python daemon that tails your Elite Dangerous journal in real time, watching over your AFK combat sessions so you don't have to. It tracks every kill, bounty, merit, and massacre mission — streaming events to your terminal, a GTK4 GUI window, and optionally to a Discord channel via webhook.

When things go wrong — your fighter blown up, hull taking critical damage, fuel running dry — EDMD will alert you so you can intervene before coming back to a rebuy screen.

---

## Features

| | |
|--|--|
| 💥 **Kill & Reward Tracking** | Logs every bounty and combat bond with ship type, timing, and credit value |
| 🎯 **Massacre Mission Stack** | Tracks active missions, stack value, and completion status with full bootstrap on start |
| 📊 **Periodic Summaries** | Session stats every 15 minutes — to terminal, GUI, and Discord |
| 🖥️ **GTK4 GUI** | Live graphical interface with commander, crew, SLF, mission, and session panels |
| 🛡️ **Combat Alerts** | Shield drops, hull damage, fighter loss, ship destruction |
| ⛽ **Fuel Monitoring** | Warn and critical thresholds for fuel percentage and estimated time remaining |
| 🚨 **Security & Cargo Events** | Cargo scans, police scans, security attacks, low-value cargo notices |
| ⚠️ **Inactivity Warnings** | Alerts on kill rate drop or extended period without kills |
| 🔄 **Hot-Reload Config** | Most settings take effect within ~1 second of saving — no restart needed |
| 📰 **Automatic Journal Switching** | Seamlessly follows new journal files between game sessions |
| 📈 **Statistical Reports** | Five journal-wide reports: career overview, bounty breakdown, session history, hunting grounds, and NPC rogues' gallery |
| 📚 **Native Docs Viewer** | Full documentation browser built into the GUI — no browser needed |
| 🔌 **Plugin System** | Drop a Python plugin into `plugins/` and it loads automatically with optional dashboard block |

<div align="center">
<img src="images/gui-screenshot.png" alt="EDMD GTK4 GUI" width="900"/>
<br><em>GTK4 GUI — default-green theme, live session in progress</em>
</div>

---

## Installation

**→ Full instructions: [INSTALL.md](INSTALL.md)**

### Linux (Arch)
```bash
sudo pacman -S python-psutil python-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
./install.sh
```

### Linux (Debian / Ubuntu)
```bash
sudo apt install python3-psutil python3-gi gir1.2-gtk-4.0
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

### Linux (Fedora)
```bash
sudo dnf install python3-psutil python3-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

### Windows
```bat
install.bat
```

> `psutil` and `PyGObject` have C extensions that require system libraries — install them via your distro's package manager, not pip. See [INSTALL.md](INSTALL.md) for details.

---

## Quick Start

```bash
git clone https://github.com/drworman/EDMD.git
cd EDMD
bash install.sh          # Linux  |  install.bat on Windows

# Set JournalFolder at minimum — config created by the installer
# Linux:   ~/.local/share/EDMD/config.toml
# Windows: %APPDATA%\EDMD\config.toml
nano ~/.local/share/EDMD/config.toml

./edmd.py              # terminal mode
./edmd.py --gui        # GTK4 GUI (Linux)
./edmd.py -p MyProfile # named config profile
```

---

## Discord Integration

1. In Discord: **Edit Channel → Integrations → Webhooks → New Webhook**
2. Copy the webhook URL into `config.toml`:

```toml
[Discord]
WebhookURL = 'https://discord.com/api/webhooks/...'
UserID = 123456789012345678
```

`UserID` enables `@mention` pings on level-3 alerts. Find yours via Discord's Developer Mode (right-click your username).

<div align="center">
<img src="images/discord_launch_notice.png" alt="Discord launch notice embed" width="420"/>
<br><em>Startup embed posted to Discord when monitoring begins</em>
</div>

---

## Documentation

| Document | Contents |
|----------|----------|
| [INSTALL.md](INSTALL.md) | Full installation instructions |
| [Configuration](docs/CONFIGURATION.md) | All config keys, notification levels, CLI flags, profiles |
| [Terminal Output](docs/TERMINAL_OUTPUT.md) | Startup banner, event line format, sigil/tag reference, periodic summary |
| [GUI Theming](docs/THEMING.md) | Built-in themes, custom theme creation |
| [Mission Bootstrap](docs/MISSION_BOOTSTRAP.md) | How EDMD reconstructs mission state on startup |
| [Plugin Development](docs/PLUGIN_DEVELOPMENT.md) | Plugin interface and CoreAPI reference |
| [Reports](docs/REPORTS.md) | Statistical reports — what each report covers and how data is sourced |

### Guides

| Guide | Description |
|-------|-------------|
| [Linux Setup](docs/guides/LINUX_SETUP.md) | Elite Dangerous on Linux with Steam, Proton, Minimal ED Launcher, EDMC, and EDMD |
| [Dual Pilot](docs/guides/DUAL_PILOT.md) | Two accounts simultaneously with independent journals and tool instances |
| [Remote Access](docs/guides/REMOTE_ACCESS.md) | EDMD GUI on a second machine as a thin client |

---

<div align="center">

*Fly safe out there, CMDR.*

<img src="images/edmd_avatar_512.png" width="56" alt="EDMD"/>

**Elite Dangerous Monitor Daemon** · by CMDR CALURSUS

</div>
