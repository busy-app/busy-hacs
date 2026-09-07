"""Registration of the BUSY Bar actions.

Actions are registered once, from `async_setup`, rather than per config
entry: Home Assistant expects an integration's actions to exist as soon as
it is loaded so an automation referencing one validates even while the
device is unreachable. This is the `action-setup` rule in the integration
quality scale, and doing it from `async_setup_entry` would also register the
same action again for every bar that gets added.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from busylib import AsyncBusyBar
from busylib.exceptions import BusyBarError

from .const import (
    APPLICATION_NAME,
    DEFAULT_DURATION,
    DEFAULT_FONT,
    DOMAIN,
    MAX_DURATION,
    ONE_LINE_FONTS,
    PRIORITY_DEFAULT,
    PRIORITY_INTERRUPT,
    SERVICE_NOTIFY,
    STOCK_SOUNDS,
    TWO_LINE_FONTS,
)
from .notify import build_elements

_LOGGER = logging.getLogger(__name__)

_COLOUR = vol.All([vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(3, 3))

_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("line_1"): cv.string,
        vol.Optional("line_2"): cv.string,
        vol.Optional("icon", default="none"): cv.string,
        vol.Optional("sound", default="none"): cv.string,
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION)
        ),
        vol.Optional("interrupt", default=False): cv.boolean,
        vol.Optional("font", default=DEFAULT_FONT): vol.In(ONE_LINE_FONTS),
        vol.Optional("line_1_color"): _COLOUR,
        vol.Optional("line_2_color"): _COLOUR,
        vol.Optional("background_color"): _COLOUR,
    }
)


def _clients(hass: HomeAssistant, device_ids: list[str]) -> list[AsyncBusyBar]:
    """
    Resolve the targeted Home Assistant devices to BUSY Bar clients.
    """
    registry = dr.async_get(hass)
    clients: list[AsyncBusyBar] = []
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_device"
            )
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                continue
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                clients.append(coordinator.client)
                break
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_not_loaded"
            )
    return clients


async def _async_notify(call: ServiceCall) -> None:
    """
    Draw a notification on every targeted bar.
    """
    data: dict[str, Any] = dict(call.data)
    line_2 = data.get("line_2")
    font = data["font"]

    # The two tallest fonts do not leave 16px for a second line. Refusing is
    # better than quietly substituting a font the caller did not ask for.
    if line_2 and font not in TWO_LINE_FONTS:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="font_too_tall_for_two_lines",
            translation_placeholders={"font": font},
        )

    payload = build_elements(
        line_1=data["line_1"],
        line_2=line_2,
        icon=data.get("icon"),
        font=font,
        line_1_color=data.get("line_1_color"),
        line_2_color=data.get("line_2_color"),
        background_color=data.get("background_color"),
        duration=data["duration"],
        priority=PRIORITY_INTERRUPT if data["interrupt"] else PRIORITY_DEFAULT,
    )

    sound = data.get("sound")
    stock_sound = STOCK_SOUNDS.get(sound) if sound and sound != "none" else None

    for client in _clients(call.hass, data[ATTR_DEVICE_ID]):
        try:
            await client.display_draw(payload)
            if stock_sound is not None:
                # application_name is request context, not part of the play
                # payload - the payload model forbids extra keys.
                await client.audio_play(
                    stock_path=stock_sound, application_name=APPLICATION_NAME
                )
        except BusyBarError as err:
            # The call itself was valid, so this is a runtime failure rather
            # than bad input: the bar may be unreachable, or it refused the
            # drawing because something with a higher priority owns the
            # display. ServiceValidationError would wrongly blame the caller.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="notify_failed",
                translation_placeholders={"error": str(err)},
            ) from err


def async_register_services(hass: HomeAssistant) -> None:
    """
    Register every action this integration provides.
    """
    hass.services.async_register(
        DOMAIN, SERVICE_NOTIFY, _async_notify, schema=_NOTIFY_SCHEMA
    )
