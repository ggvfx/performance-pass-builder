"""
Writing a Deliverable.

A `FrameWriter` that also carries the source's audio, which is what makes an
output a deliverable rather than a picture.

**New work. minicut has no counterpart**: it stream-copies whole shots and
never has to reunite frames it rebuilt with audio it did not touch.

The audio is muxed in the same pass as the picture — one ffmpeg, two inputs:
frames arriving on stdin, and the source file supplying its own audio stream.
A second muxing pass would mean writing the video twice.

Three formats, and mp4 is preferred for two of them because these files go to
generation software and compositors, which all open mp4. h264 is the safe
default; h265 is the same container at better quality for the size, for
anything that takes it. The two alpha formats in a .mov are the
exception, and only because no mp4 codec carries alpha in a form a compositor
can be relied on to open. QuickTime RLE is the default of those: lossless,
and about fifty times smaller than ProRes on line art over nothing.
"""

import logging
from fractions import Fraction
from pathlib import Path

from src.core.config import (
    ALPHA_RLE_ENCODER,
    ALPHA_RLE_PIXEL_FORMAT,
    FALLBACK_AUDIO_BITRATE,
    FALLBACK_AUDIO_CODEC,
    H264_CRF,
    H264_PRESET,
    H265_CRF,
    H265_PRESET,
    H265_TAG,
    PRORES_ENCODER,
    PRORES_PIXEL_FORMAT,
    PRORES_PROFILE,
)
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling, OutputFormat, SourceInfo
from src.media.frames import RGB, RGBA, FrameWriter


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
        output_format: OutputFormat = OutputFormat.H264,
    ):
        """
        Args:
            toolchain: The shared toolchain.
            path: Where the deliverable is written. Its suffix should match
                the format — `OutputFormat.suffix` says which.
            source: The probed source — its geometry sizes the frames, and
                its file supplies the audio.
            include_audio: Whether to carry the audio at all.
            output_format: H264 for a normal pass, PRORES_4444 to keep alpha.
        """
        super().__init__(
            toolchain,
            path,
            source.width,
            source.height,
            Fraction(source.fps_numerator, source.fps_denominator),
            pixel_format=RGBA if output_format.carries_alpha else RGB,
        )
        self.source = source
        self.output_format = output_format
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

    def video_output_arguments(self) -> list[str]:
        """
        How the picture is encoded, which the format decides.

        Notes:
            ProRes 4444 rather than h264 when alpha is wanted, because h264
            cannot carry it at all — a mesh exported as h264 would arrive in
            a compositor burned onto black, which is the opposite of useful.

            `+faststart` is an mp4 thing and is left off the .mov.
        """
        if self.output_format is OutputFormat.ALPHA_RLE:
            return ["-c:v", ALPHA_RLE_ENCODER, "-pix_fmt", ALPHA_RLE_PIXEL_FORMAT]

        if self.output_format is OutputFormat.PRORES_4444:
            return [
                "-c:v", PRORES_ENCODER,
                "-profile:v", PRORES_PROFILE,
                "-pix_fmt", PRORES_PIXEL_FORMAT,
            ]

        if self.output_format is OutputFormat.H265:
            return [
                "-c:v", "libx265",
                "-preset", H265_PRESET,
                "-crf", str(H265_CRF),
                "-tag:v", H265_TAG,
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
            ]

        return [
            "-c:v", "libx264",
            "-preset", H264_PRESET,
            "-crf", str(H264_CRF),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]

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
