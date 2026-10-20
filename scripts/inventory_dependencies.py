"""Inventory installed runtime dependencies and license-file evidence.

Run with Python 3.10+ and packaging installed. The inspected environment needs
BankParser and the selected extra; audit tools stay outside that environment.
Without --profile, inventory all profiles from an all-extra installation.
Example: python scripts/inventory_dependencies.py --python /venv/bin/python --output /tmp/inventory
Only runtime dependencies are selected, excluding unrelated dev/audit packages.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROFILES = ("base", "csv", "ofx", "camt", "alternative", "all")

COLLECT = r"""
import hashlib, json, os, platform, sys
from importlib import metadata
rows = []
for dist in metadata.distributions():
    files = []
    for path in dist.files or ():
        value = str(path)
        if any(word in value.lower() for word in ("license", "copying", "notice")):
            target = dist.locate_file(path)
            if target.is_file():
                files.append({"path": value, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    rows.append({"name": dist.metadata["Name"], "version": dist.version,
                 "requires": dist.requires or [], "license_expression": dist.metadata.get("License-Expression"),
                 "license_metadata": (dist.metadata.get("License") or "").splitlines()[:1],
                 "license_classifiers": [x for x in dist.metadata.get_all("Classifier", []) if x.startswith("License ::")],
                 "license_files": files})
version = sys.implementation.version
implementation_version = ".".join(str(x) for x in version[:3])
if version.releaselevel != "final":
    implementation_version += version.releaselevel[0] + str(version.serial)
environment = {
    "implementation_name": sys.implementation.name,
    "implementation_version": implementation_version,
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version().split(".")[:2]),
    "sys_platform": sys.platform,
}
print(json.dumps({"environment": environment, "packages": rows}))
"""


def inventory(data, *, profile=None):
    packages = {canonicalize_name(row["name"]): row for row in data["packages"]}
    project = packages["bankparser-runtime"]
    environment = data["environment"]
    profiles = {}
    requested = PROFILES if profile is None else (profile,)
    for current_profile in requested:
        extra = "" if current_profile == "base" else current_profile
        todo = []
        for value in project["requires"]:
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate(
                environment | {"extra": extra}
            ):
                todo.append(requirement)
        selected = {}
        while todo:
            requirement = todo.pop()
            if requirement.url:
                raise ValueError(
                    "Direct-URL dependencies need separate provenance review"
                )
            if requirement.extras:
                raise ValueError("Dependency extras need explicit marker handling")
            name = canonicalize_name(requirement.name)
            package = packages[name]
            if not requirement.specifier.contains(package["version"], prereleases=True):
                raise ValueError(
                    f"Installed {name}=={package['version']} violates {requirement}"
                )
            if name in selected:
                continue
            selected[name] = package["version"]
            for value in package["requires"]:
                child = Requirement(value)
                if child.marker is None or child.marker.evaluate(
                    environment | {"extra": ""}
                ):
                    todo.append(child)
        profiles[current_profile] = dict(sorted(selected.items()))
    names = sorted({name for packages in profiles.values() for name in packages})
    if "all" in profiles and any(
        set(packages) - set(profiles["all"]) for packages in profiles.values()
    ):
        raise ValueError(
            "all extra does not contain the complete runtime dependency union"
        )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_version": project["version"],
        "environment": environment,
        "profiles": profiles,
        "packages": [packages[name] for name in names],
        "scope": "Installed runtime package metadata and license-file hashes; native/component terms require manual review",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES)
    args = parser.parse_args()
    result = inventory(
        json.loads(subprocess.check_output([args.python, "-c", COLLECT], text=True)),
        profile=args.profile,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    for profile, packages in result["profiles"].items():
        (args.output / f"{profile}.txt").write_text(
            "".join(f"{name}=={version}\n" for name, version in packages.items())
        )
        print(f"{profile}: {len(packages)} runtime packages")


if __name__ == "__main__":
    main()
