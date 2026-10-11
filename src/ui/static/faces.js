/*
 * Choosing Faces.
 *
 * Drawing a box round someone, naming them, and marking them again wherever
 * the track breaks. What this produces is the selection — the whole interface
 * between the picker and the pipeline — so everything here is about getting
 * that right rather than about tracking, which knows nothing of this file.
 *
 * **Adding a seed to an existing face is the prominent action**, and that is
 * not a style choice. A face's colour belongs to the face, so someone who
 * walks out and comes back keeps their colour only if they are marked again
 * as the *same* face. Give the returning person a new face and they get a new
 * colour, and every prompt naming the old one is wrong. So each face carries
 * its own "mark again" button, sitting next to that face's name, and adding a
 * face at all is one button away from the list.
 *
 * Boxes are fractions of the picture, never pixels: the browser owns no
 * arithmetic about the source's real size, and a box drawn on the 640-wide
 * proxy has to mean the same thing on a 4K master.
 */

import { currentFrame, goToFrame } from "./player.js";
import { state } from "./state.js";

// Filled from the server so a swatch cannot disagree with the rendered mesh.
let palette = [[80, 160, 255]];

/** The hue a face will render in, by its position in the list. */
function hueFor(index) {
    return palette[index % palette.length];
}

function asCss(hue) {
    return `rgb(${hue.join(",")})`;
}

// --- THE SELECTION ---

/** A name not already taken, so two faces can never share one. */
function freeLabel() {
    const taken = new Set(state.faces.map((face) => face.label));

    for (let number = 1; ; number += 1) {
        const candidate = `Face ${number}`;
        if (!taken.has(candidate)) return candidate;
    }
}

/** Adds a face, seeded with the box just drawn. */
function addFace(box) {
    state.faces.push({ label: freeLabel(), seeds: [{ frame: currentFrame(), box }] });
    showFaces();

    // Focus the new name so it can be typed over straight away. A face
    // called "Face 2" is no use in a prompt.
    const inputs = document.querySelectorAll(".face-name");
    const last = inputs[inputs.length - 1];
    if (last) last.select();
}

/** Adds another seed to a face that already exists. */
function addSeed(index, box) {
    const face = state.faces[index];
    const frame = currentFrame();

    // One seed per frame per face. Drawing twice on the same frame is a
    // correction, not a second mark, and the model refuses duplicates
    // anyway — better to replace it here than be rejected later.
    face.seeds = face.seeds.filter((seed) => seed.frame !== frame);
    face.seeds.push({ frame, box });
    face.seeds.sort((first, second) => first.frame - second.frame);

    showFaces();
}

function removeFace(index) {
    state.faces.splice(index, 1);
    showFaces();
}

function removeSeed(faceIndex, frame) {
    const face = state.faces[faceIndex];

    // The last seed is what the face is: removing it would leave a face
    // with nothing to track from, which the model refuses.
    if (face.seeds.length === 1) {
        removeFace(faceIndex);
        return;
    }

    face.seeds = face.seeds.filter((seed) => seed.frame !== frame);
    showFaces();
}

// --- WHAT IS ON SCREEN ---

/** Rebuilds the face list, and the boxes drawn over the picture. */
export function showFaces() {
    const list = document.getElementById("face-list");
    list.replaceChildren();

    if (!state.faces.length) {
        const empty = document.createElement("li");
        empty.className = "face";
        empty.innerHTML =
            '<span class="face-label">No faces yet</span>' +
            '<span class="face-seeds">Draw a box round someone to add one.</span>';
        list.append(empty);
    }

    state.faces.forEach((face, index) => {
        list.append(faceRow(face, index));
    });

    showBoxes();
}

/** One face: its colour, its name, its seeds, and what can be done to it. */
function faceRow(face, index) {
    const row = document.createElement("li");
    row.className = "face selectable";
    row.classList.toggle("chosen", index === state.chosenFace);
    row.addEventListener("click", () => {
        state.chosenFace = index;
        showFaces();
    });

    const swatch = document.createElement("span");
    swatch.className = "face-swatch";
    swatch.style.background = asCss(hueFor(index));
    swatch.title = "The colour this face's mesh renders in";

    const name = document.createElement("input");
    name.className = "face-name";
    name.value = face.label;
    name.addEventListener("click", (event) => event.stopPropagation());
    name.addEventListener("change", () => {
        const wanted = name.value.trim();
        const taken = state.faces.some((other, at) => at !== index && other.label === wanted);

        // Labels key the report, the layer and the landmarks file, so two
        // faces sharing one would silently lose a person.
        if (!wanted || taken) {
            name.value = face.label;
            return;
        }

        face.label = wanted;

        // Repaint, so the tag on the box over the picture renames with it.
        // `change` fires on blur, so rebuilding the list here cannot
        // interrupt typing.
        showFaces();
    });

    const label = document.createElement("span");
    label.className = "face-label";
    label.append(swatch, name);

    const detail = document.createElement("span");
    detail.className = "face-seeds";
    detail.append(seedList(face, index), faceButtons(index));

    row.append(label, detail);
    return row;
}

/** The frames this face is marked on, each one a way back to that frame. */
function seedList(face, faceIndex) {
    const seeds = document.createElement("span");
    seeds.className = "seed-chips";

    for (const seed of face.seeds) {
        const chip = document.createElement("button");
        chip.className = "chip";
        chip.textContent = String(seed.frame);
        chip.title = `Go to frame ${seed.frame}`;
        chip.addEventListener("click", (event) => {
            event.stopPropagation();
            goToFrame(seed.frame);
        });

        const drop = document.createElement("button");
        drop.className = "chip-remove";
        drop.textContent = "×";
        drop.title = face.seeds.length === 1 ? "Remove this face" : "Remove this seed";
        drop.addEventListener("click", (event) => {
            event.stopPropagation();
            removeSeed(faceIndex, seed.frame);
        });

        const held = document.createElement("span");
        held.className = "chip-pair";
        held.append(chip, drop);
        seeds.append(held);
    }

    return seeds;
}

/** Mark again, and remove. The first is the one that matters. */
function faceButtons(index) {
    const holder = document.createElement("span");
    holder.className = "face-actions";

    const again = document.createElement("button");
    again.className = "secondary";
    again.textContent = "Mark again here";
    again.title =
        "Draw a new box for this face on the frame on screen — the same person, " +
        "so they keep their colour";
    again.addEventListener("click", (event) => {
        event.stopPropagation();
        state.chosenFace = index;
        state.drawingFor = index;
        showFaces();
        armDrawing();
    });

    const drop = document.createElement("button");
    drop.className = "secondary danger";
    drop.textContent = "Remove";
    drop.addEventListener("click", (event) => {
        event.stopPropagation();
        removeFace(index);
    });

    holder.append(again, drop);
    return holder;
}

/** Draws every face's box for the frame on screen, over the picture. */
export function showBoxes() {
    const overlay = document.getElementById("draw-overlay");
    overlay.replaceChildren();

    if (!state.source) return;
    const frame = currentFrame();

    state.faces.forEach((face, index) => {
        const seed = face.seeds.find((each) => each.frame === frame);
        if (!seed) return;

        const drawn = document.createElement("div");
        drawn.className = "seed-box";
        drawn.style.borderColor = asCss(hueFor(index));
        drawn.style.left = `${seed.box.left * 100}%`;
        drawn.style.top = `${seed.box.top * 100}%`;
        drawn.style.width = `${(seed.box.right - seed.box.left) * 100}%`;
        drawn.style.height = `${(seed.box.bottom - seed.box.top) * 100}%`;

        const tag = document.createElement("span");
        tag.className = "seed-tag";
        tag.style.background = asCss(hueFor(index));
        tag.textContent = face.label;
        drawn.append(tag);

        overlay.append(drawn);
    });
}

// --- DRAWING ---

/** Puts the overlay into "the next drag is a box" mode. */
function armDrawing() {
    const overlay = document.getElementById("draw-overlay");
    overlay.classList.add("armed");

    document.getElementById("draw-hint").textContent =
        state.drawingFor === null
            ? "Drag a box round a face."
            : `Drag a box round ${state.faces[state.drawingFor].label} on this frame.`;
    document.getElementById("draw-hint").hidden = false;
}

function disarmDrawing() {
    document.getElementById("draw-overlay").classList.remove("armed");
    document.getElementById("draw-hint").hidden = true;
    state.drawingFor = null;
}

/** Wires the overlay. Called once, from main.js. */
export function wireFaces() {
    const overlay = document.getElementById("draw-overlay");
    let start = null;
    let rubber = null;

    const asFraction = (event) => {
        const bounds = overlay.getBoundingClientRect();
        return {
            x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
            y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
        };
    };

    overlay.addEventListener("pointerdown", (event) => {
        if (!overlay.classList.contains("armed")) return;

        overlay.setPointerCapture(event.pointerId);
        start = asFraction(event);

        rubber = document.createElement("div");
        rubber.className = "seed-box drawing";
        overlay.append(rubber);
    });

    overlay.addEventListener("pointermove", (event) => {
        if (!start || !rubber) return;

        const now = asFraction(event);
        rubber.style.left = `${Math.min(start.x, now.x) * 100}%`;
        rubber.style.top = `${Math.min(start.y, now.y) * 100}%`;
        rubber.style.width = `${Math.abs(now.x - start.x) * 100}%`;
        rubber.style.height = `${Math.abs(now.y - start.y) * 100}%`;
    });

    overlay.addEventListener("pointerup", (event) => {
        if (!start) return;

        const end = asFraction(event);
        const box = {
            left: Math.min(start.x, end.x),
            top: Math.min(start.y, end.y),
            right: Math.max(start.x, end.x),
            bottom: Math.max(start.y, end.y),
        };

        start = null;
        rubber = null;

        // A click is not a box. The model refuses a zero-sized one, and a
        // stray click while armed should do nothing rather than fail.
        const tooSmall = box.right - box.left < 0.01 || box.bottom - box.top < 0.01;
        if (tooSmall) {
            showBoxes();
            return;
        }

        if (state.drawingFor === null) {
            addFace(box);
        } else {
            addSeed(state.drawingFor, box);
        }

        disarmDrawing();
    });

    // "Add a face" is the only global draw button. Marking an existing face
    // again is per face, next to that face's name — see the module note.
    document.getElementById("face-add").addEventListener("click", () => {
        state.drawingFor = null;
        armDrawing();
    });

    // Boxes belong to a frame, so they come and go as the frame changes.
    document.getElementById("proxy-player").addEventListener("seeked", showBoxes);
    document.getElementById("proxy-player").addEventListener("timeupdate", showBoxes);

    loadPalette();
}

/**
 * Fetches the hues the renderer will actually use.
 *
 * Notes:
 *     **Redraws when it lands.** The page renders before this returns, so
 *     without the repaint every face keeps the fallback blue until
 *     something else happens to trigger a render — which is a swatch
 *     quietly disagreeing with the mesh, the one thing a swatch must not
 *     do.
 *
 *     A failure is logged rather than swallowed. The fallback is the first
 *     of the palette, so one face would look right and the rest wrong,
 *     which is worse than an obvious problem.
 */
async function loadPalette() {
    try {
        const response = await fetch("/api/mesh-palette");
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);

        palette = await response.json();
        showFaces();
    } catch (error) {
        console.warn(
            `Could not read the mesh palette, so face colours may not match ` +
            `what is rendered: ${error.message}`
        );
    }
}
