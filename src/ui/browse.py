"""
Filesystem Browsing for the Path Picker.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Lets the browser front end walk this machine's directories to pick a source
file and an output folder.

Multi-gigabyte media is never uploaded through a form — the server and the
media are on the same machine, so the UI sends a path, not a file.
"""

import logging
import string
from pathlib import Path

from pydantic import BaseModel

from src.core.config import VIDEO_SUFFIXES

# --- RESULT MODELS ---


class DirectoryEntry(BaseModel):
    """One row in the picker."""

    name: str
    path: Path
    is_directory: bool
    is_video: bool = False
    size_bytes: int = 0


class DirectoryListing(BaseModel):
    """A directory's contents, plus where the user can navigate from here."""

    path: Path
    parent: Path | None = None  # None at a drive or filesystem root
    roots: list[str]            # Drive letters on Windows, "/" elsewhere
    entries: list[DirectoryEntry]


# --- LISTING ---


def available_roots() -> list[str]:
    """The top-level starting points: drive letters on Windows, '/' elsewhere."""
    candidates = [f"{letter}:\\" for letter in string.ascii_uppercase]
    drives = [drive for drive in candidates if Path(drive).exists()]
    return drives or ["/"]


def list_directory(path: Path, videos_only: bool = False) -> DirectoryListing:
    """
    Lists one directory for the picker.

    Args:
        path: Directory to list.
        videos_only: Hide files that are not recognised video, for the source
            picker. The output picker shows directories only anyway.

    Returns:
        DirectoryListing: directories first, then files, each alphabetical.

    Raises:
        NotADirectoryError: If the path is not a directory.
    """
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(str(resolved))

    directories: list[DirectoryEntry] = []
    files: list[DirectoryEntry] = []

    for item in sorted(resolved.iterdir(), key=lambda entry: entry.name.lower()):
        try:
            if item.is_dir():
                directories.append(DirectoryEntry(name=item.name, path=item, is_directory=True))
                continue

            is_video = item.suffix.lower() in VIDEO_SUFFIXES
            if videos_only and not is_video:
                continue

            files.append(
                DirectoryEntry(
                    name=item.name,
                    path=item,
                    is_directory=False,
                    is_video=is_video,
                    size_bytes=item.stat().st_size,
                )
            )

        except OSError as error:
            # Offline network shares, junctions and permission-denied entries
            # should not take out the whole listing
            logging.debug(f"Skipping unreadable entry {item}: {error}")
            continue

    # At a root, .parent returns the same path — report no parent instead
    parent = None if resolved.parent == resolved else resolved.parent

    return DirectoryListing(
        path=resolved,
        parent=parent,
        roots=available_roots(),
        entries=directories + files,
    )
