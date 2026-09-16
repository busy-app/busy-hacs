"""Adjustable settings of the bar: how bright, how loud."""

from __future__ import annotations

from busylib.exceptions import BusyBarError
from busylib.features import timer

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
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
            SimpleLengthNumber(coordinator, name),
            WorkNumber(coordinator, name),
            RestNumber(coordinator, name),
            CyclesNumber(coordinator, name),
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




class _QuickNumber(BusyBarEntity, RestoreNumber):
    """
    One length a quick-start button will use.

    Held in Home Assistant rather than on the bar, because writing it to
    the bar means writing one of the two cards - and leaving those alone
    is the whole point of the quick-start buttons. So this never talks to
    the device: it remembers a number, restores it across a restart, and
    the button reads it when pressed.

    Which also makes the pair automatable: set the length, press the
    button, and the bar runs exactly that without either card changing.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, key: str, field: str
    ) -> None:
        super().__init__(coordinator, name, key)
        self._field = field

    @property
    def native_value(self) -> float | None:
        return getattr(self.coordinator.quick, self._field)

    async def async_set_native_value(self, value: float) -> None:
        setattr(self.coordinator.quick, self._field, int(value))
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            setattr(self.coordinator.quick, self._field, int(restored.native_value))


class SimpleLengthNumber(_QuickNumber):
    """
    How long a quick countdown runs.

    No floor: the firmware checks a countdown at the top only, so two
    minutes is as valid as two hours.
    """

    _attr_native_min_value = 1
    _attr_native_max_value = timer.MAXIMUM_TOTAL_MS // 60_000
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "quick_timer_simple", "simple_minutes")


class WorkNumber(_QuickNumber):
    """
    How long each work phase of a quick interval session runs.

    Five minutes is the floor because the bar refuses anything shorter -
    as a parse error about the whole snapshot, which explains nothing, so
    the range is stated here instead.
    """

    _attr_native_min_value = timer.MINIMUM_PHASE_MS // 60_000
    _attr_native_max_value = timer.MAXIMUM_PHASE_MS // 60_000
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "quick_timer_interval_work", "work_minutes")


class RestNumber(_QuickNumber):
    """
    How long the break between work phases lasts.

    Five minutes at the least here too: the bar applies the same floor to
    a break as to work, which rules out the short breaks a session of
    five and one would want.
    """

    _attr_native_min_value = timer.MINIMUM_PHASE_MS // 60_000
    _attr_native_max_value = timer.MAXIMUM_PHASE_MS // 60_000
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "quick_timer_interval_rest", "rest_minutes")


class CyclesNumber(_QuickNumber):
    """
    How many work phases a quick interval session runs before it is over.
    """

    _attr_native_min_value = timer.MINIMUM_CYCLES
    _attr_native_max_value = timer.MAXIMUM_CYCLES

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "quick_timer_interval_cycles", "cycles")
