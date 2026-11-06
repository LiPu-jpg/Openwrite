#!/usr/bin/env python3
"""Build a byte-reproducible OpenWrite Core wheel from a git commit.

`uv build` embeds the build time in the dist-info ZIP entry timestamps, so two
builds of the same commit differ in bytes. This helper builds from a clean
worktree at the requested commit and rewrites the wheel with fixed ZIP metadata
(sorted entries, 1980-01-01 timestamps, stable permissions). The resulting
wheel is identical for the same commit and source tree.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def run(args: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def normalize(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zout:
        for info in sorted(zin.infolist(), key=lambda item: item.filename):
            data = zin.read(info.filename)
            entry = zipfile.ZipInfo(info.filename, date_time=FIXED_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            if info.filename.endswith("/"):
                entry.external_attr = (0o40755 << 16) | 0x10
            else:
                entry.external_attr = 0o644 << 16
            zout.writestr(entry, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True, type=Path, help="Core git repository")
    parser.add_argument("--ref", required=True, help="Commit/tag to build")
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    core = args.core.resolve()
    commit = run(["git", "rev-parse", args.ref], cwd=core)
    args.outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="openwrite-core-build-") as temporary:
        worktree = Path(temporary) / "tree"
        build_dir = Path(temporary) / "wheel"
        run(["git", "worktree", "add", "--detach", str(worktree), commit], cwd=core)
        try:
            run(["uv", "build", "--wheel", "--out-dir", str(build_dir)], cwd=worktree)
            built = next(build_dir.glob("openwrite-*.whl"))
            destination = args.outdir / built.name
            normalize(built, destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            print(
                f"commit={commit}\nwheel={destination}\nsha256={digest}",
            )
            return 0
        finally:
            run(["git", "worktree", "remove", "--force", str(worktree)], cwd=core)


if __name__ == "__main__":
    raise SystemExit(main())
