"""Data update coordination for the BUSY Bar integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
import logging

from busylib import AsyncBusyBar, types
from busylib.exceptions import BusyBarError
from busylib.features import (
    DeviceSnapshot,
    apply_state_stream_update,
    collect_device_snapshot,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

# What is polled, because the bar has no push for it: the smart-home
# switch, the configured brightness, the timezone, and the firmware update
# state. The interval is what it is because nothing depends on any of them
# being prompt - the entities people watch during a session are driven by
# the stream.
UPDATE_INTERVAL = timedelta(seconds=30)

# The stream is dominated by screen frames - roughly thirty per timer change -
# so most entities are only told about updates that carried something they
# show. Frames go to the screen entity instead, on their own throttle.
_INTERESTING = (
    "timer",
    "power",
    "wifi",
    "device_name",
    "audio_volume",
    "input",
    "ble",
)

# The bar sends about ten frames a second. Refreshing an entity that often
# would flood the state machine and the recorder for a picture nobody can
# read that fast, so the screen is announced at most this often.
_FRAME_INTERVAL = 1.0

# How long to wait before reconnecting a dropped stream. Long enough not to
# hammer a rebooting bar, short enough that a session change is not missed.
_RECONNECT_DELAY = 5.0


def _selector_position(updates: list[object]) -> str | None:
    """
    The selector position, if one of these updates reported a change.

    The bar reports the position only when it moves - there is no endpoint
    that answers "where is the selector now" - so this is the only source,
    and the position is unknown until the first move after a restart.
    """
    for update in updates:
        if not isinstance(update, dict):
            continue
        event = update.get("input")
        if not isinstance(event, dict):
            continue
        switch = event.get("switch_event")
        if isinstance(switch, dict):
            position = switch.get("position")
            if isinstance(position, str):
                return position.lower()
    return None


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
        self._stream: asyncio.Task[None] | None = None
        self._frame_listeners: list[Callable[[], None]] = []
        self._frame_announced = 0.0

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
        except BusyBarError as err:
            raise UpdateFailed(f"BUSY Bar {self.device_id} is unreachable") from err

        if self.data is not None:
            # The stream owns the snapshot; the poll must not undo its work.
            return replace(
                self.data,
                smart_home=switch,
                brightness=brightness,
                timezone=timezone,
                update_status=update_status,
                autoupdate=autoupdate,
            )

        snapshot = await collect_device_snapshot(self.client)
        return BusyBarData(
            snapshot=snapshot,
            smart_home=switch,
            brightness=brightness,
            timezone=timezone,
            update_status=update_status,
            autoupdate=autoupdate,
        )

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
                    "state stream for %s dropped, reconnecting", self.device_id,
                    exc_info=True,
                )
            await asyncio.sleep(_RECONNECT_DELAY)

    def add_frame_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """
        Be told when a new screen frame has arrived, at most once a second.

        Returns a function that unsubscribes, for an entity to call when it
        is removed.
        """
        self._frame_listeners.append(callback)

        def remove() -> None:
            if callback in self._frame_listeners:
                self._frame_listeners.remove(callback)

        return remove

    def _announce_frame(self) -> None:
        """
        Tell the screen entity, unless it was told recently.
        """
        now = self.hass.loop.time()
        if now - self._frame_announced < _FRAME_INTERVAL:
            return
        self._frame_announced = now
        for callback in list(self._frame_listeners):
            callback()

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

        if any(isinstance(u, dict) and "frame" in u for u in updates):
            # Fold the frame in and tell only the screen. Assigning `data`
            # rather than calling async_set_updated_data is deliberate: the
            # latter wakes every entity, which at ten frames a second is
            # exactly what this avoids.
            current = replace(
                current, snapshot=apply_state_stream_update(current.snapshot, message)
            )
            self.data = current
            self._announce_frame()

        if not any(
            isinstance(update, dict) and any(k in update for k in _INTERESTING)
            for update in updates
        ):
            return

        snapshot = apply_state_stream_update(current.snapshot, message)
        selector = _selector_position(updates) or current.selector
        # Assign and notify by hand rather than through
        # async_set_updated_data, which also reschedules the next poll.
        # Power updates arrive every few seconds, so letting the stream
        # reschedule pushed the poll past its interval indefinitely and the
        # polled values - the smart-home switch, the brightness setting,
        # the timezone - only refreshed when something asked them to.
        self.data = replace(current, snapshot=snapshot, selector=selector)
        self.async_update_listeners()


type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]
