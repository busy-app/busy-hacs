"""Constants for the BUSY Bar integration."""

DOMAIN = "busy"

# The bar sees this as the drawing's owner, and it is also how the cloud can
# tell a BUSY Bar is driven by Home Assistant at all - the team decided to
# identify the integration by application_name and User-Agent rather than
# have the firmware report a connection itself.
APPLICATION_NAME = "home_assistant"

# The front panel. 72x16 leaves room for two 8px lines, or one centred line.
FRONT_WIDTH = 72
FRONT_HEIGHT = 16

# A drawing loses to anything with a higher priority and is refused with
# "409 Not drawn due to low priority", so a notification sits mid-range and
# an interrupting one goes above a running Busy session.
PRIORITY_DEFAULT = 50
PRIORITY_INTERRUPT = 91

ONE_LINE_FONTS = [
    "tiny",
    "small",
    "normal",
    "condensed",
    "bold",
    "large",
    "extra_large",
]

# Two lines only fit 16px in the shorter fonts; the two tallest are offered
# for a single line only.
TWO_LINE_FONTS = ["tiny", "small", "normal", "condensed", "bold"]

DEFAULT_FONT = "small"

# Per-font vertical tuning for the 72x16 panel. The draw fonts have different
# glyph metrics, so the same anchor sits a pixel off for some of them. These
# came from live calibration in the busy_ha prototype and are kept as the
# element `y` after it.
#
# One line is anchored `mid_left`; centre is y=8, but most fonts read better a
# pixel higher.
ONE_LINE_Y = {
    "tiny": 8,
    "small": 7,
    "normal": 7,
    "condensed": 7,
    "bold": 7,
    "large": 7,
    "extra_large": 8,
}

# Two lines anchor to `top_left` and `bottom_left`. Each entry is
# (top_y, bottom_y): tiny pulls the lines together, the 9px fonts push them
# apart so they do not touch.
TWO_LINE_Y = {
    "tiny": (1, 15),
    "small": (0, 16),
    "normal": (-1, 17),
    "condensed": (-1, 17),
    "bold": (-1, 17),
}

# Gap between a left-aligned icon and the text after it.
ICON_TEXT_GAP = 2

# scroll_rate is pixels per minute. Applied only when a line cannot fit, so
# short notifications stay still instead of crawling for no reason.
SCROLL_RATE = 1200

# Roughly how many characters of the default font fit across 72px. Used to
# decide whether a line needs to scroll at all.
SCROLL_THRESHOLD_CHARS = 12

# Curated front-panel icons, as (stock_path, width_px). The path needs its
# sub-folder and extension and only resolves under "shared/" - the flat
# "shared/<name>" form in the OpenAPI spec does not work, and firmware now
# answers 400 "Failed to decode image" for it rather than a silent 200.
# Width drives the text offset, so an icon and its text never overlap.
STOCK_ICONS = {
    "check": ("shared/images/checkmark_front_8x8.image", 8),
    "error": ("shared/images/error_front_8x8.image", 8),
    "info": ("shared/images/info_front_8x8.image", 8),
    "low_battery": ("shared/images/low_battery_front_8x8.image", 8),
    "clock": ("shared/images/clock_5x5.image", 5),
    "hourglass": ("shared/images/hourglass_5x5.image", 5),
    "start": ("shared/images/start_11x11.image", 11),
    "setup": ("shared/images/setup_11x11.image", 11),
}

STOCK_SOUNDS = {
    "event": "shared/sounds/calendar_event_starts.snd",
    "reminder": "shared/sounds/calendar_reminder_ends.snd",
    "volume": "shared/sounds/volume_change.snd",
}

DEFAULT_DURATION = 10
MAX_DURATION = 120

SERVICE_NOTIFY = "notify"
