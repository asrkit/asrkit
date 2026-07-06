"""0.4.1：输出格式渲染（txt/json/srt/vtt）。"""
import json

import pytest

from asrkit import formats
from asrkit.types import Segment, TranscribeResult


def _res_with_segments():
    return TranscribeResult(
        text="hello world",
        lang="en",
        latency_ms=123,
        segments=[Segment(0.0, 1.5, "hello"), Segment(1.5, 3.25, "world")],
    )


def test_txt():
    assert formats.render(TranscribeResult(text="hi"), "txt") == "hi"


def test_json_roundtrip():
    out = formats.render(_res_with_segments(), "json")
    d = json.loads(out)
    assert d["text"] == "hello world"
    assert d["lang"] == "en"
    assert len(d["segments"]) == 2
    assert d["segments"][0]["start"] == 0.0 and d["segments"][0]["text"] == "hello"
    # 空字段不出现
    assert "error" not in d and "word_timestamps" not in d


def test_srt():
    out = formats.render(_res_with_segments(), "srt")
    assert "1\n00:00:00,000 --> 00:00:01,500\nhello" in out
    assert "2\n00:00:01,500 --> 00:00:03,250\nworld" in out


def test_vtt():
    out = formats.render(_res_with_segments(), "vtt")
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500\nhello" in out


def test_subtitle_without_segments_errors():
    r = TranscribeResult(text="no timing")
    with pytest.raises(formats.FormatError):
        formats.render(r, "srt")
    with pytest.raises(formats.FormatError):
        formats.render(r, "vtt")


def test_unknown_format_errors():
    with pytest.raises(formats.FormatError):
        formats.render(TranscribeResult(text="x"), "docx")
