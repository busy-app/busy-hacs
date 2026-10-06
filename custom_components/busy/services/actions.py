"""What each action does to one bar.

Nothing here knows how a notification is drawn. Placing elements on a 72x16
panel depends on the font, the icon's width and what the firmware can draw,
and only busylib knows the device's version - so the layout lives in
`busylib.features.notification` and this module collects fields and calls it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import difflib
from functools import partial
from typing import Any

from busylib import types
from busylib.exceptions import BusyBarAPIError, BusyBarError
from busylib.features import assets, notification, timer
from homeassistant.core import ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .. import quick
from ..const import APPLICATION_NAME, DOMAIN
from ..coordinator import BusyBarCoordinator
from ..errors import translate
from . import schemas
from .targets import bars_targeted, title

type Data = Mapping[str, Any]
type Work = Callable[[BusyBarCoordinator, Data], Awaitable[None]]


@dataclass(frozen=True)
class Action:
    """
    One action: what it accepts, what it does, and how it fails.

    `drawing` ones may be refused because the screen is taken, and leave the
    poll alone; the others are sessions and settings, which change what only
    the poll reads back. `failed` and `invalid` name the messages, so that an
    error says what was being done.
    """

    schema: Any
    work: Work
    drawing: bool = False
    failed: str = "timer_failed"
    invalid: str = "invalid_timer_request"


def _screen_is_taken(coordinator: BusyBarCoordinator) -> HomeAssistantError:
    """
    Which of the two refusals a 409 was, in words worth reading.

    "Low priority" is true and useless: a person needs to know what to do.
    A running session refuses every drawing whatever its priority (the
    firmware sets a loader priority above the API's maximum) and nothing
    helps but ending it. The bar's own screens sit lower, and an
    interrupting drawing gets past them.
    """
    running = coordinator.data.snapshot.timer
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=(
            "session_owns_the_screen"
            if running is not None and timer.timer_state(running).is_running
            else "screen_is_busy"
        ),
        translation_placeholders={"bar": title(coordinator)},
    )


async def run(call: ServiceCall, action: Action) -> None:
    """
    Run one change against every targeted bar, translating what it raises.

    Drawings have their own messages and may be refused because the screen
    is taken; everything else is a session or a setting, and asks for a
    re-read afterwards because several of these change what only the poll
    reads back.
    """
    for coordinator in bars_targeted(call):
        try:
            await action.work(coordinator, call.data)
        except (BusyBarError, ValueError) as err:
            if (
                action.drawing
                and isinstance(err, BusyBarAPIError)
                and err.status_code == 409
            ):
                raise _screen_is_taken(coordinator) from err
            raise translate(
                err,
                failed=action.failed,
                invalid=action.invalid,
                bar=title(coordinator),
            ) from err
        if not action.drawing:
            await coordinator.async_request_refresh()


def _optional(value: str | None) -> str | None:
    """Treat the dropdowns' "none" as nothing chosen."""
    return None if value in (None, "none") else value


def _priority(interrupt: bool) -> int:
    return (
        notification.PRIORITY_INTERRUPT if interrupt else notification.PRIORITY_DEFAULT
    )


async def _resolve(coordinator: BusyBarCoordinator, kind: str, name: str):
    """
    Find an icon or a sound the firmware ships, by name.

    A name that is on no bar is a mistake in the automation, not a device
    failure: say what this bar does have, the way a wrong theme does.
    """
    resolve = (
        notification.resolve_icon if kind == "image" else notification.resolve_sound
    )
    try:
        return await resolve(
            coordinator.client, name, application_name=APPLICATION_NAME
        )
    except ValueError:
        catalogue = await assets.discover_assets(coordinator.client)
        available = sorted(
            asset.name
            for asset in catalogue
            if asset.kind == kind and not asset.is_upload
        )
        # A bar holds a hundred icons and printing all of them is a wall of
        # text; the few that look like the typo are what it needs.
        closest = difflib.get_close_matches(name, available, n=5, cutoff=0.5)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_asset_closest" if closest else "unknown_asset",
            translation_placeholders={
                "kind": "icon" if kind == "image" else "sound",
                "name": name,
                "closest": ", ".join(closest),
                "count": str(len(available)),
            },
        ) from None


# The ids busylib draws a notification's pieces under: the background, the
# icon and the two lines. The bar updates a drawing element by element, by id,
# so a notification that leaves one out leaves the previous one's there.
_NOTIFICATION_ELEMENTS = ("0", "10", "11", "12")


class _Replacing:
    """
    A client that, when a notification is drawn, takes down whichever of its
    pieces the new one does not use - so the notification replaces the last
    one instead of being drawn over it.

    After drawing and not before, so nothing goes blank in between; and only
    the notification's own pieces, so a drawing left up with `draw` stays.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def display_draw(self, elements: Any, **kwargs: Any) -> Any:
        drawn = await self._client.display_draw(elements, **kwargs)
        used = {element.id for element in elements.elements}
        stale = [i for i in _NOTIFICATION_ELEMENTS if i not in used]
        if stale:
            await self._client.display_clear(
                element_ids=stale, application_name=elements.application_name
            )
        return drawn


async def notify(coordinator: BusyBarCoordinator, data: Data) -> None:
    icon = _optional(data.get("icon"))
    sound = _optional(data.get("sound"))
    await notification.notify(
        _Replacing(coordinator.client),
        data["line_1"],
        line_2=data.get("line_2"),
        icon=await _resolve(coordinator, "image", icon) if icon else None,
        sound=(await _resolve(coordinator, "sound", sound)).name if sound else None,
        line_1_font=data["line_1_font"],
        line_2_font=data.get("line_2_font"),
        line_1_color=data.get("line_1_color"),
        line_2_color=data.get("line_2_color"),
        background_color=data.get("background_color"),
        duration=data["duration"],
        priority=_priority(data["interrupt"]),
        application_name=APPLICATION_NAME,
    )


async def draw(coordinator: BusyBarCoordinator, data: Data) -> None:
    """
    One piece of text, placed exactly, with every field the firmware takes
    and a name it can be removed by - which is how a drawing stays up until
    something takes it down, or is replaced in place without a flicker. The
    back display is here and not in a notification because what goes on the
    back is usually one word for the room, not a layout.
    """
    element = types.TextElement(
        id=data.get("name") or f"draw_{data['display']}",
        text=data["text"],
        font=data["font"],
        color=data.get("color"),
        align=data.get("align"),
        x=data["x"],
        y=data["y"],
        display=data["display"],
        width=data.get("width"),
        scroll_rate=data.get("scroll_rate"),
        scroll_start_delay=data.get("scroll_start_delay"),
        # Seconds, and zero means "until something clears it".
        timeout=data["duration"],
    )
    payload = types.DisplayElements(
        application_name=APPLICATION_NAME,
        priority=_priority(data["interrupt"]),
        led_notification_color=data.get("led_color"),
        elements=[element],
    )
    # The panel's fonts are bitmap ASCII, so anything else is replaced rather
    # than refused by the bar with a 400 that names no character.
    await coordinator.client.display_draw(payload, sanitize_text=True)


async def clear(coordinator: BusyBarCoordinator, data: Data) -> None:
    # Only this integration's elements: the bar owns what other applications
    # drew, and a notification with a duration goes away by itself.
    await coordinator.client.display_clear(application_name=APPLICATION_NAME)


async def play_sound(coordinator: BusyBarCoordinator, data: Data) -> None:
    sound = await _resolve(coordinator, "sound", data["sound"])
    await coordinator.client.audio_play(
        path=sound.reference if sound.is_upload else None,
        stock_path=None if sound.is_upload else sound.reference,
        application_name=APPLICATION_NAME,
    )


async def start_card(slot: types.BusyProfileSlot, c: BusyBarCoordinator, d: Data):
    await quick.check_theme(c.client, d.get("theme"))
    await timer.start(c.client, slot, theme=d.get("theme"))


async def start_quick(kind: timer.TimerKind, c: BusyBarCoordinator, d: Data):
    interval = kind == "interval"
    await quick.start(
        c.client,
        c.quick,
        kind,
        duration=d.get("work" if interval else "duration"),
        rest=d.get("rest"),
        cycles=d.get("cycles"),
        theme=d.get("theme"),
    )


async def set_theme(c: BusyBarCoordinator, d: Data) -> None:
    if (mode := d.get("mode")) is None:
        await timer.set_session_theme(c.client, d["theme"])
    else:
        await timer.set_card_theme(c.client, mode, d["theme"])


# Starting a card is one action per position
# rather than one with a mode to pick, because that is how an automation
# reads: "start busy" is the whole thought. Likewise one per kind of quick
# session, since each kind's settings differ.
ACTIONS: dict[str, Action] = {
    "notify": Action(
        schemas.NOTIFY, notify, True, "notify_failed", "invalid_notification"
    ),
    "draw": Action(schemas.DRAW, draw, True, "display_failed", "invalid_drawing"),
    "clear": Action(schemas.TARGET, clear, True, "display_failed", "invalid_drawing"),
    "play_sound": Action(
        schemas.PLAY_SOUND, play_sound, True, "sound_failed", "sound_failed"
    ),
    "start_busy": Action(schemas.START_CARD, partial(start_card, "busy")),
    "start_custom": Action(schemas.START_CARD, partial(start_card, "custom")),
    "start_quick_infinite": Action(
        schemas.QUICK_INFINITE, partial(start_quick, "infinite")
    ),
    "start_quick_simple": Action(schemas.QUICK_SIMPLE, partial(start_quick, "simple")),
    "start_quick_interval": Action(
        schemas.QUICK_INTERVAL, partial(start_quick, "interval")
    ),
    # Not the selector's off position, which is do-not-disturb.
    "stop_session": Action(schemas.TARGET, lambda c, d: timer.stop(c.client)),
    "pause_session": Action(
        schemas.TARGET, lambda c, d: timer.set_paused(c.client, True)
    ),
    "resume_session": Action(
        schemas.TARGET, lambda c, d: timer.set_paused(c.client, False)
    ),
    # Work to rest, or rest to the next work.
    "next_phase": Action(schemas.TARGET, lambda c, d: timer.next_phase(c.client)),
    "set_theme": Action(schemas.SET_THEME, set_theme),
}


async def list_assets(call: ServiceCall) -> ServiceResponse:
    """
    Answer with what each targeted bar can draw and play.

    The icon, sound and theme fields take a name, and which names exist is
    a fact about one bar: a firmware release adds to the set. A list written
    into a dropdown can only be wrong about somebody's bar, so this asks the
    bar and answers where a person can read it - only what the firmware
    ships, in the form a field takes.
    """
    answer: dict[str, Any] = {}
    for coordinator in bars_targeted(call):
        try:
            found = await assets.discover_assets(coordinator.client)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_unreachable"
            ) from err
        kinds: dict[str, list[str]] = {}
        for asset in found:
            if not asset.is_upload:
                kinds.setdefault(f"{asset.kind}s", []).append(asset.name)
        answer[title(coordinator)] = kinds
    return answer
