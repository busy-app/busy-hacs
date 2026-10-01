"""Settings of the bar that are a choice from a list."""

from __future__ import annotations

from dataclasses import replace

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity
from .errors import reporting

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The switch's five positions, in the order they sit on the bar, with the
# key that moves it there. "Switch" is the firmware's own word.
_POSITIONS: dict[str, types.InputKey] = {
    "busy": types.InputKey.BUSY,
    "custom": types.InputKey.CUSTOM,
    "off": types.InputKey.OFF,
    "apps": types.InputKey.APPS,
    "settings": types.InputKey.SETTINGS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    # The bar's own list, so it stays whatever the firmware ships.
    try:
        themes = await timer.themes(coordinator.client)
    except BusyBarError as err:
        raise PlatformNotReady(f"{coordinator.name} is unreachable") from err
    async_add_entities(
        [
            *(
                QuickThemeSelect(coordinator, kind, themes)
                for kind in ("infinite", "simple", "interval")
            ),
            SwitchPositionSelect(coordinator),
        ]
    )


class QuickThemeSelect(BusyBarEntity, RestoreEntity, SelectEntity):
    """
    What a quick session of one kind looks like on the bar - a countdown for
    a meeting and an endless do-not-disturb should not look the same.

    Kept in Home Assistant, like the lengths beside it, and sent with the
    session; the bar's own two cards keep their own themes.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        kind: timer.TimerKind,
        themes: list[str],
    ) -> None:
        super().__init__(coordinator, f"quick_theme_{kind}")
        self._kind = kind
        # The firmware's built-in theme has no asset directory, so the bar
        # lists it only while a card is set to it - and it is what a quick
        # session falls back to. Always offering it keeps the fallback from
        # being a state this cannot show.
        self._attr_options = sorted({*themes, timer.DEFAULT_THEME})

    @property
    def current_option(self) -> str | None:
        return self.coordinator.quick.themes.get(self._kind)

    async def async_select_option(self, option: str) -> None:
        self.coordinator.quick.themes[self._kind] = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_state()
        if restored is not None and restored.state in self.options:
            self.coordinator.quick.themes[self._kind] = restored.state


class SwitchPositionSelect(BusyBarEntity, RestoreEntity, SelectEntity):
    """
    Where the bar's switch is, and where to move it.

    The bar reports the position only when it moves, so the last one seen
    is remembered across restarts and a bar that never reported one reads
    as unknown rather than guessed. Moving it from here goes through the
    same firmware path as a hand on the device, which reports the move back:
    the state follows the bar, not this entity's wishes.
    """

    _attr_options = list(_POSITIONS)

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "switch_position")

    @property
    def current_option(self) -> str | None:
        return self.data.selector

    async def async_select_option(self, option: str) -> None:
        # No optimistic write: the state follows the move on the stream.
        with reporting("input_failed"):
            await self.coordinator.client.input(_POSITIONS[option])

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = await self.async_get_last_state()
        if self.data.selector is None and restored and restored.state in _POSITIONS:
            self.coordinator.data = replace(self.data, selector=restored.state)
