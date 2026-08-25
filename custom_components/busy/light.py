"""Platform for light integration."""

from __future__ import annotations
from typing import Any, override

import asyncio
import logging

from busylib import AsyncBusyBar

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import BusyBarConfigEntry

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel("DEBUG")

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client, device_id = config_entry.runtime_data
    name = (await client.name()).name
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=name,
        manufacturer="BUSY",
        model="BUSY Bar",
    )
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        Platform.LIGHT,
        DOMAIN,
        f"{device_id}_light",
    )
    if entity_id:
        entity_registry.async_update_entity(entity_id, device_id=device.id)
    async_add_entities([BusybarLight(client, name, device_id)])

class BusybarLight(LightEntity):
    def __init__(self, client: AsyncBusyBar, name: str, device_id: str) -> None:
        self._client = client
        self._name = name
        self._attr_unique_id = f"{device_id}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="BUSY",
            model="BUSY Bar",
        )
        self._state = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool | None:
        _LOGGER.debug(f"is_on => {self._state}")
        return self._state

    @property
    @override
    def color_mode(self) -> ColorMode:
        return ColorMode.ONOFF

    @property
    @override
    def supported_color_modes(self) -> set[ColorMode]:
        return {ColorMode.ONOFF}

    async def async_turn_on(self, **kwargs: Any) -> None:
        _LOGGER.debug(f"turn_on")
        await self._client.smart_home_switch_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.debug(f"turn_off")
        await self._client.smart_home_switch_set(False)

    async def async_update(self) -> None:
        _LOGGER.debug(f"async_update")
        await asyncio.sleep(0.5) # allow internal Matter shenanigans to propagate the update
        self._state = (await self._client.smart_home_switch()).state
