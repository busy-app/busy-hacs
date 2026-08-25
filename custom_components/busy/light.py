"""Platform for light integration."""

from __future__ import annotations
from typing import Any, override

import logging

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator

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

class BusybarLight(CoordinatorEntity[BusyBarCoordinator], LightEntity):
    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator)
        self._client: AsyncBusyBar = coordinator.client
        self._name = name
        self._attr_unique_id = f"{coordinator.device_id}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=name,
            manufacturer="BUSY",
            model="BUSY Bar",
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data

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
