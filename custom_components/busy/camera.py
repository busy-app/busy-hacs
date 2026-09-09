"""The bar's front display, mirrored into Home Assistant."""

from __future__ import annotations

from busylib.exceptions import BusyBarError

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The panel is 72x16, which every viewer draws either as a postage stamp or
# smoothed into mush. Enlarging it here, by whole pixels, is what makes it
# legible in a picture card without the frontend inventing pixels: 720x160
# is big enough for a full-width card and still keeps the pixel grid visible.
_SCALE = 10

# How often the frontend refetches while a live view is open. The coordinator
# announces frames at most once a second, so asking for more would return the
# same picture again.
_FRAME_INTERVAL = 1.0


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

    async_add_entities([BusyBarScreen(coordinator, name)])


class BusyBarScreen(BusyBarEntity, Camera):
    """
    What the front panel is showing.

    A camera rather than an image entity, for two reasons: Home Assistant
    draws image entities as a round thumbnail, which crops a 72x16 panel
    into nothing, and a camera also gives a live view in the more-info
    dialog instead of one still per state change.

    The frames arrive on the state stream the coordinator is already
    following, so this costs no extra requests - the bar sends them whether
    or not anyone is looking. Decoding, enlarging and PNG encoding all come
    from busylib, which knows the panel's geometry and wire format.
    """

    _attr_frame_interval = _FRAME_INTERVAL

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        BusyBarEntity.__init__(self, coordinator, name, "screen")
        Camera.__init__(self)
        # Set after Camera.__init__, which assigns the JPEG default.
        self.content_type = "image/png"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Frames come on their own throttled signal rather than the
        # coordinator's, which would otherwise refresh every entity ten
        # times a second.
        self.async_on_remove(self.coordinator.add_frame_listener(self._frame_arrived))

    @callback
    def _frame_arrived(self) -> None:
        """
        Note that the picture changed, so the frontend refetches it.
        """
        self.async_write_ha_state()

    def _screen(self):
        """
        The latest front-panel frame, if one has arrived.
        """
        data = self.coordinator.data
        return None if data is None else data.snapshot.screen_front

    @property
    def available(self) -> bool:
        return super().available and self._screen() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # width and height are the frontend's request for a thumbnail size;
        # they are ignored, because the picture is already tiny and the
        # frontend scales what it gets. Handing back fewer pixels than the
        # panel has would only lose some.
        frame = self._screen()
        return None if frame is None else frame.scale(_SCALE).to_png()
