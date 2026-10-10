"""
Shared Test Fixtures.

Generates short test clips with ffmpeg rather than committing media to the
repository — which is public, and footage is often a client's. Every clip has
a known frame rate, frame count and geometry, so a test can assert exact
numbers rather than "about right".

Tests needing these are skipped when ffmpeg is not installed, so the suite
still runs on a machine without it.

**Frame counts are pinned with `-frames:v` rather than derived from a
duration.** At 24000/1001 a "2 second" clip is 47.952 frames, and which way
that rounds is exactly the kind of thing this project must not be vague about.

Notes:
    There is no clip with a face in it. MediaPipe needs real footage, and
    nothing synthetic that ffmpeg can generate will produce landmarks — that
    is a Phase 3 problem, solved with a short clip kept outside the repo.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.ffmpeg_tools import MediaToolchain

# --- CLIP GEOMETRY ---

# Small enough that a session's worth of clips generates in a second or two,
# and not square, so a transposed width and height cannot pass unnoticed.
CLIP_WIDTH = 320
CLIP_HEIGHT = 240

# --- CONSTANT FRAME RATE CLIPS ---

# name -> (rate as ffmpeg takes it, exact frame count)
#
# ntsc24 is the important one: 24000/1001 is the rate this project exists to
# handle exactly, and the one a float would drift against.
# Written as rationals throughout, including the whole-number rates: that is
# the form ffprobe reports back (24/1, never 24), and comparing against it is
# how these specs stay checkable rather than approximately right.
CLIP_SPECS = {
    "ntsc24": ("24000/1001", 48),
    "pal25": ("25/1", 50),
    "film24": ("24/1", 48),
}


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    """Whether ffmpeg and ffprobe are both on PATH."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture(scope="session")
def toolchain(ffmpeg_available) -> MediaToolchain:
    """A discovered toolchain, skipping the test when ffmpeg is missing."""
    if not ffmpeg_available:
        pytest.skip("ffmpeg is not installed")
    return MediaToolchain()


def _run(command: list[str]) -> None:
    """Runs one generation command, failing the session loudly if it cannot."""
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture(scope="session")
def clips(ffmpeg_available, tmp_path_factory) -> dict[str, Path]:
    """
    Generates every test clip once per session.

    Returns:
        dict of clip name -> Path. See the comments against each for what it
        is for; a test should say which property it depends on.
    """
    if not ffmpeg_available:
        pytest.skip("ffmpeg is not installed")

    directory = tmp_path_factory.mktemp("clips")
    paths: dict[str, Path] = {}

    # --- CONSTANT FRAME RATE, NO AUDIO ---

    for name, (rate, frames) in CLIP_SPECS.items():
        output = directory / f"{name}.mov"
        _run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi",
            "-i", f"testsrc=size={CLIP_WIDTH}x{CLIP_HEIGHT}:rate={rate}",
            "-frames:v", str(frames),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(output),
        ])
        paths[name] = output

    # --- WITH AUDIO THE CONTAINER CAN HOLD ---

    # aac in mp4 stream-copies into the pass untouched, which is the normal
    # path and what non-negotiable 3 asks for.
    with_audio = directory / "with_audio.mp4"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={CLIP_WIDTH}x{CLIP_HEIGHT}:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-frames:v", "48",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(with_audio),
    ])
    paths["with_audio"] = with_audio

    # --- WITH AUDIO THE CONTAINER CANNOT HOLD ---

    # 24-bit PCM off a camera is the usual case mp4 will not take, so the pass
    # has to encode it once at a high bitrate and the sidecar has to say so.
    # Without a clip like this that branch is never exercised.
    pcm_audio = directory / "pcm_audio.mov"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={CLIP_WIDTH}x{CLIP_HEIGHT}:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-frames:v", "48",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "pcm_s24le",
        "-shortest",
        str(pcm_audio),
    ])
    paths["pcm_audio"] = pcm_audio

    # --- VARIABLE FRAME RATE ---

    # Dropping every other frame for the first part leaves r_frame_rate and
    # avg_frame_rate disagreeing, which is what the probe refuses on. Without
    # this clip the refusal is never proven to fire.
    vfr = directory / "vfr.mov"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={CLIP_WIDTH}x{CLIP_HEIGHT}:rate=25:duration=3",
        "-vf", "select='not(mod(n,2))+gte(n,40)'",
        "-fps_mode", "vfr",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(vfr),
    ])
    paths["vfr"] = vfr

    # --- H265 ---

    # The mezzanine keeps the source's own codec, so this is the clip that
    # proves the libx265 path rather than assuming it.
    h265 = directory / "h265.mp4"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={CLIP_WIDTH}x{CLIP_HEIGHT}:rate=24",
        "-frames:v", "48",
        "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p",
        str(h265),
    ])
    paths["h265"] = h265

    # --- NOT A VIDEO ---

    # A source with no video stream has to be rejected rather than crashed on.
    audio_only = directory / "audio_only.mov"
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1",
        "-c:a", "aac",
        str(audio_only),
    ])
    paths["audio_only"] = audio_only

    return paths
