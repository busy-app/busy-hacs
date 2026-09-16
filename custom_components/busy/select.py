"""Settings of the bar that are a choice from a list."""

from __future__ import annotations

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer

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
        # The bar's own list, so it stays whatever the firmware ships.
        themes = await timer.themes(coordinator.client)
    except BusyBarError as err:
        raise PlatformNotReady(
            f"BUSY Bar {coordinator.device_id} is unreachable"
        ) from err

    async_add_entities(
        [
            ThemeSelect(coordinator, name, "busy", themes),
            ThemeSelect(coordinator, name, "custom", themes),
            *(TimerKindSelect(coordinator, name, slot) for slot in ("busy", "custom")),
        ]
    )


class ThemeSelect(BusyBarEntity, SelectEntity):
    """
    The theme one of the bar's cards starts with.

    A card's theme, not the running session's: this is the lasting choice,
    and it does not change what is on screen right now. To change a
    session already running, use the `set_theme` action - the bar treats
    that as temporary and returns to the card's theme when it ends.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        name: str,
        slot: types.BusyProfileSlot,
        themes: list[str],
    ) -> None:
        super().__init__(coordinator, name, f"theme_{slot}")
        self._slot: types.BusyProfileSlot = slot
        self._attr_options = themes

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        card = data.cards.get(self._slot)
        if card is None:
            return None
        theme = card.busy_bar_settings.theme
        # A theme set on the bar after this list was read - by its owner,
        # or by an upload - would otherwise be a state Home Assistant
        # refuses to display.
        if theme and theme not in (self._attr_options or []):
            self._attr_options = sorted({*(self._attr_options or []), theme})
        return theme

    async def async_select_option(self, option: str) -> None:
        try:
            await timer.set_card_theme(
                self.coordinator.client,
                self._slot,
                option,
                # Offered from this list, so it needs no second opinion.
                known=self._attr_options,
            )
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class TimerKindSelect(BusyBarEntity, SelectEntity):
    """
    What kind of timer this mode runs.

    Changing it is what makes the mode's other settings apply: a mode
    running endlessly has no phases and no cycles, so its work, rest and
    cycles sit unavailable until it becomes a pomodoro. Changing the kind
    replaces the mode's timer - there is nothing to carry from a timer
    that had no lengths - so a mode coming back to pomodoro starts from
    sensible defaults rather than from what it had long ago.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["off", "simple", "pomodoro"]

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, slot: types.BusyProfileSlot
    ) -> None:
        super().__init__(coordinator, name, f"{slot}_timer_kind")
        self._slot: types.BusyProfileSlot = slot

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        card = data.cards.get(self._slot)
        return None if card is None else timer.kind_of(card.timer_settings)

    async def async_select_option(self, option: str) -> None:
        try:
            await timer.configure(self.coordinator.client, self._slot, kind=option)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="setting_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
