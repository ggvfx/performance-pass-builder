"""
Tests for the Dependency Checks.

Three states rather than two is the thing worth protecting: `degraded` is a
limitation the user may proceed past, and collapsing it into either neighbour
either stops someone working over a missing convenience or lets a blocked app
look ready.
"""

import platform

from fastapi.testclient import TestClient

from src.core import config
from src.core.environment import (
    BLOCKED,
    DEGRADED,
    OK,
    Check,
    EnvironmentChecker,
    gating_status,
    platform_name,
    windows_release,
    worst_status,
)
from src.core.ffmpeg_tools import MediaToolchain
from src.core.templates import (
    FAL_KEY_INSTALL,
    FFMPEG_INSTALL,
    FREETYPE_INSTALL,
    PYTHON_INSTALL,
)
from src.ui.server import app

client = TestClient(app)


def a_check(status=OK, key="thing", advisory=False) -> Check:
    return Check(key=key, label=key, status=status, detail="", advisory=advisory)


def an_offline_checker() -> EnvironmentChecker:
    """A checker whose ffmpeg was never found, so the failure paths can be read."""
    return EnvironmentChecker(toolchain=MediaToolchain(discover=False))


# --- ROLLUP ---


def test_the_worst_status_wins():
    """One blocked row blocks the app however many green ones surround it."""
    assert worst_status([OK, OK, OK]) == OK
    assert worst_status([OK, DEGRADED, OK]) == DEGRADED
    assert worst_status([OK, DEGRADED, BLOCKED]) == BLOCKED


def test_nothing_to_report_is_not_a_failure():
    assert worst_status([]) == OK


def test_advisory_rows_do_not_gate():
    """
    A row about something the user may never need must not turn a working app
    amber — that is how a panel starts being ignored.
    """
    checks = [a_check(OK), a_check(BLOCKED, key="optional", advisory=True)]

    assert gating_status(checks) == OK
    assert worst_status([check.status for check in checks]) == BLOCKED, (
        "the severity is still there; it is only excluded from the headline"
    )


def test_an_all_advisory_panel_is_ok():
    """Nothing is wrong — there is just nothing to gate on."""
    assert gating_status([a_check(BLOCKED, advisory=True)]) == OK


# --- PLATFORM NAMING ---


def test_windows_11_is_not_reported_as_10():
    """Windows 11 still calls itself major version 10; only the build tells them apart."""
    assert windows_release("10", 22000) == "11"
    assert windows_release("10", 26200) == "11"
    assert windows_release("10", 19045) == "10"


def test_the_platform_names_itself():
    name = platform_name()

    print(f"platform: {name}")
    assert name, "a sidecar records this, so it must never be empty"
    assert platform.system() in name or "Windows" in name


# --- INSTALL INSTRUCTIONS ---


def test_every_platform_can_be_fixed_without_a_package_manager():
    """
    One command assumes a tool the user may not have: `brew install ffmpeg` on
    a Mac without Homebrew fails with "command not found", which reads as the
    app being broken rather than as a missing prerequisite.
    """
    tables = {
        "FFMPEG_INSTALL": FFMPEG_INSTALL,
        "FREETYPE_INSTALL": FREETYPE_INSTALL,
        "PYTHON_INSTALL": PYTHON_INSTALL,
        "FAL_KEY_INSTALL": FAL_KEY_INSTALL,
    }

    for name, table in tables.items():
        for system, options in table.items():
            needs_nothing = [label for label, command, url in options if url or not command]
            print(f"{name}[{system}]: {needs_nothing}")
            assert needs_nothing, f"{name}[{system}] offers only commands"


def test_every_install_option_is_a_command_or_a_link_but_not_both():
    """The front end renders them differently, and a row has to pick one."""
    for table in (FFMPEG_INSTALL, FREETYPE_INSTALL, PYTHON_INSTALL, FAL_KEY_INSTALL):
        for system, options in table.items():
            for label, command, url in options:
                assert label, f"{system}: an option with no label cannot be acted on"
                assert not (command and url), f"{system}: {label!r} sets both"


# --- INDIVIDUAL CHECKS ---


def test_python_passes_on_the_machine_running_the_tests():
    """The suite cannot run on an unsupported Python, so this should always be green."""
    check = an_offline_checker().check_python()

    assert check.status == OK
    assert check.detail.startswith("3.")


def test_missing_ffmpeg_blocks_and_says_how_to_fix_it():
    checker = an_offline_checker()

    for check in (checker.check_ffmpeg(), checker.check_ffprobe()):
        assert check.status == BLOCKED
        assert check.detail == "Not found on PATH"
        assert check.fixes, "a failing check with no fix is a dead end"


def test_missing_frame_numbers_are_a_limitation_not_a_failure():
    """
    The numbers are a cross-check on the player, not the product. Reporting
    their absence as a failure would stop someone working over a convenience.
    """
    check = an_offline_checker().check_filters()

    assert check.status == DEGRADED
    assert check.status != BLOCKED


def test_missing_encoders_block():
    """The proxy and both deliverables are h264. Without libx264 there is no pass."""
    check = an_offline_checker().check_encoders()

    assert check.status == BLOCKED


def test_mediapipe_and_opencv_are_found():
    """Both are pinned in requirements.txt, so a green suite means a green row."""
    checker = an_offline_checker()

    for check in (checker.check_mediapipe(), checker.check_opencv()):
        print(f"{check.label}: {check.detail}")
        assert check.status == OK
        assert check.detail != "unknown version"


def test_a_missing_fal_key_degrades_rather_than_blocks(monkeypatch):
    """
    A missing key costs hosted depth and nothing else. Face tracking is local
    and free, a mesh layer is a deliverable on its own, and depth made
    elsewhere can be supplied — so telling the user the app cannot run would
    simply be untrue.
    """
    monkeypatch.delenv(config.FAL_KEY_VARIABLE, raising=False)
    check = an_offline_checker().check_fal_key()

    assert check.status == DEGRADED
    assert check.fixes, "and it still says how to set one"


def test_a_missing_fal_key_does_not_block_the_whole_panel(monkeypatch):
    """
    The headline the user actually reads. This is the bug the three-state
    report exists to prevent: one unavailable backend reading as a dead app.
    """
    monkeypatch.delenv(config.FAL_KEY_VARIABLE, raising=False)
    checks = [
        Check(key="python", label="Python", status=OK, detail="3.12.10"),
        an_offline_checker().check_fal_key(),
    ]

    assert gating_status(checks) == DEGRADED


def test_a_present_fal_key_is_reported_without_its_value(monkeypatch):
    """CLAUDE.md non-negotiable 11: the key is never stored, and never shown."""
    secret = "fal-secret-value-that-must-not-leak"
    monkeypatch.setenv(config.FAL_KEY_VARIABLE, secret)

    check = an_offline_checker().check_fal_key()

    assert check.status == OK
    assert secret not in check.detail
    assert secret not in check.model_dump_json()


def test_whitespace_is_not_a_key(monkeypatch):
    """An empty variable set by a half-finished profile edit is not a key."""
    monkeypatch.setenv(config.FAL_KEY_VARIABLE, "   ")

    assert an_offline_checker().check_fal_key().status == DEGRADED


def test_disk_space_is_reported_in_minutes_of_footage():
    """More useful to read than gigabytes, which nobody converts in their head."""
    check = an_offline_checker().check_disk(None)

    print(f"disk: {check.detail}")
    assert "GB free" in check.detail
    assert "min of 1080p24" in check.detail


# --- THE ROUTE ---


def test_the_environment_route_returns_every_row():
    response = client.get("/api/environment")

    assert response.status_code == 200
    report = response.json()

    keys = [check["key"] for check in report["checks"]]
    print(f"rows: {keys}")
    assert report["overall"] in (OK, DEGRADED, BLOCKED)
    assert report["platform"]
    for expected in ("python", "ffmpeg", "ffprobe", "encoders", "filters", "fal_key", "disk"):
        assert expected in keys, expected


def test_every_failing_row_carries_a_fix():
    """A panel that reports a problem without a way out is worse than silence."""
    report = client.get("/api/environment").json()

    for check in report["checks"]:
        if check["status"] != OK:
            assert check["fixes"], f"{check['key']} failed with no fix offered"


def test_the_route_can_be_asked_to_re_check():
    """What Re-check does: the user may have installed something since launch."""
    assert client.get("/api/environment?refresh=true").status_code == 200

