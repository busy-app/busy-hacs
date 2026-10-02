"""Following a firmware install across the gaps in what the bar reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from busylib import types

_LOGGER = logging.getLogger(__name__)

# An install ends with a reboot, which takes the bar off the network for the
# best part of a minute. For this long after the bar was last seen
# installing, being unreachable is read as "still at it" rather than "gone".
# An install silent for longer has failed in a way the bar did not say, and
# holding "installing" forever would be its own kind of lie.
GIVE_UP = timedelta(minutes=30)

# What the bar reports while installing, from its own OpenAPI: every action
# other than "none" is work, and only the download reports how far along it
# is. (The guess was `install` and `verify`, which the firmware never says,
# so the progress vanished the moment the download ended.)
ACTIONS = frozenset({"download", "sha_verification", "unpack", "prepare", "apply"})

# The events that bracket an install. A started session is still running
# until it stops - including between one action finishing and the next
# beginning, which is `action_done` and not an idle bar.
EVENTS = frozenset(
    {"session_start", "action_begin", "action_progress", "action_done", "detail_change"}
)

# What the bar says when nothing is wrong. Anything else is a refusal or a
# failure - a low battery, a running session, a bad checksum - and none of
# them is an install still in progress.
HEALTHY = frozenset({"ok", "", None})


def is_installing(status: types.UpdateStatus | None) -> bool:
    """
    Whether the bar reports an install happening this instant - which is
    not the question a person is asking; see `InstallTracker.version`.
    """
    install = None if status is None else status.install
    if install is None or install.status not in HEALTHY:
        return False
    return install.action in ACTIONS or install.event in EVENTS


class InstallTracker:
    """
    Follows an install as the session it is.

    The bar keeps two answers that disagree for the length of an install:
    what its update check last found (which says "available" throughout,
    because starting an install does not touch it) and what the installer
    does this second (which goes quiet between phases and during the
    reboot). Reading either alone made the entity flicker between
    "installing" and "there is an update". So the install starts when the
    bar says a phase began, and is over when the bar comes back running the
    version, or reports a failure, or stays silent past `GIVE_UP`.
    """

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.version: str | None = None
        self._seen: datetime | None = None

    def follow(self, status: types.UpdateStatus | None) -> None:
        """Fold one poll's update status in."""
        install = None if status is None else status.install
        check = None if status is None else status.check
        if is_installing(status):
            # The installer never says which version it installs; the check
            # does, and keeps saying it - the same staleness that made the
            # two disagree is what names the target here.
            self.version = (
                self.version
                or (check.available_version if check is not None else None)
                or "?"
            )
            self._seen = datetime.now(UTC)
        elif self.version is not None:
            failed = install is not None and install.status not in HEALTHY
            expired = (
                self._seen is not None and datetime.now(UTC) - self._seen > GIVE_UP
            )
            if failed or expired:
                _LOGGER.info(
                    "install on %s ended without finishing (%s)",
                    self.device_id,
                    "the bar reported a failure" if failed else "nothing reported it",
                )
                self.version = None

    def landed(self, running: str | None) -> None:
        """
        End the install when the bar comes back on the version it was
        installing. The reboot is the only unambiguous end: the installer
        stops reporting well before it, and the update check goes on
        offering the very version being installed. Anything short of the
        new version running is a gap, not an end.
        """
        if running is not None and running == self.version:
            _LOGGER.info(
                "%s runs %s now, so the install is over", self.device_id, running
            )
            self.version = None
