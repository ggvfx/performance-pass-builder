# Performance Pass Builder

A local web app that turns a piece of live-action footage into a **performance
pass**: a full-frame depth video with a face mesh drawn over every selected
face, carrying the source's original audio. An artist hands that pass to a
video generation model — Seedance 2.5 is the first target — as reference
video, to replace the actor and the background while keeping the performance.

Depth removes everything that identifies the person and the place: skin, hair,
wardrobe, set. What is left is shape, staging and motion. The face mesh puts
back the one thing depth is too coarse to carry — expression and lip shape —
so the generated performance follows the original one.

**Status: Phase 3 next; Phase 2 complete.** The app runs, reports what it needs in three
states with a copyable fix for each, and lets you choose a source. Underneath, the
whole of Phase 2 is built and tested on real encodes: probe, timecode,
mezzanine, proxy, frame pipes, audio, compositor, validator, sidecar and
working folder. Nothing is tracked or generated yet.
ARCHITECTURE.md holds the agreed shape and TODO.md the order it gets built in.

**Most of the foundation is already written, in another repo.** Probing,
timecode, the mezzanine, the numbered proxy, the three-state dependency panel,
the path picker and the frame-accurate browser player all exist in
`D:\_repos\minicut-shot-detector` and are **ported in, trimmed and modernised
rather than rebuilt** — roughly 2,200 lines of proven Python and 1,700 of front
end. PORTING.md holds the inventory, what is deliberately left behind, and the
rules for bringing a module across. **Read it before writing any module that
appears in it.** That file is deleted once the port is done; the provenance
lines in the module docstrings are what remain.

**One utility now, more later.** The performance pass is the first. Combining
and manipulating depth maps, and other control passes, are expected to follow
as utilities of their own — `src/depth/` is named in ARCHITECTURE.md as their
home. Each is its own package and its own tab over shared foundations, the way
they would be added to any app built like this one. None of them is designed
yet, and the only thing v1 builds for them is the plate seam, which costs a
function signature and is listed as a non-negotiable below.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12+, FastAPI | Plain blocking routes until a measurement says otherwise |
| Frontend | Plain HTML + CSS + vanilla JS | ES modules, no npm, no build step |
| Serving | FastAPI static files on localhost | User opens it in their own browser |
| Media | ffmpeg / ffprobe as subprocesses | Frames streamed through pipes, never a Python binding |
| Output | mp4 — h265 by default, h264 where needed | What generation software and compositors open |
| Output (alpha) | QuickTime RLE `.mov`, or a PNG sequence | Only for the face mesh exported alone. No mp4 codec carries alpha; a sequence is what a compositor reads most happily |
| Face tracking | Google MediaPipe Face Landmarker | Local, CPU, a few MB of model |
| Depth (hosted) | Video Depth Anything on Fal | `fal-ai/depth-anything-video`, the default |
| Depth (local) | Video Depth Anything, PyTorch | Optional, for machines with a GPU. Later phase. Also the only way to get float depth without a multi-gigabyte download |
| Depth (stored) | 16-bit single channel | Scalar field, not a picture. The `.npz` Fal returns is transport and is deleted |
| Drawing | OpenCV | Lines on frames only. Never used to read or write video |

### Why there is no native app

Same reasoning as every tool built this way: no Electron, no Tauri, no
PyInstaller, no code signing. Distribution is a folder plus a one-time
`setup.bat` / `setup.command` that creates a venv and installs pinned deps.
A PyTorch-and-CUDA bundle in particular would run to several GB and trip
antivirus scanners.

---

## Non-negotiables

Settled decisions. Do not revisit them without asking.

1. **Integer frame numbers everywhere; frame rates as exact rationals.**
   24000/1001, never 23.976. Variable frame rate sources are detected and
   refused with a clear message, because every pass has to line up with the
   source frame for frame.

2. **A pass matches its source frame for frame.** Same frame count, same frame
   rate, same duration. A pass that does not is a pass a generation model will
   drift against, and it fails the job rather than being delivered. This
   includes the depth that comes back from a hosted model: it is checked on
   arrival, never trusted.

   **The video length is the length, and nothing is ever trimmed to fit it.**
   Not the audio, not a supplied depth pass, not anything. Where something
   does not match, the job says so and stops — `-shortest` is never passed to
   ffmpeg, and no stage silently pads or clips. A trim is the app deciding
   that its own convenience outweighs the artist knowing something was wrong,
   and the whole point of the validator is that nothing gets to make that
   trade quietly.

3. **When audio is carried, it is carried untouched.** Stream-copied into the
   output, not decoded and re-encoded, so lip sync in the generation is driven
   by exactly what was recorded. Where the source's codec cannot live in the
   container, it is encoded once as AAC 320k and the sidecar says so.

   **That re-encode is the only lossy step applied to audio anywhere in the
   app**, and it is announced three times on purpose — by the probe before
   the job, by the warning on the page, and by the sidecar afterwards.
   Silently degrading someone's production audio is not a thing to be
   discreet about. No separation, no pitch shifting — see Deferred.

   **Whether to carry it is the artist's choice**, defaulting to yes. There are
   real reasons to leave it out: a pass going to a model that ignores it, or
   client audio that should not travel with a file. Discarding is **checked**
   rather than merely skipped — the validator asserts the output has no audio
   stream, because for the privacy case "we did not add it" and "it is not
   there" are different claims.

4. **Hosted is the product. Local is the option.** This is handed to artists
   on Windows and macOS whose machines are nothing like the one it is written
   on. No design decision may assume a local GPU. A Mac with no NVIDIA card and
   a Fal key is a fully supported setup and the Setup tab reports it green.

   **Face tracking is the exception, because it is small.** MediaPipe runs on
   the CPU at about real time on any recent laptop. Sending every frame
   somewhere to get points back that could be computed locally in seconds buys
   nothing.

5. **Footage leaves the machine only for a hosted pass the user chose, and
   the page says so before it happens.** Uploading client footage is a real
   decision. It is never a side effect.

6. **No model file is committed.** The MediaPipe model is downloaded on first
   use into a gitignored cache and checked against a pinned SHA-256. Local
   depth weights are downloaded only when the local backend is chosen, and are
   never required when a hosted one is configured.

7. **Hosted depth is paid for once per source.** It is cached in the working
   folder and reused, so re-tracking faces, re-drawing meshes or changing the
   mesh style never calls the model again.

8. **Review happens against a numbered proxy, never the source.** Browsers seek
   long-GOP video approximately, so a box drawn "on frame 120" could be on 118.
   The proxy is all-intra h264 with each frame's number burned in, so the
   frame a face was selected on is something you can see. **The burned-in
   number never appears in a deliverable.**

9. **Detect, don't ask.** Frame rate, frame count, resolution, audio codec and
   duration are read from the file and shown. The user is never asked to type
   them.

10. **Pinned dependencies.** Exact versions in `requirements.txt`. MediaPipe's
    landmark output and ffmpeg's frame handling both change between releases.

11. **Credentials are never stored.** Settings name the environment variable
    holding a key — `FAL_KEY` — and it is read at the moment of the call.

12. **Depth is stored as a scalar field and shown as a picture, and the two are
    never the same thing.** What is cached is single-channel depth at the best
    precision the backend gave. What the user sees is that field windowed and
    colormapped, derived on demand, locally, in an instant. Colormapping early
    does not merely lose precision — turbo, inferno and magma are not monotonic
    or cheaply invertible, so it destroys the ability to window the range at
    all. Everything upstream of the colormap is single-channel.

13. **Passes produce layers; a stack combines them.** Each pass — depth,
    faces, later segmentation — owns its settings, its processing, its cache
    and its preview, and produces a picture. The compositor orders those
    layers and knows nothing about what made any of them, and no pass knows
    what consumes it. `composite/` may not import `performance/`.

    In v1 a layer is a source and an on/off switch, composited "over", index 0
    at the bottom. Opacity, blend modes and masks fit the same model later and
    are not built now. **Outputting a single pass is the stack with one layer
    enabled** — there is no second export path, which is the main reason the
    stack earns its place in v1.

    **The stack is editable: layers reorder as well as switch off.** That is
    the point rather than a convenience — a segmented depth region over the
    plate is a different picture from the plate over that region, and neither
    is more correct, so the order cannot be something the app decides.

    **The plate and a flat grey card are layer sources like any other.** The
    compositor should not know which layers were generated and which were
    given, and the day a segmented region sits over the plate, the plate has
    to be an ordinary layer rather than a special case underneath everything.
    The mesh is the one layer with alpha, which is what makes "mesh over the
    plate" the way to check a track and "mesh over grey" the way to look at it
    alone.

    An earlier draft called this the plate seam and implemented it as one
    function signature. The stack is the same principle done properly, and it
    is why the mesh renders to its own transparent layer rather than being
    drawn onto depth.

14. **Three of Fal's parameters are silent traps, and the code treats them as
    such.** `model` is **always sent explicitly** — Fal defaults to `VDA-Large`,
    which is CC-BY-NC-4.0, so omitting it quietly picks the licence-restricted
    model. `output_fps` is **never sent** — it is a float, and Fal matches the
    input when it is absent. `side_by_side` is **never set** — it doubles the
    picture width.

---

## How a job goes

Not one pipeline with a button at the end. A source is prepared once, each
pass is run when the artist wants it, and the stack combines whichever ones
they turned on.

### Prepare — shared, and not a pass

1. **Probe** — ffprobe: exact rational frame rate, frame count, resolution,
   codec, audio streams. Refuse VFR, with a reason the page can show.
2. **Mezzanine** — all-intra, verified frame for frame. Here for exact random
   access, which is what makes re-seeding a track usable; long-GOP h264 gives
   you fast-and-wrong or exact-and-slow.
3. **Proxy** — all-intra h264, numbered, small enough to scrub, from the
   mezzanine.

### The depth pass

4. **Generate** — ask the backend, validate against the source on arrival,
   convert to the stored scalar field, cache it.
5. **Edit** — window and colour map, applied when the layer is rendered. Local,
   instant, and never another call.

### The faces pass

6. **Select** — boxes on the proxy. A face is a label and a **list** of seeds;
   re-seeding past a turn away or a wipe is the normal way to work.
7. **Track** — one MediaPipe tracker per face, in segments between that face's
   seeds. Every frame records which seed produced it, or that it is a gap.
8. **Smooth** — damp jitter a generation model would render as shimmer.
   Resets across a gap and across a seed boundary.
9. **Render** — the mesh to **its own transparent layer**, not onto depth, so
   it can be output alone, reordered, or left out without re-tracking.

### Finish

10. **Composite** — the layers that are switched on, in the order the artist
    put them, index 0 at the bottom. The plate and a flat grey card are
    available as sources alongside the passes.
11. **Output** — the composite, or any single pass, with the source audio
    copied in unless it was asked to be left out.
12. **Validate** — frame count, frame rate, duration, audio present. Blocks.
13. **Sidecar** — what was produced, from what, by which versions.

## Output

One folder per job. Whatever the artist asked for, and nothing else:

```
<source>_performance/
    <source>_composite.mp4         the stack as composited — h265 or h264
    <source>_depth.mp4             the depth layer alone, if asked for
    <source>_faces.mov             the face layer alone, alpha intact
    <source>_faces/                or the same as a PNG sequence
        <source>_faces.0000.png
    <source>_landmarks.json        per face, per frame, normalised
    <source>_performance.json      sidecar
```

mp4 for anything going to a generation model, h265 by default. The face layer
is the one exception, because no mp4 codec carries alpha in a form a
compositor reliably opens: QuickTime RLE for one small lossless file, or a
PNG sequence for a compositor that would rather have frames. A sequence is
numbered from 0, matching this app's own frame indices, so frame 40 of a
track is frame 40 of the sequence.

A single-pass output is the stack with one layer enabled, so these come from
one code path rather than an export mode each. Each carries the source audio
unless the artist asked for it to be left out.

Working files live in `.performance-work/` inside it — the mezzanine, the
proxy, the stored depth field, and the result review proxy. The folder is kept
until the user clears it, because the depth in it was paid for. Clearing is
offered with the space it would free, never done behind the user's back.

The `.npz` Fal returns is transport: converted to the stored field on arrival
and deleted. At 1080p it is 8.3 MB a frame, so keeping it is not an option.

---

## Frontend conventions

- One `index.html`, one stylesheet, ES modules loaded natively. `main.js`
  imports the rest and attaches the listener for **every element written in
  the HTML**, so for anything on the page "what happens when this is clicked"
  has one answer. A module that builds elements wires what it builds —
  `picker.js` for its directory rows, `environment.js` for its fix buttons —
  because nothing else can.
- **The front end owns no arithmetic.** A box drawn on the proxy is sent as the
  frame it was drawn on and its corners as fractions of the picture. Pixels,
  frame rates and paths are worked out in Python, where the tests are.
- File paths are typed or chosen through a server-side directory listing.
  **Media is never uploaded through the browser** to a server on the same
  machine.
- Long operations show that work is happening. Whether they also show how far
  along is decided by measuring, not assumed.

---

## Code conventions

`D:\_repos\CODE_STYLE.md` holds the conventions shared across these repos —
layout, dependency direction, classes vs functions, docstrings, the skeleton
phase, testing and linting. Read it before writing code here. What follows is
only what is specific to this project, and overrides CODE_STYLE.md where the
two differ.

**Ownership of the boundaries.** Each of these is the only module allowed to do
its thing, so when that thing misbehaves there is one place to look:

- `src/core/ffmpeg_tools.py` — the only module that runs a subprocess,
  including the frame pipes **and their whole lifecycle**: starting, closing,
  reaping, and turning ffmpeg's last words into an error.

  The reason is swappability, not tidiness. This tool may end up inside
  something larger that does not use ffmpeg, and then this module is the one
  seam to replace — which only holds if nothing else knows what a process is.
  `media/` builds arguments and handles bytes; it never sees a `Popen`.

  The thing to watch: `ffmpeg_tools` must stay ignorant of media. The moment
  a pipe there knows about pixel formats or frame sizes, the rule has been
  obeyed in letter and broken in spirit
- `src/core/timecode.py` — the only place frames become time. Nothing else
  converts, including the thing that looks like it needs one little conversion
- `src/backends/transport.py` — the only module that opens a socket to a
  hosted model
- `src/ui/server.py` — the only module that knows about HTTP to the browser
- `src/performance/plate.py` — the only module that colormaps
- A utility's `pipeline.py` — stage order and nothing else

**Ported modules are modernised on arrival, and say where they came from.**
minicut targets 3.11 and uses `Optional[x]`, `List[x]` and paths as `str`;
this repo is 3.12, so a ported file is converted as it lands — `x | None`,
`list[x]`, `Path` — not afterwards.

The cost is accepted deliberately: a ported file is no longer byte-comparable
with its original, so a fix found in minicut later has to be read across by
hand rather than diffed. That is the trade for one consistent style here, and
it is affordable because this is a one-time lift with no intention of porting
back. What makes it survivable is the provenance line, which every ported
module carries under its docstring summary:

```
Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.
```

That line outlives PORTING.md. If a bug turns up in minicut's `parse_filters`
ffmpeg-8 handling or in `player.js`'s frame-seek arithmetic, it is how a reader
learns this repo has the same code.

**Nothing is ported that the task needing it does not use.** A module arrives
trimmed, and PORTING.md records the trim so what was left behind reads as a
decision rather than an oversight. `core/models.py` in particular is **not**
copied and cut down — this project's is written fresh, taking three shapes from
minicut's as reference.

**A skeleton is a plan, not a resident.** Pseudocode lands first and is agreed
before it becomes code (CODE_STYLE.md §6). If the decision then goes the other
way, the skeleton is deleted and the reasoning goes into TODO.md under
Deferred. An unimplemented module left in place reads as work in progress
rather than as work that was rejected.

**A validator that enforces a stated invariant is written, not skeletoned.**
CODE_STYLE.md section 6 has new functions land as pseudocode ending in
`raise NotImplementedError`, and a validator is a function — but a Pydantic
validator runs every time its model is constructed, so one that raised would
make the model impossible to build anywhere, including in the tests meant to
review the skeleton. Small declarative checks — ordered box corners, unique
seed frames, a derived `passed` — are therefore real code from the start.
Anything with actual logic stays pseudocode.

**Landmarks are the exception to Pydantic everywhere.** Models are Pydantic at
every boundary that is serialised, validated, or crossed between modules — the
selection, the sidecar, the landmarks deliverable. Landmarks in flight are not:
478 points per face per frame is millions of model instances for one job, so a
`FaceTrack` carries a numpy array and the array's shape is a contract stated in
its docstring. Validation happens where the array is built and where it is
written out, not per point.

**Naming.** Beyond CODE_STYLE.md's rules: anything holding a frame number says
so — `start_frame`, `seed_frame`, `frame_count`.

**Tests.** Test media is generated by ffmpeg in `conftest.py`, so no video is
ever committed — this repository is public and footage is often a client's.

**Both platforms.** Development happens on Windows; the app must also run on
macOS. `pathlib` everywhere, no hardcoded separators, no shell-specific calls.
Media and output folders are gitignored before the first commit.

---

## Deferred — do not build yet

Two things that used to be on this list have moved onto the plan, because
Fal's `include_raw_depths` turned out to return float32 `[N,H,W]` with its own
`min_depth` and `max_depth`, which is what makes depth manipulation possible at
all: **raw float depth** is now how depth arrives, and **windowing the depth
range** is a v1 feature. Combining and aligning *several* depth passes is a
later phase in TODO.md rather than a deferral, and `src/depth/` is where it
goes.

Still deferred:

- **Region compositing driven by masks (SAM)** — one area depth, one area the
  original plate, one area flat grey, as a control pass. The reason the plate
  seam exists, and the likeliest thing to be built on it. SAM 2.1 is
  Apache-2.0 and takes box prompts, which fits the selection step already
  planned. **None of it is designed.**
- **Vocal isolation and pitch shifting** — the project notes say the
  Genjutsu workflow pitches vocals up three semitones before generation.
  Unverified, like the mesh colours. Not needed to prove the pass.
- **Submitting to a generation model** — the tool produces passes. Sending
  them is the artist's choice of platform.
- **Blendshapes and head pose as curves** — MediaPipe can return both.
- **Freehand face selection** — a box only tells the tracker where to look,
  and a second box past a break now handles what freehand was wanted for.
- **Native packaging of any kind.**
