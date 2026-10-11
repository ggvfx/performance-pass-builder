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

## Reviewed with you, 2026-10-11

- [x] **Faces stay separate passes, and only what changed is re-tracked.**
      Agreed, with the two requirements you added. `track_selection` takes
      `retrack` and `existing`: name the faces that changed, hand back the
      rest, and a complete set comes out in selection order. A kept face's
      seeds are not re-checked — its box cannot have gone bad, and checking
      it would only create a way for an untouched face to fail a job.
      `on_face(label, position, count)` names the face being tracked, and
      the count is what is *being* tracked, not the whole selection, or the
      bar lies about the work left.
- [x] **Only the first seed can fail a track** — you noted this was already
      the behaviour you were asking for.
- [x] **A missing `FAL_KEY` degrades rather than blocks.** Confirmed: not
      needed for face tracking, so it should not stop the app.
- [x] **A decode that disagrees with the probe raises.** Confirmed.


- [x] **Faces are told apart by a hue on the tessellation.** Agreed: hue on
      the surface only, lips and eyes unchanged on everyone, auto-assigned
      from a palette in the order faces were chosen. Green and orange are
      kept out of the palette because they are the eye and lip colours.
      Face 1 keeps the existing blue, so single-face jobs are unchanged.
      Looked at on the two-officer clip: blue and red read clearly apart at
      a glance, with the feature colours still legible on both.

      **The UI requirement this creates**, written into ARCHITECTURE: adding
      a seed to an existing face must be more obvious than adding a new
      face. A returning person given a new face gets a new colour, and every
      prompt naming the old one breaks. That is the only way this scheme
      fails.

      Still untested: whether a generation model reads colour as identity
      at all. It is the only property a text prompt can name, so it is worth
      having regardless — but the checkpoint should try it on two people
      before you rely on it.
- [x] **Genjutsu is a reference in THIRD-PARTY and nothing more.** Confirmed
      by you. The unverified-attribution note can go when someone gets round
      to it; the point was never the credit, it was that I had written
      "known to read as guidance to Seedance" as fact without evidence.


- [x] **A track can transfer to the wrong face (3.10).** Agreed: require a
      recovered face to overlap where it was last, with a give-up rule after
      N missing frames as a backstop, N being a setting. Not yet built.
- [x] **`landmarks.json` stays JSON.** `.npz` would be a tenth of the size
      and Nuke cannot open one without a script, which costs more than the
      megabytes save. If a long job ever hurts, write both rather than swap
      the interface.
- [x] **Landmarks are now opt-in, off by default.** Nothing in the app reads
      the file, and a face mesh is biometric-adjacent — a weak signal beside
      the footage it came from, but a new artefact that can travel
      separately. An export nobody asked for should not be written.
- [x] **Seeking is enforced, not documented.** `SourceProbe.is_all_intra`
      samples the first 60 frames' keyframe flags, and `frames_backwards`
      refuses anything else with `NotAllIntra`. **A bug while writing it:**
      ffprobe's csv writer appends a trailing comma to a single field, so
      every flag read as `"1,"` and the check called the mezzanine long-GOP
      — it would have refused the one file that is safe. Caught by running
      it against a real mezzanine rather than trusting it.
- [x] **Confidence thresholds stay at 0.5 until the 3.8 checkpoint**, where
      "too strict" and "inventing faces" are visible rather than arguable.

- [ ] **I asserted the mesh colours were "known to read as guidance to
      Seedance", and I cannot support that.** It is not in your repo — the
      initial commit was a README stub and a LICENSE — so it entered with
      the Phase 0 design documents I wrote. Whether you mentioned Genjutsu
      in conversation I cannot verify; that part of the session is
      summarised. Either way the *"known to read as guidance"* part was an
      assumption written as established fact, and it had reached three
      documents, a config comment and a test docstring.

      All of them now say it is an untested starting point, and
      THIRD-PARTY.md marks the attribution itself unverified with
      instructions to confirm or remove it. The same treatment went to the
      "pitches vocals up three semitones" claim from the same source.
      **Worth your eye: do you recognise Genjutsu as something you pointed
      me at?** If not, the attribution should go entirely.

## Phase 3 — cleanup after 3.9

- [ ] **A segment reported the wrong seed frame.** Found by reading
      `report_for` with fresh eyes, not by a test. It set `seed_frame` to
      the *segment's* start — but the first seed's backward run covers
      everything before it, so a seed on frame 200 owns a segment starting
      at 0. Every marker on the Faces timeline would have sat in the wrong
      place for any seed not on frame 0. `report_for` now takes the faces
      and looks the real frame up; where there are none to look up it is
      `None` rather than a guess, which is the baseline run's honest answer.
- [ ] **One place opens a landmarker now, not four.** The same lazy import
      and the same six configuration lines appeared in `track_every_frame`,
      `_forward`, `_backward` and `check_seeds`, and `check_seeds` reached
      in afterwards to change the running mode. **The file got seven lines
      longer**, so this is not a size win — it is a single point of truth
      for how a landmarker is configured, which is the thing that drifts.
- [ ] **Nothing outside `src/performance/` calls any of Phase 3.**
      `track_selection`, `render_layer` and `landmarks_path_for` have no
      caller: no route, no pipeline, no UI control. The Faces step in the
      browser is still dimmed. That is expected — `pipeline.py` is Phase 4
      — but it is now four modules and about 1,800 lines deep, which is the
      most unwired work this project has carried at once. The 3.8 checkpoint
      already in TODO.md is where it gets looked at.

**Reviewed and left alone:**

- `tracking.py` at 809 lines is over the threshold and stays. It is one
  class doing one job in three ways, and the arithmetic it used to carry is
  already in `face_geometry.py`. Splitting the tracker from its own
  segments would scatter something cohesive.
- No dead code. The only unreferenced names are pydantic validators and
  FastAPI handlers, which frameworks call by other means, plus
  `DepthColormap`, still an early contract for 4.10.
- Dependency direction holds in every direction.
- Every module that exists is in ARCHITECTURE's table; the ten that are
  listed and missing are the ones still to be built.
- The app serves, both routes answer, and the environment panel reads
  `degraded` for the missing Fal key with everything else green.

## Phase 3 — 3.5 to 3.9

Two of these are bugs I found and fixed; the rest are calls worth your eye.

- [ ] **The base `FrameWriter` was throwing the alpha channel away.** It
      forced `-pix_fmt yuv420p` whatever arrived, so RGBA frames went in and
      an opaque video came out with nothing failing — a mesh layer written
      that way composites as a solid rectangle over everything beneath it.
      `OutputWriter` overrides this correctly, so deliverables were fine and
      only direct `FrameWriter` use was affected. **The existing alpha test
      could not have caught it**: it wrote alpha 255 everywhere, which reads
      back identically either way. The new one writes transparent,
      half-transparent and opaque stripes.
- [ ] **One Euro's published `beta` of 0.007 does nothing at our units.**
      That figure assumes pixels or centimetres; landmarks are fractions of
      the picture, so a briskly moving face reads as 0.03 per second rather
      than 60 and the adaptive half of the filter never engages — measured,
      the result was indistinguishable from a plain lowpass. It is 30 now,
      with a test asserting both that 0.007 is inert and that 30 is not.
- [ ] **Seeds are all checked before any tracking starts.** One detection
      each, under a second, so a box drawn on the sky is refused before
      minutes are spent — and every bad box is named at once rather than one
      per run.
- [ ] **Only the first seed can fail a track.** A later seed marks a face
      the artist can see; if the detector disagrees there, the honest result
      is a gap in that segment rather than losing everything tracked behind
      it.
- [ ] **Each face costs a full decode.** Three faces, three passes over the
      source. Sharing one decode between several landmarkers would be faster
      and is not done: the faces are seeded on different frames and run in
      different directions, and that bookkeeping is a worse thing to own
      than the extra minutes — until something says otherwise.
- [ ] **The mesh is unpremultiplied once, after all faces are drawn.**
      OpenCV's anti-aliasing leaves premultiplied edges and the compositor
      works in straight alpha, so the colour is divided back out. Doing it
      per face would compound the rounding where two faces overlap.
- [ ] **`landmarks.json` is 2.4 MB for ten seconds of one face**, and would
      be about 106 MB for two minutes of three. That is inherent — 478
      points of three numbers per face per frame — and it is written
      compactly with no indentation because nobody reads 344,000 numbers by
      eye. **`.npz` would be roughly a tenth of the size**, and is already
      the format Fal hands depth back in. Worth switching? It is an
      interface, so not a thing to change quietly later.
- [ ] **Rounding is done in float64, which halved the file.** Round a
      float32 to five places and `tolist()` writes all seventeen digits of
      the nearest float32 to that value. 5.6 MB became 2.4 MB with identical
      accuracy — 0.01 of a pixel.

## Phase 3 — what the new footage found

- [ ] **A track can transfer to the wrong face, and I have left it broken
      with an `xfail` test rather than fixing it quietly.** When the seeded
      officer walks out of frame, the search region stays put, the other
      officer walks into it, and he inherits the track. The mesh lands on the
      wrong person and nothing says so.

      Three ways to fix it and they behave differently on real footage —
      require a recovered face to overlap the last known box; give up on the
      track after N missed frames; cap how far a face may jump in a frame —
      so it is **3.10** and your call rather than mine. The failing test
      means whichever is chosen has something to prove.
- [ ] **Two clips in, both kept, both gitignored.**
      `walks_in_and_turns_away.mp4` is the first real gap: 151 frames of it,
      against a cold baseline of 89/240 and a seeded 188/240.
      `two_faces_cross_and_exit.mp4` is the hardest clip here — a genuine
      crossing, an exit, profiles, night neon, and detection flickering
      throughout.
- [ ] **The confidence thresholds now have something to tune against.** On
      the desert clip the tracker does not find a face at frame 120 that
      looks perfectly findable by eye, and on the night clip detection
      flickers on 24 frames of 240. Both are at MediaPipe's default 0.5.
      Worth a pass once the mesh is visible at 3.8, not before — it is a
      judgement that needs looking at, not measuring.

## Phase 3 — cleanup after 3.4

- [ ] **`tracking.py` split: `face_geometry.py` now holds the arithmetic.**
      701 lines was over the threshold, and the file held two different
      things — running a model, and working out where a face is. The second
      needs no MediaPipe, no ffmpeg and no footage, so its tests run in
      0.12s instead of waiting on a 240-frame track. Tracking is 504 lines
      now, still over 400 but one class doing two runs.
- [ ] **`if region` became `if region is not None`.** A pydantic model is
      always truthy so the behaviour was already right, but the code read as
      though an empty box might be falsy.

**Reviewed and left alone:**

- No new dead code. The only unreferenced names are pydantic validators and
  FastAPI handlers, which frameworks call by other means, plus
  `DepthColormap`, which is still an early contract for 4.10.
- Dependency direction still holds in every direction.
- The app still serves, both routes answer, and the environment panel reads
  `degraded` for the missing Fal key with everything else green.

## Phase 3 — 3.4

- [ ] **The search region crops the picture rather than filtering the
      results.** Both would stop a face being stolen; cropping also gives
      the model more of the face to look at. Measured on the real clip
      before committing to it: 2.10px from the baseline against the
      whole-frame search's 2.33px, at the same speed. `search_padding=None`
      keeps the whole-frame behaviour so the two stay comparable.
- [ ] **A small face's region is grown to at least 192 pixels.** MediaPipe's
      detector runs at 192x192, so cropping tight to a distant face would
      hand it a magnified thumbnail and lose the only advantage cropping
      has — on exactly the shot it should help most.
- [ ] **While a face is missing the region stays where it was.** A blink or
      a blur recovers; someone who leaves and returns elsewhere does not,
      and wants another seed. A widening search would recover more and also
      start stealing faces, which is the thing this exists to prevent.
- [ ] **The two-face test clip is built from the one-face clip, side by
      side.** It proves a seed picks one face of several and holds it. It is
      *not* a substitute for real two-person footage: these faces never move
      or cross, so the hard case is still untested and still on the wanted
      list.
- [ ] **The pseudocode guard test is gone.** It asserted the remaining stubs
      raise rather than return None, and there are none left. Keeping a test
      that forbids pseudocode would be wrong for this project — writing
      stubs first is deliberate — so it was replaced by real tests of the
      box arithmetic.

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
