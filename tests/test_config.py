"""0.4.2：配置持久化 —— keystore / 默认引擎 / 设置。"""
import os
import stat

import pytest

from asrkit import config, registry


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setenv("ASRKIT_CONFIG", str(p))
    return p


def test_set_get_creds_roundtrip(cfg_path):
    config.set_creds("dashscope", api_key="sk-secret-1234")
    assert config.get_creds("dashscope")["api_key"] == "sk-secret-1234"


def test_dual_key_creds(cfg_path):
    config.set_creds("doubao", app_key="A123", access_key="B456")
    c = config.get_creds("doubao")
    assert c["app_key"] == "A123" and c["access_key"] == "B456"


def test_file_perms_0600(cfg_path):
    config.set_creds("dashscope", api_key="x")
    mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
    assert mode == 0o600


def test_bare_filename_config_no_crash(tmp_path, monkeypatch):
    # 0.5.1：ASRKIT_CONFIG 为裸文件名时 save() 不应 makedirs("") 崩
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASRKIT_CONFIG", "cfg.json")
    config.set_creds("dashscope", api_key="k")
    assert config.get_creds("dashscope")["api_key"] == "k"


def test_mask():
    assert config.mask("sk-abcd1234") == "…1234"
    assert config.mask("ab") == "…"
    assert config.mask("") == ""


def test_keystore_feeds_make_adapter(cfg_path, monkeypatch):
    # 无显式 config、无 env → 从 keystore 取密钥
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    config.set_creds("siliconflow", api_key="stored-key")
    a = registry.make_adapter("siliconflow/sensevoice")
    assert a.config.get("api_key") == "stored-key"
    assert a.is_configured()


def test_explicit_config_beats_keystore(cfg_path):
    config.set_creds("siliconflow", api_key="stored-key")
    a = registry.make_adapter("siliconflow/sensevoice", {"api_key": "explicit"})
    assert a.config.get("api_key") == "explicit"


def test_env_beats_keystore(cfg_path, monkeypatch):
    config.set_creds("siliconflow", api_key="stored-key")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "env-key")
    a = registry.make_adapter("siliconflow/sensevoice")
    assert a.config.get("api_key") == "env-key"


def test_default_engine_changes_bare_resolution(cfg_path):
    # 缺省：裸名落到 sherpa
    registry._loaded = False
    assert registry.resolve("sensevoice").id == "sherpa/sensevoice"
    # 切默认引擎为 whispercpp 后，裸名落到 whispercpp/
    config.set_default("engine", "whispercpp")
    assert registry.resolve("tiny").id == "whispercpp/tiny"
    # 显式 sherpa/ 不受影响
    assert registry.resolve("sherpa/sensevoice").id == "sherpa/sensevoice"
    # 显式 local/ 别名仍解析同一 meta(向后兼容)
    assert registry.resolve("local/sensevoice").id == "sherpa/sensevoice"


def test_default_prefix_normalizes_legacy_engine_names(cfg_path, monkeypatch):
    # _default_prefix():eng 为 None/"sherpa-onnx"/"local"/"sherpa" 均归一到 "sherpa"
    from asrkit import registry as _registry
    for eng in (None, "sherpa-onnx", "local", "sherpa"):
        monkeypatch.setattr(config, "get_default", lambda key, _eng=eng: _eng)
        assert _registry._default_prefix() == "sherpa"
    monkeypatch.setattr(config, "get_default", lambda key: "faster-whisper")
    assert _registry._default_prefix() == "faster-whisper"
