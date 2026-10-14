"""Config flow for the BUSY Bar integration."""

from functools import partial
import logging
from typing import Any

from busylib import AsyncBusyBar
from busylib.devices import (
    BUSYBAR_INSTANCE_NAME_PREFIX,
    BUSYBAR_USB_SUBNET,
    BusyBarAddress,
    BusyBarAddressAffinity,
    BusyBarDevice,
)
from busylib.exceptions import BusyBarError, BusyBarRequestError
from busylib.transports import AiohttpTransport
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import DOMAIN
from .discovery import async_discover_busy

_LOGGER = logging.getLogger(__name__)

_KEY_FORM = vol.Schema(
    {vol.Required("password", default=""): vol.All(str, vol.Length(min=4, max=128))}
)


async def _async_mint(client: AsyncBusyBar, name: str) -> tuple[str | None, str]:
    """
    Ask a bar for a token, and say why not if it will not give one.

    Returns the token, or a problem: `http_api_disabled` for a bar whose
    HTTP API is off, `invalid_auth` for one that wants a key it was not given.

    A bar with the API off still answers over HTTP - `/api/version` is 200,
    `/api/access` says `disabled` and minting is refused with a 403 - so the
    mode has to be read, and a refusal alone cannot be told from "needs a
    key". A bar that does not answer at all is the same thing seen from
    further away.
    """
    try:
        if (await client.access()).mode == "disabled":
            return None, "http_api_disabled"
    except BusyBarRequestError:
        return None, "http_api_disabled"
    except BusyBarError:
        pass  # firmware that cannot say; minting will
    try:
        return (await client.access_token_mint(name)).token, ""
    except BusyBarRequestError:
        return None, "http_api_disabled"
    except BusyBarError:
        return None, "invalid_auth"


def _token_name(hass: Any) -> str:
    """
    What the bar lists the token as, on its own screen, where a person picks
    which one to delete: Home Assistant, and which one.
    """
    return f"HA {hass.config.location_name}"


def _reachable_address(discovery_info: Any) -> str | None:
    """
    The announced address Home Assistant can actually use.

    A bar announces every address it has, and one of them is its own USB
    network - which answers only for the machine it is plugged into. Home
    Assistant is rarely that machine, so the Wi-Fi address is the one
    worth remembering, and the USB one only as a last resort.
    """
    announced = discovery_info.ip_addresses or [discovery_info.ip_address]
    addresses = [str(ip) for ip in announced if ip.version == 4]
    over_wifi = [ip for ip in addresses if not ip.startswith(BUSYBAR_USB_SUBNET)]
    return next(iter(over_wifi or addresses), None)


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
    r"""

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
    abort (nothing found)                       v       |
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
        return await self.async_step_find_devices()

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
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
        # With the address, not without it: a bar that came back on a new
        # lease announces itself here, and aborting empty-handed would
        # leave the entry pointing at the address it no longer has. This
        # is the moment the new one is known.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: _reachable_address(discovery_info)}
        )
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
            return self.async_show_form(
                step_id="zeroconf_confirm",
                description_placeholders=self.context["title_placeholders"],
            )

        # An announcement carrying no IPv4 address leaves nothing to talk
        # to, so fall back to scanning rather than failing on a client that
        # has no address to build from.
        if self.device.get_address() is None:
            return await self.async_step_find_devices()

        return await self.async_step_mint_token()

    #
    #            +----------------+
    # "user" --> | "find_devices" | --x---> "select_device"
    #            +----------------+    \
    #                                   --> abort (nothing found)
    #
    async def async_step_find_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self.devices = await async_discover_busy(self.hass)

        if self.devices:
            # Always show the picker, even for a single device: silently
            # locking onto whichever one the scan happened to find first
            # gives the user no chance to notice a wrong or unexpected
            # device (e.g. a neighbor's bar, or the "other" one when more
            # than one exists but only one answered in time).
            return await self.async_step_select_device()
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
            return self.async_show_form(
                step_id="select_device",
                data_schema=SCHEMA,
            )

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
        password = user_input["password"] if user_input else None

        client = await self.hass.async_add_executor_job(
            partial(
                self.device.to_async_client,
                # The address Home Assistant can reach. A bar plugged
                # into some other machine announces that machine's USB
                # network too, and minting a token against it fails the
                # way a bar with its HTTP API switched off does - which
                # is a confusing thing to tell someone whose bar is on.
                affinity=(
                    "over_wifi" if self.device.get_address("over_wifi") else None
                ),
                token=password,
                # Home Assistant's own session, so minting a token uses the
                # same connection pool as everything after it.
                transport=AiohttpTransport(async_get_clientsession(self.hass)),
            )
        )

        token, problem = await _async_mint(client, _token_name(self.hass))
        if problem == "http_api_disabled":
            # Asking for a key here is worse than useless - no key exists,
            # and the person is left trying passwords against a door that
            # is not there.
            return self.async_abort(reason="http_api_disabled")
        if token is None:
            return self.async_show_form(
                step_id="mint_token",
                data_schema=_KEY_FORM,
                errors={"base": "invalid_auth"} if password else None,
            )

        entry_data = {
            CONF_DEVICE_ID: self.device.device_id,
            CONF_TOKEN: token,
            # Remembering the address is what lets setup skip the ten-second
            # mDNS scan. It is a hint, not the identity: the device_id above
            # is that, and a bar that has moved is looked for again.
            # Over Wi-Fi by preference: `get_address()` answers with the
            # USB one first, which is right for a bar plugged into the
            # machine asking and wrong for Home Assistant, which is
            # usually somewhere else entirely.
            CONF_HOST: self.device.get_address("over_wifi")
            or self.device.get_address(),
        }

        return self.async_create_entry(
            title=self.device.name,
            data=entry_data,
        )

    #
    # token refused --> "reauth" --> "reauth_confirm" --x--> done
    #                                    ^               \
    #                                    +- key needed ---+
    #
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Get a new token for a bar that stopped accepting the old one.

        Only the token changes: the entry, its device and every entity stay,
        so automations that name them go on working. A bar that needs no key
        is paired again without being asked anything.
        """
        entry = self._get_reauth_entry()
        host = entry.data.get(CONF_HOST)
        if not host:
            return self.async_abort(reason="cannot_connect")
        password = user_input["password"] if user_input else None
        client = await self.hass.async_add_executor_job(
            partial(
                AsyncBusyBar,
                host,
                token=password,
                transport=AiohttpTransport(async_get_clientsession(self.hass)),
            )
        )
        try:
            token, problem = await _async_mint(client, _token_name(self.hass))
        finally:
            await client.aclose()
        if problem == "http_api_disabled":
            return self.async_abort(
                reason="http_api_disabled",
                description_placeholders={"name": entry.title},
            )
        if token is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_KEY_FORM,
                description_placeholders={"name": entry.title},
                errors={"base": "invalid_auth"} if password else None,
            )
        return self.async_update_reload_and_abort(
            entry, data_updates={CONF_TOKEN: token}
        )
