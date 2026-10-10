"""
Tests for Frame Streaming.

The whole project rests on this: every frame goes in, every frame comes out,
and the count is exact. A pass one frame short is a pass a generation model
drifts against — non-negotiable 2 — and this is the stage where a frame would
be lost.

Everything here runs against real ffmpeg pipes rather than mocks, because the
failure being guarded is ffmpeg's behaviour, not ours.
"""

import shutil
from fractions import Fraction

import numpy as np
import pytest

from src.core.ffmpeg_tools import MediaToolchain
from src.media.frames import FrameReader, FrameWriter, frame_size_bytes
from src.media.probe import SourceProbe

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="module")
def probe(toolchain) -> SourceProbe:
    return SourceProbe(toolchain)


# --- ARITHMETIC ---


def test_a_frame_is_three_bytes_a_pixel():
    """rgb24. If this is wrong every frame is misaligned, not merely wrong."""
    assert frame_size_bytes(320, 240) == 320 * 240 * 3
    assert frame_size_bytes(1920, 1080) == 6_220_800


# --- READING ---


@needs_ffmpeg
def test_every_frame_comes_out(toolchain, probe, clips):
    """The count the validator will later enforce has to be right here first."""
    source = probe.probe(clips["film24"])

    with FrameReader.for_source(toolchain, source) as reader:
        frames = list(reader)

    print(f"read {len(frames)} frames of an expected {source.frame_count}")
    assert len(frames) == source.frame_count
    assert reader.frames_read == source.frame_count


@needs_ffmpeg
def test_a_frame_is_the_shape_and_type_the_rest_of_the_app_expects(toolchain, probe, clips):
    source = probe.probe(clips["film24"])

    with FrameReader.for_source(toolchain, source) as reader:
        frame = reader.read()

    assert frame.shape == (source.height, source.width, 3)
    assert frame.dtype == np.uint8


@needs_ffmpeg
def test_the_frames_are_not_all_the_same(toolchain, probe, clips):
    """
    A pipe misreading its stride can still yield the right number of
    correctly shaped arrays. testsrc moves, so consecutive frames must differ.
    """
    source = probe.probe(clips["film24"])

    with FrameReader.for_source(toolchain, source) as reader:
        first = reader.read()
        second = reader.read()

    assert not np.array_equal(first, second), "two consecutive frames are identical"


@needs_ffmpeg
def test_the_end_of_the_video_is_none_not_an_error(toolchain, probe, clips):
    source = probe.probe(clips["film24"])

    with FrameReader.for_source(toolchain, source) as reader:
        for _ in range(source.frame_count):
            assert reader.read() is not None
        assert reader.read() is None


@needs_ffmpeg
def test_a_reader_can_read_the_mezzanine_instead_of_the_source(toolchain, probe, clips, tmp_path):
    """Which is what every pass actually does — the mezzanine is what they read."""
    from src.media.mezzanine import MezzanineBuilder

    source = probe.probe(clips["pal25"])
    mezzanine = MezzanineBuilder(toolchain).build(source, tmp_path / "m.mov")

    with FrameReader.for_source(toolchain, source, path=mezzanine) as reader:
        assert len(list(reader)) == source.frame_count


def test_a_reader_outside_a_context_manager_says_so(toolchain, clips):
    reader = FrameReader(toolchain, clips["film24"], 320, 240)

    with pytest.raises(RuntimeError, match="context manager"):
        reader.read()


@needs_ffmpeg
def test_abandoning_a_reader_part_way_does_not_leave_ffmpeg_running(toolchain, probe, clips):
    """
    The normal case, not an edge one: a caller often stops early. ffmpeg will
    not exit on its own while pushing frames into a pipe nobody is draining.
    """
    source = probe.probe(clips["film24"])

    with FrameReader.for_source(toolchain, source) as reader:
        reader.read()
        process = reader._process

    assert process.poll() is not None, "ffmpeg is still running after the reader closed"


# --- WRITING ---


@needs_ffmpeg
def test_every_frame_written_comes_back(toolchain, probe, clips, tmp_path):
    """The round trip the whole phase exists to guarantee."""
    source = probe.probe(clips["film24"])
    output = tmp_path / "round_trip.mp4"
    rate = Fraction(source.fps_numerator, source.fps_denominator)

    with FrameReader.for_source(toolchain, source) as reader:
        with FrameWriter(toolchain, output, source.width, source.height, rate) as writer:
            for frame in reader:
                writer.write(frame)

    written = probe.probe(output)
    print(f"{source.frame_count} in, {writer.frames_written} through, {written.frame_count} out")
    assert writer.frames_written == source.frame_count
    assert written.frame_count == source.frame_count


@needs_ffmpeg
def test_the_rate_survives_the_round_trip_as_an_exact_rational(toolchain, probe, clips, tmp_path):
    """
    24000/1001 in, 24000/1001 out. A writer that formatted the rate as 23.976
    would produce a file that drifts against its own source.
    """
    source = probe.probe(clips["ntsc24"])
    output = tmp_path / "ntsc_round_trip.mp4"
    rate = Fraction(source.fps_numerator, source.fps_denominator)

    with FrameReader.for_source(toolchain, source) as reader:
        with FrameWriter(toolchain, output, source.width, source.height, rate) as writer:
            for frame in reader:
                writer.write(frame)

    written = probe.probe(output)
    assert (written.fps_numerator, written.fps_denominator) == (24000, 1001)


@needs_ffmpeg
def test_what_went_in_is_what_comes_out(toolchain, tmp_path):
    """
    Not just the count. A flat colour survives h264 at crf 18, so a frame
    written as red that reads back as blue means the channel order is wrong —
    which no count check would ever notice.
    """
    output = tmp_path / "flat.mp4"
    red = np.zeros((64, 64, 3), dtype=np.uint8)
    red[:, :, 0] = 200

    with FrameWriter(toolchain, output, 64, 64, Fraction(25, 1)) as writer:
        for _ in range(10):
            writer.write(red)

    with FrameReader(toolchain, output, 64, 64) as reader:
        back = reader.read()

    print(f"wrote RGB(200,0,0), read back {tuple(back[32, 32])}")
    assert back[32, 32][0] > 150, "the red channel did not survive"
    assert back[32, 32][1] < 60 and back[32, 32][2] < 60, "channels are out of order"


@needs_ffmpeg
def test_a_frame_of_the_wrong_shape_is_refused(toolchain, tmp_path):
    """Caught here rather than becoming a smear from a misaligned pipe."""
    with FrameWriter(toolchain, tmp_path / "bad.mp4", 64, 64, Fraction(25, 1)) as writer:
        with pytest.raises(ValueError, match="expected"):
            writer.write(np.zeros((32, 32, 3), dtype=np.uint8))

        with pytest.raises(ValueError, match="uint8"):
            writer.write(np.zeros((64, 64, 3), dtype=np.float32))

        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))


def test_a_writer_outside_a_context_manager_says_so(toolchain, tmp_path):
    writer = FrameWriter(toolchain, tmp_path / "x.mp4", 64, 64, Fraction(25, 1))

    with pytest.raises(RuntimeError, match="context manager"):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))


@needs_ffmpeg
def test_an_error_mid_write_does_not_mask_itself(toolchain, tmp_path):
    """
    If the writer raised its own failure while unwinding, the original
    exception — the one that says what actually went wrong — would be lost.
    """
    output = tmp_path / "abandoned.mp4"

    with pytest.raises(ZeroDivisionError):
        with FrameWriter(toolchain, output, 64, 64, Fraction(25, 1)) as writer:
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
            raise ZeroDivisionError("something upstream went wrong")
