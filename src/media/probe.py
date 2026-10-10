"""
Source Inspection.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.
Crop detection did not come across: letterboxing is information about a source
you are going to cut, and nothing here ever reshapes the picture.

Reads everything that has to be known about a source before any work starts:
frame rate as an exact rational, frame count, timecode, audio, and the disk
cost of a job.

Nothing here modifies the source. Variable frame rate is **reported**, not
fixed — this module states what a file is, and the pipeline decides whether to
refuse it.
"""

import json
import logging
import shutil
from fractions import Fraction
from pathlib import Path

from src.core.config import (
    DISK_COPIES_PER_JOB,
    GB_PER_MINUTE_1080P24,
    MP4_AUDIO_CODECS,
    OUTPUT_DIR_SUFFIX,
    REFERENCE_PIXELS,
    REFERENCE_RATE,
)
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import AudioInfo, ProbeReport, SourceInfo
from src.core.timecode import Timecode

# --- OUTPUT NAMING ---


def suggested_output_dir(source_path: Path) -> Path:
    """
    Where a source's deliverables should go unless the user says otherwise.

    Uses pathlib rather than splitting the string, which is the point of doing
    this server-side at all: minicut's front end used a regex that only split
    on forward slashes, so a Windows path never split. It happened to produce
    the right answer, which is the kind of luck that runs out quietly.
    """
    return source_path.parent / f"{source_path.stem}{OUTPUT_DIR_SUFFIX}"


# --- PROBE ---


class SourceProbe:
    """
    Reads technical metadata from source files.

    Holds the toolchain so a job's probe runs through the same resolved
    ffprobe binary that everything else uses.
    """

    def __init__(self, toolchain: MediaToolchain):
        self.toolchain = toolchain

    # --- FULL INSPECTION ---

    def inspect(self, source_path: Path, output_dir: Path | None = None) -> ProbeReport:
        """
        Everything the page needs to decide whether to start a job.

        Args:
            source_path: The footage to inspect.
            output_dir: Where the job would write, for the free space check.

        Returns:
            ProbeReport. `can_build` is False only when the source genuinely
            cannot carry a frame-accurate pass; everything else is a warning
            the user may proceed past.

        Notes:
            The refusal/warning split is the whole shape of this: a variable
            frame rate source cannot be worked around, while a tight disk is
            the user's call to make.
        """
        source = self.probe(source_path)

        refusal = None
        if source.is_variable_frame_rate:
            refusal = (
                "This source has a variable frame rate, so frame numbers do not map "
                "reliably to time. Convert it to constant frame rate first."
            )

        estimated_gb = self.estimate_disk_required(source)
        free_gb = None
        warnings: list[str] = []

        if output_dir is not None and output_dir.is_dir():
            free_gb = shutil.disk_usage(output_dir).free / (1024 ** 3)
            if estimated_gb > free_gb:
                warnings.append(
                    f"This job needs about {estimated_gb:.0f} GB but only "
                    f"{free_gb:.0f} GB is free on the output volume."
                )

        if source.audio is not None and not source.audio.can_stream_copy_to_mp4:
            warnings.append(
                f"The audio is {source.audio.codec}, which an mp4 cannot hold. It will be "
                f"encoded once at a high bitrate, and the sidecar will say so."
            )

        # Duration is a length, not a position, so it is measured from zero.
        # Using the source's own start timecode here would report 10:00:02:00
        # for a two second clip that happens to start at 10:00:00:00.
        length = Timecode(source.fps_numerator, source.fps_denominator)

        return ProbeReport(
            source=source,
            duration_timecode=length.frames_to_timecode(source.frame_count),
            suggested_output_dir=suggested_output_dir(source_path),
            estimated_gb=estimated_gb,
            free_gb=free_gb,
            can_build=refusal is None,
            refusal_reason=refusal,
            warnings=warnings,
        )

    def probe(self, source_path: Path) -> SourceInfo:
        """
        Reads technical metadata from the source file.

        Args:
            source_path: The footage to inspect.

        Returns:
            SourceInfo, populated from ffprobe's JSON output.

        Raises:
            FileNotFoundError: If the source does not exist.
            ValueError: If ffprobe fails, the output is unreadable, or the file
                has no video stream.
        """
        if not source_path.is_file():
            raise FileNotFoundError(f"Source not found: {source_path}")

        result = self.toolchain.run_ffprobe(
            [
                "-v", "error",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(source_path),
            ],
            timeout=60.0,
        )

        if result.returncode != 0:
            raise ValueError(f"ffprobe could not read {source_path}: {result.stderr.strip()}")

        try:
            probed = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(f"ffprobe returned unreadable output for {source_path}: {error}")

        streams = probed.get("streams", [])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        if video is None:
            raise ValueError(f"No video stream in {source_path}")

        numerator, denominator = self._parse_rate(video.get("r_frame_rate"), source_path)
        container = probed.get("format", {})

        source = SourceInfo(
            path=source_path,
            width=int(video["width"]),
            height=int(video["height"]),
            fps_numerator=numerator,
            fps_denominator=denominator,
            frame_count=self._frame_count(video, Fraction(numerator, denominator), source_path),
            codec=video.get("codec_name", "unknown"),
            pixel_format=video.get("pix_fmt", "yuv420p"),
            start_timecode=self._start_timecode(streams, container),
            is_variable_frame_rate=self._is_variable_frame_rate(video),
            container_duration_seconds=self._container_duration(container),
            audio=self._audio(streams),
        )

        logging.info(
            f"Probed {source_path.name}: {source.width}x{source.height}, "
            f"{numerator}/{denominator} fps, {source.frame_count} frames, "
            f"start {source.start_timecode}"
        )
        return source

    # --- PARSING HELPERS ---

    @staticmethod
    def _parse_rate(rate: str | None, source_path: Path) -> tuple[int, int]:
        """
        Splits an ffprobe rate string such as "24000/1001" into two integers.

        Kept as a pair rather than divided, because 24000/1001 is not 23.976
        and the difference drifts a frame roughly every forty seconds.

        Raises:
            ValueError: If the rate is missing, malformed or zero.
        """
        if not rate or "/" not in rate:
            raise ValueError(f"No usable frame rate in {source_path} (got {rate!r})")

        numerator, denominator = rate.split("/", 1)
        try:
            numerator, denominator = int(numerator), int(denominator)
        except ValueError:
            raise ValueError(f"Unreadable frame rate {rate!r} in {source_path}")

        if numerator <= 0 or denominator <= 0:
            raise ValueError(f"Frame rate {rate!r} in {source_path} is not usable")

        return numerator, denominator

    @staticmethod
    def _frame_count(video: dict, rate: Fraction, source_path: Path) -> int:
        """
        The number of frames in the video stream.

        Prefers the container's own `nb_frames`. Some containers omit it, in
        which case the count is derived from the duration — less trustworthy,
        so it is logged rather than passed over in silence.

        Raises:
            ValueError: If neither is available.
        """
        nb_frames = video.get("nb_frames")
        if nb_frames is not None:
            try:
                return int(nb_frames)
            except ValueError:
                logging.warning(f"Unreadable nb_frames {nb_frames!r} in {source_path}")

        duration = video.get("duration")
        if duration is not None:
            try:
                frames = int(round(float(duration) * rate))
            except ValueError:
                raise ValueError(f"Unreadable duration {duration!r} in {source_path}")

            logging.warning(
                f"{source_path.name} has no frame count; derived {frames} from its duration"
            )
            return frames

        raise ValueError(f"Cannot determine a frame count for {source_path}")

    @staticmethod
    def _is_variable_frame_rate(video: dict) -> bool:
        """
        Whether the container reports a variable frame rate.

        r_frame_rate is the base rate, avg_frame_rate the realised average.
        When they disagree the file has no stable frame-to-time mapping, so
        every frame of every pass would drift against it.

        An unknown average (0/0, as some containers report) is not treated as
        VFR — there is nothing to compare it against.
        """
        try:
            base = Fraction(video.get("r_frame_rate", "0/0"))
            average = Fraction(video.get("avg_frame_rate", "0/0"))
        except (ValueError, ZeroDivisionError):
            return False

        if base == 0 or average == 0:
            return False

        return base != average

    @staticmethod
    def _start_timecode(streams: list[dict], container: dict) -> str:
        """
        The source start timecode, searched in the three places it can hide.

        ffmpeg writes it to the video stream's tags and to a separate `tmcd`
        data stream; some files carry it only in the container tags.

        Returns:
            "HH:MM:SS:FF", or "00:00:00:00" when the file carries none.
        """
        for stream in streams:
            timecode = stream.get("tags", {}).get("timecode")
            if timecode:
                return timecode

        timecode = container.get("tags", {}).get("timecode")
        return timecode if timecode else "00:00:00:00"

    @staticmethod
    def _container_duration(container: dict) -> float | None:
        """
        What the container declared, which is advisory only.

        Kept because the container and the frames disagreeing is worth being
        able to show. The authoritative duration comes from the frame count
        and the exact rate — see `Timecode.duration_seconds`.
        """
        duration = container.get("duration")
        if duration is None:
            return None

        try:
            return float(duration)
        except ValueError:
            return None

    @staticmethod
    def _audio(streams: list[dict]) -> AudioInfo | None:
        """
        The first audio stream, or None for a mute source.

        Notes:
            `can_stream_copy_to_mp4` is decided here, before the job, so the
            user learns that 24-bit PCM off a camera will be re-encoded rather
            than finding out from ffmpeg at the end. CLAUDE.md
            non-negotiable 3.

            The first stream only. A source with several audio tracks is a
            real thing and is not handled: picking one silently would be worse
            than the single-track assumption being visible here.
        """
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if audio is None:
            return None

        codec = audio.get("codec_name", "unknown")
        bit_rate = audio.get("bit_rate")

        return AudioInfo(
            codec=codec,
            sample_rate=int(audio.get("sample_rate", 48000)),
            channels=int(audio.get("channels", 2)),
            bit_rate=int(bit_rate) if bit_rate is not None else None,
            can_stream_copy_to_mp4=codec in MP4_AUDIO_CODECS,
        )

    # --- DISK ---

    @staticmethod
    def estimate_disk_required(source: SourceInfo) -> float:
        """
        Estimated gigabytes for one job: the mezzanine, the stored depth and
        the deliverables.

        Reported before the job starts, so the user finds out now rather than
        when the drive fills mid-transcode.

        The reference figure is all-intra h264 at 1080p24, so both resolution
        and frame rate scale it.
        """
        rate = Fraction(source.fps_numerator, source.fps_denominator)
        minutes = float(source.frame_count / rate / 60)

        pixel_scale = (source.width * source.height) / REFERENCE_PIXELS
        rate_scale = float(rate) / REFERENCE_RATE

        return GB_PER_MINUTE_1080P24 * minutes * pixel_scale * rate_scale * DISK_COPIES_PER_JOB
