/*
 * Wiring.
 *
 * The one module the page loads. Everything else is imported from here, and
 * nothing else attaches a listener — so the answer to "what happens when this
 * is clicked" is always in this file.
 */

import { showTab } from "./tabs.js";

document.addEventListener("DOMContentLoaded", () => {
    for (const button of document.querySelectorAll(".tab")) {
        button.addEventListener("click", () => showTab(button.dataset.tab));
    }
});
