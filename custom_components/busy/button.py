"""The bar's own buttons, pressable from Home Assistant."""

from __future__ import annotations

from busylib import types
from busylib.features import timer
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity
from .errors import reporting

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The three buttons on the bar - pressing one here is indistinguishable from
# pressing it on the device, the firmware puts the same event on its stream -
# and the scrolling that navigates it. The HTTP API calls the keys up and
# down, but the menus map them to the selection moving sideways, so they are
# named for what a person sees.
_KEYS = {
    "ok": types.InputKey.OK,
    "back": types.InputKey.BACK,
    "start": types.InputKey.START,
    "scroll_right": types.InputKey.UP,
    "scroll_left": types.InputKey.DOWN,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(
        [
            *(
                BusyBarButton(coordinator, key, input_key)
                for key, input_key in _KEYS.items()
            ),
            NextPhaseButton(coordinator),
        ]
    )


class BusyBarButton(BusyBarEntity, ButtonEntity):
    """
    One of the bar's buttons, or a way to move its selection.

    Hidden from dashboards by default: a remote control is useful in an
    automation and when someone cannot reach the bar, and noise in the card
    for a room. One click from being shown.
    """

    _attr_entity_registry_visible_default = False

    def __init__(
        self, coordinator: BusyBarCoordinator, key: str, input_key: types.InputKey
    ) -> None:
        super().__init__(coordinator, key)
        self._input_key = input_key

    async def async_press(self) -> None:
        with reporting("input_failed"):
            await self.coordinator.client.input(self._input_key)


class NextPhaseButton(BusyBarEntity, ButtonEntity):
    """
    Move an interval session on to its next phase - cutting a break short,
    or starting one early. One-way and optionless, which is what makes it a
    button; the action with fields is still there for automations.
    """

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "session_next_phase")

    async def async_press(self) -> None:
        await self._write(timer.next_phase(self.coordinator.client), "timer_failed")
