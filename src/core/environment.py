"""
Dependency and Environment Checks.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

Powers the panel the user sees on launch. Reports three states, not two:

- ok        Ready to use
- degraded  Will run, but worse (no burned-in frame numbers, tight disk) —
            the user is told the cost and allowed to continue
- blocked   Genuinely cannot run

Every failure carries a copyable fix command rather than just an error string.

One tab asks, where minicut had two, so there is no per-tab check list here.
The depth backend's own rows are produced in `src/backends/` and passed in as
`extra`, because core importing a domain package would point the dependency
arrow the wrong way.
"""

import importlib.metadata
import logging
import os
import platform
import shutil
import sys
from pathlib import Path

from pydantic import BaseModel

from src.core import config
from src.core.ffmpeg_tools import MediaToolchain
from src.core.templates import (
    FAL_KEY_FALLBACK,
    FAL_KEY_INSTALL,
    FFMPEG_FALLBACK,
    FFMPEG_INSTALL,
    FREETYPE_FALLBACK,
    FREETYPE_INSTALL,
    PACKAGES_INSTALL,
    PYTHON_FALLBACK,
    PYTHON_INSTALL,
)

# --- STATUS VALUES ---

OK = "ok"
DEGRADED = "degraded"
BLOCKED = "blocked"

# Worst wins when rolling individual checks up into one overall status.
STATUS_SEVERITY = {OK: 0, DEGRADED: 1, BLOCKED: 2}

# --- RESULT MODELS ---


class FixStep(BaseModel):
    """
    One way to resolve a failing check.

    A list of these rather than a single command, because one command assumes
    a package manager the user may not have. Every dependency here ends with
    an option that needs nothing installed first.
    """

    label: str                   # "With Homebrew", "Or download a build"
    command: str | None = None   # To paste into a terminal
    url: str | None = None       # To open in a browser


class Check(BaseModel):
    """One row in the dependency panel."""

    key: str      # Stable id, used by the front end
    label: str    # What the user reads
    status: str   # ok | degraded | blocked
    detail: str   # What was found

    # How to resolve it. Empty on a passing check.
    fixes: list[FixStep] = []

    # Reported, but not counted in the overall status — for a row about
    # something the user may never use. The headline answers "can I do the job
    # in front of me?", and announcing a fault nobody has reason to act on is
    # how a panel starts being ignored.
    advisory: bool = False


class EnvironmentReport(BaseModel):
    """The whole panel: every check plus the worst status among them."""

    overall: str
    platform: str
    checks: list[Check]


# --- HELPERS ---


def gating_status(checks: list[Check]) -> str:
    """
    The panel's headline: the worst status among the checks that gate the app.

    Advisory rows are left out. All-advisory is `OK`: nothing is wrong, there
    is just nothing to gate on.
    """
    return worst_status([check.status for check in checks if not check.advisory])


def worst_status(statuses: list[str]) -> str:
    """
    The most severe status in a list, which becomes the panel's overall state.

    An empty list is ok — nothing was found to complain about.
    """
    return max(statuses, key=lambda status: STATUS_SEVERITY[status], default=OK)


def python_fixes() -> list[FixStep]:
    """Ways to install a supported Python on this machine."""
    return _steps(PYTHON_INSTALL, PYTHON_FALLBACK)


def ffmpeg_fixes() -> list[FixStep]:
    """Ways to install ffmpeg on this machine."""
    return _steps(FFMPEG_INSTALL, FFMPEG_FALLBACK)


def freetype_fixes() -> list[FixStep]:
    """Ways to get an ffmpeg that can burn in frame numbers. Always optional."""
    return _steps(FREETYPE_INSTALL, FREETYPE_FALLBACK)


def fal_key_fixes() -> list[FixStep]:
    """Ways to put a Fal key in the environment on this machine."""
    return _steps(FAL_KEY_INSTALL, FAL_KEY_FALLBACK)


def package_fixes() -> list[FixStep]:
    """The one way to install the pinned Python packages. Same on every platform."""
    return [FixStep(label=label, command=command, url=url) for label, command, url in PACKAGES_INSTALL]


def _steps(options: dict, fallback: list) -> list[FixStep]:
    """
    This platform's options, as panel rows.

    Only this platform's: the app knows which it is on, and showing a Windows
    user the Homebrew line would be noise.
    """
    return [
        FixStep(label=label, command=command, url=url)
        for label, command, url in options.get(platform.system(), fallback)
    ]


# --- PLATFORM NAMING ---

# Windows 11 still reports itself as major version 10; only the build number
# tells them apart. Anything from this build onwards is 11.
WINDOWS_11_BUILD = 22000


def windows_release(release: str, build: int) -> str:
    """Corrects the release name Windows reports for itself."""
    return "11" if build >= WINDOWS_11_BUILD else release


def platform_name() -> str:
    """
    The operating system, named the way the user would name it.

    The build number is included because it is what actually identifies a
    Windows version, and because this string is recorded in job sidecars.
    """
    system = platform.system()

    if system == "Windows":
        build = sys.getwindowsversion().build
        return f"Windows {windows_release(platform.release(), build)} (build {build})"

    return f"{system} {platform.release()}"


# --- CHECKER ---


class EnvironmentChecker:
    """
    Runs the dependency checks and holds the result.

    The checks shell out to ffmpeg several times, so a report is cached until
    the user presses Re-check or picks a different output directory. The
    toolchain is shared rather than rediscovered per check.
    """

    def __init__(self, toolchain: MediaToolchain | None = None):
        """
        Args:
            toolchain: Shared toolchain. A new one is discovered if not given.
        """
        self.toolchain = toolchain or MediaToolchain()

        # Keyed by output directory: free space is measured against whichever
        # volume the user picked, so one directory's report must not be served
        # for another's.
        self._reports: dict[str, EnvironmentReport] = {}

    # --- PUBLIC API ---

    def report(
        self,
        output_dir: Path | None = None,
        refresh: bool = False,
        extra: list[Check] | None = None,
    ) -> EnvironmentReport:
        """
        The dependency report, cached between calls.

        Args:
            output_dir: The user's chosen output directory, so free space is
                measured against the volume actually being used. None until
                they pick one, which is the normal state on launch.
            refresh: Re-run the checks instead of returning the cached report.
            extra: Rows produced elsewhere, appended after this module's own.

        Notes:
            Extra rows are not cached against, because they are cheap to
            produce and can change without anything here noticing — a key
            appearing in the environment, a local runtime being started. They
            are re-appended to the cached report each time it is asked for.
        """
        key = str(output_dir)

        if refresh or key not in self._reports:
            if refresh:
                # The user may have installed something since the last run
                self.toolchain.discover()
                self._reports.clear()
            self._reports[key] = self.run_all(output_dir)

        report = self._reports[key]

        if not extra:
            return report

        checks = [*report.checks, *extra]
        return EnvironmentReport(
            overall=gating_status(checks),
            platform=report.platform,
            checks=checks,
        )

    def run_all(
        self,
        output_dir: Path | None = None,
        extra: list[Check] | None = None,
    ) -> EnvironmentReport:
        """
        Runs every check and rolls them up. Ignores the cache.

        Args:
            output_dir: The volume free space is measured against.
            extra: Rows produced by modules this one may not import. The depth
                backends are the case: they live in `src/backends/`, and core
                importing a domain package would point the dependency arrow
                the wrong way. The caller assembles them and passes them in.
        """
        checks = [
            self.check_python(),
            self.check_ffmpeg(),
            self.check_ffprobe(),
            self.check_encoders(),
            self.check_filters(),
            self.check_mediapipe(),
            self.check_opencv(),
            self.check_fal_key(),
            self.check_disk(output_dir),
        ]
        checks.extend(extra or [])

        overall = gating_status(checks)
        logging.info(f"Environment check: {overall}")

        return EnvironmentReport(
            overall=overall,
            platform=platform_name(),
            checks=checks,
        )

    # --- INDIVIDUAL CHECKS ---

    def check_python(self) -> Check:
        """Python version. Older than the minimum cannot run the app at all."""
        current = ".".join(str(part) for part in sys.version_info[:3])
        required = ".".join(str(part) for part in config.MIN_PYTHON)

        if sys.version_info[:2] < config.MIN_PYTHON:
            return Check(
                key="python",
                label="Python",
                status=BLOCKED,
                detail=f"Python {current}; {required} or newer is required",
                fixes=python_fixes(),
            )

        return Check(key="python", label="Python", status=OK, detail=current)

    def check_ffmpeg(self) -> Check:
        """ffmpeg on PATH. Needed for the mezzanine, the proxy and every pass."""
        if self.toolchain.ffmpeg is None:
            return Check(
                key="ffmpeg",
                label="ffmpeg",
                status=BLOCKED,
                detail="Not found on PATH",
                fixes=ffmpeg_fixes(),
            )

        return Check(key="ffmpeg", label="ffmpeg", status=OK, detail=self.toolchain.ffmpeg.version)

    def check_ffprobe(self) -> Check:
        """ffprobe on PATH. Needed to read frame rate, frame count and audio."""
        if self.toolchain.ffprobe is None:
            return Check(
                key="ffprobe",
                label="ffprobe",
                status=BLOCKED,
                detail="Not found on PATH",
                fixes=ffmpeg_fixes(),
            )

        return Check(key="ffprobe", label="ffprobe", status=OK, detail=self.toolchain.ffprobe.version)

    def check_encoders(self) -> Check:
        """
        The encoders the mezzanine, the proxy and the deliverables need.

        libx264 is required: the proxy is h264, and it is the fallback every
        output can always be written as.

        libx265 is a limitation rather than a failure, but a bigger one than
        it looks — **h265 is the default output format**, so without it the
        app still works and every deliverable comes out h264. An h265 source
        also cannot keep its own codec through the mezzanine. The row says
        both, because "degraded" with no consequence attached is a row people
        learn to ignore.
        """
        if self.toolchain.ffmpeg is None:
            return Check(
                key="encoders",
                label="Encoders",
                status=BLOCKED,
                detail="Cannot check without ffmpeg",
                fixes=ffmpeg_fixes(),
            )

        if not self.toolchain.has_encoder(config.REQUIRED_ENCODER):
            return Check(
                key="encoders",
                label="Encoders",
                status=BLOCKED,
                detail=f"This ffmpeg build has no {config.REQUIRED_ENCODER}",
                fixes=ffmpeg_fixes(),
            )

        optional = [name for name in config.OPTIONAL_ENCODERS if not self.toolchain.has_encoder(name)]
        if optional:
            return Check(
                key="encoders",
                label="Encoders",
                status=DEGRADED,
                detail=(
                    f"{config.REQUIRED_ENCODER} — no {', '.join(optional)}. Outputs will "
                    f"be h264 rather than the h265 default, and an h265 source cannot "
                    f"keep its codec through the mezzanine"
                ),
                fixes=ffmpeg_fixes(),
            )

        return Check(key="encoders", label="Encoders", status=OK, detail=config.REQUIRED_ENCODER)

    def check_filters(self) -> Check:
        """
        The drawtext filter, which burns frame numbers into the review proxy.

        Never blocking. The numbers are a cross-check on the player, not the
        product — without them the proxy still builds and still seeks exactly.
        Reporting this as a failure would stop someone working over a missing
        convenience.

        Notes:
            It is checked at all because of how it fails otherwise. Homebrew's
            ffmpeg bottle is built without libfreetype and so has no drawtext;
            asking for a filter that does not exist makes ffmpeg reject the
            whole output with "Filter not found", which surfaces as a proxy
            that will not build and no indication why.
        """
        if self.toolchain.ffmpeg is None:
            return Check(
                key="filters",
                label="Frame numbers on the proxy",
                status=DEGRADED,
                detail="Cannot check without ffmpeg",
                fixes=ffmpeg_fixes(),
            )

        if self.toolchain.has_filter(config.DRAWTEXT_FILTER):
            return Check(
                key="filters",
                label="Frame numbers on the proxy",
                status=OK,
                detail="drawtext is available",
            )

        return Check(
            key="filters",
            label="Frame numbers on the proxy",
            status=DEGRADED,
            detail=(
                "This ffmpeg has no drawtext filter, so the review proxy will have no "
                "burned-in frame numbers. Everything else works."
            ),
            fixes=freetype_fixes(),
        )

    def check_mediapipe(self) -> Check:
        """
        MediaPipe, which does the face tracking.

        Blocking: it is the only thing here that finds a face, and there is no
        hosted alternative by design — tracking runs locally on the CPU because
        sending every frame somewhere to get points back buys nothing.

        Notes:
            Wheels exist for Windows and Apple Silicon macOS, not Intel macOS,
            which is ARCHITECTURE.md's open question 6. On a machine with no
            wheel this is where that surfaces.
        """
        return self._check_package("mediapipe", "MediaPipe")

    def check_opencv(self) -> Check:
        """
        OpenCV, which renders the face mesh layer.

        Blocking for the same reason as MediaPipe: nothing else draws.
        """
        return self._check_package("cv2", "OpenCV", distribution="opencv-contrib-python")

    def _check_package(self, module: str, label: str, distribution: str | None = None) -> Check:
        """
        Whether a pinned Python package imports, and which version it is.

        Args:
            module: What to import — not always the distribution's own name.
            label: What the panel calls it.
            distribution: The pip name, where it differs from the module.

        Notes:
            The import is attempted rather than only asking importlib.metadata,
            because a wheel can be recorded as installed and still fail to load
            — a missing native library on a platform without a proper wheel is
            exactly that case, and it is the one this check exists for.

            Always blocking. Every package reached through here is pinned in
            requirements.txt and has no alternative: nothing else tracks a
            face, and nothing else draws. A package whose absence only
            degraded the app would need its own status argument back.
        """
        key = label.lower().replace(" ", "_")

        try:
            __import__(module)
        except ImportError as error:
            return Check(
                key=key,
                label=label,
                status=BLOCKED,
                detail=f"Not installed, or will not load: {error}",
                fixes=package_fixes(),
            )

        try:
            version = importlib.metadata.version(distribution or module)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown version"

        return Check(key=key, label=label, status=OK, detail=version)

    def check_fal_key(self) -> Check:
        """
        Whether a Fal key is in the environment.

        **Degraded, not blocking.** A missing key costs hosted depth and
        nothing else: face tracking runs locally and free, a mesh layer is a
        deliverable on its own, and depth made elsewhere can be supplied. An
        environment check says what this machine can do, and "cannot run" is
        not true of a machine that can still produce a pass.

        What a missing key must block is the depth *operation*, at the point
        it is asked for, where the message can be about the thing being
        attempted. That gate is not this check's job.

        Notes:
            Only whether the variable is set, never what is in it, and the
            value never reaches the panel. CLAUDE.md non-negotiable 11.
        """
        if not os.environ.get(config.FAL_KEY_VARIABLE, "").strip():
            return Check(
                key="fal_key",
                label="Fal key",
                status=DEGRADED,
                detail=(
                    f"{config.FAL_KEY_VARIABLE} is not set, so hosted depth is unavailable. "
                    f"Face tracking runs locally and needs no key, and depth made elsewhere "
                    f"can be supplied."
                ),
                fixes=fal_key_fixes(),
            )

        return Check(
            key="fal_key",
            label="Fal key",
            status=OK,
            detail=f"{config.FAL_KEY_VARIABLE} is set",
        )

    def check_disk(self, output_dir: Path | None) -> Check:
        """
        Free space on the output volume.

        Warned about before a job rather than discovered when the drive fills
        halfway through. A job writes the mezzanine, the proxy and the stored
        depth beside two deliverables, so it costs several times the source.
        """
        target = output_dir if output_dir and output_dir.is_dir() else config.REPO_ROOT
        free_gb = shutil.disk_usage(target).free / (1024 ** 3)

        minutes = free_gb / (config.GB_PER_MINUTE_1080P24 * config.DISK_COPIES_PER_JOB)
        detail = f"{free_gb:.0f} GB free — about {minutes:.0f} min of 1080p24 source"

        if free_gb < config.MIN_FREE_GB:
            return Check(
                key="disk",
                label="Free disk space",
                status=DEGRADED,
                detail=f"{detail}, below the {config.MIN_FREE_GB:.0f} GB comfort threshold",
                fixes=[FixStep(label="Free some space, or write to a larger volume")],
            )

        return Check(key="disk", label="Free disk space", status=OK, detail=detail)
