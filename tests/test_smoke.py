"""0.1.0 冒烟测试：不依赖 sherpa-onnx（CI 轻量），覆盖注册/寻址/安全/音频守卫。"""
import io
import tarfile

import pytest

import asrkit
from asrkit import audio, registry, store


def test_version():
    assert asrkit.__version__ == "0.1.0"


def test_list_models():
    metas = asrkit.list_models()
    ids = {m.id for m in metas}
    assert len(metas) >= 47
    assert "local/sensevoice" in ids
    assert "siliconflow/sensevoice" in ids


def test_resolve_and_alias():
    assert registry.resolve("local/sensevoice").id == "local/sensevoice"
    # Ollama 式精度寻址
    assert registry.resolve("local/sensevoice:fp32").id == "local/sensevoice-fp32"
    assert registry.resolve("local/sensevoice:int8").id == "local/sensevoice"


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
