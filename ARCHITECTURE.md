# Architecture Overview — Performance Pass Builder

**Mostly not built. This is the agreed design, not a description of code.**
Phase 1 is finished: the app runs, reports what it needs, and picks a source.
Nothing reads a frame yet.

**Design principle:**
Each stage is decoupled and independently testable. Nothing coordinates
execution order except the places that have to.

**This is a compositing app, not a pipeline with a button at the end.** A
source is prepared once. Several independent **passes** each produce a
**layer**. A **stack** combines whichever layers the artist turned on, and the
output is that stack. One pass on its own is the stack with one layer enabled,
so there is no separate export path for "just the depth".

That shape is the reason the design is worth more than the sum of its stages:
segmentation, other control passes and depth manipulation all arrive as new
generators feeding the same stack, rather than as new branches through a
single linear flow.

**Most of the foundation is already written.** Probing, timecode, the
mezzanine, the numbered proxy, the dependency panel, the path picker and the
frame-accurate browser player exist in `minicut-shot-detector` and are ported
in rather than rebuilt. PORTING.md holds the inventory and the trims; that
file is deleted once the port is finished.

---

## The shape

```
                 ┌─ Depth pass ──────────┐
Source ─ Prepare ┤                       ├─ Stack ─ Output ─ Validate ─ Sidecar
                 └─ Faces pass ──────────┘
                    (later: segmentation,
                     other control passes)
```

**Prepare** is shared and is not a pass: probe, mezzanine, proxy. Everything
downstream reads the mezzanine.

**A pass** owns its own settings, its own processing, its own cache and its
own preview. Running one never runs another. Re-rendering a mesh never
re-tracks faces; changing a depth window never calls the model again.

**The stack** is an ordered list of layers, index 0 at the bottom. In v1 a
layer is a pass plus an on/off switch, composited "over". Opacity, blend
modes and masks fit the same model later without changing it, and are
deliberately not built now.

**The front end mirrors this exactly**: a step strip — Source, Depth, Faces,
Composite — where each step holds its own settings, its own process button
and its own result. Every step is reachable from the start and says what state
it is in, rather than being locked: someone opening the app for the first time
should be able to see the shape of the job.

---

## Stage details

### 1. Probe — `SourceProbe` in `src/media/probe.py`

*Ported from minicut, ~70%: cropdetect dropped.*

- Reads frame rate as an exact rational, frame count, duration, resolution,
  codec and audio streams via `ffprobe`
- Refuses variable frame rate sources: there is no stable frame-to-time
  mapping, and every layer has to line up with the source frame for frame
- Records whether the audio can be stream-copied into the output

Produces a `SourceInfo` inside a `ProbeReport`, which separates a **refusal**
from a **warning**: VFR cannot be worked around, while a tight disk is the
user's call. A refusal carries its reason so the page can show it.

Frame-to-time arithmetic belongs to `src/core/timecode.py` and nowhere else.

### 2. Mezzanine — `MezzanineBuilder` in `src/media/mezzanine.py`

*Ported from minicut, ~90%. Its justification here is different.*

Re-encodes the source once into the same codec with every frame a keyframe.

**minicut needs this so a stream copy lands on the right frame. This project
never stream-copies picture, so that reason does not carry over. It is here
for a different one: frame-accurate random access.**

Tracking is iterative. A person scrubs to frame 500, draws a box, tracks
forward, sees the track break at 700, scrubs back and re-seeds. Every one of
those is an arbitrary seek, and long-GOP h264 offers only fast-and-wrong
(`-ss` before `-i`, which snaps to a keyframe) or exact-and-slow (`-ss` after
`-i`, which decodes from the start every time). All-intra makes a seek both
exact and instant.

`verify()` proves the mezzanine matches the source frame for frame before
anything is built on it.

### 3. Proxy — `ProxyBuilder` in `src/media/proxy.py`

*Ported from minicut, ~95%.*

- All-intra h264, small, each frame's number burned into the corner
- Built from the mezzanine, so frame N of the proxy is provably frame N of
  what will be tracked
- The frame counter is a cross-check, not the product: a machine with no
  monospaced font, or an ffmpeg without libfreetype, loses the numbers and
  still gets a proxy. Asking for `drawtext` on a build that lacks it aborts
  the whole encode, which is why the filter is checked for first

---

## The passes

Every pass answers the same four questions, and the UI is the same shape for
each: **what settings, process it, here is the result, here is what you can
adjust without processing again.**

A pass produces a layer the stack can use, validated against the source when
it is produced. A pass that has not been run contributes nothing; a pass that
has been run and switched off contributes nothing either, and keeps its cache.

### 4. The depth pass — `src/performance/depth.py` over `src/backends/`

**Generate.** Ask the configured backend for full-frame depth, validate what
comes back against the source — frame count, frame rate, aspect ratio — and
convert it on arrival to the stored scalar field. A hosted model that dropped
or duplicated a frame fails here, before anything is built on it.

**Edit, without regenerating.** The window and the colour map are applied when
the layer is rendered, from the stored field, locally and instantly. They are
settings on the Depth step, under the result, and nothing about them costs a
call. Combining a second depth map and aligning its range belongs here too,
when it is built.

| Backend | Module | Needs |
|---|---|---|
| Fal | `src/backends/fal.py` | `FAL_KEY` in the environment. The default |
| Supplied | `src/backends/supplied.py` | A depth video the artist already has |
| Local | `src/backends/local_depth.py` | An NVIDIA GPU or Apple Silicon, PyTorch, the weights. Later phase |

Nothing above `src/backends/` knows which one ran.

#### Supplied depth

Someone who already generated depth elsewhere should not have to pay for it
again to get face meshes over it. **This is a backend like any other**: it
returns a depth video, and the arrival checks, the conversion to the stored
field, the window and the colour map all run exactly as they do for a hosted
one. The only thing it skips is the call.

That makes the existing validation worth more rather than less — depth from
another tool is precisely the thing most likely to be a different length, a
different rate or a different shape from the source, and that fails on
arrival instead of halfway through a composite.

Three things about it are different, and the page has to say so:

- **A colormapped import cannot be windowed.** Turbo and the rest are not
  invertible, so if what arrives is already coloured, the range controls are
  off. Greyscale imports are fine. This is non-negotiable 12 seen from the
  other side.
- **There is no `min_depth` / `max_depth`.** A hosted pass reports the model's
  own range; an import has only whatever 0–1 means in the file it came in as.
  The stored normalisation is recorded as unknown, and aligning it against a
  second pass is by eye with no numbers to start from.
- **Precision is whatever the file has.** An 8-bit import windows badly, and
  the panel should say so before the slider disappoints someone.

**It has to be exactly the source's length, or it is refused.** Non-negotiable
2 applies to depth that arrives as much as to depth that is generated, and an
import is the likeliest thing to be a frame out. Offering to trim or pad is a
reasonable future convenience and is deliberately not built now: a silent
one-frame correction is the kind of help that produces a pass which drifts and
a reason nobody can find.

It is also one of two reasons a missing `FAL_KEY` is **degraded rather than
blocking**. A machine with no key can build a pass from supplied depth — and
it does not have to wait for this to be built, because face tracking is local
and free and a mesh layer is a deliverable on its own. An environment check
reports what a machine can do, and "cannot run" was never true of a machine
that can still produce a pass.

What a missing key must stop is the depth *operation*, refused where it is
asked for, so the message is about the thing being attempted rather than
about the app. That gate belongs to the depth backend, not to the panel.

#### Fal's schema, read from its API page

`model` is `VDA-Small`, `VDA-Base` or `VDA-Large`; `colormap` is grayscale,
turbo, inferno, magma or viridis; `resolution` is auto, 360p, 480p, 720p or
1080p; `max_frames` tops out at 2400; `output_fps` defaults to the input's.
`include_raw_depths` returns a `.npz` containing `depths` as `[N,H,W]`
float32, plus `min_depth`, `max_depth`, `fps`, `model` and `shape`.

**Three things in that schema are silent traps:**

1. **`model` defaults to `VDA-Large`, which is CC-BY-NC-4.0.** Omitting the
   parameter quietly selects the licence-restricted model. Always sent.
2. **`output_fps` is a float.** Never sent — Fal matches the input when it is
   absent, and sending `23.976` is exactly the drift this project exists to
   avoid.
3. **`side_by_side` doubles the picture width.** Never set.

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

**Depth is low-frequency**, so raw depth can be requested at a lower
resolution than the output and upscaled with almost nothing lost. That
resolution is its own setting.

**Known trap:** `np.load` on an `.npz` returns a lazy archive, but touching
`["depths"]` decompresses the whole array into memory. The member has to be
extracted to a plain `.npy` first and then memory-mapped. The obvious
one-liner runs out of memory on any real source.

**Raw depth is optional.** A pass with no depth adjustment does not need the
download, so the page offers it with the cost stated. The grayscale video
comes back from the same call either way and is the instant preview.

#### Windowing

The user positions the 0–1 range over the part of the depth they care about —
midground figures, say — rather than spreading it from the lens to the horizon:

```
out = clamp((depth - near) / (far - near), 0, 1)
```

A levels operation with the black and white points pulled inward. It is why
stored precision matters: windowing the middle 10% of an 8-bit depth map
leaves about 25 output levels and terraces visibly on a face, while 16-bit
leaves about 6,550.

- **One window for the whole clip.** Per-frame windowing would fight Video
  Depth Anything's temporal consistency and make the depth pump, which is the
  one artefact a generation model will certainly render
- **Hard clip first.** A soft knee that compresses rather than clips the
  outside is a setting, not a rewrite
- **Depth here is relative, not metric**, and normalised per clip. `min_depth`
  and `max_depth` are what a window's numbers mean, and the only basis for
  aligning one depth pass against another

#### Colour map

Applied last, only when the layer is rendered. Grayscale is monotonic and
invertible; turbo, inferno and magma are neither, so colouring early would not
merely lose precision — it would destroy the ability to window at all.
Everything upstream of this point is single-channel.

### 5. The faces pass — `src/performance/`

**Select.** The person scrubs the proxy, draws a box round a face and labels
it. **A face carries a list of seeds, not one**: tracking forward until the
face turns away or a wipe crosses it, then re-seeding past the break, is the
normal way to work rather than a recovery path. Sent as the frame number and
the box's corners as fractions of the picture; the browser does no pixel
arithmetic. Saved as `selection.json`, which is the whole interface between
the picker and the pipeline.

**Track** — `FaceTracker` in `tracking.py`. One MediaPipe Face Landmarker per
face, so two people in frame cannot be confused for each other. Tracked in
segments between seeds: backward from the first to frame 0, forward from each
to the next. MediaPipe's video mode needs rising timestamps, so a backward run
is its own tracker fed the frames in reverse. A frame where a face is not
found is **recorded, not guessed**, and every frame records which seed
produced it — that is what lets the timeline show where another seed is
needed.

Each frame the picture is **cropped** to a region around where the face was
last, and only that is searched: a face wandering into shot is not a
candidate because it is not in the picture handed to the model. The region is
grown to at least MediaPipe's own 192-pixel working size first, so cropping
tight to a distant face does not hand the model a magnified thumbnail. While
a face is missing the region stays put — a blink recovers, someone who leaves
and returns elsewhere wants another seed.

Reading backwards is the awkward part, because a decoder only runs forwards.
`frames_backwards` buys frames in memory-bounded windows and hands them back
in reverse, which means seeking, which is **only exact on the all-intra
mezzanine**. That is the sharpest edge in the pass: on long-GOP video a seek
lands on the wrong frame and every landmark after it is attributed to the
wrong picture, with nothing downstream able to tell.

**Smooth** — `smoothing.py`. A One Euro filter per landmark coordinate:
strong smoothing when a point is still, little when it moves fast. Resets
across a gap and across a seed boundary rather than smoothing through either.
Raw jitter is rendered as shimmer by a generation model.

**Render** — `mesh.py`. The tessellation, lips and eyes drawn with OpenCV to
**the face layer: its own picture with transparency, not a drawing on top of
depth.** That is what lets the mesh be output alone, sit over any other layer,
or be left out of a composite entirely without re-tracking anything. Line
widths scale with picture height. Colours and widths are config, starting from
the Genjutsu workflow's blue tessellation, orange lips and green eyes, which
is known to read as guidance to Seedance.

**All faces render to one layer**, not one layer each: a three-person shot
should not fill the stack with near-identical rows, and per-face visibility
belongs on the Faces step where the faces are.

OpenCV draws. It never opens or writes a video file.

**Known risk:** two faces crossing. A tracker following its own previous
position can jump to the other face where they overlap. Tested for in Phase 3
on purpose. Re-seeding is also the manual answer to it.

---

## The stack

### 6. Composite — `src/composite/compositor.py`

An ordered list of layers, index 0 at the bottom, each composited over the one
below.

In v1 a layer is **a source and an on/off switch**, and the operator is always
"over". That is deliberately almost nothing: the value is the shape, not the
features. Opacity, blend modes, per-layer masks and transforms all fit this
model without changing it, and none of them has anything to drive it yet.

**The stack is editable.** Layers reorder as well as switch off, and that is
the point rather than a convenience: a segmented depth region over the plate
is a different picture from the plate over that region, and neither is more
correct. The order is the artist's, not the app's.

**The plate and a flat grey card are sources like any other**, listed beside
depth and the face mesh:

| Source | Opaque | What it is for |
|---|---|---|
| `plate` | yes | The original footage, unaltered |
| `grey` | yes | A flat card, 18% by default — `GREY_CARD_LEVEL` |
| `black` | yes | Nothing under anything |
| `depth` | yes | The depth pass, windowed and coloured |
| `face_mesh` | **no** | The mesh, with alpha |

They are one list on purpose. The compositor should not know which layers were
generated and which were given, and the day a segmented region sits over the
plate, the plate has to be an ordinary layer rather than a special case
underneath everything.

**The mesh is the only layer with alpha**, so what is under it shows through —
which makes two useful things fall out of the same mechanism rather than
needing modes of their own:

- **mesh over the plate** is how a track is checked, which is exactly what the
  Phase 3 decision point asks for
- **mesh over grey** is how the mesh is looked at on its own

**Outputting one pass is this with one layer enabled.** There is no separate
export path, which is the main reason the stack is worth having in v1 rather
than later.

**Every layer is a file, read a frame at a time.** Settled rather than
deferred, and the deciding case is an artist who already has passes and wants
to mix them with generated ones: if a layer can be something they already
have, every layer may as well be. It follows that a pass is rendered once and
reused across as many composites as the artist likes, that any layer can be
opened and looked at when something is wrong, and that supplied depth needs
no special path. The grey card and black are the exceptions — a constant is
synthesised per frame rather than written out.

Memory is not the constraint it sounds like: the compositor holds one frame
per layer, which is about 8 MB each at 1080p.

**Alpha is straight, not premultiplied, everywhere.** The composite is
`fg·α + bg·(1−α)`, and the files carry straight alpha because that is what
PNG and QuickTime RLE conventionally mean.

Premultiplied would actually be the cheaper operation — one multiply instead
of two — and it is what antialiased drawing on black naturally produces. It
is rejected anyway, because writing premultiplied data into a file that
claims to be straight puts dark fringes on every edge in a compositor that
believes the label. Straight means the array in memory and the bytes on disk
mean the same thing, with no conversion to get wrong. The unpremultiply
happens once where the mesh is drawn, not on every composite.

**Every layer is the source's length.** A pass validates its own output when
it is produced, so the composite inherits that rather than rechecking it.

The compositor knows about layers and nothing about what made them. A
generator never learns what consumes it. That is the same principle the
earlier design called the plate seam, with a real stack in place of one
function signature.

### 7. Output — `src/media/encode.py`

- Frames go into ffmpeg through a pipe and come out as h264, with the source's
  audio stream copied in **unless the artist asked for it to be left out**
- Writes whatever the stack was asked for: the composite, or any single pass
- **New work with no counterpart in minicut**, which stream-copies shots out
  of a mezzanine and never pipes RGB in either direction

#### Audio, in one place

Audio handling is spread across the probe, the encoder and the sidecar, so
what it does and what it costs is gathered here.

**Carried untouched when it is carried.** Stream-copied into the output, not
decoded and re-encoded, so lip sync in the generation is driven by exactly
what was recorded.

**Whether to carry it is the artist's choice**, defaulting to yes. Leaving it
out is checked rather than assumed — the validator asserts the output has no
audio stream, because for client audio that should not travel with a file,
"we did not add it" and "it is not there" are different claims.

**There is exactly one lossy step, and it is announced three times.** Where
the source's codec cannot live in an mp4 — 24-bit PCM off a camera being the
usual case — it is re-encoded once as AAC 320k. The probe warns before the
job, the page shows that warning, and the sidecar records it afterwards.
Silently degrading someone's production audio is not a thing to be discreet
about.

**The mux happens in the same ffmpeg pass as the picture**, as a second input
rather than a second pass over the whole video. That saves writing every
frame twice, and it carries one risk worth naming: with two inputs, ffmpeg
picks streams by its own rules unless told otherwise, and could take the
*source's* picture instead of the frames being piped in — silently delivering
the original footage as the pass. `-map 0:v:0` is therefore explicit, and a
test writes flat colour through the pipe and reads back which picture
actually arrived.

**`-shortest` is never passed.** It would trim the picture to the audio, and
nothing is ever trimmed — see non-negotiable 2.

**What happened is recorded, not inferred.** `AudioHandling` is one of
copied, encoded, omitted or none. Three of those produce files that look
identical, so the sidecar is the only place the difference survives. A PNG
sequence always records `omitted`, because a folder of frames cannot hold a
soundtrack.

### 8. Validate — `src/performance/validator.py`

*The `framemd5` machinery ported from minicut's `splitter/validator.py`, ~35%.*

- Frame count, frame rate and duration of every output match the source
- Audio present when the source had it and it was asked for, and copied rather
  than re-encoded unless the probe said it could not be. **And absent when it
  was asked to be left out** — checked rather than assumed, because for the
  privacy case "we did not add it" and "it is not there" are different claims
- Frame hashes catch a **stalled** model. Depth cannot be hash-matched
  against its source — they are not the same picture — so what is compared is
  where each file *repeats* a frame. A still shot repeats frames legitimately;
  depth repeating where the plate did not is the model having stalled, and
  metadata will never say so because the file is the right length at the right
  rate
- Any failure blocks and is shown. Never warn-and-continue

### 9. Sidecar — `src/core/sidecar.py`

*Ported from minicut, ~80%.*

Records the source, the selection including every seed, each pass that ran and
its settings, the stack as it was composited, the per-face tracking report,
the validation outcome, the depth normalisation, and the resolved environment:
app version, platform, ffmpeg build, MediaPipe version and model hash, depth
backend, model and request ID.

Written whether the job passed or failed. A failed job's sidecar is the most
useful thing to look at when working out why.

---

## Module map

```
src/
├── core/          SHARED: config, models, utils, ffmpeg toolchain, timecode,
│                 environment checks, sidecar. One file each.
├── media/         SHARED: probing, frame streaming, mezzanine, proxy, encoding
├── backends/      SHARED: the depth adapters — Fal now, local later
├── composite/     The layer stack. Knows nothing about what made a layer
├── performance/   The passes: depth, selection, tracking, smoothing, mesh,
│                 validation, pipeline
└── ui/            The app, one routes module per tab, and the front end
```

A new pass — segmentation, another control pass — is a module in
`performance/` that produces a layer, plus a step in the strip. It does not
touch the compositor, the encoder or the validator. That is the whole point of
the restructure.

| Path | Holds |
|---|---|
| `main.py` | Entry point — starts the server, opens the browser |
| `src/core/config.py` | Every constant, every default, per-pass settings, saved `Settings` |
| `src/core/models.py` | Every shared data model |
| `src/core/utils.py` | Helpers needed in more than one module |
| `src/core/ffmpeg_tools.py` | `MediaToolchain` and the pipes — the only place a subprocess runs, and the only place one is closed, killed or reaped |
| `src/core/timecode.py` | `Timecode` — the only place frames become time |
| `src/core/environment.py` | `EnvironmentChecker` — the Setup panel's rows |
| `src/core/sidecar.py` | Sidecar write, and the environment it records |
| `src/core/templates.py` | Per-platform install instructions — data, not behaviour |
| `src/media/probe.py` | `SourceProbe` |
| `src/media/frames.py` | Frames to and from a pipe: the arguments, the byte arithmetic, the numpy array. Never a process |
| `src/media/mezzanine.py` | `MezzanineBuilder` — all-intra, for exact random access |
| `src/media/proxy.py` | `ProxyBuilder` |
| `src/media/workspace.py` | The working folder's naming and lifecycle |
| `src/media/encode.py` | Writing an output, with the source audio copied in |
| `src/backends/adapter.py` | `DepthBackend` — the interface every backend implements |
| `src/backends/transport.py` | The HTTP itself — the one place a socket opens to a hosted model |
| `src/backends/fal.py` | Upload, submit, poll and fetch on Fal |
| `src/backends/availability.py` | The backend rows in the Setup panel |
| `src/composite/compositor.py` | The stack: order, enabled, over |
| `src/performance/depth.py` | The depth pass: request, validate, store, render its layer |
| `src/performance/selection.py` | Reading and checking `selection.json` |
| `src/performance/model_file.py` | Downloading and verifying the MediaPipe model |
| `src/performance/tracking.py` | `FaceTracker` — the baseline run and seeded runs |
| `src/performance/face_geometry.py` | Where a face is: search regions, crop mapping, choosing between detections |
| `src/performance/smoothing.py` | The One Euro filter |
| `src/performance/mesh.py` | Rendering the face layer |
| `src/performance/smoothing.py` | One Euro filter, resetting at every gap and seed |
| `src/performance/landmarks.py` | Writing and reading `landmarks.json` |
| `src/performance/validator.py` | The checks that block an output |
| `src/performance/pipeline.py` | Stage order within a pass, and nothing else |
| `src/ui/server.py` | The app, the page, the static mount, the wiring |
| `src/ui/runtime.py` | The toolchain and checker the routers share |
| `src/ui/browse.py` | Directory listing for the path picker |
| `src/ui/routes/setup.py` | What is installed, which backend is used |
| `src/ui/routes/performance.py` | Prepare, run a pass, composite, output |
| `src/ui/routes/files.py` | The path picker |
| `src/ui/static/index.html` | The one page: both tabs, the step strip, every panel |
| `src/ui/static/styles.css` | The one stylesheet. No framework |
| `src/ui/static/main.js` | Wiring — imports the rest, and attaches the listener for every element written in the HTML |
| `src/ui/static/tabs.js` | Performance Pass and Setup |
| `src/ui/static/state.js` | The one object holding what the page knows |
| `src/ui/static/steps.js` | The step strip, and what state each step is in |
| `src/ui/static/player.js` | Playback, stepping, the frame readout |
| `src/ui/static/source.js` | The Source step |
| `src/ui/static/depth.js` | The Depth step: settings, process, window, colour map |
| `src/ui/static/faces.js` | The Faces step: boxes, seeds, per-face visibility |
| `src/ui/static/composite.js` | The Composite step: the stack, and output |
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
composite/            may import core, media
performance/          may import core, media, backends, composite
ui/                   may import everything below it
```

Nothing imports upward. **`composite/` may not import `performance/`** — the
compositor taking a dependency on a pass is the exact mistake this structure
exists to prevent.

It *may* import `media/`, which was tightened to `core` only in an earlier
draft and relaxed when the compositor was written: layers are files, and
`FrameReader` is the generic way to read one. That is plumbing, not a pass.
The rule that carries the weight is the one above — a compositor that knows
what depth is has stopped being a compositor.

**And nothing outside `core/ffmpeg_tools.py` touches a subprocess.** Not the
frame pipes, not their closing or reaping. The reason is swappability rather
than tidiness: this tool may end up inside something larger that does not use
ffmpeg, and then that module is the one seam to replace. `media/` builds
arguments and handles bytes; `grep -r Popen src/media/` returns nothing, and
that is the check.

**A consequence worth stating**, because it decided where two things live: a
constant that is part of a data contract rather than a setting lives in
`models.py`, since `config.py` imports `models.py` and not the other way
round. `LANDMARK_COUNT` is the example. And the sidecar model, which has to
reference the run settings, lives in `core/sidecar.py` for the same reason.

---

## Key terms

- `frame` — integer frame index, 0 at the first frame of the source
- **`plate`** — **the original footage.** Used in its ordinary sense. An
  earlier draft of this document used it for "the picture the mesh is drawn
  on", which was wrong and is gone: in a layer model that thing does not exist
- `pass` — one generator: depth, faces, later segmentation. Owns its settings,
  its processing, its cache and its preview
- `layer` — what a pass produces, as a picture the stack can composite
- `stack` — the ordered list of layers. Index 0 at the bottom
- `seed` — a box drawn on a chosen frame, from which tracking runs
- `face` — one selected person: a label and a list of seeds
- `segment` — the run of frames one seed is responsible for
- `window` — the `near`/`far` pair mapped onto the output's 0–1
- `output` — a delivered video, exactly as long as the source. The composite,
  or any single pass
- `proxy` — the small numbered copy the browser plays
- `mezzanine` — the all-intra copy, for exact random access
- `work dir` — `.performance-work/`, where the mezzanine, proxy and every
  pass's cache live

---

## Open questions

Decided before the task they affect, not now.

1. **Output resolution above 1080p.** Fal returns depth at 1080p at most.
   Either the output is written at the depth's resolution, or the depth is
   scaled up. Seedance takes 1080p either way. *Affects Phase 4.*
2. **Default colour map.** Grayscale, or a colour map. Genjutsu sent Seedance
   coloured depth. Cheap to try both now that the map is the last step.
   *Affects Phase 4.*
3. **Default depth model.** VDA-Small is Apache-2.0; Base and Large are
   CC-BY-NC-4.0, non-commercial only. Large looks better and is Fal's default,
   which is why the parameter is always sent explicitly. Needs a ruling for
   work use. *Affects Phase 4.*
4. **Uploading work footage to Fal.** Whether it is allowed, and for which
   material. *Affects Phase 4.*
5. **The stored depth format.** FFV1 `gray16le` is lossless and a few GB for a
   long shot; x265 10-bit mono is a few hundred MB with an error far below
   anything a window will reveal; a 16-bit PNG or half-float EXR sequence is
   the most VFX-native and the most files. Decided by measuring one real shot.
   *Affects Phase 4.*
6. **Intel Macs.** MediaPipe 1.1.0 ships wheels for Apple Silicon macOS, not
   Intel. *Affects Phase 1, outstanding.*
