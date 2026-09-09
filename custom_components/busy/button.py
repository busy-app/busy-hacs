"""The bar's own buttons, pressable from Home Assistant."""

from __future__ import annotations

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The three buttons on the bar. Pressing one here is indistinguishable from
# pressing it on the device: the firmware puts the same event on its state
# stream either way, confirmed against hardware.
_BUTTONS = (
    ("ok", types.InputKey.OK),
    ("back", types.InputKey.BACK),
    ("start", types.InputKey.START),
)


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

    async_add_entities(
        [
            *(
                BusyBarButton(coordinator, name, key, input_key)
                for key, input_key in _BUTTONS
            ),
            NextPhaseButton(coordinator, name),
            StopTimerButton(coordinator, name),
        ]
    )


class BusyBarButton(BusyBarEntity, ButtonEntity):
    """
    One of the bar's buttons.

    Useful for the same reasons the physical button is: dismissing what is
    on screen, or starting whatever the current profile starts, from an
    automation rather than by reaching for the bar.
    """

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        name: str,
        key: str,
        input_key: types.InputKey,
    ) -> None:
        super().__init__(coordinator, name, key)
        self._input_key = input_key

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.input(self._input_key)
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="input_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class _TimerButton(BusyBarEntity, ButtonEntity):
    """
    Base for the buttons that change the session.

    Both are one-way and take no options, which is what makes them buttons
    rather than actions - the actions with fields are still there for an
    automation that needs them.
    """

    async def _change(self, work) -> None:
        try:
            await work(self.coordinator.client)
        except timer.TimerNotRunningError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_not_running",
                translation_placeholders={"error": str(err)},
            ) from err
        except BusyBarError as err:
            raise HomeAssistantError(
                translation_domain="busy",
                translation_key="timer_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class NextPhaseButton(_TimerButton):
    """
    Move an interval session on to its next phase.

    The obvious use is cutting a break short, or starting one early.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "next_phase")

    async def async_press(self) -> None:
        await self._change(timer.next_phase)


class StopTimerButton(_TimerButton):
    """
    End the session.

    Not the selector's off position, which is the bar's do-not-disturb:
    this puts the session back to not started.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "stop_timer")

    async def async_press(self) -> None:
        await self._change(timer.stop)
