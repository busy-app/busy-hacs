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
