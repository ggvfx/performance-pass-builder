"""
Tests for `landmarks.json`.

The file is the numbers behind the mesh, written for whatever comes after
this app — so what matters is that it round-trips, that a gap stays a gap,
and that it cannot quietly describe the wrong source or the wrong person.

No model and no footage: these run against arrays.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from src.core.models import (
    LANDMARK_COUNT,
    NOT_SEEDED,
    Face,
    FaceTrack,
    NormalisedBox,
    Seed,
    SourceInfo,
)
from src.performance.landmarks import (
    LANDMARKS_SCHEMA_VERSION,
    landmarks_path_for,
    read_landmarks,
    write_landmarks,
)

NOW = datetime.now(timezone.utc)


def a_source(frame_count=12) -> SourceInfo:
    return SourceInfo(
        path="C:/footage/take_01.mov",
        width=1920,
        height=1080,
        fps_numerator=24000,
        fps_denominator=1001,
        frame_count=frame_count,
        codec="h264",
    )


def a_face(label="Woman", frames=(0,)) -> Face:
    return Face(
        label=label,
        seeds=[
            Seed(frame=frame, box=NormalisedBox(left=0.4, top=0.3, right=0.6, bottom=0.7))
            for frame in frames
        ],
    )


def a_track(label="Woman", frame_count=12, missing=(), seeds=None) -> FaceTrack:
    generator = np.random.default_rng(3)
    landmarks = generator.random((frame_count, LANDMARK_COUNT, 3)).astype(np.float32)
    tracked = np.ones(frame_count, dtype=bool)
    seeded_by = np.array(
        seeds if seeds is not None else [0] * frame_count, dtype=np.int16
    )

    for frame in missing:
        landmarks[frame] = np.nan
        tracked[frame] = False
        seeded_by[frame] = NOT_SEEDED

    return FaceTrack(label=label, landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)


def write(tmp_path, source=None, faces=None, tracks=None):
    source = source or a_source()
    return write_landmarks(
        tmp_path / "out.json",
        source,
        faces if faces is not None else [a_face()],
        tracks if tracks is not None else [a_track()],
        NOW,
    )


# --- NAMING ---


def test_the_file_sits_beside_the_other_deliverables(tmp_path):
    from pathlib import Path

    assert landmarks_path_for(Path("D:/f/take_01.mov"), tmp_path).name == (
        "take_01_landmarks.json"
    )


# --- WHAT IS IN IT ---


def test_it_is_readable_json(tmp_path):
    document = json.loads(write(tmp_path).read_text(encoding="utf-8"))

    assert document["schema_version"] == LANDMARKS_SCHEMA_VERSION
    assert document["landmark_count"] == LANDMARK_COUNT
    assert document["faces"][0]["label"] == "Woman"


def test_it_records_the_source_it_describes(tmp_path):
    """
    So a file found next to the wrong footage can be told apart from one
    that belongs to it.
    """
    document = json.loads(write(tmp_path).read_text(encoding="utf-8"))

    assert document["source"]["name"] == "take_01.mov"
    assert document["source"]["frame_count"] == 12
    assert document["source"]["fps_numerator"] == 24000
    assert document["source"]["fps_denominator"] == 1001


def test_it_says_what_the_numbers_mean(tmp_path):
    """
    Three unlabelled floats per point is an invitation to assume z is depth.
    It is not, and the file says so where someone will read it.
    """
    document = json.loads(write(tmp_path).read_text(encoding="utf-8"))

    assert "fractions of the picture" in document["coordinates"]
    assert "not metric" in document["coordinates"]


def test_it_records_where_the_seeds_were(tmp_path):
    """Half the point of the file: which box produced which stretch."""
    face = a_face(frames=(0, 6))
    track = a_track(seeds=[0] * 6 + [1] * 6)

    document = json.loads(write(tmp_path, faces=[face], tracks=[track]).read_text("utf-8"))
    recorded = document["faces"][0]

    assert [seed["frame"] for seed in recorded["seeds"]] == [0, 6]
    assert recorded["seeds"][0]["box"]["left"] == 0.4
    assert {segment["seed_index"] for segment in recorded["segments"]} == {0, 1}


def test_it_records_the_gaps(tmp_path):
    document = json.loads(write(tmp_path, tracks=[a_track(missing=[4, 5])]).read_text("utf-8"))
    recorded = document["faces"][0]

    assert recorded["frames_tracked"] == 10
    assert recorded["frames_missing"] == 2
    assert recorded["gaps"] == [{"start_frame": 4, "end_frame": 5}]


def test_a_gap_is_null_rather_than_numbers(tmp_path):
    """
    The rule the whole project keeps. Anyone reading this can tell "not
    found" from "found, and here it is" — which is the distinction that
    matters when a mesh looks wrong.
    """
    document = json.loads(write(tmp_path, tracks=[a_track(missing=[4])]).read_text("utf-8"))

    rows = document["faces"][0]["landmarks"]
    assert rows[4] is None
    assert rows[3] is not None
    assert len(rows) == 12, "a gap is still a frame"


def test_every_face_is_written(tmp_path):
    faces = [a_face("Woman"), a_face("Man")]
    tracks = [a_track("Woman"), a_track("Man")]

    document = json.loads(write(tmp_path, faces=faces, tracks=tracks).read_text("utf-8"))

    assert [face["label"] for face in document["faces"]] == ["Woman", "Man"]


# --- ROUND TRIP ---


def test_the_points_come_back_as_they_went_in(tmp_path):
    track = a_track(missing=[2, 3])

    restored = read_landmarks(write(tmp_path, tracks=[track]))["faces"][0]["landmarks"]

    assert restored.shape == (12, LANDMARK_COUNT, 3)
    assert np.isnan(restored[2]).all(), "a gap should read back as NaN"
    assert np.allclose(restored[0], track.landmarks[0], atol=1e-5)


def test_rounding_stays_far_below_a_pixel(tmp_path):
    """
    Five decimal places is about 0.04 of a pixel at 4K — finer than any
    landmark is accurate to, and a third of the characters of writing
    float32's full repr for every one of them.
    """
    track = a_track()

    restored = read_landmarks(write(tmp_path, tracks=[track]))["faces"][0]["landmarks"]
    worst = float(np.nanmax(np.abs(restored - track.landmarks)))

    print(f"worst error {worst * 3840:.4f} px at 4K")
    assert worst * 3840 < 0.1


def test_a_file_from_another_version_is_refused(tmp_path):
    path = write(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="schema version"):
        read_landmarks(path)


# --- WHAT IT REFUSES ---


def test_a_track_with_no_chosen_face_is_refused(tmp_path):
    """
    Matched by label rather than position: matching by index would quietly
    attribute one person's seeds to another's landmarks.
    """
    with pytest.raises(ValueError, match="Stranger"):
        write(tmp_path, faces=[a_face("Woman")], tracks=[a_track("Stranger")])


def test_a_track_that_is_not_the_sources_length_is_refused(tmp_path):
    """
    Every pass is exactly as long as what it came from. A short track here
    would describe frames that do not line up with the footage.
    """
    with pytest.raises(ValueError, match="240 frames"):
        write(tmp_path, source=a_source(frame_count=240), tracks=[a_track(frame_count=12)])


# --- SIZE ---


def test_the_file_is_written_compactly(tmp_path):
    """
    Nobody reads 344,000 numbers by eye, and indenting them would add
    megabytes. The sidecar is the file written for people.
    """
    text = write(tmp_path).read_text(encoding="utf-8")
    indented = json.dumps(json.loads(text), indent=2)

    print(f"{len(text) / 1024:.0f} KB compact against {len(indented) / 1024:.0f} KB indented")
    assert "\n" not in text
    assert '": "' not in text, "keys are separated as though indented"
    assert len(text) < len(indented) / 2


def test_the_directory_is_made_if_it_is_not_there(tmp_path):
    path = write_landmarks(
        tmp_path / "nested" / "out.json", a_source(), [a_face()], [a_track()], NOW
    )

    assert path.is_file()
