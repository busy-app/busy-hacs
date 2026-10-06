"""Serving the dashboard card that ships with the integration."""

from __future__ import annotations

import hashlib
import logging
import pathlib

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_CARD = pathlib.Path(__file__).parent / "www/busy-bar-card.js"
_CARD_URL = f"/{DOMAIN}/busy-bar-card.js"


def card_version(path: pathlib.Path = _CARD) -> str:
    """
    What tells a browser the card changed: a hash of the file itself.

    The browser serves the copy it first downloaded until the address
    changes. A version number someone must remember to raise gets
    forgotten, and everybody keeps the old card; a hash moves exactly when
    the file does.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


async def async_offer_the_card(hass: HomeAssistant) -> None:
    """
    Serve the card and tell the frontend to load it.

    A bar has three dozen entities, and laying them out by hand is a
    morning's work everyone repeats. The card is one file with no build
    step, served from the integration so it updates with it, and registered
    once rather than per bar: it finds its bar from the device it is
    configured with.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_CARD_URL, str(_CARD), cache_headers=False)]
    )
    if "frontend" not in hass.config.components:
        # A headless install or a test harness: nobody to hand the card to.
        _LOGGER.debug("no frontend loaded, so the card is served but not offered")
        return
    version = await hass.async_add_executor_job(card_version)
    add_extra_js_url(hass, f"{_CARD_URL}?v={version}")
