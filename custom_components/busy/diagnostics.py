"""What to hand over when someone asks what this bar is doing."""

from __future__ import annotations

from typing import Any

from busylib.exceptions import BusyBarError
from busylib.features import assets

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
        # What this bar can draw and play. Here rather than on the device
        # page because it is long, it is per-bar, and the moment it is
        # wanted is when an action refused a name.
        "assets": await _assets(coordinator),
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


async def _assets(coordinator: Any) -> dict[str, Any]:
    """
    Everything this bar can draw and play, by kind.

    Read here rather than kept up to date: assets change when somebody
    uploads or deletes one, which is rare and never something an
    automation waits on. A bar that cannot be reached says so instead of
    failing the whole download.
    """
    try:
        found = await assets.discover_assets(coordinator.client)
    except BusyBarError as err:
        return {"error": str(err)}

    catalogue: dict[str, Any] = {}
    for asset in found:
        kind = catalogue.setdefault(asset.kind, {"shipped": [], "uploaded": {}})
        if asset.application is None:
            kind["shipped"].append(asset.reference)
        else:
            kind["uploaded"].setdefault(asset.application, []).append(asset.reference)
    return catalogue
