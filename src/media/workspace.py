"""
The Working Folder.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Everything a job needs but nobody asked for lives in `.performance-work/`
inside the output directory: the mezzanine, the review proxy, the stored
depth, and each pass's rendered layer. The delivery folder holds the
deliverables and the sidecar, and nothing else.

This module owns the folder's naming and its lifecycle. The pipeline decides
when a job is finished with it; what the files are called, which source each
belongs to, and what can safely be deleted is decided here.

**Nothing is reclaimed behind the user's back.** A job that is analysed and
then abandoned keeps its working files, and that is deliberate: the whole
point of preparing first is that the expensive part survives until the person
has finished. It matters more here than it did in minicut, because the
cached depth in that folder was paid for — deleting it to save disk means
paying again.
"""

import logging
from pathlib import Path

from src.core.config import PROXY_SUFFIX

# --- WORKING FILES ---

# Inside the output directory, so an abandoned job leaves one obviously
# temporary folder rather than several large files sitting among the
# deliverables.
WORK_DIRECTORY = ".performance-work"

# Each is named after the source, so two jobs sharing an output directory
# cannot collide.
MEZZANINE_SUFFIX = "_mezzanine"
DEPTH_SUFFIX = "_depth_field"
LAYER_SUFFIX = "_layer"

# Every suffix a working file can carry, longest first. Order matters:
# `owning_source` strips the first match, and "_depth_field" has to be tried
# before anything that is a prefix of it would be.
WORK_SUFFIXES = (
    MEZZANINE_SUFFIX,
    DEPTH_SUFFIX,
    LAYER_SUFFIX,
    Path(PROXY_SUFFIX).stem,  # "_proxy", without the extension
)


def work_dir_for(output_dir: Path) -> Path:
    """The working folder inside an output directory."""
    return output_dir / WORK_DIRECTORY


def owning_source(work_file: Path) -> str:
    """
    The source stem a working file belongs to.

    Notes:
        Derived by removing the suffix that was added to it, rather than by
        asking whether the name starts with a source stem — "take_02" would
        otherwise claim "take_02_extra_mezzanine.mov", and clearing the work
        folder would spare the wrong file.

        Scratch belonging to no source returns its own name, which matches
        nothing and is therefore always reclaimable.
    """
    stem = work_file.stem

    for suffix in WORK_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]

    return stem


def reclaimable_work(output_dir: Path, keep_source: Path | None = None) -> list[Path]:
    """
    Working files that can be deleted without costing anyone their work.

    Args:
        output_dir: The job's output directory, which holds the work folder.
        keep_source: The source currently being worked on, whose mezzanine
            and depth are still needed. Everything is reclaimable when this is
            None — the normal case before anything has been prepared.

    Returns:
        The files, sorted by path. Empty when there is no work folder.

    Notes:
        A sequence layer is a folder rather than a file, so directories are
        included and `clear_work` removes them whole.
    """
    work_dir = work_dir_for(output_dir)
    if not work_dir.is_dir():
        return []

    keep = keep_source.stem if keep_source else None

    return sorted(path for path in work_dir.iterdir() if owning_source(path) != keep)


def reclaimable_bytes(output_dir: Path, keep_source: Path | None = None) -> int:
    """
    How much deleting the reclaimable files would free.

    Notes:
        Reported so the user can decide, rather than reclaimed quietly. These
        are files they can rebuild — but only by waiting through the encode
        again, and in the case of depth, by paying for it again.
    """
    return sum(_size_of(path) for path in reclaimable_work(output_dir, keep_source))


def clear_work(output_dir: Path, keep_source: Path | None = None) -> int:
    """
    Deletes the reclaimable working files and reports what that freed.

    Returns:
        Bytes actually freed.

    Notes:
        A file that will not delete is logged and skipped rather than failing
        the whole request: one locked file should not stop the other three
        gigabytes going.

        The work folder itself is removed once it is empty, so an output
        directory that is finished with looks finished with.
    """
    freed = 0

    for path in reclaimable_work(output_dir, keep_source):
        size = _size_of(path)
        try:
            _remove(path)
        except OSError as error:
            logging.warning(f"Could not remove {path}: {error}")
            continue
        freed += size

    work_dir = work_dir_for(output_dir)
    if work_dir.is_dir() and not any(work_dir.iterdir()):
        work_dir.rmdir()

    logging.info(f"Cleared {freed / (1024 ** 3):.2f} GB of working files from {output_dir}")
    return freed


# --- FILES AND FOLDERS ---


def _size_of(path: Path) -> int:
    """Bytes on disk, counting a sequence folder's frames."""
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return path.stat().st_size


def _remove(path: Path) -> None:
    """Deletes a file, or a sequence folder and everything in it."""
    if not path.is_dir():
        path.unlink()
        return

    for item in sorted(path.rglob("*"), reverse=True):
        item.unlink() if item.is_file() else item.rmdir()
    path.rmdir()
