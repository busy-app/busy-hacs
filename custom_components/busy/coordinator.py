"""Data update coordination for the BUSY Bar integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import logging

from busylib import AsyncBusyBar, types
from busylib.exceptions import BusyBarError
from busylib.features import (
    DeviceSnapshot,
    InputEvent,
    SelectorEvent,
    apply_state_stream_update,
    collect_device_snapshot,
    input_events,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

# What is polled, because the bar has no push for it: the smart-home
# switch, the configured brightness, the timezone, the firmware update
# state and the two cards. The interval is what it is because nothing
# depends on any of them
# being prompt - the entities people watch during a session are driven by
# the stream.
UPDATE_INTERVAL = timedelta(seconds=30)

# Except while firmware is installing. Then this poll is what moves the
# progress bar, and half a minute of nothing looks like a bar that has
# stopped rather than one unpacking an archive.
INSTALL_UPDATE_INTERVAL = timedelta(seconds=5)

# An install ends with a reboot, which takes the bar off the network for
# the best part of a minute. Reporting that as a failure turns the last
# step of a successful install into an unavailable device, so for this
# long after the bar was last seen installing, being unreachable is read
# as "still at it" rather than "gone". An install that has reported
# nothing for this long has failed in a way the bar did not say, and
# holding "installing" forever would be its own kind of lie.
INSTALL_GIVE_UP = timedelta(minutes=30)

# The stream is dominated by screen frames - roughly thirty per timer change -
# so most entities are only told about updates that carried something they
# show. A frame carries nothing any of them show: it is folded into the
# snapshot for the camera to pick up, and announced to nobody.
_INTERESTING = (
    "timer",
    "power",
    "wifi",
    "device_name",
    "audio_volume",
    "input",
    "ble",
)

# How long to wait before reconnecting a dropped stream. Long enough not to
# hammer a rebooting bar, short enough that a session change is not missed.
_RECONNECT_DELAY = 5.0


# What the bar reports while it is installing firmware, from its own
# OpenAPI: every action other than "none" is work, and only the download
# reports how far along it is. Naming them here rather than guessing is
# the point - the guess was `install` and `verify`, which the firmware
# never says, so the progress vanished the moment the download ended.
INSTALL_ACTIONS = frozenset(
    {"download", "sha_verification", "unpack", "prepare", "apply"}
)

# The events that bracket an install. A session that has started is still
# running until it stops - including between one action finishing and the
# next beginning, which is `action_done` and not an idle bar.
INSTALL_EVENTS = frozenset(
    {
        "session_start",
        "action_begin",
        "action_progress",
        "action_done",
        "detail_change",
    }
)

# And what the bar says when nothing is wrong. Every other value is a
# refusal or a failure - a low battery, a running session, a checksum
# that did not match - and none of them is an install still in progress.
INSTALL_HEALTHY = frozenset({"ok", "", None})


def firmware_is_installing(status: types.UpdateStatus | None) -> bool:
    """
    Whether the bar reports an install happening right now.

    This is the bar's word for this instant, and an instant is not the
    question a person is asking - see `BusyBarCoordinator.installing`,
    which is what entities read.
    """
    install = None if status is None else status.install
    if install is None:
        return False
    if install.status not in INSTALL_HEALTHY:
        return False
    return install.action in INSTALL_ACTIONS or install.event in INSTALL_EVENTS


# The card a quick session names. A snapshot has to name one, and this is
# deliberately neither of the bar's two: the bar holds a card per switch
# position, the BUSY app holds more, and naming one of the others means a
# quick session cannot disturb either position - not even by name. The
# app shows the session under that card, which is how a person can see
# where it came from.
QUICK_CARD_ID = "00000000-0000-0000-0000-000000000003"


@dataclass
class QuickSession:
    """
    What the quick switches run, kept in Home Assistant.

    Not on the bar: writing any of it there would change one of the two
    cards, which is the thing the quick switches exist to avoid. So it
    lives here, is shown as themes and numbers, and is read when a switch
    is turned on - which also means an automation can set one and flip
    the other.
    """

    simple_minutes: int = 45
    work_minutes: int = 25
    rest_minutes: int = 5
    cycles: int = 4
    themes: dict[str, str] = field(
        default_factory=lambda: {
            "infinite": "busy",
            "simple": "busy",
            "interval": "busy",
        }
    )


@dataclass(frozen=True)
class BusyBarData:
    """
    Everything the entities read.

    `snapshot` is kept up to date by the stream; the rest by the poll.

    `brightness` is the *configured* value - a number as a string, or
    "auto" - and not the same thing as the brightness the stream reports,
    which is what the panel is actually lit to at this moment and moves
    with the ambient light.
    """

    snapshot: DeviceSnapshot
    smart_home: bool
    brightness: str | None = None
    timezone: str | None = None
    update_status: types.UpdateStatus | None = None
    autoupdate: types.AutoupdateSettings | None = None
    selector: str | None = None
    cards: dict[str, types.BusyProfile] = field(default_factory=dict)


class BusyBarCoordinator(DataUpdateCoordinator[BusyBarData]):
    """Keeps one bar's state current, from the stream and a slow poll."""

    def __init__(
        self, hass: HomeAssistant, client: AsyncBusyBar, device_id: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"BUSY Bar {device_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.device_id = device_id
        self._installing: str | None = None
        self._installing_since: datetime | None = None
        self._installing_version_seen: str | None = None
        self.quick = QuickSession()
        self._stream: asyncio.Task[None] | None = None
        self._input_listeners: list[Callable[[InputEvent], None]] = []

    async def _async_update_data(self) -> BusyBarData:
        try:
            # Matter propagates the switch change internally, so a read taken
            # immediately after a write can still see the old value.
            await asyncio.sleep(0.5)
            switch = (await self.client.smart_home_switch()).state
            brightness = (await self.client.display_brightness()).value
            timezone = (await self.client.time_timezone_info()).name
            update_status = await self.client.update_status()
            autoupdate = await self.client.update_autoupdate()
            # The bar's two cards, for the theme each one starts with. The
            # stream does carry a timer_profiles update, so this poll can
            # go once busylib folds that in.
            cards = {
                slot: await self.client.busy_profile(slot)
                for slot in ("busy", "custom")
            }
        except BusyBarError as err:
            if self._installing is not None and self.data is not None:
                # Mid-install silence is the reboot, not a lost bar.
                _LOGGER.debug(
                    "BUSY Bar %s is unreachable while installing firmware",
                    self.device_id,
                )
                return self.data
            raise UpdateFailed(f"BUSY Bar {self.device_id} is unreachable") from err

        self._follow_the_install(update_status)
        if self._installing is not None and not firmware_is_installing(update_status):
            # The installer has gone quiet. Either the bar has come back
            # on the new firmware, which is the only unambiguous end an
            # install has, or it is between phases and this changes
            # nothing. One read answers that.
            running = await self.client.status()
            self._end_the_install_if_it_landed(
                None if running.firmware is None else running.firmware.version
            )

        if self.data is not None:
            # The stream owns the snapshot; the poll must not undo its work.
            return replace(
                self.data,
                smart_home=switch,
                brightness=brightness,
                timezone=timezone,
                update_status=update_status,
                autoupdate=autoupdate,
                cards=cards,
            )

        snapshot = await collect_device_snapshot(self.client)
        return BusyBarData(
            snapshot=snapshot,
            smart_home=switch,
            brightness=brightness,
            timezone=timezone,
            update_status=update_status,
            autoupdate=autoupdate,
            cards=cards,
        )

    @property
    def installing(self) -> str | None:
        """
        The version being installed, or None if nothing is being.

        The bar keeps two answers that disagree for the length of an
        install: what its update check last found, which stays
        "available" the whole time because starting an install does not
        touch it, and what the installer is doing this second, which goes
        quiet between phases and during the reboot. Reading either one
        alone is how the entity spent an install flickering between
        "installing" and "there is an update".

        So the install is followed as the session it is: it starts when
        the bar says a phase began, and it is over when the bar comes
        back running a different version, or reports a failure, or takes
        so long that something has clearly gone wrong unobserved.
        """
        return self._installing

    def _follow_the_install(self, status: types.UpdateStatus | None) -> None:
        """
        Keep track of an install across the gaps in what the bar reports.
        """
        install = None if status is None else status.install
        check = None if status is None else status.check
        if firmware_is_installing(status):
            # The installer never says which version it is installing.
            # The check does, and keeps saying it for the whole install -
            # the same staleness that made these two disagree is what
            # names the target here.
            self._installing = (
                self._installing
                or (check.available_version if check is not None else None)
                or "?"
            )
            self._installing_since = datetime.now(UTC)
        elif self._installing is not None:
            failed = install is not None and install.status not in INSTALL_HEALTHY
            expired = (
                self._installing_since is not None
                and datetime.now(UTC) - self._installing_since > INSTALL_GIVE_UP
            )
            if failed or expired:
                _LOGGER.info(
                    "install on %s ended without finishing (%s)",
                    self.device_id,
                    "the bar reported a failure" if failed else "nothing reported it",
                )
                self._installing = None

        # A poll every half minute is plenty until the bar starts
        # installing, and far too slow while it does.
        self.update_interval = (
            INSTALL_UPDATE_INTERVAL if self._installing else UPDATE_INTERVAL
        )

    def _end_the_install_if_it_landed(self, running: str | None) -> None:
        """
        End the install when the bar comes back on the version it was
        installing.

        The reboot is the only unambiguous end there is: the installer
        stops reporting well before it, and the bar's own update check
        goes on offering the very version being installed until it next
        runs. Anything short of the new version running is a gap, not an
        end.
        """
        if running is None or self._installing is None:
            return
        if running == self._installing:
            _LOGGER.info(
                "%s is running %s now, so the install is over",
                self.device_id,
                running,
            )
            self._installing = None
            self._installing_version_seen = None

    def start_stream(self) -> None:
        """
        Begin following the bar's state stream.
        """
        if self._stream is None or self._stream.done():
            self._stream = self.config_entry.async_create_background_task(
                self.hass, self._follow_stream(), name=f"{self.name} state stream"
            )

    async def stop_stream(self) -> None:
        """
        Stop following the stream, and wait for it to finish.
        """
        task, self._stream = self._stream, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _follow_stream(self) -> None:
        """
        Apply pushed updates to the snapshot until cancelled.

        A dropped stream is reconnected rather than left dead: the bar
        restarts on a firmware update, and the entities would otherwise stay
        frozen at whatever they last saw until Home Assistant restarted.
        """
        while True:
            try:
                async for message in self.client.stream_status_ws():
                    if not isinstance(message, dict):
                        continue
                    self._apply(message)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a stream must not die quietly
                _LOGGER.debug(
                    "state stream for %s dropped, reconnecting",
                    self.device_id,
                    exc_info=True,
                )
            await asyncio.sleep(_RECONNECT_DELAY)

    def add_input_listener(
        self, callback: Callable[[InputEvent], None]
    ) -> Callable[[], None]:
        """
        Be told about every button, selector and wheel event as it arrives.

        Unthrottled, unlike frames: these are things a person just did, and
        an automation that misses one has missed the point. They are rare
        enough that there is nothing to protect against.

        Returns a function that unsubscribes, for an entity to call when it
        is removed.
        """
        self._input_listeners.append(callback)

        def remove() -> None:
            if callback in self._input_listeners:
                self._input_listeners.remove(callback)

        return remove

    def _announce_input(self, events: list[InputEvent]) -> None:
        """
        Hand each event to everything listening.
        """
        for event in events:
            for callback in list(self._input_listeners):
                callback(event)

    def _apply(self, message: dict[str, object]) -> None:
        """
        Fold one stream message in, and notify entities if it mattered.
        """
        updates = message.get("updates")
        if not isinstance(updates, list):
            return

        current = self.data
        if current is None:
            return

        # Input is decoded by busylib, which knows that proto3 omits an
        # enum holding its first value - so an empty button event is a
        # press of OK rather than nothing at all.
        events = input_events(message)
        if events:
            self._announce_input(events)

        if any(isinstance(u, dict) and "frame" in u for u in updates):
            # Fold the frame in and tell nobody. Assigning `data` rather
            # than calling async_set_updated_data is deliberate: the latter
            # wakes every entity, which at ten frames a second is exactly
            # what this avoids. The camera reads the newest frame when
            # somebody asks it for a picture, so nothing here has to be
            # announced at all.
            current = replace(
                current, snapshot=apply_state_stream_update(current.snapshot, message)
            )
            self.data = current

        if not any(
            isinstance(update, dict) and any(k in update for k in _INTERESTING)
            for update in updates
        ):
            return

        snapshot = apply_state_stream_update(current.snapshot, message)
        moved = [event for event in events if isinstance(event, SelectorEvent)]
        selector = moved[-1].position if moved else current.selector
        # Assign and notify by hand rather than through
        # async_set_updated_data, which also reschedules the next poll.
        # Power updates arrive every few seconds, so letting the stream
        # reschedule pushed the poll past its interval indefinitely and the
        # polled values - the smart-home switch, the brightness setting,
        # the brightness setting - only refreshed when something asked.
        self.data = replace(current, snapshot=snapshot, selector=selector)
        self.async_update_listeners()


type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]
