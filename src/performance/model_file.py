"""
The MediaPipe Model File.

Downloads the Face Landmarker bundle on first use and proves it is the file
this project was tested against. Written for this project — minicut needed no
model and has nothing to port.

**No model file is committed** (CLAUDE.md non-negotiable 6). It is 3.6 MB of
binary that would sit in every clone's history forever, and the repository is
public. So it arrives at runtime, which means it arrives over a network, from
a host we do not control, and the only thing making that trustworthy is the
pinned hash in `models.py`.

**A file that does not match the hash is never used.** Not warned about and
used anyway: deleted, and the caller told. Landmarks from a model we cannot
identify would be wrong in ways nobody could trace back here — the pass would
simply be subtly bad, six months after anyone remembers why.

Functions rather than a class: there is one file, in one place, and nothing
to carry between calls.
"""

import hashlib
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from src.core import config
from src.core.models import MODEL_BYTES, MODEL_FILENAME, MODEL_SHA256, MODEL_URL

# Read in blocks rather than whole: this is only 3.6 MB today, but a hashing
# helper that loads its argument into memory is a trap for the next file.
HASH_BLOCK_BYTES = 1024 * 1024

# While downloading. The finished file is only ever moved into place once it
# has been verified, so an interrupted run leaves this behind and never a
# half-written model that looks complete.
PARTIAL_SUFFIX = ".part"


class ModelUnavailable(RuntimeError):
    """
    The model is not here and could not be fetched.

    Carries what a person needs to fix it by hand — the URL, where to put it,
    and what it should be called — because the likeliest cause is a network
    this app cannot do anything about.
    """


def model_path() -> Path:
    """Where the bundle lives once it is cached."""
    return config.MODEL_CACHE_DIR / MODEL_FILENAME


def sha256_of(path: Path) -> str:
    """The file's SHA-256, read in blocks."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while block := handle.read(HASH_BLOCK_BYTES):
            digest.update(block)

    return digest.hexdigest()


def is_valid(path: Path) -> bool:
    """
    Whether a file is the model this project pinned.

    Notes:
        Size first, hash second. Both answer the same question, but a wrong
        size is the common case — a truncated download, or an error page
        saved under the right name — and checking it costs one stat instead
        of reading 3.6 MB.
    """
    if not path.is_file():
        return False

    if path.stat().st_size != MODEL_BYTES:
        logging.warning(
            f"{path.name} is {path.stat().st_size} bytes, not the expected {MODEL_BYTES}"
        )
        return False

    return sha256_of(path) == MODEL_SHA256


def ensure_model(on_progress: Callable[[int, int], None] | None = None) -> Path:
    """
    The cached model, downloading it first if it is not already here.

    Args:
        on_progress: Called with (bytes so far, total bytes) during a
            download, so a caller can show something. Never called when the
            model is already cached — there is nothing to wait for.

    Returns:
        Path to a file that has been verified against the pinned hash.

    Raises:
        ModelUnavailable: It could not be fetched, or what arrived was not
            the pinned file.

    Notes:
        **Verified every time, not only after downloading.** Hashing 3.6 MB
        costs a few milliseconds once per session, and it is the only thing
        standing between a corrupted or swapped cache file and a pass full of
        landmarks nobody can account for.
    """
    path = model_path()

    if is_valid(path):
        logging.info(f"Using the cached Face Landmarker model at {path}")
        return path

    if path.exists():
        # Present but wrong. Say so loudly: a cache file that fails its hash
        # is either a bad download or something that should worry someone.
        logging.warning(f"{path} does not match the pinned hash and is being replaced")
        path.unlink()

    _download(path, on_progress)

    if not is_valid(path):
        actual = sha256_of(path) if path.is_file() else "nothing"
        path.unlink(missing_ok=True)
        raise ModelUnavailable(
            f"What downloaded from {MODEL_URL} is not the pinned model file.\n"
            f"Expected SHA-256 {MODEL_SHA256}, got {actual}.\n"
            f"Nothing has been kept. This is worth looking into rather than retrying."
        )

    logging.info(f"Face Landmarker model downloaded and verified: {path}")
    return path


# --- FETCHING ---


def _download(path: Path, on_progress: Callable[[int, int], None] | None) -> None:
    """
    Fetches the bundle to `path`, via a partial file.

    Notes:
        Written to `.part` and moved into place only once the whole body has
        arrived, so an interrupted download cannot leave something at the
        real path that later looks cached. The move is the last thing that
        happens, and on one filesystem it is atomic.

        `urllib` rather than a dependency: one GET, once, and adding a
        package to the install for it would be a poor trade.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)

    logging.info(f"Downloading the Face Landmarker model from {MODEL_URL}")

    try:
        with urllib.request.urlopen(MODEL_URL, timeout=config.MODEL_DOWNLOAD_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or MODEL_BYTES)
            received = 0

            with partial.open("wb") as handle:
                while block := response.read(HASH_BLOCK_BYTES):
                    handle.write(block)
                    received += len(block)
                    if on_progress is not None:
                        on_progress(received, total)

    except (urllib.error.URLError, TimeoutError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise ModelUnavailable(
            f"Could not download the face tracking model.\n"
            f"  {error}\n\n"
            f"Face tracking cannot run without it. To do it by hand, download\n"
            f"  {MODEL_URL}\n"
            f"and save it as\n"
            f"  {path}"
        ) from error

    partial.replace(path)
