"""
Tests for the Review Proxy.

The proxy is what a face is selected against, so two properties decide whether
the selection step can be trusted: every frame is a keyframe, so the browser
seeks to the frame it was asked for; and the frame number is burned into the
picture, so the player's readout can be checked against it by eye.

The second is allowed to be missing — on a machine with no monospaced font, or
an ffmpeg without libfreetype — and the tests cover both that it is normally
there and that its absence does not take the proxy down with it.
"""

import json
import shutil
import subprocess

import pytest

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import SourceInfo
from src.media.mezzanine import MezzanineBuilder
from src.media.probe import SourceProbe
from src.media.proxy import ProxyBuilder

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="module")
def builder(toolchain) -> ProxyBuilder:
    return ProxyBuilder(toolchain)


@pytest.fixture(scope="module")
def built_proxy(toolchain, clips, tmp_path_factory):
    """One real mezzanine and the proxy built from it, made once for this module."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")

    directory = tmp_path_factory.mktemp("proxy")
    probe = SourceProbe(toolchain)
    source = probe.probe(clips["pal25"])

    mezzanine = MezzanineBuilder(toolchain).build(source, directory / "pal25_mezzanine.mov")
    proxy = ProxyBuilder(toolchain).build(mezzanine, directory / "pal25_proxy.mp4")

    return source, proxy, probe


def keyframe_flags(path) -> list[int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "frame=key_frame",
            "-print_format", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [frame["key_frame"] for frame in json.loads(result.stdout)["frames"]]


class ToolchainWithoutDrawtext(MediaToolchain):
    """A build with no libfreetype, which is Homebrew's ffmpeg on a Mac."""

    def has_filter(self, name: str) -> bool:  # noqa: ARG002 — the point is ignoring it
        return False


# --- NAMING ---


def test_the_proxy_is_named_after_its_source(tmp_path):
    source = SourceInfo(
        path="C:/footage/take_01.mov",
        width=1920, height=1080,
        fps_numerator=25, fps_denominator=1,
        frame_count=100, codec="h264",
    )

    assert ProxyBuilder.proxy_path_for(source, tmp_path).name == "take_01_proxy.mp4"


# --- THE FILTER CHAIN ---


def test_the_font_path_is_escaped_for_ffmpegs_own_parser(builder):
    """
    ffmpeg reads a colon as an argument separator, so a Windows path has to be
    written "C\\:/..." or drawtext takes the drive letter for an option.
    """
    chain = builder.video_filter()

    if "drawtext" not in chain:
        pytest.skip("this machine has no font or no drawtext")

    assert "C\\:" in chain or ":/" not in chain.split("fontfile='")[1].split("'")[0]


def test_the_counter_reads_the_frame_number_not_the_time(builder):
    """`%{n}` is the frame index. A timestamp would be the wrong cross-check."""
    chain = builder.video_filter()

    if "drawtext" not in chain:
        pytest.skip("this machine has no font or no drawtext")

    assert "text='%{n}'" in chain


def test_a_build_without_drawtext_still_gets_a_proxy():
    """
    The failure this guards is not a missing counter. Asking for a filter that
    does not exist makes ffmpeg reject the whole output with "Filter not
    found" — so no proxy at all, and no way to select a face.
    """
    builder = ProxyBuilder(ToolchainWithoutDrawtext(discover=False))
    chain = builder.video_filter()

    assert chain == "scale=640:-2"
    assert "drawtext" not in chain


def test_the_scale_keeps_the_aspect_ratio(builder):
    """-2 rather than -1, so the height stays even and h264 accepts it."""
    assert builder.video_filter().startswith("scale=640:-2")


# --- BUILDING ---


@needs_ffmpeg
def test_every_frame_of_the_proxy_is_a_keyframe(built_proxy):
    """
    What lets the browser seek to a frame rather than near it. A box drawn
    "on frame 120" must be a box on frame 120.
    """
    _, proxy, _ = built_proxy
    flags = keyframe_flags(proxy)

    print(f"{len(flags)} frames, {sum(flags)} of them keyframes")
    assert all(flags)


@needs_ffmpeg
def test_the_proxy_is_the_same_length_as_the_source(built_proxy):
    """Frame N of the proxy has to be frame N of what gets tracked."""
    source, proxy, probe = built_proxy

    assert probe.probe(proxy).frame_count == source.frame_count


@needs_ffmpeg
def test_the_proxy_keeps_the_frame_rate(built_proxy):
    source, proxy, probe = built_proxy
    built = probe.probe(proxy)

    assert (built.fps_numerator, built.fps_denominator) == (
        source.fps_numerator,
        source.fps_denominator,
    )


@needs_ffmpeg
def test_the_proxy_is_small_and_keeps_its_shape(built_proxy):
    source, proxy, probe = built_proxy
    built = probe.probe(proxy)

    assert built.width == 640
    assert built.height == round(640 * source.height / source.width / 2) * 2


@needs_ffmpeg
def test_the_proxy_carries_no_audio(built_proxy):
    """The deliverable carries the real thing; a second copy is one more to keep in step."""
    _, proxy, probe = built_proxy

    assert probe.probe(proxy).audio is None


@needs_ffmpeg
def test_the_frame_numbers_are_actually_burned_in(built_proxy, builder, tmp_path):
    """
    Not just asked for. Two frames far apart must differ in the corner where
    the counter sits, which they cannot if drawtext silently did nothing.
    """
    _, proxy, _ = built_proxy

    if "drawtext" not in builder.video_filter():
        pytest.skip("this machine has no font or no drawtext")

    corners = []
    for frame in (0, 40):
        grab = tmp_path / f"corner_{frame}.png"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(proxy),
                "-vf", f"select='eq(n\\,{frame})',crop=60:28:0:0",
                "-frames:v", "1",
                str(grab),
            ],
            check=True,
            capture_output=True,
        )
        corners.append(grab.read_bytes())

    assert corners[0] != corners[1], (
        "the corner looks identical on both frames, so no number was burned in"
    )
