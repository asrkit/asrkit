<p align="right"><a href="README.md">简体中文</a> | <b>English</b></p>

# ASRKit

**One interface for speech recognition — cloud built in, engines on demand, models pull-and-go.**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit is **Ollama + LiteLLM for speech recognition**: change one model string to swap between on-device models, cloud APIs, and any engine — your code doesn't change. **The core is just a thin interface** — cloud built in (tiny deps), local engines installed on demand, models pulled on demand, plus an optional OpenAI-compatible local server.

> ⚠️ **Early beta, under active development.** The core interface is usable, but we're still iterating — addressing/APIs may shift slightly between minor versions. Try it and tell us what breaks.

```bash
pip install asrkit                                        # seconds: interface + cloud (just requests)
asrkit transcribe audio.wav -m dashscope/qwen3-asr-flash --api-key <KEY>   # cloud, works instantly

pip install "asrkit[local]"                               # add on-device (sherpa, 47 models)
asrkit run local/sensevoice audio.wav                     # downloads on first run, then transcribes
```

> Want a global command that doesn't touch your current env? `pipx install asrkit` or `uv tool install asrkit` work too.

## One interface, swap anything

The model string is the only thing that changes — engine, model, on-device vs cloud, all the same call:

```bash
asrkit run local/sensevoice                      audio.wav              # sherpa-onnx (on-device)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper engine
asrkit run whispercpp/base                       audio.wav              # whisper.cpp engine
asrkit run transformers/openai/whisper-large-v3  audio.wav              # any HuggingFace model
asrkit run dashscope/qwen3-asr-flash             audio.wav --api-key …  # cloud, bring your own key
```

```python
from asrkit import transcribe
print(transcribe("dashscope/qwen3-asr-flash", "audio.wav", config={"api_key": "…"}).text)
```

## Batch & scripting

Transcribe many files, a directory, a glob, or stdin at once — structured tables for comparison and scripting:

```bash
asrkit transcribe *.wav        -m local/sensevoice          -f csv          # one row each: file,model,text,latency_ms,rtf…
asrkit transcribe ./recordings -m dashscope/qwen3-asr-flash -f json --batch # recurse a dir → NDJSON
cat a.wav | asrkit transcribe  -  -m local/sensevoice                       # stdin
```

- **NDJSON / csv / tsv** for batches (a single file is still one object); `srt/vtt` subtitles need model-provided timestamps, otherwise an honest error.
- **Graded exit codes** `0/2/3/4` (ok / usage error / model not found / transcription failed; any failure in a batch → non-zero), so scripts can tell why.
- **Cloud batches retry** transient failures (429/5xx) automatically — cost-safe: billable requests retry only on rate-limit/connection failure, never double-billing (`ASRKIT_HTTP_RETRIES` tunable).

## Why ASRKit

- **The interface is the core; everything is pluggable.** `pip install asrkit` ships only the interface + cloud (tiny — just `requests`); engines, models, and the server are all add-ons. No torch for things you don't use.
- **Same interface, local or cloud.** On-device `local/sensevoice` and cloud `siliconflow/sensevoice` — swap the string, not your code.
- **Curated *and* open.** 47 on-device models + 5 cloud vendors (including China's DashScope / Doubao / SiliconFlow) out of the box; custom models are one JSON line, new engines are a plugin — no fork required.
- **Transparent by design.** It doesn't touch your audio or change a model's native behavior by default. Wrong format? An honest error — never silent garbage. Conversion and long-audio chunking are opt-in.
- **Private.** Your audio and API keys never leave your machine — it's a library/tool, not a hosted service.

## Install: a tiny interface core, everything pluggable

**The base install is just the interface + cloud (only `requests` — installs in seconds, runs anywhere).** Add local engines on demand:

| You want | Install |
|---|---|
| Cloud + CLI + a client for `serve` | `pip install asrkit` |
| Default on-device engine (sherpa, 47 models) | `pip install "asrkit[local]"` |
| Other engines | `asrkit[faster-whisper]` / `asrkit[whispercpp]` / `asrkit[transformers]` |
| Local server | `asrkit[serve]` |
| Everything | `asrkit[all]` |

Use an engine you haven't installed → **a friendly error with the install command**, not an `ImportError`.

> **Ownership model:** engines are **shared pip packages** — `asrkit engine install <name>` installs into the right environment for you; uninstall with your own `pip uninstall` (shared packages, your env, your call). Models are **asrkit-owned** — `pull` to download, `rm` to delete, clean and symmetric.

## Commands

| Command | What it does |
|---|---|
| `asrkit list` | list all models (✓ = installed) |
| `asrkit run <model> <audio>` | download if missing, then transcribe |
| `asrkit transcribe <audio…> -m <model>` | transcribe only; multiple files / dir / glob / `-` (stdin), `--batch`; `--format txt/json/srt/vtt/csv/tsv`, `-o`, `--language` |
| `asrkit pull <model> [--url …]` / `rm <model>` | download (`--url` overrides the source) / remove an on-device model |
| `asrkit show <model>` | model details |
| `asrkit engine list` / `install <name>` / `default <name>` | manage engines |
| `asrkit config set-key <vendor> <KEY>` / `list` | store keys / default engine / models dir |
| `asrkit serve` | run an OpenAI-compatible local server |
| `asrkit add-model …` | register a custom sherpa model |

## Engines & models

| Engine | Install | Address | Covers |
|---|---|---|---|
| **sherpa-onnx** (default on-device) | `asrkit[local]` | `local/<model>` or bare `<model>` | 47 on-device models, 14 architectures |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<model>` | fast Whisper, native long-audio |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<model>` | ultra-light Whisper (no torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<any-hf-id>` | the whole HuggingFace ASR hub + LLM-arch SOTA |
| **cloud** | built-in | `<vendor>/<model>` | see below, bring your own key |

### Cloud vendors (built in, just add a key)

| Vendor | Addressing | Key |
|---|---|---|
| SiliconFlow | `siliconflow/sensevoice` (free), `siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| Alibaba DashScope | `dashscope/qwen3-asr-flash`, `dashscope/fun-asr-flash`, `dashscope/qwen-omni-plus`, `dashscope/qwen-omni-flash` | `--api-key` |
| Volcengine / Doubao | `doubao/auc-2` (2.0 Seed), `doubao/auc-1` (1.0) | `--api-key`, or `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

Three ways to supply a key (highest priority first): `--api-key` > env var `<VENDOR>_API_KEY` (Volcengine's dual key uses `DOUBAO_APP_KEY`/`DOUBAO_ACCESS_KEY`) > `asrkit config set-key <vendor> <KEY>` once.

## Run it as a server: OpenAI-compatible endpoint

`asrkit serve` starts a local server; any app on the OpenAI SDK (or an agent, or any language) reaches every model behind it by changing one `base_url` — this is the "LiteLLM proxy" half. **The caller needs zero asrkit deps, just HTTP.**

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
- Endpoints: `POST /v1/audio/transcriptions` (`response_format`: json/verbose_json/text/srt/vtt), `GET /v1/models`, `GET /health`.
- Cloud keys come from the `asrkit config` keystore — no per-request key needed. Transparent: raw bytes uploaded, no decoding.

## Extend it

**Add any sherpa model** — one command, or an entry in `~/.asrkit/models.json`:

```bash
asrkit add-model local/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
```

**Add an engine** — ship a small package that declares an `asrkit.adapters` entry point; `pip install` auto-registers it. No fork, no core changes. Recipe: [docs/engines-and-addressing.md](docs/engines-and-addressing.md#九扩展实操).

## Docs

[Usage](docs/usage.md) · [Adapter contract](docs/adapter-spec.md) · [Engines & addressing](docs/engines-and-addressing.md) · [Model management](docs/model-management.md)

---

Apache-2.0. Each model's license is its own — verify before commercial use (`asrkit show <model>` points to the source). Your audio and keys stay on your machine.
