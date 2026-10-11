# Third-party notices

No third-party code, model or media is included in this repository yet. This
file records what the design depends on and under what terms, so the question
is answered before anything is added rather than after.

## Models

| Model | Licence | How it is used |
|---|---|---|
| Google MediaPipe Face Landmarker | Apache-2.0 | `face_landmarker.task`, float16 v1, 3.6 MB. Downloaded on first use from Google's model storage into the gitignored `models/`, and checked against a SHA-256 pinned in `src/core/models.py`. Not committed |
| Video Depth Anything — Small | Apache-2.0 | Hosted on Fal, or locally in a later phase |
| Video Depth Anything — Base, Large | CC-BY-NC-4.0 | **Non-commercial only.** Offered only once that is ruled on for the use in hand |

Source for the Video Depth Anything licences: the
[project README](https://github.com/DepthAnything/Video-Depth-Anything).

## Services

Hosted depth runs on [Fal](https://fal.ai) under Fal's own terms, with the
user's own key. Footage sent for hosted depth leaves the machine.

## Tools

ffmpeg and ffprobe are external executables, installed by the user and run as
subprocesses. They are not redistributed here. Their licence depends on how
the installed build was configured.

## Prior work

The foundations of this app are ported from
**[minicut-shot-detector](https://github.com/ggvfx/minicut-shot-detector)**,
also by this author and also MIT: the ffmpeg toolchain, the timecode engine,
the source probe, the all-intra mezzanine, the numbered review proxy, the
three-state dependency panel, the server-side path picker and the
frame-accurate browser player. Ported at commit `6dcbd60`, trimmed to what this
project uses and modernised for Python 3.12. Each ported module names its
origin in its own docstring.

The idea of drawing a MediaPipe face mesh over depth as guidance for Seedance,
and the starting mesh colours, come from
[Genjutsu Open Source Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow)
by Sirio Berati, MIT licensed. No code from it is included. If any is, its
copyright notice goes here with it.

## Python dependencies

Pinned exactly in `requirements.txt`. Each keeps its own licence.
