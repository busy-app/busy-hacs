"""Switches: the bar's smart-home switch, and the settings that are on or off."""

from __future__ import annotations

from typing import Any

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
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
            SmartHomeSwitch(coordinator, name),
            TimerPausedSwitch(coordinator, name),
            AutomaticBrightnessSwitch(coordinator, name),
            MuteSwitch(coordinator, name),
            AutomaticUpdatesSwitch(coordinator, name),
        ]
    )


class SmartHomeSwitch(BusyBarEntity, SwitchEntity):
    """
    The bar's own smart-home switch.

    A switch, not a light: it starts and stops a Busy session, and Home
    Assistant drew it as a lamp with a brightness slider that did nothing.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "smart_home_switch")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.smart_home

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, state: bool) -> None:
        try:
            await self.coordinator.client.smart_home_switch_set(state)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
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
            self.coordinator.client.audio_volume_set(
                self._unmuted or _DEFAULT_VOLUME
            )
        )


class AutomaticUpdatesSwitch(_SettingSwitch):
    """
    Whether the bar installs firmware updates by itself.

    The bar keeps a window it is allowed to do that in - overnight by
    default - which is left alone here: this only turns the whole thing on
    or off, and the window is reported alongside it.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "automatic_updates")

    def _settings(self):
        data = self.coordinator.data
        return None if data is None else data.autoupdate

    @property
    def is_on(self) -> bool | None:
        settings = self._settings()
        return None if settings is None else settings.is_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        settings = self._settings()
        if settings is None:
            return None
        return {
            "window_start": settings.interval_start,
            "window_end": settings.interval_end,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        settings = self._settings()
        # The bar replaces the whole settings object, so the window has to
        # be sent back with the flag or it would be reset.
        payload = types.AutoupdateSettings(
            is_enabled=enabled,
            interval_start=None if settings is None else settings.interval_start,
            interval_end=None if settings is None else settings.interval_end,
        )
        await self._write(self.coordinator.client.update_autoupdate_set(payload))


class TimerPausedSwitch(BusyBarEntity, SwitchEntity):
    """
    Whether the running session is paused.

    A switch rather than a sensor and two buttons: it is one fact that can
    be read and set, and pausing is the kind of thing a person expects to
    be able to undo the same way they did it. Turning it on with nothing
    running is refused rather than starting a session to pause.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_paused")

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
