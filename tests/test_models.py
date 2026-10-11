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
    NOT_SEEDED,
    AudioInfo,
    Layer,
    LayerSource,
    LayerStack,
    OutputFormat,
    OutputRequest,
    DepthBackendName,
    DepthModel,
    DepthWindow,
    Face,
    FaceTrack,
    FaceTrackingReport,
    FrameRange,
    NormalisedBox,
    PreparedSource,
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


def a_track(frame_count=30, label="Woman", missing=(), seeds=None) -> FaceTrack:
    """
    A track that satisfies the array contract.

    Args:
        missing: Frame indices the face was not found on. Their landmark rows
            become NaN and their seed index NOT_SEEDED, because a gap that is
            only half a gap is exactly what validate_shape rejects.
        seeds: Per-frame seed index. Defaults to seed 0 throughout.
    """
    landmarks = np.zeros((frame_count, LANDMARK_COUNT, 3), dtype=np.float32)
    tracked = np.ones(frame_count, dtype=bool)
    seeded_by = np.array(seeds if seeds is not None else [0] * frame_count, dtype=np.int16)

    for frame in missing:
        landmarks[frame] = np.nan
        tracked[frame] = False
        seeded_by[frame] = NOT_SEEDED

    return FaceTrack(label=label, landmarks=landmarks, tracked=tracked, seeded_by=seeded_by)


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


def test_a_prepared_source_holds_no_pass_output():
    """
    Preparing is shared and is not a pass. An earlier draft hung the depth
    here, which only looked right while depth was the one pass — add faces and
    segmentation and it becomes a bag of every result.
    """
    prepared = PreparedSource(
        source=a_source(),
        mezzanine_path="work/take_01_mezzanine.mov",
        proxy_path="work/take_01_proxy.mp4",
    )

    assert set(PreparedSource.model_fields) == {"source", "mezzanine_path", "proxy_path"}
    assert prepared.source.frame_count == 100


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
    supplied = a_depth(
        backend=DepthBackendName.SUPPLIED, model=None, min_depth=None, max_depth=None
    )

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


def test_generated_depth_must_say_which_model_made_it():
    """
    Fal selects VDA-Large when the parameter is absent, and that one is
    CC-BY-NC-4.0 — so a model recorded by omission is a licence problem, not
    merely a missing field. CLAUDE.md non-negotiable 14.
    """
    assert DepthModel.SMALL.value == "VDA-Small"

    for backend in (DepthBackendName.FAL, DepthBackendName.LOCAL):
        with pytest.raises(ValidationError, match="must record which model"):
            a_depth(backend=backend, model=None)


def test_supplied_depth_has_no_model_to_record():
    """
    A file somebody else generated was not made by any of these, so naming one
    would be a guess written into the sidecar as fact.

    This is the case that could not be built at all until the rule became
    conditional: `model` was required outright, so supplied depth raised.
    """
    supplied = a_depth(
        backend=DepthBackendName.SUPPLIED, model=None, min_depth=None, max_depth=None
    )
    assert supplied.model is None

    with pytest.raises(ValidationError, match="no Video Depth Anything model"):
        a_depth(backend=DepthBackendName.SUPPLIED, model=DepthModel.SMALL)


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


def test_the_filename_carries_the_format_s_own_suffix():
    """
    Derived rather than typed: a .mp4 holding ProRes, or a .mov holding h264,
    is a file something downstream refuses to open.
    """
    stack = a_stack(LayerSource.DEPTH)

    assert OutputRequest(stack=stack, name="take_01_depth").filename == "take_01_depth.mp4"
    assert OutputRequest(stack=stack, name="d").output_format is OutputFormat.H265
    assert (
        OutputRequest(
            stack=a_stack(LayerSource.FACE_MESH),
            name="take_01_faces",
            output_format=OutputFormat.ALPHA_RLE,
        ).filename
        == "take_01_faces.mov"
    )


def test_either_alpha_format_is_accepted_for_the_mesh_alone():
    """QuickTime RLE for one file; a PNG sequence for a compositor."""
    for alpha_format in (OutputFormat.ALPHA_RLE, OutputFormat.PNG_SEQUENCE):
        request = OutputRequest(
            stack=a_stack(LayerSource.FACE_MESH),
            name="take_01_faces",
            output_format=alpha_format,
        )
        assert request.output_format.carries_alpha


def test_a_sequence_s_deliverable_is_its_folder():
    """The frames inside are numbered, so the name alone is the thing delivered."""
    request = OutputRequest(
        stack=a_stack(LayerSource.FACE_MESH),
        name="take_01_faces",
        output_format=OutputFormat.PNG_SEQUENCE,
    )

    assert request.filename == "take_01_faces"


def test_the_mesh_alone_cannot_be_written_to_a_format_without_alpha():
    """
    The silent one. An encoder without alpha does not refuse a transparent
    frame — it flattens it onto black and says nothing, so the artist gets a
    mesh they cannot composite and no indication why.
    """
    with pytest.raises(ValidationError, match="carries alpha"):
        OutputRequest(
            stack=a_stack(LayerSource.FACE_MESH),
            name="take_01_faces",
            output_format=OutputFormat.H264,
        )


def test_the_mesh_over_something_opaque_is_fine_in_an_mp4():
    """Composited over depth there is no transparency left to lose."""
    request = OutputRequest(
        stack=a_stack(LayerSource.DEPTH, LayerSource.FACE_MESH),
        name="take_01_composite",
        output_format=OutputFormat.H264,
    )

    assert request.filename == "take_01_composite.mp4"


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


# --- TRACKS ---


def test_a_well_formed_track_passes_its_contract():
    a_track(frame_count=10).validate_shape()
    a_track(frame_count=10, missing=[3, 4]).validate_shape()


def test_landmarks_must_be_float32():
    """float64 doubles the memory for precision no landmark has."""
    track = a_track(frame_count=4)
    track.landmarks = track.landmarks.astype(np.float64)

    with pytest.raises(ValueError, match="float32"):
        track.validate_shape()


def test_the_landmark_count_is_part_of_the_contract():
    track = a_track(frame_count=4)
    track.landmarks = np.zeros((4, 400, 3), dtype=np.float32)

    with pytest.raises(ValueError, match=str(LANDMARK_COUNT)):
        track.validate_shape()


def test_the_flags_must_be_as_long_as_the_landmarks():
    """A short `tracked` would silently stop reporting gaps near the end."""
    track = a_track(frame_count=10)
    track.tracked = np.ones(8, dtype=bool)

    with pytest.raises(ValueError, match="8 entries against 10"):
        track.validate_shape()


def test_a_half_missing_frame_is_rejected():
    """
    The invariant the drawing stage leans on. A frame marked untracked but
    still holding numbers would draw a mesh out of stale points.
    """
    track = a_track(frame_count=5)
    track.tracked[2] = False  # ...but the landmarks are still zeros

    with pytest.raises(ValueError, match="gap must be all NaN"):
        track.validate_shape()


def test_a_tracked_frame_holding_nan_is_rejected():
    """The other direction: present, but with points nothing can draw."""
    track = a_track(frame_count=5)
    track.landmarks[2][10] = np.nan

    with pytest.raises(ValueError, match="holds NaN"):
        track.validate_shape()


def test_a_tracked_frame_must_say_which_seed_found_it():
    track = a_track(frame_count=5)
    track.seeded_by[2] = NOT_SEEDED

    with pytest.raises(ValueError, match="meaning untracked"):
        track.validate_shape()


def test_a_track_with_no_gaps_reports_none():
    assert a_track(frame_count=10).gaps() == []


def test_gaps_are_ranges_not_counts():
    """One long absence and shimmer throughout need different answers."""
    gaps = a_track(frame_count=20, missing=[5, 6, 7, 15]).gaps()

    assert [(g.start_frame, g.end_frame) for g in gaps] == [(5, 7), (15, 15)]


def test_a_gap_running_to_the_last_frame_is_still_reported():
    """The run never closes, so a loop that only emits on change would drop it."""
    gaps = a_track(frame_count=10, missing=[8, 9]).gaps()

    assert [(g.start_frame, g.end_frame) for g in gaps] == [(8, 9)]


def test_a_face_found_nowhere_is_one_whole_gap():
    """
    Not an empty list. "Found nothing" and "found everything" must not look
    the same to the caller.
    """
    gaps = a_track(frame_count=6, missing=range(6)).gaps()

    assert len(gaps) == 1
    assert gaps[0].frame_count == 6


def test_segments_say_which_seed_covered_which_frames():
    seeds = [0, 0, 0, 1, 1, 2]
    segments = a_track(frame_count=6, seeds=seeds).segments()

    assert [(index, r.start_frame, r.end_frame) for index, r in segments] == [
        (0, 0, 2),
        (1, 3, 4),
        (2, 5, 5),
    ]


def test_segments_are_in_frame_order_not_seed_order():
    """
    A seed can be used again after another one. Ordered by where they land,
    because that is how a timeline reads.
    """
    seeds = [1, 1, 0, 0, 1, 1]
    segments = a_track(frame_count=6, seeds=seeds).segments()

    assert [index for index, _ in segments] == [1, 0, 1]
    assert [r.start_frame for _, r in segments] == [0, 2, 4]


def test_segments_skip_the_frames_nothing_found():
    """A segment ends where the face was lost, not where the next seed is."""
    track = a_track(frame_count=6, missing=[2, 3])
    segments = track.segments()

    assert [(r.start_frame, r.end_frame) for _, r in segments] == [(0, 1), (4, 5)]


def test_landmarks_on_a_tracked_frame_are_the_points():
    track = a_track(frame_count=5)

    assert track.landmarks_on(2).shape == (LANDMARK_COUNT, 3)


def test_landmarks_on_a_gap_are_none_rather_than_nan():
    """
    So "is there a face here" reads as a question about the face, not about
    floating point.
    """
    assert a_track(frame_count=5, missing=[2]).landmarks_on(2) is None


def test_a_frame_outside_the_track_raises_rather_than_reading_as_a_gap():
    """Out of range is a programming error. None would hide it as a gap."""
    track = a_track(frame_count=5)

    for frame in (5, -1, 99):
        with pytest.raises(IndexError):
            track.landmarks_on(frame)


# --- BOX ARITHMETIC ---

# The one owner of fractions-to-pixels. Two modules rounding their own way is
# how a search box and the crop it produces end up a pixel apart.


def test_a_box_becomes_whole_pixels():
    box = NormalisedBox(left=0.25, top=0.25, right=0.75, bottom=0.75)

    assert box.to_pixels(1920, 1080) == (480, 270, 1440, 810)


def test_pixels_round_outward_so_no_part_of_the_face_is_lost():
    """
    Left and top floor, right and bottom ceil. Rounding inward would shave a
    pixel off the box someone drew around a face.
    """
    # Deliberately between pixels: 100.5 and 899.5 on a 1000-pixel picture.
    box = NormalisedBox(left=0.1005, top=0.1005, right=0.8995, bottom=0.8995)

    left, top, right, bottom = box.to_pixels(1000, 1000)

    assert (left, top) == (100, 100), "the near edges should floor"
    assert (right, bottom) == (900, 900), "the far edges should ceil"


def test_a_box_is_never_narrower_than_one_pixel():
    """A crop that comes back empty would be an exception somewhere far away."""
    hair = NormalisedBox(left=0.5, top=0.5, right=0.5001, bottom=0.5001)

    left, top, right, bottom = hair.to_pixels(100, 100)

    assert right > left
    assert bottom > top


def test_pixels_stay_inside_the_picture():
    whole = NormalisedBox(left=0.0, top=0.0, right=1.0, bottom=1.0)

    assert whole.to_pixels(1920, 1080) == (0, 0, 1920, 1080)


def test_padding_grows_a_box_around_its_own_centre():
    """0.5 on each side makes a box twice as wide and twice as tall."""
    box = NormalisedBox(left=0.4, top=0.4, right=0.6, bottom=0.6)

    padded = box.padded(0.5)

    assert (padded.left, padded.right) == pytest.approx((0.3, 0.7))
    assert (padded.top, padded.bottom) == pytest.approx((0.3, 0.7))


def test_padding_is_clamped_to_the_picture():
    """
    A face near the edge gets a smaller pad rather than an invalid box, so
    callers never have to guard it.
    """
    corner = NormalisedBox(left=0.0, top=0.9, right=0.1, bottom=1.0)

    padded = corner.padded(1.0)

    assert padded.left == 0.0
    assert padded.bottom == 1.0
    assert (padded.right, padded.top) == pytest.approx((0.2, 0.8))


def test_padding_leaves_the_original_alone():
    """The tracker keeps the face's own bounds and derives a region each frame."""
    box = NormalisedBox(left=0.4, top=0.4, right=0.6, bottom=0.6)

    box.padded(0.5)

    assert (box.left, box.right) == (0.4, 0.6)


def test_padding_by_nothing_changes_nothing():
    box = NormalisedBox(left=0.4, top=0.3, right=0.6, bottom=0.7)

    assert box.padded(0.0).model_dump() == box.model_dump()
