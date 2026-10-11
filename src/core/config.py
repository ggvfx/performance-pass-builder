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

# --- OUTPUT FORMATS ---

# The normal deliverable. crf 18 is visually transparent at this scale, and
# the pass is a guide for a generation model rather than a master.
H264_CRF = 18
H264_PRESET = "medium"

# Same container, better quality for the size, for software that takes it.
# h265's crf scale is not h264's — roughly 20 here matches 18 there.
#
# The hvc1 tag is not cosmetic: without it QuickTime and several NLEs refuse
# the file outright, and "my mp4 will not open" is a miserable thing to debug
# from the other end.
H265_CRF = 20
H265_PRESET = "medium"
H265_TAG = "hvc1"

# The default for a layer with transparency. QuickTime RLE is lossless, is
# one file, and opens in essentially every compositor — and on line art over
# nothing it is about fifty times smaller than ProRes 4444, measured. argb
# rather than rgba is simply what qtrle takes.
ALPHA_RLE_ENCODER = "qtrle"
ALPHA_RLE_PIXEL_FORMAT = "argb"


# A sequence goes into a folder of its own, named after the pass, with the
# frames named the same — so Nuke sees `take_01_faces.####.png` and nothing
# is scattered among the single-file deliverables.
#
# Numbered from 0, matching this app's own frame indices rather than the
# 1001 an industry sequence often starts at: frame 40 of the track has to be
# frame 40 of the sequence, and inventing an offset here would break that
# correspondence with landmarks.json and everything else.
PNG_FRAME_PATTERN = "%04d"
PNG_START_NUMBER = "0"

# --- AUDIO ---

# Codecs an mp4 will carry as a stream copy. Anything else is encoded once at
# a high bitrate on the way out, and the sidecar says so — 24-bit PCM off a
# camera is the usual case. CLAUDE.md non-negotiable 3.
MP4_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus"})

# Where the source's codec will not fit the container, it is encoded ONCE, at
# a bitrate high enough that the generation model is driven by what was
# recorded rather than by what survived a second pass.
#
# **This is the only lossy step applied to audio anywhere in the app**, and it
# only happens for a codec mp4 cannot hold — 24-bit PCM off a camera being the
# usual one. The probe warns before the job, and the sidecar records that it
# happened. Said in three places on purpose: silently degrading someone's
# production audio is not something to be discreet about.
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

# --- FACE TRACKING ---

# MediaPipe's own defaults, set here rather than left implicit so the numbers
# a track was made with are visible and recorded, not buried in a library.
#
# Deliberately not tuned yet: raising them loses marginal frames that could
# have been tracked, and lowering them invents faces in noise. Which way to
# move is a question for real footage, not for a guess — see the clips in
# tests/media/WANTED.md.
FACE_DETECTION_CONFIDENCE = 0.5   # Minimum score to call something a face
FACE_PRESENCE_CONFIDENCE = 0.5    # Minimum score that the face is still there
FACE_TRACKING_CONFIDENCE = 0.5    # Minimum score to carry a track to the next frame

# Reading a video backwards means holding frames, because a decoder only goes
# forwards. This caps how many at once: frames are bought in windows of
# roughly this many bytes, so the ceiling is the same on a 4K source as on a
# 1080p one — about thirty 1080p frames, or seven at 4K.
#
# 256 MB rather than more: this app is used beside Resolve and Nuke, and
# being a memory hog for a two-second speedup is a poor trade.
BACKWARD_WINDOW_BYTES = 256 * 1024 * 1024

# The tracker looks inside a box this much larger than where the face was on
# the previous frame. 0.5 makes it twice as wide and twice as tall.
#
# It is the whole answer to two faces crossing: a face that wanders into the
# picture is not in the search region, so it cannot take the track. Too tight
# and a fast head turn escapes it; too loose and it stops excluding anyone.
FACE_SEARCH_PADDING = 0.5

# A search region is grown to at least this many pixels on its short side
# before being cropped. MediaPipe's face detector works at 192x192, so
# handing it a 60-pixel crop of a distant face throws away the one advantage
# cropping has — that the face fills more of what the model sees.
MIN_SEARCH_PIXELS = 192

# How many faces the landmarker is asked for on a seeded run. The seed box
# picks one of them, so this is "how many candidates to choose between", not
# how many are tracked. Five covers a group shot without paying for faces
# nobody asked about.
SEED_FACE_LIMIT = 5

# One face for the baseline pass. The selection-driven passes set their own.
BASELINE_FACE_LIMIT = 1

# --- LANDMARKS EXPORT ---

# Off by default. Nothing in this app reads `landmarks.json` — it exists for
# whatever an artist wants to do with the numbers afterwards — and a face
# mesh is biometric-adjacent: a weak signal next to the footage it came
# from, but a new artefact that can be shared separately from it.
#
# An export nobody asked for should not be written, and that disposes of the
# question rather than arguing about how weak the signal is.
WRITE_LANDMARKS_BY_DEFAULT = False

# --- THE FACE MESH ---

# Colours as (R, G, B).
#
# **A starting point, not a tested one.** These came in with the project's
# design notes, attributed to the Genjutsu Open Source Workflow — see
# THIRD-PARTY.md, where that attribution is also marked unverified. Whether
# a generation model reads them as guidance rather than as picture content
# is an assumption nobody here has checked.
#
# They are settings precisely so that checking is cheap: change them, render
# a pass, look at what comes out.
MESH_TESSELATION_COLOUR = (80, 160, 255)   # Blue, the whole surface
MESH_LIPS_COLOUR = (255, 150, 40)          # Orange
MESH_EYES_COLOUR = (90, 230, 120)          # Green, eyes and brows
MESH_IRIS_COLOUR = (255, 255, 255)         # White, the ten refined points

# Line widths as a fraction of picture height, so a mesh looks the same on a
# 720p proxy and a 4K master instead of becoming a cobweb or a scribble.
# Rounded up to at least one pixel at draw time.
MESH_TESSELATION_WIDTH = 0.0009   # About 1px at 1080, 2px at 2160
MESH_FEATURE_WIDTH = 0.0019       # Lips, eyes and brows: about 2px at 1080

# --- SMOOTHING ---

# One Euro filter settings. Raw landmarks jitter, and a generation model
# renders jitter as shimmer.
#
# The trade is always the same: smooth a still point hard, and a moving one
# barely at all, because smoothing movement is latency and a mesh that
# arrives late looks worse than the jitter did.
#
# **`beta` is not the paper's 0.007, and it cannot be.** That figure assumes
# coordinates in natural units — pixels, or centimetres. Landmarks here are
# fractions of the picture, so a face moving briskly reads as about 0.03 per
# second rather than 60, and 0.007 x 0.03 is three orders of magnitude too
# small to lift the cutoff off its floor. Measured on real footage: at 0.007
# the adaptive half of the filter does nothing at all, and the result is
# indistinguishable from a plain lowpass.
#
# 30 puts it back in range: a still point is filtered at 1 Hz, and the
# fastest points in a shot at around 6 Hz.
#
# **Still not tuned against a picture.** The honest place to settle these is
# beside a rendered mesh at 3.8, where "too soft" and "still crawling" are
# things you can see rather than numbers to argue about.
SMOOTHING_MIN_CUTOFF = 1.0    # Hz. Lower smooths a still point harder
SMOOTHING_BETA = 30.0         # Per fraction-of-picture per second, not pixels
SMOOTHING_SPEED_CUTOFF = 1.0  # Hz. Smooths the speed estimate itself

# --- MODEL CACHE ---

# The MediaPipe bundle lands here on first use. Inside the repo but gitignored
# (`models/` and `*.task`), rather than in a platform cache directory: one
# obvious folder someone can delete or populate by hand, and `.gitignore`
# already covers it. What the file must be is in models.py.
MODEL_CACHE_DIR = REPO_ROOT / "models"

# Generous. It is 3.6 MB, but a first run on a slow or throttled connection
# should wait rather than fail and send someone hunting for a URL.
MODEL_DOWNLOAD_TIMEOUT = 120.0

# --- SOURCE FILES ---

# What the path picker offers. Lowercase; compared against a lowercased suffix.
VIDEO_SUFFIXES = {".mov", ".mp4", ".mxf", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg", ".webm"}

# --- SERVER ---

# Loopback only. The path picker lists this machine's filesystem, so the
# server must never listen on a public interface.
HOST = "127.0.0.1"

# One above minicut-shot-detector's 8765, so the two can run at once.
PORT = 8766
