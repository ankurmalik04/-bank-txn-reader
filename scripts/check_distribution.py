"""Check release package contents/metadata and write checksums (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

POLICIES = {
    "docs/csv-onboarding.md",
    "docs/profile-evidence.md",
    "docs/conformance-plan.md",
    "examples/csv_onboarding.py",
    ".gitattributes",
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SUPPORT.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/dependency-audit.md",
    "corpus/PROVENANCE.md",
    "corpus/generate.py",
    "scripts/check_distribution.py",
    "scripts/check_install.py",
    "tests/ofx_cases.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(directory):
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    require(len(wheels) == len(sources) == 1, "Expect exactly one wheel and sdist")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_paths = [n for n in names if n.endswith(".dist-info/METADATA")]
        require(len(metadata_paths) == 1, "Missing/ambiguous wheel metadata")
        metadata = BytesParser().parsebytes(wheel.read(metadata_paths[0]))
        require("bankparser/py.typed" in names, "Wheel lacks type marker")
        require(
            any(n.endswith(".dist-info/licenses/LICENSE") for n in names),
            "Wheel lacks first-party license",
        )
        require(
            all(n.startswith(("bankparser/", "bankparser_runtime-")) for n in names),
            "Wheel includes content outside the package/metadata",
        )
    with tarfile.open(sources[0]) as source:
        members = source.getmembers()
        roots = {PurePosixPath(n.name).parts[0] for n in members}
        require(len(roots) == 1, "Source archive has multiple roots")
        root = roots.pop()
        names = {n.name for n in members}
        for member in members:
            path = PurePosixPath(member.name)
            require(
                not path.is_absolute() and ".." not in path.parts,
                "Unsafe source archive path",
            )
            require(
                member.isfile() or member.isdir(), "Non-regular source archive member"
            )
            require(
                ".git" not in path.parts
                and "/docs/reviews/" not in member.name
                and "/docs/code-review-" not in member.name,
                "Historical/private archive content in source distribution",
            )
        require(
            {f"{root}/{p}" for p in POLICIES} <= names,
            "Source archive lacks required policy/validation files",
        )
        stream = source.extractfile(f"{root}/PKG-INFO")
        require(stream is not None, "Source archive lacks metadata")
        source_metadata = BytesParser().parsebytes(stream.read())
    for key in ("Name", "Version", "Requires-Python", "License-Expression"):
        require(metadata[key] == source_metadata[key], f"Wheel/sdist disagree on {key}")
    require(metadata["Name"] == "bankparser-runtime", "Unexpected package name")
    require(metadata["Requires-Python"] == ">=3.10", "Unexpected Python requirement")
    require(metadata["License-Expression"] == "MIT", "Unexpected first-party license")
    require(
        sorted(metadata.get_all("Requires-Dist", []))
        == sorted(source_metadata.get_all("Requires-Dist", [])),
        "Wheel/sdist disagree on dependencies",
    )
    pins = [r for r in metadata.get_all("Requires-Dist", []) if r.startswith("lxml")]
    require(
        len(pins) == 4 and all("6.1.3" in r and "<7" in r for r in pins),
        "Optional lxml security floor is missing",
    )
    checksum = directory / "SHA256SUMS"
    checksum.write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in sorted(wheels + sources)
        ),
        encoding="utf-8",
    )
    print(f"Validated {metadata['Name']} {metadata['Version']}; wrote {checksum}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    check(parser.parse_args().directory)
