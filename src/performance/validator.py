"""
Output Validation.

The checks that decide whether a deliverable may be handed over. Any failure
blocks it; this stage never warns and continues.

The `framemd5` machinery is ported from minicut-shot-detector (6dcbd60) and
modernised for 3.12. Everything about shots was left behind — about two
thirds of that file — and what came across is the part that answers "is this
video, frame for frame, the picture I think it is".

**What `validate` checks is metadata**: frame count, frame rate, duration,
and whether an audio stream is there. Reading it costs nothing and catches
every ordinary failure.

**What per-frame hashing checks is stalling.** minicut used it to prove
rejoined shots matched their mezzanine; this project has no round trip, and
depth cannot be hash-compared against its source because the two are not the
same picture. What it catches here is the failure a hosted model actually
produces — repeating a frame when it stalls — which metadata never will: the
file is the right length, at the right rate, and holds the same picture
twice.

A static shot legitimately repeats frames, so a repeat is only suspicious
when the **source** did not repeat there too. That is why the check takes
both files.

Notes:
    This module owns the frame-count rule. `FrameReader` counts frames and
    deliberately does not check them, so there is exactly one place that
    decides whether a length is acceptable.
"""

import logging
from fractions import Fraction
from pathlib import Path

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioHandling, FrameRange, SourceInfo, ValidationResult
from src.core.utils import runs_of_true
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
            Metadata only. Stalled frames are a separate call because they
            cost a full decode of two files — see `find_stalled_frames`.
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

    def find_stalled_frames(self, video_path: Path, source_path: Path) -> list[FrameRange]:
        """
        Runs where a video repeats a frame but its source does not.

        Args:
            video_path: The file to check — depth back from a hosted model.
            source_path: What it was generated from, as the control.

        Returns:
            One FrameRange per run of repeated frames, inclusive at both
            ends. Empty when nothing stalled.

        Raises:
            ValueError: The two files are different lengths, which is a
                failure `validate` reports rather than this.

        Notes:
            **Both files, because a repeat on its own means nothing.** A
            locked-off camera on a still subject legitimately produces
            identical frames, and so does its depth. What is suspicious is
            depth repeating where the source did not — that is the model
            stalling rather than the shot being still.

            This is what CLAUDE.md non-negotiable 2 means by the depth being
            checked and never trusted: a stalled model returns a file of the
            right length, at the right rate, that is wrong in the middle, and
            no amount of metadata would say so.

            Costs a full decode of both files, which is why it is its own
            call rather than part of `validate`.
        """
        video = self.frame_hashes(video_path)
        source = self.frame_hashes(source_path)

        if len(video) != len(source):
            raise ValueError(
                f"{video_path.name} has {len(video)} frames against "
                f"{source_path.name}'s {len(source)}; compare lengths with validate()"
            )

        # Frame 0 can never be a repeat, so the run-finder is fed from 1 and
        # its indices shifted back up.
        repeated = (
            video[index] == video[index - 1] and source[index] != source[index - 1]
            for index in range(1, len(video))
        )
        stalled = [
            FrameRange(start_frame=start + 1, end_frame=end + 1)
            for start, end in runs_of_true(repeated)
        ]

        if stalled:
            logging.warning(
                f"{video_path.name} repeats frames its source does not, at "
                f"{[(r.start_frame, r.end_frame) for r in stalled]}"
            )

        return stalled

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
