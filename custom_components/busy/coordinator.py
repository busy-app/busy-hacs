from typing import Tuple

from homeassistant.config_entries import ConfigEntry
from busylib import AsyncBusyBar

class BusyBarConfigEntry(ConfigEntry):
    runtime_data: Tuple[AsyncBusyBar, str]
