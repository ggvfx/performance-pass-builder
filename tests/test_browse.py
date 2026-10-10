"""
Tests for the Path Picker.

Server-side browsing exists so a multi-gigabyte source is named by its path
and never uploaded. What is worth protecting is that one unreadable entry
cannot take out a whole listing, and that the picker cannot be used to read
something that is not a directory.
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from src.ui import browse
from src.ui.server import app

client = TestClient(app)


def a_tree(root: Path) -> None:
    """A directory with one of everything the picker has to sort and filter."""
    (root / "takes").mkdir()
    (root / "notes.txt").write_text("not video", encoding="utf-8")
    (root / "take_01.mov").write_text("pretend video", encoding="utf-8")
    (root / "take_02.MP4").write_text("pretend video", encoding="utf-8")
    (root / "render.exr").write_text("not video", encoding="utf-8")


# --- LISTING ---


def test_directories_come_first_then_files():
    """So the way deeper is always at the top, wherever the names sort."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        a_tree(root)

        listing = browse.list_directory(root)
        names = [entry.name for entry in listing.entries]

        print(f"listing: {names}")
        assert names[0] == "takes"
        assert [entry.is_directory for entry in listing.entries] == [True, False, False, False, False]


def test_videos_only_hides_everything_else():
    """The source picker offers footage; a folder of EXRs should not be noise."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        a_tree(root)

        listing = browse.list_directory(root, videos_only=True)
        names = sorted(entry.name for entry in listing.entries if not entry.is_directory)

        assert names == ["take_01.mov", "take_02.MP4"]
        assert "notes.txt" not in names
        assert "render.exr" not in names


def test_a_suffix_is_recognised_whatever_its_case():
    """Cameras and operating systems disagree about this, and both are right."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        a_tree(root)

        listing = browse.list_directory(root)
        by_name = {entry.name: entry for entry in listing.entries}

        assert by_name["take_02.MP4"].is_video is True
        assert by_name["notes.txt"].is_video is False


def test_a_file_reports_its_size_and_a_directory_does_not():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        a_tree(root)

        by_name = {entry.name: entry for entry in browse.list_directory(root).entries}

        assert by_name["take_01.mov"].size_bytes > 0
        assert by_name["takes"].size_bytes == 0


def test_a_subdirectory_can_be_stepped_out_of():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        a_tree(root)

        listing = browse.list_directory(root / "takes")

        assert listing.parent == root


def test_a_root_reports_no_parent():
    """At a drive root, Path.parent returns the same path, which would loop."""
    listing = browse.list_directory(Path(browse.available_roots()[0]))

    assert listing.parent is None


def test_there_is_always_somewhere_to_start():
    roots = browse.available_roots()

    print(f"roots: {roots}")
    assert roots, "with no roots the picker opens on nothing"


def test_a_file_is_not_a_directory():
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "take_01.mov"
        source.write_text("pretend video", encoding="utf-8")

        try:
            browse.list_directory(source)
        except NotADirectoryError:
            pass
        else:
            raise AssertionError("listing a file should raise rather than return nothing")


# --- THE ROUTE ---


def test_the_route_defaults_to_the_home_folder():
    """So the picker opens somewhere the user recognises rather than at a drive root."""
    response = client.get("/api/browse")

    assert response.status_code == 200
    assert response.json()["path"] == str(Path.home())


def test_the_route_lists_a_given_directory():
    with tempfile.TemporaryDirectory() as temporary:
        a_tree(Path(temporary))

        response = client.get("/api/browse", params={"path": temporary, "videos_only": True})

        assert response.status_code == 200
        names = [entry["name"] for entry in response.json()["entries"]]
        assert "take_01.mov" in names
        assert "notes.txt" not in names


def test_a_missing_directory_is_an_answer_not_a_server_error():
    """The user typed a path that is not there, which is something they can fix."""
    response = client.get("/api/browse", params={"path": "Z:/no/such/folder"})

    assert response.status_code == 404
    assert "Not a directory" in response.json()["detail"]
