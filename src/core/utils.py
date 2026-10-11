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

from collections.abc import Iterable
from pathlib import Path

# --- SEQUENCES ---


def runs_of_true(flags: Iterable[bool]) -> list[tuple[int, int]]:
    """
    Inclusive (start, end) index pairs for each unbroken run of True.

    Args:
        flags: Any iterable of truthy values — a list, a generator, or a
            numpy boolean array.

    Returns:
        One pair per run, in order. Empty when nothing is True.

    Notes:
        Two stages ask the same question of different data: which frames was
        a face missing from, and which frames did a depth model repeat. Both
        want runs rather than counts, because one long absence and shimmer
        throughout need different answers.

        A run reaching the end of the sequence is closed at the last index
        rather than dropped, which is the bug this shape exists to avoid.

        Plain Python over an iterable, not numpy, so it stays where the
        dependency rules allow everything to reach it.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    index = -1

    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None

    if start is not None:
        runs.append((start, index))

    return runs


# --- FILE HELPERS ---


def ensure_directory(path: Path) -> Path:
    """
    Creates a directory if it does not exist, and returns it.

    Used before writing deliverables, working files and sidecars, so a missing
    output folder is never the reason a job fails halfway through.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
