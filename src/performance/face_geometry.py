"""
Where a Face Is.

The arithmetic of placing and choosing a face: the region to search next,
mapping landmarks out of a crop, and deciding which of several detections is
the one being followed.

**Nothing here runs a model or touches a file.** It is pure functions over
boxes and landmark arrays, which is why it is its own module — the tracker is
slow and needs MediaPipe and real footage, and none of this does. The
geometry can be got wrong in ways that produce a perfectly valid track
pointing at the wrong place, so it is worth being able to test it exhaustively
and instantly.

Written for this project. minicut never looked at a face.
"""

import numpy as np

from src.core import config
from src.core.models import NormalisedBox

# How many times `search_region` may grow a region toward the minimum crop
# size. Three is one more than the rounding ever needs, and the cap is what
# stops a region already filling the picture from looping.
GROWTH_ATTEMPTS = 3


def search_region(
    around: NormalisedBox,
    width: int,
    height: int,
    padding: float,
    minimum_pixels: int | None = None,
) -> NormalisedBox:
    """
    The region to look in next, from where the face was last.

    Args:
        around: The face's own bounds on the previous frame.
        width: Picture width in pixels, for the minimum size.
        height: Picture height in pixels.
        padding: Fraction of the box's own size to add on each side.
        minimum_pixels: Grow the region until its short side is at least this
            many pixels. Defaults to `config.MIN_SEARCH_PIXELS`.

    Notes:
        **The minimum is what makes cropping worth doing on a wide shot.** A
        face 60 pixels across, padded, is still only a 120-pixel crop, and
        MediaPipe's detector runs at 192x192 — so it would be upscaling
        almost nothing. Growing the region first means the crop carries real
        detail rather than a magnified thumbnail.

        Clamped to the picture throughout, so a face at the edge gets a
        smaller region rather than an invalid one.
    """
    floor = config.MIN_SEARCH_PIXELS if minimum_pixels is None else minimum_pixels
    region = around.padded(padding)

    # Grown a step at a time rather than in one calculation. A box's two
    # axes do not scale alike — a fraction of the height is fewer pixels
    # than the same fraction of the width — and `to_pixels` rounds outward
    # at both ends, so one division lands a pixel or two short. Bounded,
    # because a region already filling the picture cannot grow.
    for _ in range(GROWTH_ATTEMPTS):
        left, top, right, bottom = region.to_pixels(width, height)
        shortfall = max(
            floor / (right - left) if right - left < floor else 1.0,
            floor / (bottom - top) if bottom - top < floor else 1.0,
        )

        if shortfall == 1.0:
            break

        grown = region.padded((shortfall - 1.0) / 2.0)
        if grown.model_dump() == region.model_dump():
            break  # against the edges of the picture; this is as big as it gets

        region = grown

    return region


def to_full_frame(
    points: np.ndarray, crop: tuple[int, int, int, int], width: int, height: int
) -> np.ndarray:
    """
    Landmarks found inside a crop, as fractions of the whole picture.

    Args:
        points: (LANDMARK_COUNT, 3), as fractions of the crop.
        crop: (left, top, right, bottom) in pixels of the full picture.
        width: Full picture width.
        height: Full picture height.

    Notes:
        Without this, every landmark from a cropped search would be a
        fraction of the search box, and the mesh would land in the top-left
        corner at the wrong scale. A track's contract is fractions of the
        *picture*, whatever was actually handed to the model.

        z is scaled by the crop's width rather than left alone: MediaPipe's
        relative depth is roughly in the same units as x, so a crop a third
        of the width would otherwise report depths three times too large.
    """
    left, top, right, bottom = crop
    crop_width = (right - left) / width
    crop_height = (bottom - top) / height

    mapped = np.empty_like(points)
    mapped[:, 0] = left / width + points[:, 0] * crop_width
    mapped[:, 1] = top / height + points[:, 1] * crop_height
    mapped[:, 2] = points[:, 2] * crop_width

    return mapped


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


def face_in_box(candidates: list[np.ndarray], box: NormalisedBox) -> np.ndarray | None:
    """
    Of several detected faces, the one the seed box was drawn around.

    Args:
        candidates: Each face's points, as fractions of the whole picture.
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

    for points in candidates:
        score = overlap(bounding_box(points), box)
        if score > best_overlap:
            best, best_overlap = points, score

    return best


def face_nearest(
    candidates: list[np.ndarray], to: tuple[float, float] | None
) -> np.ndarray | None:
    """
    Of several detected faces, the one closest to where the face was last.

    Returns:
        That face's points, or None when nothing was detected.

    Notes:
        Nearest centroid, with no limit on how far it may jump — the search
        region is what bounds this now. Inside a crop around the last known
        position there is rarely more than one candidate, and a face that
        wandered into shot was never in the picture handed to the model.
    """
    if not candidates:
        return None

    if to is None:
        return candidates[0]

    return min(
        candidates,
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
