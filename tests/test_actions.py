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


# A theme the bar does not have ----------------------------------------------------


@pytest.mark.parametrize(
    ("action", "data"),
    [
        ("start_busy", {}),
        ("start_custom", {}),
        ("start_quick_infinite", {}),
        ("start_quick_simple", {"duration": 5}),
        ("start_quick_interval", {}),
    ],
)
async def test_every_start_refuses_a_theme_the_bar_has_not_got(
    act, started, action, data
) -> None:
    """
    The bar does not: it starts anyway, shows its default and reports the
    missing theme as the one it is running.
    """
    with pytest.raises(ServiceValidationError, match="has no theme called nope"):
        await act(action, theme="nope", **data)

    assert not started.called, "no session was started"


async def test_the_refusal_lists_the_themes_there_are(act) -> None:
    with pytest.raises(ServiceValidationError, match="dnd, meeting"):
        await act("start_busy", theme="nope")


@pytest.mark.parametrize("theme", ["meeting", "busy"])
async def test_a_theme_the_bar_has_starts_the_session(act, started, theme) -> None:
    """
    `busy` is the firmware's own and has no directory, so the bar does not
    list it - and it must stay allowed.
    """
    await act("start_busy", theme=theme)

    assert started.call_args.kwargs["theme"] == theme


async def test_no_theme_asks_for_nothing_to_check(act, started) -> None:
    await act("start_busy")

    assert started.call_args.kwargs["theme"] is None


async def test_a_stale_quick_theme_is_refused_too(act, started, hass) -> None:
    """
    The remembered theme of a quick session is the bar's to have: one deleted
    since is refused with the list, not started as the default.
    """
    entry = hass.config_entries.async_entries("busy")[0]
    entry.runtime_data.quick.themes["simple"] = "deleted-theme"

    with pytest.raises(ServiceValidationError, match="deleted-theme"):
        await act("start_quick_simple")
    assert not started.called


# Drawing on both displays ---------------------------------------------------------


async def test_a_drawing_on_each_display_needs_no_name_of_its_own(act, bar) -> None:
    """
    The bar keeps one id for the whole application, so one default name for
    both displays made the back refused while the front held a drawing.
    """
    await act("draw", text="F")
    await act("draw", text="B", display="back")

    ids = [payload.elements[0].id for payload in bar.drawn]
    assert ids == ["draw_front", "draw_back"]


async def test_drawing_again_on_one_display_still_replaces_it(act, bar) -> None:
    await act("draw", text="one")
    await act("draw", text="two")

    assert [p.elements[0].id for p in bar.drawn] == ["draw_front", "draw_front"]


async def test_a_name_that_was_asked_for_is_the_one_used(act, bar) -> None:
    await act("draw", text="x", display="back", name="on_air")

    assert bar.drawn[-1].elements[0].id == "on_air"


@pytest.mark.parametrize(
    ("action", "data", "message"),
    [
        ("draw", {"text": "x"}, "Could not change what the bar shows"),
        ("clear", {}, "Could not change what the bar shows"),
        ("play_sound", {"sound": "event"}, "Could not play the sound"),
        ("notify", {"line_1": "x"}, "Could not show the notification"),
    ],
)
async def test_a_failure_says_what_was_being_done(
    act, bar, action, data, message
) -> None:
    """
    A refused drawing was reported as "Could not show the notification".
    """
    error = BusyBarAPIError("Bad Request", status_code=400)
    bar.display_draw = AsyncMock(side_effect=error)
    bar.display_clear = AsyncMock(side_effect=error)
    bar.audio_play = AsyncMock(side_effect=error)
    with (
        patch(f"{ACTIONS}.notification.notify", AsyncMock(side_effect=error)),
        pytest.raises(HomeAssistantError, match=message),
    ):
        await act(action, **data)


# A notification replaces the last one ---------------------------------------------


def _ids(bar) -> list[str]:
    return [element.id for element in bar.drawn[-1].elements]


async def test_a_notification_takes_down_the_pieces_the_last_one_left_up(
    act, bar
) -> None:
    """
    The bar updates a drawing by element id, so a notification with no icon
    and no second line left the last one's icon and second line on screen
    under the new text.
    """
    await act("notify", line_1="AAAA", line_2="BBBB", icon="check")
    assert _ids(bar) == ["10", "11", "12"]

    await act("notify", line_1="CCCC")

    assert _ids(bar) == ["11"]
    # Background, icon and second line: whatever the new one did not draw.
    assert bar.cleared[-1] == ["0", "10", "12"]


async def test_a_full_notification_leaves_only_the_background_to_take_down(
    act, bar
) -> None:
    await act("notify", line_1="AAAA", line_2="BBBB", icon="check")

    assert bar.cleared == [["0"]]


async def test_a_notification_with_a_background_takes_down_nothing_it_drew(
    act, bar
) -> None:
    await act(
        "notify", line_1="A", line_2="B", icon="check", background_color=[0, 0, 80]
    )

    assert _ids(bar) == ["0", "10", "11", "12"]
    assert bar.cleared == [], "nothing was left over"


async def test_what_was_drawn_with_draw_is_not_a_notification_s_to_take_down(
    act, bar
) -> None:
    await act("draw", text="ON AIR", display="back", name="on_air")
    await act("notify", line_1="hello")

    assert bar.cleared == [["0", "10", "12"]]
    assert "on_air" not in bar.cleared[0]


async def test_a_notification_is_drawn_before_anything_is_taken_down(act, bar) -> None:
    """
    So the panel is never blank in between.
    """
    order: list[str] = []
    original_draw, original_clear = bar.display_draw, bar.display_clear

    async def draw(*args, **kwargs):
        order.append("draw")
        return await original_draw(*args, **kwargs)

    async def clear(**kwargs):
        order.append("clear")
        return await original_clear(**kwargs)

    bar.display_draw, bar.display_clear = draw, clear

    await act("notify", line_1="x")

    assert order == ["draw", "clear"]
