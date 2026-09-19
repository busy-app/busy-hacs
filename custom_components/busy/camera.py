"""The bar's front display, mirrored into Home Assistant."""

from __future__ import annotations

from busylib.exceptions import BusyBarError
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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

    async_add_entities([BusyBarScreen(coordinator, name)])


class BusyBarScreen(BusyBarEntity, Camera):
    """
    What the front panel is showing.

    A camera rather than an image, for one measured reason. An image
    entity's state is when its picture last changed, so a panel that
    changes while a timer counts writes a row into the recorder every
    second it is on - which on a real installation came to 96% of the
    whole database, most of it recorded while nobody was looking. A
    camera's state does not move: frames are handed out when something
    asks for one, and Home Assistant makes a stream of them for whoever
    opens the card. Live when watched, silent otherwise.

    The picture is square, which is the shape that survives. Home
    Assistant draws a picture in entity rows as a round thumbnail cropped
    to fill, so a wide strip came out as its leftmost fifth; centred in a
    square, the whole display is there - small, but all of it.

    The frames arrive on the state stream the coordinator is already
    following, so this costs no extra requests: the bar sends them
    whether or not anyone is looking, and the newest one is always to
    hand. Decoding, enlarging, padding and PNG encoding all come from
    busylib, which knows the panel's geometry and wire format.
    """

    # What the built-in stream hands out: the bar sends about ten frames a
    # second and a 72x16 panel says all it has to say in one.
    _attr_frame_interval = 1.0

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        BusyBarEntity.__init__(self, coordinator, name, "screen")
        Camera.__init__(self)
        # Set after the base class, which assigns the default to the
        # instance - so the usual _attr_ class attribute never wins. It
        # matters twice over: the browser is told the truth, and Home
        # Assistant only runs its JPEG rescaler on what is actually JPEG.
        self.content_type = "image/png"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """
        The newest frame, enlarged and squared off.

        `width` and `height` are what the caller would like; they are the
        frontend's thumbnail sizes, and scaling a 72x16 panel down to them
        is what made it mush in the first place, so the picture is
        returned at the size the panel deserves and the browser fits it.
        """
        data = self.coordinator.data
        frame = None if data is None else data.snapshot.screen_front
        if frame is None:
            return None
        enlarged = frame.scale(_SCALE)
        return enlarged.pad(enlarged.width, enlarged.width).to_png()
