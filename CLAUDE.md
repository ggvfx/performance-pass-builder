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

**Status: Phase 1, nearly done.** The app runs, reports what it needs in three
states with a copyable fix for each, and lets you choose a source. Nothing
reads a frame yet. ARCHITECTURE.md holds the agreed shape and TODO.md the
order it gets built in.

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

3. **The source audio is carried through untouched.** Stream-copied into the
   pass, not decoded and re-encoded, so lip sync in the generation is driven by
   exactly what was recorded. Where the source's audio codec cannot live in the
   pass container, it is encoded once at a high bitrate and the sidecar says
   so. No separation, no pitch shifting — see Deferred.

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

13. **The plate seam.** Whatever produces the picture the mesh is drawn on is a
    separate stage from the drawing. Today it is window-then-colormap; later it
    is a composite of depth, plate and flat regions. `mesh.py` and `encode.py`
    consume a frame of picture and never learn what made it. This is the one
    thing v1 builds for a feature it does not have, because retrofitting it
    means touching drawing, encoding and validation at once.

14. **Three of Fal's parameters are silent traps, and the code treats them as
    such.** `model` is **always sent explicitly** — Fal defaults to `VDA-Large`,
    which is CC-BY-NC-4.0, so omitting it quietly picks the licence-restricted
    model. `output_fps` is **never sent** — it is a float, and Fal matches the
    input when it is absent. `side_by_side` is **never set** — it doubles the
    picture width.

---

## Pipeline

Two entry points, because a person selects the faces in between.

### `prepare()`

1. **Probe** — ffprobe: exact rational frame rate, frame count, resolution,
   codec, audio streams. Refuse VFR.
2. **Mezzanine** — all-intra, verified frame for frame against the source.
   Here for exact random access, not for stream copying: re-seeding a track
   means arbitrary seeks, and long-GOP h264 gives you fast-and-wrong or
   exact-and-slow.
3. **Proxy** — all-intra h264, numbered, small enough to scrub, built from the
   mezzanine.
4. **Depth** — full frame, from the configured backend. Validated against the
   source, converted to the stored scalar format, and cached.

### Select (in the browser)

The person scrubs the proxy, stops on a frame where a face is clear, and draws
a box around it. Repeat for every face wanted, on whichever frame suits each —
and **again on the same face wherever its track needs re-seeding**, past a turn
away from camera or a wipe. A face is a label and a list of seeds.

### `run()`

5. **Track** — one tracker per selected face, run in segments between that
   face's seeds: backward from the first to frame 0, forward from each to the
   next. Every frame records which seed produced it, or that it is a gap.
6. **Smooth** — damp landmark jitter, which a generation model would otherwise
   turn into shimmer. Resets across a gap and across a seed boundary.
7. **Plate** — the stored depth, windowed to the range the user chose, then
   colormapped. The picture the mesh goes on.
8. **Draw** — each face's mesh over the plate.
9. **Encode** — the pass, with the source audio copied in.
10. **Validate** — frame count, frame rate, duration, audio present. Blocks.
11. **Sidecar** — what was produced, from what, by which versions.

---

## Output

One folder per job. Deliverables only:

```
<source>_performance/
    <source>_depth.mp4             full-frame depth, source audio
    <source>_depth_mesh.mp4        depth with meshes, source audio — the pass
    <source>_landmarks.json        per face, per frame, normalised
    <source>_performance.json      sidecar
```

Working files live in `.performance-work/` inside it — the mezzanine, the
proxy, the stored depth field, and the result review proxy. The folder is kept
until the user clears it, because the depth in it was paid for. Clearing is
offered with the space it would free, never done behind the user's back.

The `.npz` Fal returns is transport: converted to the stored field on arrival
and deleted. At 1080p it is 8.3 MB a frame, so keeping it is not an option.

---

## Frontend conventions

- One `index.html`, one stylesheet, ES modules loaded natively. `main.js`
  imports the rest and is the only place a listener is attached, so "what
  happens when this is clicked" has one answer.
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
  including the frame pipes
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
- **Vocal isolation and pitch shifting** — the Genjutsu workflow pitches
  vocals up three semitones before generation. Not needed to prove the pass.
- **Submitting to a generation model** — the tool produces passes. Sending
  them is the artist's choice of platform.
- **Blendshapes and head pose as curves** — MediaPipe can return both.
- **Freehand face selection** — a box only tells the tracker where to look,
  and a second box past a break now handles what freehand was wanted for.
- **Native packaging of any kind.**
