#!/usr/bin/env python3
"""只读审计 ASRKit wheel/sdist 的路径、成员类型和发布清单。"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import os
import posixpath
import re
import stat
import sys
import tarfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union


_INTERNAL_PARTS = {".omx", ".omc", ".superpowers", "dist", "build"}
_SENSITIVE_NAMES = {
    ".env",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "pip.conf",
    "recovery-codes.txt",
    "secrets.json",
}
_SENSITIVE_SUFFIXES = (".key", ".p12", ".pem", ".pfx")
_SDIST_REQUIRED = {
    "CHANGELOG.md",
    "LICENSE",
    "PKG-INFO",
    "README.en.md",
    "pyproject.toml",
    "src/asrkit/__init__.py",
}
_SDIST_OPTIONAL_ROOT_FILES = {".gitignore"}
_DIST_INFO_RE = re.compile(r"^asrkit-[^/]+\.dist-info$")
_WINDOWS_DEVICES = {
    "aux", "con", "nul", "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
    "com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³",
}
_WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"|?*')


class ArtifactAuditError(ValueError):
    """发布物不满足安全结构或精确清单约束。"""


@dataclass(frozen=True)
class ArtifactManifest:
    kind: str
    files: frozenset[str]


def _canonicalize_archive_name(name: str) -> str:
    if not name or "\0" in name:
        raise ArtifactAuditError("archive member has an empty or invalid path")
    if "\\" in name:
        raise ArtifactAuditError(f"archive member uses a backslash path: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:/", name):
        raise ArtifactAuditError(f"archive member uses an absolute path: {name!r}")

    raw = name.rstrip("/")
    if not raw:
        raise ArtifactAuditError(f"archive member uses an invalid root path: {name!r}")
    if ".." in raw.split("/"):
        raise ArtifactAuditError(f"archive member escapes its root: {name!r}")
    for part in raw.split("/"):
        if part != "." and part.endswith((".", " ")):
            raise ArtifactAuditError(
                f"archive member has a Windows-ambiguous component: {name!r}")
        if any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN_CHARS for char in part):
            raise ArtifactAuditError(
                f"archive member has a Windows-invalid component: {name!r}")
        device_name = part.split(".", 1)[0].casefold()
        if device_name in _WINDOWS_DEVICES:
            raise ArtifactAuditError(
                f"archive member uses a reserved Windows device name: {name!r}")
    canonical = posixpath.normpath(raw)
    if canonical in ("", ".") or canonical.startswith("../"):
        raise ArtifactAuditError(f"archive member has an invalid path: {name!r}")
    return canonical


def _reject_private_path(canonical: str) -> None:
    parts = canonical.split("/")
    lowered = [part.lower() for part in parts]
    if "agents.md" in lowered or "claude.md" in lowered:
        raise ArtifactAuditError(f"internal instructions are forbidden: {canonical}")
    if any(part in _INTERNAL_PARTS for part in lowered):
        raise ArtifactAuditError(f"internal state/build path is forbidden: {canonical}")

    basename = lowered[-1]
    if (
        basename in _SENSITIVE_NAMES
        or basename.startswith(".env.")
        or basename.endswith(_SENSITIVE_SUFFIXES)
    ):
        raise ArtifactAuditError(f"sensitive-looking file is forbidden: {canonical}")


def _record_path(name: str, seen: set[str]) -> str:
    canonical = _canonicalize_archive_name(name)
    _reject_private_path(canonical)
    # 同时防守 Windows/macOS 常见的大小写与 Unicode 规范化碰撞。
    collision_key = unicodedata.normalize("NFC", canonical).casefold()
    if collision_key in seen:
        raise ArtifactAuditError(
            f"archive contains a duplicate normalized path: {canonical}")
    seen.add(collision_key)
    return canonical


def _tar_paths(path: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                canonical = _record_path(member.name, seen)
                if member.isdir():
                    directories.add(canonical)
                elif member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    files.add(canonical)
                else:
                    raise ArtifactAuditError(
                        f"unsupported tar member type: {member.name}")
    except ArtifactAuditError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ArtifactAuditError(f"cannot read sdist archive: {path}") from exc
    return files, directories


def _zip_paths(path: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                canonical = _record_path(member.filename, seen)
                if member.flag_bits & 0x1:
                    raise ArtifactAuditError(
                        f"encrypted zip member is forbidden: {member.filename}")

                unix_mode = member.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ArtifactAuditError(
                        f"unsupported zip member type: {member.filename}")
                if member.is_dir() or file_type == stat.S_IFDIR:
                    directories.add(canonical)
                else:
                    files.add(canonical)
    except ArtifactAuditError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArtifactAuditError(f"cannot read wheel archive: {path}") from exc
    return files, directories


def _single_sdist_root(paths: Iterable[str]) -> str:
    roots = {path.split("/", 1)[0] for path in paths}
    if len(roots) != 1:
        raise ArtifactAuditError("sdist must contain exactly one top-level directory")
    root = roots.pop()
    if not root.startswith("asrkit-"):
        raise ArtifactAuditError(f"unexpected sdist root directory: {root}")
    return root


ArtifactPath = Union[os.PathLike[str], str]


def audit_sdist(path: ArtifactPath) -> ArtifactManifest:
    artifact = Path(path)
    files, directories = _tar_paths(artifact)
    root = _single_sdist_root(files | directories)

    relative_files = {
        member[len(root) + 1:]
        for member in files
        if member != root and member.startswith(f"{root}/")
    }
    if len(relative_files) != len(files):
        raise ArtifactAuditError("sdist files must all live below its root directory")
    relative_directories = {
        member[len(root) + 1:]
        for member in directories
        if member != root and member.startswith(f"{root}/")
    }
    if len(relative_directories) != len(directories - {root}):
        raise ArtifactAuditError("sdist directories must all live below its root directory")

    missing = _SDIST_REQUIRED - relative_files
    if missing:
        raise ArtifactAuditError(
            "sdist is missing required files: " + ", ".join(sorted(missing)))

    allowed_root_files = _SDIST_REQUIRED | _SDIST_OPTIONAL_ROOT_FILES
    for member in relative_files:
        if "/" not in member and member not in allowed_root_files:
            raise ArtifactAuditError(f"sdist member is not allowed: {member}")
        if "/" in member and not member.startswith("src/asrkit/"):
            raise ArtifactAuditError(f"sdist member is not allowed: {member}")
    for member in relative_directories:
        if member not in ("src", "src/asrkit") and not member.startswith("src/asrkit/"):
            raise ArtifactAuditError(f"sdist directory is not allowed: {member}")

    return ArtifactManifest("sdist", frozenset(relative_files))


def audit_wheel(path: ArtifactPath) -> ArtifactManifest:
    artifact = Path(path)
    files, directories = _zip_paths(artifact)
    dist_info_roots = {
        member.split("/", 1)[0]
        for member in files
        if _DIST_INFO_RE.fullmatch(member.split("/", 1)[0])
    }
    if len(dist_info_roots) != 1:
        raise ArtifactAuditError("wheel must contain exactly one asrkit dist-info directory")
    dist_info = dist_info_roots.pop()

    for member in files:
        if not (
            member.startswith("asrkit/")
            or member.startswith(f"{dist_info}/")
        ):
            raise ArtifactAuditError(f"wheel member is not allowed: {member}")
    for member in directories:
        if not (
            member == "asrkit"
            or member.startswith("asrkit/")
            or member == dist_info
            or member.startswith(f"{dist_info}/")
        ):
            raise ArtifactAuditError(f"wheel directory is not allowed: {member}")

    required = {
        "asrkit/__init__.py",
        "asrkit/py.typed",
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        f"{dist_info}/entry_points.txt",
        f"{dist_info}/licenses/LICENSE",
        f"{dist_info}/RECORD",
    }
    missing = required - files
    if missing:
        raise ArtifactAuditError(
            "wheel is missing required files: " + ", ".join(sorted(missing)))
    _validate_wheel_record(artifact, files, f"{dist_info}/RECORD")
    return ArtifactManifest("wheel", frozenset(files))


def _zip_members_by_canonical_path(path: Path) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            canonical = _canonicalize_archive_name(member.filename)
            members[canonical] = member
    return members


def _member_sha256(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> bytes:
    digest = hashlib.sha256()
    with archive.open(member) as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.digest()


def _validate_wheel_record(path: Path, files: set[str], record_path: str) -> None:
    """验证 wheel RECORD 完整覆盖所有文件，且 sha256/字节数与实际内容一致。"""
    members = _zip_members_by_canonical_path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            record_bytes = archive.read(members[record_path])
            try:
                rows = csv.reader(record_bytes.decode("utf-8").splitlines())
            except UnicodeDecodeError as exc:
                raise ArtifactAuditError("wheel RECORD is not valid UTF-8") from exc

            recorded: set[str] = set()
            for row in rows:
                if len(row) != 3:
                    raise ArtifactAuditError("wheel RECORD contains a malformed row")
                member_path = _canonicalize_archive_name(row[0])
                if member_path in recorded or member_path not in files:
                    raise ArtifactAuditError(
                        f"wheel RECORD contains an invalid path: {member_path}")
                recorded.add(member_path)
                hash_field, size_field = row[1], row[2]
                if member_path == record_path:
                    if hash_field or size_field:
                        raise ArtifactAuditError("wheel RECORD must not hash itself")
                    continue
                if not hash_field.startswith("sha256=") or not size_field.isdigit():
                    raise ArtifactAuditError(
                        f"wheel RECORD lacks sha256/size for: {member_path}")
                member = members[member_path]
                expected_hash = base64.urlsafe_b64encode(
                    _member_sha256(archive, member)).rstrip(b"=").decode("ascii")
                if hash_field != f"sha256={expected_hash}" or int(size_field) != member.file_size:
                    raise ArtifactAuditError(
                        f"wheel RECORD does not match member content: {member_path}")
    except ArtifactAuditError:
        raise
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ArtifactAuditError("cannot validate wheel RECORD") from exc

    missing = files - recorded
    if missing:
        raise ArtifactAuditError(
            "wheel RECORD is missing files: " + ", ".join(sorted(missing)))


def _wheel_content_digests(path: Path, files: frozenset[str]) -> dict[str, str]:
    members = _zip_members_by_canonical_path(path)
    with zipfile.ZipFile(path) as archive:
        return {
            member_path: _member_sha256(archive, members[member_path]).hex()
            for member_path in files
        }


def audit_artifact(path: ArtifactPath) -> ArtifactManifest:
    artifact = Path(path)
    if artifact.suffix == ".whl":
        return audit_wheel(artifact)
    if artifact.name.endswith((".tar.gz", ".tgz")):
        return audit_sdist(artifact)
    raise ArtifactAuditError(f"unsupported artifact type: {artifact}")


def compare_wheel_contents(
    first: ArtifactPath,
    second: ArtifactPath,
) -> None:
    first_manifest = audit_wheel(first)
    second_manifest = audit_wheel(second)
    if first_manifest.files != second_manifest.files:
        only_first = sorted(first_manifest.files - second_manifest.files)
        only_second = sorted(second_manifest.files - first_manifest.files)
        details = []
        if only_first:
            details.append("only first: " + ", ".join(only_first))
        if only_second:
            details.append("only second: " + ", ".join(only_second))
        raise ArtifactAuditError("wheel manifests differ (" + "; ".join(details) + ")")
    first_digests = _wheel_content_digests(Path(first), first_manifest.files)
    second_digests = _wheel_content_digests(Path(second), second_manifest.files)
    changed = sorted(
        member for member in first_manifest.files
        if first_digests[member] != second_digests[member]
    )
    if changed:
        raise ArtifactAuditError(
            "wheel member contents differ: " + ", ".join(changed))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit ASRKit wheel and sdist contents without extracting them.",
    )
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument(
        "--compare-wheels",
        nargs=2,
        type=Path,
        metavar=("FIRST", "SECOND"),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not args.artifacts and not args.compare_wheels:
        print("Error: provide at least one artifact to audit", file=sys.stderr)
        return 2
    try:
        for artifact in args.artifacts:
            manifest = audit_artifact(artifact)
            print(f"OK {manifest.kind}: {artifact} ({len(manifest.files)} files)")
        if args.compare_wheels:
            compare_wheel_contents(*args.compare_wheels)
            print("OK: wheel manifests match")
    except ArtifactAuditError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
