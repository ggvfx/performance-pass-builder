/*
 * The Step Strip.
 *
 * Four steps — Source, Depth, Faces, Composite — each holding its own
 * settings, its own process button and its own result.
 *
 * Every step is reachable from the start. A step that needs something earlier
 * says so in its own panel rather than being locked: someone opening the app
 * for the first time should be able to see the shape of the job, and a dead
 * click with no explanation teaches them nothing.
 *
 * The same `whenShown` idea as tabs.js, kept separate because a step carries
 * state that a tab does not — a tab is a place, a step is a piece of work
 * that has or has not been done.
 */

import { state } from "./state.js";

// What a step's state marker says, and the colour it reads in. Keyed by the
// state names in state.js.
const WORDING = {
    source: { todo: "Not prepared", running: "Preparing…", done: "Prepared" },
    depth: { todo: "Not run", running: "Processing…", done: "Done" },
    faces: { todo: "Not run", running: "Tracking…", done: "Done" },
    composite: { todo: "Nothing to combine", running: "Writing…", done: "Written" },
};

// Called when a step becomes visible, so it can load what it shows then
// rather than on page load. Registered rather than imported, so this module
// stays about the strip and knows nothing about what a step does.
const onShow = {};

/** Runs `handler` every time a step is opened. */
export function whenStepShown(name, handler) {
    onShow[name] = handler;
}

/** Shows one step and hides the rest. */
export function showStep(name) {
    state.activeStep = name;

    for (const panel of document.querySelectorAll(".step-panel")) {
        panel.classList.toggle("active", panel.id === `step-${name}`);
    }

    for (const button of document.querySelectorAll(".step")) {
        button.classList.toggle("active", button.dataset.step === name);
    }

    onShow[name]?.();
}

/**
 * Records what state a step is in, and shows it on the strip.
 *
 * @param {string} name - source, depth, faces or composite.
 * @param {string} value - todo, running or done.
 */
export function setStepState(name, value) {
    state.steps[name] = value;

    const button = document.querySelector(`.step[data-step="${name}"]`);
    if (!button) return;

    button.dataset.state = value;
    button.querySelector(".step-state").textContent = WORDING[name]?.[value] ?? value;
}

/** Wires every step button and paints the initial states. Called once, from main.js. */
export function wireSteps() {
    for (const button of document.querySelectorAll(".step")) {
        button.addEventListener("click", () => showStep(button.dataset.step));
    }

    for (const [name, value] of Object.entries(state.steps)) {
        setStepState(name, value);
    }
}
