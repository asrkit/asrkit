<p align="right"><a href="README.md">简体中文</a> | <b>English</b></p>

# ASRKit

**One interface for speech recognition — on-device to cloud, swap one model string, your code doesn't change.**

[![PyPI](https://img.shields.io/pypi/v/asrkit)](https://pypi.org/project/asrkit/)
[![Python](https://img.shields.io/pypi/pyversions/asrkit)](https://pypi.org/project/asrkit/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/asrkit/asrkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asrkit/asrkit/actions)

ASRKit is to speech recognition what **Ollama + LiteLLM** are to LLMs: ASRKit-managed models pull-and-go, one addressing scheme across on-device and cloud, plus an optional OpenAI-compatible local server. **The core is just a thin interface** — the base install depends only on `requests`; engines install on demand, while external engine-owned caches remain under their engine's control. No torch for things you don't use.

It brings an uncommon combination under one interface: Chinese SOTA on-device models (SenseVoice / Paraformer / FireRed / TeleSpeech — 47 ASRKit-managed sherpa models) + major China cloud providers (DashScope / Doubao / SiliconFlow) + the Whisper family + open addressing for HuggingFace ASR models.

> ⚠️ **Early beta, under active development.** The core interface is usable, but we're still iterating — addressing/APIs may shift slightly between minor versions. Try it and tell us what breaks.

> **Current release boundary:** PyPI 0.5.5 includes the complete CLI/Python API, `serve`, and the cloud-only daemon Python module. The self-contained `asrkit-cloud` binary and npm platform packages are **not formally released yet**; do not treat the frozen-runtime prototypes in this repository as public distributions. See the [roadmap](docs/roadmap.md) for current status.

## Install — pick your way, it's not pip-only

The base install needs only `requests` (cloud is built in); engines/models/`serve` are all opt-in. So **cloud-only use is nearly zero-setup** — pick the row that fits you:

| You want | Install |
|---|---|
| **Cloud-only, zero env hassle** | `uv tool install asrkit` — `uv` is a single one-line binary; `asrkit` lands on your PATH, no Python env to manage |
| **Not even install (run once)** | `uvx asrkit transcribe audio.wav -m siliconflow/sensevoice --api-key <KEY>` — no ASRKit preinstall; uv creates a temporary environment and may retain download caches |
| **Regular Python user** | `pip install asrkit` |
| **Global command, don't touch current env** | `pipx install asrkit` |
| **On-device engines (sherpa, 47 models)** | once asrkit is installed, `asrkit engine install sherpa-onnx` (into your Python env; no shell-quoting to fight) |

> Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh` (one line on macOS/Linux, single binary; no Python environment to manage manually for ASRKit).
> After installing, run `asrkit doctor` for a one-command health check (engines / keys / dirs / config; `--net` adds connectivity checks).

## 30 seconds to first transcript

```bash
asrkit transcribe audio.wav -m siliconflow/sensevoice --api-key <KEY>   # cloud example; provider account/API key required, pricing may change
asrkit run sherpa/sensevoice audio.wav                     # on-device: downloads on first run, then transcribes (needs asrkit engine install sherpa-onnx first)
```

## The model string is the only thing that changes

Engine, model, on-device or cloud — all the same call:

```bash
asrkit run sherpa/sensevoice                      audio.wav              # sherpa-onnx (on-device)
asrkit run faster-whisper/large-v3               audio.wav              # faster-whisper engine
asrkit run whispercpp/base                       audio.wav              # whisper.cpp engine
asrkit run transformers/openai/whisper-large-v3  audio.wav              # any HuggingFace model
asrkit run dashscope/qwen3-asr-flash             audio.wav --api-key …  # cloud, bring your own key
```

On-device `sherpa/sensevoice` and cloud `siliconflow/sensevoice` are **the same call** — comparing edge vs cloud is just swapping the string.

> Note: the canonical prefix for sherpa models is `sherpa/`; the old `local/` prefix is kept permanently as a historical alias and still resolves (e.g. `local/sensevoice` is equivalent to `sherpa/sensevoice`) — existing scripts are unaffected.

```python
from asrkit import transcribe
print(transcribe("sherpa/sensevoice", "audio.wav").text)
```

## Why ASRKit

- **A Chinese/multilingual-first edge-and-cloud combination.** 47 sherpa on-device models + 5 cloud vendors out of the box; China cloud providers and Chinese on-device models are first-class citizens, not an afterthought.
- **The interface is the core; everything is pluggable.** The base install ships only the interface + cloud (just `requests`); engines, models, and the server are all add-ons. Use an engine you haven't installed → **a friendly error with the install command**, not an `ImportError`.
- **Learn once, use three ways.** CLI, Python library, and HTTP (OpenAI-compatible serve) — one model addressing scheme across all of them.
- **Compatibility is gated by real clients.** CI uses the official OpenAI Python and Node SDKs to call the model list and `json`/`text`/`verbose_json` transcription paths instead of relying only on handwritten HTTP tests.
- **Transparent by design.** It doesn't touch your audio or change a model's native behavior by default. Wrong format? An honest error — never silent garbage. Unsupported options warn instead of being silently dropped. Conversion and chunking are opt-in.
- **Clear data boundaries.** ASRKit itself does not host or collect audio. Local models stay on-device; cloud models send audio and required credentials to the provider you select, under that provider's privacy terms.

## Batch & scripting

Transcribe many files, a directory, a glob, or stdin at once — structured tables for comparison and scripting:

```bash
asrkit transcribe *.wav        -m sherpa/sensevoice          -f csv          # one row each: file,model,text,latency_ms,rtf…
asrkit transcribe ./recordings -m dashscope/qwen3-asr-flash -f json --batch # recurse a dir → NDJSON
cat a.wav | asrkit transcribe  -  -m sherpa/sensevoice                       # stdin
```

- **NDJSON / csv / tsv** for batches (a single file is still one object); contract in [docs/result-contract.md](docs/result-contract.md).
- **`srt/vtt` subtitles**: the whisper family (faster-whisper / whispercpp / openai/whisper-1) returns timestamps, so subtitles just work; other models get an **honest error** — never a fabricated timeline.
- **Graded exit codes** `0/1/2/3/4` (ok / unexpected / usage error / model not found / transcription failed; any failure in a batch → non-zero), so scripts can tell why.
- **Cloud batches retry** transient failures automatically — cost-safe: billable requests retry only on rate-limit/connection failure, never double-billing (`ASRKIT_HTTP_RETRIES` tunable).

## Streaming (minimal)

Decode sherpa online (streaming) models chunk by chunk, emitting incremental text as audio is fed:

```bash
asrkit stream sherpa/stream-paraformer-zhen meeting.wav             # live partials → stderr, final text → stdout
asrkit stream sherpa/stream-paraformer-zhen meeting.wav > out.txt   # pipe-friendly: capture final text only
asrkit stream sherpa/stream-paraformer-zhen --mic                  # live microphone transcription, Ctrl-C to stop (needs asrkit[mic])
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

## Pluggable: a tiny core, engines/serve added on demand

**The base install is just the interface + cloud (only `requests` — installs in seconds, runs anywhere).** Everything else is opt-in (extras in the table below):

| You want | Install |
|---|---|
| Cloud + CLI + a client for `serve` | `pip install asrkit` |
| Default on-device engine (sherpa, 47 models) | `asrkit engine install sherpa-onnx` |
| Other engines | `asrkit engine install faster-whisper` / `whispercpp` / `transformers` |
| Local server | extra `asrkit[serve]` |
| Live microphone streaming | extra `asrkit[mic]` |
| Everything | extra `asrkit[all]` |

> Prefer `asrkit engine install <name>` for engines (runs the right `pip install` for you, no quoting). When installing an extra with pip directly, zsh needs quotes around `asrkit[serve]` and friends: `pip install 'asrkit[serve]'`.

> **Ownership model:** engines are **shared pip packages** — `asrkit engine install <name>` installs into the right environment for you; uninstall with your own `pip uninstall`. Only models whose adapter declares `cache_owner="asrkit"` have the symmetric ASRKit-store `pull`/`rm` lifecycle. Engine-owned caches (for example HuggingFace or whisper.cpp caches) stay with that engine; `rm` refuses to delete them. Third-party adapters default to `cache_owner="unknown"`, which is also non-removable until the plugin explicitly declares ownership.

## Commands

| Command | What it does |
|---|---|
| `asrkit list` | list all models (✓ = adapter-defined legacy installed/readiness signal); filter with `--lang/--arch`, bare ids with `--ids`; JSON also reports `cached`, `cache_owner`, and `removable` |
| `asrkit search <term>` | search models by id/name |
| `asrkit run <model> <audio>` | ensure adapter readiness, then transcribe; ASRKit-managed sherpa models are pulled when absent |
| `asrkit transcribe <audio…> -m <model>` | transcribe only; multiple files / dir / glob / `-` (stdin), `--batch`; `--format txt/json/srt/vtt/csv/tsv`, `-o`, `--language` |
| `asrkit stream <model> <audio>` | streaming transcription (sherpa online models) |
| `asrkit pull <model> [--url …]` / `rm <model>` | acquire a model through its adapter / remove only an ASRKit-owned cache (`--url` is for ASRKit-managed downloads) |
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
| **sherpa-onnx** (default on-device) | `asrkit[sherpa]` | `sherpa/<model>` or bare `<model>` | 47 on-device models, 16 registered `config_type` values |
| **faster-whisper** | `asrkit[faster-whisper]` | `faster-whisper/<model>` | fast Whisper, native long-audio |
| **whisper.cpp** | `asrkit[whispercpp]` | `whispercpp/<model>` | ultra-light Whisper (no torch/onnx) |
| **transformers** | `asrkit[transformers]` | `transformers/<any-hf-id>` | the whole HuggingFace ASR hub + LLM-arch SOTA |
| **cloud** | built-in | `<vendor>/<model>` | see below, bring your own key |

### Cloud vendors (built in, just add a key)

| Vendor | Addressing | Key |
|---|---|---|
| SiliconFlow | `siliconflow/sensevoice`, `siliconflow/telespeech` | `--api-key` |
| OpenAI | `openai/whisper-1` | `--api-key` |
| Alibaba DashScope | `dashscope/qwen3-asr-flash`, `dashscope/fun-asr-flash`, `dashscope/qwen-omni-plus`, `dashscope/qwen-omni-flash` | `--api-key` |
| Volcengine / Doubao | `doubao/auc-2` (2.0 Seed), `doubao/auc-1` (1.0) | `--api-key`, or `--app-key` + `--access-key` |
| ElevenLabs | `elevenlabs/scribe-v1` | `--api-key` |

Three ways to supply a key (highest priority first): `--api-key` > env var `<VENDOR>_API_KEY` (Volcengine's dual key uses `DOUBAO_APP_KEY`/`DOUBAO_ACCESS_KEY`) > `asrkit config set-key <vendor> <KEY>` once.

## Run it as a server: OpenAI-compatible subset

`asrkit serve` starts a local server. OpenAI SDK apps that use ASRKit's supported fields, agents, and ordinary HTTP clients can change `base_url` and reach registered on-device or cloud models through one endpoint. **The caller needs zero asrkit deps, just HTTP.** See the [compatibility boundary](docs/openai-compatibility.md).

> **Security boundary:** the ordinary CLI still has no built-in authentication, but it defaults to a 200 MiB upload limit, 4 active transcriptions, a 300-second timeout, and rejects browser-origin transcription requests. It remains a trusted-local service: do not expose it directly to the public internet or an untrusted network; put authentication and exact access controls at the gateway first.

```bash
pip install 'asrkit[serve]'
asrkit config set-key dashscope <KEY>     # store a key once (only for cloud)
asrkit serve                              # 127.0.0.1:11435 by default, local only
```
```python
from openai import OpenAI
c = OpenAI(base_url="http://localhost:11435/v1", api_key="unused")
c.audio.transcriptions.create(model="sherpa/sensevoice", file=open("a.wav", "rb"))
```
- SDK contract: CI continuously verifies the model list and `json`/`text`/`verbose_json` with the official OpenAI Python and Node SDKs; `verbose_json` exposes the SDK-facing `language` field. ASRKit promises only the [documented compatibility subset](docs/openai-compatibility.md), not the complete OpenAI Audio or Realtime API.
- Endpoints: `POST /v1/audio/transcriptions` (`response_format`: json/verbose_json/text/srt/vtt), `GET /v1/models`, `GET /health`.
- Streaming: add `stream=true` to the same endpoint → `text/event-stream`, OpenAI-compatible `transcript.text.delta` (partial) / `transcript.text.done` (final) events; temp files are cleaned up automatically on disconnect. Only streaming models are supported — requesting `stream=true` on a non-streaming model errors out.
- Runtime lifecycle: each app owns a capacity-target adapter LRU and a fixed worker pool. Construction is single-flight per canonical model id; adapters are serialized by default unless they opt into concurrent calls, and active requests pin an adapter until batch or SSE work really finishes. Normal `asrkit serve` defaults to 200 MiB uploads, 4 active transcriptions, and a 300-second timeout; direct `build_app()` embedders should set their own limits. Eviction and app shutdown call the adapter's `close()` hook.
- Loopback browser defense: transcription POSTs carrying a non-empty `Origin` header are rejected by default, preventing an arbitrary web page from triggering local inference or configured cloud billing. Put an authenticated gateway with an exact CORS allowlist in front when browser access is intentional.
- Cloud keys can come from a **plaintext config file protected with 0600 permissions**, so no per-request key is needed; use environment variables if you do not want credentials persisted. Transparent: raw bytes uploaded, no decoding.

## Embedded cloud daemon and distribution status

The `python -m asrkit.daemon` module shipped in the 0.5.5 Python package is the cloud-only entry point for the future `asrkit-cloud` Sidecar. Its process registers only the 10 built-in cloud models and supports embedded random ports, ready/shutdown NDJSON, parent-process monitoring, bearer tokens, a private data directory, and resource limits. It exists for host integration and frozen-runtime validation; see [embedding and distribution](docs/embedding-and-distribution.md) for the complete contract.

The repository currently has frozen-runtime evidence for macOS arm64 and Linux x64, plus a manual-only two-provider cloud E2E bound to a protected environment. Missing credentials or a bad transcript fail the run instead of being skipped. However, the complete wheel does **not** install an `asrkit-cloud` top-level command, GitHub Releases do not yet carry a formal self-contained binary, and the npm `asrkit`/platform packages remain the next delivery phase.

## Extend it

**Add any sherpa model** — one command, or an entry in `~/.asrkit/models.json`:

```bash
asrkit add-model sherpa/my-model --url https://…/model.tar.bz2 --arch senseVoice --langs zh,en
```

**Add an engine** — ship a small package that declares an `asrkit.adapters` entry point; `pip install` auto-registers it. No fork, no core changes. Recipe: [docs/engines-and-addressing.md](docs/engines-and-addressing.md#engine-plugin-recipe).

## Design principles & boundaries

ASRKit is deliberately restrained — what it *doesn't* do matters as much as what it does:

- **It never touches your audio.** The core does zero processing and hands bytes to the model/cloud as-is; decoding/resampling/chunking are all opt-in (`--convert`/`--segment`).
- **It doesn't swallow specialist ecosystems.** Speaker diarization and forced alignment stay out of the interface layer — use the `raw_response` escape hatch or compose on top.
- **It doesn't uninstall engines for you.** Engines are shared pip packages: it helps you install into the right env, but your environment is yours.
- **It doesn't fake support.** No timestamps from the model → no subtitles; an option that won't take effect → a warning. Honest errors beat silent wrong output.

## Docs

[Usage](docs/usage.md) · [OpenAI compatibility boundary](docs/openai-compatibility.md) · [Adapter contract](docs/adapter-spec.md) · [Result contract](docs/result-contract.md) · [Engines & addressing](docs/engines-and-addressing.md) · [Model management](docs/model-management.md) · [Product form](docs/product-form.md) · [Embedding & distribution](docs/embedding-and-distribution.md) · [Roadmap](docs/roadmap.md)

---

Apache-2.0. ASRKit does not grant model licenses; verify them on the model or provider's official page before commercial use. ASRKit itself does not host audio; cloud models send audio and required credentials to the provider you select.
