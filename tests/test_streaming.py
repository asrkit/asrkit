"""Tests for W4 minimal streaming (iter_file_chunks / transcribe_stream / api / CLI)."""
import pytest

from asrkit import audio


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
