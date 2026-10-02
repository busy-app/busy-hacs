"""Sensors for the BUSY Bar timer, power and connection state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from busylib import types
from busylib.features import timer_state
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import PARALLEL_UPDATES, BusyBarEntity

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

# The firmware's own vocabulary, from ble_status_names in api_ble.c. Its
# "disabled" is the radio ready but not advertising, and "enabled" is
# advertising - not a mistake here.
_BLE_STATES = [
    "reset",
    "initialization",
    "disabled",
    "enabled",
    "connectable",
    "connected",
    "error",
    "unknown",
]


@dataclass(frozen=True, kw_only=True)
class BusySensorDescription(SensorEntityDescription):
    """
    A sensor is a name for a reading: how to get it from the coordinator,
    and optionally the attributes that ride along.
    """

    value: Callable[[BusyBarCoordinator], Any]
    attributes: Callable[[BusyBarCoordinator], dict[str, Any] | None] | None = None


def _timer(coordinator: BusyBarCoordinator):
    """The timer's state now, or None while the timer is unknown."""
    running = coordinator.data.snapshot.timer
    return None if running is None else timer_state(running)


def _phase_ends(coordinator: BusyBarCoordinator) -> datetime | None:
    # A timestamp rather than seconds: entities update when the bar pushes,
    # so seconds would sit still between pushes while a timestamp lets the
    # frontend count down by itself. A paused phase has no end.
    state = _timer(coordinator)
    if state is None or state.time_left_ms is None or not state.is_running:
        return None
    if state.is_paused:
        return None
    return dt_util.utcnow() + timedelta(milliseconds=state.time_left_ms)


def _session_theme(coordinator: BusyBarCoordinator) -> str | None:
    # Nothing while no session runs: the snapshot still carries whatever the
    # last session ended with, and reporting that would claim a theme the
    # bar is not showing.
    state = _timer(coordinator)
    if state is None or not state.is_running:
        return None
    return coordinator.data.snapshot.timer.snapshot.busy_bar_settings.theme


def _wifi(coordinator: BusyBarCoordinator) -> types.WifiStatus | None:
    """The Wi-Fi status, or None while it is unknown or disconnected."""
    wifi = coordinator.data.snapshot.wifi
    if wifi is None or wifi.state is not types.WifiState.CONNECTED:
        return None
    return wifi


def _wifi_attributes(coordinator: BusyBarCoordinator) -> dict[str, Any] | None:
    # The access point, channel and security ride along rather than as four
    # more rows nobody scans.
    wifi = _wifi(coordinator)
    if wifi is None:
        return None
    return {
        "access_point": wifi.bssid,
        "channel": wifi.channel,
        "security": None if wifi.security is None else wifi.security.value,
    }


def _boot_time(coordinator: BusyBarCoordinator) -> datetime | None:
    # The bar's uptime string does not normalise hours ("02d 53h 59m 13s"),
    # so the timestamp it booted at is both correct and what the frontend
    # renders as "3 days ago".
    system = coordinator.data.snapshot.system
    if system is None or not system.boot_time:
        return None
    return dt_util.utc_from_timestamp(system.boot_time)


def _bluetooth(coordinator: BusyBarCoordinator) -> str | None:
    ble = coordinator.data.snapshot.ble
    if ble is None or not ble.status:
        return None
    # The firmware reports its error state as "internal error", a sentence
    # rather than a state name.
    status = "error" if "error" in ble.status.lower() else ble.status.lower()
    return status if status in _BLE_STATES else "unknown"


def _power(field: str) -> Callable[[BusyBarCoordinator], Any]:
    def read(coordinator: BusyBarCoordinator) -> Any:
        power = coordinator.data.snapshot.power
        return None if power is None else getattr(power, field)

    return read


_DIAGNOSTIC = EntityCategory.DIAGNOSTIC

# The room card lists entities in this order, so it is the order a person
# reads them in: how long the bar has been up, then what it is running and
# how far along, then the diagnostic readings.
SENSORS: tuple[BusySensorDescription, ...] = (
    # Not diagnostic: "up since Tuesday" is the first thing checked when a
    # bar behaves oddly, and the room card shows nothing with a category.
    BusySensorDescription(
        key="boot_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_boot_time,
    ),
    BusySensorDescription(
        key="session_type",
        device_class=SensorDeviceClass.ENUM,
        options=["not_started", "infinite", "simple", "interval"],
        value=lambda c: state.mode if (state := _timer(c)) else None,
    ),
    BusySensorDescription(
        # What automations branch on; "none" covers no session or a
        # finished one.
        key="session_phase",
        device_class=SensorDeviceClass.ENUM,
        options=["work", "rest", "none"],
        value=lambda c: (state.phase or "none") if (state := _timer(c)) else None,
    ),
    BusySensorDescription(
        key="session_phase_ends",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_phase_ends,
    ),
    BusySensorDescription(
        key="session_theme",
        entity_category=_DIAGNOSTIC,
        value=_session_theme,
    ),
    BusySensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=_DIAGNOSTIC,
        value=_power("battery_charge"),
    ),
    BusySensorDescription(
        key="wifi_network",
        entity_category=_DIAGNOSTIC,
        value=lambda c: wifi.ssid if (wifi := _wifi(c)) else None,
        attributes=_wifi_attributes,
    ),
    BusySensorDescription(
        # In dBm: about -50 is next to the access point, -70 workable, -85
        # where a bar starts dropping off the network.
        key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=_DIAGNOSTIC,
        value=lambda c: wifi.rssi if (wifi := _wifi(c)) else None,
    ),
    BusySensorDescription(
        # A reading, not "is it plugged in": a discharging bar with nothing
        # attached still reports about 4.5 V, and the firmware does not put
        # the cable on the wire.
        key="usb_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=_DIAGNOSTIC,
        value=_power("usb_voltage"),
    ),
    BusySensorDescription(
        # Taken from the client, not the bar's Wi-Fi status: a bar plugged in
        # over USB answers on its own subnet while reporting the Wi-Fi
        # address it is not reached at. When a bar goes unavailable, where
        # Home Assistant was looking is the useful question.
        key="ip_address",
        entity_category=_DIAGNOSTIC,
        value=lambda c: urlparse(c.client.base_url).hostname,
    ),
    BusySensorDescription(
        # The number that decides whether a feature works.
        key="api_version",
        entity_category=_DIAGNOSTIC,
        value=lambda c: s.api_semver if (s := c.data.snapshot.system) else None,
    ),
    BusySensorDescription(
        key="bluetooth",
        device_class=SensorDeviceClass.ENUM,
        options=_BLE_STATES,
        entity_category=_DIAGNOSTIC,
        value=_bluetooth,
    ),
    BusySensorDescription(
        # A reading, not a picker: it is set on the bar, and offering to
        # change it here puts two places in charge of one thing.
        key="timezone",
        entity_category=_DIAGNOSTIC,
        value=lambda c: c.data.timezone,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BusyBarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(BusySensor(coordinator, d) for d in SENSORS)


class BusySensor(BusyBarEntity, SensorEntity):
    entity_description: BusySensorDescription

    def __init__(
        self, coordinator: BusyBarCoordinator, description: BusySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes = self.entity_description.attributes
        return None if attributes is None else attributes(self.coordinator)
