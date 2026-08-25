"""Home Assistant compatible BUSY Bar discovery."""

from __future__ import annotations

import logging

from busylib import BusyBarDevices

from homeassistant.core import HomeAssistant


DISCOVERY_TIMEOUT = 10.0
_LOGGER = logging.getLogger(__name__)


async def async_discover_busy(hass: HomeAssistant):
    """Discover BUSY Bars, including ones reachable only over wlan0/USB.

    A bar plugged in over USB or joined on a secondary Wi-Fi interface may
    not be visible on Home Assistant's shared Zeroconf instance, whose
    interfaces follow the user's network settings. Rather than widening
    that shared, process-wide instance (which every other Zeroconf-using
    integration relies on) let busylib open and close its own short-lived
    instance bound to every interface, scoped to this discovery call only.
    """
    devices = await BusyBarDevices.async_discover(DISCOVERY_TIMEOUT)
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
