#!/usr/bin/env python3
"""Preview, install, or verify the local exam-revision skill (stdlib only)."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import stat
import sys


# Deliberately not a recursive copy. New runtime files must be reviewed and
# explicitly added; course inputs, examples, tests, and repository data stay out.
RUNTIME_FILES = (
    "SKILL.md",
    "LICENSE",
    "agents/openai.yaml",
    "requirements.txt",
    "references/input-handling.md",
    "references/output-contract.md",
    "references/install.md",
    "references/resume.md",
    "references/teaching-style.md",
    "scripts/extract_sources.py",
    "scripts/check_pack.py",
    "scripts/session.py",
    "scripts/install.py",
)
SKILL_LOCATION = Path(".agents") / "skills" / "exam-revision"


class InstallError(ValueError):
    """A safe, actionable installation failure."""


def _kind(path: Path) -> str | None:
    """Classify without following symlinks or Windows junction/reparse points."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise InstallError(f"Refusing a symbolic link or junction: {path}")
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    raise InstallError(f"Refusing a special filesystem entry: {path}")


def _root(path: Path | str, label: str) -> Path:
    # Resolve OS/user-provided ancestor aliases, but not a linked root itself.
    path = Path(os.path.abspath(Path(path).expanduser()))
    if _kind(path) != "directory":
        raise InstallError(f"{label} must be an existing directory: {path}")
    return path.resolve(strict=True)


def _check_parents(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts[:-1]:
        current /= part
        kind = _kind(current)
        if kind not in (None, "directory"):
            raise InstallError(f"Expected a directory, found a file: {current}")


def runtime_snapshot(source: Path | str) -> dict[str, bytes]:
    """Read only allowlisted, regular runtime files under the source root."""
    source = _root(source, "Repository")
    snapshot = {}
    for name in RUNTIME_FILES:
        relative = Path(name)
        _check_parents(source, relative)
        path = source / relative
        if _kind(path) != "file":
            raise InstallError(f"Required runtime file is missing: {path}")
        snapshot[name] = path.read_bytes()
    return snapshot


def _expected_directories(snapshot: dict[str, bytes]) -> set[str]:
    return {
        parent.as_posix()
        for name in snapshot
        for parent in Path(name).parents
        if parent != Path(".")
    }


def _compare(target: Path, snapshot: dict[str, bytes]) -> list[str]:
    """Return differences, including extra directories; never follow links."""
    actual_files = set()
    actual_directories = set()

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            name = path.relative_to(target).as_posix()
            kind = _kind(path)
            if kind == "directory":
                actual_directories.add(name)
                visit(path)
            elif kind == "file":
                actual_files.add(name)
            else:
                raise InstallError(f"Installation changed during inspection: {path}")

    visit(target)
    differences = [f"missing: {name}" for name in sorted(snapshot.keys() - actual_files)]
    differences += [f"extra: {name}" for name in sorted(actual_files - snapshot.keys())]
    differences += [
        f"extra directory: {name}"
        for name in sorted(actual_directories - _expected_directories(snapshot))
    ]
    for name in sorted(snapshot.keys() & actual_files):
        _check_parents(target, Path(name))
        if _kind(target / name) != "file":
            raise InstallError(f"Installation changed during inspection: {target / name}")
        if (target / name).read_bytes() != snapshot[name]:
            differences.append(f"modified: {name}")
    return differences


def install_skill(
    source: Path | str,
    project: Path | str,
    *,
    install: bool = False,
    verify: bool = False,
) -> tuple[str, Path, int]:
    """Return (preview/installed/identical, destination, count), without overwrite."""
    if install and verify:
        raise InstallError("Choose installation or verification, not both.")
    project = _root(project, "Project")
    snapshot = runtime_snapshot(source)
    target = project / SKILL_LOCATION
    _check_parents(project, SKILL_LOCATION)
    kind = _kind(target)
    if kind is not None:
        if kind != "directory":
            raise InstallError(f"Installation destination is not a directory: {target}")
        differences = _compare(target, snapshot)
        if differences:
            details = "\n  ".join(differences[:12])
            if len(differences) > 12:
                details += f"\n  ... and {len(differences) - 12} more differences"
            raise InstallError(
                f"Existing installation differs; nothing was changed: {target}\n"
                f"  {details}\n"
                "Review and back up that directory, then move it aside yourself "
                "before installing this version. There is no overwrite option."
            )
        return "identical", target, len(snapshot)
    if verify:
        raise InstallError(f"Skill is not installed: {target}")
    if not install:
        return "preview", target, len(snapshot)

    # mkdir(exist_ok=False) reserves the destination without replacing another
    # installation. Exclusive file creation never overwrites an existing file.
    # Do not recursively delete on failure: unexpected files may belong to others.
    try:
        current = project
        for part in SKILL_LOCATION.parts[:-1]:
            current /= part
            kind = _kind(current)
            if kind is None:
                current.mkdir()
            elif kind != "directory":
                raise InstallError(f"Expected a directory: {current}")
        _check_parents(project, SKILL_LOCATION)
        target.mkdir(exist_ok=False)
        for directory in sorted(_expected_directories(snapshot), key=lambda p: (p.count("/"), p)):
            _check_parents(project, SKILL_LOCATION / directory)
            (target / directory).mkdir(exist_ok=False)
        for name, contents in snapshot.items():
            _check_parents(project, SKILL_LOCATION / name)
            with (target / name).open("xb") as destination:
                destination.write(contents)
    except (OSError, InstallError) as error:
        raise InstallError(
            f"Installation stopped: {error}\n"
            f"No existing files were overwritten. An incomplete installation may "
            f"remain at {target}; inspect it before trying again."
        ) from error
    differences = _compare(target, snapshot)
    if differences:
        raise InstallError(f"Post-install verification failed at {target}: {differences}")
    return "installed", target, len(snapshot)


def check_dependencies() -> bool:
    """Report availability only. Never import pypdf, install packages, or connect."""
    python_ok = sys.version_info >= (3, 10)
    print(f"Python: {sys.version.split()[0]} ({'OK' if python_ok else 'requires 3.10+'})")
    try:
        available = importlib.util.find_spec("pypdf") is not None
        version = importlib.metadata.version("pypdf") if available else None
        major = int(version.split(".", 1)[0]) if version else None
        pdf_ok = major is not None and 5 <= major < 7
    except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
        version = "unknown"
        pdf_ok = False
    if pdf_ok:
        print(f"pypdf: {version} (OK)")
    else:
        print(f"pypdf: {version or 'not installed'} (PDF extraction needs pypdf>=5,<7)")
    print("DOCX/PPTX extraction and the pack checker use Python's standard library.")
    print("No packages were installed; no network or permission settings were changed.")
    return python_ok and pdf_ok


def main(argv: list[str] | None = None) -> int:
    # A Windows console/redirected stream can use a legacy code page even when
    # the filesystem supports Unicode. Do not fail after copying only because
    # a status message contains a character that the terminal cannot encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Existing project folder (default: current folder)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Copy the skill; without this flag the default is a read-only preview")
    action.add_argument("--verify", action="store_true", help="Check an installed copy against this repository, without writing")
    parser.add_argument("--check-deps", action="store_true", help="Check Python/pypdf only, or also check after --install/--verify; never installs packages")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.exit(1, "Python 3.10 or newer is required. No files were changed.\n")
    # Dependency-only checks must also work with third-party installers, whose
    # payload may include files outside our strict installation allowlist.
    if args.check_deps and not (args.install or args.verify):
        return 0 if check_dependencies() else 2
    try:
        status, target, count = install_skill(
            Path(__file__).resolve().parents[1], args.project,
            install=args.install, verify=args.verify,
        )
    except (InstallError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if status == "preview":
        print(f"Preview only: would copy {count} runtime files to {target}")
        print("No files were changed. Add --install to perform the installation.")
    elif status == "installed":
        print(f"Installed and verified {count} runtime files: {target}")
    else:
        print(f"Verified: {count} runtime files are identical. No changes needed: {target}")
    if args.check_deps and not check_dependencies():
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
