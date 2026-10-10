"""
Review Proxy Creation.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Builds the small video the browser plays while faces are selected.

Why a proxy rather than the source: browsers seek long-GOP h264 and h265
approximately, landing near a frame rather than on it, and Chrome plays h265
only where the hardware allows. Neither is acceptable when the whole point is
knowing exactly which frame a box was drawn on.

The proxy is all-intra h264 at a small size, so every frame is a keyframe,
seeking is exact and instant, and it plays in any browser. It is built from
the mezzanine, which has already been verified frame-for-frame against the
source, so frame N of the proxy is provably frame N of what will be tracked.

Each frame carries its own number burned into the corner. That turns the one
real risk — the player's idea of the current frame drifting from the picture —
into something a person can see rather than something they have to trust.
"""

import logging
from pathlib import Path

from src.core.config import (
    DRAWTEXT_FILTER,
    PROXY_CRF,
    PROXY_PRESET,
    PROXY_SUFFIX,
    PROXY_WIDTH,
)
from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import SourceInfo

# --- FRAME NUMBERS ---

# Monospaced faces, so the counter does not jitter as the digits change.
FONT_CANDIDATES = (
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)

FONT_SIZE = 22


class ProxyBuilder:
    """
    Builds the review proxy for a job.

    Holds the toolchain, and resolves a font once rather than per call.
    """

    def __init__(self, toolchain: MediaToolchain):
        self.toolchain = toolchain
        self._font: str | None = None
        self._font_resolved = False

    # --- NAMING ---

    @staticmethod
    def proxy_path_for(source: SourceInfo, output_dir: Path) -> Path:
        """Returns the proxy path for a source, e.g. 'take_01_proxy.mp4'."""
        return output_dir / f"{Path(source.path).stem}{PROXY_SUFFIX}"

    # --- FONT ---

    def font_path(self) -> str | None:
        """
        The first monospaced font this machine actually has.

        Returns None when none is found, in which case the proxy is built
        without the frame counter rather than failing — the player still
        works, it just loses its cross-check.
        """
        if not self._font_resolved:
            self._font = next((path for path in FONT_CANDIDATES if Path(path).is_file()), None)
            self._font_resolved = True

            if self._font is None:
                logging.warning("No monospaced font found; the proxy will have no frame numbers")

        return self._font

    def video_filter(self) -> str:
        """
        The scale and frame-number filter chain.

        Notes:
            drawtext needs its font path escaped for ffmpeg's own parser,
            which reads a colon as an argument separator — so "C:/..." has to
            be written "C\\:/...".

            Two things can take the counter away, and neither should be fatal.
            A machine with no monospaced font, and — found on a Mac — an
            ffmpeg built without libfreetype, which has no drawtext at all.
            Asking for it there does not degrade the encode, it aborts it:
            ffmpeg rejects the entire output with "Filter not found", so no
            proxy is built and faces cannot be selected at all.

            The frame counter is a cross-check, not the product. Losing it
            costs the burned-in numbers. Asking for it anyway costs the job.
        """
        scale = f"scale={PROXY_WIDTH}:-2"

        if not self.toolchain.has_filter(DRAWTEXT_FILTER):
            logging.warning(
                "This ffmpeg has no drawtext filter, so the review proxy will "
                "have no frame numbers. It was most likely built without "
                "libfreetype."
            )
            return scale

        font = self.font_path()
        if font is None:
            return scale

        escaped = font.replace(":", r"\:")
        counter = (
            f"drawtext=fontfile='{escaped}'"
            f":text='%{{n}}'"
            f":x=8:y=8"
            f":fontsize={FONT_SIZE}"
            f":fontcolor=yellow"
            f":box=1:boxcolor=black@0.7"
        )
        return f"{scale},{counter}"

    # --- BUILDING ---

    def build(self, mezzanine_path: Path, output_path: Path, timeout: float = 1800.0) -> Path:
        """
        Writes the review proxy.

        Args:
            mezzanine_path: The all-intra mezzanine to build from, so frame
                numbers line up with what will be tracked.
            output_path: Where the proxy is written.
            timeout: Generous; this is a small encode but a long source still
                takes a while to read.

        Returns:
            Path to the proxy.

        Raises:
            RuntimeError: If ffmpeg fails, with its own last words attached.

        Notes:
            No audio. The proxy is for looking at a frame, and the deliverable
            carries the real thing — a second copy here would only be another
            file to keep in step.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = self.toolchain.run_ffmpeg(
            [
                "-y",
                "-i", str(mezzanine_path),
                "-map", "0:v:0",
                "-vf", self.video_filter(),
                "-c:v", "libx264",
                "-preset", PROXY_PRESET,
                "-crf", str(PROXY_CRF),
                # Every frame a keyframe, so the browser can seek to any of them
                "-g", "1",
                "-pix_fmt", "yuv420p",
                # Metadata at the front, so the browser can play before the
                # whole file has arrived
                "-movflags", "+faststart",
                "-an",
                str(output_path),
            ],
            timeout=timeout,
        )

        if result.returncode != 0:
            reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
            raise RuntimeError(f"Could not build a review proxy: {reason}")

        logging.info(f"Built review proxy at {output_path}")
        return output_path
