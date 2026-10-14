"""The BUSY Bar integration."""

from functools import partial
import logging

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarAPIError, BusyBarError
from busylib.transports import AiohttpTransport
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .connection import async_connect
from .const import DOMAIN
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .frontend import async_offer_the_card
from .services import async_register_services

# Order matters, and not only to this file: Home Assistant's room card lists
# a device's entities in the order the integration creates them - platform
# by platform, in this order. So this list is the top half of the card: the
# screen, then what the bar is doing, then what to do about it, with the
# remote control and the settings last because a room card is not where
# those belong.
_PLATFORMS: list[Platform] = [
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.UPDATE,
]
_LOGGER = logging.getLogger(__name__)

# A bar is added through the UI; `async_setup` only registers the actions.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Register the actions and the card.

    Done here rather than per config entry so an automation naming an action
    validates as soon as the integration loads, whether or not a bar has
    been added - and so nothing is registered again for every bar.
    """
    async_register_services(hass)
    await async_offer_the_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    client = await async_connect(hass, entry, device_id, entry.data[CONF_TOKEN])
    try:
        await client.access_tokens_list()
    except BusyBarAPIError as err:
        await client.aclose()
        if err.status_code in (401, 403):
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="access_unauthorized"
            ) from err
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="device_unreachable"
        ) from err
    except BusyBarError as err:
        # A bar that did not answer has not refused anything.
        await client.aclose()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="device_unreachable"
        ) from err

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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop_stream()
        await entry.runtime_data.client.aclose()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> None:
    """
    Take Home Assistant's token off the bar when the bar is taken out of it.

    A token can revoke itself, and nothing else would ever: it would sit in
    the bar's list for good. Best effort and no scan - a bar that is gone, off
    or on firmware without the call keeps the token, which is harmless and
    can be deleted on the bar itself.
    """
    host, token = entry.data.get(CONF_HOST), entry.data.get(CONF_TOKEN)
    if not host or not token:
        return
    client = await hass.async_add_executor_job(
        partial(
            AsyncBusyBar,
            host,
            token=token,
            transport=AiohttpTransport(async_get_clientsession(hass)),
        )
    )
    try:
        # A token's short id is its first eight characters.
        await client.access_tokens_revoke(token[:8])
    except (BusyBarError, OSError) as err:
        _LOGGER.debug("could not revoke the token of %s: %s", host, err)
    finally:
        await client.aclose()
