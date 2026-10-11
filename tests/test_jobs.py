"""
Tests for Background Jobs.

Preparing and tracking take tens of seconds, so they run off the request and
the page polls. What matters here is that a job always reaches a state the
page can act on — a worker that dies silently leaves a bar at 40% for ever,
which is the worst of both: no result and no error.
"""

import threading
import time

import pytest

from src.ui.jobs import DONE, FAILED, REMEMBERED, RUNNING, Jobs


def wait_for(job, state, timeout=5.0):
    """Waits for a job to reach a state, rather than sleeping and hoping."""
    deadline = time.monotonic() + timeout
    while job.state != state and time.monotonic() < deadline:
        time.sleep(0.01)
    return job.state == state


@pytest.fixture
def jobs() -> Jobs:
    """A register of its own, so tests cannot see each other's jobs."""
    return Jobs()


# --- FINISHING ---


def test_a_job_runs_and_keeps_its_result(jobs):
    job = jobs.start("test", lambda _job: {"answer": 42})

    assert wait_for(job, DONE)
    assert job.result == {"answer": 42}


def test_a_job_is_running_before_it_finishes(jobs):
    release = threading.Event()
    job = jobs.start("test", lambda _job: release.wait(5) and {})

    assert job.state == RUNNING
    release.set()
    assert wait_for(job, DONE)


def test_a_job_can_be_found_by_id(jobs):
    job = jobs.start("test", lambda _job: {})

    assert wait_for(job, DONE)
    assert jobs.get(job.id) is job


def test_an_unknown_id_is_none_rather_than_an_error(jobs):
    assert jobs.get("nothing") is None


# --- FAILING ---


def test_a_job_that_raises_becomes_a_failed_job(jobs):
    """
    Not a thread that dies quietly. A page polling a job that never changes
    state has no way to tell "still working" from "gave up ten minutes ago".
    """

    def explode(_job):
        raise ValueError("the box was empty")

    job = jobs.start("test", explode)

    assert wait_for(job, FAILED)
    assert job.error == "the box was empty"


def test_a_failure_with_no_message_still_says_something(jobs):
    """`str(error)` is empty for plenty of exceptions, and so is a blank bar."""

    def explode(_job):
        raise RuntimeError()

    job = jobs.start("test", explode)

    assert wait_for(job, FAILED)
    assert job.error == "RuntimeError"


def test_a_failure_does_not_block_the_next_job(jobs):
    def explode(_job):
        raise ValueError("no")

    failed = jobs.start("test", explode)
    assert wait_for(failed, FAILED)

    assert wait_for(jobs.start("test", lambda _job: {"ok": True}), DONE)


# --- ONE AT A TIME ---


def test_only_one_job_runs_at_once(jobs):
    """
    A local tool driven by one person at one page. Two tracks at once would
    compete for the same CPU and finish both later, and only one of them
    could be described by a progress bar.
    """
    release = threading.Event()
    jobs.start("first", lambda _job: release.wait(5) and {})

    with pytest.raises(RuntimeError, match="already running"):
        jobs.start("second", lambda _job: {})

    release.set()


def test_the_running_job_can_be_found_without_its_id(jobs):
    release = threading.Event()
    job = jobs.start("prepare", lambda _job: release.wait(5) and {})

    assert jobs.running() is job

    release.set()
    assert wait_for(job, DONE)
    assert jobs.running() is None


# --- PROGRESS ---


def test_a_job_reports_frames_as_it_goes(jobs):
    def count(job):
        job.total = 10
        for frame in range(10):
            job.progress(frame + 1, 10)
        return {}

    job = jobs.start("test", count)

    assert wait_for(job, DONE)
    assert (job.done, job.total) == (10, 10)


def test_a_job_says_what_it_is_doing(jobs):
    job = jobs.start("test", lambda j: (j.say("Drawing the mesh"), {})[1])

    assert wait_for(job, DONE)
    assert job.message == "Drawing the mesh"


# --- REMEMBERING ---


def test_finished_jobs_are_kept_so_a_reload_still_finds_them(jobs):
    job = jobs.start("test", lambda _job: {"kept": True})
    assert wait_for(job, DONE)

    assert jobs.get(job.id).result == {"kept": True}


def test_old_jobs_are_forgotten_rather_than_accumulating(jobs):
    first = jobs.start("test", lambda _job: {})
    assert wait_for(first, DONE)

    for _ in range(REMEMBERED):
        assert wait_for(jobs.start("test", lambda _job: {}), DONE)

    assert jobs.get(first.id) is None
