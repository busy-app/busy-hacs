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

# What the brightness setting reads back as when the bar is following its
# light sensor instead of a chosen level.
_AUTO = "auto"

# The level to apply when automatic brightness is switched off and the bar
# has no chosen level to return to.
_DEFAULT_BRIGHTNESS = 100


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
            BrightnessModeSelect(coordinator, name),
            TimezoneSelect(coordinator, name, sorted(timezones)),
        ]
    )


class BrightnessModeSelect(BusyBarEntity, SelectEntity):
    """
    Whether the bar picks its own brightness.

    The firmware keeps one setting that is either a number or "auto", so a
    brightness slider alone cannot express it: a bar on automatic has no
    chosen level to show. This says which of the two the bar is doing, and
    the brightness number carries the level for when it is not automatic.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["auto", "manual"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "brightness_mode")

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.brightness is None:
            return None
        return _AUTO if data.brightness == _AUTO else "manual"

    async def async_select_option(self, option: str) -> None:
        # Leaving automatic needs a level to leave it at, and the bar has
        # not kept the one it had before. The brightest is the safe choice:
        # a panel that goes dark on a settings change looks broken.
        value = _AUTO if option == _AUTO else _DEFAULT_BRIGHTNESS
        try:
            await self.coordinator.client.display_brightness_set(value)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


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
