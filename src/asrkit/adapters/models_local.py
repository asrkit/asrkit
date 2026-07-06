"""本地模型注册表（47 个端侧模型）。数据源：asr_bench registry.json / models.dart。

每条 → 一个 AdapterMeta，provider 统一为 "sherpa-onnx"，由 local_sherpa 通用 adapter 处理。
id = "local/<folder>"，<folder> 与磁盘模型目录名一致。
"""
from __future__ import annotations

from ..registry import register_models
from ..types import AdapterMeta

# (folder, 显示名, config_type, streaming, langs)
_TABLE = [
    ("paraformer-small", "Paraformer-small", "paraformer", False, ["zh", "en"]),
    ("paraformer-zh", "Paraformer-zh（大）", "paraformer", False, ["zh", "en"]),
    ("sensevoice", "SenseVoice", "senseVoice", False, ["zh", "en", "yue"]),
    ("paraformer-trilingual", "Paraformer 三语", "paraformer", False, ["zh", "en", "yue"]),
    ("whisper-base", "Whisper-base", "whisper", False, ["zh", "en"]),
    ("whisper-small", "Whisper-small", "whisper", False, ["zh", "en"]),
    ("moonshine-base", "Moonshine-base", "moonshine", False, ["en"]),
    ("zipformer-stream-zh", "Zipformer 流式-中", "transducer", True, ["zh"]),
    ("zipformer-stream-zhen", "Zipformer 流式-中英", "transducer", True, ["zh", "en"]),
    ("telespeech-ctc", "TeleSpeech-CTC", "telespeechCtc", False, ["zh"]),
    ("firered-ctc", "FireRedAsr v2-CTC", "fireRedAsrCtc", False, ["zh", "en"]),
    ("stream-paraformer-zhen", "流式 Paraformer 中英", "onlineParaformer", True, ["zh", "en"]),
    ("zipformer-stream-multizh", "Zipformer 流式-中（轻量）", "transducer", True, ["zh"]),
    ("zipformer-stream-xlarge", "Zipformer 流式-中（xlarge）", "transducer", True, ["zh"]),
    ("whisper-tiny", "Whisper-tiny", "whisper", False, ["zh", "en"]),
    ("whisper-tiny-en", "Whisper-tiny.en", "whisper", False, ["en"]),
    ("whisper-base-en", "Whisper-base.en", "whisper", False, ["en"]),
    ("whisper-small-en", "Whisper-small.en", "whisper", False, ["en"]),
    ("whisper-distil-small-en", "Whisper-distil-small.en", "whisper", False, ["en"]),
    ("whisper-distil-medium-en", "Whisper-distil-medium.en", "whisper", False, ["en"]),
    ("paraformer-en", "Paraformer-en", "paraformer", False, ["en"]),
    ("moonshine-tiny", "Moonshine-tiny", "moonshine", False, ["en"]),
    ("zipformer-offline-zhen", "Zipformer 离线-中英", "offlineTransducer", False, ["zh", "en"]),
    ("zipformer-cantonese", "Zipformer 离线-粤", "offlineTransducer", False, ["yue"]),
    ("dolphin-small", "Dolphin-small CTC", "dolphin", False, ["zh"]),
    ("dolphin-base", "Dolphin-base CTC", "dolphin", False, ["zh"]),
    ("parakeet-tdt-v3", "Parakeet-TDT 0.6B v3", "nemoTransducer", False, ["en"]),
    ("parakeet-tdt-v2", "Parakeet-TDT 0.6B v2", "nemoTransducer", False, ["en"]),
    ("sensevoice-yue", "SenseVoice（粤强）", "senseVoice", False, ["zh", "en", "yue"]),
    ("paraformer-zh-2023", "Paraformer-zh（老版）", "paraformer", False, ["zh", "en"]),
    ("paraformer-zh-chuan", "Paraformer-zh（川渝）", "paraformer", False, ["zh"]),
    ("stream-paraformer-tri", "流式 Paraformer 三语", "onlineParaformer", True, ["zh", "en", "yue"]),
    ("whisper-turbo", "Whisper large-v3-turbo", "whisper", False, ["zh", "en"]),
    ("whisper-distil-large-v2", "Whisper distil-large-v2（英）", "whisper", False, ["en"]),
    ("whisper-large-v3", "Whisper large-v3", "whisper", False, ["zh", "en"]),
    ("whisper-large-v2", "Whisper large-v2", "whisper", False, ["zh", "en"]),
    ("whisper-medium", "Whisper medium", "whisper", False, ["zh", "en"]),
    ("whisper-medium-en", "Whisper medium.en", "whisper", False, ["en"]),
    ("sensevoice-fp32", "SenseVoice fp32（量化对照）", "senseVoice", False, ["zh", "en"]),
    ("firered-aed-l", "FireRedASR-AED-L（中文天花板）", "fireRedAed", False, ["zh", "en"]),
    ("qwen3-asr-0.6b", "Qwen3-ASR-0.6B int8", "qwen3Asr", False, ["zh", "en"]),
    ("firered-aed2", "FireRedASR2-AED int8（v2 旗舰）", "fireRedAed", False, ["zh", "en"]),
    ("funasr-nano", "Fun-ASR-Nano int8（LLM·方言）", "funasrNano", False, ["zh", "en"]),
    ("sensevoice-nano", "SenseVoice-FunASR-Nano int8", "senseVoice", False, ["zh", "en"]),
    ("moonshine-v2-zh", "Moonshine v2 中文（超轻）", "moonshineV2", False, ["zh"]),
    ("moonshine-v2-en", "Moonshine v2 英文", "moonshineV2", False, ["en"]),
    ("omnilingual-300m", "Meta Omnilingual 300M int8（1600 语）", "omnilingualCtc", False, ["zh", "en"]),
]


def _metas():
    out = []
    for folder, name, ctype, streaming, langs in _TABLE:
        out.append(AdapterMeta(
            id=f"local/{folder}",
            provider="sherpa-onnx",
            vendor="local",
            name=name,
            source="local",
            modes=["streaming"] if streaming else ["batch"],
            langs=langs,
            model_kind="asr",
            config_type=ctype,
        ))
    return out


register_models(_metas())
