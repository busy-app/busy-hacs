"""Config flow for the BUSY Bar integration."""

from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE_ID, CONF_TOKEN

from busylib.devices import (
    BUSYBAR_INSTANCE_NAME_PREFIX,
    BUSYBAR_USB_SUBNET,
    BusyBarAddress,
    BusyBarAddressAffinity,
    BusyBarDevice,
)
from busylib.exceptions import BusyBarError

from .const import DOMAIN
from .discovery import async_discover_busy

_LOGGER = logging.getLogger(__name__)


def _announced_address(ip: str) -> BusyBarAddress:
    """Classify one announced address the way busylib's discovery does.

    busylib decides USB vs Wi-Fi from the address itself, since a bar
    plugged into this machine answers on its own USB subnet. Mirroring the
    rule here keeps a device built from an mDNS announcement equivalent to
    one that came out of a busylib scan.
    """
    return BusyBarAddress(
        ip_address=ip,
        affinity=(
            BusyBarAddressAffinity.OVER_USB
            if ip.startswith(BUSYBAR_USB_SUBNET)
            else BusyBarAddressAffinity.OVER_WIFI
        ),
    )

class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """

    "user"                                     "zeroconf"
     |                                             |
     |                                             v
     |                                    "zeroconf_confirm"
     |                                             |
     |                    no address announced <---+---> address known
     |                                |                        |
     v                                v                        |
    "find_devices" --x-> "select_device" --x-> "mint_token" <---+
     |                                          |       ^
     v                                          |       | password needed
    "no_devices"                                v       |
                                              done      +--- (retry form)

    A zeroconf discovery already names one bar and carries its address, so
    it skips the scan and the picker entirely. Only a user-initiated flow -
    or an announcement with no usable IPv4 address - goes through discovery.

    """

    VERSION = 1

    #
    #                         +--------+
    # direct user request --> | "user" | --> "find_devices"
    #                         +--------+
    #
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        _LOGGER.debug("step \"user\" -> \"find_devices\"")
        return await self.async_step_find_devices()

    async def async_step_zeroconf(
        self, discovery_info: Any
    ) -> ConfigFlowResult:
        """Handle a BUSY Bar discovered by Home Assistant Zeroconf."""
        _LOGGER.debug("zeroconf discovery: %s", discovery_info)
        # discovery_info.name is the raw mDNS instance name (e.g.
        # "busybar-0cfa22201131._http._tcp.local.") - not something to show
        # a user. The bar announces itself under the shared _http service
        # behind a "busybar-" prefix, and busylib strips that prefix to form
        # device_id; stripping it here too is what makes the unique_id set
        # on this path the same one a user-driven flow sets from a scanned
        # device. Without it the two never match, so an already-configured
        # bar keeps being offered as a fresh discovery and the dedup in
        # "select_device" never finds this flow.
        instance_name = discovery_info.name.split(".")[0]
        device_id = instance_name.removeprefix(BUSYBAR_INSTANCE_NAME_PREFIX)
        # The bar's actual name is in its TXT record, the same place
        # busylib's own device parsing reads it from.
        device_name = discovery_info.properties.get("name") or "BUSY Bar"
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": device_name}
        # The announcement already carries the addresses needed to reach
        # this one bar, so keep them rather than throwing them away and
        # rediscovering. IPv4 only, matching what busylib collects.
        addresses = discovery_info.ip_addresses or [discovery_info.ip_address]
        self.device = BusyBarDevice(
            name=device_name,
            device_id=device_id,
            addresses={
                _announced_address(str(ip)) for ip in addresses if ip.version == 4
            },
        )
        return await self.async_step_zeroconf_confirm()

    #
    #                       +--------------------+
    # "zeroconf" --x-x----> | "zeroconf_confirm" | --x--> "mint_token"
    #                       +--------------------+    \
    #                                                  --> "find_devices"
    #                                                      (no usable address)
    #
    # A bar re-announces itself over mDNS periodically. Without this pause,
    # a second announcement arriving while the first one is still busy
    # scanning (find_devices takes ~10s) would start a second flow for the
    # same unique_id and get aborted as "already_in_progress". Stopping here
    # for user confirmation keeps the flow parked on one instance that
    # repeat announcements just refresh, instead of racing each other.
    #
    # Confirming goes straight to minting a token. The user has already said
    # which bar they want by picking this discovery, and the announcement
    # carried its address, so a second 10s scan followed by a picker listing
    # every bar on the network would discard a choice already made and ask
    # for it again.
    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            _LOGGER.debug("step \"zeroconf_confirm\" (no input)")
            return self.async_show_form(
                step_id="zeroconf_confirm",
                description_placeholders=self.context["title_placeholders"],
            )

        # An announcement carrying no IPv4 address leaves nothing to talk
        # to, so fall back to scanning rather than failing on a client that
        # has no address to build from.
        if self.device.get_address() is None:
            _LOGGER.debug(
                "step \"zeroconf_confirm\" -> \"find_devices\" (no address announced)"
            )
            return await self.async_step_find_devices()

        _LOGGER.debug("step \"zeroconf_confirm\" -> \"mint_token\"")
        return await self.async_step_mint_token()

    #
    #            +----------------+
    # "user" --> | "find_devices" | --x---> "select_device"
    #            +----------------+    \
    #                                   --> "no_devices"
    #
    async def async_step_find_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        _LOGGER.debug("step \"find_devices\": discovering devices")
        self.devices = await async_discover_busy(self.hass)

        if self.devices:
            _LOGGER.debug("step \"find_devices\": %d device(s) found", len(self.devices))
            _LOGGER.debug("step \"find_devices\" -> \"select_device\"")
            # Always show the picker, even for a single device: silently
            # locking onto whichever one the scan happened to find first
            # gives the user no chance to notice a wrong or unexpected
            # device (e.g. a neighbor's bar, or the "other" one when more
            # than one exists but only one answered in time).
            return await self.async_step_select_device()
        else:
            _LOGGER.debug("step \"find_devices\" -> \"no_devices\"")
            return await self.async_step_no_devices()
    
    #
    #                    +--------------+
    # "find_devices" --> | "no_devices" | --> abort
    #                    +--------------+
    #
    async def async_step_no_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_abort(reason="no_devices_found")

    #
    #                      +-----------------+
    # "find_devices" ---x> | "select_device" | --x-> "mint_token"
    #                  /   +-----------------+    \
    #                 |                           |
    #                 \    user selects device   /
    #                  ----<-------<-------<----
    #
    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        SCHEMA = vol.Schema(
            {
                vol.Required("device", default=""): vol.In(
                    [dev.name for dev in self.devices]
                )
            }
        )

        if not user_input:
            _LOGGER.debug("step \"select_device\" (no input)")
            return self.async_show_form(
                step_id="select_device",
                data_schema=SCHEMA,
            )

        _LOGGER.debug("step \"select_device\" (with input)")
        dev_name = user_input["device"]
        device = next(dev for dev in self.devices if dev.name == dev_name)
        self.device = device
        # Another flow for this same device may already be alive - a
        # zeroconf-triggered one sitting unconfirmed in "Discovered" (the
        # bar re-announces itself over mDNS, so one is created readily and
        # never expires on its own), or this very flow having already set
        # this same unique_id back in async_step_zeroconf. Either way, this
        # flow is the one the user is actively driving to completion right
        # now, so it should win: discard any other in-progress flow for the
        # same unique_id before claiming it, instead of aborting ourselves
        # with already_in_progress.
        for progress in self._async_in_progress(
            include_uninitialized=True, match_context={"unique_id": device.device_id}
        ):
            self.hass.config_entries.flow.async_abort(progress["flow_id"])
        await self.async_set_unique_id(device.device_id)
        self._abort_if_unique_id_configured()

        _LOGGER.debug("step \"select_device\" -> \"mint_token\"")
        return await self.async_step_mint_token()

    #
    #   mDNS discovery --> "zeroconf" --
    #                                   \         +--------------+
    # token deleted --> "reconfigure" ---x---x--> | "mint_token" | --x-> done
    #                                   /   /     +--------------+    \
    #                 "select_device" --   |                          |
    #                                      \ user supplies password  /
    #                                       ----<-------<-------<---
    #
    async def async_step_mint_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        SCHEMA = vol.Schema(
            {
                vol.Required("password", default=""): vol.All(str, vol.Length(min=4, max=128))
            }
        )

        password = None
        if user_input:
            _LOGGER.debug("step \"mint_token\" (with input)")
            password = user_input["password"]
        else:
            _LOGGER.debug("step \"mint_token\" (without input)")

        client = await self.hass.async_add_executor_job(
            partial(self.device.to_async_client, token=password)
        )

        try:
            _LOGGER.debug("step \"mint_token\": minting token")
            token_info = await client.access_token_mint(
                self.hass.config.location_name
            )
            _LOGGER.debug(f"step \"mint_token\": acquired token with short_id=\"{token_info.short_id}\"")
            token = token_info.token
        except BusyBarError:
            _LOGGER.debug("step \"mint_token\": minting without password failed, requesting password from user")
            return self.async_show_form(
                step_id="mint_token",
                data_schema=SCHEMA,
            )

        self.entry_data = {
            CONF_DEVICE_ID: self.device.device_id,
            CONF_TOKEN: token,
        }

        return self.async_create_entry(
            title=self.device.name,
            data=self.entry_data,
        )
