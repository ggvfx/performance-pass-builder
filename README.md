# Performance Pass Builder

**Turns live-action footage into a performance pass** — depth with a face mesh
drawn over each face you choose, and the original audio — for handing to a
video generation model such as Seedance 2.5 as reference video, to replace the
actor and the background while keeping the performance.

## Project Status

🚦 **Phase 2 complete.** A source goes in and an output of exactly its length
comes out with its audio, composited from layers and checked by the validator
rather than by eye. Nothing is tracked or generated yet — that is Phase 3.
Most of the foundation is ported from
[minicut-shot-detector](https://github.com/ggvfx/minicut-shot-detector) rather
than rewritten — see [PORTING.md](PORTING.md).

**Works now:** the app reports what it needs in three states with a copyable
fix for each, browses this machine for a source, and lays out the whole
workflow with every unbuilt control dimmed.

Underneath, the whole of Phase 2: a source probed to an exact rational frame
rate with variable frame rate refused and a reason given, copied to an
all-intra mezzanine verified frame for frame, given a numbered review proxy,
streamed frame by frame through ffmpeg pipes, composited from a stack of
layers with straight alpha, and written back at exactly its original length
with its audio carried untouched — or deliberately left out, which is checked
rather than assumed. Every deliverable is validated against its source and
recorded in a sidecar, whether it passed or failed. 305 tests.

All of it proven against clips ffmpeg generates. Whether it is right on real
footage is a deliberate checkpoint later, because some of it only a person
can see.

**Next milestone:** Phase 3 — face tracking.

Design in [ARCHITECTURE.md](ARCHITECTURE.md), settled decisions in
[CLAUDE.md](CLAUDE.md), task order in [TODO.md](TODO.md).

## Install & Run

Requires **Python 3.12+** and **ffmpeg** on the `PATH`. No npm, no build step.

**The short way:** run `setup.bat` on Windows or `setup.command` on a Mac. It
finds a supported Python, builds the venv, installs the requirements and
starts the app. Safe to run twice.

*`setup.command` has not been run on a Mac yet — there is no Mac here to try
it on, and saying so is more use than claiming it works.*

**Or by hand:**

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

## Strategic Roadmap

| Phase | What | State |
|---|---|---|
| 0 | Documents — design agreed in writing | ✅ Complete |
| 1 | Scaffold: shared models, the UI shell, ffmpeg toolchain, dependency panel, path picker | ✅ Complete |
| 2 | Frames in, frames out — an output of exactly the source's length, with its audio | ✅ Complete |
| 3 | Face tracking — several faces, several seeds each, smoothing, the mesh | 🔧 Current |
| 4 | Depth on Fal — raw float depth, stored, windowed, colormapped | Planned |
| 5 | The workflow — a step per pass, then the composite | Planned |
| 6 | Local depth, for machines with a GPU | Optional |
| 7 | Depth editing — combining and aligning passes | Shape only |

## 🚀 Overview

Depth removes everything that identifies a person and a place — skin, hair,
wardrobe, set — and keeps shape, staging and motion. It is too coarse to carry
an expression, so the face mesh puts that back. Together they let a generation
model replace everything visible while the performance underneath stays the
actor's.

Getting usable facial tracking for this has meant reaching for a game engine.
This is meant to be a small tool an artist can run.

**It is a compositing app, not a pipeline with one button at the end.** A
source is prepared once; each pass is run when you want it; a stack combines
whichever ones you turned on. You work through four steps, using only the ones
you need:

1. **Source.** Typed or browsed to; nothing is uploaded until you ask for
   hosted depth, and the page says so before it happens. Prepared once into an
   all-intra copy, so every later seek is exact, plus a small numbered proxy.
2. **Depth.** Settings, then process. The result plays in place, and
   underneath you can position the 0–1 range over the part of the shot that
   matters and change the colour map — locally, instantly, and without ever
   calling the model again.
3. **Faces.** Draw a box round a face on the proxy and label it. As many faces
   as the shot has, and as many boxes per face as its track needs — a second
   box past a turn away from camera picks the track back up. The mesh renders
   to its own layer.
4. **Composite.** Order the layers, switch off anything you do not want, and
   output. Outputting one pass on its own is the same thing with one layer
   enabled.

Out of it come whatever you asked for — the composite, any single pass, the
landmarks as JSON, and a sidecar recording what produced them.

Segmentation and other control passes are not built, but they arrive as new
passes feeding the same stack rather than as changes to any of the above.

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
- **Passes stay separate.** Depth and the face mesh are independent layers, so
  re-rendering a mesh never re-tracks a face, changing a window never re-runs
  depth, and any pass can be delivered on its own.
- **The audio is the recording.** Stream-copied into the pass, never decoded
  and re-encoded, so lip sync in the generation is driven by exactly what was
  captured — or left out entirely if you ask, which is verified rather than
  assumed. Nothing is ever trimmed to make two lengths agree.
- **Formats that open where they are going.** mp4 for generation software and
  compositors — h265 by default, h264 for anything that will not take it. The
  face mesh exported on its own keeps its transparency, as a lossless
  QuickTime RLE `.mov` or a PNG sequence, because no mp4 codec carries alpha
  in a form a compositor reliably opens.
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
├── src/performance/    The passes: depth, selection, tracking, smoothing, mesh
├── src/composite/      The layer stack, which knows nothing about what made a layer
├── src/ui/             The app, its routes, and the front end
└── tests/              pytest, media generated by ffmpeg; real footage in tests/media/, never committed
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
