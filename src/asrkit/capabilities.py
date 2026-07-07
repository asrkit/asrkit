"""能力位(capabilities)判读:三态 language_hint 归一 + 选项诚实告警。

沿用 adapter-spec.md 的三态字符串约定,不引入 bool 混用:
  language_hint: "required" | "supported" | "none"
  segment_timestamps: True(模型返回 segments)
"""
from __future__ import annotations

_LANG_YES = ("supported", "required")
_LANG_NO = ("none",)


def language_supported(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_YES


def language_ignored(meta) -> bool:
    return (meta.capabilities or {}).get("language_hint") in _LANG_NO


def warnings_for(opts, meta) -> list:
    """仅对显式声明忽略 language 的模型、且用户传了 lang_hint 时告警;缺省/未知不告警。"""
    out = []
    if getattr(opts, "lang_hint", None) and language_ignored(meta):
        out.append(f"{meta.id} auto-detects language; --language is ignored")
    return out


def is_english_only(langs) -> bool:
    """langs 只含 'en'(归一化)→ 英语专用检查点。用于排除 whisper-*-en/distil-en。"""
    return [str(x).strip().lower() for x in (langs or [])] == ["en"]
