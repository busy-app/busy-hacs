"""Data update coordination for the BUSY Bar integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)


class BusyBarCoordinator(DataUpdateCoordinator[bool]):
    """Polls a BUSY Bar's smart-home switch state."""

    def __init__(self, hass: HomeAssistant, client: AsyncBusyBar, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"BUSY Bar {device_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.device_id = device_id

    async def _async_update_data(self) -> bool:
        try:
            await asyncio.sleep(0.5)  # allow internal Matter shenanigans to propagate the update
            return (await self.client.smart_home_switch()).state
        except BusyBarError as err:
            raise UpdateFailed(f"BUSY Bar {self.device_id} is unreachable") from err


type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]
