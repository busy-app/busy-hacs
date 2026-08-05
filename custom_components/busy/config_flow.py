"""Config flow for the BUSY Bar integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE_ID, CONF_TOKEN
from homeassistant.components import zeroconf

from busylib import BusyBarDevices
from busylib.exceptions import BusyBarError

import logging

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel("DEBUG")

class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """

    "user"                            "zeroconf", "reconfigure"
     |                                          |
     |                                          |
     |                                          |
     \                                          \ 
      --> "find_devices" --x-> "select_device" --x-> "mint_token" ---x------
                            \                   /                     \     \ 
                            |                   \   password needed   /     |
                            |                    --------------------       |
                            |                                               |
                            v                                               v
                      "no_devices"                                        done

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
        zc = await zeroconf.async_get_instance(self.hass)
        self.devices = await BusyBarDevices.discover(1.5, zc)

        if len(self.devices) > 1:
            _LOGGER.debug("step \"find_devices\": more than 1 device found")
            _LOGGER.debug("step \"find_devices\" -> \"select_device\"")
            return await self.async_step_select_device()
        elif len(self.devices) == 1:
            _LOGGER.debug("step \"find_devices\": exactly 1 device found")
            _LOGGER.debug("step \"find_devices\" -> \"select_device\"")
            device = self.devices[0]
            return await self.async_step_select_device({"device": device.name})
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
                vol.Required("password", default=""): vol.All(str, vol.Length(min=4, max=10))
            }
        )

        password = None
        if user_input:
            _LOGGER.debug("step \"mint_token\" (with input)")
            password = user_input["password"]
        else:
            _LOGGER.debug("step \"mint_token\" (without input)")

        client = self.device.to_async_client(token=password)

        try:
            _LOGGER.debug("step \"mint_token\": minting token")
            token_info = await client.token_mint(self.hass.config.location_name)
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
