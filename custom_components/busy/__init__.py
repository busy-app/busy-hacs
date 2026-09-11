"""The BUSY Bar integration."""

from functools import partial
import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError
from busylib.transports import AiohttpTransport

from .const import DOMAIN
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .discovery import async_discover_busy
from .services_setup import async_register_services

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]
_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions.

    Done here rather than per config entry so an automation referencing an
    action validates as soon as the integration is loaded, whether or not a
    bar has been added yet - and so the same action is not registered again
    for every bar.
    """
    async_register_services(hass)
    return True

async def _async_client(
    hass: HomeAssistant, entry: BusyBarConfigEntry, device_id: str, token: str
) -> AsyncBusyBar:
    """Return a client that has answered, at the cheapest address available.

    The address the bar was added at is kept in the config entry, so a
    restart talks to it straight away. An mDNS scan takes ten seconds and
    was previously run on every setup - long enough that adding a bar and
    restarting Home Assistant both looked stuck.

    A remembered address can go stale, so a bar that does not answer there
    is looked for again and the entry updated. That also covers a bar
    moving between USB and Wi-Fi.
    """
    # Requests go over the session Home Assistant already owns, rather
    # than a second connection pool beside it: busylib takes a transport
    # for exactly this. The status stream is separate - it speaks
    # WebSocket, which does not go through an HTTP transport.
    transport = AiohttpTransport(async_get_clientsession(hass))

    host = entry.data.get(CONF_HOST)
    if host:
        # Constructed in an executor: the client builds an SSL context.
        client = await hass.async_add_executor_job(
            partial(AsyncBusyBar, host, token=token, transport=transport)
        )
        _LOGGER.debug(
            f"async_setup_entry: trying remembered address {client.base_url} "
            f"for device_id=\"{device_id}\""
        )
        try:
            await client.access()
        except BusyBarError:
            await client.aclose()
            _LOGGER.debug(
                "async_setup_entry: remembered address did not answer, rediscovering"
            )
        else:
            return client

    _LOGGER.debug(f"async_setup_entry: discovering device with id=\"{device_id}\"")
    devices = await async_discover_busy(hass)
    device = next((d for d in devices if d.device_id == device_id), None)
    if not device:
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    client = await hass.async_add_executor_job(
        partial(device.to_async_client, token=token, transport=transport)
    )
    if client is None:
        raise ConfigEntryNotReady(translation_key="device_unreachable")
    _LOGGER.debug(
        f"async_setup_entry: confirming HTTP reachability of "
        f"device_id=\"{device_id}\" at {client.base_url}"
    )
    try:
        await client.access()
    except BusyBarError:
        await client.aclose()
        raise ConfigEntryNotReady(translation_key="device_unreachable")

    found = device.get_address()
    if found and found != host:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HOST: found}
        )
    return client


async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Set up BUSY Bar from a config entry."""

    try:
        device_id = entry.data[CONF_DEVICE_ID]
        token = entry.data[CONF_TOKEN]
    except KeyError as err:
        raise ConfigEntryError(f"Config entry is missing {err}") from err

    client = await _async_client(hass, entry, device_id, token)

    _LOGGER.debug(f"async_setup_entry: validating access token for device_id=\"{device_id}\"")
    try:
        await client.access_tokens_list()
    except BusyBarError:
        await client.aclose()
        raise ConfigEntryAuthFailed(translation_key="access_unauthorized")

    _LOGGER.debug(f"async_setup_entry: setting up platforms for device_id=\"{device_id}\"")
    coordinator = BusyBarCoordinator(hass, client, device_id)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.aclose()
        raise
    entry.runtime_data = coordinator
    # Entities that matter during a session are driven by the stream, so it
    # starts before they do.
    coordinator.start_stream()
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    _drop_stale_connections(hass, device_id)
    return True


def _drop_stale_connections(hass: HomeAssistant, device_id: str) -> None:
    """Remove MAC connections left on a device by an earlier version.

    A device's connections are merged, never replaced, so the MACs this
    integration used to report stay on the device page forever once
    written - as bare addresses with no interface label. Nothing here needs
    them: the bar is identified by its device_id, and the MACs are in the
    diagnostics download, labelled.
    """
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, device_id)})
    if device is not None and device.connections:
        registry.async_update_device(device.id, new_connections=set())

async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop_stream()
        await entry.runtime_data.client.aclose()
    return unloaded
