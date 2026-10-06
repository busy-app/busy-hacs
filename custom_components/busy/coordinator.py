"""Data update coordination for the BUSY Bar integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
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

from .install import InstallTracker, is_installing
from .quick import QuickSession

_LOGGER = logging.getLogger(__name__)

# What is polled, because the bar has no push for it: the smart-home
# switch, the configured brightness, the timezone, the firmware update
# state and the two cards. The interval is what it is because nothing
# depends on any of them being prompt - the entities people watch during a
# session are driven by the stream.
UPDATE_INTERVAL = timedelta(seconds=30)

# Except while firmware is installing. Then this poll is what moves the
# progress bar, and half a minute of nothing looks like a bar that has
# stopped rather than one unpacking an archive.
INSTALL_UPDATE_INTERVAL = timedelta(seconds=5)

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
        self._install = InstallTracker(device_id)
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
            if self.installing is not None and self.data is not None:
                # Mid-install silence is the reboot, not a lost bar.
                _LOGGER.debug(
                    "BUSY Bar %s is unreachable while installing firmware",
                    self.device_id,
                )
                return self.data
            raise UpdateFailed(f"BUSY Bar {self.device_id} is unreachable") from err

        self._install.follow(update_status)
        # A poll every half minute is plenty until the bar starts
        # installing, and far too slow while it does.
        self.update_interval = (
            INSTALL_UPDATE_INTERVAL if self.installing else UPDATE_INTERVAL
        )
        if self.installing is not None and not is_installing(update_status):
            # The installer has gone quiet. Either the bar has come back on
            # the new firmware - the only unambiguous end an install has -
            # or it is between phases. One read answers that.
            running = await self.client.status()
            self._install.landed(
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
        """The version being installed, or None if nothing is."""
        return self._install.version

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
