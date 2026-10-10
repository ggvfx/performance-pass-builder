"""
Setup Routes.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

What is installed and how to install it. The depth backend picker joins this
module at task 4.4; the model-backend configuration minicut carried here has
no counterpart and did not come across.
"""

from pathlib import Path

from fastapi import APIRouter

from src.core.environment import EnvironmentReport, ffmpeg_fixes, platform_name, python_fixes
from src.ui.runtime import checker

router = APIRouter()

# --- ENVIRONMENT ---


@router.get("/api/environment")
def get_environment(output_dir: str | None = None, refresh: bool = False) -> EnvironmentReport:
    """
    The dependency panel.

    Args:
        output_dir: Chosen output directory, so free space is checked against
            the volume that will actually be written to.
        refresh: True when the user presses Re-check. Otherwise the cached
            result is returned, since the checks shell out to ffmpeg several
            times.

    Notes:
        The depth backend's rows will be assembled at 4.4 and passed in as
        `extra`, rather than being produced inside the checker: they live in
        `src/backends/`, and `core` importing a domain package would point the
        dependency arrow the wrong way.
    """
    return checker.report(
        output_dir=Path(output_dir) if output_dir else None,
        refresh=refresh,
    )


# --- INSTALL GUIDE ---


@router.get("/api/install-guide")
def get_install_guide() -> dict:
    """
    How to install what the app needs on this machine, whatever its state.

    Separate from the environment checks on purpose. Those only speak up when
    something is missing, which is useless to the person setting up a second
    machine — this is readable when everything is already fine.
    """
    return {
        "platform": platform_name(),
        "requirements": [
            {"label": "Python", "fixes": [fix.model_dump() for fix in python_fixes()]},
            {"label": "ffmpeg and ffprobe", "fixes": [fix.model_dump() for fix in ffmpeg_fixes()]},
        ],
    }
