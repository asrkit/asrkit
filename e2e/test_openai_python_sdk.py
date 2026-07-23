"""用官方 Python SDK 行使 ASRKit 声明的 OpenAI 兼容子集。"""
from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

MODEL = "sdk/echo"
TRANSCRIPT = "hello from the ASRKit SDK contract"


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    fixture = Path(_required("ASRKIT_AUDIO_FIXTURE"))
    if not fixture.is_file():
        raise RuntimeError(f"audio fixture does not exist: {fixture}")
    client = OpenAI(
        api_key=_required("ASRKIT_SDK_TOKEN"),
        base_url=f"{_required('ASRKIT_BASE_URL').rstrip('/')}/v1",
    )

    models = client.models.list()
    assert any(model.id == MODEL for model in models.data)

    with fixture.open("rb") as audio:
        result = client.audio.transcriptions.create(file=audio, model=MODEL)
    assert result.text == TRANSCRIPT

    with fixture.open("rb") as audio:
        text = client.audio.transcriptions.create(
            file=audio,
            model=MODEL,
            response_format="text",
        )
    assert text == TRANSCRIPT

    with fixture.open("rb") as audio:
        verbose = client.audio.transcriptions.create(
            file=audio,
            model=MODEL,
            language="en",
            response_format="verbose_json",
        )
    assert verbose.text == TRANSCRIPT
    assert verbose.language == "en"
    assert verbose.segments and verbose.segments[0].text == TRANSCRIPT


if __name__ == "__main__":
    main()
