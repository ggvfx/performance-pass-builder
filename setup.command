#!/bin/bash
# Performance Pass Builder — first-time setup for macOS.
#
# Creates a virtual environment beside this script and installs the pinned
# dependencies into it. Safe to run again: an existing venv is reused, and pip
# simply confirms what is already there.
#
# Named .command so it runs on a double-click from Finder. It may need to be
# made executable once first:
#     chmod +x setup.command
#
# Deliberately not a packaged installer. See CLAUDE.md — no Electron, no
# PyInstaller, no code signing. A folder and this script is the whole thing.

set -u
cd "$(dirname "$0")" || exit 1

echo
echo "=== Performance Pass Builder setup ==="
echo

# --- PYTHON ---

# A specific version is asked for rather than whatever "python3" happens to
# be: numpy 2.5.3 will not install below 3.12, and the failure that produces
# is a wall of compiler errors rather than a clear message.
PYTHON=""
for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)'; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "No Python 3.12 or newer was found."
    echo
    echo "Install one, then run this again:"
    echo "    brew install python@3.12"
    echo "or download it from https://www.python.org/downloads/"
    echo
    read -r -p "Press return to close."
    exit 1
fi

echo "Using:"
"$PYTHON" --version

# --- APPLE SILICON ---

# MediaPipe 1.1.0 ships wheels for Apple Silicon macOS and not for Intel, so
# this is said before the install rather than discovered inside pip's output.
# ARCHITECTURE.md open question 6.
if [ "$(uname -m)" != "arm64" ]; then
    echo
    echo "NOTE: this Mac is not Apple Silicon. MediaPipe does not publish wheels"
    echo "      for Intel macOS, so the install below may fail on that package."
fi

# --- VIRTUAL ENVIRONMENT ---

if [ -x "venv/bin/python" ]; then
    echo "Reusing the existing virtual environment."
else
    echo "Creating a virtual environment in venv/ ..."
    if ! "$PYTHON" -m venv venv; then
        echo "Could not create the virtual environment."
        read -r -p "Press return to close."
        exit 1
    fi
fi

# --- DEPENDENCIES ---

echo "Installing the pinned dependencies. This takes a few minutes the first time."
echo

venv/bin/python -m pip install --upgrade pip --quiet
if ! venv/bin/python -m pip install -r requirements.txt; then
    echo
    echo "Something failed to install. The message above says what."
    read -r -p "Press return to close."
    exit 1
fi

# --- FFMPEG ---

# Checked but never installed: ffmpeg is a system tool, and silently putting
# one on someone's PATH is not this script's business. The app's Setup tab
# reports this too, with a command to copy.
echo
if command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg was found."

    # Homebrew's bottle is built without libfreetype, so it has no drawtext and
    # the review proxy loses its burned-in frame numbers. Not fatal, and the
    # app says so too, but it is cheaper to hear now.
    if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -qw drawtext; then
        echo "NOTE: this ffmpeg has no drawtext filter, so the review proxy will"
        echo "      have no burned-in frame numbers. Everything else works."
    fi
else
    echo "NOTE: ffmpeg was not found on PATH. The app will start and tell you"
    echo "      how to install it, but it cannot build a pass without it:"
    echo "          brew install ffmpeg"
fi

echo
echo "=== Setup finished ==="
echo
echo "Start the app with:"
echo "    venv/bin/python main.py"
echo
read -r -p "Press return to close."
