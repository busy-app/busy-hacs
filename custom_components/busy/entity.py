"""Shared base for BUSY Bar entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BusyBarCoordinator

# Entities are driven by the coordinator's shared stream and poll, not their
# own async_update, so there is no per-entity request pressure to limit.
PARALLEL_UPDATES = 0


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """
    One entity of one bar, named after it rather than repeating its name.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, name: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=name,
            manufacturer="BUSY",
            model="BUSY Bar",
        )
