"""
FFmpeg Toolchain.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Every call to ffmpeg and ffprobe in the project goes through this class. They
are invoked as subprocesses, never through a Python binding, so the exact
binary and version can be recorded in the job sidecar.

Lives in core rather than media because everything depends on it and it
depends on nothing — the environment checks need it before any media module is
touched.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

# --- TOOL INFO ---


class ToolInfo(BaseModel):
    """A located command line tool and the first line of its version banner."""

    name: str
    path: Path
    version: str


# --- TOOLCHAIN ---


class MediaToolchain:
    """
    The resolved ffmpeg and ffprobe binaries, and the commands that use them.

    Resolved once and reused. Discovery and the encoder list both shell out, so
    repeating them per call would mean several needless subprocesses every time
    the dependency panel refreshes.

    Missing tools are not an error here — they are reported as None so the
    environment checks can explain the problem to the user. Call `is_ready`
    before assuming a command will run.
    """

    def __init__(self, discover: bool = True):
        """
        Args:
            discover: Look for the tools immediately. Pass False in tests that
                want to set `ffmpeg` / `ffprobe` by hand.
        """
        self.ffmpeg: ToolInfo | None = None
        self.ffprobe: ToolInfo | None = None

        # Cached because `ffmpeg -encoders` prints several hundred lines
        self._encoders: set[str] | None = None

        # Same, and for the same reason: `ffmpeg -filters` is longer still
        self._filters: set[str] | None = None

        if discover:
            self.discover()

    # --- DISCOVERY ---

    def discover(self) -> None:
        """
        Locates both tools on PATH and reads their versions.

        Re-runnable: the user may install ffmpeg and press Re-check without
        restarting the app.
        """
        self.ffmpeg = self._probe_tool("ffmpeg")
        self.ffprobe = self._probe_tool("ffprobe")
        self._encoders = None
        self._filters = None

    @property
    def is_ready(self) -> bool:
        """True when both tools were found and will run."""
        return self.ffmpeg is not None and self.ffprobe is not None

    def _probe_tool(self, name: str) -> ToolInfo | None:
        """Finds one tool on PATH and reads the first line of its banner."""
        found = shutil.which(name)
        if found is None:
            logging.debug(f"{name} not found on PATH")
            return None

        result = self.run([found, "-version"])
        if result.returncode != 0:
            logging.warning(f"{name} was found at {found} but would not run")
            return None

        banner = result.stdout.splitlines()[0].strip() if result.stdout else ""
        return ToolInfo(name=name, path=Path(found), version=banner)

    # --- COMMAND EXECUTION ---

    def run(self, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        """
        Runs a command and captures its output.

        Args:
            args: Full command line, already split into arguments.
            timeout: Seconds before the call is abandoned. Long encodes must not
                use this — they need progress streaming instead.

        Notes:
            errors="replace" keeps a stray non-UTF-8 byte in ffmpeg's output
            from taking down the whole call.
        """
        logging.debug(f"Running: {' '.join(args)}")
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def run_ffmpeg(self, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        """
        Runs ffmpeg with the given arguments.

        Raises:
            RuntimeError: If ffmpeg was never found. Callers should have checked
                `is_ready`, so reaching here is a bug rather than a user problem.
        """
        if self.ffmpeg is None:
            raise RuntimeError("ffmpeg is not available")
        return self.run([str(self.ffmpeg.path), "-hide_banner", *args], timeout=timeout)

    def run_ffprobe(self, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        """
        Runs ffprobe with the given arguments.

        Raises:
            RuntimeError: If ffprobe was never found.
        """
        if self.ffprobe is None:
            raise RuntimeError("ffprobe is not available")
        return self.run([str(self.ffprobe.path), "-hide_banner", *args], timeout=timeout)

    def popen_ffmpeg(self, args: list[str], **streams) -> subprocess.Popen:
        """
        Starts ffmpeg as a long-running process with its pipes open.

        Args:
            args: Arguments after `-hide_banner`.
            **streams: Passed to Popen — `stdin`, `stdout`, `stderr`.

        Returns:
            The running process. The caller owns it and must wait on it.

        Raises:
            RuntimeError: If ffmpeg was never found.

        Notes:
            Here rather than in `media/frames.py` because this module is the
            only place a subprocess starts, frame pipes included — CLAUDE.md
            says so, and the reason is that "which ffmpeg ran, with what
            arguments" should have one answer.

            Unlike `run`, there is no timeout: a frame pipe is driven by the
            caller reading or writing it, and a deadline here would kill a
            long encode that was working perfectly.
        """
        if self.ffmpeg is None:
            raise RuntimeError("ffmpeg is not available")

        command = [str(self.ffmpeg.path), "-hide_banner", *args]
        logging.debug(f"Opening pipe: {' '.join(command)}")
        return subprocess.Popen(command, **streams)

    def open_read_pipe(self, args: list[str]) -> "FFmpegReadPipe":
        """
        Starts ffmpeg writing bytes to a pipe we read.

        Args:
            args: Arguments after `-hide_banner`, ending in `-` for stdout.
        """
        return FFmpegReadPipe(
            self.popen_ffmpeg(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        )

    def open_write_pipe(self, args: list[str]) -> "FFmpegWritePipe":
        """
        Starts ffmpeg reading bytes from a pipe we write.

        Args:
            args: Arguments after `-hide_banner`, taking `-i -` for stdin.
        """
        return FFmpegWritePipe(
            self.popen_ffmpeg(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE),
            args[-1],
        )

    # --- ENCODERS ---

    def available_encoders(self) -> set[str]:
        """
        Encoder names this ffmpeg build actually offers.

        Cached after the first call. Checked up front because a build without
        libx264 otherwise only surfaces mid-job.
        """
        if self._encoders is not None:
            return self._encoders

        if self.ffmpeg is None:
            self._encoders = set()
            return self._encoders

        result = self.run_ffmpeg(["-encoders"])
        if result.returncode != 0:
            logging.warning("Could not read the encoder list from ffmpeg")
            self._encoders = set()
        else:
            self._encoders = self.parse_encoders(result.stdout)

        return self._encoders

    @staticmethod
    def parse_encoders(output: str) -> set[str]:
        """
        Pulls encoder names out of `ffmpeg -encoders` output.

        Table rows look like ' V....D libx264   libx264 H.264 / AVC', where the
        first field is a six character flag block and the second is the name.

        A static method so it can be tested against captured output without
        ffmpeg being installed.
        """
        names = set()

        for line in output.splitlines():
            fields = line.split()

            # Skip headings, the flag legend, and anything that is not a row
            if len(fields) < 2 or len(fields[0]) != 6:
                continue
            if not set(fields[0]) <= set("VASFXBD."):
                continue
            if fields[1] == "=":
                continue

            names.add(fields[1])

        return names

    def has_encoder(self, name: str) -> bool:
        """Whether a named encoder is available in this build."""
        return name in self.available_encoders()

    # --- FILTERS ---

    def available_filters(self) -> set[str]:
        """
        Filter names this ffmpeg build actually offers.

        Notes:
            The same up-front check as `available_encoders`, and it exists
            because of the same class of failure found on a real machine: a
            Homebrew ffmpeg built without libfreetype has no `drawtext`, passes
            every check we had, and then aborts the whole proxy encode with
            "Filter not found" — a build problem reported as a mystery, halfway
            through a job.
        """
        if self._filters is not None:
            return self._filters

        if self.ffmpeg is None:
            self._filters = set()
            return self._filters

        result = self.run_ffmpeg(["-filters"])
        if result.returncode != 0:
            logging.warning("Could not read the filter list from ffmpeg")
            self._filters = set()
        else:
            self._filters = self.parse_filters(result.stdout)

        return self._filters

    @staticmethod
    def parse_filters(output: str) -> set[str]:
        """
        Pulls filter names out of `ffmpeg -filters` output.

        Table rows look like ' T. drawtext  V->V  Draw text on top of video.':
        a flag block, the name, then the signature of what it takes and
        returns.

        The flag block is not a fixed width. ffmpeg 8 prints two characters
        where older builds printed three, so a row is recognised by its `->`
        signature rather than by counting flags — keying off the width made
        every filter look missing on ffmpeg 8, which reported a perfectly good
        build as having no drawtext and quietly dropped the frame numbers.

        **This machine runs ffmpeg 8**, so that is not a historical note: the
        test for this uses output captured from it.

        A static method so it can be tested against captured output without
        ffmpeg being installed.
        """
        names = set()

        for line in output.splitlines():
            fields = line.split()

            # A row is a flag block, a name, and an "in->out" signature.
            if len(fields) < 3 or "->" not in fields[2]:
                continue
            if not 1 <= len(fields[0]) <= 3:
                continue
            if not set(fields[0]) <= set("TSC."):
                continue

            names.add(fields[1])

        return names

    def has_filter(self, name: str) -> bool:
        """Whether a named filter is available in this build."""
        return name in self.available_filters()

    # --- REPORTING ---

    def versions(self) -> dict[str, str]:
        """
        Resolved tool versions, for the job sidecar.

        When a pass looks wrong months later, this is how you find out which
        ffmpeg build produced it. MediaPipe and OpenCV join this at 3.1, where
        their versions start mattering to the output.
        """
        return {
            "ffmpeg": self.ffmpeg.version if self.ffmpeg else "not found",
            "ffprobe": self.ffprobe.version if self.ffprobe else "not found",
        }


# =====================================================================
# PIPES
#
# A running ffmpeg with one of its streams open, and the whole of its
# lifecycle: starting, reading or writing, closing, reaping, and turning its
# own last words into a useful error.
#
# Here rather than in `media/` because this module owns every subprocess in
# the app — and the point of that rule is swappability. Someone dropping this
# tool into a larger one that does not use ffmpeg replaces this module and
# nothing else; if the close-and-reap logic lived beside the frame handling,
# they would have to reimplement that too.
#
# These know about bytes. They know nothing about frames, pixels or formats —
# that is `media/frames.py`, and keeping the split there is what stops this
# module quietly growing media knowledge.
# =====================================================================


class FFmpegReadPipe:
    """ffmpeg writing bytes we read, until it runs out of them."""

    def __init__(self, process: subprocess.Popen):
        self._process = process

    def read_exactly(self, count: int) -> bytes | None:
        """
        Exactly `count` bytes, or None once the stream has ended.

        Raises:
            RuntimeError: The stream ended part way through — fewer than
                `count` bytes but more than zero. That is a truncated read
                rather than an ending, and treating it as an ending would
                silently lose everything after it.
        """
        if self._process.stdout is None:
            raise RuntimeError("this pipe was not opened for reading")

        chunk = self._process.stdout.read(count)
        if not chunk:
            return None

        if len(chunk) != count:
            raise RuntimeError(f"stream ended after {len(chunk)} bytes of an expected {count}")

        return chunk

    def close(self) -> None:
        """
        Stops ffmpeg and reaps it.

        Notes:
            Kills rather than waits. A reader is routinely abandoned part way
            through — the caller found what it needed — and ffmpeg will not
            exit on its own while it still has bytes to push into a pipe
            nobody is draining.
        """
        if self._process.poll() is None:
            self._process.kill()

        for stream in (self._process.stdout, self._process.stderr):
            if stream is not None:
                stream.close()

        self._process.wait()

    @property
    def is_running(self) -> bool:
        """For a test that wants to prove nothing was left behind."""
        return self._process.poll() is None


class FFmpegWritePipe:
    """ffmpeg reading bytes we write, until we tell it we are done."""

    def __init__(self, process: subprocess.Popen, describes: str):
        self._process = process
        self._describes = describes  # For an error message, usually the output path

    def write(self, data: bytes) -> None:
        """
        Hands bytes to ffmpeg.

        Raises:
            RuntimeError: ffmpeg has already exited, which means the encode
                failed and every further byte would vanish into a closed
                pipe. Its own message says why; ours would not.
        """
        if self._process.stdin is None:
            raise RuntimeError("this pipe was not opened for writing")

        try:
            self._process.stdin.write(data)
        except BrokenPipeError:
            raise RuntimeError(f"ffmpeg stopped while writing {self._describes}: {self._stderr()}")

    def finish(self) -> None:
        """
        Closes the input and waits for ffmpeg to finish the container.

        Raises:
            RuntimeError: ffmpeg exited badly, with its own last words.

        Notes:
            This is the half that matters. ffmpeg only completes a container
            when its input closes, so a pipe that is never finished leaves a
            file that will not play.
        """
        if self._process.stdin is not None:
            self._process.stdin.close()

        _, stderr = self._process.communicate()

        if self._process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            reason = message.splitlines()[-1] if message else "no output"
            raise RuntimeError(f"Could not write {self._describes}: {reason}")

    def abandon(self) -> None:
        """
        Kills ffmpeg without checking how it went.

        Notes:
            For unwinding from an error the caller already has. Raising a
            "writer failed" on top of the original exception would hide the
            one that says what actually went wrong.
        """
        self._process.kill()
        self._process.wait()

    def _stderr(self) -> str:
        if self._process.stderr is None:
            return ""
        return self._process.stderr.read().decode("utf-8", errors="replace").strip()
