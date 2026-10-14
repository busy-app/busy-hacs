"""
Pairing: what a bar's HTTP API setting means to the wizard, what happens when
the bar stops accepting the token, and what is left on the bar afterwards.

A bar's API is off, open or behind a key. Off still answers over HTTP - it
says so - so "did not answer" is not how to tell.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from busylib.exceptions import BusyBarAPIError, BusyBarError, BusyBarRequestError
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_USER,
    SOURCE_ZEROCONF,
    ConfigEntryState,
)
from homeassistant.const import CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.busy.const import DOMAIN

from .conftest import PROD_HOST, PROD_NAME, FakeBar
from .test_config_flow import announcement


async def _pick(hass, source=SOURCE_USER):
    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}
    )
    return await hass.config_entries.flow.async_configure(
        started["flow_id"], {"device": PROD_NAME}
    )


# Adding a bar ---------------------------------------------------------------------


async def test_a_bar_with_its_api_off_is_refused_by_name_not_asked_for_a_key(
    hass, bars, busy_network, no_setup
) -> None:
    """
    It answers HTTP, says `disabled`, and refuses minting with a 403 - which
    is exactly what "needs a key" looks like, so the form for a key that
    cannot work was shown instead.
    """
    bars[PROD_HOST] = FakeBar(mode="disabled")

    result = await _pick(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "http_api_disabled"


async def test_the_same_goes_for_a_bar_found_by_discovery(
    hass, bars, busy_network, no_setup
) -> None:
    bars[PROD_HOST] = FakeBar(mode="disabled")

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=announcement()
    )
    result = await hass.config_entries.flow.async_configure(started["flow_id"], {})

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "http_api_disabled",
    )


async def test_a_bar_behind_a_key_asks_for_it_and_says_when_it_is_wrong(
    hass, bars, busy_network, no_setup
) -> None:
    bars[PROD_HOST] = FakeBar(password="open sesame")

    asked = await _pick(hass)
    assert (asked["type"], asked["step_id"]) == (FlowResultType.FORM, "mint_token")
    assert not asked.get("errors")

    wrong = await hass.config_entries.flow.async_configure(
        asked["flow_id"], {"password": "not it"}
    )
    assert wrong["errors"] == {"base": "invalid_auth"}

    right = await hass.config_entries.flow.async_configure(
        wrong["flow_id"], {"password": "open sesame"}
    )
    assert right["type"] is FlowResultType.CREATE_ENTRY


async def test_an_open_bar_is_paired_without_a_question(
    hass, bars, busy_network, no_setup
) -> None:
    result = await _pick(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_token_says_which_home_assistant_it_is(
    hass, bars, busy_network, no_setup
) -> None:
    """
    The bar lists tokens on its own screen, to be deleted from there; "Home"
    alone is no help to someone with two of them.
    """
    hass.config.location_name = "Office"

    await _pick(hass)

    assert bars[PROD_HOST].minted == "HA Office"


# A token the bar stops accepting --------------------------------------------------


@pytest.fixture
def reset_bar(bars) -> FakeBar:
    """
    A bar that was reset and put behind a key: it knows no token of ours.
    """
    bar = FakeBar(password="open sesame")
    bar.valid_tokens = set()
    bars[PROD_HOST] = bar
    return bar


async def test_a_refused_token_asks_for_reauthentication_in_words(
    hass, prod_entry, reset_bar, busy_network
) -> None:
    prod_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    assert prod_entry.state is ConfigEntryState.SETUP_ERROR
    # "could not authenticate: None" was a message with no domain to look in.
    assert prod_entry.error_reason_translation_domain == DOMAIN
    assert prod_entry.error_reason_translation_key == "access_unauthorized"
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_the_key_pairs_it_again_and_keeps_everything_else(
    hass, prod_entry, reset_bar, busy_network
) -> None:
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()
    (flow,) = hass.config_entries.flow.async_progress()
    old = prod_entry.data[CONF_TOKEN]

    asked = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert (asked["type"], asked["step_id"]) == (FlowResultType.FORM, "reauth_confirm")
    wrong = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"password": "nope"}
    )
    assert wrong["errors"] == {"base": "invalid_auth"}

    reset_bar.valid_tokens = {"token-for-" + reset_bar.device_id}
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"password": "open sesame"}
    )
    await hass.async_block_till_done()

    assert (done["type"], done["reason"]) == (FlowResultType.ABORT, "reauth_successful")
    assert prod_entry.state is ConfigEntryState.LOADED
    assert (
        prod_entry.entry_id
        and prod_entry.data[CONF_TOKEN] == "token-for-" + reset_bar.device_id
    )
    assert old  # the entry was never replaced, only its token


async def test_a_bar_that_needs_no_key_is_paired_again_without_asking(
    hass, prod_entry, bars, busy_network
) -> None:
    bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    result = await prod_entry.start_reauth_flow(hass)
    await hass.async_block_till_done()

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "reauth_successful",
    )


async def test_reauthenticating_a_bar_whose_api_is_off_says_so(
    hass, prod_entry, bars, busy_network
) -> None:
    bar = bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    bar.mode = "disabled"

    result = await prod_entry.start_reauth_flow(hass)

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "http_api_disabled",
    )


async def test_a_bar_that_does_not_answer_is_waited_for_not_re_paired(
    hass, prod_entry, bars, busy_network
) -> None:
    """
    A bar that is off has not refused anything.
    """

    async def silent() -> None:
        raise BusyBarError("no route to host")

    bar = bars[PROD_HOST] = FakeBar()
    bar.access_tokens_list = silent  # type: ignore[method-assign]
    prod_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(prod_entry.entry_id)

    assert prod_entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.config_entries.flow.async_progress() == []


async def test_a_token_deleted_while_running_asks_for_reauthentication(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    """
    The poll's 403 is what a deletion on the bar looks like from here. Without
    this the entities went unavailable and nothing said why.
    """
    bar = bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()
    assert prod_entry.state is ConfigEntryState.LOADED

    refusals = [BusyBarAPIError("Forbidden", status_code=403)]

    async def refused() -> Any:
        # Once: after the new token the bar answers again.
        if refusals:
            raise refusals.pop()
        return MagicMock(state=False)

    # The token deleted, and the bar put behind a key: a new one needs it.
    bar.mode, bar.password, bar.valid_tokens = "key", "open sesame", set()
    bar.smart_home_switch = refused  # type: ignore[method-assign]
    await prod_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_any_other_error_from_the_poll_is_just_a_bar_that_is_unavailable(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    bar = bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()

    async def broken() -> None:
        raise BusyBarAPIError("Internal Server Error", status_code=500)

    bar.smart_home_switch = broken  # type: ignore[method-assign]
    await prod_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.config_entries.flow.async_progress() == []


# Taking the bar out ---------------------------------------------------------------


async def test_removing_the_bar_takes_home_assistant_s_token_off_it(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    bar = bars[PROD_HOST] = FakeBar()
    prod_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()
    token = prod_entry.data[CONF_TOKEN]

    await hass.config_entries.async_remove(prod_entry.entry_id)

    assert bar.revoked == [token[:8]]


async def test_a_bar_that_is_gone_does_not_stop_it_being_removed(
    hass, prod_entry, bars, busy_network, quiet_snapshot
) -> None:
    prod_entry.add_to_hass(hass)
    bars[PROD_HOST] = FakeBar()
    await hass.config_entries.async_setup(prod_entry.entry_id)
    await hass.async_block_till_done()
    bars[PROD_HOST].http_api = False

    await hass.config_entries.async_remove(prod_entry.entry_id)

    assert hass.config_entries.async_get_entry(prod_entry.entry_id) is None


# The corners of the wizard --------------------------------------------------------


async def test_firmware_that_cannot_say_its_mode_is_simply_asked_for_a_token(
    hass, bars, busy_network, no_setup
) -> None:
    bar = bars[PROD_HOST] = FakeBar()

    async def unknown() -> None:
        raise BusyBarAPIError("Not Found", status_code=404)

    bar.access = unknown  # type: ignore[method-assign]

    result = await _pick(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_bar_that_goes_quiet_between_the_two_questions_has_its_api_off(
    hass, bars, busy_network, no_setup
) -> None:
    bar = bars[PROD_HOST] = FakeBar()

    async def silent(name: str) -> None:
        raise BusyBarRequestError("no route", method="POST", path="/api/access/tokens")

    bar.access_token_mint = silent  # type: ignore[method-assign]

    result = await _pick(hass)

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "http_api_disabled",
    )


async def test_an_entry_with_no_address_to_pair_again_at_says_so(
    hass, prod_entry, bars, busy_network
) -> None:
    prod_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        prod_entry, data={k: v for k, v in prod_entry.data.items() if k != "host"}
    )

    result = await prod_entry.start_reauth_flow(hass)

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "cannot_connect",
    )
