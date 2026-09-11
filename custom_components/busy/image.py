"""The bar's front display, mirrored into Home Assistant."""

from __future__ import annotations

from busylib.exceptions import BusyBarError

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The panel is 72x16, which every viewer draws either as a postage stamp or
# smoothed into mush. Enlarging by whole pixels keeps the grid visible, and
# eight times over is enough to stay sharp across a full-width card.
_SCALE = 8


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

    async_add_entities([BusyBarScreen(hass, coordinator, name)])


class BusyBarScreen(BusyBarEntity, ImageEntity):
    """
    What the front panel is showing.

    An image rather than a camera: there is no video here, and a camera
    entity would live among the house's cameras, turn up in the automatic
    Security dashboard and carry a recording state that means nothing for
    a 72x16 panel.

    The picture is square, which is the shape that survives. Home
    Assistant draws a picture in entity rows as a round thumbnail cropped
    to fill, so a wide strip came out as its leftmost fifth; centred in a
    square, the whole display is there - small, but all of it.

    The frames arrive on the state stream the coordinator is already
    following, so this costs no extra requests: the bar sends them whether
    or not anyone is looking. Decoding, enlarging, padding and PNG
    encoding all come from busylib, which knows the panel's geometry and
    wire format.
    """

    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: BusyBarCoordinator, name: str
    ) -> None:
        BusyBarEntity.__init__(self, coordinator, name, "screen")
        ImageEntity.__init__(self, hass)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Frames come on their own throttled signal rather than the
        # coordinator's, which would otherwise refresh every entity ten
        # times a second.
        self.async_on_remove(self.coordinator.add_frame_listener(self._frame_arrived))
        if self._screen() is not None:
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _frame_arrived(self) -> None:
        """
        Note that the picture changed, so the frontend refetches it.
        """
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    def _screen(self):
        """
        The latest front-panel frame, if one has arrived.
        """
        data = self.coordinator.data
        return None if data is None else data.snapshot.screen_front

    async def async_image(self) -> bytes | None:
        frame = self._screen()
        if frame is None:
            return None
        enlarged = frame.scale(_SCALE)
        return enlarged.pad(enlarged.width, enlarged.width).to_png()
