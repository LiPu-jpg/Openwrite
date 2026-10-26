"""Bind full Core source tests to the exact wheel used by the plugin candidate."""

import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--restore-git-bytes", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(
        (args.plugin / "release/runtime-manifest.json").read_text(encoding="utf-8")
    )
    expected_commit = manifest["sources"]["core"]["commit"]
    actual_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.core, text=True
    ).strip()
    if actual_commit != expected_commit:
        raise ValueError("Core checkout differs from the wheel's pinned source commit")
    if args.restore_git_bytes:
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=args.core, text=True
        ).strip()
        if dirty:
            raise ValueError("Refusing to overwrite a modified Core checkout")
        # Git checkout filters can leave CRLF files even after changing
        # core.autocrlf. Archive extraction restores immutable object bytes.
        with tempfile.TemporaryFile() as source:
            subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.eol=lf",
                    "archive",
                    "--format=tar",
                    "HEAD",
                ],
                cwd=args.core,
                stdout=source,
                check=True,
            )
            source.seek(0)
            with tarfile.open(fileobj=source) as archive:
                archive.extractall(args.core, filter="data")
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=args.core, check=True)
    wheel = args.plugin / "release" / manifest["wheel"]["file"]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != manifest["wheel"]["sha256"]:
        raise ValueError("Core wheel SHA-256 differs from the runtime manifest")
    roots = {"tools", "models", "craft", "integrations"}
    checked = []
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Core wheel has duplicate entries")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Core wheel has an invalid path")
            if not name.endswith("/") and path.parts[0] in roots:
                source = args.core / name
                if not source.is_file() or archive.read(name) != source.read_bytes():
                    raise ValueError(f"Wheel source bytes differ: {name}")
                checked.append(name)
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Core wheel must have exactly one metadata record")
        version = Parser().parsestr(archive.read(metadata[0]).decode())["Version"]
        if version != manifest["core_version"]:
            raise ValueError("Core wheel version differs from the runtime manifest")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=args.core).decode().split("\0")
    expected_python = {
        name for name in tracked if name.endswith(".py") and PurePosixPath(name).parts[0] in roots
    }
    missing = sorted(expected_python - set(checked))
    if missing:
        raise ValueError(f"Core Python sources missing from wheel: {missing}")
    report = {
        "passed": True,
        "coreVersion": version,
        "coreCommit": actual_commit,
        "wheelSha256": digest,
        "sourceFilesCompared": len(checked),
        "pythonSourcesRequired": len(expected_python),
        "sourceRestoredFromGitArchive": args.restore_git_bytes,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
