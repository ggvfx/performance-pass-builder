"""
Tests for the App Shell.

The page loads, every static file it refers to is served, and static files tell
the browser to re-check them — the one header whose absence shows up as an
update that silently did nothing.
"""

import re

from fastapi.testclient import TestClient

from src.core.config import APP_NAME, HOST
from src.ui.server import app

client = TestClient(app)

# --- PAGE ---


def test_page_loads():
    response = client.get("/")

    assert response.status_code == 200
    assert APP_NAME in response.text


def test_page_has_both_tabs():
    """Each tab button names a panel that exists, so no click shows nothing."""
    page = client.get("/").text

    for tab in re.findall(r'data-tab="([^"]+)"', page):
        assert f'id="{tab}"' in page

    assert 'data-tab="performance"' in page
    assert 'data-tab="setup"' in page


def test_everything_the_page_refers_to_is_served():
    """A typo in a src or href is a blank page with nothing in the server log."""
    page = client.get("/").text

    for path in re.findall(r'(?:src|href)="(/static/[^"]+)"', page):
        assert client.get(path).status_code == 200, path


def test_every_module_main_imports_is_served():
    """The same check one level down: an import of a missing module fails silently too."""
    main = client.get("/static/main.js").text

    for name in re.findall(r'from "\./([^"]+)"', main):
        assert client.get(f"/static/{name}").status_code == 200, name


# --- STATIC FILES ---


def test_static_files_must_be_revalidated():
    """
    Without this a browser reuses an ES module across reloads, and an updated
    app runs yesterday's JavaScript.
    """
    response = client.get("/static/main.js")

    assert response.headers["cache-control"] == "no-cache"


# --- SERVER ---


def test_server_binds_to_loopback_only():
    """The path picker lists this machine's files. It must never be on the network."""
    assert HOST == "127.0.0.1"
