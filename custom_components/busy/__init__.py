"""The BUSY Bar integration."""

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components import zeroconf
from homeassistant.const import CONF_DEVICE_ID, CONF_TOKEN
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from busylib import BusyBarDevices
from busylib.exceptions import BusyBarError

from .coordinator import BusyBarConfigEntry

_PLATFORMS: list[Platform] = [Platform.LIGHT]
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel("DEBUG")

async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Set up BUSY Bar from a config entry."""

    device_id = entry.data[CONF_DEVICE_ID]
    token = entry.data[CONF_TOKEN]

    _LOGGER.debug(f"async_setup_entry: discovering device with id=\"{device_id}\"")

    zc = await zeroconf.async_get_instance(hass)
    devices = await BusyBarDevices.discover(1.5, zc)
    device = next((d for d in devices if d.device_id == device_id), None)
    if not device:
        raise ConfigEntryNotReady(translation_key="device_unreachable")
    
    client = device.to_async_client(token=token)
    _LOGGER.debug(f"async_setup_entry: confirming HTTP reachability of device_id=\"{device_id}\" at {client.base_url}")
    try:
        await client.access()
    except BusyBarError:
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    _LOGGER.debug(f"async_setup_entry: validating access token for device_id=\"{device_id}\"")
    client = device.to_async_client(token=token)
    try:
        await client.tokens_list()
    except BusyBarError:
        raise ConfigEntryAuthFailed(translation_key="access_unauthorized")
    
    _LOGGER.debug(f"async_setup_entry: setting up platforms for device_id=\"{device_id}\"")
    entry.runtime_data = (client, device.device_id)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
