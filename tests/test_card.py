"""
The dashboard card: a file of JavaScript that shares a contract with the
Python side, and that nothing else would notice breaking.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components/busy"


def test_the_card_is_shipped_and_parses() -> None:
    """
    The card is served from the integration rather than copied into
    `www/` by hand, so it arrives and updates with it. A card that fails
    to parse takes down every custom card on the dashboard, and the only
    sign is an empty page - so at least check it is there and balanced.
    """
    card = COMPONENT / "www/busy-bar-card.js"

    source = card.read_text()
    assert 'customElements.define("busy-bar-card"' in source
    assert source.count("{") == source.count("}")
    assert source.count("(") == source.count(")")


def test_what_the_card_asks_of_a_bar_is_what_a_bar_has() -> None:
    """
    The card finds entities by the tail of their unique id - "brightness",
    "session_busy" - which is a contract between two files that nothing
    else checks. Renaming an entity key on the Python side leaves a
    control that silently never appears.
    """
    source = (COMPONENT / "www/busy-bar-card.js").read_text()
    translations = json.loads((COMPONENT / "translations/en.json").read_text())
    known = {key for section in translations["entity"].values() for key in section}

    asked = set(
        re.findall(
            r'"(session_\w+|switch_position|screen|brightness|volume|ok|back|start|scroll_left|scroll_right)"',
            source,
        )
    )

    assert asked <= known, f"the card asks for what no bar has: {sorted(asked - known)}"


def test_the_card_finds_entities_the_way_the_frontend_allows() -> None:
    """
    A dashboard card sees the *display* entity registry, which carries an
    entity's translation key and not its unique id. Looking one up by
    unique id therefore finds nothing at all, and the card renders empty
    rows with no error anywhere - which is exactly how it was written the
    first time.
    """
    source = (COMPONENT / "www/busy-bar-card.js").read_text()

    assert "translation_key" in source
    assert "unique_id" not in source


def test_the_card_attaches_handlers_where_the_state_is_fresh() -> None:
    """
    The sliders are built once and updated on every change, so a handler
    attached in the building half closes over the `hass` of the first
    render and reads a state frozen at that moment. Both toggles shipped
    that way: they turned on and then never turned off, because the
    click always saw "off".
    """
    source = (COMPONENT / "www/busy-bar-card.js").read_text()

    built_once = source[source.index("if (!sliders.dataset.ready)") :]
    built_once = built_once[: built_once.index('sliders.dataset.ready = "1"')]

    assert "onclick" not in built_once
    assert "onchange" not in built_once


def test_the_card_waits_for_the_interface_before_it_registers() -> None:
    """
    A card defined the moment its file loads can run before Home Assistant's
    interface has started, and was reported to be named in the card picker and
    missing once added. It is registered when the interface exists - and
    anyway after a timeout, for a page that never defines one.

    Checked on the source: nothing at the top level of the file may define the
    element or announce the card, since that is exactly the early path.
    """
    source = (COMPONENT / "www/busy-bar-card.js").read_text()

    assert 'whenDefined("home-assistant")' in source
    assert "setTimeout" in source, (
        "a frontend that never defines it must not strand the card"
    )
    top_level = [line for line in source.splitlines() if line and not line[0].isspace()]
    assert not [
        line
        for line in top_level
        if line.startswith(("customElements.define", "window.customElements.define"))
        or "customCards.push" in line
    ], "defined or announced at load, before the interface"


def test_the_card_registers_only_once_however_often_the_file_loads() -> None:
    """
    The file can be loaded twice - a cached copy and a fresh one - and
    defining an element twice throws.
    """
    source = (COMPONENT / "www/busy-bar-card.js").read_text()

    assert 'if (!window.customElements.get("busy-bar-card"))' in source
    assert "window.customCards.some(" in source


def test_the_cards_version_moves_exactly_when_the_file_does(tmp_path: Path) -> None:
    """
    A browser serves the card it first downloaded until the address changes.
    A version number someone must remember to raise gets forgotten, and then
    everyone keeps the old card; a hash of the file cannot be forgotten.
    """
    from custom_components.busy.frontend import card_version

    card = tmp_path / "card.js"
    card.write_text("one")
    first = card_version(card)
    assert card_version(card) == first, "stable while the file is"

    card.write_text("two")
    assert card_version(card) != first

    assert re.fullmatch(r"[0-9a-f]{10}", first)
    assert card_version() == card_version(COMPONENT / "www/busy-bar-card.js")
