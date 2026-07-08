<p align="right"><a href="README.md">简体中文</a> | <b>English</b></p>

# ASRKit

**One interface for speech recognition — on-device to cloud, swap one model string, your code doesn't change.**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit is to speech recognition what **Ollama + LiteLLM** are to LLMs: models pull-and-go, one addressing scheme across on-device and cloud, plus an optional OpenAI-compatible local server. **The core is just a thin interface** — the base install depends only on `requests`; engines install on demand, models download on demand. No torch for things you don't use.

It covers a panorama **no other tool does**: Chinese SOTA on-device models (SenseVoice / Paraformer / FireRed / TeleSpeech — 47 models, pull-and-go) + China's cloud vendors (DashScope / Doubao / SiliconFlow, which no Western toolchain covers) + the whole Whisper family + the entire HuggingFace ASR hub — one interface to compare, mix, and switch.

> ⚠️ **Early beta, under active development.** The core interface is usable, but we're still iterating — addressing/APIs may shift slightly between minor versions. Try it and tell us what breaks.

## 30 seconds to first transcript

```bash
pip install asrkit                                        # seconds: interface + cloud (just requests)
asrkit transcribe audio.wav -m siliconflow/sensevoice --api-key <KEY>   # free cloud model, works instantly

pip install "asrkit[local]"                               # add on-device (sherpa, 47 models)
asrkit run local/sensevoice audio.wav                     # downloads on first run, then transcribes
```

> Want a global command that doesn't touch your current env? `pipx install asrkit` or `uv tool install asrkit` work too.
> After installing, run `asrkit doctor` for a one-command health check (engines / keys / dirs / config; `--net` adds connectivity checks).

## The model string is the only thing that changes

Engine, model, on-device or cloud — all the same call:

```bash
asrkit run local/sensevoice                      audio.wav              # sherpa-onnx (on-device)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper engine
asrkit run whispercpp/base                       audio.wav              # whisper.cpp engine
asrkit run transformers/openai/whisper-large-v3  audio.wav              # any HuggingFace model
asrkit run dashscope/qwen3-asr-flash             audio.wav --api-key …  # cloud, bring your own key
```

On-device `local/sensevoice` and cloud `siliconflow/sensevoice` are **the same call** — comparing edge vs cloud is just swapping the string.

```python
from asrkit import transcribe
print(transcribe("local/sensevoice", "audio.wav").text)
```

## Why ASRKit

- **A Chinese/multilingual panorama no one else combines.** 47 on-device models + 5 cloud vendors out of the box; China's clouds and Chinese on-device SOTA are first-class citizens, not an afterthought.
- **The interface is the core; everything is pluggable.** The base install ships only the interface + cloud (just `requests`); engines, models, and the server are all add-ons. Use an engine you haven't installed → **a friendly error with the install command**, not an `ImportError`.
- **Learn once, use three ways.** CLI, Python library, and HTTP (OpenAI-compatible serve) — one model addressing scheme across all of them.
- **Transparent by design.** It doesn't touch your audio or change a model's native behavior by default. Wrong format? An honest error — never silent garbage. Unsupported options warn instead of being silently dropped. Conversion and chunking are opt-in.
- **Private.** Your audio and API keys never leave your machine — it's a library/tool, not a hosted service.

## Batch & scripting

Transcribe many files, a directory, a glob, or stdin at once — structured tables for comparison and scripting:

```bash
asrkit transcribe *.wav        -m local/sensevoice          -f csv          # one row each: file,model,text,latency_ms,rtf…
asrkit transcribe ./recordings -m dashscope/qwen3-asr-flash -f json --batch # recurse a dir → NDJSON
cat a.wav | asrkit transcribe  -  -m local/sensevoice                       # stdin
```

- **NDJSON / csv / tsv** for batches (a single file is still one object); contract in [docs/result-contract.md](docs/result-contract.md).
- **`srt/vtt` subtitles**: the whisper family (faster-whisper / whispercpp / openai/whisper-1) returns timestamps, so subtitles just work; other models get an **honest error** — never a fabricated timeline.
- **Graded exit codes** `0/1/2/3/4` (ok / unexpected / usage error / model not found / transcription failed; any failure in a batch → non-zero), so scripts can tell why.
- **Cloud batches retry** transient failures automatically — cost-safe: billable requests retry only on rate-limit/connection failure, never double-billing (`ASRKIT_HTTP_RETRIES` tunable).

## Streaming (minimal)

Decode sherpa online (streaming) models chunk by chunk, emitting incremental text as audio is fed:

```bash
asrkit stream local/paraformer-online meeting.wav             # live partials → stderr, final text → stdout
asrkit stream local/paraformer-online meeting.wav > out.txt   # pipe-friendly: capture final text only
asrkit stream local/sensevoice --mic                          # live microphone transcription, Ctrl-C to stop (needs asrkit[mic])
```

Only models with `streaming` in `modes` are supported (batch models get a clear error). `serve` also supports streaming: see "Run it as a server" below.

## Discovery & diagnostics

```bash
asrkit search whisper        # search models by id/name
asrkit list --lang ja        # filter by language (broad multilingual models returned as candidates)
asrkit doctor                # health check: engines / keys (presence only) / models dir writable / config valid
asrkit doctor --net          # add download-source / cloud reachability checks
asrkit completion zsh        # bash/zsh/fish completion (model names complete dynamically)
```

`run`/`transcribe`/`stream`/`serve` all support `-v` (INFO) / `-vv` (DEBUG) for more log detail; silent by default, doesn't affect stdout consumed by scripts.

## Install: a tiny interface core, everything pluggable

**The base install is just the interface + cloud (only `requests` — installs in seconds, runs anywhere).** Add local engines on demand:

| You want | Install |
|---|---|
| Cloud + CLI + a client for `serve` | `pip install asrkit` |
| Default on-device engine (sherpa, 47 models) | `pip install "asrkit[local]"` |
| Other engines | `asrkit[faster-whisper]` / `asrkit[whispercpp]` / `asrkit[transformers]` |
| Local server | `asrkit[serve]` |
| Live microphone streaming | `asrkit[mic]` |
| Everything | `asrkit[all]` |

> **Ownership model:** engines are **shared pip packages** — `asrkit engine install <name>` installs into the right environment for you; uninstall with your own `pip uninstall` (shared packages, your env, your call). Models are **asrkit-owned** — `pull` to download, `rm` to delete, clean and symmetric.

## Commands

| Command | What it does |
|---|---|
| `asrkit list` | list all models (✓ = installed); filter with `--lang/--arch`, bare ids with `--ids` |
| `asrkit search <term>` | search models by id/name |
| `asrkit run <model> <audio>` | download if missing, then transcribe |
| `asrkit transcribe <audio…> -m <model>` | transcribe only; multiple files / dir / glob / `-` (stdin), `--batch`; `--format txt/json/srt/vtt/csv/tsv`, `-o`, `--language` |
| `asrkit stream <model> <audio>` | streaming transcription (sherpa online models) |
| `asrkit pull <model> [--url …]` / `rm <model>` | download (`--url` overrides the source) / remove an on-device model |
| `asrkit show <model>` | model details |
| `asrkit engine list` / `install <name>` / `default <name>` / `rm <name>` | manage engines (`rm` is advisory: prints uninstall instructions, never runs `pip uninstall`) |
| `asrkit config set-key <vendor> <KEY>` / `list` | store keys / default engine / models dir |
| `asrkit doctor [--net]` | health-check the install and config |
| `asrkit serve` | run an OpenAI-compatible local server |
| `asrkit completion <shell>` | bash/zsh/fish completion script |
| `asrkit add-model …` | register a custom sherpa model |

## Engines & models

| Engine | Install | Address | Covers |
|---|---|---|---|
| **sherpa-onnx** (default on-device) | `asrkit[local]` | `local/<model>` or bare `<model>` | 47 on-device models, 17 architectures |
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
- Streaming: add `stream=true` to the same endpoint → `text/event-stream`, OpenAI-compatible `transcript.text.delta` (partial) / `transcript.text.done` (final) events; temp files are cleaned up automatically on disconnect. Only streaming models are supported — requesting `stream=true` on a non-streaming model errors out.
- Cloud keys come from the `asrkit config` keystore — no per-request key needed. Transparent: raw bytes uploaded, no decoding.

## Extend it

**Add any sherpa model** — one command, or an entry in `~/.asrkit/models.json`:

```bash
asrkit add-model local/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
```

**Add an engine** — ship a small package that declares an `asrkit.adapters` entry point; `pip install` auto-registers it. No fork, no core changes. Recipe: [docs/engines-and-addressing.md](docs/engines-and-addressing.md#九扩展实操).

## Design principles & boundaries

ASRKit is deliberately restrained — what it *doesn't* do matters as much as what it does:

- **It never touches your audio.** The core does zero processing and hands bytes to the model/cloud as-is; decoding/resampling/chunking are all opt-in (`--convert`/`--segment`).
- **It doesn't swallow specialist ecosystems.** Speaker diarization and forced alignment stay out of the interface layer — use the `raw_response` escape hatch or compose on top.
- **It doesn't uninstall engines for you.** Engines are shared pip packages: it helps you install into the right env, but your environment is yours.
- **It doesn't fake support.** No timestamps from the model → no subtitles; an option that won't take effect → a warning. Honest errors beat silent wrong output.

## Docs

[Usage](docs/usage.md) · [Adapter contract](docs/adapter-spec.md) · [Result contract](docs/result-contract.md) · [Engines & addressing](docs/engines-and-addressing.md) · [Model management](docs/model-management.md) · [Roadmap](docs/roadmap.md)

---

Apache-2.0. Each model's license is its own — verify before commercial use (`asrkit show <model>` points to the source). Your audio and keys stay on your machine.
