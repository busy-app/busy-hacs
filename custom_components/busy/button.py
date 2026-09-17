"""The bar's own buttons, pressable from Home Assistant."""

from __future__ import annotations

from functools import partial

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import QUICK_SLOT, BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The three buttons on the bar. Pressing one here is indistinguishable from
# pressing it on the device: the firmware puts the same event on its state
# stream either way, confirmed against hardware.
_BUTTONS = (
    ("ok", types.InputKey.OK),
    ("back", types.InputKey.BACK),
    ("start", types.InputKey.START),
)


# Moving the switch, one button per position. A select entity carried
# these instead, but Home Assistant then offered every select's generic
# actions for it - "Select first", "Select next", "Select option" - which
# say nothing about a bar and cannot be renamed by an integration. A
# button per position names itself in the automation editor.
#
# "Switch" is the firmware's own word for it: the state stream calls the
# event a SwitchEvent and its values SwitchPosition.
_POSITIONS = (
    ("switch_busy", types.InputKey.BUSY),
    ("switch_custom", types.InputKey.CUSTOM),
    ("switch_off", types.InputKey.OFF),
    ("switch_apps", types.InputKey.APPS),
    ("switch_settings", types.InputKey.SETTINGS),
)

# Scrolling, which is how the bar is navigated. The keys are called up and
# down in the HTTP API, but what a person sees is the selection moving
# sideways - the firmware's menus map up to "focus the next item" and down
# to the previous - so they are named for what they do. Worth having from
# here for the same reason the buttons are: someone who cannot reach the
# bar can still drive it.
_SCROLL = (
    ("scroll_right", types.InputKey.UP),
    ("scroll_left", types.InputKey.DOWN),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    try:
        name = (await coordinator.client.name()).name
    except BusyBarError as err:
        raise PlatformNotReady(
            f"BUSY Bar {coordinator.device_id} is unreachable"
        ) from err

    async_add_entities(
        [
            *(
                BusyBarButton(coordinator, name, key, input_key)
                for key, input_key in (*_BUTTONS, *_POSITIONS, *_SCROLL)
            ),
            NextPhaseButton(coordinator, name),
            *(
                StartSessionButton(coordinator, name, slot)
                for slot in ("busy", "custom")
            ),
            *(
                QuickSessionButton(coordinator, name, kind)
                for kind in ("infinite", "simple", "interval")
            ),
        ]
    )


class BusyBarButton(BusyBarEntity, ButtonEntity):
    """
    One of the bar's buttons, or a way to move its switch.

    Hidden from dashboards by default. These are a remote control: thirteen
    of them, useful in an automation and when someone cannot reach the bar,
    and noise in the card for a room. They are created, they work, and they
    are one click from being shown - what they are not is on the wall by
    default.

    Useful for the same reasons the physical button is: dismissing what is
    on screen, or starting whatever the current profile starts, from an
    automation rather than by reaching for the bar.
    """

    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        name: str,
        key: str,
        input_key: types.InputKey,
    ) -> None:
        super().__init__(coordinator, name, key)
        self._input_key = input_key

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.input(self._input_key)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="input_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class _SessionButton(BusyBarEntity, ButtonEntity):
    """
    Base for the buttons that change a running session.

    One-way and takes no options, which is what makes it a button rather
    than an action - the actions with fields are still there for an
    automation that needs them.
    """

    async def _change(self, work) -> None:
        try:
            await work(self.coordinator.client)
        except timer.TimerNotRunningError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_not_running",
                translation_placeholders={"error": str(err)},
            ) from err
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class NextPhaseButton(_SessionButton):
    """
    Move an interval session on to its next phase.

    The obvious use is cutting a break short, or starting one early.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_next_phase")

    async def async_press(self) -> None:
        await self._change(timer.next_phase)


class StartSessionButton(_SessionButton):
    """
    Start the session one of the bar's two cards describes.

    The same thing the matching switch does, as a button, because a
    dashboard card and an automation usually want "start this" and not a
    state to hold: a button says so in one word and reads well next to the
    quick-start ones below.
    """

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, f"session_start_{slot}")
        self._slot: types.BusyProfileSlot = slot

    async def async_press(self) -> None:
        await self._change(partial(timer.start, slot=self._slot))


class QuickSessionButton(_SessionButton):
    """
    Start a session of one kind, without touching either card.

    The two cards belong to their owner: they are what the bar's own
    switch runs and what the BUSY app shows, and wanting a countdown of
    forty-five minutes this once should not rewrite one of them. So these
    start a session carrying its own kind and lengths - taken from the
    numbers beside them, which an automation can set first - and both
    cards stay as they were.

    The session still names a card, since that is what the app shows it
    under, and the switches follow it the way they follow any session.
    """

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, kind: timer.TimerKind
    ) -> None:
        super().__init__(coordinator, name, f"session_start_{kind}")
        self._kind: timer.TimerKind = kind

    async def async_press(self) -> None:
        quick = self.coordinator.quick
        interval = self._kind == "interval"
        try:
            await timer.start(
                self.coordinator.client,
                QUICK_SLOT,
                kind=self._kind,
                duration_ms=(
                    None
                    if self._kind == "infinite"
                    else (quick.work_minutes if interval else quick.simple_minutes)
                    * 60_000
                ),
                rest_ms=quick.rest_minutes * 60_000 if interval else None,
                cycles=quick.cycles if interval else None,
            )
        except (timer.PhaseTooShortError, ValueError) as err:
            # The bar answers a length it will not run with a parse error
            # about the whole snapshot, so this is the only place the
            # reason is legible.
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="phase_too_short",
                translation_placeholders={"error": str(err)},
            ) from err
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
