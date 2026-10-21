"""Export reviewed source content without Git history or historical archives.

Run from anywhere: python scripts/export_publication.py --output /tmp/export
The destination must not already exist. No source files are removed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "MANIFEST.in",
    "pyproject.toml",
    "SUPPORT.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
}
DOCS = {
    "docs/conformance-plan.md",
    "docs/api.md",
    "docs/compatibility.md",
    "docs/dependencies.md",
    "docs/dependency-audit.md",
}
SCRIPTS = {
    "scripts/export_publication.py",
    "scripts/inventory_dependencies.py",
    "scripts/check_distribution.py",
    "scripts/check_install.py",
}
TREE_SUFFIXES = {
    "src": {".py", ".typed"},
    "tests": {".py"},
    "corpus": {".py", ".md", ".json", ".mt940", ".xml", ".csv", ".ofx", ".qfx"},
    "examples": {".py", ".json"},
    ".github": {".yml", ".yaml"},
}


def selected(path):
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Unsafe repository path")
    return (
        path in ROOT_FILES
        or path in DOCS
        or path in SCRIPTS
        or (
            len(value.parts) > 2
            and value.parts[:2] == ("docs", "audits")
            and value.suffix in {".json", ".txt"}
        )
        or (
            len(value.parts) > 1
            and value.suffix in TREE_SUFFIXES.get(value.parts[0], set())
        )
    )


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    subprocess.run(
        [sys.executable, str(ROOT / "corpus/generate.py"), "--check"], check=True
    )
    tracked = git("ls-files", "-z").decode().split("\0")
    paths = sorted(path for path in tracked if path and selected(path))
    required = ROOT_FILES | DOCS | SCRIPTS | {"corpus/generate.py"}
    missing = required - set(paths)
    if missing:
        parser.error("Stage required export files first: " + ", ".join(sorted(missing)))
    # Read once so the directory, manifest and archive describe the same bytes.
    content = {}
    for path in paths:
        source = ROOT / path
        if source.resolve() != source or not source.is_file():
            parser.error("Export requires regular files: " + path)
        content[path] = source.read_bytes()
    args.output.mkdir(parents=True, exist_ok=False)
    source_dir = args.output / "bankparser-runtime"
    for path, data in content.items():
        target = source_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    archive = args.output / "bankparser-runtime-source.tar.gz"
    with (
        archive.open("wb") as stream,
        gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as compressed,
        tarfile.open(fileobj=compressed, mode="w") as tar,
    ):
        for path, data in content.items():
            info = tarfile.TarInfo("bankparser-runtime/" + path)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    manifest = {
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "working_tree_changed": bool(git("status", "--porcelain")),
        "git_history_included": False,
        "historical_review_archives_included": False,
        "excluded_tracked_paths": sorted(
            path for path in tracked if path and not selected(path)
        ),
        "files": [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in content.items()
        ],
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {len(content)} files to {source_dir}")
    print(f"Archive: {archive}")


if __name__ == "__main__":
    main()
