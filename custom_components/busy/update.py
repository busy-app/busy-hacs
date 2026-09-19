"""The bar's firmware, as something Home Assistant can offer to install."""

from __future__ import annotations

from typing import Any

from busylib.exceptions import BusyBarError
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    BusyBarConfigEntry,
    BusyBarCoordinator,
    firmware_is_installing,
)
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# What the bar's check reports when there is something newer to install.
_AVAILABLE = "available"

# Only the download knows how far along it is; the phases after it are
# work with no number attached.
_DOWNLOAD = "download"


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
        """
        Whether the bar is installing, for as long as it actually is.

        An install is a session of several phases - download, checksum,
        unpack, prepare, apply - and only the first has a percentage. This
        used to report the download alone, so the moment that finished the
        entity went back to offering the update it was in the middle of
        installing, while the bar carried on.
        """
        data = self.coordinator.data
        return firmware_is_installing(None if data is None else data.update_status)

    @property
    def update_percentage(self) -> int | None:
        install = self._install()
        if install is None or install.action != _DOWNLOAD:
            # Unpacking and applying report no progress, and a bar stuck
            # at the download's last percentage would be a lie. Home
            # Assistant shows an indeterminate bar for None.
            return None
        download = install.download
        if (
            download is None
            or not download.total_bytes
            or download.received_bytes is None
        ):
            return None
        return round(download.received_bytes / download.total_bytes * 100)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """
        Which phase the install is in, since most of them have no number.
        """
        install = self._install()
        if install is None or not self.in_progress or not install.action:
            return None
        attributes = {"installation_phase": install.action}
        if install.detail:
            attributes["installation_detail"] = install.detail
        return attributes

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
