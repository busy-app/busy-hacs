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
    UnitOfElectricPotential,
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
            # The room card reads these in this order, so it is the one a
            # person reads them in: how long the bar has been up, then
            # what it is running and how far along.
            BootTimeSensor(coordinator, name),
            SessionTypeSensor(coordinator, name),
            SessionPhaseSensor(coordinator, name),
            SessionEndsAtSensor(coordinator, name),
            SessionThemeSensor(coordinator, name),
            BatterySensor(coordinator, name),
            WifiNetworkSensor(coordinator, name),
            WifiSignalSensor(coordinator, name),
            UsbVoltageSensor(coordinator, name),
            IpAddressSensor(coordinator, name),
            ApiVersionSensor(coordinator, name),
            BluetoothSensor(coordinator, name),
            TimezoneSensor(coordinator, name),
        ]
    )
class _SessionSensor(BusyBarEntity, SensorEntity):
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


class SessionTypeSensor(_SessionSensor):
    """Which kind of session is running."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["not_started", "infinite", "simple", "interval"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_type")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        return None if state is None else state.mode


class SessionPhaseSensor(_SessionSensor):
    """
    Work or rest — the thing automations branch on.

    `none` covers every case where no phase applies: no session, or one that
    has finished.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["work", "rest", "none"]

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_phase")

    @property
    def native_value(self) -> str | None:
        state = self._state()
        if state is None:
            return None
        return state.phase or "none"


class SessionEndsAtSensor(_SessionSensor):
    """
    When the current phase runs out.

    A timestamp rather than a count of seconds: entities here are updated
    when the bar pushes a change, so a seconds value would sit still between
    pushes, while a timestamp lets the frontend and templates count down
    themselves.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_phase_ends")

    @property
    def native_value(self) -> datetime | None:
        state = self._state()
        if state is None or state.time_left_ms is None or not state.is_running:
            return None
        if state.is_paused:
            # A paused phase has no end until it is resumed.
            return None
        return dt_util.utcnow() + timedelta(milliseconds=state.time_left_ms)


class SessionThemeSensor(BusyBarEntity, SensorEntity):
    """
    The theme on screen right now.

    Nothing while no session is running, because then no theme is being
    shown: the snapshot still carries one - whatever the last session
    ended with - and reporting that would claim the bar is showing a
    theme it is not. Each card's own theme is a separate entity.

    Diagnostic: it repeats what the bar is already showing across the
    room, so it earns a place on the device page and not in the card for
    a room.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "session_theme")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.snapshot.timer is None:
            return None
        if not timer_state(data.snapshot.timer).is_running:
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
    # Not diagnostic, unlike the readings around it. "Up since Tuesday" is
    # the first thing a person checks when a bar is behaving oddly, and
    # the room card shows nothing that carries a category.

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


class TimezoneSensor(BusyBarEntity, SensorEntity):
    """
    The timezone the bar keeps its clock in.

    A reading rather than a list to pick from: the bar has its own
    timezone and its clock is on screen all day, so it is worth seeing -
    but it is set on the bar, and offering to change it from here puts two
    places in charge of one thing.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "timezone")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return None if data is None else data.timezone


class WifiSignalSensor(_WifiSensor):
    """
    How strong the bar's Wi-Fi signal is.

    In dBm, which is what the radio reports: roughly -50 is next to the
    access point, -70 is workable, -85 is where a bar starts dropping off
    the network. Diagnostic, because it is the first thing to look at when
    one does.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "wifi_signal")

    @property
    def native_value(self) -> int | None:
        wifi = self._wifi()
        return None if wifi is None else wifi.rssi


class UsbVoltageSensor(BusyBarEntity, SensorEntity):
    """
    What the bar measures on its USB rail.

    A reading, not an answer to "is it plugged in": a bar discharging with
    nothing attached still reports about 4.5 V here. Whether a cable is
    there is something the firmware knows and does not put on the wire,
    which is why this integration has no sensor claiming to know.
    """

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.MILLIVOLT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator, name: str) -> None:
        super().__init__(coordinator, name, "usb_voltage")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if data is None or data.snapshot.power is None:
            return None
        return data.snapshot.power.usb_voltage
