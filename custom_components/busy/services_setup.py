"""Registration of the BUSY Bar actions.

Actions are registered once, from `async_setup`, rather than per config
entry: Home Assistant expects an integration's actions to exist as soon as
it is loaded so an automation referencing one validates even while the
device is unreachable. This is the `action-setup` rule in the integration
quality scale, and doing it from `async_setup_entry` would also register the
same action again for every bar that gets added.

Nothing here knows how a notification is drawn. Placing elements on a 72x16
panel depends on the font, on the icon's width and on what the firmware can
draw, and only busylib knows the device's version - so the layout lives in
`busylib.features.notification` and this module collects fields and calls it.
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
from busylib.exceptions import BusyBarError, BusyBarFeatureUnavailableError
from busylib.features import notification

from .const import (
    APPLICATION_NAME,
    DEFAULT_DURATION,
    DOMAIN,
    MAX_DURATION,
    SERVICE_NOTIFY,
)

_LOGGER = logging.getLogger(__name__)

_COLOUR = vol.All(
    [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(3, 3)
)

# The icon, sound and font choices are validated against busylib's own
# catalogues rather than a copy kept here, so a name that services.yaml
# offers but the library does not know fails with a readable error instead
# of a 400 from the device.
_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("line_1"): cv.string,
        vol.Optional("line_2"): cv.string,
        vol.Optional("icon"): vol.Any("none", vol.In(sorted(notification.STOCK_ICONS))),
        vol.Optional("sound"): vol.Any(
            "none", vol.In(sorted(notification.STOCK_SOUNDS))
        ),
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION)
        ),
        vol.Optional("interrupt", default=False): cv.boolean,
        vol.Optional("font", default=notification.DEFAULT_FONT): vol.In(
            notification.ONE_LINE_FONTS
        ),
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


def _optional(value: str | None) -> str | None:
    """
    Treat the dropdowns' "none" as nothing chosen.
    """
    return None if value in (None, "none") else value


async def _async_notify(call: ServiceCall) -> None:
    """
    Draw a notification on every targeted bar.
    """
    data: dict[str, Any] = dict(call.data)

    for client in _clients(call.hass, data[ATTR_DEVICE_ID]):
        try:
            await notification.notify(
                client,
                data["line_1"],
                line_2=data.get("line_2"),
                icon=_optional(data.get("icon")),
                sound=_optional(data.get("sound")),
                font=data["font"],
                line_1_color=data.get("line_1_color"),
                line_2_color=data.get("line_2_color"),
                background_color=data.get("background_color"),
                duration=data["duration"],
                priority=(
                    notification.PRIORITY_INTERRUPT
                    if data["interrupt"]
                    else notification.PRIORITY_DEFAULT
                ),
                application_name=APPLICATION_NAME,
            )
        except BusyBarFeatureUnavailableError as err:
            # Caught before BusyBarError, which it subclasses: the fix here
            # is updating the bar's firmware, not retrying, so reporting it
            # as a failed notification would send someone the wrong way.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="feature_needs_newer_firmware",
                translation_placeholders={
                    "feature": err.feature,
                    "required_version": err.required_version,
                    "device_version": str(err.device_version),
                },
            ) from err
        except ValueError as err:
            # The library refuses a font the chosen layout cannot place, and
            # names that are not in its catalogues. That is the caller's
            # mistake, so it is a validation error rather than a failure -
            # and it carries a translation key, since a raw string here
            # would be the one message this action cannot translate.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_notification",
                translation_placeholders={"error": str(err)},
            ) from err
        except BusyBarError as err:
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
