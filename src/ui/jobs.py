"""
Background Jobs.

Written for this project. minicut's work was fast enough to do in the request.

**Preparing a source and tracking a face are tens of seconds each**, and a
three-face job is minutes. Doing that inside a request means a page that
appears to have frozen — no progress, no indication of which face is being
worked on, and a browser that may give up before the work does.

So a request starts a job and returns immediately with its id; the page asks
how it is going. That is also what lets the tracker's `on_face` reach the
screen as "Tracking Partner, 2 of 2" rather than being swallowed.

Notes:
    **One job at a time, and that is deliberate.** This is a local tool
    driven by one person at one page. Running two tracks at once would
    compete for the same CPU and finish both later, and the running job is
    the only one a progress bar can describe.

    Jobs are kept after they finish so the page can collect the result, and
    the last few are kept after that so a reload still finds it. Nothing is
    persisted: a restarted server has no jobs, which is correct — the work
    was in memory.
"""

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# How many finished jobs to remember. Enough that a page reloading mid-job
# still finds its result, few enough that nothing accumulates.
REMEMBERED = 8

RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    """
    One piece of work, and how far through it is.

    Notes:
        `done` and `total` are frames, so a bar means the same thing whether
        it is preparing or tracking. `message` is the sentence shown beside
        it, and is the only place a stage says what it is actually doing.
    """

    id: str
    kind: str
    state: str = RUNNING
    message: str = ""
    done: int = 0
    total: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def progress(self, done: int, total: int) -> None:
        """Called from the worker thread as frames go by."""
        self.done = done
        self.total = total

    def say(self, message: str) -> None:
        """Sets the line shown beside the bar."""
        self.message = message
        logging.info(f"[{self.kind}] {message}")


class Jobs:
    """
    The one running job, and the last few that finished.

    Notes:
        A lock around the dictionary rather than around the work: the worker
        thread writes progress constantly and the request thread reads it,
        and the only thing that must not tear is the bookkeeping.
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def running(self) -> Job | None:
        """The job in flight, if there is one."""
        with self._lock:
            return next((job for job in self._jobs.values() if job.state == RUNNING), None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, kind: str, work: Callable[[Job], dict[str, Any]]) -> Job:
        """
        Runs `work` on a thread, handing it the job to report into.

        Args:
            kind: What this is, for the log and for the page.
            work: Takes the Job, returns whatever the page needs.

        Returns:
            The job, already running.

        Raises:
            RuntimeError: Something else is already running.

        Notes:
            **An exception inside the worker becomes a failed job, not a
            lost one.** A thread that dies silently leaves a bar at 40% for
            ever, which is the worst of both — no result and no error.
        """
        with self._lock:
            busy = next((job for job in self._jobs.values() if job.state == RUNNING), None)
            if busy is not None:
                raise RuntimeError(f"{busy.kind} is already running")

            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job
            self._order.append(job.id)

            for old in self._order[:-REMEMBERED]:
                self._jobs.pop(old, None)
            self._order = self._order[-REMEMBERED:]

        def run() -> None:
            try:
                job.result = work(job)
                job.state = DONE
                job.say(job.message or "Finished")
            except Exception as error:  # noqa: BLE001 - a job may fail any way at all
                job.state = FAILED
                job.error = str(error) or error.__class__.__name__
                logging.error(f"[{kind}] failed: {job.error}\n{traceback.format_exc()}")

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job


jobs = Jobs()
