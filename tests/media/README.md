# Test footage

Clips with **real faces in them**, used by the face-tracking tests.

Nothing in this folder is committed except this file. The clips are large,
footage is often a client's, and this repository is public — so `.gitignore`
excludes everything here by name.

Which means: **a fresh clone has no footage, and the tests that need it skip.**
That is deliberate rather than broken. The suite still runs, and the skip
message names the file it wanted.

## Why generated clips are not enough

Every other test clip is made on the fly by ffmpeg — colour bars, counters,
flat greys — with an exact frame count and rate, so tests assert real numbers
instead of "about right". See `tests/conftest.py`.

MediaPipe will not find a landmark in any of them. A face tracker can only be
tested against a face, so these few clips are the exception.

## What belongs here

| File | What it is | What it exercises |
|------|-----------|-------------------|
| `one_face_medium.mp4` | 1920x1080, 24/1, 240 frames, h264 + AAC. One person, medium close-up, frontal, evenly lit, near-static camera with a slight push in | The ordinary case. Detection, a single track running the length of the shot, landmarks that stay put |

Still wanted, roughly in order of how much they would tell us:

- **Two faces crossing** — which track is which when they overlap and separate
- **A face leaving frame and returning** — whether the same person keeps their
  track, or silently becomes a second one
- **A profile turn** — where landmarks degrade, and whether that is reported
  or just quietly wrong
- **A moving camera** — handheld or a dolly, so tracking is not only ever
  tested against a locked-off frame
- **A small face in a wide shot** — the resolution floor, where detection
  starts failing

## Adding one

Drop the file in and give it a name that says what it contains rather than
where it came from, like the one above. Add a row to the table with its real
geometry — `ffprobe` or the app's own Inspect will tell you — and a fixture in
`tests/conftest.py` that skips when it is absent.
