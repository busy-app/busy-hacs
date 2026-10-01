"""The bar's firmware, as something Home Assistant can offer to install."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
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
    async_add_entities([BusyBarFirmware(config_entry.runtime_data)])


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

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "firmware")

    def _install(self):
        status = self.data.update_status
        return None if status is None else status.install

    def _check(self):
        status = self.data.update_status
        return None if status is None else status.check

    @property
    def installed_version(self) -> str | None:
        status = self.data.snapshot.status
        if status is None or status.firmware is None:
            return None
        return status.firmware.version

    @property
    def latest_version(self) -> str | None:
        installing = self.coordinator.installing
        if installing is not None:
            # What the check found is stale for as long as an install
            # runs: starting one does not touch it, so it goes on naming
            # the very version being installed. The install is the newer
            # fact, and naming its target is what makes Home Assistant
            # show the install rather than an offer to start another.
            return installing if installing != "?" else self.installed_version
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
        Whether an install is under way, for as long as it actually is.

        An install is a session of several phases - download, checksum,
        unpack, prepare, apply, reboot - and the bar reports nothing
        between some of them and nothing at all during the last. Asking
        "is a phase happening this second" therefore answered no several
        times per install, and the entity went back to offering the
        update it was in the middle of installing. The coordinator
        follows the session instead, which is the question being asked.
        """
        return self.coordinator.installing is not None

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
        await self._write(
            self.coordinator.client.update_install(target), "firmware_install_failed"
        )
