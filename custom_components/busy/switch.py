"""Switches: the bar's smart-home switch, and the settings that are on or off."""

from __future__ import annotations

from functools import partial
from typing import Any

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import QUICK_CARD_ID, BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# What the brightness setting reads back as when the bar is following its
# light sensor instead of a chosen level.
_AUTO = "auto"

# The level to leave the bar at when automatic brightness is switched off
# and there is no chosen level to return to. The brightest, because a panel
# that goes dark on a settings change looks broken.
_DEFAULT_BRIGHTNESS = 100

# The level to unmute to, when the bar was already silent when Home
# Assistant started and there is nothing to restore.
_DEFAULT_VOLUME = 50


def _running_card(data) -> str | None:
    """
    The card the running session belongs to, if one is running.
    """
    if data.snapshot.timer is None:
        return None
    if not timer.timer_state(data.snapshot.timer).is_running:
        return None
    return getattr(data.snapshot.timer.snapshot, "card_id", None)


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
            # This order is the room card's: what to do about a running
            # session first, then the two cards, then the quick ones.
            SessionPausedSwitch(coordinator, name),
            *(SessionSwitch(coordinator, name, slot) for slot in ("busy", "custom")),
            *(
                QuickSessionSwitch(coordinator, name, kind)
                for kind in ("simple", "interval", "infinite")
            ),
            AutomaticBrightnessSwitch(coordinator, name),
            MuteSwitch(coordinator, name),
        ]
    )


class SessionSwitch(BusyBarEntity, SwitchEntity):
    """
    Whether this mode's session is the one running.

    A switch rather than a button because a session is a state, not an
    event: turning it on starts this mode, turning it off ends whatever is
    running. Two of them, one per mode, and only one can be on - the bar
    runs one session at a time, so starting the other ends this one and
    the two switches follow, without either of them having to know about
    the other.

    That is why "is it on" asks which card the running session belongs to
    rather than remembering what was pressed here: a session started on
    the bar itself, or by an automation, moves these switches too.
    """

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, f"session_{slot}")
        self._slot: types.BusyProfileSlot = slot

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        card = data.cards.get(self._slot)
        if card is None:
            return None
        return _running_card(data) == card.id

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._change(partial(timer.start, slot=self._slot))

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Only if this mode is the one running: a session someone started
        # on the other mode is not this switch's to end.
        if self.is_on:
            await self._change(timer.stop)

    async def _change(self, work) -> None:
        try:
            await work(self.coordinator.client)
        except timer.TimerNotRunningError:
            # Already not running, which is what turning it off means.
            return
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class QuickSessionSwitch(BusyBarEntity, SwitchEntity):
    """
    Run a session of one kind, on neither of the bar's cards.

    The two cards belong to their owner: they are what the bar's own
    switch runs and what the BUSY app shows, and asking for forty-five
    minutes this once should not rewrite one of them. So these three run a
    session that carries its own kind, lengths and theme - from the
    settings beside them, which an automation can change first - and name
    a card outside both positions.

    A switch rather than a button for the same reason the two above are
    one: a session is a state. And naming a card of our own is what makes
    the state readable - a session on that card, of this kind, is this
    switch's, however it was started and whatever has restarted since.
    """

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, kind: timer.TimerKind
    ) -> None:
        super().__init__(coordinator, name, f"session_{kind}")
        self._kind: timer.TimerKind = kind

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        if _running_card(data) != QUICK_CARD_ID:
            return False
        running = data.snapshot.timer
        assert running is not None  # _running_card said a session is on
        return timer.kind_of_snapshot(running.snapshot) == self._kind

    async def async_turn_on(self, **kwargs: Any) -> None:
        quick = self.coordinator.quick
        interval = self._kind == "interval"
        try:
            await timer.start(
                self.coordinator.client,
                card_id=QUICK_CARD_ID,
                kind=self._kind,
                duration_ms=(
                    None
                    if self._kind == "infinite"
                    else (quick.work_minutes if interval else quick.simple_minutes)
                    * 60_000
                ),
                rest_ms=quick.rest_minutes * 60_000 if interval else None,
                cycles=quick.cycles if interval else None,
                theme=quick.themes.get(self._kind),
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

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Only the session this switch is showing: one started elsewhere
        # is not this switch's to end.
        if not self.is_on:
            return
        try:
            await timer.stop(self.coordinator.client)
        except timer.TimerNotRunningError:
            return
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class _SettingSwitch(BusyBarEntity, SwitchEntity):
    """
    Base for the settings that are a yes or no.
    """

    _attr_entity_category = EntityCategory.CONFIG

    async def _write(self, call) -> None:
        try:
            await call
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class AutomaticBrightnessSwitch(_SettingSwitch):
    """
    Whether the bar picks its own brightness.

    The firmware keeps one setting that is either a number or "auto", so a
    brightness slider alone cannot express it: a bar on automatic has no
    chosen level to show. This says which of the two the bar is doing, and
    the brightness number carries the level for when it is not automatic.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "automatic_brightness")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.brightness is None:
            return None
        return data.brightness == _AUTO

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(self.coordinator.client.display_brightness_set(_AUTO))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(
            self.coordinator.client.display_brightness_set(_DEFAULT_BRIGHTNESS)
        )


class MuteSwitch(_SettingSwitch):
    """
    Whether the bar is silent.

    The firmware has no mute of its own, only a volume, so muting sets it
    to zero and remembers where it was. The remembered level does not
    survive a Home Assistant restart, and a bar found already silent has
    nothing to restore, so unmuting then picks a middle volume rather than
    guessing loud.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "mute")
        self._unmuted: float | None = None

    def _volume(self) -> float | None:
        data = self.coordinator.data
        if data is None or data.snapshot.volume is None:
            return None
        return data.snapshot.volume.volume

    @property
    def is_on(self) -> bool | None:
        volume = self._volume()
        return None if volume is None else volume == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        volume = self._volume()
        if volume:
            self._unmuted = volume
        await self._write(self.coordinator.client.audio_volume_set(0))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(
            self.coordinator.client.audio_volume_set(self._unmuted or _DEFAULT_VOLUME)
        )


class SessionPausedSwitch(BusyBarEntity, SwitchEntity):
    """
    Whether the running session is paused.

    A switch rather than a sensor and two buttons: it is one fact that can
    be read and set, and pausing is the kind of thing a person expects to
    be able to undo the same way they did it. Turning it on with nothing
    running is refused rather than starting a session to pause.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_paused")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return timer.timer_state(data.snapshot.timer).is_paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._paused(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._paused(False)

    async def _paused(self, paused: bool) -> None:
        try:
            await timer.set_paused(self.coordinator.client, paused)
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
