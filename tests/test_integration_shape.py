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

def test_the_quality_scale_names_every_rule_of_its_tier() -> None:
    """
    The manifest claims a tier; this file is where that claim is either
    kept or admitted to. A rule missing from it is a rule nobody is
    tracking, which is how a claimed tier quietly stops being true.
    """
    bronze = {
        "action-setup",
        "appropriate-polling",
        "brands",
        "common-modules",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "docs-actions",
        "docs-conditions",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-removal-instructions",
        "docs-triggers",
        "entity-event-setup",
        "entity-unique-id",
        "has-entity-name",
        "runtime-data",
        "test-before-configure",
        "test-before-setup",
        "unique-config-entry",
    }

    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    scale = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text())["rules"]

    assert manifest["quality_scale"] == "bronze"
    assert set(scale) == bronze

    for rule, entry in scale.items():
        status = entry if isinstance(entry, str) else entry["status"]
        assert status in {"done", "todo", "exempt"}, rule
        if status != "done":
            # A rule that is not done has to say what is left, or the
            # file is a list of shrugs.
            assert isinstance(entry, dict) and entry.get("comment"), rule


def test_the_brand_images_are_the_sizes_brands_asks_for() -> None:
    """
    home-assistant/brands rejects anything else: icons are square 256 and
    512, and a logo's shortest side is 128-256 normal, 256-512 hDPI.
    """
    import struct

    def size(name: str) -> tuple[int, int]:
        data = (COMPONENT.parent.parent / "brand" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        return struct.unpack(">II", data[16:24])

    assert size("icon.png") == (256, 256)
    assert size("icon@2x.png") == (512, 512)
    for name in ("logo.png", "dark_logo.png"):
        assert 128 <= min(size(name)) <= 256, name
    for name in ("logo@2x.png", "dark_logo@2x.png"):
        assert 256 <= min(size(name)) <= 512, name
