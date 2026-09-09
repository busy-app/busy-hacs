"""What to hand over when someone asks what this bar is doing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import BusyBarConfigEntry

# The access token is the one secret here: it is the bar's equivalent of a
# password, and a diagnostics download is meant to be shareable.
TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: BusyBarConfigEntry
) -> dict[str, Any]:
    """
    Everything known about one bar, labelled.

    This is where the facts that have no place on the device page live: the
    three MAC addresses and which interface each belongs to, the build the
    firmware came from, the hardware identifiers. The device page has rows
    for a model, a hardware version and a serial and nothing else, and
    unlabelled MAC addresses there told the reader less than nothing.
    """
    coordinator = config_entry.runtime_data
    data = coordinator.data
    snapshot = None if data is None else data.snapshot
    status = None if snapshot is None else snapshot.status

    device: dict[str, Any] = {}
    if status is not None and status.device is not None:
        reported = status.device
        device = {
            "serial_number": reported.serial_number,
            "hardware_version": reported.otp_model,
            "hardware_identifiers_programmed": reported.otp_valid,
            "firmware_security": reported.firmware_security,
            "mac_addresses": {
                "wifi": reported.wifi_mac,
                "usb": reported.usb_mac,
                "bluetooth": reported.ble_mac,
            },
        }

    firmware: dict[str, Any] = {}
    if status is not None and status.firmware is not None:
        reported = status.firmware
        firmware = {
            "version": reported.version,
            "branch": reported.branch,
            "build_date": reported.build_date,
            "commit_hash": reported.commit_hash,
            "intercom_version": reported.intercom_version,
            "nwp_version": reported.nwp_version,
            "matter_version": reported.matter_version,
        }

    system: dict[str, Any] = {}
    if snapshot is not None and snapshot.system is not None:
        reported = snapshot.system
        system = {
            "api_version": reported.api_semver,
            "boot_time": reported.boot_time,
            "uptime_as_reported": reported.uptime,
            "auto_update_enabled": reported.auto_update_enabled,
        }

    return {
        "entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "reached_at": coordinator.client.base_url,
        "device": device,
        "firmware": firmware,
        "system": system,
        "settings": {
            "brightness": None if data is None else data.brightness,
            "timezone": None if data is None else data.timezone,
            "smart_home_switch": None if data is None else data.smart_home,
        },
        # The whole snapshot as the library models it, for anything the
        # sections above do not name. Frames are excluded by the model.
        "snapshot": None if snapshot is None else snapshot.model_dump(mode="json"),
    }
