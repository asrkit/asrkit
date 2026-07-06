"""火山引擎（豆包）录音文件识别 batch adapter — bigmodel auc (submit + poll).

两个版本靠 resource_id 区分：1.0 = volc.bigasr.auc；2.0/Seed = volc.seedasr.auc。
鉴权：新版单 api_key（x-api-key，2.0 必需）或旧版 app_key + access_key。
移植自 asr_bench/lib/cloud_asr.dart:_doubao（作者已真机接通）。
"""
from __future__ import annotations

import base64
import os
import time

from ..registry import register_model, register_protocol
from ..types import AdapterMeta, AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

_BASE = "https://openspeech.bytedance.com/api/v3/auc/bigmodel"

_SCHEMA = {
    "api_key": {"type": "secret", "required": False, "label": "Volcengine API Key (v2, x-api-key)"},
    "app_key": {"type": "secret", "required": False, "label": "App ID (X-Api-App-Key)"},
    "access_key": {"type": "secret", "required": False, "label": "Access Key (X-Api-Access-Key)"},
}


@register_protocol("doubao")
class Doubao(BaseAdapter):
    def is_configured(self) -> bool:
        c = self.config
        return bool(c.get("api_key") or (c.get("app_key") and c.get("access_key")))

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        try:
            c = self.config
            api_key, app_key, access_key = c.get("api_key", ""), c.get("app_key", ""), c.get("access_key", "")
            if not (api_key or (app_key and access_key)):
                return TranscribeResult(
                    text="", error="missing credentials (api_key, or app_key + access_key) for vendor=doubao")
            import requests
            base = c.get("base_url") or self.meta.default_base_url
            sz = os.path.getsize(audio.original_path)
            if sz > 200 * 1024 * 1024:      # base64 内联,防超大文件内存尖峰
                return TranscribeResult(
                    text="", error=f"audio is {sz >> 20}MB, over the 200MB inline-upload "
                    "limit; segment the file first")
            with open(audio.original_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()

            headers = {
                "X-Api-Resource-Id": self.meta.resource_id or "volc.bigasr.auc",
                "X-Api-Request-Id": str(int(time.time() * 1e6)),
                "X-Api-Sequence": "-1",
                "Content-Type": "application/json",
            }
            if api_key:
                headers["x-api-key"] = api_key
            else:
                headers["X-Api-App-Key"] = app_key
                headers["X-Api-Access-Key"] = access_key

            t0 = time.perf_counter()
            sub = requests.post(f"{base}/submit", headers=headers, json={
                "user": {"uid": "asrkit"},
                "audio": {"format": "wav", "data": b64},
                "request": {"model_name": self.meta.model},
            }, timeout=60)
            if sub.status_code >= 300:
                return TranscribeResult(text="", error=f"submit HTTP {sub.status_code}: {sub.text[:200]}")

            for _ in range(30):
                time.sleep(1)
                q = requests.post(f"{base}/query", headers=headers, data="{}", timeout=60)
                code = q.headers.get("x-api-status-code", "")
                if code == "20000000":
                    j = q.json()
                    text = (j.get("result") or {}).get("text") or j.get("text", "")
                    return TranscribeResult(
                        text=(text or "").strip(),
                        latency_ms=int((time.perf_counter() - t0) * 1000), raw_response=j)
                if code.startswith("45") or code.startswith("55"):
                    return TranscribeResult(text="", error=f"query failed code={code}: {q.text[:200]}")
            return TranscribeResult(text="", error="doubao polling timeout (30s)")
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")


for _mid, _name, _rid, _price in [
    ("doubao/auc-2", "Doubao 录音文件识别 2.0 (Seed)", "volc.seedasr.auc", {"unit": "hour", "cny": 0.8}),
    ("doubao/auc-1", "Doubao 录音文件识别 1.0", "volc.bigasr.auc", {"unit": "hour", "cny": 2.3}),
]:
    register_model(AdapterMeta(
        id=_mid, provider="doubao", vendor="doubao", name=_name, source="cloud",
        modes=["batch"], langs=["zh", "en"], model_kind="asr", pricing=_price,
        default_base_url=_BASE, model="bigmodel", resource_id=_rid, config_schema=_SCHEMA))
