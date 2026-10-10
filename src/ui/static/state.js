/*
 * Shared UI State.
 *
 * Everything the front end knows, in one object so it is obvious what exists.
 * Modules import it and read it directly rather than passing it down: there is
 * one page, showing one job, at a time.
 *
 * Grouped by tab, then by step. A field belongs to whichever step uses it, and
 * the shared section stays small.
 */

export const state = {
    // --- SHARED ---
    activeTab: "performance",  // The tab currently shown

    // --- PERFORMANCE PASS ---
    activeStep: "source",      // The step currently shown
    sourcePath: "",            // The footage to build a pass from

    // Where each step has got to: todo, running or done. The strip reads this,
    // and it is the one place that knows whether a pass has been run — a
    // layer in the stack is only usable once its step says done.
    steps: {
        source: "todo",
        depth: "todo",
        faces: "todo",
        composite: "todo",
    },

    // --- PATH PICKER ---
    pickerMode: "",            // "source" picks a video file

    // --- SETUP ---
};
