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
