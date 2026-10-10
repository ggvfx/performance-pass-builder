"""
Shared Configuration.

Fixed project constants, and — once a task needs one — the per-run settings
object for each utility.

One file, so there is one place to look for what a setting is and what it
defaults to. No module invents its own default for anything a user can change;
a module may hold a tuning constant it alone uses, next to the comment
explaining the number.
"""

from pathlib import Path

# --- IDENTITY ---

APP_NAME = "Performance Pass Builder"

# Recorded in every sidecar. When a pass looks wrong months later, the first
# question is which version of this tool produced it.
APP_VERSION = "0.1.0"

# --- PROJECT PATHS ---

# src/core/config.py -> repo root is two parents up
REPO_ROOT = Path(__file__).resolve().parents[2]

STATIC_DIR = REPO_ROOT / "src" / "ui" / "static"

# --- FIXED REQUIREMENTS ---

# Set by numpy 2.5.3, which will not install on anything older.
MIN_PYTHON = (3, 12)

# --- SERVER ---

# Loopback only. The path picker lists this machine's filesystem, so the
# server must never listen on a public interface.
HOST = "127.0.0.1"

# One above minicut-shot-detector's 8765, so the two can run at once.
PORT = 8766
