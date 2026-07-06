"""阿里云百炼（DashScope）batch adapters. 移植自 asr_bench/lib/cloud_asr.dart（作者已接通）。

- qwen         : Qwen3-ASR（compatible chat/completions，user 消息只放 input_audio）
- qwen-omni    : Qwen-Omni（chat/completions + 转写指令；audio LLM，best-effort）
- funasr-flash : Fun-ASR-Flash（DashScope 原生 multimodal-generation）
"""
from __future__ import annotations

import base64
import os
import time

from ..registry import register_model, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

_KEY = {"api_key": {"type": "secret", "required": True, "label": "DashScope API Key"}}


def _data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".flac": "audio/flac", ".ogg": "audio/ogg"}.get(ext, "audio/wav")
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def _post(url, key, body):
    import requests
    r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json=body, timeout=120)
    if r.status_code >= 300:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    return r.json(), None


def _content_text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(e.get("text", "") if isinstance(e, dict) else "" for e in c)
    return ""


class _DashBase(BaseAdapter):
    def is_configured(self) -> bool:
        return bool(self.config.get("api_key"))

    def _key_base(self):
        return self.config.get("api_key", ""), (self.config.get("base_url") or self.meta.default_base_url)


@register_protocol("qwen")
class Qwen(_DashBase):
    def transcribe(self, audio, opts):
        try:
            key, base = self._key_base()
            if not key:
                return TranscribeResult(text="", error="missing api_key (vendor=dashscope)")
            t0 = time.perf_counter()
            j, err = _post(f"{base}/chat/completions", key, {
                "model": self.meta.model,
                "messages": [{"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": _data_uri(audio.original_path)}}]}]})
            if err:
                return TranscribeResult(text="", error=err)
            text = _content_text((j.get("choices") or [{}])[0].get("message", {}).get("content"))
            return TranscribeResult(text=text.strip(), latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


@register_protocol("qwen-omni")
class QwenOmni(_DashBase):
    def transcribe(self, audio, opts):
        try:
            key, base = self._key_base()
            if not key:
                return TranscribeResult(text="", error="missing api_key (vendor=dashscope)")
            t0 = time.perf_counter()
            j, err = _post(f"{base}/chat/completions", key, {
                "model": self.meta.model, "modalities": ["text"],
                "messages": [
                    {"role": "system", "content": "You are a speech transcription engine. "
                     "Output only the verbatim transcript of the audio. Do not translate, summarize, or explain."},
                    {"role": "user", "content": [
                        {"type": "input_audio", "input_audio": {"data": _data_uri(audio.original_path)}},
                        {"type": "text", "text": "Transcribe verbatim; output only the transcript."}]}]})
            if err:
                return TranscribeResult(text="", error=err)
            text = _content_text((j.get("choices") or [{}])[0].get("message", {}).get("content"))
            return TranscribeResult(text=text.strip(), latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


@register_protocol("funasr-flash")
class FunAsrFlash(_DashBase):
    def transcribe(self, audio, opts):
        try:
            key, url = self._key_base()
            if not key:
                return TranscribeResult(text="", error="missing api_key (vendor=dashscope)")
            t0 = time.perf_counter()
            j, err = _post(url, key, {
                "model": self.meta.model,
                "input": {"messages": [{"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": _data_uri(audio.original_path)}}]}]},
                "parameters": {"format": "wav", "sample_rate": "16000"}})
            if err:
                return TranscribeResult(text="", error=err)
            out = j.get("output", {}) or {}
            c = ((out.get("choices") or [{}])[0].get("message", {}) or {}).get("content")
            text = _content_text(c) or out.get("text", "")
            return TranscribeResult(text=text.strip(), latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


_COMPAT = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_GEN = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

register_model(AdapterMeta(id="dashscope/qwen3-asr-flash", provider="qwen", vendor="dashscope",
    name="Qwen3-ASR-flash (DashScope)", source="cloud", modes=["batch"], langs=["zh", "en"],
    model_kind="asr", pricing={"unit": "hour", "cny": 0.79}, default_base_url=_COMPAT,
    model="qwen3-asr-flash", config_schema=_KEY))
register_model(AdapterMeta(id="dashscope/fun-asr-flash", provider="funasr-flash", vendor="dashscope",
    name="Fun-ASR-Flash (DashScope)", source="cloud", modes=["batch"], langs=["zh", "en"],
    model_kind="asr", pricing={"unit": "hour", "cny": 0.79}, default_base_url=_GEN,
    model="fun-asr-flash-2026-06-15", config_schema=_KEY))
register_model(AdapterMeta(id="dashscope/qwen-omni-plus", provider="qwen-omni", vendor="dashscope",
    name="Qwen3.5-Omni-Plus (DashScope, audio LLM)", source="cloud", modes=["batch"], langs=["zh", "en"],
    model_kind="audio_llm", maturity="experimental", default_base_url=_COMPAT,
    model="qwen3.5-omni-plus", config_schema=_KEY))
register_model(AdapterMeta(id="dashscope/qwen-omni-flash", provider="qwen-omni", vendor="dashscope",
    name="Qwen3.5-Omni-Flash (DashScope, audio LLM)", source="cloud", modes=["batch"], langs=["zh", "en"],
    model_kind="audio_llm", maturity="experimental", default_base_url=_COMPAT,
    model="qwen3.5-omni-flash", config_schema=_KEY))
