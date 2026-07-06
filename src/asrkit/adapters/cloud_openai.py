"""OpenAI 兼容协议 adapter（/audio/transcriptions）。

覆盖 OpenAI / 硅基流动 及一切 OpenAI 兼容转写端点。移植自 cloud_asr.dart 的 _openai。
第 2 波会补 deepgram / dashscope / doubao 等协议。
"""
from __future__ import annotations

import time

from ..registry import register_model, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult


@register_protocol("openai")
class OpenAICompatible(BaseAdapter):
    def is_configured(self) -> bool:
        return bool(self.config.get("api_key"))

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        try:
            key = self.config.get("api_key", "")
            if not key:
                return TranscribeResult(text="", error=f"missing api_key (vendor={self.meta.vendor})")
            base = self.config.get("base_url") or self.meta.default_base_url
            import requests  # asrkit[cloud] 依赖
            t0 = time.perf_counter()
            # 透明原则：原始文件字节级原样上传，不解码/不重采样
            with open(audio.original_path, "rb") as f:
                resp = requests.post(
                    f"{base}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    data={"model": self.meta.model},
                    files={"file": f},
                    timeout=120,
                )
            ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code >= 300:
                return TranscribeResult(text="", latency_ms=ms,
                                        error=f"HTTP {resp.status_code}: {resp.text[:200]}")
            j = resp.json()
            return TranscribeResult(
                text=str(j.get("text") or j.get("result") or "").strip(),
                latency_ms=ms, raw_response=j)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


# —— 该协议下的云端模型（第 1 波先放硅基流动免费 SenseVoice 做端云对照）——
register_model(AdapterMeta(
    id="siliconflow/sensevoice",
    provider="openai",
    vendor="siliconflow",
    name="SenseVoiceSmall (SiliconFlow, free)",
    source="cloud",
    modes=["batch"],
    langs=["zh", "en", "ja", "ko", "yue"],
    model_kind="asr",
    capabilities={"punctuation": True, "itn": True, "language_hint": "none"},
    pricing={"unit": "hour", "cny": 0.0},
    default_base_url="https://api.siliconflow.cn/v1",
    model="FunAudioLLM/SenseVoiceSmall",
    config_schema={
        "api_key": {"type": "secret", "required": True, "label": "SiliconFlow API Key"},
        "base_url": {"type": "string", "required": False, "label": "Base URL override"},
    },
))

register_model(AdapterMeta(
    id="siliconflow/telespeech",
    provider="openai",
    vendor="siliconflow",
    name="TeleSpeechASR (SiliconFlow)",
    source="cloud",
    modes=["batch"],
    langs=["zh"],
    model_kind="asr",
    default_base_url="https://api.siliconflow.cn/v1",
    model="TeleAI/TeleSpeechASR",
    config_schema={"api_key": {"type": "secret", "required": True, "label": "SiliconFlow API Key"}},
))

register_model(AdapterMeta(
    id="openai/whisper-1",
    provider="openai",
    vendor="openai",
    name="Whisper (OpenAI whisper-1)",
    source="cloud",
    modes=["batch"],
    langs=["zh", "en", "ja", "ko"],
    model_kind="asr",
    pricing={"unit": "hour", "cny": 2.6},
    default_base_url="https://api.openai.com/v1",
    model="whisper-1",
    config_schema={"api_key": {"type": "secret", "required": True, "label": "OpenAI API Key"}},
))
