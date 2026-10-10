"""
Output Validation.

The checks that decide whether a deliverable may be handed over. Any failure
blocks it; this stage never warns and continues.

The `framemd5` machinery is ported from minicut-shot-detector (6dcbd60) and
modernised for 3.12. Everything about shots was left behind — about two
thirds of that file — and what came across is the part that answers "is this
video, frame for frame, the picture I think it is".

Two kinds of check, cheapest first:

1. **What the container says** — frame count, frame rate, duration, and
   whether an audio stream is there. Reading metadata costs nothing and
   catches every ordinary failure.
2. **What the pixels say** — per-frame hashes, for the one case where the
   container can be right and the content wrong: depth arriving from a hosted
   model that dropped or duplicated a frame somewhere in the middle.

Notes:
    This module owns the frame-count rule. `FrameReader` counts frames and
    deliberately does not check them, so there is exactly one place that
    decides whether a length is acceptable.
"""

import logging
from fractions import Fraction
from pathlib import Path

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling, SourceInfo, ValidationResult
from src.media.probe import SourceProbe

# --- TIMEOUTS ---

# Hashing decodes every frame, so a feature-length source on a slow disk
# needs room. It is still far quicker than decoding in Python.
HASH_TIMEOUT = 1800.0

# --- CHECK NAMES ---

# Stable keys, recorded in the sidecar's validation block. Named rather than
# inlined so a sidecar from six months ago can still be read against today's
# checks, and so a renamed check is a visible change rather than a silent one.
CHECK_FRAME_COUNT = "frame_count"
CHECK_FRAME_RATE = "frame_rate"
CHECK_DURATION = "duration"
CHECK_AUDIO = "audio"
CHECK_FRAME_HASHES = "frame_hashes"


class OutputValidator:
    """
    Checks a deliverable against the source it was built from.

    Holds the toolchain so the probe and the hashes run through the same
    resolved binaries that produced the file.
    """

    def __init__(self, toolchain: MediaToolchain):
        self.toolchain = toolchain
        self.probe = SourceProbe(toolchain)

    # --- THE WHOLE VERDICT ---

    def validate(
        self,
        source: SourceInfo,
        output_path: Path,
        audio_handling: AudioHandling,
    ) -> ValidationResult:
        """
        Every metadata check on one deliverable.

        Args:
            source: What it was built from, and the only authority on length.
            output_path: The deliverable.
            audio_handling: What the encoder said it did, so the check can
                ask the right question — an absent stream is correct for
                `OMITTED` and a failure for `COPIED`.

        Returns:
            A ValidationResult. `passed` is derived from the checks, so it
            cannot claim a pass it did not get, and an empty set of checks is
            not a pass either.

        Notes:
            Frame hashes are not included. They cost a full decode of two
            files and only answer a question metadata cannot — see
            `compare_frames`, which the depth stage calls on arrival.
        """
        checks: dict[str, bool] = {}
        failures: list[str] = []

        if not output_path.exists():
            return ValidationResult(
                checks={CHECK_FRAME_COUNT: False},
                failures=[f"Nothing was written at {output_path}"],
            )

        written = self.probe.probe(output_path)

        # --- LENGTH ---

        checks[CHECK_FRAME_COUNT] = written.frame_count == source.frame_count
        if not checks[CHECK_FRAME_COUNT]:
            difference = written.frame_count - source.frame_count
            wording = "longer" if difference > 0 else "shorter"
            failures.append(
                f"{output_path.name} has {written.frame_count} frames, "
                f"{abs(difference)} {wording} than the source's {source.frame_count}. "
                f"A pass that is not exactly the source's length will drift."
            )

        # --- RATE ---

        source_rate = Fraction(source.fps_numerator, source.fps_denominator)
        written_rate = Fraction(written.fps_numerator, written.fps_denominator)

        checks[CHECK_FRAME_RATE] = written_rate == source_rate
        if not checks[CHECK_FRAME_RATE]:
            failures.append(
                f"{output_path.name} is {written_rate} fps against the source's "
                f"{source_rate}. Even a rounded rate drifts a frame over a long shot."
            )

        # --- DURATION ---

        # Derived from the frames and the exact rate at both ends rather than
        # read from the containers: frames are what a pass is made of, and a
        # container's own declared duration is advisory.
        checks[CHECK_DURATION] = (
            Fraction(written.frame_count) / written_rate
            == Fraction(source.frame_count) / source_rate
        )
        if not checks[CHECK_DURATION] and checks[CHECK_FRAME_COUNT] and checks[CHECK_FRAME_RATE]:
            # Only worth its own line when the count and rate both matched,
            # which would make this a genuinely separate fault rather than a
            # second symptom of one already reported.
            failures.append(f"{output_path.name} is a different duration from the source")

        # --- AUDIO ---

        checks[CHECK_AUDIO], audio_failure = self.check_audio(written, audio_handling)
        if audio_failure is not None:
            failures.append(audio_failure)

        result = ValidationResult(checks=checks, failures=failures)
        logging.info(
            f"Validated {output_path.name}: {'passed' if result.passed else 'FAILED'}"
            + (f" — {'; '.join(failures)}" if failures else "")
        )
        return result

    # --- AUDIO ---

    @staticmethod
    def check_audio(
        written: SourceInfo, audio_handling: AudioHandling
    ) -> tuple[bool, str | None]:
        """
        Whether the deliverable's audio is what the encoder claimed.

        Notes:
            Four claims, and the interesting one is `OMITTED`. An output with
            no audio could be a mute source, a deliberate omission, or a bug,
            and they look identical in the file — so the absence is asserted
            rather than assumed. For client audio that should not travel with
            a file, "we did not add it" and "it is not there" are different
            claims, and only one of them is checkable.
        """
        has_audio = written.audio is not None

        if audio_handling in (AudioHandling.OMITTED, AudioHandling.NONE):
            if has_audio:
                return False, (
                    f"audio was recorded as {audio_handling.value} but the output has "
                    f"an audio stream. It was meant not to."
                )
            return True, None

        if not has_audio:
            return False, (
                f"audio was recorded as {audio_handling.value} but the output has no "
                f"audio stream at all"
            )

        return True, None

    # --- WHAT THE PIXELS SAY ---

    def compare_frames(self, expected_path: Path, actual_path: Path) -> tuple[bool, str | None]:
        """
        Whether two videos are the same picture, frame for frame.

        Returns:
            (True, None) when identical, otherwise (False, a description
            naming the first frame that differs).

        Notes:
            For the case metadata cannot reach: a hosted depth model that
            dropped or duplicated a frame in the middle returns a file of the
            right length, at the right rate, that is wrong from that frame
            onward. The depth stage calls this on arrival — CLAUDE.md
            non-negotiable 2, which says the depth is checked and never
            trusted.

            Costs a full decode of both files, which is why it is not part of
            `validate`.
        """
        expected = self.frame_hashes(expected_path)
        actual = self.frame_hashes(actual_path)

        if len(expected) != len(actual):
            difference = len(actual) - len(expected)
            wording = "more than" if difference > 0 else "fewer than"
            return False, (
                f"{actual_path.name} has {len(actual)} frames, {abs(difference)} "
                f"{wording} {expected_path.name}'s {len(expected)} — frames were "
                f"dropped or duplicated"
            )

        for index, (left, right) in enumerate(zip(expected, actual)):
            if left != right:
                return False, (
                    f"frame {index} of {actual_path.name} does not match "
                    f"{expected_path.name}"
                )

        return True, None

    def frame_hashes(self, video_path: Path) -> list[str]:
        """
        Per-frame checksums of the decoded picture, in order.

        Raises:
            RuntimeError: ffmpeg could not read the file.

        Notes:
            Uses ffmpeg's framemd5 muxer rather than decoding in Python — far
            faster, and a hash of the decoded pixels, so an identical picture
            hashes identically whatever the container did to it.

            Video only. Audio is packetised rather than framed, so hashing it
            would report a difference on files that are in fact correct.
        """
        result = self.toolchain.run_ffmpeg(
            [
                "-i", str(video_path),
                "-map", "0:v:0",
                "-an",
                "-c:v", "rawvideo",
                "-f", "framemd5",
                "-",
            ],
            timeout=HASH_TIMEOUT,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Could not hash the frames of {video_path.name}")

        return self.parse_framemd5(result.stdout)

    @staticmethod
    def parse_framemd5(output: str) -> list[str]:
        """
        Pulls the hashes out of framemd5 output, one per frame in order.

        Rows look like "0, 0, 0, 1, 115200, d41d8cd98f00b204e9800998ecf8427e",
        with the hash last. Comment lines carry the header and are skipped.

        A static method so it can be tested against captured output without
        ffmpeg being installed.
        """
        return [
            line.split(",")[-1].strip()
            for line in output.splitlines()
            if line.strip() and not line.startswith("#")
        ]
