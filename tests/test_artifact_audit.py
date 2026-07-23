"""wheel/sdist 发布物内容与归档结构的离线安全门。"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_audit():
    name = "asrkit_artifact_audit"
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT / "packaging" / "audit_artifacts.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def _valid_sdist_members(root: str = "asrkit-0.5.4") -> list[tuple[str, bytes]]:
    return [
        (f"{root}/pyproject.toml", b"[build-system]\n"),
        (f"{root}/README.en.md", b"readme\n"),
        (f"{root}/LICENSE", b"license\n"),
        (f"{root}/CHANGELOG.md", b"changes\n"),
        (f"{root}/PKG-INFO", b"Metadata-Version: 2.4\n"),
        (f"{root}/.gitignore", b"dist/\n"),
        (f"{root}/src/asrkit/__init__.py", b'__version__ = "0.5.4"\n'),
        (f"{root}/src/asrkit/py.typed", b""),
        (f"{root}/src/asrkit/daemon/security.py", b""),
    ]


def _write_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members:
            archive.writestr(name, content)


def _valid_wheel_members(
    package_init: bytes = b'__version__ = "0.5.4"\n',
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> list[tuple[str, bytes]]:
    metadata = "asrkit-0.5.4.dist-info"
    members = [
        ("asrkit/__init__.py", package_init),
        ("asrkit/py.typed", b""),
        ("asrkit/daemon/security.py", b""),
        (f"{metadata}/METADATA", b"Metadata-Version: 2.4\n"),
        (f"{metadata}/WHEEL", b"Wheel-Version: 1.0\n"),
        (f"{metadata}/entry_points.txt", b"[console_scripts]\n"),
        (f"{metadata}/licenses/LICENSE", b"license\n"),
        *extra_members,
    ]
    rows = []
    for name, content in members:
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        rows.append(f"{name},sha256={digest},{len(content)}")
    record_path = f"{metadata}/RECORD"
    rows.append(f"{record_path},,")
    return [*members, (record_path, ("\n".join(rows) + "\n").encode())]


def test_valid_sdist_has_exact_public_manifest(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "asrkit-0.5.4.tar.gz"
    _write_tar(artifact, _valid_sdist_members())

    manifest = audit.audit_sdist(artifact)

    assert manifest.kind == "sdist"
    assert "src/asrkit/__init__.py" in manifest.files
    assert "AGENTS.md" not in manifest.files
    assert not any(path.startswith(("docs/", "tests/", "dist/")) for path in manifest.files)


@pytest.mark.parametrize(
    "member",
    [
        "/absolute/file",
        "asrkit-0.5.4/../escape",
        r"asrkit-0.5.4\escape",
        "asrkit-0.5.4/AGENTS.md",
        "asrkit-0.5.4/CLAUDE.md",
        "asrkit-0.5.4/src/asrkit/bad.py.",
        "asrkit-0.5.4/src/asrkit/bad.py ",
        "asrkit-0.5.4/src/asrkit/bad:name.py",
        "asrkit-0.5.4/src/asrkit/CON.py",
        "asrkit-0.5.4/src/asrkit/control\x01.py",
        "asrkit-0.5.4/.omx/state.json",
        "asrkit-0.5.4/.omc/project-memory.json",
        "asrkit-0.5.4/.superpowers/sdd/task.md",
        "asrkit-0.5.4/.env",
        "asrkit-0.5.4/signing-key.pem",
        "asrkit-0.5.4/tests/test_internal.py",
        "asrkit-0.5.4/docs/internal.md",
    ],
)
def test_sdist_rejects_unsafe_or_private_members(tmp_path, member):
    audit = _load_audit()
    artifact = tmp_path / "bad.tar.gz"
    _write_tar(artifact, [*_valid_sdist_members(), (member, b"private")])

    with pytest.raises(audit.ArtifactAuditError):
        audit.audit_sdist(artifact)


def test_sdist_rejects_normalized_duplicate_paths(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "duplicate.tar.gz"
    _write_tar(artifact, [
        *_valid_sdist_members(),
        ("asrkit-0.5.4/src/asrkit/./__init__.py", b"duplicate"),
    ])

    with pytest.raises(audit.ArtifactAuditError, match="duplicate"):
        audit.audit_sdist(artifact)


@pytest.mark.parametrize(
    "colliding_name",
    [
        "asrkit-0.5.4/src/asrkit/PY.TYPED",
        "asrkit-0.5.4/src/asrkit/cafe\N{COMBINING ACUTE ACCENT}.py",
    ],
)
def test_sdist_rejects_cross_platform_path_collisions(tmp_path, colliding_name):
    audit = _load_audit()
    artifact = tmp_path / "collision.tar.gz"
    members = _valid_sdist_members()
    if "cafe" in colliding_name:
        members.append(("asrkit-0.5.4/src/asrkit/caf\N{LATIN SMALL LETTER E WITH ACUTE}.py", b"one"))
    _write_tar(artifact, [*members, (colliding_name, b"two")])

    with pytest.raises(audit.ArtifactAuditError, match="duplicate"):
        audit.audit_sdist(artifact)


def test_sdist_rejects_empty_private_directory(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "directory.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        for name, content in _valid_sdist_members():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        directory = tarfile.TarInfo("asrkit-0.5.4/tests")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)

    with pytest.raises(audit.ArtifactAuditError, match="directory is not allowed"):
        audit.audit_sdist(artifact)


@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_sdist_rejects_links_and_devices(tmp_path, member_type):
    audit = _load_audit()
    artifact = tmp_path / "special.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        for name, content in _valid_sdist_members():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        special = tarfile.TarInfo("asrkit-0.5.4/src/asrkit/special")
        special.type = member_type
        special.linkname = "../../outside"
        archive.addfile(special)

    with pytest.raises(audit.ArtifactAuditError, match="unsupported tar member"):
        audit.audit_sdist(artifact)


@pytest.mark.parametrize("missing", [
    "pyproject.toml",
    "README.en.md",
    "LICENSE",
    "CHANGELOG.md",
    "src/asrkit/__init__.py",
])
def test_sdist_requires_build_and_version_sources(tmp_path, missing):
    audit = _load_audit()
    artifact = tmp_path / "missing.tar.gz"
    members = [
        (name, content)
        for name, content in _valid_sdist_members()
        if not name.endswith(f"/{missing}")
    ]
    _write_tar(artifact, members)

    with pytest.raises(audit.ArtifactAuditError, match="missing required"):
        audit.audit_sdist(artifact)


def test_valid_wheel_contains_only_runtime_package_and_metadata(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "asrkit-0.5.4-py3-none-any.whl"
    _write_zip(artifact, _valid_wheel_members())

    manifest = audit.audit_wheel(artifact)

    assert manifest.kind == "wheel"
    assert "asrkit/__init__.py" in manifest.files
    assert all(
        path.startswith("asrkit/") or ".dist-info/" in path
        for path in manifest.files
    )


@pytest.mark.parametrize("name", ["asrkit/link", "asrkit/link/"])
def test_wheel_rejects_symlink_member(tmp_path, name):
    audit = _load_audit()
    artifact = tmp_path / "symlink.whl"
    _write_zip(artifact, _valid_wheel_members())
    with zipfile.ZipFile(artifact, "a") as archive:
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../outside")

    with pytest.raises(audit.ArtifactAuditError, match="unsupported zip member"):
        audit.audit_wheel(artifact)


def test_wheel_rejects_extra_top_level_content(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "extra.whl"
    _write_zip(artifact, [*_valid_wheel_members(), ("tests/internal.py", b"")])

    with pytest.raises(audit.ArtifactAuditError, match="wheel member is not allowed"):
        audit.audit_wheel(artifact)


def test_wheel_rejects_extra_top_level_directory(tmp_path):
    audit = _load_audit()
    artifact = tmp_path / "extra-directory.whl"
    _write_zip(artifact, _valid_wheel_members())
    with zipfile.ZipFile(artifact, "a") as archive:
        archive.writestr("tests/", b"")

    with pytest.raises(audit.ArtifactAuditError, match="directory is not allowed"):
        audit.audit_wheel(artifact)


def test_compare_wheel_contents_detects_contract_drift(tmp_path):
    audit = _load_audit()
    first = tmp_path / "first.whl"
    second = tmp_path / "second.whl"
    _write_zip(first, _valid_wheel_members())
    _write_zip(second, _valid_wheel_members())

    audit.compare_wheel_contents(first, second)

    _write_zip(second, _valid_wheel_members(
        extra_members=(("asrkit/extra.py", b""),)))
    with pytest.raises(audit.ArtifactAuditError, match="wheel manifests differ"):
        audit.compare_wheel_contents(first, second)


def test_wheel_record_and_compare_detect_payload_drift(tmp_path):
    audit = _load_audit()
    first = tmp_path / "first.whl"
    second = tmp_path / "second.whl"
    _write_zip(first, _valid_wheel_members(b"benign\n"))
    _write_zip(second, _valid_wheel_members(b"different\n"))

    with pytest.raises(audit.ArtifactAuditError, match="contents differ"):
        audit.compare_wheel_contents(first, second)

    stale_record_members = [
        (name, b"tampered after RECORD\n" if name == "asrkit/__init__.py" else content)
        for name, content in _valid_wheel_members(b"original\n")
    ]
    _write_zip(second, stale_record_members)
    with pytest.raises(audit.ArtifactAuditError, match="RECORD"):
        audit.audit_wheel(second)


def test_cli_audits_artifacts_and_compares_wheels(tmp_path, capsys):
    audit = _load_audit()
    sdist = tmp_path / "asrkit-0.5.4.tar.gz"
    first = tmp_path / "first.whl"
    second = tmp_path / "second.whl"
    _write_tar(sdist, _valid_sdist_members())
    _write_zip(first, _valid_wheel_members())
    _write_zip(second, _valid_wheel_members())

    assert audit.main([
        str(sdist), str(first), str(second),
        "--compare-wheels", str(first), str(second),
    ]) == 0

    output = capsys.readouterr().out
    assert "sdist" in output
    assert "wheel" in output
    assert "wheel manifests match" in output


def test_ci_builds_and_rebuilds_artifacts_without_build_isolation():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "python -m build --sdist --no-isolation" in workflow
    assert "python -m build --wheel --no-isolation" in workflow
    assert "packaging/audit_artifacts.py" in workflow
    assert "--no-build-isolation" in workflow
    assert "--compare-wheels" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("persist-credentials: false") == 3
