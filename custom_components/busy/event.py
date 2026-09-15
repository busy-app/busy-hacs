"""What someone did to the bar, as events Home Assistant can act on."""

from __future__ import annotations

from busylib.exceptions import BusyBarError
from busylib.features import ButtonEvent, EncoderEvent, InputEvent

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# One entity per physical button, which is how Home Assistant expects a
# remote to be described: an automation subscribes to the button it cares
# about rather than to everything and then filtering.
_BUTTONS = (("button_ok", "ok"), ("button_back", "back"), ("button_start", "start"))

# Both halves of a press are reported, because the gap between them is the
# only thing that distinguishes a long press from a short one.
_BUTTON_EVENTS = ["press", "release"]

# Which way the wheel went. The distance is an attribute, since an
# automation almost always wants the direction and rarely the amount.
_WHEEL_EVENTS = ["clockwise", "counterclockwise"]


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
                BusyBarButtonEvent(coordinator, name, key, button)
                for key, button in _BUTTONS
            ),
            BusyBarWheelEvent(coordinator, name),
        ]
    )


class _BusyBarInputEvent(BusyBarEntity, EventEntity):
    """
    Base for the entities driven by physical input.

    Events arrive on the state stream the coordinator already follows, so
    these cost nothing: the bar sends them whether or not Home Assistant
    is listening. They are announced unthrottled, unlike screen frames -
    a press someone just made is not something to drop.
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.add_input_listener(self._arrived))

    @callback
    def _arrived(self, event: InputEvent) -> None:
        raise NotImplementedError


class BusyBarButtonEvent(_BusyBarInputEvent):
    """
    One of the bar's buttons, as a person presses it.

    Note that a press sent by the `press` buttons of this integration
    arrives here too: the firmware makes no distinction between a button
    pressed by a finger and one pressed over HTTP, so an automation that
    presses OK will see OK pressed.
    """

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = _BUTTON_EVENTS

    def __init__(
        self, coordinator: BusyBarCoordinator, name: str, key: str, button: str
    ) -> None:
        super().__init__(coordinator, name, key)
        self._button = button

    @callback
    def _arrived(self, event: InputEvent) -> None:
        if isinstance(event, ButtonEvent) and event.button == self._button:
            self._trigger_event(event.action)
            self.async_write_ha_state()


class BusyBarWheelEvent(_BusyBarInputEvent):
    """
    The wheel on the side of the bar, as it is turned.

    The bar reports a signed number of steps; the direction is the event
    and the distance rides along as an attribute, because an automation
    usually wants "turned right" and only sometimes "by how much".
    """

    _attr_event_types = _WHEEL_EVENTS

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "wheel")

    @callback
    def _arrived(self, event: InputEvent) -> None:
        if not isinstance(event, EncoderEvent) or not event.delta:
            return
        direction = "clockwise" if event.delta > 0 else "counterclockwise"
        self._trigger_event(direction, {"steps": abs(event.delta)})
        self.async_write_ha_state()
