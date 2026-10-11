"""
Smoothing a Track.

Written for this project. minicut had nothing to smooth.

**Raw landmarks jitter, and a generation model renders jitter as shimmer.**
MediaPipe re-solves each frame largely on its own, so a point that should be
still wanders a pixel or two every frame. On a plate nobody would notice; as
a control pass it becomes a crawling edge in the output, which is one of the
few artefacts a viewer reads as "this was made by a machine".

**A One Euro filter, not a rolling average.** The problem with averaging is
that the amount of smoothing a landmark wants depends entirely on what it is
doing: a still point wants a lot, and a point moving fast wants almost none,
because smoothing fast movement is just latency — the mesh arriving late and
sliding to catch up, which looks worse than the jitter did. One Euro adapts
per point per frame on exactly that basis: the faster a point is moving, the
less it is filtered.

**It resets at every boundary, and that is the part worth getting right.**
Smoothing across a gap would invent a slide between the last frame before the
face was lost and the first frame after — a movement that never happened,
through frames the tracker deliberately left empty. Smoothing across a seed
boundary would drag the old seed's answer into the new one's, which defeats
the point of having re-seeded. `FaceTrack.segments()` already returns exactly
the runs that may be smoothed as one: unbroken, single-seed, tracked.

Notes:
    A new track comes back; the one passed in is untouched. A pass produces a
    value rather than editing its input, and the raw track is worth keeping —
    comparing the two is how you tell smoothing from damage.
"""

import logging

import numpy as np

from src.core import config
from src.core.models import FaceTrack


def smooth(
    track: FaceTrack,
    rate: float,
    min_cutoff: float | None = None,
    beta: float | None = None,
) -> FaceTrack:
    """
    A copy of a track with its landmark paths filtered.

    Args:
        track: The raw track. Not modified.
        rate: Frames per second, which sets the filter's sense of time. Pass
            the source's exact rate as a float — a few decimal places of
            error here changes the smoothing imperceptibly, unlike
            everywhere else in this project where it would drift a frame.
        min_cutoff: Lower smooths more. Defaults to
            `config.SMOOTHING_MIN_CUTOFF`.
        beta: Higher follows fast movement more closely, at the cost of
            leaving more jitter in it. Defaults to `config.SMOOTHING_BETA`.

    Returns:
        A new FaceTrack with the same gaps, the same seeds and the same
        label. Untracked frames stay NaN.

    Raises:
        ValueError: The rate is not positive.

    Notes:
        Each segment is filtered independently — see the module docstring.
        A segment one frame long passes through untouched, which is correct:
        there is no path to smooth.
    """
    if rate <= 0:
        raise ValueError(f"frame rate must be positive, got {rate}")

    cutoff = config.SMOOTHING_MIN_CUTOFF if min_cutoff is None else min_cutoff
    speed_coefficient = config.SMOOTHING_BETA if beta is None else beta

    smoothed = track.landmarks.copy()

    for _seed_index, covered in track.segments():
        span = smoothed[covered.start_frame : covered.end_frame + 1]
        if len(span) > 1:
            span[:] = _one_euro(span, rate, cutoff, speed_coefficient)

    filtered = FaceTrack(
        label=track.label,
        landmarks=smoothed,
        tracked=track.tracked.copy(),
        seeded_by=track.seeded_by.copy(),
    )
    filtered.validate_shape()

    logging.info(
        f"Smoothed {track.label!r} over {len(track.segments())} segment(s), "
        f"min_cutoff={cutoff}, beta={speed_coefficient}"
    )
    return filtered


# --- THE FILTER ---


def _one_euro(path: np.ndarray, rate: float, min_cutoff: float, beta: float) -> np.ndarray:
    """
    One Euro over one unbroken run of frames.

    Args:
        path: (frames, LANDMARK_COUNT, 3) for a single segment.
        rate: Frames per second.
        min_cutoff: The cutoff when a point is still.
        beta: How much speed raises the cutoff.

    Notes:
        Every landmark and every axis is filtered at once as an array
        operation rather than in a loop over 478 points — the filter is
        per-coordinate but nothing about it is sequential across
        coordinates, only across frames.

        The first frame of a segment is its own starting value. There is
        nothing before it to filter against, and seeding the filter with a
        zero would drag the whole segment toward the top-left corner.
    """
    period = 1.0 / rate
    result = np.empty_like(path)
    result[0] = path[0]

    previous = path[0]
    previous_speed = np.zeros_like(path[0])

    for index in range(1, len(path)):
        speed = (path[index] - previous) * rate
        speed = _lowpass(speed, previous_speed, _alpha(period, config.SMOOTHING_SPEED_CUTOFF))

        # The adaptive part: a point moving quickly is filtered less, because
        # smoothing fast movement is latency, and latency looks worse than
        # the jitter it removed.
        cutoff = min_cutoff + beta * np.abs(speed)
        result[index] = _lowpass(path[index], previous, _alpha(period, cutoff))

        previous = result[index]
        previous_speed = speed

    return result


def _alpha(period: float, cutoff):
    """
    The filter's weight for a given cutoff, per the One Euro paper.

    Notes:
        `cutoff` may be a scalar or an array the shape of one frame, which
        is what lets every landmark adapt separately in one operation.
    """
    time_constant = 1.0 / (2.0 * np.pi * cutoff)
    return 1.0 / (1.0 + time_constant / period)


def _lowpass(value, previous, alpha):
    """One exponential step toward `value`."""
    return alpha * value + (1.0 - alpha) * previous


# --- MEASURING IT ---


def jitter(track: FaceTrack) -> float:
    """
    Mean distance a landmark moves between consecutive tracked frames.

    Returns:
        In fractions of the picture. 0.0 for a track with nothing to compare.

    Notes:
        A blunt number, and useful precisely because it is: smoothing should
        lower it, and a smoothing setting that lowers it to almost nothing
        has also removed the performance. It is how the tests check that
        smoothing did something without asserting a particular path.

        Only consecutive *tracked* pairs count. The step across a gap is not
        movement, it is two separate observations with nothing in between.
    """
    pairs = track.tracked[:-1] & track.tracked[1:]
    if not pairs.any():
        return 0.0

    steps = np.abs(np.diff(track.landmarks[:, :, :2], axis=0))
    return float(steps[pairs].mean())
