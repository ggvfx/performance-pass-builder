"""
Face Tracking.

Written for this project — minicut found shot boundaries and never looked at
a face, so there is nothing to port.

This is **the baseline run: one face, the whole frame, every frame.** No
seeds, no search box, no choosing who to follow. That is deliberately the
least clever thing that can produce a real track, and it is what the clever
versions in 3.3 onward are measured against.

What it already does, and must keep doing:

- **A frame where no face is found is recorded, not guessed.** The landmark
  row is NaN and `tracked` is False. Nothing is interpolated across a gap,
  because a mesh invented over a missing face is worse than no mesh: it looks
  like a tracked face and it is wrong.
- **The track is exactly as long as the source.** Non-negotiable 2. A frame
  that failed is a gap in a full-length track, never a shorter track.
- **Frames come through `FrameReader`**, the same ffmpeg path as everything
  else, so the frame this module calls 40 is the frame every other stage
  calls 40.

Notes:
    MediaPipe is imported where it is used rather than at module scope. There
    is no wheel for Intel macOS (ARCHITECTURE.md open question 6), and an
    import error at startup would take the server down before the dependency
    panel could render the message explaining exactly that.
"""

import logging
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from src.core import config
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import (
    LANDMARK_COUNT,
    NOT_SEEDED,
    FaceTrack,
    FaceTrackingReport,
    SegmentReport,
    SourceInfo,
    TrackingReport,
)
from src.media.frames import FrameReader
from src.performance.model_file import ensure_model

if TYPE_CHECKING:
    from collections.abc import Callable

# The baseline run has no seeds. Every tracked frame is attributed to seed 0,
# the implicit "the whole clip" seed, so the array contract holds — seeded_by
# is NOT_SEEDED only where nothing was found. 3.6 replaces this with real
# seed indices and the baseline becomes the one-seed case.
BASELINE_SEED = 0


class FaceTracker:
    """
    Runs the MediaPipe Face Landmarker over a source.

    Holds the toolchain so frames are decoded by the same binaries that
    probed the source, and resolves the model once rather than per call.
    """

    def __init__(self, toolchain: MediaToolchain, model_path: Path | None = None):
        """
        Args:
            toolchain: For decoding frames.
            model_path: An already-verified model. Left None, the first track
                fetches and verifies it — which may download 3.6 MB.
        """
        self.toolchain = toolchain
        self.model_path = model_path

    # --- THE BASELINE RUN ---

    def track_every_frame(
        self,
        source: SourceInfo,
        label: str = "Face",
        path: Path | None = None,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> FaceTrack:
        """
        Finds one face on every frame of a source, searching the whole frame.

        Args:
            source: The probed source. Its frame count is the track's length
                and is not negotiable.
            label: What to call this face in reports and layers.
            path: Decode this instead of `source.path` — the mezzanine, when
                one has been prepared. The geometry still comes from `source`.
            on_progress: Called with (frames done, frames total).

        Returns:
            A FaceTrack exactly `source.frame_count` long, already checked
            against the array contract.

        Raises:
            ModelUnavailable: The model is not here and could not be fetched.
            ValueError: The decode produced a different number of frames than
                the source claims, which would make every frame index a lie.

        Notes:
            **MediaPipe's VIDEO mode, not IMAGE mode.** Video mode carries
            state between frames, which is both steadier and far quicker than
            detecting from scratch 240 times. It requires timestamps that
            strictly rise, which is why they are derived from the exact
            rational rate rather than a rounded float.
        """
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision

        frame_count = source.frame_count

        # NaN throughout, so any frame the tracker never fills is a gap by
        # default. Starting from zeros would make a missed frame look like a
        # face collapsed into the top-left corner.
        landmarks = np.full((frame_count, LANDMARK_COUNT, 3), np.nan, dtype=np.float32)
        tracked = np.zeros(frame_count, dtype=bool)
        seeded_by = np.full(frame_count, NOT_SEEDED, dtype=np.int16)

        options = vision.FaceLandmarkerOptions(
            base_options=mediapipe_python.BaseOptions(model_asset_path=str(self._model())),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=config.BASELINE_FACE_LIMIT,
            min_face_detection_confidence=config.FACE_DETECTION_CONFIDENCE,
            min_face_presence_confidence=config.FACE_PRESENCE_CONFIDENCE,
            min_tracking_confidence=config.FACE_TRACKING_CONFIDENCE,
        )

        rate = Fraction(source.fps_numerator, source.fps_denominator)
        decoded = 0

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            with FrameReader.for_source(self.toolchain, source, path=path) as reader:
                for frame_index, frame in enumerate(reader):
                    if frame_index >= frame_count:
                        # The probe is the authority on length; a decoder that
                        # hands over more is stopped rather than trusted.
                        decoded = frame_index + 1
                        break

                    result = landmarker.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=frame),
                        timestamp_ms(frame_index, rate),
                    )

                    if result.face_landmarks:
                        landmarks[frame_index] = points_to_array(result.face_landmarks[0])
                        tracked[frame_index] = True
                        seeded_by[frame_index] = BASELINE_SEED

                    decoded = frame_index + 1
                    if on_progress is not None:
                        on_progress(decoded, frame_count)

        if decoded != frame_count:
            raise ValueError(
                f"decoded {decoded} frames from {(path or source.path).name} but the "
                f"source reports {frame_count}. Every frame index after the difference "
                f"would point at the wrong picture."
            )

        track = FaceTrack(
            label=label, landmarks=landmarks, tracked=tracked, seeded_by=seeded_by
        )
        track.validate_shape()

        found = int(tracked.sum())
        logging.info(
            f"Tracked {label!r} on {found}/{frame_count} frames "
            f"({len(track.gaps())} gap(s))"
        )
        return track

    # --- THE MODEL ---

    def _model(self) -> Path:
        """
        The verified model, fetched on first use and remembered after.

        Notes:
            Cached on the instance rather than re-verified per call: one
            tracker tracking four faces should hash the file once.
        """
        if self.model_path is None:
            self.model_path = ensure_model()

        return self.model_path


# --- CONVERSIONS ---


def timestamp_ms(frame_index: int, rate: Fraction) -> int:
    """
    A frame's position in milliseconds, for MediaPipe's video mode.

    Notes:
        Derived from the exact rational rate. At 24000/1001 a rounded 23.976
        drifts by a frame over a few minutes, and video mode cares: a
        timestamp that fails to rise is rejected outright.

        Integer division of exact rationals, so frame 1 at 24000/1001 is 41 ms
        and not 41.708333. Two consecutive frames can only collide above
        1000 fps, which no source this app accepts comes near.
    """
    return int(Fraction(frame_index, 1) / rate * 1000)


def points_to_array(points) -> np.ndarray:
    """
    MediaPipe's landmark list as a (LANDMARK_COUNT, 3) float32 array.

    Notes:
        x and y are already fractions of the picture, which is what the array
        contract wants — nothing here multiplies by a width, so a track made
        against the mezzanine and one made against the source are the same
        numbers.

        z is MediaPipe's own relative depth. It is kept because it costs
        nothing and the mesh renderer may want it, and it has **nothing** to
        do with the depth pass.
    """
    return np.array([(point.x, point.y, point.z) for point in points], dtype=np.float32)


# --- REPORTING ---


def report_for(tracks: list[FaceTrack], frame_count: int) -> TrackingReport:
    """
    What happened to every face, for the UI and the sidecar.

    Notes:
        Built from the tracks themselves, so the numbers shown and the
        numbers recorded cannot disagree — there is no second count kept
        alongside the arrays.
    """
    return TrackingReport(
        frame_count=frame_count,
        faces=[
            FaceTrackingReport(
                label=track.label,
                frames_tracked=int(track.tracked.sum()),
                frames_missing=int((~track.tracked).sum()),
                gaps=track.gaps(),
                segments=[
                    SegmentReport(
                        seed_index=seed_index,
                        seed_frame=covered.start_frame,
                        covered=covered,
                    )
                    for seed_index, covered in track.segments()
                ],
            )
            for track in tracks
        ],
    )
