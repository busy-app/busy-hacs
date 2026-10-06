"""
Actions: what an automation can ask of a bar, and what it hears back.

The bar keeps two cards, one per switch position, and their owner arranged
them. A quick session has to leave both exactly as they are - that is the
whole reason it carries its own settings - and it names a card outside both
positions so the BUSY app can show where it came from.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from busylib.exceptions import BusyBarAPIError
from busylib.features import timer
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.busy.quick import QUICK_CARD_ID

ACTIONS = "custom_components.busy.services.actions"


@pytest.fixture
def started():
    """Watch what the library is asked to start, without a bar to start it."""
    with patch(f"{ACTIONS}.timer.start", AsyncMock()) as start:
        yield start


@pytest.fixture
def notified():
    with patch(f"{ACTIONS}.notification.notify", AsyncMock()) as notify:
        yield notify


async def test_a_quick_session_names_a_card_outside_both_positions(
    act, started
) -> None:
    """
    Naming one of the bar's own two would put a session the app shows under
    a card whose settings it is not running - the one thing these starts
    exist to avoid.
    """
    await act("start_quick_simple", duration=45)

    _, kwargs = started.call_args
    assert kwargs["card_id"] == QUICK_CARD_ID
    assert kwargs["kind"] == "simple"
    assert kwargs["duration_ms"] == 45 * 60_000


async def test_a_quick_session_falls_back_to_the_quick_settings(act, started) -> None:
    await act("start_quick_interval", work=30)

    _, kwargs = started.call_args
    assert kwargs["duration_ms"] == 30 * 60_000
    assert kwargs["rest_ms"] == 5 * 60_000, "the rest is the entity's default"
    assert kwargs["cycles"] == 4


async def test_starting_a_card_names_the_slot_and_nothing_else(act, started) -> None:
    """
    Starting what a card describes is the one case that must not carry
    settings: whatever is on the card is what should run.
    """
    await act("start_busy")

    args, kwargs = started.call_args
    assert args[1] == "busy"
    assert not {"card_id", "kind", "duration_ms"} & kwargs.keys()


async def test_an_action_can_be_aimed_at_a_room(hass, bar, entity_id, started) -> None:
    """
    A target names devices, areas, labels or entities, and an automation
    uses whichever it has. Taking a device id alone made the most natural of
    them - "the bars in this room" - fail validation outright.
    """
    await hass.services.async_call(
        "busy",
        "start_quick_infinite",
        {ATTR_ENTITY_ID: entity_id("switch", "session_busy")},
        blocking=True,
    )

    assert started.called


async def test_a_bar_answers_with_what_it_can_show_and_play(act, prod_entry) -> None:
    """
    The icon, sound and theme fields take a name, and which names exist is
    a fact about one bar. A dropdown cannot know it; the bar can.
    """
    answer = await act("list_assets", response=True)

    catalogue = answer[prod_entry.title]
    assert list(answer) == [prod_entry.title]
    assert "clock_5x5" in catalogue["images"]
    assert "volume_change" in catalogue["sounds"]
    assert catalogue["themes"] == ["dnd", "meeting"]
    # Only what the firmware ships: the fake bar holds an upload too.
    assert "logo" not in catalogue["images"]


async def test_a_notification_can_size_its_two_lines_apart(act, notified) -> None:
    """
    A label over a detail is the common case, and it reads across a room
    only if the label is the bigger of the two.
    """
    await act(
        "notify",
        line_1="MEETING",
        line_2="until 15:30",
        line_1_font="bold",
        line_2_font="tiny",
    )

    _, kwargs = notified.call_args
    assert (kwargs["line_1_font"], kwargs["line_2_font"]) == ("bold", "tiny")


async def test_a_notification_with_no_icon_asks_for_none(act, notified) -> None:
    """Leaving the field out is how a notification has no icon."""
    await act("notify", line_1="Laundry")

    _, kwargs = notified.call_args
    assert kwargs["icon"] is None
    assert kwargs["sound"] is None


async def test_a_name_no_bar_has_says_what_this_one_has(act) -> None:
    """
    Nothing validates a typed name when an automation is saved, and the bar
    it will run against may not even be on yet. So the miss lands as a
    mistake in the automation, naming what is there, not as an unknown
    error out of the library.
    """
    with pytest.raises(ServiceValidationError, match="has no icon"):
        await act("notify", line_1="Deployed", icon="not_on_any_bar")


async def test_a_drawing_says_where_it_goes_and_survives_until_cleared(
    act, bar
) -> None:
    """
    The notification action arranges a panel; this one places one piece of
    text exactly, on either display, and a duration of zero leaves it there
    until something takes it down.
    """
    await act(
        "draw",
        text="ON AIR",
        display="back",
        font="bold",
        color=[255, 0, 0],
        align="center",
        duration=0,
        name="on_air",
        led_color=[255, 0, 0],
    )

    payload = bar.drawn[-1]
    element = payload.elements[0]
    assert (element.text, element.font, element.display) == ("ON AIR", "bold", "back")
    assert (element.align, element.id, element.timeout) == ("center", "on_air", 0)
    assert payload.led_notification_color is not None
    # Ordinary priority: shouting over other applications is asked for by name.
    assert payload.priority == 50


@pytest.mark.parametrize(
    ("session", "message"),
    [
        (False, "is showing something of its own"),
        (True, "is running a session"),
    ],
)
async def test_a_refused_drawing_says_why(
    act, bar, prod_entry, session, message
) -> None:
    """
    "Low priority" is true and useless: a running session refuses every
    drawing whatever its priority, while the bar's own screens give way to an
    interrupting one - and what to do about it differs.
    """
    bar.display_draw = AsyncMock(side_effect=BusyBarAPIError("busy", status_code=409))

    with (
        patch(f"{ACTIONS}.timer.timer_state") as state,
        pytest.raises(HomeAssistantError, match=message),
    ):
        state.return_value.is_running = session
        if session:
            prod_entry.runtime_data.data.snapshot.timer = object()
        await act("draw", text="hello")


async def test_pausing_with_nothing_running_is_a_mistake_in_the_automation(
    act,
) -> None:
    with (
        patch(
            f"{ACTIONS}.timer.set_paused",
            AsyncMock(side_effect=timer.TimerNotRunningError("no session")),
        ),
        pytest.raises(ServiceValidationError, match="no session"),
    ):
        await act("pause_session")
