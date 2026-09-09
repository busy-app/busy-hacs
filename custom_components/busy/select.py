"""Settings of the bar that are a choice from a list."""

from __future__ import annotations

from busylib.exceptions import BusyBarError

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
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
        # The list of timezones the firmware knows is fixed for a given
        # build, so it is read once here rather than polled.
        timezones = [zone.name for zone in (await coordinator.client.time_timezone_list()).list]
    except BusyBarError as err:
        raise PlatformNotReady(
            f"BUSY Bar {coordinator.device_id} is unreachable"
        ) from err

    async_add_entities(
        [
            TimezoneSelect(coordinator, name, sorted(timezones)),
        ]
    )


class TimezoneSelect(BusyBarEntity, SelectEntity):
    """
    Which timezone the bar shows its clock in.

    The bar keeps its own timezone rather than following Home Assistant's,
    and its clock is on screen all day, so a wrong one is visible and worth
    being able to fix from here.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, timezones: list[str]
    ) -> None:
        super().__init__(coordinator, name, "timezone")
        self._attr_options = timezones

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        return None if data is None else data.timezone

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.time_timezone(option)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
