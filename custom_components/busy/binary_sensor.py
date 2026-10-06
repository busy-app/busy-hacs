"""Binary sensors for the BUSY Bar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from busylib import types
from busylib.features import timer_state
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]


@dataclass(frozen=True, kw_only=True)
class BusyBinarySensorDescription(BinarySensorEntityDescription):
    is_on: Callable[[BusyBarCoordinator], bool | None]
    attributes: Callable[[BusyBarCoordinator], dict[str, Any] | None] | None = None


def _running(coordinator: BusyBarCoordinator) -> bool | None:
    running = coordinator.data.snapshot.timer
    return None if running is None else timer_state(running).is_running


def _charging(coordinator: BusyBarCoordinator) -> bool | None:
    power = coordinator.data.snapshot.power
    if power is None or power.state is None:
        return None
    return power.state == types.PowerState.CHARGING


def _update_window(coordinator: BusyBarCoordinator) -> dict[str, Any] | None:
    # The window the bar may update in - overnight by default.
    settings = coordinator.data.autoupdate
    if settings is None:
        return None
    return {
        "window_start": settings.interval_start,
        "window_end": settings.interval_end,
    }


BINARY_SENSORS: tuple[BusyBinarySensorDescription, ...] = (
    BusyBinarySensorDescription(
        # Whether a session is under way, paused included. For automations
        # that react to "a session started" whatever phase it began in, so
        # hidden: the two session switches already show it.
        key="session_running",
        entity_registry_visible_default=False,
        is_on=_running,
    ),
    BusyBinarySensorDescription(
        # A reading rather than a switch: turning it off from here would be
        # a decision made where the bar's owner is not looking.
        key="automatic_updates",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on=lambda c: s.is_enabled if (s := c.data.autoupdate) else None,
        attributes=_update_window,
    ),
    BusyBinarySensorDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on=_charging,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(BusyBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class BusyBinarySensor(BusyBarEntity, BinarySensorEntity):
    entity_description: BusyBinarySensorDescription

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        description: BusyBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes = self.entity_description.attributes
        return None if attributes is None else attributes(self.coordinator)
