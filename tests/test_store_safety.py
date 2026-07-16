"""模型下载、归档解包与并发发布的安全回归。"""
from __future__ import annotations

import concurrent.futures
import inspect
import io
import shutil
import stat
import tarfile
import tempfile
import threading
import time
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from asrkit import store
from asrkit.types import AdapterMeta


def _meta(model_id: str = "sherpa/safe", *, install_files=None) -> AdapterMeta:
    return AdapterMeta(
        id=model_id,
        provider="sherpa-onnx",
        vendor="sherpa",
        name=model_id,
        source="local",
        modes=["batch"],
        langs=["en"],
        download_url="https://example.invalid/model.tar.gz",
        install_files=list(install_files or []),
        cache_owner="asrkit",
    )


def _limits(**overrides) -> store.InstallLimits:
    values = {
        "max_download_bytes": 1024,
        "max_extracted_bytes": 1024,
        "max_members": 100,
        "max_member_bytes": 1024,
        "max_path_bytes": 1024,
    }
    values.update(overrides)
    return store.InstallLimits(**values)


def test_install_limit_defaults_are_frozen_and_bounded():
    limits = store.InstallLimits()
    assert limits == store.InstallLimits(
        max_download_bytes=8 << 30,
        max_extracted_bytes=16 << 30,
        max_members=20_000,
        max_member_bytes=8 << 30,
        max_path_bytes=1024,
    )
    with pytest.raises(FrozenInstanceError):
        limits.max_members = 1


class _Response:
    def __init__(self, body: bytes, content_length: str | None = None):
        self._body = io.BytesIO(body)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


@pytest.mark.parametrize("field", [
    "max_download_bytes",
    "max_extracted_bytes",
    "max_members",
    "max_member_bytes",
    "max_path_bytes",
])
def test_install_limits_require_positive_integers(field):
    values = _limits().__dict__.copy()
    values[field] = 0
    with pytest.raises(ValueError, match=field):
        store.InstallLimits(**values)
    values[field] = True
    with pytest.raises(ValueError, match=field):
        store.InstallLimits(**values)


def test_download_rejects_oversized_content_length_without_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store,
        "_open_download",
        lambda *args, **kwargs: _Response(b"abcd", "4"),
    )
    target = tmp_path / "archive"

    with store._download_limit(3):
        with pytest.raises(ValueError, match="Content-Length"):
            store._download("https://example.invalid/x", str(target), lambda *_: None)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_actual_bytes_without_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store,
        "_open_download",
        lambda *args, **kwargs: _Response(b"abcd"),
    )
    target = tmp_path / "archive"

    with store._download_limit(3):
        with pytest.raises(ValueError, match="download exceeds"):
            store._download("https://example.invalid/x", str(target), lambda *_: None)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("source", "target", "message"),
    [
        ("https://models.example/a", "ftp://mirror.example/a", "non-http"),
        ("https://models.example/a", "http://models.example/a", "downgrade"),
        ("https://models.example/a", "//user:secret@models.example/a", "credentials"),
    ],
)
def test_download_redirects_reapply_transport_policy(source, target, message):
    handler = store._SafeRedirectHandler()
    request = store.urllib.request.Request(source)

    with pytest.raises(ValueError, match=message):
        handler.redirect_request(request, None, 302, "Found", {}, target)


def test_download_redirect_allows_https_and_relative_targets():
    handler = store._SafeRedirectHandler()
    request = store.urllib.request.Request("https://models.example/path/a")

    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "../model.tar.gz")

    assert redirected.full_url == "https://models.example/model.tar.gz"


def _write_tar(path, members):
    with tarfile.open(path, "w") as tf:
        for member in members:
            if isinstance(member, tuple):
                name, data = member
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                tf.addfile(member)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "dir\\file"])
def test_tar_rejects_nonportable_or_escaping_paths(tmp_path, name):
    archive = tmp_path / "bad.tar"
    _write_tar(archive, [(name, b"x")])
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="unsafe|escapes|backslash|absolute"):
        store._extract_archive(str(archive), str(out), _limits())
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "device"])
def test_tar_rejects_special_members_before_writing(tmp_path, kind):
    archive = tmp_path / "bad.tar"
    info = tarfile.TarInfo("special")
    if kind == "symlink":
        info.type = tarfile.SYMTYPE
        info.linkname = "target"
    elif kind == "hardlink":
        info.type = tarfile.LNKTYPE
        info.linkname = "target"
    elif kind == "fifo":
        info.type = tarfile.FIFOTYPE
    else:
        info.type = tarfile.CHRTYPE
    _write_tar(archive, [info])
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="unsafe member"):
        store._extract_archive(str(archive), str(out), _limits())
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    ("members", "limits", "message"),
    [
        ([('a', b'x'), ('b', b'y')], {"max_members": 1}, "member count"),
        ([('a', b'xx')], {"max_member_bytes": 1}, "single-member"),
        ([('a', b'xx'), ('b', b'yy')], {"max_extracted_bytes": 3}, "extracted-size"),
        ([('long-name', b'x')], {"max_path_bytes": 4}, "path length"),
    ],
)
def test_tar_preflights_all_archive_budgets(tmp_path, members, limits, message):
    archive = tmp_path / "bad.tar"
    _write_tar(archive, members)
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match=message):
        store._extract_archive(str(archive), str(out), _limits(**limits))
    assert list(out.iterdir()) == []


def test_tar_rejects_normalized_duplicate_before_writing(tmp_path):
    archive = tmp_path / "bad.tar"
    _write_tar(archive, [("Model.onnx", b"a"), ("model.onnx", b"b")])
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="duplicate"):
        store._extract_archive(str(archive), str(out), _limits())
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    ["file.", "file ", "CON.onnx", "COM¹.txt", "bad:name", "bad?.onnx", "bad\x01.onnx"],
)
def test_archive_paths_reject_windows_aliases_and_invalid_names(name):
    with pytest.raises(ValueError, match="nonportable|reserved"):
        store._member_path(name, False, _limits())


def test_tar_rechecks_actual_member_size_while_streaming(tmp_path):
    class Member:
        name = "model.onnx"
        size = 1

        @staticmethod
        def isfile():
            return True

        @staticmethod
        def isdir():
            return False

    class FakeTar:
        def __iter__(self):
            return iter([Member()])

        @staticmethod
        def extractfile(member):
            return io.BytesIO(b"xx")

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="declared size"):
        store._safe_extract(FakeTar(), str(out), _limits())
    assert list(out.iterdir()) == []


def test_tar_applies_member_budget_before_reading_the_next_header(tmp_path):
    visited = []

    class Member:
        size = 0

        def __init__(self, index):
            self.name = f"{index}.onnx"

        @staticmethod
        def isfile():
            return True

        @staticmethod
        def isdir():
            return False

    class FakeTar:
        def __iter__(self):
            for index in range(10):
                visited.append(index)
                yield Member(index)

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="member count"):
        store._safe_extract(FakeTar(), str(out), _limits(max_members=2))
    assert visited == [0, 1, 2]
    assert list(out.iterdir()) == []


def test_tar_applies_declared_size_before_advancing_archive(tmp_path):
    class Member:
        name = "huge.onnx"
        size = 2

        @staticmethod
        def isfile():
            return True

        @staticmethod
        def isdir():
            return False

    class FakeTar:
        def __iter__(self):
            yield Member()
            raise AssertionError("oversized member must fail before advancing")

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="single-member"):
        store._safe_extract(
            FakeTar(), str(out), _limits(max_member_bytes=1))
    assert list(out.iterdir()) == []


def _zip_symlink(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def test_zip_rejects_symlink_before_writing(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_zip_symlink("link"), "target")
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="symlink"):
        store._extract_archive(str(archive), str(out), _limits())
    assert list(out.iterdir()) == []


def test_zip_rejects_non_symlink_special_member_before_writing(tmp_path):
    archive = tmp_path / "bad.zip"
    info = zipfile.ZipInfo("fifo")
    info.create_system = 3
    info.external_attr = (stat.S_IFIFO | 0o600) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, b"")
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="special member"):
        store._extract_archive(str(archive), str(out), _limits())
    assert list(out.iterdir()) == []


def test_zip_rejects_encrypted_flag_before_writing(tmp_path):
    class FakeZip:
        def infolist(self):
            info = zipfile.ZipInfo("secret")
            info.flag_bits = 1
            return [info]

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="encrypted"):
        store._safe_extract_zip(FakeZip(), str(out), _limits())
    assert list(out.iterdir()) == []


def test_zip_checks_member_count_before_copying_member_metadata(tmp_path):
    class ExplodingInfo:
        @property
        def flag_bits(self):
            raise AssertionError("oversized central directory must fail before inspection")

    class FakeZip:
        @staticmethod
        def infolist():
            return [ExplodingInfo(), ExplodingInfo()]

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="member count"):
        store._safe_extract_zip(FakeZip(), str(out), _limits(max_members=1))
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    ("sizes", "limits", "message"),
    [
        ([2], {"max_member_bytes": 1}, "single-member"),
        ([2, 2], {"max_extracted_bytes": 3}, "extracted-size"),
    ],
)
def test_zip_preflights_declared_size_budgets(tmp_path, sizes, limits, message):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for index, size in enumerate(sizes):
            zf.writestr(f"{index}.bin", b"x" * size)
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match=message):
        store._extract_archive(str(archive), str(out), _limits(**limits))
    assert list(out.iterdir()) == []


def test_zip_rechecks_actual_member_size_while_streaming(tmp_path):
    info = zipfile.ZipInfo("model.onnx")
    info.file_size = 1

    class FakeZip:
        @staticmethod
        def infolist():
            return [info]

        @staticmethod
        def open(member, mode):
            return io.BytesIO(b"xx")

    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="declared size"):
        store._safe_extract_zip(FakeZip(), str(out), _limits())
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    ("names", "limits", "message"),
    [
        (["../escape"], {}, "escapes"),
        (["dir\\file"], {}, "backslash"),
        (["A.onnx", "a.onnx"], {}, "duplicate"),
        (["a", "b"], {"max_members": 1}, "member count"),
        (["long-name"], {"max_path_bytes": 4}, "path length"),
    ],
)
def test_zip_preflights_paths_duplicates_and_budgets(tmp_path, names, limits, message):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in names:
            zf.writestr(name, b"x")
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match=message):
        store._extract_archive(str(archive), str(out), _limits(**limits))
    assert list(out.iterdir()) == []


def test_extractors_never_call_extractall():
    source = inspect.getsource(store._safe_extract) + inspect.getsource(store._safe_extract_zip)
    assert "extractall" not in source


def test_pull_serializes_same_destination_and_preserves_foreign_partial(
        tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    archive = tmp_path / "model.tar"
    _write_tar(archive, [("model.onnx", b"x")])
    meta = _meta()
    dest = root / "safe"
    root.mkdir()
    foreign_partial = root / "safe.partial"
    foreign_partial.mkdir()
    marker = foreign_partial / "owned-by-someone-else"
    marker.write_text("keep")
    calls = 0
    guard = threading.Lock()

    # 故意保留历史 3 参数 monkeypatch 签名，锁加固不能破坏既有扩展/测试。
    def fake_download(url, path, log):
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.05)
        shutil.copyfile(archive, path)

    monkeypatch.setattr(store, "_download", fake_download)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.pull(meta), range(2)))

    assert results == [str(dest), str(dest)]
    assert calls == 1
    assert (dest / "model.onnx").read_bytes() == b"x"
    assert marker.read_text() == "keep"
    assert not any(p.name.startswith(".asrkit-pull-") for p in root.iterdir())


def test_pull_failure_preserves_existing_target_and_cleans_private_work(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    dest = root / "safe"
    dest.mkdir(parents=True)
    marker = dest / "keep.txt"
    marker.write_text("keep")
    archive = tmp_path / "model.tar"
    _write_tar(archive, [("wrong.bin", b"x")])
    monkeypatch.setattr(store, "_download", lambda url, path, log: shutil.copyfile(archive, path))

    with pytest.raises(ValueError, match="incomplete.*refusing to replace"):
        store.pull(_meta(install_files=["required.bin"]))

    assert marker.read_text() == "keep"
    assert not (dest / "wrong.bin").exists()
    assert not any(p.name.startswith(".asrkit-pull-") for p in root.iterdir())


def test_install_file_patterns_cannot_escape_staging(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (tmp_path / "outside.onnx").write_bytes(b"outside")

    assert store._install_files_ok(
        _meta(install_files=["../outside.onnx"]), str(staging)) is False


def test_pull_keeps_valid_install_completed_by_another_process(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    archive = tmp_path / "model.tar"
    _write_tar(archive, [("model.onnx", b"ours")])
    dest = root / "safe"

    def concurrent_download(url, path, log):
        shutil.copyfile(archive, path)
        dest.mkdir(parents=True)
        (dest / "model.onnx").write_bytes(b"other-process")

    monkeypatch.setattr(store, "_download", concurrent_download)

    assert store.pull(_meta()) == str(dest)
    assert (dest / "model.onnx").read_bytes() == b"other-process"
    assert not any(p.name.startswith(".asrkit-pull-") for p in root.iterdir())


def test_publish_rollback_failure_preserves_previous_install_outside_work_dir(
        tmp_path, monkeypatch):
    dest = tmp_path / "model"
    staging = tmp_path / "staging"
    dest.mkdir()
    staging.mkdir()
    (dest / "old.onnx").write_bytes(b"old")
    (staging / "new.onnx").write_bytes(b"new")
    real_rename = store.os.rename

    def fail_publish_and_restore(source, target):
        if str(source) == str(staging):
            raise OSError("publish failed")
        if str(source).startswith(str(tmp_path / ".model.backup-")):
            raise OSError("restore failed")
        return real_rename(source, target)

    monkeypatch.setattr(store.os, "rename", fail_publish_and_restore)
    with pytest.raises(RuntimeError, match="preserved at"):
        store._publish_staging(str(staging), str(dest))

    backups = list(tmp_path.glob(".model.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "old.onnx").read_bytes() == b"old"


def test_pull_rejects_non_directory_destination_without_touching_it(tmp_path, monkeypatch):
    root = tmp_path / "models"
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    root.mkdir()
    dest = root / "safe"
    dest.write_text("keep")
    called = False

    def fake_download(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(store, "_download", fake_download)
    with pytest.raises(ValueError, match="not a directory"):
        store.pull(_meta())

    assert called is False
    assert dest.read_text() == "keep"


@pytest.mark.parametrize(
    "dangerous_root",
    [Path.home(), Path(tempfile.gettempdir()), Path.cwd(), Path(Path.cwd().anchor)],
)
def test_destructive_store_operations_reject_dangerous_roots(dangerous_root):
    with pytest.raises(ValueError, match="unsafe models root"):
        store.remove(_meta(), {"models_root": str(dangerous_root)})
    with pytest.raises(ValueError, match="unsafe models root"):
        store.pull(_meta(), {"models_root": str(dangerous_root)})


def test_pull_refuses_to_replace_unverified_existing_directory(tmp_path, monkeypatch):
    root = tmp_path / "models"
    dest = root / "safe"
    dest.mkdir(parents=True)
    marker = dest / "keep.txt"
    marker.write_text("unrelated")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    called = False

    def fake_download(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(store, "_download", fake_download)
    with pytest.raises(ValueError, match="incomplete.*refusing to replace"):
        store.pull(_meta())

    assert called is False
    assert marker.read_text() == "unrelated"


def test_remove_refuses_unverified_existing_directory(tmp_path, monkeypatch):
    root = tmp_path / "models"
    dest = root / "safe"
    dest.mkdir(parents=True)
    marker = dest / "keep.txt"
    marker.write_text("unrelated")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    with pytest.raises(ValueError, match="incomplete or unverified"):
        store.remove(_meta())

    assert marker.read_text() == "unrelated"
