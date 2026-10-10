# Decisions taken without review

Calls made while working unattended, newest first. **One or two lines each,
and only the ones worth overturning** — this is meant to be read in a few
minutes, not to be a changelog.

Tick a line once you have read it and are happy. Anything you want changed,
say so and it changes; nothing here is settled by having been done.

Delete this file when the backlog is empty and we are reviewing task by task
again.

---

## Phase 2 — 2.7 to 2.9

### 2.7 — Validator

- [ ] **Frame hashes are not part of `validate()`.** They cost a full decode
      of two files and only answer what metadata cannot — a hosted model
      returning the right length and the wrong picture. `compare_frames` is a
      separate call the depth stage makes on arrival.
- [ ] **A duration failure is only reported when the count and rate both
      passed.** Otherwise it is a second symptom of a fault already named,
      and three failures for one problem is how a report stops being read.
- [ ] **The validator asks what the encoder *claimed* it did with the
      audio**, rather than inferring from the source. That is what lets an
      absent stream be correct for `OMITTED` and a failure for `COPIED`.

## Phase 2 — before 2.6

Agreed in discussion rather than taken unattended, recorded here because
they shape the compositor.

- [x] **Every layer is a file, streamed a frame at a time.** The deciding
      case was an artist who already has passes: if a layer can be something
      they already have, every layer may as well be. Resolves what was
      ARCHITECTURE open question 6.
- [x] **Straight alpha, not premultiplied.** Premultiplied is the cheaper
      composite and what drawing on black naturally produces, but PNG and
      QuickTime RLE conventionally carry straight — so premultiplied data in
      a straight file means dark fringes in any compositor that believes the
      label.
- [x] **A real integration checkpoint after Phase 4**, rather than trusting
      stand-in clips. TODO 4.11 to 4.13.

---

## Status: all reviewed, 2026-10-10

Every decision below has been read and agreed, three of them changed in the
process. The backlog is empty; this file stays only until the one open
**task** below is done, and for anything taken unattended after it.

**Outstanding, and it is a check rather than a choice:** confirm Nuke reads
`qtrle` alpha cleanly. Test files are in `D:\_repos\_scratch` —
`alpha_test_qtrle.mov` and `alpha_test_prores4444.mov`, same content. A PNG
sequence is now available either way, so this only decides whether the
one-file option stays useful.

---

## Phase 2

### 2.5b — Output formats (from your two notes)

- [x] **Nothing is ever trimmed; the video length is the length.** Now
      non-negotiable 2 rather than only a comment in the encoder. `-shortest`
      is never passed, and no stage pads or clips.
- [x] **Three output formats, not four. h265 is the default.** ProRes 4444
      removed as unused — re-adding it is an enum member and three constants,
      and it would be the right call for a *photographic* layer with alpha if
      segmentation ever produces one. The artist sees an h264/h265 choice;
      ALPHA_RLE is selected by the app for the one export that needs it.
      *Agreed 2026-10-10.*
- [x] **The default alpha format is QuickTime RLE, not ProRes** — and this
      reversed my first answer. Measured on 48 frames of mesh-like content at
      1080p: ProRes 4444 24.3 MB, RLE 0.5 MB, and the RLE one is lossless. A
      mesh is line art over nothing, which is the worst case for a DCT codec
      and the best for run-length encoding. ProRes was also storing 12-bit
      precision that does not exist, since OpenCV draws in 8-bit.
      **ProRes stays available**, and would be the right choice for a layer
      carrying photographic content — a segmented region of the plate — where
      RLE would balloon instead.

      *Agreed 2026-10-10, and ProRes then dropped entirely as unused. A PNG
      sequence was added alongside RLE at the same review: it is what you
      mostly use in Nuke, it is unambiguously lossless, and it sidesteps the
      qtrle question below.*
      **Still to confirm: that Nuke reads qtrle alpha cleanly.** Test files
      are in `D:\_repos\_scratch` — `alpha_test_qtrle.mov` and
      `alpha_test_prores4444.mov`, same content. If Nuke is awkward with the
      RLE one, a PNG or EXR sequence is the fallback: lossless, unambiguous
      alpha, more files.
- [x] **Alpha cannot be mp4.** You asked for mp4 where possible and it is,
      for everything except this: neither h264 nor h265 carries alpha in a
      form a compositor can be relied on to open. VP9-in-webm can and is
      tiny, but After Effects will not take it natively.

### 2.5 — Audio

- [x] **Audio is muxed in the same ffmpeg pass as the picture**, as a second
      input, rather than written video-first and muxed after. One pass instead
      of writing the video twice. Cost: `-map 0:v:0` must be explicit, because
      with two inputs ffmpeg could otherwise pick the *source's* picture and
      silently deliver the original footage. There is a test for exactly that.
      *Agreed 2026-10-10, and gathered with every other audio caveat into one
      section of ARCHITECTURE.md.*
- [x] **`-shortest` is deliberately not used.** It would trim the picture to
      the audio, and a pass that is not exactly the source's length is the one
      thing this project will not deliver. If the two disagree, the validator
      at 2.7 is where it surfaces — loudly.
- [x] **`AudioHandling` is recorded, not inferred**: copied, encoded, omitted,
      or none. Three of those produce files that look identical, so the
      sidecar is the only place the difference survives. *Agreed 2026-10-10;
      written up in ARCHITECTURE.md's audio section.*
- [x] **The fallback is aac at 320k**, kept — but it is now stated plainly as
      **the only lossy step applied to audio anywhere in the app**, in config,
      in the probe's warning, and in non-negotiable 3. *Agreed 2026-10-10.*
- [x] **`FrameWriter.arguments()` was made overridable** so `OutputWriter`
      could add an audio input without reimplementing the pipe handling.
      Alternative was a separate class duplicating about sixty lines of
      process management.

      *Revisited 2026-10-10 and resolved better than either option: the sixty
      lines were not FrameWriter's to own at all. The whole process lifecycle
      moved to `ffmpeg_tools` as `FFmpegReadPipe` and `FFmpegWritePipe`, so
      the two writers now share it by holding a pipe rather than by
      inheritance. The remaining subclass is thin — argument building only —
      and the class of bug that already bit once (inheriting attributes and
      silently ignoring them) has nothing left to inherit.*

### 2.4 — Frame streaming

- [x] **Pipes, and their whole lifecycle, live in `ffmpeg_tools.py`.**

      *Agreed 2026-10-10, with a better reason than the one I gave. I argued
      it from the stated rule and from having one place to log; you argued it
      from swappability — this tool may end up inside something larger that
      does not use ffmpeg, and then this module is the single seam to
      replace. That reasoning also showed the job was half done: starting the
      process lived here, but closing, killing, reaping and reading ffmpeg's
      error did not. It all does now, and `media/` never sees a `Popen`.*
- [x] **The pipeline is 8-bit, and that is deliberate.** Depth is stored at
      16-bit and windowed *before* frames enter the pipe, so the precision is
      spent where it matters. 8-bit is what h264 and h265 deliver anyway.
      `PixelFormat` now carries its sample type rather than assuming uint8, so
      a 10- or 16-bit output later is a format added rather than a rewrite.
      Nothing wants it yet — Seedance reads a depth pass as a greyscale
      picture. *Agreed 2026-10-10.*
- [x] **A short read ends the stream rather than raising.** ffmpeg closing the
      pipe is how a decode finishes normally. A *partial* frame does raise,
      because that is a truncated read rather than an end.
- [x] **The validator owns the frame-count check, not the reader.** One
      owner; the validator already compares every other property against the
      source. *Agreed 2026-10-10.*

---

## How to read this

Each entry says what was decided and what the alternative was, because the
alternative is the part that makes a decision reviewable. Where something was
deferred rather than decided, it says so and names the task that will decide
it.
