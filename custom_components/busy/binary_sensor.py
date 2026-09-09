"""Binary sensors for the BUSY Bar."""

from __future__ import annotations

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer_state

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
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
            TimerRunningSensor(coordinator, name),
            ChargingSensor(coordinator, name),
        ]
    )


class TimerRunningSensor(BusyBarEntity, BinarySensorEntity):
    """
    Whether a session is under way, paused included.

    Separate from the phase sensor so an automation can react to "a session
    started" without caring which phase it began in.
    """

    _attr_name = "Timer running"

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_running")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return timer_state(data.snapshot.timer).is_running


class ChargingSensor(BusyBarEntity, BinarySensorEntity):
    """Whether the bar is taking charge."""

    _attr_name = "Charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "charging")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.snapshot.power is None:
            return None
        state = data.snapshot.power.state
        return None if state is None else state == types.PowerState.CHARGING
