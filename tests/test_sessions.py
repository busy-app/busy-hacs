"""
Starting a session: whose card it runs on, and what it must not write.

The bar keeps two cards, one per switch position, and their owner
arranged them. A quick session has to leave both exactly as they are -
that is the whole reason it carries its own settings - and it names a
card outside both positions so the BUSY app can show where it came from.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import ServiceValidationError
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
    # Every name is written the way a field takes it. Ours wins its bare
    # name; somebody else's carries the folder, which is both the only
    # way to ask for it and the sign that it is not ours.
    assert catalogue["images"]["yours"] == ["logo"]
    assert catalogue["images"]["other_apps"] == []


async def test_a_notification_can_size_its_two_lines_apart(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    A label over a detail is the common case, and it reads across a room
    only if the label is the bigger of the two.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.busy.services_setup.notification.notify", AsyncMock()
    ) as notified:
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "MEETING",
                "line_2": "until 15:30",
                "line_1_font": "bold",
                "line_2_font": "tiny",
            },
            blocking=True,
        )

    _, kwargs = notified.call_args
    assert (kwargs["line_1_font"], kwargs["line_2_font"]) == ("bold", "tiny")


async def test_a_notification_with_no_icon_asks_for_none(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    Leaving the field out is how a notification has no icon. There used
    to be a "none" in the list beside the real icons, which is the same
    nothing said twice.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.busy.services_setup.notification.notify", AsyncMock()
    ) as notified:
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {"device_id": _device_id(hass, prod_entry), "line_1": "Laundry"},
            blocking=True,
        )

    _, kwargs = notified.call_args
    assert kwargs["icon"] is None
    assert kwargs["sound"] is None


async def test_a_file_of_your_own_can_be_put_on_a_bar(
    hass, prod_entry, bars, busy_network, quiet_snapshot, tmp_path
) -> None:
    """
    The bar keeps each application's uploads apart and reaches only its
    own, so a picture uploaded by the BUSY app cannot be named from here.
    Putting it in this integration's folder is what makes it usable, and
    the answer says under which name.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    picture = tmp_path / "deploy_done.png"
    picture.write_bytes(b"not really a png")
    hass.config.allowlist_external_dirs = {str(tmp_path)}

    with patch(
        "custom_components.busy.services_setup.converter.convert_for_storage",
        return_value=("deploy_done.png", b"converted"),
    ):
        answer = await hass.services.async_call(
            DOMAIN,
            "upload_asset",
            {"device_id": _device_id(hass, prod_entry), "file": str(picture)},
            blocking=True,
            return_response=True,
        )

    assert answer[prod_entry.title]["name"] == "deploy_done"


async def test_a_file_home_assistant_may_not_read_is_refused(
    hass, prod_entry, bars, busy_network, quiet_snapshot, tmp_path
) -> None:
    """
    An integration reading any path it is handed is a way out of Home
    Assistant's own sandbox, so the allowlist decides - and says so
    rather than failing as a missing file.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    hass.config.allowlist_external_dirs = set()

    with pytest.raises(ServiceValidationError, match="not allowed to read"):
        await hass.services.async_call(
            DOMAIN,
            "upload_asset",
            {"device_id": _device_id(hass, prod_entry), "file": str(outside)},
            blocking=True,
        )


async def test_an_icon_somebody_else_uploaded_is_taken_over_and_used(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    The bar resolves an upload inside the folder of whichever application
    is drawing, so one made through the BUSY app or the Draw Tool is not
    Home Assistant's to draw. Asking a person to copy it themselves is
    the difference between "that icon is on the bar" and "that icon is on
    the bar, but not for you".
    """
    bar = FakeBar()
    bar.UPLOADS = {"draw_tool": ["my_logo.png"]}
    bars[PROD_HOST] = bar
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    copied: list[tuple[str, str]] = []

    async def copy(client, asset, application_name):
        copied.append((asset.application, application_name))
        bar.UPLOADS.setdefault(application_name, []).append(asset.reference)
        return replace(asset, application=application_name)

    with (
        patch("custom_components.busy.services_setup.assets.copy_to_application", copy),
        patch(
            "custom_components.busy.services_setup.notification.notify", AsyncMock()
        ) as notified,
    ):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "Deployed",
                "icon": "my_logo",
            },
            blocking=True,
        )

    assert copied == [("draw_tool", "home_assistant")]
    _, kwargs = notified.call_args
    assert kwargs["icon"].path == "my_logo.png"


async def test_a_name_no_bar_has_says_what_this_one_has(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    Nothing validates a typed name when an automation is saved - Home
    Assistant asks no integration about it, and the bar it will run
    against may not even be on yet. So the miss has to land as a
    mistake in the automation, naming what is there, rather than as an
    unknown error out of the library.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="has no icon"):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "Deployed",
                "icon": "not_on_any_bar",
            },
            blocking=True,
        )


async def test_a_folder_says_which_upload_of_a_name_is_meant(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    Two applications can each hold a file of one name, and a bare name
    then means whichever the bar answers with first. Writing the folder
    settles it, and is the form the catalogue lists an upload under.
    """
    bar = FakeBar()
    bar.UPLOADS = {"draw_tool": ["logo.png"], "pole_chudes": ["logo.png"]}
    bars[PROD_HOST] = bar
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    taken: list[str] = []

    async def copy(client, asset, application_name):
        taken.append(asset.application)
        bar.UPLOADS.setdefault(application_name, []).append(asset.reference)
        return replace(asset, application=application_name)

    with (
        patch("custom_components.busy.services_setup.assets.copy_to_application", copy),
        patch("custom_components.busy.services_setup.notification.notify", AsyncMock()),
    ):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "Deployed",
                "icon": "pole_chudes/logo",
            },
            blocking=True,
        )

    assert taken == ["pole_chudes"]


async def test_taking_a_file_never_writes_over_one_of_your_own(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    Copying happens on the way to drawing something, which is no moment
    to replace a file somebody put there deliberately. The name they
    meant may well be their own, so the error names both.
    """
    bar = FakeBar()
    bar.UPLOADS = {"draw_tool": ["logo.png"], "home_assistant": ["logo.png"]}
    bars[PROD_HOST] = bar
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="write over a file of your own"):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "Deployed",
                "icon": "draw_tool/logo",
            },
            blocking=True,
        )


async def test_an_upload_can_be_named_with_its_file_name(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    `draw_tool/logo.png` is what somebody sees on their own disk and in
    a listing of the bar's storage, so it is taken as readily as the
    name without the extension.
    """
    bar = FakeBar()
    bar.UPLOADS = {"draw_tool": ["logo.png"]}
    bars[PROD_HOST] = bar
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    async def copy(client, asset, application_name):
        bar.UPLOADS.setdefault(application_name, []).append(asset.reference)
        return replace(asset, application=application_name)

    with (
        patch("custom_components.busy.services_setup.assets.copy_to_application", copy),
        patch(
            "custom_components.busy.services_setup.notification.notify", AsyncMock()
        ) as notified,
    ):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "device_id": _device_id(hass, prod_entry),
                "line_1": "Deployed",
                "icon": "draw_tool/logo.png",
            },
            blocking=True,
        )

    _, kwargs = notified.call_args
    assert kwargs["icon"].path == "logo.png"
