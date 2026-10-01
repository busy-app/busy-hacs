"""
The package as shipped: manifest, quality scale, brand images, and the
strings a person reads. None of these needs a bar; each corresponds to a
way the integration was shipped broken at least once.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components/busy"


def test_strings_and_translations_agree() -> None:
    """
    Home Assistant reads one and its own tooling reads the other; a key in
    only one of them is a name that appears in some places and not others.
    """
    assert (COMPONENT / "strings.json").read_text() == (
        COMPONENT / "translations/en.json"
    ).read_text()


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
