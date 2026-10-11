"""
Tests for Smoothing.

Two things are being defended.

**Smoothing must actually reduce jitter**, or it is cost for nothing — and
it must not reduce it to zero, because at that point it has removed the
performance along with the shimmer.

**It must reset at every boundary.** Smoothing across a gap invents a slide
between the last frame before a face was lost and the first after it — a
movement that never happened, through frames the tracker deliberately left
empty. Smoothing across a seed boundary drags the old seed's answer into the
new one's, which is the opposite of what re-seeding is for. Those two are
the whole reason this is not three lines of rolling average.
"""

import numpy as np
import pytest

from src.core.models import LANDMARK_COUNT, NOT_SEEDED, FaceTrack
from src.performance.smoothing import jitter, smooth

RATE = 24.0


def a_track(frame_count=60, missing=(), seeds=None, jitter_amount=0.004, seed=1) -> FaceTrack:
    """
    A face drifting slowly rightward with noise on top.

    The drift is the performance and the noise is the shimmer; smoothing
    should remove much of the second and little of the first.
    """
    generator = np.random.default_rng(seed)

    landmarks = np.zeros((frame_count, LANDMARK_COUNT, 3), dtype=np.float32)
    for frame in range(frame_count):
        landmarks[frame, :, 0] = 0.4 + frame * 0.001
        landmarks[frame, :, 1] = 0.5
    landmarks += generator.normal(0, jitter_amount, landmarks.shape).astype(np.float32)

    tracked = np.ones(frame_count, dtype=bool)
    seeded_by = np.array(
        seeds if seeds is not None else [0] * frame_count, dtype=np.int16
    )

    for frame in missing:
        landmarks[frame] = np.nan
        tracked[frame] = False
        seeded_by[frame] = NOT_SEEDED

    return FaceTrack(label="Face", landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)


# --- IT SMOOTHS ---


def test_smoothing_reduces_jitter():
    raw = a_track()

    filtered = smooth(raw, RATE)

    print(f"{jitter(raw):.5f} -> {jitter(filtered):.5f}")
    assert jitter(filtered) < jitter(raw) * 0.8


def test_smoothing_does_not_flatten_the_movement():
    """
    A filter that removes everything has removed the performance too. The
    face drifts 0.06 of the picture across this track and should still.
    """
    raw = a_track()

    filtered = smooth(raw, RATE)

    travelled = float(
        filtered.landmarks[-1, :, 0].mean() - filtered.landmarks[0, :, 0].mean()
    )
    assert travelled > 0.04, f"the drift was flattened to {travelled:.3f}"


def test_the_raw_track_is_left_alone():
    """Comparing the two is how you tell smoothing from damage."""
    raw = a_track()
    before = raw.landmarks.copy()

    smooth(raw, RATE)

    assert np.array_equal(raw.landmarks, before)


def test_a_smoothed_track_still_satisfies_the_contract():
    smooth(a_track(missing=[10, 11, 12]), RATE).validate_shape()


def test_the_gaps_and_seeds_are_untouched():
    raw = a_track(missing=[10, 11], seeds=[0] * 30 + [1] * 30)

    filtered = smooth(raw, RATE)

    assert np.array_equal(filtered.tracked, raw.tracked)
    assert np.array_equal(filtered.seeded_by, raw.seeded_by)
    assert filtered.label == raw.label


# --- IT RESETS ---


def test_smoothing_does_not_reach_across_a_gap():
    """
    The face is on the left before the gap and on the right after it. If the
    filter ran through, the frames just after the gap would be dragged back
    toward where it used to be — a slide across a jump that never happened.
    """
    raw = a_track(frame_count=40, missing=range(18, 22), jitter_amount=0.0)
    raw.landmarks[22:, :, 0] += 0.3  # it reappears well to the right

    filtered = smooth(raw, RATE)

    first_after = float(filtered.landmarks[22, :, 0].mean())
    raw_after = float(raw.landmarks[22, :, 0].mean())

    print(f"raw {raw_after:.4f}, smoothed {first_after:.4f}")
    assert first_after == pytest.approx(raw_after, abs=1e-6), "the filter crossed the gap"


def test_smoothing_does_not_reach_across_a_seed_boundary():
    """
    Re-seeding exists to say "stop using what you had, use this". Carrying
    the filter through would drag the old answer into the new segment.
    """
    raw = a_track(frame_count=40, seeds=[0] * 20 + [1] * 20, jitter_amount=0.0)
    raw.landmarks[20:, :, 0] += 0.3

    filtered = smooth(raw, RATE)

    assert float(filtered.landmarks[20, :, 0].mean()) == pytest.approx(
        float(raw.landmarks[20, :, 0].mean()), abs=1e-6
    ), "the filter crossed the seed boundary"


def test_each_segment_starts_from_its_own_first_frame():
    """
    Seeding the filter with a zero instead would drag every segment toward
    the top-left corner of the picture.
    """
    raw = a_track(frame_count=30, missing=[14], jitter_amount=0.0)

    filtered = smooth(raw, RATE)

    assert float(filtered.landmarks[0, :, 0].mean()) == pytest.approx(
        float(raw.landmarks[0, :, 0].mean()), abs=1e-6
    )
    assert float(filtered.landmarks[15, :, 0].mean()) == pytest.approx(
        float(raw.landmarks[15, :, 0].mean()), abs=1e-6
    )


def test_a_single_frame_segment_passes_through():
    """There is no path to smooth, and it must not become NaN or a zero."""
    raw = a_track(frame_count=10, missing=[1, 2, 3, 4, 5, 6, 7, 8], jitter_amount=0.0)

    filtered = smooth(raw, RATE)

    assert not np.isnan(filtered.landmarks[0]).any()
    assert not np.isnan(filtered.landmarks[9]).any()


def test_a_track_with_nothing_in_it_is_not_an_error():
    raw = a_track(frame_count=10, missing=range(10))

    filtered = smooth(raw, RATE)

    assert np.isnan(filtered.landmarks).all()
    filtered.validate_shape()


# --- THE SETTINGS ---


def test_a_lower_cutoff_smooths_harder():
    raw = a_track()

    soft = smooth(raw, RATE, min_cutoff=0.3)
    sharp = smooth(raw, RATE, min_cutoff=5.0)

    assert jitter(soft) < jitter(sharp)


def test_beta_actually_does_something_at_these_units():
    """
    The bug this guards. One Euro's published beta of 0.007 assumes
    coordinates in pixels or centimetres; landmarks here are fractions of
    the picture, so speeds are three orders of magnitude smaller and that
    beta leaves the adaptive half of the filter completely inert — the
    result is indistinguishable from a plain lowpass.
    """
    raw = a_track()

    inert = smooth(raw, RATE, beta=0.007)
    plain = smooth(raw, RATE, beta=0.0)
    working = smooth(raw, RATE, beta=30.0)

    assert jitter(inert) == pytest.approx(jitter(plain), rel=0.01), (
        "0.007 should be indistinguishable from no adaptation, which is the point"
    )
    assert jitter(working) > jitter(plain) * 1.05, "beta=30 should follow movement more"


def test_a_rate_of_zero_is_refused():
    """It would divide by zero and return NaN for every landmark."""
    with pytest.raises(ValueError, match="positive"):
        smooth(a_track(), 0.0)


# --- MEASURING ---


def test_jitter_of_a_still_track_is_nothing():
    raw = a_track(jitter_amount=0.0)
    raw.landmarks[:, :, 0] = 0.5  # no drift either

    assert jitter(raw) == pytest.approx(0.0, abs=1e-7)


def test_jitter_ignores_the_step_across_a_gap():
    """
    Not movement — two separate observations with nothing between them.
    Counting it would make a track with gaps look jitterier than it is.
    """
    raw = a_track(frame_count=20, missing=[9, 10], jitter_amount=0.0)
    raw.landmarks[11:, :, 0] += 0.5

    # Drift is 0.001 per frame in x and nothing in y, and jitter averages
    # both axes — so a clean read is 0.0005. Counting the 0.5 jump across
    # the gap would put it two orders of magnitude higher.
    assert jitter(raw) == pytest.approx(0.0005, abs=1e-5), "the jump across the gap was counted"


def test_jitter_of_an_empty_track_is_zero_not_an_error():
    assert jitter(a_track(frame_count=5, missing=range(5))) == 0.0
