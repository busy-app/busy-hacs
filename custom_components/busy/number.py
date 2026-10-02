"""Adjustable settings of the bar: how bright, how loud, how long."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from busylib import AsyncBusyBar
from busylib.features import timer
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

_PERCENT = {
    "native_min_value": 0,
    "native_max_value": 100,
    "native_step": 1,
    "native_unit_of_measurement": PERCENTAGE,
    "mode": NumberMode.SLIDER,
    "entity_category": EntityCategory.CONFIG,
}


def _brightness(coordinator: BusyBarCoordinator) -> float | None:
    # Nothing while the bar is on automatic: there is no chosen level then,
    # only what the light sensor asks for.
    try:
        return float(coordinator.data.brightness)
    except TypeError, ValueError:
        return None


def _volume(coordinator: BusyBarCoordinator) -> float | None:
    volume = coordinator.data.snapshot.volume
    return None if volume is None else volume.volume


@dataclass(frozen=True, kw_only=True)
class SettingDescription(NumberEntityDescription):
    """A number the bar keeps: how to read it, and how to write it."""

    value: Callable[[BusyBarCoordinator], float | None]
    write: Callable[[AsyncBusyBar, float], Any]


# Setting a brightness level here turns automatic off, which is what moving
# a brightness slider is understood to mean.
SETTINGS = (
    SettingDescription(
        key="brightness",
        value=_brightness,
        write=lambda client, value: client.display_brightness_set(int(value)),
        **_PERCENT,
    ),
    SettingDescription(
        # Read from the stream: the bar pushes a volume change at once,
        # including one made on the device itself.
        key="volume",
        value=_volume,
        write=lambda client, value: client.audio_volume_set(value),
        **_PERCENT,
    ),
)


@dataclass(frozen=True, kw_only=True)
class QuickDescription(NumberEntityDescription):
    """A length a quick session will use, and the QuickSession field it is."""

    field: str


_MINUTES = {"native_unit_of_measurement": UnitOfTime.MINUTES}
_PHASE = {
    "native_min_value": timer.MINIMUM_PHASE_MS // 60_000,
    "native_max_value": timer.MAXIMUM_PHASE_MS // 60_000,
    **_MINUTES,
}

# Five minutes is the floor of a phase because the bar refuses anything
# shorter - as a parse error about the whole snapshot, which explains
# nothing, so the range is stated here. A countdown has no floor: the
# firmware checks it at the top only.
QUICK = (
    QuickDescription(
        key="quick_timer_simple",
        field="simple_minutes",
        native_min_value=1,
        native_max_value=timer.MAXIMUM_TOTAL_MS // 60_000,
        **_MINUTES,
    ),
    QuickDescription(key="quick_timer_interval_work", field="work_minutes", **_PHASE),
    QuickDescription(key="quick_timer_interval_rest", field="rest_minutes", **_PHASE),
    QuickDescription(
        key="quick_timer_interval_cycles",
        field="cycles",
        native_min_value=timer.MINIMUM_CYCLES,
        native_max_value=timer.MAXIMUM_CYCLES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(
        [
            *(SettingNumber(coordinator, d) for d in SETTINGS),
            *(QuickNumber(coordinator, d) for d in QUICK),
        ]
    )


class SettingNumber(BusyBarEntity, NumberEntity):
    entity_description: SettingDescription

    def __init__(
        self, coordinator: BusyBarCoordinator, description: SettingDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        await self._write(self.entity_description.write(self.coordinator.client, value))


class QuickNumber(BusyBarEntity, RestoreNumber):
    """
    One length a quick session will use.

    Held in Home Assistant, never sent to the bar: writing it there would
    write one of the two cards, and leaving those alone is the point of
    quick sessions. It is restored across a restart and read when a session
    starts - which also makes the pair automatable: set the length, start
    the session, and the bar runs exactly that.
    """

    entity_description: QuickDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self, coordinator: BusyBarCoordinator, description: QuickDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator.quick, self.entity_description.field)

    async def async_set_native_value(self, value: float) -> None:
        setattr(self.coordinator.quick, self.entity_description.field, int(value))
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            setattr(
                self.coordinator.quick,
                self.entity_description.field,
                int(restored.native_value),
            )
