"""Audit inputs must describe the installed profile, not a new resolution."""

import runpy

import pytest

inventory = runpy.run_path("scripts/inventory_dependencies.py")["inventory"]


def package(name, version, requires=()):
    return {"name": name, "version": version, "requires": list(requires)}


@pytest.fixture
def installed():
    return {
        "environment": {"python_version": "3.12", "sys_platform": "win32"},
        "packages": [
            package(
                "bankparser-runtime", "0.5.0",
                [
                    "mt-940>=5.1.1,<6",
                    'ofxparse==0.21; extra == "ofx" or extra == "all"',
                    'backend==1.0; extra == "camt" or extra == "alternative" or extra == "all"',
                ],
            ),
            package("mt-940", "5.1.1"),
            package("ofxparse", "0.21", ['shared<2; python_version >= "3.12"']),
            package("shared", "1.5", ['windows-only==2; sys_platform == "win32"', 'linux-only; sys_platform == "linux"']),
            package("windows-only", "2"),
            package("backend", "1.0"),
            package("pytest", "9.1.1"),
        ],
    }


@pytest.mark.parametrize("profile", ["base", "csv"])
def test_lightweight_inventory_does_not_require_optional_packages(installed, profile):
    installed["packages"] = installed["packages"][:2]
    result = inventory(installed, profile=profile)
    assert result["profiles"] == {profile: {"mt-940": "5.1.1"}}
    assert [p["name"] for p in result["packages"]] == ["mt-940"]


def test_inventory_pins_actual_versions_and_evaluates_target_markers(installed):
    result = inventory(installed, profile="ofx")
    assert result["profiles"] == {
        "ofx": {"mt-940": "5.1.1", "ofxparse": "0.21", "shared": "1.5", "windows-only": "2"}
    }
    assert {p["name"] for p in result["packages"]} == set(result["profiles"]["ofx"])


def test_inventory_fails_when_selected_dependency_is_missing(installed):
    installed["packages"] = installed["packages"][:2]
    with pytest.raises(KeyError, match="ofxparse"):
        inventory(installed, profile="ofx")


def test_inventory_rejects_incompatible_installed_version(installed):
    installed["packages"][1]["version"] = "6.0"
    with pytest.raises(ValueError, match="violates"):
        inventory(installed, profile="base")


def test_all_inventory_contains_every_extra_without_audit_tools(installed):
    result = inventory(installed)
    assert result["profiles"]["csv"] == result["profiles"]["base"]
    assert result["profiles"]["camt"] == result["profiles"]["alternative"]
    assert set(result["profiles"]["all"]) == {"mt-940", "ofxparse", "shared", "windows-only", "backend"}
    assert "pytest" not in {p["name"] for p in result["packages"]}


def test_all_inventory_rejects_incomplete_all_extra(installed):
    project = installed["packages"][0]
    project["requires"] = [r.replace(' or extra == "all"', "") for r in project["requires"]]
    with pytest.raises(ValueError, match="complete runtime dependency union"):
        inventory(installed)
