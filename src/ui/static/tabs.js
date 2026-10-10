/*
 * Tab Switching.
 *
 * Shows one panel and hides the rest, and tells the tab being opened that it is
 * now visible, so it can load what it needs at that moment rather than on page
 * load.
 */

import { state } from "./state.js";

// Called when a tab becomes visible. Registered rather than imported here, so
// this module stays about switching and knows nothing about what a tab does.
const onShow = {};

/** Runs `handler` every time a tab is opened. */
export function whenShown(name, handler) {
    onShow[name] = handler;
}

/** Shows one tab and hides the rest. */
export function showTab(name) {
    for (const panel of document.querySelectorAll(".tab-panel")) {
        panel.classList.toggle("active", panel.id === name);
    }

    for (const button of document.querySelectorAll(".tab")) {
        button.classList.toggle("active", button.dataset.tab === name);
    }

    state.activeTab = name;
    onShow[name]?.();
}
