# Architecture Overview — Performance Pass Builder

**Not built. This is the agreed design, not a description of code.**

**Design principle:**
Each stage is decoupled and independently testable. The pipeline only
coordinates execution order.

**Most of the foundation is already written.** Probing, timecode, the
mezzanine, the numbered proxy, the dependency panel, the path picker and the
frame-accurate browser player exist in `minicut-shot-detector` and are ported
in rather than rebuilt. PORTING.md holds the inventory and the trims; that file
is deleted once the port is finished.

**Two tabs, one of them a workflow.** Performance Pass is the job; Setup is
everything done once — what is installed, which depth backend is used, whether
a key is configured. The workflow tab carries a one-line status strip and
links to Setup when something is wrong, so a panel nobody reads does not sit
above the work.

**Data flow:**

Probe → Mezzanine → Proxy → Depth → *Select* → Track → Smooth → **Plate** →
Draw → Encode → Validate → Sidecar

`prepare()` runs up to Depth; the person selects faces on the proxy; `run()`
takes the selection through to the sidecar.

---

## Stage details

### 1. Probe — `SourceProbe` in `src/media/probe.py`

*Ported from minicut, ~70%: cropdetect dropped.*

- Reads frame rate as an exact rational, frame count, duration, resolution,
  codec and audio streams via `ffprobe`
- Refuses variable frame rate sources: there is no stable frame-to-time
  mapping, and every pass has to line up with the source frame for frame
- Records whether the audio can be stream-copied into the pass container, so
  the user learns before the job, not after it

Produces a `SourceInfo` inside a `ProbeReport`. The report separates a
**refusal** from a **warning**, as minicut's does: VFR cannot be worked around,
while a tight disk is the user's call to make. A refusal carries its reason, so
the page can show it rather than surfacing an exception.

Frame-to-time arithmetic belongs to `src/core/timecode.py` and nowhere else.
Nothing in this project reimplements it — including anything that looks like it
only needs one little conversion.

### 2. Mezzanine — `MezzanineBuilder` in `src/media/mezzanine.py`

*Ported from minicut, ~90%. Its justification here is different.*

Re-encodes the source once into the same codec with every frame a keyframe.

**minicut needs this so a stream copy lands on the right frame. This project
never stream-copies picture, so that reason does not carry over. It is here for
a different one: frame-accurate random access.**

Tracking is iterative. A person scrubs to frame 500, draws a box, tracks
forward, sees the track break at 700, scrubs back and re-seeds. Every one of
those is an arbitrary seek into the same file, and on long-GOP h264 there are
only two options: `-ss` before `-i` is instant but snaps to a keyframe, which
is the wrong frame; `-ss` after `-i` is exact but decodes from the start every
time, which gets slower the further into the shot you work. All-intra makes a
seek both exact and instant, which is what makes re-seeding usable rather than
merely possible.

`verify()` proves the mezzanine matches the source frame for frame before
anything is built on it.

### 3. Proxy — `ProxyBuilder` in `src/media/proxy.py`

*Ported from minicut, ~95%.*

- All-intra h264, small, each frame's number burned into the corner
- Built from the **mezzanine**, which has been verified against the source, so
  frame N of the proxy is provably frame N of what will be tracked
- What the browser plays while faces are selected. Long-GOP seeking lands near
  a frame rather than on it, and the frame a box was drawn on is the frame its
  tracker starts from — so it has to be exact, and visibly so

The frame counter is a cross-check, not the product: a machine with no
monospaced font, or an ffmpeg built without libfreetype, loses the numbers and
still gets a proxy. Asking for `drawtext` on a build that lacks it aborts the
whole encode, which is why the filter is checked for first.

### 4. Depth — `src/performance/depth.py` over `src/backends/`

This stage has two outputs, and keeping them apart is what makes everything
downstream possible.

**What is stored** is a scalar depth field at the best precision the backend
will give. **What is shown** is a picture derived from it. Depth is paid for
once; the picture can be re-derived as often as the user likes, locally and
instantly, and never costs another call.

- Asks the configured backend for full-frame depth of the source
- **Validates what comes back** against the source: frame count, frame rate,
  aspect ratio. A hosted model that dropped or duplicated a frame fails the job
  here, before anything is drawn over it
- Converts the raw float array to the working format on arrival, records its
  normalisation, and caches it in the working folder keyed to the source and
  the depth settings

Backends implement one interface — *give a video, get depth back* — in the same
shape as minicut's model adapters:

| Backend | Module | Needs |
|---|---|---|
| Fal | `src/backends/fal.py` | `FAL_KEY` in the environment. The default |
| Local | `src/backends/local_depth.py` | An NVIDIA GPU or Apple Silicon, PyTorch, the weights. Later phase |

Nothing above `src/backends/` knows which one ran.

#### Fal's schema, read from its API page

`model` is `VDA-Small`, `VDA-Base` or `VDA-Large`; `colormap` is grayscale,
turbo, inferno, magma or viridis; `resolution` is auto, 360p, 480p, 720p or
1080p; `max_frames` tops out at 2400; `output_fps` defaults to the input's.
`include_raw_depths` returns a `.npz` containing `depths` as `[N,H,W]` float32,
plus `min_depth`, `max_depth`, `fps`, `model` and `shape`. Limits are checked
before upload, not discovered after.

**Three things in that schema are silent traps:**

1. **`model` defaults to `VDA-Large`, which is CC-BY-NC-4.0.** Omitting the
   parameter quietly selects the licence-restricted model. This project always
   sends `model` explicitly.
2. **`output_fps` is a float.** It is never sent. Fal matches the input when
   the parameter is absent, and sending `23.976` is exactly the drift
   everything else here is built to avoid.
3. **`side_by_side` doubles the picture width.** Never set. The arrival check
   would catch it, but only after paying for it.

#### The working format

`depths` is single-channel, which is what every later operation needs. The
`.npz` is **transport, not storage** — at 1080p a float32 frame is 8.3 MB, so
the 2400-frame maximum is about 20 GB. It is converted on arrival to 16-bit
single-channel video and deleted.

| | Per frame | 2400 frames |
|---|---|---|
| float32 `.npz`, 1080p | 8.3 MB | ~20 GB |
| float32 `.npz`, 720p | 3.7 MB | ~8.9 GB |
| 16-bit single channel | ~4 MB raw | a few GB lossless, far less lossy |

**Depth is low-frequency**, so raw depth can be requested at a lower resolution
than the pass and upscaled with almost nothing lost. The raw-depth resolution
is therefore its own setting rather than following the pass.

**Known trap:** `np.load` on an `.npz` returns a lazy archive, but touching
`["depths"]` decompresses the whole array into memory — 20 GB for a long shot.
The member has to be extracted to a plain `.npy` first and then memory-mapped,
and frames streamed from it. The obvious one-liner runs out of memory on any
real source.

**Raw depth is optional.** A plain performance pass with no depth adjustment
does not need the download at all, so the page offers it with the cost stated.
The grayscale video comes back from the same call either way and is the instant
preview.

### 5. Select — the front end, and `src/performance/selection.py`

- The person scrubs the proxy, stops where a face is clear, drags a box round
  it, and gives it a label. Any number of faces
- **A face carries a list of seed boxes, not one.** Each has its own frame.
  Tracking a face forward until it breaks and re-seeding it past the break is
  the normal way to work, not a recovery path
- Sent to the server as **the frame number and the box's corners as fractions
  of the picture**. The browser does no pixel arithmetic
- Saved as `selection.json` in the working folder, so the picker and the
  pipeline are separable: a different front end only has to write the same file

### 6. Track — `FaceTracker` in `src/performance/tracking.py`

- One MediaPipe Face Landmarker per selected face, so two people in frame
  cannot be confused for each other by a single detector deciding which is
  which
- **Tracked in segments between seeds.** Backward from the first seed to frame
  0, then forward from each seed until the next seed's frame or until the face
  is lost. MediaPipe's video mode needs rising timestamps, so a backward run is
  its own tracker fed the frames in reverse
- The one-seed case — forward and backward from a single box — is this with a
  list of length one. There is no second mechanism
- Each frame, the tracker looks inside a padded box around where the face was
  on the previous frame. That is what lets a face move across the picture, and
  what keeps each tracker on its own face
- A frame where a face is not found is **recorded, not guessed**. Faces leave
  frame, turn away, and get wiped across; a gap is reported per face and is not
  a failure
- **Each frame records which seed produced it.** That is what lets the timeline
  show where a re-seed is needed rather than leaving the person to guess

Produces one `FaceTrack` per face.

**Known risk:** two faces crossing. A tracker following its own previous
position can jump to the other face where they overlap. Tested for in Phase 3
on purpose rather than discovered later. Re-seeding is also the manual answer
to it.

### 7. Smooth — `src/performance/smoothing.py`

- Raw landmarks jitter frame to frame, worst at the lips and eyelids, and a
  generation model renders jitter as shimmer
- A One Euro filter per landmark coordinate: strong smoothing when a point is
  still, little when it moves fast, so stillness is steady and motion is not
  dragged behind
- Plain functions. Resets across a gap and across a seed boundary rather than
  smoothing through either

### 8. Plate — `src/performance/plate.py`

**The seam that matters most in this design.** The plate is the picture the
mesh is drawn on, and the stage that produces it is separate from the stage
that draws.

- **Now:** the plate is the stored depth field, windowed, then colormapped
- **Later:** the plate is a composite — regions of depth, regions of the
  original picture, regions of flat grey, selected by masks
- **`mesh.py` and `encode.py` never learn the difference.** They consume a
  frame of picture and do not care what produced it

Putting this boundary in now costs a function signature. Retrofitting it later
means touching drawing, encoding and validation together.

#### Windowing

The user positions the 0–1 range over the part of the depth they care about —
midground figures, say — instead of spreading it across everything from the
lens to the horizon:

```
out = clamp((depth - near) / (far - near), 0, 1)
```

This is a levels operation with the black and white points pulled inward. It is
why the stored precision matters: windowing the middle 10% of an 8-bit depth
map leaves about 25 output levels and terraces visibly on a face, while 16-bit
leaves about 6,550 and shows nothing.

- **A window is constant across the clip.** Per-frame windowing would fight
  Video Depth Anything's temporal consistency and make the depth pump, which is
  the one artefact a generation model will certainly render
- **Hard clip first.** Everything in front of `near` clamps to white and
  everything past `far` to black, so the background becomes a flat card. A soft
  knee that compresses rather than clips the outside is a setting, not a
  rewrite
- **Depth from this model is relative, not metric**, and normalised per clip.
  `min_depth` and `max_depth` from the `.npz` are what a window's numbers mean,
  and are recorded with the stored depth

#### Colormap

Applied last, and only here.

Grayscale is monotonic and invertible. Turbo, inferno and magma are neither, so
colormapping early does not merely lose precision — it destroys the ability to
window at all, because the number 0.42 has become a colour that only a reverse
lookup can undo. Everything upstream of this point is single-channel.

Whether a deliverable is grey or coloured is an empirical question about what
Seedance responds to, and because the colormap is the last step both can be
rendered from one cached depth and compared on the same shot for nothing.

### 9. Draw — `src/performance/mesh.py`

- MediaPipe's tessellation, lips and eyes drawn over the plate
- Line widths scale with the picture height, so a 1080p pass is not drawn in
  lines meant for 640px
- Colours and widths are config. The starting point is the Genjutsu
  workflow's — blue tessellation, orange lips, green eyes — because it is known
  to read as guidance to Seedance
- OpenCV draws; it never opens or writes a video file

### 10. Encode — `src/media/encode.py`

- Frames go into ffmpeg through a pipe and come out as h264, with the source's
  audio stream copied in
- Writes both deliverables: the depth on its own, and the depth with meshes
- **New work with no counterpart in minicut**, which stream-copies shots out of
  a mezzanine and never pipes RGB in either direction

### 11. Validate — `src/performance/validator.py`

*The `framemd5` machinery ported from minicut's `splitter/validator.py`, ~35%.*

- Frame count, frame rate and duration of every deliverable match the source
- Audio present when the source had audio, and copied rather than re-encoded
  unless the probe said it could not be
- Frame hashes are how a depth video is proven to have come back frame for
  frame, rather than taken on trust
- Any failure blocks the job and is shown. Never warn-and-continue

### 12. Sidecar — `src/core/sidecar.py`

*Ported from minicut, ~80%.*

- The source, the selection including every seed, each setting, the per-face
  tracking report, the validation outcome, the depth normalisation
  (`min_depth`, `max_depth`, model, shape) and the resolved environment: app
  version, platform, ffmpeg build, MediaPipe version and model hash, depth
  backend, model and request ID
- Written whether the job passed or failed. A failed job's sidecar is the most
  useful thing to look at when working out why

---

## Module map

```
src/
├── core/          SHARED: config, models, utils, ffmpeg toolchain, timecode,
│                 environment checks, sidecar. One file each.
├── media/         SHARED: probing, frame streaming, mezzanine, proxy, encoding
├── backends/      SHARED: the depth adapters — Fal now, local later
├── performance/   The performance pass: depth stage, selection, tracking,
│                 smoothing, plate, mesh drawing, validation, pipeline
└── ui/            The app, one routes module per tab, and the front end
```

`src/depth/` is the expected home of the depth manipulation utility —
combining passes, aligning their ranges, and later the region compositing that
SAM masks would drive. **None of it is designed and none of it is built.** It
is named here only so the plate seam has a stated reason to exist, and so the
first person to need it knows where it goes.

| Path | Holds |
|---|---|
| `main.py` | Entry point — starts the server, opens the browser |
| `src/core/config.py` | Every constant, every default, the per-run `PerformanceConfig`, saved `Settings` |
| `src/core/models.py` | Every shared data model |
| `src/core/utils.py` | Helpers needed in more than one module |
| `src/core/ffmpeg_tools.py` | `MediaToolchain` — the only place a subprocess runs, including the frame pipes |
| `src/core/timecode.py` | `Timecode` — the only place frames become time |
| `src/core/environment.py` | `EnvironmentChecker` — the Setup panel's rows |
| `src/core/sidecar.py` | Sidecar write, and the environment it records |
| `src/core/templates.py` | Per-platform install instructions — data, not behaviour |
| `src/media/probe.py` | `SourceProbe` |
| `src/media/frames.py` | Reading frames from, and writing frames to, an ffmpeg pipe |
| `src/media/mezzanine.py` | `MezzanineBuilder` — all-intra, for exact random access |
| `src/media/proxy.py` | `ProxyBuilder` |
| `src/media/workspace.py` | The working folder's naming and lifecycle |
| `src/media/encode.py` | The deliverables, with the source audio copied in |
| `src/backends/adapter.py` | `DepthBackend` — the interface every backend implements |
| `src/backends/transport.py` | The HTTP itself — the one place a socket opens to a hosted model |
| `src/backends/fal.py` | Upload, submit, poll and fetch on Fal |
| `src/backends/availability.py` | The backend rows in the Setup panel |
| `src/performance/depth.py` | The depth stage: ask, validate, convert, cache |
| `src/performance/selection.py` | Reading and checking `selection.json` |
| `src/performance/model_file.py` | Downloading and verifying the MediaPipe model |
| `src/performance/tracking.py` | `FaceTracker` |
| `src/performance/smoothing.py` | The One Euro filter |
| `src/performance/plate.py` | Window and colormap — the picture the mesh goes on |
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
| `src/ui/static/selection.js` | Drawing, labelling and removing face boxes and seeds |
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
core/timecode.py      may import models
core/*                may import the above
media/, backends/     may import core
performance/          may import core, media, backends
ui/                   may import core and the utility packages
```

Nothing imports upward.

**A consequence worth stating**, because it decided where two things live: a
constant that is part of a data contract rather than a setting lives in
`models.py`, since `config.py` imports `models.py` and not the other way round.
`LANDMARK_COUNT` is the example. And the sidecar model, which has to reference
`PerformanceConfig`, lives in `core/sidecar.py` rather than `models.py` for the
same reason.

---

## Key terms

- `frame` — integer frame index, 0 at the first frame of the source
- `seed` — a box drawn on a chosen frame, from which tracking runs
- `face` — one selected person: a label and a list of seeds
- `track` — one face's landmarks on every frame, each frame recorded as tracked
  by a named seed, or as a gap
- `segment` — the run of frames one seed is responsible for
- `plate` — the picture the mesh is drawn on. Depth, windowed and colormapped
- `window` — the `near`/`far` pair mapped onto the output's 0–1
- `pass` — a deliverable video the same length as the source
- `proxy` — the small numbered copy the browser plays during selection
- `mezzanine` — the all-intra copy, for exact random access
- `work dir` — `.performance-work/`, where the mezzanine, proxy and cached
  depth live

---

## Open questions

Decided before the task they affect, not now.

1. **Pass resolution above 1080p.** Fal returns depth at 1080p at most. Either
   the pass is written at the depth's resolution, or the depth is scaled up to
   the source's. Seedance takes 1080p input either way. *Affects Phase 4.*
2. **Default colormap.** Grayscale, or a colour map. Genjutsu sent Seedance
   coloured depth. Cheap to try both on one shot now that the colormap is the
   last step. *Affects Phase 4.*
3. **Default depth model.** VDA-Small is Apache-2.0. Base and Large are
   CC-BY-NC-4.0, non-commercial only, and running them on Fal probably does
   not change that. Large looks better, and is Fal's default — which is why the
   parameter is always sent explicitly. Needs a ruling for work use.
   *Affects Phase 4.*
4. **Uploading work footage to Fal.** Whether it is allowed, and for which
   material. *Affects Phase 4.*
5. **The stored depth format.** FFV1 `gray16le` is lossless and a few GB for a
   long shot; x265 10-bit mono is a few hundred MB with an error far below
   anything a window will reveal; a 16-bit PNG or half-float EXR sequence is
   the most VFX-native and the most files. Decided by measuring one real shot,
   and `MediaToolchain.has_encoder()` is how the build gets checked first.
   *Affects Phase 4.*
6. **Intel Macs.** MediaPipe 1.1.0 ships wheels for Apple Silicon macOS, not
   Intel. Whether any artist is still on Intel decides whether that matters.
   *Affects Phase 1.*
