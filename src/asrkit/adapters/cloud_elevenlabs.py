"""ElevenLabs Scribe batch adapter (multipart, xi-api-key). 移植自 cloud_asr.dart:_elevenlabs。"""
from __future__ import annotations

import time

from ..registry import register_model, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult


@register_protocol("elevenlabs")
class ElevenLabs(BaseAdapter):
    def is_configured(self) -> bool:
        return bool(self.config.get("api_key"))

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        try:
            key = self.config.get("api_key", "")
            if not key:
                return TranscribeResult(text="", error="missing api_key (vendor=elevenlabs)")
            import requests
            base = self.config.get("base_url") or self.meta.default_base_url
            t0 = time.perf_counter()
            with open(audio.original_path, "rb") as f:
                r = requests.post(base, headers={"xi-api-key": key},
                                  data={"model_id": self.meta.model}, files={"file": f}, timeout=120)
            if r.status_code >= 300:
                return TranscribeResult(text="", error=f"HTTP {r.status_code}: {r.text[:200]}")
            j = r.json()
            return TranscribeResult(text=str(j.get("text", "")).strip(),
                                    latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


register_model(AdapterMeta(
    id="elevenlabs/scribe-v1", provider="elevenlabs", vendor="elevenlabs", name="ElevenLabs Scribe v1",
    source="cloud", modes=["batch"], langs=["zh", "en"], model_kind="asr",
    default_base_url="https://api.elevenlabs.io/v1/speech-to-text", model="scribe_v1",
    config_schema={"api_key": {"type": "secret", "required": True, "label": "ElevenLabs API Key"}}))
