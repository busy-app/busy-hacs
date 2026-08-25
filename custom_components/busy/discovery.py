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
    """Discover BUSY Bars, including ones reachable only over wlan0/USB.

    A bar plugged in over USB or joined on a secondary Wi-Fi interface may
    not be visible on Home Assistant's shared Zeroconf instance, whose
    interfaces follow the user's network settings. Passing our own instance
    to busylib instead would dodge that, but HA flags custom integrations
    that spin up a second Zeroconf engine as a stability risk (it's a
    real per-process resource). So widen the shared instance for the
    duration of the scan only, then put its interface set back exactly as
    it was - every other Zeroconf-based integration keeps relying on it.
    """
    async_zeroconf = await ha_zeroconf.async_get_async_instance(hass)
    original_interfaces = async_zeroconf.zeroconf._interfaces
    await async_zeroconf.zeroconf.async_update_interfaces(InterfaceChoice.All)
    try:
        devices = await BusyBarDevices.async_discover(DISCOVERY_TIMEOUT, async_zeroconf)
    finally:
        await async_zeroconf.zeroconf.async_update_interfaces(original_interfaces)
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
