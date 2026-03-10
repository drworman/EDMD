# EDMD GUI on Windows

> **Developer notice:** EDMD is developed and tested exclusively on Linux.
> The developer does not use Windows as a primary platform and cannot provide
> direct troubleshooting support for Windows-specific installation issues. This
> guide represents a best-effort attempt at community documentation based on
> known-working approaches from the GTK4/PyGObject Windows ecosystem.
>
> If you run into problems this guide does not cover, the following external
> resources are your best avenue:
>
> - [PyGObject on Windows (gnome.org)](https://pygobject.gnome.org/getting_started.html#windows-getting-started)
> - [MSYS2 documentation](https://www.msys2.org/docs/)
> - [gvsbuild documentation](https://github.com/wingtk/gvsbuild)
> - [GTK4 Windows notes (gtk.org)](https://gtk.org/docs/installations/windows/)
> - The EDMD GitHub issue tracker (for code bugs, not installation help)
>
> **EDMD terminal mode works on Windows with no special setup.** The GUI is an
> optional enhancement. If the GTK4 installation proves too complex for your
> situation, terminal mode with Discord notifications is a complete monitoring
> experience. See the standard [install.bat](../../install.bat) for that path.

---

## Overview

GTK4 does not ship as a standard Windows package in the way it does on Linux. Getting
it onto Windows requires one of two approaches:

| Approach | Difficulty | User experience | Best for |
|---|---|---|---|
| **MSYS2** | Moderate | Runs inside MSYS2 shell | Most users — recommended starting point |
| **gvsbuild** | Advanced | Runs in standard CMD/PowerShell | Users who want a native Windows Python experience |

Both approaches produce a fully working EDMD GUI. The difference is how you launch it
and how GTK4 is managed on your system.

---

## Option A — MSYS2 (Recommended)

MSYS2 is a Linux-like development environment for Windows that ships its own package
manager (`pacman`) and a maintained GTK4 build. It is the officially recommended path
for PyGObject on Windows.

### What you will get

- GTK4 and PyGObject managed by MSYS2's `pacman`
- EDMD runs inside the MSYS2 UCRT64 terminal
- Clean, reproducible installation
- Easy updates via `pacman -Syu`

### What this means in practice

You launch EDMD from the **MSYS2 UCRT64** shortcut, not from a standard Windows
Command Prompt or PowerShell window. The MSYS2 Python interpreter is used, not your
standard Windows Python install. This is a different terminal experience from what
most Windows users are used to, but it is stable and well-maintained.

---

### A1. Install MSYS2

Download and run the MSYS2 installer from **[msys2.org](https://www.msys2.org)**.

Accept all defaults. After installation, MSYS2 opens automatically — let it run the
initial update if prompted:

```
pacman -Syu
```

Close and reopen the MSYS2 UCRT64 terminal (use the **MSYS2 UCRT64** shortcut, not
MSYS2 MSYS or MSYS2 MinGW).

---

### A2. Run the MSYS2 EDMD installer

From the MSYS2 UCRT64 terminal, navigate to the EDMD directory. If EDMD is at
`C:\Users\YourName\EDMD`, the path in MSYS2 is `/c/Users/YourName/EDMD`:

```bash
cd /c/Users/YourName/EDMD
bash install_msys2.sh
```

The installer installs GTK4, PyGObject, and all other EDMD dependencies via pacman
and pip, then creates your config file.

---

### A3. Configure EDMD

Edit the config file created by the installer. In MSYS2:

```bash
nano ~/AppData/Roaming/EDMD/config.toml
```

Or open it in any Windows text editor — the path in Windows Explorer is:
`%APPDATA%\EDMD\config.toml`

Set `JournalFolder` to your Elite Dangerous journal path, for example:

```toml
[Settings]
JournalFolder = "C:/Users/YourName/Saved Games/Frontier Developments/Elite Dangerous"
```

Note: use forward slashes or double backslashes in the path.

---

### A4. Run EDMD

From the **MSYS2 UCRT64** terminal:

```bash
cd /c/Users/YourName/EDMD

# Terminal mode
python edmd.py

# GUI mode
python edmd.py --gui
```

> **Important:** EDMD must always be launched from the MSYS2 UCRT64 terminal with
> this setup. Double-clicking `edmd.py` from Windows Explorer, or running it from a
> standard CMD/PowerShell window, will not work because the GTK4 libraries are only
> on the MSYS2 PATH.

---

### MSYS2 troubleshooting

**`python: command not found`**
Inside MSYS2 UCRT64, Python may be `python3`. Try `python3 edmd.py`.

**`No module named 'gi'`**
The PyGObject package may not have installed correctly. Run:
```bash
pacman -S mingw-w64-ucrt-x86_64-python-gobject3
```

**Fonts look wrong / missing icons**
Install the MSYS2 Adwaita icon theme:
```bash
pacman -S mingw-w64-ucrt-x86_64-adwaita-icon-theme
```

**`gtk-theme-name Default not found`**
This warning is harmless. EDMD handles it gracefully.

---

## Option B — gvsbuild (Advanced)

gvsbuild builds GTK4 from source using Microsoft's compiler toolchain and installs it
in a way that works with a standard Windows Python interpreter. The result is that
EDMD can be launched from a normal CMD or PowerShell window, but the setup process is
significantly more involved.

**Time required:** 60–90 minutes including the GTK4 build process.

**Disk space required:** ~4 GB (Visual Studio Build Tools + GTK4 build artifacts).

### What you will get

- GTK4 installed at `C:\gtk\` (or similar), usable from any Python on your system
- EDMD runnable from standard CMD, PowerShell, or Windows Terminal
- No dependency on MSYS2

---

### B1. Prerequisites

You need **Visual Studio 2022** (Community edition is free) with the
**"Desktop development with C++"** workload. This provides the MSVC compiler that
gvsbuild requires.

Download from: [visualstudio.microsoft.com](https://visualstudio.microsoft.com/downloads/)

During installation, ensure the following are selected under "Desktop development with C++":
- MSVC v143 build tools
- Windows SDK (latest)
- C++ CMake tools

---

### B2. Install gvsbuild

From a standard Command Prompt or PowerShell (not Visual Studio's developer prompt):

```bat
pip install gvsbuild
```

---

### B3. Build GTK4

Open the **"x64 Native Tools Command Prompt for VS 2022"** — find it in the Start
menu under Visual Studio 2022. This sets the correct compiler environment.

Then run (this will take 30–60 minutes):

```bat
gvsbuild build gtk4 --enable-gi pycairo pygobject
```

gvsbuild downloads sources, builds GTK4 and its dependencies, and installs them to
`C:\gtk\` by default.

---

### B4. Add GTK to your PATH

GTK's DLLs must be on your PATH before Python can load them. Add `C:\gtk\bin`
permanently:

1. Open **System Properties → Advanced → Environment Variables**
2. Under "User variables", select **Path** and click **Edit**
3. Click **New** and add `C:\gtk\bin`
4. Click OK on all dialogs

Open a new CMD or PowerShell window for the PATH change to take effect.

---

### B5. Install PyGObject

```bat
pip install PyGObject
```

---

### B6. Run the gvsbuild EDMD installer

```bat
install_gvsbuild.bat
```

This installs the remaining pip dependencies (`discord-webhook`, `cryptography`,
`psutil`) and creates your config file.

---

### B7. Configure and run EDMD

Edit `%APPDATA%\EDMD\config.toml` and set `JournalFolder`.

```bat
# Terminal mode (standard CMD or PowerShell)
python edmd.py

# GUI mode
python edmd.py --gui
```

---

### gvsbuild troubleshooting

**Build fails with compiler errors**
Ensure you are running from the **"x64 Native Tools Command Prompt for VS 2022"**,
not a regular CMD window. The compiler environment must be set.

**`No module named 'gi'` after successful build**
Verify `C:\gtk\bin` is on your PATH (`echo %PATH%` in CMD). Restart your terminal
after editing environment variables.

**GTK DLL not found at runtime**
Run `python -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk"`.
If this fails with a DLL error, the `C:\gtk\bin` PATH entry is missing or the wrong
Python interpreter is being used.

**Antivirus blocking gvsbuild**
Some antivirus tools flag gvsbuild's compilation and download activity. Add an
exclusion for your gvsbuild working directory if builds are interrupted.

---

## Terminal mode fallback (always works)

If either GUI installation approach proves too difficult or unreliable, EDMD's
terminal mode runs on Windows with nothing beyond a standard Python installation:

```bat
pip install psutil discord-webhook cryptography
python edmd.py
```

All monitoring, alerts, and Discord notifications are fully supported in terminal
mode. The GUI is an enhancement, not a requirement.
