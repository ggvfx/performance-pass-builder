"""
Tests for the FFmpeg Toolchain.

The parsers are the part worth testing, and they are static methods so this
runs with or without ffmpeg installed. The fixtures below are **captured from
ffmpeg 8.0.1 on the development machine**, not invented: the filter table's
flag block narrowed from three characters to two in ffmpeg 8, and a parser
that counts flag widths reports a perfectly good build as having no filters at
all.
"""

import shutil

import pytest

from src.core.ffmpeg_tools import MediaToolchain, ToolInfo

# --- CAPTURED OUTPUT ---

# From `ffmpeg -hide_banner -filters` on 8.0.1. Note the two-character flag
# block on drawtext, where ffmpeg 7 and earlier printed three.
FILTERS_FFMPEG_8 = """Filters:
  T.. = Timeline support
  .S. = Slice threading
  A = Audio input/output
  V = Video input/output
  N = Dynamic number and/or type of input/output
 ... abench            A->A       Benchmark part of a filtergraph.
 T. drawtext          V->V       Draw text on top of video frames using libfreetype library.
 ..C scale             V->V       Scale the input video size and/or convert the image format.
 ... anullsink         A->N       Do absolutely nothing with the input audio.
"""

# The same table as an older build printed it, three characters wide.
FILTERS_FFMPEG_7 = """Filters:
  T.. = Timeline support
 T.. drawtext          V->V       Draw text on top of video frames using libfreetype library.
 ..C scale             V->V       Scale the input video size and/or convert the image format.
"""

# From `ffmpeg -hide_banner -encoders` on 8.0.1.
ENCODERS_FFMPEG_8 = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ....B. = Supports draw_horiz_band
 .....D = Supports direct rendering method 1
 ------
 V....D a64multi             Multicolor charset for Commodore 64 (codec a64_multi)
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
"""


# --- FILTER PARSING ---


def test_drawtext_is_found_on_ffmpeg_8():
    """
    The regression this file exists for.

    A build without libfreetype has no drawtext, and asking for it does not
    degrade the encode — it aborts the whole output with "Filter not found".
    So the proxy checks first. A parser that misreports drawtext as missing
    silently drops the burned-in frame numbers instead, which is the one
    cross-check the selection step has.
    """
    filters = MediaToolchain.parse_filters(FILTERS_FFMPEG_8)

    print(f"parsed from ffmpeg 8: {sorted(filters)}")
    assert "drawtext" in filters
    assert "scale" in filters


def test_the_same_table_parses_on_an_older_build():
    """Three-character flag blocks have to keep working; artists are not all current."""
    filters = MediaToolchain.parse_filters(FILTERS_FFMPEG_7)

    assert "drawtext" in filters
    assert "scale" in filters


def test_the_legend_is_not_mistaken_for_filters():
    """The header block above the table has no `->` signature, which is how it is told apart."""
    filters = MediaToolchain.parse_filters(FILTERS_FFMPEG_8)

    for heading in ("Filters:", "=", "Timeline", "support"):
        assert heading not in filters, heading


def test_audio_filters_are_parsed_too():
    """A->A and A->N are signatures as much as V->V is."""
    filters = MediaToolchain.parse_filters(FILTERS_FFMPEG_8)

    assert "abench" in filters
    assert "anullsink" in filters


def test_no_filters_from_empty_output():
    assert MediaToolchain.parse_filters("") == set()


# --- ENCODER PARSING ---


def test_encoders_are_parsed():
    encoders = MediaToolchain.parse_encoders(ENCODERS_FFMPEG_8)

    print(f"parsed from ffmpeg 8: {sorted(encoders)}")
    assert {"libx264", "libx265", "aac", "a64multi"} <= encoders


def test_the_encoder_legend_is_not_mistaken_for_encoders():
    """
    Every legend row has a six character flag block like a real row does, so
    they are told apart by the `=` that follows instead.
    """
    encoders = MediaToolchain.parse_encoders(ENCODERS_FFMPEG_8)

    assert "=" not in encoders
    assert "Video" not in encoders
    assert "------" not in encoders


def test_no_encoders_from_empty_output():
    assert MediaToolchain.parse_encoders("") == set()


# --- READINESS ---


def test_a_toolchain_that_found_nothing_is_not_ready():
    """
    Missing tools are reported, not raised: the dependency panel explains them
    to the user, and only a caller that skipped `is_ready` gets an exception.
    """
    toolchain = MediaToolchain(discover=False)

    assert toolchain.is_ready is False

    with pytest.raises(RuntimeError, match="ffmpeg is not available"):
        toolchain.run_ffmpeg(["-version"])

    with pytest.raises(RuntimeError, match="ffprobe is not available"):
        toolchain.run_ffprobe(["-version"])


def test_lists_are_empty_rather_than_failing_without_ffmpeg():
    """The Setup panel asks these before ffmpeg is necessarily installed."""
    toolchain = MediaToolchain(discover=False)

    assert toolchain.available_encoders() == set()
    assert toolchain.available_filters() == set()
    assert toolchain.has_encoder("libx264") is False
    assert toolchain.has_filter("drawtext") is False


def test_versions_name_what_is_missing_rather_than_omitting_it():
    """A sidecar key that is simply absent cannot be told from an older format."""
    versions = MediaToolchain(discover=False).versions()

    assert versions == {"ffmpeg": "not found", "ffprobe": "not found"}


def test_a_hand_built_toolchain_is_ready():
    """`discover=False` exists so a test can set the tools without a real install."""
    toolchain = MediaToolchain(discover=False)
    toolchain.ffmpeg = ToolInfo(name="ffmpeg", path="/usr/bin/ffmpeg", version="ffmpeg version 8.0.1")
    toolchain.ffprobe = ToolInfo(name="ffprobe", path="/usr/bin/ffprobe", version="ffprobe version 8.0.1")

    assert toolchain.is_ready is True
    assert toolchain.versions()["ffmpeg"] == "ffmpeg version 8.0.1"


# --- AGAINST THE REAL INSTALL ---

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@needs_ffmpeg
def test_discovery_finds_the_real_tools():
    toolchain = MediaToolchain()

    assert toolchain.is_ready, "ffmpeg is on PATH but was not discovered"
    assert toolchain.ffmpeg.path.is_file()
    assert "ffmpeg" in toolchain.ffmpeg.version.lower()


@needs_ffmpeg
def test_the_real_build_reports_what_the_pass_needs():
    """
    The two the proxy and the mezzanine depend on. If this fails on a machine,
    that machine cannot build a pass — which is exactly what the dependency
    panel is for.
    """
    toolchain = MediaToolchain()

    print(f"encoders found: {len(toolchain.available_encoders())}")
    print(f"filters found: {len(toolchain.available_filters())}")
    assert toolchain.has_encoder("libx264")
    assert toolchain.has_filter("drawtext")
