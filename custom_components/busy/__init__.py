"""The BUSY Bar integration."""

import logging

from busylib.exceptions import BusyBarError
from homeassistant.const import CONF_DEVICE_ID, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
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
    except BusyBarError:
        await client.aclose()
        raise ConfigEntryAuthFailed(translation_key="access_unauthorized")

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
