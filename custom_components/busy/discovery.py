"""Home Assistant compatible BUSY Bar discovery."""

from __future__ import annotations

import logging

from busylib import BusyBarDevices
from zeroconf import InterfaceChoice

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import HomeAssistant


DISCOVERY_TIMEOUT = 10.0
_LOGGER = logging.getLogger(__name__)


async def async_discover_busy(hass: HomeAssistant):
    """Discover BUSY Bars through Home Assistant's shared Zeroconf instance."""
    async_zeroconf = await ha_zeroconf.async_get_async_instance(hass)
    await async_zeroconf.zeroconf.async_update_interfaces(InterfaceChoice.All)
    devices = await BusyBarDevices.async_discover(
        DISCOVERY_TIMEOUT,
        async_zeroconf,
    )
    _LOGGER.debug(
        "Discovered BUSY Bars: %s",
        [
            {
                "device_id": device.device_id,
                "name": device.name,
                "address": device.get_address(),
            }
            for device in devices
        ],
    )
    return devices
