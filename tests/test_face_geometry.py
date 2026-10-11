"""
Tests for Where a Face Is.

Pure arithmetic, so all of it runs in milliseconds with no model, no ffmpeg
and no footage. That is the point of the module being separate: this geometry
can be wrong in ways that produce a perfectly valid-looking track pointing at
the wrong place, and catching that should not depend on having a clip to hand.
"""

import numpy as np
import pytest

from src.core.models import LANDMARK_COUNT, NormalisedBox
from src.performance.face_geometry import (
    bounding_box,
    centroid,
    face_in_box,
    face_nearest,
    overlap,
    search_region,
    to_full_frame,
)


# --- CHOOSING A FACE ---


def points_at(x_from, x_to, y_from, y_to) -> np.ndarray:
    """A stand-in face filling the given normalised rectangle."""
    points = np.zeros((LANDMARK_COUNT, 3), dtype=np.float32)
    points[:, 0] = np.linspace(x_from, x_to, LANDMARK_COUNT)
    points[:, 1] = np.linspace(y_from, y_to, LANDMARK_COUNT)
    return points


def test_a_box_is_the_bounds_of_the_points():
    box = bounding_box(points_at(0.2, 0.4, 0.3, 0.7))

    assert (box.left, box.right) == pytest.approx((0.2, 0.4))
    assert (box.top, box.bottom) == pytest.approx((0.3, 0.7))


def test_boxes_that_do_not_meet_do_not_overlap():
    left = NormalisedBox(left=0.0, top=0.0, right=0.2, bottom=0.2)
    right = NormalisedBox(left=0.8, top=0.8, right=1.0, bottom=1.0)

    assert overlap(left, right) == 0.0


def test_a_box_overlaps_itself_completely():
    box = NormalisedBox(left=0.2, top=0.2, right=0.6, bottom=0.6)

    assert overlap(box, box) == pytest.approx(1.0)


def test_overlap_is_measured_over_the_union():
    """
    A generous box round a face and the face's own tight bounds still match,
    but a box round a whole group does not match one member better than the
    member it was aimed at.
    """
    half = NormalisedBox(left=0.0, top=0.0, right=0.5, bottom=1.0)
    whole = NormalisedBox(left=0.0, top=0.0, right=1.0, bottom=1.0)

    assert overlap(half, whole) == pytest.approx(0.5)


def test_the_face_inside_the_box_is_the_one_chosen():
    faces = [points_at(0.05, 0.25, 0.1, 0.5), points_at(0.70, 0.90, 0.1, 0.5)]
    box = NormalisedBox(left=0.68, top=0.08, right=0.92, bottom=0.52)

    chosen = face_in_box(faces, box)

    assert float(chosen[:, 0].mean()) > 0.5, "picked the face on the wrong side"


def test_a_box_over_nothing_chooses_no_face():
    """
    A box drawn on empty background says so, rather than quietly returning
    whoever happened to be nearest.
    """
    faces = [points_at(0.05, 0.25, 0.1, 0.5)]
    empty = NormalisedBox(left=0.8, top=0.8, right=0.95, bottom=0.95)

    assert face_in_box(faces, empty) is None


def test_no_faces_at_all_chooses_none():
    assert face_in_box([], NormalisedBox(left=0.1, top=0.1, right=0.2, bottom=0.2)) is None
    assert face_nearest([], (0.5, 0.5)) is None


def test_the_nearest_face_is_the_one_followed():
    faces = [points_at(0.05, 0.25, 0.1, 0.5), points_at(0.70, 0.90, 0.1, 0.5)]

    chosen = face_nearest(faces, (0.8, 0.3))

    assert float(chosen[:, 0].mean()) > 0.5


def test_with_nowhere_to_follow_the_first_face_is_taken():
    """The first frame of a run has no previous position to go on."""
    assert face_nearest([points_at(0.05, 0.25, 0.1, 0.5)], None) is not None


def test_a_centroid_is_the_middle_of_the_points():
    assert centroid(points_at(0.2, 0.4, 0.4, 0.8)) == pytest.approx((0.3, 0.6))


# --- THE SEARCH REGION ---


def test_a_region_is_the_face_plus_its_padding():
    face = NormalisedBox(left=0.4, top=0.4, right=0.6, bottom=0.6)

    region = search_region(face, 1920, 1080, padding=0.5, minimum_pixels=0)

    assert (region.left, region.right) == pytest.approx((0.3, 0.7))
    assert (region.top, region.bottom) == pytest.approx((0.3, 0.7))


def test_a_region_is_clamped_to_the_picture():
    """A face at the edge gets a smaller region, not an invalid one."""
    corner = NormalisedBox(left=0.0, top=0.0, right=0.1, bottom=0.1)

    region = search_region(corner, 1920, 1080, padding=2.0, minimum_pixels=0)

    assert region.left == 0.0
    assert region.top == 0.0
    assert region.right <= 1.0


def test_a_small_face_is_grown_to_something_worth_cropping():
    """
    The reason the minimum exists. A face 2% of a 1920 frame is 38 pixels;
    padded it is 76, and MediaPipe's detector runs at 192x192 — so without
    this the crop would be a magnified thumbnail and cropping would buy
    nothing on exactly the shot it should help most.
    """
    tiny = NormalisedBox(left=0.49, top=0.49, right=0.51, bottom=0.51)

    region = search_region(tiny, 1920, 1080, padding=0.5, minimum_pixels=192)
    left, top, right, bottom = region.to_pixels(1920, 1080)

    print(f"{right - left}x{bottom - top} pixels")
    assert min(right - left, bottom - top) >= 192


def test_a_face_already_large_enough_is_not_grown():
    big = NormalisedBox(left=0.3, top=0.3, right=0.7, bottom=0.7)

    region = search_region(big, 1920, 1080, padding=0.1, minimum_pixels=192)

    assert (region.left, region.right) == pytest.approx((0.26, 0.74))


# --- MAPPING BACK OUT OF A CROP ---


def test_landmarks_from_a_crop_become_fractions_of_the_picture():
    """
    Without this the mesh would land in the top-left corner at the wrong
    scale, because MediaPipe measures against whatever it was handed.
    """
    middle = np.zeros((LANDMARK_COUNT, 3), dtype=np.float32)
    middle[:, 0] = 0.5
    middle[:, 1] = 0.5

    # A crop of the right-hand quarter, vertically centred.
    mapped = to_full_frame(middle, (1440, 270, 1920, 810), 1920, 1080)

    assert float(mapped[0, 0]) == pytest.approx(0.875)
    assert float(mapped[0, 1]) == pytest.approx(0.5)


def test_a_full_frame_crop_changes_nothing():
    points = np.zeros((LANDMARK_COUNT, 3), dtype=np.float32)
    points[:, 0] = 0.25
    points[:, 1] = 0.75

    mapped = to_full_frame(points, (0, 0, 1920, 1080), 1920, 1080)

    assert float(mapped[0, 0]) == pytest.approx(0.25)
    assert float(mapped[0, 1]) == pytest.approx(0.75)


def test_depth_is_scaled_with_the_crop():
    """
    MediaPipe's z is roughly in the same units as x, so a crop a third of
    the width would otherwise report depths three times too large.
    """
    points = np.zeros((LANDMARK_COUNT, 3), dtype=np.float32)
    points[:, 2] = 0.3

    mapped = to_full_frame(points, (0, 0, 640, 1080), 1920, 1080)

    assert float(mapped[0, 2]) == pytest.approx(0.1)
