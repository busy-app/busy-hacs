"""Shared base for BUSY Bar entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BusyBarCoordinator, BusyBarData
from .errors import reporting

# Entities are driven by the coordinator's shared stream and poll, not their
# own async_update, so there is no per-entity request pressure to limit.
PARALLEL_UPDATES = 0

_FALLBACK_NAME = "BUSY Bar"


def device_info(coordinator: BusyBarCoordinator) -> DeviceInfo:
    """
    Describe the bar for the device registry, from what the bar reports.

    The device page carries its serial, firmware and a link to its own web
    UI instead of repeating the integration's name back at the reader. No
    `connections`: the identifier is the bar's identity, and the three MACs
    (Wi-Fi, USB, Bluetooth) are in the diagnostics download, labelled.
    """
    snapshot = coordinator.data.snapshot
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=snapshot.name or _FALLBACK_NAME,
        manufacturer="BUSY",
        model=_FALLBACK_NAME,
        configuration_url=coordinator.client.base_url,
    )
    status = snapshot.status
    if status is None:
        return info

    device = status.device
    if device is not None:
        if device.serial_number:
            info["serial_number"] = device.serial_number
        # otp_model is the hardware revision ("BB.1"), which the device page
        # has its own row for; in `model` it replaced the product name with
        # a code nobody recognises. Absent on bars with no OTP programmed.
        if device.otp_model:
            info["hw_version"] = device.otp_model

    firmware = status.firmware
    if firmware is not None and firmware.version:
        # The branch is the first thing to ask about on unreleased firmware.
        suffix = f" ({firmware.branch})" if firmware.branch else ""
        info["sw_version"] = f"{firmware.version}{suffix}"
    return info


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """
    One entity of one bar, named after it rather than repeating its name.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = device_info(coordinator)

    @property
    def data(self) -> BusyBarData:
        """
        What the coordinator last read. Entities exist only after its first
        refresh, and a failed poll keeps the previous data.
        """
        return self.coordinator.data

    async def _write(self, work, failed: str = "setting_failed") -> None:
        """
        Await a change to the bar, report a refusal, and re-read what the
        stream does not push.
        """
        with reporting(failed):
            await work
        await self.coordinator.async_request_refresh()
