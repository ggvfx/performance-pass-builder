"""
Tests for Output Validation.

This is the stage that blocks. So what matters is not that it passes a good
file — it is that it refuses a bad one, and says which of them it is in terms
a person can act on.

Every failure here is one that would otherwise reach a generation model as a
pass that drifts, with nothing to explain why.
"""

import shutil
from fractions import Fraction

import numpy as np
import pytest

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling
from src.media.encode import OutputWriter
from src.media.frames import FrameReader, FrameWriter
from src.media.probe import SourceProbe
from src.performance.validator import (
    CHECK_AUDIO,
    CHECK_FRAME_COUNT,
    CHECK_FRAME_RATE,
    OutputValidator,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

CAPTURED_FRAMEMD5 = """#format: frame checksums
#version: 2
#hash: MD5
#tb 0: 1/25
0,          0,          0,        1,   115200, d41d8cd98f00b204e9800998ecf8427e
0,          1,          1,        1,   115200, 7f2b8c1e9a0d4f6b3c5e8a1d2f4b6c8e
0,          2,          2,        1,   115200, 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
"""


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="module")
def probe(toolchain) -> SourceProbe:
    return SourceProbe(toolchain)


@pytest.fixture(scope="module")
def validator(toolchain) -> OutputValidator:
    return OutputValidator(toolchain)


def copy_through(toolchain, source, output, include_audio=True) -> OutputWriter:
    """A correct deliverable: every frame of the source, written back out."""
    with FrameReader.for_source(toolchain, source) as reader:
        with OutputWriter(toolchain, output, source, include_audio=include_audio) as writer:
            for frame in reader:
                writer.write(frame)
    return writer


# --- PARSING ---


def test_hashes_are_pulled_out_in_order():
    """One per frame, the hash last on the row, comments skipped."""
    hashes = OutputValidator.parse_framemd5(CAPTURED_FRAMEMD5)

    assert len(hashes) == 3
    assert hashes[0] == "d41d8cd98f00b204e9800998ecf8427e"
    assert all(not h.startswith("#") for h in hashes)


def test_no_hashes_from_empty_output():
    assert OutputValidator.parse_framemd5("") == []


# --- AUDIO CLAIMS ---


def test_an_output_claiming_copied_audio_must_have_some(probe, clips, validator):
    """A silent file that claims to carry audio is the failure this catches."""
    mute = probe.probe(clips["film24"])

    ok, failure = validator.check_audio(mute, AudioHandling.COPIED)

    assert ok is False
    assert "no audio stream" in failure


def test_an_output_claiming_omitted_audio_must_have_none(probe, clips, validator):
    """
    The privacy case. "We did not add it" and "it is not there" are different
    claims, and only one of them is checkable — so this checks it.
    """
    with_sound = probe.probe(clips["with_audio"])

    ok, failure = validator.check_audio(with_sound, AudioHandling.OMITTED)

    assert ok is False
    assert "meant not to" in failure


def test_a_mute_source_and_a_mute_output_agree(probe, clips, validator):
    mute = probe.probe(clips["film24"])

    assert validator.check_audio(mute, AudioHandling.NONE) == (True, None)


def test_a_carried_stream_satisfies_both_carrying_claims(probe, clips, validator):
    with_sound = probe.probe(clips["with_audio"])

    for claim in (AudioHandling.COPIED, AudioHandling.ENCODED):
        assert validator.check_audio(with_sound, claim) == (True, None), claim


# --- THE WHOLE VERDICT ---


@needs_ffmpeg
def test_a_correct_deliverable_passes(toolchain, probe, clips, validator, tmp_path):
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "good.mp4"
    writer = copy_through(toolchain, source, output)

    result = validator.validate(source, output, writer.audio_handling)

    print(result.checks)
    assert result.passed is True
    assert result.failures == []


@needs_ffmpeg
def test_a_short_output_is_refused_and_says_by_how_much(toolchain, probe, clips, validator, tmp_path):
    """
    The failure the whole project exists to prevent. The message has to carry
    the number, because "it drifted" is not something anyone can act on.
    """
    source = probe.probe(clips["film24"])
    output = tmp_path / "short.mp4"
    rate = Fraction(source.fps_numerator, source.fps_denominator)

    with FrameWriter(toolchain, output, source.width, source.height, rate) as writer:
        for _ in range(source.frame_count - 3):
            writer.write(np.zeros((source.height, source.width, 3), dtype=np.uint8))

    result = validator.validate(source, output, AudioHandling.NONE)

    assert result.passed is False
    assert result.checks[CHECK_FRAME_COUNT] is False
    assert "3 shorter" in result.failures[0]
    assert "drift" in result.failures[0]


@needs_ffmpeg
def test_a_wrong_frame_rate_is_refused(toolchain, probe, clips, validator, tmp_path):
    """24000/1001 written as 25 keeps every frame and still drifts."""
    source = probe.probe(clips["ntsc24"])
    output = tmp_path / "wrong_rate.mp4"

    with FrameWriter(toolchain, output, source.width, source.height, Fraction(25, 1)) as writer:
        for _ in range(source.frame_count):
            writer.write(np.zeros((source.height, source.width, 3), dtype=np.uint8))

    result = validator.validate(source, output, AudioHandling.NONE)

    assert result.passed is False
    assert result.checks[CHECK_FRAME_RATE] is False


@needs_ffmpeg
def test_a_missing_file_is_a_failure_not_a_crash(probe, clips, validator, tmp_path):
    source = probe.probe(clips["film24"])

    result = validator.validate(source, tmp_path / "never_written.mp4", AudioHandling.NONE)

    assert result.passed is False
    assert "Nothing was written" in result.failures[0]


@needs_ffmpeg
def test_dropped_audio_is_caught_by_the_whole_verdict(toolchain, probe, clips, validator, tmp_path):
    """
    An output written without audio, then validated as though it carried it.
    That is what a silently broken mux would look like.
    """
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "no_audio.mp4"
    copy_through(toolchain, source, output, include_audio=False)

    result = validator.validate(source, output, AudioHandling.COPIED)

    assert result.passed is False
    assert result.checks[CHECK_AUDIO] is False


def test_a_result_with_no_checks_is_not_a_pass():
    """`all([])` is True, so an unchecked job would otherwise sail through."""
    from src.core.models import ValidationResult

    assert ValidationResult().passed is False


# --- WHAT THE PIXELS SAY ---


@needs_ffmpeg
def test_identical_files_hash_identically(toolchain, probe, clips, validator, tmp_path):
    source = probe.probe(clips["film24"])
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    copy_through(toolchain, source, first, include_audio=False)
    shutil.copy(first, second)

    assert validator.compare_frames(first, second) == (True, None)


@needs_ffmpeg
def test_a_different_picture_is_caught_even_at_the_right_length(
    toolchain, probe, clips, validator, tmp_path
):
    """
    The case metadata cannot reach: a hosted model returning a file of the
    right length, at the right rate, that is the wrong picture. Non-negotiable
    2 — the depth is checked on arrival, never trusted.
    """
    source = probe.probe(clips["film24"])
    original = tmp_path / "original.mp4"
    copy_through(toolchain, source, original, include_audio=False)

    flat = tmp_path / "flat.mp4"
    rate = Fraction(source.fps_numerator, source.fps_denominator)
    with FrameWriter(toolchain, flat, source.width, source.height, rate) as writer:
        for _ in range(source.frame_count):
            writer.write(np.zeros((source.height, source.width, 3), dtype=np.uint8))

    same, failure = validator.compare_frames(original, flat)

    assert same is False
    assert "frame 0" in failure


@needs_ffmpeg
def test_a_dropped_frame_is_named_by_number(toolchain, probe, clips, validator, tmp_path):
    """That number points straight at where it went wrong."""
    source = probe.probe(clips["film24"])
    full = tmp_path / "full.mp4"
    copy_through(toolchain, source, full, include_audio=False)

    short = tmp_path / "short.mp4"
    rate = Fraction(source.fps_numerator, source.fps_denominator)
    with FrameReader.for_source(toolchain, source) as reader:
        with FrameWriter(toolchain, short, source.width, source.height, rate) as writer:
            for index, frame in enumerate(reader):
                if index != 10:  # one frame quietly missing from the middle
                    writer.write(frame)

    same, failure = validator.compare_frames(full, short)

    assert same is False
    assert "1 fewer than" in failure
