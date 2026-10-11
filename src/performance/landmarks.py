"""
Writing `landmarks.json`.

Written for this project. minicut had no landmarks.

Every face, every frame, as fractions of the picture — the numbers behind the
mesh, so the mesh is not the only thing a job produces. A compositor who
wants to drive something else from the track, or check where a point actually
was on frame 112, has the data rather than a picture of it.

**A gap is `null`, never interpolated.** The same rule the track itself
keeps: a frame where the face was not found says so. Anyone reading this file
can tell "not found" from "found, and here it is", which is the distinction
that matters when a mesh looks wrong.

**Written only when asked for** — `config.WRITE_LANDMARKS_BY_DEFAULT` is
False. Nothing in the app reads this file, and a face mesh is
biometric-adjacent: not a recognition template, much weaker than the footage
it was derived from, but a new artefact that can travel separately from that
footage. An export nobody asked for should not be written, which disposes of
the question rather than arguing about how weak the signal is.

Notes:
    **This file is large and that is inherent.** 478 points of three numbers,
    per face, per frame: about 12 KB a frame, so roughly 3 MB for ten
    seconds of one face and 106 MB for two minutes of three. Measured, not
    estimated. Written compactly with no indentation for that reason —
    nobody reads 344,000 numbers by eye, and the sidecar is the file written
    for people.

    If it becomes a problem, `.npz` would be about a tenth of the size and
    is what Fal already hands back for depth. That is a decision to take
    deliberately, not a thing to switch to quietly, because this file is an
    interface.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from src.core.models import LANDMARK_COUNT, Face, FaceTrack, SourceInfo

# --- NAMING ---

LANDMARKS_SUFFIX = "_landmarks.json"

# Bumped when the shape changes, so an old file is recognised as old rather
# than half-read.
LANDMARKS_SCHEMA_VERSION = 1

# Five decimal places resolves to about 0.04 of a pixel at 4K and 0.02 at
# 1080p — comfortably finer than anything a landmark is accurate to, and
# shorter than writing float32's full repr for every one of them.
DECIMALS = 5


def landmarks_path_for(source_path: Path, output_dir: Path) -> Path:
    """The landmarks path for a source, e.g. 'take_01_landmarks.json'."""
    return output_dir / f"{source_path.stem}{LANDMARKS_SUFFIX}"


# --- WRITING ---


def write_landmarks(
    path: Path,
    source: SourceInfo,
    faces: list[Face],
    tracks: list[FaceTrack],
    written_at: datetime,
) -> Path:
    """
    Writes every face's landmarks and where its seeds were.

    Args:
        path: Destination, from `landmarks_path_for`.
        source: What was tracked, so the file can be checked against a
            source later rather than trusted to be about the right one.
        faces: The chosen faces, for their seeds.
        tracks: One per face, matched by label.
        written_at: When, in UTC with an offset — these files travel.

    Returns:
        The written path.

    Raises:
        ValueError: A track has no matching face, or a track is not the
            source's length.

    Notes:
        Faces are matched to tracks by label rather than by position. The
        selection model already refuses duplicate labels, and matching by
        index would silently attribute one person's seeds to another's
        landmarks if a caller ever reordered either list.
    """
    by_label = {face.label: face for face in faces}
    missing = [track.label for track in tracks if track.label not in by_label]
    if missing:
        raise ValueError(f"no face was chosen for these tracks: {missing}")

    wrong_length = [
        track.label for track in tracks if track.frame_count != source.frame_count
    ]
    if wrong_length:
        raise ValueError(
            f"these tracks are not the source's {source.frame_count} frames: "
            f"{wrong_length}"
        )

    document = {
        "schema_version": LANDMARKS_SCHEMA_VERSION,
        "written_at": written_at.isoformat(),
        "source": {
            "name": Path(source.path).name,
            "width": source.width,
            "height": source.height,
            "frame_count": source.frame_count,
            "fps_numerator": source.fps_numerator,
            "fps_denominator": source.fps_denominator,
        },
        "landmark_count": LANDMARK_COUNT,
        "coordinates": (
            "x and y are fractions of the picture, origin top-left. z is "
            "MediaPipe's own relative depth, roughly in the same scale as x, "
            "and is not metric — it has nothing to do with the depth pass."
        ),
        "faces": [_face_document(by_label[track.label], track) for track in tracks],
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    # Compact, and deliberately not indented. Indentation would add megabytes
    # to a file nobody reads by eye; the sidecar is the one written for people.
    path.write_text(
        json.dumps(document, separators=(",", ":")), encoding="utf-8"
    )

    logging.info(
        f"Wrote landmarks for {len(tracks)} face(s) "
        f"({path.stat().st_size / 1e6:.1f} MB): {path}"
    )
    return path


def _face_document(face: Face, track: FaceTrack) -> dict:
    """One face's seeds, outcome and per-frame landmarks."""
    return {
        "label": face.label,
        "seeds": [
            {
                "index": index,
                "frame": seed.frame,
                "box": {
                    "left": seed.box.left,
                    "top": seed.box.top,
                    "right": seed.box.right,
                    "bottom": seed.box.bottom,
                },
            }
            for index, seed in enumerate(face.seeds)
        ],
        "frames_tracked": int(track.tracked.sum()),
        "frames_missing": int((~track.tracked).sum()),
        "gaps": [
            {"start_frame": gap.start_frame, "end_frame": gap.end_frame}
            for gap in track.gaps()
        ],
        "segments": [
            {
                "seed_index": seed_index,
                "start_frame": covered.start_frame,
                "end_frame": covered.end_frame,
            }
            for seed_index, covered in track.segments()
        ],
        "landmarks": _landmarks_document(track),
    }


def _landmarks_document(track: FaceTrack) -> list:
    """
    Per-frame points, or None where the face was not found.

    Notes:
        Rounded through numpy rather than in a Python loop over 344,000
        values — the loop is the slow part of writing this file, not the
        JSON encoding.

        **Widened to float64 before rounding**, which halves the file. Round
        a float32 to five places and the nearest float32 to that is
        something like 0.45091733455657956; `tolist()` then writes all
        seventeen digits. Rounding in float64 gives 0.45092, which is what
        was meant and a third of the characters.
    """
    rounded = np.round(track.landmarks.astype(np.float64), DECIMALS)

    return [
        rounded[frame].tolist() if track.tracked[frame] else None
        for frame in range(track.frame_count)
    ]


# --- READING ---


def read_landmarks(path: Path) -> dict:
    """
    Loads a landmarks file, with each face's points as a numpy array.

    Returns:
        The document, with every face's `landmarks` replaced by a
        (frames, LANDMARK_COUNT, 3) float32 array — NaN where the file said
        null, so it reads exactly like a `FaceTrack`'s own array.

    Raises:
        ValueError: The file is a version this does not understand.

    Notes:
        Here so the round trip is testable and so a later tool has one
        obvious way in. Nothing in the app reads this file back today: it is
        written for whatever comes after the app.
    """
    document = json.loads(path.read_text(encoding="utf-8"))

    version = document.get("schema_version")
    if version != LANDMARKS_SCHEMA_VERSION:
        raise ValueError(
            f"{path.name} is schema version {version}, and this reads "
            f"version {LANDMARKS_SCHEMA_VERSION}"
        )

    frame_count = document["source"]["frame_count"]

    for face in document["faces"]:
        points = np.full((frame_count, LANDMARK_COUNT, 3), np.nan, dtype=np.float32)
        for frame, row in enumerate(face["landmarks"]):
            if row is not None:
                points[frame] = row
        face["landmarks"] = points

    return document
