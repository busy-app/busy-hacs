"""Home Assistant compatible BUSY Bar discovery."""

from __future__ import annotations

import logging

from busylib import BusyBarDevices
from zeroconf.asyncio import AsyncZeroconf

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import HomeAssistant


DISCOVERY_TIMEOUT = 10.0
_LOGGER = logging.getLogger(__name__)


async def async_discover_busy(hass: HomeAssistant):
    """Discover BUSY Bars using Home Assistant's shared Zeroconf instance.

    A bar on a secondary interface (e.g. a Wi-Fi-only bar on a host that's
    also wired) is only found if that interface is enabled for HA's own
    use, under Settings > System > Network - the shared Zeroconf instance
    only binds the interfaces listed there. Confirmed on a real two-NIC
    Pi: adding the Wi-Fi adapter there is enough on its own; this
    integration intentionally does not override that choice by widening
    the shared instance itself, since it's a process-wide resource every
    other Zeroconf-based integration also relies on.
    """
    shared_zeroconf = await ha_zeroconf.async_get_instance(hass)
    async_zeroconf = AsyncZeroconf(zc=shared_zeroconf)
    devices = await BusyBarDevices.async_discover(DISCOVERY_TIMEOUT, async_zeroconf)
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
