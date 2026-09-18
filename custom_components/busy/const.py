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
SERVICE_START_BUSY = "start_busy"
SERVICE_START_CUSTOM = "start_custom"
SERVICE_START_QUICK_INFINITE = "start_quick_infinite"
SERVICE_START_QUICK_SIMPLE = "start_quick_simple"
SERVICE_START_QUICK_INTERVAL = "start_quick_interval"
SERVICE_STOP_SESSION = "stop_session"
SERVICE_PAUSE_SESSION = "pause_session"
SERVICE_RESUME_SESSION = "resume_session"
SERVICE_NEXT_PHASE = "next_phase"
SERVICE_SET_THEME = "set_theme"
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_CLEAR = "clear"
SERVICE_LIST_ASSETS = "list_assets"
SERVICE_UPLOAD_ASSET = "upload_asset"
