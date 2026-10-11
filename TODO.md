# TODO

Working reference. The current phase is broken into tasks; later phases are
listed by what they are and broken down when we reach them.

Scope reminder, because scope creep here looks like helpfulness:

- **The performance pass** turns footage into depth with face meshes and the
  original audio. It does not mask people, change the audio, or send anything
  to a generation model.

Anything else is in `Deferred` at the bottom, with the reason it was cut.

**Ordering principle: plumbing before models.** Frames go in and come out the
right length with the right audio before any model touches them. When a mesh
later lands a frame late, the frame handling will already have been proven on
footage with nothing drawn on it, and the tracker is the only suspect. Face
tracking comes before depth because it is local and free to iterate on; depth
costs money per call.

**Tasks tagged *(port)* are in PORTING.md**, with the source module, what is
kept, and what is deliberately left behind. Read that row before starting one.
A ported task is done when the module is trimmed, modernised for 3.12,
carrying its provenance line, and covered by a test that runs.

---

## Phase 0 — Documents

- [x] **0.1** CLAUDE.md, ARCHITECTURE.md, TODO.md, README.md, THIRD-PARTY.md
- [x] **0.2** `.gitignore`, `ruff.toml`, `pytest.ini`
- [x] **0.3** Review the documents and agree the design
- [x] **0.4** Licence for a public repo — MIT
- [x] **0.5** First commit and push to `github.com/ggvfx/performance-pass-builder`
- [x] **0.6** Replace the code conventions in CLAUDE.md with a pointer to
      `CODE_STYLE.md` once it is available. Project-specific decisions kept in
      CLAUDE.md; the shared rules now live only in `D:\_repos\CODE_STYLE.md`
- [x] **0.7** Reassess against `minicut-shot-detector` rather than rebuilding
      its foundations. Produced PORTING.md, and revised the design for
      multi-seed tracking, the plate seam and the depth storage split.
      A `core/models.py` skeleton written before this reassessment was deleted
      rather than edited: it carried a `FrameRate` class duplicating
      `timecode.py`, one seed frame per face instead of a list, no
      refusal/warning split on the probe, and the wrong validation shape.
      Task 1.3 writes it fresh

---

## Phase 1 — Scaffold & Foundations

- [x] **1.1** Python 3.12+ on the dev machine, venv, and `requirements.txt`
      pinned to versions that install together on Windows and Apple Silicon.
      Python 3.12.13; everything installs and imports with `pip check` clean
      on Windows, and on Apple Silicon (M4 Pro).
      Re-verified on this machine 2026-10-09 on Python 3.12.10 (winget's
      latest): venv rebuilt, every pin installed at its exact version,
      `pip check` clean, `ruff` and `pytest` green.
- [x] **1.2** FastAPI server on localhost, the page with two tabs, static
      files served so the browser re-checks them *(6 tests)*. Tab switching
      in a real browser still to be clicked through by hand.
- [x] **1.3** `core/models.py` — the shared shapes, as a skeleton. `SourceInfo`
      and `ProbeReport`'s refusal/warning split and `ValidationResult`'s shape
      taken from minicut as reference, **not copied**; `Face` as a label and a
      list of seeds; `FaceTrack`'s array contract; the stored-depth and plate
      models. First, as CODE_STYLE.md section 2 has it: every later signature
      names these types. *19 types, 6 methods still pseudocode (36 tests).*
- [x] **1.4** UI shell and look *(port — `styles.css`, `index.html` patterns,
      `tabs.js`'s `whenShown`)*. The page reads correctly before
      anything fills it: card layout, the tab strip, the one-line status strip.
      Early on purpose rather than at the end of the phase — on minicut, seeing
      the tool take shape on screen is what surfaced the edge cases and the
      extra functionality, and that is worth having while the rest of Phase 1
      is still being decided. *All five steps laid out dimmed; a test asserts
      every unwired control stays disabled (5 tests). Checked in Chrome.
      `ui.js` was deferred to 5.3 — its only callers land there, so porting it
      now would have left an unreferenced module.*
- [x] **1.5** `MediaToolchain` *(port — `core/ffmpeg_tools.py`, `core/utils.py`,
      the `core/config.py` shape)* — locate ffmpeg and ffprobe, read versions,
      encoders and filters, the only place a subprocess runs.
      **Keep `parse_filters` exactly:** ffmpeg 8 prints a two-character flag
      block where older builds printed three, so a row is recognised by its
      `->` signature rather than by counting flags. This dev machine runs
      ffmpeg 8.0.1, where counting makes every filter look missing and silently
      drops the proxy's burned-in frame numbers. Test it against captured
      ffmpeg 8 output. *Done, with fixtures captured from this machine's 8.0.1
      and two tests against the real binary (16 tests).*
- [x] **1.6** Environment panel *(port — `core/environment.py`,
      `core/templates.py`, `ui/runtime.py`, `ui/routes/setup.py`'s environment
      half, `environment.js`)* — three states (`ok` / `degraded` / `blocked`),
      a copyable fix for every failure, cached with re-check. MediaPipe, OpenCV
      and `FAL_KEY` rows replace the PySceneDetect one. **The first real data
      on screen**. *Nine rows; a missing FAL_KEY blocks while hosted depth is
      the only depth (21 tests). Checked in Chrome.*
- [x] **1.7** Server-side path picker *(port — `ui/browse.py`,
      `ui/routes/files.py`, `picker.js`)* — the first thing on the page that
      does something when clicked. *Done (12 tests). Checked in Chrome: opens
      on the home folder, offers both drive roots, filters to video.*
- [x] **1.8** Test fixtures generated by ffmpeg in `conftest.py` — known frame
      rate, frame count, geometry, and an audio track. *Seven clips, including
      a VFR one for the probe's refusal and a 24-bit PCM one for the audio
      fallback. test_fixtures.py checks the measuring stick itself (12 tests).*
- [x] **1.9** `setup.bat` and `setup.command`. Last rather than first: until
      there is an app to start and a panel to report on, a setup script has
      nothing to hand over to, and would be rewritten once there was. Tested
      as a fresh install on Windows and the M4 Pro.

      *`setup.bat` tested from a clean directory: found Python 3.12.10, built
      the venv, installed every pin, `pip check` clean, and reused the venv on
      a second run. **`setup.command` is NOT yet tested** — there is no Mac on
      the development machine. It passes `bash -n` and its Python-selection
      loop was run in isolation, but it needs one fresh run on the M4 Pro.*

**Phase done when:** the app opens, reports what is installed, and lets you
choose a file. **Met**, with one thing outstanding: `setup.command` has not
been run on a Mac.

---

## Phase 2 — Frames In, Frames Out

Everything needed to read every frame of a source and write a pass the same
length with the same audio, proven before any model exists.

- [x] **2.1** `SourceProbe` and `Timecode` *(port — `media/probe.py`,
      `core/timecode.py`)* — exact rational rate,
      frame count, audio streams, VFR refused with a reason the page can show.
      cropdetect is not ported. *Done (47 tests). The round trip walks 20,000
      frames at six rates, both drop-frame ones included.*
- [x] **2.2** Mezzanine *(port — `media/mezzanine.py`)* — all-intra, `verify()` proving it matches the
      source frame for frame. Here for exact random access, which is what makes
      re-seeding a track usable; the justification differs from minicut's and
      is written down in ARCHITECTURE.md. *Done (14 tests). Every frame of the
      output is asserted to be a keyframe, with a control test proving the
      source is not.*
- [x] **2.3** Numbered review proxy *(port — `media/proxy.py`)* — built from
      the mezzanine, with the drawtext and font fallbacks intact. *Done (11
      tests). The burned-in numbers are checked in the pixels, not in the
      filter string.*
- [x] **2.4** Frame streaming — decode to RGB through one pipe, encode from RGB
      through another, frame count exact. **New work**: minicut stream-copies
      shots and never pipes frames in either direction. *Done (14 tests). Two
      pixel formats — RGB, and RGBA for the layer with transparency.*
- [x] **2.5** Audio carried through by stream copy, with the fallback for a
      codec the container cannot hold — and the option to leave it out, which
      the validator checks is actually absent rather than merely unrequested.
      *Done (22 tests), and grown: four output formats. h264 and h265 in mp4
      for generation software and compositors; QuickTime RLE and ProRes 4444
      in .mov for a layer delivered with its alpha intact. RLE is the default
      of those — measured fifty times smaller than ProRes on line art, and
      lossless where ProRes is not.*
      *Revised after review: ProRes dropped as unused, h265 is the default,
      and ALPHA_RLE is reserved for the one export that needs it.*
- [x] **2.6** Compositor — stack N layers in the order given, index 0 at the
      bottom, "over", skipping any switched off; write the result through the
      frame pipe. The one layer with alpha is the mesh, so this is where RGBA
      gets flattened onto whatever is beneath it.
      *Done (19 tests). Straight alpha, `fg·α + bg·(1−α)`, in float32 so
      repeated layers do not round down. Index 0 is the bottom, an opaque
      layer hides what is under it, and a layer running short stops the job
      rather than trimming the output.*
      **Here rather than in Phase 5 because it is frame plumbing**:
      it can be proven against generated clips standing in as layers, before
      any pass exists to produce a real one. v1 has no opacity, no blend modes
      and no masks — a layer is a picture and a switch.
      Includes the two sources that are not passes: the **plate** and a **flat
      grey card** at `GREY_CARD_LEVEL`. They are layers like any other, so the
      compositor never learns which were generated and which were given
- [x] **2.7** Validator *(port — `splitter/validator.py`, ~35%)* — frame count, rate, duration, audio.
      Only the `framemd5` frame-hash machinery comes across; every shot-list
      check stays behind. Blocks
- [x] **2.8** Sidecar *(port — `core/sidecar.py`)*. *Done (15 tests).
      Records the source, the depth, the tracking, every deliverable with the
      stack that made it, and the environment — written whether the job passed
      or failed.*
- [x] **2.9** Working folder *(port — `media/workspace.py`)* — `.performance-work/`, reclaimable space
      reported and cleared on request, never behind the user's back. *Done
      (15 tests). Handles a sequence layer, which is a folder rather than a
      file — counted and removed whole.*

**Phase done when:** a source goes in and an output of exactly its length
comes out with its audio, verified by the validator rather than by eye — and
two stand-in layers composite into one. **Met.** Every piece is proven
against clips ffmpeg generated; whether it is right on real footage is the
checkpoint at 4.11.

---

## Phase 3 — Face Tracking, End to End (Current)

Local and free, so this is where the iterating happens.

**Footage, not generated clips.** Everything up to here was proven against
patterns ffmpeg draws, and MediaPipe will not find a landmark in any of them.
`tests/media/one_face_medium.mp4` is the first real clip — one person, medium
close-up, frontal, well lit, near-static — and it covers 3.2 and most of 3.3.
Gitignored, with the tests skipping when it is absent so a fresh clone still
runs. `tests/media/README.md` lists the clips still wanted: two faces
crossing, a face leaving frame and returning, a profile turn, a moving camera,
a small face in a wide shot. Those are what 3.4 onward actually need.

- [x] **3.1** MediaPipe model downloaded on first use, checked against a
      pinned SHA-256, cached outside the repo's tracked files
      *`src/performance/model_file.py`. `face_landmarker.task`, float16 v1,
      3,758,596 bytes, into the gitignored `models/`. The hash was taken from
      the bundle actually exercised: it loads, finds the face in
      `one_face_medium.mp4`, and returns 478 landmarks — `LANDMARK_COUNT`.
      Verified on every call, not only after downloading, because that costs
      4 ms. A file that fails its hash is deleted, never used. Proven for
      real from a clean `models/`: downloaded, cached, then tampered with and
      replaced. 20 tests, none touching the network.*
- [x] **3.2** One face, full frame, every frame — the baseline
      *`src/performance/tracking.py`. 240/240 frames on
      `one_face_medium.mp4` at ~75 fps, landmarks checked by eye against the
      picture as well as by assert. A clip with no face gives a full-length
      track of NaN, never a short one. `FaceTrack.validate_shape`, `gaps`,
      `segments` and `landmarks_on` implemented with it — they were
      pseudocode, and the tracker is what fills the arrays they describe.*
- [x] **3.3** Seeding from a box on a chosen frame; forward and backward runs
      *`FaceTracker.track_from_seed`. 240/240 from a seed on frame 120, both
      directions. Backwards needed `FrameReader` to seek and a new
      `frames_backwards`, which buys frames in memory-bounded windows — a
      decoder only runs forwards. Seeking proven exact against the mezzanine
      by frame hash; the backward half agrees with a plain forward run to
      2.39px against the forward half's 2.25px, which is the number that
      says the reversed frames are aligned.*
- [x] **3.4** The search box following the face frame to frame
      *Each frame is cropped to a region round the last known position and
      only that is searched, so a face wandering into shot is not a
      candidate at all. Measured rather than assumed: 2.10px from the
      baseline against the whole-frame search's 2.33px, same speed. Proven
      on a two-face clip built from the one-face one side by side — seeding
      either face tracks that face for all 240 frames and never crosses.
      `NormalisedBox.to_pixels` and `.padded` implemented, which was the
      last pseudocode in the skeleton.*
- [x] **3.5** Several faces, one tracker each, **re-tracking only what changed**
      *`track_selection`, with a landmarker per face so two people cannot
      become each other. Every seed is checked before any tracking starts —
      one detection each, under a second — so a box drawn on the sky is
      refused before minutes are spent, and every bad box is named at once.
      Both officers tracked separately off the night clip. Editing one
      face's seeds re-tracks only that face and hands the others back
      untouched, because each one costs a full decode; `on_face` names the
      face being worked on so a page can say which rather than only moving
      a bar.*
- [x] **3.6** Several seeds per face — segments between them, backward from the
      first, forward from each to the next. Every frame records which seed
      produced it, or that it is a gap. 3.3 becomes the one-seed case of this
      rather than a second mechanism
      *`track_face`, and `track_from_seed` is now a wrapper over it rather
      than a second mechanism. A segment stops at the next seed instead of
      running to the end, so three seeds cost one decode and not three.
      Only the first seed can fail the track: a later one that finds nothing
      is a gap in its own segment, never the loss of everything behind it.*
- [x] **3.7** Smoothing, resetting across a gap and across a seed boundary
      rather than through either
      *`src/performance/smoothing.py`. A One Euro filter, which adapts per
      landmark per frame — a still point smoothed hard, a fast one barely,
      because smoothing movement is latency. Resets on `segments()`, which
      already returns exactly the runs that may be filtered as one. 2.48 to
      2.01 px/frame on the real clip. **The published beta of 0.007 was
      inert here** and is now 30: that figure assumes pixels, and landmarks
      are fractions of the picture, so it was three orders of magnitude too
      small to lift the cutoff off its floor. A test holds that.*
- [x] **3.8** Rendering the mesh to **its own layer, with alpha** — not drawn
      onto anything. Widths scaled to the picture. All faces in one layer, with
      per-face visibility, so a three-person shot does not fill the stack. This
      is what lets the mesh be output alone, reordered, or left out of a
      composite without re-tracking
      *`src/performance/mesh.py`. Blue tessellation, green eyes and brows,
      orange lips, white irises — the colours the design notes started from,
      whose provenance is unverified (THIRD-PARTY.md) and whose effect on a
      generation model is untested. Looked at over the plate, not just
      asserted. **Found a real bug on the way:** the base
      `FrameWriter` forced `yuv420p` whatever arrived, so RGBA went in and
      an opaque video came out — a mesh layer written that way composites
      as a solid rectangle. The old alpha test could not catch it because
      it used fully opaque alpha, which reads back the same either way.*
- [x] **3.10** **A recovered face must be shown to be the same face.** Found
      by `two_faces_cross_and_exit.mp4`: when the seeded officer walks out of
      frame, the search region stays where it was, the other officer walks
      into it, and he inherits the track. The mesh then lands on the wrong
      person with nothing indicating it — which is worse than losing him,
      because it looks like success. Options, cheapest first: require a
      recovered face to overlap the last known box; cap how long the region
      may wait before the track is declared ended; cap how far a face may
      jump in one frame.
      *Done. A face must overlap where it was **one frame ago** — and only
      one frame ago. The transfer on the night clip happened with no gap at
      all, so recovery-only checking would have missed it entirely; and a
      face lost for 52 frames on the desert clip returns overlapping its old
      box by 0.06, so any threshold strict enough to catch a transfer throws
      her return away. 0.4, against a measured floor of 0.88 for a face that
      is still itself. The give-up rule is 5 seconds, a backstop rather than
      the mechanism. All three clips measured before and after: the night
      clip now follows him out of frame and stops instead of inheriting the
      other officer, the desert clip is unchanged at 188/240, the studio
      clip unchanged at 240/240.*
- [x] **3.9** `landmarks.json` and the per-face tracking report, including
      where each face's seeds are and which frames came from which
      *`src/performance/landmarks.py`, with a reader so the round trip is
      testable and a later tool has one obvious way in. A gap is `null`,
      never interpolated. 2.4 MB for ten seconds of one face — see the
      decision about `.npz` for long jobs.*

- [x] **3.11** **Wire it to the page.** Inspect and Prepare on the Source
      step, Track on the Faces step, driving the real pipeline rather than a
      script. Long work runs as a background job so the bar moves and each
      stage says what it is doing; the preview composites the mesh over the
      plate through the real `Compositor` and the real `LayerStack`.
      *Done, and looked at in a browser: the night clip inspected, prepared,
      tracked at 235/240, and the mesh plays back over the plate in the page.
      One face, whole frame, no seeds — drawing boxes is 5.4.*

### Finishing it — a face pass you can actually make

Pulled forward from Phase 5 on 2026-10-11. The reasoning: tracking is built
and tested but you cannot *choose* a face, so multi-face, re-seeding and the
colour scheme are all unreachable from the app — and nothing produces a file
you could hand to anything. Depth would add a second unfinished system on
top of an unfinished one.

- [x] **3.12** The proxy on the Faces step: play, scrub, step a frame at a
      time, and the frame number read off the burned-in digits rather than
      from the browser's idea of time. *Ports minicut's `player.js`, which
      exists for exactly this problem*
      *`player.js`, plus `/api/proxy` which derives the proxy's location
      from the source rather than being handed a path. Inspect now reports
      whether a source is already prepared, so one prepared in an earlier
      session still shows its proxy. Arrow keys step a frame, up and down
      ten, space plays.*
      **Playback not confirmed in a browser this session** — the automation
      browser stopped playing video partway through, including a file it had
      played an hour earlier, so the failure is not the app's. The proxy
      decodes cleanly, its container is textbook with the metadata at the
      front, and the transport arithmetic is minicut's unchanged. First
      thing to check at 3.13.
- [ ] **3.13** Draw a box, name the face, remove it. **Adding a seed to an
      existing face has to be the more obvious action** — a returning person
      given a new face gets a new colour, and every prompt naming the old one
      breaks. That is the one way the identity scheme fails
- [ ] **3.14** `selection.json` written and read back, so a selection
      survives closing the app and is the whole interface between the picker
      and the pipeline
- [ ] **3.15** Track the selection from the page: a landmarker per face,
      per-face progress saying which one, and **only re-tracking the faces
      whose seeds changed**. All built at 3.5 and 3.6; this reaches it
- [ ] **3.16** Per-face visibility, the colour swatch beside each name, and a
      timeline showing each face's coverage, seeds and gaps — so where a
      re-seed is needed is visible rather than guessed at
- [ ] **3.17** **Output a face pass.** The mesh over the plate, or over grey
      or black, or alone with alpha. A real deliverable: written through
      `OutputWriter`, checked by the validator, recorded in a sidecar, with
      the audio carried or deliberately left out. Format h265 by default;
      the alpha format chosen by the app rather than offered.
      *Everything underneath this exists and is tested — the stack, the
      constant layers, the writer, the validator, the sidecar. Nothing calls
      them*
- [ ] **3.19** **Tolerance, per seed.** One setting rather than MediaPipe's
      three confidences — three dials is a panel nobody can reason about,
      one slider is something you can turn while watching the result. It
      lives on the Faces step as the default for new seeds, and **on each
      seed**, so the stretch after someone turns away can be loosened
      without touching the parts that already track well. Recorded in
      `selection.json` and the sidecar, so a track is reproducible and it is
      visible why one segment behaved differently.
      *Changing it re-tracks that face, which 3.15 already does. And
      loosening is not free: more detections means more false ones, and the
      search region will follow a false face as readily as a real one —
      which is why it is per seed rather than global.*
      *After 3.18 deliberately: a dial is worth having once you have seen
      what it needs to fix.*
- [ ] **3.18** **Checkpoint: judge it.** The three real clips, end to end in
      the app, looked at rather than measured. Settles the confidence
      thresholds, the smoothing strength, the mesh colours and line weights,
      and whether re-seeding feels like the normal way to work

**Decision point at 3.8:** composite the mesh layer over the plate — which
the stack already does, since the plate is a layer source — and judge on
real footage — two people, a face crossing another, a turn to profile, a wipe —
before depth is involved. That is also where re-seeding either proves itself or
needs rethinking.

---

## Phase 4 — Depth on Fal

- [ ] **4.1** Settle open questions 1–5 in ARCHITECTURE.md
- [ ] **4.2** **Measure what Fal actually returns**, on one short clip, before
      anything is built on assumptions: the `.npz` size and download time
      against the arithmetic in ARCHITECTURE.md, the bit depth of the grayscale
      video, and whether raw depth at a lower `resolution` is usable upscaled.
      This gates 4.8 and 4.10 — if the download turns out impractical, the
      windowing design needs revisiting, and that is far cheaper to learn here
- [ ] **4.3** `DepthBackend` interface and the transport *(port — `backends/adapter.py`
      and `backends/transport.py` shapes)*
- [ ] **4.4** Setup tab: which depth backend, whether `FAL_KEY` is set, which
      model, and the raw-depth resolution *(port — `backends/availability.py`,
      the backend half of `setup.js`)*. New work in substance: minicut's rows
      ask about an LLM, these ask about a depth model and its licence
- [ ] **4.5** Fal: upload, submit, poll, fetch, with limits checked before
      upload. `model` always sent explicitly, `output_fps` never sent,
      `side_by_side` never set — see CLAUDE.md non-negotiable 14.
      **The key is checked here**, at the point depth is asked for, and
      refused here. A missing key degrades the app rather than blocking it —
      face tracking is local and free — so the environment panel must not be
      the thing that stops a depth run
- [ ] **4.6** Depth validated on arrival rather than trusted: length and
      rate through `validate`, and `find_stalled_frames` against the source
      to catch a model that stalled and returned the same picture twice.
      Not a hash comparison against the source — depth is not the same
      picture as the plate, so the two can never match
- [ ] **4.7** **Supplied depth** — a backend that takes a depth video the
      artist already made elsewhere, so nobody pays twice to put face meshes
      over depth they already have. The same arrival checks, the same
      conversion, the same window and colour map; only the call is skipped.
      The page has to say that a colormapped import cannot be windowed, that
      there is no model range to align against, and what precision it found.
      **Exactly the source's length or refused** — no trimming, no padding:
      a silent one-frame correction produces a pass that drifts and a reason
      nobody can find. Offering to trim is a future convenience.
      **Also makes a missing `FAL_KEY` degraded rather than blocking**, since
      a machine with no key can now produce a pass
- [ ] **4.8** `.npz` → stored scalar field: extract the `depths` member to a
      plain `.npy`, memory-map it, stream to 16-bit single channel, record
      `min_depth` / `max_depth` / `model` / `shape`, delete the `.npz`.
      Loading the member directly out of the archive runs out of memory on any
      real shot
- [ ] **4.9** Depth cached and reused, keyed to the source and the depth
      settings. Changing a window or a colormap must never call Fal again
- [ ] **4.10** Rendering the depth layer — window to a `near`/`far` pair, hard
      clip, then colour map, from the stored field. The only module that
      colormaps. Local and instant, so changing either never calls the model

### Checkpoint — the first real passes, checked end to end

Everything before this is proven against generated clips. This is where a
real face on real footage goes through the whole chain for the first time,
and it is a deliberate stop rather than a formality: most of what follows
assumes these hold.

- [ ] **4.11** One real shot, all the way through: prepare, depth, track,
      composite, output. Timed at each stage, because nobody yet knows what
      Prepare costs on a long source. **Includes the one test that really
      downloads the model**, from an empty `models/` — the unit tests mock
      the network, so nothing else proves the URL is still live
- [ ] **4.12** The things only a person can see. The mesh lands on the frame
      the readout claims — against the proxy's burned-in numbers. The alpha
      edges are clean, with no dark fringing, which is the straight-versus-
      premultiplied decision actually verified. Two faces crossing. A face
      leaving frame and coming back. A profile turn
- [ ] **4.13** The deliverables open where they are going: the mp4 in the
      generation tool, the mesh layer in Nuke
- [ ] **4.14** Audio **verified**, not merely present. `check_audio` confirms
      a stream exists when one was claimed, which would pass a truncated or
      wrong-codec track — and non-negotiable 3 says carried audio is
      untouched. Compare the source's audio duration and codec against the
      output's; the probe already returns both, so it costs nothing. The
      failure this catches is a long take whose sound stops early, which
      nothing would currently report

**Checkpoint done when:** a pass built from real footage has been looked at,
not merely measured.

---

## Phase 5 — The Workflow

A step strip — Source, Depth, Faces, Composite — where each step holds its own
settings, its own process button and its own result. **Every step is reachable
from the start** and says what state it is in rather than being locked: someone
opening the app for the first time should be able to see the shape of the job.

- [x] **5.1** The step strip *(port — `tabs.js` pattern)*: four steps, each
      showing not run / processing / done, all clickable, each saying in place
      what it still needs *(built at 1.4, driven at 3.11)*
- [x] **5.2** Source step: inspect, prepare, and the facts *(port —
      `source.js`)* *(done at 3.11)*
- [ ] **5.3** Depth step: settings, a process button, the result playing in
      place, and the window and colour map underneath, re-rendering live
- [x] **5.4** Faces step — **moved to 3.12 to 3.16**, so face tracking is
      finished and usable before depth begins
- [ ] **5.5** Composite step: the stack, **reorderable**, with a switch per
      layer and the plate and grey card listed beside the passes. The output
      button, and the choice of whether to carry the audio. Outputting one
      pass is this with one layer on.
      *The single-pass half of this moved to 3.17 — a face pass with a
      chosen background. What is left here is the reorderable stack, which
      only becomes interesting once there is a depth layer to reorder.*
      *Format: the artist chooses h265 (default) or h264, and nothing else.
      The alpha format is picked by the app for a face-mesh-only export
      rather than offered — three-quarters of a format dropdown would be
      wrong for whatever they are doing. h265 is hidden when the build has no
      libx265, which the Setup panel already reports.*
- [ ] **5.6** Routes behind all of it *(port — `routes/splitter.py` shape)*:
      prepare, run one pass, composite, output
- [ ] **5.7** The warning before footage is uploaded, and the raw-depth
      download offered with its cost stated
- [ ] **5.8** Work folder panel *(port — `work.js`)*: what the working files
      are costing in GB, and a clear button. Reported rather than acted on —
      an artist reuses a pass to make several outputs from it, so nothing goes
      until it is asked for, and the source being worked on is spared even
      then. `reclaimable_bytes` and `clear_work` are written and waiting for
      this panel to call them
- [ ] **5.9** An install guide on the Setup tab — how to install what the app
      needs, readable whatever state the machine is in. The checks only speak
      up when something is missing, which is no use to someone setting up a
      second machine. *Written once at 1.6 as `/api/install-guide` and removed
      in the Phase 1 cleanup: nothing called it, and an endpoint with no caller
      is the kind of thing that rots quietly. It comes back with its panel.*

**Phase done when:** an artist with a Fal key can produce a pass end to end
from the browser, on Windows and on a Mac, choosing which passes to run.

---

## Phase 6 — Local Depth (optional)

Listed so the shape is known. Broken down when reached.

- PyTorch Video Depth Anything for machines with an NVIDIA GPU or Apple
  Silicon, as a separate optional requirements file so artists who use Fal
  never install PyTorch
- **Also the quality path for depth work**, not merely a convenience: it yields
  float depth directly with no multi-gigabyte download, which is the one real
  cost of the hosted route once raw depth is wanted

---

## Phase 7 — Depth Editing (shape only)

Named so the plate seam has a stated purpose. **Not designed.** Broken down
when reached, and not before Phase 5 is finished.

- **Not a separate utility or tab any more.** Combining depth passes is an
  edit on the Depth step, beside the window and the colour map, because that
  is where someone adjusting depth is already looking
- Loading a second depth pass and aligning it, with an offset and scale per
  pass. Alignment has to be manual: this model's depth is relative and
  normalised per clip, so there is no shared metric to align by — `min_depth`
  and `max_depth` are the starting numbers
- A soft knee on the window, as an alternative to the hard clip
- The compositor gains whatever this needs and no more. Opacity and blend
  modes are likely; masks wait for something to generate them
- Trimming or padding a supplied depth pass that is not quite the source's
  length, which 4.7 refuses outright

---

## Deferred

Two former entries have moved onto the plan. Fal's `include_raw_depths`
returns float32 `[N,H,W]` with its own `min_depth` and `max_depth`, so **raw
float depth** is now how depth arrives rather than a someday export, and
**windowing the depth range** is a v1 feature in Phase 4. Combining several
passes is Phase 7.

Still deferred:

- **Region compositing driven by masks (SAM).** One area depth, one area the
  original plate, one area flat grey, as a control pass. The reason the plate
  seam exists and the likeliest thing to be built on it. SAM 2.1 is Apache-2.0
  and takes box prompts, which fits the selection step already planned. Fal
  also hosts SAM; which version needs checking before relying on it. **None of
  it is designed.**
- **Vocal isolation and pitch shifting.** The project notes say the Genjutsu
  workflow isolates vocals with Demucs and pitches them up three semitones
  before generation — **unverified**, like the mesh colours; see
  THIRD-PARTY.md. Not needed to prove the pass; worth checking the claim
  before building anything on it.
- **Submitting to a generation model.** The artist's choice of platform.
- **Blendshapes and head pose** — MediaPipe returns both if asked.
- **Freehand face selection.** A box only tells the tracker where to look, and
  a second seed past a break covers what freehand was wanted for.
- **ONNX instead of PyTorch for local depth.** Smaller install, and Apple
  Silicon acceleration. Needs a check that usable exports exist first.
- **Native packaging.**
