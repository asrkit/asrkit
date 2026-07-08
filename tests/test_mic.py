"""Tests for microphone streaming (P3-C)."""
import logging
import sys
import types

import pytest

from asrkit import api, mic


class _FakeStream:
    def __init__(self, blocks, overflow=False):
        self._blocks = list(blocks)
        self._i = 0
        self._overflow = overflow
        self.started = False
        self.stopped = False
        self.closed = False
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): self.closed = True
    def read(self, n):
        import numpy as np
        if self._i >= len(self._blocks):
            raise KeyboardInterrupt
        self._i += 1
        return np.zeros((n, 1), dtype="float32"), self._overflow


def _fake_sd(stream):
    m = types.ModuleType("sounddevice")
    m.InputStream = lambda **kw: stream
    return m


def test_record_chunks_yields_then_ctrl_c_stops(monkeypatch):
    pytest.importorskip("numpy")
    st = _FakeStream(blocks=[1, 2, 3])
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd(st))
    out = list(mic.record_chunks(samplerate=16000, block_s=0.1))
    assert len(out) == 3
    assert st.started and st.stopped and st.closed        # finally 收尾


def test_record_chunks_missing_dep_raises_eager(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)   # import → ImportError
    with pytest.raises(RuntimeError) as ei:
        mic.record_chunks()                                 # 调用本身即抛(非生成器外壳)
    assert "asrkit[mic]" in str(ei.value)


def test_record_chunks_overflow_warns_once(monkeypatch, caplog):
    pytest.importorskip("numpy")
    st = _FakeStream(blocks=[1, 2, 3], overflow=True)
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd(st))
    with caplog.at_level(logging.WARNING, logger="asrkit"):
        list(mic.record_chunks())
    warns = [r for r in caplog.records if "overflow" in r.message.lower()]
    assert len(warns) == 1                                  # 只 warn 一次


def test_api_stream_mic_rejects_non_streaming():
    with pytest.raises(ValueError):
        api.transcribe_stream_mic("openai/whisper-1")       # 非流式 → ValueError,不碰麦克风
