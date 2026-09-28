"""
Installing firmware: the entity has to say so for as long as it lasts.

An install is a session of several phases and only the first of them has
a percentage. Reporting the first alone is how a bar that is busily
unpacking an archive goes back to offering the update it is installing.
"""

from __future__ import annotations

from busylib import types
import pytest

from custom_components.busy.coordinator import firmware_is_installing


def status(
    action: str = "none",
    event: str = "none",
    *,
    received: int | None = None,
    total: int | None = None,
) -> types.UpdateStatus:
    """
    An update status shaped the way the firmware sends one.
    """
    download = None
    if total is not None:
        download = types.UpdateInstallDownload(
            received_bytes=received, total_bytes=total, speed_bytes_per_sec=0
        )
    return types.UpdateStatus(
        install=types.UpdateInstallStatus(
            action=action, event=event, status="ok", download=download
        ),
        check=types.UpdateCheckStatus(status="none", available_version=""),
    )


@pytest.mark.parametrize(
    "action",
    ["download", "sha_verification", "unpack", "prepare", "apply"],
)
def test_every_phase_the_firmware_names_counts_as_installing(action: str) -> None:
    """
    These are the firmware's own words, from its OpenAPI. The ones this
    integration used to look for - `install`, `verify` - are not among
    them, which is why everything after the download read as idle.
    """
    assert firmware_is_installing(status(action, "action_progress"))


def test_a_started_session_is_installing_between_phases() -> None:
    """
    Between one action finishing and the next beginning there is no
    action at all, and the install is still under way.
    """
    assert firmware_is_installing(status("none", "session_start"))
    assert firmware_is_installing(status("none", "action_done"))


@pytest.mark.parametrize(
    "failure", ["battery_low", "busy", "download_failure", "sha_mismatch"]
)
def test_a_refused_or_failed_install_is_not_in_progress(failure: str) -> None:
    """
    A bar that refused the install - too little battery, a session
    running - or one that failed midway is not installing, however the
    phase reads. Otherwise the entity sits at "installing" for good.
    """
    refused = status("download", "action_begin")
    refused.install.status = failure

    assert not firmware_is_installing(refused)


def test_an_idle_bar_is_not_installing() -> None:
    assert not firmware_is_installing(status())
    assert not firmware_is_installing(status("none", "session_stop"))
    assert not firmware_is_installing(None)


class _Tracker:
    """
    Just enough of a coordinator to run its install-following on.

    The real one needs a Home Assistant, a config entry and a bar to be
    built; what is under test here is a handful of fields and the rules
    that move them.
    """

    def __init__(self) -> None:
        self._installing: str | None = None
        self._installing_since = None
        self._installing_version_seen: str | None = None
        self.device_id = "bar"
        self.update_interval = None


def _tracking(status_now: types.UpdateStatus | None) -> _Tracker:
    from custom_components.busy.coordinator import BusyBarCoordinator

    tracker = _Tracker()
    BusyBarCoordinator._follow_the_install(tracker, status_now)
    return tracker


def test_an_install_survives_the_gaps_between_its_phases() -> None:
    """
    The bar reports nothing between one phase finishing and the next
    beginning, and nothing at all while it reboots. Asking "is a phase
    happening right now" therefore answers no several times per install,
    which is exactly how the entity went back to offering the update it
    was installing.
    """
    from custom_components.busy.coordinator import BusyBarCoordinator

    tracker = _tracking(status(action="download", event="action_begin"))
    assert tracker._installing is not None

    # Between phases: the bar says nothing at all.
    BusyBarCoordinator._follow_the_install(tracker, status())
    assert tracker._installing is not None, "an install must outlive a quiet poll"

    # And what the bar's own check keeps saying the whole time.
    BusyBarCoordinator._follow_the_install(
        tracker,
        types.UpdateStatus(
            install=types.UpdateInstallStatus(action="none", event="none", status="ok"),
            check=types.UpdateCheckStatus(status="available", available_version="r999"),
        ),
    )
    assert tracker._installing is not None, "the check is stale while installing"


def test_an_install_ends_when_the_bar_comes_back_on_the_new_version() -> None:
    """
    The reboot is the only unambiguous end: the installer stops
    reporting well before it, and the check goes on offering the very
    version being installed until it next runs.
    """
    from custom_components.busy.coordinator import BusyBarCoordinator

    tracker = _tracking(status(action="apply", event="action_begin"))
    tracker._installing = "r999"

    BusyBarCoordinator._end_the_install_if_it_landed(tracker, "r985")
    assert tracker._installing == "r999", "still the old firmware: not over"

    BusyBarCoordinator._end_the_install_if_it_landed(tracker, "r999")
    assert tracker._installing is None


def test_an_install_the_bar_reports_as_failed_is_over() -> None:
    """
    A refusal is an end, and a bar that says "battery low" is not about
    to finish anything.
    """
    from custom_components.busy.coordinator import BusyBarCoordinator

    tracker = _tracking(status(action="download", event="action_begin"))
    BusyBarCoordinator._follow_the_install(
        tracker,
        types.UpdateStatus(
            install=types.UpdateInstallStatus(
                action="none", event="none", status="battery_low"
            ),
            check=types.UpdateCheckStatus(status="none", available_version=""),
        ),
    )

    assert tracker._installing is None
