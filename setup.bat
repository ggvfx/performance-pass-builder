@echo off
rem Performance Pass Builder — first-time setup for Windows.
rem
rem Creates a virtual environment beside this script and installs the pinned
rem dependencies into it. Safe to run again: an existing venv is reused, and
rem pip simply confirms what is already there.
rem
rem Deliberately not a packaged installer. See CLAUDE.md — no Electron, no
rem PyInstaller, no code signing. A folder and this script is the whole thing.

setlocal
cd /d "%~dp0"

echo.
echo === Performance Pass Builder setup ===
echo.

rem --- PYTHON ---

rem The py launcher is asked for 3.12 specifically rather than whatever
rem "python" happens to be first on PATH, which on a machine with several
rem installs is usually the wrong one. numpy 2.5.3 will not install below
rem 3.12, and the failure that produces is a wall of compiler errors rather
rem than a clear message.
set PYTHON=
py -3.12 --version >nul 2>&1 && set PYTHON=py -3.12

if not defined PYTHON (
    python --version >nul 2>&1 && set PYTHON=python
)

if not defined PYTHON (
    echo Python was not found.
    echo.
    echo Install Python 3.12 or newer, then run this again:
    echo     winget install Python.Python.3.12
    echo or download it from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)"
if errorlevel 1 (
    echo The Python found is older than 3.12, which this app needs.
    %PYTHON% --version
    echo.
    echo Install Python 3.12 or newer, then run this again:
    echo     winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

echo Using:
%PYTHON% --version

rem --- VIRTUAL ENVIRONMENT ---

if exist "venv\Scripts\python.exe" (
    echo Reusing the existing virtual environment.
) else (
    echo Creating a virtual environment in venv\ ...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo Could not create the virtual environment.
        pause
        exit /b 1
    )
)

rem --- DEPENDENCIES ---

echo Installing the pinned dependencies. This takes a few minutes the first time.
echo.

venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Something failed to install. The message above says what.
    pause
    exit /b 1
)

rem --- FFMPEG ---

rem Checked but never installed: ffmpeg is a system tool, and silently putting
rem one on someone's PATH is not this script's business. The app's Setup tab
rem reports this too, with a command to copy.
echo.
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo NOTE: ffmpeg was not found on PATH. The app will start and tell you
    echo       how to install it, but it cannot build a pass without it:
    echo           winget install Gyan.FFmpeg
) else (
    echo ffmpeg was found.
)

echo.
echo === Setup finished ===
echo.
echo Start the app with:
echo     venv\Scripts\python.exe main.py
echo.
pause
