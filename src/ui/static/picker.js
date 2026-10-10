/*
 * Path Picker.
 *
 * Ported from minicut-shot-detector (6dcbd60).
 *
 * Browses the machine through the server rather than the browser, so choosing
 * a multi-gigabyte source never uploads anything.
 */

import { state } from "./state.js";

/**
 * Opens the picker.
 * @param {string} mode - "source" picks a video file, "output" picks a folder.
 */
export async function openPicker(mode) {
    state.pickerMode = mode;
    document.getElementById("picker").showModal();
    await showDirectory("");
}

/**
 * Lists a directory in the picker.
 * @param {string} path - Empty string asks the server for the home folder.
 */
async function showDirectory(path) {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    if (state.pickerMode === "source") params.set("videos_only", "true");

    const response = await fetch(`/api/browse?${params}`);
    if (!response.ok) return;

    const listing = await response.json();

    document.getElementById("picker-path").textContent = listing.path;
    renderRoots(listing.roots);
    renderEntries(listing);
}

/** Draws the drive letter shortcuts. */
function renderRoots(roots) {
    const container = document.getElementById("picker-roots");
    container.replaceChildren();

    for (const root of roots) {
        const button = document.createElement("button");
        button.className = "secondary";
        button.textContent = root;
        button.addEventListener("click", () => showDirectory(root));
        container.append(button);
    }
}

/** Draws the directory contents, with a row to step back up. */
function renderEntries(listing) {
    const list = document.getElementById("picker-entries");
    list.replaceChildren();

    if (listing.parent) {
        const up = document.createElement("li");
        up.className = "entry directory";
        up.textContent = "↑ Up one level";
        up.addEventListener("click", () => showDirectory(listing.parent));
        list.append(up);
    }

    for (const entry of listing.entries) {
        const row = document.createElement("li");
        row.className = `entry ${entry.is_directory ? "directory" : "file"}`;
        row.textContent = entry.name;

        if (entry.is_directory) {
            row.addEventListener("click", () => showDirectory(entry.path));
        } else if (state.pickerMode === "source") {
            row.addEventListener("click", () => choosePath(entry.path));
        }

        list.append(row);
    }
}

/** Accepts a path from the picker and closes it. */
export function choosePath(path) {
    // One entry per picker button, so adding a third is a line here rather
    // than another branch in a chain of ifs
    const accept = {
        source: () => {
            state.sourcePath = path;
            document.getElementById("source-path").value = path;
        },
    };

    accept[state.pickerMode]?.();
    document.getElementById("picker").close();
}
