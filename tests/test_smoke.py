"""0.1.0 冒烟测试：不依赖 sherpa-onnx（CI 轻量），覆盖注册/寻址/安全/音频守卫。"""
import io
import tarfile
from pathlib import Path

import pytest

import asrkit
from asrkit import audio, cli, registry, store


def test_version():
    assert asrkit.__version__ == "0.5.4"


def test_imports_current_source_checkout():
    expected = Path(__file__).resolve().parents[1] / "src" / "asrkit" / "__init__.py"
    assert Path(asrkit.__file__).resolve() == expected.resolve()


def test_list_models():
    metas = asrkit.list_models()
    ids = {m.id for m in metas}
    assert len(metas) >= 47
    assert "sherpa/sensevoice" in ids
    assert not any(i.startswith("local/") for i in ids)   # local/ 已正名为 sherpa/,不应再出现
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
    p.write_text(json.dumps([{"id": "sherpa/mytest", "config_type": "senseVoice",
                              "langs": ["zh"], "download_url": "http://x/y.tar.bz2"}]))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(p))
    registry._loaded = False   # 强制重载以吃到 env
    registry.load_builtin()
    m = registry.resolve("sherpa/mytest")
    assert m.id == "sherpa/mytest" and m.config_type == "senseVoice" and m.provider == "sherpa-onnx"


def test_user_models_legacy_local_normalized(tmp_path, monkeypatch):
    # 历史用户模型条目用旧 local/ 前缀写入 —— 加载时应归一为 sherpa/,且 local/ 仍可解析同一 meta。
    import json
    p = tmp_path / "models.json"
    p.write_text(json.dumps([{"id": "local/foo", "config_type": "senseVoice",
                              "provider": "sherpa-onnx", "vendor": "local",
                              "langs": ["zh"]}]))
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(p))
    registry._loaded = False   # 强制重载以吃到 env,触发 _load_user_models 归一逻辑
    registry.load_builtin()
    m = registry.resolve("sherpa/foo")
    assert m.id == "sherpa/foo" and m.vendor == "sherpa"
    assert registry.resolve("local/foo").id == m.id


def test_add_model(tmp_path, monkeypatch):
    # asrkit add-model 写的注册表能被读回并解析
    from asrkit import usermodels
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(tmp_path / "models.json"))
    usermodels.add({"id": "sherpa/added", "config_type": "senseVoice", "langs": ["zh"]})
    assert any(e["id"] == "sherpa/added" for e in usermodels.load())
    registry._loaded = False
    registry.load_builtin()
    assert registry.resolve("sherpa/added").config_type == "senseVoice"


def test_add_model_cli_bare_id_gets_sherpa_prefix(tmp_path, monkeypatch):
    # add-model 裸 id(不含 '/')应落到 sherpa/ 前缀,而非旧 local/
    from asrkit import usermodels
    monkeypatch.setenv("ASRKIT_MODELS_JSON", str(tmp_path / "models.json"))
    rc = cli.main(["add-model", "foo", "--arch", "senseVoice"])
    assert rc == 0
    assert any(e["id"] == "sherpa/foo" for e in usermodels.load())


def test_transformers_open_provider():
    # transformers 开放寻址：任意 HF id 都能解析
    m = registry.resolve("transformers/openai/whisper-tiny")
    assert m.provider == "transformers" and m.model == "openai/whisper-tiny"
    m2 = registry.resolve("transformers/some-org/some-model")
    assert m2.provider == "transformers" and m2.model == "some-org/some-model"


def test_resolve_and_alias():
    assert registry.resolve("sherpa/sensevoice").id == "sherpa/sensevoice"
    # Ollama 式精度寻址
    assert registry.resolve("sherpa/sensevoice:fp32").id == "sherpa/sensevoice-fp32"
    assert registry.resolve("sherpa/sensevoice:int8").id == "sherpa/sensevoice"
    # 裸名简写（省略 sherpa/）
    assert registry.resolve("sensevoice").id == "sherpa/sensevoice"
    assert registry.resolve("sensevoice:fp32").id == "sherpa/sensevoice-fp32"


def test_unknown_model_raises():
    with pytest.raises(registry.ModelNotFoundError):
        registry.resolve("sherpa/does-not-exist")


def test_local_prefix_is_permanent_alias():
    # 历史别名回归(R6,永久保留):local/ 与 sherpa/ 解析到同一 meta。
    assert registry.resolve("local/sensevoice").id == registry.resolve("sherpa/sensevoice").id
    assert registry.resolve("local/sensevoice:int8").id == "sherpa/sensevoice"
    assert registry.resolve("local/sensevoice:fp32").id == "sherpa/sensevoice-fp32"
    a = registry.make_adapter("local/sensevoice")
    assert a.meta.id == "sherpa/sensevoice"


def test_model_dir_rejects_path_traversal(tmp_path, monkeypatch):
    # 0.5.1 加固：model id 里的路径穿越必须被拒(否则 rm/symlink 越界)
    from asrkit.types import AdapterMeta
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path))
    evil = AdapterMeta(id="sherpa/../../evil", provider="sherpa-onnx", vendor="sherpa",
                       name="evil", source="local", modes=["batch"], langs=[])
    with pytest.raises(ValueError):
        store.model_dir(evil)
    # 正常 id 不受影响
    ok = AdapterMeta(id="sherpa/good", provider="sherpa-onnx", vendor="sherpa",
                     name="good", source="local", modes=["batch"], langs=[])
    assert store.model_dir(ok).endswith("good")


def test_usermodels_bare_filename_no_crash(tmp_path, monkeypatch):
    # 0.5.1：ASRKIT_MODELS_JSON 为裸文件名时 add() 不应 makedirs("") 崩
    from asrkit import usermodels
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASRKIT_MODELS_JSON", "models.json")
    usermodels.add({"id": "sherpa/x", "config_type": "senseVoice", "langs": ["zh"]})
    assert any(e["id"] == "sherpa/x" for e in usermodels.load())


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


def _tar_with(path, members, mode):
    with tarfile.open(path, mode) as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_extract_archive_targz(tmp_path):
    # 用户 add-model --url 给 .tar.gz：应能识别并解压（不再限死 bz2）
    src = tmp_path / "m.tar.gz"
    _tar_with(str(src), [("model.onnx", b"x")], "w:gz")
    out = tmp_path / "out"
    out.mkdir()
    store._extract_archive(str(src), str(out))
    assert (out / "model.onnx").exists()


def test_extract_archive_zip(tmp_path):
    import zipfile
    src = tmp_path / "m.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("model.onnx", b"x")
    out = tmp_path / "out"
    out.mkdir()
    store._extract_archive(str(src), str(out))
    assert (out / "model.onnx").exists()


def test_extract_zip_rejects_traversal(tmp_path):
    import zipfile
    src = tmp_path / "evil.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("../evil.txt", b"x")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError):
        store._extract_archive(str(src), str(out))


def test_extract_archive_unsupported_format(tmp_path):
    # 既非 tar.* 也非 zip → 诚实报错，不静默
    src = tmp_path / "not-an-archive.bin"
    src.write_bytes(b"this is not a tar or zip archive")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError):
        store._extract_archive(str(src), str(out))


def test_sha256_mismatch_rejected(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    with pytest.raises(ValueError):
        store._verify_sha256(str(f), "0" * 64, log=lambda *a: None)
    store._verify_sha256(str(f), "", log=lambda *a: None)  # 空 sha 跳过，不抛


def test_sherpa_missing_engine_friendly_error(monkeypatch):
    # base 极简化后：sherpa 引擎未装时应友好报错(带安装命令)，不抛 ImportError
    from asrkit.adapters import local_sherpa
    from asrkit.types import AudioInput, TranscribeOptions
    monkeypatch.setattr(local_sherpa, "_available", lambda: False)
    a = registry.make_adapter("sherpa/sensevoice")
    r = a.transcribe(AudioInput(original_path="/nope.wav"), TranscribeOptions())
    assert r.text == "" and "asrkit[local]" in (r.error or "")


def test_cloud_only_needs_no_engine():
    # 云端模型解析/构造不依赖任何本地引擎（接口层 + requests 即可）
    a = registry.make_adapter("dashscope/qwen3-asr-flash", {"api_key": "x"})
    assert a.is_configured()


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


def test_pull_url_override(tmp_path, monkeypatch):
    import io
    import os
    import shutil
    import tarfile

    from asrkit import store
    from asrkit.types import AdapterMeta
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path / "models"))
    tar = tmp_path / "src.tar.bz2"
    with tarfile.open(tar, "w:bz2") as tf:
        info = tarfile.TarInfo("model.onnx")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(store, "_download",
                        lambda url, path, log, timeout=30: shutil.copy(str(tar), path))
    meta = AdapterMeta(id="sherpa/urltest", provider="sherpa-onnx", vendor="sherpa",
                       name="x", source="local", modes=["batch"], langs=[], download_url="")
    d = store.pull(meta, {}, url="http://example.com/whatever.tar.bz2")
    assert os.path.exists(os.path.join(d, "model.onnx"))   # 用了覆盖 URL


def test_pull_url_rejects_non_http(tmp_path, monkeypatch):
    from asrkit import store
    from asrkit.types import AdapterMeta
    monkeypatch.setenv("ASRKIT_MODELS_ROOT", str(tmp_path / "models"))
    meta = AdapterMeta(id="sherpa/x2", provider="sherpa-onnx", vendor="sherpa",
                       name="x", source="local", modes=["batch"], langs=[], download_url="")
    with pytest.raises(ValueError):
        store.pull(meta, {}, url="file:///etc/passwd")
