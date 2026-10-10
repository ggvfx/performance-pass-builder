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


def test_the_whole_workflow_is_on_the_page():
    """
    The shape of the job is visible before any of it works, so it can be
    argued with. Each numbered step is a card with a heading.
    """
    page = client.get("/").text
    headings = re.findall(r"<h2>(\d) · ([^<]+)</h2>", page)

    print(f"workflow steps on the page: {headings}")
    assert [number for number, _ in headings] == ["1", "2", "3", "4", "5"], (
        "the five workflow steps should be numbered in order"
    )


def test_every_performance_control_is_disabled():
    """
    Deliberate, not unfinished: nothing on this tab is wired yet, and a control
    that looks ready and does nothing is worse than one that admits it. This
    fails the day a control is enabled without its handler being wired.
    """
    page = client.get("/").text
    performance = page.split('id="performance"')[1].split('id="setup"')[0]

    controls = re.findall(r"<(?:button|input)\b[^>]*>", performance)
    assert controls, "the performance tab should lay its controls out"

    for control in controls:
        assert "disabled" in control, f"not disabled: {control}"


def test_setup_has_somewhere_for_the_environment_panel_to_land():
    """The ids environment.js writes into at task 1.6."""
    page = client.get("/").text

    for element_id in ("environment-summary", "environment-checks", "recheck-button"):
        assert f'id="{element_id}"' in page, element_id


# --- STYLESHEET ---


def test_the_three_check_states_have_colours():
    """
    ok / degraded / blocked are colour coded consistently wherever they appear,
    so the panel can be read at a glance rather than word by word.
    """
    css = client.get("/static/styles.css").text

    for state in ("ok", "degraded", "blocked"):
        assert f"--{state}:" in css, f"--{state} token missing"
        assert f".check.{state} .check-label" in css, f".check.{state} styling missing"
        assert f".health.{state}" in css, f".health.{state} styling missing"


def test_hidden_is_forced():
    """
    The browser's own [hidden] is only `display: none`, which any later
    `display: flex` or `display: grid` silently overrides — so a row marked
    hidden in the HTML shows anyway. Several rows here are flex or grid.
    """
    css = client.get("/static/styles.css").text

    assert "[hidden] { display: none !important; }" in css


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
