"""
What the tests need to pretend a bar is there.

These are integration tests in Home Assistant's sense: a real Home
Assistant instance, the real integration, and a fake bar at the seam
where the library would talk to hardware. That seam is deliberate - the
things worth testing here are the ones a bar cannot be asked to do on
demand, like moving to another address mid-session or having its HTTP
API switched off, and the ones that only go wrong when two bars exist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from busylib import types
from busylib.devices import BusyBarAddress, BusyBarAddressAffinity, BusyBarDevice
from busylib.exceptions import BusyBarRequestError
from busylib.features import DeviceSnapshot
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_TOKEN
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.busy.const import DOMAIN

# Two bars, because one bar hides every mistake that involves telling
# them apart. The identifiers are the shape the firmware uses: the Wi-Fi
# MAC without separators.
PROD_ID = "0cfa2200f7e4"
PROD_NAME = "tug's Prod Bar"
PROD_HOST = "192.168.50.15"

DEV_ID = "0cfa22201131"
DEV_NAME = "tug's Dev Bar"
DEV_HOST = "192.168.50.20"

# Every bar also answers on its own USB network, and announces it. That
# address is reachable only from the machine the bar is plugged into,
# which Home Assistant usually is not.
USB_HOST = "10.0.4.20"


def make_device(
    device_id: str = PROD_ID,
    name: str = PROD_NAME,
    host: str | None = PROD_HOST,
    *,
    usb_host: str | None = USB_HOST,
) -> BusyBarDevice:
    """
    A bar as discovery hands it over: named, with the addresses it has.
    """
    addresses = set()
    if usb_host:
        addresses.add(
            BusyBarAddress(
                ip_address=usb_host, affinity=BusyBarAddressAffinity.OVER_USB
            )
        )
    if host:
        addresses.add(
            BusyBarAddress(ip_address=host, affinity=BusyBarAddressAffinity.OVER_WIFI)
        )
    return BusyBarDevice(name=name, device_id=device_id, addresses=addresses)


class FakeBar:
    """
    A bar that answers, or refuses in one of the ways a real one does.

    Only the calls the integration makes on the way in: minting a token,
    proving it can be reached, and the handful of readings the first
    poll takes. Everything else is a MagicMock, so a test that reaches
    further fails loudly rather than silently passing.
    """

    def __init__(
        self,
        device_id: str = PROD_ID,
        name: str = PROD_NAME,
        host: str = PROD_HOST,
        *,
        http_api: bool = True,
    ) -> None:
        self.device_id = device_id
        self.bar_name = name
        self.host = host
        self.base_url = f"http://{host}"
        self.http_api = http_api
        self.closed = False

    def _refuse_if_off(self) -> None:
        if not self.http_api:
            # What a bar with its HTTP API switched off does: it keeps
            # announcing itself over mDNS and answers nothing.
            raise BusyBarRequestError(
                "All connection attempts failed",
                method="POST",
                path="/api/access/tokens",
            )

    async def access_token_mint(self, name: str) -> Any:
        self._refuse_if_off()
        return MagicMock(token=f"token-for-{self.device_id}", short_id="abcd")

    async def access(self) -> Any:
        self._refuse_if_off()
        return MagicMock()

    async def aclose(self) -> None:
        self.closed = True

    # What the poll asks for, answered with the library's own models
    # rather than mocks: an entity showing a mock is a test that passes
    # while Home Assistant cannot serialise its own state machine.
    async def name(self) -> types.DeviceNameResponse:
        self._refuse_if_off()
        return types.DeviceNameResponse(name=self.bar_name)

    async def smart_home_switch(self) -> Any:
        self._refuse_if_off()
        return MagicMock(state=False)

    async def display_brightness(self) -> types.DisplayBrightnessInfo:
        self._refuse_if_off()
        return types.DisplayBrightnessInfo(front="50", back="50")

    async def time_timezone_info(self) -> Any:
        self._refuse_if_off()
        return MagicMock(name_="Europe/Belgrade", name="Europe/Belgrade")

    async def update_status(self) -> types.UpdateStatus:
        self._refuse_if_off()
        return types.UpdateStatus(
            install=types.UpdateInstallStatus(action="none", event="none", status="ok"),
            check=types.UpdateCheckStatus(status="not_available", available_version=""),
        )

    async def update_autoupdate(self) -> Any:
        self._refuse_if_off()
        return MagicMock(enabled=False)

    async def busy_profile(self, slot: str) -> types.BusyProfile:
        self._refuse_if_off()
        return types.BusyProfile(
            sort_order=0,
            title=slot.upper(),
            id=f"00000000-0000-0000-0000-00000000000{'0' if slot == 'busy' else '2'}",
            timer_settings=types.BusyTimerSimpleSettings(
                type="SIMPLE", total_time_ms=25 * 60 * 1000
            ),
            busy_bar_settings=types.BusyBarSettings(
                theme="busy", show_work_phase_only=False, trigger_smart_home=True
            ),
            profile_timestamp_ms=1,
        )

    # A few assets, in both places a bar keeps them: what the firmware
    # shipped, and what an application uploaded.
    SHIPPED = {
        "/ext/apps_assets/shared/images": ["clock_5x5.image", "dt_coffee.image"],
        "/ext/apps_assets/shared/sounds": ["volume_change.snd"],
        "/ext/apps_assets/shared/fonts": ["busy_tiny.font"],
        "/ext/apps_assets/busy/animations": ["progress_busy_41x16.anim"],
    }
    THEMES = ["dnd", "meeting"]
    UPLOADS = {"home_assistant": ["logo.png"]}

    async def storage_list(self, path: str) -> types.StorageList:
        self._refuse_if_off()
        if path in self.SHIPPED:
            return types.StorageList(
                list=[
                    types.StorageFileElement(type="file", name=name, size=64)
                    for name in self.SHIPPED[path]
                ]
            )
        if path == "/ext/apps_assets/busy/themes":
            return types.StorageList(
                list=[
                    types.StorageDirElement(type="dir", name=name)
                    for name in self.THEMES
                ]
            )
        if path == "/ext/user_assets":
            return types.StorageList(
                list=[
                    types.StorageDirElement(type="dir", name=name)
                    for name in self.UPLOADS
                ]
            )
        application = path.removeprefix("/ext/user_assets/")
        if application in self.UPLOADS:
            return types.StorageList(
                list=[
                    types.StorageFileElement(type="file", name=name, size=64)
                    for name in self.UPLOADS[application]
                ]
            )
        return types.StorageList(list=[])

    async def stream_status_ws(self, **_: Any):
        # A stream that stays open and says nothing, which is what a bar
        # with nothing happening on it does.
        self._refuse_if_off()
        while True:
            await asyncio.sleep(3600)
            yield {}

    def __getattr__(self, item: str) -> Any:
        # Anything else a test happens to reach for.
        return AsyncMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """
    Load `custom_components.busy` at all. Home Assistant refuses to
    without this.
    """


@pytest.fixture
def bars() -> dict[str, FakeBar]:
    """
    The bars this test has, keyed by the address they answer at.
    """
    return {PROD_HOST: FakeBar()}


@pytest.fixture
def discovered() -> list[BusyBarDevice]:
    """
    What an mDNS scan finds. A test rewrites this to move a bar.
    """
    return [make_device()]


@pytest.fixture
def busy_network(
    bars: dict[str, FakeBar], discovered: list[BusyBarDevice]
) -> Iterator[None]:
    """
    Put the fake bars behind every way the integration reaches for one.

    Both the client the integration builds from a remembered address and
    the one a discovered device builds for itself end up here, so a test
    can say "this address answers and that one does not" and have both
    paths agree.
    """

    def client_for(host: str, **_: Any) -> FakeBar:
        bar = bars.get(str(host))
        if bar is None:
            # Nothing at that address: the same failure a wrong or stale
            # address gives.
            bar = FakeBar(host=str(host), http_api=False)
        return bar

    def client_from_device(self: BusyBarDevice, affinity=None, **kwargs: Any) -> Any:
        address = self.get_address(affinity)
        return None if address is None else client_for(address)

    with (
        patch("custom_components.busy.AsyncBusyBar", side_effect=client_for),
        patch.object(BusyBarDevice, "to_async_client", client_from_device),
        patch(
            "custom_components.busy.async_discover_busy",
            AsyncMock(side_effect=lambda hass: list(discovered)),
        ),
        patch(
            "custom_components.busy.config_flow.async_discover_busy",
            AsyncMock(side_effect=lambda hass: list(discovered)),
        ),
    ):
        yield


@pytest.fixture
def quiet_snapshot() -> Iterator[None]:
    """
    A bar with nothing happening on it, as the first poll sees it.

    Collecting a real snapshot means two dozen calls whose answers these
    tests do not care about; what they care about is that entities exist
    and can be driven.
    """
    with patch(
        "custom_components.busy.coordinator.collect_device_snapshot",
        AsyncMock(return_value=DeviceSnapshot(name=PROD_NAME)),
    ):
        yield


@pytest.fixture
def no_setup() -> Iterator[AsyncMock]:
    """
    Keep a flow test to the flow.

    Creating an entry otherwise starts the whole integration - poll,
    stream, entities - which is a different subject with its own tests.
    """
    with patch(
        "custom_components.busy.async_setup_entry", AsyncMock(return_value=True)
    ) as setup:
        yield setup


@pytest.fixture
def prod_entry() -> MockConfigEntry:
    """
    A bar already added, the way the flow leaves it.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title=PROD_NAME,
        unique_id=PROD_ID,
        data={
            CONF_DEVICE_ID: PROD_ID,
            CONF_TOKEN: "token-for-" + PROD_ID,
            CONF_HOST: PROD_HOST,
        },
    )
