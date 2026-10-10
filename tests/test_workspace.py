"""
Tests for the Working Folder.

Two things matter here and both are about not losing someone's work.

A file is matched to its source by stripping the suffix that was added to it,
never by prefix — "take_02" must not claim "take_02_extra_mezzanine.mov".

And nothing is reclaimed behind the user's back. Clearing is asked for, and
the file currently being worked on survives it, because the depth in that
folder was paid for.
"""

from pathlib import Path

from src.media import workspace
from src.media.workspace import (
    WORK_DIRECTORY,
    WORK_SUFFIXES,
    clear_work,
    owning_source,
    reclaimable_bytes,
    reclaimable_work,
    work_dir_for,
)


def make_work(root: Path, *names: str, content: str = "x" * 100) -> Path:
    """A work folder containing the named files."""
    work = work_dir_for(root)
    work.mkdir(parents=True, exist_ok=True)
    for name in names:
        (work / name).write_text(content, encoding="utf-8")
    return work


# --- NAMING ---


def test_the_work_folder_hides_inside_the_output_directory(tmp_path):
    """One obviously temporary folder rather than large files among the deliverables."""
    assert work_dir_for(tmp_path).name == WORK_DIRECTORY
    assert work_dir_for(tmp_path).name.startswith(".")


def test_a_file_is_matched_by_stripping_its_suffix():
    assert owning_source(Path("take_01_mezzanine.mov")) == "take_01"
    assert owning_source(Path("take_01_proxy.mp4")) == "take_01"
    assert owning_source(Path("take_01_depth_field.mkv")) == "take_01"
    assert owning_source(Path("take_01_layer.mov")) == "take_01"


def test_a_similar_name_is_not_claimed_by_a_shorter_one():
    """
    The bug this guards: matching by prefix would let "take_02" claim
    "take_02_extra_mezzanine.mov", and clearing would spare the wrong file.
    """
    assert owning_source(Path("take_02_extra_mezzanine.mov")) == "take_02_extra"
    assert owning_source(Path("take_02_extra_mezzanine.mov")) != "take_02"


def test_the_suffixes_are_ordered_so_a_longer_one_always_wins():
    """
    `owning_source` strips the first suffix that matches the end of a name, so
    where one suffix ends with another the longer has to be tried first. The
    tuple is sorted by length for exactly that reason, and this holds it there
    for a fifth suffix added later.
    """
    assert list(WORK_SUFFIXES) == sorted(WORK_SUFFIXES, key=len, reverse=True)

    for longer in WORK_SUFFIXES:
        for shorter in WORK_SUFFIXES:
            if longer != shorter and longer.endswith(shorter):
                assert WORK_SUFFIXES.index(longer) < WORK_SUFFIXES.index(shorter), (
                    f"{shorter} would be stripped out of {longer} first"
                )


def test_a_suffix_ending_with_another_is_still_stripped_whole(monkeypatch):
    """
    The hazard the ordering guards, made concrete rather than hypothetical.
    Add "_field" alongside "_depth_field" in the wrong order and
    "take_01_depth_field.mkv" reports its owner as "take_01_depth" — a source
    that does not exist, so clearing would spare the wrong file.
    """
    monkeypatch.setattr(
        workspace,
        "WORK_SUFFIXES",
        tuple(sorted(("_field", "_depth_field"), key=len, reverse=True)),
    )

    assert workspace.owning_source(Path("take_01_depth_field.mkv")) == "take_01"


def test_scratch_belonging_to_nothing_is_always_reclaimable():
    """It matches no source, so no `keep_source` ever protects it."""
    assert owning_source(Path("scratch.txt")) == "scratch"


# --- WHAT CAN GO ---


def test_an_empty_output_directory_has_nothing_to_reclaim(tmp_path):
    assert reclaimable_work(tmp_path) == []
    assert reclaimable_bytes(tmp_path) == 0


def test_everything_is_reclaimable_before_anything_is_being_worked_on(tmp_path):
    """The normal state: nothing is currently prepared, so nothing is protected."""
    make_work(tmp_path, "take_01_mezzanine.mov", "take_02_proxy.mp4")

    assert len(reclaimable_work(tmp_path)) == 2
    assert reclaimable_bytes(tmp_path) == 200


def test_the_source_being_worked_on_is_spared(tmp_path):
    """
    The point of the whole module. Clearing while someone is mid-job must not
    take the mezzanine and the depth out from under them.
    """
    make_work(
        tmp_path,
        "take_01_mezzanine.mov",
        "take_01_depth_field.mkv",
        "take_02_mezzanine.mov",
    )

    reclaimable = reclaimable_work(tmp_path, keep_source=Path("D:/f/take_01.mov"))
    names = [path.name for path in reclaimable]

    print(names)
    assert names == ["take_02_mezzanine.mov"]


# --- CLEARING ---


def test_clearing_reports_what_it_freed(tmp_path):
    make_work(tmp_path, "take_01_mezzanine.mov", "take_02_proxy.mp4")

    freed = clear_work(tmp_path)

    assert freed == 200
    assert reclaimable_work(tmp_path) == []


def test_clearing_keeps_the_file_in_use(tmp_path):
    make_work(tmp_path, "take_01_mezzanine.mov", "take_02_mezzanine.mov")

    clear_work(tmp_path, keep_source=Path("D:/f/take_01.mov"))
    left = [path.name for path in work_dir_for(tmp_path).iterdir()]

    assert left == ["take_01_mezzanine.mov"]


def test_an_emptied_work_folder_removes_itself(tmp_path):
    """So an output directory that is finished with looks finished with."""
    make_work(tmp_path, "take_01_mezzanine.mov")

    clear_work(tmp_path)

    assert not work_dir_for(tmp_path).exists()


def test_a_work_folder_still_in_use_stays(tmp_path):
    make_work(tmp_path, "take_01_mezzanine.mov", "take_02_proxy.mp4")

    clear_work(tmp_path, keep_source=Path("D:/f/take_01.mov"))

    assert work_dir_for(tmp_path).is_dir()


def test_clearing_nothing_is_not_an_error(tmp_path):
    assert clear_work(tmp_path) == 0


# --- SEQUENCES ---


def test_a_sequence_layer_is_a_folder_and_is_counted_whole(tmp_path):
    """
    A PNG layer is many files in a folder. Counting only loose files would
    report a few kilobytes reclaimable when it is actually gigabytes.
    """
    work = make_work(tmp_path, "take_01_mezzanine.mov")
    sequence = work / "take_01_layer"
    sequence.mkdir()
    for index in range(5):
        (sequence / f"take_01_layer.{index:04d}.png").write_text("y" * 50, encoding="utf-8")

    assert reclaimable_bytes(tmp_path) == 100 + 250


def test_a_sequence_layer_is_deleted_whole(tmp_path):
    work = make_work(tmp_path)
    sequence = work / "take_01_layer"
    (sequence / "nested").mkdir(parents=True)
    (sequence / "take_01_layer.0000.png").write_text("y" * 50, encoding="utf-8")
    (sequence / "nested" / "deeper.png").write_text("y" * 50, encoding="utf-8")

    freed = clear_work(tmp_path)

    assert freed == 100
    assert not sequence.exists()


def test_a_sequence_layer_is_spared_like_any_other_file(tmp_path):
    work = make_work(tmp_path, "take_02_mezzanine.mov")
    sequence = work / "take_01_layer"
    sequence.mkdir()
    (sequence / "take_01_layer.0000.png").write_text("y" * 50, encoding="utf-8")

    clear_work(tmp_path, keep_source=Path("D:/f/take_01.mov"))

    assert sequence.is_dir(), "the sequence belongs to the source being worked on"
