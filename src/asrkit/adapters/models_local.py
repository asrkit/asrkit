"""本地模型注册表（47 个端侧模型）。数据源：registry.json / models.dart / 下载脚本。

每条 → 一个 AdapterMeta（provider=sherpa-onnx，由 local_sherpa 处理）。
id = "local/<folder>"；下载地址来自 sherpa-onnx 的 GitHub releases。
精度：默认 tag=int8（端侧默认）；SenseVoice 另有 fp32 版，二者共享 base=sensevoice，
      可用 local/sensevoice:int8 / local/sensevoice:fp32 寻址。
"""
from __future__ import annotations

from ..registry import register_models
from ..types import AdapterMeta

_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

# (folder, 显示名, config_type, streaming, langs, tarball 资产名)
_TABLE = [
    ("paraformer-small", "Paraformer-small", "paraformer", False, ["zh", "en"], "sherpa-onnx-paraformer-zh-small-2024-03-09"),
    ("paraformer-zh", "Paraformer-zh (large)", "paraformer", False, ["zh", "en"], "sherpa-onnx-paraformer-zh-2024-03-09"),
    ("sensevoice", "SenseVoice", "senseVoice", False, ["zh", "en", "yue"], "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"),
    ("paraformer-trilingual", "Paraformer trilingual (zh/yue/en)", "paraformer", False, ["zh", "en", "yue"], "sherpa-onnx-paraformer-trilingual-zh-cantonese-en"),
    ("whisper-base", "Whisper-base", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-base"),
    ("whisper-small", "Whisper-small", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-small"),
    ("moonshine-base", "Moonshine-base", "moonshine", False, ["en"], "sherpa-onnx-moonshine-base-en-int8"),
    ("zipformer-stream-zh", "Zipformer streaming (zh)", "transducer", True, ["zh"], "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"),
    ("zipformer-stream-zhen", "Zipformer streaming (zh-en)", "transducer", True, ["zh", "en"], "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"),
    ("telespeech-ctc", "TeleSpeech-CTC", "telespeechCtc", False, ["zh"], "sherpa-onnx-telespeech-ctc-int8-zh-2024-06-04"),
    ("firered-ctc", "FireRedAsr v2-CTC", "fireRedAsrCtc", False, ["zh", "en"], "sherpa-onnx-fire-red-asr2-ctc-zh_en-int8-2026-02-25"),
    ("stream-paraformer-zhen", "Paraformer streaming (zh-en)", "onlineParaformer", True, ["zh", "en"], "sherpa-onnx-streaming-paraformer-bilingual-zh-en"),
    ("zipformer-stream-multizh", "Zipformer streaming (zh, light)", "transducer", True, ["zh"], "sherpa-onnx-streaming-zipformer-multi-zh-hans-2023-12-12"),
    ("zipformer-stream-xlarge", "Zipformer streaming (zh, xlarge)", "transducer", True, ["zh"], "sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30"),
    ("whisper-tiny", "Whisper-tiny", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-tiny"),
    ("whisper-tiny-en", "Whisper-tiny.en", "whisper", False, ["en"], "sherpa-onnx-whisper-tiny.en"),
    ("whisper-base-en", "Whisper-base.en", "whisper", False, ["en"], "sherpa-onnx-whisper-base.en"),
    ("whisper-small-en", "Whisper-small.en", "whisper", False, ["en"], "sherpa-onnx-whisper-small.en"),
    ("whisper-distil-small-en", "Whisper-distil-small.en", "whisper", False, ["en"], "sherpa-onnx-whisper-distil-small.en"),
    ("whisper-distil-medium-en", "Whisper-distil-medium.en", "whisper", False, ["en"], "sherpa-onnx-whisper-distil-medium.en"),
    ("paraformer-en", "Paraformer-en", "paraformer", False, ["en"], "sherpa-onnx-paraformer-en-2024-03-09"),
    ("moonshine-tiny", "Moonshine-tiny", "moonshine", False, ["en"], "sherpa-onnx-moonshine-tiny-en-int8"),
    ("zipformer-offline-zhen", "Zipformer offline (zh-en)", "offlineTransducer", False, ["zh", "en"], "sherpa-onnx-zipformer-zh-en-2023-11-22"),
    ("zipformer-cantonese", "Zipformer offline (yue)", "offlineTransducer", False, ["yue"], "sherpa-onnx-zipformer-cantonese-2024-03-13"),
    ("dolphin-small", "Dolphin-small CTC", "dolphin", False, ["zh"], "sherpa-onnx-dolphin-small-ctc-multi-lang-2025-04-02"),
    ("dolphin-base", "Dolphin-base CTC", "dolphin", False, ["zh"], "sherpa-onnx-dolphin-base-ctc-multi-lang-int8-2025-04-02"),
    ("parakeet-tdt-v3", "Parakeet-TDT 0.6B v3", "nemoTransducer", False, ["en"], "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"),
    ("parakeet-tdt-v2", "Parakeet-TDT 0.6B v2", "nemoTransducer", False, ["en"], "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"),
    ("sensevoice-yue", "SenseVoice (Cantonese)", "senseVoice", False, ["zh", "en", "yue"], "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"),
    ("paraformer-zh-2023", "Paraformer-zh (2023)", "paraformer", False, ["zh", "en"], "sherpa-onnx-paraformer-zh-2023-03-28"),
    ("paraformer-zh-chuan", "Paraformer-zh (Sichuan)", "paraformer", False, ["zh"], "sherpa-onnx-paraformer-zh-int8-2025-10-07"),
    ("stream-paraformer-tri", "Paraformer streaming (zh/yue/en)", "onlineParaformer", True, ["zh", "en", "yue"], "sherpa-onnx-streaming-paraformer-trilingual-zh-cantonese-en"),
    ("whisper-turbo", "Whisper large-v3-turbo", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-turbo"),
    ("whisper-distil-large-v2", "Whisper distil-large-v2 (en)", "whisper", False, ["en"], "sherpa-onnx-whisper-distil-large-v2"),
    ("whisper-large-v3", "Whisper large-v3", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-large-v3"),
    ("whisper-large-v2", "Whisper large-v2", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-large-v2"),
    ("whisper-medium", "Whisper medium", "whisper", False, ["zh", "en"], "sherpa-onnx-whisper-medium"),
    ("whisper-medium-en", "Whisper medium.en", "whisper", False, ["en"], "sherpa-onnx-whisper-medium.en"),
    ("sensevoice-fp32", "SenseVoice fp32", "senseVoice", False, ["zh", "en"], "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"),
    ("firered-aed-l", "FireRedASR-AED-L", "fireRedAed", False, ["zh", "en"], "sherpa-onnx-fire-red-asr-large-zh_en-2025-02-16"),
    ("qwen3-asr-0.6b", "Qwen3-ASR-0.6B int8", "qwen3Asr", False, ["zh", "en"], "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"),
    ("firered-aed2", "FireRedASR2-AED int8", "fireRedAed", False, ["zh", "en"], "sherpa-onnx-fire-red-asr2-zh_en-int8-2026-02-26"),
    ("funasr-nano", "Fun-ASR-Nano int8", "funasrNano", False, ["zh", "en"], "sherpa-onnx-funasr-nano-int8-2025-12-30"),
    ("sensevoice-nano", "SenseVoice-FunASR-Nano int8", "senseVoice", False, ["zh", "en"], "sherpa-onnx-sense-voice-funasr-nano-int8-2025-12-17"),
    ("moonshine-v2-zh", "Moonshine v2 (zh)", "moonshineV2", False, ["zh"], "sherpa-onnx-moonshine-base-zh-quantized-2026-02-27"),
    ("moonshine-v2-en", "Moonshine v2 (en)", "moonshineV2", False, ["en"], "sherpa-onnx-moonshine-base-en-quantized-2026-02-27"),
    ("omnilingual-300m", "Meta Omnilingual 300M int8 (1600 langs)", "omnilingualCtc", False, ["zh", "en"], "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05"),
]

# 同 base 的多精度：SenseVoice 有 int8 与 fp32 两版
_BASE_OVERRIDE = {"sensevoice": "sensevoice", "sensevoice-fp32": "sensevoice"}
_TAG_OVERRIDE = {"sensevoice-fp32": "fp32"}


def _metas():
    out = []
    for folder, name, ctype, streaming, langs, asset in _TABLE:
        out.append(AdapterMeta(
            id=f"local/{folder}",
            provider="sherpa-onnx",
            vendor="local",
            name=name,
            source="local",
            modes=["streaming"] if streaming else ["batch"],
            langs=langs,
            model_kind="asr",
            # whisper 是 30s 定长窗口，超长会截断 → 引擎据此发 warnings（见 D-3）
            capabilities={"max_input_duration_s": 30} if ctype == "whisper" else {},
            config_type=ctype,
            download_url=f"{_BASE}/{asset}.tar.bz2",
            base=_BASE_OVERRIDE.get(folder, folder),
            tag=_TAG_OVERRIDE.get(folder, "int8"),
        ))
    return out


register_models(_metas())
