<p align="right"><a href="README.md">简体中文</a> | <b>English</b></p>

# ASRKit

**One interface to run any speech-to-text model — local & cloud, any engine.**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit is **Ollama + LiteLLM for speech recognition**. Pull an on-device model and run it with one command; call a cloud API by changing one string; snap in a whole new inference engine as a plugin. One contract, everything behind it.

> ⚠️ **Early beta, under active development.** The core interface is usable, but we're still iterating fast — APIs and addressing may change between minor versions. Try it and tell us what breaks.

```bash
pipx install asrkit                                         # use it as a tool (isolated, global command)
asrkit transcribe audio.wav -m dashscope/qwen3-asr-flash --api-key <KEY>   # cloud, works instantly

pipx inject asrkit "asrkit[local]"                         # add on-device (sherpa, 47 models)
asrkit run local/sensevoice audio.wav                      # downloads on first run, then transcribes
```

> `pip install asrkit` works too (to `import` it in your code); `pipx` / `uv tool install` are better when you just want the command.

## Install: a tiny interface core, everything pluggable

**The base install is just the interface + cloud (only `requests` — installs in seconds, runs anywhere).** Add local engines on demand:

| You want | Install |
|---|---|
| Cloud + CLI + a client for `serve` | `pip install asrkit` (or `pipx install asrkit`) |
| Default on-device engine (sherpa, 47 models) | `pip install "asrkit[local]"` |
| Other engines | `asrkit[faster-whisper]` / `asrkit[whispercpp]` / `asrkit[transformers]` |
| Local server | `asrkit[serve]` |
| Everything | `asrkit[all]` |

Use an engine you haven't installed → **a friendly error with the install command**, not an `ImportError`.

## One interface, swap anything

The model string is the only thing that changes — engine, model, on-device vs cloud, all the same call:

```bash
asrkit run local/sensevoice                      audio.wav              # sherpa-onnx (on-device, default)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper engine
asrkit run whispercpp/base                       audio.wav              # whisper.cpp engine
asrkit run transformers/openai/whisper-large-v3  audio.wav              # any HuggingFace model
asrkit run siliconflow/sensevoice                audio.wav --api-key …  # cloud, bring your own key
```

```python
from asrkit import transcribe
print(transcribe("local/sensevoice", "audio.wav").text)
```

## Why ASRKit

- **Curated *and* open.** 47 on-device models work out of the box (`asrkit list`); anything else drops in via a JSON entry or a plugin — no fork required.
- **Four engines, more via plugins.** sherpa-onnx, faster-whisper, whisper.cpp, and transformers (the entire HuggingFace hub, incl. LLM-architecture SOTA). `pip install asrkit-<engine>` adds your own.
- **Transparent by design.** ASRKit doesn't touch your audio or change a model's native behavior by default. Wrong format? An honest error — never silent garbage. Format conversion and long-audio chunking are opt-in flags.
- **Private.** Your audio and API keys never leave your machine — ASRKit is a library, not a hosted service.
- **The interface is the core.** `pip install asrkit` ships only the interface + cloud (tiny — just `requests`); engines, models, and the server are all add-ons. Cloud is built in (minuscule code/deps); on-device is one extra away.

## Commands

| Command | What it does |
|---|---|
| `asrkit list` | list all models (✓ = installed) |
| `asrkit run <model> <audio>` | download if missing, then transcribe |
| `asrkit transcribe <audio> -m <model>` | transcribe only (no auto-download) |
| `asrkit pull <model>` / `rm <model>` | download / remove an on-device model |
| `asrkit show <model>` | model details |
| `asrkit engine list` / `install <name>` | manage engines |

## Engines & models

| Engine | Install | Address | Covers |
|---|---|---|---|
| **sherpa-onnx** (default) | built-in | `local/<model>` or bare `<model>` | 47 on-device models, 14 architectures |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<model>` | fast Whisper, native long-audio |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<model>` | ultra-light Whisper (no torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<any-hf-id>` | the whole HuggingFace ASR hub + LLM-arch SOTA |
| **cloud** | built-in | `<vendor>/<model>` | see below, bring your own key |

### Cloud vendors

| Vendor | Addressing | Key |
|---|---|---|
| SiliconFlow | `siliconflow/sensevoice` (free), `siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| Alibaba DashScope | `dashscope/qwen3-asr-flash`, `dashscope/fun-asr-flash`, `dashscope/qwen-omni-plus`, `dashscope/qwen-omni-flash` | `--api-key` |
| Volcengine / Doubao | `doubao/auc-2` (2.0 Seed), `doubao/auc-1` (1.0) | `--api-key`, or `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

Keys also fall back to env vars: `<VENDOR>_API_KEY` (e.g. `DASHSCOPE_API_KEY`); Volcengine's dual key uses `DOUBAO_APP_KEY` / `DOUBAO_ACCESS_KEY`.

## Run it as a server: OpenAI-compatible endpoint

`asrkit serve` starts a local server; any app built on the OpenAI SDK reaches every model behind it by changing one `base_url` — this is the "LiteLLM proxy" half:

```bash
pip install "asrkit[serve]"
asrkit config set-key dashscope <KEY>     # store a key once (only for cloud)
asrkit serve                              # 127.0.0.1:11435 by default, local only
```
```python
from openai import OpenAI
c = OpenAI(base_url="http://localhost:11435/v1", api_key="unused")
c.audio.transcriptions.create(model="local/sensevoice", file=open("a.wav", "rb"))
```
- Endpoints: `POST /v1/audio/transcriptions` (`response_format`: json/text/srt/vtt), `GET /v1/models`, `GET /health`.
- Cloud keys come from the `asrkit config` keystore — no per-request key needed. Transparent: raw bytes uploaded, no decoding.

## Extend it

**Add any sherpa model** — drop an entry in `~/.asrkit/models.json`:

```json
[{"id": "local/my-model", "download_url": "https://…/model.tar.bz2", "config_type": "senseVoice", "langs": ["zh"]}]
```

**Add an engine** — ship a small package that declares an `asrkit.adapters` entry point; `pip install` auto-registers it. No fork, no core changes. Recipe: [docs/engines-and-addressing.md](docs/engines-and-addressing.md#九扩展实操).

## Docs

[Usage](docs/usage.md) · [Adapter contract](docs/adapter-spec.md) · [Engines & addressing](docs/engines-and-addressing.md) · [Model management](docs/model-management.md)

---

Apache-2.0. Each model's license is its own — verify before commercial use (`asrkit show <model>` points to the source). Your audio and keys stay on your machine.
