"""Constants for the BUSY Bar integration."""

DOMAIN = "busy"

# The bar sees this as the drawing's owner, and it is also how the cloud can
# tell a BUSY Bar is driven by Home Assistant at all - the team decided to
# identify the integration by application_name and User-Agent rather than
# have the firmware report a connection itself.
APPLICATION_NAME = "home_assistant"

DEFAULT_DURATION = 10
MAX_DURATION = 120

SERVICE_NOTIFY = "notify"
SERVICE_START_TIMER = "start_timer"
SERVICE_STOP_TIMER = "stop_timer"
SERVICE_PAUSE_TIMER = "pause_timer"
SERVICE_RESUME_TIMER = "resume_timer"
SERVICE_NEXT_PHASE = "next_phase"
SERVICE_SET_THEME = "set_theme"
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_CLEAR = "clear"

# Where the bar keeps the themes it can show. Reading the directory is how
# the theme list stays whatever the firmware actually ships, instead of a
# copy here that goes stale on the next release.
THEMES_PATH = "/ext/apps_assets/busy/themes"

# The theme every bar has without an asset directory of its own.
DEFAULT_THEME = "busy"
