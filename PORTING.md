# Porting from minicut-shot-detector

**This file is scaffolding. Delete it once every row below is ticked** — at
that point the code is wholly this repo's, and the only record anyone needs is
the provenance line in each module's docstring and the note in THIRD-PARTY.md.

Nothing else should refer to this file. If something here turns out to be worth
keeping permanently, it belongs in ARCHITECTURE.md instead.

---

## Why this exists

`D:\_repos\minicut-shot-detector` already solves, with tests and on real
footage, most of what this project needs before it reaches anything new:
locating ffmpeg, probing a source, refusing variable frame rate, frame-exact
timecode, an all-intra mezzanine, a numbered review proxy, a frame-accurate
browser player, a three-state dependency panel, a server-side path picker and
a work folder that does not delete things behind the user's back.

That is roughly **2,500 lines of proven Python and 1,700 of front end**. The
original plan for this repo described rebuilding all of it, because the design
was written before anyone had read minicut. This file is the correction.

**Provenance:** `minicut-shot-detector` at commit `6dcbd60`
("Take the terminal's colour out of the answer, and the export with it",
2026-09-14), working tree clean.

---

## The three rules

**1. Nothing is ported that the task needing it does not use.** A module
arrives trimmed. The *Dropped* column below records the trim, so that what was
left behind is visible as a decision rather than looking like an oversight.
This is the whole point of the file: a copied foundation that brings three
features' worth of code with it is worse than writing the one feature's worth
by hand.

**2. Modernised on arrival.** minicut targets Python 3.11 and uses
`Optional[x]`, `List[x]`, `Dict[k, v]` and paths as `str`. This repo targets
3.12: `x | None`, `list[x]`, `dict[k, v]`, and `Path` wherever a path is held.
Converted as each file lands, not afterwards.

The cost is accepted deliberately: a ported file is no longer a byte-comparable
copy, so a fix found in minicut later has to be read across by hand rather than
diffed. That is the trade for one consistent style in this repo, and it is
affordable because this is a one-time lift with no intention of porting back.

**3. Every ported module says where it came from.** First line after the
module docstring's summary:

```
Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.
```

This is the one part that outlives this file. If a bug turns up in minicut's
`parse_filters` ffmpeg-8 handling, or in `player.js`'s frame-seek arithmetic,
that line is how a reader learns this repo carries the same code.

---

## Inventory

Percentages are estimates from reading the modules, not measurements. They are
here to say "expect to keep nearly all of this" or "expect to keep the shape
and rewrite the body", nothing finer.

### `src/core/`

| Module | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `ffmpeg_tools.py` | 285 | ~100% | Nothing. `versions()` gains MediaPipe and OpenCV | 1.5 |
| `utils.py` | 26 | ~100% | Nothing. It is one function | 1.5 |
| `timecode.py` | 318 | ~100% | Nothing. Drop-frame is not needed for a pass, but removing it is a change to tested arithmetic for no gain | 2.1 |
| `environment.py` | 542 | ~60% | The PySceneDetect check. The `SPLITTER` / `IDENTIFIER` tab split becomes `PERFORMANCE` alone | 1.6 |
| `templates.py` | 105 | ~70% | Nothing structural — the ffmpeg and Python install steps are identical. MediaPipe, OpenCV and `FAL_KEY` steps are new | 1.6 |
| `sidecar.py` | 93 | ~80% | The scenedetect version capture. Payload is this project's | 2.7 |
| `models.py` | 501 | **~40%** | Most of it. See below | 1.3 |
| `config.py` | 377 | ~25% | Every backend, CLI preset and identifier setting. The `Settings` load/save shape and the banner layout are what come across | 1.5 |

**`models.py` is the biggest bloat risk in the exercise.** This repo wants the
*shapes* of three models and none of the rest:

- **Take:** `SourceInfo` (as the field list, modernised), `ProbeReport`'s
  `can_* / refusal_reason / warnings` split, `ValidationResult`'s
  `passed / checks / failures` shape.
- **Leave:** `Boundary`, `Shot`, `PreparedJob`, `JobResult`, `ModelReply`,
  `Observation`, `Interpretation`, `NamingScheme`, `ProjectKnowledge`,
  `ShotListEntry`, `AttributeMatch`, `Candidate`, `ShotRecord` — roughly 300
  lines of splitter and identifier models with no counterpart here.

Do not copy this file and delete from it. Write this project's `models.py` and
take the three shapes as reference.

### `src/media/`

| Module | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `probe.py` | 401 | ~70% | **cropdetect entirely** — ~60 lines and two config constants. Letterboxing is information about a source you are going to *cut*; a depth pass never reshapes the picture. The disk estimate, VFR detection and frame-count fallback all stay | 2.1 |
| `mezzanine.py` | 203 | ~90% | Nothing. The encoder table, `-g 1` / `keyint=1` split and `verify()` all apply. Its *justification* changes — see ARCHITECTURE.md | 2.2 |
| `proxy.py` | 183 | ~95% | Nothing. Already builds exactly what non-negotiable 8 describes, including the font fallback and the libfreetype trap | 2.3 |
| `workspace.py` | 125 | ~90% | Nothing structural. `.minicut-work` → `.performance-work`, and the suffix list becomes this project's | 2.8 |
| `splitter.py` | 175 | **0%** | Cutting shots out of a mezzanine. No counterpart | — |

### `src/backends/`

Missed on the first pass of this file. ARCHITECTURE.md says this project's
backends follow "the same shape as minicut's model adapters", so the shape is
the thing being ported — the payload is entirely different. minicut's backends
move text to and from a language model; these move a video to a depth model and
a `.npz` back.

| Module | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `adapter.py` | 266 | ~40% | The prompt and reply handling. The interface, the dispatch and the "nothing above here knows which one ran" structure are what come across | 4.3 |
| `transport.py` | 90 | ~50% | Shape and the single-socket rule. A depth call uploads a video, polls a queue and fetches two files, which is not what this does today | 4.3 |
| `availability.py` | 171 | ~60% | Which LLM is reachable. The structure of asking "is this backend usable, and what do I tell the user if not" is the same question | 4.4 |
| `command.py` | 274 | 0% | Running a CLI tool as a model backend. No counterpart | — |
| `http_api.py` | 138 | 0% | Anthropic/OpenAI/Ollama dialects | — |
| `local.py` | 173 | 0% | A local LLM endpoint. The later local *depth* backend is new work, not this | — |

### `src/splitter/`

| Module | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `validator.py` | 345 | ~35% | Everything about shots. **Take only `_frame_hashes` and `_parse_framemd5`** — the `framemd5` machinery. `_compare_frame_hashes` came across too but its premise did not: depth cannot be hash-matched against its source. Reshaped into `find_stalled_frames`, which compares a file's *repeats* against its source's | 2.6 |
| `integrity.py` | 169 | 0% | Shot-list arithmetic | — |
| `reconcile.py`, `scene_detect.py`, `pipeline.py` | 608 | 0% | Shot detection | — |

### `src/ui/`

| Module | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `server.py` | 68 | **done** | Already in this repo. Its duplicated `# --- PAGE ---` banner was not copied | 1.2 ✔ |
| `runtime.py` | 22 | ~100% | Nothing. Also carries the reason it exists: it breaks the router↔app circular import | 1.6 |
| `browse.py` | 110 | ~100% | Nothing | 1.7 |
| `routes/files.py` | 37 | ~100% | Nothing | 1.7 |
| `routes/setup.py` | 236 | ~50% | Model-backend configuration. The environment and settings routes come across | 1.6 |
| `routes/splitter.py` | 223 | ~30% | Route *shape* only. Here it becomes prepare, run one pass, composite, output | 5.6 |
| `routes/identifier.py` | 424 | 0% | — | — |

### `src/ui/static/`

| File | Lines | Keep | Dropped, and why | Task |
|---|---|---|---|---|
| `styles.css` | 731 | ~85% | The identifier's table and column styles. Card layout, three-state panel, transport and timeline all come across | 1.4 → 5.4 |
| `index.html` | 565 | ~30% | Both old tabs' markup. The header, tab strip, card and status-strip *patterns* are the reference | 1.4 → 5.4 |
| `player.js` | 307 | ~70% | Boundary markers and `goToCut`. **Keep the frame maths exactly** — seek to the middle of a frame's duration, because `currentTime` after a seek does not land on a boundary and naive rounding drifts at 23.976. Markers become face seeds | 5.4 |
| `setup.js` | 249 | ~50% | Split across two tasks: the environment half at 1.6, the depth-backend half at 4.4 | 1.6 → 4.4 |
| `environment.js` | 213 | ~90% | Nothing structural | 1.6 |
| `source.js` | 201 | ~60% | Shot estimation display | 5.2 |
| `picker.js` | 114 | ~100% | Nothing | 1.7 |
| `work.js` | 99 | ~90% | Nothing structural | 5.8 |
| `main.js` | 88 | **done** | Already in this repo in miniature. Grows as listeners are added | 1.2 ✔ |
| `tabs.js` | 40 | ~100% | Already in this repo; `whenShown` is still to come | 1.2 ✔ |
| `state.js` | 37 | ~100% | Already in this repo as the empty shape | 1.2 ✔ |
| `ui.js` | 28 | ~100% | Nothing, but deferred: its only callers are `source.js` and the run flow, so porting it at 1.4 left an unreferenced module | 5.2 |
| `identify.js`, `columns.js`, `splitting.js` | 965 | 0% | — | — |

---

## Checklist

Ticked when the module is in this repo, trimmed, modernised, carrying its
provenance line, and covered by a test that runs.

- [x] **1.3** the three model shapes as reference — `models.py` is **not** copied
- [x] **1.4** `styles.css`, the `index.html` patterns, `tabs.js`'s `whenShown`
      — the shell and the look, early
- [x] **1.5** `ffmpeg_tools.py`, `utils.py`, the `config.py` shape
- [x] **1.6** `environment.py`, `templates.py`, `runtime.py`, `routes/setup.py`'s
      environment half, `environment.js`
- [x] **1.7** `browse.py`, `routes/files.py`, `picker.js`
- [x] **2.1** `probe.py` (no cropdetect), `timecode.py`
- [x] **2.2** `mezzanine.py`
- [x] **2.3** `proxy.py`
- [ ] **2.6** `validator.py`'s `framemd5` machinery only
- [ ] **2.7** `sidecar.py`
- [ ] **2.8** `workspace.py`
- [ ] **4.3** `adapter.py` and `transport.py` shapes
- [ ] **4.4** `availability.py`, the depth-backend half of `setup.js`
- [ ] **5.2** `source.js`, `ui.js`
- [ ] **5.4** `player.js`, the transport and timeline CSS
- [ ] **5.6** `routes/splitter.py` shape
- [ ] **5.8** `work.js`

When the last box is ticked: confirm every ported module has its provenance
line, check THIRD-PARTY.md records the port, and delete this file.
