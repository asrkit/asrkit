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


def test_result_dict_always_includes_text():
    d = formats.result_dict(TranscribeResult(text="", error="boom"))
    assert d["text"] == ""          # 失败行也恒含 text
    assert d["error"] == "boom"


def test_result_dict_drops_other_empties_and_expands_segments():
    d = formats.result_dict(TranscribeResult(text="hi", segments=[Segment(0.0, 1.0, "hi")]))
    assert d["text"] == "hi"
    assert "lang" not in d          # 空 lang 略去
    assert d["segments"][0]["text"] == "hi"


def test_single_json_still_drops_empty_text():
    out = formats.render(TranscribeResult(text="", error="x"), "json")
    assert '"text"' not in out       # 单文件 json 行为不变
