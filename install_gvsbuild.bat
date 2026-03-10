@echo off
setlocal enabledelayedexpansion
title EDMD — gvsbuild Installer

:: =============================================================================
:: EDMD — install_gvsbuild.bat
:: Windows GUI installer for ED Monitor Daemon — gvsbuild path
:: https://github.com/drworman/EDMD
::
:: Prerequisite: GTK4 must already be built via gvsbuild and C:\gtk\bin
:: must be on your PATH before running this script.
::
:: For full instructions see: docs/guides/WINDOWS_GUI.md
::
:: Developer notice: EDMD is developed on Linux. Windows GUI support is
:: best-effort community documentation. The developer cannot provide
:: direct troubleshooting for Windows-specific issues.
:: =============================================================================

echo.
echo   ███████╗██████╗ ███╗   ███╗ ██████╗ ███╗   ██╗██████╗
echo   ██╔════╝██╔══██╗████╗ ████║██╔═══██╗████╗  ██║██╔══██╗
echo   █████╗  ██║  ██║██╔████╔██║██║   ██║██╔██╗ ██║██║  ██║
echo   ██╔══╝  ██║  ██║██║╚██╔╝██║██║   ██║██║╚██╗██║██║  ██║
echo   ███████╗██████╔╝██║ ╚═╝ ██║╚██████╔╝██║ ╚████║██████╔╝
echo   ╚══════╝╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═════╝
echo.
echo   ED Monitor Daemon -- Windows Installer (gvsbuild path)
echo   https://github.com/drworman/EDMD
echo.
echo   Developer notice: EDMD is developed on Linux. Windows GUI support is
echo   best-effort. See docs/guides/WINDOWS_GUI.md for full instructions.
echo.

:: ── Python check ──────────────────────────────────────────────────────────────
echo [EDMD] Checking Python...

set PYTHON_CMD=
for %%P in (python python3 py) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
            set PYVER=%%V
        )
        set PYTHON_CMD=%%P
        goto :found_python
    )
)

echo [ FAIL ] Python not found.
echo.
echo   Install Python 3.11 or newer from https://python.org
echo   Check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
echo [  OK  ] Found Python %PYVER% at %PYTHON_CMD%

for /f "tokens=1,2 delims=." %%A in ("%PYVER%") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)
if %PY_MAJOR% LSS 3 goto :python_too_old
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 11 goto :python_too_old
goto :python_ok

:python_too_old
echo [ FAIL ] Python %PYVER% is too old. EDMD requires Python 3.11+.
pause
exit /b 1

:python_ok

:: ── Check GTK4 is on PATH ─────────────────────────────────────────────────────
echo.
echo [EDMD] Checking GTK4 (gvsbuild)...

where gtk4-demo >nul 2>&1
if errorlevel 1 (
    echo [ WARN ] gtk4-demo not found on PATH.
    echo [ WARN ] Either gvsbuild has not been run yet, or C:\gtk\bin is not on your PATH.
    echo.
    echo   If you have not yet built GTK4 via gvsbuild, see:
    echo   docs/guides/WINDOWS_GUI.md -- Option B for full instructions.
    echo.
    echo   If you have already built GTK4, add C:\gtk\bin to your PATH:
    echo     System Properties -^> Advanced -^> Environment Variables -^> Path -^> New
    echo     Add: C:\gtk\bin
    echo   Then open a new CMD window and re-run this installer.
    echo.
    goto :skip_gtk_ok
)
echo [  OK  ] GTK4 found on PATH

:skip_gtk_ok

:: ── Check PyGObject is importable ─────────────────────────────────────────────
echo.
echo [EDMD] Checking PyGObject...

%PYTHON_CMD% -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" >nul 2>&1
if errorlevel 1 (
    echo [ WARN ] PyGObject is not importable by %PYTHON_CMD%.
    echo [ INFO ] Attempting pip install...
    %PYTHON_CMD% -m pip install PyGObject --quiet
    if errorlevel 1 (
        echo [ WARN ] pip install PyGObject failed.
        echo [ WARN ] Ensure C:\gtk\bin is on your PATH before pip can find the GTK DLLs.
        echo [ WARN ] GUI mode will not work until PyGObject is importable.
        echo [ INFO ] Terminal mode will still work fine.
        set GUI_AVAILABLE=false
        goto :after_pygobject
    )
    %PYTHON_CMD% -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" >nul 2>&1
    if errorlevel 1 (
        echo [ WARN ] PyGObject installed but still not importable.
        echo [ WARN ] Verify C:\gtk\bin is on PATH and restart your terminal.
        set GUI_AVAILABLE=false
        goto :after_pygobject
    )
)
echo [  OK  ] PyGObject (GTK4) is importable
set GUI_AVAILABLE=true

:after_pygobject

:: ── Install pip packages ───────────────────────────────────────────────────────
echo.
echo -- Installing pip packages --

echo [EDMD] Installing psutil...
%PYTHON_CMD% -m pip install "psutil>=5.9.0" --quiet
if errorlevel 1 (
    echo [ WARN ] psutil install failed. Run manually: pip install psutil
) else (
    echo [  OK  ] psutil installed
)

echo [EDMD] Installing discord-webhook...
%PYTHON_CMD% -m pip install "discord-webhook>=1.3.0" --quiet
if errorlevel 1 (
    echo [ WARN ] discord-webhook install failed. Run manually: pip install discord-webhook
) else (
    echo [  OK  ] discord-webhook installed
)

echo [EDMD] Installing cryptography...
%PYTHON_CMD% -m pip install "cryptography>=41.0.0" --quiet
if errorlevel 1 (
    echo [ WARN ] cryptography install failed. Run manually: pip install cryptography
) else (
    echo [  OK  ] cryptography installed
)

:: ── Config setup ──────────────────────────────────────────────────────────────
echo.
echo -- Configuration --

set EDMD_DATA=%APPDATA%\EDMD
if not exist "%EDMD_DATA%" mkdir "%EDMD_DATA%"

if exist "%EDMD_DATA%\config.toml" (
    echo [  OK  ] config.toml already exists at %EDMD_DATA%\config.toml -- leaving untouched
) else (
    if exist "%~dp0example.config.toml" (
        copy "%~dp0example.config.toml" "%EDMD_DATA%\config.toml" >nul
        echo [  OK  ] Created config.toml at %EDMD_DATA%\config.toml
    ) else (
        echo [ WARN ] example.config.toml not found -- config.toml was not created.
        echo [ WARN ] Copy example.config.toml to %EDMD_DATA%\config.toml manually.
    )
)

:: ── Summary ───────────────────────────────────────────────────────────────────
echo.
echo -- Installation complete --
echo.
echo   EDMD is ready to run.
echo.
echo   Terminal mode (always works):
echo     %PYTHON_CMD% edmd.py
echo.

if "%GUI_AVAILABLE%"=="true" (
    echo   GUI mode:
    echo     %PYTHON_CMD% edmd.py --gui
    echo.
) else (
    echo   GUI mode requires PyGObject -- see warnings above.
    echo   Terminal mode is fully functional without the GUI.
    echo.
)

echo   With a config profile:
echo     %PYTHON_CMD% edmd.py -p YourProfileName
echo.
echo   Edit %EDMD_DATA%\config.toml to set JournalFolder before running.
echo   See docs\guides\WINDOWS_GUI.md for full Windows documentation.
echo.
pause
