/*
 * The Performance Pass Steps.
 *
 * Inspect and prepare on the Source step, track on the Faces step. The first
 * part of this app that drives the real pipeline rather than describing it.
 *
 * Preparing and tracking take tens of seconds, so the server runs them as
 * jobs and this polls. Every long action goes through `runJob`, which is what
 * keeps the bar, the message and the button state behaving the same way
 * wherever they appear.
 */

import { setStepState } from "./steps.js";
import { state } from "./state.js";

// How often to ask a running job how it is doing. Fast enough that the bar
// moves, slow enough that a two-minute track is not thousands of requests.
const POLL_MS = 400;

/**
 * The footage path, read from the field rather than from state.
 *
 * state.sourcePath is kept up to date by a `change` listener, which only
 * fires when the field loses focus — so typing a path and clicking Inspect
 * straight away used to read an empty string and say "choose some footage"
 * with the path visibly in the box. The field is the truth; state follows it.
 */
function sourcePath() {
    const typed = document.getElementById("source-path").value.trim();
    state.sourcePath = typed;
    return typed;
}

/** POSTs JSON and returns the parsed body, throwing the server's own message. */
async function post(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.detail || `${response.status} ${response.statusText}`);
    }
    return data;
}

/**
 * Starts a job and follows it to the end.
 *
 * Resolves with the finished job's result, or throws with the message the
 * server put in `error` — which is the stage's own wording, not a status code.
 */
async function runJob(url, { bar, status, buttons }) {
    for (const button of buttons) button.disabled = true;
    bar.hidden = false;
    const fill = bar.querySelector(".progress-bar");
    fill.style.width = "0%";
    fill.classList.add("unknown");

    try {
        let job = await post(url, { path: sourcePath() });

        while (job.state === "running") {
            status.textContent = job.message || "Working…";

            // A stage says how much work it has once it knows. Until then
            // the bar sweeps rather than claiming a percentage of nothing.
            fill.classList.toggle("unknown", !job.total);
            if (job.total) {
                fill.style.width = `${(100 * job.done) / job.total}%`;
            }

            await new Promise((resume) => setTimeout(resume, POLL_MS));
            const response = await fetch(`/api/job/${job.id}`);
            job = await response.json();
        }

        if (job.state === "failed") throw new Error(job.error);

        fill.classList.remove("unknown");
        fill.style.width = "100%";
        status.textContent = job.message;
        return job.result;
    } finally {
        for (const button of buttons) button.disabled = false;
    }
}

// --- SOURCE ---

/** Probes the footage and fills in the facts. */
async function inspect() {
    const status = document.getElementById("inspect-status");
    const button = document.getElementById("inspect-button");

    const path = sourcePath();
    if (!path) {
        status.textContent = "Choose some footage first.";
        return;
    }

    button.disabled = true;
    status.textContent = "Reading…";

    try {
        const report = await post("/api/inspect", { path });
        const source = report.source;

        document.getElementById("fact-rate").textContent =
            `${source.fps_numerator}/${source.fps_denominator}`;
        document.getElementById("fact-frames").textContent =
            `${source.frame_count} (${report.duration_timecode})`;
        document.getElementById("fact-resolution").textContent =
            `${source.width} × ${source.height}`;
        document.getElementById("fact-audio").textContent = source.audio
            ? `${source.audio.codec}, ${source.audio.channels}ch`
            : "none";

        // A refusal is an answer, not an error — it says which footage this
        // app cannot carry frame-accurately, and why.
        status.textContent = report.can_build
            ? (report.warnings || []).join(" ") || "Ready to prepare."
            : report.refusal_reason;
        status.classList.toggle("blocked", !report.can_build);

        document.getElementById("prepare-button").disabled = !report.can_build;
        document.getElementById("faces-process").disabled = !report.can_build;
    } catch (error) {
        status.textContent = error.message;
        status.classList.add("blocked");
    } finally {
        button.disabled = false;
    }
}

/** Builds the mezzanine and the numbered proxy. */
async function prepare() {
    const status = document.getElementById("prepare-status");
    setStepState("source", "running");

    try {
        await runJob("/api/prepare", {
            bar: document.getElementById("prepare-progress"),
            status,
            buttons: [document.getElementById("prepare-button")],
        });
        setStepState("source", "done");
    } catch (error) {
        status.textContent = error.message;
        status.classList.add("blocked");
        setStepState("source", "todo");
    }
}

// --- FACES ---

/** Tracks the face, draws the mesh, and shows it over the plate. */
async function track() {
    const status = document.getElementById("faces-status");
    status.classList.remove("blocked");
    setStepState("faces", "running");

    try {
        const result = await runJob("/api/track", {
            bar: document.getElementById("faces-progress"),
            status,
            buttons: [document.getElementById("faces-process")],
        });

        showReport(result.report, result.colours);

        const player = document.getElementById("faces-preview");
        player.src = `/api/preview/${result.preview}`;
        player.hidden = false;
        player.load();

        setStepState("faces", "done");
    } catch (error) {
        status.textContent = error.message;
        status.classList.add("blocked");
        setStepState("faces", "todo");
    }
}

/** Fills the face list from the tracking report. */
function showReport(report, colours) {
    const list = document.getElementById("face-list");
    list.replaceChildren();

    for (const face of report.faces) {
        const row = document.createElement("li");
        row.className = "face";

        // The swatch goes inside the label rather than beside it: `.face` is
        // a two-column grid, and a third child wraps onto its own row.
        const swatch = document.createElement("span");
        swatch.className = "face-swatch";
        const hue = colours[face.label];
        if (hue) swatch.style.background = `rgb(${hue.join(",")})`;

        const label = document.createElement("span");
        label.className = "face-label";
        label.append(swatch, face.label);

        // Gaps are the thing worth reading here: a face found on every frame
        // needs no comment, and one with a long absence wants another seed.
        const detail = document.createElement("span");
        detail.className = "face-seeds";
        detail.textContent = face.frames_missing
            ? `${face.frames_tracked}/${report.frame_count} frames · ` +
              `${face.gaps.length} gap${face.gaps.length === 1 ? "" : "s"}, ` +
              `longest ${face.longest_gap_frames}`
            : `${face.frames_tracked}/${report.frame_count} frames · no gaps`;

        row.append(label, detail);
        list.append(row);
    }
}

/** Attaches the handlers for both steps. */
export function wirePerformance() {
    document.getElementById("inspect-button").addEventListener("click", inspect);
    document.getElementById("prepare-button").addEventListener("click", prepare);
    document.getElementById("faces-process").addEventListener("click", track);
}
