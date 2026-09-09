"""Sensors for the BUSY Bar timer and power state."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from busylib.exceptions import BusyBarError
from busylib.features import timer_state

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

_LOGGER = logging.getLogger(__name__)

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
            TimerModeSensor(coordinator, name),
            TimerPhaseSensor(coordinator, name),
            TimerEndsAtSensor(coordinator, name),
            TimerIntervalSensor(coordinator, name),
            ThemeSensor(coordinator, name),
            BatterySensor(coordinator, name),
        ]
    )


class _TimerSensor(BusyBarEntity, SensorEntity):
    """
    Base for sensors that read the timer.
    """

    def _state(self):
        """
        The timer's state now, or None while the timer is unknown.
        """
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return timer_state(data.snapshot.timer)


class TimerModeSensor(_TimerSensor):
    """Which kind of session is running."""

    _attr_name = "Timer mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["not_started", "infinite", "simple", "interval"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_mode")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        return None if state is None else state.mode


class TimerPhaseSensor(_TimerSensor):
    """
    Work or rest — the thing automations branch on.

    `none` covers every case where no phase applies: no session, or one that
    has finished.
    """

    _attr_name = "Timer phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["work", "rest", "none"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_phase")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        if state is None:
            return None
        return state.phase or "none"


class TimerEndsAtSensor(_TimerSensor):
    """
    When the current phase runs out.

    A timestamp rather than a count of seconds: entities here are updated
    when the bar pushes a change, so a seconds value would sit still between
    pushes, while a timestamp lets the frontend and templates count down
    themselves.
    """

    _attr_name = "Timer phase ends"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_ends_at")

    @property
    def native_value(self) -> datetime | None:
        state = self._state()
        if state is None or state.time_left_ms is None or not state.is_running:
            return None
        if state.is_paused:
            # A paused phase has no end until it is resumed.
            return None
        return dt_util.utcnow() + timedelta(milliseconds=state.time_left_ms)


class TimerIntervalSensor(_TimerSensor):
    """Which interval of the session is running."""

    _attr_name = "Timer interval"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_interval")

    @property
    def native_value(self) -> int | None:
        state = self._state()
        return None if state is None else state.interval


class ThemeSensor(BusyBarEntity, SensorEntity):
    """The theme the running profile is showing."""

    _attr_name = "Theme"

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "theme")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return data.snapshot.timer.snapshot.busy_bar_settings.theme


class BatterySensor(BusyBarEntity, SensorEntity):
    """Charge level."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "battery")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if data is None or data.snapshot.power is None:
            return None
        return data.snapshot.power.battery_charge
