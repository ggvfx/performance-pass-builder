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

**Status: planning.** No code exists yet. ARCHITECTURE.md holds the agreed
shape and TODO.md the order it gets built in.

**One utility now, more later.** The performance pass is the first. Combining
and manipulating depth maps, and other control passes, are expected to follow
as utilities of their own. Each is its own package and its own tab over shared
foundations, the way they would be added to any app built like this one. None
of them is designed yet, and nothing in v1 is built speculatively for them.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.11+, FastAPI | Plain blocking routes until a measurement says otherwise |
| Frontend | Plain HTML + CSS + vanilla JS | ES modules, no npm, no build step |
| Serving | FastAPI static files on localhost | User opens it in their own browser |
| Media | ffmpeg / ffprobe as subprocesses | Frames streamed through pipes, never a Python binding |
| Face tracking | Google MediaPipe Face Landmarker | Local, CPU, a few MB of model |
| Depth (hosted) | Video Depth Anything on Fal | `fal-ai/depth-anything-video`, the default |
| Depth (local) | Video Depth Anything, PyTorch | Optional, for machines with a GPU. Later phase |
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

---

## Pipeline

Two entry points, because a person selects the faces in between.

### `prepare()`

1. **Probe** — ffprobe: exact rational frame rate, frame count, resolution,
   codec, audio streams. Refuse VFR.
2. **Proxy** — all-intra h264, numbered, small enough to scrub.
3. **Depth** — full frame, from the configured backend. Validated against the
   source and cached.

### Select (in the browser)

The person scrubs the proxy, stops on a frame where a face is clear, and draws
a box around it. Repeat for every face wanted, on whichever frame suits each.

### `run()`

4. **Track** — one tracker per selected face, seeded from its box, run forward
   and backward from the frame it was drawn on.
5. **Smooth** — damp landmark jitter, which a generation model would otherwise
   turn into shimmer.
6. **Draw** — each face's mesh over the depth.
7. **Encode** — the pass, with the source audio copied in.
8. **Validate** — frame count, frame rate, duration, audio present. Blocks.
9. **Sidecar** — what was produced, from what, by which versions.

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

Working files live in `.performance-work/` inside it — the proxy, the depth as
downloaded, the result review proxy. The folder is kept until the user clears
it, because the depth in it was paid for.

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

`CODE_STYLE.md` — the shared conventions across repos — is not on this
machine. Until it is, these are carried over from minicut-shot-detector, and
this section is replaced by a pointer once it arrives.

The point of all of it is that the author can open any file months later and
follow it without re-reading the whole project. Readability beats cleverness.

**Process**
- Architecture first, agreed in writing. TODO.md holds the ordered tasks.
- **Pseudocode before implementation.** A new function lands as a signature, a
  real docstring and numbered `# PSEUDOCODE` steps ending in
  `raise NotImplementedError`. The author reads and agrees the plan before it
  becomes code.
- **A skeleton is a plan, not a resident.** If the decision goes the other way,
  delete it and put the reasoning in TODO.md under Deferred.
- One task at a time, tested before the next begins.
- **Ask before restructuring.** Moving or renaming modules, adding a package,
  or changing a settled decision is a conversation first.
- Commit at task granularity or finer, with a message saying what changed in
  plain words.

**Layout**
- `main.py` at the repo root is the entry point. Everything else lives under
  `src/<package>/`, imported absolutely: `from src.core.models import Face`.
- Packages group by role, not pipeline order.
- A utility's `pipeline.py` holds stage order and nothing else.
- `src/ui/server.py` is the only module that knows about HTTP to the browser.
- `src/core/ffmpeg_tools.py` is the only module that runs a subprocess.
- `src/backends/transport.py` is the only module that opens a socket to a
  hosted model.

**Modules and functions**
- Every module starts with a docstring: Title Case name, what it does, and why
  it exists where that is not obvious.
- Sections separated by `# --- CAPS ---` banners.
- Data models are Pydantic `BaseModel`. Fields carry a short trailing comment
  when the name does not explain them.
- Docstrings are short, with `Args:` / `Returns:` / `Raises:` when a function
  takes more than one argument. `Notes:` is for the trap a future reader would
  otherwise fall into.
- **Comments explain why, never what.**

**Naming**
- Functions are verb phrases: `track_face`, `draw_mesh`.
- Anything holding a frame number says so: `start_frame`, `seed_frame`.
- No abbreviations beyond the domain's own (`fps`, `tc`, `sha256`).

**Config**
- Every per-run setting and every default lives in `src/core/config.py`.
  A module may hold a tuning constant it alone uses, next to the comment
  explaining the number.
- `core/models.py`, `core/config.py` and `core/utils.py` stay one file each.
  Splitting one is a conversation.

**Repo**
- Lint: `ruff check .` before every commit.
- Tests: `pytest` from the repo root. Test media is generated by ffmpeg in
  `conftest.py`, so no video is ever committed.
- Dev happens on Windows; the app must also run on macOS. `pathlib`
  everywhere, no hardcoded separators, no shell-specific calls.
- Media and output folders are gitignored before the first commit.

---

## Deferred — do not build yet

- **Person masks (SAM)** — depth on the people only, the original picture
  elsewhere. For swapping the actor while keeping the location. The next
  likely addition.
- **Vocal isolation and pitch shifting** — the Genjutsu workflow pitches
  vocals up three semitones before generation. Not needed to prove the pass.
- **Submitting to a generation model** — the tool produces passes. Sending
  them is the artist's choice of platform.
- **Combining and manipulating depth maps, other control passes.**
- **Blendshapes and head pose as curves** — MediaPipe can return both.
- **Freehand face selection** — a box only tells the tracker where to look.
- **Raw float depth export.**
- **Native packaging of any kind.**
