"""
Tests for the Model File.

The model is not committed, so it arrives over a network from a host we do
not control. Everything here is about one question: **is a file that is not
the pinned model ever used?**

The answer has to be no in every shape that failure takes — truncated, an
error page saved under the right name, a swapped file in the cache, a
download that died halfway. A model we cannot identify produces landmarks
nobody can trace, and the pass is simply subtly wrong.

Nothing here touches the network. The real download is exercised once, in the
integration phase, where a slow test is affordable.
"""

import hashlib

import pytest

from src.core import config
from src.core.models import MODEL_BYTES, MODEL_FILENAME, MODEL_SHA256, MODEL_URL
from src.performance import model_file
from src.performance.model_file import (
    ModelUnavailable,
    ensure_model,
    is_valid,
    model_path,
    sha256_of,
)

# Stands in for the bundle. The tests never need real model weights — only a
# file whose hash is known, and one whose hash is wrong.
GENUINE = b"x" * 2048
IMPOSTOR = b"y" * 2048


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A model cache pointed somewhere disposable, pinned to GENUINE."""
    monkeypatch.setattr(config, "MODEL_CACHE_DIR", tmp_path / "models")
    monkeypatch.setattr(model_file, "MODEL_SHA256", hashlib.sha256(GENUINE).hexdigest())
    monkeypatch.setattr(model_file, "MODEL_BYTES", len(GENUINE))
    return tmp_path / "models"


def write_model(cache, content: bytes):
    """Puts a file at the cached model path."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / MODEL_FILENAME
    path.write_bytes(content)
    return path


def serve(monkeypatch, body: bytes, fail: Exception | None = None):
    """Replaces the network with a fixed response, or a failure."""

    class Response:
        headers = {"Content-Length": str(len(body))}

        def __init__(self):
            self._rest = body

        def read(self, size):
            block, self._rest = self._rest[:size], self._rest[size:]
            return block

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(url, timeout=None):
        # Asserted rather than ignored: a download with no timeout hangs a
        # first run forever on a connection that accepts and then stalls.
        assert url == MODEL_URL, url
        assert timeout, "the download was made with no timeout"
        if fail is not None:
            raise fail
        return Response()

    monkeypatch.setattr(model_file.urllib.request, "urlopen", fake_urlopen)


# --- WHAT IS PINNED ---


def test_the_pinned_hash_is_a_real_sha256():
    """
    A typo here would mean the real model never validates and the app can
    never track a face — and the message would blame the download.
    """
    assert len(MODEL_SHA256) == 64
    assert all(character in "0123456789abcdef" for character in MODEL_SHA256)


def test_the_model_is_fetched_over_https_from_a_pinned_url():
    """A model arriving over plain http could be anything in transit."""
    assert MODEL_URL.startswith("https://")
    assert MODEL_URL.endswith(MODEL_FILENAME)


def test_the_cache_is_not_tracked_by_git():
    """
    Non-negotiable 6: no model file is committed. The cache sits inside the
    repository, so that only holds for as long as git ignores it.
    """
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", str(config.MODEL_CACHE_DIR / MODEL_FILENAME)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "the model cache is NOT gitignored"


# --- HASHING ---


def test_a_file_hashes_to_what_sha256sum_would_say(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(GENUINE)

    assert sha256_of(path) == hashlib.sha256(GENUINE).hexdigest()


def test_hashing_reads_in_blocks_rather_than_loading_the_file(tmp_path, monkeypatch):
    """
    3.6 MB is nothing, but a helper that loads its argument whole is a trap
    for whatever gets hashed next.
    """
    monkeypatch.setattr(model_file, "HASH_BLOCK_BYTES", 64)
    path = tmp_path / "f.bin"
    path.write_bytes(GENUINE)

    assert sha256_of(path) == hashlib.sha256(GENUINE).hexdigest()


# --- VALIDATION ---


def test_the_pinned_file_is_valid(cache):
    assert is_valid(write_model(cache, GENUINE))


def test_a_file_that_is_not_the_pinned_one_is_not_valid(cache):
    """Right name, right size, wrong contents — the case only a hash catches."""
    assert is_valid(write_model(cache, IMPOSTOR)) is False


def test_a_truncated_file_is_not_valid(cache):
    assert is_valid(write_model(cache, GENUINE[:100])) is False


def test_a_missing_file_is_not_valid(cache):
    assert is_valid(cache / MODEL_FILENAME) is False


def test_a_wrong_size_is_rejected_without_hashing(cache, monkeypatch):
    """
    Size first, hash second. A truncated download is the common failure and
    it should not cost a full read to find out.
    """
    monkeypatch.setattr(
        model_file, "sha256_of", lambda _path: pytest.fail("hashed a wrong-sized file")
    )

    assert is_valid(write_model(cache, GENUINE[:100])) is False


# --- GETTING IT ---


def test_a_cached_model_is_used_without_touching_the_network(cache, monkeypatch):
    monkeypatch.setattr(
        model_file.urllib.request,
        "urlopen",
        lambda *_a, **_k: pytest.fail("downloaded a model that was already cached"),
    )
    write_model(cache, GENUINE)

    assert ensure_model() == model_path()


@pytest.mark.usefixtures("cache")
def test_a_missing_model_is_downloaded_and_verified(monkeypatch):
    serve(monkeypatch, GENUINE)

    path = ensure_model()

    assert path.read_bytes() == GENUINE
    assert path == model_path()


@pytest.mark.usefixtures("cache")
def test_the_cache_directory_is_made_if_it_is_not_there(monkeypatch):
    """First run on a fresh clone. A missing folder is not a failure."""
    serve(monkeypatch, GENUINE)

    assert ensure_model().is_file()


@pytest.mark.usefixtures("cache")
def test_progress_is_reported_while_downloading(monkeypatch):
    """So a first run on a slow connection can show something."""
    monkeypatch.setattr(model_file, "HASH_BLOCK_BYTES", 512)
    serve(monkeypatch, GENUINE)
    seen = []

    ensure_model(on_progress=lambda done, total: seen.append((done, total)))

    print(seen)
    assert seen[-1] == (len(GENUINE), len(GENUINE))
    assert len(seen) > 1, "reported in steps, not once at the end"


def test_no_progress_is_reported_when_nothing_is_downloaded(cache):
    """There is nothing to wait for, so a progress bar would be a lie."""
    write_model(cache, GENUINE)

    ensure_model(
        on_progress=lambda _done, _total: pytest.fail("reported progress for a cache hit")
    )


# --- WHEN IT GOES WRONG ---


@pytest.mark.usefixtures("cache")
def test_a_download_that_is_not_the_pinned_file_is_refused_and_not_kept(monkeypatch):
    """
    The one that matters. An error page saved under the right name must not
    become the model, and must not be left behind to look cached next time.
    """
    serve(monkeypatch, IMPOSTOR)

    with pytest.raises(ModelUnavailable, match="not the pinned model"):
        ensure_model()

    assert not model_path().exists(), "a file that failed its hash was kept"


def test_a_stale_cache_file_is_replaced_rather_than_trusted(cache, monkeypatch):
    """A cache file that fails its hash is a bad download or something worse."""
    write_model(cache, IMPOSTOR)
    serve(monkeypatch, GENUINE)

    assert ensure_model().read_bytes() == GENUINE


@pytest.mark.usefixtures("cache")
def test_a_network_failure_says_how_to_do_it_by_hand(monkeypatch):
    """
    The likeliest cause is a network this app cannot do anything about, so
    the error carries the URL and the exact path to save to.
    """
    serve(monkeypatch, b"", fail=model_file.urllib.error.URLError("no route to host"))

    with pytest.raises(ModelUnavailable) as raised:
        ensure_model()

    message = str(raised.value)
    print(message)
    assert MODEL_URL in message
    assert MODEL_FILENAME in message
    assert "no route to host" in message


def test_an_interrupted_download_leaves_nothing_that_looks_cached(cache, monkeypatch):
    """
    A half-written file at the real path would pass a `.is_file()` check
    forever. The body is written to `.part` and only moved once complete.
    """
    serve(monkeypatch, b"", fail=TimeoutError("timed out"))

    with pytest.raises(ModelUnavailable):
        ensure_model()

    assert not model_path().exists()
    assert list(cache.glob("*")) == [], "a partial file was left behind"


def test_the_real_model_constants_describe_one_specific_file():
    """
    Not monkeypatched: the values actually shipped. A placeholder size or a
    hash of the wrong build would only surface on a user's first run.
    """
    assert MODEL_BYTES == 3_758_596
    assert MODEL_SHA256 == "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
