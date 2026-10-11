/*
 * Wiring.
 *
 * The one module the page loads, and where every element that is written in
 * index.html gets its listener — so for anything on the page, the answer to
 * "what happens when this is clicked" is in this file.
 *
 * A module that BUILDS elements wires what it builds, because nothing else
 * can: picker.js attaches to rows it creates per directory, and
 * environment.js to the fix buttons it creates per failing check. The rule is
 * about static markup, which is where hunting for a handler is otherwise
 * genuinely hard.
 */

import { loadEnvironment } from "./environment.js";
import { wirePerformance } from "./performance.js";
import { openPicker } from "./picker.js";
import { state } from "./state.js";
import { wireSteps } from "./steps.js";
import { whenShown, wireTabs } from "./tabs.js";

document.addEventListener("DOMContentLoaded", () => {
    wireTabs();
    wireSteps();
    wirePerformance();

    // The strip on the workflow tab is the answer to "can I start?", so it is
    // filled on load rather than when Setup is first opened.
    loadEnvironment();

    // Each tab loads what it shows when it is opened, not on page load.
    whenShown("setup", () => loadEnvironment());

    document.getElementById("recheck-button")
        .addEventListener("click", () => loadEnvironment(true));

    // --- PATH PICKER ---

    for (const button of document.querySelectorAll("[data-picker]")) {
        button.addEventListener("click", () => openPicker(button.dataset.picker));
    }

    document.getElementById("picker-close")
        .addEventListener("click", () => document.getElementById("picker").close());

    // Typed paths are as valid as picked ones
    document.getElementById("source-path")
        .addEventListener("change", (event) => { state.sourcePath = event.target.value; });
});
