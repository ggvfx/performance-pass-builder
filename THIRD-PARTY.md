# Third-party notices

No third-party code, model or media is included in this repository yet. This
file records what the design depends on and under what terms, so the question
is answered before anything is added rather than after.

## Models

| Model | Licence | How it is used |
|---|---|---|
| Google MediaPipe Face Landmarker | Apache-2.0 | Downloaded on first use from Google's model storage. Not committed |
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

The idea of drawing a MediaPipe face mesh over depth as guidance for Seedance,
and the starting mesh colours, come from
[Genjutsu Open Source Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow)
by Sirio Berati, MIT licensed. No code from it is included. If any is, its
copyright notice goes here with it.

## Python dependencies

Listed in `requirements.txt` once Phase 1 pins them. Each keeps its own licence.
