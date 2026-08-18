@echo off
setlocal EnableDelayedExpansion
title SPWB

REM ---------------------------------------------------------------------
REM  Double-click launcher for the SPWB desktop application (Windows).
REM
REM  It checks everything that can be wrong BEFORE launching, so a problem
REM  shows a readable message instead of a console window that flashes and
REM  disappears. Once the checks pass it starts the app with pythonw, so no
REM  console window is left behind.
REM ---------------------------------------------------------------------

cd /d "%~dp0"

REM --- 1. find an interpreter -------------------------------------------
REM  A virtual environment beside this file wins, so a project-local
REM  install is used even when another Python is first on PATH.
set "PY="
set "PYW="
if exist ".venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
    set "PYW=%~dp0.venv\Scripts\pythonw.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PY=%~dp0venv\Scripts\python.exe"
    set "PYW=%~dp0venv\Scripts\pythonw.exe"
) else (
    REM  "python" before "py": python on PATH is what an activated virtual
    REM  environment provides, and it must win over the py launcher, which
    REM  would silently resolve to the system-wide Python instead.
    where python >nul 2>&1 && set "PY=python" && set "PYW=pythonw"
    if not defined PY (
        where py >nul 2>&1 && set "PY=py" && set "PYW=pyw"
    )
)

if not defined PY (
    echo.
    echo   Python was not found on this computer.
    echo.
    echo   Install Python 3.10 or newer from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during the installation.
    echo.
    pause
    exit /b 1
)

REM --- 2. is SPWB installed, with its GUI? -------------------------------
REM  find_spec LOCATES the modules without executing them. The obvious
REM  check - "import spwb.gui" - runs PySide6, pyqtgraph, numpy and scipy
REM  in full just to learn whether they are importable: measured at 2.37 s,
REM  against 0.22 s for this. The app then imports them again for real, so
REM  the old check made you wait for the same two seconds twice, which is
REM  what the console window was doing while it sat there.
"%PY%" -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('spwb.gui') and u.find_spec('PySide6') and u.find_spec('pyqtgraph') else 1)" >nul 2>&1
if not errorlevel 1 goto :launch

echo.
echo   SPWB is not installed for this Python yet
echo   (or the GUI extra is missing).
echo.
echo   I can install it now from this folder. It downloads PySide6, so it
echo   needs an internet connection and about a minute.
echo.

REM  Set SPWB_AUTO_INSTALL=1 to skip this prompt (unattended setup, and it
REM  is how the launcher's install path is tested - "choice" reads the
REM  console directly, so it cannot be driven from a script).
if "%SPWB_AUTO_INSTALL%"=="1" goto :install

choice /c YN /n /m "   Install now? [Y/N] "
if errorlevel 2 (
    echo.
    echo   Nothing was installed. To do it yourself later:
    echo       pip install -e ".[gui,io]"
    echo.
    pause
    exit /b 1
)

:install

echo.
echo   Installing, please wait...
echo.
"%PY%" -m pip install -e ".[gui,io]"
if errorlevel 1 (
    echo.
    echo   The installation failed - the messages above say why.
    echo.
    pause
    exit /b 1
)

"%PY%" -c "import spwb.gui" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   The install finished but SPWB still cannot start.
    echo   Please report this with the messages above:
    echo   https://github.com/Charette-AI-Group/SPWB-py/issues
    echo.
    pause
    exit /b 1
)

REM --- 3. launch ---------------------------------------------------------
:launch
REM  pythonw has no console window. Any file names dragged onto this script
REM  are passed through, so "drag a .tdms onto runApp.cmd" opens it.
start "" "%PYW%" -m spwb %*
exit /b 0
