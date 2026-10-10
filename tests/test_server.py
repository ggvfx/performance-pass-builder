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


# The four steps, in order. Each has a panel of its own.
STEPS = ["source", "depth", "faces", "composite"]


def test_the_whole_workflow_is_on_the_page():
    """
    The shape of the job is visible before any of it works, so it can be
    argued with — and this is a compositing app, so the Composite step has to
    be there from the start even with nothing yet to combine.
    """
    page = client.get("/").text
    steps = re.findall(r'data-step="([^"]+)"', page)

    print(f"steps on the page: {steps}")
    assert steps == STEPS, "the four steps should be present and in order"


def test_every_step_has_a_panel_and_says_what_state_it_is_in():
    """A step that shows nothing when clicked is worse than one that is absent."""
    page = client.get("/").text

    for step in STEPS:
        assert f'id="step-{step}"' in page, f"no panel for {step}"

    assert len(re.findall(r'class="step-state"', page)) == len(STEPS)


def test_the_stack_is_numbered_from_the_bottom():
    """
    Layer 0 is the background. The list reads top of stack first, the way a
    layer panel does, so the indices run downward — which is the thing a
    reader has to get right and the thing a careless edit would reverse.
    """
    page = client.get("/").text
    composite = page.split('id="step-composite"')[1]
    indices = re.findall(r'class="layer-index">(\d+)<', composite)

    print(f"stack listed top-down: {indices}")
    assert indices, "the composite step should show a stack"
    assert indices == sorted(indices, reverse=True), (
        "listed top first, so the indices should descend"
    )
    assert indices[-1] == "0", "the bottom layer is 0"


# Controls on the Performance tab that are wired and so may be enabled.
# Everything else must be dimmed: a control that looks ready and does nothing
# is worse than one that admits it. Adding to this list is how enabling a
# control stays a deliberate act rather than something that slips through.
LIVE_CONTROLS = {
    'id="source-path"',      # 1.7 — a typed path is as valid as a picked one
    'data-picker="source"',  # 1.7 — opens the path picker
    "data-step=",            # the strip itself: every step is reachable
}


def test_only_wired_performance_controls_are_enabled():
    """
    The shape of the workflow is laid out before it works, so it can be seen
    and argued with. Anything not yet wired is dimmed rather than hidden.
    """
    page = client.get("/").text
    performance = page.split('id="performance"')[1].split('id="setup"')[0]

    controls = re.findall(r"<(?:button|input|select)\b[^>]*>", performance)
    assert controls, "the performance tab should lay its controls out"

    for control in controls:
        if any(marker in control for marker in LIVE_CONTROLS):
            print(f"live: {control}")
            continue
        assert "disabled" in control, f"not wired, but not disabled either: {control}"


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
