"""
Face Tracking.

Written for this project — minicut found shot boundaries and never looked at
a face, so there is nothing to port.

Two ways to make a track, and the first is the yardstick for the second:

- **`track_every_frame`** — one face, the whole frame, every frame. No seeds,
  no choosing. Deliberately the least clever thing that produces a real
  track, which is what makes it useful to measure against.
- **`track_from_seed`** — the face inside a box the artist drew, followed
  forwards to the end of the source and backwards to frame 0.

**Backwards is the awkward half.** A decoder only runs forwards and
MediaPipe's video mode demands timestamps that rise, so a backward run is its
own landmarker fed reversed frames on its own clock, and the frames come from
`frames_backwards`, which buys them in memory-bounded windows. It seeks, so
it needs the all-intra mezzanine — on long-GOP video a seek lands on the
wrong frame and every landmark after it is attributed to the wrong picture.

What both runs do, and must keep doing:

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
    NormalisedBox,
    Seed,
    SegmentReport,
    SourceInfo,
    TrackingReport,
)
from src.media.frames import FrameReader, frames_backwards
from src.performance.model_file import ensure_model

if TYPE_CHECKING:
    from collections.abc import Callable

# The baseline run has no seeds. Every tracked frame is attributed to seed 0,
# the implicit "the whole clip" seed, so the array contract holds — seeded_by
# is NOT_SEEDED only where nothing was found. 3.6 replaces this with real
# seed indices and the baseline becomes the one-seed case.
BASELINE_SEED = 0


class NoFaceInSeed(ValueError):
    """
    No face was found inside the box, on the frame it was drawn on.

    Its own type because it is the one tracking failure that is the *user's*
    to fix rather than the app's: the answer is to draw the box again, or on
    another frame, and the message should say that rather than read like a
    bug.
    """


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

        options = self._options(vision, mediapipe_python, config.BASELINE_FACE_LIMIT)
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

    # --- SEEDED RUNS ---

    def track_from_seed(
        self,
        source: SourceInfo,
        seed: Seed,
        label: str = "Face",
        path: Path | None = None,
        seed_index: int = 0,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> FaceTrack:
        """
        Tracks the face in a seed box, forwards and backwards from its frame.

        Args:
            source: The probed source. Its frame count is the track's length.
            seed: The box, and the frame it was drawn on.
            label: What to call this face.
            path: **The mezzanine.** The backward run seeks, and a seek is
                only exact on an all-intra file. Passing a long-GOP source
                here puts landmarks on the wrong frames, silently.
            seed_index: Which of the face's seeds this is, recorded per frame
                so the timeline can show where each stretch came from.
            on_progress: Called with (frames done, frames total).

        Returns:
            A FaceTrack exactly `source.frame_count` long.

        Raises:
            NoFaceInSeed: Nothing was found inside the box on the seed frame.
            ValueError: The seed is outside the source.

        Notes:
            **Two runs and two landmarkers.** Video mode carries state
            between frames and demands timestamps that rise, so a backward
            run cannot share a tracker with a forward one — it is its own
            landmarker, fed the frames in reverse on its own rising clock.

            The backward run starts *on* the seed frame rather than below it,
            so it begins from the same known-good detection the forward run
            did instead of guessing at frame `seed - 1`. That frame's result
            is discarded; the forward run already owns it.

            **Which face** is decided by the box on the seed frame, and by
            nearest-centroid continuity after that. The padded search region
            that makes this hold when two faces cross is 3.4 — here, two
            faces that touch can still be confused.
        """
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision

        if not 0 <= seed.frame < source.frame_count:
            raise ValueError(
                f"seed is on frame {seed.frame}, but the source has "
                f"{source.frame_count} frames"
            )

        frame_count = source.frame_count
        landmarks = np.full((frame_count, LANDMARK_COUNT, 3), np.nan, dtype=np.float32)
        tracked = np.zeros(frame_count, dtype=bool)
        seeded_by = np.full(frame_count, NOT_SEEDED, dtype=np.int16)

        rate = Fraction(source.fps_numerator, source.fps_denominator)
        options = self._options(vision, mediapipe_python, config.SEED_FACE_LIMIT)

        done = 0

        def record(frame_index: int, points: np.ndarray) -> None:
            landmarks[frame_index] = points
            tracked[frame_index] = True
            seeded_by[frame_index] = seed_index

        def step() -> None:
            nonlocal done
            done += 1
            if on_progress is not None:
                on_progress(done, frame_count)

        # --- FORWARDS, FROM THE SEED ---

        following: tuple[float, float] | None = None

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            with FrameReader.for_source(
                self.toolchain, source, path=path, start_frame=seed.frame
            ) as reader:
                for offset, frame in enumerate(reader):
                    frame_index = seed.frame + offset
                    if frame_index >= frame_count:
                        break

                    faces = landmarker.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=frame),
                        timestamp_ms(offset, rate),
                    ).face_landmarks

                    if frame_index == seed.frame:
                        chosen = face_in_box(faces, seed.box)
                        if chosen is None:
                            raise NoFaceInSeed(
                                f"no face was found inside the box on frame {seed.frame}. "
                                f"{len(faces)} face(s) were found elsewhere in the picture. "
                                f"Try drawing the box again, or seeding on another frame."
                            )
                    else:
                        chosen = face_nearest(faces, following)

                    if chosen is not None:
                        record(frame_index, chosen)
                        following = centroid(chosen)

                    step()

        # --- BACKWARDS, FROM THE SEED ---

        if seed.frame > 0:
            following = centroid(landmarks[seed.frame])

            with vision.FaceLandmarker.create_from_options(options) as landmarker:
                backwards = frames_backwards(
                    self.toolchain, source, last_frame=seed.frame, first_frame=0, path=path
                )

                for clock, (frame_index, frame) in enumerate(backwards):
                    faces = landmarker.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=frame),
                        timestamp_ms(clock, rate),
                    ).face_landmarks

                    chosen = face_nearest(faces, following)

                    # The seed frame is here only to start this tracker from
                    # the same known-good detection. The forward run owns it.
                    if frame_index == seed.frame:
                        continue

                    if chosen is not None:
                        record(frame_index, chosen)
                        following = centroid(chosen)

                    step()

        track = FaceTrack(label=label, landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)
        track.validate_shape()

        logging.info(
            f"Tracked {label!r} from the seed on frame {seed.frame}: "
            f"{int(tracked.sum())}/{frame_count} frames, {len(track.gaps())} gap(s)"
        )
        return track

    # --- THE MODEL ---

    def _options(self, vision, mediapipe_python, face_limit: int):
        """
        Landmarker options, so the two runs cannot drift apart.

        Notes:
            Built per run rather than shared: a forward and a backward
            landmarker must be separate objects, but they must be configured
            identically, and two literal blocks is how that stops being true.
        """
        return vision.FaceLandmarkerOptions(
            base_options=mediapipe_python.BaseOptions(model_asset_path=str(self._model())),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=face_limit,
            min_face_detection_confidence=config.FACE_DETECTION_CONFIDENCE,
            min_face_presence_confidence=config.FACE_PRESENCE_CONFIDENCE,
            min_tracking_confidence=config.FACE_TRACKING_CONFIDENCE,
        )

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


def centroid(points: np.ndarray) -> tuple[float, float]:
    """The middle of a set of landmarks, as fractions of the picture."""
    return float(points[:, 0].mean()), float(points[:, 1].mean())


def bounding_box(points: np.ndarray) -> NormalisedBox:
    """
    The box a set of landmarks fills.

    Notes:
        Built from the points rather than from MediaPipe's own detection box,
        so it describes the mesh that will actually be drawn. The two are
        close but not the same, and the box is compared against one a person
        drew round what they could see.
    """
    return NormalisedBox(
        left=float(points[:, 0].min()),
        top=float(points[:, 1].min()),
        right=float(points[:, 0].max()),
        bottom=float(points[:, 1].max()),
    )


def overlap(first: NormalisedBox, second: NormalisedBox) -> float:
    """
    Intersection over union of two boxes, 0.0 when they do not meet.

    Notes:
        Over union rather than over either box alone: a box drawn generously
        round a face and the face's own tight bounds should still match, but
        a box drawn round a whole group should not match one face in it
        better than the face it was aimed at.
    """
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)

    if right <= left or bottom <= top:
        return 0.0

    intersection = (right - left) * (bottom - top)
    areas = (first.right - first.left) * (first.bottom - first.top) + (
        second.right - second.left
    ) * (second.bottom - second.top)

    return intersection / (areas - intersection)


def face_in_box(faces, box: NormalisedBox) -> np.ndarray | None:
    """
    Of several detected faces, the one the seed box was drawn around.

    Args:
        faces: MediaPipe's landmark lists for this frame.
        box: What the artist drew.

    Returns:
        That face's points, or None when no face meets the box at all.

    Notes:
        Best overlap wins, and *no* overlap is None rather than the nearest
        thing — a box drawn on empty background should say so, not quietly
        return whoever happened to be closest.
    """
    best: np.ndarray | None = None
    best_overlap = 0.0

    for face in faces:
        points = points_to_array(face)
        score = overlap(bounding_box(points), box)
        if score > best_overlap:
            best, best_overlap = points, score

    return best


def face_nearest(faces, to: tuple[float, float] | None) -> np.ndarray | None:
    """
    Of several detected faces, the one closest to where the face was last.

    Returns:
        That face's points, or None when nothing was detected.

    Notes:
        Plain nearest-centroid, with no limit on how far it may jump. That is
        the honest limit of 3.3: the padded search region which makes this
        hold when two faces cross is 3.4, and until then a face passing in
        front of another can take the track with it.
    """
    if not faces:
        return None

    if to is None:
        return points_to_array(faces[0])

    return min(
        (points_to_array(face) for face in faces),
        key=lambda points: (centroid(points)[0] - to[0]) ** 2
        + (centroid(points)[1] - to[1]) ** 2,
    )


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
