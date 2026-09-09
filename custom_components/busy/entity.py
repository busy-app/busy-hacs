"""Shared base for BUSY Bar entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BusyBarCoordinator

# Entities are driven by the coordinator's shared stream and poll, not their
# own async_update, so there is no per-entity request pressure to limit.
PARALLEL_UPDATES = 0

_FALLBACK_MODEL = "BUSY Bar"


def _device_info(coordinator: BusyBarCoordinator, name: str) -> DeviceInfo:
    """
    Describe the bar for the device registry.

    Filled from what the bar reports rather than hardcoded, so the device
    page carries its serial, firmware and a link to its own web UI instead
    of repeating the integration's name back at the reader.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=name,
        manufacturer="BUSY",
        model=_FALLBACK_MODEL,
        configuration_url=coordinator.client.base_url,
    )

    data = coordinator.data
    status = data.snapshot.status if data is not None else None
    if status is None:
        return info

    device = status.device
    if device is not None:
        if device.serial_number:
            info["serial_number"] = device.serial_number
        # otp_model is the hardware revision ("BB.1"), which the device
        # page has its own row for. Putting it in `model` replaced the
        # product name with a code nobody recognises. It is absent on bars
        # whose OTP is not programmed - development units.
        if device.otp_model:
            info["hw_version"] = device.otp_model
        # No `connections`. They exist so two integrations can recognise
        # the same device, which nothing needs here - the identifier above
        # is this bar's identity - and the device page rendered them as
        # bare MAC addresses with no interface label and a link to
        # somewhere unexplained. The bar has three MACs (Wi-Fi, USB,
        # Bluetooth); labelled, they are in the diagnostics download.

    firmware = status.firmware
    if firmware is not None and firmware.version:
        # The branch matters on a bar running unreleased firmware, and it is
        # the first thing to ask about when something behaves oddly.
        suffix = f" ({firmware.branch})" if firmware.branch else ""
        info["sw_version"] = f"{firmware.version}{suffix}"

    return info


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """
    One entity of one bar, named after it rather than repeating its name.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, name: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = _device_info(coordinator, name)
