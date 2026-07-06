"""转写结果的输出格式渲染：txt / json / srt / vtt。

CLI 与未来的 `asrkit serve`（response_format）共用。字幕格式依赖 result.segments；
模型未给时间戳时诚实报错，不伪造。
"""
from __future__ import annotations

import dataclasses
import json as _json
from typing import List

from .types import Segment, TranscribeResult

FORMATS = ("txt", "json", "srt", "vtt")


class FormatError(ValueError):
    """请求的格式无法从该结果渲染（如无 segments 却要字幕）。"""


def _ts(seconds: float, sep: str) -> str:
    """秒 → HH:MM:SS<sep>mmm（SRT 用 ',', VTT 用 '.'）。"""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _srt(segs: List[Segment]) -> str:
    lines = []
    for i, seg in enumerate(segs, 1):
        lines.append(str(i))
        lines.append(f"{_ts(seg.start, ',')} --> {_ts(seg.end, ',')}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _vtt(segs: List[Segment]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segs:
        lines.append(f"{_ts(seg.start, '.')} --> {_ts(seg.end, '.')}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _json_payload(r: TranscribeResult) -> str:
    # 仅输出非空字段；dataclass（segments 等）转 dict。
    out = {}
    for f in dataclasses.fields(r):
        v = getattr(r, f.name)
        if v in (None, "", [], {}):
            continue
        if f.name == "segments":
            v = [dataclasses.asdict(s) for s in v]
        out[f.name] = v
    return _json.dumps(out, ensure_ascii=False, indent=2)


def render(result: TranscribeResult, fmt: str) -> str:
    """把结果渲染为指定格式字符串。fmt ∈ FORMATS。字幕缺 segments → FormatError。"""
    fmt = (fmt or "txt").lower()
    if fmt == "txt":
        return result.text
    if fmt == "json":
        return _json_payload(result)
    if fmt in ("srt", "vtt"):
        if not result.segments:
            raise FormatError(
                f"model returned no timestamps; '{fmt}' needs segments — use --format txt or json")
        return _srt(result.segments) if fmt == "srt" else _vtt(result.segments)
    raise FormatError(f"unknown format '{fmt}' (choose from {', '.join(FORMATS)})")
