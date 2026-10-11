/*
 * The Review Player.
 *
 * Ported from minicut-shot-detector and trimmed: this one carries no shot
 * markers and no cut-to-cut navigation, because there are no cuts here — a
 * performance pass is one shot.
 *
 * Everything counts in frames. The proxy carries its frame number burned into
 * the picture, so the readout can be checked against it by eye, which is the
 * one thing a frame-accurate player has to get right.
 */

import { state } from "./state.js";

/*
 * Frames, not seconds.
 *
 * The proxy is all-intra, so the browser can seek to any frame exactly. The
 * awkward direction is reading back: `currentTime` after a seek is a float
 * that does not land cleanly on a frame boundary, and at 24000/1001 rounding
 * it the obvious way drifts.
 *
 * So we seek to the MIDDLE of a frame's duration, where there is most room
 * either side, and read it back the same way. The number burned into the
 * picture is the check: if the readout and the picture disagree, this is
 * wrong, and it is wrong visibly rather than silently.
 */

/** The source's exact rate as a number. The rational itself lives on the server. */
function frameRate() {
    const source = state.source;
    return source ? source.fps_numerator / source.fps_denominator : 24;
}

/** The last frame of the source. */
function lastFrame() {
    return state.source ? state.source.frame_count - 1 : 0;
}

/** The moment at which a frame is unambiguously on screen. */
function secondsForFrame(frame) {
    return (frame + 0.5) / frameRate();
}

function video() {
    return document.getElementById("proxy-player");
}

/** The frame currently on screen. */
export function currentFrame() {
    return Math.max(0, Math.min(Math.floor(video().currentTime * frameRate()), lastFrame()));
}

/** Moves to a frame, clamped to the source. */
export function goToFrame(frame) {
    const target = Math.max(0, Math.min(Math.round(frame), lastFrame()));
    video().currentTime = secondsForFrame(target);
    return target;
}

/** Steps by whole frames, pausing first — stepping while playing is meaningless. */
export function stepFrames(count) {
    video().pause();
    return goToFrame(currentFrame() + count);
}

// --- WHAT THE PAGE SHOWS ---

/** Repaints the frame readout and the scrubber from the video's own position. */
function showPosition() {
    if (!state.source) return;

    const frame = currentFrame();
    document.getElementById("player-frame").textContent =
        `${frame} / ${lastFrame()}`;

    const scrub = document.getElementById("player-scrub");
    if (document.activeElement !== scrub) scrub.value = String(frame);
}

/**
 * Points the player at a source's proxy and makes the transport usable.
 *
 * Notes:
 *     Called when a source turns out to be prepared — on inspecting one that
 *     already is, and after preparing one that was not.
 */
export function openProxy(source) {
    state.source = source;

    const player = video();
    player.src = `/api/proxy?path=${encodeURIComponent(state.sourcePath)}`;
    player.load();

    const scrub = document.getElementById("player-scrub");
    scrub.max = String(lastFrame());
    scrub.value = "0";
    scrub.disabled = false;

    for (const button of document.querySelectorAll("[data-step-frames]")) {
        button.disabled = false;
    }

    document.getElementById("player-shell").hidden = false;
    document.getElementById("player-missing").hidden = true;

    // Nothing can be drawn on until there is a frame to draw on.
    document.getElementById("face-add").disabled = false;

    showPosition();
}

/** Says the proxy is not there yet, rather than showing a dead player. */
export function closeProxy(message) {
    state.source = null;
    document.getElementById("player-shell").hidden = true;
    document.getElementById("face-add").disabled = true;

    const missing = document.getElementById("player-missing");
    missing.textContent = message;
    missing.hidden = false;
}

/** Wires the transport. Called once, from main.js. */
export function wirePlayer() {
    const player = video();

    // Both events, because a seek lands without timeupdate firing and
    // playback moves without seeking. Between them the readout never lags
    // the picture, which is the only thing it is for.
    player.addEventListener("timeupdate", showPosition);
    player.addEventListener("seeked", showPosition);

    document.getElementById("player-scrub").addEventListener("input", (event) => {
        player.pause();
        goToFrame(Number(event.target.value));
    });

    for (const button of document.querySelectorAll("[data-step-frames]")) {
        button.addEventListener("click", () =>
            stepFrames(Number(button.dataset.stepFrames))
        );
    }

    // Arrow keys step, space plays. Only while the Faces step is open and
    // nothing is being typed into, so they cannot steal a keystroke meant
    // for a path or a face's name.
    document.addEventListener("keydown", (event) => {
        if (state.activeStep !== "faces" || !state.source) return;
        if (event.target.matches("input, textarea")) return;

        const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: 10, ArrowDown: -10 };

        if (event.key in steps) {
            event.preventDefault();
            stepFrames(steps[event.key]);
        } else if (event.key === " ") {
            event.preventDefault();
            player.paused ? player.play() : player.pause();
        }
    });
}
