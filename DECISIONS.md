# Decisions taken without review

Calls made while working unattended, newest first. **One or two lines each,
and only the ones worth overturning** — this is meant to be read in a few
minutes, not to be a changelog.

Tick a line once you have read it and are happy. `[~]` means deferred —
read, nothing pending, judge it later against something real. Anything you want changed,
say so and it changes; nothing here is settled by having been done.

Delete this file when the backlog is empty and we are reviewing task by task
again.

---

## Phase 3 — 3.3

- [ ] **`FrameReader` can now seek, and a seek is only exact on an all-intra
      file.** `-ss` before `-i` is instant but lands on the nearest keyframe
      at or before the time asked for — exact on the mezzanine, quietly wrong
      on long-GOP h264. It is documented loudly in three places and proven by
      frame hash in a test, but **it is a sharp edge**: a caller that passes
      the original source instead of the mezzanine gets landmarks on the
      wrong frames and nothing downstream can tell. If you would rather it
      refused outright than documented, say so.
- [ ] **Backwards reading buys frames in 256 MB windows.** A decoder only
      runs forwards, so going backwards means holding frames; holding all of
      them is 1.4 GB for ten seconds of 1080p. Windows cap it at about thirty
      1080p frames or seven at 4K, the same ceiling on a two-minute source as
      a two-second one. The cost is one seek per window.
- [ ] **The backward run starts *on* the seed frame, not below it**, so it
      begins from the same known-good detection the forward run did rather
      than guessing at frame `seed - 1`. That frame's result is thrown away.
- [ ] **Which face is chosen: best box overlap on the seed frame, then
      nearest centroid.** Overlap is over the union, so a generous box still
      matches a face but a box round a whole group does not claim one member.
      **Nearest-centroid has no distance limit**, which is 3.3's honest
      limit — two faces that touch can still swap. The padded search region
      that fixes it is 3.4.
- [ ] **A box with no face in it raises `NoFaceInSeed`.** The one tracking
      failure that is the user's to fix rather than the app's, so it is its
      own type with a message about drawing the box again. Everywhere else, a
      frame with no face is recorded as a gap and never raises.

## Phase 3 — 3.1 and 3.2

- [ ] **MediaPipe is imported inside the function, not at module scope.**
      There is no wheel for Intel macOS, and an import error at startup would
      take the server down *before* the dependency panel could render the
      message explaining exactly that. Unusual enough to be worth your eye.
- [ ] **The baseline attributes every tracked frame to seed 0.** It has no
      seeds, but the array contract says `seeded_by` is `NOT_SEEDED` only
      where nothing was found. An implicit "the whole clip" seed keeps the
      contract true, and 3.6 makes the baseline the one-seed case of the real
      thing rather than a second mechanism.
- [ ] **The three confidence thresholds are set in `config.py` to
      MediaPipe's own defaults**, rather than left implicit. Deliberately not
      tuned: a track that found nothing reads very differently if the
      threshold was 0.9, so the number a track was made with should be
      visible. Which way to move them is a question for real footage.
- [ ] **VIDEO mode, not IMAGE mode**, with timestamps derived from the exact
      rational rate. Video mode carries state between frames — steadier and
      much faster — but rejects a timestamp that fails to rise, which is
      where a rounded 23.976 would eventually bite.
- [ ] **A decode that disagrees with the probe raises.** If the file hands
      over fewer frames than the source claims, every frame index after the
      difference points at the wrong picture, and nothing downstream could
      detect it. Refused rather than padded.
- [ ] **`runs_of_true` moved into `core/utils.py` and the validator
      refactored onto it.** Finding gaps in a track and finding repeats in a
      depth video are the same question, and I had written the loop twice —
      including the "close a run that reaches the end" case, which is the bug
      that shape exists to avoid.

## Phase 3 — cleanup findings, pre-phase

- [ ] **A missing `FAL_KEY` no longer blocks the whole app.** Found by
      running it: this machine reported `blocked` with every other check
      green. The reasoning in `check_fal_key` was that hosted depth is the
      only depth there is — but face tracking is local and free, a mesh layer
      is a deliverable on its own, and supplied depth arrives at 4.7. An
      environment check reports what a machine *can* do, and "cannot run" was
      not true. Now `degraded`, still carrying the fix. The real gate — refuse
      a depth run without a key, where it is asked for — is written into 4.5.

      **This is a user-facing behaviour change made during a cleanup pass**,
      so it is the one here most worth overturning if you disagree.
- [ ] **The three environment states are now worded in one place.** The
      banner and the Setup panel each had their own vocabulary and disagreed
      on all three, so the same machine read "Ready, with limits" on one tab
      and "Ready, with limitations" on the other. The banner now appends its
      count to the shared wording.
- [ ] **README was telling people `setup.bat` had not arrived yet.** It was
      built at 1.9 and ticked. The install section now leads with it, and
      says plainly that `setup.command` has never been run on a Mac.
- [ ] **`models.py` stays one file, and the reason is now in the file.** Not
      the foundation-file exemption — `sidecar.py` must live in `core` and
      references almost every model, so `core` cannot give them up. Written
      down so the split stops being re-proposed.

**Reviewed and left alone**, so the next pass does not re-examine them:

- `environment.py` at 545 lines is over the flag threshold and stays. It is
  ten checks and three small models, with the install copy already separated
  into `templates.py`. Splitting it would only move the checks away from the
  thing that reports them.
- The six `NotImplementedError` stubs in `models.py` are the Phase 3 tracking
  methods, written as pseudocode on purpose. They are the next thing built,
  not dead code.
- `DepthColormap` has no caller. It is Fal's own list and a documented
  contract for 4.10, so it is early rather than dead.
- Dependency direction holds in every direction: `core` imports nothing of
  ours, `media` imports neither `composite` nor `performance`, and nothing
  outside `src/ui/` imports `src/ui/`.

## Phase 2 — cleanup findings

- [x] **`compare_frames` reshaped into `find_stalled_frames`** — agreed
      2026-10-10. It now takes the file *and* its source, and reports runs
      where the file repeats a frame the source did not. A still shot
      legitimately repeats frames, so the source is the control; without it
      the check would fire on exactly the footage people shoot most. Six
      tests, including a stall at the very end, two separate stalls, and a
      length mismatch raising rather than reporting.
- [x] **`CHECK_FRAME_HASHES` removed** — a constant for a check that never
      ran.

## Phase 2 — 2.7 to 2.9

### 2.9 — Working folder

- [x] **A working file can be a folder.** A PNG sequence layer is many files,
      so reclaimable space counts a folder's contents and clearing removes it
      whole. Counting only loose files would report kilobytes where there are
      gigabytes. minicut had no case like this.
- [x] **Four suffixes rather than minicut's two** — mezzanine, proxy, depth
      field, layer — matched longest-first, because where one suffix *ends
      with* another the longer has to be stripped first. **Reviewed
      2026-10-10 and the comment was wrong twice over:** the tuple was not
      actually in that order, and the rule was stated as being about
      prefixes. Harmless as it stood, since no two of the four overlap, but
      it claimed a protection that was not there. Now sorted by length at
      definition, so it holds for a fifth suffix too, with a test that fails
      on a wrong order rather than only asserting the current one.
- [x] **Nothing is reclaimed automatically**, as in minicut, but the stakes
      are higher here: the cached depth was paid for, so deleting it to save
      disk means paying again. Clearing stays something the user asks for.
      **Agreed 2026-10-10:** a clear button, because an artist reuses a pass
      to make several outputs from it. The panel that calls it is 5.8.

### 2.8 — Sidecar

- [x] **The `Sidecar` model lives in `sidecar.py`, not `models.py`.** It has
      to reference the run settings, and `config.py` imports `models.py` — a
      model naming a settings type there would point the dependency arrow
      backwards. The settings arrive as a free-form dump instead, which is
      the one place in the project not using a typed model. **Agreed
      2026-10-10:** a dict is acceptable for something that is only ever
      written out, never read back and acted on.
- [~] **A job with no deliverables has not passed.** `all([])` is True, so
      "produced nothing" would otherwise read as success. **Deferred
      2026-10-10** — nothing is pending either way, so it stays as written
      until there is a real job to see it against.
- [x] **Timestamps are UTC with an explicit offset.** These files travel
      between machines, and a naive local time is worse than none. **Agreed
      2026-10-10:** one machine-readable field only. If reading it is ever
      awkward the UI formats it for display, rather than the file carrying
      two timestamps that can disagree.
- [~] **A `DeliverableRecord` carries the whole stack**, not just the format.
      Without it, "why does this composite look like that" has no answer six
      months on. **Deferred 2026-10-10**, same reason — easier to judge
      against a real sidecar than in the abstract.

### 2.7 — Validator

- [x] **Frame hashes are not part of `validate()`.** They cost a full decode
      of two files and only answer what metadata cannot — a hosted model
      returning the right length and the wrong picture. `find_stalled_frames`
      is a separate call, made when depth arrives.
- [x] **A duration failure is only reported when the count and rate both
      passed.** Otherwise it is a second symptom of a fault already named,
      and three failures for one problem is how a report stops being read.
      **Agreed 2026-10-10** — one failure for count, length and duration —
      and now held in place by a test, which nothing was doing before.
- [x] **The validator asks what the encoder *claimed* it did with the
      audio**, rather than inferring from the source. That is what lets an
      absent stream be correct for `OMITTED` and a failure for `COPIED`.
      **Reviewed 2026-10-10 and a gap came out of it:** for the carrying
      claims it only checks that *a* stream exists, which would pass a
      truncated or re-encoded track while non-negotiable 3 says carried audio
      is untouched. Comparing duration and codec is task 4.14.

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
