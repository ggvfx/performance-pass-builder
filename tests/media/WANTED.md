# Test footage wanted

A gathering list. Nothing here is committed — drop the files in
`tests/media/` and they stay out of git. See `README.md` in this folder for
how the fixtures pick them up.

**Tiers are priority, not difficulty.** Tier 1 is what Phase 3 needs to be
honest work. Everything below it is the difference between a tool that works
and a tool that works on somebody else's footage.

## How to make them

**5 to 15 seconds is plenty.** Longer wastes disk and test time, and nothing
here needs a performance.

**Three ways to get one, and they are not interchangeable:**

- **Generate it** — fine for framing, head pose, number of people,
  expression. Most of tiers 1 and 2.
- **Shoot it** — needed for anything about lighting, grain, compression or
  motion blur. A generated clip is too clean to prove the tool survives a
  real one. A phone is fine.
- **Transcode something you already have** — the right way to make tier 4.
  Do not go looking for 23.976 footage; take a clip you have and re-wrap it.
  Commands are given for those.

**Name by what is in it, not where it came from** — `two_faces_crossing.mp4`,
not `Scientist_recording_20261010.mp4`. Lowercase, underscores.

---

## Tier 1 — Phase 3 cannot honestly be finished without these

Each of these is a thing the app claims to do.

- [x] **`one_face_medium.mp4`** — one person, medium close-up, frontal,
      evenly lit, near-static camera. *Have it.* **Proves:** detection, one
      track running the length of a shot, landmarks that stay put.
- [ ] **`two_faces_separated.mp4`** — two people, both facing camera, clearly
      apart, neither moving much. **Proves:** two tracks exist and stay
      distinct. Must work before crossing is worth attempting.
- [ ] **`two_faces_crossing.mp4`** — two people who pass in front of one
      another and separate again. **Proves:** identity survives occlusion.
      *The single most valuable clip on this list* — it is where trackers
      swap people, and nothing else catches it.
- [ ] **`face_leaves_and_returns.mp4`** — one person walks out of frame and
      back in. **Proves:** the same person keeps their track rather than
      quietly becoming a second one.
- [ ] **`profile_turn.mp4`** — frontal, turn to full 90° profile, hold, turn
      back. **Proves:** where landmarks degrade, and that the degradation is
      *reported* rather than silently wrong.
- [ ] **`face_small_wide.mp4`** — wide shot, face roughly 5–10% of frame
      height. **Proves:** the detection floor, and whether the search box
      earns its place.
- [ ] **`moving_camera_handheld.mp4`** — handheld follow, moderate shake, one
      subject. **Proves:** tracking is not quietly relying on a locked-off
      frame. Shoot this one; generated camera shake is too regular.

## Tier 2 — robustness, before anyone else uses it

### More faces

- [ ] **`three_faces_group.mp4`** — three or more people. **Proves:**
      selection and the UI hold up past two, and tracking cost scales the way
      we think.
- [ ] **`two_faces_near_and_far.mp4`** — one person close, one well behind.
      **Proves:** face size and depth range varying at once — the case where
      one window setting cannot flatter both.

### Framing

- [ ] **`face_big_closeup.mp4`** — face fills frame, edges of the head
      cropped. **Proves:** landmarks running past the frame edge are handled
      rather than clamped into nonsense.
- [ ] **`face_tiny_very_wide.mp4`** — face under 5% of frame height.
      **Proves:** where it gives up, and that giving up is explicit. A clip
      that is *meant* to fail.

### Head pose

- [ ] **`head_pitch_up_down.mp4`** — looking up to the ceiling, down to the
      floor. **Proves:** the vertical extremes, handled worse by most
      trackers than horizontal.
- [ ] **`head_roll_tilt.mp4`** — ear toward shoulder, both ways. **Proves:**
      rotation the mesh has to follow rather than average out.
- [ ] **`turns_fully_away.mp4`** — shows the back of the head, holds, turns
      back. **Proves:** clean track loss and recovery. Distinct from the
      profile turn: there is genuinely no face for a stretch.
- [ ] **`fast_head_turn.mp4`** — a snap turn with motion blur. **Proves:**
      detection surviving blur, and whether a gap is interpolated or
      reported.

### Occlusion

- [ ] **`hand_across_face.mp4`** — a hand passes over the face. **Proves:**
      brief partial occlusion does not end the track.
- [ ] **`emerges_from_behind.mp4`** — steps out from behind a door or pillar.
      **Proves:** a face appearing mid-shot is picked up.
- [ ] **`late_entry.mp4`** — frame starts empty, someone walks in after a few
      seconds. **Proves:** seeding does not assume frame 0 holds the subject.
      *Catches a real class of bug* — tracking that only ever starts at the
      beginning.

### Worn and grown

- [ ] **`glasses_clear.mp4`** — ordinary glasses with some reflection.
      **Proves:** eye landmarks through lenses.
- [ ] **`sunglasses.mp4`** — dark glasses. **Proves:** what happens when the
      irises are not visible at all. The refined model returns 10 iris points
      that cannot be real here, and we should know what it does with them.
- [ ] **`hat_shadow.mp4`** — cap or brim throwing shadow across the eyes.
      **Proves:** the most common real partial occlusion on set.
- [ ] **`covered_mouth.mp4`** — scarf, mask or hand over the lower face.
      **Proves:** half a mesh, and whether that is flagged.
- [ ] **`hair_across_face.mp4`** — long hair blowing or falling across.
      **Proves:** intermittent, ragged occlusion, which is harder than a
      clean block.

### Lighting

Shoot these. Generated footage is worst at exactly this category.

- [ ] **`low_light.mp4`** — underexposed, noisy, maybe one practical lamp.
      **Proves:** detection in grain.
- [ ] **`backlit_silhouette.mp4`** — window or sun behind the subject, face in
      shadow. **Proves:** the most common difficult real lighting, and one
      depth models also struggle with.
- [ ] **`hard_side_light.mp4`** — half the face lit, half in darkness.
      **Proves:** landmarks across a hard shadow line.
- [ ] **`flickering_light.mp4`** — firelight, a screen, a failing practical.
      **Proves:** frame-to-frame brightness change does not make the track
      jitter. *Also the best natural test for stall detection* — a stalled
      model is obvious when every frame should differ.
- [ ] **`mixed_colour_light.mp4`** — competing colour temperatures, neon or
      practicals. **Proves:** no reliance on neutral skin tone.

### Expression

- [ ] **`big_expressions.mp4`** — laughing, shouting, mouth wide, eyes
      squeezed shut. **Proves:** the mesh deforms rather than holding a
      neutral face. *The one that matters most for the actual product* — a
      performance pass exists to carry expression, and a mesh that averages
      it away is worthless however well it tracks.
- [ ] **`eyes_closed.mp4`** — sustained closed eyes and slow blinks.
      **Proves:** eyelid landmarks, and that closed eyes are not read as a
      lost face.

## Tier 3 — depth, since it is half the output

The depth pass has its own failure modes, and no clip above is chosen for
them.

- [ ] **`deep_scene.mp4`** — subject close, background far off: a corridor or
      a street. **Proves:** the windowing feature. Compressing 0–1 onto the
      range you care about is pointless without a scene that has range.
- [ ] **`flat_scene.mp4`** — subject against a close wall. **Proves:** the
      opposite — a near-empty depth range that must not be stretched into
      false contrast.
- [ ] **`subject_moves_to_camera.mp4`** — walking toward or away from the
      lens. **Proves:** depth changing across the shot, and whether a fixed
      window holds up or needs to follow. *Likely to expose a real design
      question rather than a bug.*
- [ ] **`glass_and_reflections.mp4`** — a window, mirror or glass partition.
      **Proves:** where monocular depth is simply wrong, so the app does not
      present a confident wrong answer.
- [ ] **`face_in_mirror.mp4`** — a real face and its reflection both visible.
      **Proves:** two faces detected where there is one person. A selection
      problem rather than a tracking one, and worth knowing before a user
      meets it.

## Tier 4 — format and technical

**Make these by transcoding, not by filming.** Take any clip you have.

- [ ] **`rate_23976.mp4`** — 24000/1001. **Proves:** the exact rate this
      project exists to handle, on real content.
      `ffmpeg -i in.mp4 -r 24000/1001 -c:v libx264 rate_23976.mp4`
- [ ] **`rate_5994.mp4`** — high frame rate. **Proves:** frame counts at
      double rate, and the slowest thing the tracker will meet.
      `ffmpeg -i in.mp4 -r 60000/1001 -c:v libx264 rate_5994.mp4`
- [ ] **`vertical_9x16.mp4`** — portrait, phone-shaped. **Proves:** the UI,
      the mesh and the composite do not assume landscape. *Easy to forget and
      very visible when wrong.* Shoot on a phone, or crop.
- [ ] **`anamorphic_2391.mp4`** — wide aspect, ideally non-square pixels.
      **Proves:** pixel aspect is carried rather than silently squashed.
- [ ] **`log_flat_profile.mp4`** — ungraded log or a flat picture profile.
      **Proves:** detection on low-contrast footage, which is what comes off
      a real camera before anyone grades it.
- [ ] **`heavily_compressed.mp4`** — low bitrate, visible blocking.
      **Proves:** survival on footage that has been through a messaging app.
      `ffmpeg -i in.mp4 -b:v 300k -c:v libx264 heavily_compressed.mp4`
- [ ] **`four_k.mp4`** — 3840×2160. **Proves:** memory and timing at the
      resolution people actually shoot. *Expect this to be the clip that
      makes Prepare feel slow* — better to know before a user does.
- [ ] **`long_two_minutes.mp4`** — 2 minutes or more. **Proves:** nothing
      leaks or drifts over length, and gives stall detection something real
      to run on. The only clip here allowed to be large.
- [ ] **`very_short.mp4`** — a handful of frames. **Proves:** the edge case
      where ranges and windows go wrong.
      `ffmpeg -i in.mp4 -frames:v 5 -c:v libx264 very_short.mp4`
- [ ] **`no_audio.mp4`** — video only. **Proves:** the `NONE` audio path on
      real footage.
      `ffmpeg -i in.mp4 -an -c:v copy no_audio.mp4`
- [ ] **`pcm_audio.mov`** — 24-bit PCM, as a camera records it. **Proves:**
      the one lossy audio step, which has to be announced three times.
      `ffmpeg -i in.mp4 -c:v copy -c:a pcm_s24le pcm_audio.mov`

## Tier 5 — should fail, and fail well

Clips that exist to prove the app refuses cleanly instead of crashing or
inventing an answer.

- [ ] **`no_face_at_all.mp4`** — an empty room, a landscape, anything with no
      person. **Proves:** "no faces found" is a clear message, not an
      exception and not an empty track.
- [ ] **`face_in_a_poster.mp4`** — a photograph or poster of a face on a
      wall, no real person. **Proves:** a false positive is selectable and
      dismissable rather than silently tracked.
- [ ] **`variable_frame_rate.mp4`** — VFR, as screen recorders produce.
      **Proves:** the refusal fires on real VFR, not only the generated case.
      Easiest to get by screen-recording anything.
- [ ] **`not_a_video.txt`** — any text file renamed. **Proves:** the probe
      refuses rather than crashes. Costs nothing to make.

---

## What is already covered without footage

Not on this list because `tests/conftest.py` generates them and they need no
face: constant frame rates (24, 25, 24000/1001), stream-copyable and
non-copyable audio, h265 sources, variable frame rate refusal, and files with
no video stream. Do not go gathering those.
