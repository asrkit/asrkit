<p align="right"><a href="README.md">简体中文</a> | <b>English</b></p>

# ASRKit

**One interface to run and compare any speech-to-text model — local & cloud.**

一套接口，跑遍端云所有语音识别。

ASRKit is the Ollama + LiteLLM for speech recognition: pull and run open-source ASR models locally with one command, call cloud ASR APIs by changing one string, all through the same interface.

## Install

```bash
pip install asrkit
```

One command sets up both local and cloud. Model weights are downloaded on demand via `asrkit pull`; cloud needs your API key (just like Ollama: install the engine, fetch models when you use them).

## Quickstart

```bash
asrkit list                                              # list all models (✓ = installed)
asrkit run local/sensevoice a.wav                        # local: auto-download if missing, then transcribe
asrkit run siliconflow/sensevoice a.wav --api-key <KEY>  # cloud: just change the string
```

Python:

```python
from asrkit import transcribe
r = transcribe("local/sensevoice", "a.wav")
print(r.text)
```

## Highlights

- **47 on-device models** (SenseVoice / Paraformer / Whisper / Zipformer / Moonshine / Parakeet / FireRed / Qwen3-ASR …), pull-and-go.
- **OpenAI-compatible cloud endpoint**, bring your own key (more providers landing).
- **Transparent by design**: never touches your audio or changes the model's native behavior by default; honest errors on format mismatch; conversion (`--convert`) and long-audio segmentation (`--segment`) are opt-in.
- **Privacy**: your audio and keys never pass through us — ASRKit runs on your machine.

Apache-2.0. Usage: [docs/usage.md](docs/usage.md); write an adapter for a new engine/model: [docs/adapter-spec.md](docs/adapter-spec.md).

> Each model's license is defined by its own **upstream** (ASRKit is an interface and does not distribute weights; `pull` downloads from official releases); **verify before commercial use**. `asrkit show <model>` points you to the source.
