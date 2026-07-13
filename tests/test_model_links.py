"""自定义模型外部目录软链的功能与安全边界。"""
from __future__ import annotations

import os

import pytest

from asrkit import api, cli, registry, store, usermodels
from asrkit.types import AdapterMeta


def _meta(model_id: str) -> AdapterMeta:
    return AdapterMeta(
        id=model_id,
        provider="sherpa-onnx",
        vendor="sherpa",
        name=model_id,
        source="local",
        modes=["batch"],
        langs=["en"],
    )


def _symlink_dir(source, dest) -> None:
    try:
        os.symlink(source, dest, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")


def test_managed_leaf_symlink_is_installed(tmp_path, monkeypatch):
    root = tmp_path / "models"
    source = tmp_path / "external"
    root.mkdir()
    source.mkdir()
    (source / "model.onnx").write_bytes(b"onnx")
    dest = root / "linked"
    _symlink_dir(source, dest)
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    meta = _meta("sherpa/linked")

    assert store.model_dir(meta) == str(dest)
    assert store.is_installed(meta)
    assert store.dir_size(meta) == 4


def test_remove_leaf_symlink_preserves_external_directory(tmp_path, monkeypatch):
    root = tmp_path / "models"
    source = tmp_path / "external"
    root.mkdir()
    source.mkdir()
    model_file = source / "model.onnx"
    model_file.write_bytes(b"onnx")
    dest = root / "linked"
    _symlink_dir(source, dest)
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    assert store.remove(_meta("sherpa/linked")) == str(dest)
    assert not os.path.lexists(dest)
    assert source.is_dir()
    assert model_file.read_bytes() == b"onnx"


def test_managed_model_dir_rejects_parent_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "models"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _symlink_dir(outside, root / "namespace")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    with pytest.raises(ValueError, match="escapes the models root"):
        store.model_dir(_meta("sherpa/namespace/model"))


@pytest.mark.parametrize(
    "model_id",
    ["sherpa/", "sherpa/.", "sherpa/nested/..", "sherpa/../escape", "sherpa/nested/../escape"],
)
def test_managed_model_dir_rejects_dotdot_segments(tmp_path, monkeypatch, model_id):
    root = tmp_path / "models"
    root.mkdir()
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    with pytest.raises(ValueError, match="escapes the models root"):
        store.model_dir(_meta(model_id))


def test_invalid_model_id_cannot_remove_models_root(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    with pytest.raises(ValueError, match="escapes the models root"):
        store.remove(_meta("sherpa/"))
    assert marker.read_text() == "keep"


def test_remove_ignores_runtime_model_dir_override(tmp_path):
    root = tmp_path / "models"
    managed = root / "linked"
    external = tmp_path / "external"
    managed.mkdir(parents=True)
    external.mkdir()
    external_marker = external / "keep.txt"
    external_marker.write_text("keep")
    meta = _meta("sherpa/linked")
    registry.register_model(meta)

    assert api.remove(meta.id, config={
        "models_root": str(root),
        "model_dir": str(external),
    }) == str(managed)
    assert not managed.exists()
    assert external_marker.read_text() == "keep"


def test_pull_rejects_runtime_model_dir_override(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep")

    with pytest.raises(ValueError, match="runtime-only"):
        store.pull(_meta("sherpa/linked"), {"model_dir": str(external)})
    assert marker.read_text() == "keep"


def test_remove_unlinks_dangling_leaf_symlink(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    dest = root / "dangling"
    _symlink_dir(tmp_path / "missing-target", dest)
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))

    assert store.remove(_meta("sherpa/dangling")) == str(dest)
    assert not os.path.lexists(dest)


def test_pull_refuses_incomplete_external_link_before_download(tmp_path, monkeypatch):
    root = tmp_path / "models"
    source = tmp_path / "external"
    root.mkdir()
    source.mkdir()
    dest = root / "incomplete"
    _symlink_dir(source, dest)
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    meta = _meta("sherpa/incomplete")
    meta.download_url = "https://example.invalid/model.tar.bz2"
    called = False

    def fake_download(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(store, "_download", fake_download)

    with pytest.raises(ValueError, match="incomplete external model directory"):
        store.pull(meta)
    assert called is False
    assert dest.is_symlink()
    assert source.is_dir()


@pytest.mark.parametrize("source_kind", ["missing", "file"])
def test_add_model_rejects_invalid_model_dir_without_registration(
        tmp_path, monkeypatch, capsys, source_kind):
    root = tmp_path / "models"
    registry_file = tmp_path / "models.json"
    source = tmp_path / "source"
    if source_kind == "file":
        source.write_bytes(b"not a directory")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(registry_file))

    rc = cli.main([
        "add-model", f"invalid-{source_kind}", "--arch", "senseVoice",
        "--model-dir", str(source),
    ])

    assert rc == 1
    assert "model directory" in capsys.readouterr().err.lower()
    assert usermodels.load() == []
    assert not os.path.lexists(root / f"invalid-{source_kind}")


def test_add_model_external_dir_end_to_end_and_safe_rm(tmp_path, monkeypatch, capsys):
    root = tmp_path / "models"
    registry_file = tmp_path / "models.json"
    source = tmp_path / "external"
    source.mkdir()
    model_file = source / "model.onnx"
    model_file.write_bytes(b"onnx")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(registry_file))

    rc = cli.main([
        "add-model", "linked-e2e", "--arch", "senseVoice",
        "--model-dir", str(source),
    ])
    assert rc == 0
    assert "linked local files" in capsys.readouterr().out
    assert any(item["id"] == "sherpa/linked-e2e" for item in usermodels.load())

    registry._loaded = False
    meta = registry.resolve("sherpa/linked-e2e")
    dest = root / "linked-e2e"
    assert dest.is_symlink()
    assert store.model_dir(meta) == str(dest)
    assert store.is_installed(meta)

    assert cli.main(["show", "sherpa/linked-e2e"]) == 0
    assert "installed:yes" in capsys.readouterr().out
    assert cli.main(["rm", "sherpa/linked-e2e"]) == 0
    assert "removed" in capsys.readouterr().out
    assert not os.path.lexists(dest)
    assert source.is_dir()
    assert model_file.read_bytes() == b"onnx"


def test_add_model_rejects_traversal_without_registry_entry(tmp_path, monkeypatch, capsys):
    root = tmp_path / "models"
    registry_file = tmp_path / "models.json"
    source = tmp_path / "external"
    source.mkdir()
    (source / "model.onnx").write_bytes(b"onnx")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(registry_file))

    rc = cli.main([
        "add-model", "sherpa/nested/../escape", "--arch", "senseVoice",
        "--model-dir", str(source),
    ])

    assert rc == 1
    assert "escapes the models root" in capsys.readouterr().err
    assert usermodels.load() == []
    assert not root.exists()


def test_add_model_rejects_source_containing_its_managed_link(tmp_path, monkeypatch, capsys):
    root = tmp_path / "models"
    registry_file = tmp_path / "models.json"
    root.mkdir()
    (root / "model.onnx").write_bytes(b"onnx")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(registry_file))

    rc = cli.main([
        "add-model", "sherpa/recursive/nested", "--arch", "senseVoice",
        "--model-dir", str(root),
    ])

    assert rc == 1
    assert "would contain its own managed link" in capsys.readouterr().err
    assert usermodels.load() == []
    assert not os.path.lexists(root / "recursive")


def test_add_model_rejects_invalid_id_without_model_dir(tmp_path, monkeypatch, capsys):
    root = tmp_path / "models"
    registry_file = tmp_path / "models.json"
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(registry_file))

    rc = cli.main(["add-model", "sherpa/.", "--arch", "senseVoice"])

    assert rc == 1
    assert "escapes the models root" in capsys.readouterr().err
    assert usermodels.load() == []


def test_cli_rm_reports_managed_path_rejection(tmp_path, monkeypatch, capsys):
    root = tmp_path / "models"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep")
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(root))
    registry.register_model(_meta("sherpa/bad/.."))

    assert cli.main(["rm", "sherpa/bad/.."]) == 1
    assert "escapes the models root" in capsys.readouterr().err
    assert marker.read_text() == "keep"
