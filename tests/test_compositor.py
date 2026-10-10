"""
Tests for the Layer Stack.

Proven against generated clips standing in as layers, because no pass exists
to make a real one yet. The arithmetic and the ordering can be checked
exactly here; whether a real mesh over real depth *looks* right is the
checkpoint at 4.12, and no test replaces it.

The one property worth stating up front: the length comes from the source,
never from whichever layer is shortest.
"""

import shutil
from fractions import Fraction

import numpy as np
import pytest

from src.composite.compositor import (
    CONSTANT_LEVELS,
    Compositor,
    composite_frame,
    constant_frame,
    over,
)
from src.core.config import GREY_CARD_LEVEL
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import Layer, LayerSource, LayerStack
from src.media.frames import RGB, RGBA, FrameReader, FrameWriter

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

SIZE = (8, 12)  # height, width — not square, so a transpose cannot hide


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


def rgb(colour) -> np.ndarray:
    frame = np.zeros((*SIZE, 3), dtype=np.uint8)
    frame[:, :] = colour
    return frame


def rgba(colour, alpha) -> np.ndarray:
    frame = np.zeros((*SIZE, 4), dtype=np.uint8)
    frame[:, :, :3] = colour
    frame[:, :, 3] = alpha
    return frame


def a_stack(*sources, disabled=()) -> LayerStack:
    return LayerStack(layers=[Layer(source=s, enabled=s not in disabled) for s in sources])


# --- THE OVER OPERATOR ---


def test_opaque_foreground_wins_completely():
    result = over(rgba((255, 0, 0), 255), rgb((0, 0, 255)))

    assert tuple(result[0, 0]) == (255, 0, 0)


def test_transparent_foreground_shows_everything_beneath():
    result = over(rgba((255, 0, 0), 0), rgb((0, 0, 255)))

    assert tuple(result[0, 0]) == (0, 0, 255)


def test_half_alpha_is_half_way_between():
    """
    Straight alpha: fg·α + bg·(1−α). Premultiplied would give (255, 0, 126)
    here instead — the foreground at full strength over a half-darkened
    background, which is the dark-fringe failure in miniature.
    """
    result = over(rgba((255, 0, 0), 128), rgb((0, 0, 255)))

    assert 120 <= int(result[0, 0, 0]) <= 135
    assert 120 <= int(result[0, 0, 2]) <= 135


def test_the_arithmetic_does_not_round_at_every_layer():
    """
    Done in uint8 throughout, a faint layer applied repeatedly would darken.
    Twenty passes of a barely-there mesh should leave the background alone.
    """
    background = rgb((100, 100, 100))
    faint = rgba((255, 255, 255), 2)

    result = background
    for _ in range(20):
        result = over(faint, result)

    assert int(result[0, 0, 0]) >= 100, "repeated compositing lost brightness"


# --- CONSTANT LAYERS ---


def test_the_grey_card_is_eighteen_percent():
    """The photographic mid-grey, and the level a neutral region sits at."""
    frame = constant_frame(LayerSource.GREY, 12, 8)

    assert frame.shape == (8, 12, 3)
    assert int(frame[0, 0, 0]) == round(GREY_CARD_LEVEL * 255)


def test_black_is_black():
    assert int(constant_frame(LayerSource.BLACK, 4, 4)[0, 0, 0]) == 0


def test_asking_a_file_layer_for_a_constant_fails_loudly():
    """A caller confusing the two has made a mistake worth hearing about."""
    with pytest.raises(KeyError):
        constant_frame(LayerSource.DEPTH, 4, 4)


# --- STACKING ---


def test_index_zero_is_the_bottom():
    """Red over blue is red. Blue over red is blue. The order is the picture."""
    red_over_blue = composite_frame([rgb((0, 0, 255)), rgba((255, 0, 0), 255)])
    blue_over_red = composite_frame([rgb((255, 0, 0)), rgba((0, 0, 255), 255)])

    assert tuple(red_over_blue[0, 0]) == (255, 0, 0)
    assert tuple(blue_over_red[0, 0]) == (0, 0, 255)


def test_an_opaque_layer_hides_everything_under_it():
    """
    Not an optimisation — it is what opaque means. A stack with depth above
    the plate shows no plate, which is correct and occasionally surprising.
    """
    result = composite_frame([rgb((255, 0, 0)), rgb((0, 255, 0))])

    assert tuple(result[0, 0]) == (0, 255, 0)


def test_a_mesh_over_grey_shows_grey_where_it_is_clear():
    """How the mesh gets looked at on its own."""
    mesh = rgba((80, 160, 255), 0)
    mesh[0:2, :, 3] = 255  # a couple of opaque rows

    result = composite_frame([constant_frame(LayerSource.GREY, SIZE[1], SIZE[0]), mesh])

    assert tuple(result[0, 0]) == (80, 160, 255)
    assert int(result[5, 0, 0]) == round(GREY_CARD_LEVEL * 255)


def test_a_lone_alpha_layer_lands_on_black():
    """
    An h264 output would do this anyway; doing it here means the result is
    the same whatever it is written to.
    """
    result = composite_frame([rgba((255, 255, 255), 0)])

    assert tuple(result[0, 0]) == (0, 0, 0)


def test_layers_that_disagree_about_size_are_refused():
    small = np.zeros((4, 4, 3), dtype=np.uint8)
    big = np.zeros((8, 8, 4), dtype=np.uint8)

    with pytest.raises(ValueError, match="disagree about their size"):
        composite_frame([small, big])


def test_an_empty_composite_is_refused():
    with pytest.raises(ValueError, match="at least one layer"):
        composite_frame([])


# --- THE COMPOSITOR ---


def test_a_layer_with_no_picture_is_caught_before_any_work():
    """Better than discovering it part way through a long clip."""
    with pytest.raises(ValueError, match="no picture for enabled layer"):
        Compositor(a_stack(LayerSource.DEPTH, LayerSource.FACE_MESH), sources={})


def test_constants_need_no_file():
    Compositor(a_stack(LayerSource.GREY, LayerSource.BLACK), sources={})


def test_a_disabled_layer_needs_no_picture_either():
    """Switching a layer off is how a single pass is delivered."""
    stack = a_stack(LayerSource.GREY, LayerSource.DEPTH, disabled=(LayerSource.DEPTH,))

    Compositor(stack, sources={})


def test_every_constant_source_is_actually_constant():
    """So `CONSTANT_LEVELS` and the enum cannot drift apart unnoticed."""
    for source in CONSTANT_LEVELS:
        assert constant_frame(source, 2, 2).shape == (2, 2, 3)


# --- OVER A WHOLE CLIP ---


@needs_ffmpeg
def test_a_stack_of_real_files_composites_every_frame(toolchain, tmp_path):
    """
    Two generated clips standing in as layers, because no pass exists yet to
    make a real one. What this proves is the plumbing and the count.
    """
    height, width, frames = 8, 12, 10
    rate = Fraction(25, 1)

    depth = tmp_path / "depth.mp4"
    with FrameWriter(toolchain, depth, width, height, rate) as writer:
        for _ in range(frames):
            writer.write(rgb((0, 0, 255)))

    mesh = tmp_path / "mesh.mov"
    with FrameWriter(
        toolchain, mesh, width, height, rate, codec="qtrle", pixel_format=RGBA
    ) as writer:
        for _ in range(frames):
            writer.write(rgba((255, 0, 0), 255))

    stack = a_stack(LayerSource.DEPTH, LayerSource.FACE_MESH)
    compositor = Compositor(stack, {LayerSource.DEPTH: depth, LayerSource.FACE_MESH: mesh})

    output = tmp_path / "composite.mp4"
    with FrameReader(toolchain, depth, width, height, RGB) as depth_reader:
        with FrameReader(toolchain, mesh, width, height, RGBA) as mesh_reader:
            with FrameWriter(toolchain, output, width, height, rate) as writer:
                written = compositor.run(
                    {LayerSource.DEPTH: depth_reader, LayerSource.FACE_MESH: mesh_reader},
                    writer,
                    frames,
                    width,
                    height,
                )

    assert written == frames
    assert output.is_file()


@needs_ffmpeg
def test_a_layer_running_short_stops_the_job(toolchain, tmp_path):
    """
    The failure non-negotiable 2 exists for. Trimming to the shortest layer
    would deliver a pass that drifts, and say nothing.
    """
    height, width = 8, 12
    rate = Fraction(25, 1)

    short = tmp_path / "short.mp4"
    with FrameWriter(toolchain, short, width, height, rate) as writer:
        for _ in range(4):
            writer.write(rgb((0, 0, 255)))

    compositor = Compositor(a_stack(LayerSource.DEPTH), {LayerSource.DEPTH: short})
    output = tmp_path / "out.mp4"

    with FrameReader(toolchain, short, width, height, RGB) as reader:
        with FrameWriter(toolchain, output, width, height, rate) as writer:
            with pytest.raises(RuntimeError, match="ran out at frame 4"):
                compositor.run({LayerSource.DEPTH: reader}, writer, 10, width, height)
