"""Platform for light integration."""

from __future__ import annotations
from typing import Any, override

import logging

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    try:
        name = (await coordinator.client.name()).name
    except BusyBarError as err:
        raise PlatformNotReady(f"BUSY Bar {coordinator.device_id} is unreachable") from err
    async_add_entities([BusybarLight(coordinator, name)])

class BusybarLight(BusyBarEntity, LightEntity):

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "smart_home_switch")
        self._client: AsyncBusyBar = coordinator.client

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.smart_home

    @property
    @override
    def color_mode(self) -> ColorMode:
        return ColorMode.ONOFF

    @property
    @override
    def supported_color_modes(self) -> set[ColorMode]:
        return {ColorMode.ONOFF}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.smart_home_switch_set(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.smart_home_switch_set(False)
        await self.coordinator.async_request_refresh()
