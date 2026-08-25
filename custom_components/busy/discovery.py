"""Home Assistant compatible BUSY Bar discovery."""

from __future__ import annotations

import logging

from busylib import BusyBarDevices
from zeroconf.asyncio import AsyncZeroconf

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import HomeAssistant


DISCOVERY_TIMEOUT = 2.5
_LOGGER = logging.getLogger(__name__)


async def async_discover_busy(hass: HomeAssistant):
    """Discover BUSY Bars using Home Assistant's shared Zeroconf instance."""
    shared_zeroconf = await ha_zeroconf.async_get_instance(hass)
    async_zeroconf = AsyncZeroconf(zc=shared_zeroconf)
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
