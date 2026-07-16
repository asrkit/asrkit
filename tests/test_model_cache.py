"""模型运行时就绪与缓存所有权必须是两个独立契约。"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

import asrkit
from asrkit import api, cli, registry, store
from asrkit.adapters.local_sherpa import SherpaLocal
from asrkit.cli_commands.shared import emit_model_rows
from asrkit.types import AdapterMeta, BaseAdapter, ModelCacheState


def _meta(*, owner: str = "unknown", source: str = "local") -> AdapterMeta:
    return AdapterMeta(
        id=f"test/{owner}",
        provider="test",
        vendor="test",
        name="Test",
        source=source,
        modes=["batch"],
        langs=["en"],
        cache_owner=owner,
    )


def test_model_cache_state_is_immutable():
    state = ModelCacheState("asrkit", True, True, "/models/test", 4)

    with pytest.raises(FrozenInstanceError):
        state.cached = False  # type: ignore[misc]


def test_model_cache_state_is_a_top_level_public_type():
    assert asrkit.ModelCacheState is ModelCacheState


def test_asrkit_cache_state_and_remove_use_managed_store(monkeypatch):
    calls = []
    adapter = BaseAdapter(_meta(owner="asrkit"), {
        "models_root": "/managed",
        "model_dir": "/runtime-only",
    })
    monkeypatch.setattr(store, "is_installed", lambda meta, config: calls.append(
        ("installed", dict(config))) or True)
    monkeypatch.setattr(store, "model_dir", lambda meta, config: calls.append(
        ("location", dict(config))) or "/managed/asrkit")
    monkeypatch.setattr(store, "dir_size", lambda meta, config: calls.append(
        ("size", dict(config))) or 123)
    monkeypatch.setattr(store, "remove", lambda meta, config: calls.append(
        ("remove", dict(config))) or "/managed/asrkit")

    assert adapter.cache_state() == ModelCacheState(
        owner="asrkit",
        cached=True,
        removable=True,
        location="/managed/asrkit",
        size_bytes=123,
    )
    assert adapter.remove_cached_model() == "/managed/asrkit"
    assert all("model_dir" not in config for _, config in calls)
    assert all(config["models_root"] == "/managed" for _, config in calls)


@pytest.mark.parametrize("owner", ["engine", "unknown"])
def test_external_or_unknown_cache_is_never_inspected_or_removed(owner, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("ASRKit store must not be touched")

    monkeypatch.setattr(store, "is_installed", forbidden)
    monkeypatch.setattr(store, "model_dir", forbidden)
    monkeypatch.setattr(store, "dir_size", forbidden)
    monkeypatch.setattr(store, "remove", forbidden)
    adapter = BaseAdapter(_meta(owner=owner))

    assert adapter.cache_state() == ModelCacheState(
        owner=owner,
        cached=None,
        removable=False,
        location=None,
        size_bytes=None,
    )
    with pytest.raises(ValueError, match="will not remove"):
        adapter.remove_cached_model()


@pytest.mark.parametrize("owner", ["engine", "unknown"])
def test_sherpa_adapter_does_not_override_explicit_cache_ownership(owner, monkeypatch):
    meta = AdapterMeta(
        id=f"third-party/{owner}",
        provider="sherpa-onnx",
        vendor="third-party",
        name="Third-party Sherpa model",
        source="local",
        modes=["batch"],
        langs=["en"],
        cache_owner=owner,
    )
    monkeypatch.setattr(store, "remove", lambda *args, **kwargs: pytest.fail(
        "Sherpa must not override external or unknown cache ownership"))

    adapter = SherpaLocal(meta)
    with pytest.raises(ValueError, match="will not remove"):
        adapter.remove_cached_model()


def test_legacy_size_fields_remain_empty_when_runtime_is_not_installed(
    monkeypatch, capsys,
):
    meta = _meta(owner="asrkit")
    monkeypatch.setattr(
        "asrkit.cli_commands.shared.model_cache_state",
        lambda _meta: ModelCacheState("asrkit", False, True, "/models/test", 5),
    )

    assert emit_model_rows([(meta, False)], as_json=True) == 0
    assert json.loads(capsys.readouterr().out)[0]["size_bytes"] == 0

    assert emit_model_rows([(meta, False)], as_json=False) == 0
    assert "5 B" not in capsys.readouterr().out


def test_cloud_has_no_local_cache_and_cannot_be_removed(monkeypatch):
    monkeypatch.setattr(store, "remove", lambda *args, **kwargs: pytest.fail(
        "cloud removal must not touch the local store"))
    adapter = BaseAdapter(_meta(source="cloud"))

    assert adapter.cache_state() == ModelCacheState(
        owner="none",
        cached=False,
        removable=False,
        location=None,
        size_bytes=None,
    )
    with pytest.raises(ValueError, match="no local model cache"):
        adapter.remove_cached_model()


def test_builtin_model_cache_owners_are_explicit():
    expected = {
        "sherpa/whisper-tiny": "asrkit",
        "faster-whisper/tiny": "engine",
        "transformers/openai/whisper-tiny": "engine",
        "whispercpp/tiny": "engine",
        "openai/whisper-1": "none",
        "dashscope/qwen3-asr-flash": "none",
        "doubao/auc-2": "none",
        "elevenlabs/scribe-v1": "none",
    }

    assert {model: registry.resolve(model).cache_owner for model in expected} == expected

    builtin_providers = {
        "sherpa-onnx", "faster-whisper", "transformers", "whispercpp",
        "openai", "qwen", "qwen-omni", "funasr-flash", "doubao", "elevenlabs",
    }
    builtin_metas = [
        meta for meta in registry.list_metas()
        if meta.provider in builtin_providers
    ]
    assert len(builtin_metas) >= 71
    for meta in builtin_metas:
        if meta.source == "cloud":
            assert meta.cache_owner == "none", meta.id
        elif meta.provider == "sherpa-onnx":
            assert meta.cache_owner == "asrkit", meta.id
        else:
            assert meta.cache_owner == "engine", meta.id


def test_third_party_meta_defaults_to_unknown_owner():
    assert _meta().cache_owner == "unknown"


def test_api_remove_routes_through_adapter(monkeypatch):
    calls = []

    class _Adapter(BaseAdapter):
        def remove_cached_model(self):
            calls.append((self.meta.id, self.config))
            return "/managed/test"

    adapter = _Adapter(_meta(owner="asrkit"), {"models_root": "/managed"})
    monkeypatch.setattr(registry, "make_adapter", lambda model, config: adapter)
    monkeypatch.setattr(store, "remove", lambda *args, **kwargs: pytest.fail(
        "api.remove must not bypass the adapter"))

    assert api.remove("test/asrkit", config={"models_root": "/managed"}) == "/managed/test"
    assert calls == [("test/asrkit", {"models_root": "/managed"})]


def test_api_and_cli_refuse_engine_cache_without_store_deletion(monkeypatch, capsys):
    monkeypatch.setattr(store, "remove", lambda *args, **kwargs: pytest.fail(
        "engine-owned cache must not be deleted by ASRKit"))

    with pytest.raises(ValueError, match="managed by its engine"):
        api.remove("faster-whisper/tiny")

    assert cli.main(["rm", "faster-whisper/tiny"]) == 1
    assert "managed by its engine" in capsys.readouterr().err


def test_adapter_concurrency_defaults_serialized_and_cloud_opts_in():
    assert BaseAdapter(_meta()).supports_concurrent_calls() is False
    for model in (
        "openai/whisper-1",
        "dashscope/qwen3-asr-flash",
        "doubao/auc-2",
        "elevenlabs/scribe-v1",
    ):
        assert registry.make_adapter(model).supports_concurrent_calls() is True


@pytest.mark.parametrize(
    ("model", "attribute"),
    [
        ("sherpa/whisper-tiny", "_rec"),
        ("faster-whisper/tiny", "_model"),
        ("transformers/openai/whisper-tiny", "_pipe"),
        ("whispercpp/tiny", "_model"),
    ],
)
def test_local_adapter_close_releases_native_state(model, attribute):
    adapter = registry.make_adapter(model)
    setattr(adapter, attribute, object())

    adapter.close()

    assert getattr(adapter, attribute) is None
