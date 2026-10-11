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

The arithmetic of *where* a face is — the search region, mapping landmarks
out of a crop, choosing between detections — is in `face_geometry.py`. It
needs no model and no footage, so it is testable instantly and exhaustively,
which this is not.

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
    Face,
    FaceTrack,
    FaceTrackingReport,
    NormalisedBox,
    Seed,
    SegmentReport,
    Selection,
    SourceInfo,
    TrackingReport,
)
from src.media.frames import FrameReader, frames_backwards
from src.performance.face_geometry import (
    bounding_box,
    centroid,
    face_in_box,
    face_nearest,
    points_to_array,
    search_region,
    to_full_frame,
)
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


class _Fill:
    """
    One face's arrays while they are being filled, and where it was last.

    Several segments write into the same three arrays — a backward run and
    one forward run per seed — so the arrays, the last known position and
    the region to search next belong together rather than being threaded
    through every call as arguments.

    Private because it is scaffolding for building a `FaceTrack`, not
    something to hand anybody. What comes out is the track.
    """

    def __init__(self, source: SourceInfo, search_padding: float | None):
        self.source = source
        self.search_padding = search_padding

        # NaN throughout, so any frame no segment reaches is a gap by
        # default. Zeros would make a missed frame look like a face
        # collapsed into the top-left corner.
        self.landmarks = np.full(
            (source.frame_count, LANDMARK_COUNT, 3), np.nan, dtype=np.float32
        )
        self.tracked = np.zeros(source.frame_count, dtype=bool)
        self.seeded_by = np.full(source.frame_count, NOT_SEEDED, dtype=np.int16)

        self.following: tuple[float, float] | None = None
        self.region: NormalisedBox | None = None

    def aim_at(self, box: NormalisedBox) -> None:
        """Points the search region at a box, or at the whole frame."""
        self.region = (
            None
            if self.search_padding is None
            else search_region(
                box, self.source.width, self.source.height, self.search_padding
            )
        )

    def record(self, frame_index: int, points: np.ndarray, seed_index: int) -> None:
        """Writes one frame's result and remembers where it was."""
        self.landmarks[frame_index] = points
        self.tracked[frame_index] = True
        self.seeded_by[frame_index] = seed_index
        self.following = centroid(points)

    def look(self, landmarker, mp, frame, clock: int, rate: Fraction, choose):
        """
        One frame: crop to the region, detect, map back to the picture, choose.

        Notes:
            The region moves to whatever was chosen, so the next frame looks
            where this one found something. When nothing is found it stays
            put — a blink or a blur recovers, and a face that left and came
            back elsewhere wants another seed.
        """
        crop = (
            self.region.to_pixels(self.source.width, self.source.height)
            if self.region is not None
            else None
        )
        picture = frame if crop is None else frame[crop[1] : crop[3], crop[0] : crop[2]]

        found = landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(picture)),
            timestamp_ms(clock, rate),
        ).face_landmarks

        candidates = [points_to_array(face) for face in found]
        if crop is not None:
            candidates = [
                to_full_frame(points, crop, self.source.width, self.source.height)
                for points in candidates
            ]

        chosen = choose(candidates)

        if chosen is not None:
            self.aim_at(bounding_box(chosen))

        return chosen

    def to_track(self, label: str) -> FaceTrack:
        """The finished track. Not validated here — the caller does that."""
        return FaceTrack(
            label=label,
            landmarks=self.landmarks,
            tracked=self.tracked,
            seeded_by=self.seeded_by,
        )


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
        search_padding: float | None = config.FACE_SEARCH_PADDING,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> FaceTrack:
        """
        Tracks the face in one seed box, forwards and backwards from its frame.

        The one-seed case of `track_face`, which is the general shape. Kept
        as its own call because one seed is what most shots need and
        building a `Face` to ask for it would be ceremony.

        Args:
            source: The probed source. Its frame count is the track's length.
            seed: The box, and the frame it was drawn on.
            label: What to call this face.
            path: **The mezzanine.** The backward run seeks, and a seek is
                only exact on an all-intra file.
            seed_index: Which of the face's seeds this is, recorded per frame.
            search_padding: How far around the last known position to look.
                None searches the whole frame — see `track_face`.
            on_progress: Called with (frames done, frames total).

        Raises:
            NoFaceInSeed: Nothing was found inside the box on the seed frame.
            ValueError: The seed is outside the source.
        """
        return self.track_face(
            source,
            Face(label=label, seeds=[seed]),
            path=path,
            first_seed_index=seed_index,
            search_padding=search_padding,
            on_progress=on_progress,
        )

    def track_face(
        self,
        source: SourceInfo,
        face: Face,
        path: Path | None = None,
        first_seed_index: int = 0,
        search_padding: float | None = config.FACE_SEARCH_PADDING,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> FaceTrack:
        """
        Tracks one face from all of its seeds, in segments between them.

        Args:
            source: The probed source. Its frame count is the track's length.
            face: The label and its seeds, which the model keeps in frame
                order with no frame used twice.
            path: **The mezzanine.** Backward runs seek.
            first_seed_index: What to call the first seed in `seeded_by`.
                Only interesting to `track_from_seed`, which may be reporting
                a seed from the middle of a larger list.
            search_padding: How far around the last known position to look,
                as a fraction of the face's own size. None searches the whole
                frame every time.
            on_progress: Called with (frames done, frames total).

        Returns:
            A FaceTrack exactly `source.frame_count` long.

        Raises:
            NoFaceInSeed: Nothing was found inside the first seed's box.
            ValueError: A seed is outside the source.

        Notes:
            **Re-seeding is the normal way to work, not a recovery path.**
            Tracking until a face turns away or a wipe crosses it, then
            marking it again past the break, is how a shot gets done. So the
            seeds divide the source into segments: backward from the first
            to frame 0, then forward from each seed to the frame before the
            next, and from the last to the end.

            **Each segment is its own landmarker.** Starting fresh at a seed
            is the whole point of re-seeding — carrying state across one
            would carry in whatever went wrong before it.

            **A segment stops at the next seed rather than running on.** It
            would be simpler to track each seed to the end of the source and
            keep the parts wanted, and it would cost a full decode per seed.

            Only the *first* seed can raise. A later one marks a face the
            artist can see, so if the detector disagrees there, the honest
            result is a gap in that segment — not the loss of the whole
            track behind it.
        """
        for seed in face.seeds:
            if not 0 <= seed.frame < source.frame_count:
                raise ValueError(
                    f"{face.label!r} has a seed on frame {seed.frame}, but the "
                    f"source has {source.frame_count} frames"
                )

        fill = _Fill(source, search_padding)
        rate = Fraction(source.fps_numerator, source.fps_denominator)
        done = 0

        def step() -> None:
            nonlocal done
            done += 1
            if on_progress is not None:
                on_progress(done, source.frame_count)

        first = face.seeds[0]

        # --- FORWARD, SEED BY SEED ---

        for offset, seed in enumerate(face.seeds):
            index = first_seed_index + offset
            last = (
                face.seeds[offset + 1].frame - 1
                if offset + 1 < len(face.seeds)
                else source.frame_count - 1
            )
            if last < seed.frame:
                continue  # two seeds on adjacent frames; the later one wins

            self._forward(source, path, fill, seed, index, last, rate, step, offset == 0)

        # --- BACKWARD, FROM THE FIRST SEED ---

        if first.frame > 0:
            self._backward(source, path, fill, first, first_seed_index, rate, step)

        track = fill.to_track(face.label)
        track.validate_shape()

        logging.info(
            f"Tracked {face.label!r} from {len(face.seeds)} seed(s): "
            f"{int(track.tracked.sum())}/{source.frame_count} frames, "
            f"{len(track.gaps())} gap(s)"
        )
        return track

    # --- ONE SEGMENT AT A TIME ---

    def _forward(
        self,
        source: SourceInfo,
        path: Path | None,
        fill: "_Fill",
        seed: Seed,
        seed_index: int,
        last_frame: int,
        rate: Fraction,
        step: "Callable[[], None]",
        may_raise: bool,
    ) -> None:
        """
        One segment: from a seed's frame to `last_frame`, inclusive.

        Args:
            may_raise: Whether a seed box with nothing in it is fatal. True
                for the first seed only — see `track_face`.
        """
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision

        options = self._options(vision, mediapipe_python, config.SEED_FACE_LIMIT)
        fill.aim_at(seed.box)
        fill.following = None

        wanted = last_frame - seed.frame + 1

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            with FrameReader.for_source(
                self.toolchain, source, path=path, start_frame=seed.frame, max_frames=wanted
            ) as reader:
                for offset, frame in enumerate(reader):
                    frame_index = seed.frame + offset

                    if frame_index == seed.frame:
                        chosen = fill.look(
                            landmarker, mp, frame, offset, rate,
                            lambda found: face_in_box(found, seed.box),
                        )
                        if chosen is None and may_raise:
                            raise NoFaceInSeed(
                                f"no face was found inside the box on frame {seed.frame}. "
                                f"Try drawing the box again, or seeding on another frame."
                            )
                    else:
                        chosen = fill.look(
                            landmarker, mp, frame, offset, rate,
                            lambda found: face_nearest(found, fill.following),
                        )

                    if chosen is not None:
                        fill.record(frame_index, chosen, seed_index)

                    step()

    def _backward(
        self,
        source: SourceInfo,
        path: Path | None,
        fill: "_Fill",
        seed: Seed,
        seed_index: int,
        rate: Fraction,
        step: "Callable[[], None]",
    ) -> None:
        """
        From the first seed's frame down to frame 0.

        Notes:
            Starts *on* the seed frame rather than below it, so it begins
            from the same known-good detection the forward run did instead
            of guessing at frame `seed - 1`. That frame's result is thrown
            away; the forward run already owns it.
        """
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision

        options = self._options(vision, mediapipe_python, config.SEED_FACE_LIMIT)

        if fill.tracked[seed.frame]:
            fill.following = centroid(fill.landmarks[seed.frame])
            fill.aim_at(bounding_box(fill.landmarks[seed.frame]))
        else:
            fill.following = None
            fill.aim_at(seed.box)

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            backwards = frames_backwards(
                self.toolchain, source, last_frame=seed.frame, first_frame=0, path=path
            )

            for clock, (frame_index, frame) in enumerate(backwards):
                chosen = fill.look(
                    landmarker, mp, frame, clock, rate,
                    lambda found: face_nearest(found, fill.following),
                )

                if frame_index == seed.frame:
                    continue

                if chosen is not None:
                    fill.record(frame_index, chosen, seed_index)

                step()

    # --- A WHOLE SELECTION ---

    def check_seeds(
        self, source: SourceInfo, selection: Selection, path: Path | None = None
    ) -> list[str]:
        """
        Whether every seed box actually has a face in it, before tracking any.

        Args:
            source: The probed source.
            selection: Every face the artist chose.
            path: **The mezzanine.** This seeks to each seed frame.

        Returns:
            One message per bad seed, empty when they are all fine.

        Notes:
            **A pre-flight, and the reason is time.** Tracking three faces
            through a two-minute source takes minutes; discovering the third
            box was drawn on a shoulder at the end of that is a poor way to
            spend them. One detection per seed answers it in under a second,
            and the caller can report every bad box at once rather than the
            first one.
        """
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision

        options = self._options(vision, mediapipe_python, config.SEED_FACE_LIMIT)
        problems: list[str] = []

        # IMAGE mode, not VIDEO: these frames are scattered through the
        # source and have nothing to do with each other, so carrying tracker
        # state between them would be meaningless and the rising-timestamp
        # rule would be in the way.
        options.running_mode = vision.RunningMode.IMAGE

        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            for face in selection.faces:
                for index, seed in enumerate(face.seeds):
                    region = search_region(
                        seed.box, source.width, source.height, config.FACE_SEARCH_PADDING
                    )
                    crop = region.to_pixels(source.width, source.height)

                    with FrameReader.for_source(
                        self.toolchain, source, path=path, start_frame=seed.frame, max_frames=1
                    ) as reader:
                        frame = reader.read()

                    if frame is None:
                        problems.append(
                            f"{face.label!r} seed {index}: frame {seed.frame} could not be read"
                        )
                        continue

                    picture = frame[crop[1] : crop[3], crop[0] : crop[2]]
                    found = landmarker.detect(
                        mp.Image(
                            image_format=mp.ImageFormat.SRGB,
                            data=np.ascontiguousarray(picture),
                        )
                    ).face_landmarks

                    candidates = [
                        to_full_frame(
                            points_to_array(each), crop, source.width, source.height
                        )
                        for each in found
                    ]

                    if face_in_box(candidates, seed.box) is None:
                        problems.append(
                            f"{face.label!r} seed {index}: no face inside the box on "
                            f"frame {seed.frame}"
                        )

        logging.info(f"Checked {sum(len(f.seeds) for f in selection.faces)} seed(s): {len(problems)} bad")
        return problems

    def track_selection(
        self,
        source: SourceInfo,
        selection: Selection,
        path: Path | None = None,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> list[FaceTrack]:
        """
        One track per chosen face, each from its own seed.

        Args:
            source: The probed source. Its frame count is every track's length.
            selection: The faces, which the model has already checked against
                this source's length and for duplicate labels.
            path: **The mezzanine.** Backward runs seek.
            on_progress: Called with (frames done, frames total) across the
                whole job, not per face — so a three-face run fills one bar
                rather than three.

        Returns:
            A FaceTrack per face, in the selection's order.

        Raises:
            NoFaceInSeed: One or more boxes have no face in them. Every bad
                box is named, not just the first.
            ValueError: The selection was made against a different source.

        Notes:
            **A landmarker per face, never one shared.** Two people in frame
            must not be able to become each other, and MediaPipe's video mode
            carries state — a shared tracker would carry it between faces.

            **Every seed is checked before any tracking starts.** See
            `check_seeds`: failing after four minutes of work, on a box that
            could have been rejected in a second, is the kind of thing that
            makes a tool feel hostile.

            **Each face costs a full decode of the source.** Three faces,
            three passes. Sharing one decode between several landmarkers
            would be faster and is not done, because the faces are seeded on
            different frames and run in different directions — the
            bookkeeping to share a pass between them is a worse thing to own
            than the extra minutes, until something says otherwise.
        """
        if selection.source_frame_count != source.frame_count:
            raise ValueError(
                f"this selection was made against {selection.source_frame_count} frames "
                f"and the source has {source.frame_count}. It belongs to a different cut."
            )

        problems = self.check_seeds(source, selection, path=path)
        if problems:
            raise NoFaceInSeed(
                "some boxes have no face in them:\n  "
                + "\n  ".join(problems)
                + "\nTry drawing them again, or seeding on another frame."
            )

        total = source.frame_count * len(selection.faces)
        done = 0

        def across_the_job(_face_done: int, _face_total: int) -> None:
            nonlocal done
            done += 1
            if on_progress is not None:
                on_progress(done, total)

        tracks = [
            self.track_face(source, face, path=path, on_progress=across_the_job)
            for face in selection.faces
        ]

        logging.info(
            f"Tracked {len(tracks)} face(s): "
            + ", ".join(f"{t.label} {int(t.tracked.sum())}/{source.frame_count}" for t in tracks)
        )
        return tracks

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
