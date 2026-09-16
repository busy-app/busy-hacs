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
from busylib.features import notification, timer

from .const import (
    APPLICATION_NAME,
    DEFAULT_DURATION,
    DOMAIN,
    MAX_DURATION,
    SERVICE_CLEAR,
    SERVICE_NEXT_PHASE,
    SERVICE_NOTIFY,
    SERVICE_PAUSE_SESSION,
    SERVICE_PLAY_SOUND,
    SERVICE_RESUME_SESSION,
    SERVICE_SET_THEME,
    SERVICE_START_SESSION,
    SERVICE_STOP_SESSION,
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
        # Not checked against a list here: which icons exist is a fact
        # about the bar being written to, and busylib asks it, so a name
        # this integration has never heard of still works if that bar has
        # the file.
        vol.Optional("icon"): cv.string,
        vol.Optional("sound"): vol.Any(
            "none", vol.In(sorted(notification.STOCK_SOUNDS))
        ),
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION)
        ),
        vol.Optional("font", default=notification.DEFAULT_FONT): vol.In(
            notification.ONE_LINE_FONTS
        ),
        vol.Optional("line_1_color"): _COLOUR,
        vol.Optional("line_2_color"): _COLOUR,
        vol.Optional("background_color"): _COLOUR,
    }
)


# Which bar to target, and nothing else: these actions take the same
# device selector as every other action here.
_TARGET_SCHEMA = vol.Schema(
    {vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
)

_SLOT = vol.In(("busy", "custom"))

# Durations are minutes in the action and milliseconds on the wire:
# nobody writes a pomodoro in milliseconds, and the bar takes nothing
# shorter than five minutes anyway.
_MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=24 * 60))

_START_SCHEMA = _TARGET_SCHEMA.extend(
    {
        # "Mode" is what the bar's two positions are called; `card` is what
        # the API calls the thing each one points at.
        vol.Optional("mode", default="busy"): _SLOT,
        # Endless, a countdown or a pomodoro. Given, the mode's timer
        # becomes that kind before the session starts, which is what makes
        # "run a countdown for forty minutes" one call rather than three.
        vol.Optional("kind"): vol.In(("endless", "countdown", "pomodoro")),
        # A theme here belongs to this session only; the card keeps its own.
        vol.Optional("theme"): cv.string,
        # These do outlast the session. A session cannot carry a length of
        # its own - the device rejects a snapshot that disagrees with its
        # card - so asking for one writes the card, and the bar and the
        # phone app see the change. Left out, the card is not touched.
        vol.Optional("duration"): _MINUTES,
        vol.Optional("rest"): _MINUTES,
        vol.Optional("cycles"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
    }
)

_SET_THEME_SCHEMA = _TARGET_SCHEMA.extend(
    {
        vol.Required("theme"): cv.string,
        # Without a mode, the running session's theme changes and reverts
        # when it ends. With one, that mode's own theme changes for good.
        vol.Optional("mode"): _SLOT,
    }
)

_PLAY_SOUND_SCHEMA = _TARGET_SCHEMA.extend(
    {vol.Required("sound"): vol.In(sorted(notification.STOCK_SOUNDS))}
)


def _coordinators(hass: HomeAssistant, device_ids: list[str]) -> list[Any]:
    """
    Resolve the targeted Home Assistant devices to their coordinators.

    The coordinator rather than the client, so that an action can ask for
    a refresh when it is done: several of these change settings the bar
    does not push - a mode's timer, its kind - and without a nudge the
    entities showing them would sit on stale values until the next poll.
    """
    registry = dr.async_get(hass)
    coordinators: list[Any] = []
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
                coordinators.append(coordinator)
                break
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_not_loaded"
            )
    return coordinators


def _ms(minutes: int | None) -> int | None:
    """
    Minutes as the action takes them, milliseconds as the bar wants them.
    """
    return None if minutes is None else minutes * 60_000


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

    for coordinator in _coordinators(call.hass, data[ATTR_DEVICE_ID]):
        client = coordinator.client
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
                priority=notification.PRIORITY_DEFAULT,
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


async def _for_each_bar(call: ServiceCall, work) -> None:
    """
    Run one change against every targeted bar, translating what it raises.

    `TimerNotRunningError` is a validation failure rather than a device
    failure: the automation asked to pause something that is not running,
    and retrying will not help.
    """
    for coordinator in _coordinators(call.hass, call.data[ATTR_DEVICE_ID]):
        try:
            await work(coordinator.client, call.data)
        except timer.TimerNotRunningError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="timer_not_running",
                translation_placeholders={"error": str(err)},
            ) from err
        except timer.PhaseTooShortError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="phase_too_short",
                translation_placeholders={"error": str(err)},
            ) from err
        except ValueError as err:
            # busylib refuses a length the card cannot use - a total for an
            # interval card, say - which is a mistake in the automation.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_timer_request",
                translation_placeholders={"error": str(err)},
            ) from err
        except timer.UnknownThemeError as err:
            # Caught before BusyBarError, which it subclasses: a theme
            # this bar does not have is a mistake in the automation, not
            # a device failure, and retrying will not fix it.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_theme",
                translation_placeholders={
                    "theme": err.theme,
                    "available": ", ".join(err.available),
                },
            ) from err
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # Several of these change what only the poll reads back.
        await coordinator.async_request_refresh()


async def _async_start_session(call: ServiceCall) -> None:
    """
    Start the session one of the bar's two cards describes.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        mode = data["mode"]
        wanted = ("kind", "duration", "rest", "cycles")
        if any(data.get(field) is not None for field in wanted):
            # The library puts the duration where that kind of timer keeps
            # it, so this does not have to know whether the mode runs a
            # countdown or a pomodoro.
            await timer.configure(
                client,
                mode,
                kind=data.get("kind"),
                duration_ms=_ms(data.get("duration")),
                rest_ms=_ms(data.get("rest")),
                cycles=data.get("cycles"),
            )
        await timer.start(client, mode, theme=data.get("theme"))

    await _for_each_bar(call, work)


async def _async_stop_session(call: ServiceCall) -> None:
    """
    End the session. Not the selector's off position, which is the bar's
    do-not-disturb rather than a session ending.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await timer.stop(client)

    await _for_each_bar(call, work)


async def _async_pause_session(call: ServiceCall) -> None:
    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await timer.set_paused(client, True)

    await _for_each_bar(call, work)


async def _async_resume_session(call: ServiceCall) -> None:
    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await timer.set_paused(client, False)

    await _for_each_bar(call, work)


async def _async_next_phase(call: ServiceCall) -> None:
    """
    Move an interval session on: work to rest, or rest to the next work.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await timer.next_phase(client)

    await _for_each_bar(call, work)


async def _async_set_theme(call: ServiceCall) -> None:
    """
    Change a theme, either for this session or for one of the cards.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        mode = data.get("mode")
        if mode is None:
            await timer.set_session_theme(client, data["theme"])
        else:
            await timer.set_card_theme(client, mode, data["theme"])

    await _for_each_bar(call, work)


async def _async_play_sound(call: ServiceCall) -> None:
    """
    Play one of the bar's built-in sounds.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await client.audio_play(
            stock_path=notification.STOCK_SOUNDS[data["sound"]],
            application_name=APPLICATION_NAME,
        )

    await _for_each_bar(call, work)


async def _async_clear(call: ServiceCall) -> None:
    """
    Remove what this integration drew, leaving the bar's own screen.

    Only this integration's elements: the bar owns everything drawn under
    a different application name, and a notification with a duration
    disappears on its own anyway.
    """

    async def work(client: AsyncBusyBar, data: dict[str, Any]) -> None:
        await client.display_clear(application_name=APPLICATION_NAME)

    await _for_each_bar(call, work)


def async_register_services(hass: HomeAssistant) -> None:
    """
    Register every action this integration provides.
    """
    hass.services.async_register(
        DOMAIN, SERVICE_NOTIFY, _async_notify, schema=_NOTIFY_SCHEMA
    )
    for name, handler, schema in (
        (SERVICE_START_SESSION, _async_start_session, _START_SCHEMA),
        (SERVICE_STOP_SESSION, _async_stop_session, _TARGET_SCHEMA),
        (SERVICE_PAUSE_SESSION, _async_pause_session, _TARGET_SCHEMA),
        (SERVICE_RESUME_SESSION, _async_resume_session, _TARGET_SCHEMA),
        (SERVICE_NEXT_PHASE, _async_next_phase, _TARGET_SCHEMA),
        (SERVICE_SET_THEME, _async_set_theme, _SET_THEME_SCHEMA),
        (SERVICE_PLAY_SOUND, _async_play_sound, _PLAY_SOUND_SCHEMA),
        (SERVICE_CLEAR, _async_clear, _TARGET_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)
