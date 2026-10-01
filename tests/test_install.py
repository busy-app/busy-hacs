"""
Installing firmware: the entity has to say so for as long as it lasts.

An install is a session of several phases and only the first of them has
a percentage. Reporting the first alone is how a bar that is busily
unpacking an archive goes back to offering the update it is installing.
"""

from __future__ import annotations

from busylib import types
import pytest

from custom_components.busy.install import InstallTracker, is_installing


def status(
    action: str = "none",
    event: str = "none",
    *,
    result: str = "ok",
    available: str = "",
) -> types.UpdateStatus:
    """An update status shaped the way the firmware sends one."""
    return types.UpdateStatus(
        install=types.UpdateInstallStatus(action=action, event=event, status=result),
        check=types.UpdateCheckStatus(
            status="available" if available else "none", available_version=available
        ),
    )


@pytest.mark.parametrize(
    "action", ["download", "sha_verification", "unpack", "prepare", "apply"]
)
def test_every_phase_the_firmware_names_counts_as_installing(action: str) -> None:
    """
    These are the firmware's own words, from its OpenAPI. The ones this
    integration used to look for - `install`, `verify` - are not among
    them, which is why everything after the download read as idle.
    """
    assert is_installing(status(action, "action_progress"))


@pytest.mark.parametrize("event", ["session_start", "action_done"])
def test_a_started_session_is_installing_between_phases(event: str) -> None:
    assert is_installing(status("none", event))


@pytest.mark.parametrize(
    "failure", ["battery_low", "busy", "download_failure", "sha_mismatch"]
)
def test_a_refused_or_failed_install_is_not_in_progress(failure: str) -> None:
    """
    A bar that refused (too little battery, a session running) or failed
    midway is not installing, however the phase reads. Otherwise the entity
    sits at "installing" for good.
    """
    assert not is_installing(status("download", "action_begin", result=failure))


@pytest.mark.parametrize("idle", [status(), status("none", "session_stop"), None])
def test_an_idle_bar_is_not_installing(idle) -> None:
    assert not is_installing(idle)


def test_an_install_survives_the_gaps_between_its_phases() -> None:
    """
    The bar reports nothing between one phase finishing and the next
    beginning, and nothing at all while it reboots - and its own update
    check keeps offering the version being installed throughout.
    """
    tracker = InstallTracker("bar")
    tracker.follow(status("download", "action_begin", available="r999"))
    assert tracker.version == "r999"

    tracker.follow(status())
    assert tracker.version == "r999", "an install must outlive a quiet poll"

    tracker.follow(status(available="r999"))
    assert tracker.version == "r999", "the check is stale while installing"


def test_an_install_ends_when_the_bar_comes_back_on_the_new_version() -> None:
    """
    The reboot is the only unambiguous end: the installer stops reporting
    well before it, and the check goes on offering the very version being
    installed until it next runs.
    """
    tracker = InstallTracker("bar")
    tracker.follow(status("apply", "action_begin", available="r999"))

    tracker.landed("r985")
    assert tracker.version == "r999", "still the old firmware: not over"

    tracker.landed("r999")
    assert tracker.version is None


def test_an_install_the_bar_reports_as_failed_is_over() -> None:
    """A bar that says "battery low" is not about to finish anything."""
    tracker = InstallTracker("bar")
    tracker.follow(status("download", "action_begin"))
    assert tracker.version == "?"

    tracker.follow(status(result="battery_low"))
    assert tracker.version is None
