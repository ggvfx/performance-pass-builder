"""
Tests for the Shared Data Models.

Covers what models.py implements: the invariants the types enforce and the
fields derived from other fields. The methods that are still pseudocode are
tested for one thing only — that they raise rather than returning None, which
is the difference between an unimplemented function and a silent wrong answer.
"""

from datetime import datetime, timezone

import numpy as np
import pytest
from pydantic import ValidationError

from src.core.models import (
    LANDMARK_COUNT,
    AudioInfo,
    Layer,
    LayerSource,
    LayerStack,
    OutputRequest,
    DepthBackendName,
    DepthModel,
    DepthWindow,
    Face,
    FaceTrack,
    FaceTrackingReport,
    FrameRange,
    NormalisedBox,
    PreparedJob,
    ProbeReport,
    Seed,
    Selection,
    SourceInfo,
    StoredDepth,
    ValidationResult,
)

# --- HELPERS ---

A_TIME = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


def a_box(left=0.4, top=0.4, right=0.6, bottom=0.6) -> NormalisedBox:
    return NormalisedBox(left=left, top=top, right=right, bottom=bottom)


def a_source(**overrides) -> SourceInfo:
    """A probed source. Overrides are applied before validation, so bad ones raise."""
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


def a_depth(**overrides) -> StoredDepth:
    fields = {
        "path": "work/take_01_depth.mkv",
        "cache_key": "abc123",
        "backend": DepthBackendName.FAL,
        "model": DepthModel.SMALL,
        "bit_depth": 16,
        "min_depth": 0.5,
        "max_depth": 42.0,
        "width": 1920,
        "height": 1080,
        "frame_count": 100,
    }
    return StoredDepth(**(fields | overrides))


def a_track(frame_count=30, label="Woman") -> FaceTrack:
    return FaceTrack(
        label=label,
        landmarks=np.zeros((frame_count, LANDMARK_COUNT, 3), dtype=np.float32),
        tracked=np.ones(frame_count, dtype=bool),
        seeded_by=np.zeros(frame_count, dtype=np.int16),
    )


# --- FRAME RANGES ---


def test_frame_range_counts_both_ends():
    """A gap covering only frame 40 is one frame long, not zero."""
    assert FrameRange(start_frame=40, end_frame=40).frame_count == 1
    assert FrameRange(start_frame=10, end_frame=19).frame_count == 10


def test_frame_range_rejects_a_reversed_range():
    with pytest.raises(ValidationError):
        FrameRange(start_frame=50, end_frame=49)


# --- SOURCE ---


def test_frame_rate_is_two_integers_and_nothing_else():
    """
    The invariant the whole project rests on: a rate cannot be a float.

    CODE_STYLE section 5 — a docstring promising no floating-point drift beside
    a signature taking 23.976 is the trap this asserts away.
    """
    for field in ("fps_numerator", "fps_denominator"):
        annotation = SourceInfo.model_fields[field].annotation
        print(f"SourceInfo.{field}: {annotation}")
        assert annotation is int, f"{field} must be an int, got {annotation}"


def test_frame_rate_keeps_the_exact_pair():
    """24000/1001 is what the sidecar has to record, not 23.976 and not 24/1."""
    source = a_source()

    assert source.fps_numerator == 24000
    assert source.fps_denominator == 1001


def test_frame_rate_rejects_zero():
    """ffprobe reports 0/0 for a stream it could not read. It must not become 0 fps."""
    for bad in ({"fps_numerator": 0}, {"fps_denominator": 0}):
        with pytest.raises(ValidationError):
            a_source(**bad)


def test_source_geometry_and_length_must_be_positive():
    """A zero-frame or zero-pixel source is a failed probe, not a source."""
    for bad in ({"width": 0}, {"height": 0}, {"frame_count": 0}):
        with pytest.raises(ValidationError):
            a_source(**bad)


def test_source_knows_whether_it_has_audio():
    """Derived from the stream being there, so the two cannot disagree."""
    assert a_source().has_audio is False

    with_sound = a_source(
        audio=AudioInfo(
            codec="pcm_s24le",
            sample_rate=48_000,
            channels=2,
            can_stream_copy_to_mp4=False,
        )
    )
    assert with_sound.has_audio is True


def test_probe_report_separates_a_refusal_from_a_warning():
    """VFR cannot be worked around; a tight disk is the user's call."""
    refused = ProbeReport(
        source=a_source(is_variable_frame_rate=True),
        duration_timecode="00:00:04:04",
        suggested_output_dir="C:/footage/take_01_performance",
        estimated_gb=4.0,
        can_build=False,
        refusal_reason="This source has a variable frame rate.",
    )
    assert refused.can_build is False
    assert refused.warnings == []

    warned = ProbeReport(
        source=a_source(),
        duration_timecode="00:00:04:04",
        suggested_output_dir="C:/footage/take_01_performance",
        estimated_gb=40.0,
        free_gb=10.0,
        warnings=["This job needs about 40 GB but only 10 GB is free."],
    )
    assert warned.can_build is True
    assert len(warned.warnings) == 1


def test_prepared_job_carries_its_depth_once_the_stage_has_run():
    """`StoredDepth` is declared after PreparedJob, so this proves the reference resolves."""
    job = PreparedJob(
        source=a_source(),
        mezzanine_path="work/take_01_mezzanine.mov",
        proxy_path="work/take_01_proxy.mp4",
    )
    assert job.depth is None

    with_depth = job.model_copy(update={"depth": a_depth()})
    assert with_depth.depth.model is DepthModel.SMALL


# --- DEPTH ---


def test_stored_depth_rejects_a_backwards_range():
    """min and max come from the model; equal values would make a window meaningless."""
    for bad in ({"min_depth": 5.0, "max_depth": 5.0}, {"min_depth": 9.0, "max_depth": 1.0}):
        with pytest.raises(ValidationError):
            a_depth(**bad)


def test_supplied_depth_may_have_no_range_at_all():
    """
    Depth somebody else generated carries no model range, so 0..1 means only
    what it meant in that file. Recorded as unknown rather than guessed.
    """
    supplied = a_depth(backend=DepthBackendName.SUPPLIED, min_depth=None, max_depth=None)

    assert supplied.min_depth is None
    assert supplied.max_depth is None


def test_a_half_known_range_is_rejected():
    """
    Worse than neither: a caller reading only min_depth would take it for a
    complete answer and align a second pass against nothing.
    """
    for half in ({"max_depth": None}, {"min_depth": None}):
        with pytest.raises(ValidationError, match="both known or both unknown"):
            a_depth(**half)


def test_stored_depth_records_its_precision():
    """What decides whether a tight window is honest or terraces."""
    assert a_depth(bit_depth=16).bit_depth == 16

    with pytest.raises(ValidationError):
        a_depth(bit_depth=4)


def test_depth_model_default_is_never_implied():
    """
    Fal defaults to VDA-Large, which is CC-BY-NC-4.0. The enum carries no
    default of its own, so a caller has to choose — CLAUDE.md non-negotiable 14.
    """
    assert DepthModel.SMALL.value == "VDA-Small"
    assert StoredDepth.model_fields["model"].is_required(), (
        "StoredDepth.model must stay required: a default here would let the "
        "licence-restricted VDA-Large be recorded by omission"
    )

    with pytest.raises(ValidationError):
        StoredDepth(
            path="work/d.mkv",
            cache_key="abc",
            backend=DepthBackendName.FAL,
            bit_depth=16,
            min_depth=0.5,
            max_depth=42.0,
            width=1920,
            height=1080,
            frame_count=100,
        )


def test_window_must_have_width():
    """A zero-width window would divide by zero and means nothing."""
    for bad in ({"near": 0.5, "far": 0.5}, {"near": 0.8, "far": 0.2}):
        with pytest.raises(ValidationError):
            DepthWindow(**bad)


def test_window_reports_how_much_of_the_range_it_spans():
    """The number that decides how many output levels a pull leaves."""
    assert DepthWindow(near=0.0, far=1.0).width == 1.0
    assert DepthWindow(near=0.45, far=0.55).width == pytest.approx(0.10)


# --- THE STACK ---


def a_stack(*sources, disabled=()) -> LayerStack:
    """Bottom first, the way the model stores it."""
    return LayerStack(
        layers=[Layer(source=s, enabled=s not in disabled) for s in sources]
    )


def test_index_zero_is_the_bottom():
    """The one convention a careless edit would reverse."""
    stack = a_stack(LayerSource.PLATE, LayerSource.DEPTH, LayerSource.FACE_MESH)

    assert stack.layers[0].source is LayerSource.PLATE
    assert stack.enabled_sources[0] is LayerSource.PLATE
    assert stack.enabled_sources[-1] is LayerSource.FACE_MESH


def test_the_same_two_layers_either_way_up_are_different_stacks():
    """
    Not a quirk to be normalised away: a segmented depth region over the plate
    and the plate over that region are both things someone might want.
    """
    over = a_stack(LayerSource.PLATE, LayerSource.DEPTH)
    under = a_stack(LayerSource.DEPTH, LayerSource.PLATE)

    assert over.enabled_sources != under.enabled_sources


def test_switching_layers_off_is_how_a_single_pass_is_delivered():
    """So there is no separate export path to keep in step with this one."""
    stack = a_stack(
        LayerSource.GREY, LayerSource.DEPTH, LayerSource.FACE_MESH,
        disabled=(LayerSource.GREY, LayerSource.FACE_MESH),
    )

    assert stack.enabled_sources == [LayerSource.DEPTH]


def test_a_source_cannot_appear_twice():
    """Until a per-layer setting can tell two of the same pass apart."""
    with pytest.raises(ValidationError, match="one layer per source"):
        a_stack(LayerSource.DEPTH, LayerSource.DEPTH)


def test_a_stack_needs_a_layer():
    with pytest.raises(ValidationError):
        LayerStack(layers=[])


def test_the_mesh_can_sit_over_the_plate_or_over_grey():
    """
    The mesh is the one layer with alpha, so what is under it shows through.
    Over the plate is how a track is checked; over grey is how the mesh is
    looked at on its own. Both are the same mechanism.
    """
    for background in (LayerSource.PLATE, LayerSource.GREY):
        stack = a_stack(background, LayerSource.FACE_MESH)
        assert stack.enabled_sources == [background, LayerSource.FACE_MESH]


# --- OUTPUT ---


def test_audio_is_carried_by_default():
    """Carried untouched when it is carried — but whether to is a choice."""
    request = OutputRequest(stack=a_stack(LayerSource.DEPTH), name="take_01_depth")

    assert request.include_audio is True


def test_audio_can_be_discarded():
    """For a pass going to a model that ignores it, or client audio that should not travel."""
    request = OutputRequest(
        stack=a_stack(LayerSource.DEPTH), name="take_01_depth", include_audio=False
    )

    assert request.include_audio is False


def test_an_output_has_to_be_called_something():
    with pytest.raises(ValidationError):
        OutputRequest(stack=a_stack(LayerSource.DEPTH), name="")


# --- SELECTION ---


def test_box_rejects_corners_out_of_order_or_zero_sized():
    """A zero-width box is a click rather than a drag, and crops to nothing."""
    for bad in (
        {"left": 0.6, "right": 0.4},
        {"top": 0.6, "bottom": 0.4},
        {"left": 0.5, "right": 0.5},
    ):
        with pytest.raises(ValidationError):
            a_box(**bad)


def test_box_rejects_fractions_outside_the_picture():
    for bad in ({"left": -0.01}, {"right": 1.01}):
        with pytest.raises(ValidationError):
            a_box(**bad)


def test_face_label_is_stripped_and_cannot_be_blank():
    assert Face(label="  Woman  ", seeds=[Seed(frame=12, box=a_box())]).label == "Woman"

    with pytest.raises(ValidationError):
        Face(label="   ", seeds=[Seed(frame=12, box=a_box())])


def test_face_needs_at_least_one_seed():
    with pytest.raises(ValidationError):
        Face(label="Woman", seeds=[])


def test_face_seeds_are_sorted_into_frame_order():
    """Tracking runs forward from each seed to the next, so the order is the plan."""
    face = Face(
        label="Woman",
        seeds=[
            Seed(frame=400, box=a_box()),
            Seed(frame=12, box=a_box()),
            Seed(frame=220, box=a_box()),
        ],
    )

    assert face.seed_frames == [12, 220, 400]


def test_face_rejects_two_seeds_on_one_frame():
    """Two boxes on the same frame give the tracker no way to choose."""
    with pytest.raises(ValidationError, match="more than one seed"):
        Face(
            label="Woman",
            seeds=[Seed(frame=12, box=a_box()), Seed(frame=12, box=a_box(0.1, 0.1, 0.2, 0.2))],
        )


def test_selection_rejects_two_faces_with_the_same_label():
    """landmarks.json and the report are keyed by label, so a duplicate loses a face."""
    with pytest.raises(ValidationError, match="unique"):
        Selection(
            created_at=A_TIME,
            source_name="take_01.mov",
            source_frame_count=100,
            faces=[
                Face(label="Woman", seeds=[Seed(frame=10, box=a_box())]),
                Face(label="Woman", seeds=[Seed(frame=40, box=a_box())]),
            ],
        )


def test_selection_rejects_a_seed_past_the_end_of_the_source():
    """The symptom of a selection made against a longer cut."""
    with pytest.raises(ValidationError, match="100 frames"):
        Selection(
            created_at=A_TIME,
            source_name="take_01.mov",
            source_frame_count=100,
            faces=[Face(label="Woman", seeds=[Seed(frame=10, box=a_box()),
                                              Seed(frame=100, box=a_box())])],
        )


def test_selection_needs_at_least_one_face():
    with pytest.raises(ValidationError):
        Selection(
            created_at=A_TIME,
            source_name="take_01.mov",
            source_frame_count=100,
            faces=[],
        )


def test_a_valid_selection_survives_a_round_trip_through_json():
    """selection.json is the whole interface between the picker and the pipeline."""
    selection = Selection(
        created_at=A_TIME,
        source_name="take_01.mov",
        source_frame_count=500,
        faces=[
            Face(label="Woman", seeds=[Seed(frame=10, box=a_box()),
                                       Seed(frame=260, box=a_box(0.5, 0.3, 0.7, 0.6))]),
            Face(label="Man", seeds=[Seed(frame=62, box=a_box(0.1, 0.2, 0.3, 0.5))]),
        ],
    )

    restored = Selection.model_validate_json(selection.model_dump_json())

    assert restored == selection
    assert [face.label for face in restored.faces] == ["Woman", "Man"]
    assert restored.faces[0].seed_frames == [10, 260]


# --- TRACKS ---


def test_track_reads_its_length_off_the_array():
    """So a track cannot claim a frame count its landmarks do not have."""
    assert a_track(frame_count=30).frame_count == 30


# --- REPORTS AND VALIDATION ---


def test_longest_gap_is_zero_when_nothing_was_missed():
    report = FaceTrackingReport(label="Woman", frames_tracked=100, frames_missing=0)

    assert report.longest_gap_frames == 0


def test_longest_gap_picks_the_longest_not_the_last():
    report = FaceTrackingReport(
        label="Woman",
        frames_tracked=80,
        frames_missing=20,
        gaps=[
            FrameRange(start_frame=20, end_frame=34),  # 15 frames
            FrameRange(start_frame=90, end_frame=94),  # 5 frames
        ],
    )

    assert report.longest_gap_frames == 15


def test_a_result_cannot_claim_a_pass_it_did_not_get():
    """Derived from the checks: there is no way to set `passed` to True directly."""
    assert ValidationResult(checks={"frame_count": True, "frame_rate": True}).passed is True
    assert ValidationResult(checks={"frame_count": True, "frame_rate": False}).passed is False


def test_a_result_with_no_checks_is_not_a_pass():
    """all([]) is True, so an unchecked job would otherwise sail through."""
    assert ValidationResult().passed is False


# --- THE SKELETON ITSELF ---


def test_nothing_unimplemented_returns_none():
    """
    The anti-pattern this guards: `pass` as a placeholder returns None, so an
    unimplemented function flows through the app pretending it worked. Every
    one of these is pseudocode today and must raise until it is not.
    """
    track = a_track(frame_count=2)

    unimplemented = {
        "NormalisedBox.to_pixels": lambda: a_box().to_pixels(1920, 1080),
        "NormalisedBox.padded": lambda: a_box().padded(0.5),
        "FaceTrack.validate_shape": track.validate_shape,
        "FaceTrack.gaps": track.gaps,
        "FaceTrack.segments": track.segments,
        "FaceTrack.landmarks_on": lambda: track.landmarks_on(0),
    }

    for name, call in unimplemented.items():
        print(f"still pseudocode: {name}")
        with pytest.raises(NotImplementedError):
            call()
