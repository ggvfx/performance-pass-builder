"""
SMPTE Timecode Engine.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

The only place in the project where frames become time. Everything else works
in integer frames and calls in here at output boundaries — sidecar fields, UI
labels, ffmpeg arguments.

Frame rate mistakes (23.976 against 24) and off-by-one errors are the failure
this project is most exposed to, so the arithmetic is isolated here where it
can be unit tested on its own.

Two ideas are easy to confuse and are kept strictly apart:

- **Frames** are real pictures. Frame 1798 is the 1799th picture in the file.
- **Labels** are what timecode counts. At 29.97 drop-frame, some labels are
  never used, so the label count runs ahead of the frame count by design.

Notes:
    MediaPipe's video mode needs a strictly rising millisecond timestamp per
    frame. That conversion belongs here when Phase 3 needs it, and nowhere
    else — it is the same class of arithmetic as everything above.
"""

import math
from fractions import Fraction

from src.core.models import SourceInfo

# --- DROP FRAME ---

# Drop-frame applies to 29.97 and 59.94 only. It skips timecode LABELS to keep
# the clock honest over long durations — it never skips actual frames.
DROP_FRAME_RATES = (Fraction(30000, 1001), Fraction(60000, 1001))

# Labels are dropped at the start of every minute except every tenth minute.
MINUTES_BETWEEN_KEPT = 10

# Hours wrap at 24, as on any timecode display.
HOURS_PER_DAY = 24


class Timecode:
    """
    Frame and timecode arithmetic for one source's frame rate.

    Constructed once per job from the probed source, then used everywhere a
    frame number has to be shown or handed to ffmpeg.

    The rate is held as an exact Fraction, never a float. `fps = 23.976` looks
    harmless and drifts a frame roughly every forty seconds.
    """

    def __init__(self, numerator: int, denominator: int, start_timecode: str = "00:00:00:00"):
        """
        Args:
            numerator: Frame rate numerator as ffprobe reports it, e.g. 24000.
            denominator: Frame rate denominator, e.g. 1001.
            start_timecode: Source start timecode. Added as an offset by
                `frames_to_timecode` so displayed values match the editor.

        Raises:
            ValueError: If the rate is zero or negative, or the start timecode
                cannot be parsed.
        """
        if numerator <= 0 or denominator <= 0:
            raise ValueError(f"Frame rate must be positive, got {numerator}/{denominator}")

        self.rate = Fraction(numerator, denominator)
        self.start_timecode = start_timecode

        # Validates the start timecode now rather than mid-job
        self.start_frames = self.timecode_to_frames(start_timecode)

    @classmethod
    def from_source(cls, source: SourceInfo) -> "Timecode":
        """Builds a Timecode from a probed source."""
        return cls(source.fps_numerator, source.fps_denominator, source.start_timecode)

    def __repr__(self) -> str:
        return f"Timecode({self.rate}, start={self.start_timecode})"

    # --- RATE PROPERTIES ---

    @property
    def is_drop_frame(self) -> bool:
        """Whether this rate uses drop-frame timecode."""
        return self.rate in DROP_FRAME_RATES

    @property
    def labels_per_second(self) -> int:
        """
        Timecode labels in one second of this rate.

        The nominal integer, not the real rate: 23.976 counts 24 labels per
        second, and hiding that difference is what timecode exists to do.
        """
        return math.ceil(self.rate)

    @property
    def dropped_labels_per_minute(self) -> int:
        """
        Labels skipped at the start of a dropping minute.

        Two at 29.97, four at 59.94 — always enough to absorb the same 0.1%
        difference between the nominal and real rate.
        """
        if not self.is_drop_frame:
            return 0
        return 2 * (self.labels_per_second // 30)

    @property
    def separator(self) -> str:
        """Frames separator: ';' marks drop-frame, ':' is non-drop."""
        return ";" if self.is_drop_frame else ":"

    # --- FRAMES TO TIMECODE ---

    def frames_to_timecode(self, frames: int) -> str:
        """
        Converts a source frame index to a timecode string.

        Args:
            frames: Frame index, 0 = first frame of the source.

        Returns:
            "HH:MM:SS:FF", or "HH:MM:SS;FF" when drop-frame. Includes the
            source start timecode offset.

        Raises:
            ValueError: If frames is negative.
        """
        if frames < 0:
            raise ValueError(f"Frame index cannot be negative, got {frames}")

        return self._frames_to_timecode_absolute(frames + self.start_frames)

    def _frames_to_timecode_absolute(self, frames: int) -> str:
        """
        Converts an absolute frame count to a timecode string, no offset applied.

        Notes:
            Drop-frame works by converting the frame count into a LABEL count —
            adding back the labels that were skipped — and then doing ordinary
            arithmetic on the result.
        """
        labels = frames

        if self.is_drop_frame:
            drop = self.dropped_labels_per_minute
            frames_per_minute = self.labels_per_second * 60 - drop
            frames_per_block = self.labels_per_second * 60 * MINUTES_BETWEEN_KEPT - (
                (MINUTES_BETWEEN_KEPT - 1) * drop
            )

            blocks, remainder = divmod(frames, frames_per_block)

            # Every ten minute block skips labels in nine of its ten minutes
            labels += (MINUTES_BETWEEN_KEPT - 1) * drop * blocks

            # The first minute of a block drops nothing, hence the offset
            if remainder >= drop:
                labels += drop * ((remainder - drop) // frames_per_minute)

        frames_field = labels % self.labels_per_second
        total_seconds = labels // self.labels_per_second

        seconds = total_seconds % 60
        minutes = (total_seconds // 60) % 60
        hours = (total_seconds // 3600) % HOURS_PER_DAY

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}{self.separator}{frames_field:02d}"

    # --- TIMECODE TO FRAMES ---

    def timecode_to_frames(self, timecode: str) -> int:
        """
        Converts a timecode string to an absolute frame count.

        The inverse of `_frames_to_timecode_absolute`: no start offset is
        removed, so this is the right call for reading a source start timecode.
        Use `timecode_to_frame_index` to get back to a frame index within a
        source that starts at a non-zero timecode.

        Raises:
            ValueError: If the string is malformed, a field is out of range, or
                it names a label that drop-frame never uses.
        """
        hours, minutes, seconds, frames_field = self._parse(timecode)

        labels = ((hours * 60 + minutes) * 60 + seconds) * self.labels_per_second + frames_field

        if self.is_drop_frame:
            total_minutes = hours * 60 + minutes
            kept_minutes = total_minutes // MINUTES_BETWEEN_KEPT
            labels -= self.dropped_labels_per_minute * (total_minutes - kept_minutes)

        return labels

    def timecode_to_frame_index(self, timecode: str) -> int:
        """
        Converts a displayed timecode back to a frame index within the source.

        The exact inverse of `frames_to_timecode`.
        """
        return self.timecode_to_frames(timecode) - self.start_frames

    def _parse(self, timecode: str):
        """
        Splits a timecode string into its four integer fields.

        Returns:
            (hours, minutes, seconds, frames)

        Raises:
            ValueError: If the shape is wrong, a field is out of range, or the
                label is one that drop-frame skips — 00:01:00;00 does not exist
                at 29.97, and silently accepting it would shift a frame.
        """
        fields = timecode.replace(";", ":").split(":")
        if len(fields) != 4:
            raise ValueError(f"Timecode must be HH:MM:SS:FF, got {timecode!r}")

        try:
            hours, minutes, seconds, frames_field = (int(field) for field in fields)
        except ValueError:
            raise ValueError(f"Timecode fields must be whole numbers, got {timecode!r}")

        if not 0 <= hours < HOURS_PER_DAY:
            raise ValueError(f"Hours out of range in {timecode!r}")
        if not 0 <= minutes < 60:
            raise ValueError(f"Minutes out of range in {timecode!r}")
        if not 0 <= seconds < 60:
            raise ValueError(f"Seconds out of range in {timecode!r}")
        if not 0 <= frames_field < self.labels_per_second:
            raise ValueError(f"Frames out of range for {self.labels_per_second} fps in {timecode!r}")

        if self.is_drop_frame:
            drops_this_minute = minutes % MINUTES_BETWEEN_KEPT != 0
            if drops_this_minute and seconds == 0 and frames_field < self.dropped_labels_per_minute:
                raise ValueError(f"{timecode!r} is a dropped label and never occurs at this rate")

        return hours, minutes, seconds, frames_field

    # --- FRAMES TO SECONDS, FOR FFMPEG ---

    def frame_to_seconds(self, frame: int) -> Fraction:
        """
        Exact start time of a frame, as a Fraction.

        A Fraction rather than a float on purpose: this becomes an ffmpeg `-ss`
        argument, and a time landing a millionth of a second early puts the
        seek on the wrong frame.
        """
        return Fraction(frame) / self.rate

    def duration_seconds(self, frame_count: int) -> Fraction:
        """
        Exact duration of a run of frames at this rate.

        Notes:
            The authoritative duration of a source, and of everything produced
            from it: frames are what a pass is made of, and a container's own
            declared duration is advisory.
        """
        return Fraction(frame_count) / self.rate

    @staticmethod
    def format_seconds(seconds: Fraction, decimal_places: int = 6) -> str:
        """
        Renders an exact time as a decimal string for an ffmpeg argument.

        Args:
            seconds: Exact time from `frame_to_seconds`.
            decimal_places: Six is comfortably finer than one frame at any
                broadcast rate.

        Returns:
            A fixed-point decimal string, e.g. "0.041708".

        Raises:
            ValueError: If seconds is negative or decimal_places is below 1.

        Notes:
            Never routes through float() — that is the bug this class exists to
            prevent. Scales to integers, rounds half-up, then places the point.
        """
        if seconds < 0:
            raise ValueError(f"Time cannot be negative, got {seconds}")
        if decimal_places < 1:
            raise ValueError(f"decimal_places must be at least 1, got {decimal_places}")

        scale = 10 ** decimal_places
        scaled = Fraction(seconds) * scale

        units, remainder = divmod(scaled.numerator, scaled.denominator)
        if remainder * 2 >= scaled.denominator:
            units += 1

        whole, fraction = divmod(units, scale)
        return f"{whole}.{fraction:0{decimal_places}d}"
