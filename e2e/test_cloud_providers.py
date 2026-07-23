"""通过官方 OpenAI Python SDK 验证两家真实云厂的 ASRKit 路径。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from openai import APIStatusError, OpenAI

DASHSCOPE_MODEL = "dashscope/qwen3-asr-flash"
SECOND_MODELS = {
    "siliconflow": "siliconflow/sensevoice",
    "doubao": "doubao/auc-2",
}
TRANSCRIPT_ANCHORS = {"nightfall", "yellow", "lamps", "squalid", "brothels"}


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _validate_credentials(second_provider: str) -> None:
    _required("DASHSCOPE_API_KEY")
    if second_provider == "siliconflow":
        _required("SILICONFLOW_API_KEY")
        return
    if not os.environ.get("DOUBAO_API_KEY") and not (
        os.environ.get("DOUBAO_APP_KEY") and os.environ.get("DOUBAO_ACCESS_KEY")
    ):
        raise RuntimeError(
            "DOUBAO_API_KEY or both DOUBAO_APP_KEY and DOUBAO_ACCESS_KEY are required"
        )


def _transcribe(client: OpenAI, fixture: Path, model: str) -> None:
    try:
        with fixture.open("rb") as audio:
            result = client.audio.transcriptions.create(file=audio, model=model, language="en")
    except APIStatusError as exc:
        raise RuntimeError(f"{model} failed with HTTP {exc.status_code}") from None
    text = result.text.strip()
    if not text:
        raise RuntimeError(f"{model} returned an empty transcript")
    words = set(re.findall(r"[a-z]+", text.lower()))
    matched = words & TRANSCRIPT_ANCHORS
    if len(matched) < 2:
        raise RuntimeError(
            f"{model} matched only {len(matched)} expected transcript anchors"
        )
    print(f"{model}: ok ({len(text)} characters, {len(matched)} anchors)")


def main() -> None:
    second_provider = os.environ.get("ASRKIT_SECOND_PROVIDER", "siliconflow")
    if second_provider not in SECOND_MODELS:
        raise RuntimeError(f"unsupported second provider: {second_provider}")
    _validate_credentials(second_provider)

    fixture = Path(_required("ASRKIT_AUDIO_FIXTURE"))
    if not fixture.is_file():
        raise RuntimeError(f"audio fixture does not exist: {fixture}")
    client = OpenAI(
        api_key=_required("ASRKIT_GATEWAY_TOKEN"),
        base_url=f"{_required('ASRKIT_BASE_URL').rstrip('/')}/v1",
        timeout=330,
        max_retries=0,
    )
    expected = [DASHSCOPE_MODEL, SECOND_MODELS[second_provider]]
    available = {model.id for model in client.models.list().data}
    missing = set(expected) - available
    if missing:
        raise RuntimeError(f"ASRKit cloud profile is missing models: {sorted(missing)}")
    for model in expected:
        _transcribe(client, fixture, model)


if __name__ == "__main__":
    main()
