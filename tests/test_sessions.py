"""
Starting a session: whose card it runs on, and what it must not write.

The bar keeps two cards, one per switch position, and their owner
arranged them. A quick session has to leave both exactly as they are -
that is the whole reason it carries its own settings - and it names a
card outside both positions so the BUSY app can show where it came from.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import ATTR_ENTITY_ID
import pytest

from custom_components.busy.const import DOMAIN
from custom_components.busy.coordinator import QUICK_CARD_ID

from .conftest import PROD_HOST, FakeBar


@pytest.fixture
def started() -> AsyncMock:
    """
    Watch what the library is asked to start, without a bar to start it.
    """
    with (
        patch("custom_components.busy.switch.timer.start", AsyncMock()) as start,
        patch("custom_components.busy.button.timer.start", AsyncMock()),
    ):
        yield start


@pytest.fixture
def action_started() -> AsyncMock:
    with patch(
        "custom_components.busy.services_setup.timer.start", AsyncMock()
    ) as start:
        yield start


async def test_a_quick_session_names_a_card_outside_both_positions(
    hass, prod_entry, bars, busy_network, action_started
) -> None:
    """
    Naming one of the bar's own two would put a session the app shows
    under a card whose settings it is not running - and would be the one
    thing these starts exist to avoid.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "start_quick_simple",
        {"device_id": _device_id(hass, prod_entry), "duration": 45},
        blocking=True,
    )

    _, kwargs = action_started.call_args
    assert kwargs["card_id"] == QUICK_CARD_ID
    assert kwargs["kind"] == "simple"
    assert kwargs["duration_ms"] == 45 * 60_000


async def test_starting_a_card_names_the_slot_and_nothing_else(
    hass, prod_entry, bars, busy_network, action_started
) -> None:
    """
    Starting what a card describes is the one case that must not carry
    settings: whatever is on the card is what should run.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "start_busy",
        {"device_id": _device_id(hass, prod_entry)},
        blocking=True,
    )

    args, kwargs = action_started.call_args
    assert args[1] == "busy"
    assert kwargs.get("card_id") is None
    assert kwargs.get("kind") is None
    assert kwargs.get("duration_ms") is None


async def test_an_action_can_be_aimed_at_a_room(
    hass, prod_entry, bars, busy_network, action_started
) -> None:
    """
    A target names devices, areas, labels or entities, and an automation
    uses whichever it has. Taking a device id alone made the most natural
    of them - "the bars in this room" - fail validation outright.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = next(
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.startswith("switch.") and "session" in state.entity_id
    )

    await hass.services.async_call(
        DOMAIN,
        "start_quick_infinite",
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )

    assert action_started.called


def _device_id(hass, entry) -> str:
    """
    The Home Assistant device id for a bar, which is what a target takes.
    """
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    return devices[0].id


async def test_a_bar_answers_with_what_it_can_show_and_play(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    The icon, sound and theme fields take a name, and which names exist
    is a fact about one bar. A dropdown cannot know it; the bar can, and
    this is how a person reads the answer.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    answer = await hass.services.async_call(
        DOMAIN,
        "list_assets",
        {"device_id": _device_id(hass, prod_entry)},
        blocking=True,
        return_response=True,
    )

    catalogue = answer[prod_entry.title]

    assert list(answer) == [prod_entry.title]
    assert "clock_5x5" in catalogue["images"]["shipped"]
    assert "volume_change" in catalogue["sounds"]["shipped"]
    assert catalogue["themes"]["shipped"] == ["dnd", "meeting"]
    # Uploads are kept apart by the application that put them there: a
    # name is only usable by the application whose folder it is in.
    assert catalogue["images"]["uploaded"] == {"home_assistant": ["logo"]}
