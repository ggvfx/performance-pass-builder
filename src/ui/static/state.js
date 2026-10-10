/*
 * Shared UI State.
 *
 * Everything the front end knows, in one object so it is obvious what exists.
 * Modules import it and read it directly rather than passing it down: there is
 * one page, showing one job, at a time.
 *
 * Grouped by tab. A field belongs to whichever tab uses it, and the shared
 * section stays small.
 */

export const state = {
    // --- SHARED ---
    activeTab: "performance",  // The tab currently shown

    // --- PERFORMANCE PASS ---
    sourcePath: "",       // The footage to build a pass from

    // --- PATH PICKER ---
    pickerMode: "",       // "source" picks a video file
    pickerPath: "",       // The directory currently shown

    // --- SETUP ---
};
