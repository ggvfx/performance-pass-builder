"""
Tests for Face Tracking.

The baseline run: one face, the whole frame, every frame.

Two things are being defended here. **The track is exactly as long as the
source** — a frame that failed is a gap in a full-length track, never a
shorter track, because every later stage indexes by frame number. And **a
frame where nothing was found stays empty**: NaN, flagged, never interpolated
into a plausible-looking mesh that is simply wrong.

The clip-based tests need `tests/media/one_face_medium.mp4` and a cached
model, and skip without either, so a fresh clone still runs its suite.
"""

from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from src.core import config
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import LANDMARK_COUNT, NOT_SEEDED, FaceTrack, NormalisedBox, Seed
from src.media.probe import SourceProbe
from src.performance import model_file
from src.performance.tracking import (
    BASELINE_SEED,
    FaceTracker,
    NoFaceInSeed,
    points_to_array,
    report_for,
    timestamp_ms,
)


# Round the face on this clip, drawn generously the way a person would.
SEED_BOX = NormalisedBox(left=0.40, top=0.18, right=0.66, bottom=0.68)


@pytest.fixture(scope="session")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="session")
def tracker(toolchain, ffmpeg_available) -> FaceTracker:
    """
    A tracker, skipping when the model is not already cached.

    Notes:
        Never downloads. A test suite that reaches for the network is a test
        suite that fails on a train — the real download is 4.11's job.
    """
    if not ffmpeg_available:
        pytest.skip("ffmpeg is not installed")

    if not model_file.is_valid(model_file.model_path()):
        pytest.skip(
            f"the Face Landmarker model is not cached at {model_file.model_path()}. "
            f"Run the app once, or call ensure_model()"
        )

    return FaceTracker(toolchain, model_path=model_file.model_path())


@pytest.fixture(scope="session")
def one_face_source(toolchain, one_face):
    return SourceProbe(toolchain).probe(one_face)


@pytest.fixture(scope="session")
def one_face_mezzanine(toolchain, one_face_source, tmp_path_factory) -> Path:
    """
    An all-intra copy, because the backward run seeks.

    Built once. It is the same encode every pass would do, and doing it per
    test would dominate the file.
    """
    from src.media.mezzanine import MezzanineBuilder

    return MezzanineBuilder(toolchain).build(
        one_face_source, tmp_path_factory.mktemp("mezzanine") / "one_face.mov"
    )


@pytest.fixture(scope="session")
def two_faces(toolchain, one_face, tmp_path_factory):
    """
    A two-face clip, built from the one-face one side by side.

    Real two-person footage is still wanted — see WANTED.md — and this is
    not a substitute for it: the faces never move or cross. What it does
    prove is that a seed picks one face out of several and the track stays
    on it, which is the part that can be tested without waiting for footage.
    """
    from src.media.mezzanine import MezzanineBuilder
    from src.media.probe import SourceProbe

    directory = tmp_path_factory.mktemp("two_faces")
    doubled = directory / "two_faces.mp4"

    toolchain.run_ffmpeg([
        "-y", "-i", str(one_face), "-i", str(one_face),
        "-filter_complex",
        "[0:v]scale=960:540[l];[1:v]scale=960:540[r];[l][r]hstack=inputs=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(doubled),
    ])

    source = SourceProbe(toolchain).probe(doubled)
    return source, MezzanineBuilder(toolchain).build(source, directory / "m.mov")


@pytest.fixture(scope="session")
def one_face_track(tracker, one_face_source) -> FaceTrack:
    """
    The baseline track of the real clip, run once for the whole session.

    Tracking 240 frames costs about three seconds. Six tests asking the same
    question of the same clip should ask it once — a slow suite is a suite
    that stops being run.
    """
    return tracker.track_every_frame(one_face_source, label="Scientist")


def a_track(frame_count=10, missing=()) -> FaceTrack:
    """A valid track with the named frames missing."""
    landmarks = np.zeros((frame_count, LANDMARK_COUNT, 3), dtype=np.float32)
    tracked = np.ones(frame_count, dtype=bool)
    seeded_by = np.zeros(frame_count, dtype=np.int16)

    for frame in missing:
        landmarks[frame] = np.nan
        tracked[frame] = False
        seeded_by[frame] = NOT_SEEDED

    return FaceTrack(label="Face", landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)


# --- TIMESTAMPS ---


def test_timestamps_rise_strictly_at_an_awkward_rate():
    """
    MediaPipe's video mode rejects a timestamp that does not rise, so at
    24000/1001 this is the difference between a track and an exception.
    """
    rate = Fraction(24000, 1001)
    stamps = [timestamp_ms(frame, rate) for frame in range(500)]

    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:]))


def test_timestamps_rise_strictly_at_every_rate_the_app_accepts():
    for numerator, denominator in ((24, 1), (25, 1), (24000, 1001), (30000, 1001), (60, 1)):
        rate = Fraction(numerator, denominator)
        stamps = [timestamp_ms(frame, rate) for frame in range(200)]

        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"{numerator}/{denominator}"


def test_a_timestamp_is_the_frame_position_in_milliseconds():
    assert timestamp_ms(0, Fraction(24, 1)) == 0
    assert timestamp_ms(24, Fraction(24, 1)) == 1000
    assert timestamp_ms(12, Fraction(24, 1)) == 500


def test_timestamps_use_the_exact_rate_rather_than_a_rounded_one():
    """
    One second of 24000/1001 is 1001 ms, not 1000. Rounding 23.976 drifts,
    and the whole project exists to not do that.
    """
    assert timestamp_ms(24, Fraction(24000, 1001)) == 1001


# --- LANDMARKS ---


def test_points_become_the_array_the_contract_asks_for():
    class Point:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    points = [Point(0.1 * i, 0.2 * i, 0.3 * i) for i in range(LANDMARK_COUNT)]
    array = points_to_array(points)

    assert array.shape == (LANDMARK_COUNT, 3)
    assert array.dtype == np.float32
    assert array[1].tolist() == pytest.approx([0.1, 0.2, 0.3])


# --- REPORTING ---


def test_a_report_counts_what_the_track_actually_holds():
    """
    Built from the arrays, so the numbers shown and the numbers recorded
    cannot drift apart.
    """
    report = report_for([a_track(frame_count=20, missing=[4, 5, 12])], 20).faces[0]

    assert report.frames_tracked == 17
    assert report.frames_missing == 3
    assert report.frames_tracked + report.frames_missing == 20


def test_a_report_names_the_gaps_and_the_longest():
    report = report_for([a_track(frame_count=20, missing=[4, 5, 6, 12])], 20).faces[0]

    assert [(g.start_frame, g.end_frame) for g in report.gaps] == [(4, 6), (12, 12)]
    assert report.longest_gap_frames == 3


def test_a_clean_track_reports_no_gap():
    report = report_for([a_track(frame_count=20)], 20).faces[0]

    assert report.gaps == []
    assert report.longest_gap_frames == 0


def test_a_report_carries_the_denominator():
    """A per-face number is meaningless without the length it is out of."""
    assert report_for([a_track(frame_count=20)], 20).frame_count == 20


def test_every_face_gets_its_own_row():
    tracks = [a_track(frame_count=10), a_track(frame_count=10, missing=[1])]
    tracks[1].label = "Second"

    report = report_for(tracks, 10)

    assert [face.label for face in report.faces] == ["Face", "Second"]
    assert [face.frames_missing for face in report.faces] == [0, 1]


# --- THE REAL THING ---


def test_the_baseline_tracks_a_real_face_on_every_frame(one_face_source, one_face_track):
    """
    The task itself. Not "it ran" — it found the face on all 240 frames of a
    frontal, evenly lit medium shot, which is the easiest footage there is
    and therefore the floor rather than an achievement.
    """
    track = one_face_track

    print(f"tracked {int(track.tracked.sum())}/{one_face_source.frame_count}")
    assert track.frame_count == one_face_source.frame_count
    assert track.tracked.all(), f"missed {track.gaps()}"
    assert track.label == "Scientist"


def test_a_real_track_satisfies_the_array_contract(one_face_track):
    """The tracker builds the arrays, so it is the thing that has to get it right."""
    one_face_track.validate_shape()  # raises if not


def test_landmarks_come_back_as_fractions_of_the_picture(one_face_track):
    """
    Not pixels. It is what lets a track made against the mezzanine and one
    made against the source be the same numbers.
    """
    points = one_face_track.landmarks_on(0)

    assert 0.0 <= points[:, 0].min() and points[:, 0].max() <= 1.0
    assert 0.0 <= points[:, 1].min() and points[:, 1].max() <= 1.0


def test_the_landmarks_are_where_the_face_is(one_face_track):
    """
    A track can be full length, correctly shaped and still be nonsense. The
    face in this clip is centred and in the upper half, so points clustered
    in a corner would mean something is wrong that no shape check sees.
    """
    points = one_face_track.landmarks_on(120)

    print(f"x {points[:, 0].min():.2f}-{points[:, 0].max():.2f}")
    assert 0.3 < float(points[:, 0].mean()) < 0.7, "the face is not near the middle"
    assert 0.1 < float(points[:, 1].mean()) < 0.7, "the face is not in the upper half"


def test_progress_is_reported_frame_by_frame(tracker, clips, toolchain):
    """
    A 4K source takes long enough that silence looks like a hang.

    Run against a short generated clip rather than the real one: this is
    about the callback, not about faces.
    """
    source = SourceProbe(toolchain).probe(clips["film24"])
    seen = []

    tracker.track_every_frame(source, on_progress=lambda done, _total: seen.append(done))

    assert seen[0] == 1
    assert seen[-1] == source.frame_count
    assert len(seen) == source.frame_count


def test_every_tracked_frame_is_attributed_to_the_baseline_seed(one_face_source, one_face_track):
    """
    The baseline has no seeds, but the contract still needs every tracked
    frame to name one. 3.6 replaces this with real seed indices.
    """
    track = one_face_track

    assert (track.seeded_by[track.tracked] == BASELINE_SEED).all()

    seed_index, covered = track.segments()[0]
    assert len(track.segments()) == 1, "one unbroken run, so one segment"
    assert seed_index == BASELINE_SEED
    assert (covered.start_frame, covered.end_frame) == (0, one_face_source.frame_count - 1)


# --- SEEDED RUNS ---


def test_a_seeded_track_covers_the_whole_source(tracker, one_face_source, one_face_mezzanine):
    """
    Forward from the seed to the end, backward from it to frame 0. A seed in
    the middle does not make a half-length track.
    """
    track = tracker.track_from_seed(
        one_face_source, Seed(frame=120, box=SEED_BOX), label="Scientist",
        path=one_face_mezzanine,
    )

    print(f"tracked {int(track.tracked.sum())}/{one_face_source.frame_count}")
    assert track.frame_count == one_face_source.frame_count
    assert track.tracked.all(), f"missed {track.gaps()}"


def test_the_backward_half_is_as_good_as_the_forward_half(
    tracker, one_face_source, one_face_mezzanine, one_face_track
):
    """
    The real question about reading a video backwards. If the reversed frames
    were misaligned, the half tracked backwards would disagree with a plain
    forward run far more than the half tracked forwards does.
    """
    seeded = tracker.track_from_seed(
        one_face_source, Seed(frame=120, box=SEED_BOX), path=one_face_mezzanine
    )

    difference = np.abs(seeded.landmarks - one_face_track.landmarks)
    backward = float(difference[:120].mean()) * one_face_source.width
    forward = float(difference[120:].mean()) * one_face_source.width

    print(f"backward {backward:.2f}px vs forward {forward:.2f}px from the baseline")
    assert backward < forward * 3, "the backward half disagrees far more than the forward half"
    assert backward < 10, "the backward half is nowhere near the baseline track"


def test_a_seeded_track_records_which_seed_found_each_frame(
    tracker, one_face_source, one_face_mezzanine
):
    """What lets the timeline show where a stretch of track came from."""
    track = tracker.track_from_seed(
        one_face_source, Seed(frame=60, box=SEED_BOX), path=one_face_mezzanine, seed_index=2
    )

    assert (track.seeded_by[track.tracked] == 2).all()


def test_a_seed_on_frame_zero_needs_no_backward_run(tracker, one_face_source, one_face_mezzanine):
    """The edge case where the backward range would be empty."""
    track = tracker.track_from_seed(
        one_face_source, Seed(frame=0, box=SEED_BOX), path=one_face_mezzanine
    )

    assert track.frame_count == one_face_source.frame_count
    assert track.tracked[0]


def test_a_box_with_no_face_in_it_says_so(tracker, one_face_source, one_face_mezzanine):
    """
    The user's failure to fix rather than the app's, so it has its own
    exception and a message about drawing the box again.
    """
    corner = Seed(frame=120, box=NormalisedBox(left=0.01, top=0.80, right=0.15, bottom=0.98))

    with pytest.raises(NoFaceInSeed, match="drawing the box again"):
        tracker.track_from_seed(one_face_source, corner, path=one_face_mezzanine)


def test_a_seed_outside_the_source_is_refused(tracker, one_face_source, one_face_mezzanine):
    beyond = Seed(frame=one_face_source.frame_count, box=SEED_BOX)

    with pytest.raises(ValueError, match="frames"):
        tracker.track_from_seed(one_face_source, beyond, path=one_face_mezzanine)


def test_a_seeded_run_reports_progress_over_the_whole_source(
    tracker, one_face_source, one_face_mezzanine
):
    """Both halves count toward the total, or the bar stops at the seed."""
    seen = []

    tracker.track_from_seed(
        one_face_source,
        Seed(frame=120, box=SEED_BOX),
        path=one_face_mezzanine,
        on_progress=lambda done, _total: seen.append(done),
    )

    assert seen[-1] == one_face_source.frame_count


# --- TWO FACES ---


def test_the_seeded_face_is_the_one_tracked(tracker, two_faces):
    """
    What the search region is for. Two identical faces, one seeded: the
    track must stay on the one the box was drawn round for every frame, not
    wander to the other.
    """
    source, mezzanine = two_faces
    right = Seed(frame=0, box=NormalisedBox(left=0.70, top=0.18, right=0.83, bottom=0.68))

    track = tracker.track_from_seed(source, right, label="Right", path=mezzanine)

    middles = [
        float(track.landmarks_on(frame)[:, 0].mean())
        for frame in range(source.frame_count)
        if track.tracked[frame]
    ]
    print(f"centroid x ran {min(middles):.3f} to {max(middles):.3f}")
    assert track.tracked.all()
    assert all(x > 0.5 for x in middles), "the track crossed to the other face"


def test_seeding_the_other_face_tracks_the_other_face(tracker, two_faces):
    """The mirror of the above, so the first is not passing by luck."""
    source, mezzanine = two_faces
    left = Seed(frame=0, box=NormalisedBox(left=0.17, top=0.18, right=0.30, bottom=0.68))

    track = tracker.track_from_seed(source, left, label="Left", path=mezzanine)

    middles = [
        float(track.landmarks_on(frame)[:, 0].mean())
        for frame in range(source.frame_count)
        if track.tracked[frame]
    ]
    assert all(x < 0.5 for x in middles), "the track crossed to the other face"


# --- NO FACE ---


def test_a_clip_with_no_face_is_a_full_length_track_of_nothing(tracker, toolchain, clips):
    """
    The generated clips are colour bars. Nothing is found, and the result
    must still be a track exactly as long as the source — not an exception,
    not an empty array, and not a shorter track.
    """
    source = SourceProbe(toolchain).probe(clips["film24"])
    track = tracker.track_every_frame(source)

    assert track.frame_count == source.frame_count
    assert not track.tracked.any()
    assert np.isnan(track.landmarks).all()
    assert (track.seeded_by == NOT_SEEDED).all()
    track.validate_shape()


def test_a_face_found_nowhere_reports_one_whole_gap(tracker, toolchain, clips):
    """"Found nothing" and "found everything" must not look alike."""
    source = SourceProbe(toolchain).probe(clips["film24"])
    report = report_for([tracker.track_every_frame(source)], source.frame_count).faces[0]

    assert report.frames_tracked == 0
    assert report.longest_gap_frames == source.frame_count
    assert report.segments == [], "nothing was tracked, so no seed covered anything"


# --- WHEN THE LENGTHS DISAGREE ---


def test_a_source_claiming_more_frames_than_it_has_is_refused(tracker, toolchain, clips):
    """
    Every later stage indexes by frame number. A track quietly shorter than
    the source would put the mesh on the wrong frame from the gap onward, and
    nothing downstream could tell.
    """
    source = SourceProbe(toolchain).probe(clips["film24"])
    lying = source.model_copy(update={"frame_count": source.frame_count + 10})

    with pytest.raises(ValueError, match="would point at the wrong picture"):
        tracker.track_every_frame(lying)


def test_the_confidences_a_track_was_made_with_are_recorded_settings():
    """
    Not buried in MediaPipe's defaults. A track that found nothing is read
    very differently if the threshold was 0.9.
    """
    for name in (
        "FACE_DETECTION_CONFIDENCE",
        "FACE_PRESENCE_CONFIDENCE",
        "FACE_TRACKING_CONFIDENCE",
    ):
        assert 0.0 < getattr(config, name) <= 1.0, name
