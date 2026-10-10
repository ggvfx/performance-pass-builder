"""
Shared Data Models.

The structured schemas passed between stages and written to disk. BaseModel
means a file can be re-loaded and re-validated without hand-written parsing,
and a missing field is an error rather than a wrong answer further on.

Grouped by stage. Written for this project rather than ported, taking three
shapes from minicut as reference — see PORTING.md.

Imports nothing of ours: `config.py` imports this, so a constant that is part
of a data contract rather than a setting lives here.

Design reasoning for every stage is in ARCHITECTURE.md. What is here is the
contract — the invariants a caller can rely on.

Key terms:
- frame     = integer frame index, 0 at the first frame of the source
- seed      = a box drawn on a chosen frame, from which tracking runs
- face      = one selected person: a label and a list of seeds
- segment   = the run of frames one seed is responsible for
- plate     = the original footage
- pass      = one generator: depth, faces, later segmentation
- layer     = what a pass produces, for the stack to composite
- pass      = a deliverable video exactly as long as the source
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

# =====================================================================
# CONTRACT CONSTANTS
#
# Facts about a file format or a model file, not settings. They live here
# because config.py imports this module and not the other way round.
# =====================================================================

# MediaPipe Face Landmarker with refined landmarks returns 478 points per face:
# 468 of the base mesh plus 10 for the irises. The second axis of FaceTrack's
# landmark array.
LANDMARK_COUNT = 478

# Bumped when a written file's shape changes, so an old selection.json is
# recognised as old rather than half-read.
SELECTION_SCHEMA_VERSION = 1


# =====================================================================
# SHARED
# =====================================================================

# --- FRAME RANGES ---


class FrameRange(BaseModel):
    """
    A run of consecutive frames, both ends included.

    Inclusive because it describes frames rather than slices: a gap covering
    only frame 40 is `FrameRange(start_frame=40, end_frame=40)` and is one
    frame long.
    """

    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)

    @computed_field
    @property
    def frame_count(self) -> int:
        """Length in frames, inclusive of both ends."""
        return self.end_frame - self.start_frame + 1

    @model_validator(mode="after")
    def check_order(self) -> "FrameRange":
        if self.end_frame < self.start_frame:
            raise ValueError(f"end_frame {self.end_frame} is before start_frame {self.start_frame}")
        return self


# --- SOURCE ---


class AudioInfo(BaseModel):
    """
    One audio stream of the source, as ffprobe reported it.

    The source's audio is carried into every pass untouched, so whether that
    is possible is something the user learns from the probe, before the job,
    rather than from ffmpeg failing at the end of it.
    """

    codec: str                      # ffprobe's codec_name: "aac", "pcm_s24le"
    sample_rate: int = Field(gt=0)  # Hz
    channels: int = Field(gt=0)
    bit_rate: int | None = None     # None when the container does not declare one

    # False for the formats mp4 cannot hold — 24-bit PCM off a camera being the
    # usual one. The encode stage then encodes once at a high bitrate and the
    # sidecar records that it did. CLAUDE.md non-negotiable 3.
    can_stream_copy_to_mp4: bool


class SourceInfo(BaseModel):
    """What ffprobe reported about the source file."""

    path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    # The exact rational ffmpeg reports (24000/1001), never a rounded float:
    # 23.976 drifts a frame roughly every forty seconds. All arithmetic on
    # these belongs to core/timecode.py and nowhere else.
    fps_numerator: int = Field(gt=0)    # e.g. 24000
    fps_denominator: int = Field(gt=0)  # e.g. 1001

    frame_count: int = Field(gt=0)
    codec: str

    # Carried through to the mezzanine so a 10-bit source is not quietly
    # flattened to 8-bit on the way out.
    pixel_format: str = "yuv420p"

    # Source start timecode, e.g. "10:00:00:00". Sidecar timecodes are offset
    # by this so they match what the editor sees.
    start_timecode: str = "00:00:00:00"

    # True when r_frame_rate and avg_frame_rate disagree — variable frame rate.
    # Recorded here and refused by the pipeline, so the refusal carries a
    # reason the page can show rather than surfacing an exception.
    is_variable_frame_rate: bool = False

    # What the container declared. Advisory only: duration is derived from the
    # frame count and the exact rate, because frames are what a pass is made
    # of. Kept because the two disagreeing is worth being able to show.
    container_duration_seconds: float | None = None

    audio: AudioInfo | None = None  # None when the source is mute

    @computed_field
    @property
    def has_audio(self) -> bool:
        return self.audio is not None


class ProbeReport(BaseModel):
    """
    What inspecting a source told us, and whether a job can proceed.

    The split between `can_build` and `warnings` is deliberate: a variable
    frame rate source cannot carry a frame-accurate pass at all, while a tight
    disk is the user's call to make.
    """

    source: SourceInfo

    # Duration as a timecode, which reads better than a frame count in the UI.
    duration_timecode: str

    # A folder of its own beside the source, unless the user says otherwise.
    # Worked out server-side, where splitting a path for both platforms can be
    # tested.
    suggested_output_dir: Path

    estimated_gb: float
    free_gb: float | None = None

    can_build: bool = True
    refusal_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PreparedJob(BaseModel):
    """
    What a source needs before faces can be selected on it.

    Everything expensive happens here — the mezzanine encode and the depth
    call — so it is done once and the selection happens against the result.
    """

    source: SourceInfo

    # All-intra, verified against the source, for exact random access while
    # re-seeding. ARCHITECTURE.md stage 2 says why.
    mezzanine_path: Path

    # Small, all-intra, frame numbers burned in. What the browser plays.
    proxy_path: Path

    depth: "StoredDepth | None" = None  # None until the depth stage has run


# =====================================================================
# DEPTH
#
# What is stored is a scalar field; what is shown is a picture derived from
# it. Keeping those apart is what lets the window and the colour map be
# changed locally and instantly, without ever calling the model again.
# =====================================================================

# --- WHAT WAS ASKED FOR ---


class DepthModel(str, Enum):
    """
    The Video Depth Anything weights Fal exposes.

    SMALL is Apache-2.0; BASE and LARGE are CC-BY-NC-4.0, non-commercial only.
    Fal defaults to LARGE, so this project always sends the parameter
    explicitly — CLAUDE.md non-negotiable 14.
    """

    SMALL = "VDA-Small"
    BASE = "VDA-Base"
    LARGE = "VDA-Large"


class DepthColormap(str, Enum):
    """
    How a depth picture is coloured. Fal's own list, nothing invented here.

    Applied when the depth layer is rendered, never to what is stored: the
    others are not invertible, so colouring early would make windowing
    impossible.
    """

    GRAYSCALE = "grayscale"
    TURBO = "turbo"
    INFERNO = "inferno"
    MAGMA = "magma"
    VIRIDIS = "viridis"


class DepthBackendName(str, Enum):
    """Which implementation of `DepthBackend` produced a depth field."""

    FAL = "fal"
    LOCAL = "local"


# --- WHAT CAME BACK ---


class StoredDepth(BaseModel):
    """
    A depth field that has been checked against its source and cached.

    A StoredDepth existing means frame count, frame rate and aspect ratio all
    matched the source on arrival.

    Notes:
        Single-channel, and not a picture — the `.npz` is transport and is
        deleted once converted.

        Values run 0..1 across `[min_depth, max_depth]`, the model's own
        figures. Depth here is relative, not metric, and normalised per clip,
        so those two numbers are what a window's values mean.
    """

    path: Path                      # Inside the job's `.performance-work/`
    cache_key: str                  # Source identity plus the settings below

    # --- WHAT PRODUCED IT ---
    backend: DepthBackendName
    model: DepthModel
    request_id: str | None = None   # Fal's, for the sidecar. None for local

    # --- PRECISION ---
    # How many levels a window has to work with: the middle 10% of 8-bit depth
    # leaves about 25 and terraces on a face, 16-bit about 6,550. Recorded so
    # the UI can say when a tight window is not honest.
    bit_depth: int = Field(ge=8, le=32)

    # The model's own range, from the .npz. See the note above.
    min_depth: float
    max_depth: float

    # --- AS CHECKED ON ARRIVAL ---
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_count: int = Field(gt=0)

    # The colormapped video that came back from the same call. Free, and the
    # instant preview before a window is chosen. Never the source of a layer.
    preview_path: Path | None = None

    @model_validator(mode="after")
    def check_range_is_ordered(self) -> "StoredDepth":
        if self.max_depth <= self.min_depth:
            raise ValueError(
                f"max_depth {self.max_depth} must be greater than min_depth {self.min_depth}"
            )
        return self


# --- WHAT IS SHOWN ---


class DepthWindow(BaseModel):
    """
    The part of the depth range mapped onto the output's full 0..1.

    A levels operation with the black and white points pulled inward, so the
    whole output range is spent on the part of the shot that matters:

        out = clamp((depth - near) / (far - near), 0, 1)

    Notes:
        Fractions of the stored field's own 0..1, so they mean whatever
        `min_depth` and `max_depth` meant.

        **One window for the whole clip** — per-frame would make the depth
        pump. Outside it is clipped. See ARCHITECTURE.md, the depth pass.
    """

    near: float = Field(ge=0.0, le=1.0)  # Maps to the output's white
    far: float = Field(ge=0.0, le=1.0)   # Maps to the output's black

    @model_validator(mode="after")
    def check_window_has_width(self) -> "DepthWindow":
        if self.far <= self.near:
            raise ValueError(f"far {self.far} must be beyond near {self.near}")
        return self

    @computed_field
    @property
    def width(self) -> float:
        """How much of the range the window spans. 1.0 is the whole thing."""
        return self.far - self.near


# =====================================================================
# SELECTION
# =====================================================================


class NormalisedBox(BaseModel):
    """
    A rectangle as fractions of the picture, origin top-left.

    Fractions rather than pixels so the front end owns no arithmetic, and so
    one box describes both the proxy it was drawn on and the full-resolution
    mezzanine it is applied to.
    """

    left: float = Field(ge=0.0, le=1.0)
    top: float = Field(ge=0.0, le=1.0)
    right: float = Field(ge=0.0, le=1.0)
    bottom: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_corners_ordered(self) -> "NormalisedBox":
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError(
                f"box corners out of order or zero-sized: left={self.left} "
                f"right={self.right} top={self.top} bottom={self.bottom}"
            )
        return self

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """
        The box in whole pixels of a picture of the given size.

        Args:
            width: Picture width in pixels.
            height: Picture height in pixels.

        Returns:
            (left, top, right, bottom), left and top inclusive, right and
            bottom exclusive, so the width is right - left and the result can
            slice a frame array directly.

        Notes:
            The one owner of this conversion. Two modules rounding fractions to
            pixels their own way is how a search box and the crop it produces
            end up a pixel apart.
        """
        # PSEUDOCODE
        # 1. Multiply each fraction by width or height as appropriate.
        # 2. Floor left and top, ceil right and bottom, so a box never loses a
        #    pixel of the face it was drawn around.
        # 3. Clamp to the picture, and guarantee at least one pixel in each
        #    axis so a crop can never come back empty.
        raise NotImplementedError

    def padded(self, by: float) -> "NormalisedBox":
        """
        A larger box around the same centre, clamped to the picture.

        Args:
            by: Fraction of the box's own width and height to add on each side.
                0.5 makes a box twice as wide and twice as tall.

        Returns:
            A new box; this one is unchanged.

        Notes:
            The tracker's search region: each frame it looks inside a padded
            box around where the face was on the previous frame. The amount is
            a setting, in config.py.

            Clamping means a face near the edge gets a smaller pad rather than
            an invalid box, so callers never have to guard it.
        """
        # PSEUDOCODE
        # 1. Work out the current width and height as fractions.
        # 2. Expand each edge outward by `by` times that dimension.
        # 3. Clamp every edge into 0..1 and return a new box.
        raise NotImplementedError


class Seed(BaseModel):
    """
    One box on one frame, from which a face is tracked.

    A face usually needs more than one: re-seeding past a break is the normal
    way to work, not a recovery path.
    """

    frame: int = Field(ge=0)  # The frame the box was drawn on
    box: NormalisedBox        # Where the face is on that frame


class Face(BaseModel):
    """
    One face the artist chose: what to call it, and where it was marked.

    Each face is marked on whichever frames suit it — the frame where one
    person is clearest is not the frame where everyone else is.
    """

    label: str = Field(min_length=1)       # Shown in the UI, and names the face in reports
    seeds: list[Seed] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def check_label_is_not_blank(cls, label: str) -> str:
        if not label.strip():
            raise ValueError("a face label cannot be only whitespace")
        return label.strip()

    @model_validator(mode="after")
    def check_seeds_are_ordered_and_distinct(self) -> "Face":
        """
        Keeps seeds in frame order with no frame used twice.

        Notes:
            The order is the segment boundaries — tracking runs backward from
            the first seed and forward from each to the next — so it is sorted
            here rather than trusted from the browser.
        """
        frames = [seed.frame for seed in self.seeds]
        duplicates = {frame for frame in frames if frames.count(frame) > 1}
        if duplicates:
            raise ValueError(
                f"face {self.label!r} has more than one seed on {sorted(duplicates)}"
            )

        self.seeds.sort(key=lambda seed: seed.frame)
        return self

    @computed_field
    @property
    def seed_frames(self) -> list[int]:
        """The frames this face was marked on, in order."""
        return [seed.frame for seed in self.seeds]


class Selection(BaseModel):
    """
    Every face chosen for one source. Written as `selection.json`.

    Notes:
        This file is the whole interface between the picker and the pipeline,
        so a different front end only has to write the same thing. The source
        fields are here so a selection left over from another cut is caught
        rather than applied to the wrong footage.
    """

    schema_version: int = SELECTION_SCHEMA_VERSION
    created_at: datetime

    source_name: str                   # File name only; the path may have moved
    source_frame_count: int = Field(gt=0)

    faces: list[Face] = Field(min_length=1)

    @model_validator(mode="after")
    def check_faces_are_distinct_and_in_range(self) -> "Selection":
        """
        Rejects a selection the pipeline could not act on.

        Raises:
            ValueError: Two faces share a label, or a seed is past the end of
                the source.

        Notes:
            Labels are keyed on by the report and landmarks.json, so two faces
            called "Woman" would silently lose one. A seed past the end usually
            means a selection made against a longer cut.
        """
        labels = [face.label for face in self.faces]
        duplicates = {label for label in labels if labels.count(label) > 1}
        if duplicates:
            raise ValueError(f"face labels must be unique; repeated: {sorted(duplicates)}")

        for face in self.faces:
            for seed in face.seeds:
                if seed.frame >= self.source_frame_count:
                    raise ValueError(
                        f"face {face.label!r} has a seed on frame {seed.frame}, "
                        f"but the source has {self.source_frame_count} frames"
                    )
        return self


# =====================================================================
# TRACKS
# =====================================================================


@dataclass
class FaceTrack:
    """
    One face's landmarks on every frame of the source.

    The documented exception to Pydantic everywhere: 478 points per face per
    frame is several million values for a normal shot, and validation only
    needs to happen where the arrays are filled and where they are written out.

    Array contract, checked by `validate_shape()` and nowhere else:

        landmarks   float32, shape (frame_count, LANDMARK_COUNT, 3).
                    x and y are fractions of the picture; z is MediaPipe's own
                    relative depth, roughly in the same scale as x. It is not
                    metric and has nothing to do with the depth pass.
        tracked     bool, shape (frame_count,). True where the face was found.
        seeded_by   int16, shape (frame_count,). Index into the face's `seeds`
                    of whichever seed this frame was tracked from, and -1
                    where it was not tracked.

    Notes:
        An untracked frame's landmarks row is NaN, not zero, so a caller that
        forgot to check `tracked` fails loudly instead of quietly drawing a
        mesh in the top-left corner. A gap is recorded, never guessed.

        `seeded_by` is what lets the timeline show which box a stretch of
        track came from.
    """

    label: str
    landmarks: np.ndarray
    tracked: np.ndarray
    seeded_by: np.ndarray

    @property
    def frame_count(self) -> int:
        """Length of the track. Read off the array so it cannot disagree with it."""
        return int(self.landmarks.shape[0])

    def validate_shape(self) -> None:
        """
        Asserts the array contract in the class docstring.

        Raises:
            ValueError: A shape, dtype or length does not match it.

        Notes:
            Called where a track is built and before it is written out, and
            nowhere else — the point of raw arrays is that nothing else pays
            for validation, so those two places have to be deliberate.
        """
        # PSEUDOCODE
        # 1. landmarks: three dimensions, second is LANDMARK_COUNT, third is 3.
        # 2. landmarks dtype is float32 — float64 doubles the memory for
        #    precision no landmark has.
        # 3. tracked and seeded_by: one dimension each, both the same length as
        #    landmarks, dtypes bool and int16.
        # 4. Every row where tracked is False is entirely NaN and has
        #    seeded_by == -1; no row where it is True holds a NaN or a -1.
        #    That is the invariant the drawing stage relies on, and it is cheap
        #    to check once.
        raise NotImplementedError

    def gaps(self) -> list[FrameRange]:
        """
        The runs of frames where the face was not found.

        Notes:
            Reported per face, and not a failure. Ranges rather than a count,
            because one long absence and shimmer throughout need different
            answers from the artist.
        """
        # PSEUDOCODE
        # 1. Walk `tracked` for transitions True->False and False->True.
        # 2. Emit a FrameRange per run of False, inclusive at both ends.
        # 3. A track that is False throughout is one range covering the shot,
        #    not an empty list — "found nothing" and "found everything" must
        #    not look the same to the caller.
        raise NotImplementedError

    def segments(self) -> list[tuple[int, FrameRange]]:
        """
        Which frames each seed ended up responsible for.

        Returns:
            (seed index, frame range) pairs in frame order, covering only the
            frames that were actually tracked.

        Notes:
            Read off `seeded_by` rather than derived from the seed frames: a
            segment ends where the face was lost, which is not knowable until
            the track exists.
        """
        # PSEUDOCODE
        # 1. Walk `seeded_by`, skipping -1.
        # 2. Start a new range whenever the value changes.
        # 3. Emit (value, FrameRange) per run.
        raise NotImplementedError

    def landmarks_on(self, frame: int) -> np.ndarray | None:
        """
        The (LANDMARK_COUNT, 3) points for one frame, or None if it is a gap.

        Raises:
            IndexError: The frame is outside the track.

        Notes:
            None rather than the NaN row, so the drawing stage's "is there a
            face here" reads as a question about the face and not about
            floating point.
        """
        # PSEUDOCODE
        # 1. Bounds-check the frame. Out of range is a programming error, so it
        #    raises rather than returning None and being mistaken for a gap.
        # 2. Return None where tracked[frame] is False, else that row.
        raise NotImplementedError


# =====================================================================
# REPORTS AND VALIDATION
# =====================================================================


class SegmentReport(BaseModel):
    """Which frames one seed ended up covering, for the UI and the sidecar."""

    seed_index: int = Field(ge=0)
    seed_frame: int = Field(ge=0)
    covered: FrameRange


class FaceTrackingReport(BaseModel):
    """
    What happened to one face.

    Built from a `FaceTrack` once tracking finishes, so the numbers shown and
    the numbers recorded are the same numbers.
    """

    label: str
    frames_tracked: int = Field(ge=0)
    frames_missing: int = Field(ge=0)
    gaps: list[FrameRange] = Field(default_factory=list)
    segments: list[SegmentReport] = Field(default_factory=list)

    @computed_field
    @property
    def longest_gap_frames(self) -> int:
        """0 when the face was found on every frame."""
        return max((gap.frame_count for gap in self.gaps), default=0)


class TrackingReport(BaseModel):
    """Every face's outcome for one job."""

    # The source's frame count, so a per-face number has a denominator wherever
    # the report is read.
    frame_count: int = Field(gt=0)
    faces: list[FaceTrackingReport] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """
    Outcome of the validation stage. Any failure blocks the job, and this
    stage never warns and continues.
    """

    checks: dict[str, bool] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        """
        Derived, so a result cannot claim a pass it did not get.

        Notes:
            An empty `checks` is not a pass — `all([])` is True, which would
            let a job that was never checked sail through.
        """
        return bool(self.checks) and all(self.checks.values())
