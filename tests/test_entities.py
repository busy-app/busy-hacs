"""
Entities: that every one a bar gets exists and has a name, and that driving
them reaches the bar the way the actions do.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from busylib.exceptions import BusyBarError
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.busy.quick import QUICK_CARD_ID

EN = (
    Path(__file__).resolve().parent.parent
    / "custom_components/busy/translations/en.json"
)


async def test_every_entity_a_bar_gets_has_a_name(hass, bar, prod_entry) -> None:
    """
    An entity whose translation key is missing shows up as a blank row, and
    renaming a key on one side only is how that happens. Setting every
    platform up also catches one that builds a class which is not there.
    """
    translations = json.loads(EN.read_text())["entity"]
    entries = er.async_entries_for_config_entry(er.async_get(hass), prod_entry.entry_id)

    unnamed = [
        f"{e.domain}.{e.translation_key}"
        for e in entries
        if e.translation_key not in translations.get(e.domain, {})
    ]
    assert entries
    assert not unnamed, f"entities without a name: {unnamed}"


async def test_every_name_belongs_to_an_entity(hass, bar, prod_entry) -> None:
    """The other direction: a name nothing uses is a key left behind."""
    translations = json.loads(EN.read_text())["entity"]
    made = {
        (e.domain, e.translation_key)
        for e in er.async_entries_for_config_entry(
            er.async_get(hass), prod_entry.entry_id
        )
    }
    named = {(domain, key) for domain, keys in translations.items() for key in keys}

    assert named == made


async def test_a_quick_session_switch_starts_what_the_quick_settings_say(
    hass, entity_id
) -> None:
    """
    The switch and the action share one way of starting a session, so both
    name the quick card and read the lengths kept beside them.
    """
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id("number", "quick_timer_simple"), "value": 20},
        blocking=True,
    )

    with patch("custom_components.busy.quick.timer.start", AsyncMock()) as started:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": entity_id("switch", "session_simple")},
            blocking=True,
        )

    _, kwargs = started.call_args
    assert kwargs["card_id"] == QUICK_CARD_ID
    assert kwargs["duration_ms"] == 20 * 60_000


async def test_a_refusal_from_the_bar_is_reported_not_swallowed(
    hass, entity_id
) -> None:
    with (
        patch(
            "custom_components.busy.quick.timer.start",
            AsyncMock(side_effect=BusyBarError("no")),
        ),
        pytest.raises(HomeAssistantError, match="no"),
    ):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": entity_id("switch", "session_infinite")},
            blocking=True,
        )


async def test_the_brightness_slider_writes_to_the_bar(hass, bar, entity_id) -> None:
    bar.display_brightness_set = AsyncMock()

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id("number", "brightness"), "value": 40},
        blocking=True,
    )

    bar.display_brightness_set.assert_awaited_once_with(40)


async def test_muting_remembers_nothing_it_was_not_told(hass, bar, entity_id) -> None:
    """A bar found silent has nothing to restore, so unmuting picks a middle level."""
    bar.audio_volume_set = AsyncMock()

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id("switch", "mute")}, blocking=True
    )

    bar.audio_volume_set.assert_awaited_once_with(50)
