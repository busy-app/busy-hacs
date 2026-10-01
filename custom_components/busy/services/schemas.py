"""What each action accepts."""

from __future__ import annotations

from busylib.features import notification
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

DEFAULT_DURATION = 10
MAX_DURATION = 120

# Home Assistant's own target fields rather than a device id of our own,
# because an automation targets what it has to hand: a room, a label, one of
# the bar's entities. Asking for a device alone made "every bar in the
# living room" fail validation.
TARGET = vol.Schema(cv.TARGET_SERVICE_FIELDS)

_COLOUR = vol.All(
    [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(3, 3)
)
_DURATION = vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_DURATION))
_UINT = vol.All(vol.Coerce(int), vol.Range(min=0))

# Durations are minutes in the action and milliseconds on the wire. The
# bounds are the firmware's own - a countdown up to a day, a phase 5 minutes
# to 8 hours - and busylib checks them again before the write, since the bar
# reports a length it will not run as an unparseable snapshot.
_MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=24 * 60))
_PHASE = vol.All(vol.Coerce(int), vol.Range(min=5, max=8 * 60))

_ALIGNMENTS = (
    "top_left",
    "top_mid",
    "top_right",
    "mid_left",
    "center",
    "mid_right",
    "bottom_left",
    "bottom_mid",
    "bottom_right",
)

# Icon and sound names are not checked against a list here: which exist is a
# fact about the bar written to, and busylib asks it.
NOTIFY = TARGET.extend(
    {
        vol.Required("line_1"): cv.string,
        vol.Optional("line_2"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("sound"): cv.string,
        vol.Optional("duration", default=DEFAULT_DURATION): _DURATION,
        # Above other applications' drawings, not above a session: while one
        # runs the firmware refuses every drawing whatever its priority.
        vol.Optional("interrupt", default=False): cv.boolean,
        vol.Optional("line_1_font", default=notification.DEFAULT_FONT): vol.In(
            notification.ONE_LINE_FONTS
        ),
        # Two lines fit only the shorter fonts.
        vol.Optional("line_2_font"): vol.In(notification.TWO_LINE_FONTS),
        vol.Optional("line_1_color"): _COLOUR,
        vol.Optional("line_2_color"): _COLOUR,
        vol.Optional("background_color"): _COLOUR,
    }
)

# Every knob the firmware's own draw call has, under the API's own names.
DRAW = TARGET.extend(
    {
        vol.Required("text"): cv.string,
        vol.Optional("display", default="front"): vol.In(("front", "back")),
        vol.Optional("font", default=notification.DEFAULT_FONT): vol.In(
            notification.ONE_LINE_FONTS
        ),
        vol.Optional("color"): _COLOUR,
        vol.Optional("align"): vol.In(_ALIGNMENTS),
        vol.Optional("x", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=-4096, max=4095)
        ),
        vol.Optional("y", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=-4096, max=4095)
        ),
        # Text longer than `width` scrolls if a rate was given, else is cut.
        vol.Optional("width"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("scroll_rate"): _UINT,
        vol.Optional("scroll_start_delay"): _UINT,
        vol.Optional("duration", default=DEFAULT_DURATION): _DURATION,
        vol.Optional("interrupt", default=False): cv.boolean,
        vol.Optional("led_color"): _COLOUR,
        # Drawing again under one name replaces what it drew, and `clear`
        # can take the name to remove that one piece.
        vol.Optional("name", default="draw"): cv.matches_regex(r"^[a-zA-Z0-9._-]+$"),
    }
)

# A theme given here belongs to the session; the card keeps its own.
START_CARD = TARGET.extend({vol.Optional("theme"): cv.string})

# Every quick field is optional: left out, the value is the one set in the
# quick settings entities.
QUICK_INFINITE = START_CARD
QUICK_SIMPLE = TARGET.extend(
    {vol.Optional("duration"): _MINUTES, vol.Optional("theme"): cv.string}
)
QUICK_INTERVAL = TARGET.extend(
    {
        vol.Optional("work"): _PHASE,
        vol.Optional("rest"): _PHASE,
        vol.Optional("cycles"): vol.All(vol.Coerce(int), vol.Range(min=2, max=35)),
        vol.Optional("theme"): cv.string,
    }
)

# Without a mode the running session's theme changes and reverts when it
# ends; with one, that card's own theme changes for good.
SET_THEME = TARGET.extend(
    {
        vol.Required("theme"): cv.string,
        vol.Optional("mode"): vol.In(("busy", "custom")),
    }
)

PLAY_SOUND = TARGET.extend({vol.Required("sound"): cv.string})
