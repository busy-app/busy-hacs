"""Adjustable settings of the bar: how bright, how loud."""

from __future__ import annotations

from busylib.exceptions import BusyBarError

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
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
