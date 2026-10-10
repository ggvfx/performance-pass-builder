# Performance Pass Builder

**Performance Pass Builder** turns live-action footage into a performance
pass: full-frame depth with a face mesh drawn over each selected face, and the
original audio. Hand it to a video generation model such as Seedance 2.5 as
reference video to replace the actor and the background while keeping the
performance.

## Project Status
🚦 **Planning.** The design is written down and no code exists yet. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the shape and [TODO.md](TODO.md) for
the order it gets built in.

## What it will do

1. **Choose a source.** Typed or browsed to; nothing is uploaded until you ask
   for hosted depth.
2. **Prepare.** The source is inspected, a small numbered copy is made for
   review, and full-frame depth is generated — on Fal by default, or locally on
   a machine with a GPU.
3. **Select faces.** Scrub to a frame where a face is clear and draw a box
   round it. As many faces as the shot has.
4. **Run.** Each face is tracked through the shot on your own machine, its mesh
   drawn over the depth, and the source audio copied in untouched. Every pass is
   checked to be exactly the source's length before it is handed over.

Out of it come the depth pass, the depth-with-meshes pass, the landmarks as
JSON, and a sidecar recording what produced them.

## Why

Depth removes what identifies a person and a place — skin, hair, wardrobe,
set — and keeps shape, staging and motion. It is too coarse to carry an
expression, so the face mesh puts that back. Together they let a generation
model replace everything visible while the performance underneath stays the
actor's.

Getting usable facial tracking has meant reaching for a game engine. This is
meant to be a small tool an artist can run.

## Development Approach

* **Architecture first.** Data flow, module boundaries and settled decisions
  are agreed in writing before implementation — see
  [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md).
* **Skeletons before code.** Modules land as signatures, docstrings and
  pseudocode, reviewed before they are implemented.
* **One task at a time.** Each is built, tested and reviewed before the next,
  and committed separately.

## Planned Stack
* **Language:** Python 3.11+
* **Backend:** FastAPI, Uvicorn, Pydantic
* **Frontend:** Plain HTML, CSS and vanilla JavaScript ES modules — no build step
* **Media:** ffmpeg / ffprobe as subprocesses
* **Face tracking:** Google MediaPipe Face Landmarker, local, on the CPU
* **Depth:** Video Depth Anything, hosted on Fal, or locally as an option


## Licence
MIT — see [LICENSE](LICENSE).
