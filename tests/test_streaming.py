"""Tests for W4 minimal streaming (iter_file_chunks / transcribe_stream / api / CLI)."""
import pytest

from asrkit import audio
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
    assert all(p.committed == "" and p.partial == "" for p in out)   # 契约留空


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
