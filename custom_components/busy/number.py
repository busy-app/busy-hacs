"""Adjustable settings of the bar: how bright, how loud."""

from __future__ import annotations

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]


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
            BrightnessNumber(coordinator, name),
            VolumeNumber(coordinator, name),
            *(
                entity(coordinator, name, slot)
                for slot in ("busy", "custom")
                for entity in (WorkNumber, RestNumber, CyclesNumber)
            ),
        ]
    )


class _SettingNumber(BusyBarEntity, NumberEntity):
    """
    A number the bar keeps as a percentage.

    Both settings are whole percentages, both belong in the device page's
    configuration section rather than among the things being watched.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER


class BrightnessNumber(_SettingNumber):
    """
    How bright the panels are set to be.

    Reports nothing while the bar is set to automatic brightness: there is
    no chosen level then, only whatever the light sensor is asking for.
    Setting a level here turns automatic off, which is what moving a
    brightness slider is understood to mean.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "brightness")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or data.brightness is None:
            return None
        try:
            return float(data.brightness)
        except ValueError:
            # "auto", the only non-numeric the bar reports.
            return None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.display_brightness_set(int(value))
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class VolumeNumber(_SettingNumber):
    """
    How loud the bar's sounds are.

    Read from the stream rather than polled: the bar pushes a volume change
    as soon as it happens, including one made on the device itself.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "volume")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or data.snapshot.volume is None:
            return None
        return data.snapshot.volume.volume

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.audio_volume_set(value)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class _CardNumber(BusyBarEntity, NumberEntity):
    """
    One setting of one of the bar's two modes.

    These are what make a session a particular length. A session cannot
    carry a length of its own - the device refuses a snapshot that
    disagrees with the card it names - so this writes the mode's own
    timer, which the bar and the BUSY app see too.

    Unavailable when the mode's timer has no such setting: an endless
    mode has no lengths at all, and a countdown has no rest or cycles.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot,
        key: str,
    ) -> None:
        super().__init__(coordinator, name, f"{slot}_{key}")
        self._slot: types.BusyProfileSlot = slot

    def _settings(self):
        data = self.coordinator.data
        if data is None:
            return None
        card = data.cards.get(self._slot)
        return None if card is None else card.timer_settings

    async def _write(self, **change: int) -> None:
        try:
            await timer.configure(self.coordinator.client, self._slot, **change)
        except timer.PhaseTooShortError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="phase_too_short",
                translation_placeholders={"error": str(err)},
            ) from err
        except (BusyBarError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class WorkNumber(_CardNumber):
    """
    How long the mode runs for - the work phase, or the whole countdown.

    Five minutes is the floor because the bar ignores anything shorter and
    keeps what it had, without saying so.
    """

    _attr_native_min_value = timer.MINIMUM_PHASE_MS // 60_000
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, slot, "work")

    @property
    def available(self) -> bool:
        return super().available and not isinstance(
            self._settings(), types.BusyTimerInfiniteSettings
        )

    @property
    def native_value(self) -> float | None:
        settings = self._settings()
        if isinstance(settings, types.BusySnapshotIntervalSettings):
            return settings.interval_work_ms / 60_000
        if isinstance(settings, types.BusyTimerSimpleSettings):
            return settings.total_time_ms / 60_000
        return None

    async def async_set_native_value(self, value: float) -> None:
        settings = self._settings()
        minutes = int(value) * 60_000
        if isinstance(settings, types.BusyTimerSimpleSettings):
            await self._write(total_ms=minutes)
        else:
            await self._write(work_ms=minutes)


class RestNumber(_CardNumber):
    """
    How long the break between work phases lasts.
    """

    _attr_native_min_value = timer.MINIMUM_PHASE_MS // 60_000
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, slot, "rest")

    @property
    def available(self) -> bool:
        return super().available and isinstance(
            self._settings(), types.BusySnapshotIntervalSettings
        )

    @property
    def native_value(self) -> float | None:
        settings = self._settings()
        if isinstance(settings, types.BusySnapshotIntervalSettings):
            return settings.interval_rest_ms / 60_000
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self._write(rest_ms=int(value) * 60_000)


class CyclesNumber(_CardNumber):
    """
    How many work phases the session runs before it is over.
    """

    _attr_native_min_value = 1
    _attr_native_max_value = 12
    _attr_native_step = 1

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, slot, "cycles")

    @property
    def available(self) -> bool:
        return super().available and isinstance(
            self._settings(), types.BusySnapshotIntervalSettings
        )

    @property
    def native_value(self) -> float | None:
        settings = self._settings()
        if isinstance(settings, types.BusySnapshotIntervalSettings):
            return settings.interval_work_cycles_count
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self._write(cycles=int(value))
