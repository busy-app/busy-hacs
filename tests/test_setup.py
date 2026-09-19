"""
Setting a bar up: finding it again when it has moved, and keeping two
bars apart.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.busy.const import DOMAIN

from .conftest import (
    DEV_HOST,
    DEV_ID,
    DEV_NAME,
    PROD_HOST,
    PROD_ID,
    USB_HOST,
    FakeBar,
    make_device,
)


@pytest.fixture
def no_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Set the entry up without its entities.

    What these tests are about is which address the integration ends up
    talking to; the entities have their own subjects and their own fakes.
    """
    import custom_components.busy as integration

    monkeypatch.setattr(integration, "_PLATFORMS", [])


async def test_a_remembered_address_is_used_as_it_is(
    hass, prod_entry, busy_network, no_platforms
) -> None:
    """
    An address that answers is the whole setup: no ten-second scan for a
    bar that is exactly where it was left.
    """
    prod_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.LOADED
    assert prod_entry.data[CONF_HOST] == PROD_HOST


async def test_a_bar_that_moved_is_found_and_remembered(
    hass, prod_entry, bars, discovered, busy_network, no_platforms
) -> None:
    """
    A new lease changes the address and nothing else. The identity is the
    device id, so the bar is looked for by that and the entry is rewritten
    with where it actually is.
    """
    prod_entry.add_to_hass(hass)
    moved_to = "192.168.50.77"
    bars.clear()
    bars[moved_to] = FakeBar(host=moved_to)
    discovered[:] = [make_device(host=moved_to, usb_host=USB_HOST)]

    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.LOADED
    assert prod_entry.data[CONF_HOST] == moved_to


async def test_a_moved_bar_is_reached_over_the_network_not_over_usb(
    hass, prod_entry, bars, discovered, busy_network, no_platforms
) -> None:
    """
    A bar plugged into some other machine announces that machine's USB
    network as well. Reaching for it there is how a bar that is present
    and healthy looks unreachable.
    """
    prod_entry.add_to_hass(hass)
    moved_to = "192.168.50.77"
    bars.clear()
    # Only the network address answers - as it would from anywhere that
    # is not the machine the bar is plugged into.
    bars[moved_to] = FakeBar(host=moved_to)
    discovered[:] = [make_device(host=moved_to, usb_host=USB_HOST)]

    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.data[CONF_HOST] == moved_to


async def test_a_bar_that_is_not_there_is_retried_not_failed(
    hass, prod_entry, bars, discovered, busy_network, no_platforms
) -> None:
    """
    A bar switched off, or on another network, is a bar to wait for
    rather than a broken configuration: Home Assistant retries an entry
    left in this state on its own.
    """
    prod_entry.add_to_hass(hass)
    bars.clear()
    discovered.clear()

    assert not await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.SETUP_RETRY


async def test_two_bars_are_set_up_apart(
    hass, prod_entry, bars, discovered, busy_network, no_platforms
) -> None:
    """
    Two entries, two devices, two clients. The failure this guards
    against is one bar's address or token being used for the other.
    """
    dev_entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEV_NAME,
        unique_id=DEV_ID,
        data={
            CONF_DEVICE_ID: DEV_ID,
            CONF_TOKEN: f"token-for-{DEV_ID}",
            CONF_HOST: DEV_HOST,
        },
    )
    prod_entry.add_to_hass(hass)
    dev_entry.add_to_hass(hass)
    bars[DEV_HOST] = FakeBar(device_id=DEV_ID, name=DEV_NAME, host=DEV_HOST)
    discovered.append(make_device(DEV_ID, DEV_NAME, DEV_HOST, usb_host=None))

    # Setting one up loads the integration, which brings every entry of
    # its own with it - so this is both bars, not one.
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.LOADED
    assert dev_entry.state is ConfigEntryState.LOADED
    assert prod_entry.runtime_data.device_id == PROD_ID
    assert dev_entry.runtime_data.device_id == DEV_ID
    assert prod_entry.runtime_data.client.base_url.endswith(PROD_HOST)
    assert dev_entry.runtime_data.client.base_url.endswith(DEV_HOST)


async def test_one_bar_missing_does_not_take_the_other_down(
    hass, prod_entry, bars, discovered, busy_network, no_platforms
) -> None:
    """
    The dev bar being off is not the prod bar's problem.
    """
    dev_entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEV_NAME,
        unique_id=DEV_ID,
        data={
            CONF_DEVICE_ID: DEV_ID,
            CONF_TOKEN: f"token-for-{DEV_ID}",
            CONF_HOST: DEV_HOST,
        },
    )
    prod_entry.add_to_hass(hass)
    dev_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.LOADED
    assert dev_entry.state is ConfigEntryState.SETUP_RETRY


async def test_the_screen_does_not_write_a_row_for_every_frame(
    hass, prod_entry, bars, busy_network
) -> None:
    """
    The screen was an image entity, whose state is when its picture last
    changed - so a bar counting down wrote a state change a second, all
    day, watched or not. On a real installation that came to 96% of the
    recorder's database. A camera's state does not move: frames are
    handed out when something asks for one.
    """
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    screen = next(
        state for state in hass.states.async_all() if state.domain == "camera"
    )
    before = hass.states.get(screen.entity_id).last_updated

    coordinator = prod_entry.runtime_data
    for _ in range(50):
        coordinator._apply({"updates": [{"frame": {"display": "front"}}]})
    await hass.async_block_till_done()

    assert hass.states.get(screen.entity_id).last_updated == before
    assert not [s for s in hass.states.async_all() if s.domain == "image"]
