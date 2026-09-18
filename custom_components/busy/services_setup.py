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

from functools import partial
import logging
import pathlib
from typing import Any

from busylib import converter, types
from busylib.exceptions import (
    BusyBarAPIError,
    BusyBarError,
    BusyBarFeatureUnavailableError,
)
from busylib.features import assets, notification, timer
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
import voluptuous as vol

from .const import (
    APPLICATION_NAME,
    DEFAULT_DURATION,
    DOMAIN,
    MAX_DURATION,
    SERVICE_CLEAR,
    SERVICE_LIST_ASSETS,
    SERVICE_NEXT_PHASE,
    SERVICE_NOTIFY,
    SERVICE_PAUSE_SESSION,
    SERVICE_PLAY_SOUND,
    SERVICE_RESUME_SESSION,
    SERVICE_SET_THEME,
    SERVICE_START_BUSY,
    SERVICE_START_CUSTOM,
    SERVICE_START_QUICK_INFINITE,
    SERVICE_START_QUICK_INTERVAL,
    SERVICE_START_QUICK_SIMPLE,
    SERVICE_STOP_SESSION,
    SERVICE_UPLOAD_ASSET,
)
from .coordinator import QUICK_CARD_ID, BusyBarCoordinator

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
        **cv.TARGET_SERVICE_FIELDS,
        vol.Required("line_1"): cv.string,
        vol.Optional("line_2"): cv.string,
        # Not checked against a list here: which icons exist is a fact
        # about the bar being written to, and busylib asks it, so a name
        # this integration has never heard of still works if that bar has
        # the file.
        vol.Optional("icon"): cv.string,
        # Not checked against a list here, for the same reason as the
        # icon above: which sounds exist is a fact about the bar being
        # written to, and busylib asks it.
        vol.Optional("sound"): cv.string,
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION)
        ),
        # Above other applications' drawings. Not above a session: while
        # one runs the firmware refuses every drawing whatever its
        # priority, which is why that case has a message of its own.
        vol.Optional("interrupt", default=False): cv.boolean,
        vol.Optional("font", default=notification.DEFAULT_FONT): vol.In(
            notification.ONE_LINE_FONTS
        ),
        # A size for the second line alone. Two lines fit only the
        # shorter fonts, and busylib refuses either line over that.
        vol.Optional("font_2"): vol.In(notification.TWO_LINE_FONTS),
        vol.Optional("line_1_color"): _COLOUR,
        vol.Optional("line_2_color"): _COLOUR,
        vol.Optional("background_color"): _COLOUR,
    }
)


# Which bars to act on. Home Assistant's own target fields rather than a
# device id of our own, because an automation targets what it has to
# hand: a room, a label, one of the bar's entities. Asking for a device
# alone made "every bar in the living room" fail validation, which is the
# most natural way to say it.
_TARGET_SCHEMA = vol.Schema(cv.TARGET_SERVICE_FIELDS)

_SLOT = vol.In(("busy", "custom"))

# Durations are minutes in the action and milliseconds on the wire:
# nobody writes a session length in milliseconds. The bounds are the
# firmware's own - a countdown up to a day, a phase 5 minutes to 8 hours -
# and busylib checks them again before the write, since the bar reports a
# length it will not run as an unparseable snapshot.
_MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=24 * 60))
_PHASE = vol.All(vol.Coerce(int), vol.Range(min=5, max=8 * 60))

# Starting a card is one action per position rather than one with a mode
# to pick, because that is how an automation reads: "start busy" is the
# whole thought, and a dashboard button needs no fields at all. A theme
# here belongs to the session; the card keeps its own.
_START_CARD_SCHEMA = _TARGET_SCHEMA.extend({vol.Optional("theme"): cv.string})

# And one action per kind of quick session, for the same reason - plus
# each kind's settings are different, and a single action could only
# offer all of them and ignore most. Every field is optional: left out,
# the value is the one set on the bar's own quick settings, so an
# automation can either say what it wants or use what is configured.
_QUICK_INFINITE_SCHEMA = _TARGET_SCHEMA.extend({vol.Optional("theme"): cv.string})

_QUICK_SIMPLE_SCHEMA = _TARGET_SCHEMA.extend(
    {
        vol.Optional("duration"): _MINUTES,
        vol.Optional("theme"): cv.string,
    }
)

_QUICK_INTERVAL_SCHEMA = _TARGET_SCHEMA.extend(
    {
        vol.Optional("work"): _PHASE,
        vol.Optional("rest"): _PHASE,
        vol.Optional("cycles"): vol.All(vol.Coerce(int), vol.Range(min=2, max=35)),
        vol.Optional("theme"): cv.string,
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

_PLAY_SOUND_SCHEMA = _TARGET_SCHEMA.extend({vol.Required("sound"): cv.string})

_UPLOAD_SCHEMA = _TARGET_SCHEMA.extend(
    {
        vol.Required("file"): cv.string,
        vol.Optional("name"): cv.string,
    }
)


def _targeted_devices(call: ServiceCall) -> list[str]:
    """
    Every bar the call points at, however it was pointed at.

    A target can name devices, areas, labels, floors or entities, and
    Home Assistant expands all of that for us - but it answers in
    entities, so anything named by area or label arrives as an entity and
    has to be traced back to the device it belongs to.
    """
    selected = async_extract_referenced_entity_ids(
        call.hass, TargetSelection(call.data)
    )
    devices = set(selected.referenced_devices)
    entities = er.async_get(call.hass)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entry = entities.async_get(entity_id)
        if entry is not None and entry.device_id:
            devices.add(entry.device_id)
    if not devices:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_device"
        )
    return sorted(devices)


def _named(hass: HomeAssistant, coordinator: Any) -> str:
    """
    What to call a bar in an error.

    A target can reach several bars, and what one refuses another may
    not - an icon uploaded to one is on that one alone - so an error that
    does not say which bar answered sends the reader to the wrong device.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if getattr(entry, "runtime_data", None) is coordinator:
            return entry.title
    return coordinator.device_id


def _coordinators(hass: HomeAssistant, device_ids: list[str]) -> list[Any]:
    """
    Resolve the targeted Home Assistant devices to their coordinators.

    The coordinator rather than the client, so that an action can ask for
    a refresh when it is done: several of these change settings the bar
    does not push, and without a nudge the entities showing them would
    sit on stale values until the next poll.

    Targets reach things that are not bars - a room holds lamps too - so
    a device that is not one of ours is passed over rather than refused.
    """
    registry = dr.async_get(hass)
    coordinators: list[Any] = []
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device is None:
            continue
        if not any(
            (entry := hass.config_entries.async_get_entry(entry_id)) is not None
            and entry.domain == DOMAIN
            for entry_id in device.config_entries
        ):
            continue
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
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_device"
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

    for coordinator in _coordinators(call.hass, _targeted_devices(call)):
        client = coordinator.client
        try:
            icon = _optional(data.get("icon"))
            sound = _optional(data.get("sound"))
            await notification.notify(
                client,
                data["line_1"],
                line_2=data.get("line_2"),
                icon=await _resolve(coordinator, "image", icon) if icon else None,
                sound=(
                    (await _resolve(coordinator, "sound", sound)).name
                    if sound
                    else None
                ),
                font=data["font"],
                font_2=data.get("font_2"),
                line_1_color=data.get("line_1_color"),
                line_2_color=data.get("line_2_color"),
                background_color=data.get("background_color"),
                duration=data["duration"],
                priority=(
                    notification.PRIORITY_INTERRUPT
                    if data.get("interrupt")
                    else notification.PRIORITY_DEFAULT
                ),
                application_name=APPLICATION_NAME,
            )
        except BusyBarAPIError as err:
            if err.status_code != 409:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="notify_failed",
                    translation_placeholders={
                        "error": f"{_named(call.hass, coordinator)}: {err}"
                    },
                ) from err
            # The bar answers "low priority", which sends the reader
            # looking for a priority to raise. There is none: a running
            # session blocks every drawing, whatever it asks for.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="screen_is_taken",
                translation_placeholders={"bar": _named(call.hass, coordinator)},
            ) from err
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
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="notify_failed",
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err


async def _for_each_bar(call: ServiceCall, work) -> None:
    """
    Run one change against every targeted bar, translating what it raises.

    `TimerNotRunningError` is a validation failure rather than a device
    failure: the automation asked to pause something that is not running,
    and retrying will not help.
    """
    for coordinator in _coordinators(call.hass, _targeted_devices(call)):
        try:
            await work(coordinator, call.data)
        except timer.TimerNotRunningError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="timer_not_running",
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err
        except timer.PhaseTooShortError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="phase_too_short",
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err
        except ValueError as err:
            # busylib refuses a length the card cannot use - a total for an
            # interval card, say - which is a mistake in the automation.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_timer_request",
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
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
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err
        # Several of these change what only the poll reads back.
        await coordinator.async_request_refresh()


def _start_card(slot: types.BusyProfileSlot):
    """
    Build the handler that starts what one of the bar's cards describes.
    """

    async def handler(call: ServiceCall) -> None:
        async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
            await timer.start(coordinator.client, slot, theme=data.get("theme"))

        await _for_each_bar(call, work)

    return handler


def _start_quick(kind: timer.TimerKind):
    """
    Build the handler that starts a quick session of one kind.

    Quick means two things. It carries its own settings, so nothing is
    written to a card - the call says what to run and the snapshot says it
    to the bar. And it names a card outside both switch positions, so the
    bar's own two are not involved even by name; the BUSY app shows the
    session under that other card, which is how its owner can tell where
    it came from.

    Anything the call leaves out comes from the bar's quick settings, the
    ones shown as entities - so an automation can pass a length, or set
    the number first and pass nothing.
    """

    async def handler(call: ServiceCall) -> None:
        async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
            quick = coordinator.quick
            duration = data.get("work" if kind == "interval" else "duration")
            if duration is None and kind != "infinite":
                duration = (
                    quick.work_minutes if kind == "interval" else quick.simple_minutes
                )
            await timer.start(
                coordinator.client,
                card_id=QUICK_CARD_ID,
                kind=kind,
                duration_ms=_ms(duration),
                rest_ms=_ms(data.get("rest", quick.rest_minutes))
                if kind == "interval"
                else None,
                cycles=data.get("cycles", quick.cycles) if kind == "interval" else None,
                theme=data.get("theme") or quick.themes.get(kind),
            )

        await _for_each_bar(call, work)

    return handler


async def _async_stop_session(call: ServiceCall) -> None:
    """
    End the session. Not the selector's off position, which is the bar's
    do-not-disturb rather than a session ending.
    """

    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        await timer.stop(coordinator.client)

    await _for_each_bar(call, work)


async def _async_pause_session(call: ServiceCall) -> None:
    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        await timer.set_paused(coordinator.client, True)

    await _for_each_bar(call, work)


async def _async_resume_session(call: ServiceCall) -> None:
    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        await timer.set_paused(coordinator.client, False)

    await _for_each_bar(call, work)


async def _async_next_phase(call: ServiceCall) -> None:
    """
    Move an interval session on: work to rest, or rest to the next work.
    """

    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        await timer.next_phase(coordinator.client)

    await _for_each_bar(call, work)


async def _async_set_theme(call: ServiceCall) -> None:
    """
    Change a theme, either for this session or for one of the cards.
    """

    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        mode = data.get("mode")
        if mode is None:
            await timer.set_session_theme(coordinator.client, data["theme"])
        else:
            await timer.set_card_theme(coordinator.client, mode, data["theme"])

    await _for_each_bar(call, work)


async def _async_play_sound(call: ServiceCall) -> None:
    """
    Play a sound the bar has.

    Any of them, not only the three with short names: a bar holds the
    timer's own sounds too, and whatever was uploaded to it. The name is
    resolved against that bar, so a sound one bar has and another does
    not fails with the list rather than with silence.
    """

    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        sound = await _resolve(coordinator, "sound", data["sound"])
        await coordinator.client.audio_play(
            path=sound.reference if sound.is_upload else None,
            stock_path=None if sound.is_upload else sound.reference,
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

    async def work(coordinator: BusyBarCoordinator, data: dict[str, Any]) -> None:
        await coordinator.client.display_clear(application_name=APPLICATION_NAME)

    await _for_each_bar(call, work)


async def _async_list_assets(call: ServiceCall) -> ServiceResponse:
    """
    Answer with what this bar can draw and play.

    The icon, sound and theme fields take a name, and which names exist
    is a fact about one bar: the firmware ships a set, a release adds to
    it, and anything uploaded is there too. A list written into a
    dropdown can only be wrong about somebody's bar, so this asks the
    bar - and answers where a person can read it, in the action's own
    response rather than in a log or a diagnostics download.
    """
    answer: dict[str, Any] = {}
    for coordinator in _coordinators(call.hass, _targeted_devices(call)):
        try:
            found = await assets.discover_assets(coordinator.client)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unreachable",
            ) from err

        kinds: dict[str, Any] = {}
        for asset in found:
            names = kinds.setdefault(f"{asset.kind}s", {"shipped": [], "uploaded": {}})
            if asset.application is None:
                names["shipped"].append(asset.name)
            else:
                names["uploaded"].setdefault(asset.application, []).append(asset.name)
        answer[_named(call.hass, coordinator)] = kinds
    return answer


async def _resolve(coordinator: BusyBarCoordinator, kind: str, name: str):
    """
    Find an icon or a sound by name, wherever on the bar it is.

    A name this integration can use is one of the firmware's or one in
    its own folder: the device resolves an upload inside the folder of
    whichever application is drawing. An upload made by the BUSY app or
    the Draw Tool is therefore not ours to draw - so it is copied across
    first, byte for byte, and then it is.

    Doing it here rather than asking the person to copy it themselves is
    the difference between "that icon is on the bar" and "that icon is on
    the bar, but not for you".
    """
    resolve = (
        notification.resolve_icon if kind == "image" else notification.resolve_sound
    )
    try:
        return await resolve(
            coordinator.client, name, application_name=APPLICATION_NAME
        )
    except ValueError:
        theirs = next(
            (
                asset
                for asset in await assets.discover_assets(coordinator.client)
                if asset.kind == kind and asset.name == name and asset.is_upload
            ),
            None,
        )
        if theirs is None:
            raise
        _LOGGER.info(
            "copying %r from %s so Home Assistant can use it",
            theirs.reference,
            theirs.application,
        )
        await assets.copy_to_application(coordinator.client, theirs, APPLICATION_NAME)
        return await resolve(
            coordinator.client, name, application_name=APPLICATION_NAME
        )


async def _async_upload_asset(call: ServiceCall) -> ServiceResponse:
    """
    Put a picture or a sound of your own on the bar.

    The device resolves an asset by name inside the folder of whichever
    application asked for the drawing, so a file uploaded by the BUSY app
    or the Draw Tool is one this integration cannot name. Uploading it
    here puts it where Home Assistant can: its own folder, under the name
    this answers with, which is then what the icon and sound fields take.

    The file is converted on the way - a PNG is scaled and re-encoded for
    the panel, a WAV for the speaker - because what the bar stores is not
    what a phone or a laptop calls a picture.
    """
    source = pathlib.Path(call.data["file"])
    if not call.hass.config.is_allowed_path(str(source)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_allowed",
            translation_placeholders={"file": str(source)},
        )

    def read() -> bytes:
        return source.read_bytes()

    try:
        payload = await call.hass.async_add_executor_job(read)
    except OSError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_unreadable",
            translation_placeholders={"file": str(source), "error": str(err)},
        ) from err

    wanted = call.data.get("name") or source.name
    try:
        filename, converted = await call.hass.async_add_executor_job(
            partial(converter.convert_for_storage, wanted, payload)
        )
    except BusyBarError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_convertible",
            translation_placeholders={"file": str(source), "error": str(err)},
        ) from err

    answer: dict[str, Any] = {}
    for coordinator in _coordinators(call.hass, _targeted_devices(call)):
        try:
            await coordinator.client.assets_upload(
                application_name=APPLICATION_NAME,
                filename=filename,
                data=converted,
            )
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="upload_failed",
                translation_placeholders={
                    "error": f"{_named(call.hass, coordinator)}: {err}"
                },
            ) from err
        # The name without its extension is what the icon and sound
        # fields take, which is the only part a caller needs back.
        answer[_named(call.hass, coordinator)] = {
            "name": pathlib.Path(filename).stem,
            "file": filename,
        }
    return answer


def async_register_services(hass: HomeAssistant) -> None:
    """
    Register every action this integration provides.
    """
    hass.services.async_register(
        DOMAIN, SERVICE_NOTIFY, _async_notify, schema=_NOTIFY_SCHEMA
    )
    for name, handler, schema in (
        (SERVICE_START_BUSY, _start_card("busy"), _START_CARD_SCHEMA),
        (SERVICE_START_CUSTOM, _start_card("custom"), _START_CARD_SCHEMA),
        (
            SERVICE_START_QUICK_INFINITE,
            _start_quick("infinite"),
            _QUICK_INFINITE_SCHEMA,
        ),
        (SERVICE_START_QUICK_SIMPLE, _start_quick("simple"), _QUICK_SIMPLE_SCHEMA),
        (
            SERVICE_START_QUICK_INTERVAL,
            _start_quick("interval"),
            _QUICK_INTERVAL_SCHEMA,
        ),
        (SERVICE_STOP_SESSION, _async_stop_session, _TARGET_SCHEMA),
        (SERVICE_PAUSE_SESSION, _async_pause_session, _TARGET_SCHEMA),
        (SERVICE_RESUME_SESSION, _async_resume_session, _TARGET_SCHEMA),
        (SERVICE_NEXT_PHASE, _async_next_phase, _TARGET_SCHEMA),
        (SERVICE_SET_THEME, _async_set_theme, _SET_THEME_SCHEMA),
        (SERVICE_PLAY_SOUND, _async_play_sound, _PLAY_SOUND_SCHEMA),
        (SERVICE_CLEAR, _async_clear, _TARGET_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

    # Answers with the name the file ended up with, which is what the
    # icon and sound fields then take.
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPLOAD_ASSET,
        _async_upload_asset,
        schema=_UPLOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Read-only, and the caller always wants the answer: this exists to
    # be run from the UI and read.
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_ASSETS,
        _async_list_assets,
        schema=_TARGET_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
