"""
Tests for the Face Mesh Layer.

The mesh is **its own picture with transparency**, not a drawing on top of
depth. Everything here defends that: the layer is empty where there is no
face, the alpha is straight rather than premultiplied, and several faces
share one layer rather than one each.

No model and no footage — these run against landmark arrays, so they are
fast and they isolate the drawing from the tracking.
"""

import numpy as np
import pytest

from src.core import config
from src.core.models import LANDMARK_COUNT, NOT_SEEDED, FaceTrack
from src.performance.mesh import (
    draw_face,
    empty_layer,
    line_width,
    render_frame,
    render_layer,
)

WIDTH, HEIGHT = 320, 240


def a_face(centre_x=0.5, centre_y=0.5, size=0.3) -> np.ndarray:
    """
    Landmarks spread over a square, which is enough to draw a mesh from.

    Not a real face: the drawing code cares about where points are, not
    whether they make a plausible one.
    """
    points = np.zeros((LANDMARK_COUNT, 3), dtype=np.float32)
    side = int(np.ceil(np.sqrt(LANDMARK_COUNT)))
    grid = np.linspace(-0.5, 0.5, side)

    for index in range(LANDMARK_COUNT):
        points[index, 0] = centre_x + grid[index % side] * size
        points[index, 1] = centre_y + grid[index // side] * size

    return points


def a_track(label="Face", frame_count=4, missing=(), **face) -> FaceTrack:
    landmarks = np.repeat(a_face(**face)[None, :, :], frame_count, axis=0)
    tracked = np.ones(frame_count, dtype=bool)
    seeded_by = np.zeros(frame_count, dtype=np.int16)

    for frame in missing:
        landmarks[frame] = np.nan
        tracked[frame] = False
        seeded_by[frame] = NOT_SEEDED

    return FaceTrack(label=label, landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)


def lit(layer) -> int:
    """How many pixels the mesh actually painted."""
    return int((layer[:, :, 3] > 0).sum())


# --- THE CANVAS ---


def test_an_empty_layer_is_transparent_everywhere():
    layer = empty_layer(WIDTH, HEIGHT)

    assert layer.shape == (HEIGHT, WIDTH, 4)
    assert layer.dtype == np.uint8
    assert not layer.any()


def test_a_line_is_never_thinner_than_a_pixel():
    """
    Zero would make OpenCV draw nothing at all, silently, and only on small
    pictures — so it would look like the proxy was broken rather than this.
    """
    assert line_width(0.0009, 120) == 1
    assert line_width(0.0, 1080) == 1


def test_line_width_scales_with_the_picture():
    """So a mesh is not a cobweb at 4K and a scribble at 480p."""
    assert line_width(0.002, 1080) == 2
    assert line_width(0.002, 2160) == 4


# --- DRAWING ---


def test_drawing_a_face_marks_the_layer():
    layer = empty_layer(WIDTH, HEIGHT)

    draw_face(layer, a_face())

    assert lit(layer) > 0


def test_a_face_is_drawn_where_it_is():
    """A mesh in the wrong place is worse than no mesh."""
    left = render_frame([a_track(centre_x=0.2)], 0, WIDTH, HEIGHT)
    right = render_frame([a_track(centre_x=0.8)], 0, WIDTH, HEIGHT)

    left_half = slice(None), slice(0, WIDTH // 2)
    assert left[left_half][:, :, 3].sum() > right[left_half][:, :, 3].sum() * 5


def test_landmarks_of_the_wrong_shape_are_refused():
    with pytest.raises(ValueError, match=str(LANDMARK_COUNT)):
        draw_face(empty_layer(WIDTH, HEIGHT), np.zeros((10, 3), dtype=np.float32))


def test_landmarks_outside_the_picture_do_not_crash():
    """
    A face at the very edge has points past the frame — clamped rather than
    refused, because it is a real thing that happens and the visible part
    should still draw.
    """
    layer = empty_layer(WIDTH, HEIGHT)

    draw_face(layer, a_face(centre_x=0.02, centre_y=0.02))

    assert lit(layer) > 0


# --- ALPHA ---


def test_the_layer_is_empty_where_there_is_no_face():
    """
    Not black — *transparent*. A layer that is opaque black where nothing
    was found would hide every layer beneath it.
    """
    layer = render_frame([a_track(missing=[1])], 1, WIDTH, HEIGHT)

    assert lit(layer) == 0
    assert not layer.any()


def test_nothing_is_held_over_from_the_previous_frame():
    """A mesh drawn where a face was last seen is a mesh in the wrong place."""
    track = a_track(frame_count=3, missing=[2])

    assert lit(render_frame([track], 0, WIDTH, HEIGHT)) > 0
    assert lit(render_frame([track], 2, WIDTH, HEIGHT)) == 0


def test_the_alpha_is_straight_not_premultiplied():
    """
    The compositor works in straight alpha — `fg·α + bg·(1−α)`. OpenCV's
    anti-aliasing leaves premultiplied edges, where a half-covered pixel has
    half the colour as well as half the alpha; composited straight, every
    line would darken against what is beneath it.

    Straight means a soft edge keeps full-strength colour and carries its
    coverage in alpha alone.
    """
    layer = render_frame([a_track()], 0, WIDTH, HEIGHT)

    edges = (layer[:, :, 3] > 0) & (layer[:, :, 3] < 255)
    assert edges.any(), "no anti-aliased edges to check"

    brightest = layer[:, :, :3][edges].max(axis=1)
    assert int(brightest.max()) > 240, "soft edges lost their colour, so it is premultiplied"


def test_a_fully_transparent_layer_is_left_alone():
    """Dividing by a zero alpha has nothing to recover and must not try."""
    layer = render_frame([a_track(missing=[0])], 0, WIDTH, HEIGHT)

    assert not np.isnan(layer.astype(np.float32)).any()


# --- SEVERAL FACES, ONE LAYER ---


def test_every_face_goes_into_the_same_layer():
    """
    A three-person shot should not fill the stack with near-identical rows.
    """
    one = render_frame([a_track(centre_x=0.25)], 0, WIDTH, HEIGHT)
    two = render_frame(
        [a_track("A", centre_x=0.25), a_track("B", centre_x=0.75)], 0, WIDTH, HEIGHT
    )

    assert lit(two) > lit(one) * 1.5


def test_a_face_can_be_switched_off():
    """Per-face visibility belongs on the Faces step, not in the compositor."""
    tracks = [a_track("A", centre_x=0.25), a_track("B", centre_x=0.75)]

    both = render_frame(tracks, 0, WIDTH, HEIGHT)
    only_a = render_frame(tracks, 0, WIDTH, HEIGHT, visible={"A"})

    assert lit(only_a) < lit(both)
    assert only_a[:, WIDTH // 2 :, 3].sum() == 0, "the hidden face was still drawn"


def test_hiding_everything_gives_an_empty_layer():
    tracks = [a_track("A"), a_track("B")]

    assert lit(render_frame(tracks, 0, WIDTH, HEIGHT, visible=set())) == 0


# --- THE WHOLE LAYER ---


def test_a_layer_is_exactly_as_long_as_the_track():
    """Non-negotiable 2 again. A pass is the length of what it came from."""
    frames = list(render_layer([a_track(frame_count=7)], WIDTH, HEIGHT))

    assert len(frames) == 7
    assert all(frame.shape == (HEIGHT, WIDTH, 4) for frame in frames)


def test_tracks_of_different_lengths_are_refused():
    """
    They cannot both be the length of the source, so one of them is wrong
    and the layer would be silently truncated to the shorter.
    """
    with pytest.raises(ValueError, match="disagree"):
        list(render_layer([a_track(frame_count=5), a_track(frame_count=9)], WIDTH, HEIGHT))


def test_a_layer_needs_a_track():
    with pytest.raises(ValueError, match="at least one"):
        list(render_layer([], WIDTH, HEIGHT))


def test_a_layer_is_a_generator_rather_than_a_list():
    """
    A 1080p RGBA frame is 8 MB. Holding a two-minute layer whole would be
    23 GB, and nothing needs more than one frame at a time.
    """
    layer = render_layer([a_track(frame_count=1000)], WIDTH, HEIGHT)

    assert next(iter(layer)).shape == (HEIGHT, WIDTH, 4)


# --- WHAT IT IS DRAWN WITH ---


def test_the_features_are_told_apart_by_colour():
    """
    Blue tessellation, orange lips, green eyes. Whether those particular
    colours help a generation model is untested — what this checks is only
    that the features are told apart at all. If they were one colour the
    mesh would be a net.
    """
    assert config.MESH_TESSELATION_COLOUR != config.MESH_LIPS_COLOUR
    assert config.MESH_LIPS_COLOUR != config.MESH_EYES_COLOUR

    layer = render_frame([a_track()], 0, WIDTH, HEIGHT)
    painted = layer[:, :, :3][layer[:, :, 3] > 0]
    distinct = {tuple(colour) for colour in painted.tolist()}

    assert len(distinct) > 3, "the mesh came out a single colour"
