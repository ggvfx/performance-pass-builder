/*
 * Tab Switching.
 *
 * Ported from minicut-shot-detector (6dcbd60).
 *
 * Switching shows one panel and hides the other, and tells the tab being
 * opened that it is now visible so it can load whatever it needs at that
 * moment rather than on page load.
 */

// Called when a tab becomes visible. Registered rather than imported here, so
// this module stays about switching and knows nothing about what a tab does.
const onShow = {};

/** Runs `handler` the first time a tab is opened, and on every open after. */
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

    onShow[name]?.();
}

/** Wires every tab button. Called once, from main.js. */
export function wireTabs() {
    for (const button of document.querySelectorAll(".tab")) {
        button.addEventListener("click", () => showTab(button.dataset.tab));
    }
}
