"""Reaching a bar: the address it was added at, or wherever it is now."""

from __future__ import annotations

from functools import partial
import logging

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError
from busylib.transports import AiohttpTransport
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import BusyBarConfigEntry
from .discovery import async_discover_busy

_LOGGER = logging.getLogger(__name__)


async def async_connect(
    hass: HomeAssistant, entry: BusyBarConfigEntry, device_id: str, token: str
) -> AsyncBusyBar:
    """
    Return a client that has answered, at the cheapest address available.

    The address the bar was added at is kept in the config entry, so a
    restart talks to it straight away - an mDNS scan takes ten seconds and
    made adding a bar and restarting Home Assistant both look stuck. A
    remembered address can go stale, so a bar that does not answer there is
    looked for again and the entry updated, which also covers a bar moving
    between USB and Wi-Fi.
    """
    # Requests go over the session Home Assistant already owns, not a second
    # pool beside it. The status stream speaks WebSocket and is separate.
    transport = AiohttpTransport(async_get_clientsession(hass))

    async def answering(client: AsyncBusyBar | None) -> AsyncBusyBar | None:
        if client is None:
            return None
        try:
            await client.access()
        except BusyBarError:
            await client.aclose()
            return None
        return client

    host = entry.data.get(CONF_HOST)
    if host:
        # Built in an executor: the client builds an SSL context.
        client = await answering(
            await hass.async_add_executor_job(
                partial(AsyncBusyBar, host, token=token, transport=transport)
            )
        )
        if client is not None:
            return client
        _LOGGER.debug("%s did not answer for %s, rediscovering", host, device_id)

    devices = await async_discover_busy(hass)
    device = next((d for d in devices if d.device_id == device_id), None)
    if device is None:
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    over_wifi = device.get_address("over_wifi")
    client = await answering(
        await hass.async_add_executor_job(
            partial(
                device.to_async_client,
                affinity="over_wifi" if over_wifi else None,
                token=token,
                transport=transport,
            )
        )
    )
    if client is None:
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    # The address Home Assistant can reach, not the bar's USB one.
    found = over_wifi or device.get_address()
    if found and found != host:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HOST: found}
        )
    return client
