"""
Tests for the Shared Utilities.

One function so far. It is here because a missing output folder should never
be the reason a job fails after the expensive part has already run.
"""

import tempfile
from pathlib import Path

from src.core.utils import ensure_directory


def test_a_missing_directory_is_created():
    with tempfile.TemporaryDirectory() as temporary:
        wanted = Path(temporary) / "take_01_performance" / ".performance-work"
        assert not wanted.exists()

        returned = ensure_directory(wanted)

        assert wanted.is_dir(), "the directory and its parents should have been created"
        assert returned == wanted, "the path is returned so a caller can chain on it"


def test_an_existing_directory_is_left_alone():
    """Called before every write, so it has to be safe to call repeatedly."""
    with tempfile.TemporaryDirectory() as temporary:
        existing = Path(temporary) / "work"
        existing.mkdir()
        (existing / "depth.mkv").write_text("paid for", encoding="utf-8")

        ensure_directory(existing)

        assert (existing / "depth.mkv").read_text(encoding="utf-8") == "paid for", (
            "an existing directory's contents must survive"
        )
