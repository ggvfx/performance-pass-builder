"""
Tests for the Test Fixtures.

The clips are the deliverable of task 1.8, and every later test asserts exact
numbers against them — so if a clip is not what conftest.py claims, those
tests are measuring the wrong thing and still passing.

This is the one place that checks the measuring stick.
"""

import json
import subprocess

import pytest

from tests.conftest import CLIP_HEIGHT, CLIP_SPECS, CLIP_WIDTH, FACE_CLIP_SPECS


def probe(path) -> dict:
    """The video stream's own report, read straight from ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def video_stream(path) -> dict | None:
    streams = probe(path)["streams"]
    return next((s for s in streams if s["codec_type"] == "video"), None)


def audio_stream(path) -> dict | None:
    streams = probe(path)["streams"]
    return next((s for s in streams if s["codec_type"] == "audio"), None)


# --- CONSTANT FRAME RATE CLIPS ---


@pytest.mark.parametrize("name", list(CLIP_SPECS))
def test_each_clip_has_the_rate_and_length_it_claims(clips, name):
    """
    Exact, not approximate. A test that asserts 48 frames against a clip that
    happens to have 47 is a test that proves nothing.
    """
    rate, frames = CLIP_SPECS[name]
    stream = video_stream(clips[name])

    print(f"{name}: {stream['r_frame_rate']}, {stream['nb_frames']} frames")
    assert stream["r_frame_rate"] == rate
    assert int(stream["nb_frames"]) == frames


def test_the_ntsc_clip_is_an_exact_rational_not_a_rounded_float():
    """
    The rate this whole project exists to handle without drifting. If ffmpeg
    ever writes 23.976 here instead, every frame-accuracy test built on this
    clip is quietly testing the wrong thing.
    """
    assert CLIP_SPECS["ntsc24"][0] == "24000/1001"


def test_the_clips_are_not_square(clips):
    """A transposed width and height would pass unnoticed on a square clip."""
    stream = video_stream(clips["film24"])

    assert stream["width"] == CLIP_WIDTH
    assert stream["height"] == CLIP_HEIGHT
    assert CLIP_WIDTH != CLIP_HEIGHT


# --- AUDIO ---


def test_the_aac_clip_carries_audio_the_container_can_hold(clips):
    """The normal path: stream-copied into the pass untouched."""
    stream = audio_stream(clips["with_audio"])

    assert stream is not None
    assert stream["codec_name"] == "aac"
    assert int(stream["sample_rate"]) == 48000


def test_the_pcm_clip_carries_audio_mp4_cannot_hold(clips):
    """
    Without this clip the encode stage's fallback — encode once at a high
    bitrate, and say so in the sidecar — is never exercised.
    """
    stream = audio_stream(clips["pcm_audio"])

    assert stream is not None
    assert stream["codec_name"] == "pcm_s24le"


def test_the_silent_clips_really_are_silent(clips):
    """Two of the probe's branches depend on there being no audio stream at all."""
    for name in CLIP_SPECS:
        assert audio_stream(clips[name]) is None, f"{name} should have no audio"


# --- THE AWKWARD CASES ---


def test_the_vfr_clip_really_is_variable(clips):
    """
    The probe refuses this. If the clip were secretly constant, the refusal
    would never fire and the test asserting it would pass for the wrong reason.
    """
    stream = video_stream(clips["vfr"])

    print(f"vfr: r_frame_rate={stream['r_frame_rate']} avg_frame_rate={stream['avg_frame_rate']}")
    assert stream["r_frame_rate"] != stream["avg_frame_rate"], (
        "the two rates agreeing means this clip is constant frame rate"
    )


def test_the_h265_clip_is_h265(clips):
    """The mezzanine keeps the source's codec, so this proves the libx265 path."""
    assert video_stream(clips["h265"])["codec_name"] == "hevc"


def test_the_audio_only_clip_has_no_picture(clips):
    """A source with no video stream has to be rejected rather than crashed on."""
    assert video_stream(clips["audio_only"]) is None
    assert audio_stream(clips["audio_only"]) is not None


# --- REAL FOOTAGE ---


def test_the_face_clip_is_what_conftest_claims(one_face):
    """
    The measuring stick again, for the one clip nobody can regenerate. A
    different file dropped in under the same name would make the tracking
    tests measure something else and still look like a tracking bug.
    """
    _, width, height, rate, frames = FACE_CLIP_SPECS["one_face"]
    stream = video_stream(one_face)

    print({k: stream[k] for k in ("width", "height", "r_frame_rate", "nb_frames")})
    assert stream["width"] == width
    assert stream["height"] == height
    assert stream["r_frame_rate"] == rate
    assert int(stream["nb_frames"]) == frames


def test_the_face_clip_has_the_audio_a_pass_would_carry(one_face):
    """
    Real footage comes with sound, and non-negotiable 3 says a carried track
    is untouched. The generated clips cover that path, but this is the first
    one where the audio was not made by a sine generator.
    """
    assert audio_stream(one_face) is not None


def test_the_face_clip_is_not_tracked_by_git(one_face):
    """
    The one that matters. This repository is public, and footage is often a
    client's — so the clip living in the working tree is only safe for as
    long as git is genuinely ignoring it.
    """
    result = subprocess.run(
        ["git", "check-ignore", str(one_face)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"{one_face.name} is NOT gitignored and could be committed"


# --- HOUSEKEEPING ---


def test_no_generated_clip_is_written_inside_the_repository(clips):
    """
    The repo is public and media is gitignored, but the safest version of that
    is media that never lands in the working tree at all.

    Real footage in `tests/media/` is the deliberate exception — it cannot be
    generated, so it is kept in the tree and ignored instead, which the test
    above checks rather than assumes.
    """
    from src.core.config import REPO_ROOT

    for name, path in clips.items():
        assert REPO_ROOT not in path.resolve().parents, f"{name} was written into the repo"
