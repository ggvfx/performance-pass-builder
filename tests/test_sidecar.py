"""
Tests for the Sidecar.

The sidecar's job is to make a wrong pass diagnosable six months later, so
what matters is that it records what cannot be recovered from the files
themselves, and that it gets written even when the job failed — especially
then.
"""

import json
from datetime import timezone

import pytest
from pydantic import ValidationError

from src.core.ffmpeg_tools import MediaToolchain
from src.core.models import (
    AudioHandling,
    DepthBackendName,
    DepthModel,
    Layer,
    LayerSource,
    LayerStack,
    OutputFormat,
    SourceInfo,
    StoredDepth,
    ValidationResult,
)
from src.core.sidecar import (
    DeliverableRecord,
    Sidecar,
    capture_environment,
    now,
    sidecar_path_for,
    write_sidecar,
)


def a_source(**overrides) -> SourceInfo:
    fields = {
        "path": "C:/footage/take_01.mov",
        "width": 1920,
        "height": 1080,
        "fps_numerator": 24000,
        "fps_denominator": 1001,
        "frame_count": 100,
        "codec": "h264",
    }
    return SourceInfo(**(fields | overrides))


def a_stack(*sources) -> LayerStack:
    return LayerStack(layers=[Layer(source=s) for s in sources])


def a_deliverable(passed=True) -> DeliverableRecord:
    return DeliverableRecord(
        path="out/take_01_composite.mp4",
        output_format=OutputFormat.H265,
        audio=AudioHandling.COPIED,
        stack=a_stack(LayerSource.DEPTH, LayerSource.FACE_MESH),
        validation=ValidationResult(
            checks={"frame_count": passed, "audio": True},
            failures=[] if passed else ["48 frames, 2 shorter than the source's 50"],
        ),
    )


def a_sidecar(**overrides) -> Sidecar:
    fields = {"written_at": now(), "source": a_source(), "deliverables": [a_deliverable()]}
    return Sidecar(**(fields | overrides))


# --- NAMING ---


def test_the_sidecar_sits_beside_the_deliverables(tmp_path):
    from pathlib import Path

    assert sidecar_path_for(Path("D:/f/take_01.mov"), tmp_path).name == "take_01_performance.json"


# --- THE VERDICT ---


def test_a_job_passes_only_when_every_deliverable_did():
    assert a_sidecar().passed is True
    assert a_sidecar(deliverables=[a_deliverable(), a_deliverable(passed=False)]).passed is False


def test_a_job_that_produced_nothing_has_not_passed():
    """It has not run. `all([])` would otherwise call that a success."""
    assert a_sidecar(deliverables=[]).passed is False


# --- WHAT IS RECORDED ---


def test_the_environment_records_what_cannot_be_recovered_later():
    """
    Which ffmpeg wrote the file and which MediaPipe tracked the face are not
    in the file, so if they are not here they are gone.
    """
    environment = capture_environment(MediaToolchain())

    print(environment)
    for key in ("app", "platform", "python", "ffmpeg", "ffprobe", "mediapipe", "opencv"):
        assert key in environment, key
        assert environment[key], key


def test_something_absent_is_recorded_as_absent_rather_than_omitted():
    """
    A sidecar simply lacking a key cannot be told apart from one written by
    an older version of this app.
    """
    environment = capture_environment(MediaToolchain(discover=False))

    assert environment["ffmpeg"] == "not found"
    assert environment["ffprobe"] == "not found"


def test_the_timestamp_says_which_clock_it_came_from():
    """These files travel between machines; a naive local time is worse than none."""
    assert now().tzinfo is not None
    assert now().astimezone(timezone.utc).tzinfo is timezone.utc


def test_a_deliverable_records_the_stack_that_made_it():
    """
    Which layers, in which order. Without it, "why does this composite look
    like that" has no answer six months on.
    """
    record = a_deliverable()

    assert record.stack.enabled_sources == [LayerSource.DEPTH, LayerSource.FACE_MESH]
    assert record.output_format is OutputFormat.H265
    assert record.audio is AudioHandling.COPIED


def test_depth_and_tracking_are_optional():
    """A job may run one pass, both, or neither."""
    sidecar = a_sidecar()

    assert sidecar.depth is None
    assert sidecar.tracking is None


def test_the_depth_record_carries_its_normalisation():
    """`min_depth` and `max_depth` are what a window's numbers meant."""
    depth = StoredDepth(
        path="work/depth.mkv",
        cache_key="abc",
        backend=DepthBackendName.FAL,
        model=DepthModel.SMALL,
        bit_depth=16,
        min_depth=0.5,
        max_depth=42.0,
        width=1920,
        height=1080,
        frame_count=100,
    )
    sidecar = a_sidecar(depth=depth)

    assert sidecar.depth.min_depth == 0.5
    assert sidecar.depth.model is DepthModel.SMALL


# --- WRITING ---


def test_a_failed_job_is_still_written(tmp_path):
    """
    The whole point. A failed job's sidecar is the most useful thing to look
    at when working out why, and nothing else records it.
    """
    sidecar = a_sidecar(deliverables=[a_deliverable(passed=False)])
    path = write_sidecar(sidecar, tmp_path / "take_01_performance.json")

    assert path.is_file()

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["deliverables"][0]["validation"]["passed"] is False
    assert "2 shorter" in written["deliverables"][0]["validation"]["failures"][0]


def test_what_is_written_is_readable_json_with_the_awkward_types_handled(tmp_path):
    """Paths, datetimes and enums all appear; `json.dump` would refuse them."""
    sidecar = a_sidecar(environment=capture_environment(MediaToolchain(discover=False)))
    path = write_sidecar(sidecar, tmp_path / "s.json")

    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["source"]["path"].endswith("take_01.mov")
    assert written["written_at"]
    assert written["deliverables"][0]["output_format"] == "h265"
    assert written["environment"]["ffmpeg"] == "not found"


def test_a_sidecar_survives_a_round_trip(tmp_path):
    """It is read back by people, and one day by a tool."""
    sidecar = a_sidecar()
    path = write_sidecar(sidecar, tmp_path / "s.json")

    restored = Sidecar.model_validate_json(path.read_text(encoding="utf-8"))

    assert restored.source.frame_count == 100
    assert restored.passed is True
    assert restored.schema_version == sidecar.schema_version


def test_the_directory_is_made_if_it_is_not_there(tmp_path):
    """A missing folder should never be the reason a record is lost."""
    path = write_sidecar(a_sidecar(), tmp_path / "take_01_performance" / "s.json")

    assert path.is_file()


def test_settings_are_free_form_because_config_cannot_be_imported_here():
    """
    `config.py` imports `models.py`, so a model naming a settings type would
    point the dependency arrow backwards. The run settings arrive as a dump.
    """
    sidecar = a_sidecar(settings={"depth_model": "VDA-Small", "near": 0.4, "far": 0.6})

    assert sidecar.settings["near"] == 0.4


def test_a_sidecar_needs_a_source():
    with pytest.raises(ValidationError):
        Sidecar(written_at=now())
