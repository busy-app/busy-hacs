"""
The checks that caught real breakage while this was being written.

None of these needs a bar. They exist because each one corresponds to a
way the integration was shipped broken at least once: a platform whose
entity class had been deleted, an entity with no name because its
translation key was renamed on one side only, an action offered in the
UI that the schema refuses.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

import pytest
import yaml

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components/busy"
PLATFORMS = sorted(
    path for path in COMPONENT.glob("*.py") if "async_setup_entry" in path.read_text()
)


def _defined_names(tree: ast.AST) -> set[str]:
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef | ast.FunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in node.names}
        if isinstance(node, ast.Import):
            names |= {
                (alias.asname or alias.name).split(".")[0] for alias in node.names
            }
    return names


@pytest.mark.parametrize("path", PLATFORMS, ids=lambda path: path.name)
def test_every_class_a_platform_builds_exists(path: Path) -> None:
    """
    A platform that constructs a class which is not there fails at setup
    with a NameError and takes every entity of that platform with it.
    This has happened twice, both times from an edit that removed a class
    the file below still referred to.
    """
    tree = ast.parse(path.read_text())
    defined = _defined_names(tree)
    missing = sorted(
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id[:1].isupper()
        and node.func.id not in defined
    )

    assert not missing, f"{path.name} builds {missing}, which it does not have"


def test_every_entity_key_has_a_name() -> None:
    """
    An entity whose translation key is missing shows up as a blank row.
    Renaming a key on one side only is how that happens.
    """
    translations = json.loads((COMPONENT / "translations/en.json").read_text())
    known = {key for section in translations["entity"].values() for key in section}

    literal = re.compile(r'super\(\).__init__\(\s*coordinator,\s*name,\s*"([^"{}]+)"')
    templated = re.compile(r'super\(\).__init__\(\s*coordinator,\s*name,\s*f"([^"]+)"')

    missing: list[str] = []
    for path in COMPONENT.glob("*.py"):
        source = path.read_text()
        missing += [
            f"{path.name}: {key}" for key in literal.findall(source) if key not in known
        ]
        for template in templated.findall(source):
            # A templated key covers a family - session_{slot} is
            # session_busy and session_custom - so the family has to be
            # there, not the template.
            prefix = template.split("{")[0]
            if not any(key.startswith(prefix) for key in known):
                missing.append(f"{path.name}: {template}")

    assert not missing, f"entities without a name: {missing}"


def test_strings_and_translations_agree() -> None:
    """
    Home Assistant reads one and its own tooling reads the other; a key
    in only one of them is a name that appears in some places and not
    others.
    """
    strings = json.loads((COMPONENT / "strings.json").read_text())
    english = json.loads((COMPONENT / "translations/en.json").read_text())

    def keys(document: dict) -> set[str]:
        found = set()
        for section, entries in document.get("entity", {}).items():
            found |= {f"{section}.{key}" for key in entries}
        for name in document.get("services", {}):
            found.add(f"service.{name}")
        return found

    assert keys(strings) == keys(english)


def test_every_action_is_described() -> None:
    """
    An action with no description is one nobody can use from the UI
    without reading this repository.
    """
    offered = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    described = json.loads((COMPONENT / "strings.json").read_text())["services"]

    assert set(offered) == set(described)

    def named(body: dict) -> set[str]:
        """
        Every field of an action, including those inside a collapsible
        section - which services.yaml nests under the section's own name
        and the strings keep in a "sections" block beside the fields.
        """
        found = set()
        for key, spec in (body.get("fields") or {}).items():
            if isinstance(spec, dict) and "fields" in spec:
                found |= set(spec["fields"])
            else:
                found.add(key)
        for section in (body.get("sections") or {}).values():
            found |= set(section.get("fields") or {})
        return found

    for name, body in offered.items():
        assert named(body) == named(described[name]), name


def test_the_manifest_asks_for_the_library_it_uses() -> None:
    """
    The integration calls things that arrived in a particular release of
    busylib; a pin that predates them installs a version that cannot run
    it, and the failure lands at runtime as a missing attribute.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    requirement = next(r for r in manifest["requirements"] if "busylib" in r)

    assert ">=2.6" in requirement


def test_the_tests_run_against_the_library_the_manifest_asks_for() -> None:
    """
    Home Assistant installs what the manifest pins; these tests install
    what pyproject pins. When the two drift, the suite passes against a
    library nobody runs - which is how a release with new calls in it
    still came back red here.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    pinned = next(r for r in manifest["requirements"] if "busylib" in r)
    project = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    tested = next(
        line.strip().strip('",')
        for line in project.splitlines()
        if "busylib" in line and ">=" in line
    )

    def floor(requirement: str) -> str:
        return requirement.split(">=")[1].split(",")[0]

    assert floor(tested) == floor(pinned), f"{tested} against {pinned}"


def test_a_name_field_says_where_to_see_the_names() -> None:
    """
    Choosing an icon, a sound or a theme means typing a name, and a
    field with nothing but a blank box is a guess. Home Assistant
    forbids URLs in these strings - they go to translators - so what
    the description has to carry is the action that answers with the
    names this bar actually has.
    """
    described = json.loads((COMPONENT / "strings.json").read_text())["services"]

    missing = []
    for action, body in described.items():
        for field, spec in (body.get("fields") or {}).items():
            if field not in {"icon", "sound", "theme"}:
                continue
            if "List what a bar can show and play" not in spec.get("description", ""):
                missing.append(f"{action}.{field}")

    assert not missing, f"no way to see the choices from: {missing}"


def test_no_translation_carries_a_url() -> None:
    """
    hassfest refuses them: these strings are handed to translators, and
    a link is not theirs to keep current. The integration's own
    documentation link lives in the manifest, where it belongs.
    """
    for name in ("strings.json", "translations/en.json"):
        assert "https://" not in (COMPONENT / name).read_text(), name


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
    from custom_components.busy import card_version

    card = tmp_path / "card.js"
    card.write_text("one")
    first = card_version(card)
    assert card_version(card) == first, "stable while the file is"

    card.write_text("two")
    assert card_version(card) != first

    assert re.fullmatch(r"[0-9a-f]{10}", first)
    assert card_version() == card_version(COMPONENT / "www/busy-bar-card.js")
