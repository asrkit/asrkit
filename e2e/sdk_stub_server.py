"""供官方 OpenAI SDK 契约测试使用的确定性本地服务。"""
from __future__ import annotations

import argparse
import os

from asrkit import registry, server
from asrkit.types import AdapterMeta, BaseAdapter, Segment, TranscribeResult

MODEL = "sdk/echo"
TRANSCRIPT = "hello from the ASRKit SDK contract"


@registry.register_protocol("sdk-stub")
class SDKStubAdapter(BaseAdapter):
    def transcribe(self, audio, opts):
        return TranscribeResult(
            text=TRANSCRIPT,
            lang=opts.lang_hint or "en",
            segments=[Segment(start=0.0, end=1.0, text=TRANSCRIPT)],
        )


registry.register_model(AdapterMeta(
    id=MODEL,
    provider="sdk-stub",
    vendor="asrkit",
    name="SDK contract stub",
    source="cloud",
    modes=["batch"],
    langs=["en"],
    capabilities={"language_hint": "supported", "segment_timestamps": True},
    cache_owner="none",
))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    token = os.environ.get("ASRKIT_SDK_TOKEN")
    if not token:
        raise SystemExit("ASRKIT_SDK_TOKEN is required")
    server.serve(
        host="127.0.0.1",
        port=args.port,
        auth_token=token,
        max_upload_bytes=1024 * 1024,
        max_concurrency=2,
        request_timeout_s=10,
    )


if __name__ == "__main__":
    main()
