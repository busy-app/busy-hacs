"""Switches: the bar's sessions, and the settings that are on or off."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from busylib import AsyncBusyBar, types
from busylib.features import timer
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import quick
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator, BusyBarData
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# What the brightness setting reads back as when the bar follows its light
# sensor, and the level to leave it at when that is switched off with no
# chosen level to return to - the brightest, because a panel that goes dark
# on a settings change looks broken.
_AUTO = "auto"
_DEFAULT_BRIGHTNESS = 100

# What to unmute to when the bar was already silent at start-up.
_DEFAULT_VOLUME = 50


def _running_card(data: BusyBarData) -> str | None:
    """The card the running session belongs to, if one is running."""
    running = data.snapshot.timer
    if running is None or not timer.timer_state(running).is_running:
        return None
    return getattr(running.snapshot, "card_id", None)


async def _stop(client: AsyncBusyBar) -> None:
    # Already not running is what turning a session off means.
    with suppress(timer.TimerNotRunningError):
        await timer.stop(client)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(
        [
            # The room card's order: what to do about a running session
            # first, then the two cards, then the quick ones.
            SessionPausedSwitch(coordinator),
            *(CardSwitch(coordinator, slot) for slot in ("busy", "custom")),
            *(
                QuickSwitch(coordinator, kind)
                for kind in ("simple", "interval", "infinite")
            ),
            AutomaticBrightnessSwitch(coordinator),
            MuteSwitch(coordinator),
        ]
    )


class _SessionSwitch(BusyBarEntity, SwitchEntity):
    """
    A session is a state, not an event, so starting one is a switch.

    Whether it is on asks which session is running rather than remembering
    what was pressed here: one started on the bar itself, or by an
    automation, moves these switches too. Turning one off ends only its own
    session - one started elsewhere is not its to end.
    """

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self._write(_stop(self.coordinator.client), "timer_failed")


class CardSwitch(_SessionSwitch):
    """
    Whether this card's session is the one running. One per card; the bar
    runs one session at a time, so starting the other ends this one and the
    two switches follow without knowing about each other.
    """

    def __init__(
        self, coordinator: BusyBarCoordinator, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, f"session_{slot}")
        self._slot = slot

    @property
    def is_on(self) -> bool | None:
        card = self.data.cards.get(self._slot)
        return None if card is None else _running_card(self.data) == card.id

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(
            timer.start(self.coordinator.client, slot=self._slot), "timer_failed"
        )


class QuickSwitch(_SessionSwitch):
    """
    A session of one kind on neither of the bar's cards, run from the
    settings beside it. Naming a card of its own is what makes the state
    readable: a session on that card, of this kind, is this switch's,
    however it was started and whatever has restarted since.
    """

    def __init__(self, coordinator: BusyBarCoordinator, kind: timer.TimerKind) -> None:
        super().__init__(coordinator, f"session_{kind}")
        self._kind = kind

    @property
    def is_on(self) -> bool:
        if _running_card(self.data) != quick.QUICK_CARD_ID:
            return False
        return timer.kind_of_snapshot(self.data.snapshot.timer.snapshot) == self._kind

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(
            quick.start(self.coordinator.client, self.coordinator.quick, self._kind),
            "timer_failed",
        )


class SessionPausedSwitch(BusyBarEntity, SwitchEntity):
    """
    Whether the running session is paused. Turning it on with nothing
    running is refused rather than starting a session to pause.
    """

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "session_paused")

    @property
    def is_on(self) -> bool | None:
        running = self.data.snapshot.timer
        return None if running is None else timer.timer_state(running).is_paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(
            timer.set_paused(self.coordinator.client, True), "timer_failed"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(
            timer.set_paused(self.coordinator.client, False), "timer_failed"
        )


class _SettingSwitch(BusyBarEntity, SwitchEntity):
    """A setting that is a yes or no."""

    _attr_entity_category = EntityCategory.CONFIG


class AutomaticBrightnessSwitch(_SettingSwitch):
    """
    Whether the bar picks its own brightness.

    The firmware keeps one setting that is a number or "auto", so a slider
    alone cannot say a bar is automatic; the brightness number carries the
    level for when it is not.
    """

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "automatic_brightness")

    @property
    def is_on(self) -> bool | None:
        brightness = self.data.brightness
        return None if brightness is None else brightness == _AUTO

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(self.coordinator.client.display_brightness_set(_AUTO))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(
            self.coordinator.client.display_brightness_set(_DEFAULT_BRIGHTNESS)
        )


class MuteSwitch(_SettingSwitch):
    """
    Whether the bar is silent.

    The firmware has no mute, only a volume, so muting sets it to zero and
    remembers where it was. The remembered level does not survive a restart,
    and a bar found already silent has nothing to restore, so unmuting then
    picks a middle volume rather than guessing loud.
    """

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "mute")
        self._unmuted: float | None = None

    def _volume(self) -> float | None:
        volume = self.data.snapshot.volume
        return None if volume is None else volume.volume

    @property
    def is_on(self) -> bool | None:
        volume = self._volume()
        return None if volume is None else volume == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        if volume := self._volume():
            self._unmuted = volume
        await self._write(self.coordinator.client.audio_volume_set(0))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(
            self.coordinator.client.audio_volume_set(self._unmuted or _DEFAULT_VOLUME)
        )
