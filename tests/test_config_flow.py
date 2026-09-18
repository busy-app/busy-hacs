"""
Adding a bar: what the flow does with what it finds.

The cases here are the ones that cost real time to find out on hardware
- a bar announcing an address nobody can reach, a bar with its HTTP API
switched off, two bars where one was assumed, a bar that came back on a
different lease.
"""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest

from custom_components.busy.const import DOMAIN

from .conftest import (
    DEV_HOST,
    DEV_ID,
    DEV_NAME,
    PROD_HOST,
    PROD_ID,
    PROD_NAME,
    USB_HOST,
    FakeBar,
    make_device,
)


def announcement(
    device_id: str = PROD_ID,
    name: str = PROD_NAME,
    *,
    addresses: list[str] | None = None,
) -> ZeroconfServiceInfo:
    """
    What Home Assistant hands over when a bar announces itself.

    The instance name carries the identity and the TXT record the name,
    which is how the bar presents itself; both matter, because the flow
    builds its unique id from the first and its title from the second.
    """
    hosts = addresses if addresses is not None else [USB_HOST, PROD_HOST]
    return ZeroconfServiceInfo(
        ip_address=ip_address(hosts[0]),
        ip_addresses=[ip_address(host) for host in hosts],
        hostname=f"busybar-{device_id}.local.",
        name=f"busybar-{device_id}._http._tcp.local.",
        port=80,
        type="_http._tcp.local.",
        properties={"name": name},
    )


async def test_a_discovered_bar_is_added_at_an_address_we_can_reach(
    hass, busy_network, no_setup
) -> None:
    """
    A bar announces every address it has, including its own USB network -
    which answers only for the machine it is plugged into. The entry has
    to keep the other one.
    """
    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=announcement()
    )

    assert started["type"] is FlowResultType.FORM
    assert started["step_id"] == "zeroconf_confirm"

    confirmed = await hass.config_entries.flow.async_configure(started["flow_id"], {})
    await hass.async_block_till_done()

    assert confirmed["type"] is FlowResultType.CREATE_ENTRY
    assert confirmed["title"] == PROD_NAME
    assert confirmed["data"][CONF_HOST] == PROD_HOST
    assert confirmed["data"][CONF_DEVICE_ID] == PROD_ID
    assert confirmed["data"][CONF_TOKEN]


async def test_a_bar_with_its_http_api_off_is_refused_by_name(
    hass, bars, busy_network, no_setup
) -> None:
    """
    Such a bar keeps announcing itself, so it is found and offered, and
    then answers nothing. Asking for a password would be worse than
    useless: there is no door to try it on.
    """
    bars[PROD_HOST] = FakeBar(http_api=False)

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=announcement()
    )
    refused = await hass.config_entries.flow.async_configure(started["flow_id"], {})

    assert refused["type"] is FlowResultType.ABORT
    assert refused["reason"] == "http_api_disabled"


async def test_an_announcement_moves_a_configured_bar_to_its_new_address(
    hass, prod_entry, bars, discovered, busy_network, no_setup
) -> None:
    """
    A bar that came back on a different lease announces itself, and this
    is the moment its new address is known. Aborting without using it
    leaves the entry pointing at an address the bar no longer has.
    """
    prod_entry.add_to_hass(hass)
    moved_to = "192.168.50.77"
    bars.clear()
    bars[moved_to] = FakeBar(host=moved_to)

    aborted = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=announcement(addresses=[USB_HOST, moved_to]),
    )
    await hass.async_block_till_done()

    assert aborted["type"] is FlowResultType.ABORT
    assert aborted["reason"] == "already_configured"
    assert prod_entry.data[CONF_HOST] == moved_to


async def test_two_bars_are_offered_as_two(
    hass, bars, discovered, busy_network, no_setup
) -> None:
    """
    One bar hides every mistake that involves telling them apart, so the
    picker is shown even when a scan finds a single device - and with two
    it must offer both, and add the one chosen.
    """
    bars[DEV_HOST] = FakeBar(device_id=DEV_ID, name=DEV_NAME, host=DEV_HOST)
    discovered.append(make_device(DEV_ID, DEV_NAME, DEV_HOST, usb_host=None))

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert started["step_id"] == "select_device"
    offered = started["data_schema"]({"device": DEV_NAME})
    assert offered["device"] == DEV_NAME

    chosen = await hass.config_entries.flow.async_configure(
        started["flow_id"], {"device": DEV_NAME}
    )
    await hass.async_block_till_done()

    assert chosen["type"] is FlowResultType.CREATE_ENTRY
    assert chosen["title"] == DEV_NAME
    assert chosen["data"][CONF_DEVICE_ID] == DEV_ID
    assert chosen["data"][CONF_HOST] == DEV_HOST


async def test_a_bar_already_added_is_not_offered_again(
    hass, prod_entry, busy_network, no_setup
) -> None:
    """
    The flow a user starts and the one a discovery starts have to agree
    about identity, or an added bar keeps being offered as a new one.
    """
    prod_entry.add_to_hass(hass)

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert started["step_id"] == "select_device"
    chosen = await hass.config_entries.flow.async_configure(
        started["flow_id"], {"device": PROD_NAME}
    )

    assert chosen["type"] is FlowResultType.ABORT
    assert chosen["reason"] == "already_configured"


async def test_nothing_on_the_network_says_so(
    hass, discovered, busy_network, no_setup
) -> None:
    """
    An empty scan is an answer, not an error.
    """
    discovered.clear()

    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert started["type"] is FlowResultType.ABORT
    assert started["reason"] == "no_devices_found"


@pytest.mark.parametrize(
    ("announced", "expected"),
    [
        ([USB_HOST, PROD_HOST], PROD_HOST),
        ([PROD_HOST, USB_HOST], PROD_HOST),
        ([USB_HOST], USB_HOST),
    ],
)
async def test_the_usb_address_is_the_last_resort(
    hass, bars, busy_network, no_setup, announced, expected
) -> None:
    """
    Whatever order they arrive in, the address Home Assistant can reach
    wins - and a bar that announced nothing else is still better than
    nothing at all.
    """
    bars[USB_HOST] = FakeBar(host=USB_HOST)

    started = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=announcement(addresses=announced),
    )
    created = await hass.config_entries.flow.async_configure(started["flow_id"], {})
    await hass.async_block_till_done()

    assert created["data"][CONF_HOST] == expected
