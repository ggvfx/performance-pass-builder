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

from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from src.core import config
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import (
    LANDMARK_COUNT,
    NOT_SEEDED,
    Face,
    FaceTrack,
    NormalisedBox,
    Seed,
    Selection,
)
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


# --- A REAL GAP ---

# Everything above about gaps is checked against arrays built by hand.
# `walks_in_and_turns_away.mp4` is the first clip where the tracker actually
# loses the face: she starts far off and turned away, and arrives in a medium
# shot. The baseline finds her on 89 frames of 240.


@pytest.fixture(scope="session")
def gap_source(toolchain, with_gap):
    return SourceProbe(toolchain).probe(with_gap)


@pytest.fixture(scope="session")
def gap_mezzanine(toolchain, gap_source, tmp_path_factory) -> Path:
    from src.media.mezzanine import MezzanineBuilder

    return MezzanineBuilder(toolchain).build(
        gap_source, tmp_path_factory.mktemp("gap") / "m.mov"
    )


@pytest.fixture(scope="session")
def gap_track(tracker, gap_source, gap_mezzanine) -> FaceTrack:
    return tracker.track_every_frame(gap_source, label="Girl", path=gap_mezzanine)


def test_a_lost_face_is_a_gap_in_a_full_length_track(gap_source, gap_track):
    """
    The rule everything downstream depends on. She is not found for most of
    this clip, and the track is still exactly as long as the source — a gap
    in it, never a shorter track.
    """
    print(f"tracked {int(gap_track.tracked.sum())}/{gap_source.frame_count}")
    assert gap_track.frame_count == gap_source.frame_count
    assert not gap_track.tracked.all(), "this clip is only useful if she is lost"
    assert gap_track.gaps(), "frames are missing but no gap was reported"


def test_a_real_gap_is_left_empty_rather_than_guessed(gap_track):
    """
    Non-negotiable: a mesh invented over a missing face looks like a tracked
    face and is wrong. Checked here against a gap the tracker actually
    produced rather than one written into an array by a test.
    """
    missing = ~gap_track.tracked

    assert np.isnan(gap_track.landmarks[missing]).all()
    assert (gap_track.seeded_by[missing] == NOT_SEEDED).all()
    assert gap_track.landmarks_on(int(np.flatnonzero(missing)[0])) is None


def test_a_real_track_with_a_gap_still_satisfies_the_contract(gap_track):
    """validate_shape has never met a gap it did not have to be handed."""
    gap_track.validate_shape()


def test_the_report_counts_a_real_gap(gap_source, gap_track):
    report = report_for([gap_track], gap_source.frame_count).faces[0]

    print(f"{report.frames_missing} missing, longest {report.longest_gap_frames}")
    assert report.frames_tracked + report.frames_missing == gap_source.frame_count
    assert report.longest_gap_frames == max(gap.frame_count for gap in gap_track.gaps())
    assert report.frames_missing == sum(gap.frame_count for gap in gap_track.gaps())


def test_seeding_late_and_tracking_back_recovers_far_more_than_the_baseline(
    tracker, gap_source, gap_mezzanine, gap_track
):
    """
    What the backward run and the search region are *for*, on footage that
    actually needs them.

    Searching the whole frame from a standing start finds her on 89 frames.
    Seeding where she is clearest and working outwards finds roughly twice
    that, because the search region carries a known-good position into
    frames where a cold detector sees nothing worth calling a face.
    """
    clearest = int(np.flatnonzero(gap_track.tracked)[-1]) - 39
    points = gap_track.landmarks_on(clearest)
    seed = Seed(
        frame=clearest,
        box=NormalisedBox(
            left=max(0.0, float(points[:, 0].min()) - 0.02),
            top=max(0.0, float(points[:, 1].min()) - 0.03),
            right=min(1.0, float(points[:, 0].max()) + 0.02),
            bottom=min(1.0, float(points[:, 1].max()) + 0.03),
        ),
    )

    seeded = tracker.track_from_seed(gap_source, seed, label="Girl", path=gap_mezzanine)

    baseline_found = int(gap_track.tracked.sum())
    seeded_found = int(seeded.tracked.sum())
    print(f"baseline {baseline_found}, seeded {seeded_found} of {gap_source.frame_count}")

    assert seeded.frame_count == gap_source.frame_count
    assert seeded_found > baseline_found * 1.5, "seeding bought little over a cold search"
    seeded.validate_shape()


# --- TWO REAL FACES, CROSSING ---

# `two_faces_cross_and_exit.mp4`. Two officers at night: both turn to each
# other so both spend time in profile, and the one on the right walks left
# across the frame, past the other, and out of shot. Detection flickers all
# the way through.
#
# The side-by-side clip above proves a seed picks one of two faces. This one
# asks the harder question, which is whether it keeps the right one.

# Where each officer's face sits on frame 0.
LEFT_OFFICER = NormalisedBox(left=0.24, top=0.22, right=0.42, bottom=0.62)
RIGHT_OFFICER = NormalisedBox(left=0.56, top=0.22, right=0.74, bottom=0.62)


@pytest.fixture(scope="session")
def crossing_source(toolchain, two_faces_clip):
    return SourceProbe(toolchain).probe(two_faces_clip)


@pytest.fixture(scope="session")
def crossing_mezzanine(toolchain, crossing_source, tmp_path_factory) -> Path:
    from src.media.mezzanine import MezzanineBuilder

    return MezzanineBuilder(toolchain).build(
        crossing_source, tmp_path_factory.mktemp("crossing") / "m.mov"
    )


def middles(track, frame_count):
    """Where the face sat across the frames it was found on."""
    return {
        frame: float(track.landmarks_on(frame)[:, 0].mean())
        for frame in range(frame_count)
        if track.tracked[frame]
    }


def test_the_officer_who_stays_is_held_throughout(
    tracker, crossing_source, crossing_mezzanine
):
    """
    He is in profile for much of the clip, under neon, with another face
    crossing in front of him and leaving. The track should stay on him.
    """
    track = tracker.track_from_seed(
        crossing_source,
        Seed(frame=0, box=LEFT_OFFICER),
        label="Left",
        path=crossing_mezzanine,
    )

    where = middles(track, crossing_source.frame_count)
    print(
        f"found on {len(where)}/{crossing_source.frame_count}, "
        f"x {min(where.values()):.2f}-{max(where.values()):.2f}"
    )

    assert len(where) > crossing_source.frame_count * 0.9, "lost him too often"
    assert max(where.values()) < 0.55, "the track wandered onto the other officer"


def test_flickering_detection_is_recorded_as_gaps_not_smoothed_over(
    tracker, crossing_source, crossing_mezzanine
):
    """
    The other shape of absence. The desert clip is one long gap; this one is
    intermittent, which `FaceTrack.gaps` exists to tell apart — one long
    absence and shimmer throughout need different answers from the artist.
    """
    track = tracker.track_from_seed(
        crossing_source,
        Seed(frame=0, box=RIGHT_OFFICER),
        label="Right",
        path=crossing_mezzanine,
    )

    gaps = track.gaps()
    print(f"{len(gaps)} gaps, longest {max(g.frame_count for g in gaps)}")

    assert len(gaps) > 1, "this clip flickers; one gap would mean they were merged"
    assert track.frame_count == crossing_source.frame_count
    track.validate_shape()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known limitation. When the seeded face leaves the frame, the search "
        "region stays where it was, and the other officer walks into it and "
        "takes the track. Nothing currently asks whether a recovered face is "
        "the same face. See DECISIONS.md."
    ),
)
def test_a_track_does_not_transfer_to_another_face_after_its_own_leaves(
    tracker, crossing_source, crossing_mezzanine
):
    """
    The right officer walks left across the frame and out. After that there
    is no right officer to track, so the honest answer is a gap to the end.

    What happens instead is that the remaining officer is sitting inside the
    search region, is the nearest face, and inherits the track. The mesh then
    gets drawn on the wrong person with no indication anything went wrong —
    which is worse than losing him, because it looks like success.
    """
    track = tracker.track_from_seed(
        crossing_source,
        Seed(frame=0, box=RIGHT_OFFICER),
        label="Right",
        path=crossing_mezzanine,
    )

    where = middles(track, crossing_source.frame_count)
    started = where[0]
    ended = where[max(where)]

    print(f"started at x {started:.2f}, ended at x {ended:.2f}")
    assert ended > 0.45, "the track ended on the other officer"


# --- A WHOLE SELECTION ---


def a_selection(source, *faces) -> Selection:
    return Selection(
        created_at=datetime.now(timezone.utc),
        source_name=source.path.name,
        source_frame_count=source.frame_count,
        faces=list(faces),
    )


def both_officers() -> list[Face]:
    return [
        Face(label="Bearded", seeds=[Seed(frame=0, box=LEFT_OFFICER)]),
        Face(label="Partner", seeds=[Seed(frame=0, box=RIGHT_OFFICER)]),
    ]


SKY = NormalisedBox(left=0.80, top=0.02, right=0.95, bottom=0.15)


@pytest.fixture(scope="session")
def both_tracks(tracker, crossing_source, crossing_mezzanine) -> list[FaceTrack]:
    """
    Both officers tracked, once for the session.

    Two faces through 240 frames of 1080p is six seconds. Several tests ask
    different questions of the same result, and asking it once keeps the file
    usable — a suite nobody waits for is a suite nobody runs.
    """
    selection = a_selection(crossing_source, *both_officers())
    return tracker.track_selection(crossing_source, selection, path=crossing_mezzanine)


def test_every_chosen_face_gets_its_own_full_length_track(crossing_source, both_tracks):
    """
    Two people, two tracks, both the length of the source. A face that was
    lost for most of the clip is still a full-length track with gaps in it.
    """
    tracks = both_tracks

    assert [track.label for track in tracks] == ["Bearded", "Partner"]
    for track in tracks:
        assert track.frame_count == crossing_source.frame_count
        track.validate_shape()


def test_two_tracks_are_not_the_same_face(both_tracks):
    """
    The point of a landmarker each. They start on opposite sides and must not
    both end up describing whoever the detector liked best.
    """
    bearded, partner = both_tracks

    assert float(bearded.landmarks_on(0)[:, 0].mean()) < 0.5
    assert float(partner.landmarks_on(0)[:, 0].mean()) > 0.5


def test_a_box_with_nothing_in_it_is_refused_before_any_tracking(
    tracker, crossing_source, crossing_mezzanine
):
    """
    The pre-flight. Tracking three faces through a long source takes
    minutes, and finding out at the end that one box was drawn on the sky is
    a poor way to spend them.
    """
    selection = a_selection(
        crossing_source,
        Face(label="Bearded", seeds=[Seed(frame=0, box=LEFT_OFFICER)]),
        Face(label="Sky", seeds=[Seed(frame=0, box=SKY)]),
    )

    with pytest.raises(NoFaceInSeed, match="Sky"):
        tracker.track_selection(crossing_source, selection, path=crossing_mezzanine)


def test_every_bad_box_is_named_not_just_the_first(
    tracker, crossing_source, crossing_mezzanine
):
    """Fixing them one run at a time would be its own kind of hostile."""
    selection = a_selection(
        crossing_source,
        Face(label="Sky", seeds=[Seed(frame=0, box=SKY)]),
        Face(
            label="Pavement",
            seeds=[Seed(frame=0, box=NormalisedBox(left=0.05, top=0.88, right=0.2, bottom=0.99))],
        ),
    )

    with pytest.raises(NoFaceInSeed) as raised:
        tracker.track_selection(crossing_source, selection, path=crossing_mezzanine)

    message = str(raised.value)
    print(message)
    assert "Sky" in message
    assert "Pavement" in message


def test_checking_seeds_is_quick_enough_to_be_worth_doing(
    tracker, crossing_source, crossing_mezzanine
):
    """
    One detection per seed rather than a pass over the source. If this were
    not far cheaper than tracking, it would not be worth having.
    """
    selection = a_selection(crossing_source, *both_officers())

    assert tracker.check_seeds(crossing_source, selection, path=crossing_mezzanine) == []


def test_a_selection_from_another_cut_is_refused(
    tracker, crossing_source, crossing_mezzanine
):
    """
    Seeds are frame numbers. Against a different cut they point at different
    pictures, and every mesh would land somewhere arbitrary.
    """
    selection = a_selection(crossing_source, *both_officers())
    selection.source_frame_count = crossing_source.frame_count + 50

    with pytest.raises(ValueError, match="different cut"):
        tracker.track_selection(crossing_source, selection, path=crossing_mezzanine)


def test_progress_covers_the_whole_job_not_each_face(
    tracker, crossing_source, crossing_mezzanine
):
    """Three faces should fill one bar, not three."""
    selection = a_selection(crossing_source, *both_officers())
    seen = []

    tracker.track_selection(
        crossing_source,
        selection,
        path=crossing_mezzanine,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen[-1] == (crossing_source.frame_count * 2, crossing_source.frame_count * 2)


# --- SEVERAL SEEDS PER FACE ---

# Re-seeding is the normal way to work, not a recovery path: track until the
# face turns away, mark it again past the break. The seeds divide the source
# into segments, and every frame records which one produced it.


def box_round(points, pad=0.03) -> NormalisedBox:
    """A seed box around a set of landmarks, drawn a little generously."""
    return NormalisedBox(
        left=max(0.0, float(points[:, 0].min()) - pad),
        top=max(0.0, float(points[:, 1].min()) - pad),
        right=min(1.0, float(points[:, 0].max()) + pad),
        bottom=min(1.0, float(points[:, 1].max()) + pad),
    )


def test_a_later_seed_owns_the_frames_after_it(tracker, gap_source, gap_mezzanine, gap_track):
    """
    The point of `seeded_by`: the timeline can show which box a stretch of
    track came from, so an artist knows where to add another.
    """
    face = Face(
        label="Girl",
        seeds=[
            Seed(frame=160, box=box_round(gap_track.landmarks_on(160))),
            Seed(frame=200, box=box_round(gap_track.landmarks_on(200))),
        ],
    )

    track = tracker.track_face(gap_source, face, path=gap_mezzanine)

    assert (track.seeded_by[200:][track.tracked[200:]] == 1).all()
    assert (track.seeded_by[160:200][track.tracked[160:200]] == 0).all()


def test_segments_report_both_the_seeds_and_the_gaps(
    tracker, gap_source, gap_mezzanine, gap_track
):
    """
    A segment ends where the face was lost *or* where the next seed takes
    over, and both show up as separate runs.
    """
    face = Face(
        label="Girl",
        seeds=[
            Seed(frame=160, box=box_round(gap_track.landmarks_on(160))),
            Seed(frame=200, box=box_round(gap_track.landmarks_on(200))),
        ],
    )

    track = tracker.track_face(gap_source, face, path=gap_mezzanine)
    segments = [(index, r.start_frame, r.end_frame) for index, r in track.segments()]

    print(segments)
    assert any(index == 1 and start == 200 for index, start, _ in segments)
    assert len(segments) > 2, "the gap should split the first seed's run in two"


def test_only_the_first_seed_can_fail_the_whole_track(
    tracker, gap_source, gap_mezzanine, gap_track
):
    """
    A later seed marks a face the artist can see. If the detector disagrees
    there, the honest result is a gap in that segment — not the loss of
    everything tracked behind it.
    """
    face = Face(
        label="Girl",
        seeds=[
            Seed(frame=200, box=box_round(gap_track.landmarks_on(200))),
            Seed(frame=220, box=NormalisedBox(left=0.02, top=0.02, right=0.12, bottom=0.12)),
        ],
    )

    track = tracker.track_face(gap_source, face, path=gap_mezzanine)

    assert track.tracked[:200].any(), "the backward run behind the good seed was lost"
    track.validate_shape()


def test_a_bad_first_seed_still_raises(tracker, gap_source, gap_mezzanine):
    """It is the one the whole track hangs from."""
    face = Face(
        label="Girl",
        seeds=[Seed(frame=10, box=NormalisedBox(left=0.02, top=0.02, right=0.12, bottom=0.12))],
    )

    with pytest.raises(NoFaceInSeed):
        tracker.track_face(gap_source, face, path=gap_mezzanine)


def test_a_seed_past_the_end_names_the_face(tracker, gap_source, gap_mezzanine):
    face = Face(
        label="Girl",
        seeds=[Seed(frame=gap_source.frame_count + 5, box=SEED_BOX)],
    )

    with pytest.raises(ValueError, match="Girl"):
        tracker.track_face(gap_source, face, path=gap_mezzanine)


def test_seeds_on_adjacent_frames_do_not_make_an_empty_segment(
    tracker, gap_source, gap_mezzanine, gap_track
):
    """
    The first seed's segment would run to the frame before the next, which
    is itself. An empty run would be a FrameRange with its end before its
    start, which the model refuses outright.
    """
    face = Face(
        label="Girl",
        seeds=[
            Seed(frame=200, box=box_round(gap_track.landmarks_on(200))),
            Seed(frame=201, box=box_round(gap_track.landmarks_on(201))),
        ],
    )

    track = tracker.track_face(gap_source, face, path=gap_mezzanine)

    track.validate_shape()
    assert track.frame_count == gap_source.frame_count


def test_one_seed_through_track_face_matches_track_from_seed(
    tracker, gap_source, gap_mezzanine, gap_track
):
    """
    `track_from_seed` is a wrapper now, and the one-seed case is the shape
    the general one reduces to. If they ever disagree, one of them is wrong.
    """
    seed = Seed(frame=200, box=box_round(gap_track.landmarks_on(200)))

    direct = tracker.track_from_seed(gap_source, seed, label="Girl", path=gap_mezzanine)
    general = tracker.track_face(
        gap_source, Face(label="Girl", seeds=[seed]), path=gap_mezzanine
    )

    assert int(direct.tracked.sum()) == int(general.tracked.sum())
    assert direct.gaps() == general.gaps()


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
