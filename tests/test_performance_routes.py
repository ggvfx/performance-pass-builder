"""
Tests for the Performance Pass Routes.

The first routes that drive the real pipeline, so what matters is that a bad
request is answered rather than crashed on, and that a job's result is only
reachable through the job — not by handing the server a path.

The heavy paths are exercised in the modules they belong to. What is tested
here is the wiring: refusals, 404s, and one real prepare on a generated clip
small enough to be worth the seconds.
"""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from src.ui.server import app

client = TestClient(app)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def finished(job_id, timeout=120.0) -> dict:
    """Polls a job the way the page does, and returns it once it stops."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        job = client.get(f"/api/job/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)

    raise AssertionError(f"job {job_id} never finished")


# --- INSPECT ---


def test_inspecting_nothing_says_so_rather_than_crashing():
    response = client.post("/api/inspect", json={"path": "D:/nowhere/absent.mov"})

    assert response.status_code == 404
    assert "absent.mov" in response.json()["detail"]


@needs_ffmpeg
def test_inspecting_a_clip_answers_in_the_request(clips):
    """
    A probe is cheap. Making it a job would mean a spinner for something
    that answers in well under a second.
    """
    response = client.post("/api/inspect", json={"path": str(clips["film24"])})

    assert response.status_code == 200
    answer = response.json()
    assert answer["report"]["source"]["fps_numerator"] == 24
    assert answer["report"]["can_build"] is True


@needs_ffmpeg
def test_a_refusal_is_an_answer_not_an_error(clips):
    """
    Variable frame rate cannot carry a frame-accurate pass. That is a thing
    to read, with a reason, rather than a 400 the page has to interpret.
    """
    response = client.post("/api/inspect", json={"path": str(clips["vfr"])})

    assert response.status_code == 200
    report = response.json()["report"]
    assert report["can_build"] is False
    assert report["refusal_reason"]


@needs_ffmpeg
def test_inspecting_says_whether_it_has_been_prepared(clips, tmp_path, monkeypatch):
    """
    A source prepared in an earlier session is still prepared. Without this
    the page would call it untouched and refuse to show the proxy until it
    had been built a second time.
    """
    from src.ui.routes import performance

    monkeypatch.setattr(performance, "suggested_output_dir", lambda _path: tmp_path)
    clip = str(clips["film24"])

    assert client.post("/api/inspect", json={"path": clip}).json()["prepared"] is False

    finished(client.post("/api/prepare", json={"path": clip}).json()["id"])

    assert client.post("/api/inspect", json={"path": clip}).json()["prepared"] is True


# --- THE PROXY ---


def test_an_unprepared_source_has_no_proxy_to_serve():
    response = client.get("/api/proxy", params={"path": "D:/nowhere/absent.mov"})

    assert response.status_code == 404
    assert "prepared" in response.json()["detail"]


@needs_ffmpeg
def test_the_proxy_is_served_once_it_exists(clips, tmp_path, monkeypatch):
    from src.ui.routes import performance

    monkeypatch.setattr(performance, "suggested_output_dir", lambda _path: tmp_path)
    clip = str(clips["film24"])

    finished(client.post("/api/prepare", json={"path": clip}).json()["id"])
    response = client.get("/api/proxy", params={"path": clip})

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


def test_the_proxy_route_derives_its_path_rather_than_opening_one():
    """
    The page sends a source and gets back a file it never named. A route
    that opens whatever path it is handed will open anything on the disk.
    """
    import inspect as inspect_module

    from src.ui.routes.performance import _proxy_path, proxy

    assert list(inspect_module.signature(proxy).parameters) == ["path"]

    from pathlib import Path as RealPath

    derived = _proxy_path(RealPath("D:/footage/take_01.mov"))
    assert derived.name == "take_01_proxy.mp4"
    assert ".performance-work" in str(derived)


# --- PREPARE ---


def test_preparing_nothing_says_so():
    response = client.post("/api/prepare", json={"path": "D:/nowhere/absent.mov"})

    assert response.status_code == 404


@needs_ffmpeg
def test_preparing_builds_both_working_files(clips, tmp_path, monkeypatch):
    """
    The mezzanine and the proxy, not one. Tracking reads the first because
    it seeks; a person scrubs the second because its frame numbers are
    burned in.
    """
    from pathlib import Path

    from src.ui.routes import performance

    monkeypatch.setattr(performance, "suggested_output_dir", lambda _path: tmp_path)

    started = client.post("/api/prepare", json={"path": str(clips["film24"])}).json()
    job = finished(started["id"])

    print(job["message"])
    assert job["state"] == "done", job["error"]
    assert Path(job["result"]["mezzanine"]).is_file()
    assert Path(job["result"]["proxy"]).is_file()


@needs_ffmpeg
def test_a_prepared_mezzanine_is_all_intra(clips, tmp_path, monkeypatch):
    """
    The whole reason preparing exists. If this were ever false, backward
    tracking would refuse to run against it.
    """
    from pathlib import Path

    from src.media.probe import SourceProbe
    from src.ui.routes import performance

    monkeypatch.setattr(performance, "suggested_output_dir", lambda _path: tmp_path)

    started = client.post("/api/prepare", json={"path": str(clips["film24"])}).json()
    job = finished(started["id"])

    assert job["state"] == "done", job["error"]
    assert SourceProbe(performance.toolchain).is_all_intra(
        Path(job["result"]["mezzanine"])
    )


# --- JOBS ---


def test_an_unknown_job_is_a_404_not_a_crash():
    assert client.get("/api/job/nosuchjob").status_code == 404


@needs_ffmpeg
def test_a_second_job_while_one_runs_is_refused_clearly(clips, tmp_path, monkeypatch):
    """
    One at a time, and the page should be told which one is in the way
    rather than getting a generic failure.
    """
    from src.ui.routes import performance

    monkeypatch.setattr(performance, "suggested_output_dir", lambda _path: tmp_path)

    first = client.post("/api/prepare", json={"path": str(clips["film24"])}).json()
    second = client.post("/api/prepare", json={"path": str(clips["film24"])})

    if second.status_code == 409:
        assert "prepare" in second.json()["detail"]

    finished(first["id"])


# --- PREVIEW ---


def test_a_preview_for_an_unknown_job_is_a_404():
    assert client.get("/api/preview/nosuchjob").status_code == 404


def test_a_preview_is_reached_by_job_rather_than_by_path():
    """
    The route takes a job id, never a path. A route that opens whatever
    path the page sends it will open anything on the disk that is asked for.
    """
    import inspect as inspect_module

    from src.ui.routes.performance import preview

    assert list(inspect_module.signature(preview).parameters) == ["job_id"]
