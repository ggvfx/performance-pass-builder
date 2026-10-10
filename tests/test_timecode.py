"""
Tests for the Timecode Engine.

The arithmetic this project is most exposed to. Frames and labels are kept
strictly apart: frames are real pictures, labels are what timecode counts, and
at 29.97 drop-frame the two diverge by design.

Nothing here touches ffmpeg, so it all runs on any machine.
"""

from fractions import Fraction

import pytest

from src.core.models import SourceInfo
from src.core.timecode import Timecode

NTSC_24 = (24000, 1001)
PAL_25 = (25, 1)
NTSC_30_DF = (30000, 1001)
NTSC_60_DF = (60000, 1001)


# --- CONSTRUCTION ---


def test_a_rate_must_be_positive():
    for numerator, denominator in ((0, 1001), (24000, 0), (-24, 1)):
        with pytest.raises(ValueError, match="must be positive"):
            Timecode(numerator, denominator)


def test_a_bad_start_timecode_fails_now_rather_than_mid_job():
    """Validated in the constructor, so the job does not die at output time."""
    with pytest.raises(ValueError):
        Timecode(*PAL_25, start_timecode="banana")


def test_it_builds_from_a_probed_source():
    source = SourceInfo(
        path="take_01.mov",
        width=1920,
        height=1080,
        fps_numerator=24000,
        fps_denominator=1001,
        frame_count=100,
        codec="h264",
        start_timecode="10:00:00:00",
    )
    timecode = Timecode.from_source(source)

    assert timecode.rate == Fraction(24000, 1001)
    assert timecode.start_timecode == "10:00:00:00"


# --- RATE PROPERTIES ---


def test_a_rounded_rate_counts_the_labels_its_name_implies():
    """23.976 counts 24 labels a second. Hiding that is what timecode is for."""
    assert Timecode(*NTSC_24).labels_per_second == 24
    assert Timecode(*NTSC_30_DF).labels_per_second == 30
    assert Timecode(*PAL_25).labels_per_second == 25


def test_only_2997_and_5994_drop():
    assert Timecode(*NTSC_30_DF).is_drop_frame is True
    assert Timecode(*NTSC_60_DF).is_drop_frame is True

    for rate in (NTSC_24, PAL_25, (30, 1), (24, 1)):
        assert Timecode(*rate).is_drop_frame is False, rate


def test_the_separator_says_which_kind_of_timecode_it_is():
    """A semicolon is how drop-frame announces itself on any display."""
    assert ";" in Timecode(*NTSC_30_DF).frames_to_timecode(0)
    assert ":" in Timecode(*NTSC_24).frames_to_timecode(0)
    assert ";" not in Timecode(*NTSC_24).frames_to_timecode(0)


# --- NON-DROP ---


def test_the_first_frame_is_zero_not_one():
    """Frame 0 is the first picture. Off-by-one here would shift everything."""
    assert Timecode(*PAL_25).frames_to_timecode(0) == "00:00:00:00"


def test_a_whole_second_rolls_over():
    timecode = Timecode(*PAL_25)

    assert timecode.frames_to_timecode(24) == "00:00:00:24"
    assert timecode.frames_to_timecode(25) == "00:00:01:00"


def test_a_rounded_rate_labels_by_the_nominal_count():
    """At 23.976 the 24th frame is 00:00:01:00, because labels count 24 a second."""
    timecode = Timecode(*NTSC_24)

    assert timecode.frames_to_timecode(23) == "00:00:00:23"
    assert timecode.frames_to_timecode(24) == "00:00:01:00"


def test_an_hour_wraps_at_24():
    timecode = Timecode(*PAL_25)
    a_day = 25 * 60 * 60 * 24

    assert timecode.frames_to_timecode(a_day) == "00:00:00:00"


def test_a_negative_frame_is_not_a_frame():
    with pytest.raises(ValueError, match="cannot be negative"):
        Timecode(*PAL_25).frames_to_timecode(-1)


# --- DROP FRAME ---


def test_two_labels_are_dropped_a_minute_at_2997():
    """
    The whole point of drop-frame: 00:00:59;29 is followed by 00:01:00;02,
    because ;00 and ;01 are labels that minute never uses.
    """
    timecode = Timecode(*NTSC_30_DF)
    last_of_the_first_minute = 60 * 30 - 1  # labels run 1:1 until the first drop

    assert timecode.frames_to_timecode(last_of_the_first_minute) == "00:00:59;29"
    assert timecode.frames_to_timecode(last_of_the_first_minute + 1) == "00:01:00;02"


def test_the_tenth_minute_drops_nothing():
    """Which is what keeps the clock honest over an hour."""
    timecode = Timecode(*NTSC_30_DF)
    frames = timecode.timecode_to_frames("00:10:00;00")

    assert timecode.frames_to_timecode(frames) == "00:10:00;00"


def test_a_dropped_label_is_rejected_rather_than_quietly_accepted():
    """00:01:00;00 does not exist at 29.97, and accepting it would shift a frame."""
    timecode = Timecode(*NTSC_30_DF)

    with pytest.raises(ValueError, match="never occurs"):
        timecode.timecode_to_frames("00:01:00;00")

    timecode.timecode_to_frames("00:10:00;00")  # the tenth minute is fine


def test_5994_drops_four():
    assert Timecode(*NTSC_60_DF).dropped_labels_per_minute == 4
    assert Timecode(*NTSC_30_DF).dropped_labels_per_minute == 2
    assert Timecode(*PAL_25).dropped_labels_per_minute == 0


# --- ROUND TRIPS ---


@pytest.mark.parametrize("rate", [NTSC_24, PAL_25, NTSC_30_DF, NTSC_60_DF, (24, 1), (30, 1)])
def test_every_frame_of_a_long_run_survives_a_round_trip(rate):
    """
    The property that matters more than any single value: a frame turned into
    a timecode and back is the same frame, at every rate, across the minute
    boundaries where drop-frame does its work.
    """
    timecode = Timecode(*rate)

    for frame in range(0, 20_000, 7):
        shown = timecode.frames_to_timecode(frame)
        assert timecode.timecode_to_frame_index(shown) == frame, f"{frame} -> {shown}"


def test_a_start_timecode_offsets_the_display_but_not_the_index():
    """
    What the editor sees and what the file counts are different numbers, and
    confusing them is how a frame reference lands an hour out.
    """
    timecode = Timecode(*PAL_25, start_timecode="10:00:00:00")

    assert timecode.frames_to_timecode(0) == "10:00:00:00"
    assert timecode.frames_to_timecode(25) == "10:00:01:00"
    assert timecode.timecode_to_frame_index("10:00:01:00") == 25


# --- PARSING ---


def test_a_malformed_timecode_says_what_was_expected():
    timecode = Timecode(*PAL_25)

    for bad in ("00:00:00", "00:00:00:00:00", "aa:bb:cc:dd", ""):
        with pytest.raises(ValueError):
            timecode.timecode_to_frames(bad)


def test_a_field_out_of_range_is_rejected():
    timecode = Timecode(*PAL_25)

    for bad in ("25:00:00:00", "00:60:00:00", "00:00:60:00", "00:00:00:25"):
        with pytest.raises(ValueError, match="out of range"):
            timecode.timecode_to_frames(bad)


# --- SECONDS, FOR FFMPEG ---


def test_a_frame_time_is_exact_not_floating():
    """
    A Fraction, never a float: this becomes an ffmpeg -ss argument, and a time
    landing a millionth of a second early seeks to the wrong frame.
    """
    timecode = Timecode(*NTSC_24)
    at_one_thousand = timecode.frame_to_seconds(1000)

    assert isinstance(at_one_thousand, Fraction)
    assert at_one_thousand == Fraction(1000 * 1001, 24000)


def test_duration_comes_from_the_frames_and_the_exact_rate():
    """Frames are what a pass is made of; a container's own duration is advisory."""
    timecode = Timecode(*NTSC_24)

    assert timecode.duration_seconds(48) == Fraction(48 * 1001, 24000)
    assert Timecode(*PAL_25).duration_seconds(50) == 2


def test_seconds_format_without_going_through_a_float():
    timecode = Timecode(*NTSC_24)

    assert Timecode.format_seconds(timecode.frame_to_seconds(0)) == "0.000000"
    assert Timecode.format_seconds(timecode.frame_to_seconds(1)) == "0.041708"
    assert Timecode.format_seconds(Fraction(1, 2), decimal_places=2) == "0.50"


def test_formatting_rounds_half_up_rather_than_to_even():
    """Python's round() goes to even, which would put some frames one tick early."""
    assert Timecode.format_seconds(Fraction(5, 1000), decimal_places=2) == "0.01"
    assert Timecode.format_seconds(Fraction(15, 1000), decimal_places=2) == "0.02"


def test_a_negative_time_is_refused():
    with pytest.raises(ValueError, match="cannot be negative"):
        Timecode.format_seconds(Fraction(-1, 24))
