"""
Writing a Deliverable.

A `FrameWriter` that also carries the source's audio, which is what makes an
output a deliverable rather than a picture.

**New work. minicut has no counterpart**: it stream-copies whole shots and
never has to reunite frames it rebuilt with audio it did not touch.

The audio is muxed in the same pass as the picture — one ffmpeg, two inputs:
frames arriving on stdin, and the source file supplying its own audio stream.
A second muxing pass would mean writing the video twice.
"""

import logging
from fractions import Fraction
from pathlib import Path

from src.core.config import FALLBACK_AUDIO_BITRATE, FALLBACK_AUDIO_CODEC
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling, SourceInfo
from src.media.frames import FrameWriter


def plan_audio(source: SourceInfo, include_audio: bool) -> AudioHandling:
    """
    What will happen to the audio, decided before the encode rather than
    discovered during it.

    Args:
        source: The probed source, which knows whether its codec fits.
        include_audio: The artist's choice. CLAUDE.md non-negotiable 3 —
            when audio is carried it is carried untouched, but whether to
            carry it is theirs to decide.

    Returns:
        The handling, which is also what the sidecar records.
    """
    if not include_audio:
        return AudioHandling.OMITTED
    if source.audio is None:
        return AudioHandling.NONE
    if source.audio.can_stream_copy_to_mp4:
        return AudioHandling.COPIED
    return AudioHandling.ENCODED


class OutputWriter(FrameWriter):
    """
    Writes one deliverable: composited frames in, a playable file out.

    Notes:
        The audio decision is made in `plan_audio` and exposed as
        `audio_handling`, so the sidecar records what actually happened rather
        than what was asked for. Those differ whenever a source's codec will
        not fit the container.
    """

    def __init__(
        self,
        toolchain: MediaToolchain,
        path: Path,
        source: SourceInfo,
        include_audio: bool = True,
        **frame_writer_arguments,
    ):
        """
        Args:
            toolchain: The shared toolchain.
            path: Where the deliverable is written.
            source: The probed source — its geometry sizes the frames, and
                its file supplies the audio.
            include_audio: Whether to carry the audio at all.
            **frame_writer_arguments: codec, crf, preset.
        """
        super().__init__(
            toolchain,
            path,
            source.width,
            source.height,
            Fraction(source.fps_numerator, source.fps_denominator),
            **frame_writer_arguments,
        )
        self.source = source
        self.audio_handling = plan_audio(source, include_audio)

    @property
    def carries_audio(self) -> bool:
        """Whether this output will have an audio stream at all."""
        return self.audio_handling in (AudioHandling.COPIED, AudioHandling.ENCODED)

    def audio_arguments(self) -> list[str]:
        """
        The input, the mapping and the codec for the audio.

        Notes:
            Copied where the container will take it, so lip sync in the
            generation is driven by exactly what was recorded. Where it will
            not — 24-bit PCM off a camera being the usual case — it is
            encoded **once**, at a high bitrate, and the sidecar says so.
        """
        if not self.carries_audio:
            # Explicit rather than implied. Leaving it out would let ffmpeg
            # pick up a stream from a later input if one were ever added.
            return ["-an"]

        arguments = ["-i", str(self.source.path), "-map", "1:a:0"]

        if self.audio_handling is AudioHandling.COPIED:
            return [*arguments, "-c:a", "copy"]

        return [*arguments, "-c:a", FALLBACK_AUDIO_CODEC, "-b:a", FALLBACK_AUDIO_BITRATE]

    def arguments(self) -> list[str]:
        """
        One ffmpeg, two inputs: frames on stdin, audio from the source.

        Notes:
            `-map 0:v:0` has to be explicit once there is a second input, or
            ffmpeg picks streams by its own rules and may take the source's
            picture instead of the frames being piped in — which would
            silently deliver the original footage.

            `-shortest` is deliberately NOT used. It would quietly trim the
            picture to the audio, and a pass that is not exactly the source's
            length is the one thing this project will not deliver. If the two
            disagree, the validator is where that surfaces.
        """
        return [
            "-v", "error",
            *self.frame_input_arguments(),
            *self.audio_arguments(),
            "-map", "0:v:0",
            *self.video_output_arguments(),
            "-y",
            str(self.path),
        ]

    def close(self, abandon: bool = False) -> None:
        super().close(abandon=abandon)
        if not abandon:
            logging.info(f"Audio for {self.path.name}: {self.audio_handling.value}")
