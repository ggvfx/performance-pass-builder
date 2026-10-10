"""
Tests for the Mezzanine.

The mezzanine exists so an arbitrary seek lands on the frame it was asked
for. Two things therefore have to hold and are tested on real encodes: it
matches the source frame for frame, and every frame of it is a keyframe.

The second is the whole point and is the one nothing else would catch — a
mezzanine that is merely a re-encode would pass every count check and still
seek to the wrong picture.
"""

import json
import shutil
import subprocess

import pytest

from src.core.ffmpeg_tools import MediaToolchain
from src.media.mezzanine import MezzanineBuilder
from src.media.probe import SourceProbe

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="module")
def builder(toolchain) -> MezzanineBuilder:
    return MezzanineBuilder(toolchain)


@pytest.fixture(scope="module")
def probe(toolchain) -> SourceProbe:
    return SourceProbe(toolchain)


def keyframe_flags(path) -> list[str]:
    """Every frame's key_frame flag, straight from ffprobe."""
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


# --- ENCODER SELECTION ---


def test_the_encoder_follows_the_source_codec(builder, clips, probe):
    """
    The mezzanine is the source in all respects but its keyframe interval, so
    the codec is not a choice.
    """
    assert builder.encoder_for(probe.probe(clips["film24"])) == "libx264"
    assert builder.encoder_for(probe.probe(clips["h265"])) == "libx265"


def test_a_codec_we_cannot_reproduce_is_refused(builder, clips, probe):
    """
    Better than working from a mezzanine in a different format from the
    source it claims to represent.
    """
    source = probe.probe(clips["film24"]).model_copy(update={"codec": "prores"})

    with pytest.raises(ValueError, match="Cannot re-encode 'prores'"):
        builder.encoder_for(source)


def test_each_encoder_gets_its_own_way_of_saying_every_frame_is_a_keyframe(builder, clips, probe):
    """x264 takes -g 1; x265 only listens through -x265-params."""
    h264 = builder.arguments_for(probe.probe(clips["film24"]))
    h265 = builder.arguments_for(probe.probe(clips["h265"]))

    assert "-g" in h264 and h264[h264.index("-g") + 1] == "1"
    assert "-x265-params" in h265
    assert "keyint=1" in h265[h265.index("-x265-params") + 1]


def test_the_pixel_format_is_carried_across(builder, clips, probe):
    """So a 10-bit source is not quietly flattened to 8-bit on the way out."""
    source = probe.probe(clips["film24"]).model_copy(update={"pixel_format": "yuv422p10le"})
    arguments = builder.arguments_for(source)

    assert arguments[arguments.index("-pix_fmt") + 1] == "yuv422p10le"


def test_the_timeout_scales_with_the_source(builder, clips, probe):
    """A fixed one would abandon a long job or let a hung one block the app."""
    short = probe.probe(clips["film24"])
    long = short.model_copy(update={"frame_count": 24 * 60 * 60})  # an hour

    assert builder._timeout_for(long) > builder._timeout_for(short)
    assert builder._timeout_for(short) >= 600.0


# --- BUILDING ---


@needs_ffmpeg
def test_every_frame_of_the_mezzanine_is_a_keyframe(builder, probe, clips, tmp_path):
    """
    The reason this stage exists. Without it a seek either snaps to the
    nearest keyframe — the wrong frame — or decodes from the start every time.
    """
    source = probe.probe(clips["film24"])
    output = tmp_path / "film24_mezzanine.mov"

    builder.build(source, output)
    flags = keyframe_flags(output)

    print(f"{len(flags)} frames, {sum(flags)} of them keyframes")
    assert len(flags) == source.frame_count
    assert all(flags), "a non-keyframe is a frame a seek cannot land on exactly"


@needs_ffmpeg
def test_the_source_itself_is_not_all_intra(clips):
    """
    The control for the test above: if the generated clips happened to be
    all-intra already, it would pass without the mezzanine doing anything.
    """
    flags = keyframe_flags(clips["film24"])

    assert not all(flags), "the source should be long-GOP, or the mezzanine proves nothing"


@needs_ffmpeg
def test_the_mezzanine_matches_the_source_frame_for_frame(builder, probe, clips, tmp_path):
    source = probe.probe(clips["ntsc24"])
    output = tmp_path / "ntsc24_mezzanine.mov"

    builder.build(source, output)
    mezzanine = probe.probe(output)

    assert mezzanine.frame_count == source.frame_count
    assert (mezzanine.width, mezzanine.height) == (source.width, source.height)
    assert (mezzanine.fps_numerator, mezzanine.fps_denominator) == (24000, 1001)


@needs_ffmpeg
def test_audio_survives_the_mezzanine_as_a_copy(builder, probe, clips, tmp_path):
    """Copied rather than re-encoded: a second lossy generation buys nothing."""
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "with_audio_mezzanine.mp4"

    builder.build(source, output)
    mezzanine = probe.probe(output)

    assert mezzanine.audio is not None
    assert mezzanine.audio.codec == source.audio.codec


@needs_ffmpeg
def test_a_silent_source_is_not_an_error(builder, probe, clips, tmp_path):
    """The audio map is optional, so a mute source builds like any other."""
    source = probe.probe(clips["film24"])
    output = tmp_path / "silent_mezzanine.mov"

    builder.build(source, output)

    assert probe.probe(output).audio is None


# --- VERIFICATION ---


@needs_ffmpeg
def test_verify_accepts_a_good_mezzanine(builder, probe, clips, tmp_path):
    source = probe.probe(clips["pal25"])
    output = tmp_path / "pal25_mezzanine.mov"
    builder.build(source, output)

    assert builder.verify(source, output) is True


@needs_ffmpeg
def test_verify_rejects_a_mezzanine_of_the_wrong_length(builder, probe, clips, tmp_path):
    """
    The failure that matters: a mezzanine a frame short would put every seed
    frame and every landmark on the wrong picture, silently.
    """
    source = probe.probe(clips["pal25"])
    output = tmp_path / "pal25_mezzanine.mov"
    builder.build(source, output)

    claiming_more = source.model_copy(update={"frame_count": source.frame_count + 1})
    assert builder.verify(claiming_more, output) is False


@needs_ffmpeg
def test_verify_rejects_the_wrong_size(builder, probe, clips, tmp_path):
    source = probe.probe(clips["pal25"])
    output = tmp_path / "pal25_mezzanine.mov"
    builder.build(source, output)

    resized = source.model_copy(update={"width": 1920, "height": 1080})

    assert builder.verify(resized, output) is False
    assert output.is_file(), "the mezzanine is fine; it is the claim about it that is wrong"


@needs_ffmpeg
def test_verify_rejects_a_mezzanine_that_was_never_written(builder, probe, clips, tmp_path):
    """An encode that failed leaves nothing, and nothing must not read as a match."""
    source = probe.probe(clips["film24"])

    assert builder.verify(source, tmp_path / "nothing_here.mov") is False
