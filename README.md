# Performance Pass Builder

**Turns live-action footage into a performance pass** — depth with a face mesh
drawn over each face you choose, and the original audio — for handing to a
video generation model such as Seedance 2.5 as reference video, to replace the
actor and the background while keeping the performance.

## Project Status

🚦 **Planning.** The app shell runs; nothing else is built. Most of the
foundation is being ported from
[minicut-shot-detector](https://github.com/ggvfx/minicut-shot-detector) rather
than rewritten — see [PORTING.md](PORTING.md).

**Works now:** the server starts, the page opens with its two tabs, static
files are served so the browser always picks up changes.

**Next milestone:** Phase 1 — the app reports what is installed and lets you
choose a file.

Design in [ARCHITECTURE.md](ARCHITECTURE.md), settled decisions in
[CLAUDE.md](CLAUDE.md), task order in [TODO.md](TODO.md).

## Install & Run

Requires **Python 3.12+** and **ffmpeg** on the `PATH`. No npm, no build step.

```bash
git clone https://github.com/ggvfx/performance-pass-builder.git
cd performance-pass-builder

python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS

pip install -r requirements.txt
python main.py
```

It opens `http://127.0.0.1:8766` in your browser. The server binds to loopback
only, deliberately: the path picker lists this machine's filesystem.

A one-time `setup.bat` / `setup.command` arrives at the end of Phase 1, once
there is an app for it to hand over to.

## Strategic Roadmap

| Phase | What | State |
|---|---|---|
| 0 | Documents — design agreed in writing | ✅ Complete |
| 1 | Scaffold: shared models, ffmpeg toolchain, dependency panel, path picker | 🔧 Current |
| 2 | Frames in, frames out — a pass of exactly the source's length, with its audio | Planned |
| 3 | Face tracking — several faces, several seeds each, smoothing, the mesh | Planned |
| 4 | Depth on Fal — raw float depth, stored, windowed, colormapped | Planned |
| 5 | The Performance tab — selection, depth controls, results | Planned |
| 6 | Local depth, for machines with a GPU | Optional |
| 7 | Depth manipulation — combining and aligning passes | Shape only |

## 🚀 Overview

Depth removes everything that identifies a person and a place — skin, hair,
wardrobe, set — and keeps shape, staging and motion. It is too coarse to carry
an expression, so the face mesh puts that back. Together they let a generation
model replace everything visible while the performance underneath stays the
actor's.

Getting usable facial tracking for this has meant reaching for a game engine.
This is meant to be a small tool an artist can run.

The workflow is four steps:

1. **Choose a source.** Typed or browsed to; nothing is uploaded until you ask
   for hosted depth, and the page says so before it happens.
2. **Prepare.** The source is inspected, copied to an all-intra mezzanine so
   every seek is exact, given a small numbered proxy for review, and sent for
   full-frame depth — on Fal by default, or locally on a machine with a GPU.
3. **Select faces.** Scrub to a frame where a face is clear and draw a box
   round it. As many faces as the shot has, and as many boxes per face as its
   track needs — a second box past a turn away from camera picks the track back
   up.
4. **Run.** Each face is tracked on your own machine, its mesh drawn over the
   depth, and the source audio copied in untouched. Every pass is checked to be
   exactly the source's length before it is handed over.

Out of it come the depth pass, the depth-with-meshes pass, the landmarks as
JSON, and a sidecar recording what produced them.

## ✨ Key Features

- **Frame-exact, and provably so.** Integer frame numbers everywhere, frame
  rates as exact rationals — 24000/1001, never 23.976. Variable frame rate
  sources are refused with a reason rather than quietly drifting. Every
  deliverable is validated against the source by frame hash before it is
  handed over, and a failure blocks the job instead of warning and continuing.
- **Depth you can position.** Depth arrives as a float field and is stored as
  one, so you can put the 0–1 range over just the part of the shot you care
  about — the midground figures rather than everything from the lens to the
  horizon — and get the whole output range spent on them. Windowing 8-bit
  depth leaves about 25 levels and terraces on a face; this leaves thousands.
- **Paid for once.** Hosted depth is cached against the source and its
  settings. Changing the window, the colour map or the mesh style re-renders
  locally and instantly, and never calls the model again.
- **Tracks you can fix.** One tracker per face, so two people in frame are
  never confused for each other. Where a track breaks — a profile, a wipe —
  you add another box past the break instead of starting over. A frame where a
  face was not found is recorded, not guessed.
- **The audio is the recording.** Stream-copied into the pass, never decoded
  and re-encoded, so lip sync in the generation is driven by exactly what was
  captured.
- **Review against burned-in frame numbers.** Browsers seek long-GOP video
  approximately, so the proxy is all-intra with each frame's number in the
  corner — the frame you selected on is a frame you can see. The number never
  reaches a deliverable.
- **Nothing leaves the machine by accident.** Footage is uploaded only for a
  hosted pass you chose, and the page tells you before it happens. Keys are
  read from the environment at the moment of the call and never stored.

## 🛠️ Technical Stack

* **Language:** Python 3.12+
* **Backend:** FastAPI, Uvicorn, Pydantic
* **Frontend:** Plain HTML, CSS and vanilla JavaScript ES modules — no build step
* **Media:** ffmpeg / ffprobe as subprocesses, frames through pipes
* **Face tracking:** Google MediaPipe Face Landmarker, local, on the CPU
* **Depth:** Video Depth Anything, hosted on Fal, or locally as an option
* **Drawing:** OpenCV, for lines on frames only
* **Foundations:** ported from
  [minicut-shot-detector](https://github.com/ggvfx/minicut-shot-detector) —
  the ffmpeg toolchain, timecode engine, probe, mezzanine, proxy, dependency
  panel, path picker and frame-accurate player

## 📂 Project Structure

```
performance-pass-builder/
├── main.py             Entry point — starts the server, opens the browser
├── src/core/           Shared foundation: config, models, ffmpeg, timecode, sidecar
├── src/media/          Probing, frame streaming, mezzanine, proxy, encoding
├── src/backends/       Depth adapters — Fal now, local later
├── src/performance/    The pass: depth, selection, tracking, smoothing, plate, mesh
├── src/ui/             The app, its routes, and the front end
└── tests/              pytest, with test media generated by ffmpeg
```

## Development Approach

* **Architecture first.** Data flow, module boundaries and settled decisions
  are agreed in writing before implementation — see
  [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md).
* **Reuse before rewrite.** What another of these tools already does well is
  ported in, trimmed to what this one needs — see [PORTING.md](PORTING.md).
* **Skeletons before code.** Modules land as signatures, docstrings and
  pseudocode, reviewed before they are implemented.
* **One task at a time.** Each is built, tested and reviewed before the next,
  and committed separately.

Conventions shared across these repos live in `CODE_STYLE.md`; what is specific
to this one is in [CLAUDE.md](CLAUDE.md).

## Licence

MIT — see [LICENSE](LICENSE). Third-party models, services and prior work are
credited in [THIRD-PARTY.md](THIRD-PARTY.md).
