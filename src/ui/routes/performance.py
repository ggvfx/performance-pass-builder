"""
Performance Pass Routes.

Written for this project. minicut's splitter routes are a different job.

The Source and Faces steps, wired to the real pipeline — probe, mezzanine,
proxy, tracker, smoothing, mesh, compositor. Nothing here reimplements any of
it; the routes choose paths, start jobs and hand back what the page needs.

**This is the first thing that calls Phase 3 at all.** Until now the tracker,
the smoother and the mesh renderer were complete, tested and reachable only
from a script.

Notes:
    Preparing and tracking run as background jobs because they take tens of
    seconds — see `src/ui/jobs.py`. Inspecting is a probe and answers inside
    the request.

    Everything is written into the job's working folder, which is beside the
    source and hidden. Nothing is written next to the deliverables until
    there are deliverables.
"""

import logging
from fractions import Fraction
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core import config
from src.core.models import (
    Layer,
    LayerSource,
    LayerStack,
    ProbeReport,
    SourceInfo,
    TrackingReport,
)
from src.core.utils import ensure_directory
from src.composite.compositor import Compositor
from src.media.frames import RGB, RGBA, FrameReader, FrameWriter
from src.media.mezzanine import MezzanineBuilder
from src.media.probe import SourceProbe, suggested_output_dir
from src.media.proxy import ProxyBuilder
from src.media.workspace import work_dir_for
from src.performance import mesh
from src.performance.smoothing import smooth
from src.performance.tracking import FaceTracker, report_for
from src.ui.jobs import jobs
from src.ui.runtime import toolchain

router = APIRouter()

probe = SourceProbe(toolchain)

# What the preview is called inside the working folder. One per source, so
# tracking the same clip twice replaces it rather than accumulating.
PREVIEW_SUFFIX = "_faces_preview.mp4"


# --- WHAT THE PAGE SENDS AND GETS ---


class SourceRequest(BaseModel):
    path: str


class PreparedPaths(BaseModel):
    """Where a prepared source's working files ended up."""

    mezzanine: str
    proxy: str


class TrackResult(BaseModel):
    """What the page needs after a track, and nothing it does not."""

    report: TrackingReport
    preview: str                 # The job id, which is how the preview is fetched
    colours: dict[str, list[int]]

    # Where the preview actually is. The page never sees this — it is what
    # `/api/preview/{id}` looks up, so a path from the browser is never a
    # path this server opens.
    preview_path: str
    source: str


class JobState(BaseModel):
    id: str
    kind: str
    state: str
    message: str
    done: int
    total: int
    error: str
    result: dict | None = None


# --- INSPECT ---


@router.post("/api/inspect")
def inspect(request: SourceRequest) -> ProbeReport:
    """
    What the footage is, and whether a pass can be built from it.

    Raises:
        HTTPException: The path is not a file, or ffprobe could not read it.

    Notes:
        Cheap enough to answer in the request. The report carries its own
        refusal reason, so a variable frame rate source comes back as a
        readable answer rather than an error.
    """
    source_path = Path(request.path)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"No file at {source_path}")

    try:
        return probe.inspect(source_path)
    except Exception as error:  # noqa: BLE001 - ffprobe can fail many ways
        raise HTTPException(status_code=400, detail=str(error)) from error


# --- PREPARE ---


@router.post("/api/prepare")
def prepare(request: SourceRequest) -> JobState:
    """
    Builds the all-intra mezzanine and the numbered review proxy.

    Notes:
        **Both, not one.** The mezzanine is what tracking reads, because
        backward runs seek and a seek is only exact on an all-intra file.
        The proxy is what a person scrubs, because its frame numbers are
        burned in and a box drawn on frame 120 is then provably on frame 120.
    """
    source_path = Path(request.path)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"No file at {source_path}")

    def work(job) -> dict:
        job.say(f"Reading {source_path.name}")
        source = probe.probe(source_path)

        work_dir = ensure_directory(work_dir_for(suggested_output_dir(source_path)))
        mezzanine_path = work_dir / f"{source_path.stem}_mezzanine.mov"
        proxy_path = work_dir / f"{source_path.stem}{config.PROXY_SUFFIX}"

        job.total = source.frame_count * 2

        job.say(f"Copying {source.frame_count} frames to an all-intra mezzanine")
        MezzanineBuilder(toolchain).build(source, mezzanine_path)
        job.progress(source.frame_count, job.total)

        job.say("Building the numbered review proxy")
        ProxyBuilder(toolchain).build(mezzanine_path, proxy_path)
        job.progress(job.total, job.total)

        job.say(f"Prepared {source_path.name}")
        return PreparedPaths(
            mezzanine=str(mezzanine_path), proxy=str(proxy_path)
        ).model_dump()

    return _start("prepare", work)


# --- TRACK ---


@router.post("/api/track")
def track(request: SourceRequest) -> JobState:
    """
    Tracks the face, draws the mesh, and composites it over the plate.

    Notes:
        **The baseline run for now**: one face, whole frame, no seeds. The
        selection UI is 5.4, and until a person can draw a box there is
        nothing to seed from — but the baseline is enough to look at the
        mesh, the smoothing and the colours on real footage, which is what
        this checkpoint is for.

        The preview composites the mesh over the plate using the real
        `Compositor` and the real `LayerStack`, not a shortcut, so what is
        on screen is what the pass would produce.
    """
    source_path = Path(request.path)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"No file at {source_path}")

    def work(job) -> dict:
        source = probe.probe(source_path)
        work_dir = ensure_directory(work_dir_for(suggested_output_dir(source_path)))
        mezzanine_path = work_dir / f"{source_path.stem}_mezzanine.mov"

        reading = mezzanine_path if mezzanine_path.is_file() else source_path
        if reading is source_path:
            job.say("No mezzanine yet — tracking the source directly")

        # Tracking, then the mesh layer, then the composite: three passes
        # over the frames, which is what the bar is counting.
        job.total = source.frame_count * 3

        job.say(f"Tracking a face through {source.frame_count} frames")
        tracker = FaceTracker(toolchain)
        raw = tracker.track_every_frame(
            source,
            label="Face",
            path=reading,
            on_progress=lambda done, _total: job.progress(done, job.total),
        )

        rate = source.fps_numerator / source.fps_denominator
        tracked = smooth(raw, rate)
        found = int(tracked.tracked.sum())
        job.say(f"Found the face on {found} of {source.frame_count} frames")

        colours = mesh.colours_for([tracked.label])
        layer_path = work_dir / f"{source_path.stem}_faces_layer.mov"

        job.say("Drawing the mesh layer")
        _write_mesh_layer(source, [tracked], colours, layer_path, job)

        preview_path = work_dir / f"{source_path.stem}{PREVIEW_SUFFIX}"
        job.say("Compositing the mesh over the plate")
        _write_preview(source, reading, layer_path, preview_path, job)

        job.say(f"Found the face on {found} of {source.frame_count} frames")
        return TrackResult(
            report=report_for([tracked], source.frame_count),
            preview=job.id,
            colours={label: list(hue) for label, hue in colours.items()},
            preview_path=str(preview_path),
            source=str(source_path),
        ).model_dump()

    return _start("track", work)


@router.get("/api/preview/{job_id}")
def preview(job_id: str):
    """
    The composited preview for a finished track, for the page to play.

    Raises:
        HTTPException: No such job, or it produced no preview.

    Notes:
        Served by job id rather than by path. A route that takes a path from
        the page and returns that file is a route that will read anything on
        the disk if someone asks it to.
    """
    job = jobs.get(job_id)
    if job is None or not job.result:
        raise HTTPException(status_code=404, detail="No preview for that job")

    source_path = Path(job.result.get("source", ""))
    path = Path(job.result.get("preview_path", ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"The preview for {source_path} is gone")

    return FileResponse(path, media_type="video/mp4")


# --- JOBS ---


@router.get("/api/job/{job_id}")
def job_state(job_id: str) -> JobState:
    """How a running job is getting on, and its result once it is done."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")

    return _state(job)


# --- THE WORK ---


def _write_mesh_layer(
    source: SourceInfo,
    tracks: list,
    colours: dict,
    path: Path,
    job,
) -> Path:
    """
    Renders the mesh to its own file with alpha.

    Notes:
        QuickTime RLE, because it is the one codec here that carries alpha
        losslessly and opens in a compositor. Writing it through the plain
        `FrameWriter` is safe now that the writer refuses to flatten alpha
        rather than doing it quietly.
    """
    rate = Fraction(source.fps_numerator, source.fps_denominator)
    base = job.done

    with FrameWriter(
        toolchain,
        path,
        source.width,
        source.height,
        rate,
        pixel_format=RGBA,
        codec=config.ALPHA_RLE_ENCODER,
    ) as writer:
        for index, frame in enumerate(
            mesh.render_layer(tracks, source.width, source.height, colours=colours)
        ):
            writer.write(frame)
            job.progress(base + index + 1, job.total)

    return path


def _write_preview(
    source: SourceInfo, plate: Path, layer: Path, path: Path, job
) -> Path:
    """
    The mesh over the plate, through the real compositor.

    Notes:
        The plate is a layer like any other, which is why this needs no
        special case: the stack is plate then mesh, and the same code that
        will composite depth composites this.
    """
    rate = Fraction(source.fps_numerator, source.fps_denominator)
    stack = LayerStack(
        layers=[Layer(source=LayerSource.PLATE), Layer(source=LayerSource.FACE_MESH)]
    )
    compositor = Compositor(
        stack, {LayerSource.PLATE: plate, LayerSource.FACE_MESH: layer}
    )
    base = job.done

    with FrameReader.for_source(toolchain, source, path=plate, pixel_format=RGB) as plates:
        with FrameReader.for_source(
            toolchain, source, path=layer, pixel_format=RGBA
        ) as meshes:
            with FrameWriter(
                toolchain, path, source.width, source.height, rate
            ) as writer:
                written = compositor.run(
                    {LayerSource.PLATE: plates, LayerSource.FACE_MESH: meshes},
                    writer,
                    source.frame_count,
                    source.width,
                    source.height,
                )

    job.progress(base + written, job.total)
    logging.info(f"Wrote a {written}-frame preview to {path}")
    return path


def _start(kind: str, work) -> JobState:
    """Starts a job, or says what is already running."""
    try:
        return _state(jobs.start(kind, work))
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _state(job) -> JobState:
    return JobState(
        id=job.id,
        kind=job.kind,
        state=job.state,
        message=job.message,
        done=job.done,
        total=job.total,
        error=job.error,
        result=job.result or None,
    )
