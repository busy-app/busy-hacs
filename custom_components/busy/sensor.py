"""Sensors for the BUSY Bar timer and power state."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any
from urllib.parse import urlparse

from busylib import types
from busylib.exceptions import BusyBarError
from busylib.features import timer_state

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

_LOGGER = logging.getLogger(__name__)

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]


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
            TimerModeSensor(coordinator, name),
            TimerPhaseSensor(coordinator, name),
            TimerEndsAtSensor(coordinator, name),
            ThemeSensor(coordinator, name),
            BatterySensor(coordinator, name),
            WifiNetworkSensor(coordinator, name),
            WifiSignalSensor(coordinator, name),
            WifiSignalStrengthSensor(coordinator, name),
            IpAddressSensor(coordinator, name),
            ApiVersionSensor(coordinator, name),
            BluetoothSensor(coordinator, name),
            BootTimeSensor(coordinator, name),
        ]
    )


# Where "weak", "medium" and "strong" divide. Wi-Fi radios are usually
# described as good above -60 dBm and barely usable below -75, which is the
# range worth naming rather than showing a number nobody reads.
_STRONG_RSSI = -60
_MEDIUM_RSSI = -75


class _TimerSensor(BusyBarEntity, SensorEntity):
    """
    Base for sensors that read the timer.
    """

    def _state(self):
        """
        The timer's state now, or None while the timer is unknown.
        """
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return timer_state(data.snapshot.timer)


class TimerModeSensor(_TimerSensor):
    """Which kind of session is running."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["not_started", "infinite", "simple", "interval"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_mode")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        return None if state is None else state.mode


class TimerPhaseSensor(_TimerSensor):
    """
    Work or rest — the thing automations branch on.

    `none` covers every case where no phase applies: no session, or one that
    has finished.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["work", "rest", "none"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_phase")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        if state is None:
            return None
        return state.phase or "none"


class TimerEndsAtSensor(_TimerSensor):
    """
    When the current phase runs out.

    A timestamp rather than a count of seconds: entities here are updated
    when the bar pushes a change, so a seconds value would sit still between
    pushes, while a timestamp lets the frontend and templates count down
    themselves.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timer_ends_at")

    @property
    def native_value(self) -> datetime | None:
        state = self._state()
        if state is None or state.time_left_ms is None or not state.is_running:
            return None
        if state.is_paused:
            # A paused phase has no end until it is resumed.
            return None
        return dt_util.utcnow() + timedelta(milliseconds=state.time_left_ms)


class ThemeSensor(BusyBarEntity, SensorEntity):
    """The theme the running profile is showing."""


    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "theme")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        return data.snapshot.timer.snapshot.busy_bar_settings.theme


class BatterySensor(BusyBarEntity, SensorEntity):
    """
    Charge level.

    Diagnostic, so it sits with the other power and connectivity readings
    rather than among the timer entities people actually watch. Home
    Assistant still shows the battery in the device header regardless.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "battery")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if data is None or data.snapshot.power is None:
            return None
        return data.snapshot.power.battery_charge


class _WifiSensor(BusyBarEntity, SensorEntity):
    """
    Base for the Wi-Fi readings, which all come from one status object.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _wifi(self):
        """
        The Wi-Fi status, or None while it is unknown or disconnected.
        """
        data = self.coordinator.data
        if data is None or data.snapshot.wifi is None:
            return None
        wifi = data.snapshot.wifi
        if wifi.state is not types.WifiState.CONNECTED:
            return None
        return wifi


class WifiNetworkSensor(_WifiSensor):
    """
    Which network the bar is on.

    The rest of what the bar knows about the connection - the access point
    it picked, the channel, the security - rides along as attributes rather
    than as four more rows nobody scans.
    """

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "wifi_network")

    @property
    def native_value(self) -> str | None:
        wifi = self._wifi()
        return None if wifi is None else wifi.ssid

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        wifi = self._wifi()
        if wifi is None:
            return None
        return {
            "access_point": wifi.bssid,
            "channel": wifi.channel,
            "security": None if wifi.security is None else wifi.security.value,
        }


class WifiSignalSensor(_WifiSensor):
    """
    How good the signal is, in words.

    dBm is the honest unit and it is available as its own sensor, but the
    question being asked of this one is whether the bar is well placed, and
    "weak" answers that without anyone having to remember that -80 is bad.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["weak", "medium", "strong"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "wifi_signal")

    @property
    def native_value(self) -> str | None:
        wifi = self._wifi()
        if wifi is None or wifi.rssi is None:
            return None
        if wifi.rssi >= _STRONG_RSSI:
            return "strong"
        if wifi.rssi >= _MEDIUM_RSSI:
            return "medium"
        return "weak"


class WifiSignalStrengthSensor(_WifiSensor):
    """
    The signal in dBm, for anyone who wants to graph it.

    Off by default: the named version above is what the reading is usually
    wanted for, and two entities saying the same thing crowd the page.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "wifi_signal_strength")

    @property
    def native_value(self) -> int | None:
        wifi = self._wifi()
        return None if wifi is None else wifi.rssi


class IpAddressSensor(BusyBarEntity, SensorEntity):
    """
    The address Home Assistant is talking to the bar on.

    Taken from the client rather than from the bar's Wi-Fi status: a bar
    plugged in over USB answers on its own subnet and reports the Wi-Fi
    address it is not being reached at, and the stream's Wi-Fi updates
    carry no address at all. This is the one that matters anyway - when a
    bar goes unavailable, the first useful question is where Home Assistant
    was looking for it.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "ip_address")

    @property
    def native_value(self) -> str | None:
        return urlparse(self.coordinator.client.base_url).hostname


class ApiVersionSensor(BusyBarEntity, SensorEntity):
    """
    The HTTP API version the firmware implements.

    The firmware version is on the device page already; this is the number
    that decides whether a given feature works, so it is the one to ask for
    when something is unsupported.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "api_version")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.system is None:
            return None
        return data.snapshot.system.api_semver


class BootTimeSensor(BusyBarEntity, SensorEntity):
    """
    When the bar last started.

    The bar also reports uptime as a preformatted string, but it does not
    normalise the hours ("02d 53h 59m 13s" on a bar up for two days), so
    the timestamp it boots at is both correct and what Home Assistant
    expects: the frontend renders it as "3 days ago" on its own.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "boot_time")

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if data is None or data.snapshot.system is None:
            return None
        boot_time = data.snapshot.system.boot_time
        if not boot_time:
            return None
        return dt_util.utc_from_timestamp(boot_time)


class BluetoothSensor(BusyBarEntity, SensorEntity):
    """
    What the bar's Bluetooth radio is doing.

    Not a connectivity switch: the bar decides for itself when to be
    connectable, and this says which of those states it is in.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    # The firmware's own vocabulary, from ble_status_names in api_ble.c.
    # Note that "disabled" is its name for the radio being ready but not
    # advertising, and "enabled" for advertising - not a mistake here.
    _attr_options = [
        "reset",
        "initialization",
        "disabled",
        "enabled",
        "connectable",
        "connected",
        "error",
        "unknown",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "bluetooth")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.ble is None:
            return None
        status = data.snapshot.ble.status
        if not status:
            return None
        # The firmware reports its error state as "internal error", which
        # is a sentence rather than a state name.
        status = "error" if "error" in status.lower() else status.lower()
        return status if status in self._attr_options else "unknown"
