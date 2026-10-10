"""
Shared Configuration.

Fixed project constants, and — once a task needs one — the per-run settings
object for each utility.

One file, so there is one place to look for what a setting is and what it
defaults to. No module invents its own default for anything a user can change;
a module may hold a tuning constant it alone uses, next to the comment
explaining the number.
"""

from pathlib import Path

# --- IDENTITY ---

APP_NAME = "Performance Pass Builder"

# Recorded in every sidecar. When a pass looks wrong months later, the first
# question is which version of this tool produced it.
APP_VERSION = "0.1.0"

# --- PROJECT PATHS ---

# src/core/config.py -> repo root is two parents up
REPO_ROOT = Path(__file__).resolve().parents[2]

STATIC_DIR = REPO_ROOT / "src" / "ui" / "static"

# --- FIXED REQUIREMENTS ---

# Set by numpy 2.5.3, which will not install on anything older.
MIN_PYTHON = (3, 12)

# --- FFMPEG REQUIREMENTS ---

# The proxy and both deliverables are h264, so a build without this cannot
# produce a pass at all.
REQUIRED_ENCODER = "libx264"

# The mezzanine keeps the source's own codec, so an h265 source needs this one.
# Its absence is a limitation, not a failure.
OPTIONAL_ENCODERS = ("libx265",)

# Burns the frame number into each proxy frame. Needs an ffmpeg built with
# libfreetype, which Homebrew's bottle is not — and asking for a filter that
# does not exist aborts the whole encode rather than degrading it, so it is
# checked for before the proxy is built.
DRAWTEXT_FILTER = "drawtext"

# --- HOSTED DEPTH ---

# The variable holding the key, never the key. Read at the moment of the call.
FAL_KEY_VARIABLE = "FAL_KEY"

# --- DISK ---

# Rough figure for all-intra h264 at 1080p24, from minicut's measurements on
# real footage. Only used to turn free space into "about N minutes of source",
# which is a far more useful thing to read than a number of gigabytes.
GB_PER_MINUTE_1080P24 = 1.5

# A job writes the mezzanine, the proxy, the stored depth and two deliverables.
# The mezzanine and the deliverables dominate; three source-sized copies is the
# honest round number.
DISK_COPIES_PER_JOB = 3

# Below this the panel says so. Not a refusal — the user may know the job is
# short.
MIN_FREE_GB = 20.0

# --- COMPOSITING ---

# The flat card's level, as a fraction of full scale. 18% is the photographic
# mid-grey: it is what a grey card is, and the level a region "left neutral"
# in a control pass is expected to sit at. A user may want another value, so
# it lives here rather than in the compositor.
GREY_CARD_LEVEL = 0.18

# --- MEZZANINE ---

# The mezzanine keeps the source's own codec, so this maps what came in to the
# encoder that writes it back out all-intra. A codec not listed here cannot be
# reproduced, and saying so beats working from a mezzanine that is not really
# the source.
MEZZANINE_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
}

# Visually transparent. The mezzanine costs one re-encode generation, which is
# the price of exact random access, so it should not also cost quality.
MEZZANINE_CRF = 12
MEZZANINE_PRESET = "veryfast"

# An all-intra encode at this preset runs faster than real time, so ten times
# the source duration is generous without leaving a hung ffmpeg to block the
# app indefinitely.
ENCODE_TIMEOUT_FACTOR = 10
MINIMUM_ENCODE_TIMEOUT = 600.0

# --- REVIEW PROXY ---

# Small enough to seek instantly and to sit in a browser without ceremony;
# large enough to judge whether a face is clear and where its box belongs.
# minicut found 480 legible but soft on 1080p material.
PROXY_WIDTH = 640
PROXY_CRF = 23
PROXY_PRESET = "veryfast"

PROXY_SUFFIX = "_proxy.mp4"

# --- AUDIO ---

# Codecs an mp4 will carry as a stream copy. Anything else is encoded once at
# a high bitrate on the way out, and the sidecar says so — 24-bit PCM off a
# camera is the usual case. CLAUDE.md non-negotiable 3.
MP4_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus"})

# Where the source's codec will not fit the container, it is encoded ONCE, at
# a bitrate high enough that the generation model is driven by what was
# recorded rather than by what survived a second pass. The sidecar records
# that this happened.
FALLBACK_AUDIO_CODEC = "aac"
FALLBACK_AUDIO_BITRATE = "320k"

# --- DISK ESTIMATION ---

# The reference figure above is quoted for 1080p at 24 fps, so both resolution
# and frame rate scale it.
REFERENCE_PIXELS = 1920 * 1080
REFERENCE_RATE = 24

# --- OUTPUT NAMING ---

# Deliverables go in a folder of their own beside the source, rather than
# scattering files among the masters.
OUTPUT_DIR_SUFFIX = "_performance"

# --- SOURCE FILES ---

# What the path picker offers. Lowercase; compared against a lowercased suffix.
VIDEO_SUFFIXES = {".mov", ".mp4", ".mxf", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg", ".webm"}

# --- SERVER ---

# Loopback only. The path picker lists this machine's filesystem, so the
# server must never listen on a public interface.
HOST = "127.0.0.1"

# One above minicut-shot-detector's 8765, so the two can run at once.
PORT = 8766
