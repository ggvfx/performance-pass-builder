"""
Shared Utility Functions.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Small helpers needed in more than one module. Anything here must depend on
nothing but the standard library — this is the bottom of the dependency chain,
and everything else is free to import it.

If a helper is only used by one module, it belongs in that module instead. One
file; split it per-package only when there is a concrete reason, and say what
the reason is at the time.
"""

from pathlib import Path

# --- FILE HELPERS ---


def ensure_directory(path: Path) -> Path:
    """
    Creates a directory if it does not exist, and returns it.

    Used before writing deliverables, working files and sidecars, so a missing
    output folder is never the reason a job fails halfway through.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
