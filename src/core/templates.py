"""
Install Instructions.

Ported from minicut-shot-detector (6dcbd60) and modernised for 3.12.

How to get what the app needs onto a machine, per platform. Data rather than
behaviour, following the `templates.py` convention in CODE_STYLE.md.

Lives apart from `environment.py` because checking whether something is
installed and explaining how to install it are different jobs. One of them is
read by the Setup tab whatever state the machine is in, which is the whole
point of having it: the checks only speak up when something is missing, and
that is useless to the person setting up a second machine.

**Every platform offers at least one option that needs no package manager.** A
single command assumes a tool the user may not have — `brew install ffmpeg` on
a Mac without Homebrew fails with "command not found", which reads as the app
being broken rather than as a missing prerequisite. A test asserts this holds,
so it cannot quietly stop being true.

Where that option comes in the list differs on purpose: ffmpeg leads with the
package manager, because someone installing ffmpeg usually has one. Python
leads with the download, because someone whose Python is too old usually does
not.

Each entry is `(label, command, url)`. Exactly one of command or url is set;
the label says what the option is for.
"""

# --- FFMPEG ---

FFMPEG_INSTALL = {
    "Windows": [
        ("With winget (Windows 10 and 11)", "winget install Gyan.FFmpeg", None),
        ("Or download a build", None, "https://www.gyan.dev/ffmpeg/builds/"),
    ],
    "Darwin": [
        ("With Homebrew", "brew install ffmpeg", None),
        (
            "No Homebrew? Install it first",
            '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
            None,
        ),
        ("Or download a build", None, "https://evermeet.cx/ffmpeg/"),
    ],
    "Linux": [
        ("Debian and Ubuntu", "sudo apt install ffmpeg", None),
        ("Fedora", "sudo dnf install ffmpeg", None),
        ("Or download a build", None, "https://johnvansickle.com/ffmpeg/"),
    ],
}

# Used where the platform is not one of the three above.
FFMPEG_FALLBACK = [
    ("Install ffmpeg and put it on PATH", None, "https://ffmpeg.org/download.html"),
]

# --- FFMPEG WITH LIBFREETYPE ---

# Only for the burned-in frame numbers on the review proxy, which need the
# drawtext filter, which needs an ffmpeg built with libfreetype. Homebrew's
# bottle is not, and on that machine the app simply leaves the numbers out.
#
# So every option here is optional by definition, and the labels say so. The
# download is listed first on macOS rather than last, because the prebuilt
# binaries already include freetype and rebuilding ffmpeg from source to get a
# frame counter is not a reasonable thing to ask of anyone.
FREETYPE_INSTALL = {
    "Windows": [
        ("Standard Windows builds already include this", None, "https://www.gyan.dev/ffmpeg/builds/"),
    ],
    "Darwin": [
        ("Optional — a prebuilt binary that includes it", None, "https://evermeet.cx/ffmpeg/"),
        (
            "Or build Homebrew's ffmpeg with freetype",
            "brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-freetype",
            None,
        ),
    ],
    "Linux": [
        ("Debian and Ubuntu builds already include this", "sudo apt install ffmpeg", None),
        ("Or a prebuilt binary", None, "https://johnvansickle.com/ffmpeg/"),
    ],
}

FREETYPE_FALLBACK = [
    ("Optional — an ffmpeg built with libfreetype", None, "https://ffmpeg.org/download.html"),
]

# --- PYTHON ---

# The download comes first here, unlike ffmpeg: someone whose Python is too old
# is usually not the person who already has Homebrew set up.
#
# 3.12 rather than minicut's 3.11, because numpy 2.5.3 will not install on
# anything older and that is what sets this project's floor.
PYTHON_INSTALL = {
    "Windows": [
        ("Download an installer", None, "https://www.python.org/downloads/"),
        ("Or with winget", "winget install Python.Python.3.12", None),
    ],
    "Darwin": [
        ("Download an installer", None, "https://www.python.org/downloads/"),
        ("Or with Homebrew", "brew install python@3.12", None),
    ],
    "Linux": [
        ("Debian and Ubuntu", "sudo apt install python3.12", None),
        ("Or download the source", None, "https://www.python.org/downloads/"),
    ],
}

PYTHON_FALLBACK = [
    ("Download an installer", None, "https://www.python.org/downloads/"),
]

# --- PYTHON PACKAGES ---

# MediaPipe and OpenCV are pinned in requirements.txt and install the same way
# everywhere, so there is one option rather than a table. It needs no package
# manager beyond pip, which is already present if the app is running at all.
PACKAGES_INSTALL = [
    ("Install the pinned dependencies", "pip install -r requirements.txt", None),
]

# --- HOSTED DEPTH ---

# A key rather than an install, so the instructions are "set this variable",
# which differs per shell rather than per package manager. Never the key
# itself: CLAUDE.md non-negotiable 11 — settings name the variable, and it is
# read at the moment of the call.
FAL_KEY_INSTALL = {
    "Windows": [
        ("Set it for future sessions, then restart the app", 'setx FAL_KEY "your-key-here"', None),
        ("Get a key from Fal", None, "https://fal.ai/dashboard/keys"),
    ],
    "Darwin": [
        ("Add it to your shell profile, then restart the app", 'export FAL_KEY="your-key-here"', None),
        ("Get a key from Fal", None, "https://fal.ai/dashboard/keys"),
    ],
    "Linux": [
        ("Add it to your shell profile, then restart the app", 'export FAL_KEY="your-key-here"', None),
        ("Get a key from Fal", None, "https://fal.ai/dashboard/keys"),
    ],
}

FAL_KEY_FALLBACK = [
    ("Set FAL_KEY in the environment, then restart the app", None, "https://fal.ai/dashboard/keys"),
]
