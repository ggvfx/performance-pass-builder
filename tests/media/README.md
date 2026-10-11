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
| `walks_in_and_turns_away.mp4` | 1920x1080, 24/1, 240 frames, h264 + AAC. A figure walks toward camera from a wide shot, turns to look behind her, arrives in a medium shot | **The hard case, and the only one with a real gap.** The baseline finds her on 89 of 240 frames; seeding late and tracking back finds 188. Gap handling, backward recovery, and a face both too small and too turned away to detect |

**`WANTED.md` in this folder is the gathering list** — every clip still
wanted, in priority order, with what each one proves and how to make it. Tier
1 is what Phase 3 needs.

## Adding one

Drop the file in and give it a name that says what it contains rather than
where it came from, like the one above. Add a row to the table with its real
geometry — `ffprobe` or the app's own Inspect will tell you — and a fixture in
`tests/conftest.py` that skips when it is absent.
