#!/usr/bin/env python3
"""
edmd.py — Elite Dangerous Monitor Daemon — entry point

All business logic lives in the packages below:
  core/     — state, config, emit, journal loop, plugin loader, shared API
  builtins/ — five built-in data plugins (commander, missions, stats, crew/SLF, alerts)
  plugins/  — user plugin directory
  gui/      — GTK4 interface (helpers, block widgets, EdmdApp)
"""

import argparse
import json
import os
import platform as _pl
import subprocess as _sp
import sys
import threading
import time
import queue
from pathlib import Path
from urllib.request import urlopen

# ── Ensure repo root is on sys.path ───────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.state  import PROGRAM, VERSION, AUTHOR, GITHUB_REPO, DEBUG_MODE
from core.emit   import Terminal
from core.config import resolve_config_path, load_config_file, ConfigManager


# ── Argument parsing ──────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    prog=PROGRAM,
    description="Continuous monitoring of Elite Dangerous AFK sessions.",
)
parser.add_argument("-p", "--config_profile",
                    help="Load a specific config profile")
parser.add_argument("-t", "--test", action="store_true", default=None,
                    help="Re-route Discord output to terminal instead of webhook")
parser.add_argument("-d", "--trace", action="store_true", default=None,
                    help="Print verbose debug/trace output")
parser.add_argument("-g", "--gui", action="store_true", default=None,
                    help="Launch GTK4 GUI (Linux only; requires PyGObject)")
parser.add_argument("--upgrade", action="store_true", default=False,
                    help="Pull latest version from GitHub and restart")

args = parser.parse_args()

if args.upgrade and any(f for f in [args.config_profile, args.test, args.trace, args.gui] if f):
    parser.error("--upgrade cannot be combined with other flags")


# ── In-place upgrade (self-contained — runs before full package import) ────────

def _do_upgrade() -> None:
    repo_dir = _HERE
    print(f"{Terminal.CYAN}{'=' * 52}\n  EDMD In-Place Upgrade\n{'=' * 52}{Terminal.END}\n")

    import shutil
    if not shutil.which("git"):
        print(f"{Terminal.WARN}ERROR:{Terminal.END} git not found on PATH.")
        sys.exit(1)

    r = _sp.run(["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True)
    if r.returncode != 0:
        print(f"{Terminal.WARN}ERROR:{Terminal.END} {repo_dir} is not a git repository.")
        sys.exit(1)

    dirty = _sp.run(["git", "-C", str(repo_dir), "status", "--porcelain"],
                    capture_output=True, text=True)
    modified = [l for l in dirty.stdout.splitlines() if not l.strip().endswith("config.toml")]
    if modified:
        print(f"{Terminal.YELL}Warning:{Terminal.END} Uncommitted local changes:")
        for l in modified[:5]: print(f"  {l}")
        if len(modified) > 5: print(f"  ... and {len(modified) - 5} more")
        print()
        try:
            ans = input("Continue? Local changes may be overwritten. [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans != "y":
            print("Upgrade cancelled."); sys.exit(0)
        print()

    print(f"  Current version : {VERSION}\n  Pulling from    : origin/main")
    pull = _sp.run(["git", "-C", str(repo_dir), "pull", "--ff-only"],
                   capture_output=True, text=True)
    if pull.returncode != 0:
        print(f"\n{Terminal.WARN}ERROR:{Terminal.END} git pull failed:")
        print(pull.stderr.strip() or pull.stdout.strip()); sys.exit(1)
    if "Already up to date" in pull.stdout:
        print(f"\n  Already up to date (v{VERSION}). Nothing to do.\n"); sys.exit(0)
    print(pull.stdout.strip()); print()

    install_sh = repo_dir / "install.sh"
    if install_sh.exists() and _pl.system() != "Windows":
        print("  Running install.sh...\n")
        inst = _sp.run(["bash", str(install_sh)], cwd=str(repo_dir))
        if inst.returncode != 0:
            print(f"\n{Terminal.WARN}Warning:{Terminal.END} install.sh exited with errors.")
    elif _pl.system() == "Windows":
        install_bat = repo_dir / "install.bat"
        if install_bat.exists():
            print("  Running install.bat...\n")
            _sp.run([str(install_bat)], cwd=str(repo_dir), shell=True)

    new_argv = [a for a in sys.argv if a != "--upgrade"]
    print(f"\n{Terminal.GOOD}  Upgrade complete. Relaunching EDMD...{Terminal.END}\n")
    os.execv(sys.executable, [sys.executable] + new_argv)


if args.upgrade:
    _do_upgrade()
    sys.exit(0)  # unreachable — execv replaces process


# ── Header ────────────────────────────────────────────────────────────────────

title = f"{PROGRAM} v{VERSION} by {AUTHOR}"
print(f"{Terminal.CYAN}{'=' * len(title)}\n{title}\n{'=' * len(title)}{Terminal.END}\n")


# ── Background update check ───────────────────────────────────────────────────

_update_notice: str | None = None

def _check_for_update() -> None:
    global _update_notice
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urlopen(url, timeout=4) as resp:
            if resp.status == 200:
                import re as _re
                tag = json.loads(resp.read()).get("tag_name", "").lstrip("v").strip()
                if tag and tag != VERSION:
                    def _vkey(v):
                        m = _re.match(r"^(\d+)([a-z]*)$", v)
                        return (int(m.group(1)), m.group(2)) if m else (0, "")
                    if _vkey(tag) > _vkey(VERSION):
                        _update_notice = tag
    except Exception:
        pass

_update_thread = threading.Thread(target=_check_for_update, daemon=True)
_update_thread.start()


# ── Config ────────────────────────────────────────────────────────────────────

config_path = resolve_config_path(Path(__file__))
if config_path is None:
    _data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "EDMD" / "config.toml"
    _repo = _HERE / "config.toml"
    print(
        f"{Terminal.WARN}ERROR:{Terminal.END} Config file not found.\n"
        f"  Expected: {_data}\n"
        f"  Or:       {_repo}\n"
        f"  Copy example.config.toml to either location to get started."
    )
    sys.exit(1)

config_dict = load_config_file(config_path)
notify_test = bool(args.test)  if args.test  is not None else False
trace_mode  = bool(args.trace) if args.trace is not None else DEBUG_MODE

# Preliminary manager — profile may be updated after commander name is known
mgr = ConfigManager(config_dict, config_path, config_profile=args.config_profile)


# ── State and session objects ─────────────────────────────────────────────────

from core.state import MonitorState, SessionData, load_session_state

state          = MonitorState()
active_session = SessionData()
lifetime       = SessionData()
gui_queue: queue.Queue = queue.Queue()


# ── Find journal ──────────────────────────────────────────────────────────────

from core.journal import find_latest_journal

journal_dir_str = mgr.app_settings.get("JournalFolder", "")
journal_dir     = Path(journal_dir_str).expanduser() if journal_dir_str else None

if not journal_dir or not journal_dir.is_dir():
    print(
        f"{Terminal.WARN}ERROR:{Terminal.END} JournalFolder not set or not found: {journal_dir_str!r}\n"
        f"Set JournalFolder in config.toml to your Elite Dangerous journal directory."
    )
    sys.exit(1)

journal_file = find_latest_journal(journal_dir)
if not journal_file:
    print(f"{Terminal.WARN}ERROR:{Terminal.END} No journal files found in {journal_dir}")
    sys.exit(1)


# ── Commander name — for profile auto-detection ───────────────────────────────

try:
    for _raw in journal_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            _j = json.loads(_raw.strip())
            if _j.get("event") in ("Commander", "LoadGame") and _j.get("Name"):
                state.pilot_name = _j["Name"]
                break
        except ValueError:
            pass
except OSError:
    pass

print(f"{Terminal.YELL}Commander name:{Terminal.END} {state.pilot_name or '(unknown)'}")

_config_profile = args.config_profile
_config_info    = ""
if not _config_profile and state.pilot_name and state.pilot_name in config_dict:
    _config_profile = state.pilot_name
    _config_info    = " (auto)"
    mgr = ConfigManager(config_dict, config_path, config_profile=_config_profile)

print(
    f"{Terminal.YELL}Config profile:{Terminal.END} "
    f"{_config_profile or 'Default'}{_config_info}"
)


# ── GUI mode ──────────────────────────────────────────────────────────────────

gui_mode = bool(args.gui) or bool(mgr.gui_cfg.get("Enabled", False))


# ── Emitter ───────────────────────────────────────────────────────────────────

from core.emit import Emitter, emit_summary

emitter = Emitter(
    mgr, state,
    gui_queue=gui_queue,
    notify_test=notify_test,
    gui_mode=gui_mode,
)


# ── CoreAPI + plugins ─────────────────────────────────────────────────────────

from core.core_api      import CoreAPI
from core.plugin_loader import PluginLoader
from core.journal       import build_dispatch_map

core = CoreAPI(
    state=state,
    active_session=active_session,
    lifetime=lifetime,
    cfg_mgr=mgr,
    emitter=emitter,
    gui_queue=gui_queue,
    journal_dir=journal_dir,
    launch_argv=sys.argv,
)

loader = PluginLoader(_HERE)
loader.load_all(core)
plugin_dispatch = build_dispatch_map(list(core._plugins.values()))


# ── Bootstrap from journal history ────────────────────────────────────────────

print("\nStarting... (Press Ctrl+C to stop)\n")

from core.journal import bootstrap_slf, bootstrap_crew, bootstrap_missions

bootstrap_slf(state, journal_dir, trace_mode=trace_mode)
bootstrap_crew(state, journal_dir, trace_mode=trace_mode)
bootstrap_missions(state, journal_dir, mgr, trace_mode=trace_mode)


# ── Update notice ─────────────────────────────────────────────────────────────

_update_thread.join(timeout=2)
if _update_notice:
    _releases_url = f"https://github.com/{GITHUB_REPO}/releases"
    if not gui_mode:
        print(
            f"{Terminal.YELL}\u26a0 Update available: v{_update_notice}{Terminal.END}"
            f"  {Terminal.WHITE}{_releases_url}{Terminal.END}\n"
            f"  Run {Terminal.CYAN}edmd.py --upgrade{Terminal.END} to update and restart automatically.\n"
        )
    if gui_mode:
        gui_queue.put(("update_notice", _update_notice))
    emitter.set_update_notice(_update_notice)


# ── Session restore + startup banner ─────────────────────────────────────────

load_session_state(journal_file, active_session)
state.sessionstart(active_session)
emit_summary(emitter, state, active_session)


# ── Monitor + launch ──────────────────────────────────────────────────────────

from core.journal      import run_monitor as _run_monitor, _poll_status_json
from core.state        import save_session_state

_edmd_start_mono = time.monotonic()

def run_monitor() -> None:
    _run_monitor(
        journal_file,
        state, active_session, lifetime,
        emitter, mgr, gui_queue, journal_dir,
        _edmd_start_mono,
        trace_mode=trace_mode,
        plugin_dispatch=plugin_dispatch,
    )


if __name__ == "__main__":
    if gui_mode:
        try:
            from gui.app import EdmdApp
        except ImportError as e:
            print(
                f"{Terminal.WARN}ERROR:{Terminal.END} GUI mode requested but gui/ could not be loaded: {e}\n"
                f"Ensure PyGObject (GTK4) is installed: pacman -S python-gobject gtk4"
            )
            sys.exit(1)

        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()

        status_thread = threading.Thread(
            target=_poll_status_json,
            args=(journal_dir, state, gui_queue),
            daemon=True,
        )
        status_thread.start()

        app = EdmdApp(core, PROGRAM, VERSION)
        app.run(None)

    else:
        run_monitor()
