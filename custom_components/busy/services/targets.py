"""Which bars an action was pointed at."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)

from ..const import DOMAIN
from ..coordinator import BusyBarCoordinator


def bars_targeted(call: ServiceCall) -> list[BusyBarCoordinator]:
    """
    Every bar the call points at, however it was pointed at.

    A target can name devices, areas, labels, floors or entities, and Home
    Assistant expands all of that - but answers in entities, so anything
    named by area or label arrives as an entity and is traced back to its
    device. Targets reach things that are not bars (a room holds lamps
    too), so a device that is not ours is passed over rather than refused.
    """
    hass = call.hass
    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    entities = er.async_get(hass)
    device_ids = set(selected.referenced_devices)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entry = entities.async_get(entity_id)
        if entry is not None and entry.device_id:
            device_ids.add(entry.device_id)

    devices = dr.async_get(hass)
    bars: list[BusyBarCoordinator] = []
    for device_id in sorted(device_ids):
        device = devices.async_get(device_id)
        entry = next(
            (
                entry
                for entry_id in (device.config_entries if device else ())
                if (entry := hass.config_entries.async_get_entry(entry_id))
                and entry.domain == DOMAIN
            ),
            None,
        )
        if entry is None:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="device_not_loaded"
            )
        bars.append(entry.runtime_data)
    if not bars:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_device"
        )
    return bars


def title(coordinator: BusyBarCoordinator) -> str:
    """
    What to call a bar in an error. A target can reach several, and what one
    refuses another may not, so an error must say which answered.
    """
    return coordinator.config_entry.title
