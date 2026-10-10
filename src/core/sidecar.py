"""
JSON Sidecar Writing.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

One sidecar per job, written beside the deliverables: the record of how they
came to exist.

It is what makes a wrong pass diagnosable. Without it, a mesh that sits a
frame late tells you nothing about which model produced the depth, which
MediaPipe weights tracked the face, where the seeds were, or which ffmpeg
build wrote the file.

**Written whether the job passed or failed.** A failed job's sidecar is the
most useful thing to look at when working out why, and it is the one part of
a job that cannot be reconstructed afterwards.

The `Sidecar` model lives here rather than in `models.py` because it has to
reference the run settings, and `config.py` imports `models.py` — so a model
naming a settings type cannot live there without pointing the dependency
arrow backwards.

Functions rather than a class: writing one file shares no state between
calls.
"""

import importlib.metadata
import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from src.core import config
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import (
    AudioHandling,
    LayerStack,
    OutputFormat,
    SourceInfo,
    StoredDepth,
    TrackingReport,
    ValidationResult,
)

# --- NAMING ---

SIDECAR_SUFFIX = "_performance.json"

# Bumped when the shape changes, so an old sidecar is recognised as old
# rather than half-read.
SIDECAR_SCHEMA_VERSION = 1


def sidecar_path_for(source_path: Path, output_dir: Path) -> Path:
    """The sidecar path for a source, e.g. 'take_01_performance.json'."""
    return output_dir / f"{source_path.stem}{SIDECAR_SUFFIX}"


# --- WHAT WENT INTO IT ---


class DeliverableRecord(BaseModel):
    """One file this job produced, and whether it may be handed over."""

    path: Path
    output_format: OutputFormat
    audio: AudioHandling
    stack: LayerStack          # Which layers, in which order, switched on
    validation: ValidationResult


class Sidecar(BaseModel):
    """
    Everything one job produced, from what, and by which versions.

    Notes:
        The environment block is the part that cannot be reconstructed. A
        pass that looks wrong six months from now is diagnosed by knowing
        which ffmpeg build wrote it and which MediaPipe weights tracked the
        face, and neither is recoverable from the file itself.
    """

    schema_version: int = SIDECAR_SCHEMA_VERSION
    written_at: datetime

    # --- WHAT IT WAS MADE FROM ---
    source: SourceInfo
    depth: StoredDepth | None = None          # None when no depth pass ran
    tracking: TrackingReport | None = None    # None when no faces were tracked

    # --- WHAT CAME OUT ---
    deliverables: list[DeliverableRecord] = Field(default_factory=list)

    # --- HOW ---
    settings: dict[str, object] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """
        Whether every deliverable passed validation.

        Notes:
            A job with no deliverables has not passed. It has not run.
        """
        return bool(self.deliverables) and all(
            record.validation.passed for record in self.deliverables
        )


# --- ENVIRONMENT CAPTURE ---


def capture_environment(toolchain: MediaToolchain) -> dict[str, str]:
    """
    Records the resolved toolchain and libraries for reproducibility.

    Args:
        toolchain: The toolchain the job actually ran with, so the versions
            recorded are the ones that produced these files.

    Notes:
        Anything absent is recorded as absent rather than omitted. A sidecar
        that simply lacks a key cannot be told apart from one written by an
        older version of this app.
    """
    environment = {
        "app": f"{config.APP_NAME} {config.APP_VERSION}",
        "platform": platform.platform(),
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        **toolchain.versions(),
    }

    for label, distribution in (("mediapipe", "mediapipe"), ("opencv", "opencv-contrib-python")):
        try:
            environment[label] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            environment[label] = "not installed"

    return environment


# --- WRITING ---


def write_sidecar(sidecar: Sidecar, output_path: Path) -> Path:
    """
    Serialises a job to JSON.

    Args:
        sidecar: The finished job, including every validation outcome.
        output_path: Destination, from `sidecar_path_for`.

    Returns:
        Path to the written file.

    Notes:
        Written whether validation passed or failed, and indented because it
        is read by people more often than by programs.

        Pydantic's own JSON rather than `json.dump`: the Path, datetime and
        Enum fields here would make `json.dump` raise, and the alternative is
        a converter per type that drifts from the model.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(sidecar.model_dump_json(indent=2), encoding="utf-8")

    outcome = "passed" if sidecar.passed else "FAILED validation"
    logging.info(
        f"Wrote sidecar for {len(sidecar.deliverables)} deliverable(s) "
        f"({outcome}): {output_path}"
    )
    return output_path


def now() -> datetime:
    """
    The moment a sidecar was written, in UTC.

    Notes:
        UTC with an explicit offset rather than a naive local time: these
        files travel between machines, and a timestamp that does not say
        which clock it came from is worse than none.
    """
    return datetime.now(timezone.utc)
