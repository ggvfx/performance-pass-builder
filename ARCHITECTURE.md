# Architecture Overview — Performance Pass Builder

**Not built. This is the agreed design, not a description of code.**

**Design principle:**
Each stage is decoupled and independently testable. The pipeline only
coordinates execution order.

**Two tabs, one of them a workflow.** Performance Pass is the job; Setup is
everything done once — what is installed, which depth backend is used, whether
a key is configured. The workflow tab carries a one-line status strip and
links to Setup when something is wrong, so a panel nobody reads does not sit
above the work.

**Data flow:**

Probe → Proxy → Depth → *Select* → Track → Smooth → Draw → Encode → Validate → Sidecar

`prepare()` runs up to Depth; the person selects faces on the proxy; `run()`
takes the selection through to the sidecar.

---

## Stage details

### 1. Probe — `SourceProbe` in `src/media/probe.py`

- Reads frame rate as an exact rational, frame count, duration, resolution,
  codec and audio streams via `ffprobe`
- Refuses variable frame rate sources: there is no stable frame-to-time
  mapping, and every pass has to line up with the source frame for frame
- Records whether the audio can be stream-copied into the pass container, so
  the user learns before the job, not after it

Produces a `SourceInfo`.

### 2. Proxy — `ProxyBuilder` in `src/media/proxy.py`

- All-intra h264, small, each frame's number burned into the corner
- What the browser plays while faces are selected. Long-GOP seeking lands near
  a frame rather than on it, and the frame a box was drawn on is the frame its
  tracker starts from — so it has to be exact, and visibly so

### 3. Depth — `src/performance/depth.py` over `src/backends/`

- Asks the configured backend for full-frame depth of the source
- **Validates what comes back** against the source: frame count, frame rate,
  aspect ratio. A hosted model that dropped or duplicated a frame fails the job
  here, before anything is drawn over it
- Caches the result in the working folder, keyed to the source and the depth
  settings, so tracking and drawing can be redone without paying again

Backends implement one interface — *give a video, get a depth video back* —
in the same shape as minicut's model adapters:

| Backend | Module | Needs |
|---|---|---|
| Fal | `src/backends/fal.py` | `FAL_KEY` in the environment. The default |
| Local | `src/backends/local_depth.py` | An NVIDIA GPU or Apple Silicon, PyTorch, the weights. Later phase |

The product team's platform would become a third implementation of the same
interface. Nothing above `src/backends/` knows which one ran.

**What Fal's schema says**, read from its OpenAPI at the time of writing:
`model` is `VDA-Small`, `VDA-Base` or `VDA-Large`; `colormap` is grayscale,
turbo, inferno, magma or viridis; `resolution` tops out at 1080p; `max_frames`
at 2400; `output_fps` defaults to the input's. Those limits are checked before
upload, not discovered after.

### 4. Select — the front end, and `src/performance/selection.py`

- The person scrubs the proxy, stops where a face is clear, drags a box round
  it, and gives it a label. Any number of faces, each on whichever frame suits
  it
- Sent to the server as **the frame number and the box's corners as fractions
  of the picture**. The browser does no pixel arithmetic
- Saved as `selection.json` in the working folder, so the picker and the
  pipeline are separable: a different front end — the product team's — only
  has to write the same file

### 5. Track — `FaceTracker` in `src/performance/tracking.py`

- One MediaPipe Face Landmarker per selected face, so two people in frame
  cannot be confused for each other by a single detector deciding which is
  which
- Seeded from the face's box on the frame it was drawn on, then run **forward
  to the end and backward to the start**. MediaPipe's video mode needs rising
  timestamps, so the backward run is its own tracker fed the frames in reverse
- Each frame, the tracker looks inside a padded box around where the face was
  on the previous frame. That is what lets a face move across the picture, and
  what keeps each tracker on its own face
- A frame where a face is not found is **recorded, not guessed**. Faces leave
  frame and turn away; a gap is reported per face and is not a failure

Produces one `FaceTrack` per face.

**Known risk:** two faces crossing. A tracker following its own previous
position can jump to the other face where they overlap. Tested for in Phase 3
on purpose rather than discovered later.

### 6. Smooth — `src/performance/smoothing.py`

- Raw landmarks jitter frame to frame, worst at the lips and eyelids, and a
  generation model renders jitter as shimmer
- A One Euro filter per landmark coordinate: strong smoothing when a point is
  still, little when it moves fast, so stillness is steady and motion is not
  dragged behind
- Plain functions. Resets across a gap rather than smoothing across it

### 7. Draw — `src/performance/mesh.py`

- MediaPipe's tessellation, lips and eyes drawn over the depth frame
- Line widths scale with the picture height, so a 1080p pass is not drawn in
  lines meant for 640px
- Colours and widths are config. The starting point is the Genjutsu
  workflow's — blue tessellation, orange lips, green eyes — because it is known
  to read as guidance to Seedance
- OpenCV draws; it never opens or writes a video file

### 8. Encode — `src/media/encode.py`

- Frames go into ffmpeg through a pipe and come out as h264, with the source's
  audio stream copied in
- Writes both deliverables: the depth on its own, and the depth with meshes

### 9. Validate — `src/performance/validator.py`

- Frame count, frame rate and duration of every deliverable match the source
- Audio present when the source had audio, and copied rather than re-encoded
  unless the probe said it could not be
- Any failure blocks the job and is shown. Never warn-and-continue

### 10. Sidecar — `src/core/sidecar.py`

- The source, the selection, every setting, the per-face tracking report, the
  validation outcome and the resolved environment: app version, platform,
  ffmpeg build, MediaPipe version and model hash, depth backend, model and
  request ID
- Written whether the job passed or failed. A failed job's sidecar is the most
  useful thing to look at when working out why

---

## Module map

```
src/
├── core/          SHARED: config, models, utils, ffmpeg toolchain,
│                 environment checks, sidecar. One file each.
├── media/         SHARED: probing, frame streaming, proxy, encoding
├── backends/      SHARED: the depth adapters — Fal now, local later
├── performance/   The performance pass: depth stage, selection, tracking,
│                 smoothing, mesh drawing, validation, pipeline
└── ui/            The app, one routes module per tab, and the front end
```

A later utility gets its own package beside `performance/`, its own routes
module and its own front-end module. If it needs something `performance/`
has, that thing moves to `core/` or `media/` at the time — not in advance.

| Path | Holds |
|---|---|
| `main.py` | Entry point — starts the server, opens the browser |
| `src/core/config.py` | Every constant, every default, the per-run `PerformanceConfig` |
| `src/core/models.py` | Every shared data model |
| `src/core/utils.py` | Helpers needed in more than one module |
| `src/core/ffmpeg_tools.py` | `MediaToolchain` — the only place a subprocess runs, including the frame pipes |
| `src/core/environment.py` | `EnvironmentChecker` — the Setup panel's rows |
| `src/core/sidecar.py` | Sidecar write, and the environment it records |
| `src/core/templates.py` | Per-platform install instructions — data, not behaviour |
| `src/media/probe.py` | `SourceProbe` |
| `src/media/frames.py` | Reading frames from, and writing frames to, an ffmpeg pipe |
| `src/media/proxy.py` | `ProxyBuilder` |
| `src/media/encode.py` | The deliverables, with the source audio copied in |
| `src/backends/adapter.py` | `DepthBackend` — the interface every backend implements |
| `src/backends/transport.py` | The HTTP itself — the one place a socket opens to a hosted model |
| `src/backends/fal.py` | Upload, submit, poll and fetch on Fal |
| `src/backends/availability.py` | The backend rows in the Setup panel |
| `src/performance/depth.py` | The depth stage: ask, validate, cache |
| `src/performance/selection.py` | Reading and checking `selection.json` |
| `src/performance/model_file.py` | Downloading and verifying the MediaPipe model |
| `src/performance/tracking.py` | `FaceTracker` |
| `src/performance/smoothing.py` | The One Euro filter |
| `src/performance/mesh.py` | Drawing a mesh on a frame |
| `src/performance/validator.py` | The checks that block a job |
| `src/performance/pipeline.py` | `PerformancePipeline` — stage order only |
| `src/ui/server.py` | The app, the page, the static mount, the wiring |
| `src/ui/runtime.py` | The toolchain and checker the routers share |
| `src/ui/browse.py` | Directory listing for the path picker |
| `src/ui/routes/setup.py` | What is installed, which backend is used |
| `src/ui/routes/performance.py` | Probe, prepare, proxy, select, run |
| `src/ui/routes/files.py` | The path picker |
| `src/ui/static/main.js` | Wiring — imports the rest, attaches every listener |
| `src/ui/static/state.js` | The one object holding what the page knows |
| `src/ui/static/player.js` | Proxy playback, stepping, the frame readout |
| `src/ui/static/selection.js` | Drawing, labelling and removing face boxes |
| `src/ui/static/performance.js` | The tab: source, prepare, run, results |
| `src/ui/static/setup.js` | The Setup tab |
| `src/ui/static/environment.js` | Dependency panel |
| `src/ui/static/picker.js` | Path picker |
| `src/ui/static/ui.js` | Display helpers used by more than one module |

Several of these will turn out to be one function, or to belong together.
That is decided when each is skeletoned, not here.

---

## Dependency direction

```
core/models.py        imports nothing of ours
core/config.py        may import models
core/utils.py         standard library only
core/ffmpeg_tools.py  standard library only
core/*                may import the above
media/, backends/     may import core
performance/          may import core, media, backends
ui/                   may import core and the utility packages
```

Nothing imports upward.

---

## Key terms

- `frame` — integer frame index, 0 at the first frame of the source
- `seed frame` — the frame a face's box was drawn on, where its tracking starts
- `face` — one selected person: a label, a seed frame and a box
- `track` — one face's landmarks on every frame, or a recorded gap
- `pass` — a deliverable video the same length as the source
- `proxy` — the small numbered copy the browser plays during selection
- `work dir` — `.performance-work/`, where the proxy and cached depth live

---

## Open questions

Decided before the task they affect, not now.

1. **Pass resolution above 1080p.** Fal returns depth at 1080p at most. Either
   the pass is written at the depth's resolution, or the depth is scaled up to
   the source's. Seedance takes 1080p input either way. *Affects Phase 4.*
2. **Default colormap.** Grayscale, or a colour map. Genjutsu sent Seedance
   coloured depth. Worth trying both on the same shot. *Affects Phase 4.*
3. **Default depth model.** VDA-Small is Apache-2.0. Base and Large are
   CC-BY-NC-4.0, non-commercial only, and running them on Fal probably does
   not change that. Large looks better. Needs a ruling for work use.
   *Affects Phase 4.*
4. **Uploading work footage to Fal.** Whether it is allowed, and for which
   material. *Affects Phase 4.*
5. **Intel Macs.** MediaPipe 1.1.0 ships wheels for Apple Silicon macOS, not
   Intel. Whether any artist is still on Intel decides whether that matters.
   *Affects Phase 1.*
