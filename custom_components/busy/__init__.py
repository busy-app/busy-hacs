"""The BUSY Bar integration."""

from functools import partial
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_DEVICE_ID, CONF_TOKEN
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from busylib.exceptions import BusyBarError

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .discovery import async_discover_busy

_PLATFORMS: list[Platform] = [Platform.LIGHT]
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Set up BUSY Bar from a config entry."""

    try:
        device_id = entry.data[CONF_DEVICE_ID]
        token = entry.data[CONF_TOKEN]
    except KeyError as err:
        raise ConfigEntryError(f"Config entry is missing {err}") from err

    _LOGGER.debug(f"async_setup_entry: discovering device with id=\"{device_id}\"")

    devices = await async_discover_busy(hass)
    device = next((d for d in devices if d.device_id == device_id), None)
    if not device:
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    client = await hass.async_add_executor_job(partial(device.to_async_client, token=token))
    _LOGGER.debug(f"async_setup_entry: confirming HTTP reachability of device_id=\"{device_id}\" at {client.base_url}")
    try:
        await client.access()
    except BusyBarError:
        await client.aclose()
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    _LOGGER.debug(f"async_setup_entry: validating access token for device_id=\"{device_id}\"")
    try:
        await client.access_tokens_list()
    except BusyBarError:
        await client.aclose()
        raise ConfigEntryAuthFailed(translation_key="access_unauthorized")

    _LOGGER.debug(f"async_setup_entry: setting up platforms for device_id=\"{device_id}\"")
    coordinator = BusyBarCoordinator(hass, client, device.device_id)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.aclose()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.aclose()
    return unloaded
