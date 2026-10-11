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
from src.media.frames import (
    RGB,
    RGBA,
    FrameReader,
    FrameWriter,
    frame_size_bytes,
    frames_backwards,
    seek_seconds,
)
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


# --- SEEKING ---


@pytest.fixture(scope="module")
def intra(toolchain, probe, clips, tmp_path_factory):
    """
    A mezzanine and its probed source, built once.

    Seeking is only exact on an all-intra file, so every test below needs
    one. `testsrc` draws a different picture every frame, which is what makes
    "did the seek land on the right frame" answerable by hash.
    """
    from src.media.mezzanine import MezzanineBuilder

    source = probe.probe(clips["film24"])
    path = MezzanineBuilder(toolchain).build(
        source, tmp_path_factory.mktemp("intra") / "m.mov"
    )
    return probe.probe(path), path


def frame_hashes(toolchain, source, path, **extra):
    """Short hashes of each frame a reader hands back."""
    import hashlib

    with FrameReader.for_source(toolchain, source, path=path, **extra) as reader:
        return [hashlib.md5(frame.tobytes()).hexdigest()[:12] for frame in reader]


@needs_ffmpeg
def test_a_seek_lands_on_exactly_the_frame_asked_for(toolchain, intra):
    """
    The one that matters. A seek landing a frame early would put every
    landmark after it on the wrong picture, and nothing downstream could
    tell — the track would simply be subtly wrong.
    """
    source, path = intra
    every = frame_hashes(toolchain, source, path)

    for wanted in (0, 1, 17, 30, source.frame_count - 1):
        got = frame_hashes(toolchain, source, path, start_frame=wanted, max_frames=1)

        assert got == [every[wanted]], f"seeking to {wanted} landed somewhere else"


@needs_ffmpeg
def test_a_seek_reads_on_from_there(toolchain, intra):
    source, path = intra
    every = frame_hashes(toolchain, source, path)

    assert frame_hashes(toolchain, source, path, start_frame=40) == every[40:]


@needs_ffmpeg
def test_a_frame_limit_stops_where_it_is_told(toolchain, intra):
    source, path = intra
    every = frame_hashes(toolchain, source, path)

    assert frame_hashes(toolchain, source, path, start_frame=10, max_frames=5) == every[10:15]


def test_seeking_without_a_rate_is_refused(toolchain, clips):
    """
    A frame number cannot become a time without one, and guessing a rate is
    how a seek ends up on the wrong frame.
    """
    with pytest.raises(ValueError, match="exact rate"):
        FrameReader(toolchain, clips["film24"], 320, 240, start_frame=10)


def test_a_seek_time_comes_from_the_exact_rate():
    """At 24000/1001 frame 24 is 1.001 seconds, not 1.0."""
    assert seek_seconds(24, Fraction(24, 1)) == "1.000000"
    assert seek_seconds(24, Fraction(24000, 1001)) == "1.001000"
    assert seek_seconds(0, Fraction(24, 1)) == "0.000000"


# --- ALPHA ---


@needs_ffmpeg
def test_partial_alpha_survives_a_write(toolchain, tmp_path):
    """
    The bug this guards. The writer used to force `yuv420p` whatever
    arrived, so RGBA frames went in and an opaque video came out with
    nothing failing — a mesh layer written that way composites as a solid
    rectangle over everything beneath it.

    It has to be *partial* alpha. A layer that is fully opaque reads back
    identically whether the channel survived or not, which is exactly why
    the test that existed did not catch this.
    """
    import numpy as np

    width, height, frames = 64, 48, 4
    path = tmp_path / "mesh.mov"

    frame = np.zeros((height, width, 4), dtype=np.uint8)
    frame[:, :, 0] = 255          # red
    frame[:, :16, 3] = 0          # transparent stripe
    frame[:, 16:32, 3] = 128      # half-transparent stripe
    frame[:, 32:, 3] = 255        # opaque

    with FrameWriter(
        toolchain, path, width, height, Fraction(24, 1), codec="qtrle", pixel_format=RGBA
    ) as writer:
        for _ in range(frames):
            writer.write(frame)

    with FrameReader(toolchain, path, width, height, RGBA) as reader:
        back = next(iter(reader))

    print(f"alpha came back as {sorted(set(back[0, ::16, 3].tolist()))}")
    assert int(back[0, 8, 3]) == 0, "the transparent stripe came back opaque"
    assert 120 <= int(back[0, 20, 3]) <= 136, "the half-transparent stripe was flattened"
    assert int(back[0, 50, 3]) == 255


def test_alpha_frames_through_a_codec_that_cannot_hold_them_is_refused(toolchain, tmp_path):
    """
    Silently flattening would be the same bug wearing a different hat, and
    h264 is the default codec — so this is the easy mistake to make.
    """
    writer = FrameWriter(
        toolchain, tmp_path / "x.mp4", 64, 48, Fraction(24, 1), pixel_format=RGBA
    )

    with pytest.raises(ValueError, match="cannot carry alpha"):
        writer.video_output_arguments()


def test_a_pixel_format_knows_whether_it_has_alpha():
    assert RGBA.carries_alpha is True
    assert RGB.carries_alpha is False


# --- BACKWARDS ---


@needs_ffmpeg
def test_backwards_hands_back_every_frame_in_reverse(toolchain, intra):
    source, path = intra

    seen = list(frames_backwards(toolchain, source, source.frame_count - 1, path=path))

    assert [index for index, _ in seen] == list(range(source.frame_count - 1, -1, -1))


@needs_ffmpeg
def test_every_frame_read_backwards_is_the_right_picture(toolchain, intra):
    """
    Reverse order is not the same claim as right frames. This checks the
    picture, by hash, against the forward read.
    """
    source, path = intra
    import hashlib

    every = frame_hashes(toolchain, source, path)

    for index, frame in frames_backwards(toolchain, source, source.frame_count - 1, path=path):
        got = hashlib.md5(frame.tobytes()).hexdigest()[:12]
        assert got == every[index], f"frame {index} read backwards is a different picture"


@needs_ffmpeg
def test_backwards_is_still_correct_across_several_windows(toolchain, intra):
    """
    The window is a memory ceiling, not a correctness boundary. A budget of
    five frames forces ten windows over this clip, and the seams between them
    are where an off-by-one would live.
    """
    source, path = intra
    budget = frame_size_bytes(source.width, source.height) * 5

    seen = list(
        frames_backwards(
            toolchain, source, source.frame_count - 1, path=path, budget_bytes=budget
        )
    )

    assert [index for index, _ in seen] == list(range(source.frame_count - 1, -1, -1))


@needs_ffmpeg
def test_backwards_can_stop_part_way_down(toolchain, intra):
    """Tracking back from a seed stops at frame 0 of the segment, not the clip."""
    source, path = intra

    seen = list(frames_backwards(toolchain, source, 20, first_frame=10, path=path))

    assert [index for index, _ in seen] == list(range(20, 9, -1))


@needs_ffmpeg
def test_one_frame_backwards_is_a_valid_run(toolchain, intra):
    """A seed on frame 0 asks for exactly this, and it must not be an error."""
    source, path = intra

    seen = list(frames_backwards(toolchain, source, 0, first_frame=0, path=path))

    assert [index for index, _ in seen] == [0]


def test_an_empty_backward_range_is_refused(toolchain, probe, clips):
    source = probe.probe(clips["film24"])

    with pytest.raises(ValueError, match="is empty"):
        list(frames_backwards(toolchain, source, 5, first_frame=10))


def test_a_backward_range_outside_the_source_is_refused(toolchain, probe, clips):
    """Asking past the end would read nothing and look like a short clip."""
    source = probe.probe(clips["film24"])

    with pytest.raises(ValueError, match="outside"):
        list(frames_backwards(toolchain, source, source.frame_count))


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
        pipe = reader._pipe

    assert pipe.is_running is False, "ffmpeg is still running after the reader closed"


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
