"""
File Browsing.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

The path picker. Server-side rather than a browser file dialog, because the
media and the app are on one machine and a multi-gigabyte source should never
be uploaded to reach a server that could have opened it.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.ui import browse

router = APIRouter()

# --- FILE BROWSING ---


@router.get("/api/browse")
def get_directory(path: str | None = None, videos_only: bool = False) -> browse.DirectoryListing:
    """
    Lists a directory for the path picker.

    Args:
        path: Directory to list. Defaults to the user's home folder.
        videos_only: Hide non-video files, for the source picker.

    Raises:
        HTTPException: 404 when the path is not a directory, 403 when it
            cannot be read. Both are things the user can act on, so they are
            answers rather than server errors.
    """
    target = Path(path) if path else Path.home()

    try:
        return browse.list_directory(target, videos_only=videos_only)
    except NotADirectoryError:
        raise HTTPException(status_code=404, detail=f"Not a directory: {target}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")
