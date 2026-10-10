# Decisions taken without review

Calls made while working unattended, newest first. **One or two lines each,
and only the ones worth overturning** — this is meant to be read in a few
minutes, not to be a changelog.

Tick a line once you have read it and are happy. Anything you want changed,
say so and it changes; nothing here is settled by having been done.

Delete this file when the backlog is empty and we are reviewing task by task
again.

---

## Phase 2

### 2.5 — Audio

- [ ] **Audio is muxed in the same ffmpeg pass as the picture**, as a second
      input, rather than written video-first and muxed after. One pass instead
      of writing the video twice. Cost: `-map 0:v:0` must be explicit, because
      with two inputs ffmpeg could otherwise pick the *source's* picture and
      silently deliver the original footage. There is a test for exactly that.
- [ ] **`-shortest` is deliberately not used.** It would trim the picture to
      the audio, and a pass that is not exactly the source's length is the one
      thing this project will not deliver. If the two disagree, the validator
      at 2.7 is where it surfaces — loudly.
- [ ] **`AudioHandling` is recorded, not inferred**: copied, encoded, omitted,
      or none. Three of those produce files that look identical, so the
      sidecar is the only place the difference survives.
- [ ] **The fallback is aac at 320k**, in config. High enough that the
      generation is driven by what was recorded rather than by what survived a
      second pass. A guess at a sensible number — change it if you disagree.
- [ ] **`FrameWriter.arguments()` was made overridable** so `OutputWriter`
      could add an audio input without reimplementing the pipe handling.
      Alternative was a separate class duplicating about sixty lines of
      process management.

### 2.4 — Frame streaming

- [ ] **Pipes are opened in `ffmpeg_tools.py`, not in `frames.py`.** CLAUDE.md
      says the toolchain is the only module that runs a subprocess, "including
      the frame pipes", so `MediaToolchain.popen_ffmpeg()` is the one place
      `Popen` is called. `frames.py` builds the arguments and does the numpy
      work. Alternative was letting frames.py own its own process, which reads
      more naturally but breaks a stated rule.
- [ ] **Frames are read and written as `rgb24`, 8-bit, no alpha.** Enough for
      depth and the plate. **The face mesh layer needs alpha**, so the writer
      will have to take `rgba` and the compositor flatten it — deferred to 2.6
      rather than guessed at now.
- [ ] **A short read ends the stream rather than raising.** ffmpeg closing the
      pipe is how a decode finishes normally. A *partial* frame does raise,
      because that is a truncated read rather than an end.
- [ ] **The reader counts frames and the caller is expected to check.** The
      reader does not know what the source said it had; the validator at 2.7
      is where frame counts are enforced. Asserting it in two places would
      make it ambiguous which one owns the rule.

---

## How to read this

Each entry says what was decided and what the alternative was, because the
alternative is the part that makes a decision reviewable. Where something was
deferred rather than decided, it says so and names the task that will decide
it.
