"""
Frame Streaming.

Reading frames out of a video and writing frames back into one, through
ffmpeg pipes, as numpy arrays.

**New work. minicut has no counterpart**: it stream-copies shots out of a
mezzanine and never moves a frame through Python. Everything this project
does to a picture — windowing depth, drawing a mesh, compositing a stack —
happens on arrays between these two.

**No subprocess is touched here.** `ffmpeg_tools` owns every process in the
app, lifecycle included — starting, closing, reaping, and turning ffmpeg's
last words into an error. This module owns what is frame-shaped: the
arguments, the byte arithmetic, and the numpy array at the end.

That split is about swappability. Someone dropping this tool into a larger
one that does not use ffmpeg replaces `ffmpeg_tools` and nothing else — which
only holds if the closing and reaping live there too, not beside the frames.

Notes:
    Two pixel formats, both 8-bit. `RGB` covers the plate and depth; `RGBA`
    exists because the face mesh is the one layer that needs transparency.

    8-bit is what h264 and h265 deliver, and depth is windowed at 16-bit
    before it ever reaches here — see `PixelFormat` for what going wider
    would take, and why nothing wants it yet.
"""

import logging
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from src.core.ffmpeg_tools import FFmpegReadPipe, FFmpegWritePipe, MediaToolchain
from src.core.models import SourceInfo

# --- PIXEL FORMATS ---


@dataclass(frozen=True)
class PixelFormat:
    """
    How a frame is laid out in the pipe, and what numpy array that gives.

    Two of them today, both 8-bit: `RGB` for the plate and depth, `RGBA`
    because the face mesh is the one layer that needs transparency.

    Notes:
        **Depth is stored at 16-bit and windowed before it reaches the pipe**,
        so the precision is spent where it matters rather than lost here. What
        travels between modules is the already-windowed picture, and 8-bit is
        what h264 and h265 deliver anyway.

        Going 10- or 16-bit later is a format added here, not a rewrite: the
        depth of a sample is a field rather than an assumption, so a
        `PixelFormat("rgb48le", 3, np.uint16)` plus a 10-bit output codec
        would carry through. Nothing wants it yet — Seedance reads a depth
        pass as a greyscale picture, not as depth — so nothing is built for
        it.
    """

    name: str                      # What ffmpeg calls it
    channels: int                  # The array's third dimension
    sample: type = np.uint8        # One component's numpy type

    @property
    def bytes_per_pixel(self) -> int:
        return self.channels * np.dtype(self.sample).itemsize


RGB = PixelFormat("rgb24", 3)
RGBA = PixelFormat("rgba", 4)


def frame_size_bytes(width: int, height: int, pixel_format: PixelFormat = RGB) -> int:
    """
    How many bytes one frame occupies in the pipe.

    Notes:
        Channels and bytes are not the same question, even though they happen
        to give the same answer at 8-bit. Conflating them is what would break
        first the day a 16-bit format is added.
    """
    return width * height * pixel_format.bytes_per_pixel


# --- READING ---


class FrameReader:
    """
    Decodes a video to RGB frames, one at a time.

    A context manager, because an abandoned ffmpeg holding a pipe open is a
    process nobody will ever reap:

        with FrameReader(toolchain, path, width, height) as reader:
            for frame in reader:
                ...

    Notes:
        Sequential only. Reading frame 500 means reading the 500 before it,
        which is why the mezzanine exists — a seek into long-GOP h264 is
        either inexact or slower than this.
    """

    def __init__(
        self,
        toolchain: MediaToolchain,
        path: Path,
        width: int,
        height: int,
        pixel_format: PixelFormat = RGB,
    ):
        self.toolchain = toolchain
        self.path = path
        self.width = width
        self.height = height
        self.pixel_format = pixel_format

        self.frames_read = 0
        self._pipe: FFmpegReadPipe | None = None

    @classmethod
    def for_source(
        cls,
        toolchain: MediaToolchain,
        source: SourceInfo,
        path: Path | None = None,
        pixel_format: PixelFormat = RGB,
    ):
        """
        A reader sized from a probed source.

        Args:
            toolchain: The shared toolchain.
            source: Where the geometry comes from.
            path: What to read, when it is not the source itself — the
                mezzanine usually, which has the same geometry.
        """
        return cls(
            toolchain, path or Path(source.path), source.width, source.height, pixel_format
        )

    # --- LIFECYCLE ---

    def __enter__(self) -> "FrameReader":
        self._pipe = self.toolchain.open_read_pipe([
            "-v", "error",
            "-i", str(self.path),
            "-map", "0:v:0",
            "-f", "rawvideo",
            "-pix_fmt", self.pixel_format.name,
            "-",
        ])
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Stops ffmpeg and reaps it — see `FFmpegReadPipe.close`."""
        if self._pipe is None:
            return

        self._pipe.close()
        self._pipe = None

    # --- READING ---

    def __iter__(self):
        return self

    def __next__(self) -> np.ndarray:
        frame = self.read()
        if frame is None:
            raise StopIteration
        return frame

    def read(self) -> np.ndarray | None:
        """
        The next frame, or None at the end of the video.

        Returns:
            A (height, width, 3) uint8 array, or None.

        Raises:
            RuntimeError: If the reader was not opened, or the pipe ended
                mid-frame.

        Notes:
            An empty read is the normal end: ffmpeg closes the pipe when it
            runs out of frames. A *partial* read is not — that is a truncated
            stream, and treating it as the end would silently lose a frame
            and every frame after it.
        """
        if self._pipe is None:
            raise RuntimeError("FrameReader must be used as a context manager")

        wanted = frame_size_bytes(self.width, self.height, self.pixel_format)

        try:
            raw = self._pipe.read_exactly(wanted)
        except RuntimeError as error:
            raise RuntimeError(
                f"{self.path.name} ended mid-frame after {self.frames_read} frames: {error}"
            )

        if raw is None:
            return None

        self.frames_read += 1
        return np.frombuffer(raw, dtype=self.pixel_format.sample).reshape(
            self.height, self.width, self.pixel_format.channels
        )


# --- WRITING ---


class FrameWriter:
    """
    Encodes RGB frames into a video, one at a time.

    A context manager, and the exit matters more than the entry: ffmpeg only
    finishes writing the container when its input closes, so a writer that is
    never closed leaves a file that will not play.

        with FrameWriter(toolchain, path, width, height, rate) as writer:
            writer.write(frame)
    """

    def __init__(
        self,
        toolchain: MediaToolchain,
        path: Path,
        width: int,
        height: int,
        rate: Fraction,
        codec: str = "libx264",
        crf: int = 18,
        preset: str = "medium",
        pixel_format: PixelFormat = RGB,
    ):
        self.toolchain = toolchain
        self.path = path
        self.width = width
        self.height = height
        self.rate = rate
        self.codec = codec
        self.crf = crf
        self.preset = preset
        self.pixel_format = pixel_format

        self.frames_written = 0
        self._pipe: FFmpegWritePipe | None = None

    # --- LIFECYCLE ---

    def frame_input_arguments(self) -> list[str]:
        """
        The arguments describing the frames arriving on stdin.

        Notes:
            The rate goes in as an exact rational — ffmpeg takes "24000/1001"
            here — because a rounded 23.976 would drift against the source.
        """
        return [
            "-f", "rawvideo",
            "-pix_fmt", self.pixel_format.name,
            "-s", f"{self.width}x{self.height}",
            "-r", f"{self.rate.numerator}/{self.rate.denominator}",
            "-i", "-",
        ]

    def video_output_arguments(self) -> list[str]:
        """How the picture is encoded."""
        return [
            "-c:v", self.codec,
            "-preset", self.preset,
            "-crf", str(self.crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]

    @property
    def written_path(self) -> Path:
        """What ffmpeg is told to write. A subclass may expand it — see encode.py."""
        return self.path

    def arguments(self) -> list[str]:
        """
        The whole command, as one list.

        Notes:
            Assembled in one overridable place so a writer that also muxes
            audio can add an input and a mapping without reimplementing the
            pipe handling below it — see `media/encode.py`.
        """
        return [
            "-v", "error",
            *self.frame_input_arguments(),
            *self.video_output_arguments(),
            "-y",
            str(self.written_path),
        ]

    def __enter__(self) -> "FrameWriter":
        # A sequence writes into its own folder, so that folder is what has to
        # exist. `written_path` says which; for a single file it is the path.
        self.written_path.parent.mkdir(parents=True, exist_ok=True)

        self._pipe = self.toolchain.open_write_pipe(self.arguments())
        return self

    def __exit__(self, exception_type, *_) -> None:
        self.close(abandon=exception_type is not None)

    def close(self, abandon: bool = False) -> None:
        """
        Closes the input and waits for ffmpeg to finish the container.

        Args:
            abandon: True when the caller is unwinding from an error. The
                process is killed and no completion check runs, because the
                original exception is the interesting one and a "writer
                failed" raised on top of it would hide it.

        Raises:
            RuntimeError: If ffmpeg exited badly, with its own last words.
        """
        if self._pipe is None:
            return

        pipe, self._pipe = self._pipe, None

        if abandon:
            pipe.abandon()
            return

        pipe.finish()
        logging.info(f"Wrote {self.frames_written} frames to {self.path}")

    # --- WRITING ---

    def write(self, frame: np.ndarray) -> None:
        """
        Appends one frame.

        Raises:
            RuntimeError: If the writer was not opened, or ffmpeg has already
                exited — see `FFmpegWritePipe.write`.
            ValueError: If the frame is the wrong shape or dtype.
        """
        if self._pipe is None:
            raise RuntimeError("FrameWriter must be used as a context manager")

        expected = (self.height, self.width, self.pixel_format.channels)
        if frame.shape != expected:
            raise ValueError(f"Frame {self.frames_written} is {frame.shape}, expected {expected}")
        if frame.dtype != self.pixel_format.sample:
            raise ValueError(
                f"Frame {self.frames_written} is {frame.dtype}, "
                f"expected {np.dtype(self.pixel_format.sample)}"
            )

        self._pipe.write(frame.tobytes())
        self.frames_written += 1
