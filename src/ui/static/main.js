/*
 * Wiring.
 *
 * The one module the page loads. Everything else is imported from here, and
 * nothing else attaches a listener — so the answer to "what happens when this
 * is clicked" is always in this file.
 */

import { wireTabs } from "./tabs.js";

document.addEventListener("DOMContentLoaded", () => {
    wireTabs();

    // Each tab loads what it shows when it is opened, not on page load.
    // Registrations join here as the tabs gain something to load: the
    // environment panel at 1.6, the backend rows at 4.4.
});
