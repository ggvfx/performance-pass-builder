"""
All-Intra Mezzanine Creation.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Re-encodes the source once into the same codec it arrived in, but with every
frame a keyframe.

**minicut needs this so a stream copy lands on the right frame. This project
never stream-copies picture, so that reason does not carry over. It is here
for a different one: frame-accurate random access.**

Tracking is iterative. A person scrubs to frame 500, draws a box, tracks
forward, sees the track break at 700, scrubs back and re-seeds. Every one of
those is an arbitrary seek, and long-GOP h264 offers only two bad options:
`-ss` before `-i` is instant but snaps to a keyframe, which is the wrong
frame; `-ss` after `-i` is exact but decodes from the start every time, which
gets slower the further into the shot you work. All-intra makes a seek both
exact and instant, which is what makes re-seeding usable rather than merely
possible.

That costs one re-encode generation, which is why the quality setting is
deliberately transparent.
"""

import logging
from fractions import Fraction
from pathlib import Path

from src.core.config import (
    ENCODE_TIMEOUT_FACTOR,
    MEZZANINE_CRF,
    MEZZANINE_ENCODERS,
    MEZZANINE_PRESET,
    MINIMUM_ENCODE_TIMEOUT,
)
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import SourceInfo
from src.media.probe import SourceProbe

# --- ENCODER SETTINGS ---

# Every frame a keyframe. x264 takes -g 1; x265 wants it through -x265-params.
INTRA_ARGUMENTS = {
    "libx264": ["-g", "1"],
    "libx265": ["-x265-params", "keyint=1"],
}

# Take the first video stream and any audio, and nothing else. The "?" makes
# audio optional, so a silent source is not an error. Data streams such as a
# timecode track are deliberately left behind: the start timecode travels in
# SourceInfo, and a stray stream only complicates things later.
STREAM_MAPPING = ["-map", "0:v:0", "-map", "0:a?"]

# Audio is copied, not re-encoded. It is already what the user gave us, and a
# second generation of lossy audio would buy nothing. Whether it reaches a
# deliverable at all is decided at output time, not here.
AUDIO_ARGUMENTS = ["-c:a", "copy"]


class MezzanineBuilder:
    """
    Builds and verifies the all-intra copy every pass reads.

    The encoder is not configurable: it follows the source codec, so the
    mezzanine is the source in all respects but its keyframe interval.
    """

    def __init__(self, toolchain: MediaToolchain):
        self.toolchain = toolchain

    # --- ENCODER SELECTION ---

    @staticmethod
    def encoder_for(source: SourceInfo) -> str:
        """
        The encoder that writes an all-intra version of this source.

        Raises:
            ValueError: If the source codec is not one we can reproduce.
                Better to say so than to work from a mezzanine in a different
                format from the source it claims to represent.
        """
        encoder = MEZZANINE_ENCODERS.get(source.codec)
        if encoder is None:
            supported = ", ".join(sorted(MEZZANINE_ENCODERS))
            raise ValueError(f"Cannot re-encode {source.codec!r}; supported codecs are {supported}")
        return encoder

    def arguments_for(self, source: SourceInfo) -> list[str]:
        """
        The encoding arguments for a source.

        Pixel format is carried across explicitly so a 10-bit source is not
        quietly flattened to 8-bit on the way out.
        """
        encoder = self.encoder_for(source)

        return [
            "-c:v", encoder,
            "-preset", MEZZANINE_PRESET,
            "-crf", str(MEZZANINE_CRF),
            *INTRA_ARGUMENTS[encoder],
            "-pix_fmt", source.pixel_format,
        ]

    # --- TRANSCODE ---

    def build(self, source: SourceInfo, output_path: Path) -> Path:
        """
        Writes an all-intra copy of the source, at full frame.

        Args:
            source: Probed source information.
            output_path: Where the mezzanine is written. Its extension should
                match the source container.

        Returns:
            Path to the mezzanine.

        Raises:
            ValueError: If the source codec cannot be reproduced.
            RuntimeError: If ffmpeg fails, or the result does not match the
                source. A mezzanine one frame short would put every seed frame
                and every landmark on the wrong picture.
        """
        source_path = Path(source.path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command = [
            "-y",
            "-i", str(source_path),
            *STREAM_MAPPING,
            *self.arguments_for(source),
            *AUDIO_ARGUMENTS,
            str(output_path),
        ]

        logging.info(f"Building mezzanine for {source_path.name} at {output_path}")
        result = self.toolchain.run_ffmpeg(command, timeout=self._timeout_for(source))

        if result.returncode != 0:
            # ffmpeg's own last words are far more useful than ours
            reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
            raise RuntimeError(f"Could not build a mezzanine for {source_path.name}: {reason}")

        if not self.verify(source, output_path):
            raise RuntimeError(
                f"The mezzanine for {source_path.name} does not match its source. "
                f"Everything downstream assumes frame N of one is frame N of the other."
            )

        return output_path

    @staticmethod
    def _timeout_for(source: SourceInfo) -> float:
        """
        How long to allow the encode, scaled to the length of the source.

        A fixed timeout would either abandon a long job or let a hung one
        block the app for hours.
        """
        rate = Fraction(source.fps_numerator, source.fps_denominator)
        duration_seconds = float(source.frame_count / rate)

        return max(MINIMUM_ENCODE_TIMEOUT, duration_seconds * ENCODE_TIMEOUT_FACTOR)

    def verify(self, source: SourceInfo, mezzanine_path: Path) -> bool:
        """
        Confirms the mezzanine is a frame-for-frame match of the source.

        Checks frame count, resolution and frame rate. Called before anything
        is built on it, because every pass assumes frame N of the mezzanine is
        frame N of the source.

        Returns:
            True when it matches. Logs precisely which field differs when not.
        """
        if not mezzanine_path.is_file():
            logging.error(f"No mezzanine was written at {mezzanine_path}")
            return False

        mezzanine = SourceProbe(self.toolchain).probe(mezzanine_path)

        differences = []
        if mezzanine.frame_count != source.frame_count:
            differences.append(
                f"frame count {mezzanine.frame_count} against the source's {source.frame_count}"
            )
        if (mezzanine.width, mezzanine.height) != (source.width, source.height):
            differences.append(
                f"size {mezzanine.width}x{mezzanine.height} against "
                f"{source.width}x{source.height}"
            )

        source_rate = Fraction(source.fps_numerator, source.fps_denominator)
        mezzanine_rate = Fraction(mezzanine.fps_numerator, mezzanine.fps_denominator)
        if mezzanine_rate != source_rate:
            differences.append(f"frame rate {mezzanine_rate} against {source_rate}")

        if differences:
            logging.error(f"Mezzanine mismatch — {'; '.join(differences)}")
            return False

        return True
