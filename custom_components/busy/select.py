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

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    try:
        name = (await coordinator.client.name()).name
        # The bar's own list, so it stays whatever the firmware ships.
        themes = await timer.themes(coordinator.client)
    except BusyBarError as err:
        raise PlatformNotReady(
            f"BUSY Bar {coordinator.device_id} is unreachable"
        ) from err

    async_add_entities(
        [
            *(
                QuickThemeSelect(coordinator, name, kind, themes)
                for kind in ("infinite", "simple", "interval")
            ),
            SwitchPositionSelect(coordinator, name),
        ]
    )


class QuickThemeSelect(BusyBarEntity, RestoreEntity, SelectEntity):
    """
    What a quick session of one kind looks like on the bar.

    A theme per kind, because that is the difference a person wants to
    see across the room: a countdown for a meeting and an endless do-not-
    disturb should not look the same.

    Kept in Home Assistant, like the lengths beside it, and sent with the
    session. The bar's own two cards each keep their own theme, set on the
    bar or in the BUSY app, and nothing here touches them.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        name: str,
        kind: timer.TimerKind,
        themes: list[str],
    ) -> None:
        super().__init__(coordinator, name, f"quick_theme_{kind}")
        self._kind: timer.TimerKind = kind
        # The firmware's built-in has no asset directory of its own, so it
        # appears in the bar's list only while one of the cards is set to
        # it - and it is what a quick session falls back to. Offering it
        # always keeps the fallback from being a state this cannot show.
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
        if restored is not None and restored.state in (self._attr_options or []):
            self.coordinator.quick.themes[self._kind] = restored.state


# The switch's five positions, in the order they sit on the bar, with the
# key that moves it there. "Switch" is the firmware's own word: the state
# stream calls the event a SwitchEvent and its values SwitchPosition.
_POSITIONS: dict[str, types.InputKey] = {
    "busy": types.InputKey.BUSY,
    "custom": types.InputKey.CUSTOM,
    "off": types.InputKey.OFF,
    "apps": types.InputKey.APPS,
    "settings": types.InputKey.SETTINGS,
}


class SwitchPositionSelect(BusyBarEntity, RestoreEntity, SelectEntity):
    """
    Where the bar's switch is, and where to move it.

    A button per position was here before, which could move the switch
    but could never say where it was - so an automation could not ask,
    and a dashboard could not show it. One entity does both, and reads
    in an automation as the thing it is: a switch with five positions.

    The bar reports the position only when it moves; nothing answers the
    question directly. So the last position seen is remembered across
    restarts, and a bar that has never reported one reads as unknown
    rather than guessing. Moving the switch from here goes through the
    same firmware path as a hand on the device, which then reports the
    move back - the state follows the bar, not this entity's wishes.
    """

    _attr_options = list(_POSITIONS)

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "switch_position")

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        return None if data is None else data.selector

    async def async_select_option(self, option: str) -> None:
        # No optimistic write: the bar answers the press with a move on
        # the state stream, and that is what the state follows.
        await self.coordinator.client.input(_POSITIONS[option])

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = self.coordinator.data
        restored = await self.async_get_last_state()
        if (
            data is not None
            and data.selector is None
            and restored is not None
            and restored.state in _POSITIONS
        ):
            self.coordinator.data = replace(data, selector=restored.state)
