"""Data update coordination for the BUSY Bar integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
import logging

from busylib import AsyncBusyBar
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

# Only the smart-home switch is polled: the bar pushes timer, power and Wi-Fi
# changes over /api/status/ws, but not this one, so it needs asking for. The
# interval is what it is because nothing depends on it being prompt - the
# entities people watch during a session are driven by the stream.
UPDATE_INTERVAL = timedelta(seconds=30)

# The stream is dominated by screen frames - roughly thirty per timer change -
# so entities are only told about updates that carried something they show.
_INTERESTING = ("timer", "power", "wifi", "device_name")

# How long to wait before reconnecting a dropped stream. Long enough not to
# hammer a rebooting bar, short enough that a session change is not missed.
_RECONNECT_DELAY = 5.0


@dataclass(frozen=True)
class BusyBarData:
    """
    Everything the entities read.

    `snapshot` is kept up to date by the stream; `smart_home` by the poll.
    """

    snapshot: DeviceSnapshot
    smart_home: bool


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

    async def _async_update_data(self) -> BusyBarData:
        try:
            # Matter propagates the switch change internally, so a read taken
            # immediately after a write can still see the old value.
            await asyncio.sleep(0.5)
            switch = (await self.client.smart_home_switch()).state
        except BusyBarError as err:
            raise UpdateFailed(f"BUSY Bar {self.device_id} is unreachable") from err

        if self.data is not None:
            # The stream owns the snapshot; the poll must not undo its work.
            return replace(self.data, smart_home=switch)

        snapshot = await collect_device_snapshot(self.client)
        return BusyBarData(snapshot=snapshot, smart_home=switch)

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

    def _apply(self, message: dict[str, object]) -> None:
        """
        Fold one stream message in, and notify entities if it mattered.
        """
        updates = message.get("updates")
        if not isinstance(updates, list):
            return
        if not any(
            isinstance(update, dict) and any(k in update for k in _INTERESTING)
            for update in updates
        ):
            return

        current = self.data
        if current is None:
            return
        snapshot = apply_state_stream_update(current.snapshot, message)
        self.async_set_updated_data(replace(current, snapshot=snapshot))


type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]
