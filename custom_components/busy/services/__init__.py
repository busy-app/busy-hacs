"""Registration of the BUSY Bar actions.

Registered once, from `async_setup`, rather than per config entry: an
automation naming an action validates as soon as the integration loads,
whether or not a bar is reachable (the `action-setup` quality-scale rule),
and nothing is registered again for every bar added.
"""

from __future__ import annotations

from functools import partial

from homeassistant.core import HomeAssistant, SupportsResponse

from ..const import DOMAIN
from . import schemas
from .actions import ACTIONS, list_assets, run


def async_register_services(hass: HomeAssistant) -> None:
    for name, (schema, work, drawing) in ACTIONS.items():
        hass.services.async_register(
            DOMAIN, name, partial(run, work=work, drawing=drawing), schema=schema
        )
    # Read-only, and the caller always wants the answer: this exists to be
    # run from the UI and read.
    hass.services.async_register(
        DOMAIN,
        "list_assets",
        list_assets,
        schema=schemas.TARGET,
        supports_response=SupportsResponse.ONLY,
    )
