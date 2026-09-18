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
    for name, body in offered.items():
        fields = set(body.get("fields") or {})
        # The notify action groups some fields behind a collapsible
        # section, which describes its contents one level up.
        if name == "notify":
            continue
        assert fields == set(described[name].get("fields") or {}), name


def test_the_manifest_asks_for_the_library_it_uses() -> None:
    """
    The integration calls things that arrived in a particular release of
    busylib; a pin that predates them installs a version that cannot run
    it, and the failure lands at runtime as a missing attribute.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    requirement = next(r for r in manifest["requirements"] if "busylib" in r)

    assert ">=2.6" in requirement


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
