"""Tests for W4 minimal streaming (iter_file_chunks / transcribe_stream / api / CLI)."""
import pytest

from asrkit import api, audio, cli, emit
from asrkit.adapters import local_sherpa
from asrkit.types import AdapterMeta, PartialResult, TranscribeOptions  # noqa: F401


def test_iter_file_chunks_slicing(monkeypatch):
    """iter_file_chunks 按窗切块,拼接还原,窗口数 = ceil(n/win)。"""
    seq = list(range(5000))
    monkeypatch.setattr(audio, "load_samples", lambda *a, **k: (seq, 16000))
    chunks = list(audio.iter_file_chunks("x.wav", 16000, 1, 0.1))
    assert [len(c) for c in chunks] == [1600, 1600, 1600, 200]     # win = 0.1*16000
    flat = [x for c in chunks for x in c]
    assert flat == seq


def test_iter_file_chunks_format_guard_lazy(monkeypatch):
    """格式不符 → AudioFormatError,在首次迭代时抛(生成器懒抛)。"""
    def boom(*a, **k):
        raise audio.AudioFormatError("bad format")
    monkeypatch.setattr(audio, "load_samples", boom)
    gen = audio.iter_file_chunks("x.wav")          # 构造不抛
    with pytest.raises(audio.AudioFormatError):
        next(iter(gen))                             # 首次迭代才抛


class _FakeStream:
    def __init__(self):
        self.fed = 0
    def accept_waveform(self, sr, samples):
        self.fed += 1
    def input_finished(self):
        pass


class _FakeRec:
    """get_result 随喂入块数递增,便于断言 text 增长。"""
    def create_stream(self):
        return _FakeStream()
    def is_ready(self, st):
        return False                       # 不进 decode 循环
    def decode_stream(self, st):
        pass
    def get_result(self, st):
        return "x" * st.fed
    def is_endpoint(self, st):
        return False
    def reset(self, st):
        pass


def _streaming_meta():
    return AdapterMeta(id="local/fake-stream", provider="sherpa-onnx", vendor="local",
                       name="Fake", source="local", modes=["streaming"], langs=["en"],
                       config_type="onlineParaformer")


def _batch_meta():
    return AdapterMeta(id="local/fake-batch", provider="sherpa-onnx", vendor="local",
                       name="Fake", source="local", modes=["batch"], langs=["en"],
                       config_type="senseVoice")


def _patch_engine(monkeypatch, tmp_path, rec):
    monkeypatch.setattr(local_sherpa, "_available", lambda: True)
    monkeypatch.setattr(local_sherpa.store, "model_dir", lambda meta, cfg: str(tmp_path))
    monkeypatch.setattr(local_sherpa, "_build", lambda *a, **k: rec)


def test_transcribe_stream_yields_growing_partials(monkeypatch, tmp_path):
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    _patch_engine(monkeypatch, tmp_path, _FakeRec())
    out = list(ad.transcribe_stream(iter([[0.0], [0.0], [0.0]]), TranscribeOptions()))
    assert len(out) == 4                                   # 3 块 + 1 定稿
    assert [p.is_final for p in out] == [False, False, False, True]
    texts = [p.text for p in out]
    assert texts == sorted(texts, key=len)                 # 递增
    assert all(p.committed == "" for p in out[:3])            # 无端点 → committed 累积前为空
    assert all(p.partial == p.text for p in out[:3])          # 无 committed 时 text == partial
    assert all(p.partial for p in out[:3])                    # partial = 当前假设,非空
    assert out[-1].partial == "" and out[-1].committed == out[-1].text   # 定稿全进 committed


def test_transcribe_stream_endpoints_accumulate_committed(monkeypatch, tmp_path):
    """端点触发时当前段进 committed、reset 被调、新段从头开始。"""
    pytest.importorskip("numpy")

    class _EPStream:
        def __init__(self):
            self.seg = 0            # 当前段已喂块数
        def accept_waveform(self, sr, samples):
            self.seg += 1
        def input_finished(self):
            pass

    class _EPRec:
        """第 2 块是端点;每段 get_result = 'seg'*当前段块数。"""
        def __init__(self):
            self.resets = 0
            self._st = None
        def create_stream(self):
            self._st = _EPStream()
            return self._st
        def is_ready(self, st):
            return False
        def decode_stream(self, st):
            pass
        def get_result(self, st):
            return "a" * st.seg
        def is_endpoint(self, st):
            return st.seg == 2       # 第 2 块判为端点
        def reset(self, st):
            self.resets += 1
            st.seg = 0               # 新段从头

    ad = local_sherpa.SherpaLocal(_streaming_meta())
    rec = _EPRec()
    _patch_engine(monkeypatch, tmp_path, rec)
    out = list(ad.transcribe_stream(iter([[0.0], [0.0], [0.0]]), TranscribeOptions()))
    # 第 2 块(index 1)是端点:committed 收下 "aa",partial 清空
    assert out[1].committed == "aa" and out[1].partial == ""
    assert rec.resets >= 1
    # 定稿:committed 含两段(第一段 aa + 尾段剩余),partial 空,is_final
    assert out[-1].is_final and out[-1].partial == ""
    assert "aa" in out[-1].committed


def test_transcribe_stream_batch_model_raises_call_time(monkeypatch):
    """非流式模型:外壳非生成器,调用本身即抛(无需迭代)。"""
    ad = local_sherpa.SherpaLocal(_batch_meta())
    with pytest.raises(NotImplementedError):
        ad.transcribe_stream(iter([]), TranscribeOptions())    # 不 list(),调用即抛


def test_transcribe_stream_build_error_symmetric(monkeypatch, tmp_path):
    """_build 抛 → 收进末尾 PartialResult.error,不逃出生成器。"""
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    monkeypatch.setattr(local_sherpa, "_available", lambda: True)
    monkeypatch.setattr(local_sherpa.store, "model_dir", lambda meta, cfg: str(tmp_path))
    def boom(*a, **k):
        raise RuntimeError("no onnx files")
    monkeypatch.setattr(local_sherpa, "_build", boom)
    out = list(ad.transcribe_stream(iter([[0.0]]), TranscribeOptions()))
    assert out[-1].is_final is True
    assert out[-1].error and "streaming failed" in out[-1].error


def test_transcribe_stream_audioformat_error_propagates(monkeypatch, tmp_path):
    """AudioFormatError 从 chunks 迭代抛出 → 穿透 _stream,不被吞成 PartialResult.error。"""
    pytest.importorskip("numpy")
    ad = local_sherpa.SherpaLocal(_streaming_meta())
    _patch_engine(monkeypatch, tmp_path, _FakeRec())
    def bad_chunks():
        raise local_sherpa.AudioFormatError("bad wav")
        yield  # noqa (make it a generator)
    with pytest.raises(local_sherpa.AudioFormatError):
        list(ad.transcribe_stream(bad_chunks(), TranscribeOptions()))


def test_api_stream_rejects_non_streaming_model():
    """非流式 model → 及早 ValueError(不迭代即抛)。"""
    with pytest.raises(ValueError):
        api.transcribe_stream("openai/whisper-1", "x.wav")    # 云端 batch 模型


def test_api_stream_rejects_bad_window():
    """window_s<=0 → 及早 ValueError(在 make_adapter 之前,故未注册 model 也先抛这个)。"""
    with pytest.raises(ValueError):
        api.transcribe_stream("local/fake-stream", "x.wav", window_s=0)


def test_cli_stream_renders_final_to_stdout(monkeypatch, capsys):
    """最终文本进 stdout,退 EXIT_OK。"""
    def fake_stream(model, audio, *, config=None, opts=None):
        yield PartialResult(text="he", is_final=False)
        yield PartialResult(text="hello", is_final=True)
    monkeypatch.setattr(cli.api, "transcribe_stream", fake_stream)
    rc = cli.main(["stream", "local/fake-stream", "x.wav"])
    out = capsys.readouterr().out
    assert rc == emit.EXIT_OK
    assert "hello" in out


def test_cli_stream_non_streaming_usage(monkeypatch, capsys):
    """非流式 model(api 抛 ValueError)→ EXIT_USAGE,提示进 stderr。"""
    def boom(*a, **k):
        raise ValueError("openai/whisper-1 is not a streaming model")
    monkeypatch.setattr(cli.api, "transcribe_stream", boom)
    rc = cli.main(["stream", "openai/whisper-1", "x.wav"])
    err = capsys.readouterr().err
    assert rc == emit.EXIT_USAGE
    assert "not a streaming model" in err


def test_cli_stream_runtime_failure(monkeypatch, capsys):
    """PartialResult.error → EXIT_FAILED,[error] 进 stderr。"""
    def fake_stream(model, audio, *, config=None, opts=None):
        yield PartialResult(text="", is_final=True, error="streaming failed: boom")
    monkeypatch.setattr(cli.api, "transcribe_stream", fake_stream)
    rc = cli.main(["stream", "local/fake-stream", "x.wav"])
    err = capsys.readouterr().err
    assert rc == emit.EXIT_FAILED
    assert "[error]" in err
