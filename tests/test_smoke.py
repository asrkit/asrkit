"""0.1.0 冒烟测试：不依赖 sherpa-onnx（CI 轻量），覆盖注册/寻址/安全/音频守卫。"""
import io
import tarfile

import pytest

import asrkit
from asrkit import audio, registry, store


def test_version():
    assert asrkit.__version__ == "0.4.0"


def test_list_models():
    metas = asrkit.list_models()
    ids = {m.id for m in metas}
    assert len(metas) >= 47
    assert "local/sensevoice" in ids
    assert "siliconflow/sensevoice" in ids
    assert "faster-whisper/tiny" in ids   # 第二个引擎已注册（可选,懒加载）
    assert "whispercpp/tiny" in ids       # 第三个引擎
    # 云端第 2 波：火山豆包（双版本）、阿里百炼、ElevenLabs、OpenAI whisper-1
    for cid in ("doubao/auc-1", "doubao/auc-2", "dashscope/qwen3-asr-flash",
                "dashscope/fun-asr-flash", "dashscope/qwen-omni-plus",
                "elevenlabs/scribe-v1", "openai/whisper-1", "siliconflow/telespeech"):
        assert cid in ids, cid


def test_doubao_dual_key_env_injection(monkeypatch):
    # 火山双密钥（app_key + access_key）环境变量兜底
    monkeypatch.setenv("DOUBAO_APP_KEY", "app-x")
    monkeypatch.setenv("DOUBAO_ACCESS_KEY", "acc-y")
    a = registry.make_adapter("doubao/auc-2")
    assert a.config.get("app_key") == "app-x"
    assert a.config.get("access_key") == "acc-y"
    assert a.is_configured()


def test_user_models(tmp_path, monkeypatch):
    # 用户自定义模型注册表（~/.asrkit/models.json）——sherpa 模型开放
    import json
    p = tmp_path / "models.json"
    p.write_text(json.dumps([{"id": "local/mytest", "config_type": "senseVoice",
                              "langs": ["zh"], "download_url": "http://x/y.tar.bz2"}]))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(p))
    registry._loaded = False   # 强制重载以吃到 env
    registry.load_builtin()
    m = registry.resolve("local/mytest")
    assert m.id == "local/mytest" and m.config_type == "senseVoice" and m.provider == "sherpa-onnx"


def test_add_model(tmp_path, monkeypatch):
    # asrkit add-model 写的注册表能被读回并解析
    from asrkit import usermodels
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(tmp_path / "models.json"))
    usermodels.add({"id": "local/added", "config_type": "senseVoice", "langs": ["zh"]})
    assert any(e["id"] == "local/added" for e in usermodels.load())
    registry._loaded = False
    registry.load_builtin()
    assert registry.resolve("local/added").config_type == "senseVoice"


def test_transformers_open_provider():
    # transformers 开放寻址：任意 HF id 都能解析
    m = registry.resolve("transformers/openai/whisper-tiny")
    assert m.provider == "transformers" and m.model == "openai/whisper-tiny"
    m2 = registry.resolve("transformers/some-org/some-model")
    assert m2.provider == "transformers" and m2.model == "some-org/some-model"


def test_resolve_and_alias():
    assert registry.resolve("local/sensevoice").id == "local/sensevoice"
    # Ollama 式精度寻址
    assert registry.resolve("local/sensevoice:fp32").id == "local/sensevoice-fp32"
    assert registry.resolve("local/sensevoice:int8").id == "local/sensevoice"
    # 裸名简写（省略 local/）
    assert registry.resolve("sensevoice").id == "local/sensevoice"
    assert registry.resolve("sensevoice:fp32").id == "local/sensevoice-fp32"


def test_unknown_model_raises():
    with pytest.raises(registry.ModelNotFoundError):
        registry.resolve("local/does-not-exist")


def test_safe_extract_rejects_traversal(tmp_path):
    p = tmp_path / "evil.tar.bz2"
    with tarfile.open(p, "w:bz2") as tf:
        info = tarfile.TarInfo("../evil.txt")
        data = b"x"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    with tarfile.open(p, "r:bz2") as tf:
        with pytest.raises(ValueError):
            store._safe_extract(tf, str(tmp_path / "out"))


def test_sha256_mismatch_rejected(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    with pytest.raises(ValueError):
        store._verify_sha256(str(f), "0" * 64, log=lambda *a: None)
    store._verify_sha256(str(f), "", log=lambda *a: None)  # 空 sha 跳过，不抛


def test_env_key_injection(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "env-k")
    a = registry.make_adapter("siliconflow/sensevoice")
    assert a.config.get("api_key") == "env-k"
    assert a.is_configured()


def test_audio_guard(tmp_path):
    sf = pytest.importorskip("soundfile")
    pytest.importorskip("soxr")
    import numpy as np
    p = tmp_path / "s.wav"
    sf.write(str(p), np.zeros((44100, 2), dtype="float32"), 44100)  # 44.1k 立体声
    # 默认守卫：格式不符 → 诚实报错
    with pytest.raises(audio.AudioFormatError):
        audio.load_samples(str(p), 16000, 1, convert=False)
    # opt-in convert：成功并转到 16k
    samples, sr = audio.load_samples(str(p), 16000, 1, convert=True)
    assert sr == 16000
    assert getattr(samples, "ndim", 1) == 1
