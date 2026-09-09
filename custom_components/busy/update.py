"""The bar's firmware, as something Home Assistant can offer to install."""

from __future__ import annotations

from typing import Any

from busylib.exceptions import BusyBarError

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# What the bar's check reports when there is something newer to install.
_AVAILABLE = "available"

# What its installer reports while it is working.
_BUSY_ACTIONS = frozenset({"download", "install", "verify"})


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

    async_add_entities([BusyBarFirmware(coordinator, name)])


class BusyBarFirmware(BusyBarEntity, UpdateEntity):
    """
    Whether the bar has newer firmware, and a way to install it.

    The bar checks for itself on a schedule it keeps, so this reports what
    that check found rather than asking again. Installing is the same call
    the bar's own web interface makes, and the bar decides whether it is
    allowed: a session running or a low battery makes it refuse, and that
    refusal is what surfaces here.
    """

    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "firmware")

    def _install(self):
        data = self.coordinator.data
        if data is None or data.update_status is None:
            return None
        return data.update_status.install

    def _check(self):
        data = self.coordinator.data
        if data is None or data.update_status is None:
            return None
        return data.update_status.check

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.status is None:
            return None
        firmware = data.snapshot.status.firmware
        return None if firmware is None else firmware.version

    @property
    def latest_version(self) -> str | None:
        check = self._check()
        if check is None:
            return None
        if check.status != _AVAILABLE or not check.available_version:
            # Nothing newer: Home Assistant reads "up to date" from the two
            # versions matching, so it has to be told the installed one.
            return self.installed_version
        return check.available_version

    @property
    def in_progress(self) -> bool:
        install = self._install()
        return install is not None and install.action in _BUSY_ACTIONS

    @property
    def update_percentage(self) -> int | None:
        install = self._install()
        if install is None or install.download is None or not self.in_progress:
            return None
        total = install.download.total_bytes
        received = install.download.received_bytes
        if not total or received is None:
            return None
        return round(received / total * 100)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        target = version or self.latest_version
        if not target:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="no_firmware_to_install",
            )
        try:
            await self.coordinator.client.update_install(target)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="firmware_install_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
