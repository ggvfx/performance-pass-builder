"""
Tests for Writing a Deliverable.

Three things have to hold, and the third is the one that would otherwise go
unnoticed: the picture is the frames that were piped in (not the source's own
picture, which is also an input), the audio is carried untouched when it is
carried, and an output asked to have no audio genuinely has none.

That last distinction matters because an output with no audio could be a mute
source, a deliberate omission, or a bug, and they look identical in the file.
"""

import shutil
import subprocess

import numpy as np
import pytest

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling
from src.media.encode import OutputWriter, plan_audio
from src.media.frames import FrameReader
from src.media.probe import SourceProbe

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture(scope="module")
def toolchain() -> MediaToolchain:
    return MediaToolchain()


@pytest.fixture(scope="module")
def probe(toolchain) -> SourceProbe:
    return SourceProbe(toolchain)


def write_all_frames(toolchain, source, output, include_audio=True) -> OutputWriter:
    """Reads every frame of a source and writes it straight back out."""
    with FrameReader.for_source(toolchain, source) as reader:
        with OutputWriter(toolchain, output, source, include_audio=include_audio) as writer:
            for frame in reader:
                writer.write(frame)
    return writer


# --- THE PLAN ---


@needs_ffmpeg
def test_aac_is_copied(probe, clips):
    """The normal path: untouched, so lip sync is driven by what was recorded."""
    assert plan_audio(probe.probe(clips["with_audio"]), include_audio=True) is AudioHandling.COPIED


@needs_ffmpeg
def test_pcm_is_encoded_because_the_container_will_not_hold_it(probe, clips):
    assert plan_audio(probe.probe(clips["pcm_audio"]), include_audio=True) is AudioHandling.ENCODED


@needs_ffmpeg
def test_a_mute_source_reports_none_rather_than_omitted(probe, clips):
    """
    Different claims. "There was none" and "you asked me to drop it" look the
    same in the file and must not look the same in the sidecar.
    """
    assert plan_audio(probe.probe(clips["film24"]), include_audio=True) is AudioHandling.NONE


@needs_ffmpeg
def test_asking_for_no_audio_reports_omitted(probe, clips):
    assert plan_audio(probe.probe(clips["with_audio"]), include_audio=False) is AudioHandling.OMITTED


# --- ARGUMENTS ---


@needs_ffmpeg
def test_the_video_mapping_is_explicit(toolchain, probe, clips, tmp_path):
    """
    With a second input, ffmpeg picks streams by its own rules — and could
    take the SOURCE's picture rather than the frames being piped in, which
    would silently deliver the original footage as the pass.
    """
    source = probe.probe(clips["with_audio"])
    writer = OutputWriter(toolchain, tmp_path / "out.mp4", source)

    arguments = writer.arguments()
    assert "-map" in arguments
    assert "0:v:0" in arguments, "the piped frames must be mapped explicitly"
    assert "1:a:0" in arguments, "the audio comes from the second input"


@needs_ffmpeg
def test_shortest_is_never_used(toolchain, probe, clips, tmp_path):
    """
    It would quietly trim the picture to the audio. A pass that is not
    exactly the source's length is the one thing this project will not
    deliver — if the two disagree, the validator is where that surfaces.
    """
    source = probe.probe(clips["with_audio"])
    writer = OutputWriter(toolchain, tmp_path / "out.mp4", source)

    assert "-shortest" not in writer.arguments()


@needs_ffmpeg
def test_dropping_audio_says_so_explicitly(toolchain, probe, clips, tmp_path):
    """`-an` rather than silence: leaving it implied lets a later input sneak one in."""
    source = probe.probe(clips["with_audio"])
    writer = OutputWriter(toolchain, tmp_path / "out.mp4", source, include_audio=False)

    assert "-an" in writer.arguments()
    assert writer.carries_audio is False


# --- REAL ENCODES ---


@needs_ffmpeg
def test_a_deliverable_keeps_the_frame_count_and_the_audio(toolchain, probe, clips, tmp_path):
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "with_audio_out.mp4"

    writer = write_all_frames(toolchain, source, output)
    written = probe.probe(output)

    assert writer.audio_handling is AudioHandling.COPIED
    assert written.frame_count == source.frame_count
    assert written.audio is not None
    assert written.audio.codec == "aac"


@needs_ffmpeg
def test_copied_audio_is_bit_for_bit_the_source_stream(toolchain, probe, clips, tmp_path):
    """
    Copied, not re-encoded. Comparing the decoded samples is what proves it:
    a re-encode at any bitrate would change them.
    """
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "copied.mp4"
    write_all_frames(toolchain, source, output)

    def samples(path) -> bytes:
        """Every audio sample, decoded, so a re-encode would change them."""
        process = toolchain.popen_ffmpeg(
            ["-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-ac", "1", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        decoded, _ = process.communicate()
        return decoded

    assert samples(output) == samples(source.path)


@needs_ffmpeg
def test_pcm_audio_is_re_encoded_rather_than_lost(toolchain, probe, clips, tmp_path):
    """
    The branch nothing else exercises. mp4 will not hold pcm_s24le, so the
    alternative to encoding it once is silently delivering a mute pass.
    """
    source = probe.probe(clips["pcm_audio"])
    output = tmp_path / "pcm_out.mp4"

    writer = write_all_frames(toolchain, source, output)
    written = probe.probe(output)

    assert writer.audio_handling is AudioHandling.ENCODED
    assert written.audio is not None
    assert written.audio.codec == "aac"
    assert written.frame_count == source.frame_count


@needs_ffmpeg
def test_an_output_asked_to_drop_audio_really_has_none(toolchain, probe, clips, tmp_path):
    """
    Checked, not assumed. For the privacy case — client audio that should not
    travel with a file — "we did not add it" and "it is not there" are
    different claims, and only one of them is verifiable.
    """
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "silent_out.mp4"

    writer = write_all_frames(toolchain, source, output, include_audio=False)
    written = probe.probe(output)

    assert writer.audio_handling is AudioHandling.OMITTED
    assert written.audio is None
    assert written.frame_count == source.frame_count


@needs_ffmpeg
def test_a_mute_source_produces_a_mute_deliverable_without_complaint(toolchain, probe, clips, tmp_path):
    source = probe.probe(clips["film24"])
    output = tmp_path / "mute_out.mp4"

    writer = write_all_frames(toolchain, source, output)

    assert writer.audio_handling is AudioHandling.NONE
    assert probe.probe(output).audio is None


@needs_ffmpeg
def test_the_picture_delivered_is_the_frames_that_were_piped_in(toolchain, probe, clips, tmp_path):
    """
    The silent failure this guards: with the source as a second input, a
    wrong mapping delivers the ORIGINAL footage and every count check still
    passes. Writing flat red proves which picture came out.
    """
    source = probe.probe(clips["with_audio"])
    output = tmp_path / "red_out.mp4"

    red = np.zeros((source.height, source.width, 3), dtype=np.uint8)
    red[:, :, 0] = 200

    with OutputWriter(toolchain, output, source) as writer:
        for _ in range(source.frame_count):
            writer.write(red)

    with FrameReader(toolchain, output, source.width, source.height) as reader:
        back = reader.read()

    print(f"centre pixel of the delivered picture: {tuple(back[source.height // 2, 10])}")
    assert back[source.height // 2, 10][0] > 150, "the delivered picture is not the frames written"
