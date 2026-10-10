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
